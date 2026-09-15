"""Multiprocess-safe SQLite authority for the V3 human-review workflow."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS human_decisions (
  decision_id TEXT PRIMARY KEY,
  workspace TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  record_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (workspace, request_id)
);
CREATE TABLE IF NOT EXISTS decision_audit (
  audit_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_json TEXT NOT NULL,
  previous_hash TEXT,
  record_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS glossary_outbox (
  event_id TEXT PRIMARY KEY,
  workspace TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  processed_at TEXT,
  last_error TEXT,
  UNIQUE (workspace, decision_id)
);
CREATE TABLE IF NOT EXISTS glossary_candidates (
  workspace TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  candidate_hash TEXT NOT NULL,
  PRIMARY KEY (workspace, candidate_id)
);
CREATE TABLE IF NOT EXISTS sealed_plans (
  plan_id TEXT PRIMARY KEY,
  workspace TEXT NOT NULL,
  job_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  state TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  plan_hash TEXT NOT NULL,
  decision_ids_json TEXT NOT NULL,
  proposal_ids_json TEXT NOT NULL,
  sealed_at TEXT NOT NULL,
  applied_at TEXT,
  apply_id TEXT,
  UNIQUE (workspace, job_id, revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sealed_plan_vigente
  ON sealed_plans(workspace, job_id) WHERE state='sealed';
CREATE INDEX IF NOT EXISTS idx_sealed_plan_por_corrida
  ON sealed_plans(workspace, job_id, revision);
CREATE INDEX IF NOT EXISTS idx_review_active
  ON human_decisions(workspace, proposal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_glossary_pending
  ON glossary_outbox(workspace, processed_at);
"""


class SealConflict(RuntimeError):
    """Las decisiones cambiaron entre leerlas y sellar el plan.

    FALLA CERRADO: no se sella nada. Sellar de todos modos produciría un plan
    que dice ser el snapshot de unas decisiones y es el de otras.
    """


class SQLiteReviewStore:
    """Short SQLite transactions with WAL and database-enforced uniqueness."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(60):
            try:
                with self.connection() as connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.executescript(SCHEMA)
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 59:
                    raise
                time.sleep(0.05)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def decisions(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM human_decisions ORDER BY created_at, decision_id"
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def append_decision_and_outbox(
        self,
        record: dict[str, Any],
        outbox_payload: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically append a human decision and its candidate request."""
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT record_json FROM human_decisions
                   WHERE workspace=? AND request_id=?""",
                (record["workspace"], record["request_id"]),
            ).fetchone()
            if existing:
                return json.loads(existing["record_json"]), False
            connection.execute(
                """INSERT INTO human_decisions
                   (decision_id, workspace, proposal_id, request_id, record_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record["decision_id"],
                    record["workspace"],
                    record["proposal_id"],
                    record["request_id"],
                    canonical(record),
                    record["timestamp"],
                ),
            )
            previous = connection.execute(
                """SELECT record_hash FROM decision_audit
                   WHERE workspace=? ORDER BY audit_seq DESC LIMIT 1""",
                (record["workspace"],),
            ).fetchone()
            audit = {
                "event": "HUMAN_DECISION_RECORDED",
                "decision_id": record["decision_id"],
                "request_id": record["request_id"],
                "proposal_id": record["proposal_id"],
            }
            previous_hash = previous["record_hash"] if previous else None
            record_hash = digest({"previous_hash": previous_hash, **audit})
            connection.execute(
                """INSERT INTO decision_audit
                   (workspace, event_type, event_json, previous_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    record["workspace"],
                    audit["event"],
                    canonical(audit),
                    previous_hash,
                    record_hash,
                ),
            )
            # UN PLAN SELLADO NO SOBREVIVE A UN CAMBIO DE DECISIÓN.
            #
            # Va DENTRO de esta transacción, la misma que graba la decisión.
            # Hacerlo después, en otro commit, dejaría una ventana en la que la
            # decisión ya cambió y el plan todavía se considera aplicable: un
            # Apply en esa ventana escribiría en el grafo algo que el operador
            # acababa de rectificar. El plan no se edita nunca; se INVALIDA.
            self._supersede_sealed(connection, record["workspace"])
            if outbox_payload:
                connection.execute(
                    """INSERT INTO glossary_outbox
                       (event_id, workspace, decision_id, payload_json)
                       VALUES (?, ?, ?, ?)""",
                    (
                        f"glossary-request:{record['decision_id']}",
                        record["workspace"],
                        record["decision_id"],
                        canonical(outbox_payload),
                    ),
                )
        return record, True


    # -----------------------------------------------------------------
    # PLANES SELLADOS. El artefacto que el operador revisó, inmutable.
    # -----------------------------------------------------------------
    #
    # POR QUÉ VIVEN AQUÍ Y NO EN UN FICHERO
    # -------------------------------------
    # Esta base YA es la autoridad efectiva de las decisiones (Corte 2).
    # Guardar el plan aprobado en otro sitio reabriría el problema de las dos
    # verdades: un fichero y una tabla capaces de contradecirse, con la
    # semántica dependiendo de que dos procesos vean bien un directorio — que
    # es exactamente el fallo que el invariante de `proposals/` ya costó.
    # Los ficheros pueden seguir siendo artefactos DERIVADOS (exportación,
    # diagnóstico); no determinan qué se aplica.
    #
    # LOS ESTADOS, Y QUÉ SIGNIFICA CADA UNO
    # -------------------------------------
    #   `sealed`      el plan vigente de esa corrida. Como máximo UNO, y lo
    #                 impone la BASE: `idx_sealed_plan_vigente` es un índice
    #                 único PARCIAL sobre (workspace, job_id) WHERE
    #                 state='sealed'. No es una comprobación en Python que
    #                 alguien pueda olvidarse de llamar.
    #   `applied`     se aplicó. Queda INMUTABLE y ligado a su `apply_id`,
    #                 para procedencia y auditoría.
    #   `superseded`  una decisión cambió después de sellarlo. El plan NO se
    #                 modifica: se invalida y exige una revisión nueva.

    ESTADO_SELLADO = "sealed"
    ESTADO_APLICADO = "applied"
    ESTADO_SUPERSEDIDO = "superseded"

    def _supersede_sealed(self, connection: sqlite3.Connection, workspace: str) -> int:
        """Invalida el plan vigente de CADA corrida del workspace. Nunca lo edita.

        Se llama DENTRO de la transacción que registra la decisión, no después:
        si fuese un segundo commit, entre uno y otro existiría una ventana en
        la que hay un plan `sealed` que ya no corresponde a las decisiones
        confirmadas — y aplicar en esa ventana escribiría en el grafo lo que el
        operador acaba de rectificar.

        Sólo toca `sealed`. Un plan `applied` es historia: ya se escribió en el
        grafo y su inmutabilidad es lo que sostiene la procedencia.
        """
        cursor = connection.execute(
            """UPDATE sealed_plans SET state=?
               WHERE workspace=? AND state=?""",
            (self.ESTADO_SUPERSEDIDO, workspace, self.ESTADO_SELLADO),
        )
        return cursor.rowcount or 0

    def _active_decision_ids(
        self, connection: sqlite3.Connection, workspace: str
    ) -> list[str]:
        """Los `decision_id` ACTIVOS del workspace, con la semántica del visor.

        Misma regla que `_active_decisions` en `v3_review`: la última por
        propuesta gana, una supersedida no cuenta y un `undo` devuelve la
        propuesta a pendiente. Se recalcula aquí, sobre la conexión de la
        transacción, porque leerlo fuera sería leer OTRO instante.
        """
        rows = connection.execute(
            """SELECT record_json FROM human_decisions
               WHERE workspace=? ORDER BY created_at, decision_id""",
            (workspace,),
        ).fetchall()
        ultima: dict[str, dict[str, Any]] = {}
        supersedidas: set[str] = set()
        for row in rows:
            record = json.loads(row["record_json"])
            if record.get("supersedes_decision_id"):
                supersedidas.add(str(record["supersedes_decision_id"]))
            identificador = str((record.get("proposal") or {}).get("proposal_id") or "")
            if identificador:
                ultima[identificador] = record
        activas = {
            str(record.get("decision_id") or "")
            for record in ultima.values()
            if str(record.get("decision_id") or "") not in supersedidas
            and not (record.get("correction") or {}).get("undo")
        }
        activas.discard("")
        return sorted(activas)

    def seal_plan(
        self,
        *,
        workspace: str,
        job_id: str,
        plan_id: str,
        plan_json: str,
        plan_hash: str,
        decision_ids: list,
        proposal_ids: list,
        sealed_at: str,
        expected_decision_ids: list,
    ) -> dict:
        """Sella un plan en la MISMA transacción que comprueba las decisiones.

        `expected_decision_ids` es el conjunto de decisiones activas que el
        llamante leyó para construir el plan. Se vuelve a leer AQUÍ, dentro de
        `BEGIN IMMEDIATE`, y si no coincide NO SE SELLA NADA: entre la lectura
        y el sellado alguien decidió, deshizo o corrigió, y el plan ya no es el
        snapshot de las decisiones confirmadas.

        Es la forma concreta de la propiedad que se pide: **no puede existir un
        plan considerado aplicable que no corresponda a un snapshot confirmado
        de las decisiones.** La transacción es de SQLite; no hay ventana.
        """
        with self.transaction() as connection:
            activas = self._active_decision_ids(connection, workspace)
            if activas != sorted(set(expected_decision_ids)):
                raise SealConflict(
                    "las decisiones cambiaron entre la lectura y el sellado"
                )
            # Un sellado nuevo invalida el anterior de esa corrida ANTES de
            # insertar: el índice único parcial no admite dos vigentes, así que
            # sin esto el segundo sellado fallaría con un error de base en vez
            # de con la semántica correcta (el plan v1 queda SUPERSEDED).
            connection.execute(
                """UPDATE sealed_plans SET state=?
                   WHERE workspace=? AND job_id=? AND state=?""",
                (self.ESTADO_SUPERSEDIDO, workspace, job_id, self.ESTADO_SELLADO),
            )
            fila = connection.execute(
                "SELECT MAX(revision) AS r FROM sealed_plans WHERE workspace=? AND job_id=?",
                (workspace, job_id),
            ).fetchone()
            revision = int(fila["r"] if fila and fila["r"] is not None else 0) + 1
            connection.execute(
                """INSERT INTO sealed_plans
                   (plan_id, workspace, job_id, revision, state, plan_json,
                    plan_hash, decision_ids_json, proposal_ids_json, sealed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan_id, workspace, job_id, revision, self.ESTADO_SELLADO,
                    plan_json, plan_hash, canonical(sorted(set(decision_ids))),
                    canonical(sorted(set(proposal_ids))), sealed_at,
                ),
            )
            self._audit(connection, workspace, {
                "event": "REVIEW_PLAN_SEALED",
                "plan_id": plan_id,
                "job_id": job_id,
                "revision": revision,
                "plan_hash": plan_hash,
            })
        return self.sealed_plan(workspace=workspace, job_id=job_id)

    def sealed_plan(self, *, workspace: str, job_id: str):
        """El plan VIGENTE de una corrida, o `None`. Nunca uno supersedido."""
        with self.connection() as connection:
            row = connection.execute(
                """SELECT * FROM sealed_plans
                   WHERE workspace=? AND job_id=? AND state=?""",
                (workspace, job_id, self.ESTADO_SELLADO),
            ).fetchone()
        return dict(row) if row else None

    def last_plan(self, *, workspace: str, job_id: str):
        """El último plan de la corrida, sea cual sea su estado.

        Sirve para CONTAR LA VERDAD en pantalla: un plan ya aplicado y uno
        supersedido no son «no hay plan», y decirle al operador que no hay nada
        justo después de aplicar sería el mismo falso silencio de siempre.
        """
        with self.connection() as connection:
            row = connection.execute(
                """SELECT * FROM sealed_plans
                   WHERE workspace=? AND job_id=?
                   ORDER BY revision DESC LIMIT 1""",
                (workspace, job_id),
            ).fetchone()
        return dict(row) if row else None

    def plan_by_id(self, plan_id: str):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sealed_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return dict(row) if row else None

    def claim_for_apply(self, *, plan_id: str, now: str) -> dict:
        """Toma el plan para aplicarlo. ATÓMICO: dos clics no aplican dos veces.

        El `UPDATE ... WHERE state='sealed'` es la reserva: quien consigue
        `rowcount == 1` es el único que va a llamar al writer. El segundo clic
        encuentra el plan ya en `applied` y recibe un desenlace EXPLÍCITO — no
        un segundo apply silencioso, y tampoco un error genérico.

        Se marca ANTES de escribir en el grafo a propósito. El orden inverso
        (escribir y luego marcar) deja una ventana en la que un segundo clic
        aplicaría de verdad. Este orden, en el peor caso, deja un plan marcado
        cuyo writer falló — y eso no se queda así: `record_apply_result` lo
        devuelve a `sealed` en cuanto se confirma el desenlace real.
        """
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE sealed_plans SET state=?, applied_at=?
                   WHERE plan_id=? AND state=?""",
                (self.ESTADO_APLICADO, now, plan_id, self.ESTADO_SELLADO),
            )
            tomado = (cursor.rowcount or 0) == 1
            row = connection.execute(
                "SELECT * FROM sealed_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if tomado:
                self._audit(connection, row["workspace"], {
                    "event": "REVIEW_PLAN_APPLY_CLAIMED",
                    "plan_id": plan_id,
                    "job_id": row["job_id"],
                })
        return {"claimed": tomado, "plan": dict(row)}

    def record_apply_result(
        self, *, plan_id: str, apply_id, ok: bool, now: str
    ) -> None:
        """Deja el desenlace REAL del apply sobre el plan tomado.

        Si el writer NO aplicó, el plan vuelve a `sealed`: no se ha escrito
        nada, así que dejarlo marcado como aplicado sería mentir y además
        impediría reintentar lo que nunca llegó a ocurrir.
        """
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sealed_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if ok:
                connection.execute(
                    "UPDATE sealed_plans SET apply_id=?, applied_at=? WHERE plan_id=?",
                    (apply_id, now, plan_id),
                )
            else:
                connection.execute(
                    """UPDATE sealed_plans SET state=?, applied_at=NULL, apply_id=NULL
                       WHERE plan_id=?""",
                    (self.ESTADO_SELLADO, plan_id),
                )
            self._audit(connection, row["workspace"], {
                "event": "REVIEW_PLAN_APPLIED" if ok else "REVIEW_PLAN_APPLY_FAILED",
                "plan_id": plan_id,
                "job_id": row["job_id"],
                "apply_id": apply_id or "",
            })

    def _audit(self, connection: sqlite3.Connection, workspace: str, event: dict) -> None:
        """Una entrada en la MISMA cadena de auditoría encadenada que ya existe.

        No se crea un registro nuevo: `decision_audit` ya es append-only y
        encadenada por hash, y meter los eventos de plan en otra tabla haría
        que la historia de una revisión hubiera que leerla en dos sitios.
        """
        previous = connection.execute(
            """SELECT record_hash FROM decision_audit
               WHERE workspace=? ORDER BY audit_seq DESC LIMIT 1""",
            (workspace,),
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else None
        record_hash = digest({"previous_hash": previous_hash, **event})
        connection.execute(
            """INSERT INTO decision_audit
               (workspace, event_type, event_json, previous_hash, record_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (workspace, event["event"], canonical(event), previous_hash, record_hash),
        )

    def audit_events(self, workspace: str) -> list:
        """La cadena de auditoría del workspace, para poder COMPROBARLA."""
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT event_type, event_json FROM decision_audit
                   WHERE workspace=? ORDER BY audit_seq""",
                (workspace,),
            ).fetchall()
        return [
            {"event_type": row["event_type"], **json.loads(row["event_json"])}
            for row in rows
        ]

    def audit_stale(self, event: dict[str, Any]) -> None:
        with self.transaction() as connection:
            previous = connection.execute(
                """SELECT record_hash FROM decision_audit
                   WHERE workspace=? ORDER BY audit_seq DESC LIMIT 1""",
                (event["workspace"],),
            ).fetchone()
            previous_hash = previous["record_hash"] if previous else None
            record_hash = digest({"previous_hash": previous_hash, **event})
            connection.execute(
                """INSERT INTO decision_audit
                   (workspace, event_type, event_json, previous_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event["workspace"],
                    event["event"],
                    canonical(event),
                    previous_hash,
                    record_hash,
                ),
            )

    def project_outbox(self, workspace: str, now: str) -> int:
        """Idempotently materialise candidates and mark events in one commit."""
        projected = 0
        with self.transaction() as connection:
            rows = connection.execute(
                """SELECT event_id, payload_json FROM glossary_outbox
                   WHERE workspace=? AND processed_at IS NULL ORDER BY event_id""",
                (workspace,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                for candidate in payload.get("candidates") or []:
                    candidate_id = candidate["candidate_id"]
                    existing = connection.execute(
                        """SELECT candidate_json FROM glossary_candidates
                           WHERE workspace=? AND candidate_id=?""",
                        (workspace, candidate_id),
                    ).fetchone()
                    item = json.loads(existing["candidate_json"]) if existing else candidate
                    if existing:
                        item["source_ids"] = sorted(
                            set(item["source_ids"]) | set(candidate["source_ids"])
                        )
                        item["episode_ids"] = sorted(
                            set(item["episode_ids"]) | set(candidate["episode_ids"])
                        )
                        item["evidence"] = sorted(
                            {
                                canonical(value): value
                                for value in item["evidence"] + candidate["evidence"]
                            }.values(),
                            key=canonical,
                        )
                        item["origin"]["human_decision_ids"] = sorted(
                            set(item["origin"]["human_decision_ids"])
                            | set(candidate["origin"]["human_decision_ids"])
                        )
                        item["origin"]["proposal_ids"] = sorted(
                            set(item["origin"]["proposal_ids"])
                            | set(candidate["origin"]["proposal_ids"])
                        )
                    item["occurrence_count"] = len(item["origin"]["human_decision_ids"])
                    item["source_count"] = len(item["source_ids"])
                    item["candidate_hash"] = digest(
                        {key: value for key, value in item.items() if key != "candidate_hash"}
                    )
                    connection.execute(
                        """INSERT INTO glossary_candidates
                           (workspace, candidate_id, candidate_json, candidate_hash)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(workspace, candidate_id) DO UPDATE SET
                             candidate_json=excluded.candidate_json,
                             candidate_hash=excluded.candidate_hash""",
                        (
                            workspace,
                            candidate_id,
                            canonical(item),
                            item["candidate_hash"],
                        ),
                    )
                connection.execute(
                    "UPDATE glossary_outbox SET processed_at=?, last_error=NULL WHERE event_id=?",
                    (now, row["event_id"]),
                )
                projected += 1
        return projected

    def candidates(self, workspace: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT candidate_json FROM glossary_candidates
                   WHERE workspace=? ORDER BY candidate_id""",
                (workspace,),
            ).fetchall()
        return [json.loads(row["candidate_json"]) for row in rows]

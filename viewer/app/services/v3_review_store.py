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
  applied_operations INTEGER,
  apply_notes_json TEXT,
  provenance_json TEXT,
  UNIQUE (workspace, job_id, revision)
);
CREATE TABLE IF NOT EXISTS entity_altas (
  workspace TEXT NOT NULL,
  job_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  entity_type TEXT,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  PRIMARY KEY (workspace, job_id, entity_id)
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


def active_decision_ids(records: list, workspace: str) -> list[str]:
    """`decision_id` ACTIVOS de un workspace. LA derivación, sobre registros.

    POR QUÉ ES UNA FUNCIÓN PURA Y NO UN MÉTODO QUE LEE
    --------------------------------------------------
    B1. El sellado construía el plan con las decisiones leídas en t1 y pasaba
    como esperadas una SEGUNDA lectura en t2, en otra conexión. La guarda
    comparaba t2 contra t3 y NUNCA t1 contra t3, así que un cambio de decisión
    entre t1 y t2 era INVISIBLE: medido por el camino del producto, registrar
    un `REJECT` en esa ventana dejaba el plan `sealed` con la afirmación que el
    operador acababa de RECHAZAR, sin `SEAL_CONFLICT`. Y no hacía falta nada
    exótico: un admin sellando mientras alguien decide en `/panel/review` es el
    uso normal.

    Con la derivación aquí, el servicio la aplica a LA MISMA lista de registros
    con la que construyó el plan, y lo que la transacción compara es t1 contra
    t3. Que sea una sola definición es lo que impide que las dos lecturas usen
    semánticas distintas y produzcan conflictos fantasma o, peor, silencios.

    Semántica, idéntica a `_active_decisions` en `v3_review`: la última por
    propuesta gana, una supersedida no cuenta, y un `undo` devuelve la
    propuesta a pendiente.
    """
    ultima: dict[str, Any] = {}
    supersedidas: set[str] = set()
    for record in records:
        if str(record.get("workspace") or "") != workspace:
            continue
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


class AuditChainBroken(RuntimeError):
    """La cadena de auditoría del workspace no verifica.

    FALLA CERRADO: no se sella. Si el registro encadenado que sostiene la
    procedencia está roto, lo que se escriba encima no es auditable.
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
                    self._migrar(connection)
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 59:
                    raise
                time.sleep(0.05)

    #: Columnas que se ANADEN a una base ya creada. `CREATE TABLE IF NOT
    #: EXISTS` no las pone en una tabla que ya existe: sin esto, un despliegue
    #: con almacen previo arrancaba sin la columna y el primer `INSERT` la
    #: reventaba en produccion, no aqui. Es una lista, no un `try/except`
    #: suelto, para que anadir la siguiente no sea inventarse el patron otra
    #: vez.
    _COLUMNAS_ANADIDAS = (("sealed_plans", "provenance_json", "TEXT"),)

    def _migrar(self, connection: sqlite3.Connection) -> None:
        """Pone al dia una base anterior a este corte. Idempotente.

        Se comprueba lo que la tabla TIENE (`PRAGMA table_info`) en vez de
        intentar el `ALTER` y tragarse el error: un `OperationalError` tapado
        esconderia tambien los que no son "la columna ya existe".
        """
        for tabla, columna, tipo in self._COLUMNAS_ANADIDAS:
            presentes = {
                fila["name"]
                for fila in connection.execute(f"PRAGMA table_info({tabla})")
            }
            if not presentes or columna in presentes:
                continue
            connection.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")

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
    #   `applying`    RESERVADO y EN VUELO: alguien lo tomó y todavía no consta
    #                 qué pasó. NO es «aplicado».
    #   `applied`     se aplicó Y SE CONFIRMÓ. Queda INMUTABLE y ligado a su
    #                 `apply_id`, para procedencia y auditoría.
    #   `superseded`  no vale: una decisión cambió, o el apply no llegó a
    #                 escribir. El plan NO se modifica nunca: se invalida.
    #
    # B2. `applying` NACE DE UN FALSO ÉXITO MEDIDO. Antes, `claim_for_apply`
    # marcaba directamente `applied` con `apply_id` a NULL, y si el proceso
    # moría entre la reserva y la escritura `record_apply_result` no corría
    # jamás: la fila quedaba `applied`, la pantalla decía «ya forma parte del
    # conocimiento», el grafo estaba VACÍO y el camino para reintentarlo estaba
    # cerrado. El marcador de «en vuelo» existía —`applied` con `apply_id`
    # nulo— y NADIE LO MIRABA. Ahora es un estado con nombre, y quien lo lee no
    # puede confundirlo con un éxito.

    ESTADO_SELLADO = "sealed"
    ESTADO_EN_VUELO = "applying"
    ESTADO_APLICADO = "applied"
    #: L2 ESCRITO, pero ALGO de lo que el plan declaraba NO se materializo:
    #: una arista que no esta, una procedencia que no llego. NO es `applied`
    #: --anunciarlo como exito completo seria el falso exito que este carril
    #: cierra-- y NO es `superseded` --el conocimiento SI se escribio y volver
    #: a sellar no lo desharia--. Es un estado con NOMBRE, como `applying`, y
    #: es el unico desde el que la reconciliacion vuelve a intentarlo.
    ESTADO_PARCIAL = "partial"
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
        """Los `decision_id` ACTIVOS del workspace, LEÍDOS EN ESTA CONEXIÓN.

        Lee las filas y delega en `active_decision_ids`, que es LA derivación.
        Leerlas aquí y no fuera importa: dentro de `BEGIN IMMEDIATE` esto es el
        instante contra el que se compara.
        """
        rows = connection.execute(
            """SELECT record_json FROM human_decisions
               ORDER BY created_at, decision_id"""
        ).fetchall()
        return active_decision_ids(
            [json.loads(row["record_json"]) for row in rows], workspace
        )

    # -- ALTAS DE ENTIDAD: la SEGUNDA decision, en la MISMA autoridad --------
    #
    # POR QUE AQUI Y NO EN OTRO SITIO
    # -------------------------------
    # Aprobar el alta de una entidad es una decision humana durable que
    # DETERMINA QUE SE ESCRIBE en el grafo, exactamente como una decision de
    # propuesta. Ponerla en un fichero aparte --que es donde vive hoy la del
    # CLI, `entity_decisions` serializado a `decisiones.json`-- habria creado
    # la segunda verdad que el Corte 2 cerro: un fichero y una tabla capaces
    # de contradecirse sobre que se aplica.
    #
    # Y hay una razon mas fuerte que la simetria: un alta aprobada TIENE QUE
    # invalidar el plan sellado, igual que una decision de propuesta. Eso solo
    # es atomico si las dos viven en la misma base y se tocan en la misma
    # transaccion. Con el fichero por un lado y la tabla por otro existiria la
    # ventana en la que hay un plan `sealed` que ya no corresponde a las altas
    # aprobadas -- y aplicar en esa ventana escribiria (o dejaria de escribir)
    # una entidad contra la decision vigente.

    def approve_entity_alta(
        self,
        *,
        workspace: str,
        job_id: str,
        entity_id: str,
        entity_type: str | None,
        approved_by: str,
        approved_at: str,
    ) -> dict[str, Any]:
        """Aprueba UN alta, por su id. Sin comodines y sin «aprobar todas».

        IDEMPOTENTE POR LA BASE, no por una comprobacion en Python: la clave
        primaria `(workspace, job_id, entity_id)` es la que impide la segunda
        fila. Repetir la aprobacion no duplica la entidad ni reescribe la
        atribucion: el autor y el momento de la PRIMERA aprobacion se
        conservan, porque son los que de verdad ocurrieron.

        INVALIDA EL PLAN VIGENTE, y en la misma transaccion. Un plan sellado
        antes de esta aprobacion no la contiene: seguir ofreciendolo seria
        ofrecer un plan que no corresponde al conjunto de decisiones
        confirmadas. No se edita --los planes nunca se editan--: se supersede.
        Cuando la aprobacion ya existia no se invalida nada, porque nada ha
        cambiado.

        AUDITADA en la cadena encadenada del workspace, como el resto. Un acto
        que decide que nace en el grafo sin rastro auditable no cumple el
        contrato del chasis.
        """
        if not approved_by:
            raise ValueError("una aprobacion sin revisor no es una aprobacion")
        with self.transaction() as connection:
            self.verify_audit_chain(connection, workspace)
            existente = connection.execute(
                """SELECT * FROM entity_altas
                   WHERE workspace=? AND job_id=? AND entity_id=?""",
                (workspace, job_id, entity_id),
            ).fetchone()
            if existente is not None:
                return {"nuevo": False, "planes_invalidados": 0,
                        "alta": dict(existente)}
            connection.execute(
                """INSERT INTO entity_altas
                   (workspace, job_id, entity_id, entity_type, approved_by,
                    approved_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (workspace, job_id, entity_id, entity_type or None,
                 approved_by, approved_at),
            )
            cursor = connection.execute(
                """UPDATE sealed_plans SET state=?
                   WHERE workspace=? AND job_id=? AND state=?""",
                (self.ESTADO_SUPERSEDIDO, workspace, job_id, self.ESTADO_SELLADO),
            )
            invalidados = cursor.rowcount or 0
            self._audit(connection, workspace, {
                "event": "ENTITY_ALTA_APPROVED",
                "job_id": job_id,
                "entity_id": entity_id,
                "entity_type": entity_type or None,
                "approved_by": approved_by,
                "approved_at": approved_at,
                "planes_invalidados": invalidados,
            })
        return {"nuevo": True, "planes_invalidados": invalidados,
                "alta": {"workspace": workspace, "job_id": job_id,
                         "entity_id": entity_id, "entity_type": entity_type,
                         "approved_by": approved_by, "approved_at": approved_at}}

    def entity_altas_aprobadas(self, *, workspace: str, job_id: str) -> list[dict[str, Any]]:
        """Las altas APROBADAS de una corrida. Acotado por workspace Y corrida.

        Las dos claves, no solo la corrida: un `job_id` es opaco y la consulta
        que solo filtrara por el dejaria que una corrida homonima de otro
        workspace aportase altas a este plan.
        """
        with self.connection() as connection:
            filas = connection.execute(
                """SELECT * FROM entity_altas
                   WHERE workspace=? AND job_id=? ORDER BY entity_id""",
                (workspace, job_id),
            ).fetchall()
        return [dict(f) for f in filas]

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
        provenance_json: str | None = None,
        expected_alta_ids: list | None = None,
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
            # La cadena, VERIFICADA antes de añadirle nada.
            self.verify_audit_chain(connection, workspace)
            activas = self._active_decision_ids(connection, workspace)
            if activas != sorted(set(expected_decision_ids)):
                raise SealConflict(
                    "las decisiones cambiaron entre la lectura y el sellado"
                )
            # LA MISMA GUARDA PARA LA SEGUNDA DECISION. Aprobar un alta
            # despues de sellar invalida el plan (`approve_entity_alta`); esto
            # cierra la ventana CONTRARIA -- aprobar un alta mientras se
            # componia el plan--, en la que el plan saldria `sealed` sin la
            # entidad que el operador acaba de aprobar y nadie lo notaria.
            # `None` significa "este llamante no leyo altas", y entonces no se
            # compara nada: no se convierte una ausencia en un cero.
            if expected_alta_ids is not None:
                presentes = sorted({
                    str(fila["entity_id"])
                    for fila in connection.execute(
                        """SELECT entity_id FROM entity_altas
                           WHERE workspace=? AND job_id=?""",
                        (workspace, job_id),
                    )
                })
                if presentes != sorted(set(str(x) for x in expected_alta_ids)):
                    raise SealConflict(
                        "las altas de entidad cambiaron entre la lectura y el sellado"
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
                    plan_hash, decision_ids_json, proposal_ids_json, sealed_at,
                    provenance_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan_id, workspace, job_id, revision, self.ESTADO_SELLADO,
                    plan_json, plan_hash, canonical(sorted(set(decision_ids))),
                    canonical(sorted(set(proposal_ids))), sealed_at,
                    provenance_json,
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

    def claim_for_apply(self, *, plan_id: str, now: str) -> dict:
        """Toma el plan para aplicarlo. ATÓMICO: dos clics no aplican dos veces.

        El `UPDATE ... WHERE state='sealed'` es la reserva: quien consigue
        `rowcount == 1` es el único que va a llamar al writer. El segundo clic
        encuentra el plan ya en `applied` y recibe un desenlace EXPLÍCITO — no
        un segundo apply silencioso, y tampoco un error genérico.

        Se marca ANTES de escribir en el grafo a propósito: el orden inverso
        deja una ventana en la que un segundo clic aplicaría de verdad. Pero se
        marca `applying`, NO `applied`. Si el proceso muere aquí, la fila queda
        en un estado que NADIE puede leer como éxito, y la pantalla lo dice.
        """
        with self.transaction() as connection:
            # Se toma desde `sealed` Y desde `partial`. Lo segundo es la
            # RECONCILIACION: un apply que dejo L2 escrito y la proyeccion o
            # la procedencia sin materializar no se resuelve solo, y el unico
            # camino honesto para terminarlo es reejecutar EL MISMO plan
            # sellado -- que es idempotente por `idempotency_key` (las
            # operaciones ya aplicadas salen NOOP) y cuyo volcado de
            # procedencia comprueba la ausencia antes de crear. Volver a
            # `sealed` no serviria: `sealed` significa "todavia no se toco el
            # grafo", y aqui SI se toco.
            cursor = connection.execute(
                """UPDATE sealed_plans SET state=?, applied_at=?
                   WHERE plan_id=? AND state IN (?, ?)""",
                (self.ESTADO_EN_VUELO, now, plan_id,
                 self.ESTADO_SELLADO, self.ESTADO_PARCIAL),
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
        self, *, plan_id: str, apply_id, ok: bool, now: str,
        applied_operations: int = 0, notes: list | None = None,
        complete: bool = True,
    ) -> None:
        """Deja el desenlace REAL del apply sobre el plan EN VUELO.

        `applied_operations` es lo que el WRITER dijo haber escrito, y `notes`
        los códigos que emitió. Se persisten porque la pantalla tiene que poder
        contar lo que pasó DE VERDAD: derivar el recuento de
        `len(mutation_operations)` no distingue un apply hecho de uno abortado,
        y las notas del núcleo (`APPLY_PROVENANCE_NOT_PERSISTED`, entre otras)
        morían aquí sin llegar a nadie.

        SI EL WRITER NO APLICÓ, EL PLAN SE INVALIDA — no vuelve a `sealed`.
        Devolverlo a `sealed` con un `WHERE plan_id=?` a secas resucitaba un
        plan cuyas decisiones pudieron cambiar durante el apply, sin guarda de
        estado y sin revalidar nada. Preparar de nuevo cuesta un clic y vuelve
        a leer las decisiones; resucitar a ciegas no tiene arreglo.

        Los dos `UPDATE` llevan `AND state='applying'`: sólo se cierra lo que
        esta misma petición reservó.
        """
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sealed_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if ok:
                # `ok` dice que el WRITER escribio. `complete` dice que lo
                # DECLARADO esta materializado y es trazable, y eso lo
                # contesta haber MIRADO el grafo, no el writer. Solo con las
                # dos cosas la fila puede decir `applied`.
                estado = (
                    self.ESTADO_APLICADO if complete else self.ESTADO_PARCIAL
                )
                connection.execute(
                    """UPDATE sealed_plans
                       SET state=?, apply_id=?, applied_at=?,
                           applied_operations=?, apply_notes_json=?
                       WHERE plan_id=? AND state=?""",
                    (estado, apply_id, now, int(applied_operations),
                     canonical(sorted(set(notes or ()))), plan_id,
                     self.ESTADO_EN_VUELO),
                )
            else:
                connection.execute(
                    """UPDATE sealed_plans
                       SET state=?, applied_at=NULL, apply_id=NULL,
                           applied_operations=NULL, apply_notes_json=?
                       WHERE plan_id=? AND state=?""",
                    (self.ESTADO_SUPERSEDIDO, canonical(sorted(set(notes or ()))),
                     plan_id, self.ESTADO_EN_VUELO),
                )
            self._audit(connection, row["workspace"], {
                "event": (
                    ("REVIEW_PLAN_APPLIED" if complete else "REVIEW_PLAN_APPLY_PARTIAL")
                    if ok else "REVIEW_PLAN_APPLY_FAILED"
                ),
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
        """La cadena de auditoría del workspace, ENTERA y en orden.

        Es el ÚNICO lector de `decision_audit`. Reusar esa tabla para los
        eventos de plan fue el argumento para no crear un registro nuevo; si
        nadie la leyera, ese argumento no sostendría nada y la cadena sería de
        sólo escritura.
        """
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT event_type, event_json, previous_hash, record_hash
                   FROM decision_audit WHERE workspace=? ORDER BY audit_seq""",
                (workspace,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "previous_hash": row["previous_hash"],
                "record_hash": row["record_hash"],
                **json.loads(row["event_json"]),
            }
            for row in rows
        ]

    def verify_audit_chain(self, connection: sqlite3.Connection, workspace: str) -> None:
        """RECOMPUTA la cadena encadenada por hash. Levanta si no verifica.

        Se llama DENTRO de la transacción del sellado, y ése es el punto: la
        cadena deja de ser un adorno que se escribe y nadie mira, y pasa a ser
        una precondición del acto que más importa. Si está rota, no se sella:
        lo que se escribiera encima no sería auditable.
        """
        rows = connection.execute(
            """SELECT event_type, event_json, previous_hash, record_hash
               FROM decision_audit WHERE workspace=? ORDER BY audit_seq""",
            (workspace,),
        ).fetchall()
        anterior = None
        for indice, row in enumerate(rows):
            if row["previous_hash"] != anterior:
                raise AuditChainBroken(
                    f"cadena rota en la entrada {indice + 1} del registro"
                )
            cuerpo = json.loads(row["event_json"])
            esperado = digest({"previous_hash": anterior, **cuerpo})
            if row["record_hash"] != esperado:
                raise AuditChainBroken(
                    f"hash no corresponde al contenido en la entrada {indice + 1}"
                )
            anterior = row["record_hash"]

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

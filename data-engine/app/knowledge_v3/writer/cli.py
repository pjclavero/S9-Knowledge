# -*- coding: utf-8 -*-
"""MANDO DE BAJO NIVEL del writer. **No es la ruta de operador.**

QUE ES Y QUE NO ES (leelo antes de usarlo)
------------------------------------------
Esto aplica un `GraphMutationPlan` ya sellado y nada mas. **No produce el
producto de extremo a extremo de V3.** Un plan no contiene la procedencia: cita
`evidence_fragment_ids`, pero los documentos `SourceAsset` / `SourceEpisode` /
`EvidenceFragment` que esos ids nombran viven en la corrida de ingesta. Si aqui
solo se da `plan.json`, el conocimiento se escribe y esas referencias **quedan
colgando**.

Eso se midio: el mismo plan por los dos mandos daba 18 aristas / 1 `V3Source` /
7 `V3Evidence` por la ruta de operador, y 0 / 0 / 0 por esta -- que ademas
reportaba `APPLIED` sin una sola advertencia. Ya no calla: sin paquete de
procedencia el resultado trae `APPLY_PROVENANCE_NOT_PERSISTED` con la lista de
referencias colgantes, y `rc = 2` (no es un exito limpio).

**La ruta de operador es `knowledge_v3.pipeline.ingest_cli`**, que recorre
fuente -> ingesta -> decisiones -> revision -> promocion -> plan sellado ->
apply -> procedencia -> documento de rollback.

NO HAY DOS DEFINICIONES DE APLICAR
----------------------------------
Este mando **no implementa** el apply: llama a `writer.apply.apply_v3`, la
misma y unica funcion que llama la ruta de operador. Lo que las distingue no es
codigo, son datos: con `--procedencia PAQUETE.json` este mando produce
exactamente el mismo grafo que la ruta de operador; sin el, produce menos y lo
declara.

Dry-run por defecto; el APPLY hay que pedirlo escribiendolo.

Lo que esta CLI NO hace, a proposito:

* **No abre ninguna conexion en dry-run.** El modo por defecto no construye
  fabrica ninguna: sin `--apply` no hay URI que resolver ni secreto que leer.
* **No acepta la contrasena en `argv`.** Para el APPLY hay que declarar URI,
  usuario y el CAMINO de un fichero 0600 con el secreto (o `-` para leerlo de la
  entrada estandar). El secreto no se imprime ni aparece en el resultado.
* **No adivina el workspace.** Hay que declararlo dos veces —`--workspace` y
  `S9K_WRITER_WORKSPACE`— y coincidir.
* **No adivina el snapshot vigente.** `--snapshot` es obligatorio: es el testigo
  externo (R2) y nadie mas que el operador puede afirmarlo.
* **No confirma el hash por ti.** `--expect-plan-hash` lo teclea el operador.

Uso tipico, en dos pasos que no se pueden saltar:

    python -m knowledge_v3.writer.cli plan.json \\
        --workspace leyenda --snapshot snapshot:neo4j:2026-07-27T10:29:00Z

    S9K_ALLOW_REAL_INGEST=1 S9K_WRITER_WORKSPACE=leyenda \\
    python -m knowledge_v3.writer.cli plan.json \\
        --workspace leyenda --snapshot snapshot:neo4j:2026-07-27T10:29:00Z \\
        --operator pjc --expect-plan-hash af2ee1... --apply \\
        --neo4j-uri "$S9K_NEO4J_URI" --neo4j-user neo4j \\
        --neo4j-password-file /etc/s9k/neo4j.pass

El paquete de procedencia lo emite la ruta de operador en su `--out-dir`
(`procedencia.json`). Pasarselo aqui con `--procedencia` es lo que hace que
este mando escriba lo mismo que aquella.

El documento de rollback que devuelve el APPLY se guarda con `--rollback-out`:
es lo que hay que conservar para poder deshacer, y esta escrito con identidad
durable `(workspace, entity_id, predicado, objeto)`, no con `elementId`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ..driver_neo4j import (
    ENV_DATABASE,
    ENV_PASSWORD_FILE,
    ENV_URI,
    ENV_USER,
    DriverConfigError,
    build_driver_factory,
    resolve_config,
)
from . import codes
from .apply import (
    CODE_PROVENANCE_FAILED,
    CODE_PROVENANCE_NOT_PERSISTED,
    ProvenanceBundle,
    apply_v3,
    logical_plan_identity,
)
from .audit import JsonlAuditSink
from .gate import DEFAULT_MAX_OPERATIONS, OperatorRequest
from .idempotency import JsonlAppliedKeys
from .writer import GraphWriter


def driver_factory_from_args(args: argparse.Namespace, env: Optional[dict[str, str]] = None):
    """Construye la FABRICA de driver a partir de lo que declaro el operador.

    No conecta: devuelve un invocable que el `GraphWriter` llamara solo si el
    gate autoriza el APPLY. En dry-run no se llama a esta funcion siquiera.
    """
    config = resolve_config(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password_file=args.neo4j_password_file,
        database=args.neo4j_database,
        env=env,
    )
    return build_driver_factory(config)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="knowledge_v3.writer",
        description=(
            "MANDO DE BAJO NIVEL. Aplica un GraphMutationPlan sellado y nada "
            "mas. NO es la ruta de operador: sin --procedencia el conocimiento "
            "se escribe con las referencias de evidencia COLGANDO. La ruta de "
            "operador es knowledge_v3.pipeline.ingest_cli. Dry-run por defecto."
        ),
    )
    p.add_argument("plan", help="ruta del GraphMutationPlan en JSON")
    p.add_argument("--workspace", required=True, help="workspace (declaracion 1 de 2)")
    p.add_argument("--snapshot", required=True, help="snapshot vigente declarado (R2)")
    p.add_argument("--operator", default=None, help="identificador del operador")
    p.add_argument("--expect-plan-hash", default=None, help="plan_hash que autorizas")
    p.add_argument("--max-operations", type=int, default=DEFAULT_MAX_OPERATIONS)
    p.add_argument("--audit-log", default="writer_audit.jsonl")
    p.add_argument("--applied-keys", default="writer_applied_keys.jsonl")
    p.add_argument(
        "--procedencia", default=None, metavar="PAQUETE_JSON",
        help="paquete de procedencia (source_asset/episodes/fragments) que la "
             "ruta de operador emite en su --out-dir como procedencia.json. "
             "SIN el, este mando escribe conocimiento con las referencias de "
             "evidencia colgando, lo declara con "
             "APPLY_PROVENANCE_NOT_PERSISTED y sale con rc=2",
    )
    p.add_argument("--rollback-out", default=None,
                   help="fichero donde guardar el documento de rollback del APPLY. "
                        "NUNCA se pisa una poliza existente con un documento sin "
                        "instrucciones: repetir un apply no destruye el rollback.")
    p.add_argument("--forget-applied-keys", default=None, metavar="ROLLBACK_JSON",
                   help="MANDO DE OPERADOR: retira del almacen de claves aplicadas "
                        "las de ESE documento de rollback, para que un plan ya "
                        "revertido se pueda volver a aplicar. No toca el grafo.")
    p.add_argument("--neo4j-uri", default=None, help=f"URI del servidor ({ENV_URI})")
    p.add_argument("--neo4j-user", default=None, help=f"usuario ({ENV_USER})")
    p.add_argument(
        "--neo4j-password-file",
        default=None,
        help=f"CAMINO de un fichero 0600 con la contrasena, o '-' para stdin "
             f"({ENV_PASSWORD_FILE}). La contrasena NUNCA se pasa por argv.",
    )
    p.add_argument("--neo4j-database", default=None, help=f"base de datos ({ENV_DATABASE})")
    p.add_argument(
        "--apply",
        action="store_true",
        help="ESCRITURA REAL. Sin esto, y sin S9K_ALLOW_REAL_INGEST=1, solo simula.",
    )
    return p


def forget_keys_from_rollback(path: str, store: Any) -> dict[str, Any]:
    """Retira del almacen las claves de un documento de rollback ya ejecutado.

    Por que hace falta un mando explicito: nadie limpiaba el almacen. Tras
    revertir un plan, sus claves seguian marcadas como aplicadas, asi que el
    dry-run siguiente clasificaba como no-op unas operaciones cuyo conocimiento
    ya no estaba en el grafo.

    Es del OPERADOR y no automatico a proposito: olvidar una clave habilita una
    reescritura, y eso no se decide solo. Solo mira el documento; no toca Neo4j.
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    claves: list[str] = []
    for instruccion in doc.get("instructions") or []:
        clave = (instruccion.get("detail") or {}).get("idempotency_key")
        if clave and clave not in claves:
            claves.append(clave)
    olvidadas = [c for c in claves if store.forget(c)]
    return {
        "code": codes.CLI_APPLIED_KEYS_FORGOTTEN,
        "rollback_document": path,
        "keys_in_document": claves,
        "forgotten": olvidadas,
        "already_absent": [c for c in claves if c not in olvidadas],
    }


def save_rollback(path: str, doc: Any) -> dict[str, Any]:
    """Guarda la poliza SIN poder destruir la que ya hubiera.

    Un apply repetido es un no-op idempotente y su documento no trae ninguna
    instruccion. Escribirlo encima del anterior borraria la unica forma de
    deshacer lo que se aplico la primera vez -- una orden inocua destruyendo la
    poliza de recuperacion. Asi que un documento SIN instrucciones nunca pisa
    un fichero existente, y se dice con codigo.
    """
    destino = Path(path)
    payload = doc.to_dict()
    if destino.exists() and not payload.get("instructions"):
        return {
            "code": codes.CLI_ROLLBACK_OUT_PRESERVED,
            "path": str(destino),
            "reason": "el documento nuevo no trae instrucciones y ya habia una "
                      "poliza guardada: no se pisa",
        }
    destino.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {"code": None, "path": str(destino), "instructions": len(payload.get("instructions") or [])}


def main(
    argv: Optional[list[str]] = None,
    *,
    driver_factory: Optional[Callable[[], Any]] = None,
    env: Optional[dict[str, str]] = None,
) -> int:
    args = build_parser().parse_args(argv)
    plan_doc = json.loads(Path(args.plan).read_text(encoding="utf-8"))

    # La FABRICA, no el driver: `GraphWriter` la invoca solo si el gate deja
    # pasar el APPLY. Construir la conexion aqui gastaria credenciales y una
    # sesion en un intento que aun puede bloquearse.
    #
    # En dry-run no se resuelve ni la configuracion: el modo seguro sigue sin
    # necesitar URI, usuario ni secreto.
    factory = driver_factory
    if args.apply and factory is None:
        try:
            factory = driver_factory_from_args(args, env)
        except DriverConfigError as exc:
            # Falla CERRADO y sin secreto en el mensaje: no hay APPLY sin
            # conexion declarada, y no se degrada a dry-run silencioso.
            # Codigo estable, no redaccion: quien automatice esto distingue
            # "conexion sin declarar" de cualquier otro fallo sin leer el texto.
            print(json.dumps(
                {"ok": False, "code": codes.CLI_DRIVER_CONFIG_MISSING,
                 "error": str(exc)},
                ensure_ascii=False, indent=2, sort_keys=True))
            return 1
    applied_keys = JsonlAppliedKeys(args.applied_keys)

    # Mando de operador: no aplica nada, solo retira claves. Va antes de
    # construir el writer porque no necesita ni plan ni conexion.
    if args.forget_applied_keys:
        informe = forget_keys_from_rollback(args.forget_applied_keys, applied_keys)
        print(json.dumps(informe, ensure_ascii=False, indent=2, sort_keys=True))
        if not args.apply:
            return 0

    writer = GraphWriter(
        workspace=args.workspace,
        driver_factory=factory if args.apply else None,
        audit=JsonlAuditSink(args.audit_log),
        applied_keys=applied_keys,
        max_operations=args.max_operations,
    )
    paquete = None
    if args.procedencia:
        try:
            paquete = ProvenanceBundle.from_dict(
                json.loads(Path(args.procedencia).read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # Falla CERRADO: un paquete ilegible NO se degrada a "sin paquete".
            # Degradarlo escribiria conocimiento sin procedencia creyendo el
            # operador que la lleva, que es exactamente el defecto que se cierra.
            print(json.dumps(
                {"ok": False, "code": "CLI_PROVENANCE_BUNDLE_UNREADABLE",
                 "error": str(exc)},
                ensure_ascii=False, indent=2, sort_keys=True))
            return 1

    # UNA SOLA DEFINICION DE APLICAR. Este mando no reimplementa el apply: lo
    # pide a la misma funcion que la ruta de operador.
    outcome = apply_v3(
        plan_doc,
        OperatorRequest(
            apply=bool(args.apply),
            operator_id=args.operator,
            workspace=args.workspace,
            expected_plan_hash=args.expect_plan_hash,
            max_operations=args.max_operations,
            current_snapshot_id=args.snapshot,
            env=env,
        ),
        writer=writer,
        provenance=paquete,
    )
    result = outcome.write_result
    salida = result.to_dict()
    salida["apply"] = {
        "apply_id": outcome.apply_id,
        "plan_id_no_firmado": logical_plan_identity(plan_doc),
        "provenance": (
            outcome.provenance_result.to_dict()
            if outcome.provenance_result else None
        ),
        "dangling_fragment_ids": list(outcome.dangling_fragment_ids),
        "notes": [dict(n) for n in outcome.notes],
    }
    print(json.dumps(salida, ensure_ascii=False, indent=2, sort_keys=True))
    guardado = None
    if args.rollback_out and result.rollback is not None:
        guardado = save_rollback(args.rollback_out, result.rollback)
        print(json.dumps({"rollback_out": guardado}, ensure_ascii=False,
                         indent=2, sort_keys=True))
    if not result.ok:
        # INCONSISTENT entra por aqui: la transaccion no fallo, pero el grafo no
        # sostiene lo que un APPLIED afirmaria. rc=1, no rc=0.
        return 1
    if guardado is not None and guardado.get("code"):
        return 2  # la poliza vieja se conservo: hay algo que leer, no es limpio
    # Salio bien pero con codigos: p.ej. AUDIT_APPEND_FAILED, escritura aplicada
    # sin linea de desenlace. Un runner desatendido no puede leer eso como exito
    # limpio, asi que se distingue del 0.
    #
    # LA PROCEDENCIA AUSENTE CUENTA. Un APPLY que escribe conocimiento cuyas
    # referencias de evidencia quedan colgando NO es un exito limpio, por mucho
    # que la transaccion del plan haya ido bien: es justo el desenlace que este
    # mando declaraba antes como `APPLIED` sin decir nada.
    sin_procedencia = {CODE_PROVENANCE_NOT_PERSISTED, CODE_PROVENANCE_FAILED}
    if sin_procedencia.intersection(outcome.codes):
        return 2
    return 2 if result.codes else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

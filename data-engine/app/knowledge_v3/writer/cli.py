# -*- coding: utf-8 -*-
"""CLI del writer. Dry-run por defecto; el APPLY hay que pedirlo escribiendolo.

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
        description="Aplica un GraphMutationPlan sellado. Dry-run por defecto.",
    )
    p.add_argument("plan", help="ruta del GraphMutationPlan en JSON")
    p.add_argument("--workspace", required=True, help="workspace (declaracion 1 de 2)")
    p.add_argument("--snapshot", required=True, help="snapshot vigente declarado (R2)")
    p.add_argument("--operator", default=None, help="identificador del operador")
    p.add_argument("--expect-plan-hash", default=None, help="plan_hash que autorizas")
    p.add_argument("--max-operations", type=int, default=DEFAULT_MAX_OPERATIONS)
    p.add_argument("--audit-log", default="writer_audit.jsonl")
    p.add_argument("--applied-keys", default="writer_applied_keys.jsonl")
    p.add_argument("--rollback-out", default=None,
                   help="fichero donde guardar el documento de rollback del APPLY")
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
    writer = GraphWriter(
        workspace=args.workspace,
        driver_factory=factory if args.apply else None,
        audit=JsonlAuditSink(args.audit_log),
        applied_keys=JsonlAppliedKeys(args.applied_keys),
        max_operations=args.max_operations,
    )
    result = writer.write(
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
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if args.rollback_out and result.rollback is not None:
        Path(args.rollback_out).write_text(
            json.dumps(result.rollback.to_dict(), ensure_ascii=False, indent=2,
                       sort_keys=True),
            encoding="utf-8",
        )
    if not result.ok:
        return 1
    # Salio bien pero con codigos: p.ej. AUDIT_APPEND_FAILED, escritura aplicada
    # sin linea de desenlace. Un runner desatendido no puede leer eso como exito
    # limpio, asi que se distingue del 0.
    return 2 if result.codes else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

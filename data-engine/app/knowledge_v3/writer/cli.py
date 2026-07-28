# -*- coding: utf-8 -*-
"""CLI del writer. Dry-run por defecto; el APPLY hay que pedirlo escribiendolo.

Lo que esta CLI NO hace, a proposito:

* **No abre ninguna conexion.** No hay URI, ni usuario, ni contrasena, ni
  fichero de configuracion con credenciales. El driver llega por
  `driver_factory`, y la de por defecto lanza `NotImplementedError` con el
  motivo. Conectar de verdad es trabajo del despliegue, no de este bloque.
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
        --operator pjc --expect-plan-hash af2ee1... --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from .audit import JsonlAuditSink
from .gate import DEFAULT_MAX_OPERATIONS, OperatorRequest
from .idempotency import JsonlAppliedKeys
from .writer import GraphWriter


def no_driver() -> Any:
    """Fabrica por defecto: no hay conexion real en este bloque."""
    raise NotImplementedError(
        "este writer no abre conexiones: inyecta un driver Neo4j (driver_factory). "
        "La conexion real y su unidad systemd son trabajo del despliegue."
    )


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
    p.add_argument(
        "--apply",
        action="store_true",
        help="ESCRITURA REAL. Sin esto, y sin S9K_ALLOW_REAL_INGEST=1, solo simula.",
    )
    return p


def main(
    argv: Optional[list[str]] = None,
    *,
    driver_factory: Callable[[], Any] = no_driver,
    env: Optional[dict[str, str]] = None,
) -> int:
    args = build_parser().parse_args(argv)
    plan_doc = json.loads(Path(args.plan).read_text(encoding="utf-8"))

    # La FABRICA, no el driver: `GraphWriter` la invoca solo si el gate deja
    # pasar el APPLY. Construir la conexion aqui gastaria credenciales y una
    # sesion en un intento que aun puede bloquearse.
    writer = GraphWriter(
        workspace=args.workspace,
        driver_factory=driver_factory if args.apply else None,
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
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

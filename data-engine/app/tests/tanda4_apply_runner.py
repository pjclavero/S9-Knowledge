# -*- coding: utf-8 -*-
"""Aplica un plan en un PROCESO NUEVO. Instrumento, no suite.

POR QUE UN PROCESO APARTE
-------------------------
La idempotencia del segundo apply solo vale si la decide el GRAFO. Repetir el
apply dentro del mismo proceso deja abierta la duda de si quien dijo "no-op"
fue el grafo o alguna memoria viva del propio writer (`AppliedKeyStore` y
demas). Un proceso nuevo no comparte ninguna de esas memorias: si aqui sale
`noop`, lo decidio lo que hay escrito en Neo4j.

No lo recoge pytest (`python_files = test_*.py` en `pytest.ini`): se invoca con
`python -m tests.tanda4_apply_runner <plan.json>` desde `data-engine/app`, con
la conexion en el entorno, y escribe UN objeto JSON por stdout.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    plan_path = Path(argv[1])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    import neo4j

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
        apply_request,
        writer as make_writer,
    )

    uri = os.environ["S9K_T4_URI"]
    clave = Path(os.environ["S9K_T4_PASSWORD_FILE"]).read_text().strip()
    driver = neo4j.GraphDatabase.driver(
        uri, auth=(os.environ.get("S9K_T4_USER", "neo4j"), clave)
    )
    try:
        salida = make_writer(driver).write(plan, apply_request(plan))
        print(
            json.dumps(
                {
                    "outcome": salida.outcome,
                    "applied_operations": salida.applied_operations,
                    "noop_operations": salida.noop_operations,
                    "codes": list(salida.codes or []),
                    "pid": os.getpid(),
                },
                ensure_ascii=False,
            )
        )
    finally:
        driver.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))

# -*- coding: utf-8 -*-
"""CARRIL B -- calibracion: el hueco EXISTE, medido contra un Neo4j real.

No es una puerta ni un test. Es el control POSITIVO del carril: reproduce, con
la fuente de ejemplo del carril A y contra un Neo4j real y vacio, el fallo que
el supervisor encontro. Si este guion dejara de ponerse rojo, el arreglo del
carril B no estaria demostrando nada.

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/carril-b/calibracion_hueco.py

El contenedor lo levanta y lo destruye `neo4j_efimero`, el MISMO mecanismo de
arranque que la fixture de `test_knowledge_v3_writer_neo4j_real`. No hay un
segundo camino.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "data-engine" / "app"))
sys.path.insert(0, str(RAIZ / "data-engine" / "app" / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero  # noqa: E402

from knowledge_v3.pipeline.ingest_cli import run_ingest  # noqa: E402
from knowledge_v3.writer import GraphWriter, InMemoryAppliedKeys  # noqa: E402
from knowledge_v3.writer.gate import OperatorRequest  # noqa: E402

EJEMPLOS = RAIZ / "examples" / "ingesta-v3"


def main() -> int:
    informe = run_ingest(
        EJEMPLOS / "nota-cofradia-de-ambar.md",
        profile_path=EJEMPLOS / "perfil-operador.json",
        catalog_path=EJEMPLOS / "catalogo-workspace.json",
        now="2026-09-05T10:00:00Z",
        ingested_at="2026-09-05T10:00:00Z",
    )
    plan = informe["plan"]
    tipos = [op["operation_type"] for op in plan["mutation_operations"]]
    print("== plan del ejemplo (carril A, dry-run)")
    print("   operaciones:", json.dumps(tipos))
    print("   CREATE_ENTITY en el plan:", tipos.count("CREATE_ENTITY"))
    print("   altas que el resolutor PIDE:",
          json.dumps([c["assigned_entity_id"]
                      for c in informe["candidates"]["create_entity"]]))
    print("   objetivos que el plan PRESUPONE existentes:",
          json.dumps(sorted({
              op.get("target_entity_id") for op in plan["mutation_operations"]
              if op.get("target_entity_id")
          } | {
              (op.get("payload") or {}).get("object_entity_id")
              for op in plan["mutation_operations"]
              if (op.get("payload") or {}).get("object_entity_id")
          })))

    with neo4j_efimero("s9k-carril-b-calibracion") as driver:
        writer = GraphWriter(
            workspace=plan["workspace"],
            driver=driver,
            applied_keys=InMemoryAppliedKeys(),
        )
        resultado = writer.write(
            plan,
            OperatorRequest(
                apply=True,
                operator_id="calibracion",
                workspace=plan["workspace"],
                expected_plan_hash=plan["plan_hash"]["value"],
                current_snapshot_id=plan["snapshot_id"],
                env={
                    "S9K_ALLOW_REAL_INGEST": "1",
                    "S9K_WRITER_WORKSPACE": plan["workspace"],
                },
            ),
        )
        print()
        print("== APPLY contra Neo4j real y VACIO")
        print("   outcome:", resultado.outcome)
        print("   codes:  ", json.dumps(resultado.codes))
        for r in resultado.rejections:
            print("   ->", r.code, "|", r.message)
        with driver.session() as s:
            filas = list(s.run(
                "MATCH (n) WHERE n:V3Entity OR n:V3Assertion RETURN count(n) AS c"))
            print("   nodos de conocimiento escritos:", filas[0]["c"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Los dos ataques de ambito del supervisor, medidos contra Neo4j real.

Reutiliza la base efimera y los ayudantes de la suite real del writer (una
sola forma de levantar Neo4j en el proyecto). Imprime el CENSO antes y
despues y la CONSULTA generada, para que el que lea no tenga que creerse un
resumen.

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/tanda3-r2/demostracion_ambito_rollback.py

No toca produccion: levanta y destruye su propio contenedor.
"""
from __future__ import annotations

import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "data-engine" / "app"))
sys.path.insert(0, str(RAIZ / "data-engine" / "app" / "tests"))

os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
    HASH_A,
    HASH_B,
    WORKSPACE,
    GraphProbe,
    apply_request,
    create_assertion,
    link_existing,
    make_plan,
    neo4j_efimero,
    writer,
    _censo_relaciones,
    _gemela_de_relacion,
    _instruccion,
)
from knowledge_v3.writer.rollback import rollback_query  # noqa: E402
from knowledge_v3.writer.schema import (  # noqa: E402
    V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT,
    V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER,
)

OK = True


def comprobar(etiqueta: str, condicion: bool) -> None:
    global OK
    OK = OK and bool(condicion)
    print(f"  [{'OK ' if condicion else 'FALLO'}] {etiqueta}")


def ataque_b(graph: GraphProbe) -> None:
    print("\n== ATAQUE (b): arista gemela en otra partida ==")
    graph.clean()
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    plan = make_plan([link_existing("op:0001", "entity:origen", "entity:destino")])
    result = writer(graph.driver).write(plan, apply_request(plan))
    print("  outcome del apply:", result.outcome)

    instruccion = _instruccion(result.rollback.to_dict(), "DELETE_RELATIONSHIP")
    print("  partida_id de la instruccion:", instruccion.detail["partida_id"])
    _gemela_de_relacion(
        graph, partida_id="partida:otra", clave=instruccion.detail["idempotency_key"]
    )
    antes = _censo_relaciones(graph)
    print("  censo ANTES:", antes)

    query = rollback_query(instruccion)
    print("  cypher:", query.cypher)
    print("  params:", query.params)
    borradas = graph.run(query.cypher, query.params)[0]["borradas"]
    despues = _censo_relaciones(graph)
    print("  borradas:", borradas)
    print("  censo DESPUES:", despues)
    comprobar("censo previo no vacio (2 aristas)", len(antes) == 2)
    comprobar("borra exactamente una", borradas == 1)
    comprobar(
        "sobrevive la de partida:otra",
        [f["partida"] for f in despues] == ["partida:otra"],
    )


def ataque_a(graph: GraphProbe) -> None:
    print("\n== ATAQUE (a): nodo gemelo en otra partida ==")
    graph.clean()
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    plan = make_plan(
        [create_assertion("op:0001", "assertion:gemela", "entity:origen", "entity:destino")]
    )
    result = writer(graph.driver).write(plan, apply_request(plan))
    print("  outcome del apply:", result.outcome)
    instruccion = _instruccion(result.rollback.to_dict(), "DELETE_NODE")
    print("  label:", instruccion.detail["label"],
          "| partida_id:", instruccion.detail["partida_id"])

    # La restriccion (workspace, assertion_id) no incluye el ambito: hoy
    # impediria el gemelo aqui, y la base real no tiene ni una restriccion.
    graph.run(f"DROP CONSTRAINT {V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT} IF EXISTS")
    graph.run(
        "CREATE (:V3Assertion $props)",
        {"props": {"assertion_id": "assertion:gemela", "workspace": WORKSPACE,
                   "idempotency_key": instruccion.detail["idempotency_key"],
                   "partida_id": "partida:otra", "status": "ASSERTED"}},
    )
    antes = graph.run(
        "MATCH (n:V3Assertion) RETURN n.assertion_id AS id, n.partida_id AS partida "
        "ORDER BY partida"
    )
    print("  censo ANTES:", antes)
    query = rollback_query(instruccion)
    print("  cypher:", query.cypher)
    print("  params:", query.params)
    borrados = graph.run(query.cypher, query.params)[0]["borrados"]
    despues = graph.run(
        "MATCH (n:V3Assertion) RETURN n.assertion_id AS id, n.partida_id AS partida"
    )
    print("  borrados:", borrados)
    print("  censo DESPUES:", despues)
    comprobar("censo previo no vacio (2 nodos)", len(antes) == 2)
    comprobar("borra exactamente uno", borrados == 1)
    comprobar(
        "sobrevive el de partida:otra",
        [f["partida"] for f in despues] == ["partida:otra"],
    )
    graph.run("MATCH (n:V3Assertion) DETACH DELETE n")
    graph.run(V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER)


def main() -> int:
    with neo4j_efimero("s9k-v3-r2-demo") as driver:
        graph = GraphProbe(driver)
        ataque_b(graph)
        ataque_a(graph)
        graph.clean()
    print("\nRESULTADO:", "TODO EN VERDE" if OK else "HAY FALLOS")
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())

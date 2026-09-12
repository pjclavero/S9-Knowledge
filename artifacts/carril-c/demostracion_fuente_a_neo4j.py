# -*- coding: utf-8 -*-
"""CARRIL C -- evidencia: una fuente real entra por V3 y TERMINA VISIBLE en Neo4j.

No es una puerta ni un test: es el guion que genera la evidencia pegada en el
informe. Ejecuta la cadena completa desde bytes (`KnowledgePipeline`), aplica el
plan aprobado contra un Neo4j efimero y DESPUES consulta el grafo con Cypher,
imprimiendo consulta y resultado.

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/carril-c/demostracion_fuente_a_neo4j.py

El contenedor lo levanta y lo destruye el propio guion, reutilizando el mismo
mecanismo (docker run --rm, puerto libre, password aleatoria) que la fixture de
`test_knowledge_v3_writer_neo4j_real`; no hay un segundo camino de arranque.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "data-engine" / "app"))
sys.path.insert(0, str(RAIZ / "data-engine" / "app" / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

import neo4j  # noqa: E402

import test_knowledge_v3_writer_neo4j_real as W  # noqa: E402
import test_knowledge_v3_e2e_neo4j_real as E  # noqa: E402
from knowledge_v3.writer import InMemoryAppliedKeys, bootstrap_writer_schema  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: E402


def arrancar():
    """Mismo mecanismo que la fixture `neo4j_driver`, sin pytest."""
    image = os.environ.get("S9K_WRITER_NEO4J_IMAGE", "neo4j:5.26-community")
    name = "s9k-carril-c-" + uuid.uuid4().hex[:12]
    port = W._free_port()
    password = "carril-c-" + uuid.uuid4().hex[:12]
    W._run([
        "docker", "run", "--rm", "--detach", "--name", name,
        "--publish", f"127.0.0.1:{port}:7687",
        "--env", f"NEO4J_AUTH=neo4j/{password}",
        "--env", "NEO4J_server_memory_heap_initial__size=128m",
        "--env", "NEO4J_server_memory_heap_max__size=256m",
        image,
    ])
    uri = f"bolt://127.0.0.1:{port}"
    driver = neo4j.GraphDatabase.driver(uri, auth=("neo4j", password))
    limite = time.monotonic() + 180
    while True:
        try:
            driver.verify_connectivity()
            break
        except Exception:
            if time.monotonic() >= limite:
                raise
            time.sleep(1)
    bootstrap_writer_schema(driver)
    return driver, name, uri


def consulta(probe, titulo, cypher, params=None):
    filas = probe.run(cypher, params or {})
    print("\n--- %s" % titulo)
    print("    cypher> %s" % " ".join(cypher.split()))
    for fila in filas:
        print("    " + json.dumps(fila, sort_keys=True, default=str, ensure_ascii=False))
    if not filas:
        print("    (0 filas)")
    return filas


def main() -> int:
    driver, name, uri = arrancar()
    probe = W.GraphProbe(driver=driver)
    try:
        print("== Neo4j efimero en %s (contenedor %s)" % (uri, name))

        # ---------------------------------------------------------------
        # 1. FUENTE REAL -> plan aprobado, recorriendo la cadena V3 entera.
        # ---------------------------------------------------------------
        plan_doc, run, _p = E.pipeline_plan("carril-c-fuente", E.T_HECHO)
        print("\n== 1. Fuente -> plan por la cadena V3 completa (desde bytes)")
        print("   texto fuente : %r" % (E.T_HECHO,))
        print("   workspace    : %s" % plan_doc["workspace"])
        print("   plan_id      : %s" % plan_doc["plan_id"])
        print("   aprobado     : %s" % plan_doc["local_approval"]["approved"])
        print("   operaciones  : %s" % [o["operation_type"] for o in plan_doc["mutation_operations"]])

        proj = next(o for o in plan_doc["mutation_operations"]
                    if o["operation_type"] == "PROJECT_RELATION")
        pl = proj["payload"]
        probe.seed_entity(pl["subject_entity_id"], workspace=plan_doc["workspace"],
                          version=proj["expected_version"],
                          state_hash=proj["expected_hash"]["value"])
        probe.seed_entity(pl["object_entity_id"], workspace=plan_doc["workspace"],
                          version=1, state_hash=W.HASH_B["value"])

        res = E.writer_for(plan_doc, driver).write(plan_doc, E.request_for(plan_doc))
        print("   resultado    : %s %s" % (res.outcome, res.codes))
        assert res.outcome == OUTCOME_APPLIED, res.codes

        consulta(probe, "2. El grafo DESPUES: nodos escritos por el plan de la fuente",
                 "MATCH (n) WHERE n.written_by_plan_hash IS NOT NULL "
                 "RETURN labels(n) AS labels, n.entity_id AS entity_id, "
                 "n.assertion_id AS assertion_id, n.workspace AS workspace, "
                 "n.source_asset_id AS source_asset_id, "
                 "n.evidence_fragment_ids AS evidencia ORDER BY labels")
        consulta(probe, "3. Relaciones consultables",
                 "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, "
                 "a.entity_id AS desde, b.entity_id AS hasta, "
                 "r.workspace AS workspace ORDER BY tipo, desde, hasta")

        # DEFECTO DE IDENTIDAD DURABLE (ver informe): para una RELACION el
        # writer devuelve como `created_id` el elementId de Neo4j
        # (cypher.py:406 -> executor.py:544), y `build_rollback` lo usa como
        # `target_id` de la instruccion DELETE_RELATIONSHIP (rollback.py:102).
        # El elementId se regenera al restaurar un dump: un documento de
        # rollback guardado apunta entonces a otra cosa, o a nada.
        print("\n== 3b. Identidad que el writer devuelve para lo escrito")
        print("   created_ids : %s" % (res.created_ids,))
        consulta(probe, "3c. elementId de las relaciones del grafo",
                 "MATCH ()-[r]->() RETURN type(r) AS tipo, elementId(r) AS element_id")

        # ---------------------------------------------------------------
        # 4. IDEMPOTENCIA sobre un plan del utillaje (dos aplicaciones).
        # ---------------------------------------------------------------
        probe.clean()
        probe.seed_entity("entity:origen", version=1, state_hash=W.HASH_A["value"])
        probe.seed_entity("entity:destino", version=1, state_hash=W.HASH_B["value"])
        plan = W.make_plan([W.create_assertion(
            "op:0001", "assertion:carril-c", "entity:origen", "entity:destino")])
        keys = InMemoryAppliedKeys()

        r1 = W.writer(driver, keys=keys).write(plan, W.apply_request(plan))
        print("\n== 4. Idempotencia -- 1a aplicacion: %s %s" % (r1.outcome, r1.codes))
        # Dos subconsultas INDEPENDIENTES: encadenar `MATCH (n) ... MATCH ()-[r]->()`
        # produce un producto cartesiano y devuelve CERO filas cuando no hay
        # relaciones -- una comparacion `[] == []` que pareceria idempotencia y
        # no mide nada.
        RECUENTO = (
            "CALL () { MATCH (n) RETURN count(n) AS nodos } "
            "CALL () { MATCH ()-[r]->() RETURN count(r) AS relaciones } "
            "CALL () { MATCH (a:V3Assertion) RETURN count(a) AS aserciones } "
            "RETURN nodos, relaciones, aserciones"
        )
        antes = consulta(probe, "4a. Recuento tras la PRIMERA aplicacion", RECUENTO)
        huella = probe.snapshot_bytes()

        r2 = W.writer(driver, keys=keys).write(plan, W.apply_request(plan))
        print("\n   2a aplicacion del MISMO plan: %s %s" % (r2.outcome, r2.codes))
        despues = consulta(probe, "4b. Recuento tras la SEGUNDA aplicacion", RECUENTO)
        assert antes and antes[0]["nodos"] > 0, "el recuento no midio nada"
        consulta(probe, "4c. Marcas de operacion aplicada (una por idempotency_key)",
                 "MATCH (op:V3AppliedOperation) RETURN op.workspace AS workspace, "
                 "op.idempotency_key AS idempotency_key, count(*) AS veces "
                 "ORDER BY idempotency_key")
        igual = probe.snapshot_bytes() == huella
        print("\n   grafo byte-identico tras la segunda aplicacion: %s" % igual)
        assert igual and antes == despues, "la segunda aplicacion cambio el grafo"

        # ---------------------------------------------------------------
        # 5. IDENTIDAD DURABLE: (workspace, entity_id), nunca elementId.
        # ---------------------------------------------------------------
        consulta(probe, "5. Identidad de producto vs elementId de Neo4j",
                 "MATCH (n:V3Entity) RETURN n.workspace AS workspace, "
                 "n.entity_id AS entity_id, elementId(n) AS element_id "
                 "ORDER BY entity_id")
        consulta(probe, "5b. Restricciones que sostienen la identidad durable",
                 "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties "
                 "RETURN name, labelsOrTypes, properties ORDER BY name")

        # ---------------------------------------------------------------
        # 6. Aislamiento por workspace.
        # ---------------------------------------------------------------
        probe.seed_entity("entity:origen", workspace=W.OTHER_WORKSPACE,
                          version=1, state_hash=W.HASH_C["value"])
        consulta(probe, "6. Mismo entity_id en dos workspaces = dos identidades",
                 "MATCH (n:V3Entity {entity_id:'entity:origen'}) "
                 "RETURN n.workspace AS workspace, n.state_hash AS state_hash "
                 "ORDER BY workspace")

        # ---------------------------------------------------------------
        # 7. ROLLBACK: que identidad viaja en el documento de reversion.
        # ---------------------------------------------------------------
        print("\n== VEREDICTO: plan aplicado, grafo consultable, idempotencia observada")
        return 0
    finally:
        driver.close()
        W._run(["docker", "rm", "-f", name], check=False)


if __name__ == "__main__":
    raise SystemExit(main())

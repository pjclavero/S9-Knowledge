# -*- coding: utf-8 -*-
"""EQUIPO 1 (tanda 2) -- evidencia: la fuente es NAVEGABLE dentro del grafo.

No es una puerta ni un calibrador: es el guion que genera la evidencia pegada
en el informe. Recorre la cadena V3 desde BYTES con `apply=True` y un Neo4j
efimero de verdad, y DESPUES consulta el grafo con Cypher, imprimiendo cada
consulta y su resultado.

    S9K_WRITER_NEO4J_REAL=1 python3 \\
      artifacts/equipo1-procedencia/demostracion_procedencia_navegable.py

El contenedor lo levanta y lo destruye el propio guion, reutilizando el mismo
mecanismo que la fixture de `test_knowledge_v3_writer_neo4j_real`; no hay un
segundo camino de arranque.

Lo que se demuestra, y en este orden:

  1. La cadena escribe conocimiento Y procedencia (etapa 7b del pipeline).
  2. El recorrido asercion -> evidencia -> episodio -> fuente devuelve el
     LITERAL y el nombre de la fuente, en UNA consulta y por el camino.
  3. El recorrido inverso: dada una fuente, que conocimiento sostiene.
  4. Repetir la ingesta NO duplica procedencia (recuentos y huella del grafo).
  5. La identidad durable es `(workspace, <id del contrato>)`; el `elementId`
     no se guarda ni se usa para enlazar.
  6. Ninguna consulta del visor (`(n:Entity)` / `(n:Entity)-[r]->(m:Entity)`)
     alcanza un nodo de procedencia.
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
from test_knowledge_v3_e2e_global import T_MIEMBRO  # noqa: E402
from knowledge_v3.pipeline.pipeline import KnowledgePipeline  # noqa: E402
from knowledge_v3.writer import bootstrap_writer_schema  # noqa: E402
from knowledge_v3.writer import provenance as P  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: E402


def arrancar():
    """Mismo mecanismo que la fixture `neo4j_driver`, sin pytest."""
    image = os.environ.get("S9K_WRITER_NEO4J_IMAGE", "neo4j:5.26-community")
    name = "s9k-equipo1-" + uuid.uuid4().hex[:12]
    port = W._free_port()
    password = "equipo1-" + uuid.uuid4().hex[:12]
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


def consulta(driver, titulo, cypher, params=None):
    with driver.session() as s:
        filas = [dict(r) for r in s.run(cypher, params or {})]
    print("\n--- %s" % titulo)
    print("    cypher> %s" % " ".join(cypher.split()))
    for fila in filas:
        print("    " + json.dumps(fila, sort_keys=True, default=str, ensure_ascii=False))
    if not filas:
        print("    (0 filas)")
    return filas


def ingerir(driver, source_id, texto):
    """La cadena ENTERA desde bytes, con APPLY real contra este Neo4j."""
    gold = E.gold_dev()
    entidades = E.snapshot_entities(gold)
    cfg = E.base_config(
        gold,
        apply=True,
        writer_driver=driver,
        operator_id="equipo1",
        writer_env={
            "S9K_ALLOW_REAL_INGEST": "1",
            "S9K_WRITER_WORKSPACE": E.base_config(gold).workspace,
        },
    )
    pipeline = KnowledgePipeline(cfg)
    run = pipeline.run([E.raw_case(source_id, texto)], catalog_entities=entidades).runs[0]
    return run, cfg.workspace


def sembrar_extremos(driver, source_id, texto):
    """Las entidades que el plan ENLAZA tienen que existir ya.

    Una corrida en seco (sin driver) da el plan; de el se leen los extremos de
    la `PROJECT_RELATION` y se siembran con la version y el hash que el propio
    plan espera. Es el mismo preparativo que hace la demostracion del carril C:
    el writer nunca crea el objetivo de una relacion, y sin esto el plan aborta
    con `EXEC_TARGET_MISSING` -- que es lo correcto.
    """
    gold = E.gold_dev()
    pipeline = KnowledgePipeline(E.base_config(gold, writer_driver=None))
    run = pipeline.run([E.raw_case(source_id, texto)],
                       catalog_entities=E.snapshot_entities(gold)).runs[0]
    assert run.plan is not None, (run.stopped_at, run.stop_reason)
    ws = run.plan.workspace
    probe = W.GraphProbe(driver=driver)

    def existe(entity_id):
        with driver.session() as s:
            return bool(list(s.run(
                "MATCH (n:V3Entity {entity_id:$id, workspace:$ws}) RETURN 1 LIMIT 1",
                {"id": entity_id, "ws": ws})))

    for op in run.plan.mutation_operations:
        if op["operation_type"] != "PROJECT_RELATION":
            continue
        pl = op["payload"]
        # Sembrar dos veces el mismo `entity_id` chocaria con la restriccion
        # de identidad durable `(workspace, entity_id)` -- que es justo lo que
        # esa restriccion existe para impedir. Se comprueba la ausencia antes.
        if not existe(pl["subject_entity_id"]):
            probe.seed_entity(pl["subject_entity_id"], workspace=ws,
                              version=op["expected_version"],
                              state_hash=op["expected_hash"]["value"])
        if not existe(pl["object_entity_id"]):
            probe.seed_entity(pl["object_entity_id"], workspace=ws,
                              version=1, state_hash=W.HASH_B["value"])
    return ws


RECUENTO = (
    "CALL () { MATCH (n:V3Source) RETURN count(n) AS fuentes } "
    "CALL () { MATCH (n:V3Episode) RETURN count(n) AS episodios } "
    "CALL () { MATCH (n:V3Evidence) RETURN count(n) AS evidencias } "
    "CALL () { MATCH (n:V3Assertion) RETURN count(n) AS aserciones } "
    "CALL () { MATCH ()-[r:HAS_EPISODE]->() RETURN count(r) AS r_has_episode } "
    "CALL () { MATCH ()-[r:HAS_FRAGMENT]->() RETURN count(r) AS r_has_fragment } "
    "CALL () { MATCH ()-[r:SUPPORTED_BY]->() RETURN count(r) AS r_supported_by } "
    "CALL () { MATCH ()-[r:HAS_SUBJECT]->() RETURN count(r) AS r_has_subject } "
    "CALL () { MATCH ()-[r:HAS_OBJECT]->() RETURN count(r) AS r_has_object } "
    "RETURN fuentes, episodios, evidencias, aserciones, r_has_episode, "
    "r_has_fragment, r_supported_by, r_has_subject, r_has_object"
)


def huella(driver):
    """Huella ordenada del grafo: nodos con su identidad y aristas por clave."""
    with driver.session() as s:
        nodos = sorted(
            json.dumps(dict(r), sort_keys=True, default=str)
            for r in s.run(
                "MATCH (n) RETURN labels(n) AS l, "
                "coalesce(n.entity_id, n.assertion_id, n.source_asset_id, "
                "n.episode_id, n.fragment_id, n.idempotency_key) AS id"
            )
        )
        aristas = sorted(
            json.dumps(dict(r), sort_keys=True, default=str)
            for r in s.run(
                "MATCH (a)-[r]->(b) RETURN type(r) AS t, "
                "coalesce(a.assertion_id, a.source_asset_id, a.episode_id, "
                "a.entity_id) AS de, "
                "coalesce(b.entity_id, b.fragment_id, b.episode_id, "
                "b.assertion_id) AS a"
            )
        )
    return nodos, aristas


def main() -> int:
    driver, name, uri = arrancar()
    try:
        print("== Neo4j efimero en %s (contenedor %s)" % (uri, name))

        # -------------------------------------------------------------
        # 0. CONTROL: el grafo esta vacio ANTES. Sin esto, cualquier
        #    recuento posterior podria estar midiendo estado heredado.
        # -------------------------------------------------------------
        vacio = consulta(driver, "0. Control: recuento ANTES de ingerir nada", RECUENTO)
        assert vacio and all(v == 0 for v in vacio[0].values()), (
            "el grafo NO estaba vacio: %s" % vacio)

        # -------------------------------------------------------------
        # 1. La cadena entera, desde bytes, con APPLY real.
        # -------------------------------------------------------------
        sembrar_extremos(driver, "equipo1-fuente", E.T_HECHO)
        run, workspace = ingerir(driver, "equipo1-fuente", E.T_HECHO)
        print("\n== 1. Cadena V3 completa desde bytes, apply=True")
        print("   texto fuente : %r" % (E.T_HECHO,))
        print("   workspace    : %s" % workspace)
        print("   episodios    : %d  fragmentos: %d" % (len(run.episodes), len(run.fragments)))
        print("   write        : %s %s" % (run.write_result.outcome, run.write_result.codes))
        assert run.write_result.outcome == OUTCOME_APPLIED, run.write_result.codes
        print("   procedencia  : %s" % json.dumps(
            run.provenance_result.to_dict() if run.provenance_result else None,
            sort_keys=True, ensure_ascii=False))
        assert run.provenance_result is not None, "la etapa 7b no se ejecuto"

        consulta(driver, "1b. Nodos de procedencia escritos",
                 "MATCH (n) WHERE any(l IN labels(n) WHERE l IN "
                 "['V3Source','V3Episode','V3Evidence']) "
                 "RETURN labels(n) AS labels, n.source_asset_id AS source_asset_id, "
                 "n.episode_id AS episode_id, n.fragment_id AS fragment_id, "
                 "n.workspace AS workspace, n.provenance_contract AS contrato, "
                 "n.visibility AS visibility ORDER BY labels")

        # -------------------------------------------------------------
        # 2. EL RECORRIDO: de la asercion al literal y a la fuente.
        # -------------------------------------------------------------
        aserciones = [r["assertion_id"] for r in consulta(
            driver, "2. Aserciones escritas por el plan",
            "MATCH (a:V3Assertion {workspace:$ws}) "
            "RETURN a.assertion_id AS assertion_id, a.predicate AS predicate, "
            "a.evidence_fragment_ids AS evidencia ORDER BY a.assertion_id",
            {"ws": workspace})]
        assert aserciones, "no hay ni una asercion: el recorrido no mediria nada"

        total = 0
        for assertion_id in aserciones:
            q = P.trace_query(workspace, assertion_id)
            filas = consulta(driver, "2b. RECORRIDO COMPLETO desde %s" % assertion_id,
                             q.cypher, q.params)
            total += len(filas)
        assert total > 0, "el recorrido devolvio 0 filas: la fuente NO es navegable"
        print("\n   filas de recorrido (no vacio): %d" % total)

        # -------------------------------------------------------------
        # 3. El recorrido INVERSO: de la fuente al conocimiento.
        # -------------------------------------------------------------
        inverso = consulta(
            driver, "3. Recorrido INVERSO: que conocimiento sostiene esta fuente",
            "MATCH (src:V3Source {workspace:$ws})-[:HAS_EPISODE]->(ep:V3Episode)"
            "-[:HAS_FRAGMENT]->(ev:V3Evidence)<-[:SUPPORTED_BY]-(a:V3Assertion)"
            "-[:HAS_SUBJECT]->(e:V3Entity) "
            "RETURN src.original_name AS fuente, ep.episode_id AS episodio, "
            "left(ev.literal_text, 80) AS literal, a.assertion_id AS assertion_id, "
            "e.entity_id AS sujeto ORDER BY a.assertion_id",
            {"ws": workspace})
        assert inverso, "el recorrido inverso devolvio 0 filas"

        # -------------------------------------------------------------
        # 3b. DOS fuentes: cada conocimiento apunta a LA SUYA.
        # -------------------------------------------------------------
        sembrar_extremos(driver, "equipo1-fuente-2", T_MIEMBRO)
        run_b, _ = ingerir(driver, "equipo1-fuente-2", T_MIEMBRO)
        print("\n== 3b. Segunda fuente DISTINTA: %r -> %s %s" % (
            T_MIEMBRO, run_b.write_result.outcome, run_b.write_result.codes))
        cruce = consulta(
            driver, "3c. Cada asercion y LA fuente que la sostiene",
            "MATCH (a:V3Assertion {workspace:$ws})-[:SUPPORTED_BY]->(ev:V3Evidence)"
            "<-[:HAS_FRAGMENT]-(:V3Episode)<-[:HAS_EPISODE]-(src:V3Source) "
            "RETURN a.assertion_id AS assertion_id, a.predicate AS predicate, "
            "ev.literal_text AS literal, src.original_name AS fuente "
            "ORDER BY a.assertion_id",
            {"ws": workspace})
        assert len(cruce) >= 2, "menos de dos recorridos: el cruce no mide nada"
        por_asercion: dict = {}
        for fila in cruce:
            por_asercion.setdefault(fila["assertion_id"], set()).add(fila["fuente"])
        assert all(len(v) == 1 for v in por_asercion.values()), (
            "una asercion apunta a mas de una fuente: hay cruce de procedencia "
            "(%s)" % por_asercion)
        assert len({next(iter(v)) for v in por_asercion.values()}) == 2, (
            "las dos aserciones apuntan a la misma fuente: el cruce no discrimina")
        print("   cada asercion -> exactamente una fuente, y son dos distintas: %s"
              % {k: sorted(v) for k, v in por_asercion.items()})

        # -------------------------------------------------------------
        # 4. IDEMPOTENCIA: repetir la ingesta no duplica procedencia.
        # -------------------------------------------------------------
        antes = consulta(driver, "4a. Recuento tras las DOS ingestas", RECUENTO)
        assert antes and antes[0]["evidencias"] > 0 and antes[0]["r_supported_by"] > 0, (
            "el recuento no midio nada: sin evidencia ni aristas no hay idempotencia "
            "que demostrar")
        h_antes = huella(driver)

        run2, _ = ingerir(driver, "equipo1-fuente", E.T_HECHO)
        print("\n== 4. SEGUNDA ingesta del mismo texto: %s %s" % (
            run2.write_result.outcome, run2.write_result.codes))
        print("   procedencia  : %s" % json.dumps(
            run2.provenance_result.to_dict() if run2.provenance_result else None,
            sort_keys=True, ensure_ascii=False))
        despues = consulta(driver, "4b. Recuento tras REPETIR la primera ingesta", RECUENTO)
        h_despues = huella(driver)
        print("\n   recuentos identicos     : %s" % (antes == despues,))
        print("   huella grafo identica   : %s" % (h_antes == h_despues,))
        assert antes == despues, "la segunda ingesta cambio los recuentos"
        assert h_antes == h_despues, "la segunda ingesta cambio el grafo"
        if run2.provenance_result is not None:
            assert run2.provenance_result.total_created == 0, (
                "la segunda ingesta CREO procedencia: %s"
                % run2.provenance_result.to_dict())

        # -------------------------------------------------------------
        # 5. Identidad durable, no elementId.
        # -------------------------------------------------------------
        consulta(driver, "5. Identidad de producto vs elementId",
                 "MATCH (n:V3Evidence) RETURN n.workspace AS workspace, "
                 "n.fragment_id AS fragment_id, elementId(n) AS element_id "
                 "ORDER BY fragment_id LIMIT 5")
        consulta(driver, "5b. Restricciones de unicidad de la procedencia",
                 "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties "
                 "WHERE any(l IN labelsOrTypes WHERE l IN "
                 "['V3Source','V3Episode','V3Evidence']) "
                 "RETURN name, labelsOrTypes, properties ORDER BY name")

        # -------------------------------------------------------------
        # 6. La procedencia NO es alcanzable por la superficie del visor.
        # -------------------------------------------------------------
        fuga = consulta(
            driver, "6. Superficie de lectura del visor sobre la procedencia",
            "CALL () { MATCH (n:Entity) WHERE any(l IN labels(n) WHERE l IN "
            "['V3Source','V3Episode','V3Evidence']) RETURN count(n) AS nodos_visor } "
            "CALL () { MATCH (:Entity)-[r]->(:Entity) WHERE type(r) IN "
            "['HAS_EPISODE','HAS_FRAGMENT','SUPPORTED_BY','HAS_SUBJECT','HAS_OBJECT'] "
            "RETURN count(r) AS aristas_visor } "
            "RETURN nodos_visor, aristas_visor")
        assert fuga and fuga[0]["nodos_visor"] == 0 and fuga[0]["aristas_visor"] == 0, (
            "la procedencia es alcanzable desde la superficie de lectura del visor")

        print("\n== VEREDICTO: procedencia PERSISTIDA, recorrido NAVEGABLE en ambos "
              "sentidos, idempotente y fuera de la superficie de lectura del visor")
        return 0
    finally:
        driver.close()
        W._run(["docker", "rm", "-f", name], check=False)


if __name__ == "__main__":
    raise SystemExit(main())

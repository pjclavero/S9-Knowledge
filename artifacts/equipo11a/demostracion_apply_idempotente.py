# -*- coding: utf-8 -*-
"""EQUIPO 11A -- los cuatro pasos (apply / repeat / rollback / re-apply).

Contra un Neo4j REAL y efimero, desde VACIO, por la ruta de producto
(`KnowledgePipeline` desde bytes -> plan aprobado -> `GraphWriter`). No hay un
solo Cypher de ESCRITURA a mano: todo lo que entra al grafo lo escribe el
producto. El Cypher que se ve aqui es SOLO censo (lectura).

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/equipo11a/demostracion_apply_idempotente.py

El texto de la fuente nombra una entidad que el catalogo NO conoce, asi que el
plan trae `CREATE_ENTITY`: es exactamente el caso en el que se midieron los dos
defectos.
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
from knowledge_v3.engine.snapshot import SnapshotEntity  # noqa: E402
from knowledge_v3.pipeline.pipeline import KnowledgePipeline  # noqa: E402
from knowledge_v3.writer import InMemoryAppliedKeys, bootstrap_writer_schema  # noqa: E402
from knowledge_v3.writer.rollback_provenance import execute_rollback  # noqa: E402

TEXTO = "Ilaria Vandreth lidera la Casa del Ciervo."
#: Sujeto del hecho. En este escenario es un ALTA APROBADA todavia no escrita
#: en el grafo, que es lo que produce `pending_creation=True` por la ruta de
#: producto (`entity_decisions.approved_snapshot_entities`).
ALTAS = ("entity:leyenda:ilaria", "entity:leyenda:casa-ciervo")


def plan_con_alta(source_id: str, texto: str):
    """Mismo recorrido que `E.pipeline_plan`, con el SUJETO como alta aprobada.

    No se inventa un camino nuevo: se reproduce lo que
    `entity_decisions.approved_snapshot_entities` -> `graph_catalog
    .snapshot_entities(..., altas=...)` entrega al motor cuando un humano
    aprueba el alta de una entidad que el grafo aun no tiene
    (`pending_creation=True`, sin version ni hash previos).
    """
    gold = E.gold_dev()
    entidades = []
    visto = set()
    for ent in E.snapshot_entities(gold):
        if ent.entity_id in ALTAS:
            visto.add(ent.entity_id)
            entidades.append(
                SnapshotEntity.of(
                    ent.entity_id,
                    ent.entity_type,
                    0,
                    pending_creation=True,
                    canonical_name=ent.canonical_name or ent.entity_id,
                    aliases=tuple(ent.aliases),
                )
            )
        else:
            entidades.append(ent)
    assert visto == set(ALTAS), (
        "el catalogo no trae %s: el escenario no es el medido" % (set(ALTAS) - visto,)
    )
    pipeline = KnowledgePipeline(E.base_config(gold, writer_driver=None))
    run = pipeline.run([E.raw_case(source_id, texto)], catalog_entities=entidades).runs[0]
    assert run.plan is not None, (run.stopped_at, run.stop_reason)
    return run.plan.to_dict(), run, pipeline

# Censo. UNA subconsulta por cosa contada: encadenar dos MATCH sueltos da
# producto cartesiano y devuelve CERO cuando alguna parte esta vacia.
CENSO = (
    "CALL () { MATCH (n) RETURN count(n) AS nodos } "
    "CALL () { MATCH (n:V3Entity) RETURN count(n) AS entidades } "
    "CALL () { MATCH (n:V3Assertion) RETURN count(n) AS aserciones } "
    "CALL () { MATCH (m:V3AppliedOperation) RETURN count(m) AS marcas } "
    "CALL () { MATCH ()-[r]->() RETURN count(r) AS aristas } "
    "CALL () { MATCH (:V3Entity)-[r]->(:V3Entity) RETURN count(r) AS aristas_ent_ent } "
    "RETURN nodos, entidades, aserciones, marcas, aristas, aristas_ent_ent"
)


def arrancar():
    image = os.environ.get("S9K_WRITER_NEO4J_IMAGE", "neo4j:5.26-community")
    name = "s9k-eq11a-" + uuid.uuid4().hex[:12]
    port = W._free_port()
    password = "eq11a-" + uuid.uuid4().hex[:12]
    W._run([
        "docker", "run", "--rm", "--detach", "--name", name,
        "--publish", "127.0.0.1:%d:7687" % port,
        "--env", "NEO4J_AUTH=neo4j/%s" % password,
        "--env", "NEO4J_server_memory_heap_initial__size=128m",
        "--env", "NEO4J_server_memory_heap_max__size=512m",
        image,
    ])
    driver = neo4j.GraphDatabase.driver(
        "bolt://127.0.0.1:%d" % port, auth=("neo4j", password)
    )
    # `verify_connectivity()` responde en cuanto el Bolt acepta conexiones,
    # ANTES de que la base por defecto este servible: bajo presion de memoria
    # el arranque se alarga y `bootstrap_writer_schema` se comia un
    # `DatabaseUnavailable` transitorio. Se espera por la CONDICION FINAL --que
    # la base conteste una consulta-- y el propio bootstrap se reintenta.
    limite = time.monotonic() + 300
    try:
        while True:
            try:
                with driver.session() as ses:
                    ses.run("RETURN 1").consume()
                bootstrap_writer_schema(driver)
                break
            except Exception:
                if time.monotonic() >= limite:
                    raise
                time.sleep(2)
    except BaseException:
        # Si el arranque falla, el contenedor se retira AQUI. El `finally` de
        # `main` no puede hacerlo: todavia no ha recibido el nombre, y asi es
        # como se quedaron dos Neo4j mios vivos comiendo la memoria que hacia
        # falta para arrancar el siguiente.
        driver.close()
        W._run(["docker", "rm", "-f", name], check=False)
        raise
    return driver, name


def censo(probe, titulo):
    filas = probe.run(CENSO, {})
    assert filas, "el censo no devolvio ninguna fila: no ha medido nada"
    fila = filas[0]
    print("\n-- CENSO %s" % titulo)
    print("   " + json.dumps(fila, sort_keys=True, default=str, ensure_ascii=False))
    marcas = probe.run(
        "MATCH (m:V3AppliedOperation) RETURN m.idempotency_key AS key, "
        "m.operation_id AS operation_id, m.plan_hash AS plan_hash ORDER BY key",
        {},
    )
    for m in marcas:
        print("   marca: " + json.dumps(m, sort_keys=True, default=str, ensure_ascii=False))
    aristas = probe.run(
        "MATCH (a:V3Entity)-[r]->(b:V3Entity) RETURN type(r) AS tipo, "
        "a.entity_id AS desde, b.entity_id AS hasta ORDER BY tipo, desde",
        {},
    )
    for a in aristas:
        print("   arista entidad->entidad: "
              + json.dumps(a, sort_keys=True, ensure_ascii=False))
    return fila, aristas


def escenario_b(driver, probe):
    """DEF-2: la marca colgante que deja irrecuperable la relacion.

    Todo por la ruta de producto, sin un solo Cypher de escritura:

      apply A  -- primera ingesta, con las dos entidades como altas aprobadas.
      apply B  -- SEGUNDA ingesta de la MISMA fuente. Las entidades ya estan en
                  el grafo, asi que el catalogo las da por existentes y el plan
                  sale con `PROJECT_RELATION` anclada a su version.
      rollback A
      re-apply

    Sobre el producto SIN arreglo, apply A no proyecta nada y es apply B quien
    escribe la arista, con su propio `plan_hash`. Al revertir A, el
    `DETACH DELETE` se lleva la arista pero la marca de B sobrevive: colgante,
    invisible para `residues` --que solo miraba el `plan_hash` propio-- y
    suficiente para que cualquier reintento se cierre en NOOP.
    """
    fallos = []
    probe.clean()
    print("\n" + "#" * 70)
    print("# ESCENARIO B -- marca colgante y recuperabilidad")
    print("#" * 70)
    censo(probe, "S0 (vacio)")

    plan_a, _r, _q = plan_con_alta("eq11a-b", TEXTO)
    ra = E.writer_for(plan_a, driver, InMemoryAppliedKeys()).write(
        plan_a, E.request_for(plan_a)
    )
    print("\n== apply A: %s codes=%s ops=%s" % (ra.outcome, ra.codes, ra.applied_operations))
    sa, aristas_a = censo(probe, "tras apply A")

    # Segunda ingesta de la misma fuente: las entidades YA existen en el grafo,
    # asi que entran por el catalogo normal, sin alta.
    plan_b, _r2, _q2 = E.pipeline_plan("eq11a-b", TEXTO)
    rb = E.writer_for(plan_b, driver, InMemoryAppliedKeys()).write(
        plan_b, E.request_for(plan_b)
    )
    print("\n== apply B (segunda ingesta): %s codes=%s ops=%s created=%s"
          % (rb.outcome, rb.codes, rb.applied_operations, rb.created_ids))
    sb, aristas_b = censo(probe, "tras apply B")
    if rb.applied_operations:
        fallos.append(
            "DEF-1: la SEGUNDA ingesta escribio %s operacion(es) %s: el primer "
            "apply no habia terminado el trabajo"
            % (rb.applied_operations, rb.created_ids)
        )

    assert ra.rollback is not None, "apply A no dejo documento de rollback"
    with driver.session() as ses:
        rep = execute_rollback(ses, ra.rollback)
    print("\n== rollback(A): clean=%s residues=%s unrecoverable=%s"
          % (rep.clean, len(rep.residues), len(rep.unrecoverable)))
    for r in rep.residues:
        print("   residuo: " + json.dumps(r, sort_keys=True, default=str, ensure_ascii=False))
    s0, _ = censo(probe, "tras rollback(A)")
    if s0["marcas"] and rep.clean:
        fallos.append(
            "DEF-2: rollback declara clean=True con %s marca(s) V3AppliedOperation "
            "viva(s): estado aparentemente limpio pero irrecuperable" % s0["marcas"]
        )

    plan_c, _r3, _q3 = plan_con_alta("eq11a-b", TEXTO)
    rc = E.writer_for(plan_c, driver, InMemoryAppliedKeys()).write(
        plan_c, E.request_for(plan_c)
    )
    print("\n== re-apply: %s codes=%s ops=%s" % (rc.outcome, rc.codes, rc.applied_operations))
    sc, aristas_c = censo(probe, "tras re-apply")
    if aristas_c != aristas_a or sc["aristas_ent_ent"] == 0:
        fallos.append(
            "DEF-2: el re-apply NO vuelve a materializar la relacion: %s vs %s"
            % (aristas_c, aristas_a)
        )
    return fallos


def main() -> int:
    driver, name = arrancar()
    probe = W.GraphProbe(driver=driver)
    fallos = []
    try:
        plan, _run, _p = plan_con_alta("eq11a-alta", TEXTO)
        tipos = [o["operation_type"] for o in plan["mutation_operations"]]
        print("== PLAN por la ruta de producto (desde bytes)")
        print("   texto       : %r" % TEXTO)
        print("   aprobado    : %s" % plan["local_approval"]["approved"])
        print("   operaciones : %s" % tipos)
        assert "CREATE_ENTITY" in tipos, "el plan no trae alta: no es el caso medido"

        censo(probe, "S0 (vacio)")

        # ---- PASO 1: primer apply ------------------------------------
        r1 = E.writer_for(plan, driver, InMemoryAppliedKeys()).write(
            plan, E.request_for(plan)
        )
        print("\n== PASO 1 apply#1: %s codes=%s applied_operations=%s"
              % (r1.outcome, r1.codes, r1.applied_operations))
        s1, aristas1 = censo(probe, "S1 (tras apply#1)")
        if "PROJECT_RELATION" not in tipos:
            fallos.append("DEF-1: el plan del primer apply NO trae PROJECT_RELATION")
        if s1["aristas_ent_ent"] == 0:
            fallos.append("DEF-1: tras el PRIMER apply NO hay arista entidad->entidad")

        # ---- PASO 2: repeat apply ------------------------------------
        r2 = E.writer_for(plan, driver, InMemoryAppliedKeys()).write(
            plan, E.request_for(plan)
        )
        print("\n== PASO 2 apply#2: %s codes=%s applied_operations=%s created=%s"
              % (r2.outcome, r2.codes, r2.applied_operations, r2.created_ids))
        s2, aristas2 = censo(probe, "S1' (tras apply#2)")
        if s2 != s1 or aristas2 != aristas1:
            fallos.append("DEF-1: el SEGUNDO apply cambio el grafo: %s -> %s" % (s1, s2))
        if r2.applied_operations:
            fallos.append(
                "DEF-1: apply#2 declara %s operaciones aplicadas (no es NOOP)"
                % r2.applied_operations
            )

        # ---- PASO 3: rollback del primer apply -----------------------
        assert r1.rollback is not None, (
            "apply#1 no dejo documento de rollback: %s %s" % (r1.outcome, r1.codes)
        )
        with driver.session() as ses:
            rep = execute_rollback(ses, r1.rollback)
        print("\n== PASO 3 rollback(apply#1): clean=%s residues=%s unrecoverable=%s"
              % (rep.clean, len(rep.residues), len(rep.unrecoverable)))
        for r in rep.residues:
            print("   residuo: "
                  + json.dumps(r, sort_keys=True, default=str, ensure_ascii=False))
        s3, _ = censo(probe, "S0' (tras rollback)")
        if s3["marcas"] and rep.clean:
            fallos.append(
                "DEF-2: rollback declara clean=True dejando %s marca(s) viva(s)"
                % s3["marcas"]
            )

        # ---- PASO 4: re-apply por la ruta de producto ----------------
        plan_b, _r, _q = plan_con_alta("eq11a-alta", TEXTO)
        r3 = E.writer_for(plan_b, driver, InMemoryAppliedKeys()).write(
            plan_b, E.request_for(plan_b)
        )
        print("\n== PASO 4 re-apply: %s codes=%s applied_operations=%s"
              % (r3.outcome, r3.codes, r3.applied_operations))
        s4, aristas4 = censo(probe, "S1'' (tras re-apply)")
        if s4["aristas_ent_ent"] != s1["aristas_ent_ent"] or aristas4 != aristas1:
            fallos.append(
                "DEF-2: el re-apply NO vuelve a materializar la relacion: %s vs %s"
                % (aristas4, aristas1)
            )

        fallos.extend(escenario_b(driver, probe))

        print("\n" + "=" * 70)
        if fallos:
            print("VEREDICTO: DEFECTOS PRESENTES")
            for f in fallos:
                print("  * " + f)
            return 1
        print("VEREDICTO: los cuatro pasos se comportan como exige el contrato")
        return 0
    finally:
        driver.close()
        W._run(["docker", "rm", "-f", name], check=False)


if __name__ == "__main__":
    raise SystemExit(main())

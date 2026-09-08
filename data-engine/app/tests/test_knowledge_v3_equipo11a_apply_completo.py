# -*- coding: utf-8 -*-
"""EQUIPO 11A -- un apply que crea entidades TERMINA el trabajo.

Estas pruebas son las que faltaban. El supervisor cerro 8262 tests en verde con
los dos defectos vivos porque ninguna prueba miraba lo unico que importaba: si
la arista entidad->entidad existe DESPUES DEL PRIMER APPLY.

Las de plan no necesitan Neo4j y se ponen rojas sobre el producto sin arreglo.
La de grafo levanta su propio Neo4j efimero y recorre los cuatro pasos.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.engine.snapshot import SnapshotEntity  # noqa: E402
from knowledge_v3.pipeline.pipeline import KnowledgePipeline  # noqa: E402

import test_knowledge_v3_e2e_neo4j_real as E  # noqa: E402


TEXTO = "Ilaria Vandreth lidera la Casa del Ciervo."
#: Las dos puntas del hecho, como altas aprobadas todavia no escritas en el
#: grafo. Es la primera ingesta de un workspace vacio: el caso en el que se
#: midieron los dos defectos.
ALTAS = ("entity:leyenda:ilaria", "entity:leyenda:casa-ciervo")


def plan_con_altas(source_id: str = "eq11a"):
    """Plan del producto donde AMBOS extremos se crean en el propio plan.

    Reproduce lo que `entity_decisions.approved_snapshot_entities` entrega al
    motor cuando un humano aprueba el alta de entidades que el grafo aun no
    tiene: `pending_creation=True`, sin version ni hash previos.
    """
    gold = E.gold_dev()
    entidades = []
    vistas = set()
    for ent in E.snapshot_entities(gold):
        if ent.entity_id in ALTAS:
            vistas.add(ent.entity_id)
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
    assert vistas == set(ALTAS), "el catalogo no trae %s" % (set(ALTAS) - vistas,)
    pipeline = KnowledgePipeline(E.base_config(gold, writer_driver=None))
    run = pipeline.run([E.raw_case(source_id, TEXTO)], catalog_entities=entidades).runs[0]
    assert run.plan is not None, (run.stopped_at, run.stop_reason)
    return run.plan.to_dict()


def _ops(plan, tipo):
    return [o for o in plan["mutation_operations"] if o["operation_type"] == tipo]


def test_el_plan_que_crea_entidades_TRAE_la_proyeccion():
    """El defecto en una linea: antes salia alta + asercion y NADA mas.

    La arista quedaba para "la siguiente ingesta", es decir: para un SEGUNDO
    apply. Un plan a medias que otro apply termina no es un plan idempotente.
    """
    plan = plan_con_altas()
    assert _ops(plan, "CREATE_ENTITY"), "el escenario exige altas en el plan"
    proyecciones = _ops(plan, "PROJECT_RELATION")
    assert proyecciones, (
        "el plan crea entidades y NO proyecta la relacion: el conocimiento "
        "queda a la espera de un segundo apply"
    )


def test_la_proyeccion_se_ancla_al_alta_del_propio_plan():
    """El ancla es el `CREATE_ENTITY` de delante, no una version inventada.

    Lo que NO se hace: darle una `expected_version` a una entidad que aun no
    existe. El contrato reserva `WOULD_CREATE` + version/hash nulos justamente
    para "la operacion crea algo que aun no existe".
    """
    plan = plan_con_altas()
    altas = {o["target_entity_id"] for o in _ops(plan, "CREATE_ENTITY")}
    for op in _ops(plan, "PROJECT_RELATION"):
        if op["expected_state"] != "WOULD_CREATE":
            continue
        assert op["expected_version"] is None and op["expected_hash"] is None, (
            "una proyeccion anclada al plan no declara estado previo del grafo"
        )
        assert op["target_entity_id"] in altas, (
            "proyeccion sin version esperada y SIN el alta que la anclaria: "
            "eso no es un ancla, es saltarse el control optimista"
        )


def test_el_alta_va_ANTES_que_la_proyeccion_que_la_usa():
    """Orden dentro de la transaccion. Si no, el extremo no existe al leerlo."""
    plan = plan_con_altas()
    orden = [o["operation_type"] for o in plan["mutation_operations"]]
    for op in _ops(plan, "PROJECT_RELATION"):
        if op["expected_state"] != "WOULD_CREATE":
            continue
        idx_proy = plan["mutation_operations"].index(op)
        altas_antes = {
            o["target_entity_id"]
            for o in plan["mutation_operations"][:idx_proy]
            if o["operation_type"] == "CREATE_ENTITY"
        }
        assert op["target_entity_id"] in altas_antes, (
            "la proyeccion va delante de su alta (%s): al ejecutarla el extremo "
            "todavia no existe" % orden
        )


# ==========================================================================
# Contra Neo4j real: los cuatro pasos, con censo antes y despues de cada uno.
# ==========================================================================
LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"

CENSO = (
    "CALL () { MATCH (n) RETURN count(n) AS nodos } "
    "CALL () { MATCH (n:V3Entity) RETURN count(n) AS entidades } "
    "CALL () { MATCH (n:V3Assertion) RETURN count(n) AS aserciones } "
    "CALL () { MATCH (m:V3AppliedOperation) RETURN count(m) AS marcas } "
    "CALL () { MATCH (:V3Entity)-[r]->(:V3Entity) RETURN count(r) AS aristas_ent_ent } "
    "RETURN nodos, entidades, aserciones, marcas, aristas_ent_ent"
)


def _censo(probe):
    filas = probe.run(CENSO, {})
    assert filas, "el censo no devolvio ninguna fila: no ha medido nada"
    return filas[0]


def _aristas(probe):
    return probe.run(
        "MATCH (a:V3Entity)-[r]->(b:V3Entity) RETURN type(r) AS tipo, "
        "a.entity_id AS desde, b.entity_id AS hasta ORDER BY tipo, desde",
        {},
    )


@pytest.fixture(scope="module")
def _driver_11a():
    """Neo4j propio. UN solo mecanismo de arranque: el de la fixture del writer."""
    import test_knowledge_v3_writer_neo4j_real as W

    with W.neo4j_efimero("s9k-eq11a-test") as driver:
        yield driver


@pytest.fixture()
def graph(_driver_11a):
    import test_knowledge_v3_writer_neo4j_real as W

    probe = W.GraphProbe(_driver_11a)
    probe.clean()
    yield probe
    probe.clean()


@pytest.mark.skipif(not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1")
def test_apply_repeat_rollback_reapply_contra_neo4j_real(graph):
    """S0 -> S1 -> S1 (NOOP real) -> S0 -> S1. Con censo en cada paso."""
    from knowledge_v3.writer import InMemoryAppliedKeys
    from knowledge_v3.writer.rollback_provenance import execute_rollback

    probe = graph
    s0 = _censo(probe)
    assert s0["nodos"] == 0, "el escenario empieza desde VACIO"

    plan = plan_con_altas("eq11a-real")
    r1 = E.writer_for(plan, probe.driver, InMemoryAppliedKeys()).write(
        plan, E.request_for(plan)
    )
    assert r1.outcome == "APPLIED", (r1.outcome, r1.codes)
    s1, aristas1 = _censo(probe), _aristas(probe)

    # PASO 1: TODO presente ya en el PRIMER apply.
    assert s1["entidades"] == 2, s1
    assert s1["aserciones"] == 1, s1
    assert s1["aristas_ent_ent"] == 1, (
        "el primer apply creo las entidades pero NO materializo la relacion: %s" % s1
    )
    assert aristas1, "no hay arista entidad->entidad que comparar"

    # PASO 2: repeat apply = CERO cambios semanticos.
    r2 = E.writer_for(plan, probe.driver, InMemoryAppliedKeys()).write(
        plan, E.request_for(plan)
    )
    assert r2.applied_operations == 0, (
        "el segundo apply escribio %s operacion(es) %s: estaba terminando el "
        "trabajo del primero" % (r2.applied_operations, r2.created_ids)
    )
    assert _censo(probe) == s1 and _aristas(probe) == aristas1

    # PASO 3: rollback deja S0 EXACTO, marcas incluidas.
    assert r1.rollback is not None
    with probe.driver.session() as ses:
        rep = execute_rollback(ses, r1.rollback)
    s3 = _censo(probe)
    assert s3["marcas"] == 0, (
        "quedan %s marca(s) V3AppliedOperation tras el rollback: una marca "
        "superviviente hace la relacion irrecuperable" % s3["marcas"]
    )
    assert s3["nodos"] == 0, s3
    # `clean` tiene que ser coherente con el censo, no con lo que el documento
    # nombra: un `clean:true` sobre marcas vivas es el `residues:[]` mentiroso
    # un nivel mas abajo.
    assert rep.clean is (s3["marcas"] == 0 and s3["nodos"] == 0), (
        "clean=%s no describe el grafo real %s (residuos: %s)"
        % (rep.clean, s3, rep.residues)
    )

    # PASO 4: re-apply vuelve a materializar lo mismo.
    plan_b = plan_con_altas("eq11a-real")
    r3 = E.writer_for(plan_b, probe.driver, InMemoryAppliedKeys()).write(
        plan_b, E.request_for(plan_b)
    )
    assert r3.outcome == "APPLIED", (r3.outcome, r3.codes)
    assert _censo(probe) == s1, "el re-apply no reconstruye S1"
    assert _aristas(probe) == aristas1, "el re-apply no rehace la relacion"

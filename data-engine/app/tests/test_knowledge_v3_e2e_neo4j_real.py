# -*- coding: utf-8 -*-
"""PUERTA 7 — E2E contra un Neo4j REAL y efimero.

Los dos escenarios diferidos de `test_knowledge_v3_e2e_global.py` (E2E-01 y
E2E-12), mas la cesacion contra grafo real que pedia el encargo. Saltados por
defecto; se activan igual que el writer real:

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \
      data-engine/app/tests/test_knowledge_v3_e2e_neo4j_real.py -q

POR QUE UN FICHERO APARTE Y NO DENTRO DE `test_knowledge_v3_e2e_global.py`
--------------------------------------------------------------------------
Porque las fixtures del contenedor viven en `test_knowledge_v3_writer_neo4j_real`
y ese modulo hace `pytest.importorskip("neo4j")`. Importarlo desde el fichero
global ataria sus 39 tests —que hoy corren siempre— a que el paquete `neo4j`
este instalado: un dia sin esa dependencia perderiamos 39 tests en silencio.
Aqui el riesgo esta acotado a este fichero, que ya requiere Docker de todos
modos.

QUE SE EJERCITA DE VERDAD
-------------------------
El plan de E2E-01 se construye recorriendo la CADENA COMPLETA desde bytes (el
mismo `run_text` del fichero global), no a mano. Lo que se aplica contra Neo4j
es exactamente lo que el motor produce en produccion.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="puerta 7 / Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1",
)

from knowledge_v3.pipeline.pipeline import KnowledgePipeline  # noqa: E402
from knowledge_v3.writer import (  # noqa: E402
    GraphWriter,
    InMemoryAppliedKeys,
    InMemoryAuditSink,
    OperatorRequest,
    codes,
)
from knowledge_v3.writer.writer import OUTCOME_ABORTED, OUTCOME_APPLIED  # noqa: E402

# Fixtures del contenedor efimero y utillaje de planes, reutilizados tal cual.
from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401,I100
    HASH_A,
    HASH_B,
    GraphProbe,
    apply_request,
    create_assertion,
    graph,
    make_plan,
    neo4j_driver,
    supersede_assertion,
)
from test_knowledge_v3_writer_neo4j_real import WORKSPACE as WRITER_WORKSPACE  # noqa: E402

from test_knowledge_v3_e2e_global import (  # noqa: E402,I100
    T_CESACION,
    T_HECHO,
    T_NEG_CESACION,
    base_config,
    gold_dev,
    raw_case,
    snapshot_entities,
)


# ==========================================================================
# Utillaje: llevar un plan REAL del pipeline hasta el grafo
# ==========================================================================
def pipeline_plan(source_id: str, text: str):
    """Recorre la cadena entera desde bytes y devuelve `(plan_doc, run)`.

    Sin driver: aqui solo se quiere el PLAN. Quien escribe es el writer que
    monta cada test, con el driver del contenedor.
    """
    gold = gold_dev()
    entities = snapshot_entities(gold)
    pipeline = KnowledgePipeline(base_config(gold, writer_driver=None))
    run = pipeline.run([raw_case(source_id, text)], catalog_entities=entities).runs[0]
    assert run.plan is not None, (run.stopped_at, run.stop_reason)
    return run.plan.to_dict(), run, pipeline


def clock_for(plan_doc: dict):
    """Reloj dentro de la validez del plan. El plan del pipeline caduca."""
    moment = datetime.fromisoformat(plan_doc["created_at"].replace("Z", "+00:00"))
    return lambda: moment.astimezone(timezone.utc)


def writer_for(plan_doc: dict, driver, keys=None) -> GraphWriter:
    return GraphWriter(
        workspace=plan_doc["workspace"],
        driver=driver,
        audit=InMemoryAuditSink(),
        applied_keys=keys or InMemoryAppliedKeys(),
        clock=clock_for(plan_doc),
    )


def request_for(plan_doc: dict, **over) -> OperatorRequest:
    base = dict(
        apply=True,
        operator_id="puerta7",
        workspace=plan_doc["workspace"],
        expected_plan_hash=plan_doc["plan_hash"]["value"],
        max_operations=50,
        current_snapshot_id=plan_doc["snapshot_id"],
        env={
            "S9K_ALLOW_REAL_INGEST": "1",
            "S9K_WRITER_WORKSPACE": plan_doc["workspace"],
        },
    )
    base.update(over)
    return OperatorRequest(**base)


# ==========================================================================
# E2E-01 — el plan real del motor, aplicado contra Neo4j
# ==========================================================================
# REGRESION F7-2: antes era xfail por el assertion_id duplicado en payload.
def test_e2e_01_aplicado_contra_neo4j_efimero(graph: GraphProbe):
    """El plan de E2E-01, construido desde bytes, se aplica de verdad."""
    plan_doc, _run, _p = pipeline_plan("p7-e2e-01", T_HECHO)
    assert plan_doc["approved"] is True or plan_doc["local_approval"]["approved"] is True

    result = writer_for(plan_doc, graph.driver).write(plan_doc, request_for(plan_doc))

    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert graph.counts()["nodes"] >= 1


def test_e2e_01_la_forma_que_el_writer_si_admite_se_aplica_y_es_idempotente(
    graph: GraphProbe,
):
    """Control que AISLA F7-2 al payload, no al camino.

    Mismo hecho, mismas entidades, pero con el payload en la forma que el writer
    documenta. Si esto pasa y el test anterior falla, el grafo y el writer estan
    bien: lo que esta mal es lo que el planner mete en el payload.
    """
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    plan = make_plan(
        [create_assertion("op:0001", "assertion:e2e01", "entity:origen", "entity:destino")]
    )
    keys = InMemoryAppliedKeys()

    first = _writer_real(graph.driver, keys).write(plan, apply_request(plan))
    assert first.outcome == OUTCOME_APPLIED, first.codes
    nodo = graph.node("V3Assertion", "assertion_id", "assertion:e2e01")
    assert nodo is not None and nodo["status"] == "ASSERTED"
    despues_de_la_primera = graph.snapshot_bytes()

    # Segunda pasada: la idempotency_key ya esta registrada, no se reescribe.
    second = _writer_real(graph.driver, keys).write(plan, apply_request(plan))
    assert second.outcome in (OUTCOME_APPLIED,), second.codes
    assert graph.snapshot_bytes() == despues_de_la_primera, (
        "la segunda aplicacion del MISMO plan cambio el grafo"
    )


def _writer_real(driver, keys=None) -> GraphWriter:
    """Writer para los planes construidos con el utillaje de writer-real."""
    from test_knowledge_v3_writer_neo4j_real import writer as _w

    return _w(driver, keys=keys)


# ==========================================================================
# E2E-12 — la correccion del operador llega al GRAFO
# ==========================================================================
def test_e2e_12_correccion_propagada_al_grafo_real(graph: GraphProbe):
    """Corregir no es borrar: la version anterior sigue en el grafo, marcada.

    E2E-12 en el arbol sin Docker demuestra que la retractacion desaparece del
    SNAPSHOT que veria la siguiente fuente. Lo que no podia demostrar es que el
    grafo se entere. Eso es lo que se comprueba aqui.
    """
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    graph.seed_assertion("assertion:vieja", version=1, state_hash=HASH_B["value"])

    plan = make_plan(
        [
            create_assertion("op:0001", "assertion:nueva", "entity:origen", "entity:destino"),
            supersede_assertion("op:0002", "assertion:vieja", successor="assertion:nueva"),
        ]
    )
    result = _writer_real(graph.driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes

    vieja = graph.node("V3Assertion", "assertion_id", "assertion:vieja")
    nueva = graph.node("V3Assertion", "assertion_id", "assertion:nueva")

    # La correccion surtio efecto...
    assert vieja is not None, "la version anterior fue BORRADA: eso no es corregir"
    assert vieja["status"] == "SUPERSEDED"
    assert vieja.get("valid_to"), "se cerro la vigencia sin fecha de cierre"
    assert vieja.get("superseded_by") == "assertion:nueva"
    # ...y la nueva ocupa su lugar, viva.
    assert nueva is not None and nueva["status"] == "ASSERTED"


def test_e2e_12_una_correccion_repetida_no_duplica_nada(graph: GraphProbe):
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    graph.seed_assertion("assertion:vieja", version=1, state_hash=HASH_B["value"])
    plan = make_plan(
        [
            create_assertion("op:0001", "assertion:nueva", "entity:origen", "entity:destino"),
            supersede_assertion("op:0002", "assertion:vieja", successor="assertion:nueva"),
        ]
    )
    keys = InMemoryAppliedKeys()
    _writer_real(graph.driver, keys).write(plan, apply_request(plan))
    huella = graph.snapshot_bytes()

    _writer_real(graph.driver, keys).write(plan, apply_request(plan))

    assert graph.snapshot_bytes() == huella


# ==========================================================================
# CESACION contra grafo real
# ==========================================================================
class TestCesacionContraGrafoReal:
    """`ya no lidera` cierra la vigencia anterior; `no dejo de` no cierra nada.

    El escenario del encargo (Toturi / Clan del Leon) se materializa con las
    entidades del utillaje de writer-real: lo que se prueba es el EFECTO EN EL
    GRAFO de una supersesion, no los nombres.
    """

    def _seed(self, graph: GraphProbe) -> None:
        graph.seed_entity("entity:toturi", version=1, state_hash=HASH_A["value"])
        graph.seed_entity("entity:clan-leon", version=1, state_hash=HASH_B["value"])
        graph.seed_assertion("assertion:lidera", version=1, state_hash=HASH_B["value"])

    def test_la_cesacion_cierra_la_vigencia_y_conserva_la_historia(self, graph: GraphProbe):
        self._seed(graph)
        plan = make_plan(
            [
                create_assertion(
                    "op:0001", "assertion:ya-no-lidera", "entity:toturi", "entity:clan-leon"
                ),
                supersede_assertion(
                    "op:0002", "assertion:lidera", successor="assertion:ya-no-lidera"
                ),
            ]
        )

        result = _writer_real(graph.driver).write(plan, apply_request(plan))

        assert result.outcome == OUTCOME_APPLIED, result.codes
        anterior = graph.node("V3Assertion", "assertion_id", "assertion:lidera")
        assert anterior["status"] == "SUPERSEDED"
        assert anterior["valid_to"], "una cesacion sin fecha de cierre no cierra nada"
        assert anterior.get("reason_code"), "R1 del writer: no se cierra sin motivo"
        # La historia se conserva: el nodo anterior sigue ahi con su evidencia.
        assert anterior["assertion_id"] == "assertion:lidera"

    def test_la_cesacion_es_idempotente(self, graph: GraphProbe):
        self._seed(graph)
        plan = make_plan(
            [supersede_assertion("op:0001", "assertion:lidera", successor="assertion:x")]
        )
        keys = InMemoryAppliedKeys()
        _writer_real(graph.driver, keys).write(plan, apply_request(plan))
        huella = graph.snapshot_bytes()

        _writer_real(graph.driver, keys).write(plan, apply_request(plan))

        assert graph.snapshot_bytes() == huella

    def test_un_hash_distinto_bloquea_el_cierre(self, graph: GraphProbe):
        """Concurrencia optimista de verdad: si otro cambio la afirmacion, no se cierra."""
        self._seed(graph)
        plan = make_plan(
            [
                supersede_assertion(
                    "op:0001",
                    "assertion:lidera",
                    successor="assertion:x",
                    state_hash={"algorithm": "sha256", "value": "f" * 64},
                )
            ]
        )
        antes = graph.snapshot_bytes()

        result = _writer_real(graph.driver).write(plan, apply_request(plan))

        assert result.outcome == OUTCOME_ABORTED
        assert codes.EXEC_HASH_MISMATCH in result.codes
        assert graph.snapshot_bytes() == antes, "un cierre bloqueado dejo rastro"


# ==========================================================================
# La negacion de cesacion NO cierra nada — verificable desde el motor
# ==========================================================================
class TestNegacionDeCesacionNoCierra:
    """`no dejo de liderar` no es una cesacion: 0 cierres, 0 supersesiones.

    Se comprueba sobre el PLAN, que es donde se decidiria el cierre. Si el plan
    no lleva SUPERSEDE_ASSERTION, no hay nada que pueda cerrar una vigencia en
    ningun grafo.
    """

    def test_el_plan_de_una_negacion_de_cesacion_no_lleva_supersesion(self):
        _plan, run, _p = _plan_or_none("p7-neg-ces", T_NEG_CESACION)
        ops = [] if run.plan is None else [
            o["operation_type"] for o in run.plan.mutation_operations
        ]
        assert "SUPERSEDE_ASSERTION" not in ops, ops

    def test_el_plan_de_una_cesacion_si_supersede(self):
        """REGRESION F7-1: una cesacion anclada cierra la vigencia anterior."""
        _plan, run, _p = _plan_or_none("p7-ces", T_CESACION)
        ops = [] if run.plan is None else [
            o["operation_type"] for o in run.plan.mutation_operations
        ]
        assert "SUPERSEDE_ASSERTION" in ops, ops


def _plan_or_none(source_id: str, text: str):
    gold = gold_dev()
    entities = snapshot_entities(gold)
    pipeline = KnowledgePipeline(base_config(gold, writer_driver=None))
    run = pipeline.run([raw_case(source_id, text)], catalog_entities=entities).runs[0]
    return (run.plan.to_dict() if run.plan else None), run, pipeline

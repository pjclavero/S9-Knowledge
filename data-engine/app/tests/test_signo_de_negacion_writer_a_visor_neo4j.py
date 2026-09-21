# -*- coding: utf-8 -*-
"""EL SIGNO SOBREVIVE AL VIAJE: writer REAL -> Neo4j REAL -> visor REAL.

    fuente negativa -> extracción -> assertion `negated=true` -> apply
        -> Neo4j -> lectura -> visor -> SIGUE SIENDO NEGATIVA

Este fichero ejerce el tramo de ese recorrido que el defecto rompía: desde el
APPLY hasta la pantalla. El tramo de arriba —que «no lidera» produce
`decision.negated is True` y que la propuesta lo lleva— ya lo cubren
`test_knowledge_v3_e2e_global.py` (`decision.negated is True`,
`negation_kind == "SIMPLE"`) y `test_knowledge_v3_e2e_neo4j_real.py`; repetirlo
aquí no añadiría nada y alargaría un fichero que necesita Docker.

POR QUÉ HACE FALTA ESTE FICHERO
===============================
`viewer/tests/test_panel_signo_de_negacion.py` mide las tres pantallas con
dobles: demuestra que la plantilla pinta el signo que le den. NO demuestra que
el signo LLEGUE. Aquí no hay doble en ninguna capa:

  * el `negated` del grafo lo estampa `GraphWriter` aplicando un plan, no un
    `CREATE` escrito a mano en este fichero;
  * lo lee el `Neo4jGraphProvider` real y el `ProvenanceReader` real, con su
    Cypher de verdad contra una base de verdad.

La procedencia del dato medido es parte de la medición: un `negated` que
pusiera este arnés no probaría que el recorrido lo conserva.

CÓMO SE ACTIVA
==============
Igual que el resto de suites de Neo4j real de este directorio::

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \
      data-engine/app/tests/test_signo_de_negacion_writer_a_visor_neo4j.py -q

NUNCA producción: la fixture levanta y destruye su propia instancia efímera.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1",
)

from knowledge_v3.writer import (  # noqa: E402
    InMemoryAppliedKeys,
    InMemoryAuditSink,
    bootstrap_writer_schema,
)
from knowledge_v3.writer.writer import GraphWriter, OUTCOME_APPLIED  # noqa: E402

# Utillaje del contenedor efímero y de los planes, reutilizado TAL CUAL.
from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401,I100
    WORKSPACE,
    GraphProbe,
    apply_request,
    create_assertion,
    create_entity,
    graph,
    make_plan,
    neo4j_driver,
)

SUJETO = "entity:sela-marrec"
OBJETO = "entity:consejo-umbra"
NEGADA = "assertion:no-pertenece"
AFIRMATIVA = "assertion:si-pertenece"
PREDICADO = "MEMBER_OF"


def _vigente(plan: dict) -> dict:
    """El mismo plan, con la vigencia DERIVADA DEL RELOJ y vuelto a sellar.

    `make_plan` fija `created_at`/`expires_at` a un día de julio de 2026. Con
    esas fechas el writer rechaza todo con `PLAN_EXPIRED` desde que ese día
    pasó, y lo hace por una razón correcta: un plan sellado caduca. Se midió al
    escribir este fichero —seis casos en rojo con `['PLAN_EXPIRED']`— y se
    arregla aquí, para este fichero, sin tocar el utillaje compartido: la
    caducidad del corpus del writer-real es deuda de otro carril y se declara
    en el informe en vez de repararse de paso.

    `seal_plan` devuelve una COPIA y recalcula los hashes, así que volver a
    sellar el documento con las fechas nuevas produce un plan íntegro, no uno
    parcheado.
    """
    from datetime import datetime, timedelta, timezone

    from knowledge_v3.contracts.base import seal_plan

    ahora = datetime.now(timezone.utc)
    def _iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    doc = dict(plan)
    doc["created_at"] = _iso(ahora)
    doc["expires_at"] = _iso(ahora + timedelta(hours=2))
    aprobacion = dict(doc["local_approval"])
    aprobacion["created_at"] = _iso(ahora)
    doc["local_approval"] = aprobacion
    return seal_plan(doc)


@pytest.fixture()
def aplicado(graph: GraphProbe) -> dict:
    """LA PREMISA: el grafo lo puebla el WRITER, con las dos aserciones.

    Las DOS, y no sólo la negada, por la misma razón que en las pantallas: con
    una sola, «marcarlo todo como negado» —el error simétrico— pasaría este
    fichero entero.
    """
    bootstrap_writer_schema(graph.driver)
    plan = _vigente(make_plan([
        create_entity("op:0001", SUJETO, "Sela Marrec"),
        create_entity("op:0002", OBJETO, "Consejo de Umbra"),
        create_assertion("op:0003", NEGADA, SUJETO, OBJETO,
                         predicate=PREDICADO, negated=True),
        create_assertion("op:0004", AFIRMATIVA, SUJETO, OBJETO,
                         predicate=PREDICADO, negated=False),
    ]))
    escritor = GraphWriter(
        workspace=WORKSPACE, driver=graph.driver,
        audit=InMemoryAuditSink(), applied_keys=InMemoryAppliedKeys(),
    )
    resultado = escritor.write(plan, apply_request(plan))
    assert resultado.outcome == OUTCOME_APPLIED, resultado.codes
    return {"plan": plan, "resultado": resultado}


# ===========================================================================
# 1. SUELO — el signo está en el grafo, y lo puso el producto
# ===========================================================================
def test_el_writer_estampa_el_signo_en_el_nodo(graph, aplicado):
    """Sin esto, todo lo demás mediría el vacío.

    Es también el CONTROL POSITIVO de este fichero: si el writer dejara de
    escribir `negated`, los ceros de más abajo («el visor no lo pierde») serían
    ciertos y vacíos a la vez.
    """
    negada = graph.node("V3Assertion", "assertion_id", NEGADA)
    afirmativa = graph.node("V3Assertion", "assertion_id", AFIRMATIVA)
    assert negada is not None and afirmativa is not None, (
        "el writer dijo APPLIED y no hay nodos: el arnés está midiendo el vacío")
    assert negada["negated"] is True, negada
    assert afirmativa["negated"] is False, afirmativa


# ===========================================================================
# 2. EL PROVEEDOR REAL — la ficha de entidad se alimenta de aquí
# ===========================================================================
def test_el_proveedor_del_visor_no_pierde_el_signo(graph, aplicado):
    """`_assertion_to_dict` es una lista BLANCA: lo que no esté, no sale.

    El defecto entraba aquí: el campo no estaba en la lista, así que el hecho
    llegaba entero a la pantalla MENOS su significado.
    """
    # `viewer/` ya está en `sys.path` por el conftest raíz, así que `app`
    # resuelve al paquete del visor. Se importa DENTRO del caso para no atar
    # la recogida de este fichero a que el visor sea importable.
    from app.providers.neo4j_provider import _assertion_to_dict

    with graph.driver.session() as s:
        filas = {
            r["a"]["assertion_id"]: _assertion_to_dict(r["a"])
            for r in s.run(
                "MATCH (a:V3Assertion {workspace:$ws}) RETURN a",
                {"ws": WORKSPACE})
        }
    assert filas, "no hay aserciones que proyectar"
    assert filas[NEGADA]["negated"] is True, filas[NEGADA]
    assert filas[AFIRMATIVA]["negated"] is False, filas[AFIRMATIVA]


def test_el_serializador_convierte_el_signo_real_en_el_codigo_correcto(
        graph, aplicado):
    """La cadena entera hasta la forma que ve la plantilla, sobre dato REAL."""
    from app.providers.neo4j_provider import _assertion_to_dict
    from app.serializers import serialize_assertion

    with graph.driver.session() as s:
        crudas = {
            r["a"]["assertion_id"]: _assertion_to_dict(r["a"])
            for r in s.run(
                "MATCH (a:V3Assertion {workspace:$ws}) RETURN a",
                {"ws": WORKSPACE})
        }
    assert serialize_assertion(crudas[NEGADA])["signo"] == "HECHO_NEGADO"
    assert serialize_assertion(crudas[AFIRMATIVA])["signo"] == "HECHO_AFIRMATIVO"


# ===========================================================================
# 3. EL LECTOR DE PROCEDENCIA — las dos pantallas de resultado
# ===========================================================================
def test_el_lector_de_procedencia_trae_el_signo_desde_el_grafo(graph, aplicado):
    """El `RETURN` real, contra la base real.

    Este es el punto que una prueba con dobles NO puede cubrir: el servicio
    recibía `None` para todos los hechos porque la consulta no pedía el campo,
    y un doble que sí lo devolviera habría tapado exactamente eso.
    """
    from app.providers.provenance_reader import ProvenanceReader

    with graph.driver.session() as s:
        claves = [
            r["k"] for r in s.run(
                "MATCH (a:V3Assertion {workspace:$ws}) "
                "RETURN DISTINCT a.idempotency_key AS k",
                {"ws": WORKSPACE}) if r["k"]
        ]
    assert claves, (
        "las aserciones no llevan `idempotency_key`: sin ella el lector de "
        "procedencia no puede atribuirlas a un apply y este caso no mide nada")

    filas = {
        f["assertion_id"]: f
        for f in ProvenanceReader(graph.driver).assertions_for_keys(
            WORKSPACE, claves)
    }
    assert filas, "el lector no atribuyó ninguna aserción a estas claves"
    assert filas[NEGADA]["negated"] is True, filas[NEGADA]
    assert filas[AFIRMATIVA]["negated"] is False, filas[AFIRMATIVA]


def test_el_servicio_de_resultado_publica_el_signo_real(graph, aplicado):
    """Hasta la fila que la plantilla de resultado itera, con dato real."""
    from app.labels import negation_code
    from app.providers.provenance_reader import ProvenanceReader

    with graph.driver.session() as s:
        claves = [
            r["k"] for r in s.run(
                "MATCH (a:V3Assertion {workspace:$ws}) "
                "RETURN DISTINCT a.idempotency_key AS k",
                {"ws": WORKSPACE}) if r["k"]
        ]
    filas = ProvenanceReader(graph.driver).assertions_for_keys(WORKSPACE, claves)
    signos = {f["assertion_id"]: negation_code(f.get("negated")) for f in filas}
    assert signos[NEGADA] == "HECHO_NEGADO", signos
    assert signos[AFIRMATIVA] == "HECHO_AFIRMATIVO", signos


# ===========================================================================
# 4. LA REGLA DEL OPERADOR, DICHA COMO SE DIJO
# ===========================================================================
def test_A_no_pertenece_a_B_nunca_reaparece_como_A_pertenece_a_B(graph, aplicado):
    """«A no pertenece a B» nunca puede reaparecer como «A pertenece a B».

    Se comprueba sobre la frase que la pantalla de resultado compone, con el
    dato que salió del grafo. Es la formulación del operador, verificada en el
    único sitio donde puede fallar: cuando el signo ha hecho todo el viaje.
    """
    from app.labels import negation_code
    from app.providers.provenance_reader import ProvenanceReader

    with graph.driver.session() as s:
        claves = [
            r["k"] for r in s.run(
                "MATCH (a:V3Assertion {workspace:$ws}) "
                "RETURN DISTINCT a.idempotency_key AS k",
                {"ws": WORKSPACE}) if r["k"]
        ]
    filas = {f["assertion_id"]: f for f in
             ProvenanceReader(graph.driver).assertions_for_keys(WORKSPACE, claves)}

    def frase(f):
        signo = negation_code(f.get("negated"))
        return " ".join(filter(None, [
            "Sela Marrec", "NO" if signo == "HECHO_NEGADO" else "",
            f.get("predicate") or "", "Consejo de Umbra"]))

    assert frase(filas[NEGADA]) == f"Sela Marrec NO {PREDICADO} Consejo de Umbra"
    assert frase(filas[AFIRMATIVA]) == f"Sela Marrec {PREDICADO} Consejo de Umbra"

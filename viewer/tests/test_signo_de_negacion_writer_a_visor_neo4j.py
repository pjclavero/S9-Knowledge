# -*- coding: utf-8 -*-
"""EL SIGNO SOBREVIVE AL VIAJE: writer REAL -> Neo4j REAL -> visor REAL.

    fuente negativa -> extracción -> assertion `negated=true` -> apply
        -> Neo4j -> lectura -> visor -> SIGUE SIENDO NEGATIVA

Este fichero ejerce el tramo de ese recorrido que el defecto rompía: desde el
APPLY hasta lo que la pantalla recibe. El tramo de arriba —que «no lidera»
produce `decision.negated is True` y que la propuesta lo lleva— ya lo cubren
`test_knowledge_v3_e2e_global.py` (`decision.negated is True`,
`negation_kind == "SIMPLE"`) y `test_knowledge_v3_e2e_neo4j_real.py`.

POR QUÉ HACE FALTA ESTE FICHERO
===============================
`viewer/tests/test_panel_signo_de_negacion.py` mide las tres pantallas con
dobles: demuestra que la plantilla pinta el signo que le den. NO demuestra que
el signo LLEGUE. Aquí no hay doble en ninguna capa:

  * el `negated` del grafo lo estampa `GraphWriter` aplicando un plan sellado,
    no un `CREATE` escrito a mano en este fichero;
  * lo leen el `Neo4jGraphProvider` y el `ProvenanceReader` REALES, con su
    Cypher de verdad contra una base de verdad.

La procedencia del dato medido es parte de la medición: un `negated` que
pusiera este arnés no probaría que el recorrido lo conserva.

POR QUÉ VIVE EN `viewer/tests` Y NO EN `data-engine/app/tests`
==============================================================
Estuvo allí, y CI lo tumbó con la razón exacta::

    ModuleNotFoundError: No module named 'pydantic_settings'

El job `Data Engine Tests` instala `data-engine/requirements.txt` y NO el del
visor, así que cinco de sus seis casos —los que importan `app.*`— morían al
importar. El caso que no toca el visor pasaba, que es lo que hace este fallo
instructivo: la mitad verde disimulaba la mitad rota.

El sitio correcto es el paso `Authz integration (Neo4j efímero)`, que es el
ÚNICO que tiene a la vez las dos cosas que este fichero necesita: las
dependencias del visor y un Neo4j efímero. Por eso se activa con la familia
`NEO4J_TEST_URI` / `NEO4J_TEST_PASSWORD` —la que ese paso define— y no con
`S9K_WRITER_NEO4J_REAL`, y por eso está añadido a su invocación: fuera de ella
saldría SKIPPED en `test-viewer` con rc=0 y el job verde, y un skip verde
equivale a no tener la prueba.

NUNCA producción: sólo instancia efímera y local.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest

URI = os.environ.get("NEO4J_TEST_URI")
USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not URI or not PASSWORD,
    reason="sin Neo4j efimero (define NEO4J_TEST_URI y NEO4J_TEST_PASSWORD)",
)

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

#: Lista BLANCA. Esta suite BORRA nodos de su workspace; apuntarla a produccion
#: no puede depender de que nadie se equivoque de variable.
ANFITRIONES_EFIMEROS = frozenset({"localhost", "127.0.0.1", "::1", "neo4j"})

#: Workspace PROPIO, disjunto del de las demas suites que comparten instancia.
#:
#: SIN dos puntos. El contrato congelado lo exige
#: (`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`) y un `juego:signo-negacion` hacia que
#: el writer devolviera `REJECTED ['PLAN_CONTRACT_INVALID']` -- seis casos en
#: rojo por el NOMBRE, no por el signo. Se midio antes de subirlo.
WS = "signo-de-negacion"

SUJETO = "entity:signo-sela-marrec"
OBJETO = "entity:signo-consejo-umbra"
NEGADA = "assertion:signo-no-pertenece"
AFIRMATIVA = "assertion:signo-si-pertenece"
PREDICADO = "MEMBER_OF"


def _exigir_efimera(uri: str) -> None:
    host = (urlparse(uri).hostname or "").strip().lower()
    if host not in ANFITRIONES_EFIMEROS:
        raise RuntimeError(
            f"NEO4J_TEST_URI apunta a {host!r}, que no es una base efimera. "
            f"Anfitriones admitidos: {sorted(ANFITRIONES_EFIMEROS)}."
        )


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


#: La vigencia se DERIVA DEL RELOJ. Fijarla a mano arma una bomba de reloj que
#: estalla el dia que `expires_at` pasa y se atribuye al entorno: se midio en
#: el utillaje de writer-real, cuyo corpus caduca el 2026-07-27 y desde
#: entonces devuelve `PLAN_EXPIRED` para todo.
AHORA_DT = datetime.now(timezone.utc)
AHORA = _iso(AHORA_DT)


def _decision(decision_id: str, *, negated: bool) -> dict:
    return {
        "decision_id": decision_id,
        "claim_id": f"claim:{decision_id}",
        "decision": "ACCEPT",
        "predicate": PREDICADO,
        "direction": "SUBJECT_TO_OBJECT",
        "subject_entity_id": SUJETO,
        "object_entity_id": OBJETO,
        "epistemic_status": "ASSERTED",
        "negated": negated,
        "confidence": 0.81,
        "reason_codes": ["LOCAL_APPROVED"],
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
    }


def _op(op_id, tipo, decision_id, *, target=None, assertion=None, payload=None,
        clave_idem) -> dict:
    return {
        "operation_id": op_id,
        "operation_type": tipo,
        "decision_id": decision_id,
        "target_entity_id": target,
        "assertion_id": assertion,
        "payload": payload or {},
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
        # Clave DISTINTA por operacion: la de idempotencia es lo que atribuye
        # cada escritura a su apply, y repetirla haria que el lector de
        # procedencia no pudiera separar una asercion de otra.
        "idempotency_key": clave_idem,
        "expected_state": "WOULD_CREATE",
        "expected_version": None,
        "expected_hash": None,
    }


def _plan() -> dict:
    """UN plan V3 sellado por el producto (`seal_plan`), no un CREATE a mano.

    Lleva las DOS aserciones —negada y afirmativa— y no sólo la negada: con una
    sola, «marcarlo todo como negado» —el error simétrico— pasaría este fichero
    entero.
    """
    from knowledge_v3.contracts.base import seal_plan

    doc = {
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        "contract_version": "1.0.0",
        "workspace": WS,
        "source_asset_id": "asset:signo-de-negacion",
        "source_hash": {"algorithm": "sha256", "value": "d" * 64},
        "provider_trace": [{
            "step": "engine.plan", "provider": "local",
            "name": "s9k.knowledge_v3", "version": "3.0.0", "model": None,
            "produced": ["decisions", "mutation_operations"],
        }],
        "produced_by_step": "engine.plan",
        "plan_id": "plan:signo:" + uuid.uuid4().hex[:8],
        "plan_hash": {"algorithm": "sha256", "value": "0" * 64},
        "snapshot_id": "snapshot:sha256:" + "e" * 64,
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "game_profile": "generic",
        "collection_id": "collection:" + WS,
        "created_at": AHORA,
        "expires_at": _iso(AHORA_DT + timedelta(hours=2)),
        "decisions": [
            _decision("decision:negada", negated=True),
            _decision("decision:afirmativa", negated=False),
        ],
        "mutation_operations": [
            _op("op:0001", "CREATE_ENTITY", "decision:negada", target=SUJETO,
                payload={"entity_type": "Character", "canonical_name": "Sela Marrec"},
                clave_idem="idem:sha256:" + "1" * 64),
            _op("op:0002", "CREATE_ENTITY", "decision:negada", target=OBJETO,
                payload={"entity_type": "Faction", "canonical_name": "Consejo de Umbra"},
                clave_idem="idem:sha256:" + "2" * 64),
            _op("op:0003", "CREATE_ASSERTION", "decision:negada", assertion=NEGADA,
                payload={"subject_entity_id": SUJETO, "object_entity_id": OBJETO,
                         "predicate": PREDICADO, "negated": True,
                         "status": "ASSERTED"},
                clave_idem="idem:sha256:" + "3" * 64),
            _op("op:0004", "CREATE_ASSERTION", "decision:afirmativa",
                assertion=AFIRMATIVA,
                payload={"subject_entity_id": SUJETO, "object_entity_id": OBJETO,
                         "predicate": PREDICADO, "negated": False,
                         "status": "ASSERTED"},
                clave_idem="idem:sha256:" + "4" * 64),
        ],
        "local_approval": {
            "approved": True,
            "decision_hash": {"algorithm": "sha256", "value": "0" * 64},
            "validator_chain": [
                {"validator": "structural", "version": "3.0.0", "result": "PASS"},
                {"validator": "semantic", "version": "3.0.0", "result": "PASS"},
            ],
            "created_at": AHORA,
            "approved_by": {"provider": "local", "name": "s9k.engine.local",
                            "version": "3.0.0"},
        },
    }
    return seal_plan(doc)


@pytest.fixture(scope="module")
def driver():
    from neo4j import GraphDatabase

    _exigir_efimera(URI)
    drv = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    drv.verify_connectivity()
    yield drv
    # Se lleva SOLO lo suyo: su propio workspace.
    with drv.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    drv.close()


@pytest.fixture(scope="module")
def aplicado(driver):
    """LA PREMISA: el grafo lo puebla el WRITER REAL, no este fichero."""
    from knowledge_v3.writer import (
        InMemoryAppliedKeys,
        InMemoryAuditSink,
        OperatorRequest,
        bootstrap_writer_schema,
    )
    from knowledge_v3.writer.writer import GraphWriter

    with driver.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    bootstrap_writer_schema(driver)

    plan = _plan()
    escritor = GraphWriter(
        workspace=WS, driver=driver,
        audit=InMemoryAuditSink(), applied_keys=InMemoryAppliedKeys(),
    )
    resultado = escritor.write(plan, OperatorRequest(
        apply=True, operator_id="signo-negacion", workspace=WS,
        expected_plan_hash=plan["plan_hash"]["value"], max_operations=50,
        current_snapshot_id=plan["snapshot_id"],
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
    ))
    assert resultado.outcome == "APPLIED", (
        f"el plan no se aplico: {resultado.outcome} {getattr(resultado, 'codes', None)}")
    return resultado


def _aserciones_crudas(driver) -> dict:
    from app.providers.neo4j_provider import _assertion_to_dict

    with driver.session() as s:
        return {
            r["a"]["assertion_id"]: _assertion_to_dict(r["a"])
            for r in s.run("MATCH (a:V3Assertion {workspace:$ws}) RETURN a",
                           {"ws": WS})
        }


def _claves(driver) -> list:
    with driver.session() as s:
        return [r["k"] for r in s.run(
            "MATCH (a:V3Assertion {workspace:$ws}) "
            "RETURN DISTINCT a.idempotency_key AS k", {"ws": WS}) if r["k"]]


# ===========================================================================
# 1. SUELO — el signo está en el grafo, y lo puso el producto
# ===========================================================================
def test_el_writer_estampa_el_signo_en_el_nodo(driver, aplicado):
    """Sin esto, todo lo demás mediría el vacío.

    Es además el CONTROL POSITIVO de este fichero: si el writer dejara de
    escribir `negated`, los ceros de más abajo («el visor no lo pierde») serían
    ciertos y vacíos a la vez.
    """
    with driver.session() as s:
        filas = {
            r["id"]: r["neg"] for r in s.run(
                "MATCH (a:V3Assertion {workspace:$ws}) "
                "RETURN a.assertion_id AS id, a.negated AS neg", {"ws": WS})
        }
    assert filas, "el writer dijo APPLIED y no hay aserciones: se mide el vacío"
    assert filas[NEGADA] is True, filas
    assert filas[AFIRMATIVA] is False, filas


# ===========================================================================
# 2. EL PROVEEDOR REAL — de aquí come la ficha de entidad
# ===========================================================================
def test_el_proveedor_del_visor_no_pierde_el_signo(driver, aplicado):
    """`_assertion_to_dict` es una lista BLANCA: lo que no esté, no sale.

    El defecto entraba aquí: el campo no estaba en la lista, así que el hecho
    llegaba entero a la pantalla MENOS su significado.
    """
    filas = _aserciones_crudas(driver)
    assert filas, "no hay aserciones que proyectar"
    assert filas[NEGADA]["negated"] is True, filas[NEGADA]
    assert filas[AFIRMATIVA]["negated"] is False, filas[AFIRMATIVA]


def test_el_serializador_convierte_el_signo_real_en_el_codigo_correcto(
        driver, aplicado):
    """La cadena entera hasta la forma que ve la plantilla, sobre dato REAL."""
    from app.serializers import serialize_assertion

    crudas = _aserciones_crudas(driver)
    assert serialize_assertion(crudas[NEGADA])["signo"] == "HECHO_NEGADO"
    assert serialize_assertion(crudas[AFIRMATIVA])["signo"] == "HECHO_AFIRMATIVO"


# ===========================================================================
# 3. EL LECTOR DE PROCEDENCIA — las dos pantallas de resultado
# ===========================================================================
def test_el_lector_de_procedencia_trae_el_signo_desde_el_grafo(driver, aplicado):
    """El `RETURN` real, contra la base real.

    Éste es el punto que una prueba con dobles NO puede cubrir: el servicio
    recibía `None` para todos los hechos porque la consulta no pedía el campo,
    y un doble que sí lo devolviera habría tapado exactamente eso.
    """
    from app.providers.provenance_reader import ProvenanceReader

    claves = _claves(driver)
    assert claves, (
        "las aserciones no llevan `idempotency_key`: sin ella el lector no "
        "puede atribuirlas a un apply y este caso no mide nada")

    filas = {f["assertion_id"]: f
             for f in ProvenanceReader(driver).assertions_for_keys(WS, claves)}
    assert filas, "el lector no atribuyó ninguna aserción a estas claves"
    assert filas[NEGADA]["negated"] is True, filas[NEGADA]
    assert filas[AFIRMATIVA]["negated"] is False, filas[AFIRMATIVA]


def test_el_servicio_de_resultado_publica_el_signo_real(driver, aplicado):
    """Hasta el CÓDIGO que la plantilla de resultado itera, con dato real."""
    from app.labels import negation_code
    from app.providers.provenance_reader import ProvenanceReader

    filas = ProvenanceReader(driver).assertions_for_keys(WS, _claves(driver))
    signos = {f["assertion_id"]: negation_code(f.get("negated")) for f in filas}
    assert signos[NEGADA] == "HECHO_NEGADO", signos
    assert signos[AFIRMATIVA] == "HECHO_AFIRMATIVO", signos


# ===========================================================================
# 4. LA REGLA DEL OPERADOR, DICHA COMO SE DIJO
# ===========================================================================
def test_A_no_pertenece_a_B_nunca_reaparece_como_A_pertenece_a_B(driver, aplicado):
    """«A no pertenece a B» nunca puede reaparecer como «A pertenece a B».

    QUÉ AÑADE, Y QUÉ NO. La frase la compone ESTE arnés, no el producto: la
    plantilla vive en `resultado.html` y aquí no se renderiza nada. Así que
    esto NO es un testigo de la pantalla y, como comprobación, es REDUNDANTE
    con los dos casos anteriores —mide el mismo `negation_code` sobre las
    mismas filas—.

    Se queda por una razón distinta de medir: deja la regla del operador
    escrita en forma ejecutable y junto al dato real, de modo que quien toque
    esta zona lea la propiedad antes que la implementación. Quien comprueba que
    el «NO» llega al HTML es `viewer/tests/test_panel_signo_de_negacion.py`
    (con dobles, pero pidiendo la página).

    Dicho sin adornos: no existe un solo test que recorra texto crudo -> HTML.
    La propiedad se sostiene por COMPOSICIÓN de tres ficheros —extracción
    (`test_knowledge_v3_e2e_global.py`), apply-a-lectura (este) y
    lectura-a-pantalla (aquél)—, y conviene decirlo porque leído del tirón
    parece que hay un E2E que no hay.
    """
    from app.labels import negation_code
    from app.providers.provenance_reader import ProvenanceReader

    filas = {f["assertion_id"]: f for f in
             ProvenanceReader(driver).assertions_for_keys(WS, _claves(driver))}

    def frase(f):
        signo = negation_code(f.get("negated"))
        return " ".join(filter(None, [
            "Sela Marrec", "NO" if signo == "HECHO_NEGADO" else "",
            f.get("predicate") or "", "Consejo de Umbra"]))

    assert frase(filas[NEGADA]) == f"Sela Marrec NO {PREDICADO} Consejo de Umbra"
    assert frase(filas[AFIRMATIVA]) == f"Sela Marrec {PREDICADO} Consejo de Umbra"

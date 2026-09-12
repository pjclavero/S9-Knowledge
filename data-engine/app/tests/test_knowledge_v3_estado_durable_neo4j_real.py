# -*- coding: utf-8 -*-
"""Estado durable e idempotencia REAL, contra un Neo4j efimero.

QUE PROPIEDAD SE FIJA AQUI
--------------------------
Una entidad que crea el propio producto sale del `CREATE` con TODO el estado
durable que el planificador y el writer le van a exigir despues -- `version` y
un `state_hash` que DESCRIBE lo persistido -- y aplicar dos veces lo mismo deja
el grafo EXACTAMENTE igual.

El defecto que motiva el fichero se midio primero en rojo con el mando del
operador (`pipeline.ingest_cli`) sobre un Neo4j real: la segunda ingesta de la
misma fuente moria con

    EnginePlanError: el plan construido no valida contra el contrato congelado:
    op:...:project modifica algo existente sin expected_version/expected_hash

porque el writer creaba las entidades con `version 0` y `state_hash NULL`. La
carencia declarada (`ENTIDAD_SIN_STATE_HASH`, docs/v3/55 §6.1) predecia el
hecho pero afirmaba que "el carril lo rodea no proyectando": falso en la
SEGUNDA ingesta, donde la entidad ya existe y el planificador si proyecta.

Estas pruebas cubren las dos mitades y, sobre todo, el CONTROL NEGATIVO: un
cambio real de estado tiene que seguir tumbando la concurrencia optimista. Sin
esa mitad, "las tres primeras pasan" no distingue un arreglo de un hash que
siempre coincide.
"""
from __future__ import annotations

import os
from typing import Any

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1",
)

from knowledge_v3.writer import codes  # noqa: E402
from knowledge_v3.writer.state import (  # noqa: E402
    hash_doc,
    state_hash_value,
)
from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: E402

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401,I100
    GraphProbe,
    apply_request,
    create_assertion,
    create_entity,
    link_existing,
    make_plan,
    neo4j_driver as neo4j_driver_efimero,
    writer as make_writer,
)

WS = "ws-writer-real"

#: Neo4j REAL ya en marcha al que apuntar en vez de levantar otro.
#: En una maquina con varios Neo4j efimeros a la vez, el contenedor propio no
#: llega a aceptar conexiones dentro del plazo del arranque y la suite da un
#: rojo que NO es del producto. Apuntando a una base real ya viva se mide lo
#: mismo -- cada prueba la deja vacia antes y despues -- sin competir por la
#: memoria. Sin estas variables, se levanta el efimero de siempre.
URI_REUTILIZABLE = os.environ.get("S9K_4A_NEO4J_URI", "").strip()
PASS_REUTILIZABLE = os.environ.get("S9K_4A_NEO4J_PASSWORD_FILE", "").strip()


@pytest.fixture(scope="session")
def neo4j_driver(request):
    if not (URI_REUTILIZABLE and PASS_REUTILIZABLE):
        yield request.getfixturevalue("neo4j_driver_efimero")
        return
    import pathlib

    import neo4j as _neo4j

    from knowledge_v3.writer.schema import bootstrap_writer_schema

    clave = pathlib.Path(PASS_REUTILIZABLE).read_text().strip()
    driver = _neo4j.GraphDatabase.driver(URI_REUTILIZABLE, auth=("neo4j", clave))
    driver.verify_connectivity()
    bootstrap_writer_schema(driver)
    try:
        yield driver
    finally:
        driver.close()


def _props(probe: GraphProbe, entity_id: str) -> dict[str, Any]:
    filas = probe.run(
        "MATCH (n:V3Entity {entity_id: $id}) RETURN properties(n) AS props",
        {"id": entity_id},
    )
    assert filas, f"conjunto vacio: {entity_id} no esta en el grafo"
    return dict(filas[0]["props"])


def _huella(probe: GraphProbe) -> str:
    """Huella del CONTENIDO del grafo, sin `elementId`.

    El `elementId` cambia entre bases y no es identidad durable: compararlo
    daria "distinto" en grafos identicos, y mirar a ojo daria "igual" en
    grafos distintos. La identidad de producto es `(workspace, entity_id)`.
    """
    import hashlib
    import json

    nodos = probe.run("MATCH (n) RETURN labels(n) AS l, properties(n) AS p")
    rels = probe.run(
        "MATCH (a)-[r]->(b) RETURN type(r) AS t, properties(r) AS p, "
        "coalesce(a.entity_id, a.assertion_id) AS a, "
        "coalesce(b.entity_id, b.assertion_id) AS b"
    )
    assert nodos, "conjunto vacio: no habria nada que comparar"
    clave = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
    doc = {
        "nodos": sorted(
            [{"labels": sorted(n["l"]), "props": dict(n["p"])} for n in nodos], key=clave
        ),
        "relaciones": sorted(
            [
                {"t": r["t"], "from": r["a"], "to": r["b"], "props": dict(r["p"])}
                for r in rels
            ],
            key=clave,
        ),
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


@pytest.fixture()
def probe(neo4j_driver):
    """Grafo limpio antes y despues. Cada prueba mide sobre lo que ella escribio."""
    p = GraphProbe(neo4j_driver)
    p.clean()
    yield p
    p.clean()


@pytest.fixture()
def writer(probe):
    return make_writer(probe.driver)


def _crea_dos(writer_real, probe):
    plan = make_plan(
        [
            create_entity("op:e1", "entity:uno", "Uno"),
            create_entity("op:e2", "entity:dos", "Dos"),
        ]
    )
    salida = writer_real.write(plan, apply_request(plan))
    assert salida.outcome == OUTCOME_APPLIED, salida.codes
    return plan


def test_create_entity_deja_state_hash_que_describe_lo_persistido(writer, probe):
    """El hash no es "un valor que valida": se recomputa DESDE el grafo."""
    _crea_dos(writer, probe)

    for entity_id in ("entity:uno", "entity:dos"):
        props = _props(probe, entity_id)
        assert props.get("version") == 0
        guardado = props.get("state_hash")
        assert isinstance(guardado, str) and len(guardado) == 64, guardado
        # La prueba de que describe el estado REAL: se rehace desde lo leido.
        assert guardado == state_hash_value(props)

    # Y no es el mismo hash para dos nodos distintos, que seria un hash que no
    # describe nada.
    assert _props(probe, "entity:uno")["state_hash"] != _props(probe, "entity:dos")[
        "state_hash"
    ]


def test_una_relacion_se_proyecta_con_la_version_y_el_hash_del_grafo(writer, probe):
    """Lo que la segunda ingesta necesitaba y no podia hacer."""
    _crea_dos(writer, probe)
    props = _props(probe, "entity:uno")

    plan = make_plan(
        [
            link_existing(
                "op:link",
                "entity:uno",
                "entity:dos",
                version=props["version"],
                state_hash=hash_doc(props["state_hash"]),
            )
        ],
        plan_id="plan:writer-real:link",
    )
    salida = writer.write(plan, apply_request(plan))
    assert salida.outcome == OUTCOME_APPLIED, salida.codes
    assert probe.run("MATCH ()-[r:MEMBER_OF]->() RETURN count(r) AS c")[0]["c"] == 1


def test_aplicar_dos_veces_el_mismo_plan_deja_el_grafo_EXACTAMENTE_igual(writer, probe):
    """S1 -> segundo apply -> S1 exacto, comparado por huella sin `elementId`."""
    _crea_dos(writer, probe)
    plan = make_plan(
        [create_assertion("op:a1", "assertion:uno", "entity:uno", "entity:dos")],
        plan_id="plan:writer-real:idem",
    )
    primera = writer.write(plan, apply_request(plan))
    assert primera.outcome == OUTCOME_APPLIED, primera.codes
    s1 = _huella(probe)

    segunda = writer.write(plan, apply_request(plan))
    assert segunda.outcome == OUTCOME_APPLIED, segunda.codes
    assert segunda.applied_operations == 0, "el segundo apply escribio algo"
    assert segunda.noop_operations == 1, "el segundo apply no lo trato como repeticion"
    assert _huella(probe) == s1, "el segundo apply movio el grafo"
    # Ni identidad ni version se movieron por repetir.
    assert _props(probe, "entity:uno")["version"] == 0


def test_CONTROL_NEGATIVO_un_cambio_real_de_estado_sigue_tumbando_el_control(
    writer, probe
):
    """Si esto pasa a verde, el arreglo se habria comido la comprobacion.

    Se construye el plan con el hash BUENO, se mueve el grafo por debajo -- un
    escritor concurrente honesto: cambia el estado Y recalcula su hash -- y el
    apply tiene que abortar. Es la prueba de que la comprobacion sigue viva.
    """
    _crea_dos(writer, probe)
    props = _props(probe, "entity:uno")
    plan = make_plan(
        [
            link_existing(
                "op:link",
                "entity:uno",
                "entity:dos",
                version=props["version"],
                state_hash=hash_doc(props["state_hash"]),
            )
        ],
        plan_id="plan:writer-real:drift",
    )

    movidas = {**props, "name": "Uno, pero cambiado"}
    movidas["state_hash"] = state_hash_value(movidas)
    probe.run(
        "MATCH (n:V3Entity {entity_id: 'entity:uno'}) "
        "SET n.name = $name, n.state_hash = $hash",
        {"name": movidas["name"], "hash": movidas["state_hash"]},
    )
    assert _props(probe, "entity:uno")["state_hash"] != props["state_hash"]

    salida = writer.write(plan, apply_request(plan))
    assert codes.EXEC_HASH_MISMATCH in salida.codes, salida.codes
    assert probe.run("MATCH ()-[r:MEMBER_OF]->() RETURN count(r) AS c")[0]["c"] == 0


def test_CONTROL_NEGATIVO_un_hash_que_no_describe_el_nodo_tambien_aborta(writer, probe):
    """El plan miente sobre el estado: el writer no puede creerselo."""
    _crea_dos(writer, probe)
    props = _props(probe, "entity:uno")
    plan = make_plan(
        [
            link_existing(
                "op:link",
                "entity:uno",
                "entity:dos",
                version=props["version"],
                state_hash={"algorithm": "sha256", "value": "f" * 64},
            )
        ],
        plan_id="plan:writer-real:mentira",
    )
    salida = writer.write(plan, apply_request(plan))
    assert codes.EXEC_HASH_MISMATCH in salida.codes, salida.codes
    assert probe.run("MATCH ()-[r:MEMBER_OF]->() RETURN count(r) AS c")[0]["c"] == 0

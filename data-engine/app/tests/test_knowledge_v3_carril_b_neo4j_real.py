# -*- coding: utf-8 -*-
"""CARRIL B contra un Neo4j real y efimero: reconciliar sin sembrar a mano.

Saltadas por defecto (arrancan un contenedor). Se activan con:

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \
        data-engine/app/tests/test_knowledge_v3_carril_b_neo4j_real.py -q

Lo que se mide aqui NO se puede medir con un driver falso: que la consulta del
catalogo devuelve lo que Neo4j tiene, que un plan con `CREATE_ENTITY` se aplica
de verdad, y que despues la procedencia es navegable por el CAMINO.
"""
from __future__ import annotations

import os
import pathlib
import stat
import sys
from datetime import datetime, timezone

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
    neo4j_efimero_conexion,
)

from knowledge_v3.pipeline import entity_decisions, graph_catalog, ingest_cli  # noqa: E402
from knowledge_v3.writer.provenance import trace  # noqa: E402
from knowledge_v3.writer.reads import list_entities, locate_entity  # noqa: E402


LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)

RAIZ = pathlib.Path(__file__).resolve().parents[3]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"
WS = "ws-cofradia"
#: INTEGRACION TANDA 6 -- BOMBA DE RELOJ DESACTIVADA DE RAIZ. Ver la nota
#: extensa en `test_knowledge_v3_tanda3_integracion_neo4j_real.py`: este
#: fichero llevaba la MISMA fecha fija (`2026-09-06T10:00:00Z`) con el mismo
#: `plan_ttl_seconds = 86400`, y caducaba el mismo instante con `PLAN_EXPIRED`.
#: Se deriva del reloj por el mismo motivo: adelantar la fecha reprograma la
#: bomba, derivarla la desactiva.
AHORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def conexion():
    with neo4j_efimero_conexion("s9k-carril-b-tests") as cx:
        yield cx


@pytest.fixture()
def limpio(conexion):
    with conexion.driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    return conexion


def _ingesta(driver, *, altas=(), apply=False, env=None, catalogo=CATALOGO):
    """El catalogo declarado NO es opcional para que haya algo que escribir.

    MEDIDO: sin el, el resolutor no tiene vocabulario con el que enlazar, todas
    las entidades salen provisionales y el motor manda a revision humana
    cualquier hecho sobre una provisional (`ENTITY_PROVISIONAL`) -- 0
    operaciones y `PLAN_NO_OPERATIONS`. El catalogo dice COMO SE LLAMAN las
    cosas; el grafo dice QUE EXISTE. Son dos preguntas distintas.
    """
    return ingest_cli.run_ingest(
        FUENTE,
        profile_path=PERFIL,
        catalog_path=catalogo,
        driver=driver,
        now=AHORA,
        ingested_at=AHORA,
        approved_altas=list(altas),
        apply=apply,
        operator_id="pjc" if apply else None,
        writer_env=env,
    )


# --- la lectura que faltaba -------------------------------------------------
def test_catalogo_vacio_es_un_dato_observado_no_un_fallo(limpio):
    """Un grafo nuevo devuelve CERO entidades. Y eso significa: todo es alta."""
    assert list_entities(limpio.driver, WS) == []
    assert graph_catalog.catalog_rows(limpio.driver, WS) == []


def test_el_catalogo_no_cruza_workspaces(limpio):
    """El aislamiento se comprueba con el conjunto NO vacio, no con dos ceros."""
    with limpio.driver.session() as s:
        s.run(
            "CREATE (:V3Entity {entity_id:'entity:a', workspace:$ws, "
            "entity_type:'Faction', name:'A', version:0})", {"ws": WS})
        s.run(
            "CREATE (:V3Entity {entity_id:'entity:b', workspace:'otra', "
            "entity_type:'Faction', name:'B', version:0})")
    mios = [e.entity_id for e in list_entities(limpio.driver, WS)]
    otros = [e.entity_id for e in list_entities(limpio.driver, "otra")]
    # Conjuntos NO vacios por los dos lados: dos listas vacias no demostrarian
    # aislamiento ninguno, solo que la consulta no encuentra nada.
    assert mios == ["entity:a"]
    assert otros == ["entity:b"]
    assert locate_entity(limpio.driver, "entity:a") == [WS]
    assert locate_entity(limpio.driver, "entity:nadie") == []


def test_el_catalogo_no_cruza_ambitos_de_partida(limpio):
    """Capa juego siempre visible; la partida ajena, nunca."""
    with limpio.driver.session() as s:
        s.run("CREATE (:V3Entity {entity_id:'entity:lore', workspace:$ws, "
              "entity_type:'Faction', name:'Lore', version:0})", {"ws": WS})
        s.run("CREATE (:V3Entity {entity_id:'entity:p1', workspace:$ws, "
              "partida_id:'partida:1', entity_type:'Faction', name:'P1', "
              "version:0})", {"ws": WS})
        s.run("CREATE (:V3Entity {entity_id:'entity:p2', workspace:$ws, "
              "partida_id:'partida:2', entity_type:'Faction', name:'P2', "
              "version:0})", {"ws": WS})
    juego = [e.entity_id for e in list_entities(limpio.driver, WS)]
    p1 = [e.entity_id for e in list_entities(limpio.driver, WS, "partida:1")]
    assert juego == ["entity:lore"]
    assert p1 == ["entity:lore", "entity:p1"]
    assert "entity:p2" not in p1


def _altas_aprobadas(driver):
    """Primera pasada + aprobacion humana, que es lo que da un plan con altas."""
    primera = _ingesta(driver)
    ledger = entity_decisions.reconcile(
        resolutions=(primera["candidates"]["link_existing"]
                     + primera["candidates"]["create_entity"]),
        graph_entity_ids=graph_catalog.entity_ids(
            graph_catalog.catalog_rows(driver, WS)),
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
    )
    aprobado = entity_decisions.approve(
        ledger, sorted({d.entity_id for d in ledger.altas}),
        reviewer="pjc", at=AHORA)
    return entity_decisions.approved_snapshot_entities(aprobado)


# --- la regla que no se relaja ---------------------------------------------
def test_grafo_vacio_no_produce_ni_un_enlace_automatico(limpio):
    """Con el grafo vacio, TODO sale como alta pendiente. Nada se enlaza."""
    informe = _ingesta(limpio.driver)
    filas = graph_catalog.catalog_rows(limpio.driver, WS)
    ledger = entity_decisions.reconcile(
        resolutions=(
            informe["candidates"]["link_existing"]
            + informe["candidates"]["create_entity"]
            + informe["candidates"]["review_identity"]
        ),
        graph_entity_ids=graph_catalog.entity_ids(filas),
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
    )
    assert ledger.decisions, "sin decisiones no hay nada que comprobar"
    assert not [d for d in ledger.decisions
                if d.decision == entity_decisions.LINK_EXISTING]
    assert ledger.altas
    # Y ninguna esta aprobada por si sola.
    assert not ledger.aprobadas
    assert all(d.review == entity_decisions.PENDIENTE for d in ledger.altas)


def test_un_alta_sin_aprobar_no_llega_al_snapshot(limpio):
    """`approved_snapshot_entities` filtra por el campo que escribe un humano."""
    informe = _ingesta(limpio.driver)
    ledger = entity_decisions.reconcile(
        resolutions=informe["candidates"]["create_entity"],
        graph_entity_ids=[],
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
    )
    assert ledger.altas
    assert entity_decisions.approved_snapshot_entities(ledger) == []
    with pytest.raises(entity_decisions.AltaNoAprobada):
        entity_decisions.require_reviewed(ledger)


def test_aprobar_un_id_que_no_esta_pendiente_es_un_error(limpio):
    informe = _ingesta(limpio.driver)
    ledger = entity_decisions.reconcile(
        resolutions=informe["candidates"]["create_entity"],
        graph_entity_ids=[],
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
    )
    with pytest.raises(ValueError):
        entity_decisions.approve(ledger, ["entity:inventada"], reviewer="pjc",
                                 at=AHORA)
    with pytest.raises(ValueError):
        entity_decisions.approve(ledger, [], reviewer="", at=AHORA)


def test_un_enlace_sin_respaldo_en_el_grafo_se_degrada_a_alta():
    """El hallazgo del supervisor, convertido en decision revisable.

    El resolutor dice LINK_EXISTING; el grafo no tiene la entidad. NO se crea
    sola: sale como alta PENDIENTE, con el motivo escrito al lado.
    """
    ledger = entity_decisions.reconcile(
        resolutions=[{
            "resolution_id": "resolution:x",
            "action": "LINK_EXISTING",
            "selected_entity_id": "entity:sela-marrec",
            "assigned_entity_id": None,
            "entity_type": "Character",
            "confidence": 1.0,
            "mention_ids": ["mention:1"],
            "reason_codes": ["STRONG_MATCH"],
        }],
        graph_entity_ids=[],
        workspace=WS,
        source_path="x",
        names_by_mention={},
    )
    (decision,) = ledger.decisions
    assert decision.decision == entity_decisions.CREATE_ENTITY_REQUIRED
    assert decision.review == entity_decisions.PENDIENTE
    assert "ENLACE_SIN_RESPALDO_EN_GRAFO" in decision.reason_codes


def test_un_enlace_con_respaldo_se_queda_en_enlace():
    """Control positivo: si la entidad SI esta, no se inventa ningun alta."""
    ledger = entity_decisions.reconcile(
        resolutions=[{
            "resolution_id": "resolution:x",
            "action": "LINK_EXISTING",
            "selected_entity_id": "entity:sela-marrec",
            "assigned_entity_id": None,
            "entity_type": "Character",
            "confidence": 1.0,
            "mention_ids": ["mention:1"],
            "reason_codes": ["STRONG_MATCH"],
        }],
        graph_entity_ids=["entity:sela-marrec"],
        workspace=WS,
        source_path="x",
        names_by_mention={},
    )
    (decision,) = ledger.decisions
    assert decision.decision == entity_decisions.LINK_EXISTING
    assert decision.review == entity_decisions.NO_PROCEDE
    assert "OBSERVADA_EN_GRAFO" in decision.reason_codes


# --- la cadena entera -------------------------------------------------------
def test_con_altas_aprobadas_el_plan_trae_create_entity(limpio):
    """Antes de este carril, NINGUN plan del producto traia un CREATE_ENTITY."""
    primera = _ingesta(limpio.driver)
    ledger = entity_decisions.reconcile(
        resolutions=(primera["candidates"]["link_existing"]
                     + primera["candidates"]["create_entity"]),
        graph_entity_ids=[],
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
    )
    ids = [d.entity_id for d in ledger.altas]
    aprobado = entity_decisions.approve(ledger, ids, reviewer="pjc", at=AHORA)
    altas = entity_decisions.approved_snapshot_entities(aprobado)
    assert altas, "sin altas aprobadas este caso no mide nada"

    segunda = _ingesta(limpio.driver, altas=altas)
    tipos = [op["operation_type"]
             for op in (segunda["plan"] or {}).get("mutation_operations", [])]
    assert "CREATE_ENTITY" in tipos


def test_apply_real_escribe_y_deja_la_procedencia_navegable(limpio):
    """La cadena completa contra Neo4j real, sin sembrar nada por Cypher."""
    primera = _ingesta(limpio.driver)
    ledger = entity_decisions.reconcile(
        resolutions=(primera["candidates"]["link_existing"]
                     + primera["candidates"]["create_entity"]),
        graph_entity_ids=[],
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
    )
    aprobado = entity_decisions.approve(
        ledger, [d.entity_id for d in ledger.altas], reviewer="pjc", at=AHORA)
    altas = entity_decisions.approved_snapshot_entities(aprobado)

    informe = _ingesta(
        limpio.driver, altas=altas, apply=True,
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
    )
    escritura = informe.get("write")
    assert escritura is not None, "no hubo intento de escritura"
    assert escritura["outcome"] == "APPLIED", escritura
    assert escritura["applied_operations"] > 0

    entidades = [e.entity_id for e in list_entities(limpio.driver, WS)]
    assert entidades, "el APPLY dijo que escribio y el grafo esta vacio"

    with limpio.driver.session() as s:
        aserciones = [r.data()["id"] for r in s.run(
            "MATCH (n:V3Assertion {workspace:$ws}) RETURN n.assertion_id AS id",
            {"ws": WS})]
    assert aserciones, "sin aserciones no hay recorrido que comprobar"

    recorridos = {a: trace(limpio.driver, WS, a) for a in aserciones}
    # NO basta con que la consulta no falle: tiene que devolver filas. Un
    # `[] == []` no demuestra que la procedencia sea navegable.
    assert any(filas for filas in recorridos.values()), recorridos
    for filas in recorridos.values():
        for fila in filas:
            assert fila["source_asset_id"]
            assert fila["episode_id"]
            assert fila["fragment_id"]


def test_el_gate_del_writer_sigue_mandando(limpio):
    """Sin `S9K_ALLOW_REAL_INGEST=1` no se escribe, aunque TODO lo demas este.

    Ojo con el orden: la admision del plan corre ANTES que el gate. Si el plan
    viniera vacio, el resultado seria `PLAN_NO_OPERATIONS` y esta prueba
    pasaria sin haber ejercitado el gate ni una vez -- un verde prestado. Por
    eso primero se aprueban las altas, para que haya un plan con operaciones
    de verdad, y solo entonces se le quita el permiso de entorno.
    """
    altas = _altas_aprobadas(limpio.driver)
    assert altas, "sin altas aprobadas el plan iria vacio y el gate no se probaria"
    informe = _ingesta(
        limpio.driver, altas=altas, apply=True,
        env={"S9K_WRITER_WORKSPACE": WS},  # falta el permiso de entorno
    )
    escritura = informe.get("write")
    assert escritura is not None
    assert escritura["outcome"] != "APPLIED"
    assert "GATE_ENV_NOT_ALLOWED" in escritura["codes"]
    with limpio.driver.session() as s:
        n = list(s.run("MATCH (n:V3Entity {workspace:$ws}) RETURN count(n) AS c",
                       {"ws": WS}))[0]["c"]
    assert n == 0


def test_el_secreto_no_viaja_por_argv(tmp_path):
    """La CLI solo admite el CAMINO de un fichero privado, nunca el secreto."""
    opciones = {
        cadena
        for accion in ingest_cli.build_parser()._actions
        for cadena in accion.option_strings
    }
    assert "--neo4j-password-file" in opciones
    assert "--neo4j-password" not in opciones
    # Y el fichero tiene que ser privado de verdad.
    from knowledge_v3.driver_neo4j import DriverConfigError, read_secret

    abierto = tmp_path / "abierto.pass"
    abierto.write_text("x", encoding="utf-8")
    abierto.chmod(0o644)
    with pytest.raises(DriverConfigError):
        read_secret(str(abierto))
    privado = tmp_path / "privado.pass"
    privado.write_text("x", encoding="utf-8")
    privado.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert read_secret(str(privado)) == "x"

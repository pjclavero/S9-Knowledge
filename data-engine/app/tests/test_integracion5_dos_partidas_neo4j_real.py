# -*- coding: utf-8 -*-
"""INTEGRACION tanda 5: dos partidas desde CERO, y el radio de propiedad.

QUE SE MIDE AQUI Y POR QUE NO LO MIDE NINGUN CARRIL
---------------------------------------------------
Cada equipo probo SU mitad, y las dos mitades pasan por separado:

* 5A demostro que dos partidas no comparten `idempotency_key` ni objeto, y que
  el ambito queda estampado (`test_equipo5a_...::test_dos_partidas_...`).
* 5B demostro que revertir un apply no se lleva lo que creo otro apply
  (`test_..._equipo5b_...::test_revertir_el_segundo_apply_no_toca_...`).

Ninguno de los dos mide la propiedad COMPUESTA, que es la que el operador
exige y la unica que atraviesa los tres defectos a la vez: **revertir la
partida B deja la partida A intacta, y revertir despues la A devuelve el grafo
al estado inicial EXACTO**. Esa propiedad necesita el ambito de 5A *y* la
propiedad de 5B al mismo tiempo; sobre cualquiera de las dos ramas por
separado no se puede ni escribir.

Sin `partida_id` en el plan (el defecto que 5A cerro) las dos partidas
colisionaban en la misma `idempotency_key` y la segunda salia no-op: revertir
una borraba el objeto de la otra. Sin `apply_id` (el que cerro 5B) el barrido
de procedencia revertia por `run` y se llevaba la evidencia compartida.

DISCIPLINA DE MEDIDA
--------------------
* El grafo se comprueba VACIO al empezar; no se presume.
* El esquema lo instala el PRODUCTO (`schema.bootstrap_writer_schema`), no
  Cypher a mano. Este fichero no escribe ni un `CREATE` propio: todo nodo del
  grafo lo pone el writer.
* UNA consulta por cosa contada. Dos `MATCH` sueltos dan producto cartesiano y,
  con un lado vacio, CERO filas -- un verde que no mide nada. Cada censo se
  afirma NO VACIO antes de compararlo.
* El "estado inicial EXACTO" se compara por HUELLA DE CONTENIDO, nunca por
  `elementId`: `elementId` no es identidad durable y volveria a ser distinto
  tras un borrado y una reescritura aunque el contenido fuese identico.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real: activar con S9K_WRITER_NEO4J_REAL=1"
)

from knowledge_v3.writer import schema  # noqa: E402
from knowledge_v3.writer.state import hash_doc  # noqa: E402
from knowledge_v3.writer.rollback_provenance import execute_rollback  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: E402

from test_knowledge_v3_estado_durable_neo4j_real import (  # noqa: E402,F401
    neo4j_driver,
    neo4j_driver_efimero,
    probe,
    writer,
)
from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401
    WORKSPACE,
    apply_request,
    create_assertion,
    create_entity,
    link_existing,
    make_plan,
)

PARTIDA_A = "partida:A"
PARTIDA_B = "partida:B"


def _scope(partida_id: str) -> dict:
    return {"layer": "PARTIDA", "game_id": WORKSPACE, "partida_id": partida_id}


def _plan(partida_id: str, *, sufijo: str, plan_id: str) -> dict:
    """La MISMA fuente logica en dos ambitos distintos.

    Los ids se separan por partida porque `executor._assert_absent` lo exige
    ("dos ambitos jamas comparten el mismo id"): es una regla del producto y no
    se relaja para que pase un test. Lo que queda identico entre A y B es la
    identidad LOGICA que alimenta la `idempotency_key` salvo el ambito, que es
    justo el punto.
    """
    operaciones = [
        create_entity(f"op:e1:{sufijo}", f"entity:capitana:{sufijo}", "Ilva Roen"),
        create_entity(f"op:e2:{sufijo}", f"entity:nave:{sufijo}", "Alba"),
        create_assertion(
            f"op:a1:{sufijo}",
            f"assertion:manda:{sufijo}",
            f"entity:capitana:{sufijo}",
            f"entity:nave:{sufijo}",
        ),
    ]
    # Ambito de PARTIDA: `known_from_session` es obligatorio por operacion
    # (visibilidad M5b). Se CUMPLE la regla ajena, no se rodea.
    for operacion in operaciones:
        operacion["payload"]["known_from_session"] = 0
    return make_plan(
        operaciones, plan_id=plan_id, partida_id=partida_id, scope=_scope(partida_id)
    )


# --- Censo -----------------------------------------------------------------
def _ident(props: dict) -> str:
    for campo in ("entity_id", "assertion_id", "fragment_id", "episode_id"):
        if props.get(campo):
            return f"{campo}={props[campo]}"
    return "?"


def _huella(driver) -> list[str]:
    """Huella completa del workspace, derivada del CONTENIDO durable.

    Dos bases distintas con el mismo contenido dan la misma huella. Es lo
    contrario de lo que haria `elementId`, que cambiaria tras cualquier
    reescritura y convertiria "estado inicial exacto" en algo incomprobable.
    """
    with driver.session() as s:
        nodos = [
            r.data()
            for r in s.run(
                "MATCH (n) WHERE n.workspace = $ws "
                "RETURN labels(n) AS labels, properties(n) AS props",
                ws=WORKSPACE,
            )
        ]
        aristas = [
            r.data()
            for r in s.run(
                "MATCH (a)-[r]->(b) WHERE a.workspace = $ws "
                "RETURN type(r) AS t, properties(a) AS ap, properties(b) AS bp",
                ws=WORKSPACE,
            )
        ]
    fuera = []
    for n in nodos:
        fuera.append(
            "NODO "
            + json.dumps(
                {"labels": sorted(n["labels"]), "props": dict(sorted(n["props"].items()))},
                sort_keys=True,
                default=str,
            )
        )
    for r in aristas:
        fuera.append(
            "ARISTA "
            + json.dumps(
                {"tipo": r["t"], "de": _ident(r["ap"]), "a": _ident(r["bp"])},
                sort_keys=True,
                default=str,
            )
        )
    return sorted(fuera)


def _censo(driver, partida_id: str | None = None) -> dict[str, int]:
    """UNA consulta por cosa contada. Nunca dos `MATCH` en la misma."""
    cond = (
        "n.partida_id IS NULL" if partida_id is None else "n.partida_id = $p"
    )
    params: dict[str, Any] = {"ws": WORKSPACE}
    if partida_id is not None:
        params["p"] = partida_id
    fuera = {}
    with driver.session() as s:
        for clave, etiqueta in (
            ("entidades", "V3Entity"),
            ("aserciones", "V3Assertion"),
            ("operaciones", "V3AppliedOperation"),
        ):
            fuera[clave] = s.run(
                f"MATCH (n:{etiqueta} {{workspace: $ws}}) WHERE {cond} "
                "RETURN count(n) AS c",
                **params,
            ).single()["c"]
    return fuera


def _claves(driver, partida_id: str) -> set[str]:
    with driver.session() as s:
        filas = list(
            s.run(
                "MATCH (n:V3AppliedOperation {workspace: $ws}) "
                "WHERE n.partida_id = $p RETURN n.idempotency_key AS k",
                ws=WORKSPACE,
                p=partida_id,
            )
        )
    return {f["k"] for f in filas if f["k"]}


@pytest.fixture()
def grafo_vacio(probe):
    """Neo4j VACIO con el esquema puesto POR EL PRODUCTO, y observado."""
    schema.bootstrap_writer_schema(probe.driver)
    assert schema.missing_required_constraints(probe.driver) == [], (
        "el bootstrap del producto no dejo las constraints requeridas"
    )
    with probe.driver.session() as s:
        vivos = s.run(
            "MATCH (n) WHERE n.workspace = $ws RETURN count(n) AS c", ws=WORKSPACE
        ).single()["c"]
    assert vivos == 0, f"el grafo no arranca vacio ({vivos} nodos): nada de esto valdria"
    return probe.driver


# ---------------------------------------------------------------------------
# LA PRUEBA QUE EXIGE EL OPERADOR
# ---------------------------------------------------------------------------
def test_dos_partidas_desde_cero_y_rollback_que_devuelve_el_estado_exacto(
    writer, grafo_vacio
):
    driver = grafo_vacio

    # --- S0: estado inicial, medido, no presumido -------------------------
    s0 = _huella(driver)
    assert s0 == [], f"el estado inicial no esta vacio: {s0[:3]}"

    # --- Partida A --------------------------------------------------------
    plan_a = _plan(PARTIDA_A, sufijo="a", plan_id="plan:int5:a")
    r_a = writer.write(plan_a, apply_request(plan_a))
    assert r_a.outcome == OUTCOME_APPLIED, r_a.codes
    tras_a = _censo(driver, PARTIDA_A)
    assert all(v > 0 for v in tras_a.values()), (
        f"censo de A vacio: no se estaria midiendo nada ({tras_a})"
    )

    # --- Partida B: MISMA fuente logica, otro ambito ----------------------
    plan_b = _plan(PARTIDA_B, sufijo="b", plan_id="plan:int5:b")
    r_b = writer.write(plan_b, apply_request(plan_b))
    assert r_b.outcome == OUTCOME_APPLIED, r_b.codes

    # 1. LAS DOS PARTIDAS EXISTEN DE VERDAD.
    censo_a = _censo(driver, PARTIDA_A)
    censo_b = _censo(driver, PARTIDA_B)
    assert censo_a == tras_a, "la segunda partida altero el censo de la primera"
    assert all(v > 0 for v in censo_b.values()), f"la partida B no existe: {censo_b}"

    # 2. NO COMPARTEN `AppliedOperation`. Este es el defecto que 5A cerro: sin
    #    `partida_id` en la clave, B salia no-op y reutilizaba la marca de A.
    assert r_b.noop_operations == 0, "B declaro no-op: esta reutilizando lo de A"
    claves_a, claves_b = _claves(driver, PARTIDA_A), _claves(driver, PARTIDA_B)
    assert claves_a and claves_b, "censo de marcas vacio: no se mide nada"
    assert claves_a.isdisjoint(claves_b), (
        f"las dos partidas COMPARTEN idempotency_key: {claves_a & claves_b}"
    )

    # 3. AMBITO ESTAMPADO en todo, marca incluida. Ni una asercion ni una
    #    operacion pierde su partida.
    with driver.session() as s:
        for etiqueta in ("V3Entity", "V3Assertion", "V3AppliedOperation"):
            filas = list(
                s.run(
                    f"MATCH (n:{etiqueta} {{workspace: $ws}}) RETURN n.partida_id AS p",
                    ws=WORKSPACE,
                )
            )
            assert filas, f"censo vacio para {etiqueta}"
            assert {f["p"] for f in filas} == {PARTIDA_A, PARTIDA_B}, (
                f"{etiqueta} pierde el ambito: {sorted({f['p'] for f in filas})}"
            )
            assert None not in {f["p"] for f in filas}, (
                f"{etiqueta} tiene filas SIN partida: el ambito se perdio"
            )

    # 4. RELACIONES correctas y dentro de su ambito: ninguna arista cruza de
    #    una partida a la otra.
    with driver.session() as s:
        cruces = s.run(
            "MATCH (a)-[r]->(b) WHERE a.workspace = $ws AND b.workspace = $ws "
            "AND a.partida_id IS NOT NULL AND b.partida_id IS NOT NULL "
            "AND a.partida_id <> b.partida_id RETURN count(r) AS c",
            ws=WORKSPACE,
        ).single()["c"]
    assert cruces == 0, f"{cruces} aristas cruzan de una partida a la otra"

    s_ab = _huella(driver)
    assert len(s_ab) > len(s0), "el grafo no crecio: no hay nada que revertir"

    # --- ROLLBACK DE B: la partida A tiene que quedar INTACTA -------------
    doc_b = r_b.rollback
    assert doc_b is not None, "el writer no entrego documento de reversion para B"
    with driver.session() as sesion:
        informe_b = execute_rollback(sesion, doc_b, annotate=True)
    assert informe_b is not None

    censo_a_tras_b = _censo(driver, PARTIDA_A)
    assert censo_a_tras_b == censo_a, (
        f"revertir B toco la partida A: {censo_a} -> {censo_a_tras_b}"
    )
    censo_b_tras = _censo(driver, PARTIDA_B)
    assert censo_b_tras == {"entidades": 0, "aserciones": 0, "operaciones": 0}, (
        f"revertir B dejo residuo en B: {censo_b_tras}"
    )

    # --- ROLLBACK DE A: estado inicial EXACTO -----------------------------
    doc_a = r_a.rollback
    assert doc_a is not None, "el writer no entrego documento de reversion para A"
    with driver.session() as sesion:
        execute_rollback(sesion, doc_a, annotate=True)

    s_final = _huella(driver)
    assert s_final == s0, (
        "el grafo NO volvio al estado inicial exacto.\n"
        f"  sobra: {[x for x in s_final if x not in s0][:5]}\n"
        f"  falta: {[x for x in s0 if x not in s_final][:5]}"
    )


def test_control_negativo_la_huella_distingue_de_verdad(writer, grafo_vacio):
    """Sin esto, `s_final == s0` podria ser un verde que no mide nada.

    Si `_huella` devolviese siempre lo mismo --por mirar donde no hay nada, o
    por comparar listas vacias entre si--, la prueba de arriba pasaria sobre
    cualquier grafo. Aqui se comprueba que la huella SI cambia cuando el
    contenido cambia, que es la unica forma de que su igualdad signifique algo.
    """
    driver = grafo_vacio
    vacia = _huella(driver)
    assert vacia == []

    plan = _plan(PARTIDA_A, sufijo="ctl", plan_id="plan:int5:ctl")
    resultado = writer.write(plan, apply_request(plan))
    assert resultado.outcome == OUTCOME_APPLIED, resultado.codes

    llena = _huella(driver)
    assert llena != vacia, "la huella NO distingue un grafo lleno de uno vacio"
    assert len(llena) >= 3, f"la huella apenas ve nada ({len(llena)} lineas)"


# ---------------------------------------------------------------------------
# SEGUNDA FUENTE COMPARTIENDO OBJETO: el radio de propiedad del rollback
# ---------------------------------------------------------------------------
def test_segunda_fuente_comparte_entidad_y_el_rollback_no_se_la_lleva(
    writer, grafo_vacio
):
    """Revertir el apply de UNA fuente no puede llevarse lo que creo la otra.

    Es el ataque directo al radio de propiedad que introdujo 5B, y va POR EL
    PRODUCTO: dos corridas del writer en el MISMO ambito, la segunda enlazando
    contra una entidad que creo la primera. Sin `apply_id` el barrido revertia
    por `run` y se llevaba por delante lo compartido; con propiedad por apply
    la reversion de la segunda solo puede tocar lo suyo.

    La entidad compartida es el caso duro a proposito: no es un objeto aislado
    de la segunda corrida, es uno del que la segunda DEPENDE y que la primera
    posee. Un radio mal puesto se lo lleva y deja el grafo con una arista
    apuntando a la nada -- o borra conocimiento de la primera fuente, que es
    peor porque nadie lo pidio.
    """
    driver = grafo_vacio
    assert _huella(driver) == [], "el grafo no arranca vacio"

    # --- Fuente 1: crea la capitana y la nave -----------------------------
    ops1 = [
        create_entity("op:f1:e1", "entity:capitana:f1", "Ilva Roen"),
        create_entity("op:f1:e2", "entity:nave:f1", "Alba"),
        create_assertion(
            "op:f1:a1", "assertion:manda:f1", "entity:capitana:f1", "entity:nave:f1"
        ),
    ]
    for o in ops1:
        o["payload"]["known_from_session"] = 0
    plan1 = make_plan(
        ops1, plan_id="plan:int5:f1", partida_id=PARTIDA_A, scope=_scope(PARTIDA_A)
    )
    r1 = writer.write(plan1, apply_request(plan1))
    assert r1.outcome == OUTCOME_APPLIED, r1.codes

    censo_f1 = _huella(driver)
    assert censo_f1, "la primera fuente no escribio nada: no habria nada que compartir"

    # --- Fuente 2: crea lo suyo y ENLAZA con la entidad de la fuente 1 ----
    # El `expected_version`/`expected_hash` del enlace se LEEN del grafo, no se
    # inventan: la concurrencia optimista del producto es real y rechaza con
    # `EXEC_VERSION_MISMATCH` un enlace que no declare el estado que de verdad
    # tiene la entidad. Se cumple la regla ajena, no se rodea -- y de paso esto
    # confirma que la entidad de la fuente 1 salio con estado durable completo
    # (`version` + `state_hash`), que es lo que arreglo el carril de estado.
    with driver.session() as s:
        props = s.run(
            "MATCH (n:V3Entity {entity_id: $e, workspace: $ws}) "
            "RETURN n.version AS v, n.state_hash AS h",
            e="entity:nave:f1",
            ws=WORKSPACE,
        ).single()
    assert props is not None, "la entidad de la fuente 1 no existe"
    assert props["h"], "la entidad salio sin state_hash: no se podria enlazar"
    ops2 = [
        create_entity("op:f2:e1", "entity:flota:f2", "Flota del Norte"),
        link_existing(
            "op:f2:l1",
            "entity:nave:f1",
            "entity:flota:f2",
            version=props["v"],
            state_hash=hash_doc(props["h"]),
        ),
    ]
    for o in ops2:
        o["payload"]["known_from_session"] = 0
    plan2 = make_plan(
        ops2, plan_id="plan:int5:f2", partida_id=PARTIDA_A, scope=_scope(PARTIDA_A)
    )
    r2 = writer.write(plan2, apply_request(plan2))
    assert r2.outcome == OUTCOME_APPLIED, r2.codes

    # El objeto COMPARTIDO existe y lo posee la PRIMERA corrida, no la segunda.
    with driver.session() as s:
        fila = s.run(
            "MATCH (n:V3Entity {entity_id: $e, workspace: $ws}) "
            "RETURN n.apply_id AS a",
            e="entity:nave:f1",
            ws=WORKSPACE,
        ).single()
    assert fila is not None, "la entidad compartida no existe: no se mide nada"
    duenno_compartido = fila["a"]

    # --- Revertir la SEGUNDA fuente ---------------------------------------
    doc2 = r2.rollback
    assert doc2 is not None
    with driver.session() as sesion:
        execute_rollback(sesion, doc2, annotate=True)

    # 1. Lo que creo la PRIMERA fuente sigue entero, byte a byte.
    with driver.session() as s:
        sobrevive = s.run(
            "MATCH (n:V3Entity {entity_id: $e, workspace: $ws}) RETURN count(n) AS c",
            e="entity:nave:f1",
            ws=WORKSPACE,
        ).single()["c"]
    assert sobrevive == 1, (
        "revertir la segunda fuente se llevo la entidad COMPARTIDA que creo la "
        "primera: el radio de propiedad no esta acotando"
    )
    with driver.session() as s:
        duenno_tras = s.run(
            "MATCH (n:V3Entity {entity_id: $e, workspace: $ws}) RETURN n.apply_id AS a",
            e="entity:nave:f1",
            ws=WORKSPACE,
        ).single()["a"]
    assert duenno_tras == duenno_compartido, (
        "la reversion cambio el duenno de lo compartido"
    )

    # 2. Y lo que creo la segunda, y solo eso, se fue.
    with driver.session() as s:
        propia = s.run(
            "MATCH (n:V3Entity {entity_id: $e, workspace: $ws}) RETURN count(n) AS c",
            e="entity:flota:f2",
            ws=WORKSPACE,
        ).single()["c"]
    assert propia == 0, "la segunda fuente dejo residuo de lo suyo"

    # 3. El grafo vuelve EXACTAMENTE a como lo dejo la primera fuente.
    assert _huella(driver) == censo_f1, (
        "revertir la segunda fuente no devolvio el grafo al estado que dejo la "
        "primera"
    )

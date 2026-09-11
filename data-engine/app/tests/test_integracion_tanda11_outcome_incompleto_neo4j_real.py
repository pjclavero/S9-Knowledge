# -*- coding: utf-8 -*-
"""TANDA 11 -- `INCOMPLETE` alcanzable POR SU SEMANTICA, con Neo4j real.

EL HALLAZGO QUE ORIGINA ESTE FICHERO
------------------------------------
`cli_rollback.OUTCOME_INCOMPLETE` estaba definido, tenia `rc` en la tabla de
`exit_codes` y lo esperaban tres ficheros de prueba, y NINGUNA linea del
producto se lo asignaba nunca: la decision era un solo bit con dos salidas
(`ROLLED_BACK if report.clean else UNEXPECTED_RESIDUE`). Vocabulario muerto
que aparentaba soportar un estado que el producto no podia producir.

MEDIDO ANTES DE TOCAR NADA (Neo4j real, ruta de producto)
---------------------------------------------------------
Una reversion con UNA parte no reconstruible y CERO residuos salia:

    outcome = UNEXPECTED_RESIDUE   rc = 1
    human   = "NO es una reversion limpia: 0 residuos ... y 1 puntos no
               revertidos"

Es decir, el mando afirmaba un fallo de POSTCONDICION --«algo que debia
desaparecer sigue ahi»-- que el grafo no sostenia: no habia residuo ninguno.
Lo que habia era un fallo de PRECONDICION.

LA SEMANTICA QUE SE MIDE AQUI, QUE ES EL CONTRATO
-------------------------------------------------
    UNEXPECTED_RESIDUE = se intento revertir algo que DEBIA desaparecer y el
                         postestado demuestra que SIGUE AHI.
    INCOMPLETE         = se sabe DE ANTEMANO que una o mas partes solicitadas
                         no pueden revertirse (no reconstruible).
    ROLLED_BACK        = todo lo reversible quedo revertido, sin residuos y
                         sin irreversibles pendientes.

    not_reconstructible > 0 · residues = 0  -> INCOMPLETE          · rc != 0
    not_reconstructible = 0 · residues > 0  -> UNEXPECTED_RESIDUE  · rc != 0
    not_reconstructible > 0 · residues > 0  -> UNEXPECTED_RESIDUE  · rc != 0
                                               (+ irreversibles INFORMADOS)
    not_reconstructible = 0 · residues = 0  -> ROLLED_BACK         · rc = 0

COMO SE FABRICA CADA FILA, Y POR QUE ES RUTA DE PRODUCTO
--------------------------------------------------------
El grafo lo escribe el PRODUCTO (`_b_completo`: fichero -> reconciliar ->
aprobar -> apply). Este fichero NO siembra con Cypher: su unico Cypher es el
`DETACH DELETE` de limpieza de su PROPIO contenedor, y por eso levanta un
Neo4j efimero propio en vez de compartir el de otro fichero -- ahi esta el
`DETACH DELETE` ajeno que ya ha contaminado calibraciones dos veces.

Lo que se fabrica es la forma del DOCUMENTO de reversion, que es una ENTRADA
del mando:

* **no reconstruible**: a una instruccion se le quita la identidad durable con
  la que se localiza su objetivo. Es la forma de un documento HEREDADO, y el
  producto responde con `RollbackNotReconstructible`.
* **residuo**: se RETIRA una instruccion del documento. Lo que esa instruccion
  borraba sigue en el grafo, es propiedad de este apply y nada lo sostiene:
  residuo por la definicion del operador, sin escribir una sola linea.

CALIBRACION -- cada control tiene que poder ponerse ROJO
--------------------------------------------------------
Cada fila trae su mutacion, y la mutacion REVIERTE ESA fila en concreto (no
una cualquiera). Se comprueba que con la mutacion puesta el desenlace pasa a
ser el equivocado CONCRETO que la mutacion predice. Un rojo por grafo vacio no
calibraria nada: por eso cada mutacion corre sobre un grafo RECIEN aplicado y
el conjunto de partida se comprueba no vacio antes de comparar.

    S9K_WRITER_NEO4J_REAL=1 python3 -m pytest \\
        data-engine/app/tests/test_integracion_tanda11_outcome_incompleto_neo4j_real.py -q
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
    neo4j_efimero_conexion,
)
import test_knowledge_v3_tanda3_integracion_neo4j_real as tanda3  # noqa: E402
from test_knowledge_v3_tanda3_integracion_neo4j_real import (  # noqa: E402
    WS_B,
    _b_completo,
)
from test_knowledge_v3_equipo4b_mando_rollback_neo4j_real import (  # noqa: E402
    ejecutar_mando,
)

from knowledge_v3.writer import cli_rollback  # noqa: E402
from knowledge_v3.writer.rollback import (  # noqa: E402
    ACTION_DELETE_NODE,
    ACTION_DELETE_RELATIONSHIP,
)

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)

#: Campos de identidad durable. Quitarlos es lo que hace una instruccion NO
#: RECONSTRUIBLE, y es la unica manipulacion del documento que se hace.
CAMPOS_DURABLES = ("workspace", "idempotency_key")


@pytest.fixture(autouse=True)
def _reloj_vivo(monkeypatch):
    """UN ROJO PRESTADO QUE NO ES MIO, y por eso se neutraliza aqui.

    `tanda3` fija `AHORA` en una fecha ya pasada y el plan tiene
    `plan_ttl_seconds = 86400`: desde entonces CUALQUIER `_b_completo` sale
    `REJECTED` por `PLAN_EXPIRED` y no hay nada que revertir. No se relaja
    ningun TTL ni se toca el fichero ajeno: se le da al plan la hora VIVA, que
    es la que el mando ve en produccion.
    """
    ahora = (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    monkeypatch.setattr(tanda3, "AHORA", ahora)


@pytest.fixture(scope="module")
def conexion():
    """Contenedor PROPIO, con prefijo propio, destruido al salir.

    No se comparte con otros ficheros a proposito: alguno hace
    `MATCH (n) DETACH DELETE n` y deja el grafo vacio para el siguiente, y una
    calibracion sobre un grafo vacio se pone roja por la razon equivocada.
    """
    with neo4j_efimero_conexion("s9k-tanda11-incompleto") as cx:
        yield cx


@pytest.fixture
def limpio(conexion):
    with conexion.driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    return conexion


# --- utillaje ---------------------------------------------------------------
def _cuenta(driver, cypher, params=None):
    """UNA consulta por cosa contada. Dos `MATCH` sueltos dan cartesiano."""
    with driver.session() as s:
        filas = [r.data() for r in s.run(cypher, params or {})]
    return int(filas[0]["c"]) if filas else 0


def _grafo_aplicado(driver):
    """Deja el grafo como lo deja un apply REAL y devuelve su documento.

    Comprueba que el conjunto de partida NO esta vacio: sin eso, cualquier
    comparacion posterior demuestra cualquier cosa.
    """
    informe = _b_completo(driver)
    assert informe["write"]["outcome"] == "APPLIED", informe["write"]
    nodos = _cuenta(driver, "MATCH (n) RETURN count(n) AS c")
    assert nodos > 0, "conjunto de partida VACIO: no se puede medir nada"
    return informe["rollback"]


def _guardar_doc(tmp_path, doc, nombre):
    destino = tmp_path / nombre
    destino.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destino


def _indice_de(doc, accion):
    for i, instr in enumerate(doc["instructions"]):
        if instr["action"] == accion:
            return i
    raise AssertionError(f"el documento del producto no trae {accion}: {doc}")


def _sin_identidad_durable(doc, accion):
    """Documento con UNA instruccion no reconstruible. La forma heredada."""
    mutado = copy.deepcopy(doc)
    idx = _indice_de(mutado, accion)
    detalle = mutado["instructions"][idx]["detail"]
    quitados = [k for k in list(detalle) if k in CAMPOS_DURABLES]
    assert quitados, f"la instruccion {accion} no traia identidad que quitar"
    for k in quitados:
        detalle.pop(k)
    return mutado


def _sin_la_instruccion(doc, accion):
    """Documento al que le falta una instruccion: su objetivo SOBREVIVE."""
    mutado = copy.deepcopy(doc)
    mutado["instructions"].pop(_indice_de(mutado, accion))
    return mutado


# --- las cuatro mutaciones de calibracion -----------------------------------
# Cada una revierte UNA fila de la tabla, y solo una. Se aplican sobre
# `cli_rollback.decide_outcome`, que es EL punto de decision.
def _mut_regla_anterior(report):
    """La regla que habia antes: un bit, dos salidas. Mata `INCOMPLETE`."""
    return (
        cli_rollback.OUTCOME_ROLLED_BACK
        if report.clean
        else cli_rollback.OUTCOME_UNEXPECTED_RESIDUE
    )


def _mut_residuo_no_cuenta(report):
    """El residuo deja de decidir. Revierte la fila 2."""
    if report.not_reconstructible:
        return cli_rollback.OUTCOME_INCOMPLETE
    return cli_rollback.OUTCOME_ROLLED_BACK


def _mut_prioridad_invertida(report):
    """Lo irreconstruible gana al residuo. Revierte la fila 3."""
    if report.not_reconstructible:
        return cli_rollback.OUTCOME_INCOMPLETE
    if report.residues:
        return cli_rollback.OUTCOME_UNEXPECTED_RESIDUE
    return cli_rollback.OUTCOME_ROLLED_BACK


def _mut_incompleto_demasiado_ancho(report):
    """`INCOMPLETE` sin exigir irreconstruibles. Revierte la fila 4."""
    if report.residues:
        return cli_rollback.OUTCOME_UNEXPECTED_RESIDUE
    return cli_rollback.OUTCOME_INCOMPLETE


# ===========================================================================
# FILA 1 -- irreconstruible > 0, residuo = 0 -> INCOMPLETE, rc != 0
# ===========================================================================
def test_fila1_irreconstruible_sin_residuo_sale_INCOMPLETE(limpio, tmp_path, capsys):
    """El caso que el producto NO podia nombrar. Es el encargo entero.

    ANTES de este cambio, medido con Neo4j real y este mismo documento:
    `UNEXPECTED_RESIDUE`, `rc=1`, «NO es una reversion limpia: 0 residuos y 1
    puntos no revertidos». Un fallo de postcondicion afirmado sobre un
    postestado que no lo sostiene.
    """
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(
        tmp_path, _sin_identidad_durable(doc, ACTION_DELETE_RELATIONSHIP), "f1.json"
    )

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)
    informe = salida["report"]

    # Las DOS premisas de la fila, observadas -- no presumidas.
    assert len(informe["not_reconstructible"]) > 0, informe
    assert informe["residues"] == [], informe["residues"]

    assert salida["outcome"] == cli_rollback.OUTCOME_INCOMPLETE, salida
    assert rc != 0, salida
    assert salida["hechos"]["not_reconstructible"] == len(
        informe["not_reconstructible"]
    )
    # La prosa no puede afirmar el fallo que el grafo no sostiene.
    assert "NO es una reversion limpia" not in salida["human"], salida["human"]
    assert "INCOMPLETA" in salida["human"], salida["human"]


def test_CALIBRACION_fila1_con_la_regla_anterior_vuelve_a_ser_RESIDUO(
    limpio, tmp_path, capsys, monkeypatch
):
    """Con la decision de antes reinyectada, la fila 1 se pone ROJA.

    Y por la causa correcta: el desenlace pasa a ser EXACTAMENTE
    `UNEXPECTED_RESIDUE` --lo que se medio antes del cambio--, no un rojo
    cualquiera. El grafo es el mismo y NO esta vacio.
    """
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(
        tmp_path, _sin_identidad_durable(doc, ACTION_DELETE_RELATIONSHIP), "f1c.json"
    )
    monkeypatch.setattr(cli_rollback, "decide_outcome", _mut_regla_anterior)

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)

    assert salida["report"]["residues"] == [], "el escenario dejo de ser el de la fila 1"
    assert len(salida["report"]["not_reconstructible"]) > 0
    assert salida["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, (
        "con la regla anterior el desenlace NO vuelve a `UNEXPECTED_RESIDUE`: "
        "entonces la fila 1 no la sostiene `decide_outcome` y mide otra cosa"
    )
    assert rc != 0


# ===========================================================================
# FILA 2 -- irreconstruible = 0, residuo > 0 -> UNEXPECTED_RESIDUE, rc != 0
# ===========================================================================
def test_fila2_residuo_sin_irreconstruible_sale_UNEXPECTED_RESIDUE(
    limpio, tmp_path, capsys
):
    """Lo que ya funcionaba, que este cambio NO podia romper."""
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(
        tmp_path, _sin_la_instruccion(doc, ACTION_DELETE_NODE), "f2.json"
    )

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)
    informe = salida["report"]

    assert informe["not_reconstructible"] == [], informe["not_reconstructible"]
    assert len(informe["residues"]) > 0, informe

    assert salida["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, salida
    assert rc != 0, salida
    assert "NO es una reversion limpia" in salida["human"], salida["human"]


def test_CALIBRACION_fila2_si_el_residuo_no_decide_deja_de_ser_RESIDUO(
    limpio, tmp_path, capsys, monkeypatch
):
    """Si el residuo dejase de decidir, esta fila saldria `ROLLED_BACK`."""
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(
        tmp_path, _sin_la_instruccion(doc, ACTION_DELETE_NODE), "f2c.json"
    )
    monkeypatch.setattr(cli_rollback, "decide_outcome", _mut_residuo_no_cuenta)

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)

    assert len(salida["report"]["residues"]) > 0, "el escenario perdio su residuo"
    assert salida["outcome"] == cli_rollback.OUTCOME_ROLLED_BACK, (
        "con el residuo sin decidir el desenlace NO se afloja: la fila 2 no la "
        "sostiene `decide_outcome`"
    )
    assert rc == 0


# ===========================================================================
# FILA 3 -- los dos a la vez -> UNEXPECTED_RESIDUE, y lo otro INFORMADO
# ===========================================================================
def test_fila3_los_dos_a_la_vez_manda_el_RESIDUO_y_el_otro_hecho_se_conserva(
    limpio, tmp_path, capsys
):
    """El desenlace es el fallo mas fuerte; el informe conserva AMBOS hechos.

    Un desenlace no puede llevar dos nombres. Un informe si puede llevar dos
    hechos, y aqui se exige que los lleve: estructurados (`hechos`,
    `not_reconstructible`) y en la prosa.
    """
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(
        tmp_path, _sin_identidad_durable(doc, ACTION_DELETE_NODE), "f3.json"
    )

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)
    informe = salida["report"]

    assert len(informe["not_reconstructible"]) > 0, informe
    assert len(informe["residues"]) > 0, informe

    assert salida["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, salida
    assert rc != 0, salida
    # AMBOS hechos, en el canal estructurado.
    assert salida["hechos"]["residues"] == len(informe["residues"])
    assert salida["hechos"]["not_reconstructible"] == len(
        informe["not_reconstructible"]
    )
    # Y en la prosa, que es de donde se entera un operador.
    assert "NO es una reversion limpia" in salida["human"], salida["human"]
    assert "not_reconstructible" in salida["human"], salida["human"]


def test_CALIBRACION_fila3_con_la_prioridad_invertida_sale_INCOMPLETE(
    limpio, tmp_path, capsys, monkeypatch
):
    """Si mandase lo irreconstruible, este caso se llamaria `INCOMPLETE`.

    Es la mutacion que de verdad revierte ESTA fila: la de la regla anterior
    no serviria, porque aqui tambien daria `UNEXPECTED_RESIDUE` y el control
    saldria verde sin probar nada.
    """
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(
        tmp_path, _sin_identidad_durable(doc, ACTION_DELETE_NODE), "f3c.json"
    )
    monkeypatch.setattr(cli_rollback, "decide_outcome", _mut_prioridad_invertida)

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)

    assert len(salida["report"]["residues"]) > 0, "el escenario perdio su residuo"
    assert len(salida["report"]["not_reconstructible"]) > 0
    assert salida["outcome"] == cli_rollback.OUTCOME_INCOMPLETE, (
        "con la prioridad invertida el desenlace NO cambia: la fila 3 no la "
        "sostiene el orden de `decide_outcome`"
    )
    assert rc != 0


# ===========================================================================
# FILA 4 -- ninguno de los dos -> ROLLED_BACK, rc = 0
# ===========================================================================
def test_fila4_sin_residuo_ni_irreconstruible_sale_ROLLED_BACK(
    limpio, tmp_path, capsys
):
    """La reversion exacta sigue valiendo `rc = 0`. Ningun gate se estrecha."""
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(tmp_path, doc, "f4.json")

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)
    informe = salida["report"]

    assert informe["residues"] == [], informe["residues"]
    assert informe["not_reconstructible"] == [], informe["not_reconstructible"]

    assert salida["outcome"] == cli_rollback.OUTCOME_ROLLED_BACK, salida
    assert rc == 0, salida
    assert salida["hechos"]["clean"] is True, salida["hechos"]


def test_CALIBRACION_fila4_si_INCOMPLETE_se_ensancha_el_verde_se_pierde(
    limpio, tmp_path, capsys, monkeypatch
):
    """Sin exigir irreconstruibles, `INCOMPLETE` se comeria el caso limpio.

    Es la mutacion que revierte ESTA fila, y la que demuestra que el `rc = 0`
    de una reversion exacta lo sostiene la condicion nueva y no una casualidad.
    """
    driver = limpio.driver
    doc = _grafo_aplicado(driver)
    ruta = _guardar_doc(tmp_path, doc, "f4c.json")
    monkeypatch.setattr(
        cli_rollback, "decide_outcome", _mut_incompleto_demasiado_ancho
    )

    rc, salida = ejecutar_mando(driver, ruta, capsys=capsys)

    assert salida["report"]["residues"] == [], "el escenario dejo de ser limpio"
    assert salida["outcome"] == cli_rollback.OUTCOME_INCOMPLETE, (
        "ensanchando `INCOMPLETE` el desenlace SIGUE siendo `ROLLED_BACK`: "
        "entonces la fila 4 no la sostiene `decide_outcome`"
    )
    assert rc != 0

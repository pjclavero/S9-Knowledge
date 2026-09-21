# -*- coding: utf-8 -*-
"""EL ESTADO DE UN PLAN, EXPLICADO POR LA CAUSA QUE EL SISTEMA CONOCE.

EL DEFECTO, medido por un operador. Tras un apply rechazado por restricciones
de esquema, la MISMA pantalla decía dos cosas incompatibles:

  · el aviso hablaba de restricciones que faltan;
  · y el bloque del plan, tres centímetros más abajo: «Una decisión cambió
    después de preparar lo aprobado… vuelve a prepararlo para incluir la
    decisión nueva».

NINGUNA decisión había cambiado. El operador siguió el consejo de la pantalla
—Preparar → Añadir— y volvió a fallar idénticamente: **el consejo era un
bucle**.

EL PRODUCTO YA SABÍA DISTINGUIRLO, Y SÓLO EN UN SITIO
=====================================================
`PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO` existe, está en `CODIGOS` y se deriva de
`apply_notes_json` —columna que sólo escribe `record_apply_result`—. Pero
únicamente en el POST del SEGUNDO intento. El render GET del estado
`superseded` tenía una rama única y contaba el primero de los tres caminos como
si fuera el único.

Así que este corte no inventa una inferencia: reúne la que ya había
(`v3_apply.causa_de_superseded`) y la usa en los dos sitios.

LO QUE ESTOS TESTIGOS PIDEN
===========================
La PANTALLA (`GET` del hueco de operaciones) y el marcado que emite. Un testigo
sobre `estado().to_dict()` habría seguido verde con la plantilla equivocada,
que es exactamente donde vivía el defecto.
"""
from __future__ import annotations

import json
import re

import pytest

# Fixtures y utillaje del arnés de apply, reusados TAL CUAL: `real_app`,
# `paneles_on`, `cola`, `operador`, `almacenes`, `_aprobar_una`, `_sellar`,
# `_aplicar`, `_panel`, `_bloque_plan`, `_filas_de_plan`, `SLOT_B`…
#
# No se copian aquí: una copia del arnés es una segunda verdad sobre cómo se
# monta el panel, y el día que la original cambie esta seguiría verde midiendo
# un producto que ya no existe.
# Se importan POR NOMBRE, nunca con `*`: un `import *` arrastra además los
# ~40 casos de aquel módulo y los vuelve a ejecutar bajo este fichero. Se midió:
# 33 rojos que no eran de este corte.
from test_panel_apply_desde_la_ui import (  # noqa: F401
    SELLADO_DEL_ARNES,
    _aplicar,
    _aprobar_una,
    _aviso_de,
    _bloque_plan,
    _filas_de_plan,
    _panel,
    _sellar,
)

# Las FIXTURES, también por nombre. Las tres primeras son `autouse=True` en su
# módulo y lo siguen siendo aquí: sin ellas la ingesta del panel no encuentra
# conexión declarada al grafo y todos los casos mueren con
# `GRAPH_OBSERVATION_UNCONFIGURED`, que no es un rojo de este corte.
from test_panel_apply_desde_la_ui import (  # noqa: F401,E402
    _entorno_limpio,
    _grafo_de_mentira,
    _salud_aislada,
    almacenes,
    auth_on,
    cola,
    operador,
    paneles_on,
    real_app,
)

CAUSA_APPLY = "PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO"
CAUSA_GENERICA = "PLAN_SUPERSEDED"

#: La frase del defecto, tal y como la pantalla la emitía. Se busca sin tildes
#: y en trozo corto porque lo que importa es la ATRIBUCIÓN, no la redacción.
FRASE_DEL_DEFECTO = "Una decisi"


def _superseded_por_apply_fallido(operador, cola, almacenes, monkeypatch):
    """Deja la corrida con un plan `superseded` POR UNA ESCRITURA FALLIDA.

    Por la UI entera: aprobar → sellar → aplicar contra un grafo inalcanzable.
    No se toca el almacén a mano en ningún punto: el estado y la columna que lo
    explica los deja el producto, y esta función los comprueba antes de
    devolver. Si los fabricara este arnés, la prueba mediría su propia siembra.
    """
    from app.config import get_settings

    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    # Grafo INALCANZABLE: el writer rechaza de verdad, no se simula el fallo.
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", "no-importa")
    get_settings.cache_clear()

    _aplicar(operador, job_id)

    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["state"] == "superseded", (
        f"el plan quedó en {fila['state']!r}: sin `superseded` esta prueba no "
        f"mide la rama que viene a arreglar")
    assert fila["apply_notes_json"], (
        "el apply fallido no dejó notas: sin ellas el producto NO puede "
        "distinguir el camino y este arnés estaría midiendo el caso genérico "
        "creyendo que mide el específico")
    return job_id


# ===========================================================================
# 1. EL DEFECTO, en la pantalla
# ===========================================================================
def test_la_pantalla_no_culpa_a_una_decision_de_lo_que_fue_un_apply_fallido(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """EL CASO DEL DEFECTO. GET del panel, bloque del plan, causa nombrada."""
    from app import panel_errors
    from app.config import get_settings

    job_id = _superseded_por_apply_fallido(operador, cola, almacenes, monkeypatch)

    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque, "el bloque del plan no se ha pintado: no hay nada que medir"
    assert bloque["desenlace"] == ["superseded"], bloque["desenlace"]

    assert bloque["atributos"].get("causa") == CAUSA_APPLY, (
        f"el bloque del plan publica la causa "
        f"{bloque['atributos'].get('causa')!r}: la pantalla sigue sin "
        f"distinguir un apply fallido de un cambio de decisión")
    assert FRASE_DEL_DEFECTO not in bloque["texto"], (
        "la pantalla sigue achacando a una decisión lo que fue una escritura "
        "fallida, y con ello sigue aconsejando un bucle")
    assert panel_errors.CATALOGO[CAUSA_APPLY] in bloque["texto"], (
        "la causa se publica como código pero la pantalla no la traduce")
    get_settings.cache_clear()


def test_la_pantalla_y_el_error_del_segundo_intento_dicen_LO_MISMO(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """LA COSTURA. Dos superficies, una sola causa.

    El defecto no era que el producto no supiera: era que lo sabía en el POST y
    no en el GET. Este caso ata las dos y es el que enrojece si vuelven a
    separarse.
    """
    from app.config import get_settings

    job_id = _superseded_por_apply_fallido(operador, cola, almacenes, monkeypatch)

    segundo = _aviso_de(_aplicar(operador, job_id))
    assert segundo == CAUSA_APPLY, segundo

    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"].get("causa") == segundo, (
        f"el POST dice {segundo!r} y el GET dice "
        f"{bloque['atributos'].get('causa')!r} sobre EL MISMO plan")
    get_settings.cache_clear()


# ===========================================================================
# 2. CONTROL POSITIVO EN SENTIDO CONTRARIO
# ===========================================================================
# Sin esto, la forma más fácil de aprobar lo de arriba sería cablear
# `PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO` en la plantilla y decírselo a TODOS los
# planes supersedidos —incluidos aquellos en los que sí cambió una decisión—.
# Eso sería fabricar una causa que el dato no contiene, que es la mitad
# prohibida de este corte.

def test_un_superseded_SIN_notas_de_apply_no_se_atribuye_a_un_apply_fallido(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """El camino que el dato NO distingue sale con el código GENÉRICO.

    Se llega por la ruta real: sellar y volver a sellar. `_supersede_sealed`
    sólo toca `state`, así que la fila queda `superseded` con
    `apply_notes_json` a NULL — el caso en el que no hay forma de saber cuál de
    los dos primeros caminos fue.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    filas = _filas_de_plan(almacenes["base"])
    supersedidas = [f for f in filas if f["state"] == "superseded"]
    assert supersedidas, (
        "el resellado no dejó ningún plan supersedido: este control no está "
        "midiendo nada")
    assert not supersedidas[0]["apply_notes_json"], (
        "la fila trae notas de apply y este control esperaba el caso SIN "
        "notas: estaría midiendo la misma rama que el caso de arriba")


def test_la_inferencia_distingue_los_dos_casos_por_ENUMERACION():
    """La autoridad única, y la trampa que tiene dentro.

    `record_apply_result` escribe `canonical(sorted(set(notes or ())))`, que
    para una lista vacía es la CADENA `"[]"`. Sobre la lista ya parseada eso es
    `()` —falso—, y decidir ahí haría que un apply fallido SIN notas se leyera
    como un cambio de decisión. La cuarta fila de esta tabla es ese caso, y es
    la razón de que la función mire la columna cruda.

    NINGÚN `assert` DE AQUÍ VA SIN SU FRASE, y no es estilo. Tres de ellos la
    llevaban implícita y enrojecían con la comparación pelada de pytest
    (`assert 'PLAN_SUPERSE...' == 'PLAN_SUPERSEDED'`). Eso no sólo se lee mal:
    el arnés de calibración daba por buena esa mutación porque buscaba el
    substring `"PLAN_SUPERSEDED"`, ¡que aparece dentro de la propia comparación
    pelada! El control que debía cazar el rojo mudo pasaba por coincidencia de
    texto. Se arreglaron las dos mitades: la frase, aquí; el criterio, en el
    calibrador.
    """
    from app.services.v3_apply import causa_de_superseded

    # NO SE CALLA LA CAUSA QUE SE SABE: con notas, hubo un apply que terminó mal.
    assert causa_de_superseded(
        {"apply_notes_json": '["EXEC_DRIVER_FAILURE"]'}) == CAUSA_APPLY, (
        "una fila CON notas de apply no se está atribuyendo a la escritura "
        "fallida que las escribió: vuelve el consejo en bucle")
    # NO SE FABRICA LA CAUSA QUE NO SE SABE: sin notas no hubo `finish_apply`.
    assert causa_de_superseded({"apply_notes_json": None}) == CAUSA_GENERICA, (
        "una fila SIN notas de apply se está atribuyendo a un apply fallido: "
        "eso es fabricar una causa que el dato no contiene")
    assert causa_de_superseded({}) == CAUSA_GENERICA, (
        "una fila sin la columna se está atribuyendo a un apply fallido: "
        "eso es fabricar una causa que el dato no contiene")
    # EL CASO FINO: apply fallido que no emitió ni un código.
    assert causa_de_superseded({"apply_notes_json": "[]"}) == CAUSA_APPLY, (
        "un apply fallido sin notas se está leyendo como un cambio de "
        "decisión: la inferencia ha pasado a mirar la lista parseada")
    assert causa_de_superseded(None) == CAUSA_GENERICA, (
        "sin fila se está afirmando un apply fallido: "
        "eso es fabricar una causa que el dato no contiene")


def test_los_dos_codigos_de_causa_estan_declarados_y_se_saben_traducir():
    """Un código que la pantalla no supiera traducir saldría en blanco, y un
    desenlace mudo se lee como «no ha pasado nada»."""
    from app import panel_errors
    from app.services.v3_apply import CODIGOS

    for codigo in (CAUSA_APPLY, CAUSA_GENERICA):
        assert codigo in CODIGOS, codigo
        assert panel_errors.CATALOGO.get(codigo), codigo

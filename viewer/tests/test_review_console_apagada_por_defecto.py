# -*- coding: utf-8 -*-
"""PR-1 (USABLE-V1) — `/review-console` NO se monta por defecto.

El panel v1 (laboratorio, Equipo B) servía siempre `src_demo_01`/`src_demo_02`
desde fixtures del repo, sin estar en `NAV` ni enlazado desde ninguna otra
pantalla salvo él mismo, con `POST …/decide` vivo: un revisor que tecleara la
URL podía decidir sobre datos de laboratorio creyendo revisar de verdad —
falsa confirmación con efecto de escritura.

Decisión del operador (D1): no se convierte en consola de producto ni se
conecta al motor real; se deja de montar por defecto. `S9K_REVIEW_CONSOLE_ENABLED`
reutiliza EXACTAMENTE la misma autoridad que `app.routers.resultado` usa para
`/panel/resultado` (`app.config.effective_env_value` + `chassis.FLAG_ON_VALUES`,
fallo cerrado, se lee en cada petición).

Este testigo mide las TRES rutas, no sólo la de entrada: `GET /review-console`,
`GET /review-console/source/{id}` y `POST /review-console/source/{id}/decide`
— el `POST` es el que importa de verdad, porque es el que escribe.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers import reviews_console as rc_router
from app.services import review_console as rc

FLAG = "S9K_REVIEW_CONSOLE_ENABLED"


def _client(lector_por_dependencia=None):
    """Cliente de la consola. Con `lector_por_dependencia` instala un lector
    LEGÍTIMO (ver `conftest.py`): sin él, el ámbito anónimo no entrega la capa
    juego y los tests de control positivo (bandera encendida) no verían nada
    que no sea por la propia bandera. Los de apagada no lo necesitan: el 404
    por interruptor ocurre ANTES de tocar el ámbito."""
    from app.main import app
    if lector_por_dependencia is not None:
        lector_por_dependencia(app)
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Estado de fábrica: la clave AUSENTE del entorno (ni siquiera "false")
# ---------------------------------------------------------------------------
def test_sin_la_clave_en_el_entorno_get_inbox_da_404(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    r = _client().get("/review-console")
    assert r.status_code == 404


def test_sin_la_clave_en_el_entorno_get_detalle_da_404_por_el_interruptor(
    monkeypatch, lector_por_dependencia
):
    """Discrimina POR CAUSA: con un lector legítimo EN ámbito de
    `src_demo_01` (`lector_por_dependencia`), el único 404 posible es el del
    interruptor (`APAGADA` = "No encontrado"), no el del filtro de ámbito
    anónimo (que da un cuerpo distinto: "Fuente no encontrada: …"). Sin el
    lector, este 404 sería indistinguible del de ámbito -- por eso antes
    quedaba fuera de M1; ya no hace falta: con lector en ámbito, SÍ se
    puede exigir."""
    monkeypatch.delenv(FLAG, raising=False)
    r = _client(lector_por_dependencia).get("/review-console/source/src_demo_01")
    assert r.status_code == 404
    assert r.json()["detail"] == rc_router.APAGADA


def test_sin_la_clave_en_el_entorno_post_decide_da_404(monkeypatch):
    """EL CASO QUE IMPORTA: el `POST` que escribe también da 404 apagado."""
    monkeypatch.delenv(FLAG, raising=False)
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)["value"]
    r = _client().post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "APPROVE",
              "expected_candidate_hash": ch},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Valores que NO encienden: ausente, vacía, "false", ininteligible
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["false", "0", "", "no", "TRUE_PERO_MAL"])
def test_valores_que_no_encienden_siguen_dando_404(monkeypatch, valor):
    monkeypatch.setenv(FLAG, valor)
    assert _client().get("/review-console").status_code == 404


# ---------------------------------------------------------------------------
# Control positivo: encendida, sigue viva (laboratorio legítimo)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["true", "1", "True", "TRUE"])
def test_encendida_el_get_inbox_sigue_vivo(monkeypatch, valor, lector_por_dependencia):
    monkeypatch.setenv(FLAG, valor)
    r = _client(lector_por_dependencia).get("/review-console")
    assert r.status_code == 200
    assert "src_demo_01" in r.text


def test_encendida_el_post_decide_sigue_escribiendo(monkeypatch, tmp_path, lector_por_dependencia):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setenv("S9K_REVIEW_LAB_DIR", str(tmp_path))
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)["value"]
    r = _client(lector_por_dependencia).post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "APPROVE",
              "expected_candidate_hash": ch},
    )
    assert r.status_code == 303
    assert len(rc.read_decisions(tmp_path)) == 1


# ---------------------------------------------------------------------------
# Regresión: la función no vuelve a leer el entorno a pelo (misma guarda que
# S-3 exige para chassis.slot_enabled y resultado._encendido) -- POR AST, NO
# POR TEXTO. Una comparación de texto (`"os.environ.get(" not in fuente`) la
# pasan al menos cuatro reintroducciones medidas del defecto: `os.getenv(x)`
# (la forma MÁS idiomática), `os.environ[x]`, `os.environ .get(x)` (con un
# espacio) y `environ.get(x)` (tras `from os import environ`). Y el segundo
# `assert` ("effective_env_value" in fuente) se satisface aunque la función
# LLAME a `effective_env_value` e ignore el resultado por completo.
#
# Aquí se comprueban dos PROPIEDADES sobre el AST de la función, no sobre su
# texto:
#   (1) ninguna lectura del entorno por otra vía: ningún nodo del AST es un
#       atributo/nombre `environ` o `getenv`, en NINGUNA forma sintáctica
#       (atributo, subíndice, alias de import) -- el AST ya ignora espacios y
#       formas de llamada, así que una sola comprobación cubre las cuatro
#       variantes de arriba.
#   (2) el valor que la función DEVUELVE procede de una variable asignada
#       directamente desde una llamada a `effective_env_value`: tiene que
#       existir un `Assign` `var = effective_env_value(...)` Y al menos un
#       `Return` cuya expresión use ese `var` -- no basta con que la cadena
#       "effective_env_value" aparezca en el cuerpo.
#
# TECHO DECLARADO DE ESTA RED: no cierra el aliasing dinámico -- una lectura
# construida en tiempo de ejecución (`getattr(os, "env" + "iron")`,
# `os.__dict__["environ"]`, `importlib.import_module("os").environ`, o pasar
# el NOMBRE de la función por una variable antes de llamarla) no la ve.
# Tampoco demuestra que `effective_env_value` en sí sea correcta -- eso lo
# cubre su propio módulo. Lo que demuestra es la propiedad estructural: esta
# función concreta no tiene una segunda vía de lectura del entorno y su
# devuelto depende de verdad de la autoridad única.
# ---------------------------------------------------------------------------
import ast as _ast  # noqa: E402


def _lecturas_de_entorno_fuera_de_effective_env_value(funcdef: _ast.FunctionDef) -> list[str]:
    """Nombres/atributos que leen el entorno por una vía DISTINTA de
    `effective_env_value`, en cualquier forma sintáctica. Devuelve la lista
    de hallazgos (vacía si no hay ninguno)."""
    hallazgos = []
    for nodo in _ast.walk(funcdef):
        if isinstance(nodo, _ast.Attribute) and nodo.attr in ("environ", "getenv"):
            hallazgos.append(nodo.attr)
        elif isinstance(nodo, _ast.Name) and nodo.id in ("environ", "getenv"):
            hallazgos.append(nodo.id)
    return hallazgos


def _retorno_procede_de_effective_env_value(funcdef: _ast.FunctionDef) -> bool:
    """¿Existe una variable asignada DIRECTAMENTE desde una llamada a
    `effective_env_value`, y al menos un `return` de la función construye su
    valor a partir de esa variable? Si la llamada se hace pero el resultado
    se descarta (no se asigna, o se asigna y no se usa en ningún `return`),
    es `False`."""
    variables_de_effective_env_value = set()
    for nodo in _ast.walk(funcdef):
        if (
            isinstance(nodo, _ast.Assign)
            and isinstance(nodo.value, _ast.Call)
            and isinstance(nodo.value.func, (_ast.Name, _ast.Attribute))
            and getattr(nodo.value.func, "id", getattr(nodo.value.func, "attr", None))
            == "effective_env_value"
        ):
            for objetivo in nodo.targets:
                if isinstance(objetivo, _ast.Name):
                    variables_de_effective_env_value.add(objetivo.id)

    if not variables_de_effective_env_value:
        return False

    for nodo in _ast.walk(funcdef):
        if isinstance(nodo, _ast.Return) and nodo.value is not None:
            nombres_usados = {
                n.id for n in _ast.walk(nodo.value) if isinstance(n, _ast.Name)
            }
            if nombres_usados & variables_de_effective_env_value:
                return True
    return False


def _funcdef_de(fuente: str, nombre: str) -> _ast.FunctionDef:
    arbol = _ast.parse(fuente)
    for nodo in _ast.walk(arbol):
        if isinstance(nodo, _ast.FunctionDef) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"no se encontró la función {nombre!r} en la fuente dada")


def test_encendido_no_lee_el_entorno_por_otra_via_y_su_devuelto_procede_de_la_autoridad():
    import inspect
    from app.routers import reviews_console

    funcdef = _funcdef_de(inspect.getsource(reviews_console._encendido), "_encendido")
    assert _lecturas_de_entorno_fuera_de_effective_env_value(funcdef) == []
    assert _retorno_procede_de_effective_env_value(funcdef)


# Las CUATRO reintroducciones medidas del defecto que la comparación de texto
# anterior dejaba pasar: las cuatro deben poner la propiedad (1) en rojo.
@pytest.mark.parametrize("variante,fuente_mutada", [
    ("os.getenv (idiomatica)", """
def _encendido():
    raw = __import__("os").getenv(FLAG_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in valores
"""),
    ("os.environ[x] (subindice)", """
def _encendido():
    import os
    raw = os.environ[FLAG_ENV]
    return raw.strip().lower() in valores
"""),
    ("os.environ .get(x) (con espacio)", """
def _encendido():
    import os
    raw = os.environ .get(FLAG_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in valores
"""),
    ("environ.get(x) (alias de import)", """
def _encendido():
    from os import environ
    raw = environ.get(FLAG_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in valores
"""),
])
def test_las_cuatro_reintroducciones_medidas_ponen_la_propiedad_en_rojo(variante, fuente_mutada):
    funcdef = _funcdef_de(fuente_mutada, "_encendido")
    hallazgos = _lecturas_de_entorno_fuera_de_effective_env_value(funcdef)
    assert hallazgos, f"la variante {variante!r} debía detectarse y no se detectó"


# El segundo defecto medido: la función LLAMA a `effective_env_value` pero
# ignora el resultado por completo -- el `assert "effective_env_value" in
# fuente` de antes lo dejaba pasar.
def test_llamar_a_effective_env_value_e_ignorar_el_resultado_pone_la_propiedad_en_rojo():
    fuente_mutada = """
def _encendido():
    effective_env_value(FLAG_ENV)  # resultado descartado
    return True
"""
    funcdef = _funcdef_de(fuente_mutada, "_encendido")
    assert not _retorno_procede_de_effective_env_value(funcdef)


def test_asignar_desde_effective_env_value_y_no_usarlo_en_ningun_return_pone_la_propiedad_en_rojo():
    fuente_mutada = """
def _encendido():
    raw = effective_env_value(FLAG_ENV)
    return True
"""
    funcdef = _funcdef_de(fuente_mutada, "_encendido")
    assert not _retorno_procede_de_effective_env_value(funcdef)

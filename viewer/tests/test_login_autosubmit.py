# -*- coding: utf-8 -*-
"""Contrato del formulario de login: ENVIO EXCLUSIVAMENTE EXPLICITO.

Historia: en móvil, la tecla "Ir" del teclado disparaba el envío implícito del
formulario mientras el operador aún escribía; con autofill del gestor de
contraseñas el POST salía con credenciales erróneas (el email como username) y
el login "desaparecía" repintado con los campos vacíos.

El contrato nuevo (orden del operador): el POST solo puede producirse pulsando
el botón visible. Enter dentro de los campos NO envía. El botón es
type="button" y una compuerta JS en closure llama a requestSubmit() solo tras
un click explícito; el evento submit se cancela si no está armado.

Estos tests validan el MECANISMO en el template. La CONSECUENCIA en un
navegador real la validan viewer/tests/browser/.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "auth" / "login.html"


@pytest.fixture()
def html() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# El botón: única puerta de entrada
# ---------------------------------------------------------------------------

def test_el_boton_es_type_button(html):
    """type=submit permitiría el envío implícito del navegador; type=button no."""
    boton = re.search(r'<button[^>]*id="login-submit"[^>]*>', html).group(0)
    assert 'type="button"' in boton, boton


def test_no_hay_ningun_boton_submit(html):
    assert 'type="submit"' not in html


def test_el_boton_no_usa_formaction(html):
    assert "formaction" not in html


# ---------------------------------------------------------------------------
# La compuerta JS
# ---------------------------------------------------------------------------

def test_la_compuerta_usa_requestSubmit_no_submit(html):
    """form.submit() saltaría la validación y el evento submit: prohibido."""
    assert "requestSubmit()" in html
    assert re.search(r"\bform\.submit\(\)", html) is None


def test_el_estado_vive_en_un_closure(html):
    """La autorización no puede ser falsificable desde otra variable global."""
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert "(function ()" in script, "el script no está encerrado en un IIFE"
    assert "window.armed" not in script
    assert "window.submitting" not in script


def test_enter_en_campos_queda_cancelado(html):
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert '"keydown"' in script
    assert 'event.key === "Enter"' in script
    assert "event.preventDefault()" in script


def test_el_submit_no_autorizado_se_cancela_en_captura(html):
    """La escucha de submit va en fase de captura: un requestSubmit externo no
    puede colarse por delante."""
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert re.search(r'addEventListener\("submit",.*?\}, true\)', script, re.S), (
        "el listener de submit no está en fase de captura"
    )
    assert "stopImmediatePropagation" in script


def test_bfcache_reactiva_el_boton(html):
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert '"pageshow"' in script


def test_hay_aviso_noscript(html):
    assert "<noscript>" in html


# ---------------------------------------------------------------------------
# La validación nativa sigue viva
# ---------------------------------------------------------------------------

def test_el_formulario_no_lleva_novalidate(html):
    form = re.search(r"<form[^>]*>", html).group(0)
    assert "novalidate" not in form, form


def test_los_campos_siguen_siendo_required(html):
    for campo in ("username", "password"):
        bloque = re.search(rf'<input[^>]*name="{campo}".*?>', html, re.S).group(0)
        assert "required" in bloque, bloque


def test_checkValidity_antes_de_armar(html):
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert "checkValidity()" in script
    assert "reportValidity()" in script


# ---------------------------------------------------------------------------
# CSRF y campos intactos
# ---------------------------------------------------------------------------

def test_el_csrf_sigue_en_el_formulario(html):
    assert 'name="csrf_token"' in html


def test_los_nombres_de_campo_no_cambian(html):
    for name in ("username", "password", "next", "csrf_token"):
        assert f'name="{name}"' in html


def test_autocomplete_para_gestores_de_contrasenas(html):
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html


def test_solo_hay_un_formulario(html):
    assert html.count("<form") == 1

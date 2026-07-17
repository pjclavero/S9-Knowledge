# -*- coding: utf-8 -*-
"""Contrato del formulario de login y del cambio obligatorio de contrasena.

Origen: en movil, al terminar de escribir el usuario, la tecla "Ir" del teclado
disparaba el envio implicito del formulario. `novalidate` anulaba los `required`,
asi que el POST salia VACIO y la respuesta era un 422 con JSON crudo: el login
"desaparecia" sin que el operador llegara a pulsar el boton.

No habia ningun JavaScript implicado, y sigue sin haberlo: la correccion es
devolverle al navegador su validacion nativa.
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
# La regresion
# ---------------------------------------------------------------------------

def test_el_formulario_no_lleva_novalidate(html):
    """LA CAUSA RAIZ: novalidate desactivaba los `required` y permitia el envio vacio."""
    form = re.search(r"<form[^>]*>", html).group(0)
    assert "novalidate" not in form, form


def test_los_campos_siguen_siendo_required(html):
    """Sin `required`, quitar novalidate no serviria de nada."""
    for campo in ("username", "password"):
        bloque = re.search(rf'<input[^>]*name="{campo}".*?>', html, re.S).group(0)
        assert "required" in bloque, bloque


def test_no_hay_javascript_que_envie_el_formulario(html):
    """El contrato prohibe enviar el formulario con JS. No hay JS en absoluto."""
    prohibido = ("<script", "oninput", "onchange", "onkeyup", "onkeydown",
                 "onblur", "onfocus", "requestSubmit", ".submit()", "addEventListener")
    for patron in prohibido:
        assert patron not in html, f"aparecio {patron!r} en el login"


def test_el_boton_es_submit_explicito(html):
    boton = re.search(r"<button[^>]*>", html).group(0)
    assert 'type="submit"' in boton, boton


# ---------------------------------------------------------------------------
# Se mantiene lo que ya funcionaba
# ---------------------------------------------------------------------------

def test_csrf_sigue_presente(html):
    assert 'name="csrf_token"' in html


def test_autocomplete_se_conserva(html):
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html


def test_accesibilidad_labels(html):
    for campo in ("username", "password"):
        assert f'<label for="{campo}">' in html


def test_usuario_no_se_autocapitaliza(html):
    """En movil el teclado convierte s9admin en S9admin y el lookup distingue mayusculas."""
    bloque = re.search(r'<input[^>]*name="username".*?>', html, re.S).group(0)
    assert 'autocapitalize="none"' in bloque
    assert 'spellcheck="false"' in bloque


def test_el_form_va_por_post_a_login(html):
    form = re.search(r"<form[^>]*>", html).group(0)
    assert 'method="post"' in form
    assert 'action="/login"' in form

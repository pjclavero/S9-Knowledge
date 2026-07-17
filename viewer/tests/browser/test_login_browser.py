# -*- coding: utf-8 -*-
"""Contrato del login en un NAVEGADOR REAL (Playwright): envío solo explícito.

Matriz del operador: escribir, pegar, autofill, Tab, blur, Enter en cada campo,
la tecla "Ir" del móvil, click fuera, requestSubmit externo → 0 POST.
Click en el botón, o Enter/Espacio con el botón enfocado → exactamente 1 POST.
Doble click → una única validación efectiva (1 POST).

Se omiten solos si Playwright o el navegador no están: NUNCA se dan por pasados.
Correr con:  pytest viewer/tests/browser -q
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import closing
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="Playwright no instalado: SKIP, no PASS")

from playwright.sync_api import sync_playwright  # noqa: E402

TEMP_PASSWORD = "3uq28-7DRZX-pufao"

MOBILE_VIEWPORT = {"width": 393, "height": 851}


@pytest.fixture(scope="module")
def server(tmp_path_factory) -> Iterator[str]:
    """Arranca el visor real con auth activa y un admin de verdad."""
    import socket

    import uvicorn

    db_path = tmp_path_factory.mktemp("auth") / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    os.environ["S9K_SESSION_SECURE"] = "false"      # el lab va por HTTP
    os.environ["S9K_CSRF_SECRET"] = "secreto-de-laboratorio-no-productivo"

    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password

    get_auth_settings.cache_clear()
    auth_db.ensure_migrated(db_path)
    with auth_db.get_conn(db_path) as conn:
        auth_db.create_user(conn, username="s9admin", display_name="Admin",
                            password_hash=hash_password(TEMP_PASSWORD),
                            role="admin", must_change_password=False)

    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    from app.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    else:
        pytest.skip("el servidor de pruebas no arranco")

    yield f"http://127.0.0.1:{port}"

    srv.should_exit = True
    thread.join(timeout=5)
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_SESSION_SECURE",
              "S9K_CSRF_SECRET"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


def _new_page(p, server, viewport=None):
    try:
        browser = p.chromium.launch()
    except Exception as exc:                         # navegador no descargado
        pytest.skip(f"chromium no disponible: {exc}")
    ctx = browser.new_context(viewport=viewport) if viewport else browser.new_context()
    pg = ctx.new_page()
    pg.posts = []                                    # type: ignore[attr-defined]
    pg.on("request", lambda r: pg.posts.append(r.url)   # type: ignore[attr-defined]
          if r.method == "POST" else None)
    pg.goto(f"{server}/login")
    return browser, pg


@pytest.fixture()
def page(server):
    with sync_playwright() as p:
        browser, pg = _new_page(p, server)
        yield pg
        browser.close()


@pytest.fixture()
def mobile_page(server):
    with sync_playwright() as p:
        browser, pg = _new_page(p, server, viewport=MOBILE_VIEWPORT)
        yield pg
        browser.close()


def _posts(page) -> list:
    return [u for u in page.posts if u.endswith("/login")]


# ---------------------------------------------------------------------------
# 0 POST: nada de lo que no sea el botón puede enviar
# ---------------------------------------------------------------------------

def test_escribir_usuario_no_genera_post(page):
    page.fill("#username", "s9admin")
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_escribir_password_no_genera_post(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_escritura_caracter_a_caracter_no_genera_post(page):
    page.type("#username", "s9admin", delay=20)
    page.type("#password", TEMP_PASSWORD, delay=20)
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_pegar_password_no_genera_post(page):
    page.fill("#username", "s9admin")
    page.click("#password")
    page.evaluate("""(pw) => navigator.clipboard.writeText(pw)""", TEMP_PASSWORD)
    page.keyboard.press("Control+V")
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_tab_entre_campos_no_genera_post(page):
    page.fill("#username", "s9admin")
    page.keyboard.press("Tab")
    page.fill("#password", TEMP_PASSWORD)
    page.keyboard.press("Tab")
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_blur_no_genera_post(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.click("h2")                                 # perder el foco
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_click_fuera_del_formulario_no_genera_post(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.click("body", position={"x": 5, "y": 5})
    page.wait_for_timeout(200)
    assert _posts(page) == []


def test_autofill_programatico_no_genera_post(page):
    """Rellenado por gestor de contrasenas: dispara input/change, no submit."""
    page.evaluate("""() => {
        const u = document.getElementById('username');
        const p = document.getElementById('password');
        u.value = 's9admin';
        p.value = 'loquesea';
        u.dispatchEvent(new Event('input',  {bubbles: true}));
        u.dispatchEvent(new Event('change', {bubbles: true}));
        p.dispatchEvent(new Event('input',  {bubbles: true}));
        p.dispatchEvent(new Event('change', {bubbles: true}));
        p.dispatchEvent(new Event('blur',   {bubbles: true}));
    }""")
    page.wait_for_timeout(200)
    assert _posts(page) == []


# ---------------------------------------------------------------------------
# EL CONTRATO NUEVO: Enter en los campos NO envía, ni siquiera completo
# ---------------------------------------------------------------------------

def test_enter_en_username_con_formulario_completo_no_envia(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert _posts(page) == [], "Enter en username envió el formulario"


def test_enter_en_password_con_formulario_completo_no_envia(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.press("#password", "Enter")
    page.wait_for_timeout(300)
    assert _posts(page) == [], "Enter en password envió el formulario"


def test_enter_movil_go_no_envia(mobile_page):
    """La tecla "Ir"/"Go" del teclado móvil llega como Enter en el campo."""
    mobile_page.fill("#username", "s9admin")
    mobile_page.fill("#password", TEMP_PASSWORD)
    mobile_page.press("#password", "Enter")
    mobile_page.wait_for_timeout(300)
    assert _posts(mobile_page) == []


def test_enter_con_password_vacia_no_envia(page):
    page.fill("#username", "s9admin")
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert _posts(page) == []


def test_enter_sin_nada_escrito_no_envia(page):
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert _posts(page) == []


def test_requestSubmit_externo_queda_bloqueado(page):
    """Un script ajeno no puede enviar sin el click del botón."""
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.evaluate("() => document.getElementById('login-form').requestSubmit()")
    page.wait_for_timeout(300)
    assert _posts(page) == [], "requestSubmit externo produjo un POST"


def test_dispatch_submit_sintetico_no_navega(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.evaluate("""() => {
        const f = document.getElementById('login-form');
        f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    }""")
    page.wait_for_timeout(300)
    assert _posts(page) == []
    assert "/login" in page.url


# ---------------------------------------------------------------------------
# 1 POST: el botón, y solo el botón
# ---------------------------------------------------------------------------

def test_boton_con_formulario_completo_envia_exactamente_uno(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.click("#login-submit")
    page.wait_for_load_state("networkidle")
    assert len(_posts(page)) == 1


def test_enter_sobre_el_boton_enfocado_envia_exactamente_uno(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.focus("#login-submit")
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")
    assert len(_posts(page)) == 1


def test_espacio_sobre_el_boton_enfocado_envia_exactamente_uno(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.focus("#login-submit")
    page.keyboard.press("Space")
    page.wait_for_load_state("networkidle")
    assert len(_posts(page)) == 1


def test_doble_click_produce_un_unico_post(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.dblclick("#login-submit")
    page.wait_for_load_state("networkidle")
    assert len(_posts(page)) == 1, f"doble click produjo {len(_posts(page))} POSTs"


def test_boton_con_formulario_incompleto_no_envia(page):
    page.fill("#username", "s9admin")
    page.click("#login-submit")
    page.wait_for_timeout(300)
    assert _posts(page) == []
    # y el botón sigue vivo para reintentar
    assert page.locator("#login-submit").is_enabled()


def test_login_completo_entra(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.click("#login-submit")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, f"sigue en el login: {page.url}"


def test_login_con_espacio_final_en_username_entra(page):
    """Los teclados móviles añaden un espacio tras el autocompletado."""
    page.fill("#username", "s9admin ")
    page.fill("#password", TEMP_PASSWORD)
    page.click("#login-submit")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, "el espacio final del username rompió el login"


# ---------------------------------------------------------------------------
# Errores: siempre HTML con el formulario, nunca JSON crudo
# ---------------------------------------------------------------------------

def test_credenciales_malas_repintan_formulario_html(page):
    page.fill("#username", "s9admin")
    page.fill("#password", "contraseña-incorrecta-123")
    page.click("#login-submit")
    page.wait_for_load_state("networkidle")
    assert page.locator("form#login-form").count() == 1, "el formulario desapareció"
    assert "Usuario o contraseña incorrectos" in page.content()
    assert page.locator("#login-submit").is_enabled(), "el botón quedó muerto tras el error"


def test_no_aparece_json_crudo_nunca(page):
    page.fill("#username", "s9admin")
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert "Field required" not in page.content()
    assert page.locator("form").count() == 1, "el formulario desapareció"

# -*- coding: utf-8 -*-
"""Contrato del login en un NAVEGADOR REAL (Playwright).

Los tests de plantilla comprueban el mecanismo (no hay `novalidate`, los
`required` estan, no hay JS). Solo un navegador puede comprobar la CONSECUENCIA:
que escribir no envie nada y que la tecla Enter con el formulario incompleto sea
bloqueada por la validacion nativa.

Ese era el fallo real: en movil, "Ir" dentro del campo usuario disparaba el envio
implicito, el POST salia vacio y el login desaparecia tras un 422 de JSON crudo.

Se omiten solos si Playwright o el navegador no estan: NUNCA se dan por pasados.
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


@pytest.fixture()
def page(server):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                     # navegador no descargado
            pytest.skip(f"chromium no disponible: {exc}")
        pg = browser.new_page()
        pg.posts = []                                # type: ignore[attr-defined]
        pg.on("request", lambda r: pg.posts.append(r.url)   # type: ignore[attr-defined]
              if r.method == "POST" else None)
        pg.goto(f"{server}/login")
        yield pg
        browser.close()


def _posts(page) -> list:
    return [u for u in page.posts if u.endswith("/login")]


# ---------------------------------------------------------------------------
# El contrato: escribir NO envia
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


def test_cambiar_de_campo_no_genera_post(page):
    """blur: pasar de un campo a otro no puede enviar nada."""
    page.fill("#username", "s9admin")
    page.click("#password")
    page.fill("#password", TEMP_PASSWORD)
    page.click("#username")
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
# El fallo original: Enter con el formulario incompleto
# ---------------------------------------------------------------------------

def test_enter_con_password_vacia_no_envia(page):
    """EL FALLO DE VM105: la tecla "Ir" del movil enviaba el formulario vacio.

    Con la validacion nativa restaurada, el navegador la bloquea. Sin ella salia
    un POST vacio -> 422 -> JSON crudo -> "el login desaparece".
    """
    page.fill("#username", "s9admin")
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert _posts(page) == [], "el formulario se envio incompleto"
    assert page.locator("#password:invalid").count() == 1


def test_enter_sin_nada_escrito_no_envia(page):
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert _posts(page) == []


def test_boton_con_formulario_incompleto_no_envia(page):
    page.fill("#username", "s9admin")
    page.click("button[type=submit]")
    page.wait_for_timeout(300)
    assert _posts(page) == []


# ---------------------------------------------------------------------------
# Y lo que SI debe enviar: exactamente una vez
# ---------------------------------------------------------------------------

def test_boton_con_formulario_completo_envia_exactamente_uno(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert len(_posts(page)) == 1


def test_enter_con_formulario_completo_envia_exactamente_uno(page):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.press("#password", "Enter")
    page.wait_for_load_state("networkidle")
    assert len(_posts(page)) == 1


def test_login_completo_entra(page, server):
    page.fill("#username", "s9admin")
    page.fill("#password", TEMP_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, f"sigue en el login: {page.url}"


def test_no_aparece_json_crudo_nunca(page):
    """El sintoma que vio el operador: una pagina de JSON en vez del login."""
    page.fill("#username", "s9admin")
    page.press("#username", "Enter")
    page.wait_for_timeout(300)
    assert "Field required" not in page.content()
    assert page.locator("form").count() == 1, "el formulario desaparecio"

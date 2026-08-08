# -*- coding: utf-8 -*-
"""Infraestructura compartida de las pruebas de navegador (Playwright).

Extiende la que ya existia para `test_login_browser.py` (servidor uvicorn real +
Playwright sincrono) y la generaliza para todo el producto: varios roles, varias
pestanas simultaneas, captura de errores de consola y utilidades de login.

PRINCIPIO INNEGOCIABLE
----------------------
Aqui NO se simula la autorizacion. El servidor que se arranca es la app real
(`app.main:app`) con `S9K_AUTH_ENABLED=true`, una base de auth SQLite de verdad,
sesiones server-side reales y los mismos guardas de rol que produccion. Lo unico
sustituido es el ORIGEN DE DATOS del grafo (`S9K_GRAPH_PROVIDER=mock`), que es un
proveedor del propio producto y no forma parte de la frontera de autorizacion que
estas pruebas intentan comprobar.

El alcance de las fixtures es de MODULO, igual que en `test_login_browser.py`:
cada modulo arranca su propio servidor y limpia sus variables de entorno al
terminar. Compartir un servidor de sesion con aquel modulo romperia sus
`cache_clear()` de teardown.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

import pytest

pytest.importorskip("playwright.sync_api", reason="Playwright no instalado: SKIP, no PASS")

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

# Contrasenas de LABORATORIO. No existen fuera de la base temporal que crea cada
# modulo de prueba; ninguna corresponde a una credencial real de ningun entorno.
ADMIN_PW = "lab-admin-3uq28-7DRZX"
REVIEWER_PW = "lab-reviewer-8kd91-QWERT"
VIEWER_PW = "lab-viewer-2mz47-ASDFG"
DISABLED_PW = "lab-disabled-9pl03-ZXCVB"

DESKTOP_VIEWPORT = {"width": 1280, "height": 800}
MOBILE_VIEWPORT = {"width": 393, "height": 851}

# Mensajes de consola que NO cuentan como error grave del producto: ruido del
# navegador o del entorno de laboratorio, no defectos de la aplicacion.
_CONSOLE_NOISE = (
    "favicon",
    "Failed to load resource: the server responded with a status of 404",
    "net::ERR_",
    "Download the React DevTools",
)


@dataclass
class ViewerServer:
    """Un visor real corriendo en un puerto libre, con su base de auth."""

    base_url: str
    db_path: str
    users: dict = field(default_factory=dict)

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"


def _free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


_ENV_KEYS = (
    "S9K_AUTH_ENABLED",
    "S9K_AUTH_DB_PATH",
    "S9K_SESSION_SECURE",
    "S9K_CSRF_SECRET",
    "S9K_GRAPH_PROVIDER",
    "S9K_NEO4J_URI",
    "S9K_NEO4J_USER",
    "S9K_NEO4J_PASSWORD",
    "S9K_JOBS_DB",
    "S9K_DEFAULT_WORKSPACE",
)


def start_viewer(tmp_path_factory, *, env: Optional[dict] = None,
                 seed_users: bool = True) -> Iterator[ViewerServer]:
    """Arranca el visor real. Generador: usar desde una fixture con `yield from`.

    `env` permite reconfigurar el proveedor de grafo u otras variables ANTES de
    importar la app, que es cuando se leen las settings cacheadas.
    """
    import uvicorn

    db_path = tmp_path_factory.mktemp("authdb") / "auth.db"

    previous = {k: os.environ.get(k) for k in _ENV_KEYS}
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    os.environ["S9K_SESSION_SECURE"] = "false"       # el laboratorio va por HTTP
    os.environ["S9K_CSRF_SECRET"] = "secreto-de-laboratorio-no-productivo"
    os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
    for key, value in (env or {}).items():
        os.environ[key] = value

    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.config import get_settings
    from app.deps import get_provider

    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()

    auth_db.ensure_migrated(db_path)
    users: dict = {}
    if seed_users:
        specs = [
            ("s9admin", "Admin de laboratorio", ADMIN_PW, "admin", True),
            ("s9reviewer", "Revisor de laboratorio", REVIEWER_PW, "reviewer", True),
            ("s9viewer", "Viewer de laboratorio", VIEWER_PW, "viewer", True),
            ("s9disabled", "Cuenta desactivada", DISABLED_PW, "viewer", False),
        ]
        with auth_db.get_conn(db_path) as conn:
            for username, display, pw, role, active in specs:
                user = auth_db.create_user(
                    conn,
                    username=username,
                    display_name=display,
                    password_hash=hash_password(pw),
                    role=role,
                    must_change_password=False,
                )
                users[username] = {"id": user.id, "password": pw, "role": role}
                if not active:
                    # Desactivacion por la via real del producto: la misma
                    # funcion que usa el panel de admin.
                    auth_db.update_user(conn, user_id=user.id, is_active=False)

    port = _free_port()
    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.skip("el servidor de pruebas no arranco")

    try:
        yield ViewerServer(base_url=f"http://127.0.0.1:{port}",
                           db_path=str(db_path), users=users)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_auth_settings.cache_clear()
        get_settings.cache_clear()
        get_provider.cache_clear()

def attach_recorders(page: Page) -> Page:
    """Registra en la pagina los errores de consola y las excepciones JS."""
    page.console_errors = []                          # type: ignore[attr-defined]
    page.page_errors = []                             # type: ignore[attr-defined]

    def _on_console(msg):
        if msg.type != "error":
            return
        text = msg.text or ""
        if any(noise in text for noise in _CONSOLE_NOISE):
            return
        page.console_errors.append(text)              # type: ignore[attr-defined]

    page.on("console", _on_console)
    page.on("pageerror", lambda exc: page.page_errors.append(str(exc)))  # type: ignore[attr-defined]
    return page


def create_lab_user(viewer: ViewerServer, username: str, *, role: str = "viewer",
                    password: Optional[str] = None, active: bool = True) -> dict:
    """Crea un usuario nuevo en la base de auth del visor de laboratorio.

    Es PREPARACION de datos, no la frontera bajo prueba: las pruebas que mutan el
    estado de un usuario (desactivarlo, revocarle las sesiones) necesitan su
    propio usuario para no envenenar a las demas del modulo. La autenticacion y
    la autorizacion se siguen ejerciendo enteras contra el servidor real.
    """
    from pathlib import Path

    from app.auth import db as auth_db
    from app.auth.passwords import hash_password

    pw = password or f"lab-{username}-7HJ21-qwerty"
    with auth_db.get_conn(Path(viewer.db_path)) as conn:
        user = auth_db.create_user(
            conn,
            username=username,
            display_name=f"Usuario {username}",
            password_hash=hash_password(pw),
            role=role,
            must_change_password=False,
        )
        if not active:
            auth_db.update_user(conn, user_id=user.id, is_active=False)
    entry = {"id": user.id, "password": pw, "role": role}
    viewer.users[username] = entry
    return entry


def do_login(page: Page, viewer: ViewerServer, username: str, password: str,
             *, next_url: str = "/") -> Page:
    """Inicia sesion como lo haria una persona: formulario y boton."""
    page.goto(viewer.url(f"/login?next={next_url}"))
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-submit")
    page.wait_for_load_state("networkidle")
    return page


def login_as(page: Page, viewer: ViewerServer, username: str, **kwargs) -> Page:
    return do_login(page, viewer, username, viewer.users[username]["password"], **kwargs)


def is_logged_in(page: Page) -> bool:
    return "/login" not in page.url


def fetch_status(page: Page, viewer: ViewerServer, path: str) -> int:
    """Codigo HTTP FINAL de una navegacion, con las cookies reales de la pagina.

    Ojo: `goto` sigue las redirecciones, asi que un 302 al login se observa aqui
    como un 200 (el del formulario de login). Para decidir si el acceso fue
    denegado hay que mirar tambien la URL final: usar `is_denied`.
    """
    response = page.goto(viewer.url(path), wait_until="domcontentloaded")
    return response.status if response is not None else -1


def is_denied(page: Page, viewer: ViewerServer, path: str) -> tuple[bool, int, str]:
    """Navega a `path` y dice si el visor DENEGO el acceso.

    Denegado = 401/403, o redireccion al formulario de login. Devuelve tambien
    status y URL final para que el mensaje de fallo sea util.
    """
    status = fetch_status(page, viewer, path)
    url = page.url
    denied = status in (401, 403) or "/login" in url
    return denied, status, url


def is_allowed(page: Page, viewer: ViewerServer, path: str) -> bool:
    denied, status, _ = is_denied(page, viewer, path)
    return (not denied) and status == 200

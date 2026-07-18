"""conftest.py de tests/e2e — utilidades de laboratorio para los E2E.

Fase 1 (este PR): la mayoría de E2E están skip/xfail porque dependen de endpoints
y funciones que los EQUIPOS A (auth/sesión), B (data-engine review/ingest) y
C (viewer routes/authz) aún no han publicado. Aquí se dejan preparados:

  - `require_playwright`: skip limpio si Playwright/navegador no están (nunca PASS
    falso), igual que en viewer/tests/browser.
  - `lab_viewer_server`: arranque de un visor LOCAL (127.0.0.1, puerto efímero,
    SQLite temporal) reutilizable por los E2E cuando A/B/C expongan las rutas.
    Se marca xfail/skip hasta entonces.

El cortafuegos de producción (tests/conftest.py) sigue activo aquí: cualquier
E2E que intente salir a producción abortará.
"""
from __future__ import annotations

import os
import socket
from contextlib import closing
from typing import Iterator

import pytest


@pytest.fixture(scope="session")
def require_playwright():
    """Devuelve sync_playwright o hace SKIP (nunca PASS) si no está disponible."""
    pytest.importorskip("playwright.sync_api", reason="Playwright no instalado: SKIP, no PASS")
    from playwright.sync_api import sync_playwright  # noqa: WPS433

    return sync_playwright


def _free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def lab_env(tmp_path_factory) -> Iterator[dict[str, str]]:
    """Entorno de laboratorio: SQLite temporal + secretos no productivos.

    NO arranca el servidor todavía: los E2E que lo requieran están skip hasta que
    A/B/C publiquen las rutas de review/ingest/permisos. Cuando existan, este
    fixture se ampliará para lanzar uvicorn contra 127.0.0.1:_free_port().
    """
    db_path = tmp_path_factory.mktemp("e2e_auth") / "auth.db"
    env = {
        "S9K_AUTH_ENABLED": "true",
        "S9K_AUTH_DB_PATH": str(db_path),
        "S9K_SESSION_SECURE": "false",
        "S9K_CSRF_SECRET": "secreto-de-laboratorio-no-productivo",
        "S9K_ALLOW_REAL_INGEST": "",  # ingesta real SIEMPRE desactivada en tests
        "S9K_LAB_PORT": str(_free_port()),
    }
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield env
    finally:
        for k, old in previous.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old

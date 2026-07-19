"""conftest.py de tests/e2e — arnés E2E REAL contra el producto integrado.

Fase 2 (A/B/C ya en main): los E2E ejercitan la app FastAPI real vía TestClient
in-process, con autenticación real (usuarios + sesiones + CSRF reales) y la
autorización real del visor (contexto RPG + PolicyFilteredProvider de C). Lo
UNICO que se sustituye por un doble de laboratorio es la FUENTE DE DATOS
(``get_provider`` -> MockGraphProvider sobre una fixture anonimizada): nunca se
mockea la autorizacion, el endpoint bajo prueba, el control optimista ni la
persistencia de decisiones.

El cortafuegos de produccion (tests/conftest.py) permanece activo: cualquier
intento de salir a produccion aborta la suite.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterator, Optional

import pytest

# --- viewer en sys.path (sin tocar tests/logica de otros equipos) -----------
_VIEWER_ROOT = Path(__file__).resolve().parents[2] / "viewer"


def _ensure_viewer_importable() -> None:
    if str(_VIEWER_ROOT) not in sys.path:
        sys.path.insert(0, str(_VIEWER_ROOT))
    # En corrida combinada, data-engine puede haber registrado su propio paquete
    # 'app' en sys.modules. Limpiamos los 'app.*' que no apunten al viewer para
    # forzar la resolucion correcta desde _VIEWER_ROOT/app (mismo patron que
    # viewer/tests/conftest.py).
    viewer_app = _VIEWER_ROOT / "app"
    stale = [
        name for name, mod in list(sys.modules.items())
        if (name == "app" or name.startswith("app."))
        and not (getattr(mod, "__file__", None) and str(viewer_app) in str(mod.__file__))
    ]
    for name in stale:
        sys.modules.pop(name, None)


def _clear_caches() -> None:
    try:
        from app.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Playwright (compat con fase 1): SKIP limpio, nunca PASS falso
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def require_playwright():
    pytest.importorskip("playwright.sync_api", reason="Playwright no instalado: SKIP, no PASS")
    from playwright.sync_api import sync_playwright  # noqa: WPS433

    return sync_playwright


# ---------------------------------------------------------------------------
# Arnes E2E
# ---------------------------------------------------------------------------
def _csrf_from_html(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, "no se encontro csrf_token en el HTML"
    return m.group(1)


class E2EHarness:
    """Utilidades de laboratorio para conducir E2E reales."""

    def __init__(self, db_path: Path, lab_dir: Path, graph_path: Path):
        self.db_path = db_path
        self.lab_dir = lab_dir
        self.graph_path = graph_path
        from app.main import app  # import diferido tras fijar el entorno
        self._app = app

    # -- usuarios/sesiones reales -------------------------------------------
    def make_user(self, username: str, role: str, password: str = "LabPass_1234567890!"):
        from app.auth import db as auth_db_mod
        from app.auth.passwords import hash_password
        with auth_db_mod.get_conn(self.db_path) as conn:
            return auth_db_mod.create_user(
                conn, username=username, display_name=username.title(),
                password_hash=hash_password(password), role=role,
            )

    def session_token(self, user) -> str:
        from app.auth import db as auth_db_mod
        from app.auth.sessions import create_session
        with auth_db_mod.get_conn(self.db_path) as conn:
            token, _ = create_session(conn, user)
        return token

    def revoke(self, token: str) -> None:
        from app.auth import db as auth_db_mod
        from app.auth.sessions import revoke_session_by_token
        with auth_db_mod.get_conn(self.db_path) as conn:
            revoke_session_by_token(conn, token)

    def client(self, user=None, token: Optional[str] = None):
        from app.auth.config import get_auth_settings
        from fastapi.testclient import TestClient
        c = TestClient(self._app, raise_server_exceptions=False, follow_redirects=False)
        if token is None and user is not None:
            token = self.session_token(user)
        if token is not None:
            c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
        return c

    @staticmethod
    def csrf_from_html(html: str) -> str:
        return _csrf_from_html(html)


@pytest.fixture
def e2e(tmp_path) -> Iterator[E2EHarness]:
    """Arnes E2E: auth real (SQLite temporal), visor con provider de laboratorio.

    NUNCA toca produccion ni Neo4j: el provider es un doble de laboratorio y la
    ingesta real esta desactivada. La autorizacion (rol -> contexto RPG ->
    PolicyFilteredProvider) es la REAL del producto.
    """
    _ensure_viewer_importable()

    db_path = tmp_path / "e2e_auth.db"
    lab_dir = tmp_path / "review_lab"
    lab_dir.mkdir(parents=True, exist_ok=True)
    graph_path = Path(__file__).resolve().parents[1] / "fixtures" / "e2e_rpg_graph.json"

    env = {
        "S9K_AUTH_ENABLED": "true",
        "S9K_AUTH_DB_PATH": str(db_path),
        "S9K_SESSION_SECURE": "false",
        "S9K_CSRF_SECRET": "secreto-de-laboratorio-e2e-no-productivo-0123456789",
        "S9K_ALLOW_REAL_INGEST": "",  # ingesta real SIEMPRE desactivada
        "S9K_DEFAULT_WORKSPACE": "leyenda",
        "S9K_GRAPH_PROVIDER": "mock",
        "S9K_SAMPLE_GRAPH_PATH": str(graph_path),
        "S9K_REVIEW_LAB_DIR": str(lab_dir),
    }
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    _clear_caches()

    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)

    # Sustituye SOLO la fuente de datos por un doble de laboratorio; la
    # autorizacion sigue siendo la real (get_filtered_provider envuelve esto).
    from app.deps import get_provider
    from app.providers.mock_provider import MockGraphProvider
    from app.main import app
    lab_provider = MockGraphProvider(graph_path)
    app.dependency_overrides[get_provider] = lambda: lab_provider

    harness = E2EHarness(db_path, lab_dir, graph_path)
    try:
        yield harness
    finally:
        app.dependency_overrides.pop(get_provider, None)
        for k, old in previous.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        _clear_caches()

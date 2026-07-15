"""Tests del visor de solo lectura (Tarea C): entidades paginadas, fuentes, vendoring."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parents[1]


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


# ---------------------------------------------------------------------------
# API /api/entities (auth off => público, provider mock)
# ---------------------------------------------------------------------------

def test_api_entities_envelope():
    r = _client().get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 200
    j = r.json()
    for k in ("workspace", "query", "entity_type", "total", "limit", "offset", "has_more", "items"):
        assert k in j
    assert isinstance(j["items"], list)


def test_api_entities_pagination():
    c = _client()
    r1 = c.get("/api/entities?limit=1&offset=0")
    j1 = r1.json()
    assert len(j1["items"]) <= 1
    assert j1["limit"] == 1
    if j1["total"] > 1:
        assert j1["has_more"] is True
        r2 = c.get("/api/entities?limit=1&offset=1")
        assert r2.json()["items"] != j1["items"]


def test_api_entities_filter_type():
    r = _client().get("/api/entities?entity_type=Character&limit=100")
    for it in r.json()["items"]:
        assert it["type"] == "Character"


def test_api_entities_limit_capped():
    # limit fuera de rango -> 422 (validación ge/le), no explota
    assert _client().get("/api/entities?limit=99999").status_code == 422


# ---------------------------------------------------------------------------
# Página HTML /entities
# ---------------------------------------------------------------------------

def test_entities_page_renders():
    r = _client().get("/entities", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "Entidades" in r.text


# ---------------------------------------------------------------------------
# vis-network vendorizado (sin CDN)
# ---------------------------------------------------------------------------

def test_graph_no_cdn():
    html = (VIEWER / "app/templates/graph.html").read_text(encoding="utf-8")
    # Ningún <script src> externo (unpkg/jsdelivr/http(s) remoto)
    assert "unpkg" not in html and "jsdelivr" not in html
    assert 'src="https://' not in html and 'src="http://' not in html
    assert "/static/js/vendor/vis-network.min.js" in html
    assert "integrity=" in html  # SRI presente


def test_vendor_file_present():
    f = VIEWER / "app/static/js/vendor/vis-network.min.js"
    assert f.exists() and f.stat().st_size > 100_000


# ---------------------------------------------------------------------------
# Solo lectura: el router no expone métodos de escritura
# ---------------------------------------------------------------------------

def test_readonly_router_has_no_write_methods():
    from app.routers import readonly
    for route in readonly.router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert not (methods & {"POST", "PUT", "PATCH", "DELETE"}), route.path


# ---------------------------------------------------------------------------
# Roles con auth activada
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_env(tmp_path):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-tests-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)
    yield db
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


def _cookie(db, username, role):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    with auth_db.get_conn(db) as conn:
        u = auth_db.create_user(conn, username=username, display_name=username,
                                password_hash=hash_password("x" * 14), role=role)
        token, _ = create_session(conn, u)
    return token


def test_api_entities_anon_401(auth_env):
    r = _client().get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 401


def test_entities_html_anon_redirect(auth_env):
    r = _client().get("/entities", headers={"accept": "text/html"})
    assert r.status_code == 302 and "/login" in r.headers.get("location", "")


def test_sources_viewer_forbidden(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "v", "viewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/sources", headers={"accept": "text/html"}).status_code == 403


def test_sources_reviewer_ok(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "rev", "reviewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/sources", headers={"accept": "text/html"}).status_code == 200


def test_entities_viewer_ok(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "v2", "viewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/entities", headers={"accept": "text/html"}).status_code == 200

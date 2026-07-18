"""Enforcement extremo a extremo vía API con autenticación activada.

Usa el grafo de ejemplo (sample_graph.json), que contiene un nodo `secret`
(n_culto_pozo_viejo) y un nodo `narrator` (n_bayushi_hisao). Con auth ON:
  - un viewer NO los ve por listado ni por acceso directo (404),
  - un admin SÍ los ve.
"""
from __future__ import annotations

import os

import pytest

SECRET_ID = "n_culto_pozo_viejo"     # visibility=secret en el sample
NARRATOR_ID = "n_bayushi_hisao"      # visibility=narrator en el sample


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


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


def _authed(db, username, role):
    from app.auth.config import get_auth_settings
    tok = _cookie(db, username, role)
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    return c


def test_viewer_no_ve_secreto_en_listado(auth_env):
    c = _authed(auth_env, "vw1", "viewer")
    r = c.get("/api/entities?limit=200", headers={"accept": "application/json"})
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert SECRET_ID not in ids
    assert NARRATOR_ID not in ids


def test_viewer_acceso_directo_secreto_404(auth_env):
    c = _authed(auth_env, "vw2", "viewer")
    assert c.get(f"/api/entities/{SECRET_ID}").status_code == 404
    assert c.get(f"/api/entities/{NARRATOR_ID}").status_code == 404


def test_admin_si_ve_secreto(auth_env):
    c = _authed(auth_env, "ad1", "admin")
    r = c.get("/api/entities?limit=200")
    ids = {i["id"] for i in r.json()["items"]}
    assert SECRET_ID in ids
    assert c.get(f"/api/entities/{SECRET_ID}").status_code == 200


def test_viewer_conteo_quality_no_incluye_secreto(auth_env):
    # /api/quality es reviewer+; un reviewer tampoco ve secretos ajenos.
    c = _authed(auth_env, "rv1", "reviewer")
    r = c.get("/api/quality")
    assert r.status_code == 200
    by_vis = r.json().get("by_visibility", {})
    assert by_vis.get("secret", 0) == 0

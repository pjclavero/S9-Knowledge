"""Tests del endurecimiento de seguridad de autenticación (Fase A4/A5).

Cubre: protección estricta de APIs (401/403 JSON), CSRF de login real
(firmado, temporal, double-submit), validación de arranque (secreto CSRF y
backend de contraseñas), middleware fail-closed, gating de /docs y aislamiento
(sin escritura en Neo4j ni en el writer de ingesta).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_env(tmp_path):
    """Activa auth con una DB temporal y un secreto CSRF fuerte."""
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    os.environ["S9K_CSRF_SECRET"] = "una-clave-csrf-larga-y-aleatoria-de-test-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    yield db_path
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_AUTH_EXPOSE_DOCS"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


def _make_user(db_path, username, role, password="TestPass_1234567890!"):
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    with auth_db_mod.get_conn(db_path) as conn:
        return auth_db_mod.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(password), role=role,
        )


def _session_cookie(db_path, user):
    from app.auth import db as auth_db_mod
    from app.auth.sessions import create_session
    with auth_db_mod.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    return token


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


# Endpoints de API que deben exigir sesión (viewer+).
API_ENDPOINTS = [
    "/api/status",
    "/api/workspaces",
    "/api/entity-types",
    "/api/search?q=x",
    "/api/graph",
    "/api/jobs",
    "/api/jobs/counts",
]


# ---------------------------------------------------------------------------
# A5.1 — cada API anónima devuelve 401 JSON
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", API_ENDPOINTS)
def test_api_anonymous_returns_401(auth_env, path):
    client = _client()
    resp = client.get(path, headers={"accept": "application/json"})
    assert resp.status_code == 401, f"{path} debería ser 401 anónimo"
    # Respuesta JSON, no HTML ni redirección
    assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# A5.2 — usuario autenticado (viewer) accede a las APIs viewer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", API_ENDPOINTS)
def test_api_viewer_authenticated_ok(auth_env, path):
    user = _make_user(auth_env, "viewer_api", "viewer")
    token = _session_cookie(auth_env, user)
    from app.auth.config import get_auth_settings
    cfg = get_auth_settings()
    client = _client()
    client.cookies.set(cfg.S9K_SESSION_COOKIE_NAME, token)
    resp = client.get(path, headers={"accept": "application/json"})
    assert resp.status_code == 200, f"{path} debería ser accesible por viewer"


def test_api_public_when_auth_disabled(tmp_path):
    """Con auth desactivada las APIs siguen siendo públicas (sin cambios)."""
    os.environ.pop("S9K_AUTH_ENABLED", None)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    client = _client()
    resp = client.get("/api/status", headers={"accept": "application/json"})
    assert resp.status_code == 200
    get_auth_settings.cache_clear()


# ---------------------------------------------------------------------------
# A5.4-8 — CSRF de login real (unitario: válido / vacío / aleatorio / caducado)
# ---------------------------------------------------------------------------

SECRET = "secreto-de-test-para-csrf-login-0123456789"


def test_login_csrf_valid():
    from app.auth.csrf import issue_login_csrf, validate_login_csrf
    tok = issue_login_csrf(SECRET)
    assert validate_login_csrf(tok, tok, secret=SECRET) is True


def test_login_csrf_empty_fails():
    from app.auth.csrf import validate_login_csrf
    assert validate_login_csrf("", "", secret=SECRET) is False
    assert validate_login_csrf(None, None, secret=SECRET) is False


def test_login_csrf_random_unsigned_fails():
    from app.auth.csrf import validate_login_csrf
    fake = "1784116114.noncefalso.deadbeefdeadbeef"
    assert validate_login_csrf(fake, fake, secret=SECRET) is False


def test_login_csrf_cookie_mismatch_fails():
    """Un token válido pero que no coincide con la cookie (no ligado al navegador)."""
    from app.auth.csrf import issue_login_csrf, validate_login_csrf
    a = issue_login_csrf(SECRET)
    b = issue_login_csrf(SECRET)
    assert validate_login_csrf(a, b, secret=SECRET) is False


def test_login_csrf_expired_fails():
    from app.auth.csrf import issue_login_csrf, validate_login_csrf
    tok = issue_login_csrf(SECRET)
    # Simula "ahora" muy posterior a la emisión
    later = int(tok.split(".")[0]) + 10_000
    assert validate_login_csrf(tok, tok, secret=SECRET, now=later) is False


def test_login_csrf_wrong_secret_fails():
    from app.auth.csrf import issue_login_csrf, validate_login_csrf
    tok = issue_login_csrf(SECRET)
    assert validate_login_csrf(tok, tok, secret="otro-secreto-distinto") is False


def test_login_post_without_csrf_cookie_is_403(auth_env):
    """POST /login sin cookie CSRF → 403 (no procesa credenciales)."""
    client = _client()
    resp = client.post("/login", data={
        "username": "x", "password": "y" * 12, "csrf_token": "inventado", "next": "/",
    })
    assert resp.status_code == 403


def test_login_post_full_flow_reaches_credentials(auth_env):
    """GET /login + POST con cookie válida → pasa CSRF y llega a validar credenciales (401)."""
    from app.auth.csrf import LOGIN_CSRF_COOKIE
    client = _client()
    client.get("/login")
    csrf = client.cookies.get(LOGIN_CSRF_COOKIE)
    assert csrf
    resp = client.post("/login", data={
        "username": "noexiste", "password": "y" * 12, "csrf_token": csrf, "next": "/",
    })
    assert resp.status_code == 401  # CSRF OK, credenciales inválidas


# ---------------------------------------------------------------------------
# A5.9-12 — validación de arranque: secreto CSRF y backend de contraseñas
# ---------------------------------------------------------------------------

def _auth_settings(**overrides):
    from app.auth.config import AuthSettings
    base = dict(S9K_AUTH_ENABLED=True,
                S9K_CSRF_SECRET="una-clave-larga-y-aleatoria-suficiente-1234567890")
    base.update(overrides)
    return AuthSettings(_env_file=None, **base)


def test_default_csrf_secret_blocks_startup():
    from app.auth.security import AuthSecurityError, enforce_auth_security
    with pytest.raises(AuthSecurityError):
        enforce_auth_security(_auth_settings(S9K_CSRF_SECRET="s9k-csrf-change-me"))


def test_empty_csrf_secret_blocks_startup():
    from app.auth.security import AuthSecurityError, enforce_auth_security
    with pytest.raises(AuthSecurityError):
        enforce_auth_security(_auth_settings(S9K_CSRF_SECRET=""))


def test_short_csrf_secret_blocks_startup():
    from app.auth.security import AuthSecurityError, enforce_auth_security
    with pytest.raises(AuthSecurityError):
        enforce_auth_security(_auth_settings(S9K_CSRF_SECRET="corto123"))


def test_strong_csrf_secret_allows_startup(tmp_path):
    from app.auth import db as auth_db
    from app.auth.security import enforce_auth_security
    # El contrato nuevo exige además ruta de DB absoluta y existente.
    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    # No debe lanzar
    enforce_auth_security(_auth_settings(S9K_AUTH_DB_PATH=str(db_path)))


def test_auth_disabled_skips_enforcement():
    from app.auth.security import enforce_auth_security
    # Con auth off, un secreto por defecto no aborta
    enforce_auth_security(_auth_settings(S9K_AUTH_ENABLED=False,
                                         S9K_CSRF_SECRET="s9k-csrf-change-me"))


def test_pbkdf2_backend_blocked(monkeypatch):
    import app.auth.security as sec
    monkeypatch.setattr(sec, "get_backend", lambda: "pbkdf2-sha256-dev")
    assert sec.validate_password_backend()  # lista de problemas no vacía


def test_argon2_backend_allowed(monkeypatch):
    import app.auth.security as sec
    monkeypatch.setattr(sec, "get_backend", lambda: "argon2id")
    assert sec.validate_password_backend() == []


def test_bcrypt_backend_allowed(monkeypatch):
    import app.auth.security as sec
    monkeypatch.setattr(sec, "get_backend", lambda: "bcrypt")
    assert sec.validate_password_backend() == []


def test_pbkdf2_backend_aborts_full_enforcement(monkeypatch):
    import app.auth.security as sec
    from app.auth.security import AuthSecurityError, enforce_auth_security
    monkeypatch.setattr(sec, "get_backend", lambda: "pbkdf2-sha256-dev")
    with pytest.raises(AuthSecurityError):
        enforce_auth_security(_auth_settings())


# ---------------------------------------------------------------------------
# A5.13-16 — cookies de sesión y de login CSRF (flags de seguridad)
# ---------------------------------------------------------------------------

def test_login_csrf_cookie_httponly(auth_env):
    client = _client()
    resp = client.get("/login")
    set_cookie = resp.headers.get("set-cookie", "")
    assert "_s9k_login_csrf" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite" in set_cookie.lower()


# ---------------------------------------------------------------------------
# A5.21-22 — middleware fail-closed: fallo de auth DB no abre rutas protegidas
# ---------------------------------------------------------------------------

def test_middleware_fail_closed_on_auth_error(auth_env, monkeypatch):
    """Si get_valid_session lanza, el usuario queda anónimo y la API responde 401."""
    user = _make_user(auth_env, "viewer_fc", "viewer")
    token = _session_cookie(auth_env, user)
    import app.auth.middleware as mw

    def _boom(*a, **k):
        raise RuntimeError("auth DB caída")

    monkeypatch.setattr(mw, "get_valid_session", _boom)
    from app.auth.config import get_auth_settings
    cfg = get_auth_settings()
    client = _client()
    client.cookies.set(cfg.S9K_SESSION_COOKIE_NAME, token)
    resp = client.get("/api/status", headers={"accept": "application/json"})
    assert resp.status_code == 401  # fail-closed: NO abre la ruta


# ---------------------------------------------------------------------------
# A5.23-24 — /docs gating
# ---------------------------------------------------------------------------

def test_docs_absent_by_default(auth_env):
    """Con auth on y expose=false → /docs no existe (404) y openapi tampoco."""
    client = _client()
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_docs_anonymous_401_when_exposed(auth_env):
    os.environ["S9K_AUTH_EXPOSE_DOCS"] = "true"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    client = _client()
    assert client.get("/docs").status_code == 401


def test_docs_requires_admin_when_exposed(auth_env):
    os.environ["S9K_AUTH_EXPOSE_DOCS"] = "true"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    cfg = get_auth_settings()
    viewer = _make_user(auth_env, "viewer_docs", "viewer")
    admin = _make_user(auth_env, "admin_docs", "admin")
    vtok = _session_cookie(auth_env, viewer)
    atok = _session_cookie(auth_env, admin)

    client = _client()
    client.cookies.set(cfg.S9K_SESSION_COOKIE_NAME, vtok)
    assert client.get("/docs").status_code == 403  # viewer no

    client2 = _client()
    client2.cookies.set(cfg.S9K_SESSION_COOKIE_NAME, atok)
    assert client2.get("/docs").status_code == 200  # admin sí


# ---------------------------------------------------------------------------
# A5.27-29 — aislamiento: el subsistema auth no toca Neo4j ni el writer de ingesta
# ---------------------------------------------------------------------------

def test_auth_code_does_not_touch_neo4j_or_ingest():
    auth_dir = Path(__file__).resolve().parents[1] / "app" / "auth"
    forbidden = ("ingest_approved", "approved_payload", "GraphDatabase",
                 "neo4j", "S9K_ALLOW_REAL_INGEST")
    offenders = []
    for py in auth_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                offenders.append(f"{py.name}: {term}")
    assert not offenders, f"El subsistema auth referencia recursos prohibidos: {offenders}"

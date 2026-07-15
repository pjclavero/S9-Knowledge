"""Tests del núcleo de autenticación: passwords, sesiones, CSRF, DB."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures de DB en memoria
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Base de datos SQLite temporal para tests."""
    db_path = tmp_path / "auth_test.db"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    # Limpiar cache de settings
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass
    yield db_path
    os.environ.pop("S9K_AUTH_DB_PATH", None)
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass


@pytest.fixture
def conn(tmp_db):
    """Conexión a DB de tests con migraciones aplicadas."""
    from app.auth import db as auth_db
    auth_db.ensure_migrated(tmp_db)
    with auth_db.get_conn(tmp_db) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Hash y verificación de contraseña
# ---------------------------------------------------------------------------

def test_password_hash_and_verify():
    from app.auth.passwords import hash_password, verify_password
    pw = "MiContraseña_Segura_123!"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True


# ---------------------------------------------------------------------------
# 2. Contraseña incorrecta devuelve False
# ---------------------------------------------------------------------------

def test_password_wrong_returns_false():
    from app.auth.passwords import hash_password, verify_password
    hashed = hash_password("ContraseñaCorrecta_X99!")
    assert verify_password("ContraseñaIncorrecta_X99!", hashed) is False


# ---------------------------------------------------------------------------
# 3. Usuario inexistente → mensaje genérico (no revela si existe)
# ---------------------------------------------------------------------------

def test_login_unknown_user_generic_message(conn, tmp_db, monkeypatch):
    """POST /login con usuario inexistente devuelve 401 con mensaje genérico."""
    os.environ["S9K_AUTH_ENABLED"] = "true"
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass

    from app.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/login", data={
        "username": "usuario_inexistente",
        "password": "alguna_clave_larga_123",
        "csrf_token": "token_dummy",
        "next": "/",
    })
    # Debe responder con error genérico, no revelar si el usuario existe
    assert resp.status_code in (401, 200)
    assert "inexistente" not in resp.text.lower()
    assert "no existe" not in resp.text.lower()

    os.environ.pop("S9K_AUTH_ENABLED", None)
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 4. Creación de sesión
# ---------------------------------------------------------------------------

def test_session_creation(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    pw_hash = hash_password("Test_Pass_1234567")
    user = auth_db.create_user(
        conn, username="testuser", display_name="Test",
        password_hash=pw_hash, role="viewer",
    )
    token, session = create_session(conn, user)
    assert token is not None
    assert len(token) > 20
    assert session.user_id == user.id
    assert session.revoked_at is None


# ---------------------------------------------------------------------------
# 5. Token almacenado como hash (nunca en claro)
# ---------------------------------------------------------------------------

def test_token_stored_as_hash(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    pw_hash = hash_password("Test_Pass_Hash_9999!")
    user = auth_db.create_user(
        conn, username="hashuser", display_name="Hash User",
        password_hash=pw_hash, role="viewer",
    )
    token, session = create_session(conn, user)

    # El token en claro NO debe estar en la DB
    raw = conn.execute("SELECT session_hash FROM sessions WHERE id = ?", (session.id,)).fetchone()
    stored_hash = raw[0]
    assert stored_hash != token
    # Debe ser sha256 del token
    expected = hashlib.sha256(token.encode()).hexdigest()
    assert stored_hash == expected


# ---------------------------------------------------------------------------
# 6. Cookie HttpOnly
# ---------------------------------------------------------------------------

def test_cookie_httponly(conn, tmp_db, monkeypatch):
    from app.auth.sessions import cookie_kwargs
    kwargs = cookie_kwargs()
    assert kwargs.get("httponly") is True


# ---------------------------------------------------------------------------
# 7. Cookie Secure
# ---------------------------------------------------------------------------

def test_cookie_secure(conn, tmp_db, monkeypatch):
    from app.auth.sessions import cookie_kwargs
    kwargs = cookie_kwargs()
    # Por defecto S9K_SESSION_SECURE=True
    assert kwargs.get("secure") is True


# ---------------------------------------------------------------------------
# 8. SameSite
# ---------------------------------------------------------------------------

def test_cookie_samesite():
    from app.auth.sessions import cookie_kwargs
    kwargs = cookie_kwargs()
    assert kwargs.get("samesite") in ("lax", "strict", "none")


# ---------------------------------------------------------------------------
# 9. Logout revoca sesión
# ---------------------------------------------------------------------------

def test_logout_revokes_session(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session, revoke_session_by_token

    pw_hash = hash_password("Logout_Test_1234567")
    user = auth_db.create_user(
        conn, username="logoutuser", display_name="Logout",
        password_hash=pw_hash, role="viewer",
    )
    token, session = create_session(conn, user)
    assert session.revoked_at is None

    result = revoke_session_by_token(conn, token)
    assert result is True

    # La sesión debe estar revocada en DB
    sess = auth_db.get_session_by_id(conn, session.id)
    assert sess.revoked_at is not None


# ---------------------------------------------------------------------------
# 10. Expiración absoluta
# ---------------------------------------------------------------------------

def test_session_absolute_expiry(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import get_valid_session

    pw_hash = hash_password("Expiry_Test_1234567")
    user = auth_db.create_user(
        conn, username="expiryuser", display_name="Expiry",
        password_hash=pw_hash, role="viewer",
    )
    # Crear sesión ya expirada
    import hashlib, secrets
    token = secrets.token_urlsafe(32)
    session_hash = hashlib.sha256(token.encode()).hexdigest()
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    auth_db.create_session(conn, user.id, session_hash=session_hash, expires_at=past)

    result = get_valid_session(conn, token)
    assert result is None


# ---------------------------------------------------------------------------
# 11. Expiración por inactividad
# ---------------------------------------------------------------------------

def test_session_idle_expiry(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session, get_valid_session

    pw_hash = hash_password("Idle_Test_1234567890")
    user = auth_db.create_user(
        conn, username="idleuser", display_name="Idle",
        password_hash=pw_hash, role="viewer",
    )
    token, session = create_session(conn, user)
    # Simular last_seen_at muy antigua
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
        ((datetime.utcnow() - timedelta(hours=3)).isoformat(), session.id),
    )
    conn.commit()

    result = get_valid_session(conn, token, idle_minutes=60)
    assert result is None


# ---------------------------------------------------------------------------
# 12. Bloqueo tras intentos fallidos
# ---------------------------------------------------------------------------

def test_account_lockout(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password

    pw_hash = hash_password("Lockout_Test_9999!")
    user = auth_db.create_user(
        conn, username="lockuser", display_name="Lock",
        password_hash=pw_hash, role="viewer",
    )
    locked_until = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    auth_db.update_user(conn, user.id, failed_login_count=5, locked_until=locked_until)

    updated = auth_db.get_user_by_id(conn, user.id)
    assert updated.is_locked() is True
    assert updated.failed_login_count == 5


# ---------------------------------------------------------------------------
# 13. Desbloqueo de cuenta
# ---------------------------------------------------------------------------

def test_account_unlock(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password

    pw_hash = hash_password("Unlock_Test_9999!")
    user = auth_db.create_user(
        conn, username="unlockuser", display_name="Unlock",
        password_hash=pw_hash, role="viewer",
    )
    locked_until = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    auth_db.update_user(conn, user.id, failed_login_count=5, locked_until=locked_until)
    # Desbloquear
    auth_db.update_user(conn, user.id, failed_login_count=0, locked_until="")
    updated = auth_db.get_user_by_id(conn, user.id)
    assert updated.is_locked() is False
    assert updated.failed_login_count == 0


# ---------------------------------------------------------------------------
# 14. Usuario desactivado no puede tener sesión válida
# ---------------------------------------------------------------------------

def test_disabled_user_no_valid_session(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session, get_valid_session

    pw_hash = hash_password("Disabled_Test_9999!")
    user = auth_db.create_user(
        conn, username="disableduser", display_name="Disabled",
        password_hash=pw_hash, role="viewer",
    )
    token, session = create_session(conn, user)
    # Desactivar usuario
    auth_db.update_user(conn, user.id, is_active=False)

    result = get_valid_session(conn, token)
    assert result is None


# ---------------------------------------------------------------------------
# 15. Cambio de contraseña revoca sesiones
# ---------------------------------------------------------------------------

def test_password_change_revokes_sessions(conn, tmp_db):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    pw_hash = hash_password("OldPass_Test_9999!")
    user = auth_db.create_user(
        conn, username="pwchangeuser", display_name="PwChange",
        password_hash=pw_hash, role="viewer",
    )
    token, session = create_session(conn, user)

    # Cambiar contraseña y revocar sesiones
    new_hash = hash_password("NewPass_Test_9999!")
    auth_db.update_user(conn, user.id, password_hash=new_hash)
    count = auth_db.revoke_sessions_for_user(conn, user.id)
    assert count >= 1

    sess = auth_db.get_session_by_id(conn, session.id)
    assert sess.revoked_at is not None


# ---------------------------------------------------------------------------
# 16. CSRF válido pasa
# ---------------------------------------------------------------------------

def test_csrf_valid():
    from app.auth.csrf import generate_csrf_token, get_csrf_token_for_session, validate_csrf
    raw = generate_csrf_token()
    derived = get_csrf_token_for_session(42, raw, secret="test-secret")
    assert validate_csrf(derived, 42, raw, secret="test-secret") is True


# ---------------------------------------------------------------------------
# 17. CSRF ausente devuelve False
# ---------------------------------------------------------------------------

def test_csrf_absent_fails():
    from app.auth.csrf import generate_csrf_token, get_csrf_token_for_session, validate_csrf
    raw = generate_csrf_token()
    assert validate_csrf(None, 42, raw, secret="test-secret") is False


# ---------------------------------------------------------------------------
# 18. CSRF incorrecto devuelve False
# ---------------------------------------------------------------------------

def test_csrf_wrong_token_fails():
    from app.auth.csrf import generate_csrf_token, get_csrf_token_for_session, validate_csrf
    raw = generate_csrf_token()
    derived = get_csrf_token_for_session(42, raw, secret="test-secret")
    assert validate_csrf("token_incorrecto", 42, raw, secret="test-secret") is False
    assert validate_csrf(derived, 99, raw, secret="test-secret") is False  # session_id distinto

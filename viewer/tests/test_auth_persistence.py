# -*- coding: utf-8 -*-
"""Persistencia e identidad de la auth DB, normalización del login y no-store.

Cubre el contrato forense del operador:
- una sola base física (device/inode) para login, cambio y CLI;
- sin fallback silencioso a rutas relativas ni creación automática en arranque;
- el cambio de contraseña se verifica en disco con una conexión NUEVA;
- la contraseña sobrevive a un "reinicio" (cierre total de conexiones);
- el username se recorta (espacio final del teclado móvil), el password JAMÁS;
- locked_until se limpia a NULL real, no a cadena vacía;
- las respuestas de autenticación llevan Cache-Control: no-store.

SQLite real en disco en todos los casos: aquí no hay mocks de base de datos.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PASSWORD = "Correcta-Horse-Battery_42"
PASSWORD_UNICODE = "contraseña-cañón-🔑-ñÑ áé 42"
PASSWORD_LONG = "x" * 96 + "-Final_Password_123!"  # >72 bytes (límite bcrypt clásico)


@pytest.fixture(autouse=True)
def reset_settings():
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass
    yield
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_CSRF_SECRET",
              "S9K_SESSION_SECURE"):
        os.environ.pop(k, None)
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass


@pytest.fixture
def auth_env(tmp_path):
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    os.environ["S9K_SESSION_SECURE"] = "false"   # TestClient va por http
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db_path)
    return db_path


def _make_user(db_path, username="labuser", password=PASSWORD, **kw):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db_path) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username,
            password_hash=hash_password(password), role=kw.pop("role", "admin"), **kw,
        )


# ---------------------------------------------------------------------------
# Identidad física de la base
# ---------------------------------------------------------------------------

def test_db_identity_expone_device_e_inode(auth_env):
    from app.auth import db as auth_db
    ident = auth_db.db_identity(auth_env)
    st = auth_env.stat()
    assert ident["exists"] is True
    assert ident["device"] == st.st_dev
    assert ident["inode"] == st.st_ino
    assert ident["path"] == str(auth_env.resolve())
    assert ident["schema_version"] == auth_db.SCHEMA_VERSION


def test_db_identity_no_contiene_secretos(auth_env):
    _make_user(auth_env)
    from app.auth import db as auth_db
    ident = auth_db.db_identity(auth_env)
    dump = str(ident)
    assert "labuser" not in dump
    assert "argon2" not in dump.lower()
    assert PASSWORD not in dump


def test_login_cambio_y_cli_usan_el_mismo_inode(auth_env):
    """Las tres vías resuelven la MISMA ruta → mismo device/inode."""
    from app.auth.config import get_auth_settings
    from app.routers.auth import _get_db_path as router_path
    from app.cli.auth import _get_db_path as cli_path

    cfg_path = Path(get_auth_settings().S9K_AUTH_DB_PATH).resolve()
    assert router_path().resolve() == cfg_path
    assert cli_path().resolve() == cfg_path


# ---------------------------------------------------------------------------
# Sin fallback silencioso
# ---------------------------------------------------------------------------

def test_ruta_relativa_aborta_con_auth_activa():
    from app.auth.security import validate_auth_db_path
    problems = validate_auth_db_path("viewer/state/auth.db")
    assert problems, "una ruta relativa debe ser rechazada en producción"


def test_db_inexistente_aborta_con_auth_activa(tmp_path):
    from app.auth.security import validate_auth_db_path
    problems = validate_auth_db_path(str(tmp_path / "no-existe" / "auth.db"))
    assert problems, "una base inexistente debe abortar el arranque, no crearse"


def test_ruta_absoluta_existente_es_valida(auth_env):
    from app.auth.security import validate_auth_db_path
    assert validate_auth_db_path(str(auth_env)) == []


def test_enforce_auth_security_incluye_la_ruta(tmp_path):
    from app.auth.config import AuthSettings
    from app.auth.security import AuthSecurityError, enforce_auth_security
    cfg = AuthSettings(
        S9K_AUTH_ENABLED=True,
        S9K_AUTH_DB_PATH="viewer/state/auth.db",
        S9K_CSRF_SECRET="un-secreto-largo-y-unico-abcdefghij123456",
    )
    with pytest.raises(AuthSecurityError):
        enforce_auth_security(cfg)


# ---------------------------------------------------------------------------
# Persistencia: commit real, conexión nueva, "reinicio"
# ---------------------------------------------------------------------------

def test_verificacion_post_commit_con_conexion_nueva(auth_env):
    from app.auth import db as auth_db
    user = _make_user(auth_env)
    assert auth_db.verify_persisted_password(auth_env, user.id, PASSWORD) is True
    assert auth_db.verify_persisted_password(auth_env, user.id, "otra-cosa-123") is False


@pytest.mark.parametrize("pw", [PASSWORD, PASSWORD_UNICODE, PASSWORD_LONG,
                                "  espacios  interiores  y exteriores  "])
def test_password_exacta_sin_normalizar(auth_env, pw):
    """El password es la secuencia exacta: ni strip, ni casefold, ni Unicode."""
    from app.auth import db as auth_db
    user = _make_user(auth_env, username=f"u{abs(hash(pw)) % 10**8}", password=pw)
    assert auth_db.verify_persisted_password(auth_env, user.id, pw) is True
    if pw.strip() != pw:
        assert auth_db.verify_persisted_password(auth_env, user.id, pw.strip()) is False


def test_password_sobrevive_a_un_reinicio_en_proceso_nuevo(auth_env):
    """La prueba de reinicio: un PROCESO nuevo verifica el hash persistido."""
    user = _make_user(auth_env)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from pathlib import Path\n"
        "from app.auth import db as auth_db\n"
        "ok = auth_db.verify_persisted_password(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4])\n"
        "sys.exit(0 if ok else 1)\n"
    )
    viewer_root = str(Path(__file__).resolve().parents[1])
    r = subprocess.run(
        [sys.executable, "-c", code, viewer_root, str(auth_env), str(user.id), PASSWORD],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"el proceso nuevo no verificó el hash: {r.stderr}"


def test_cambio_de_password_invalida_la_anterior(auth_env):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    user = _make_user(auth_env)
    with auth_db.get_conn(auth_env) as conn:
        auth_db.update_user(conn, user.id, password_hash=hash_password("Nueva-Definitiva_99"))
    assert auth_db.verify_persisted_password(auth_env, user.id, "Nueva-Definitiva_99") is True
    assert auth_db.verify_persisted_password(auth_env, user.id, PASSWORD) is False


# ---------------------------------------------------------------------------
# locked_until: NULL real
# ---------------------------------------------------------------------------

def test_desbloquear_deja_null_no_cadena_vacia(auth_env):
    from app.auth import db as auth_db
    user = _make_user(auth_env)
    with auth_db.get_conn(auth_env) as conn:
        auth_db.update_user(conn, user.id, locked_until="2099-01-01T00:00:00")
        auth_db.update_user(conn, user.id, failed_login_count=0, locked_until="")
    raw = sqlite3.connect(auth_env)
    val = raw.execute("SELECT locked_until FROM users WHERE id = ?", (user.id,)).fetchone()[0]
    raw.close()
    assert val is None, f"locked_until quedó como {val!r}, no NULL"


# ---------------------------------------------------------------------------
# Login por HTTP: username recortado, password intacta, no-store
# ---------------------------------------------------------------------------

def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _login(client, username, password):
    # El GET deja la cookie CSRF de doble envío en el jar del cliente.
    page = client.get("/login")
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    return client.post("/login", data={
        "username": username, "password": password, "csrf_token": token,
    })


def test_username_con_espacio_final_entra(auth_env):
    _make_user(auth_env, username="s9admin")
    resp = _login(_client(), "s9admin ", PASSWORD)
    assert resp.status_code == 302, resp.text[:300]


def test_password_con_espacio_final_no_entra(auth_env):
    """El password NO se recorta: un espacio de más debe fallar."""
    _make_user(auth_env, username="s9admin")
    resp = _login(_client(), "s9admin", PASSWORD + " ")
    assert resp.status_code == 401


def test_login_lleva_no_store(auth_env):
    client = _client()
    resp = client.get("/login")
    assert resp.headers.get("cache-control") == "no-store"
    resp = _login(client, "nadie", "da-igual-123456")
    assert resp.headers.get("cache-control") == "no-store"


def test_error_de_login_repinta_html_y_conserva_formulario(auth_env):
    _make_user(auth_env, username="s9admin")
    resp = _login(_client(), "s9admin", "incorrecta-123456")
    assert resp.status_code == 401
    assert "text/html" in resp.headers.get("content-type", "")
    assert 'name="username"' in resp.text
    assert "Usuario o contraseña incorrectos" in resp.text


def test_post_login_sin_campos_devuelve_html_400(auth_env):
    client = _client()
    resp = client.post("/login", data={})
    assert resp.status_code == 400
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Field required" not in resp.text


# ---------------------------------------------------------------------------
# CLI: set-password --must-change y db-identity
# ---------------------------------------------------------------------------

def test_cli_set_password_must_change(auth_env, monkeypatch):
    import argparse
    from app.auth import db as auth_db
    from app.cli import auth as cli
    _make_user(auth_env, username="s9admin")

    monkeypatch.setattr("getpass.getpass", lambda *_: "Temporal-De-Reparto_77")
    args = argparse.Namespace(username="s9admin", must_change=True)
    assert cli.cmd_set_password(args) == 0

    with auth_db.get_conn(auth_env) as conn:
        user = auth_db.get_user_by_username(conn, "s9admin")
    assert user.must_change_password is True
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert auth_db.verify_persisted_password(auth_env, user.id, "Temporal-De-Reparto_77")


def test_cli_set_password_sin_flag_es_definitiva(auth_env, monkeypatch):
    import argparse
    from app.auth import db as auth_db
    from app.cli import auth as cli
    _make_user(auth_env, username="s9admin", must_change_password=True)

    monkeypatch.setattr("getpass.getpass", lambda *_: "Definitiva-Del-Operador_88")
    args = argparse.Namespace(username="s9admin", must_change=False)
    assert cli.cmd_set_password(args) == 0
    with auth_db.get_conn(auth_env) as conn:
        user = auth_db.get_user_by_username(conn, "s9admin")
    assert user.must_change_password is False


def test_cli_db_identity(auth_env, capsys):
    import argparse
    from app.cli import auth as cli
    assert cli.cmd_db_identity(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert str(auth_env.resolve()) in out
    assert "inode:" in out and "device:" in out

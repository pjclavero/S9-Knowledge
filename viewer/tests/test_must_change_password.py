# -*- coding: utf-8 -*-
"""Cambio obligatorio de contrasena: bloqueo efectivo y flujo completo.

Hueco que motiva esta suite: must_change_password solo dirigia la redireccion
POSTERIOR al login. Nada bloqueaba las rutas, asi que bastaba teclear /entities
para saltarse la obligacion. El bloqueo vive ahora en el middleware.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def reset_settings():
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    yield
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


@pytest.fixture
def auth_db(tmp_path):
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    yield db_path


TEMP_PASSWORD = "3uq28-7DRZX-pufao"
NEW_PASSWORD = "UnaContrasenaLargaYNueva_2026!"


def _user(db_path, must_change: bool, password: str = TEMP_PASSWORD, role: str = "admin"):
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    with auth_db_mod.get_conn(db_path) as conn:
        return auth_db_mod.create_user(
            conn, username="s9admin", display_name="Admin",
            password_hash=hash_password(password), role=role,
            must_change_password=must_change,
        )


def _client(token: str | None = None):
    from fastapi.testclient import TestClient
    from app.auth.config import get_auth_settings
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if token:
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return c


def _session(db_path, user):
    from app.auth import db as auth_db_mod
    from app.auth.sessions import create_session
    with auth_db_mod.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    return token


def _reload(db_path, username="s9admin"):
    from app.auth import db as auth_db_mod
    with auth_db_mod.get_conn(db_path) as conn:
        return auth_db_mod.get_user_by_username(conn, username)


# ---------------------------------------------------------------------------
# El bloqueo (la regresion)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/", "/entities", "/sources", "/quality",
                                  "/jobs", "/reviews", "/admin"])
def test_rutas_bloqueadas_mientras_deba_cambiar(auth_db, ruta):
    """EL HUECO: antes se entraba directamente sin cambiar la contrasena."""
    user = _user(auth_db, must_change=True)
    r = _client(_session(auth_db, user)).get(ruta, headers={"accept": "text/html"})
    assert r.status_code == 302, f"{ruta} -> {r.status_code}"
    assert r.headers["location"] == "/account/change-password"


def test_api_protegida_da_403_json_no_redireccion(auth_db):
    """Un cliente que espera JSON no sabe seguir un 302 a HTML."""
    user = _user(auth_db, must_change=True)
    r = _client(_session(auth_db, user)).get("/api/status",
                                             headers={"accept": "application/json"})
    assert r.status_code == 403
    assert r.json()["change_password_url"] == "/account/change-password"


@pytest.mark.parametrize("ruta", ["/account/change-password", "/login"])
def test_rutas_permitidas_mientras_deba_cambiar(auth_db, ruta):
    user = _user(auth_db, must_change=True)
    r = _client(_session(auth_db, user)).get(ruta, headers={"accept": "text/html"})
    assert r.status_code == 200, f"{ruta} -> {r.status_code}"


def test_logout_permitido(auth_db):
    """Encerrar al usuario sin poder ni salir seria una trampa."""
    from app.auth.middleware import _must_change_allows
    assert _must_change_allows("/logout")
    assert _must_change_allows("/static/css/app.css")


def test_sin_la_marca_no_se_bloquea_nada(auth_db):
    user = _user(auth_db, must_change=False)
    r = _client(_session(auth_db, user)).get("/", headers={"accept": "text/html"})
    assert r.status_code == 200


def test_anonimo_va_al_login_no_al_cambio(auth_db):
    """El bloqueo no puede pisar el flujo normal de los no autenticados."""
    r = _client().get("/", headers={"accept": "text/html"})
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


# ---------------------------------------------------------------------------
# Login con la marca puesta
# ---------------------------------------------------------------------------

def test_login_temporal_redirige_al_cambio(auth_db):
    _user(auth_db, must_change=True)
    c = _client()
    page = c.get("/login")
    token = _csrf_de(page.text)
    r = c.post("/login", data={"username": "s9admin", "password": TEMP_PASSWORD,
                               "csrf_token": token, "next": "/entities"})
    assert r.status_code == 302
    # Ni siquiera respeta `next`: la obligacion manda.
    assert r.headers["location"] == "/account/change-password"


def _csrf_de(html: str) -> str:
    import re
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


# ---------------------------------------------------------------------------
# El cambio en si
# ---------------------------------------------------------------------------

def _cambiar(auth_db, nueva: str, actual: str = TEMP_PASSWORD):
    user = _user(auth_db, must_change=True)
    token = _session(auth_db, user)
    c = _client(token)
    page = c.get("/account/change-password")
    csrf = _csrf_de(page.text)
    return c, c.post("/account/change-password", data={
        "current_password": actual, "new_password": nueva,
        "confirm_password": nueva, "csrf_token": csrf,
    })


def test_cambio_correcto_limpia_todo_y_rota_la_sesion(auth_db):
    c, r = _cambiar(auth_db, NEW_PASSWORD)
    assert r.status_code == 302
    assert r.headers["location"] == "/"          # sigue dentro: sesion rotada
    u = _reload(auth_db)
    assert u.must_change_password is False
    assert u.failed_login_count == 0
    assert not u.locked_until
    from app.auth.passwords import verify_password
    assert verify_password(NEW_PASSWORD, u.password_hash)


def test_la_nueva_no_puede_ser_la_temporal(auth_db):
    """Repetir la temporal no es un cambio: deja viva la credencial repartida."""
    _, r = _cambiar(auth_db, TEMP_PASSWORD)
    assert r.status_code == 400
    assert "distinta de la actual" in r.text
    assert _reload(auth_db).must_change_password is True


def test_minimo_12_caracteres(auth_db):
    _, r = _cambiar(auth_db, "corta1!")
    assert r.status_code == 400
    assert _reload(auth_db).must_change_password is True


def test_no_puede_ser_igual_al_username(auth_db):
    _, r = _cambiar(auth_db, "s9admin")
    assert r.status_code == 400
    assert _reload(auth_db).must_change_password is True


def test_confirmacion_debe_coincidir(auth_db):
    user = _user(auth_db, must_change=True)
    c = _client(_session(auth_db, user))
    csrf = _csrf_de(c.get("/account/change-password").text)
    r = c.post("/account/change-password", data={
        "current_password": TEMP_PASSWORD, "new_password": NEW_PASSWORD,
        "confirm_password": "otra-distinta-larga-123", "csrf_token": csrf,
    })
    assert r.status_code == 400
    assert _reload(auth_db).must_change_password is True


def test_contrasena_actual_incorrecta_no_cambia_nada(auth_db):
    _, r = _cambiar(auth_db, NEW_PASSWORD, actual="no-es-la-temporal-123")
    assert r.status_code == 400
    assert _reload(auth_db).must_change_password is True


def test_csrf_invalido_bloquea(auth_db):
    user = _user(auth_db, must_change=True)
    c = _client(_session(auth_db, user))
    r = c.post("/account/change-password", data={
        "current_password": TEMP_PASSWORD, "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD, "csrf_token": "basura",
    })
    assert r.status_code == 403
    assert _reload(auth_db).must_change_password is True


def test_el_cambio_se_audita_sin_registrar_la_contrasena(auth_db):
    _cambiar(auth_db, NEW_PASSWORD)
    from app.auth import db as auth_db_mod
    with auth_db_mod.get_conn(auth_db) as conn:
        filas = conn.execute(
            "SELECT event_type, result, metadata_json FROM audit_events"
        ).fetchall()
    texto = str([tuple(f) for f in filas])
    assert "PASSWORD_CHANGED" in texto
    assert NEW_PASSWORD not in texto, "la contraseña acabo en la auditoria"
    assert TEMP_PASSWORD not in texto


def test_tras_cambiar_ya_se_navega(auth_db):
    c, r = _cambiar(auth_db, NEW_PASSWORD)
    assert c.get("/", headers={"accept": "text/html"}).status_code == 200

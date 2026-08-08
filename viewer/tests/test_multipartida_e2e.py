"""E2E de M5a: selector de partida real (cookie de sesión + DB de auth real),
gestión admin de asignaciones, y aislamiento observado a través de la API.

Usa el proveedor mock con `multipartida_graph.json` (2 partidas + capa juego)
igual que `test_multipartida_isolation.py`, pero aquí conducido por HTTP real
(login/sesión/selector), no por construcción directa de ViewerContext.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "multipartida_graph.json")
WS = "juego:lab"


@pytest.fixture
def auth_env(tmp_path):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-tests-m5a-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ["S9K_SAMPLE_GRAPH_PATH"] = FIXTURE
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    from app.deps import get_provider
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)
    yield db
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_SAMPLE_GRAPH_PATH", "S9K_DEFAULT_WORKSPACE"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _make_user(db, username, role="viewer"):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username,
            password_hash=hash_password("x" * 14), role=role,
        )


def _cookie_for(db, user):
    from app.auth import db as auth_db
    from app.auth.sessions import create_session
    with auth_db.get_conn(db) as conn:
        token, _ = create_session(conn, user)
    return token


def _logged_client(db, user):
    from app.auth.config import get_auth_settings
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, _cookie_for(db, user))
    return c


def _entity_ids(client):
    r = client.get("/api/entities?limit=1000", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text
    return {i["id"] for i in r.json()["items"]}


def _csrf_from(client, path="/entities"):
    page = client.get(path, headers={"accept": "text/html"})
    m = re.search(r'name="csrf_token" value="([^"]*)"', page.text)
    assert m, f"no se encontró csrf_token en {path}: {page.text[:300]}"
    return m.group(1)


# ---------------------------------------------------------------------------
# Sin asignación: solo capa juego
# ---------------------------------------------------------------------------

def test_usuario_sin_asignacion_ve_solo_capa_juego(auth_env):
    user = _make_user(auth_env, "sin_partida")
    c = _logged_client(auth_env, user)
    ids = _entity_ids(c)
    assert ids == {"lore_dios_sol"}


# ---------------------------------------------------------------------------
# Selector cambia la vista; aislamiento entre partidas nunca cruza
# ---------------------------------------------------------------------------

def test_selector_cambia_vista_y_aisla_partidas(auth_env):
    from app.auth import db as auth_db

    user = _make_user(auth_env, "jugador_multi")
    with auth_db.get_conn(auth_env) as conn:
        auth_db.grant_partida_access(conn, user.id, WS, "partida:uno", granted_by="admin")
        auth_db.grant_partida_access(conn, user.id, WS, "partida:dos", granted_by="admin")

    c = _logged_client(auth_env, user)

    # Aún sin seleccionar ninguna: solo capa juego.
    assert _entity_ids(c) == {"lore_dios_sol"}

    csrf = _csrf_from(c)
    r = c.post("/partida/select", data={"partida_id": "partida:uno", "next": "/entities", "csrf_token": csrf})
    assert r.status_code == 302

    ids_uno = _entity_ids(c)
    assert ids_uno == {"lore_dios_sol", "partida1_pc_arden"}
    assert "partida2_pc_bryn" not in ids_uno

    csrf2 = _csrf_from(c)
    r2 = c.post("/partida/select", data={"partida_id": "partida:dos", "next": "/entities", "csrf_token": csrf2})
    assert r2.status_code == 302

    ids_dos = _entity_ids(c)
    assert ids_dos == {"lore_dios_sol", "partida2_pc_bryn"}
    assert "partida1_pc_arden" not in ids_dos

    # Acceso directo por id a la partida ajena sigue en 404 con partida:dos activa.
    r3 = c.get("/api/entities/partida1_pc_arden")
    assert r3.status_code == 404


def test_no_puede_seleccionar_partida_no_asignada(auth_env):
    user = _make_user(auth_env, "sin_permiso")
    c = _logged_client(auth_env, user)
    csrf = _csrf_from(c)
    r = c.post("/partida/select", data={"partida_id": "partida:uno", "next": "/entities", "csrf_token": csrf})
    assert r.status_code == 403
    # La vista sigue en capa juego, no se filtró nada de la partida rechazada.
    assert _entity_ids(c) == {"lore_dios_sol"}


# ---------------------------------------------------------------------------
# Admin: gestión de asignaciones
# ---------------------------------------------------------------------------

def test_admin_gestiona_asignaciones(auth_env):
    from app.auth import db as auth_db

    admin = _make_user(auth_env, "elgm", role="admin")
    target = _make_user(auth_env, "jugador1")
    c = _client()
    from app.auth.config import get_auth_settings
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, _cookie_for(auth_env, admin))

    page = c.get("/admin/partidas", headers={"accept": "text/html"})
    assert page.status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', page.text).group(1)

    r = c.post("/admin/partidas/grant", data={
        "user_id": target.id, "workspace": WS, "partida_id": "partida:uno", "csrf_token": csrf,
    })
    assert r.status_code == 302

    with auth_db.get_conn(auth_env) as conn:
        access = auth_db.list_partida_access(conn, user_id=target.id)
    assert len(access) == 1
    assert access[0].partida_id == "partida:uno"

    # Auditoría registrada.
    with auth_db.get_conn(auth_env) as conn:
        events = auth_db.list_audit_events(conn, event_type="PARTIDA_ACCESS_GRANTED")
    assert len(events) == 1

    # Revocar.
    page2 = c.get("/admin/partidas", headers={"accept": "text/html"})
    csrf2 = re.search(r'name="csrf_token" value="([^"]*)"', page2.text).group(1)
    r2 = c.post(f"/admin/partidas/{access[0].id}/revoke", data={"csrf_token": csrf2})
    assert r2.status_code == 302

    with auth_db.get_conn(auth_env) as conn:
        access_after = auth_db.list_partida_access(conn, user_id=target.id)
        events2 = auth_db.list_audit_events(conn, event_type="PARTIDA_ACCESS_REVOKED")
    assert access_after == []
    assert len(events2) == 1


def test_no_admin_no_accede_a_gestion_de_partidas(auth_env):
    user = _make_user(auth_env, "viewer_llano")
    c = _logged_client(auth_env, user)
    r = c.get("/admin/partidas", headers={"accept": "text/html"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Retrocompatibilidad explícita end-to-end
# ---------------------------------------------------------------------------

def test_usuario_admin_ve_ambas_partidas_sin_selector(auth_env):
    admin = _make_user(auth_env, "elgm2", role="admin")
    c = _logged_client(auth_env, admin)
    ids = _entity_ids(c)
    assert {"partida1_pc_arden", "partida2_pc_bryn", "lore_dios_sol",
            "legacy_material_sin_partida", "partida1_sin_revelacion"} == ids

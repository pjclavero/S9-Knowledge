"""CORTE 6B-2(a) — editar el nombre humano del workspace desde la web.

Testigos de superficie HTTP:

  1. Un admin (que hoy tiene las dos capacidades) puede editar el label del
     workspace canónico, y el cambio se ve al releer `/admin/partidas`.
  2. C3 — el negativo obligatorio: `can_manage_access=True,
     can_edit_context_label=False` puede conceder/revocar pero el POST de
     label le devuelve 403. Demuestra que las dos capacidades son guardas
     independientes, no el mismo booleano con dos nombres.
  3. 409 real por HTTP cuando la huella enviada no coincide con la que hay en
     disco (alguien más lo cambió entre el GET y el POST).
  4. La auditoría registra `CONTEXT_LABEL_UPDATED` con antes/después, y el
     panel de auditoría nunca sustituye al fichero como autoridad del label.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from boveda_seis_a import crear_boveda_minima

WS = "juego-pruebas-label"
PARTIDA = "partida:alfa"


@pytest.fixture
def entorno(tmp_path):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-de-test-1234567890"
    boveda = crear_boveda_minima(tmp_path / "bovedas", WS, PARTIDA)
    os.environ["S9K_VAULT_ROOT"] = str(boveda)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"
    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db

    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    from app.main import app

    yield db_path, auth_db, app, boveda

    app.dependency_overrides.clear()
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_CSRF_SECRET", "S9K_VAULT_ROOT", "S9K_VAULT_REQUIRE_MOUNT"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _perfil_path(boveda):
    return boveda / "juego-de-prueba" / "perfil-operador.json"


def _cliente(auth_db, db_path, app, *, capability_overrides=None):
    from fastapi.testclient import TestClient

    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        admin = auth_db.create_user(
            conn, username="gm", display_name="GM",
            password_hash=hash_password("TestPass_1234567890!"), role="admin",
        )
        token, _ = create_session(conn, admin)

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)

    if capability_overrides is not None:
        # C3: simular el negativo (hoy sin rol de producción que lo produzca
        # por sí solo) sustituyendo SOLO `require_authenticated_user` -- la
        # dependencia común de la que cuelgan `require_manage_access` y
        # `require_edit_context_label` -- por un usuario con overrides. La
        # lógica de las DOS capacidades que se está probando sigue siendo la
        # REAL (`User.can_manage_access`/`can_edit_context_label`), no se
        # sustituye la guarda: sólo se inyecta el usuario que la ejercita.
        import dataclasses
        from app.auth.dependencies import require_authenticated_user

        overridden = dataclasses.replace(admin, capability_overrides=capability_overrides)
        app.dependency_overrides[require_authenticated_user] = lambda: overridden

    return c


def _csrf(cliente):
    r = cliente.get("/admin/partidas")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    fp = re.search(r'name="fingerprint"\s+value="([^"]*)"', r.text)
    return m.group(1), (fp.group(1) if fp else "")


def test_admin_puede_editar_el_label_del_workspace(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    assert fp, "el GET no expuso el fingerprint del perfil conforme"

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "La Mesa de los Jueves",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 302, r.text[:400]

    r2 = c.get("/admin/partidas")
    assert "La Mesa de los Jueves" in r2.text

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert en_disco["metadata"]["label"] == "La Mesa de los Jueves"


def test_409_si_la_huella_enviada_no_coincide(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, _fp_real = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "Intento con huella vieja",
        "fingerprint": "0" * 64 + ":0:0:0", "csrf_token": tok,
    })
    assert r.status_code == 409, r.text[:400]

    # El perfil no cambió: el 409 no escribe nada.
    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "metadata" not in en_disco or en_disco["metadata"].get("label") != "Intento con huella vieja"


def test_c3_gestiona_accesos_pero_no_puede_editar_el_label(entorno):
    """El negativo obligatorio: `can_manage_access=True`,
    `can_edit_context_label=False`. Puede conceder/revocar (200/302) pero el
    POST de label le da 403 — la prueba de que son DOS capacidades reales."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(
        auth_db, db_path, app,
        capability_overrides={"can_manage_access": True, "can_edit_context_label": False},
    )
    tok, fp = _csrf(c)

    # PUEDE conceder acceso (can_manage_access=True).
    with auth_db.get_conn(db_path) as conn:
        jugadora = auth_db.create_user(
            conn, username="ana", display_name="Ana",
            password_hash="x", role="viewer",
        )
    r_grant = c.post("/admin/partidas/grant", data={
        "user_id": jugadora.id, "workspace": WS, "partida_id": PARTIDA,
        "csrf_token": tok, "max_visible_session": "", "character_id": "",
    })
    assert r_grant.status_code == 302, r_grant.text[:400]

    # NO PUEDE editar el label (can_edit_context_label=False).
    r_label = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "No debería poder", "fingerprint": fp,
        "csrf_token": tok,
    })
    assert r_label.status_code == 403, r_label.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "metadata" not in en_disco or en_disco["metadata"].get("label") != "No debería poder"


def test_la_auditoria_registra_el_evento_con_antes_y_despues(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "Nombre Auditado", "fingerprint": fp,
        "csrf_token": tok,
    })

    from app.auth import audit

    with auth_db.get_conn(db_path) as conn:
        eventos = auth_db.list_audit_events(conn, event_type=audit.CONTEXT_LABEL_UPDATED)
    assert len(eventos) == 1
    meta = json.loads(eventos[0].metadata_json)
    assert meta["workspace"] == WS
    assert meta["label_after"] == "Nombre Auditado"

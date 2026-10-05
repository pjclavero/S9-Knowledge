# -*- coding: utf-8 -*-
"""CORTE 6B-2(b) — editar el nombre humano de UNA PARTIDA desde la web.

Testigos de superficie HTTP (mismo patrón que `test_admin_label_6b2.py`,
adaptado a que la partida es OPCIONAL de elegir vía `?editar_partida=`):

  1. Un admin puede nombrar una partida REAL de la bóveda, y el cambio se ve
     al releer `/admin/partidas?editar_partida=<id>`.
  2. C3 — el mismo negativo: `can_manage_access=True,
     can_edit_context_label=False` -> 403 en el POST de partida también.
  3. 409 real cuando la huella no coincide.
  4. El identificador de la partida NUNCA es el `value` por defecto del
     formulario (D1), y el POST rechaza un nombre igual al identificador de
     la partida (comparación NFKC+casefold).
  5. Un `partida_id` que la bóveda NO reconoce se rechaza con 400 -- el
     mismo ámbito autorizado que ya protege `/admin/partidas/grant` --
     aunque se manipule el POST directamente.
  6. D2/D3 reutilizados: vacío borra, longitud/control se rechazan.
  7. La auditoría registra `CONTEXT_LABEL_UPDATED` con `scope=partida`.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from boveda_seis_a import crear_boveda_minima

WS = "juego-pruebas-label-partida"
PARTIDA = "partida:alfa"
PARTIDA_AJENA = "partida:no-existe"


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


def _manifiesto_path(boveda):
    return boveda / "juego-de-prueba" / "partidas" / PARTIDA / "manifiesto-partida.json"


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
        import dataclasses
        from app.auth.dependencies import require_authenticated_user

        overridden = dataclasses.replace(admin, capability_overrides=capability_overrides)
        app.dependency_overrides[require_authenticated_user] = lambda: overridden

    return c


def _csrf_partida(cliente, partida_id: str = PARTIDA):
    r = cliente.get("/admin/partidas", params={"editar_partida": partida_id})
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    # El GET pinta DOS formularios con campo `fingerprint` (workspace y
    # partida): se localiza el de la SECCIÓN de partida acotando por el bloque
    # `action="/admin/partidas/label-partida"`.
    bloque = r.text.split('action="/admin/partidas/label-partida"', 1)
    assert len(bloque) == 2, "no se encontró el formulario de nombre de partida"
    fp_match = re.search(r'name="fingerprint"\s+value="([^"]*)"', bloque[1])
    assert fp_match, "el formulario de partida no trae fingerprint"
    return m.group(1), fp_match.group(1), r.text


def test_admin_puede_nombrar_una_partida_real(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)
    assert fp, "el GET no expuso el fingerprint del manifiesto (ausente)"

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "Mesa de los Jueves",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 302, r.text[:400]

    r2 = c.get("/admin/partidas", params={"editar_partida": PARTIDA})
    assert "Mesa de los Jueves" in r2.text

    en_disco = json.loads(_manifiesto_path(boveda).read_text())
    assert en_disco["metadata"]["label"] == "Mesa de los Jueves"


def test_409_si_la_huella_enviada_no_coincide(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, _fp_real, _html = _csrf_partida(c)

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "Intento con huella vieja",
        "fingerprint": "0" * 64 + ":0:0:0", "csrf_token": tok,
    })
    assert r.status_code == 409, r.text[:400]
    assert not _manifiesto_path(boveda).exists()


def test_c3_gestiona_accesos_pero_no_puede_nombrar_la_partida(entorno):
    """C3 sin capacidad de edición ni siquiera ve el formulario (la pantalla
    ya lo oculta), así que el fingerprint se calcula con la MISMA huella
    "ausente" que expondría el formulario si estuviera visible -- la guarda
    real que se mide es la del servidor (403), no la del render."""
    from app import vault_writer as vw

    db_path, auth_db, app, boveda = entorno
    c = _cliente(
        auth_db, db_path, app,
        capability_overrides={"can_manage_access": True, "can_edit_context_label": False},
    )
    r = c.get("/admin/partidas", params={"editar_partida": PARTIDA})
    assert r.status_code == 200
    tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text).group(1)
    assert "No tienes capacidad para editar" in r.text

    r_label = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "No debería poder",
        "fingerprint": vw.huella_ausente().a_texto(), "csrf_token": tok,
    })
    assert r_label.status_code == 403, r_label.text[:400]
    assert not _manifiesto_path(boveda).exists()


def test_el_valor_del_formulario_nunca_es_el_identificador_de_partida(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    _tok, _fp, html = _csrf_partida(c)

    bloque = html.split('action="/admin/partidas/label-partida"', 1)[1]
    m_value = re.search(r'<input type="text" id="partida_label"[^>]*\bvalue="([^"]*)"', bloque)
    assert m_value, "el input de label de partida no se encontró"
    assert m_value.group(1) == "", (
        f"el value del input no está vacío sin label declarado: {m_value.group(1)!r}"
    )

    m_placeholder = re.search(
        r'<input type="text" id="partida_label"[^>]*\bplaceholder="([^"]*)"', bloque
    )
    assert m_placeholder and m_placeholder.group(1) == PARTIDA, (
        "el identificador de la partida debería ofrecerse como placeholder, no como value"
    )


def test_post_rechaza_label_igual_al_identificador_de_partida(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": PARTIDA,
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]
    assert not _manifiesto_path(boveda).exists()


def test_post_rechaza_partida_que_la_boveda_no_conoce(entorno):
    """Corte 6A extendido a este endpoint: manipular el POST no permite
    nombrar una partida que la bóveda real no clasifica en este workspace."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA_AJENA, "label": "Nombre Inventado",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]
    assert not (boveda / "juego-de-prueba" / "partidas" / PARTIDA_AJENA).exists()


def test_label_vacio_borra_el_nombre_humano_de_la_partida(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "Nombre que se va a borrar",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 302, r.text[:400]

    tok2, fp2, _html2 = _csrf_partida(c)
    r2 = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "",
        "fingerprint": fp2, "csrf_token": tok2,
    })
    assert r2.status_code == 302, r2.text[:400]

    en_disco = json.loads(_manifiesto_path(boveda).read_text())
    assert "label" not in en_disco.get("metadata", {})


def test_servidor_rechaza_label_de_partida_demasiado_largo(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "x" * 201,
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]
    assert not _manifiesto_path(boveda).exists()


def test_servidor_rechaza_caracteres_de_control_en_label_de_partida(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)

    r = c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "con\x00nulo",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]
    assert not _manifiesto_path(boveda).exists()


def test_la_auditoria_registra_el_evento_de_partida_con_scope(entorno):
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp, _html = _csrf_partida(c)
    c.post("/admin/partidas/label-partida", data={
        "workspace": WS, "partida_id": PARTIDA, "label": "Nombre Auditado",
        "fingerprint": fp, "csrf_token": tok,
    })

    from app.auth import audit

    with auth_db.get_conn(db_path) as conn:
        eventos = auth_db.list_audit_events(conn, event_type=audit.CONTEXT_LABEL_UPDATED)
    assert len(eventos) == 1
    meta = json.loads(eventos[0].metadata_json)
    assert meta["scope"] == "partida"
    assert meta["partida_id"] == PARTIDA
    assert meta["label_after"] == "Nombre Auditado"

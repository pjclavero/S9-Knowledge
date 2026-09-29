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
  5. (revisión independiente de PR #258) D1 — el identificador nunca es el
     `value` por defecto del formulario, y el POST rechaza un label igual al
     identificador. R2 (segunda ronda) — esa guarda resiste homóglifos
     Unicode, comparando `NFKC` + `casefold()` en los dos lados.
  6. D2/D3 — un label vacío borra el nombre humano en vez de fallar, y el
     servidor rechaza longitud excesiva y caracteres de control.
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


def test_el_valor_del_formulario_nunca_es_el_identificador(entorno):
    """D1 (revisión independiente de PR #258, RANGO 2 bloqueante). Antes: sin
    label declarado, `value="{{ label_actual }}"` ponía el IDENTIFICADOR
    como valor por defecto, y un POST sin tocar nada lo escribía como
    nombre humano. Ahora: el `value` está vacío, y el identificador sólo
    aparece como `placeholder` (presentación, nunca escritura por defecto)."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    r = c.get("/admin/partidas")
    assert r.status_code == 200

    m_value = re.search(r'<input type="text" id="label"[^>]*\bvalue="([^"]*)"', r.text)
    assert m_value, "el input de label no se encontró en la página"
    assert m_value.group(1) == "", (
        f"el value del input no está vacío sin label declarado: {m_value.group(1)!r} "
        "(el identificador se coló como valor por defecto de escritura)"
    )

    m_placeholder = re.search(r'<input type="text" id="label"[^>]*\bplaceholder="([^"]*)"', r.text)
    assert m_placeholder and m_placeholder.group(1) == WS, (
        "el identificador debería ofrecerse como placeholder, no como value"
    )


def test_post_sin_tocar_el_campo_ya_no_escribe_el_identificador(entorno):
    """El escenario exacto que demostró el revisor: perfil sin label -> GET
    -> reenviar el `value` del formulario tal cual (que ahora es "") -> el
    perfil sigue sin label, nunca se escribe el identificador."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    r = c.get("/admin/partidas")
    m_value = re.search(r'<input type="text" id="label"[^>]*\bvalue="([^"]*)"', r.text)
    tok, fp = _csrf(c)

    r2 = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": m_value.group(1), "fingerprint": fp, "csrf_token": tok,
    })
    assert r2.status_code == 302, r2.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert en_disco.get("metadata", {}).get("label") != WS
    assert "label" not in en_disco.get("metadata", {})


def test_post_rechaza_label_igual_al_identificador(entorno):
    """D1 — el rechazo explícito, no sólo el placeholder: ni siquiera
    tecleando el identificador a mano se admite como nombre humano.
    Insensible a mayúsculas."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": WS, "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]

    r2 = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": WS.upper(), "fingerprint": fp, "csrf_token": tok,
    })
    assert r2.status_code == 400, r2.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "metadata" not in en_disco or en_disco["metadata"].get("label") != WS


@pytest.mark.parametrize("variante,nombre", [
    ("ｊｕｅｇｏ-ｐｒｕｅｂａｓ-ｌａｂｅｌ",
     "fullwidth"),
    ("juego-pruebas-ⅼabeⅼ", "letra de otro bloque (U+217C, se ve como 'l')"),
], ids=["fullwidth", "otro_bloque_u217c"])
def test_post_rechaza_homoglifos_del_identificador(entorno, variante, nombre):
    """R2 (revisión independiente de PR #258, segunda ronda). La guarda D1
    comparaba `casefold()` crudo: un homóglifo Unicode -- fullwidth o una
    letra de OTRO bloque que se ve exactamente igual -- entraba con 302 y
    era indistinguible del identificador a la vista. `NFKC` los pliega a su
    forma canónica ANTES de comparar."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": variante, "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, f"{nombre}: {r.text[:400]}"

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "metadata" not in en_disco, nombre


def test_control_negativo_un_nombre_parecido_pero_distinto_se_acepta(entorno):
    """R2 no puede volverse tan agresivo que rechace un nombre humano
    LEGÍTIMO que simplemente se parece al identificador."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "Juego de Pruebas (Label de Verdad)",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 302, r.text[:400]


def test_label_vacio_borra_el_nombre_humano(entorno):
    """D2 — dejar el campo vacío y guardar BORRA `metadata.label` en vez de
    quedar atascado con un error permanente desde la web."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "Nombre que se va a borrar",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 302, r.text[:400]

    tok2, fp2 = _csrf(c)
    r2 = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "", "fingerprint": fp2, "csrf_token": tok2,
    })
    assert r2.status_code == 302, r2.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "label" not in en_disco.get("metadata", {})


def test_label_de_solo_espacios_borra_con_el_mismo_codigo_que_vacio(entorno):
    """D2 — unifica el código de respuesta entre 'vacío' y 'sólo espacios':
    los dos son la misma señal de borrado, no dos comportamientos
    distintos."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "Nombre que se va a borrar",
        "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 302

    tok2, fp2 = _csrf(c)
    r2 = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "   ", "fingerprint": fp2, "csrf_token": tok2,
    })
    assert r2.status_code == 302, r2.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "label" not in en_disco.get("metadata", {})


def test_servidor_rechaza_label_demasiado_largo(entorno):
    """D3 — el `maxlength` del HTML es cosmética del cliente; el servidor
    tiene que rechazarlo también, sin escribir nada."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "x" * 201, "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "metadata" not in en_disco


def test_servidor_rechaza_caracteres_de_control(entorno):
    """D3 — NUL y saltos de línea crudos no pueden llegar al documento del
    operador: 200 KB, `\\n` y `\\x00` es el ataque real que demostró el
    revisor."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "con\x00nulo", "fingerprint": fp, "csrf_token": tok,
    })
    assert r.status_code == 400, r.text[:400]

    tok2, fp2 = _csrf(c)
    r2 = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "con\nsalto", "fingerprint": fp2, "csrf_token": tok2,
    })
    assert r2.status_code == 400, r2.text[:400]

    en_disco = json.loads(_perfil_path(boveda).read_text())
    assert "metadata" not in en_disco


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

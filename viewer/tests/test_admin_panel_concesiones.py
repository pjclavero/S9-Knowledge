"""El PANEL como productor real de `max_visible_session` y `active_character`.

Sexto dictamen, H6-8 y H6-10. `routers/admin.py` esta DECLARADO en el registro
como productor de las dos dimensiones de contexto que mas pesan --el tope de
sesion y el personaje-- y no tenia ni una prueba: nada demostraba que lo que el
operador teclea llegue a `partida_access`. Un panel que ignora el formulario y
concede otra cosa (9999, o un personaje que no se puede quitar) es un bypass
invisible, porque la interfaz muestra lo que el operador escribio.

H6-10 ademas: el formulario decia `placeholder="vacio = sin tope"` mientras el
backend ya trataba el vacio como 0. Documentacion e implementacion diciendo lo
contrario es la misma clase de defecto que esta ronda cierra, sin codigo de por
medio.
"""
from __future__ import annotations

import os
import re

import pytest


@pytest.fixture
def entorno(tmp_path):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_DEFAULT_WORKSPACE"] = "juego:pruebas"
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-de-test-1234567890"
    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db

    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    from app.main import app

    yield db_path, auth_db, app

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_CSRF_SECRET"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


WS = "juego:pruebas"
PARTIDA = "partida:alfa"


def _cliente_admin(auth_db, db_path, app):
    from fastapi.testclient import TestClient

    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        admin = auth_db.create_user(
            conn, username="gm", display_name="GM",
            password_hash=hash_password("TestPass_1234567890!"), role="admin",
        )
        jugadora = auth_db.create_user(
            conn, username="ana", display_name="Ana",
            password_hash=hash_password("TestPass_1234567890!"), role="viewer",
        )
        token, _ = create_session(conn, admin)

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c, jugadora


def _csrf(cliente):
    r = cliente.get("/admin/partidas")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    return m.group(1), r.text


def _conceder(cliente, jugadora, tope, personaje):
    tok, _ = _csrf(cliente)
    return cliente.post("/admin/partidas/grant", data={
        "user_id": jugadora.id, "workspace": WS, "partida_id": PARTIDA,
        "csrf_token": tok, "max_visible_session": tope, "character_id": personaje,
    })


def test_el_tope_tecleado_en_el_panel_llega_a_la_concesion(entorno):
    """H6-8: nada probaba que el panel escribiera lo que el operador teclea."""
    db_path, auth_db, app = entorno
    c, jugadora = _cliente_admin(auth_db, db_path, app)
    r = _conceder(c, jugadora, "7", "pc:ana")
    assert r.status_code == 302, r.text[:400]

    with auth_db.get_conn(db_path) as conn:
        tope, pj = auth_db.partida_progress(conn, jugadora.id, WS, PARTIDA)
    assert tope == 7, f"el panel concedio {tope!r} en vez de lo tecleado"
    assert pj == "pc:ana"


def test_el_panel_puede_BAJAR_el_tope_y_no_solo_subirlo(entorno):
    """`INSERT OR IGNORE` sin UPDATE dejaba la primera concesion congelada."""
    db_path, auth_db, app = entorno
    c, jugadora = _cliente_admin(auth_db, db_path, app)
    _conceder(c, jugadora, "40", "pc:ana")
    _conceder(c, jugadora, "3", "pc:ana")

    with auth_db.get_conn(db_path) as conn:
        tope, _ = auth_db.partida_progress(conn, jugadora.id, WS, PARTIDA)
    assert tope == 3


def test_el_panel_puede_REVOCAR_el_personaje_dejandolo_en_blanco(entorno):
    """`active_character` salta la regla de nivel: si no se puede quitar desde
    el panel, es un permiso que el operador cree haber retirado y no retiro."""
    db_path, auth_db, app = entorno
    c, jugadora = _cliente_admin(auth_db, db_path, app)
    _conceder(c, jugadora, "5", "pc:ana")
    _conceder(c, jugadora, "5", "")

    with auth_db.get_conn(db_path) as conn:
        _, pj = auth_db.partida_progress(conn, jugadora.id, WS, PARTIDA)
    assert pj is None, "el personaje sobrevivio a una reconcesion en blanco"


def test_dejar_el_tope_en_blanco_concede_CERO_y_no_via_libre(entorno):
    """H6-10. Lo que el operador no teclea es la opcion mas restrictiva."""
    db_path, auth_db, app = entorno
    c, jugadora = _cliente_admin(auth_db, db_path, app)
    _conceder(c, jugadora, "", "")

    with auth_db.get_conn(db_path) as conn:
        accesos = auth_db.list_partida_access(conn, user_id=jugadora.id)
        tope, _ = auth_db.partida_progress(conn, jugadora.id, WS, PARTIDA)
    assert tope == 0
    assert accesos[0].max_visible_session == 0, (
        "se guardo NULL: indistinguible de una fila migrada, que es la "
        "ambiguedad que hubo que cerrar"
    )


def test_un_tope_no_numerico_se_rechaza_en_vez_de_ignorarse(entorno):
    db_path, auth_db, app = entorno
    c, jugadora = _cliente_admin(auth_db, db_path, app)
    r = _conceder(c, jugadora, "-1", "pc:ana")
    assert r.status_code == 400
    with auth_db.get_conn(db_path) as conn:
        assert auth_db.list_partida_access(conn, user_id=jugadora.id) == []


def test_el_formulario_no_promete_algo_distinto_de_lo_que_hace(entorno):
    """H6-10: el placeholder decia "vacio = sin tope" y el backend hacia 0."""
    db_path, auth_db, app = entorno
    c, _ = _cliente_admin(auth_db, db_path, app)
    _, html = _csrf(c)
    for promesa in ("sin tope", "sin límite", "sin limite"):
        assert promesa not in html, (
            f"el formulario sigue prometiendo '{promesa}', que no existe como "
            f"estado: el backend trata el vacío como 0"
        )
    assert "vacío = 0" in html or "vacio = 0" in html


def test_sin_CSRF_valido_el_panel_no_concede_nada(entorno):
    db_path, auth_db, app = entorno
    c, jugadora = _cliente_admin(auth_db, db_path, app)
    r = c.post("/admin/partidas/grant", data={
        "user_id": jugadora.id, "workspace": WS, "partida_id": PARTIDA,
        "csrf_token": "falso", "max_visible_session": "99", "character_id": "pc:ana",
    })
    assert r.status_code == 403
    with auth_db.get_conn(db_path) as conn:
        assert auth_db.list_partida_access(conn, user_id=jugadora.id) == []

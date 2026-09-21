# -*- coding: utf-8 -*-
"""CORTE F-2 · PIEZA 4 — la divergencia se ve ANTES de operar, y desde el producto.

Hasta este corte el unico sitio que comparaba declaraciones de workspace era
`deploy/scripts/preflight_ensayo_rc.py`, que **un arranque cualquiera no
ejecuta**. Un despliegue con el perfil de la boveda y el entorno diciendo cosas
distintas arrancaba sin una sola senal y se comportaba asi:

  - `/admin/partidas` pintaba el workspace del ENTORNO en un campo de solo
    lectura;
  - conceder acceso al workspace del PERFIL —donde acaba el conocimiento—
    devolvia 400 con un texto generico que no mencionaba la divergencia.

Aqui se fija que eso ya no pasa. LOS TESTIGOS DE UNA PANTALLA PIDEN LA PANTALLA:
todo lo que se afirma sobre lo que el operador ve se comprueba sobre el HTML de
un `GET`, no sobre un diccionario de servicio.

TECHO: estas pruebas miden el aviso y el diagnostico. NO miden que el
conocimiento acabe en un workspace u otro — eso lo mide
`test_f2_vault_workspace_hasta_neo4j.py` contra Neo4j real.
"""
from __future__ import annotations

import json
import os
import re

import pytest

#: Lo que declara el ENTORNO (hoy, la autoridad de `/admin/partidas`).
WS_ENTORNO = "ws-del-entorno"
#: Lo que declara el PERFIL de la boveda (la autoridad del conocimiento).
WS_PERFIL = "ws-del-perfil"


@pytest.fixture
def entorno(tmp_path):
    """Despliegue con las DOS autoridades declarando cosas distintas."""
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS_PERFIL}), encoding="utf-8"
    )

    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS_ENTORNO
    os.environ["S9K_INGEST_SOURCES_DIR"] = str(fuentes)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-de-test-1234567890"
    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db

    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    from app.main import app

    yield db_path, auth_db, app, fuentes

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_INGEST_SOURCES_DIR", "S9K_CSRF_SECRET"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _admin(auth_db, db_path):
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
    return jugadora, token


def _cliente(app, token):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c


def _pantalla(cliente) -> tuple[str, str]:
    """EL HTML de verdad, mas su csrf. Nada de diccionarios de servicio."""
    r = cliente.get("/admin/partidas")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    return r.text, m.group(1)


def _conceder(cliente, user_id, workspace, csrf):
    return cliente.post("/admin/partidas/grant", data={
        "user_id": user_id, "workspace": workspace, "partida_id": "partida:mesa1",
        "csrf_token": csrf, "max_visible_session": "5", "character_id": "",
    })


# ---------------------------------------------------------------------------
# LA PANTALLA AVISA
# ---------------------------------------------------------------------------

def test_la_pantalla_de_partidas_avisa_de_la_divergencia(entorno):
    db_path, auth_db, app, _ = entorno
    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))

    assert "aviso-autoridad-workspace" in html, (
        "la pantalla NO avisa de que las dos autoridades declaran workspaces "
        "distintos: el operador ve el del entorno y nada mas, que es el estado "
        "que este corte existe para eliminar"
    )
    # EL MENSAJE, no el color: tiene que nombrar el codigo y LAS DOS
    # declaraciones, o el aviso no sirve para corregir nada.
    assert "WORKSPACE_AUTHORITY_DIVERGENT" in html
    assert WS_PERFIL in html and WS_ENTORNO in html


def test_el_aviso_no_publica_rutas_internas(entorno):
    """Repo publico: se publican CODIGOS, no rutas ni texto libre del motor."""
    db_path, auth_db, app, fuentes = entorno
    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))

    assert str(fuentes) not in html, "la pantalla publica la ruta del almacen"
    assert "perfil-operador.json" not in html


# ---------------------------------------------------------------------------
# EL PUNTO DE OPERACION DICE LA CAUSA
# ---------------------------------------------------------------------------

def test_conceder_en_el_workspace_del_perfil_sigue_rechazandose_pero_con_causa(entorno):
    """Fail-closed IGUAL que antes; lo que cambia es que dice por que.

    La unidad de control del Corte 1 no se toca: el 400 sigue ahi. Si alguien
    la relajara para «arreglar» la divergencia, esta prueba se pondria roja.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, WS_PERFIL, csrf)

    assert r.status_code == 400, (
        f"la concesion en el workspace del perfil ya NO se rechaza ({r.status_code}): "
        "se habria abierto la puerta que el Corte 1 cerro"
    )
    cuerpo = r.text
    assert "WORKSPACE_AUTHORITY_DIVERGENT" in cuerpo, (
        "el 400 sigue siendo mudo: el operador no puede saber que lo que falla "
        "es que hay dos declaraciones de workspace, no su tecleo"
    )


def test_un_workspace_inventado_se_rechaza_SIN_inventar_una_causa(entorno):
    """NO SE FABRICA CAUSALIDAD.

    Con una errata cualquiera el producto no sabe por que se tecleo eso, asi
    que NO dice «divergencia». Si dijera lo mismo para los dos casos, el
    diagnostico no distinguiria nada y el test anterior seria un falso verde.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, "ws-que-nadie-declara", csrf)

    assert r.status_code == 400
    assert "WORKSPACE_AUTHORITY_DIVERGENT" not in r.text, (
        "se atribuye a la divergencia un rechazo que no tiene nada que ver: "
        "eso es fabricar causalidad"
    )


def test_el_workspace_del_entorno_sigue_concediendose(entorno):
    """CONTROL POSITIVO de la tabla.

    Sin esto, los dos rechazos de arriba saldrian verdes aunque el endpoint
    estuviera roto y rechazara TODO.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, WS_ENTORNO, csrf)
    assert r.status_code in (302, 303), r.text[:300]


# ---------------------------------------------------------------------------
# SIMETRICO — sin divergencia no hay aviso
# ---------------------------------------------------------------------------

def test_simetrico_una_configuracion_coherente_no_ensena_ningun_aviso(entorno):
    """Un gate que se pone rojo siempre no guarda, molesta."""
    from app.config import get_settings

    db_path, auth_db, app, fuentes = entorno
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS_ENTORNO}), encoding="utf-8"
    )
    get_settings.cache_clear()

    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))

    assert "aviso-autoridad-workspace" not in html, (
        "se avisa de una divergencia que no existe: perfil y entorno declaran "
        "lo mismo"
    )
    assert "WORKSPACE_AUTHORITY_DIVERGENT" not in html


def test_simetrico_un_despliegue_sin_perfil_tampoco_avisa(entorno):
    """Sin boveda solo habla el entorno: es el fallback, no una divergencia."""
    from app.config import get_settings

    db_path, auth_db, app, fuentes = entorno
    (fuentes / "perfil-operador.json").unlink()
    get_settings.cache_clear()

    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))
    assert "aviso-autoridad-workspace" not in html

# -*- coding: utf-8 -*-
"""CORTE 6A · SELECCIÓN REAL DE CONTEXTO.

La propiedad: un usuario puede elegir un contexto EXISTENTE sin conocer ni
teclear identificadores internos, y sólo puede elegir contextos que el
sistema REALMENTE conoce y autoriza.

Lo que este corte cambia en `/admin/partidas`:

  1. El campo `partida_id` deja de ser texto libre con un `datalist` que era
     un ECO de concesiones anteriores (circular: para conceder la PRIMERA
     partida había que teclearla de memoria). Pasa a ser un `<select>`
     pintado con `sources_catalog.partidas_descubiertas_en_boveda`, que
     enumera la BÓVEDA REAL (`vault_scope.clasificar`), independiente de
     `partida_access`.
  2. El servidor vuelve a calcular esa MISMA enumeración al recibir el POST:
     manipular el formulario (`curl`, DevTools) no permite conceder una
     partida que la bóveda no declara.
  3. Estado cero: sin bóveda consultable, o con bóveda consultable pero sin
     ninguna partida clasificable, la pantalla explica la situación y ofrece
     un CAMINO WEB (`/panel/operations`) -- nunca "escribe aquí el
     identificador".

Este fichero NO repite las pruebas del Corte 1 (unidad de control
`workspace, partida_id`) ni las de F-2 (autoridad del workspace): las dos
siguen vivas en sus propios ficheros y se ejecutan con la suite. Aquí se mide
específicamente la ENUMERACIÓN y su cumplimiento en las dos puntas (pantalla y
servidor).
"""
from __future__ import annotations

import os
import re

import pytest

from boveda_seis_a import crear_boveda_minima

WS = "juego:6a"


@pytest.fixture
def entorno(tmp_path):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-de-test-1234567890"
    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db

    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    from app.main import app

    yield tmp_path, db_path, auth_db, app

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_CSRF_SECRET", "S9K_VAULT_ROOT", "S9K_VAULT_REQUIRE_MOUNT"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _admin_y_jugadora(auth_db, db_path):
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
        tok, _ = create_session(conn, admin)
    return admin, jugadora, tok


def _cliente(app, token):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c


def _pantalla(cliente):
    r = cliente.get("/admin/partidas")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    return r.text, m.group(1)


def _conceder(cliente, csrf, user_id, workspace, partida_id):
    return cliente.post("/admin/partidas/grant", data={
        "user_id": user_id, "workspace": workspace, "partida_id": partida_id,
        "csrf_token": csrf, "max_visible_session": "0", "character_id": "",
    })


# ---------------------------------------------------------------------------
# ESTADO CERO — SIN BÓVEDA CONSULTABLE
# ---------------------------------------------------------------------------

def test_sin_boveda_configurada_no_pide_identificadores(entorno):
    """Sin `S9K_VAULT_ROOT` (ni `S9K_INGEST_SOURCES_DIR`), el catálogo cae en
    el material de ejemplo del repo, así que SÍ hay catálogo -- pero en modo
    plano, que nunca declara partida. Este es el estado "no hay nada que
    elegir todavía", y la pantalla lo dice sin pedir texto libre.
    """
    _tmp_path, db_path, auth_db, app = entorno
    _, _, tok = _admin_y_jugadora(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, tok))

    assert 'name="partida_id"' not in html, (
        "estado cero, y aun así se pinta un campo (select o input) para "
        "partida_id -- no hay ninguna opción real que ofrecer"
    )
    assert '/panel/operations' in html, (
        "el estado cero no ofrece ningún camino web para crear o conceder"
    )


def test_boveda_declarada_pero_vacia_de_partidas_ofrece_camino_no_texto(entorno):
    """Bóveda REAL, consultable, con ZERO partidas clasificables: distinto del
    caso anterior (ahí no había ni bóveda), pero misma doctrina de pantalla.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = tmp_path / "bovedas-vacia"
    juego = raiz / "l5r"
    (juego / "compartido" / "lore").mkdir(parents=True)
    (juego / "compartido" / "lore" / "nota.md").write_text("hola", encoding="utf-8")
    import json as _json
    from pathlib import Path as _Path
    plantilla = _json.loads(
        (_Path(__file__).resolve().parents[2] / "examples" / "ingesta-v3"
         / "perfil-operador.json").read_text(encoding="utf-8")
    )
    perfil = dict(plantilla)
    perfil["workspace"] = WS
    perfil["source_asset_id"] = f"profile:{WS}"
    (juego / "perfil-operador.json").write_text(
        _json.dumps(perfil, ensure_ascii=False), encoding="utf-8",
    )
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    _, _, tok = _admin_y_jugadora(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, tok))

    assert 'name="partida_id"' not in html, (
        "con cero partidas descubribles se sigue pintando un campo para "
        "elegir/escribir una partida"
    )
    assert '/panel/operations' in html, (
        "estado cero (bóveda vacía) sin camino web para crear la primera partida"
    )
    from app import sources_catalog
    assert sources_catalog.partidas_descubiertas_en_boveda(WS) == [], (
        "la bóveda de este test tiene una partida real: el escenario no mide "
        "estado cero"
    )


# ---------------------------------------------------------------------------
# CONTROL POSITIVO — LA BÓVEDA REAL OFRECE, Y TODO LO OFRECIDO SE PUEDE ELEGIR
# ---------------------------------------------------------------------------

def test_todas_las_opciones_ofrecidas_son_realmente_seleccionables(entorno):
    """Recorre TODAS las opciones que la pantalla pinta y las ejerce por HTTP,
    una a una. Ninguna puede fallar -- si el `<select>` mintiera sobre una
    opción, este es el testigo que lo vería.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = tmp_path / "bovedas"
    from boveda_seis_a import crear_boveda_minima as _cbm

    for partida in ("partida:cofradia", "partida:saga-sur"):
        base = raiz / f"juego-{partida.split(':')[1]}"
        # Reusa el mismo `carpeta_juego` neutro por partida y el MISMO
        # workspace para las dos, sin chocar entre sí (carpetas distintas).
        _cbm(raiz, WS, partida, carpeta_juego=f"juego-{partida.split(':')[1]}")
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    from app import sources_catalog
    descubiertas = sources_catalog.partidas_descubiertas_en_boveda(WS)
    assert descubiertas == sorted(["partida:cofradia", "partida:saga-sur"]), descubiertas

    _admin, jugadora, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)
    html, _ = _pantalla(cliente)

    # LO QUE LA PANTALLA OFRECE, leído del HTML -- no de la función interna.
    opciones = re.findall(r'<option value="([^"]+)">', html)
    ofrecidas = [o for o in opciones if o in descubiertas]
    assert set(ofrecidas) == set(descubiertas), (
        f"la pantalla ofrece {ofrecidas}, la bóveda declara {descubiertas}"
    )
    assert ofrecidas, "la pantalla no ofreció ninguna opción real"

    for partida in ofrecidas:
        _, csrf = _pantalla(cliente)
        r = _conceder(cliente, csrf, jugadora.id, WS, partida)
        assert r.status_code == 302, (
            f"la opción «{partida}» se pintó como elegible y el servidor la "
            f"rechazó: {r.status_code} {r.text[:300]}"
        )


def test_el_primer_grant_no_depende_de_ninguna_concesion_previa(entorno):
    """CORTE 6A punto 2/3: el admin hace el PRIMER grant de todo el despliegue
    -- cero filas en `partida_access` antes de este POST -- apoyado SÓLO en
    lo que la bóveda declara, no en un censo de concesiones que aún no existe.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = tmp_path / "bovedas"
    crear_boveda_minima(raiz, WS, "partida:primera")
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    with auth_db.get_conn(db_path) as conn:
        assert auth_db.list_partida_access(conn) == [], (
            "el escenario ya tenía concesiones: no mide el primer grant"
        )

    _admin, jugadora, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)
    html, csrf = _pantalla(cliente)
    assert '<option value="partida:primera">' in html

    r = _conceder(cliente, csrf, jugadora.id, WS, "partida:primera")
    assert r.status_code == 302, r.text[:300]


# ---------------------------------------------------------------------------
# EL SERVIDOR VALIDA SIEMPRE — MANIPULAR EL POST NO INVENTA CONTEXTO
# ---------------------------------------------------------------------------

def test_post_con_partida_id_fuera_de_la_enumeracion_se_rechaza(entorno):
    """El formulario ya no ofrece texto libre, pero un POST directo (curl,
    DevTools) sí puede mandar cualquier cadena. El servidor vuelve a comprobar
    la MISMA enumeración: no basta con que la pantalla no lo ofrezca.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = tmp_path / "bovedas"
    crear_boveda_minima(raiz, WS, "partida:real")
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    _admin, jugadora, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, csrf, jugadora.id, WS, "partida:inventada-por-curl")
    assert r.status_code == 400, (
        f"un partida_id que la bóveda no declara se aceptó: {r.status_code}"
    )
    with auth_db.get_conn(db_path) as conn:
        assert auth_db.list_partida_access(conn) == [], (
            "quedó una fila viva para una partida que la bóveda no conoce"
        )


def test_post_con_workspace_manipulado_sigue_rechazandose(entorno):
    """Negativo hermano, ya cerrado por el Corte 1 -- se re-mide aquí para que
    la tabla de este corte quede completa en un solo fichero.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = tmp_path / "bovedas"
    crear_boveda_minima(raiz, WS, "partida:real")
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    _admin, jugadora, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, csrf, jugadora.id, "juego:otro-inventado", "partida:real")
    assert r.status_code == 400, (
        f"un workspace que ningún perfil declara se aceptó: {r.status_code}"
    )


# ---------------------------------------------------------------------------
# LA ENUMERACIÓN NO CRUZA WORKSPACES — unidad, sin pasar por la autoridad
# canónica de la petición (que colapsa con DOS perfiles divergentes; ver
# `authz.autoridad_workspace.resolver`, COD_VARIOS_PERFILES). Esta propiedad
# de `partidas_descubiertas_en_boveda` se mide aquí, directa.
# ---------------------------------------------------------------------------

def test_partidas_descubiertas_no_cruza_workspaces(tmp_path):
    from app import sources_catalog

    raiz = tmp_path / "bovedas"
    crear_boveda_minima(raiz, "juego:propio", "partida:propia",
                         carpeta_juego="juego-propio")
    crear_boveda_minima(raiz, "juego:ajeno", "partida:ajena",
                         carpeta_juego="juego-ajeno")

    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"
    try:
        descubiertas = sources_catalog.partidas_descubiertas_en_boveda("juego:propio")
    finally:
        os.environ.pop("S9K_VAULT_ROOT", None)
        os.environ.pop("S9K_VAULT_REQUIRE_MOUNT", None)

    assert descubiertas == ["partida:propia"], (
        f"la enumeración de 'juego:propio' se filtró en {descubiertas}: "
        "cruzó una partida de otro workspace, o perdió la propia"
    )

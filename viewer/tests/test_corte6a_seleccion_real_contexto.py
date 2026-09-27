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
              "S9K_CSRF_SECRET", "S9K_VAULT_ROOT", "S9K_VAULT_REQUIRE_MOUNT",
              "S9K_PANEL_B_ENABLED"):
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


def _boveda_vacia(tmp_path, workspace):
    """Una bóveda REAL (montaje simulado sin exigir montaje), con material de
    capa juego pero SIN NINGUNA partida bajo `partidas/`.
    """
    import json as _json
    from pathlib import Path as _Path

    raiz = tmp_path / "bovedas-vacia"
    juego = raiz / "l5r"
    (juego / "compartido" / "lore").mkdir(parents=True)
    (juego / "compartido" / "lore" / "nota.md").write_text("hola", encoding="utf-8")
    plantilla = _json.loads(
        (_Path(__file__).resolve().parents[2] / "examples" / "ingesta-v3"
         / "perfil-operador.json").read_text(encoding="utf-8")
    )
    perfil = dict(plantilla)
    perfil["workspace"] = workspace
    perfil["source_asset_id"] = f"profile:{workspace}"
    (juego / "perfil-operador.json").write_text(
        _json.dumps(perfil, ensure_ascii=False), encoding="utf-8",
    )
    return raiz


# ---------------------------------------------------------------------------
# ESTADO CERO — SIN BÓVEDA CONSULTABLE
# ---------------------------------------------------------------------------

def test_sin_boveda_declarada_partidas_descubiertas_levanta(entorno):
    """RONDA 2 · H2, unidad: sin ningún árbol de bóvedas declarado
    (`S9K_VAULT_ROOT` sin fijar), `partidas_descubiertas_en_boveda` debe
    LEVANTAR `CatalogoNoDisponible`, no degradar a `[]`. `[]` se lee como
    "bóveda real, cero partidas"; sin bóveda declarada la afirmación correcta
    es "no hay bóveda que preguntar", y son estados de verdad distintos.
    """
    from app import sources_catalog

    with pytest.raises(sources_catalog.CatalogoNoDisponible):
        sources_catalog.partidas_descubiertas_en_boveda(WS)


def test_sin_boveda_configurada_no_pide_identificadores_ni_finge_vacio(entorno):
    """Sin `S9K_VAULT_ROOT`, el catálogo cae en modo plano: no hay bóveda que
    preguntar. Este es el estado "no se sabe", DISTINTO de "se preguntó y está
    vacía" (ver el siguiente test): la pantalla no pide texto libre, no
    inventa que hay un árbol vacío, y el POST se rechaza igual.
    """
    _tmp_path, db_path, auth_db, app = entorno
    _, jugadora, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)
    html, csrf = _pantalla(cliente)

    assert 'name="partida_id"' not in html, (
        "estado 'no se sabe', y aun así se pinta un campo (select o input) "
        "para partida_id -- no hay ninguna opción real que ofrecer"
    )
    assert 'id="aviso_boveda_no_disponible"' in html, (
        "no se distingue 'no hay bóveda' de 'bóveda vacía' en la pantalla"
    )
    assert "el árbol no tiene material clasificable" not in html, (
        "la pantalla afirma que hay un árbol (vacío) cuando no hay ningún "
        "árbol declarado -- exactamente la falsa confirmación de H2"
    )
    assert "S9K_VAULT_ROOT" in html, (
        "no dice qué hace falta declarar para poder consultar la bóveda"
    )

    r = _conceder(cliente, csrf, jugadora.id, WS, "partida:cualquiera")
    assert r.status_code == 400, (
        f"sin bóveda declarada, un grant se aceptó igual: {r.status_code}"
    )


def test_boveda_real_vacia_de_partidas_se_distingue_de_sin_boveda(entorno):
    """Bóveda REAL, consultable, con ZERO partidas clasificables: estado
    DISTINTO del anterior (ahí no había ni árbol), y la pantalla lo dice con
    su propio mensaje y su propio id.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = _boveda_vacia(tmp_path, WS)
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    from app import sources_catalog
    assert sources_catalog.partidas_descubiertas_en_boveda(WS) == [], (
        "la bóveda de este test tiene una partida real: el escenario no mide "
        "estado cero"
    )

    _, _, tok = _admin_y_jugadora(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, tok))

    assert 'name="partida_id"' not in html, (
        "con cero partidas descubribles se sigue pintando un campo para "
        "elegir/escribir una partida"
    )
    assert 'id="aviso_boveda_vacia"' in html, (
        "no se distingue 'bóveda vacía' de 'no hay bóveda' en la pantalla"
    )
    assert 'id="aviso_boveda_no_disponible"' not in html


def test_boveda_vacia_con_panel_b_apagado_no_ofrece_enlace_muerto(entorno):
    """RONDA 2 · H3: de fábrica el hueco B (`/panel/operations`) está apagado
    (`S9K_PANEL_B_ENABLED=false`). Ofrecer el enlace igual sería un enlace
    MUERTO (404): se mide primero que `/panel/operations` es, en efecto, 404
    en este estado, y luego que la pantalla NO lo enlaza -- dice la verdad en
    su lugar.
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = _boveda_vacia(tmp_path, WS)
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"
    os.environ.pop("S9K_PANEL_B_ENABLED", None)

    _, _, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)

    r_panel = cliente.get("/panel/operations")
    assert r_panel.status_code == 404, (
        "el escenario no reproduce un hueco B apagado de verdad"
    )

    html, _ = _pantalla(cliente)
    assert '<a href="/panel/operations"' not in html, (
        "la pantalla enlaza un camino que hoy devuelve 404: enlace muerto"
    )
    assert "S9K_PANEL_B_ENABLED" in html, (
        "no dice qué hace falta encender para tener un camino web real"
    )


def test_boveda_vacia_con_panel_b_encendido_ofrece_enlace_vivo(entorno):
    """Simétrico del anterior: con el hueco B encendido, el camino web SÍ
    existe y la pantalla SÍ lo enlaza -- y se comprueba que el destino
    responde, no sólo que la cadena aparezca en el HTML (el patrón que S1 ya
    cerró para el enlace de resultado).
    """
    tmp_path, db_path, auth_db, app = entorno
    raiz = _boveda_vacia(tmp_path, WS)
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"
    os.environ["S9K_PANEL_B_ENABLED"] = "true"

    _, _, tok = _admin_y_jugadora(auth_db, db_path)
    cliente = _cliente(app, tok)

    html, _ = _pantalla(cliente)
    assert '<a href="/panel/operations"' in html, (
        "con el hueco B encendido la pantalla no ofrece el camino web"
    )

    r_panel = cliente.get("/panel/operations")
    assert r_panel.status_code != 404, (
        f"el camino que la pantalla ofrece sigue siendo un enlace muerto: "
        f"{r_panel.status_code}"
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


# ---------------------------------------------------------------------------
# LO OFRECIDO ES *EXACTAMENTE* LO QUE LA FUNCIÓN COMPARTIDA DICE — no una
# copia independiente que pantalla y servidor pudieran ver divergir.
#
# RONDA 2 DE REVISIÓN: `test_partidas_descubiertas_no_cruza_workspaces` sólo
# muta la función que ALIMENTA a la vez la pantalla y el servidor, así que una
# mutación sobre ella mueve las dos puntas a la vez y NO PUEDE demostrar
# divergencia por construcción. Este testigo alimenta la pantalla con una
# fila de `partida_access` que NO está en la bóveda (el eco viejo, circular),
# y exige que la pantalla NO la ofrezca -- si `/admin/partidas` alguna vez
# volviera a leer de `access` en vez de la función compartida, este testigo
# la vería sin necesidad de un POST completo.
# ---------------------------------------------------------------------------

def test_lo_ofrecido_es_exactamente_la_enumeracion_compartida_no_access(entorno):
    tmp_path, db_path, auth_db, app = entorno
    raiz = tmp_path / "bovedas"
    crear_boveda_minima(raiz, WS, "partida:real-en-la-boveda")
    os.environ["S9K_VAULT_ROOT"] = str(raiz)
    os.environ["S9K_VAULT_REQUIRE_MOUNT"] = "0"

    admin, jugadora, tok = _admin_y_jugadora(auth_db, db_path)
    # Fila fantasma en `partida_access`, EL ECO VIEJO: si la pantalla la
    # ofreciera, sería exactamente la circularidad que el Corte 6A cerró.
    with auth_db.get_conn(db_path) as conn:
        auth_db.grant_partida_access(
            conn, jugadora.id, WS, "partida:solo-en-access",
            granted_by=admin.username,
        )

    from app import sources_catalog
    esperado = sources_catalog.partidas_descubiertas_en_boveda(WS)

    html, _ = _pantalla(_cliente(app, tok))
    ofrecido = sorted(re.findall(r'<option value="(partida:[^"]+)">', html))

    assert ofrecido == sorted(esperado), (
        f"la pantalla ofrece {ofrecido}, y la función compartida (la misma "
        f"que valida el POST) dice {sorted(esperado)}: divergieron"
    )
    assert "partida:solo-en-access" not in ofrecido, (
        "la pantalla volvió a ofrecer una partida que sólo existe como fila "
        "de `partida_access`, no en el árbol -- el eco circular de antes"
    )

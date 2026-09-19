"""CORTE 1 — la existencia de una partida es el par `(workspace, partida_id)`.

El defecto medido: `/admin/partidas` aceptaba los tres campos de ámbito como
texto libre. Conceder `workspace=juego:inventado-no-existe` devolvía 302 y una
fila viva en «Asignaciones existentes». Y no era cosmético: `partida_exists`
hacía `SELECT 1 FROM partida_access WHERE partida_id = ?` SIN filtrar por
workspace, de modo que esa concesión fantasma convertía su `partida_id` en
«partida existente» para todo el despliegue, EL WORKSPACE REAL INCLUIDO.

Sus dos lectores son `routers/partida.py` (activar partida) y
`authz/dependencies.py` (re-verificación por petición del acceso de un admin).
El remate: el docstring de `partida_exists` declaraba existir «para que un admin
no pueda activar una partida inventada por error tipográfico», y el formulario
de texto libre desarmaba esa única guarda antierratas.

Estas pruebas recorren la matriz caso a caso, sobre los TRES consumidores.
"""
from __future__ import annotations

import os
import re

import pytest

WS = "juego:real"
WS_AJENO = "juego:otro"
WS_FANTASMA = "juego:inventado-no-existe"
PARTIDA = "partida:mesa1"
PARTIDA_FANTASMA = "partida:tampoco-existe"


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

    yield db_path, auth_db, app

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_CSRF_SECRET"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _usuarios(auth_db, db_path):
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
        tok_admin, _ = create_session(conn, admin)
    return admin, jugadora, tok_admin


def _cliente(app, token):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c


def _csrf(cliente):
    r = cliente.get("/admin/partidas")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    return m.group(1), r.text


def _conceder(cliente, user_id, workspace, partida_id):
    tok, _ = _csrf(cliente)
    return cliente.post("/admin/partidas/grant", data={
        "user_id": user_id, "workspace": workspace, "partida_id": partida_id,
        "csrf_token": tok, "max_visible_session": "5", "character_id": "pc:ana",
    })


def _sembrar_fantasma(auth_db, db_path, user_id, workspace, partida_id):
    """La concesión fantasma, escrita DIRECTAMENTE en la tabla.

    Salta el panel a propósito: el negativo sensible tiene que demostrar que el
    agujero está cerrado POR DEBAJO, no sólo que el formulario ya no lo fabrica.
    Es exactamente la fila que el panel de texto libre producía.
    """
    with auth_db.get_conn(db_path) as conn:
        auth_db.grant_partida_access(
            conn, user_id, workspace, partida_id, granted_by="fantasma",
            max_visible_session=5, character_id=None,
        )


# ---------------------------------------------------------------------------
# LA UNIDAD DE CONTROL, en la función que la decide
# ---------------------------------------------------------------------------

def test_workspace_A_partida_X_existente_VALIDA_en_A(entorno):
    db_path, auth_db, app = entorno
    _, jugadora, _ = _usuarios(auth_db, db_path)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS, PARTIDA)

    from app.authz import existencia

    with auth_db.get_conn(db_path) as conn:
        assert existencia.partida_existe(conn, WS, PARTIDA) is True


def test_EL_CRUCE_workspace_B_partida_X_inexistente_NO_valida_en_B(entorno):
    """El caso que hoy pasa: X concedida en A hacía «existir» X en B."""
    db_path, auth_db, app = entorno
    _, jugadora, _ = _usuarios(auth_db, db_path)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS_AJENO, PARTIDA)

    from app.authz import existencia

    with auth_db.get_conn(db_path) as conn:
        assert existencia.partida_existe(conn, WS, PARTIDA) is False, (
            "una concesión en otro workspace sigue tiñendo de existente ese "
            "partida_id en el workspace canónico: el cruce no está cerrado"
        )


def test_un_workspace_inventado_no_contiene_partidas_ni_las_suyas(entorno):
    db_path, auth_db, app = entorno
    _, jugadora, _ = _usuarios(auth_db, db_path)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS_FANTASMA, PARTIDA)

    from app.authz import existencia

    with auth_db.get_conn(db_path) as conn:
        assert existencia.partida_existe(conn, WS_FANTASMA, PARTIDA) is False, (
            "un workspace inventado se comporta como un ámbito real: contiene "
            "las partidas que se le concedan"
        )


# ---------------------------------------------------------------------------
# CONSUMIDOR 1 — conceder
# ---------------------------------------------------------------------------

def test_conceder_con_workspace_inventado_NO_crea_existencia(entorno):
    db_path, auth_db, app = entorno
    _, jugadora, tok = _usuarios(auth_db, db_path)
    c = _cliente(app, tok)

    r = _conceder(c, jugadora.id, WS_FANTASMA, PARTIDA_FANTASMA)
    assert r.status_code == 400, (
        f"el panel devolvió {r.status_code}: la concesión en un workspace "
        f"inventado se guardó igual que antes"
    )
    with auth_db.get_conn(db_path) as conn:
        assert auth_db.list_partida_access(conn) == [], (
            "quedó una fila viva en «Asignaciones existentes», con fecha y "
            "botón de revocar, para un workspace que no existe"
        )


def test_conceder_en_el_workspace_canonico_sigue_funcionando(entorno):
    """Control positivo: la guarda no cierra el caso legítimo."""
    db_path, auth_db, app = entorno
    _, jugadora, tok = _usuarios(auth_db, db_path)
    c = _cliente(app, tok)

    r = _conceder(c, jugadora.id, WS, PARTIDA)
    assert r.status_code == 302, r.text[:400]
    from app.authz import existencia

    with auth_db.get_conn(db_path) as conn:
        assert existencia.partida_existe(conn, WS, PARTIDA) is True


# ---------------------------------------------------------------------------
# CONSUMIDOR 2 — activar
# ---------------------------------------------------------------------------

def test_activar_X_en_workspace_incorrecto_es_RECHAZADO(entorno):
    """La concesión vive en otro workspace; el admin activa en el canónico."""
    db_path, auth_db, app = entorno
    _, jugadora, tok = _usuarios(auth_db, db_path)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS_AJENO, PARTIDA)
    c = _cliente(app, tok)
    tok_csrf, _ = _csrf(c)

    r = c.post("/partida/select", data={"partida_id": PARTIDA, "next": "/",
                                        "csrf_token": tok_csrf})
    assert r.status_code == 400, (
        f"el admin activó {PARTIDA}, que sólo existe en {WS_AJENO}: "
        f"status {r.status_code}"
    )


def test_activar_una_partida_fantasma_es_RECHAZADO(entorno):
    db_path, auth_db, app = entorno
    _, _, tok = _usuarios(auth_db, db_path)
    c = _cliente(app, tok)
    tok_csrf, _ = _csrf(c)

    r = c.post("/partida/select", data={"partida_id": PARTIDA_FANTASMA,
                                        "next": "/", "csrf_token": tok_csrf})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# CONSUMIDOR 3 — re-verificación por petición
# ---------------------------------------------------------------------------

def test_reverificar_una_concesion_CRUZADA_es_RECHAZADO(entorno):
    """`_still_has_access` admitía cualquier partida de la tabla para un admin.

    Se fija la partida activa a mano en la sesión (como si se hubiera activado
    antes del arreglo) y se comprueba que la re-verificación de la SIGUIENTE
    petición la degrada a capa juego.
    """
    db_path, auth_db, app = entorno
    admin, jugadora, tok = _usuarios(auth_db, db_path)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS_AJENO, PARTIDA)

    with auth_db.get_conn(db_path) as conn:
        sid = conn.execute(
            "SELECT id FROM sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
        auth_db.set_session_active_partida(conn, sid, PARTIDA)
        assert auth_db.get_session_by_id(conn, sid).active_partida == PARTIDA

    c = _cliente(app, tok)
    # Una peticion que SI construye el ViewerContext: ahi vive la
    # re-verificacion. `GET /` no depende de `get_visibility_context`.
    r = c.get("/api/entities?limit=1", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text[:300]

    with auth_db.get_conn(db_path) as conn:
        activa = auth_db.get_session_by_id(conn, sid).active_partida
    assert activa is None, (
        f"la re-verificación aceptó una partida de {WS_AJENO} como válida en "
        f"{WS} y dejó {activa!r} activa"
    )


# ---------------------------------------------------------------------------
# EL NEGATIVO SENSIBLE
# ---------------------------------------------------------------------------

def test_la_concesion_FANTASMA_no_altera_la_existencia_de_ninguna_canonica(entorno):
    """El testigo del corte.

    Se crea deliberadamente la concesión fantasma que hoy hace pasar la guarda
    —`juego:inventado-no-existe` / `partida:tampoco-existe`— y se comprueba que,
    después del arreglo, NO cambia la existencia de nada canónico: ni inventa la
    partida en el workspace real, ni afecta a la partida real que sí existe.
    """
    db_path, auth_db, app = entorno
    _, jugadora, tok = _usuarios(auth_db, db_path)
    from app.authz import existencia

    # Estado canónico de partida: una real, una inexistente.
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS, PARTIDA)
    with auth_db.get_conn(db_path) as conn:
        antes = {
            (WS, PARTIDA): existencia.partida_existe(conn, WS, PARTIDA),
            (WS, PARTIDA_FANTASMA): existencia.partida_existe(conn, WS, PARTIDA_FANTASMA),
        }
    assert antes == {(WS, PARTIDA): True, (WS, PARTIDA_FANTASMA): False}

    # La concesión fantasma, escrita por debajo del panel.
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS_FANTASMA, PARTIDA_FANTASMA)

    with auth_db.get_conn(db_path) as conn:
        despues = {
            (WS, PARTIDA): existencia.partida_existe(conn, WS, PARTIDA),
            (WS, PARTIDA_FANTASMA): existencia.partida_existe(conn, WS, PARTIDA_FANTASMA),
        }
    assert despues == antes, (
        f"la concesión fantasma alteró la existencia canónica: {antes} -> {despues}"
    )

    # Y tampoco es activable por el admin.
    c = _cliente(app, tok)
    tok_csrf, _ = _csrf(c)
    r = c.post("/partida/select", data={"partida_id": PARTIDA_FANTASMA,
                                        "next": "/", "csrf_token": tok_csrf})
    assert r.status_code == 400, (
        "la concesión fantasma sigue haciendo activable una partida inventada"
    )


# ---------------------------------------------------------------------------
# UN SOLO SITIO QUE DECIDE
# ---------------------------------------------------------------------------

def test_los_tres_consumidores_entran_por_app_authz_existencia():
    """Garantía estructural, por AST y no por grep de texto.

    Si mañana un cuarto sitio vuelve a preguntar «¿existe esta partida?» por su
    cuenta llamando a `auth_db.partida_exists`, esta prueba se pone roja. El
    techo declarado: ve llamadas escritas como `<algo>.partida_exists(...)` o
    `partida_exists(...)`; NO vería un `getattr(auth_db, "partida_" + "exists")`
    ni una importación renombrada con `as`.
    """
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parent.parent / "app"
    permitidos = {"auth/db.py", "authz/existencia.py"}
    culpables = []
    for fichero in raiz.rglob("*.py"):
        rel = fichero.relative_to(raiz).as_posix()
        if rel in permitidos:
            continue
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            f = nodo.func
            nombre = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if nombre == "partida_exists":
                culpables.append(f"{rel}:{nodo.lineno}")

    assert culpables == [], (
        "hay consumidores que preguntan por la existencia de una partida sin "
        f"pasar por app.authz.existencia: {culpables}"
    )


def test_partida_exists_exige_el_workspace_y_no_lo_hace_opcional():
    """La firma es la barrera: un llamante viejo tiene que ROMPER, no colar.

    Si `workspace` fuese opcional o fuese el segundo parámetro, el código
    anterior seguiría compilando y devolvería `False` en silencio —un
    fail-closed mudo indistinguible de la guarda funcionando.
    """
    import inspect

    from app.auth.db import partida_exists

    params = list(inspect.signature(partida_exists).parameters.values())
    nombres = [p.name for p in params]
    assert nombres == ["conn", "workspace", "partida_id"], nombres
    assert all(p.default is inspect.Parameter.empty for p in params), (
        "algún parámetro de ámbito tiene default: un llamante puede omitirlo"
    )


# ---------------------------------------------------------------------------
# LA PANTALLA — la garantía es visible, así que el testigo la PIDE
# ---------------------------------------------------------------------------

def test_el_formulario_ya_no_pide_el_workspace_de_memoria(entorno):
    db_path, auth_db, app = entorno
    _, _, tok = _usuarios(auth_db, db_path)
    c = _cliente(app, tok)
    _, html = _csrf(c)

    m = re.search(r'<input[^>]*\bid="workspace"[^>]*>', html)
    assert m, "el campo workspace desapareció de la pantalla"
    campo = m.group(0)
    assert "readonly" in campo, f"el workspace sigue siendo texto libre: {campo}"
    assert f'value="{WS}"' in campo, (
        f"el campo no muestra el workspace canónico {WS}: {campo}"
    )


def test_la_pantalla_ofrece_las_partidas_ya_concedidas_y_dice_que_no_son_un_censo(entorno):
    db_path, auth_db, app = entorno
    _, jugadora, tok = _usuarios(auth_db, db_path)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS, PARTIDA)
    _sembrar_fantasma(auth_db, db_path, jugadora.id, WS_AJENO, "partida:ajena")
    c = _cliente(app, tok)
    _, html = _csrf(c)

    assert 'list="partidas_existentes"' in html, (
        "el campo Partida sigue pidiendo el identificador de memoria: no hay "
        "lista, ni desplegable, ni ninguna pantalla que diga qué partidas hay"
    )
    assert f'<option value="{PARTIDA}">' in html, (
        "la pantalla no ofrece la partida que sí existe en este workspace"
    )
    assert '<option value="partida:ajena">' not in html, (
        "la pantalla ofrece partidas de otro workspace como si fueran de éste"
    )
    assert "no tiene censo de partidas" in html, (
        "la pantalla presenta la lista como si fuera un censo: eso es una "
        "falsa confirmación, que es justo lo que este corte cierra"
    )

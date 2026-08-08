"""Cadena de autorizacion COMPLETA, atravesada por HTTP (M5b-C).

Ninguna de las cinco rondas de revision anteriores probo esto. Todas las
pruebas del motor fabricaban el `ViewerContext` a mano, y por eso los defectos
vivian justo en los tramos que ese atajo se salta:

    HTTP -> autenticacion -> partida activa -> concesion en auth.db
         -> ViewerContext -> provider -> policy -> respuesta

H-A es el ejemplo exacto: el motor estaba bien, sus pruebas verdes, y el dato
que necesitaba no lo escribia nadie. Un test que inyecta el contexto no puede
detectarlo, por construccion.

Aqui NO se construye ningun `ViewerContext`: se concede en la base, se pide por
HTTP con cookie de sesion real, y se mira lo que devuelve el visor.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _limpia_settings():
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_GRAPH_PROVIDER",
              "S9K_DEFAULT_WORKSPACE"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


WS = "juego:pruebas"
PARTIDA = "partida:alfa"

#: Grafo minimo. Todo declara ambito y visibilidad: son datos "nacidos" bajo el
#: contrato nuevo, no legacy.
NODOS = [
    {"id": "revelado_s2", "label": "Revelado en la 2", "type": "Evento",
     "workspace": WS, "scope": "partida", "partida_id": PARTIDA,
     "visibility": "player", "known_from_session": 2},
    {"id": "spoiler_s40", "label": "Spoiler de la 40", "type": "Evento",
     "workspace": WS, "scope": "partida", "partida_id": PARTIDA,
     "visibility": "player", "known_from_session": 40},
    {"id": "spoiler_conocido", "label": "Spoiler que el PJ ya sabe", "type": "Evento",
     "workspace": WS, "scope": "partida", "partida_id": PARTIDA,
     "visibility": "player", "known_from_session": 40, "known_by": ["pc:ana"]},
    {"id": "lore", "label": "Lore compartido", "type": "Regla",
     "workspace": WS, "scope": "juego", "visibility": "player"},
]


class _ProveedorFalso:
    """Proveedor minimo: el objetivo es la CADENA, no el driver de Neo4j."""

    name = "fake"

    def workspaces(self):
        return [WS]

    def graph(self, workspace=None, **kw):
        return list(NODOS), []

    def list_entities(self, workspace, **kw):
        return list(NODOS), len(NODOS)

    def entity(self, entity_id, *, workspaces=None):
        for n in NODOS:
            if n["id"] == entity_id:
                if workspaces is not None and n.get("workspace") not in workspaces:
                    return None
                return n
        return None

    def search(self, workspace, q, **kw):
        return [n for n in NODOS if q.lower() in n["label"].lower()]

    def counts(self, workspace=None):
        return len(NODOS), 0

    def entity_types(self, workspace):
        return []

    def list_sources(self, workspace):
        return []

    def quality_metrics(self, workspace=None):
        return {}

    def relations_for_entity(self, entity_id, **kw):
        return []

    def health(self):
        return {"ok": True}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Auth activa, base temporal y proveedor falso inyectado."""
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS

    from app.auth.config import get_auth_settings
    from app.config import get_settings

    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db
    auth_db.ensure_migrated(db_path)

    import app.deps as deps
    from app.main import app

    app.dependency_overrides[deps.get_provider] = lambda: _ProveedorFalso()
    yield db_path, auth_db, app
    app.dependency_overrides.clear()


def _jugadora(auth_db, db_path, tope=None, personaje=None):
    """Crea la usuaria, le concede la partida y devuelve su cookie de sesion."""
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(
            conn, username="ana", display_name="Ana",
            password_hash=hash_password("TestPass_1234567890!"), role="viewer",
        )
        auth_db.grant_partida_access(
            conn, u.id, WS, PARTIDA, granted_by="admin",
            max_visible_session=tope, character_id=personaje,
        )
        token, sesion = create_session(conn, u)
        auth_db.set_session_active_partida(conn, sesion.id, PARTIDA)
    return u, token


def _cliente(app, token):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c


def _ids_listados(cliente):
    r = cliente.get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text
    datos = r.json()
    items = datos.get("items", datos) if isinstance(datos, dict) else datos
    return {i.get("id") for i in items}


# --- la barrera de revelacion, atravesando la cadena entera -----------------

def test_una_concesion_con_tope_oculta_lo_no_revelado(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    ids = _ids_listados(_cliente(app, token))
    assert "revelado_s2" in ids
    assert "spoiler_s40" not in ids, "FUGA: material no revelado en el listado"


def test_una_concesion_MIGRADA_sin_tope_no_gana_acceso(entorno):
    """El caso exacto del quinto dictamen, como regresion permanente.

    `ALTER TABLE ADD COLUMN` deja a NULL toda concesion anterior. Si NULL
    significara "sin tope", la barrera quedaria apagada justo para las filas
    que ya existian -- que son todas las de produccion.
    """
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=None)
    ids = _ids_listados(_cliente(app, token))
    assert "spoiler_s40" not in ids, (
        "una concesion sin tope declarado NO puede conceder acceso a material "
        "no revelado"
    )


def test_known_by_no_abre_el_spoiler_por_HTTP(entorno):
    """`known_by` dice que el PJ lo sabe, no desde cuando."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana")
    ids = _ids_listados(_cliente(app, token))
    assert "spoiler_conocido" not in ids


def test_subir_el_tope_revela_el_mismo_recurso(entorno):
    """La barrera no puede ser "denegar siempre": tiene que abrirse al avanzar."""
    db_path, auth_db, app = entorno
    u, token = _jugadora(auth_db, db_path, tope=5)
    assert "spoiler_s40" not in _ids_listados(_cliente(app, token))

    with auth_db.get_conn(db_path) as conn:
        auth_db.grant_partida_access(conn, u.id, WS, PARTIDA, max_visible_session=40)

    # MISMA cookie, sin reiniciar ni cerrar sesion.
    assert "spoiler_s40" in _ids_listados(_cliente(app, token))


def test_el_acceso_por_ID_no_esquiva_la_barrera(entorno):
    """Lista y detalle deben coincidir: un ID directo no es una puerta trasera."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    r = _cliente(app, token).get("/api/entities/spoiler_s40",
                                 headers={"accept": "application/json"})
    assert r.status_code == 404, f"el ID directo revelo el recurso: {r.status_code}"


def test_la_busqueda_tampoco_lo_revela(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    r = _cliente(app, token).get("/api/entities?q=Spoiler",
                                 headers={"accept": "application/json"})
    assert r.status_code == 200
    assert "spoiler_s40" not in r.text


# --- revocacion: efecto en la PETICION SIGUIENTE ----------------------------

def test_revocar_la_partida_surte_efecto_en_la_siguiente_peticion(entorno):
    """Sin reiniciar, sin limpiar cache, sin volver a entrar.

    Si existiera una cache que prolongue el permiso, este test la encuentra.
    """
    db_path, auth_db, app = entorno
    u, token = _jugadora(auth_db, db_path, tope=50)
    cliente = _cliente(app, token)
    assert "revelado_s2" in _ids_listados(cliente)

    with auth_db.get_conn(db_path) as conn:
        accesos = auth_db.list_partida_access(conn, user_id=u.id)
        for a in accesos:
            auth_db.revoke_partida_access(conn, a.id)

    ids = _ids_listados(cliente)
    assert "revelado_s2" not in ids, "la revocacion no tuvo efecto inmediato"
    assert "spoiler_s40" not in ids
    # Y una tercera peticion sigue denegando (no es un efecto de un solo tiro).
    assert "revelado_s2" not in _ids_listados(cliente)
    # El lore de juego compartido no depende de la partida y sigue visible.
    assert "lore" in _ids_listados(cliente)


def test_revocar_el_personaje_retira_el_conocimiento_individual(entorno):
    """Reconceder declara el estado COMPLETO: el `COALESCE` impedia revocar."""
    db_path, auth_db, app = entorno
    u, token = _jugadora(auth_db, db_path, tope=50, personaje="pc:ana")
    with auth_db.get_conn(db_path) as conn:
        assert auth_db.partida_progress(conn, u.id, WS, PARTIDA)[1] == "pc:ana"
        auth_db.grant_partida_access(conn, u.id, WS, PARTIDA, max_visible_session=50)
        assert auth_db.partida_progress(conn, u.id, WS, PARTIDA)[1] is None


def test_cambiar_de_partida_no_arrastra_lo_anterior(entorno):
    """Material de una partida que ya no esta activa no puede seguir visible."""
    db_path, auth_db, app = entorno
    u, token = _jugadora(auth_db, db_path, tope=50)
    cliente = _cliente(app, token)
    assert "revelado_s2" in _ids_listados(cliente)

    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        auth_db.grant_partida_access(conn, u.id, WS, "partida:beta",
                                     max_visible_session=50)
        token2, sesion2 = create_session(conn, u)
        auth_db.set_session_active_partida(conn, sesion2.id, "partida:beta")

    ids = _ids_listados(_cliente(app, token2))
    assert "revelado_s2" not in ids, "FUGA entre partidas por HTTP"
    assert "lore" in ids

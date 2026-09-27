"""EL PRODUCTO, NO UN ENDPOINT: el ambito lo decide la autoridad del servidor.

La ronda 1 de este corte cerro `/api/graph` y dejo el resto del producto con el
patron viejo (`workspace or S9K_DEFAULT_WORKSPACE`). Medido entonces por HTTP,
un viewer con autoridad `juego:p0` pidiendo `?workspace=juego:ajeno` recibia:

    /api/graph        -> 200, workspace juego:p0    (la autoridad)   OK
    /api/search       -> 200, workspace juego:ajeno (el cliente)     FUGA
    /api/entity-types -> 200, workspace juego:ajeno                  FUGA

Y con la autoridad SIN RESOLVER, cuatro de cinco endpoints respondian 200 con
`workspace: ""` y contenido vacio -- es decir, presentaban el fail-closed como
un workspace normal que resulta estar vacio.

Este fichero mide LA TABLA ENTERA, por HTTP, con cookie de sesion real y
atravesando la cadena de autorizacion de verdad (no se inyecta ningun
`ViewerContext`: `get_filtered_provider` llama a `get_visibility_context` como
funcion normal y sobrescribirla con `dependency_overrides` no surtiria efecto).

Las tres columnas son:
  · autoridad resuelta + parametro AJENO   -> manda la autoridad
  · autoridad resuelta + parametro PROPIO  -> CONTROL POSITIVO (se ve algo)
  · autoridad SIN RESOLVER                 -> 409, nunca 200 vacio
"""
from __future__ import annotations

import os

import pytest

WS = "juego:p0"
OTRO_WS = "juego:ajeno"

NODOS = [
    {"id": "lore", "label": "Lore compartido", "type": "Regla",
     "workspace": WS, "scope": "juego", "visibility": "player",
     "source_document": "sesion_propia"},
    {"id": "otro_ws", "label": "Lore de otro sitio", "type": "Regla",
     "workspace": OTRO_WS, "scope": "juego", "visibility": "player",
     "source_document": "sesion_ajena"},
]


def _del_ws(ws):
    return [n for n in NODOS if n.get("workspace") == ws]


class _ProveedorFalso:
    """Doble que HONRA el workspace pedido, como haria el Cypher real.

    Es la unica parte que importa: un doble que devolviera siempre todo mediria
    su propio andamiaje y dejaria pasar la fuga que este fichero busca.
    """

    name = "fake"

    def workspaces(self):
        return [WS, OTRO_WS]

    def is_connected(self):
        return True

    def graph(self, workspace=None, **kw):
        if workspace is None:
            return list(NODOS), []
        return _del_ws(workspace), []

    def list_entities(self, workspace, **kw):
        items = _del_ws(workspace)
        return items, len(items)

    def entity(self, entity_id, *, workspaces=None):
        for n in NODOS:
            if n["id"] == entity_id:
                if workspaces is not None and n.get("workspace") not in workspaces:
                    return None
                return n
        return None

    def search(self, workspace, q, **kw):
        return [n for n in _del_ws(workspace) if q.lower() in n["label"].lower()]

    def counts(self, workspace=None):
        items = _del_ws(workspace) if workspace else NODOS
        return len(items), 0

    def entity_types(self, workspace):
        return [{"entity_type": "Regla", "count": len(_del_ws(workspace))}]

    def list_sources(self, workspace):
        return [{"source_id": n["source_document"], "entity_count": 1}
                for n in _del_ws(workspace)]

    def source_detail(self, workspace, source_id):
        items = [n for n in _del_ws(workspace)
                 if n["source_document"] == source_id]
        if not items:
            return None
        return {"source_id": source_id, "workspace": workspace,
                "entity_count": len(items), "entity_types": ["Regla"]}

    def quality_metrics(self, workspace=None):
        items = _del_ws(workspace) if workspace else NODOS
        return {"workspace": workspace, "total_entities": len(items),
                "total_relations": 0, "by_review_status": {}}

    def relations_for_entity(self, entity_id, **kw):
        return [], []

    def health(self):
        return {"ok": True}


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


def _montar(tmp_path, workspace_canonico):
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    # `""` es la forma declarada de que el entorno DEJE de declarar workspace
    # (docs/v3/65). Con el perfil de boveda ausente, la autoridad no resuelve
    # nada y `allowed_workspaces` queda vacio.
    os.environ["S9K_DEFAULT_WORKSPACE"] = workspace_canonico

    from app.auth.config import get_auth_settings
    from app.config import get_settings

    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db
    auth_db.ensure_migrated(db_path)

    import app.deps as deps
    from app.main import app

    app.dependency_overrides[deps.get_provider] = lambda: _ProveedorFalso()
    return db_path, auth_db, app


@pytest.fixture
def entorno(tmp_path):
    db_path, auth_db, app = _montar(tmp_path, WS)
    yield db_path, auth_db, app
    app.dependency_overrides.clear()


@pytest.fixture
def entorno_sin_autoridad(tmp_path):
    db_path, auth_db, app = _montar(tmp_path, "")
    yield db_path, auth_db, app
    app.dependency_overrides.clear()


def _cliente(app, auth_db, db_path, *, role, usuario):
    from fastapi.testclient import TestClient
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(
            conn, username=usuario, display_name=usuario.title(),
            password_hash=hash_password("TestPass_1234567890!"), role=role,
        )
        token, _ = create_session(conn, u)
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c


# --- la tabla de endpoints -------------------------------------------------
#
# (ruta, rol minimo, como se lee el workspace de la respuesta)

def _ws_directo(cuerpo):
    return cuerpo.get("workspace")


def _ws_en_filtros(cuerpo):
    return cuerpo.get("filters", {}).get("workspace")


# La cuarta columna es la HUELLA del contenido propio en la respuesta: no todos
# los endpoints devuelven nodos (los agregados devuelven recuentos y fuentes),
# asi que cada uno declara por que se le reconoce que SI esta viendo lo suyo.
# Sin esa huella el control positivo seria decorativo.
ENDPOINTS_JSON = [
    ("/api/graph", "viewer", _ws_directo, '"lore"'),
    ("/api/search", "viewer", _ws_directo, '"lore"'),
    ("/api/entity-types", "viewer", _ws_directo, '"count":1'),
    ("/api/entities", "viewer", _ws_en_filtros, '"lore"'),
    ("/api/sources", "reviewer", _ws_directo, "sesion_propia"),
    ("/api/quality", "reviewer", _ws_directo, '"total_entities":1'),
]

# Huellas del workspace AJENO: si alguna aparece, ha habido fuga de contenido.
HUELLAS_AJENAS = ("otro_ws", "sesion_ajena", OTRO_WS)

# `/api/workspaces` no recibe `workspace`: no puede fugarlo, pero SI puede
# presentar la falta de ambito como un inventario vacio. Va en su propia tabla.
ENDPOINTS_SIN_PARAMETRO = [("/api/workspaces", "viewer")]

PAGINAS_HTML = [("/entities", "viewer"), ("/sources", "reviewer"),
                ("/quality", "reviewer")]

ACEPTA_JSON = {"accept": "application/json"}


@pytest.mark.parametrize("ruta,rol,leer_ws,huella", ENDPOINTS_JSON)
def test_el_parametro_ajeno_NO_decide_el_ambito_de_un_no_admin(entorno, ruta, rol, leer_ws, huella):
    db_path, auth_db, app = entorno
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta, params={"workspace": OTRO_WS, "q": "Lore"}, headers=ACEPTA_JSON)
    assert r.status_code == 200, f"{ruta}: {r.status_code} {r.text}"
    visto = leer_ws(r.json())
    assert visto == WS, (
        f"FUGA DE AMBITO en {ruta}: el parametro del cliente ({OTRO_WS!r}) "
        f"decidio el workspace consultado ({visto!r}) en vez de la autoridad "
        f"del servidor ({WS!r})"
    )
    for rastro in HUELLAS_AJENAS:
        assert rastro not in r.text, (
            f"FUGA DE CONTENIDO en {ruta}: aparece {rastro!r}, material del "
            f"workspace ajeno"
        )


@pytest.mark.parametrize("ruta,rol,leer_ws,huella", ENDPOINTS_JSON)
def test_control_positivo_el_lector_sigue_viendo_LO_SUYO(entorno, ruta, rol, leer_ws, huella):
    """Sin esta mitad, "devolver vacio siempre" pasaria por arreglo."""
    db_path, auth_db, app = entorno
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta, params={"workspace": WS, "q": "Lore"}, headers=ACEPTA_JSON)
    assert r.status_code == 200, f"{ruta}: {r.status_code} {r.text}"
    assert leer_ws(r.json()) == WS
    assert huella in r.text.replace(" ", ""), (
        f"el control positivo de {ruta} no ve NADA de su propio workspace "
        f"(no aparece {huella!r}): la columna de ausencia de arriba no esta "
        f"midiendo nada"
    )


@pytest.mark.parametrize("ruta,rol,leer_ws,huella", ENDPOINTS_JSON)
def test_sin_autoridad_resuelta_ningun_endpoint_finge_un_workspace_vacio(
    entorno_sin_autoridad, ruta, rol, leer_ws, huella
):
    db_path, auth_db, app = entorno_sin_autoridad
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta, params={"q": "Lore"}, headers=ACEPTA_JSON)
    assert r.status_code == 409, (
        f"{ruta} respondio {r.status_code} con la autoridad sin resolver. Un "
        f"200 aqui presenta el fail-closed como un workspace normal y vacio, "
        f"que es indistinguible de «existe y no tiene nada»: {r.text[:200]}"
    )


@pytest.mark.parametrize("ruta,rol", ENDPOINTS_SIN_PARAMETRO)
def test_sin_autoridad_resuelta_el_inventario_tampoco_sale_vacio(
    entorno_sin_autoridad, ruta, rol
):
    db_path, auth_db, app = entorno_sin_autoridad
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta, headers=ACEPTA_JSON)
    assert r.status_code == 409, (
        f"{ruta} respondio {r.status_code}: una lista vacia aqui afirma que "
        f"este principal no tiene ningun workspace, y lo que pasa es que la "
        f"autoridad no ha resuelto ninguno"
    )


@pytest.mark.parametrize("ruta,rol", ENDPOINTS_SIN_PARAMETRO)
def test_control_positivo_el_inventario_sale_cuando_hay_autoridad(entorno, ruta, rol):
    db_path, auth_db, app = entorno
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta, headers=ACEPTA_JSON)
    assert r.status_code == 200 and WS in r.text, r.text[:200]


@pytest.mark.parametrize("ruta,rol", PAGINAS_HTML)
def test_las_pantallas_HTML_usan_el_mismo_criterio(entorno_sin_autoridad, ruta, rol):
    """Un solo criterio para todos: la pantalla tampoco se pinta como un
    workspace normal que resulta estar vacio."""
    db_path, auth_db, app = entorno_sin_autoridad
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta)
    assert r.status_code == 409, (
        f"{ruta} respondio {r.status_code} con la autoridad sin resolver"
    )


@pytest.mark.parametrize("ruta,rol", PAGINAS_HTML)
def test_control_positivo_las_pantallas_HTML_siguen_pintando(entorno, ruta, rol):
    db_path, auth_db, app = entorno
    c = _cliente(app, auth_db, db_path, role=rol, usuario="ana")
    r = c.get(ruta)
    assert r.status_code == 200, r.text[:200]


# --- la excepcion declarada: `admin_full` --------------------------------

@pytest.mark.parametrize("ruta,rol,leer_ws,huella", ENDPOINTS_JSON)
def test_admin_full_conserva_el_selector_de_workspace(entorno, ruta, rol, leer_ws, huella):
    """Decision declarada (docs/v3/65, `app.authz.ambito`): para un admin el
    parametro es un SELECTOR, no una concesion -- ya ve todo."""
    db_path, auth_db, app = entorno
    c = _cliente(app, auth_db, db_path, role="admin", usuario="jefa")
    r = c.get(ruta, params={"workspace": OTRO_WS, "q": "Lore"}, headers=ACEPTA_JSON)
    assert r.status_code == 200, f"{ruta}: {r.status_code} {r.text}"
    assert leer_ws(r.json()) == OTRO_WS, (
        f"{ruta} le ha retirado a `admin_full` el selector que la decision "
        f"declarada le concede"
    )


def test_admin_full_sin_autoridad_resuelta_tampoco_finge_un_workspace(
    entorno_sin_autoridad,
):
    """La precedencia de `admin_full` no fabrica un ambito de la nada: sin
    autoridad y sin parametro, tambien 409."""
    db_path, auth_db, app = entorno_sin_autoridad
    c = _cliente(app, auth_db, db_path, role="admin", usuario="jefa")
    r = c.get("/api/graph", headers=ACEPTA_JSON)
    assert r.status_code == 409, r.text[:200]


# --- `/graph`: UN SOLO LECTOR, TAMBIEN PARA `admin_full` -------------------
#
# `main._workspace_inicial_del_grafo` leia `settings.S9K_DEFAULT_WORKSPACE`
# para el admin: un SEGUNDO lector del entorno fuera de la autoridad, que es la
# forma exacta del defecto que costo el corte F-2 (docs/v3/65). Aqui se hace
# DIVERGIR la autoridad del entorno y se mira cual de los dos gobierna la
# pagina. Sin divergencia no se distingue una cosa de la otra: el entorno es el
# fallback declarado del resolvedor, asi que en configuracion de fabrica los
# dos valores coinciden y cualquier lectura pasaria.

WS_DEL_PERFIL = "juego:perfil"


@pytest.fixture
def entorno_con_autoridad_divergente(tmp_path, monkeypatch):
    """El entorno declara WS; la autoridad canonica resuelve OTRA cosa."""
    db_path, auth_db, app = _montar(tmp_path, WS)

    from app.authz import autoridad_workspace

    class _Autoridad:
        valor = WS_DEL_PERFIL
        resuelto = True
        diverge = True

    monkeypatch.setattr(autoridad_workspace, "resolver_por_peticion",
                        lambda env=None: _Autoridad())
    yield db_path, auth_db, app
    app.dependency_overrides.clear()


@pytest.mark.parametrize("rol", ["viewer", "admin"])
def test_la_pagina_del_grafo_arranca_en_lo_que_dice_la_autoridad_no_el_entorno(
    entorno_con_autoridad_divergente, rol
):
    db_path, auth_db, app = entorno_con_autoridad_divergente
    c = _cliente(app, auth_db, db_path, role=rol, usuario="quien")
    r = c.get("/graph")
    assert r.status_code == 200, r.text[:200]
    assert WS_DEL_PERFIL in r.text, (
        f"/graph no inyecta el workspace de la AUTORIDAD para el rol {rol}"
    )
    assert WS not in r.text, (
        f"SEGUNDO LECTOR DEL ENTORNO: /graph inyecta {WS!r}, que es lo que "
        f"declara S9K_DEFAULT_WORKSPACE, en vez de lo que resolvio la "
        f"autoridad canonica ({WS_DEL_PERFIL!r}). Es la regresion que costo "
        f"el corte F-2."
    )

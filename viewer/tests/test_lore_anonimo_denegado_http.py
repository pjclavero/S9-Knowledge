"""LORE_ANONIMO = DENEGADO, atravesado por HTTP de punta a punta.

DECISION DEL OPERADOR (V3 RC, 2026-08-14), literal:

    LORE_ANONIMO = DENEGADO en V3 RC. Auth desactivada produce contexto anonimo
    sin privilegios. La ausencia de partida no concede visibilidad adicional.
    Cualquier futura exposicion publica de lore requerira una politica
    explicita y pruebas propias.

QUE HABIA ANTES, MEDIDO
-----------------------
Con `S9K_AUTH_ENABLED` ausente o `false` el contexto ya era anonimo y de minimo
privilegio: `admin_full=False`, sin `can_view_secret`, sin `can_view_reference`,
sin partidas, `max_visible_session=0`. Eso estaba bien y no se ha tocado.

Pero la capa juego (`scope=juego`, `visibility=player`) era la unica rama del
ambito SIN NINGUNA CONDICION SOBRE EL LECTOR: bastaba superar la barrera de
workspace, y un anonimo la supera porque el workspace por defecto del despliegue
entra en `allowed_workspaces`. Resultado medido por dos carriles independientes
sobre huecos distintos --paneles G y F, docs/77 §3 y docs/78 §3--: 1 de 11 casos
visible, mismo veredicto y misma proporcion. Ese caso salia en la lista, contaba
en los contadores y su ficha respondia 200 con el texto completo.

La llave de la capa juego era, literalmente, NO TENER PARTIDA. Una ausencia
concediendo: la misma inferencia permisiva que M5c arranco del dato --"sin
`partida_id` = lore compartido"--, sobreviviendo un nivel mas arriba, en el
lector. Ahora la capa juego tiene llave POSITIVA (`can_view_lore`), declarada en
el registro M5b con su cadena completa.

POR QUE ESTE FICHERO EXISTE, Y POR QUE POR HTTP
-----------------------------------------------
Aqui NO se fabrica ningun contexto a mano. Se crea el usuario en `auth.db`, se
pide con cookie de sesion real y se mira lo que el visor devuelve. Un test que
inyecta el `ViewerContext` se salta justo los tramos donde vivieron H-A y H6-5,
y ademas el punto de inyeccion de este visor esta CONGELADO:
`get_filtered_provider` llama a `get_visibility_context` como funcion normal, no
via `Depends`, asi que sobrescribirlo con `dependency_overrides` es INERTE y
sale verde por no morder. Por eso lo que se sustituye es el proveedor BASE y la
cadena se atraviesa entera.

Y por eso el primer test del fichero no mide el sistema sino el INSTRUMENTO: si
al cambiar el principal el resultado no cambia, no se esta midiendo nada.
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


WS = "juego:lore"
PARTIDA = "partida:alfa"

#: Los DOS nodos que separan las dos mitades de la medicion: uno de capa juego
#: (la via que se cierra) y uno de partida propia (que un lector legitimo debe
#: seguir viendo, para que "no ve nada" no pueda pasar por autorizacion).
NODOS = [
    {"id": "lore", "label": "Lore compartido", "type": "Regla",
     "workspace": WS, "scope": "juego", "visibility": "player"},
    {"id": "de_su_partida", "label": "Escena de su partida", "type": "Evento",
     "workspace": WS, "scope": "partida", "partida_id": PARTIDA,
     "visibility": "player", "known_from_session": 1},
]


class _ProveedorFalso:
    """Proveedor BASE tonto: toda la autorizacion la pone la cadena real.

    Honra el `workspace` pedido, como haria el Cypher real: un doble que ignora
    la unica parte que importa mide su propio andamiaje.
    """

    name = "fake"

    def workspaces(self):
        return [WS]

    def graph(self, workspace=None, **kw):
        if workspace is None:
            return list(NODOS), []
        return [n for n in NODOS if n.get("workspace") == workspace], []

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
def entorno(tmp_path):
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


def _usuario(auth_db, db_path, *, role, usuario, partida=None, tope=None):
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(
            conn, username=usuario, display_name=usuario.title(),
            password_hash=hash_password("TestPass_1234567890!"), role=role,
        )
        if partida:
            auth_db.grant_partida_access(
                conn, u.id, WS, partida, granted_by="admin",
                max_visible_session=tope,
            )
        token, sesion = create_session(conn, u)
        if partida:
            auth_db.set_session_active_partida(conn, sesion.id, partida)
    return u, token


def _cliente(app, token=None):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if token:
        c.cookies.set("s9k_session", token)
    return c


def _ids_listados(cliente) -> set[str]:
    r = cliente.get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text
    datos = r.json()
    items = datos.get("items", datos) if isinstance(datos, dict) else datos
    return {i.get("id") for i in items}


def _apaga_la_autenticacion():
    from app.auth.config import get_auth_settings

    os.environ["S9K_AUTH_ENABLED"] = "false"
    get_auth_settings.cache_clear()


# --- 0. EL INSTRUMENTO MUERDE ------------------------------------------------

def test_el_control_COLAPSA_al_cambiar_el_principal(entorno):
    """Va primero a proposito: comprueba el BANCO, no el sistema.

    Si un lector legitimo y un anonimo recibieran lo mismo, todo lo de abajo
    seria compatible con un visor averiado que no sirve nada, y "el anonimo no
    ve el lore" no diria una palabra sobre la autorizacion.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="viewer", usuario="ana",
                        partida=PARTIDA, tope=10)
    legitimo = _ids_listados(_cliente(app, token))

    _apaga_la_autenticacion()
    anonimo = _ids_listados(_cliente(app))

    assert legitimo != anonimo, (
        "el resultado NO cambia al cambiar el principal: el banco no esta "
        "conectado a la autorizacion y no mide nada"
    )
    assert legitimo, "el lector legitimo no recibe nada: el banco esta averiado"


# --- 1. la dimension declarada por el registro, ejercida por HTTP ------------

def test_el_lore_de_capa_juego_exige_can_view_lore_por_HTTP(entorno):
    """PRUEBA HTTP declarada por `can_view_lore` en el registro M5b.

    Las dos mitades, sobre EL MISMO corpus y por la MISMA ruta:

      * el anonimo con la autenticacion desactivada no recibe `lore`,
      * el `viewer` autenticado --que si tiene la llave-- SI lo recibe.

    Lo que separa los dos resultados es la dimension, no la pantalla.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="viewer", usuario="ana",
                        partida=PARTIDA, tope=10)
    assert "lore" in _ids_listados(_cliente(app, token)), (
        "el lector CON la llave no recibe el lore: entonces la prueba de abajo "
        "no mediria la llave, sino un visor roto"
    )

    _apaga_la_autenticacion()
    assert "lore" not in _ids_listados(_cliente(app)), (
        "FUGA: el lore de capa juego se entrega a un contexto anonimo. La "
        "ausencia de partida no concede visibilidad adicional (V3 RC)"
    )


def test_con_la_autenticacion_desactivada_no_se_entrega_NADA(entorno):
    """La forma fuerte: no es que se recorte, es que no queda nada.

    Sin principal no hay autoridad. El unico material que sobrevivia era el de
    capa juego, y ya no lo hace.
    """
    _, _, app = entorno
    _apaga_la_autenticacion()
    ids = _ids_listados(_cliente(app))
    assert ids == set(), (
        f"con la autenticacion desactivada el visor entrega {sorted(ids)}"
    )


def test_la_ficha_tampoco_lo_entrega_por_ID(entorno):
    """La barrera no puede depender de por donde se entre.

    El acceso por ID es el camino que se olvida: un listado que filtra y una
    ficha que no, es la misma fuga con un clic mas.
    """
    _, _, app = entorno
    _apaga_la_autenticacion()
    cliente = _cliente(app)
    for nodo in ("lore", "de_su_partida"):
        r = cliente.get(f"/api/entities/{nodo}",
                        headers={"accept": "application/json"})
        assert r.status_code in (401, 403, 404), (
            f"la ficha de '{nodo}' respondio {r.status_code} a un anonimo"
        )
        assert "Lore compartido" not in r.text


# --- 2. CONTROL DE COLAPSO: el lector legitimo NO pierde acceso --------------

def test_un_lector_legitimo_sigue_viendo_su_lore_por_HTTP(entorno):
    """La mitad que impide que esto se "arregle" apagando el visor.

    Un `viewer` autenticado con su partida activa sigue viendo LAS DOS cosas:
    la capa juego y el material de su propia partida. Si un dia se ocultara de
    mas, este test se pone rojo -- y ese es el modo de fallo que mas facilmente
    se confunde con seguridad.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="viewer", usuario="ana",
                        partida=PARTIDA, tope=10)
    ids = _ids_listados(_cliente(app, token))
    assert {"lore", "de_su_partida"} <= ids, (
        f"el lector legitimo ha PERDIDO acceso: le faltan "
        f"{sorted({'lore', 'de_su_partida'} - ids)}. La denegacion al anonimo "
        f"se ha llevado por delante a quien si tenia derecho"
    )


def test_un_admin_autenticado_tampoco_pierde_nada(entorno):
    """El bypass total sigue siendo total: la dimension nueva no lo estorba."""
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="admin", usuario="jefa")
    ids = _ids_listados(_cliente(app, token))
    assert {"lore", "de_su_partida"} <= ids, sorted(ids)


def test_la_llave_se_revoca_al_cambiar_el_rol(entorno):
    """Revocacion, que es lo que el registro declara como `inmediata`.

    Se declara `revocation="inmediata (cambio de rol)"`, y una revocacion que
    nadie ejerce es una declaracion, no una garantia. Degradar el rol en
    `auth.db` retira la llave en la SIGUIENTE peticion, con la misma sesion.
    """
    db_path, auth_db, app = entorno
    usuario, token = _usuario(auth_db, db_path, role="viewer", usuario="ana",
                              partida=PARTIDA, tope=10)
    assert "lore" in _ids_listados(_cliente(app, token))

    with auth_db.get_conn(db_path) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?",
                     ("anonymous", usuario.id))
        conn.commit()

    assert "lore" not in _ids_listados(_cliente(app, token)), (
        "el rol se degrado y la llave de la capa juego sobrevivio: quedo "
        "congelada en la sesion en vez de releerse en cada peticion"
    )

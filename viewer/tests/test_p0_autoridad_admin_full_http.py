"""UNA SOLA AUTORIDAD sobre `admin_full`, atravesada por HTTP (P0-AUTH).

`admin_full` no es una dimension mas: es el bypass TOTAL. Se salta workspace,
aislamiento entre partidas, nivel de visibilidad, `known_by` y el tope de
sesion, y en `filtered_provider._scope_workspaces()` quita ademas el acotado en
el propio Cypher. Lo unico que no salta es una `visibility` invalida y `deny`.

Hasta este carril habia TRES vias a esa misma potestad y NINGUNA declarada:

  1. `ctx.admin_full` directo,
  2. `authz/scope.py` -> `bool(ctx.admin_full) or ctx.role == "admin"`,
  3. `authz/context.py` -> `admin_full=True` cuando `S9K_AUTH_ENABLED` es falso.

Ahora la cadena es una sola y va de punta a punta:

    principal autenticado -> build_viewer_context() -> admin_full -> consumidores

Aqui NO se fabrica ningun contexto: se crea el usuario en `auth.db`, se pide por
HTTP con cookie de sesion real y se mira lo que devuelve el visor. Es
deliberado: un test que inyecta el `ViewerContext` se salta justo los tramos
donde vivieron H-A y H6-5, y la revocacion --que es un tramo de base de datos--
no se puede demostrar de ninguna otra forma.
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


WS = "juego:p0"
OTRO_WS = "juego:ajeno"
PARTIDA = "partida:alfa"

NODOS = [
    # Lore corriente: visible para cualquiera con el workspace.
    {"id": "lore", "label": "Lore compartido", "type": "Regla",
     "workspace": WS, "scope": "juego", "visibility": "player"},
    # Material de referencia: SOLO con `can_view_reference`.
    {"id": "manual", "label": "Pagina del manual", "type": "Regla",
     "workspace": WS, "scope": "juego", "visibility": "reference"},
    # Secreto de otra jugadora: solo `can_view_secret` o `admin_full`.
    {"id": "secreto_ajeno", "label": "Secreto de Bryn", "type": "Evento",
     "workspace": WS, "scope": "partida", "partida_id": PARTIDA,
     "visibility": "secret", "known_from_session": 1, "known_by": ["pc:bryn"]},
    # Otro workspace: la barrera que `admin_full` tambien se salta.
    {"id": "otro_ws", "label": "De otro workspace", "type": "Regla",
     "workspace": OTRO_WS, "scope": "juego", "visibility": "player"},
    # `deny` es TERMINAL: ni un admin lo abre.
    {"id": "denegado", "label": "Retirado a proposito", "type": "Regla",
     "workspace": WS, "scope": "juego", "visibility": "deny"},
    # Conocimiento por ID precomputado: solo lo abriria `character_knowledge`.
    {"id": "solo_por_character_knowledge", "label": "Secreto sin known_by",
     "type": "Evento", "workspace": WS, "scope": "partida",
     "partida_id": PARTIDA, "visibility": "secret", "known_from_session": 1},
]


class _ProveedorFalso:
    """Proveedor minimo: el objetivo es la CADENA, no el driver de Neo4j."""

    name = "fake"

    def workspaces(self):
        return [WS, OTRO_WS]

    def graph(self, workspace=None, **kw):
        # HONRA el workspace pedido, como haria el Cypher real. La primera
        # version lo ignoraba y devolvia el grafo entero: entonces un lector que
        # pedia un workspace ajeno recibia igualmente los nodos del suyo, la
        # prueba de colapso salia roja y el defecto estaba en el DOBLE, no en el
        # sistema. Un banco que no imita la unica parte que importa mide su
        # propio andamiaje.
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


def _usuario(auth_db, db_path, *, role, usuario, partida=None, tope=None,
             personaje=None):
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
                max_visible_session=tope, character_id=personaje,
            )
        token, sesion = create_session(conn, u)
        if partida:
            auth_db.set_session_active_partida(conn, sesion.id, partida)
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


# --- 1. la potestad existe de verdad, y llega desde el principal -------------

def test_el_admin_autenticado_recibe_la_potestad_total_por_HTTP(entorno):
    """Contraveneno de todo lo demas.

    Si un admin no viera lo que solo `admin_full` abre, las comprobaciones
    negativas de abajo pasarian sin demostrar nada: es el modo de fallo
    silencioso clasico de una prueba de revocacion.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="admin", usuario="jefa")
    ids = _ids_listados(_cliente(app, token))
    assert {"secreto_ajeno", "manual", "otro_ws"} <= ids, (
        "el admin autenticado NO recibe la potestad total: faltan "
        f"{sorted({'secreto_ajeno', 'manual', 'otro_ws'} - ids)}"
    )


# --- 1b. EL INSTRUMENTO MUERDE: el control tiene que poder COLAPSAR ----------

def test_el_control_de_autorizacion_COLAPSA_en_api_graph(entorno):
    """Comprobacion del INSTRUMENTO, no del sistema. Va primero a proposito.

    Motivo, medido en otro carril y aplicable palabra por palabra aqui:
    `get_filtered_provider` llama a `get_visibility_context(request)` como
    FUNCION NORMAL, no via `Depends`. Sobrescribir `get_visibility_context` con
    `app.dependency_overrides` no surte NINGUN efecto sobre `/api/graph`: alli
    un banco creyo estar midiendo con la autorizacion puesta y seguia recibiendo
    300 nodos / 171 aristas. Una cifra cierta por no mirar.

    Estas pruebas NO usan ese punto de inyeccion --sustituyen el proveedor BASE
    y atraviesan la cadena real con cookie de sesion-- pero eso hay que
    DEMOSTRARLO, no afirmarlo. La forma de demostrarlo es exigir que el control
    colapse: si al cambiar el principal el resultado no cambia, el instrumento
    no esta conectado a nada.

    Aqui se mide sobre `/api/graph` justo porque es la ruta donde el defecto se
    manifesto: admin ve el grafo entero; un anonimo sin workspace permitido lo
    ve colapsar a CERO.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="admin", usuario="jefa")

    r = _cliente(app, token).get(
        "/api/graph", params={"workspace": WS}, headers={"accept": "application/json"}
    )
    assert r.status_code == 200, r.text
    nodos_admin = len(r.json()["nodes"])
    assert nodos_admin > 0, (
        "ni siquiera el admin recibe nodos: el banco no esta midiendo nada y "
        "cualquier 'no hay fuga' de abajo seria cierto por vacuidad"
    )

    # Mismo endpoint, mismo grafo, principal sin potestad: tiene que COLAPSAR.
    _, token_sin = _usuario(auth_db, db_path, role="viewer", usuario="ana")
    r2 = _cliente(app, token_sin).get(
        "/api/graph", params={"workspace": OTRO_WS},
        headers={"accept": "application/json"},
    )
    # Se exige 200 y CERO nodos, no "200-o-404". Aceptar 404 como rama
    # alternativa era una coartada: un 404 puede venir de una ruta mal escrita,
    # de un parametro invalido o de un fallo de arranque, y entonces el test
    # pasaria sin que la politica hubiera intervenido en absoluto. El colapso
    # que se quiere demostrar es "misma ruta, misma respuesta valida, cero
    # contenido", que es la unica forma de saber que quien recorto fue la
    # politica y no el enrutador.
    assert r2.status_code == 200, (
        f"se esperaba 200 con el grafo vacio y llego {r2.status_code}: sin una "
        f"respuesta valida no se puede afirmar que el recorte lo hizo la politica"
    )
    assert len(r2.json()["nodes"]) == 0, (
        "FUGA: un `viewer` recibe nodos de un workspace que no tiene "
        "permitido. Y si esto no colapsa, tampoco colapsaria una fuga real: "
        "el instrumento no estaria conectado."
    )


# --- 2. REVOCACION: retirar el rol retira la potestad ------------------------

def test_retirar_el_rol_admin_retira_admin_full_en_la_siguiente_peticion(entorno):
    """La semantica de REVOCACION declarada en el registro, ejercida.

    Una potestad que no se puede retirar no es una concesion: es una propiedad
    del usuario. El registro declara `revocation="inmediata (el rol se relee de
    auth.db en cada peticion)"` y esto lo demuestra sobre la sesion YA ABIERTA,
    sin nuevo login y sin revocar la sesion: misma cookie, peticion siguiente.
    """
    db_path, auth_db, app = entorno
    u, token = _usuario(auth_db, db_path, role="admin", usuario="jefa")
    cliente = _cliente(app, token)

    antes = _ids_listados(cliente)
    assert "secreto_ajeno" in antes, "el admin no tenia la potestad que se va a revocar"

    with auth_db.get_conn(db_path) as conn:
        auth_db.update_user(conn, u.id, role="viewer")

    despues = _ids_listados(cliente)
    assert "secreto_ajeno" not in despues, (
        "FUGA: retirado el rol admin, la MISMA sesion sigue viendo secretos "
        "ajenos. La potestad de bypass total habria quedado congelada en la "
        "sesion y solo se retiraria al volver a entrar."
    )
    assert "otro_ws" not in despues, (
        "FUGA: retirado el rol admin, la sesion sigue viendo otro workspace"
    )
    assert "lore" in despues, (
        "la revocacion ha degradado al usuario mas alla de su rol nuevo: un "
        "`viewer` debe seguir viendo el lore de su workspace"
    )


# --- 3. `deny` es TERMINAL incluso para la potestad total --------------------

def test_un_nodo_deny_no_lo_abre_ni_un_admin_por_HTTP(entorno):
    """`deny + admin_full` => DENY. Un bypass se salta reglas de PERMISO; no
    convierte un estado terminal en permiso, ni un dato invalido en valido."""
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="admin", usuario="jefa")
    cliente = _cliente(app, token)

    assert "denegado" not in _ids_listados(cliente), (
        "FUGA: `visibility=deny` entregado a un admin. `deny` es terminal: el "
        "bypass total se evalua DESPUES de la regla 0 justo para esto."
    )
    r = cliente.get("/api/entities/denegado", headers={"accept": "application/json"})
    assert r.status_code == 404, (
        f"acceso por ID a un nodo `deny` siendo admin: {r.status_code}"
    )


# --- 4. `can_view_reference`: unica llave del nivel `reference` --------------

def test_el_material_de_referencia_exige_can_view_reference_por_HTTP(entorno):
    """`can_view_reference` es la UNICA llave del nivel `reference`.

    Se ejerce en las dos direcciones con dos roles reales: `viewer` la recibe
    del constructor, `anonymous` no.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="viewer", usuario="ana")
    assert "manual" in _ids_listados(_cliente(app, token)), (
        "un `viewer` autenticado ha dejado de recibir `can_view_reference`"
    )

    from fastapi.testclient import TestClient

    anonimo = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    r = anonimo.get("/api/entities", headers={"accept": "application/json"})
    if r.status_code == 200:
        datos = r.json()
        items = datos.get("items", datos) if isinstance(datos, dict) else datos
        assert "manual" not in {i.get("id") for i in items}, (
            "FUGA: material `reference` entregado sin `can_view_reference`"
        )
    else:
        assert r.status_code in (401, 403, 307), r.status_code


# --- 5. `character_knowledge`: declarada CON su limite medido ----------------

def test_character_knowledge_no_la_puebla_la_cadena_de_peticion(entorno):
    """Testigo del LIMITE declarado en el registro, no de una garantia inventada.

    `character_knowledge` concede conocimiento por ID precomputado y se salta la
    regla de NIVEL sin pasar por `known_by`. La cadena de peticion
    (`authz/dependencies.py`) NO la puebla: en produccion llega siempre vacia y
    la unica concesion efectiva es `known_by`/`known_by_characters` del propio
    nodo. Eso esta declarado en el registro como semantica, y aqui se MIDE.

    Si alguien conecta un productor a esta dimension, este test se pone rojo y
    obliga a declarar su autoridad y su revocacion antes, en vez de estrenarla
    en silencio.
    """
    db_path, auth_db, app = entorno
    _, token = _usuario(auth_db, db_path, role="viewer", usuario="ana",
                        partida=PARTIDA, tope=10, personaje="pc:ana")
    ids = _ids_listados(_cliente(app, token))
    assert "solo_por_character_knowledge" not in ids, (
        "un nodo `secret` SIN `known_by` se ha vuelto visible: o hay un "
        "productor nuevo de `character_knowledge` sin declarar, o la regla de "
        "nivel ha dejado de aplicarse"
    )


# --- 6. desactivar la autenticacion NO concede nada --------------------------

def test_con_la_autenticacion_desactivada_no_hay_potestad_total(entorno, tmp_path):
    """La TERCERA via, cerrada: un flag de despliegue no es una autoridad.

    `S9K_AUTH_ENABLED=false` devolvia `admin_full=True`. Sin autenticacion no
    hay principal, luego no hay autoridad: minimo privilegio.
    """
    db_path, auth_db, app = entorno
    os.environ["S9K_AUTH_ENABLED"] = "false"
    from app.auth.config import get_auth_settings

    get_auth_settings.cache_clear()

    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    r = c.get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text
    datos = r.json()
    items = datos.get("items", datos) if isinstance(datos, dict) else datos
    ids = {i.get("id") for i in items}
    # LORE-ANONIMO-DENEGADO (decision del operador, V3 RC, 2026-08-14).
    # Aqui vivia `assert "lore" in ids`: el contexto anonimo SI recibia el lore
    # de capa juego, y lo unico que se lo daba era NO TENER PARTIDA. Es decir,
    # una ausencia concediendo -- la misma inferencia permisiva que M5c arranco
    # del dato, sobreviviendo en el lector, y justo donde ya se habia decidido
    # que "auth desactivada != acceso total".
    #
    # El apagon que aquella linea temia se sigue vigilando, pero donde
    # corresponde: en el CONTROL DE COLAPSO
    # (`test_un_lector_legitimo_sigue_viendo_su_lore_por_HTTP`), donde un
    # `viewer` autenticado sobre este mismo corpus SI recibe `lore`. Que el
    # anonimo no lo reciba es autorizacion; que no lo reciba NADIE seria una
    # averia, y por eso las dos mitades se miden por separado.
    assert not ids, (
        f"con la autenticacion desactivada el visor sigue entregando {sorted(ids)}: "
        f"sin principal no hay autoridad, y la ausencia de partida no concede "
        f"visibilidad adicional"
    )

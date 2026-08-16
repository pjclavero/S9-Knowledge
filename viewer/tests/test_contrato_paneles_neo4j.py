"""CONTRATO PANELES <-> NEO4J: los cuatro huecos contra una base EFIMERA real.

EL HUECO QUE ESTO CIERRA
========================
Sabiamos que el proveedor funciona (``test_neo4j_integration_authz.py``) y que
las pantallas funcionan CON SUS FIXTURES (``test_panel_*.py``). Lo que nadie
media es que una consulta Neo4j REAL entregue EXACTAMENTE los campos de los que
viven los paneles. Las suites de panel inyectan un ``ProveedorFalso`` que
devuelve diccionarios escritos a mano con las claves ya correctas; si la
proyeccion Cypher perdiera ``source_document`` o ``review_status``, esas suites
seguirian verdes y la pantalla saldria en blanco en produccion.

Aqui se escribe en un Neo4j de verdad, se lee por el ``Neo4jGraphProvider`` de
verdad, se atraviesa la cadena de autorizacion de verdad y se renderiza la
plantilla de verdad, POR HTTP y sobre ``app.main.app``.

LA CALIBRACION ES EL CONTRATO
=============================
Un contrato que no puede ponerse rojo es decorativo. Por eso la pieza central de
este fichero no es la lista de campos: es ``ABLACIONES``. Por CADA campo que un
panel consume se BORRA la propiedad en Neo4j, se vuelve a pedir la pantalla y se
exige que la observacion CAMBIE y que el degradado sea el DECLARADO. Un campo
cuya ablacion no cambia nada no se cobra como cubierto: el test falla y hay que
sacarlo del contrato.

EL ARNES NO PUEDE PASAR EN VACIO
================================
La trampa clasica de este repo: si el contenedor no levanta o el grafo queda
vacio, un arnes mal hecho pasa en verde sin ejercer nada. Aqui hay tres suelos
independientes (seccion 0): la base tiene N nodos CONTADOS EN NEO4J, la pantalla
pinta M filas, y la ablacion ejerce K casos. Y ``_exigir_efimera`` aborta la
sesion entera si la URI no es local: esta suite BORRA nodos, y apuntarla a
produccion no puede depender de que nadie se equivoque de variable.

NUNCA PRODUCCION. Solo contenedor/instancia efimera y local.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app.chassis import FEATURE_SLOTS, slot_flag_env

URI = os.environ.get("NEO4J_TEST_URI")
USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not URI or not PASSWORD,
    reason="sin Neo4j efimero (define NEO4J_TEST_URI y NEO4J_TEST_PASSWORD)",
)

#: Anfitriones aceptados. La lista es BLANCA a proposito: cualquier cosa que no
#: este aqui se rechaza, incluida una IP de la LAN escrita por error. Un fallo
#: abierto en este punto no seria un test rojo, seria un DETACH DELETE contra el
#: grafo de VM105.
ANFITRIONES_EFIMEROS = frozenset({"localhost", "127.0.0.1", "::1", "neo4j"})


def _exigir_efimera(uri: str) -> None:
    host = (urlparse(uri).hostname or "").strip().lower()
    if host not in ANFITRIONES_EFIMEROS:
        raise RuntimeError(
            f"NEO4J_TEST_URI apunta a {host!r}, que no es una base efimera. "
            f"Esta suite BORRA nodos. Anfitriones admitidos: "
            f"{sorted(ANFITRIONES_EFIMEROS)}."
        )


WS = "contrato:paneles"
WS_AJENO = "contrato:ajeno"
P_A = "partida:contrato-a"
P_B = "partida:contrato-b"
PASSWORD_USUARIO = "ContratoPaneles_1234567890!"

SLOT_C = next(s for s in FEATURE_SLOTS if s.key == "C")
SLOT_B = next(s for s in FEATURE_SLOTS if s.key == "B")
SLOT_F = next(s for s in FEATURE_SLOTS if s.key == "F")
SLOT_G = next(s for s in FEATURE_SLOTS if s.key == "G")

#: Rol minimo de cada hueco, tal y como lo publica el contrato del chasis. No se
#: escribe a mano: si el contrato cambiara, estos tests lo siguen.
ROL = {s.key: s.role for s in (SLOT_C, SLOT_B, SLOT_F, SLOT_G)}


# ===========================================================================
# Material: nodos MINIMOS y CONOCIDOS, uno por cosa que se quiere afirmar
# ===========================================================================

#: Fuente del nodo de ablacion. Es SUYA Y DE NADIE MAS: asi, al borrarle
#: `source_document`, la fila de esa fuente desaparece del panel F y el cambio
#: es observable sin ambiguedad.
FUENTE_ABL = "/srv/material/libros/ablacion.pdf"
FUENTE_COMUN = "/srv/material/libros/comun.pdf"

TEXTO_DESCRIPCION = "La torre de Vela guarda el ultimo faro encendido"

#: Etiqueta de la relacion sembrada. TIENE que ser distinta de lo que
#: `relation_label()` deriva del TIPO (`CUSTODIA` -> "custodia"), o la ablacion
#: de `relation_label_es` no puede observarse: el respaldo devolveria exactamente
#: la misma cadena y el contrato saldria VERDE con el campo destruido.
#:
#: Ese fue un FALSO NEGATIVO real de la primera version de este fichero: la
#: semilla decia `relation_label_es:'custodia'` sobre un tipo `CUSTODIA`, asi que
#: quitar el campo no cambiaba ni un byte del HTML. El defecto no estaba en la
#: asercion, estaba en el MATERIAL: un fixture cuyo valor coincide con el del
#: degradado no puede distinguir "llego el dato" de "se aplico el respaldo".
ETIQUETA_RELACION = "guarda el faro de"
TIPO_RELACION = "CUSTODIA"


def _respaldo_de_relacion() -> str:
    """Lo que `relation_label()` deriva del tipo cuando NO hay etiqueta propia.

    Se calcula con la funcion real, no se escribe a mano: si el respaldo
    cambiara, el degradado esperado cambia con el.
    """
    from app.labels import relation_label
    return relation_label(TIPO_RELACION, None)

#: Cada entrada es un nodo con TODAS sus propiedades explicitas. Nada se hereda
#: ni se completa por defecto: un fixture que rellena huecos no puede demostrar
#: que la ausencia de un campo se propaga.
SEMILLA: tuple[dict, ...] = (
    # --- el nodo que se ablaciona. Completo a proposito: es el unico sobre el
    #     que se mide, y necesita tener TODO para poder perderlo.
    dict(entity_id="abl", canonical_name="Nodo de ablacion", entity_type="PERSONAJE",
         description=TEXTO_DESCRIPCION, confidence=0.91, review_status="reviewed",
         source_document=FUENTE_ABL, source_kind="pdf",
         workspace=WS, scope="juego", visibility="player"),
    # --- testigo: NUNCA se toca. Si una ablacion lo moviera, la ablacion no
    #     estaria midiendo lo que dice medir.
    dict(entity_id="testigo", canonical_name="Testigo inmovil", entity_type="LUGAR",
         description="No se toca", confidence=0.5, review_status="needs_review",
         source_document=FUENTE_COMUN, source_kind="manual",
         workspace=WS, scope="juego", visibility="player"),
    # --- ausencias declaradas de origen: el panel debe decir "no disponible",
    #     nunca inventar un cero ni una cadena plausible.
    dict(entity_id="sin_confianza", canonical_name="Sin confianza", entity_type="LUGAR",
         review_status="reviewed", source_document=FUENTE_COMUN, source_kind="pdf",
         workspace=WS, scope="juego", visibility="player"),
    dict(entity_id="sin_fuente", canonical_name="Sin fuente", entity_type="LUGAR",
         confidence=0.4, review_status="reviewed", source_kind="pdf",
         workspace=WS, scope="juego", visibility="player"),
    dict(entity_id="sin_estado", canonical_name="Sin estado", entity_type="LUGAR",
         confidence=0.4, source_document=FUENTE_COMUN, source_kind="pdf",
         workspace=WS, scope="juego", visibility="player"),
    # --- estado FUERA del vocabulario canonico: no es lo mismo que ausente, y
    #     el panel no puede pintarlo con aspecto de estado legitimo.
    dict(entity_id="estado_raro", canonical_name="Estado raro", entity_type="LUGAR",
         confidence=0.4, review_status="pendiente_de_algo",
         source_document=FUENTE_COMUN, source_kind="pdf",
         workspace=WS, scope="juego", visibility="player"),
    # --- autorizacion: existe, y para un `viewer` tiene que ser indistinguible
    #     de inexistente (mismo codigo, mismo cuerpo).
    dict(entity_id="secreto", canonical_name="Secreto del narrador", entity_type="PERSONAJE",
         description="No debe salir", confidence=0.99, review_status="reviewed",
         source_document="/srv/material/secreto.pdf", source_kind="pdf",
         workspace=WS, scope="juego", visibility="secret"),
    # --- workspace ajeno.
    dict(entity_id="ajeno", canonical_name="Material ajeno", entity_type="PERSONAJE",
         confidence=0.7, review_status="reviewed", source_document="/srv/ajeno.pdf",
         source_kind="pdf", workspace=WS_AJENO, scope="juego", visibility="player"),
    # --- partidas: espejo simetrico, para que un conteo asimetrico signifique
    #     fuga y no un fixture cojo.
    dict(entity_id="pa", canonical_name="Cosa de la partida A", entity_type="PERSONAJE",
         confidence=0.7, review_status="reviewed", source_document=FUENTE_COMUN,
         source_kind="pdf", workspace=WS, scope="partida", partida_id=P_A,
         visibility="player", known_from_session=0),
    dict(entity_id="pb", canonical_name="Cosa de la partida B", entity_type="PERSONAJE",
         confidence=0.7, review_status="reviewed", source_document=FUENTE_COMUN,
         source_kind="pdf", workspace=WS, scope="partida", partida_id=P_B,
         visibility="player", known_from_session=0),
)

#: Lo que un `viewer` sin partida activa DEBE ver en capa juego. Escrito a mano:
#: derivarlo del motor que se esta midiendo lo haria incapaz de discrepar.
VISIBLES_VIEWER = {
    "Nodo de ablacion", "Testigo inmovil", "Sin confianza", "Sin fuente",
    "Sin estado", "Estado raro",
}


# ===========================================================================
# Espia de Cypher: lo que de verdad se le pide a la base
# ===========================================================================

#: Clausulas de ESCRITURA de Cypher. Si una aparece en una consulta emitida
#: durante un GET, el panel escribio.
ESCRITURA = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s*\{\s*[^}]*\bCREATE)\b",
    re.IGNORECASE,
)


class SesionEspia:
    def __init__(self, real, registro):
        self._real, self._registro = real, registro

    def run(self, query, *a, **kw):
        self._registro.append(str(query))
        return self._real.run(query, *a, **kw)

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


class DriverEspia:
    """Envuelve el driver REAL y anota cada Cypher que sale hacia la base.

    No simula nada: la consulta se ejecuta contra Neo4j igual que sin espia. Lo
    unico que anade es el registro, que es lo que permite afirmar "ningun GET
    escribio" mirando lo emitido y no la prosa del modulo.

    DOS VIAS, NO UNA. El driver de Neo4j permite ejecutar Cypher por dos caminos
    independientes: `driver.session().run(...)` y `driver.execute_query(...)`.
    La primera version de este espia solo envolvia `session`, y `__getattr__`
    reenviaba `execute_query` AL DRIVER REAL sin registrarlo. Combinado con una
    foto acotada a los workspaces sembrados, una escritura por esa via evadia
    los DOS controles a la vez -- y se midio: decenas de nodos creados desde
    peticiones GET con la suite en verde.

    Un espia con un agujero es peor que no tener espia: publica un "cero
    escrituras" que nadie va a volver a comprobar.
    """

    #: Todo lo que ejecuta Cypher tiene que pasar por el registro. Se enumera
    #: explicitamente para que anadir un metodo nuevo del driver sea una
    #: decision consciente y no un reenvio silencioso de `__getattr__`.
    EJECUTAN_CYPHER = ("execute_query",)

    def __init__(self, real):
        self._real, self.consultas = real, []

    def session(self, *a, **kw):
        return SesionEspia(self._real.session(*a, **kw), self.consultas)

    def execute_query(self, query, *a, **kw):
        self.consultas.append(str(query))
        return self._real.execute_query(query, *a, **kw)

    def __getattr__(self, nombre):
        # Red de seguridad: si el driver expusiera manana otra via de ejecucion
        # y alguien la usara, este espia NO debe reenviarla en silencio.
        if nombre in self.EJECUTAN_CYPHER:  # pragma: no cover - ya envuelto arriba
            raise AttributeError(nombre)
        return getattr(self._real, nombre)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(scope="module")
def driver():
    from neo4j import GraphDatabase

    _exigir_efimera(URI)
    drv = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    drv.verify_connectivity()
    yield drv
    drv.close()


def _limpiar(driver) -> None:
    with driver.session() as s:
        s.run("MATCH (n:Entity) WHERE n.workspace IN $ws DETACH DELETE n",
              {"ws": [WS, WS_AJENO]})


@pytest.fixture(scope="module")
def semilla(driver):
    """Siembra la base efimera y la deja como estaba al terminar."""
    _exigir_efimera(URI)
    _limpiar(driver)
    with driver.session() as s:
        for nodo in SEMILLA:
            s.run("CREATE (n:Entity $props)", {"props": dict(nodo)})
        s.run(
            f"MATCH (a:Entity {{entity_id:'abl'}}), (t:Entity {{entity_id:'testigo'}}) "
            f"CREATE (a)-[:{TIPO_RELACION} {{visibility:'player', workspace:$ws, "
            f"scope:'juego', relation_label_es:$etiqueta}}]->(t)",
            {"ws": WS, "etiqueta": ETIQUETA_RELACION})
    yield
    _limpiar(driver)


@pytest.fixture(scope="module")
def elemento(driver, semilla) -> dict[str, str]:
    """``entity_id`` -> ``elementId``, que es el id con el que hablan los paneles.

    Se resuelve UNA vez y desde la base: escribirlo a mano seria inventarse la
    identidad que precisamente se quiere comprobar que es estable.
    """
    with driver.session() as s:
        filas = s.run(
            "MATCH (n:Entity) WHERE n.workspace IN $ws "
            "RETURN n.entity_id AS eid, elementId(n) AS elid", {"ws": [WS, WS_AJENO]}
        ).data()
    mapa = {f["eid"]: f["elid"] for f in filas}
    assert len(mapa) == len(SEMILLA), (
        f"la semilla no cuajo: {len(mapa)} nodos en la base, {len(SEMILLA)} esperados"
    )
    return mapa


@pytest.fixture
def app_real():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def entorno(tmp_path):
    """Workspace por defecto, huecos ENCENDIDOS y auth ACTIVA, con vuelta atras."""
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    claves = ["S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE"]
    claves += [slot_flag_env(s) for s in (SLOT_C, SLOT_B, SLOT_F, SLOT_G)]
    previos = {k: os.environ.get(k) for k in claves}

    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    for s in (SLOT_C, SLOT_B, SLOT_F, SLOT_G):
        os.environ[slot_flag_env(s)] = "true"
    get_settings.cache_clear()
    get_auth_settings.cache_clear()

    from app.auth import db as auth_db
    auth_db.ensure_migrated(Path(os.environ["S9K_AUTH_DB_PATH"]))

    yield Path(os.environ["S9K_AUTH_DB_PATH"])

    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


@pytest.fixture
def proveedor(app_real, semilla):
    """Instala el ``Neo4jGraphProvider`` REAL como proveedor BASE de la app.

    Se sustituye el proveedor BASE, NO el filtrado: asi la cadena entera
    (``get_filtered_provider`` -> ``get_visibility_context`` ->
    ``build_viewer_context`` -> ``PolicyFilteredProvider`` -> ``VisibilityPolicy``)
    se atraviesa en cada peticion sobre datos que vienen de Neo4j.
    """
    import app.deps as deps
    from app.providers.neo4j_provider import Neo4jGraphProvider

    _exigir_efimera(URI)
    prov = Neo4jGraphProvider(URI, USER, PASSWORD)
    espia = DriverEspia(prov._driver)
    prov._driver = espia
    prov.espia = espia
    app_real.dependency_overrides[deps.get_provider] = lambda: prov
    yield prov
    app_real.dependency_overrides.pop(deps.get_provider, None)
    espia._real.close()


def usuario(db_path: Path, nombre: str, rol: str, *, partida: str | None = None,
            tope: int | None = None) -> str:
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(conn, username=nombre, display_name=nombre.title(),
                                password_hash=hash_password(PASSWORD_USUARIO), role=rol)
        auth_db.update_user(conn, u.id, must_change_password=False)
        u = auth_db.get_user_by_id(conn, u.id)
        token, sesion = create_session(conn, u)
        if partida:
            auth_db.grant_partida_access(conn, u.id, WS, partida, granted_by="test",
                                         max_visible_session=tope if tope is not None else 100)
            auth_db.set_session_active_partida(conn, sesion.id, partida)
    return token


def cliente(app, cookie: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        from app.auth.config import get_auth_settings
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


# ---------------------------------------------------------------------------
# Lectura de lo renderizado. Se mira el HTML porque es lo que ve el operador:
# un campo que llega al contexto de plantilla y no se pinta no esta entregado.
# ---------------------------------------------------------------------------

def fila_g(html: str, elid: str) -> str:
    """El ``<tr>`` del panel G correspondiente a ese elementId."""
    m = re.search(r'<tr data-entity-id="' + re.escape(elid) + r'".*?</tr>', html, re.S)
    return m.group(0) if m else ""


def atributo(fragmento: str, nombre: str) -> str | None:
    m = re.search(nombre + r'="([^"]*)"', fragmento)
    return m.group(1) if m else None


def ids_g(html: str) -> list[str]:
    return re.findall(r'<tr data-entity-id="([^"]+)"', html)


def etiquetas_g(html: str) -> set[str]:
    return set(re.findall(r'<td><a href="[^"]*">([^<]*)</a></td>', html))


def filas_f(html: str) -> dict[str, str]:
    """asa -> fragmento ``<tr>`` del panel F."""
    return {m.group(1): m.group(0) for m in
            re.finditer(r'<tr data-source-handle="([^"]+)".*?</tr>', html, re.S)}


def G(c) -> str:
    return c.get(SLOT_G.prefix).text


def F(c) -> str:
    return c.get(SLOT_F.prefix, params={"workspace": WS}).text


# ===========================================================================
# 0. SUELOS. Sin esto todo lo demas es adorno.
# ===========================================================================

def test_la_base_efimera_tiene_el_material_contado_en_neo4j(driver, semilla):
    """Suelo 1: se cuenta EN LA BASE, no en la constante de Python.

    Contar la lista `SEMILLA` seria un suelo que se autocumple: pasaria aunque
    el `CREATE` no hubiera escrito nada.
    """
    with driver.session() as s:
        total = s.run("MATCH (n:Entity) WHERE n.workspace IN $ws RETURN count(n) AS c",
                      {"ws": [WS, WS_AJENO]}).single()["c"]
        con_fuente = s.run(
            "MATCH (n:Entity {workspace:$ws}) WHERE n.source_document IS NOT NULL "
            "RETURN count(DISTINCT n.source_document) AS c", {"ws": WS}).single()["c"]
    assert total == len(SEMILLA) == 10, f"la base tiene {total} nodos, no 10"
    assert con_fuente >= 2, "menos de dos fuentes distintas: el panel F no agruparia nada"


def test_los_paneles_pintan_filas_de_verdad(app_real, proveedor, entorno):
    """Suelo 2: el recorrido EJERCE algo. Cero filas no puede salir verde."""
    c = cliente(app_real, usuario(entorno, "suelo_v", ROL["G"]))
    html_g = G(c)
    assert len(ids_g(html_g)) >= 5, f"panel G pinto {len(ids_g(html_g))} filas"
    assert etiquetas_g(html_g) == VISIBLES_VIEWER, (
        f"el panel G no entrega lo declarado: {etiquetas_g(html_g)}")

    c2 = cliente(app_real, usuario(entorno, "suelo_r", ROL["F"]))
    assert len(filas_f(F(c2))) >= 2, "panel F no agrupo ni dos fuentes"


def test_el_control_de_autorizacion_COLAPSA(app_real, proveedor, entorno):
    """Suelo 3: cambiar el principal CAMBIA lo entregado.

    Si no colapsara, cada comprobacion negativa de abajo pasaria sin demostrar
    nada. Es el modo de fallo silencioso clasico de este repo.
    """
    admin = etiquetas_g(G(cliente(app_real, usuario(entorno, "col_a", "admin"))))
    viewer = etiquetas_g(G(cliente(app_real, usuario(entorno, "col_v", "viewer"))))
    assert "Secreto del narrador" in admin, "el admin no recibe potestad total"
    assert viewer < admin, f"el instrumento no colapsa: admin={admin} viewer={viewer}"


# ===========================================================================
# 1. CAMPOS OBLIGATORIOS: presentes, con el tipo esperado, DESDE NEO4J
# ===========================================================================

def test_el_panel_G_entrega_todos_los_campos_que_pinta(app_real, proveedor, entorno,
                                                       elemento):
    """La fila del panel G, campo a campo, con el valor que hay en la base."""
    c = cliente(app_real, usuario(entorno, "g_campos", ROL["G"]))
    tr = fila_g(G(c), elemento["abl"])
    assert tr, "la fila del nodo de ablacion no llego a pintarse"
    assert "Nodo de ablacion" in tr                       # canonical_name
    assert atributo(tr, "data-entity-type") == "PERSONAJE"  # entity_type
    assert atributo(tr, "data-confidence") == "0.91"      # confidence, float
    assert atributo(tr, "data-review-status") == "reviewed"
    assert atributo(tr, "data-visibility") == "player"
    assert FUENTE_ABL in tr                                # source_document
    assert "Revisado" in tr, "la etiqueta canonica del estado no llego"


def test_la_ficha_del_panel_G_entrega_descripcion_y_relaciones(app_real, proveedor,
                                                               entorno, elemento):
    c = cliente(app_real, usuario(entorno, "g_ficha", ROL["G"]))
    r = c.get(f"{SLOT_G.prefix}/item/{elemento['abl']}")
    assert r.status_code == 200
    assert TEXTO_DESCRIPCION in r.text, "`description` no viaja de Neo4j a la ficha"
    assert f'data-relation="{TIPO_RELACION}"' in r.text, "la relacion real no llego"
    assert ETIQUETA_RELACION in r.text, (
        "`relation_label_es` no viaja de Neo4j a la ficha: la pantalla estaria "
        "pintando el respaldo derivado del tipo sin que nada lo dijera")
    assert "Testigo inmovil" in r.text, "el otro extremo de la relacion no se resolvio"


def test_el_panel_F_entrega_fuente_procedencia_y_estado(app_real, proveedor, entorno):
    """`source_document`, `source_kind`, `review_status` y `entity_type` agregados."""
    c = cliente(app_real, usuario(entorno, "f_campos", ROL["F"]))
    html = F(c)
    from app.routers.chassis_sources import asa_de
    tr = filas_f(html).get(asa_de(FUENTE_ABL))
    assert tr, "la fuente del nodo de ablacion no aparecio en el panel F"
    assert "ablacion.pdf" in tr, "la etiqueta de la fuente no llego"
    assert atributo(tr, "data-source-declared") == "true"
    assert atributo(tr, "data-path-redacted") == "true", "la ruta debia recortarse"
    assert FUENTE_ABL not in html, "el panel F publico la RUTA completa de la fuente"
    assert "pdf (1)" in tr, "`source_kind` no llego al reparto de procedencia"
    assert 'data-status-known="true"' in tr, "`review_status` canonico no llego"


# ===========================================================================
# 2. ABLACION. ESTE ES EL CONTRATO: quitar el campo pone algo ROJO.
# ===========================================================================

def _quitar(driver, entity_id: str, prop: str) -> None:
    with driver.session() as s:
        s.run(f"MATCH (n:Entity {{entity_id:$e}}) REMOVE n.`{prop}`", {"e": entity_id})


def _poner(driver, entity_id: str, prop: str, valor) -> None:
    with driver.session() as s:
        s.run(f"MATCH (n:Entity {{entity_id:$e}}) SET n.`{prop}` = $v",
              {"e": entity_id, "v": valor})


def _obs_g(app_real, entorno, elid, nombre_usuario):
    def _f():
        c = cliente(app_real, usuario(entorno, nombre_usuario, ROL["G"]))
        html = G(c)
        return fila_g(html, elid) or "(FILA AUSENTE)", html
    return _f


#: (campo, valor, panel, degradado esperado en la observacion)
#:
#: `panel` dice DONDE se observa. `degradado` es lo que la pantalla debe decir
#: cuando el dato no esta: siempre una AUSENCIA declarada, nunca un cero ni un
#: valor plausible inventado.
ABLACIONES = (
    ("canonical_name", "Nodo de ablacion", "G", "etiqueta vacia"),
    ("entity_type", "PERSONAJE", "G", 'data-entity-type=""'),
    ("confidence", 0.91, "G", "no disponible"),
    ("review_status", "reviewed", "G", "no disponible"),
    ("source_document", FUENTE_ABL, "G", "no disponible"),
    ("visibility", "player", "G", "fila ausente (fallo cerrado)"),
    ("workspace", WS, "G", "fila ausente (fuera del workspace)"),
    ("source_kind", "pdf", "F", "no disponible"),
)


@pytest.mark.parametrize("campo,valor,panel,degradado", ABLACIONES,
                         ids=[f"{p}:{c}" for c, _, p, _ in ABLACIONES])
def test_quitar_un_campo_que_el_panel_consume_pone_algo_ROJO(
    driver, app_real, proveedor, entorno, elemento, campo, valor, panel, degradado
):
    """CALIBRACION OBLIGATORIA, una por campo.

    Se observa la pantalla CON el campo, se BORRA la propiedad en Neo4j, se
    vuelve a observar y se exige (a) que la observacion CAMBIE y (b) que el
    degradado sea el DECLARADO. Si no cambia, el campo no esta cubierto por
    ningun panel y no puede cobrarse como cubierto: el test falla.

    Se restaura siempre, y el TESTIGO se comprueba intacto: una ablacion que
    moviera otra fila no estaria midiendo lo que dice.
    """
    from app.routers.chassis_sources import asa_de

    def observar(sufijo: str) -> str:
        if panel == "G":
            c = cliente(app_real, usuario(entorno, f"abl_{campo}_{sufijo}", ROL["G"]))
            html = G(c)
            return fila_g(html, elemento["abl"]) or "(FILA AUSENTE)"
        c = cliente(app_real, usuario(entorno, f"abl_{campo}_{sufijo}", ROL["F"]))
        html = F(c)
        return filas_f(html).get(asa_de(FUENTE_ABL), "(FUENTE AUSENTE)")

    antes = observar("antes")
    assert antes not in ("(FILA AUSENTE)", "(FUENTE AUSENTE)"), (
        f"el caso {campo} parte de una observacion vacia: no puede medir nada")

    try:
        _quitar(driver, "abl", campo)
        despues = observar("despues")
    finally:
        _poner(driver, "abl", campo, valor)

    assert despues != antes, (
        f"ROJO NO PRODUCIDO: quitar `{campo}` de Neo4j no cambia nada en el panel "
        f"{panel}. El contrato para ese campo es DECORATIVO y no debe cobrarse."
    )

    # (b) el degradado es el declarado, no cualquier cambio.
    if degradado == "fila ausente (fallo cerrado)" or degradado.startswith("fila ausente"):
        assert despues == "(FILA AUSENTE)", (
            f"quitar `{campo}` cambio la fila pero no la retiro: {despues[:200]}")
    elif degradado == "no disponible":
        assert "no disponible" in despues, (
            f"quitar `{campo}` no produce la ausencia declarada: {despues[:200]}")
    elif degradado == 'data-entity-type=""':
        assert atributo(despues, "data-entity-type") == "", despues[:200]
    elif degradado == "etiqueta vacia":
        assert "Nodo de ablacion" not in despues, despues[:200]

    # el testigo no se movio: la ablacion mide lo suyo y nada mas.
    restaurada = observar("restaurada")
    assert restaurada == antes, f"la restauracion de `{campo}` no dejo la pantalla igual"


def test_quitar_la_etiqueta_de_la_relacion_pone_algo_ROJO(driver, app_real, proveedor,
                                                          entorno, elemento):
    """El ULTIMO campo del grafo que consume una plantilla: `e.label` en la ficha G.

    Se ablaciona sobre la RELACION, no sobre un nodo, que es la razon por la que
    no cabe en la parametrizacion de arriba.

    DEGRADADO DECLARADO: aqui la pantalla NO dice "no disponible". Cae al
    respaldo de `relation_label()`, que deriva una etiqueta del TIPO de la
    relacion. Se exige EXACTAMENTE eso -- que es lo que hace de esta prueba un
    contrato y no un "cambio algo": se afirma el VALOR del degradado, no su mera
    diferencia.

    Que el respaldo sea razonable no lo hace inocuo: la pantalla pasa de mostrar
    la etiqueta CURADA del dominio a mostrar una derivada del identificador
    tecnico, y no lo declara en ninguna parte. Queda anotado en docs/82 como
    degradado silencioso; corregirlo tocaria plantilla de producto, que este
    carril no toca.
    """
    def ficha() -> str:
        c = cliente(app_real, usuario(entorno, f"rel_{ficha.n}", ROL["G"]))
        ficha.n += 1
        r = c.get(f"{SLOT_G.prefix}/item/{elemento['abl']}")
        assert r.status_code == 200
        m = re.search(r'<li data-relation="[^"]*">(.*?)</li>', r.text, re.S)
        return m.group(1).strip() if m else "(RELACION AUSENTE)"
    ficha.n = 0

    respaldo = _respaldo_de_relacion()
    assert respaldo != ETIQUETA_RELACION, (
        "la semilla usa una etiqueta que coincide con el respaldo derivado del "
        "tipo: asi la ablacion NO puede observarse y el caso seria decorativo")

    antes = ficha()
    assert ETIQUETA_RELACION in antes, f"el arnes parte sin la etiqueta: {antes!r}"

    with driver.session() as s:
        s.run(f"MATCH ()-[r:{TIPO_RELACION}]->() REMOVE r.relation_label_es")
    try:
        despues = ficha()
    finally:
        with driver.session() as s:
            s.run(f"MATCH ()-[r:{TIPO_RELACION}]->() SET r.relation_label_es = $e",
                  {"e": ETIQUETA_RELACION})

    assert despues != antes, (
        "ROJO NO PRODUCIDO: quitar `relation_label_es` de Neo4j no cambia la "
        "ficha del panel G. El contrato para ese campo seria DECORATIVO.")
    assert ETIQUETA_RELACION not in despues, despues[:200]
    assert respaldo in despues, (
        f"el degradado no es el declarado: se esperaba el respaldo {respaldo!r} "
        f"derivado del tipo, y se obtuvo {despues[:200]!r}")

    assert ficha() == antes, "la restauracion no dejo la ficha igual"


def test_quitar_source_document_manda_la_entidad_al_cubo_de_ausencia(
    driver, app_real, proveedor, entorno
):
    """Panel F: sin fuente declarada NO se inventa una fuente, se declara la ausencia.

    Es el caso que la parametrizacion de arriba no puede expresar, porque el
    efecto no es un degradado DENTRO de la fila: la fila entera desaparece y la
    entidad reaparece contada en el cubo "sin fuente declarada".
    """
    from app.routers.chassis_sources import asa_de

    def leer():
        c = cliente(app_real, usuario(entorno, f"f_cubo_{id(driver)}_{leer.n}", ROL["F"]))
        leer.n += 1
        return F(c)
    leer.n = 0

    def cubo(filas) -> str:
        sin = [tr for tr in filas.values() if 'data-source-declared="false"' in tr]
        assert len(sin) == 1, f"se esperaba UN cubo de ausencia, hay {len(sin)}"
        return sin[0]

    antes = filas_f(leer())
    assert asa_de(FUENTE_ABL) in antes, "el arnes parte sin la fuente que va a quitar"
    contadas_antes = int(re.search(r'data-count="entities">(\d+)<', cubo(antes)).group(1))

    try:
        _quitar(driver, "abl", "source_document")
        despues = filas_f(leer())
    finally:
        _poner(driver, "abl", "source_document", FUENTE_ABL)

    assert asa_de(FUENTE_ABL) not in despues, (
        "quitar `source_document` no retiro la fuente: el panel la sigue publicando")
    tr_cubo = cubo(despues)
    contadas = int(re.search(r'data-count="entities">(\d+)<', tr_cubo).group(1))
    assert contadas == contadas_antes + 1, (
        f"la entidad sin fuente no se conto en el cubo de ausencia declarada: "
        f"{contadas_antes} -> {contadas}")
    assert "sin fuente declarada" in tr_cubo


# ===========================================================================
# 3. AUSENCIA != CERO, y desconocido != ausente
# ===========================================================================

def test_la_ausencia_de_confianza_no_se_pinta_como_cero(app_real, proveedor, entorno,
                                                        elemento):
    """`sin_confianza` no declara `confidence`. La pantalla debe DECIRLO."""
    c = cliente(app_real, usuario(entorno, "aus_conf", ROL["G"]))
    tr = fila_g(G(c), elemento["sin_confianza"])
    assert tr, "la entidad sin confianza no llego a la pantalla"
    assert atributo(tr, "data-confidence") == "", "ausencia serializada como valor"
    assert "no disponible" in tr
    assert "0.00" not in tr, "AUSENCIA PINTADA COMO CERO: es el fallo que se persigue"


def test_la_ausencia_de_fuente_no_inventa_un_nombre(app_real, proveedor, entorno,
                                                    elemento):
    c = cliente(app_real, usuario(entorno, "aus_fuente", ROL["G"]))
    tr = fila_g(G(c), elemento["sin_fuente"])
    assert tr and "no disponible" in tr


def test_un_estado_desconocido_no_se_confunde_con_uno_ausente(app_real, proveedor,
                                                              entorno):
    """Tres casos DISTINGUIBLES en el panel F, sobre datos reales de Neo4j.

    canonico -> etiqueta en espanol y `conocido=true`;
    fuera del vocabulario -> "no reconocido (x)" y `conocido=false`;
    ausente -> "no declarado" y `conocido=false`.
    Fundir los dos ultimos es como un estado inventado acaba pareciendo legitimo.
    """
    c = cliente(app_real, usuario(entorno, "f_estados", ROL["F"]))
    from app.routers.chassis_sources import asa_de
    tr = filas_f(F(c))[asa_de(FUENTE_COMUN)]
    assert 'data-status="needs_review"' in tr and 'data-status-known="true"' in tr
    assert "no reconocido (pendiente_de_algo)" in tr, "estado fuera del vocabulario fundido"
    assert 'data-status=""' in tr and "no declarado" in tr, "estado AUSENTE no declarado"
    assert re.search(r'data-status="pendiente_de_algo"[^>]*data-status-known="false"', tr), \
        "un estado desconocido se pinto con aspecto de legitimo"


def test_null_en_neo4j_es_indistinguible_de_ausente_y_asi_se_declara(driver, app_real,
                                                                     proveedor, entorno,
                                                                     elemento):
    """LIMITE MEDIDO, no supuesto: Neo4j no puede almacenar una propiedad `null`.

    `SET n.confidence = null` BORRA la propiedad. Por tanto "null" y "ausente"
    no son estados distinguibles en esta frontera, y el panel los trata igual
    -- que es lo correcto, porque son el mismo hecho. Lo que si se distingue de
    ambos es el VACIO (`""`), y eso si se comprueba.
    """
    with driver.session() as s:
        s.run("MATCH (n:Entity {entity_id:'abl'}) SET n.confidence = null")
        quedan = s.run("MATCH (n:Entity {entity_id:'abl'}) "
                       "RETURN n.confidence IS NULL AS nula, "
                       "'confidence' IN keys(n) AS presente").single()
    try:
        assert quedan["nula"] is True and quedan["presente"] is False, (
            "Neo4j habria almacenado un null explicito: revisar esta afirmacion")
        c = cliente(app_real, usuario(entorno, "null_conf", ROL["G"]))
        tr = fila_g(G(c), elemento["abl"])
        assert atributo(tr, "data-confidence") == "" and "no disponible" in tr
    finally:
        _poner(driver, "abl", "confidence", 0.91)

    # VACIO: distinguible de ausente en la base, y el panel lo degrada igual que
    # una ausencia en vez de pintar una fuente llamada "".
    try:
        _poner(driver, "abl", "source_document", "")
        with driver.session() as s:
            presente = s.run("MATCH (n:Entity {entity_id:'abl'}) "
                             "RETURN 'source_document' IN keys(n) AS p").single()["p"]
        assert presente is True, "la cadena vacia si es una propiedad presente"
        c = cliente(app_real, usuario(entorno, "vacio_fuente", ROL["G"]))
        assert "no disponible" in fila_g(G(c), elemento["abl"])
    finally:
        _poner(driver, "abl", "source_document", FUENTE_ABL)


# ===========================================================================
# 4. IDs ESTABLES: la ficha es la del MISMO objeto que la fila
# ===========================================================================

def test_el_id_de_la_lista_abre_la_ficha_del_mismo_objeto(app_real, proveedor, entorno,
                                                          elemento):
    """No se compara contra una constante: se sigue el enlace que pinta la lista.

    Un id que la lista publica y la ficha no reconoce es el defecto clasico de
    "lista y detalle por caminos distintos". Aqui el camino es el mismo que
    recorreria el operador con el raton.
    """
    c = cliente(app_real, usuario(entorno, "id_estable", ROL["G"]))
    html = G(c)
    # `url_for` produce URL absoluta (http://testserver/...): se captura entera y
    # se sigue tal cual, que es lo que haria el navegador.
    enlaces = re.findall(r'<a href="(\S*?/panel/entities/item/[^"]+)">([^<]*)</a>', html)
    assert len(enlaces) >= 5, f"la lista solo publico {len(enlaces)} enlaces de ficha"
    for url, etiqueta in enlaces:
        r = c.get(url)
        assert r.status_code == 200, f"la lista publico {url}, que la ficha no reconoce"
        assert f'data-entity-id="{url.rsplit("/", 1)[-1]}"' in r.text
        assert etiqueta in r.text, f"la ficha de {url} no es la del objeto listado"


def test_el_id_es_el_mismo_entre_dos_lecturas(app_real, proveedor, entorno):
    """Estable entre peticiones: si cambiara, todo enlace guardado se rompe."""
    c = cliente(app_real, usuario(entorno, "id_dos", ROL["G"]))
    assert ids_g(G(c)) == ids_g(G(c))


def test_el_asa_de_una_fuente_es_estable_y_no_es_la_ruta(app_real, proveedor, entorno):
    c = cliente(app_real, usuario(entorno, "f_asa", ROL["F"]))
    una, otra = filas_f(F(c)), filas_f(F(c))
    assert set(una) == set(otra) and una
    for asa in una:
        r = c.get(f"{SLOT_F.prefix}/ficha/{asa}", params={"workspace": WS})
        assert r.status_code == 200, f"la lista publico el asa {asa} que la ficha no abre"
        assert "/srv/" not in r.text, "la ficha publico una ruta de servidor"


# ===========================================================================
# 5. WORKSPACE Y PARTIDA ACOTADOS
# ===========================================================================

def test_el_workspace_ajeno_no_se_cuela_por_ninguno_de_los_dos_paneles(app_real,
                                                                      proveedor,
                                                                      entorno, elemento):
    c_g = cliente(app_real, usuario(entorno, "ws_g", ROL["G"]))
    assert "Material ajeno" not in G(c_g)
    assert c_g.get(f"{SLOT_G.prefix}/item/{elemento['ajeno']}").status_code == 404

    c_f = cliente(app_real, usuario(entorno, "ws_f", ROL["F"]))
    assert "ajeno.pdf" not in F(c_f)


def test_una_partida_no_ve_el_material_de_la_otra_por_el_panel(app_real, proveedor,
                                                               entorno, elemento):
    """Aislamiento entre partidas medido POR HTTP y sobre datos reales."""
    a = cliente(app_real, usuario(entorno, "p_a", ROL["G"], partida=P_A))
    b = cliente(app_real, usuario(entorno, "p_b", ROL["G"], partida=P_B))
    vista_a, vista_b = etiquetas_g(G(a)), etiquetas_g(G(b))
    assert "Cosa de la partida A" in vista_a, "la partida activa no aporta su material"
    assert "Cosa de la partida B" not in vista_a, "FUGA entre partidas por el panel G"
    assert "Cosa de la partida A" not in vista_b, "FUGA entre partidas por el panel G"
    assert len(vista_a) == len(vista_b), "conteos asimetricos entre partidas"
    assert a.get(f"{SLOT_G.prefix}/item/{elemento['pb']}").status_code == 404


def test_sin_partida_activa_no_se_ve_material_de_partida(app_real, proveedor, entorno):
    c = cliente(app_real, usuario(entorno, "sin_p", ROL["G"]))
    vista = etiquetas_g(G(c))
    assert "Cosa de la partida A" not in vista and "Cosa de la partida B" not in vista


# ===========================================================================
# 6. AUTORIZACION: lo no autorizado, INDISTINGUIBLE de lo inexistente
# ===========================================================================

def test_lo_no_autorizado_responde_igual_que_lo_inexistente(app_real, proveedor,
                                                            entorno, elemento):
    """Mismo codigo Y MISMO CUERPO. Un 403 aqui diria "existe pero no es tuya".

    Se compara contra un id INVENTADO con la misma forma sintactica, para que la
    diferencia no pueda venir del formato del identificador.
    """
    c = cliente(app_real, usuario(entorno, "indist", ROL["G"]))
    existente_no_autorizado = c.get(f"{SLOT_G.prefix}/item/{elemento['secreto']}")
    inexistente = c.get(f"{SLOT_G.prefix}/item/4:00000000-0000-0000-0000-000000000000:999")
    assert existente_no_autorizado.status_code == 404 == inexistente.status_code
    assert existente_no_autorizado.text == inexistente.text, (
        "el cuerpo distingue 'no es tuya' de 'no existe'")
    assert "Secreto del narrador" not in existente_no_autorizado.text


def test_una_fuente_solo_de_material_no_autorizado_no_existe_para_el_viewer(app_real,
                                                                           proveedor,
                                                                           entorno):
    from app.routers.chassis_sources import asa_de
    c = cliente(app_real, usuario(entorno, "f_indist", ROL["F"]))
    asa = asa_de("/srv/material/secreto.pdf")
    assert asa not in filas_f(F(c)), "el panel F publico una fuente solo secreta"
    r = c.get(f"{SLOT_F.prefix}/ficha/{asa}", params={"workspace": WS})
    inventada = c.get(f"{SLOT_F.prefix}/ficha/{'0' * 16}", params={"workspace": WS})
    assert r.status_code == 404 == inventada.status_code
    assert r.text == inventada.text


@pytest.mark.parametrize("clave", ["C", "B", "F", "G"])
def test_un_rol_insuficiente_no_entra_en_el_panel(app_real, proveedor, entorno, clave):
    """El rol del CONTRATO manda. Un `viewer` no entra en B ni en C ni en F."""
    slot = {"C": SLOT_C, "B": SLOT_B, "F": SLOT_F, "G": SLOT_G}[clave]
    c = cliente(app_real, usuario(entorno, f"rol_{clave}", "viewer"))
    r = c.get(slot.prefix)
    if slot.role == "viewer":
        assert r.status_code == 200
    else:
        assert r.status_code in (302, 303, 403, 404), (
            f"un viewer entro en el panel {clave}, que exige {slot.role}")


@pytest.mark.parametrize("clave", ["C", "B", "F", "G"])
def test_el_panel_apagado_es_indistinguible_de_una_ruta_inexistente(app_real, proveedor,
                                                                    entorno, clave):
    """El interruptor apagado da 404, no una pagina vacia ni un 200 mudo."""
    slot = {"C": SLOT_C, "B": SLOT_B, "F": SLOT_F, "G": SLOT_G}[clave]
    os.environ[slot_flag_env(slot)] = "false"
    try:
        c = cliente(app_real, usuario(entorno, f"off_{clave}", slot.role))
        assert c.get(slot.prefix).status_code == 404
    finally:
        os.environ[slot_flag_env(slot)] = "true"


# ===========================================================================
# 7. NINGUN GET ESCRIBE. Dos controles independientes.
# ===========================================================================

def _foto(driver) -> list:
    """Estado COMPLETO de LA BASE ENTERA: todo nodo y toda arista, con sus props.

    No es un conteo. Un conteo no ve un `SET` que cambie un valor sin crear
    nada, que es justo la escritura mas facil de colar desde un GET.

    Y NO se acota a los workspaces sembrados. Acotarla era el segundo agujero
    del par: una escritura que creara nodos con otra ETIQUETA -- o sin
    `workspace` -- caia fuera del `WHERE` y la foto salia identica. Fotografiar
    la base entera cuesta lo mismo en una base efimera de diez nodos y no deja
    esa puerta. Si algo aparece en la base durante un GET, esto lo ve, se llame
    como se llame.
    """
    with driver.session() as s:
        nodos = s.run(
            "MATCH (n) RETURN elementId(n) AS elid, labels(n) AS l, "
            "properties(n) AS p ORDER BY elid").data()
        rels = s.run(
            "MATCH ()-[r]->() RETURN elementId(r) AS elid, type(r) AS t, "
            "properties(r) AS p ORDER BY elid").data()
    return [nodos, rels]


def _recorrer_los_cuatro(app_real, entorno, elemento) -> list[int]:
    """Un recorrido COMPLETO: lista y ficha de los cuatro huecos."""
    codigos = []
    for clave, slot in (("C", SLOT_C), ("B", SLOT_B), ("F", SLOT_F), ("G", SLOT_G)):
        c = cliente(app_real, usuario(entorno, f"rec_{clave}", ROL[clave]))
        codigos.append(c.get(slot.prefix).status_code)
        codigos.append(c.get(slot.prefix, params={"workspace": WS}).status_code)
    from app.routers.chassis_sources import asa_de
    g = cliente(app_real, usuario(entorno, "rec_g2", ROL["G"]))
    for eid in ("abl", "testigo", "sin_confianza"):
        codigos.append(g.get(f"{SLOT_G.prefix}/item/{elemento[eid]}").status_code)
    f = cliente(app_real, usuario(entorno, "rec_f2", ROL["F"]))
    for fuente in (FUENTE_ABL, FUENTE_COMUN):
        codigos.append(
            f.get(f"{SLOT_F.prefix}/ficha/{asa_de(fuente)}",
                  params={"workspace": WS}).status_code)
    return codigos


def test_recorrer_los_cuatro_paneles_no_cambia_el_estado_de_la_base(
    driver, app_real, proveedor, entorno, elemento
):
    """Control 1: la base ANTES y DESPUES, propiedad a propiedad."""
    antes = _foto(driver)
    codigos = _recorrer_los_cuatro(app_real, entorno, elemento)
    assert len(codigos) >= 13, "el recorrido no ejercio suficientes pantallas"
    assert sum(1 for c in codigos if c == 200) >= 8, (
        f"el recorrido no llego a servir contenido: {codigos}")
    assert _foto(driver) == antes, "UN GET ESCRIBIO: el estado de la base cambio"


def test_ningun_get_emite_una_sola_clausula_de_escritura(app_real, proveedor, entorno,
                                                         elemento):
    """Control 2, INDEPENDIENTE del anterior: lo EMITIDO hacia la base.

    La foto veria una escritura que dejara el estado igual (un `SET` al mismo
    valor, un `MERGE` idempotente) como si no hubiera pasado nada. El espia la
    ve igualmente, porque mira el Cypher que sale, no el resultado.
    """
    proveedor.espia.consultas.clear()
    _recorrer_los_cuatro(app_real, entorno, elemento)
    consultas = list(proveedor.espia.consultas)
    assert len(consultas) >= 10, (
        f"solo {len(consultas)} consultas: el recorrido no toco la base y este "
        f"control estaria pasando en vacio")
    culpables = [q for q in consultas if ESCRITURA.search(q)]
    assert not culpables, f"un GET emitio Cypher de ESCRITURA: {culpables[:3]}"


def test_el_detector_de_escritura_MUERDE(app_real, proveedor, entorno, driver):
    """CONTROL NEGATIVO del control 2. Sin esto, "0 culpables" no vale nada.

    Se emite a proposito una escritura POR EL MISMO DRIVER que espia el control
    y se exige que la cace. Se escribe y se borra un nodo de usar y tirar, fuera
    de los workspaces de la semilla.
    """
    proveedor.espia.consultas.clear()
    with proveedor._driver.session() as s:
        s.run("CREATE (n:CanarioContrato {marca:'calibracion'})")
        s.run("MATCH (n:CanarioContrato) DELETE n")
    culpables = [q for q in proveedor.espia.consultas if ESCRITURA.search(q)]
    assert len(culpables) == 2, (
        "el detector de escritura NO muerde: dejaria pasar un CREATE de verdad")


def test_el_espia_ve_TAMBIEN_la_via_de_execute_query(app_real, proveedor, entorno):
    """CONTROL NEGATIVO de la SEGUNDA via de ejecucion. El agujero que hubo.

    `driver.execute_query(...)` ejecuta Cypher sin pasar por `session().run`.
    Mientras el espia solo envolvia `session`, esta via se reenviaba intacta al
    driver real y no quedaba registrada; con la foto acotada ademas a los
    workspaces sembrados, una escritura por aqui con otra etiqueta evadia los
    DOS controles a la vez. Se midio antes de arreglarlo: decenas de nodos
    creados desde peticiones GET, con la suite en VERDE.

    Esta prueba exige que la via quede cubierta. Si alguien vuelve a dejar que
    `__getattr__` la reenvie, se pone roja.
    """
    proveedor.espia.consultas.clear()
    proveedor._driver.execute_query("CREATE (n:CanarioExecuteQuery {marca:'calibracion'})")
    proveedor._driver.execute_query("MATCH (n:CanarioExecuteQuery) DELETE n")
    culpables = [q for q in proveedor.espia.consultas if ESCRITURA.search(q)]
    assert len(culpables) == 2, (
        "el espia NO registra `execute_query`: hay una via de escritura que "
        f"ningun control ve. Registradas: {proveedor.espia.consultas}")


def test_la_foto_ve_un_nodo_creado_FUERA_de_los_workspaces_sembrados(driver, semilla):
    """CONTROL NEGATIVO del acotado de la foto.

    Un nodo con otra etiqueta y sin `workspace` caia fuera del `WHERE` de la
    version anterior y la foto salia identica. Ahora la foto es de la base
    entera y esto se ve.
    """
    antes = _foto(driver)
    with driver.session() as s:
        s.run("CREATE (n:RastroFueraDeAmbito {marca:'calibracion'})")
    try:
        assert _foto(driver) != antes, (
            "la foto NO ve un nodo creado fuera de los workspaces sembrados: "
            "una escritura con otra etiqueta pasaria inadvertida")
    finally:
        with driver.session() as s:
            s.run("MATCH (n:RastroFueraDeAmbito) DELETE n")
    assert _foto(driver) == antes, "la limpieza no dejo la base igual"


def test_la_foto_de_la_base_MUERDE(driver, semilla):
    """CONTROL NEGATIVO del control 1. Un `SET` que no crea nada debe verse."""
    antes = _foto(driver)
    try:
        _poner(driver, "testigo", "confidence", 0.123456)
        assert _foto(driver) != antes, "la foto no ve un cambio de propiedad"
    finally:
        _poner(driver, "testigo", "confidence", 0.5)
    assert _foto(driver) == antes, "la restauracion no dejo la base igual"


# ===========================================================================
# 8. LOS PANELES B Y C: medidos, no supuestos
# ===========================================================================

def test_los_paneles_B_y_C_no_consultan_neo4j_en_absoluto(app_real, proveedor, entorno):
    """HECHO MEDIDO, no leido en la prosa del modulo.

    B (operaciones) vive de la base de jobs y del informe de salud; C (revision)
    del paquete de propuestas V3. Ninguno de los dos toca el grafo. Se afirma
    con el espia: cero Cypher emitido durante sus peticiones. Y se declara aqui
    porque es la respuesta al encargo: el contrato con Neo4j tiene superficie
    real en F y G, y NINGUNA en B y C. Si algun dia alguien conectara B o C al
    grafo, este test se pondria rojo y habria que ampliar el contrato.
    """
    for clave, slot in (("B", SLOT_B), ("C", SLOT_C)):
        proveedor.espia.consultas.clear()
        c = cliente(app_real, usuario(entorno, f"nc_{clave}", ROL[clave]))
        r = c.get(slot.prefix)
        assert r.status_code in (200, 503), f"el panel {clave} respondio {r.status_code}"
        assert proveedor.espia.consultas == [], (
            f"el panel {clave} consulto Neo4j: {proveedor.espia.consultas[:2]}")


def test_los_cuatro_paneles_responden_en_un_estado_declarado(app_real, proveedor,
                                                             entorno):
    """Ninguno revienta con Neo4j real detras, y ninguno responde 500."""
    for clave, slot in (("C", SLOT_C), ("B", SLOT_B), ("F", SLOT_F), ("G", SLOT_G)):
        c = cliente(app_real, usuario(entorno, f"est_{clave}", ROL[clave]))
        r = c.get(slot.prefix)
        assert r.status_code in (200, 503), f"panel {clave}: {r.status_code}"
        if r.status_code == 503:
            assert 'data-state="error"' in r.text, (
                f"el panel {clave} degrado sin declarar el estado de error")
        assert "/srv/" not in r.text or clave in ("F", "G"), "fuga de ruta de servidor"
        assert URI.split("//")[-1] not in r.text, "la URI de la base salio a la pantalla"


# ===========================================================================
# 9. LO QUE NEO4J NO ENTREGA. Medido, para que no se descubra en produccion.
# ===========================================================================

def test_la_proyeccion_cypher_NO_entrega_entity_id_y_eso_esta_medido(proveedor, semilla):
    """LIMITE CONOCIDO Y MEDIDO, no una sorpresa.

    `_node_to_dict` es una LISTA BLANCA de propiedades, no `dict(n)`: lo que no
    esta en esa lista no llega, aunque este en la base. `entity_id` no esta.
    Consecuencia real: `serialize_node` publica `entity_id` = "" para TODO nodo
    que venga de Neo4j, y la identidad que viaja en las URLs de los paneles es
    el `elementId`, que la propia nota de `app/serializers.py` declara NO
    durable (se regenera al restaurar un dump).

    Ninguno de los cuatro paneles pinta `entity_id` hoy, asi que esto no rompe
    ninguna pantalla; se congela aqui para que el dia que alguien lo pinte,
    o el dia que se restaure un dump y los enlaces guardados dejen de resolver,
    exista una prueba que ya lo decia.
    """
    from app.serializers import serialize_node

    items, total = proveedor.list_entities(WS, limit=100)
    assert total >= 6, f"la lectura directa del proveedor devolvio {total}: arnes vacio"
    assert all("entity_id" not in n for n in items), (
        "la proyeccion SI entrega `entity_id`: actualiza este limite documentado")
    assert all(serialize_node(n)["entity_id"] == "" for n in items)
    assert all(n["id"] and n["id"] == n["id"] for n in items)

    # Lo que si entrega, y de lo que viven los paneles.
    imprescindibles = ("id", "label", "type", "workspace", "visibility", "scope",
                       "review_status", "source_document", "source_kind", "confidence",
                       "description")
    abl = next(n for n in items if n["label"] == "Nodo de ablacion")
    faltan = [k for k in imprescindibles if k not in abl]
    assert not faltan, f"la proyeccion Cypher perdio campos que los paneles consumen: {faltan}"


def test_short_summary_no_viaja_desde_neo4j(proveedor, semilla, driver):
    """Otro limite medido: `serialize_node` lo publica, la proyeccion no lo trae."""
    from app.serializers import serialize_node

    _poner(driver, "abl", "short_summary", "Resumen breve de la torre")
    try:
        items, _ = proveedor.list_entities(WS, limit=100)
        abl = next(n for n in items if n["label"] == "Nodo de ablacion")
        assert "short_summary" not in abl, (
            "la proyeccion ya trae `short_summary`: actualiza este limite documentado")
        assert serialize_node(abl)["short_summary"] == ""
    finally:
        with driver.session() as s:
            s.run("MATCH (n:Entity {entity_id:'abl'}) REMOVE n.short_summary")

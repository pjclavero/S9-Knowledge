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

import ast
import importlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import jinja2
from jinja2 import nodes as JN

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
    #     Los campos de ANCLA (carril 4 de V3.1) llevan valores unicos y
    #     reconocibles a proposito: ver `ANCLAS_DE_LA_FICHA` mas abajo. Un
    #     fixture cuyo valor coincide con el respaldo de la plantilla no puede
    #     distinguir «llego el dato» de «se aplico el degradado» -- el falso
    #     negativo que ya se pago con `relation_label_es`.
    dict(entity_id="abl", canonical_name="Nodo de ablacion", entity_type="PERSONAJE",
         description=TEXTO_DESCRIPCION, confidence=0.91, review_status="reviewed",
         source_document=FUENTE_ABL, source_kind="pdf",
         aliases=["Alias unico de ablacion"], source_pages=[4242],
         created_at="2019-01-01T00:00:00Z-creado-abl",
         updated_at="2020-02-02T00:00:00Z-actualizado-abl",
         extractor_version="extractor-9.9.9-abl",
         prompt_version="prompt-8.8.8-abl",
         source_hash="hash-de-ablacion-7777",
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


class TxEspia:
    """Transaccion espiada. Es el eslabon que faltaba.

    `session.execute_write(lambda tx: tx.run(...))` NO pasa por `session.run`:
    el Cypher lo emite el `tx` que el driver le entrega a la funcion. Si ese
    `tx` no esta envuelto, la consulta no se registra por mucho que la sesion
    lo este.
    """

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


class SesionEspia:
    """Sesion espiada, con TODAS sus vias de ejecucion cubiertas.

    La version anterior solo envolvia `run`, y su `__getattr__` reenviaba
    `execute_write`, `execute_read` y `begin_transaction` SIN registrar. Una
    escritura por cualquiera de esas tres era invisible para el espia; si ademas
    era IDEMPOTENTE (un `SET` al mismo valor), la foto tampoco la veia, porque
    el estado no cambiaba. Es decir: la capacidad que §5 de docs/82 atribuye al
    espia --ver lo que la foto no puede ver-- no existia para esas tres vias.
    """

    #: Toda via de ejecucion de la sesion. Enumerada explicitamente: si el
    #: driver anade otra manana, `__getattr__` NO la reenvia en silencio.
    EJECUTAN_CYPHER = ("execute_write", "execute_read", "begin_transaction")

    def __init__(self, real, registro):
        self._real, self._registro = real, registro

    def run(self, query, *a, **kw):
        self._registro.append(str(query))
        return self._real.run(query, *a, **kw)

    def _envuelto(self, fn):
        registro = self._registro

        def envoltorio(tx, *a, **kw):
            return fn(TxEspia(tx, registro), *a, **kw)
        return envoltorio

    def execute_write(self, fn, *a, **kw):
        return self._real.execute_write(self._envuelto(fn), *a, **kw)

    def execute_read(self, fn, *a, **kw):
        return self._real.execute_read(self._envuelto(fn), *a, **kw)

    def begin_transaction(self, *a, **kw):
        return TxEspia(self._real.begin_transaction(*a, **kw), self._registro)

    def __getattr__(self, nombre):
        if nombre in self.EJECUTAN_CYPHER:  # pragma: no cover - ya envueltos arriba
            raise AttributeError(nombre)
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
    """``entity_id`` -> el id con el que hablan los paneles.

    Se resuelve UNA vez y DESDE LA BASE: escribirlo a mano seria inventarse la
    identidad que precisamente se quiere comprobar que es estable.

    CAMBIO DE IDENTIDAD (carril «identificador durable», P0 de RC)
    --------------------------------------------------------------
    Este mapa devolvia el ``elementId``. Ya no: los paneles hablan ahora el
    ``entity_id``, el identificador canonico del modelo V3. El motivo esta
    medido en la seccion 9 de este mismo fichero, que antes congelaba la
    carencia y ahora congela su cierre: el ``elementId`` es la direccion FISICA
    del store y ``dump``/``restore`` la reasigna, asi que todo enlace guardado
    dejaba de resolver tras una restauracion -- con un 404 que, por diseno de la
    politica, es indistinguible de «no existe».

    Lo que NO cambia es la regla de este fixture: el valor se lee de la base.
    Se lee ``n.entity_id``, que es una propiedad real del nodo, no una constante
    del test. Y se comprueba abajo que ese valor NO coincide con el fisico, para
    que ninguna prueba de este fichero pueda pasar por confundirlos.
    """
    with driver.session() as s:
        filas = s.run(
            "MATCH (n:Entity) WHERE n.workspace IN $ws "
            "RETURN n.entity_id AS eid, elementId(n) AS elid", {"ws": [WS, WS_AJENO]}
        ).data()
    mapa = {f["eid"]: f["eid"] for f in filas}
    assert len(mapa) == len(SEMILLA), (
        f"la semilla no cuajo: {len(mapa)} nodos en la base, {len(SEMILLA)} esperados"
    )
    # NO-COLISION, comprobada antes de que ningun test la use. Si el `entity_id`
    # y el `elementId` pudieran confundirse, este fichero entero seria incapaz
    # de distinguir «viaja la identidad de dominio» de «viaja la fisica».
    fisicos = {f["elid"] for f in filas}
    assert not (set(mapa) & fisicos), "entity_id y elementId colisionan en la semilla"
    return mapa


@pytest.fixture(scope="module")
def elemento_fisico(driver, semilla) -> dict[str, str]:
    """``entity_id`` -> ``elementId``. El identificador FISICO, para NEGARLO.

    Existe para poder afirmar que este valor NO aparece en ninguna pantalla.
    Sin el, «el elementId ya no viaja» seria una afirmacion sin testigo.
    """
    with driver.session() as s:
        filas = s.run(
            "MATCH (n:Entity) WHERE n.workspace IN $ws "
            "RETURN n.entity_id AS eid, elementId(n) AS elid", {"ws": [WS, WS_AJENO]}
        ).data()
    return {f["eid"]: f["elid"] for f in filas}


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


def test_el_espia_ve_las_TRES_vias_de_la_sesion(proveedor, semilla):
    """CONTROL NEGATIVO de `execute_write`, `execute_read` y `begin_transaction`.

    Las tres emiten Cypher SIN pasar por `session.run`, y las tres se reenviaban
    sin registrar. La peor era `execute_write` con una escritura IDEMPOTENTE
    (`SET n.confidence = <el mismo valor>`): invisible para el espia por no estar
    envuelta, e invisible para la foto por no cambiar el estado. Justo la
    combinacion que §5 de docs/82 dice cubrir.

    Se ejercitan las tres de verdad contra la base y se exige que las tres
    queden registradas.
    """
    espia = proveedor.espia
    espia.consultas.clear()

    with proveedor._driver.session() as s:
        # 1. escritura IDEMPOTENTE: la foto no la veria.
        s.execute_write(
            lambda tx: tx.run("MATCH (n:Entity {entity_id:'abl'}) SET n.confidence = 0.91"))
        # 2. lectura por su propia via.
        s.execute_read(lambda tx: tx.run("MATCH (n:Entity) RETURN count(n) AS c").single())
        # 3. transaccion explicita.
        with s.begin_transaction() as tx:
            tx.run("MATCH (n:Entity {entity_id:'abl'}) SET n.confidence = 0.91")
            tx.commit()

    assert len(espia.consultas) == 3, (
        f"el espia no registra las tres vias de la sesion: {espia.consultas}")
    culpables = [q for q in espia.consultas if ESCRITURA.search(q)]
    assert len(culpables) == 2, (
        f"las escrituras idempotentes por `execute_write`/`begin_transaction` no "
        f"se detectan: {espia.consultas}")


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

def test_la_proyeccion_cypher_SI_entrega_entity_id_LIMITE_CERRADO(proveedor, semilla):
    """LIMITE CERRADO. Este test decia lo contrario, y decia bien.

    Su version anterior congelaba la carencia: `_node_to_dict` es una LISTA
    BLANCA y `entity_id` no estaba en ella, asi que `serialize_node` publicaba
    `entity_id` = "" para TODO nodo venido de Neo4j y la identidad que viajaba
    en las URLs era el `elementId` -- que `app/serializers.py` ya declaraba NO
    durable. Aquel test pedia literalmente «actualiza este limite documentado»
    el dia que dejara de ser cierto. Ese dia es este.

    Se invierte la afirmacion en vez de borrarla: la carencia y su cierre son
    la misma medida, y dejarla escrita es lo que impide que vuelva sin ruido.
    """
    from app.serializers import serialize_node

    items, total = proveedor.list_entities(WS, limit=100)
    assert total >= 6, f"la lectura directa del proveedor devolvio {total}: arnes vacio"
    assert all(n.get("entity_id") for n in items), (
        "la proyeccion ha DEJADO de entregar `entity_id`: la identidad de las "
        "URLs vuelve a ser el identificador fisico y los enlaces guardados "
        "moriran en la proxima restauracion")
    assert all(serialize_node(n)["entity_id"] for n in items)
    # La identidad publicada ES la de dominio, no la fisica.
    assert all(n["id"] == n["entity_id"] for n in items)

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


# ===========================================================================
# 10. IDENTIDAD DURABLE: el identificador FISICO no sale a ninguna pantalla
# ===========================================================================
#
# La seccion 9 mide lo que la proyeccion ENTREGA. Esta mide lo que las
# pantallas PUBLICAN, que es lo que el operador guarda en un marcador. Son dos
# medidas distintas: una proyeccion correcta con una plantilla que pinte
# `elementId` volveria a romper los enlaces guardados, y la seccion 9 seguiria
# verde.


def test_el_element_id_no_aparece_en_las_pantallas_que_leen_del_grafo(
        app_real, proveedor, entorno, elemento, elemento_fisico):
    """Barrido negativo sobre el HTML REAL de las pantallas que leen del grafo.

    Se buscan los `elementId` de VERDAD, leidos de la base, no un patron: un
    patron podria no casar con el formato que use esta version del driver y el
    test pasaria sin haber mirado nada.

    POR QUE F Y G Y NO LOS CUATRO
    -----------------------------
    Porque un control que no puede cambiar ningun resultado no se cobra. Los
    huecos B y C no tienen NINGUNA superficie contra Neo4j -- lo demuestra en
    este mismo fichero `test_los_paneles_B_y_C_no_consultan_neo4j_en_absoluto`,
    que exige
    cero Cypher emitido durante sus peticiones. Un identificador que solo puede
    llegar del grafo no puede aparecer en una pantalla que no lee del grafo, asi
    que incluirlas aqui seria inflar la cobertura con dos casos que nunca podran
    enrojecer. La primera version de este test si las incluia y el panel C
    respondio 404: un caso que ni siquiera se renderizaba.

    Si algun dia B o C se conectaran al grafo, aquel test se pondria rojo y hay
    que ampliar TAMBIEN este barrido.
    """
    fisicos = [v for v in elemento_fisico.values() if v]
    assert len(fisicos) == len(SEMILLA), "el mapa de ids fisicos no cuajo"

    paginas: dict[str, str] = {}
    codigos: dict[str, int] = {}
    for clave, slot in (("F", SLOT_F), ("G", SLOT_G)):
        c = cliente(app_real, usuario(entorno, f"nofis_{clave}", ROL[clave]))
        r = c.get(slot.prefix, params={"workspace": WS})
        paginas[f"lista-{clave}"], codigos[f"lista-{clave}"] = r.text, r.status_code
    g = cliente(app_real, usuario(entorno, "nofis_ficha", ROL["G"]))
    for eid in ("abl", "testigo"):
        r = g.get(f"{SLOT_G.prefix}/item/{elemento[eid]}")
        paginas[f"ficha-{eid}"], codigos[f"ficha-{eid}"] = r.text, r.status_code

    # SUELO: un barrido negativo sobre paginas vacias no encuentra nada y pasa
    # sin haber mirado una sola pantalla. Se exige 200 Y cuerpo, y el codigo se
    # publica en el mensaje: la primera version de este test fallo porque le
    # faltaba el fixture `proveedor` --la app servia el proveedor por defecto,
    # no Neo4j-- y sin el codigo a la vista eso se lee como «pantalla vacia»
    # en vez de como «arnes mal cableado».
    assert all(v == 200 for v in codigos.values()), f"codigos: {codigos}"
    assert all(len(t) > 500 for t in paginas.values()), (
        f"alguna pantalla vino vacia: { {k: len(v) for k, v in paginas.items()} }")
    assert "Nodo de ablacion" in paginas["ficha-abl"], "la ficha no es la del objeto"

    culpables = {
        nombre: [f for f in fisicos if f in html]
        for nombre, html in paginas.items()
        if any(f in html for f in fisicos)
    }
    assert not culpables, (
        f"el identificador FISICO de Neo4j se publica en {culpables}: no es "
        "durable y todo enlace guardado hacia el morira en la proxima "
        "restauracion"
    )


def test_la_ficha_no_abre_por_identificador_fisico(app_real, proveedor, entorno,
                                                   elemento_fisico):
    """CONTRAPESO del test anterior. Que no se pinte no basta: no debe abrir.

    Si el `elementId` siguiera siendo una llave valida, la identidad no habria
    migrado -- solo se habria duplicado, y la puerta no durable seguiria ahi
    para cualquiera que tuviera un enlace viejo.
    """
    c = cliente(app_real, usuario(entorno, "nofis_llave", ROL["G"]))
    # Contrapeso: lo durable SI abre. Sin esta linea, «todo da 404» pasaria.
    assert c.get(f"{SLOT_G.prefix}/item/abl").status_code == 200
    assert c.get(f"{SLOT_G.prefix}/item/{elemento_fisico['abl']}").status_code == 404


# ===========================================================================
# 11. SIN IDENTIDAD DURABLE NO HAY FILA -- Y EL RECUENTO LO SABE
# ===========================================================================


def test_un_nodo_sin_entity_id_no_se_lista_y_el_TOTAL_no_lo_cuenta(
        app_real, proveedor, entorno, driver, semilla):
    """FUGA POR DIFERENCIA: el defecto que este test existe para impedir.

    Un nodo sin `entity_id` no es direccionable, asi que no se lista. Si aun
    asi entrara en el `count(n)`, el panel diria «1 de 8» mostrando 7 filas, y
    esa diferencia es informacion: revela que existe algo que no se puede ver.
    El visor ya tiene precedente de fugas por diferencia, por eso el filtro va
    en el propio Cypher y no en un recorte posterior en Python.

    Se mide con el nodo REALMENTE creado en la base, no con un doble.
    """
    antes_items, antes_total = proveedor.list_entities(WS, limit=100)
    assert antes_total >= 6, "arnes vacio: la lectura base no devolvio nada"

    with driver.session() as s:
        s.run(
            "CREATE (n:Entity $props)",
            {"props": {"canonical_name": "Huerfano sin identidad",
                       "entity_type": "LUGAR", "workspace": WS, "scope": "juego",
                       "visibility": "player", "review_status": "reviewed"}},
        )
    try:
        # SUELO: el nodo existe de verdad en la base. Sin esto, un CREATE que
        # fallara en silencio haria pasar el test por ausencia.
        with driver.session() as s:
            assert s.run(
                "MATCH (n:Entity {workspace:$ws}) WHERE n.entity_id IS NULL "
                "RETURN count(n) AS c", {"ws": WS}).single()["c"] == 1

        items, total = proveedor.list_entities(WS, limit=100)
        assert total == antes_total, (
            f"el TOTAL subio de {antes_total} a {total} por un nodo que no se "
            "lista: fuga de informacion por diferencia entre recuento y pagina"
        )
        assert len(items) == len(antes_items)
        assert total == len(items), (
            f"recuento ({total}) y pagina ({len(items)}) divergen"
        )
        assert all(n["label"] != "Huerfano sin identidad" for n in items)

        # Y en la pantalla: ni fila, ni cifra.
        c = cliente(app_real, usuario(entorno, "huerfano", ROL["G"]))
        html = G(c)
        assert "Huerfano sin identidad" not in html
        assert len(ids_g(html)) >= 5, "la lista quedo vacia: no discrimina nada"
        assert "" not in ids_g(html), "hay una fila con identidad vacia"
    finally:
        with driver.session() as s:
            s.run("MATCH (n:Entity {workspace:$ws}) WHERE n.entity_id IS NULL "
                  "DETACH DELETE n", {"ws": WS})


# ===========================================================================
# 12. LOS OTROS CUATRO CAMINOS DEL GRAFO: SIN IDENTIDAD DURABLE NO SE ENTREGA
# ===========================================================================
#
# POR QUE EXISTE ESTA SECCION
# ---------------------------
# La seccion 11 cubre `list_entities`. El proveedor tiene CUATRO caminos mas
# que filtran por identidad durable y ninguno tenia una prueba capaz de
# ponerse roja: `relations_for_entity` (extremos), `graph()/node_query`,
# `graph()/rel_query` y `search()`. Cuatro filtros de produccion sin gate es
# lo mismo que cuatro filtros que se pueden borrar sin que nadie se entere.
#
# La consecuencia del que faltaba en `graph()` esta MEDIDA, no deducida: sin
# ese filtro el huerfano llega a `GET /api/graph` con `"id": null` y
# `nodes_total` sube mientras el panel G lista uno menos. Es EXACTAMENTE la
# fuga por diferencia que la seccion 11 existe para impedir, por otra puerta.
#
# CADA TEST LLEVA SU CONTROL DE ABLACION
# --------------------------------------
# Medir «el huerfano no aparece» no demuestra nada por si solo: podria no
# aparecer porque la POLITICA lo esconde, o porque el arnes no lo creo, o
# porque la consulta no devuelve nada. Por eso cada test mide DOS VECES el
# mismo nodo, con las MISMAS propiedades, cambiando UNA sola cosa: que tenga o
# no `entity_id`. Si con `entity_id` tampoco apareciera, el test se declara
# incapaz de discriminar y falla.

NOMBRE_EXTRA = "Nodo extra de la seccion 12"
#: Workspace que NO existe en la semilla: se crea y se borra dentro del test de
#: `workspaces()`. Tiene que ser propio para que su aparicion o su ausencia en
#: el listado sea atribuible a UN solo nodo.
WS_SIN_IDENTIDAD = "contrato:sin-identidad"

#: Aristas sembradas por `_sembrar_extra(con_arista=True)`: UNA SALIENTE y UNA
#: ENTRANTE respecto de `abl`.
#:
#: POR QUE LAS DOS (superviviente MR4 de la revision independiente)
#: ---------------------------------------------------------------
#: `relations_for_entity` tiene el filtro DUPLICADO -- `out_query` e
#: `in_query` --, y esta seccion sembraba solo la saliente. Consecuencia MEDIDA:
#: mutando UNICAMENTE `in_query` la suite quedaba VERDE con el defecto puesto.
#: Un filtro que ningun test puede poner rojo es codigo borrable sin que nadie
#: se entere: exactamente lo que este carril existe para impedir. Con las dos
#: aristas, mutar `in_query` sola y mutar `out_query` sola son DOS mutaciones
#: distintas y AMBAS rojas.
ARISTAS_EXTRA = 2


def _sembrar_extra(driver, *, entity_id: str | None, con_arista: bool,
                   workspace: str = WS) -> None:
    """Crea UN nodo con propiedades identicas salvo por `entity_id`.

    Visibilidad `player` y ambito `juego`: la politica lo deja ver. Si no fuera
    visible, su ausencia no probaria nada sobre la identidad durable -- estaria
    midiendo la barrera de autorizacion, que ya tiene sus propias pruebas.
    """
    props = {"canonical_name": NOMBRE_EXTRA, "entity_type": "LUGAR",
             "workspace": workspace, "scope": "juego", "visibility": "player",
             "review_status": "reviewed", "confidence": 0.9,
             "source_document": "seccion12.pdf", "source_kind": "manual"}
    if entity_id is not None:
        props["entity_id"] = entity_id
    with driver.session() as s:
        s.run("CREATE (n:Entity $props)", {"props": props})
        if con_arista:
            s.run(
                "MATCH (a:Entity {entity_id:'abl'}), (x:Entity {canonical_name:$n}) "
                "CREATE (a)-[:VENERA {visibility:'player', workspace:$ws, "
                "scope:'juego', relation_label_es:'venera'}]->(x)",
                {"n": NOMBRE_EXTRA, "ws": workspace},
            )
            # La ENTRANTE: sin ella, `in_query` no tiene ninguna prueba capaz
            # de ponerse roja (ver ARISTAS_EXTRA).
            s.run(
                "MATCH (a:Entity {entity_id:'abl'}), (x:Entity {canonical_name:$n}) "
                "CREATE (x)-[:SIRVE_A {visibility:'player', workspace:$ws, "
                "scope:'juego', relation_label_es:'sirve a'}]->(a)",
                {"n": NOMBRE_EXTRA, "ws": workspace},
            )


def _borrar_extra(driver) -> None:
    with driver.session() as s:
        s.run("MATCH (n:Entity {canonical_name:$n}) DETACH DELETE n",
              {"n": NOMBRE_EXTRA})


@pytest.fixture
def extra(driver, semilla):
    """Deja la base como estaba pase lo que pase."""
    _borrar_extra(driver)
    yield
    _borrar_extra(driver)


def _api_graph(c) -> dict:
    r = c.get("/api/graph", params={"workspace": WS, "limit": 2000})
    assert r.status_code == 200, f"/api/graph respondio {r.status_code}"
    return r.json()


# --- MR5: `graph()` / `node_query` ------------------------------------------

def test_MR5_un_nodo_sin_entity_id_no_entra_en_el_grafo_ni_en_su_TOTAL(
        app_real, proveedor, entorno, driver, extra):
    """FUGA POR DIFERENCIA en `/api/graph`, la puerta que la seccion 11 no ve.

    Sin el filtro en `node_query`, el huerfano llega con `"id": null` y
    `nodes_total` sube mientras el panel G lista uno menos. Esa diferencia es
    informacion: revela que existe algo que no se puede ver.
    """
    c = cliente(app_real, usuario(entorno, "mr5", ROL["G"]))
    base = _api_graph(c)
    n_base = base["view"]["nodes_total"]
    filas_base = len(ids_g(G(c)))
    assert n_base >= 5 and filas_base >= 5, "arnes vacio: ni grafo ni panel"

    # --- sin identidad durable: no entra, y el TOTAL no lo cuenta
    _sembrar_extra(driver, entity_id=None, con_arista=False)
    with driver.session() as s:  # suelo: existe DE VERDAD en la base
        assert s.run("MATCH (n:Entity {canonical_name:$n}) RETURN count(n) AS c",
                     {"n": NOMBRE_EXTRA}).single()["c"] == 1

    datos = _api_graph(c)
    assert datos["view"]["nodes_total"] == n_base, (
        f"`nodes_total` subio de {n_base} a {datos['view']['nodes_total']} por un "
        "nodo que no se entrega: fuga por diferencia en /api/graph"
    )
    assert datos["view"]["nodes_shown"] == datos["view"]["nodes_total"], (
        "recuento y pagina divergen en /api/graph"
    )
    assert all(n.get("id") is not None for n in datos["nodes"]), (
        "un nodo llego con `id: null`: identidad ausente publicada como nodo"
    )
    assert all(n.get("label") != NOMBRE_EXTRA for n in datos["nodes"])
    assert len(ids_g(G(c))) == filas_base, "el panel G tampoco debe moverse"

    # --- CONTROL DE ABLACION: el MISMO nodo, con `entity_id`, SI entra.
    # Sin esta mitad, «no aparece» podria deberse a la politica o al arnes.
    _borrar_extra(driver)
    _sembrar_extra(driver, entity_id="extra12", con_arista=False)
    con_id = _api_graph(c)
    assert con_id["view"]["nodes_total"] == n_base + 1, (
        "con `entity_id` tampoco aparece: este test no sabe distinguir "
        "«excluido por falta de identidad» de «excluido por cualquier otra cosa»"
    )
    assert any(n.get("label") == NOMBRE_EXTRA for n in con_id["nodes"])


# --- MR7: `graph()` / `rel_query` -------------------------------------------

def test_MR7_una_arista_hacia_un_nodo_sin_entity_id_no_entra_en_el_grafo(
        app_real, proveedor, entorno, driver, extra):
    """Una arista cuyo extremo no es direccionable no se puede enlazar.

    Dejarla pasar produce una arista colgante que el recorte posterior tirara
    -- pero contandola antes en `edges_total`, que es la misma fuga por
    diferencia un nivel mas abajo.
    """
    c = cliente(app_real, usuario(entorno, "mr7", ROL["G"]))
    base = _api_graph(c)
    e_base = base["view"]["edges_total"]

    _sembrar_extra(driver, entity_id=None, con_arista=True)
    with driver.session() as s:  # suelo: LAS DOS aristas existen DE VERDAD
        assert s.run("MATCH (:Entity {entity_id:'abl'})-[r]-(:Entity {canonical_name:$n}) "
                     "RETURN count(r) AS c",
                     {"n": NOMBRE_EXTRA}).single()["c"] == ARISTAS_EXTRA

    datos = _api_graph(c)
    assert datos["view"]["edges_total"] == e_base, (
        f"`edges_total` subio de {e_base} a {datos['view']['edges_total']} por una "
        "arista con un extremo sin identidad"
    )
    assert datos["view"]["edges_shown"] == datos["view"]["edges_total"]
    for a in datos["edges"]:
        assert a.get("from") is not None and a.get("to") is not None, (
            f"arista con extremo nulo publicada: {a}"
        )

    # CONTROL DE ABLACION: con `entity_id`, la arista SI entra.
    _borrar_extra(driver)
    _sembrar_extra(driver, entity_id="extra12", con_arista=True)
    con_id = _api_graph(c)
    assert con_id["view"]["edges_total"] == e_base + ARISTAS_EXTRA, (
        "con `entity_id` las aristas tampoco aparecen: el test no discrimina"
    )


# --- MR6: `search()` --------------------------------------------------------

def test_MR6_la_busqueda_no_devuelve_nodos_sin_entity_id(
        app_real, proveedor, entorno, driver, extra):
    """`/api/search` publica `id`: sin identidad durable no hay resultado.

    Devolverlo seria peor que inutil: un resultado cuyo enlace no abre.
    """
    c = cliente(app_real, usuario(entorno, "mr6", ROL["G"]))

    def _buscar():
        r = c.get("/api/search", params={"workspace": WS, "q": "seccion 12"})
        assert r.status_code == 200, r.status_code
        return r.json()["results"]

    _sembrar_extra(driver, entity_id=None, con_arista=False)
    sin_id = _buscar()
    assert all(n.get("label") != NOMBRE_EXTRA for n in sin_id), (
        "la busqueda devuelve un nodo sin identidad durable: su enlace no abre"
    )
    assert all(n.get("id") for n in sin_id), "resultado con `id` vacio"

    # CONTROL DE ABLACION.
    _borrar_extra(driver)
    _sembrar_extra(driver, entity_id="extra12", con_arista=False)
    con_id = _buscar()
    assert any(n.get("label") == NOMBRE_EXTRA for n in con_id), (
        "con `entity_id` tampoco lo encuentra: el test no discrimina (revisa "
        "que el termino de busqueda case con `canonical_name`)"
    )
    assert all(n.get("entity_id") for n in con_id)


# --- MR4: `relations_for_entity()` ------------------------------------------

def test_MR4_las_relaciones_de_una_ficha_no_traen_extremos_sin_entity_id(
        app_real, proveedor, entorno, driver, extra):
    """La ficha de `abl` no puede mostrar una relacion que no lleva a ningun
    sitio: su enlace apuntaria a un identificador que no existe.

    LAS DOS DIRECCIONES, POR SEPARADO
    ---------------------------------
    `relations_for_entity` tiene DOS consultas con el MISMO filtro (`out_query`
    e `in_query`). Medir solo el total las trata como una sola defensa: mutando
    `in_query` a solas la suite quedaba VERDE (superviviente MR4 de la revision
    independiente). Aqui se afirma cada sentido contra su propia cifra, asi que
    cada consulta tiene su control negativo propio.
    """
    c = cliente(app_real, usuario(entorno, "mr4", ROL["G"]))

    def _relaciones() -> tuple[int, int]:
        salientes, entrantes = proveedor.relations_for_entity("abl")
        for a in salientes + entrantes:
            assert a.get("from") is not None and a.get("to") is not None, a
        return len(salientes), len(entrantes)

    base_out, base_in = _relaciones()

    _sembrar_extra(driver, entity_id=None, con_arista=True)
    ahora_out, ahora_in = _relaciones()
    assert ahora_out == base_out, (
        f"`out_query` paso de {base_out} a {ahora_out} salientes incluyendo una "
        "con extremo sin identidad"
    )
    assert ahora_in == base_in, (
        f"`in_query` paso de {base_in} a {ahora_in} entrantes incluyendo una "
        "con extremo sin identidad"
    )

    # Y en la pantalla: la ficha no menciona al huerfano.
    ficha = c.get(f"{SLOT_G.prefix}/item/abl")
    assert ficha.status_code == 200
    assert NOMBRE_EXTRA not in ficha.text

    # CONTROL DE ABLACION, tambien por sentido: si con `entity_id` alguno de los
    # dos no llegara, ese sentido no estaria midiendo nada.
    _borrar_extra(driver)
    _sembrar_extra(driver, entity_id="extra12", con_arista=True)
    con_out, con_in = _relaciones()
    assert con_out == base_out + 1, (
        "con `entity_id` la relacion SALIENTE tampoco llega: `out_query` no se mide"
    )
    assert con_in == base_in + 1, (
        "con `entity_id` la relacion ENTRANTE tampoco llega: `in_query` no se mide"
    )
    assert NOMBRE_EXTRA in c.get(f"{SLOT_G.prefix}/item/abl").text


# --- MR8: `workspaces()`, la quinta via -------------------------------------

def test_MR8_un_workspace_solo_con_nodos_sin_entity_id_no_se_lista(
        app_real, proveedor, entorno, driver, extra):
    """El unico camino que `PolicyFilteredProvider` NO recalcula.

    Su `workspaces()` se limita a intersectar con `allowed_workspaces`: no
    deriva de `list_entities`, asi que lo que el proveedor base liste es lo que
    llega al selector. Un workspace cuyos nodos no tienen identidad durable
    aparece y luego se abre VACIO (0 de 0) -- la misma fuga por diferencia de
    MR4-MR7, un nivel mas arriba.

    Severidad BAJA (solo se muestran workspaces ya permitidos, no cruza
    inquilinos), pero es la forma EXACTA en que se presentaria en produccion si
    el bloqueo de despliegue se confirmara: el selector lleno, todo vacio.
    """
    with driver.session() as s:  # suelo: el workspace no existe de antes
        assert s.run("MATCH (n:Entity {workspace:$w}) RETURN count(n) AS c",
                     {"w": WS_SIN_IDENTIDAD}).single()["c"] == 0

    # --- sin identidad durable: el workspace NO se lista
    _sembrar_extra(driver, entity_id=None, con_arista=False,
                   workspace=WS_SIN_IDENTIDAD)
    with driver.session() as s:  # suelo: el nodo existe DE VERDAD
        assert s.run("MATCH (n:Entity {workspace:$w}) RETURN count(n) AS c",
                     {"w": WS_SIN_IDENTIDAD}).single()["c"] == 1

    listado = proveedor.workspaces()
    assert WS in listado, "arnes vacio: no se lista ni el workspace de la semilla"
    assert WS_SIN_IDENTIDAD not in listado, (
        f"`workspaces()` ofrece {WS_SIN_IDENTIDAD!r}, que se abriria vacio: "
        "fuga por diferencia en el selector de workspaces"
    )

    # Y la razon por la que ofrecerlo seria mentir: no tiene NADA que entregar.
    nodos, total = proveedor.list_entities(WS_SIN_IDENTIDAD, limit=10, offset=0)
    assert (len(nodos), total) == (0, 0), (
        "el workspace entrega contenido: entonces este test no esta midiendo "
        "«se ofrece algo vacio», y hay que rehacerlo"
    )

    # --- CONTROL DE ABLACION: el MISMO nodo, con `entity_id`, SI lo lista.
    _borrar_extra(driver)
    _sembrar_extra(driver, entity_id="extra12", con_arista=False,
                   workspace=WS_SIN_IDENTIDAD)
    con_id = proveedor.workspaces()
    assert WS_SIN_IDENTIDAD in con_id, (
        "con `entity_id` tampoco se lista: este test no sabe distinguir "
        "«excluido por falta de identidad» de «excluido por cualquier otra cosa»"
    )


# --- EXCEPCION DECLARADA: el `id` de arista en JSON -------------------------

def test_EXCEPCION_el_id_de_arista_en_api_graph_SI_es_el_element_id(
        app_real, proveedor, entorno, elemento_fisico):
    """EXCEPCION EXPLICITA, no un olvido de la seccion 10.

    La seccion 10 barre el HTML de F y G. `GET /api/graph` publica ademas
    `edges[].id`, y ese valor SI es el `elementId` de la relacion. Se declara
    aqui, con su razon, en vez de dejarlo fuera del barrido sin decirlo:

    * las relaciones NO tienen identificador durable en el modelo V3
      (`writer/cypher.py::create_relation` no escribe `relation_id` ni
      `assertion_id`; el objeto durable de un hecho es el nodo `:V3Assertion`);
    * ningun `href` del visor usa el id de una arista: los enlaces salen de
      `from`/`to`, y esos dos SI son durables -- lo afirma la linea de abajo;
    * es un valor de un solo viaje para que vis-network distinga aristas dentro
      de la misma respuesta. No se marca, no se enlaza, no se persiste.

    Si algun dia el modelo diera identidad durable a las relaciones, este test
    se pone rojo y hay que cerrar tambien esta puerta.
    """
    c = cliente(app_real, usuario(entorno, "exc_json", ROL["G"]))
    datos = _api_graph(c)
    assert datos["edges"], "sin aristas no se esta midiendo nada"

    # Lo que SI es durable en una arista: sus extremos.
    fisicos = set(elemento_fisico.values())
    for a in datos["edges"]:
        assert a["from"] not in fisicos and a["to"] not in fisicos, (
            f"un EXTREMO de arista viaja como elementId: {a}")

    # Y la excepcion, afirmada: el `id` de arista es fisico y se acepta.
    assert any(re.match(r"^\d+:[0-9a-fA-F-]{36}:\d+$", str(a.get("id")))
               for a in datos["edges"]), (
        "el `id` de arista ha dejado de ser el elementId. Si es porque el "
        "modelo ya da identidad durable a las relaciones, ACTUALIZA esta "
        "excepcion y haz que viaje ese identificador")

    # Ningun NODO, en cambio, admite excepcion.
    for n in datos["nodes"]:
        assert n["id"] not in fisicos, f"un nodo viaja como elementId: {n['id']}"


# ===========================================================================
# 2-bis. LA LISTA DE CAMPOS SE DERIVA, NO SE ESCRIBE (carril 4 de V3.1)
#
# EL HUECO QUE ESTO CIERRA
# ------------------------
# Sobre `main=aaf9695`, `aliases` y `updated_at` de `_node_to_dict` los
# consumen las plantillas y NO aparecian en `ABLACIONES` ni en ninguna otra
# prueba: quitarlos de la proyeccion dejaba todo verde. No fue un descuido
# puntual, fue el metodo: la tabla `ABLACIONES` era una lista DOCUMENTAL
# mantenida a mano, y una lista a mano se queda corta el dia que alguien pinta
# un campo nuevo en una plantilla.
#
# Aqui la lista de campos a proteger se DERIVA de codigo ejecutable, en tres
# saltos, cada uno leido con AST (o con el AST de Jinja), nunca con `grep`:
#
#   1. QUE PLANTILLAS PINTAN NODOS. Se buscan las funciones de `viewer/app`
#      que llaman a `serialize_node` Y renderizan una plantilla, y se resuelve
#      el nombre de esa plantilla -- incluso cuando no es una cadena literal
#      (`SLOT.template`, `ITEM_TEMPLATE`), importando el modulo y leyendo el
#      valor real. Asi el panel G entra por su contrato del chasis y no porque
#      alguien escriba su nombre aqui.
#   2. QUE ATRIBUTOS CONSUME CADA PLANTILLA. Se parsea la plantilla con el
#      parser de Jinja y se recogen los `Getattr`/`Getitem`. `{{ entity.foo }}`
#      cuenta; un comentario que mencione `foo`, no.
#   3. DE QUE PROPIEDAD DE NEO4J SALE CADA ATRIBUTO. Se compone el diccionario
#      devuelto por `serialize_node` (atributo -> claves del nodo crudo) con el
#      devuelto por `_node_to_dict` (clave -> `props.get("...")`). El bloque
#      `technical` se expande por su constante real (`_NODE_TECHNICAL_FIELDS`),
#      que es como llegan `updated_at` y compania a la pantalla.
#
# EL COSTE, DECLARADO Y DELIBERADO
# --------------------------------
# La proteccion NO crece sola: un campo nuevo consumido por una plantilla pone
# ROJO `test_la_lista_de_campos_se_DERIVA_de_las_plantillas` hasta que alguien
# lo CLASIFICA en `CAMPOS_CLASIFICADOS`. Se elige asi porque una ablacion no es
# solo un nombre: necesita una semilla con valor de ancla, una superficie donde
# observarse y un DEGRADADO DECLARADO. Generar eso automaticamente produciria
# ablaciones que «pasan» sin medir nada -- exactamente la clase de verde vacio
# que este fichero existe para impedir. El precio es una parada; la alternativa
# era volver a la lista a mano.
# ===========================================================================

VIEWER_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = VIEWER_ROOT / "app"
PLANTILLAS_DIR = APP_DIR / "templates"


def _modulo_de(ruta: Path):
    """El modulo YA IMPORTADO que corresponde a ese fichero.

    Hace falta para resolver `SLOT.template` e `ITEM_TEMPLATE`: son valores,
    no literales, y leerlos del texto seria adivinar.
    """
    punteado = ".".join(ruta.relative_to(VIEWER_ROOT).with_suffix("").parts)
    try:
        return importlib.import_module(punteado)
    except Exception:
        return None


def _nombre_de_plantilla(nodo, modulo):
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) \
       and nodo.value.endswith(".html"):
        return nodo.value
    if modulo is None:
        return None
    if isinstance(nodo, ast.Name):
        v = getattr(modulo, nodo.id, None)
        return v if isinstance(v, str) and v.endswith(".html") else None
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        base = getattr(modulo, nodo.value.id, None)
        v = getattr(base, nodo.attr, None)
        return v if isinstance(v, str) and v.endswith(".html") else None
    return None


def _llama_a(fn, nombre: str) -> bool:
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
               and c.func.id == nombre for c in ast.walk(fn))


def plantillas_que_pintan_nodos() -> dict[str, set[str]]:
    """``plantilla -> {fichero::funcion}`` que la renderiza pintando un nodo."""
    salida: dict[str, set[str]] = {}
    for py in sorted(APP_DIR.rglob("*.py")):
        texto = py.read_text(encoding="utf-8")
        if "serialize_node" not in texto:
            continue
        try:
            arbol = ast.parse(texto)
        except SyntaxError:
            continue
        modulo = None
        for fn in ast.walk(arbol):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _llama_a(fn, "serialize_node"):
                continue
            if modulo is None:
                modulo = _modulo_de(py)
            for c in ast.walk(fn):
                if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and c.func.attr == "TemplateResponse"):
                    continue
                for arg in list(c.args) + [k.value for k in c.keywords]:
                    n = _nombre_de_plantilla(arg, modulo)
                    if n and (PLANTILLAS_DIR / n).is_file():
                        salida.setdefault(n, set()).add(f"{py.name}::{fn.name}")
    return salida


def atributos_de_plantilla(plantilla: str) -> set[str]:
    """Atributos que la plantilla CONSUME, por el AST de Jinja."""
    arbol = jinja2.Environment().parse(
        (PLANTILLAS_DIR / plantilla).read_text(encoding="utf-8"))
    out = set()
    for g in arbol.find_all(JN.Getattr):
        out.add(g.attr)
    for g in arbol.find_all(JN.Getitem):
        if isinstance(g.arg, JN.Const) and isinstance(g.arg.value, str):
            out.add(g.arg.value)
    return out


def _lecturas(expr, var: str) -> set[str]:
    """`var.get("x")` y `var["x"]` dentro de una expresion."""
    out = set()
    for c in ast.walk(expr):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
           and c.func.attr == "get" and isinstance(c.func.value, ast.Name) \
           and c.func.value.id == var and c.args and isinstance(c.args[0], ast.Constant):
            out.add(c.args[0].value)
        if isinstance(c, ast.Subscript) and isinstance(c.value, ast.Name) \
           and c.value.id == var and isinstance(c.slice, ast.Constant):
            out.add(c.slice.value)
    return out


def _dict_devuelto(ruta: Path, funcion: str, var: str) -> dict[str, set[str]]:
    """``clave del dict devuelto -> claves de entrada que la alimentan``.

    Se resuelven tambien las variables locales (`technical`, `entity_type`,
    `name`, `confidence`) y las constantes de modulo en MAYUSCULAS que
    contengan cadenas: asi `technical` se expande por `_NODE_TECHNICAL_FIELDS`
    de verdad y no por una copia escrita aqui.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arbol)
              if isinstance(n, ast.FunctionDef) and n.name == funcion)
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.Dict), (
        f"{funcion} ya no devuelve un diccionario literal: la derivacion no "
        f"puede leerlo y esta prueba tiene que detenerse, no adivinar")
    modulo = _modulo_de(ruta)
    locales: dict[str, set[str]] = {}
    for n in fn.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            leidas = _lecturas(n.value, var)
            for c in ast.walk(n.value):
                if isinstance(c, ast.Name) and c.id.upper() == c.id:
                    v = getattr(modulo, c.id, None)
                    if isinstance(v, (tuple, list, set, frozenset)) and \
                       all(isinstance(x, str) for x in v):
                        leidas |= set(v)
            locales[n.targets[0].id] = leidas
    mapa: dict[str, set[str]] = {}
    for k, v in zip(ret.value.keys, ret.value.values):
        leidas = _lecturas(v, var)
        for c in ast.walk(v):
            if isinstance(c, ast.Name) and c.id in locales:
                leidas |= locales[c.id]
        mapa[k.value] = leidas
    return mapa


def _propiedades_desde(pares) -> dict[str, set[tuple[str, str]]]:
    """``propiedad de Neo4j -> {(plantilla, atributo) que la consume}``.

    Se separa de `propiedades_neo4j_consumidas` para poder CALIBRAR la
    derivacion: se le pueden pasar pares inventados y comprobar que la cadena
    de composicion los sigue hasta la propiedad.
    """
    ser = _dict_devuelto(APP_DIR / "serializers.py", "serialize_node", "node")
    prov = _dict_devuelto(APP_DIR / "providers" / "neo4j_provider.py",
                          "_node_to_dict", "props")
    evidencia: dict[str, set[tuple[str, str]]] = {}
    for plantilla, attr in pares:
        for clave in ser.get(attr, ()):
            for prop in prov.get(clave, ()):
                evidencia.setdefault(prop, set()).add((plantilla, attr))
    return evidencia


def propiedades_neo4j_consumidas() -> dict[str, set[tuple[str, str]]]:
    return _propiedades_desde(
        (plantilla, attr)
        for plantilla in plantillas_que_pintan_nodos()
        for attr in atributos_de_plantilla(plantilla)
    )


# ---------------------------------------------------------------------------
# Ablacion en la FICHA `/entity/{id}` (`entity.html`)
#
# Los ocho campos de aqui NO se ven en el panel G ni en el F: viven en la ficha
# de solo lectura. `aliases` y `updated_at` son los dos supervivientes medidos;
# los otros seis entraron con ellos porque la derivacion los senala y ninguno
# tenia ablacion.
#
# `ancla` es el texto EXACTO que el valor produce en el HTML. Ninguno coincide
# con el respaldo de la plantilla (`'-'` para alias y paginas, la desaparicion
# de la clave para el bloque tecnico), que es la condicion que hace observable
# la ablacion.
# ---------------------------------------------------------------------------
#: (campo, ancla en el HTML, degradado declarado)
ABLACIONES_FICHA = (
    ("aliases", "Alias unico de ablacion", "el campo Alias cae al guion"),
    ("source_pages", "4242", "el campo Paginas cae al guion"),
    ("description", TEXTO_DESCRIPCION, "el parrafo de descripcion desaparece"),
    ("created_at", "2019-01-01T00:00:00Z-creado-abl", "sale del bloque tecnico"),
    ("updated_at", "2020-02-02T00:00:00Z-actualizado-abl", "sale del bloque tecnico"),
    ("extractor_version", "extractor-9.9.9-abl", "sale del bloque tecnico"),
    ("prompt_version", "prompt-8.8.8-abl", "sale del bloque tecnico"),
    ("source_hash", "hash-de-ablacion-7777", "sale del bloque tecnico"),
)

#: Valor sembrado de cada campo de la ficha, para poder RESTAURARLO. Sale de
#: la propia semilla, no de una segunda copia escrita a mano: si la semilla
#: cambiara, la restauracion la sigue.
_ABL = next(n for n in SEMILLA if n["entity_id"] == "abl")
VALOR_SEMBRADO = {campo: _ABL[campo] for campo, _, _ in ABLACIONES_FICHA}


#: LA CLASIFICACION. Cada propiedad de Neo4j que las plantillas consumen dice
#: DONDE se ablaciona. No es la lista de campos --esa se deriva-- sino la
#: respuesta a «¿como se mide este?», que es lo unico que no se puede derivar.
CAMPOS_CLASIFICADOS: dict[str, str] = {
    # Panel G (lista), tabla `ABLACIONES`.
    "canonical_name": "ABLACIONES:G",
    "entity_type": "ABLACIONES:G",
    "confidence": "ABLACIONES:G",
    "review_status": "ABLACIONES:G",
    "source_document": "ABLACIONES:G",
    "visibility": "ABLACIONES:G",
    "workspace": "ABLACIONES:G",
    # Panel F (fuentes), misma tabla.
    "source_kind": "ABLACIONES:F",
    # Ficha `/entity/{id}`, tabla `ABLACIONES_FICHA`.
    "aliases": "ABLACIONES_FICHA",
    "source_pages": "ABLACIONES_FICHA",
    "description": "ABLACIONES_FICHA",
    "created_at": "ABLACIONES_FICHA",
    "updated_at": "ABLACIONES_FICHA",
    "extractor_version": "ABLACIONES_FICHA",
    "prompt_version": "ABLACIONES_FICHA",
    "source_hash": "ABLACIONES_FICHA",
    # Dos que no caben en ninguna tabla y tienen prueba propia, NOMBRADA:
    # `display_name` no esta sembrado (el respaldo es `canonical_name`), asi
    # que su ablacion necesita ponerlo primero; y quitar `entity_id` deja al
    # nodo sin la clave por la que se le busca, asi que hay que restaurarlo
    # por otra.
    "display_name": "test:test_ablacion_de_display_name_devuelve_el_nombre_canonico",
    "entity_id": "test:test_ablacion_de_entity_id_retira_la_entidad_de_los_paneles",
}


def _ficha(app_real, entorno, elid: str, nombre_usuario: str) -> str:
    """La ficha `/entity/{id}` renderizada, que es donde se pintan estos ocho."""
    c = cliente(app_real, usuario(entorno, nombre_usuario, ROL["G"]))
    r = c.get(f"/entity/{elid}")
    assert r.status_code == 200, (
        f"la ficha /entity/{elid} respondio {r.status_code}: sin observacion no "
        f"hay ablacion que medir (esta suite no puede pasar por no mirar)")
    return r.text


def test_la_ficha_de_solo_lectura_es_una_superficie_OBSERVABLE(app_real, proveedor,
                                                               entorno, elemento):
    """SUELO de la seccion. Antes de ablacionar nada: las ocho anclas estan, y
    cada una aparece UNA SOLA VEZ.

    La unicidad no es cosmetica: si dos campos compartieran ancla, el rojo de
    uno seria el rojo del otro y uno de los dos estaria sin cubrir sin que se
    notara. Es la misma regla que el arnes de mutaciones impone a sus anclas.
    """
    html = _ficha(app_real, entorno, elemento["abl"], "ficha_suelo")
    anclas = [ancla for _, ancla, _ in ABLACIONES_FICHA]
    assert len(set(anclas)) == len(anclas), "hay anclas repetidas en ABLACIONES_FICHA"
    for campo, ancla, _ in ABLACIONES_FICHA:
        assert html.count(ancla) == 1, (
            f"el ancla de `{campo}` aparece {html.count(ancla)} veces en la ficha; "
            f"tiene que aparecer exactamente 1 para que su rojo sea suyo")


@pytest.mark.parametrize("campo,ancla,degradado", ABLACIONES_FICHA,
                         ids=[c for c, _, _ in ABLACIONES_FICHA])
def test_quitar_un_campo_que_la_FICHA_consume_pone_algo_ROJO(
    driver, app_real, proveedor, entorno, elemento, campo, ancla, degradado
):
    """CALIBRACION, una por campo, sobre `entity.html`.

    Se exige (a) que el ancla del campo DESAPAREZCA, (b) que la ficha siga
    respondiendo (el degradado es una ausencia declarada, no un 500) y (c) que
    las anclas de los OTROS SIETE sigan intactas: sin eso, un cambio global
    --la ficha en blanco, un error, otra plantilla-- se cobraria como rojo de
    este campo. Es la comprobacion de que ningun rojo es PRESTADO.
    """
    elid = elemento["abl"]
    antes = _ficha(app_real, entorno, elid, f"fic_{campo}_antes")
    assert ancla in antes, f"el caso `{campo}` parte sin su ancla: no mide nada"

    try:
        _quitar(driver, "abl", campo)
        despues = _ficha(app_real, entorno, elid, f"fic_{campo}_despues")
    finally:
        _poner(driver, "abl", campo, VALOR_SEMBRADO[campo])

    assert ancla not in despues, (
        f"ROJO NO PRODUCIDO: quitar `{campo}` de Neo4j no borra su valor de la "
        f"ficha. El contrato para ese campo seria DECORATIVO. Degradado "
        f"declarado: {degradado}")
    # (b) la ficha sigue viva y sigue siendo la del mismo objeto.
    assert "Nodo de ablacion" in despues, (
        f"quitar `{campo}` no degrado la ficha: la tumbo entera")
    # (c) ninguna otra ancla se movio -> el rojo es de este campo y de nadie mas.
    for otro, ancla_otro, _ in ABLACIONES_FICHA:
        if otro == campo:
            continue
        assert ancla_otro in despues, (
            f"quitar `{campo}` tambien borro el ancla de `{otro}`: el rojo de "
            f"`{otro}` podria estar PRESTADO de este")

    restaurada = _ficha(app_real, entorno, elid, f"fic_{campo}_restaurada")
    assert ancla in restaurada, f"la restauracion de `{campo}` no volvio a dejar el dato"


def test_ablacion_de_display_name_devuelve_el_nombre_canonico(driver, app_real,
                                                              proveedor, entorno,
                                                              elemento):
    """`display_name` gana a `canonical_name` en `serialize_node`. Aqui se mide
    ese orden, que es la razon por la que este campo no cabe en las tablas: hay
    que PONERLO primero (la semilla no lo trae, justo para que la ablacion de
    `canonical_name` sea observable) y quitarlo despues.

    DEGRADADO DECLARADO: no es «no disponible». Es el nombre canonico. Se exige
    ese valor exacto, no un cambio cualquiera.
    """
    elid = elemento["abl"]
    mostrado = "Nombre mostrado de ablacion"
    try:
        _poner(driver, "abl", "display_name", mostrado)
        con = _ficha(app_real, entorno, elid, "dn_con")
        assert mostrado in con, (
            "`display_name` no llega a la pantalla: el orden de respaldo de "
            "`serialize_node` no se esta ejerciendo y la ablacion no mediria nada")
        _quitar(driver, "abl", "display_name")
        sin = _ficha(app_real, entorno, elid, "dn_sin")
    finally:
        _quitar(driver, "abl", "display_name")

    assert mostrado not in sin, "quitar `display_name` no cambio el nombre pintado"
    assert "Nodo de ablacion" in sin, (
        "quitar `display_name` no cayo al `canonical_name`: la ficha se quedo "
        "sin nombre, que es un degradado DISTINTO del declarado")


def test_ablacion_de_entity_id_retira_la_entidad_de_los_paneles(driver, app_real,
                                                                proveedor, entorno,
                                                                elemento):
    """`entity_id` es la identidad durable: sin ella la entidad no es
    direccionable y las consultas la excluyen (`_CON_IDENTIDAD_DURABLE`).

    No cabe en la tabla porque `_quitar`/`_poner` buscan el nodo POR
    `entity_id`: al quitarlo se pierde el asa. Aqui se busca y se restaura por
    `canonical_name`, que en la semilla es unico.

    DEGRADADO DECLARADO: fila ausente en el panel G y ficha inaccesible. Fallo
    CERRADO: nada de servir el nodo con un identificador fisico prestado.
    """
    elid = elemento["abl"]
    obs = _obs_g(app_real, entorno, elid, "eid_antes")
    fila_antes, _ = obs()
    assert fila_antes != "(FILA AUSENTE)", "el caso parte de una observacion vacia"

    try:
        with driver.session() as s:
            s.run("MATCH (n:Entity {canonical_name:'Nodo de ablacion'}) REMOVE n.entity_id")
        fila_despues, _ = _obs_g(app_real, entorno, elid, "eid_despues")()
        c = cliente(app_real, usuario(entorno, "eid_ficha", ROL["G"]))
        r = c.get(f"/entity/{elid}")
    finally:
        with driver.session() as s:
            s.run("MATCH (n:Entity {canonical_name:'Nodo de ablacion'}) "
                  "SET n.entity_id = 'abl'")

    assert fila_despues == "(FILA AUSENTE)", (
        f"un nodo SIN identidad durable sigue listado en el panel G: {fila_despues[:200]}")
    assert r.status_code == 404, (
        f"la ficha de un nodo sin `entity_id` respondio {r.status_code}: tenia que "
        f"ser indistinguible de inexistente")

    fila_restaurada, _ = _obs_g(app_real, entorno, elid, "eid_restaurada")()
    assert fila_restaurada == fila_antes, "la restauracion no dejo el panel igual"


# ---------------------------------------------------------------------------
# La guarda: la lista DERIVADA y la CLASIFICACION tienen que coincidir
# ---------------------------------------------------------------------------

def test_la_lista_de_campos_se_DERIVA_de_las_plantillas():
    """LA PIEZA CENTRAL DEL CARRIL. Si una plantilla empieza a consumir un
    campo nuevo, esto se pone ROJO hasta que alguien decida COMO se ablaciona.

    Y al reves: si un campo deja de consumirse, sobra de la clasificacion y
    tambien enrojece -- una ablacion de algo que ya nadie pinta es una prueba
    que mide una pantalla que no existe.
    """
    derivadas = propiedades_neo4j_consumidas()
    assert derivadas, (
        "la derivacion no encontro NI UN campo: la cadena plantilla -> "
        "serializador -> proveedor se ha roto y esta guarda estaria muda")

    faltan = set(derivadas) - set(CAMPOS_CLASIFICADOS)
    assert not faltan, (
        "campos que una plantilla CONSUME y nadie ablaciona: "
        + ", ".join(f"{c} (lo pinta {sorted(derivadas[c])[0]})" for c in sorted(faltan))
        + ". Clasificalos en CAMPOS_CLASIFICADOS y anadeles su ablacion: "
        "esta parada es el coste declarado de no mantener la lista a mano.")

    sobran = set(CAMPOS_CLASIFICADOS) - set(derivadas)
    assert not sobran, (
        f"campos clasificados que ninguna plantilla consume ya: {sorted(sobran)}")


def test_cada_campo_clasificado_tiene_su_ablacion_DE_VERDAD():
    """La clasificacion no puede ser una etiqueta: cada campo tiene que
    aparecer donde dice aparecer. Sin esto, poner `"loquesea": "ABLACIONES:G"`
    silenciaria la guarda de arriba sin medir nada.
    """
    en_g = {c for c, _, p, _ in ABLACIONES if p == "G"}
    en_f = {c for c, _, p, _ in ABLACIONES if p == "F"}
    en_ficha = {c for c, _, _ in ABLACIONES_FICHA}

    for campo, donde in sorted(CAMPOS_CLASIFICADOS.items()):
        if donde == "ABLACIONES:G":
            assert campo in en_g, f"`{campo}` se declara en el panel G y no esta en ABLACIONES"
        elif donde == "ABLACIONES:F":
            assert campo in en_f, f"`{campo}` se declara en el panel F y no esta en ABLACIONES"
        elif donde == "ABLACIONES_FICHA":
            assert campo in en_ficha, f"`{campo}` no esta en ABLACIONES_FICHA"
        elif donde.startswith("test:"):
            nombre = donde.split(":", 1)[1]
            fn = globals().get(nombre)
            assert callable(fn), (
                f"`{campo}` dice medirse en `{nombre}`, que no existe en este modulo")
        else:
            raise AssertionError(f"clasificacion desconocida para `{campo}`: {donde!r}")


def test_la_derivacion_MUERDE():
    """CALIBRACION DE LA DERIVACION. Un derivador que no reacciona a un campo
    nuevo seria la lista a mano otra vez, con mas lineas.

    Se le pasa un par inventado --una plantilla ficticia que consumiria
    `knowledge_layer`, que HOY ninguna pinta (`entity.html` lo omite a
    proposito)-- y se exige (a) que la cadena lo siga hasta la propiedad de
    Neo4j y (b) que ese campo NO este clasificado, es decir, que la guarda de
    arriba se habria puesto roja.
    """
    inventado = _propiedades_desde([("ficticia.html", "knowledge_layer_label")])
    assert "knowledge_layer" in inventado, (
        "la composicion serializador->proveedor no sigue un atributo nuevo: la "
        "derivacion no derivaria nada")
    assert "knowledge_layer" not in CAMPOS_CLASIFICADOS, (
        "el ejemplo de calibracion ya esta clasificado; hace falta otro campo "
        "consumible que hoy no se pinte")

    derivadas = dict(propiedades_neo4j_consumidas())
    derivadas.update(inventado)
    faltan = set(derivadas) - set(CAMPOS_CLASIFICADOS)
    assert faltan == {"knowledge_layer"}, (
        f"con un campo nuevo consumido, la guarda tendria que senalarlo a el y "
        f"solo a el; senala {sorted(faltan)}")


def test_las_plantillas_que_pintan_nodos_se_ENCUENTRAN_solas():
    """Suelo de la derivacion. Si el descubrimiento devolviera un conjunto
    vacio --o perdiera el panel G, que llega por `SLOT.template` y no por una
    cadena literal-- la lista derivada saldria corta y la guarda pasaria en
    verde sin cubrir nada.
    """
    encontradas = plantillas_que_pintan_nodos()
    assert SLOT_G.template in encontradas, (
        "el panel G no se descubrio: su plantilla llega por el contrato del "
        "chasis (`SLOT.template`), no como literal, y resolverla es justo lo "
        "que hace que este carril no sea una lista escrita a mano")
    for esperada in ("entity.html", "entities.html", "chassis/entities_item.html"):
        assert esperada in encontradas, f"no se descubrio {esperada}"
    # Y ninguna de ellas se descubre «porque si»: cada una viene de una funcion
    # que llama a `serialize_node`.
    for plantilla, funciones in encontradas.items():
        assert funciones, f"{plantilla} descubierta sin funcion que la pinte"

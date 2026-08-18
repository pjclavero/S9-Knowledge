"""INTEGRACION REAL contra Neo4j efimero: Neo4j -> serializador -> politica.

Este es el test que faltaba, y su ausencia es la causa directa del defecto que
encontro la revision independiente. Todo lo demas se probaba con diccionarios
fabricados a mano, asi que el motor de politicas estaba perfectamente cubierto
y la frontera por la que los datos ENTRAN al motor no lo estaba en absoluto.
Resultado: 675 pruebas verdes conviviendo con un aislamiento entre partidas que
no llegaba a evaluarse nunca sobre datos reales.

Aqui se escribe en una base de verdad, se lee con el proveedor de verdad y se
decide con la politica de verdad. Si una propiedad se pierde entre Neo4j y el
motor --en el Cypher, en el driver o en el serializador-- estos tests lo ven.

Necesita un Neo4j accesible. Se omite entero si no lo hay (`NEO4J_TEST_URI`);
en CI lo levanta un contenedor de servicio. Nunca apunta a produccion: escribe
y borra, asi que exige una base marcada explicitamente como desechable.
"""
from __future__ import annotations

import os

import pytest

from app.authz.filtered_provider import PolicyFilteredProvider
from app.policies.models import ViewerContext

URI = os.environ.get("NEO4J_TEST_URI")
USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not URI or not PASSWORD,
    reason="sin Neo4j efimero (define NEO4J_TEST_URI y NEO4J_TEST_PASSWORD)",
)

WS = "juego:integracion"
OTRO_WS = "juego:ajeno"
P_A = "partida:alfa"
P_B = "partida:beta"

# Sembrado: dos partidas del mismo juego, lore compartido declarado, un nodo de
# otro workspace, y datos deliberadamente corruptos para comprobar que denegar
# no es lo mismo que reventar.
SEMILLA = [
    dict(id="lore", ws=WS, scope="juego", pid=None, vis="player"),
    # 7a ronda (H6-1): el contenido de partida DEBE declarar desde que sesion
    # puede revelarse. Estos cuatro se sembraban sin declararla y ahora el motor
    # los deniega -- correctamente. Solo lo detecto el job de CI, porque estas 19
    # pruebas se saltan sin `NEO4J_TEST_URI` y el septimo dictamen se emitio sin
    # Neo4j: es la limitacion que el propio revisor declaro, materializada.
    dict(id="a_player", ws=WS, scope="partida", pid=P_A, vis="player", desde=0),
    dict(id="a_secret", ws=WS, scope="partida", pid=P_A, vis="secret", desde=0),
    dict(id="b_player", ws=WS, scope="partida", pid=P_B, vis="player", desde=0),
    dict(id="b_secret", ws=WS, scope="partida", pid=P_B, vis="secret", desde=0),
    dict(id="ajeno", ws=OTRO_WS, scope="juego", pid=None, vis="player"),
    dict(id="conocido", ws=WS, scope="juego", pid=None, vis="secret",
         known_by=["pc:ana"]),
    # --- corruptos: cada uno debe DENEGAR, y ninguno debe provocar un 500.
    dict(id="corrupto_sin_scope", ws=WS, scope=None, pid=None, vis="player"),
    dict(id="corrupto_vis", ws=WS, scope="juego", pid=None, vis="publico"),
    dict(id="corrupto_known_by", ws=WS, scope="juego", pid=None, vis="secret",
         known_by="pc:ana"),          # cadena, no lista
    dict(id="corrupto_sin_ws", ws=None, scope="juego", pid=None, vis="player"),
    # T2 -- sesion de REVELACION, sobre datos reales de Neo4j.
    dict(id="rev_0", ws=WS, scope="partida", pid=P_A, vis="player", desde=0),
    dict(id="rev_3", ws=WS, scope="partida", pid=P_A, vis="player", desde=3),
    dict(id="rev_8", ws=WS, scope="partida", pid=P_A, vis="player", desde=8),
    # Revelado en la 8 y ya conocido por el PJ: `known_by` NO debe saltarse el
    # tope, o "ver como PJ hasta la sesion 5" se convierte en un spoiler.
    dict(id="rev_8_conocido", ws=WS, scope="partida", pid=P_A, vis="player",
         desde=8, known_by=["pc:ana"]),
    dict(id="rev_corrupta", ws=WS, scope="partida", pid=P_A, vis="player",
         desde="tres"),
    # Espejo en la partida B. No lo usa ninguna prueba de T2: existe para que el
    # invariante de conteos simetricos entre partidas siga significando algo. Si
    # solo se sembrara un lado, ese test fallaria por construccion del fixture y
    # no por una fuga, que es justo lo que un invariante no debe hacer.
    dict(id="rev_b_0", ws=WS, scope="partida", pid=P_B, vis="player", desde=0),
    dict(id="rev_b_3", ws=WS, scope="partida", pid=P_B, vis="player", desde=3),
    dict(id="rev_b_8", ws=WS, scope="partida", pid=P_B, vis="player", desde=8),
    dict(id="rev_b_8_conocido", ws=WS, scope="partida", pid=P_B, vis="player",
         desde=8, known_by=["pc:ana"]),
    dict(id="rev_b_corrupta", ws=WS, scope="partida", pid=P_B, vis="player",
         desde="tres"),
]


def _ctx(partida=None, **over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_partida=partida,
        allowed_partida_ids=frozenset({partida}) if partida else frozenset(),
        session_public=True,
        # 7a ronda: un tope NO DECLARADO deniega todo lo que declare sesion de
        # revelacion (antes se saltaba la regla entera). Este contexto base
        # existe para probar el AISLAMIENTO entre partidas, no la progresion de
        # campana, asi que declara un tope alto explicito. Los casos que si
        # prueban la barrera historica lo sobreescriben con `_jugador_a(tope)`.
        max_visible_session=1000,
        # LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14): la capa juego exige llave
        # propia y un lector AUTENTICADO la tiene. Sin ella estos casos --que
        # miden aislamiento entre partidas y `known_by` contra Neo4j de verdad--
        # se pondrian rojos por `lore_not_allowed`, es decir, por el motivo
        # equivocado.
        can_view_lore=True,
    )
    base.update(over)
    return ViewerContext(**base)


@pytest.fixture(scope="module")
def driver():
    from neo4j import GraphDatabase

    drv = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    drv.verify_connectivity()
    yield drv
    drv.close()


@pytest.fixture(scope="module")
def base(driver):
    """Siembra la base efimera y la deja limpia al terminar."""
    with driver.session() as s:
        s.run("MATCH (n:Entity) WHERE n.workspace IN $ws DETACH DELETE n",
              {"ws": [WS, OTRO_WS]})
        for n in SEMILLA:
            props = {"entity_id": n["id"], "canonical_name": n["id"],
                     "entity_type": "Test", "visibility": n["vis"]}
            for clave, valor in (("workspace", n["ws"]), ("scope", n["scope"]),
                                 ("partida_id", n["pid"]), ("known_by", n.get("known_by")),
                                 ("known_from_session", n.get("desde"))):
                if valor is not None:
                    props[clave] = valor
            s.run("CREATE (n:Entity $props)", {"props": props})
        # Aristas: una interna de A, y una que cruza hacia el secreto de A.
        s.run(
            "MATCH (a:Entity {entity_id:'a_player'}), (l:Entity {entity_id:'lore'}) "
            "CREATE (a)-[:VENERA {visibility:'player', workspace:$ws, scope:'partida', known_from_session:0, "
            "partida_id:$p, relation_label_es:'venera'}]->(l)", {"ws": WS, "p": P_A})
        s.run(
            "MATCH (a:Entity {entity_id:'a_player'}), (x:Entity {entity_id:'a_secret'}) "
            "CREATE (a)-[:OCULTA {visibility:'secret', workspace:$ws, scope:'partida', known_from_session:0, "
            "partida_id:$p, relation_label_es:'oculta'}]->(x)", {"ws": WS, "p": P_A})

    from app.providers.neo4j_provider import Neo4jGraphProvider

    proveedor = Neo4jGraphProvider(URI, USER, PASSWORD)
    yield proveedor
    with driver.session() as s:
        s.run("MATCH (n:Entity) WHERE n.workspace IN $ws DETACH DELETE n",
              {"ws": [WS, OTRO_WS]})


def _ids(items):
    return {i.get("id") for i in items}


def _nombres(items):
    return {i.get("label") for i in items}


# --- aislamiento entre partidas, atravesando Neo4j de verdad -----------------

def test_una_partida_no_ve_el_material_de_la_otra(base):
    prov = PolicyFilteredProvider(base, _ctx(P_A))
    items, _ = prov.list_entities(WS, limit=1000)
    nombres = _nombres(items)
    assert "a_player" in nombres
    assert "b_player" not in nombres, "FUGA entre partidas en el camino real"
    assert "b_secret" not in nombres


def test_el_conteo_no_revela_material_de_otra_partida(base):
    a, _ = PolicyFilteredProvider(base, _ctx(P_A)).counts(WS)
    b, _ = PolicyFilteredProvider(base, _ctx(P_B)).counts(WS)
    assert a == b, "conteos asimetricos: uno de los dos ve algo que no le toca"


def test_la_busqueda_tampoco_cruza_partidas(base):
    prov = PolicyFilteredProvider(base, _ctx(P_A))
    assert "b_player" not in _nombres(prov.search(WS, "b_"))


def test_el_acceso_por_id_no_cruza_workspace(base):
    """La consulta va acotada por workspace en el propio Cypher, ademas del filtro."""
    prov = PolicyFilteredProvider(base, _ctx(P_A))
    ajeno = [n for n in base.list_entities(OTRO_WS, limit=10)[0]]
    assert ajeno, "la semilla del otro workspace no se creo"
    assert prov.entity(ajeno[0]["id"]) is None


# --- relaciones: el camino que estaba completamente muerto -------------------

def test_las_relaciones_llegan_con_su_visibilidad(base):
    """Sin `visibility` en el serializador, aqui no aparecia NI UNA arista."""
    prov = PolicyFilteredProvider(base, _ctx(P_A))
    _, edges = prov.graph(WS, limit=1000)
    assert edges, "el visor real se quedaba sin una sola relacion"
    assert all(e.get("visibility") for e in edges)


def test_una_arista_no_revela_un_extremo_secreto(base):
    """Monotonia observada a traves de Neo4j, no sobre diccionarios de test."""
    prov = PolicyFilteredProvider(base, _ctx(P_A))
    nodes, edges = prov.graph(WS, limit=1000)
    visibles = _nombres(nodes)
    assert "a_secret" not in visibles
    for e in edges:
        assert e.get("label") != "oculta", (
            "una arista secreta ha sobrevivido y delata la existencia de a_secret"
        )


# --- datos corruptos: denegar, no reventar ----------------------------------

@pytest.mark.parametrize(
    "nombre",
    ["corrupto_sin_scope", "corrupto_vis", "corrupto_known_by", "corrupto_sin_ws"],
)
def test_el_dato_corrupto_deniega_y_no_provoca_un_error(base, nombre):
    prov = PolicyFilteredProvider(base, _ctx(P_A))
    items, _ = prov.list_entities(WS, limit=1000)      # no debe lanzar
    assert nombre not in _nombres(items)


# --- conocimiento de personaje ----------------------------------------------

def test_known_by_valido_concede_y_solo_a_quien_toca(base):
    ana = PolicyFilteredProvider(base, _ctx(active_character="pc:ana"))
    otro = PolicyFilteredProvider(base, _ctx(active_character="pc:bruno"))
    assert "conocido" in _nombres(ana.list_entities(WS, limit=1000)[0])
    assert "conocido" not in _nombres(otro.list_entities(WS, limit=1000)[0])


def test_admin_ve_las_dos_partidas(base):
    admin = PolicyFilteredProvider(
        base, ViewerContext(role="admin", admin_full=True, session_public=True)
    )
    nombres = _nombres(admin.list_entities(WS, limit=1000)[0])
    assert {"a_player", "b_player"} <= nombres


# --- T2: la sesion de revelacion, atravesando Neo4j de verdad ----------------

def _jugador_a(tope=5, **over):
    return _ctx(partida=P_A, max_visible_session=tope, **over)


def _ids_visibles(prov, ctx):
    """OJO: no llamar a esto `_ids`. Este fichero ya tiene un `_ids(items)`
    arriba, y una segunda definicion con otra firma lo sombrea y rompe las
    pruebas anteriores sin decir por que."""
    from app.authz.filtered_provider import PolicyFilteredProvider
    items, _ = PolicyFilteredProvider(prov, ctx).list_entities(WS, limit=1000)
    # El nombre de dominio aflora como `label` (desde `canonical_name`). Se usa
    # la misma clave que `_nombres`, que ya funcionaba en este fichero.
    # (Nota historica: aqui decia que `entity_id` no viajaba en la proyeccion
    # del visor. Era cierto y era el defecto; el carril de identidad durable lo
    # corrigio y ahora `id` == `entity_id`.)
    return {i.get("label") for i in items}


def test_revelacion_pasada_visible_y_futura_oculta(base):
    ids = _ids_visibles(base, _jugador_a(5))
    assert {"rev_0", "rev_3"} <= ids
    assert "rev_8" not in ids


def test_known_by_no_salta_la_barrera_historica_en_neo4j(base):
    """La propiedad de T2 que solo vale si se prueba sobre datos reales."""
    ids = _ids_visibles(base, _jugador_a(5, active_character="pc:ana"))
    assert "rev_8_conocido" not in ids


def test_can_view_future_si_la_salta(base):
    assert "rev_8" in _ids_visibles(base, _jugador_a(5, can_view_future=True))


def test_tope_cero_ve_lo_conocido_desde_el_inicio(base):
    ids = _ids_visibles(base, _jugador_a(0))
    assert "rev_0" in ids
    assert "rev_3" not in ids


def test_revelacion_corrupta_deniega_sin_error(base):
    ids = _ids_visibles(base, _jugador_a(5))
    assert "rev_corrupta" not in ids


def test_el_conteo_y_el_grafo_respetan_la_revelacion(base):
    from app.authz.filtered_provider import PolicyFilteredProvider

    prov = PolicyFilteredProvider(base, _jugador_a(5))
    n_visibles, _ = prov.counts(WS)
    assert n_visibles == len(_ids_visibles(base, _jugador_a(5)))
    nodos, _ = prov.graph(WS, limit=1000)
    assert "rev_8" not in {n.get("label") for n in nodos}


def test_el_acceso_por_id_no_esquiva_la_revelacion(base):
    """Lista y detalle deben coincidir: un ID directo no es una puerta trasera."""
    from app.authz.filtered_provider import PolicyFilteredProvider

    prov = PolicyFilteredProvider(base, _jugador_a(5))
    # CONTRAPESO OBLIGATORIO. Desde que la identidad publicada es `entity_id`,
    # el proveedor devuelve None ante CUALQUIER `elementId`, asi que la version
    # anterior de esta prueba --que pedia el `elementId` de `rev_8`-- habria
    # seguido verde por el motivo equivocado: no por la barrera de revelacion,
    # sino porque ese identificador ya no resuelve nada. Se pide por el
    # identificador de dominio, y se exige ademas que uno PERMITIDO si resuelva:
    # sin esa segunda linea, «todo devuelve None» pasaria por exito.
    assert prov.entity("rev_0") is not None, (
        "ni siquiera lo permitido resuelve: la prueba no discrimina"
    )
    assert prov.entity("rev_8") is None


# ===========================================================================
# IDENTIFICADOR DURABLE (P0 de Release Candidate)
# ===========================================================================
#
# LO QUE SE DEMUESTRA AQUI
# ------------------------
# Que un enlace guardado desde el panel SOBREVIVE a una restauracion del
# grafo. No es un test de conversion: crea la entidad, saca el enlace del HTML
# del panel, restaura los datos en un store distinto, COMPRUEBA que el
# identificador fisico de Neo4j cambio, y vuelve a abrir EXACTAMENTE el enlace
# guardado.
#
# El paso de comprobar que el identificador fisico cambio no es ceremonia: sin
# el, la prueba pasaria igual con un identificador NO durable, y no probaria
# nada. Por eso vive en su propio test y ademas se reafirma dentro del test
# del enlace.
#
# COMO SE EMULA EL `dump`/`restore` -- Y POR QUE ESTA EMULACION ES HONESTA
# -----------------------------------------------------------------------
# `neo4j-admin database dump` exige parar la base y `restore` exige crear otra;
# la CI levanta un Neo4j Community de servicio, que no admite ninguna de las
# dos cosas. Lo que se hace es un volcado LOGICO: se exportan etiquetas y
# propiedades --exactamente lo que un dump preserva y lo unico que un restore
# reconstruye--, se vacia el ambito y se vuelve a crear desde el volcado.
#
# La propiedad que importa es que el `elementId` es una direccion FISICA del
# store y se reasigna al reconstruirlo. Esta emulacion la reproduce y, lo que
# es decisivo, la VERIFICA en vez de suponerla. Lo que la emulacion NO cubre
# --y se declara-- es el formato binario del dump y el `neo4j-admin` real.
import re as _re

WS_DUR = "juego:durabilidad"

#: `entity_id` con el formato REAL del writer V3: `entity:new:` + 16 hex de
#: `sha256(workspace \x1f superficie \x1f tipo)`.
#:
#: LA TRAMPA QUE ESTO EVITA: si el `entity_id` de prueba pudiera confundirse
#: con el `canonical_name` o con un `elementId`, la prueba no distinguiria
#: «llego el identificador durable» de «se aplico el respaldo al degradado».
#: Los tres espacios de nombres son deliberadamente disjuntos, y
#: `test_los_identificadores_de_prueba_no_pueden_confundirse` lo comprueba
#: ANTES de que ninguna otra medida de esta seccion signifique algo.
ID_DURABLE = "entity:new:0dcb4f1a2e5b7c93"
ID_VECINO = "entity:new:aa11bb22cc33dd44"
#: Existe, pero la politica no lo deja ver (secreto de capa juego).
ID_SECRETO = "entity:new:5150c0ffee123456"
#: No se siembra JAMAS.
ID_FANTASMA = "entity:new:ffffffffffffffff"

NOMBRE_DURABLE = "Agasha Tamori"

#: Forma del identificador fisico del driver: `<n>:<uuid>:<id interno>`.
_FORMA_ELEMENT_ID = _re.compile(r"^\d+:[0-9a-fA-F-]{36}:\d+$")

_SEMILLA_DUR = [
    (ID_DURABLE, NOMBRE_DURABLE, "player"),
    (ID_VECINO, "Kitsuki Yaruma", "player"),
    (ID_SECRETO, "El pacto de la Fosa", "secret"),
]


def _proveedor():
    from app.providers.neo4j_provider import Neo4jGraphProvider

    return Neo4jGraphProvider(URI, USER, PASSWORD)


def _crear_dur(session):
    for eid, nombre, vis in _SEMILLA_DUR:
        session.run(
            "CREATE (n:Entity $props)",
            {"props": {"entity_id": eid, "canonical_name": nombre,
                       "entity_type": "Character", "workspace": WS_DUR,
                       "scope": "juego", "visibility": vis,
                       "review_status": "reviewed", "confidence": 0.9}},
        )
    session.run(
        "MATCH (a:Entity {entity_id:$a}), (b:Entity {entity_id:$b}) "
        "CREATE (a)-[:VENERA {visibility:'player', workspace:$ws, scope:'juego', "
        "relation_label_es:'venera'}]->(b)",
        {"a": ID_DURABLE, "b": ID_VECINO, "ws": WS_DUR},
    )


def _borrar_dur(session):
    session.run("MATCH (n:Entity {workspace:$ws}) DETACH DELETE n", {"ws": WS_DUR})


@pytest.fixture
def grafo_dur(driver):
    """Ambito propio y desechable. NUNCA toca el de las demas pruebas."""
    with driver.session() as s:
        _borrar_dur(s)
        _crear_dur(s)
    yield driver
    with driver.session() as s:
        _borrar_dur(s)


def _element_id_de(driver, entity_id):
    with driver.session() as s:
        rec = s.run(
            "MATCH (n:Entity {entity_id:$id}) RETURN elementId(n) AS eid",
            {"id": entity_id},
        ).single()
    return rec["eid"] if rec else None


def _restaurar_en_store_nuevo(driver):
    """Volcado logico + restauracion. Devuelve (nodos, aristas) revividos.

    Devuelve las cifras a proposito: un arnes que restaura 0 nodos dejaria la
    base vacia y el test del enlace se pondria rojo sin que nadie supiera que
    el fallo fue del arnes. Quien llama exige un suelo.
    """
    with driver.session() as s:
        nodos = [
            {"labels": list(r["l"]), "props": dict(r["p"])}
            for r in s.run(
                "MATCH (n:Entity {workspace:$ws}) "
                "RETURN labels(n) AS l, properties(n) AS p", {"ws": WS_DUR})
        ]
        aristas = [
            {"desde": r["d"], "hacia": r["h"], "tipo": r["t"], "props": dict(r["p"])}
            for r in s.run(
                "MATCH (a:Entity {workspace:$ws})-[r]->(b:Entity {workspace:$ws}) "
                "RETURN a.entity_id AS d, b.entity_id AS h, type(r) AS t, "
                "properties(r) AS p", {"ws": WS_DUR})
        ]

        # El volcado tiene que parecerse a lo que preserva un dump de verdad:
        # etiquetas y propiedades. Si aparecieran etiquetas que la restauracion
        # de abajo no sabe recrear, la emulacion seria infiel y hay que verlo.
        for n in nodos:
            assert n["labels"] == ["Entity"], f"etiquetas no previstas: {n['labels']}"
            assert "entity_id" in n["props"]

        _borrar_dur(s)

        # Relleno: consume los identificadores internos que acaba de liberar el
        # borrado, para que la reconstruccion NO caiga por casualidad en los
        # mismos. Es lo que hace un restore de verdad --reasignar-- sin dejarlo
        # al azar. Aun asi la desigualdad se AFIRMA, no se da por hecha: si
        # coincidieran, el test tiene que enrojecer, no disimular.
        s.run("UNWIND range(1,500) AS i CREATE (:RellenoRestore {i:i})")

        for n in nodos:
            s.run("CREATE (n:Entity $props)", {"props": n["props"]})
        for a in aristas:
            assert _re.match(r"^[A-Z][A-Z0-9_]*$", a["tipo"]), a["tipo"]
            s.run(
                "MATCH (x:Entity {entity_id:$d}), (y:Entity {entity_id:$h}) "
                "CREATE (x)-[r:`%s` $props]->(y)" % a["tipo"],
                {"d": a["desde"], "h": a["hacia"], "props": a["props"]},
            )

        s.run("MATCH (n:RellenoRestore) DELETE n")
    return len(nodos), len(aristas)


# --- 0. El material discrimina. Sin esto, lo demas no mide nada. ------------

def test_los_identificadores_de_prueba_no_pueden_confundirse(grafo_dur):
    """No-colision COMPROBADA antes de medir.

    Un fixture cuyo `entity_id` coincidiera con el `canonical_name` o tuviera
    forma de `elementId` no podria distinguir «llego el dato» de «se aplico el
    respaldo». Se comprueba contra los valores REALES de la base, no solo
    contra las constantes.
    """
    valores = [ID_DURABLE, ID_VECINO, ID_SECRETO, ID_FANTASMA, NOMBRE_DURABLE]
    assert len(set(valores)) == len(valores)
    for v in valores:
        assert not _FORMA_ELEMENT_ID.match(v), f"«{v}» tiene forma de elementId"

    eid = _element_id_de(grafo_dur, ID_DURABLE)
    assert eid is not None, "la semilla no se creo: el arnes no ejercio nada"
    assert _FORMA_ELEMENT_ID.match(eid), f"elementId inesperado: {eid}"
    assert eid not in valores
    with grafo_dur.session() as s:
        assert s.run(
            "MATCH (n:Entity {entity_id:$id}) RETURN n.canonical_name AS c",
            {"id": ID_DURABLE}).single()["c"] == NOMBRE_DURABLE
        assert s.run(
            "MATCH (n:Entity {entity_id:$id}) RETURN count(n) AS c",
            {"id": ID_FANTASMA}).single()["c"] == 0, "el fantasma existe"


# --- 1. El paso imprescindible: el identificador FISICO cambio --------------

def test_tras_la_restauracion_el_identificador_fisico_de_neo4j_CAMBIO(grafo_dur):
    """Sin esto, la prueba del enlace no prueba nada.

    Un enlace que sigue funcionando despues de una restauracion que NO reasigno
    identificadores es un enlace que no ha demostrado ser durable: pasaria
    exactamente igual con el identificador no durable de antes.
    """
    antes = _element_id_de(grafo_dur, ID_DURABLE)
    nodos, aristas = _restaurar_en_store_nuevo(grafo_dur)
    assert (nodos, aristas) == (3, 1), (
        f"el arnes restauro {nodos} nodos y {aristas} aristas; se esperaban 3 y 1"
    )
    despues = _element_id_de(grafo_dur, ID_DURABLE)

    assert antes and despues
    assert despues != antes, (
        "el identificador fisico NO cambio en la restauracion: la prueba de "
        f"durabilidad no ejerceria nada ({antes})"
    )
    # Y la identidad de dominio, en cambio, es la misma.
    with grafo_dur.session() as s:
        assert s.run(
            "MATCH (n:Entity {entity_id:$id}) RETURN n.canonical_name AS c",
            {"id": ID_DURABLE}).single()["c"] == NOMBRE_DURABLE


# --- 2. El proveedor resuelve por identidad durable, no por la fisica -------

def test_el_proveedor_no_resuelve_por_element_id(grafo_dur):
    """CONTROL NEGATIVO: el identificador fisico ya no abre nada."""
    prov = _proveedor()
    eid = _element_id_de(grafo_dur, ID_DURABLE)
    assert prov.entity(ID_DURABLE) is not None, "ni lo durable resuelve"
    assert prov.entity(eid) is None, (
        "el `elementId` sigue siendo una llave valida: la identidad no ha "
        "migrado, solo se ha duplicado"
    )


def test_el_entity_id_viaja_en_la_proyeccion_real(grafo_dur):
    prov = _proveedor()
    n = prov.entity(ID_DURABLE)
    assert n["entity_id"] == ID_DURABLE
    assert n["id"] == ID_DURABLE
    assert not _FORMA_ELEMENT_ID.match(str(n["id"]))
    assert _element_id_de(grafo_dur, ID_DURABLE) not in str(n), (
        "el elementId se cuela en algun campo de la proyeccion real"
    )


def test_las_aristas_llegan_con_extremos_durables(grafo_dur):
    prov = _proveedor()
    salientes, _ = prov.relations_for_entity(ID_DURABLE)
    assert salientes, "sin aristas: el arnes no ejercio el camino de relaciones"
    e = salientes[0]
    assert e["from"] == ID_DURABLE and e["to"] == ID_VECINO


# --- 3. EL ENLACE DEL PANEL, DE EXTREMO A EXTREMO ---------------------------
#
# Aqui se cierra la deuda. Lo anterior mide el proveedor; esto mide lo que el
# usuario guarda en sus marcadores: el `href` que pinta el panel.

_PASSWORD_DUR = "DurableTest_1234567890!"


@pytest.fixture
def panel_dur(grafo_dur, tmp_path):
    """Panel G encendido, auth real y el proveedor de Neo4j DE VERDAD detras.

    Se sustituye el proveedor BASE (`app.deps.get_provider`), no el filtrado:
    asi la peticion atraviesa entera la cadena real
    `get_filtered_provider -> build_viewer_context -> PolicyFilteredProvider ->
    VisibilityPolicy`. Sustituir mas arriba dejaria la politica fuera de la
    medida y el resultado seria un adorno.
    """
    from app.auth import db as auth_db_mod
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    from app.chassis import FEATURE_SLOTS, slot_flag_env
    from app.config import get_settings
    from fastapi.testclient import TestClient

    slot = next(s for s in FEATURE_SLOTS if s.key == "G")
    flag = slot_flag_env(slot)
    claves = ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_GRAPH_PROVIDER", flag)
    previos = {k: os.environ.get(k) for k in claves}

    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS_DUR
    os.environ[flag] = "true"
    get_settings.cache_clear()
    get_auth_settings.cache_clear()
    auth_db_mod.ensure_migrated(db_path)

    with auth_db_mod.get_conn(db_path) as conn:
        u = auth_db_mod.create_user(
            conn, username="jugadora_dur", display_name="Jugadora",
            password_hash=hash_password(_PASSWORD_DUR), role="viewer",
        )
        auth_db_mod.update_user(conn, u.id, must_change_password=False)
        u = auth_db_mod.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)

    import app.deps as deps
    from app.main import app

    prov = _proveedor()
    app.dependency_overrides[deps.get_provider] = lambda: prov

    cliente = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    cliente.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    try:
        yield cliente
    finally:
        app.dependency_overrides.pop(deps.get_provider, None)
        for k, v in previos.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
        get_auth_settings.cache_clear()


def _enlace_del_panel(cliente, entity_id=ID_DURABLE):
    """Paso 2 del guion: el enlace se saca DEL PANEL, no se construye a mano.

    Construirlo a mano probaria que la ruta funciona, no que el panel la
    publica. El defecto vivia justo ahi: la plantilla pintaba `row.id`, que era
    el `elementId`.
    """
    r = cliente.get(f"/panel/entities?workspace={WS_DUR}")
    assert r.status_code == 200, f"el panel no responde: {r.status_code}"
    # `url_for` de Starlette devuelve la URL ABSOLUTA
    # (`http://testserver/panel/entities/item/...`), asi que el esquema y el
    # host son opcionales en el patron. Con el patron anclado a `/panel` esto
    # no encontraba ni un enlace y las cuatro pruebas de esta seccion morian
    # por un fallo del ARNES: rojo, si, pero por el motivo equivocado.
    enlaces = _re.findall(r'href="([^"]*/panel/entities/item/[^"]+)"', r.text)
    assert enlaces, "el panel no publico ni un enlace de ficha"
    # Se compara sobre el enlace DESCODIFICADO: `url_for` puede escapar los
    # `:` del `entity_id` como `%3A`, y comparar sobre el texto crudo daria un
    # "no aparece" falso. El enlace se DEVUELVE tal cual viene, sin descodificar:
    # lo que se reabre despues tiene que ser exactamente lo que publico el panel.
    from urllib.parse import unquote

    del_nuestro = [e for e in enlaces if entity_id in unquote(e)]
    assert del_nuestro, (
        f"el panel no publica un enlace hacia «{entity_id}». Enlaces vistos: "
        f"{enlaces}"
    )
    return del_nuestro[0]


def test_el_enlace_que_publica_el_panel_lleva_la_identidad_durable(panel_dur, grafo_dur):
    """El `href` lleva `entity_id` y NO el identificador fisico."""
    from urllib.parse import unquote

    enlace = _enlace_del_panel(panel_dur)
    eid = _element_id_de(grafo_dur, ID_DURABLE)
    assert ID_DURABLE in unquote(enlace)
    assert eid not in unquote(enlace), f"el elementId sigue en la URL: {enlace}"
    # Y en ningun sitio del HTML del panel, no solo en este `href`.
    html = panel_dur.get(f"/panel/entities?workspace={WS_DUR}").text
    assert eid not in html, "el elementId aparece en el HTML del panel"


def test_EL_ENLACE_GUARDADO_SOBREVIVE_A_LA_RESTAURACION(panel_dur, grafo_dur):
    """LA PRUEBA QUE CIERRA LA DEUDA.

    1) entidad con `entity_id` estable  2) enlace sacado DEL PANEL
    3) enlace guardado                  4)+5) volcado y restauracion
    6) se COMPRUEBA que el identificador fisico cambio
    7) se abre EXACTAMENTE el enlace guardado
    8) resuelve la MISMA entidad autorizada.

    Antes de este carril, el paso 7 devolvia 404 -- y ese 404 era, por diseno de
    la politica, indistinguible de «no existe». El fallo era silencioso.
    """
    # 1-3
    enlace = _enlace_del_panel(panel_dur)
    fisico_antes = _element_id_de(grafo_dur, ID_DURABLE)
    previa = panel_dur.get(enlace)
    assert previa.status_code == 200, (
        f"el enlace no funcionaba ni ANTES de restaurar ({previa.status_code}); "
        "el resto de la prueba no mediria durabilidad"
    )
    assert NOMBRE_DURABLE in previa.text

    # 4-5
    nodos, aristas = _restaurar_en_store_nuevo(grafo_dur)
    assert (nodos, aristas) == (3, 1), "el arnes no restauro lo que dice"

    # 6 -- IMPRESCINDIBLE. Sin esto la prueba pasaria con un id no durable.
    fisico_despues = _element_id_de(grafo_dur, ID_DURABLE)
    assert fisico_despues != fisico_antes, (
        "el identificador fisico no cambio: esta prueba no demuestra nada"
    )
    # Descodificado a proposito: si el enlace viniera escapado, comparar sobre
    # el texto crudo haria pasar esta linea por construccion.
    from urllib.parse import unquote

    assert fisico_antes not in unquote(enlace)
    assert fisico_despues not in unquote(enlace)

    # 7-8 -- el MISMO enlace, byte a byte.
    despues = panel_dur.get(enlace)
    assert despues.status_code == 200, (
        f"el enlace guardado murio en la restauracion ({despues.status_code}): "
        "el identificador de la URL no es durable"
    )
    assert NOMBRE_DURABLE in despues.text, (
        "el enlace resuelve, pero no a la misma entidad"
    )


# --- 4. LOS CUATRO CONTROLES NEGATIVOS --------------------------------------

def test_negativo_inexistente_y_no_autorizado_son_INDISTINGUIBLES(panel_dur):
    """Mismo codigo Y mismo cuerpo. Si difirieran, la URL seria un oraculo de
    existencia: bastaria pasear identificadores para saber que hay ahi.

    `ID_SECRETO` existe en la base (lo siembra el fixture) y la politica lo
    niega a esta jugadora; `ID_FANTASMA` no se ha sembrado jamas.
    """
    fantasma = panel_dur.get(f"/panel/entities/item/{ID_FANTASMA}")
    secreto = panel_dur.get(f"/panel/entities/item/{ID_SECRETO}")

    # Contrapeso: si TODO diera 404, la igualdad seria trivial.
    assert panel_dur.get(f"/panel/entities/item/{ID_DURABLE}").status_code == 200

    assert fantasma.status_code == secreto.status_code == 404, (
        f"fantasma={fantasma.status_code} secreto={secreto.status_code}"
    )
    assert fantasma.content == secreto.content, (
        "el cuerpo revela cual de los dos existe"
    )


def test_negativo_lo_existente_sin_permiso_no_revela_su_existencia(panel_dur):
    """Ni el codigo, ni el cuerpo, ni el listado mencionan el secreto."""
    r = panel_dur.get(f"/panel/entities/item/{ID_SECRETO}")
    assert r.status_code == 404
    assert "El pacto de la Fosa" not in r.text
    listado = panel_dur.get(f"/panel/entities?workspace={WS_DUR}").text
    assert ID_SECRETO not in listado
    assert "El pacto de la Fosa" not in listado
    assert ID_DURABLE in listado, "el listado esta vacio: no discrimina nada"


def test_negativo_cambiar_el_ELEMENT_ID_no_rompe_el_enlace(panel_dur, grafo_dur):
    """Tercer control: se mueve el identificador FISICO y el enlace aguanta.

    Es la restauracion reducida a su esencia. Se hace aparte del test grande
    para que, si algo falla, se sepa si fallo el volcado o la identidad.
    """
    enlace = _enlace_del_panel(panel_dur)
    antes = _element_id_de(grafo_dur, ID_DURABLE)

    # Recrear el nodo con las MISMAS propiedades le da otro identificador
    # fisico: es lo unico que un `restore` cambia.
    with grafo_dur.session() as s:
        props = dict(s.run(
            "MATCH (n:Entity {entity_id:$id}) RETURN properties(n) AS p",
            {"id": ID_DURABLE}).single()["p"])
        s.run("MATCH (n:Entity {entity_id:$id}) DETACH DELETE n", {"id": ID_DURABLE})
        s.run("UNWIND range(1,500) AS i CREATE (:RellenoRestore {i:i})")
        s.run("CREATE (n:Entity $props)", {"props": props})
        s.run("MATCH (n:RellenoRestore) DELETE n")

    despues = _element_id_de(grafo_dur, ID_DURABLE)
    assert despues != antes, "el elementId no cambio: el control no ejercio nada"
    r = panel_dur.get(enlace)
    assert r.status_code == 200 and NOMBRE_DURABLE in r.text


def test_negativo_DECISIVO_cambiar_el_ENTITY_ID_rompe_el_enlace(panel_dur, grafo_dur):
    """EL CONTROL QUE SOSTIENE TODO LO DEMAS.

    Si mover el identificador de dominio NO rompiera el enlace, entonces el
    enlace no esta atado a `entity_id` y ninguna de las pruebas de arriba mide
    durabilidad: mediria que «cualquier cosa resuelve».

    Aqui ese rojo se afirma como comportamiento esperado --404-- para que viva
    permanentemente en la suite. Su version «la prueba se pone ROJA» es la
    mutacion homonima del arnes de calibracion.
    """
    enlace = _enlace_del_panel(panel_dur)
    assert panel_dur.get(enlace).status_code == 200, "no partimos de verde"

    otro = "entity:new:0000deadbeef0000"
    assert otro != ID_DURABLE and not _FORMA_ELEMENT_ID.match(otro)
    with grafo_dur.session() as s:
        s.run("MATCH (n:Entity {entity_id:$v}) SET n.entity_id = $n",
              {"v": ID_DURABLE, "n": otro})

    roto = panel_dur.get(enlace)
    assert roto.status_code == 404, (
        "el enlace SIGUE resolviendo despues de cambiarle el `entity_id` a la "
        f"entidad ({roto.status_code}): no esta atado a la identidad durable, "
        "asi que las pruebas de durabilidad no miden durabilidad"
    )
    # Y con el identificador nuevo si resuelve: el nodo no ha desaparecido, se
    # ha renombrado. Sin esta linea, «lo borre sin querer» pasaria por exito.
    nuevo = panel_dur.get(f"/panel/entities/item/{otro}")
    assert nuevo.status_code == 200 and NOMBRE_DURABLE in nuevo.text


# =============================================================================
# 5. UNICIDAD DURABLE: para cada URL, 0 o 1 objetos. NUNCA 2+.
# =============================================================================
#
# POR QUE ESTA SECCION NO ES HIGIENE DE DATOS
# -------------------------------------------
# Si dos nodos comparten `entity_id`, `/entities/{entity_id}` deja de nombrar
# un objeto y pasa a nombrar un CONJUNTO. Quien elige entonces es el orden de
# devolucion de Neo4j. Medido: 12/12 peticiones devolvieron el duplicado y la
# entidad legitima se volvio un 404 indistinguible de «no existe». Un objeto
# servido por una URL que no le pertenece ha esquivado la identidad, y todo lo
# que se decide a partir de la identidad va detras.
#
# LA CLAVE DE UNICIDAD SE DERIVA, NO SE ELIGE
# -------------------------------------------
# `data-engine/app/knowledge_v3/writer/cypher.py::_scoped_match` define la
# identidad de almacenamiento como `{id_field, workspace, partida_id}` ("MATCH
# exacto de un nodo en SU propio ambito declarado (...) Nunca un comodin"). Esa
# terna es la clave. El DDL vive en `writer/schema.py` y se IMPORTA aqui: una
# sola fuente normativa, no una copia que pueda divergir.
#
# LAS DOS BARRERAS
# ----------------
# 1. Restriccion de esquema: impide CREAR el estado invalido. No cubre la capa
#    juego (Neo4j no aplica compuestas con propiedades ausentes) ni cubre el
#    pasado. Ambos huecos se MIDEN aqui abajo en vez de suponerse.
# 2. Resolver fail-closed: con 2+ no se escoge ninguno. Es la unica que cubre
#    datos historicos, una restauracion defectuosa o un retro-relleno de
#    `entity_id` con una derivacion imperfecta.

#: COLISION REALISTA, no dos copias del mismo nodo. Son dos entidades DISTINTAS
#: y legitimas --dos personajes con el mismo nombre canonico en el mismo
#: workspace-- que una derivacion apoyada en el nombre haria colisionar en el
#: mismo `entity_id`. Es el escenario que casi ocurre en la base real: alli
#: `canonical_name` YA colisiona (4 claves, mayor grupo 3, 9 nodos), asi que el
#: dia que se retro-rellene `entity_id` con una derivacion por nombre esto no
#: sera hipotetico. Dos copias identicas habrian sido un test mas facil y una
#: medida peor: con descripciones distintas se puede ver CUAL se habria servido.
ID_COLISION = "entity:new:c0111510dcafe001"
NOMBRE_COLISION = "Doji Hotaru"
_GEMELAS = [
    {"entity_id": ID_COLISION, "canonical_name": NOMBRE_COLISION,
     "entity_type": "Character", "workspace": WS_DUR, "scope": "juego",
     "visibility": "player", "review_status": "reviewed", "confidence": 0.9,
     "description": "La duelista de la Grulla, sesion 3"},
    {"entity_id": ID_COLISION, "canonical_name": NOMBRE_COLISION,
     "entity_type": "Character", "workspace": WS_DUR, "scope": "juego",
     "visibility": "player", "review_status": "reviewed", "confidence": 0.9,
     "description": "La cartografa de Toshi Ranbo, sesion 11"},
]


def _constraints_vigentes(driver) -> dict:
    with driver.session() as s:
        return {
            r["name"]: (r["type"], r["labelsOrTypes"], r["properties"])
            for r in s.run(
                "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
                "RETURN name, type, labelsOrTypes, properties"
            )
        }


def _aplicar_constraints(driver):
    from knowledge_v3.writer.schema import DURABLE_IDENTITY_CONSTRAINTS

    with driver.session() as s:
        for _, _, _, ddl in DURABLE_IDENTITY_CONSTRAINTS:
            s.run(ddl).consume()


def _retirar_constraints(driver):
    from knowledge_v3.writer.schema import (
        ENTITY_DURABLE_IDENTITY_CONSTRAINT,
        V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT,
        V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT,
    )

    with driver.session() as s:
        for nombre in (ENTITY_DURABLE_IDENTITY_CONSTRAINT,
                       V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT,
                       V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT):
            s.run(f"DROP CONSTRAINT {nombre} IF EXISTS").consume()


@pytest.fixture
def con_constraints(grafo_dur):
    """Barrera 1 puesta, y RETIRADA al salir.

    Se retira a proposito: estas restricciones son globales a la base y el job
    corre mas suites detras. Una barrera que se queda puesta convertiria un
    fallo de OTRA suite en un misterio.
    """
    _aplicar_constraints(grafo_dur)
    yield grafo_dur
    _retirar_constraints(grafo_dur)


# --- 5.1 Barrera 1: la restriccion de esquema -------------------------------

def test_la_restriccion_de_unicidad_existe_y_es_de_UNICIDAD(con_constraints):
    """Existe, es de tipo UNIQUENESS y cae sobre la clave DERIVADA.

    Se comprueban las propiedades una a una: una restriccion con el nombre
    correcto sobre las columnas equivocadas pasaria un test de presencia y no
    protegeria nada.
    """
    from knowledge_v3.writer.schema import (
        ENTITY_DURABLE_IDENTITY_CONSTRAINT,
        V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT,
        V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT,
    )

    vigentes = _constraints_vigentes(con_constraints)
    esperado = {
        # La clave es la de `_assert_absent`: `(workspace, <id>)`. Sin
        # `partida_id`, a proposito -- meterlo la haria mas laxa que el writer
        # y dejaria la capa juego sin cubrir.
        ENTITY_DURABLE_IDENTITY_CONSTRAINT:
            (["Entity"], ["workspace", "entity_id"]),
        V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT:
            (["V3Entity"], ["workspace", "entity_id"]),
        V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT:
            (["V3Assertion"], ["workspace", "assertion_id"]),
    }
    for nombre, (etiquetas, props) in esperado.items():
        assert nombre in vigentes, f"no existe la restriccion {nombre}: {sorted(vigentes)}"
        tipo, labels, propiedades = vigentes[nombre]
        assert "UNIQUE" in tipo.upper(), f"{nombre} no es de unicidad: {tipo}"
        assert labels == etiquetas, f"{nombre} sobre {labels}, se esperaba {etiquetas}"
        assert propiedades == props, f"{nombre} sobre {propiedades}, se esperaba {props}"


def test_la_restriccion_IMPIDE_crear_el_duplicado_en_capa_partida(con_constraints):
    """El estado invalido no se puede CREAR: el segundo CREATE muere en la base."""
    from neo4j.exceptions import ClientError

    with con_constraints.session() as s:
        s.run("CREATE (n:Entity $props)",
              {"props": dict(_GEMELAS[0], scope="partida", partida_id="partida:X")})
        with pytest.raises(ClientError) as exc:
            s.run("CREATE (n:Entity $props)",
                  {"props": dict(_GEMELAS[1], scope="partida",
                                 partida_id="partida:X")}).consume()
        # Se afirma el CODIGO de Neo4j, no una subcadena del mensaje: un
        # `ClientError` cualquiera --sintaxis mala, sesion muerta-- pasaria una
        # comprobacion por texto y este test daria por cortada una restriccion
        # que no corto nada.
        assert "ConstraintValidationFailed" in (exc.value.code or ""), (
            f"murio por otro motivo, no por la restriccion: {exc.value.code}"
        )
        cuantos = s.run(
            "MATCH (n:Entity {entity_id:$id, workspace:$ws}) RETURN count(n) AS c",
            {"id": ID_COLISION, "ws": WS_DUR}).single()["c"]
    assert cuantos == 1, f"quedaron {cuantos} nodos: la barrera no fue la que corto"


def test_ABLACION_sin_la_restriccion_el_duplicado_SI_se_crea(grafo_dur):
    """NECESIDAD POR ABLACION -- control negativo de la barrera 1.

    Sin esto, la restriccion podria estar prohibiendo algo que de todas formas
    nadie iba a crear, y se cobraria como defensa sin serlo. Se quita la
    barrera y se comprueba que el duplicado ENTRA: era lo unico que lo impedia.
    """
    _retirar_constraints(grafo_dur)
    with grafo_dur.session() as s:
        for g in _GEMELAS:
            s.run("CREATE (n:Entity $props)",
                  {"props": dict(g, scope="partida", partida_id="partida:X")})
        cuantos = s.run(
            "MATCH (n:Entity {entity_id:$id, workspace:$ws}) RETURN count(n) AS c",
            {"id": ID_COLISION, "ws": WS_DUR}).single()["c"]
    assert cuantos == 2, (
        f"sin la restriccion solo se crearon {cuantos} nodos: algo mas los "
        "estaba frenando y la restriccion no es la defensa que se cobra"
    )


def test_la_restriccion_SI_cubre_la_capa_juego(con_constraints):
    """LA CAPA JUEGO TAMBIEN QUEDA CUBIERTA, y por eso la clave es la que es.

    La primera version de este carril uso `(workspace, entity_id, partida_id)`
    y este mismo test afirmaba lo CONTRARIO: que la capa juego quedaba fuera,
    porque el lore se escribe con `partida_id: None` --Neo4j lo guarda como
    ausencia-- y una restriccion compuesta no se aplica a un nodo al que le
    falta una propiedad. Aquello era cierto y era un agujero enorme: el lore es
    justo donde vive casi todo.

    Con la clave que el writer REALMENTE aplica (`_assert_absent`:
    `(workspace, entity_id)`, sin filtro de partida) las dos propiedades estan
    siempre presentes en un nodo direccionable y el agujero desaparece. Se
    afirma como comportamiento MEDIDO, no como consecuencia razonada.
    """
    from neo4j.exceptions import ClientError

    with con_constraints.session() as s:
        s.run("CREATE (n:Entity $props)", {"props": _GEMELAS[0]})  # sin partida_id
        with pytest.raises(ClientError) as exc:
            s.run("CREATE (n:Entity $props)", {"props": _GEMELAS[1]}).consume()
        # Se afirma el CODIGO de Neo4j, no una subcadena del mensaje: un
        # `ClientError` cualquiera --sintaxis mala, sesion muerta-- pasaria una
        # comprobacion por texto y este test daria por cortada una restriccion
        # que no corto nada.
        assert "ConstraintValidationFailed" in (exc.value.code or ""), (
            f"murio por otro motivo, no por la restriccion: {exc.value.code}"
        )
        cuantos = s.run(
            "MATCH (n:Entity {entity_id:$id, workspace:$ws}) RETURN count(n) AS c",
            {"id": ID_COLISION, "ws": WS_DUR}).single()["c"]
    assert cuantos == 1, f"quedaron {cuantos} nodos: la barrera no fue la que corto"


def test_la_capa_juego_y_una_partida_TAMPOCO_pueden_compartir_entity_id(con_constraints):
    """La coherencia entre las dos barreras, afirmada como test.

    Este es el caso que la clave anterior admitia A PROPOSITO --capa juego y
    `partida:Y` con el mismo `entity_id`-- y que el resolver del visor, que no
    filtra por `partida_id`, habria leido como AMBIGUO cerrando en falso una
    ficha legitima. `_assert_absent` ya lo prohibe en el writer ("dos ambitos
    jamas comparten el mismo id"); ahora tambien lo prohibe el esquema.

    Mientras este test siga verde, ningun estado que el esquema admita puede
    hacer que el resolver falle cerrado.
    """
    from neo4j.exceptions import ClientError

    with con_constraints.session() as s:
        s.run("CREATE (n:Entity $props)", {"props": _GEMELAS[0]})  # capa juego
        with pytest.raises(ClientError):
            s.run("CREATE (n:Entity $props)",
                  {"props": dict(_GEMELAS[1], scope="partida",
                                 partida_id="partida:X")}).consume()


def test_la_restriccion_NO_cubre_EL_PASADO_HUECO_DECLARADO(grafo_dur):
    """EL HUECO QUE QUEDA, medido: una base SIN la restriccion admite el
    duplicado, y la restriccion no se puede crear despues sobre datos que ya la
    violan.

    No es teorico: el preflight de solo lectura midio que la base real no tiene
    NI UNA restriccion. Este es exactamente el estado en el que llegaria una
    colision historica, una restauracion defectuosa o un retro-relleno de
    `entity_id` derivado del nombre canonico --que en esa base YA colisiona--.

    Por eso la barrera del resolver no es redundante: es la unica que cubre
    este escenario, y el ultimo `assert` lo demuestra sobre el mismo estado.
    """
    from neo4j.exceptions import Neo4jError

    _retirar_constraints(grafo_dur)
    with grafo_dur.session() as s:
        for g in _GEMELAS:
            s.run("CREATE (n:Entity $props)", {"props": g})
        cuantos = s.run(
            "MATCH (n:Entity {entity_id:$id, workspace:$ws}) RETURN count(n) AS c",
            {"id": ID_COLISION, "ws": WS_DUR}).single()["c"]
        assert cuantos == 2, "sin restriccion el duplicado tenia que entrar"

        # Y ya no se puede poner la barrera: los datos la violan. Neo4j lo
        # senala como `Neo.DatabaseError.Schema.ConstraintCreationFailed` --un
        # `DatabaseError`, NO un `ClientError`: la primera version de este test
        # esperaba la clase equivocada y fallo en CI--. Se afirma el CODIGO, no
        # la clase: cualquier otro fallo de base (contenedor caido, sesion
        # muerta) daria el mismo tipo y este test lo daria por bueno.
        with pytest.raises(Neo4jError) as exc:
            _aplicar_constraints(grafo_dur)
        assert "ConstraintCreationFailed" in (exc.value.code or ""), (
            f"fallo por otra cosa, no por los datos que la violan: {exc.value.code}"
        )

    # El unico que sigue defendiendo la URL en este estado es el resolver.
    assert _proveedor().entity(ID_COLISION) is None


# --- 5.1bis Aserciones: la garantia se EJERCE, no solo se declara -----------

ID_ASERCION_COLISION = "assertion:c0111510dcafe002"


def test_la_restriccion_de_ASERCIONES_corta_la_colision_de_verdad(con_constraints):
    """O3: la garantia de aserciones deja de estar cobrada sin prueba.

    Antes se verificaba la FORMA de la restriccion (nombre, tipo, columnas) y
    se declaraba que su colision no se ejercia. Una laguna no es una garantia,
    asi que aqui se provoca: dos aserciones DISTINTAS con el mismo
    `assertion_id` en el mismo workspace. La segunda muere en la base.

    Lo que sigue SIN existir --y se declara-- es una barrera de resolver para
    aserciones, porque el visor no expone ninguna ruta `/assertions/{id}`: no
    hay URL durable de asercion que secuestrar. El dia que la haya, hara falta
    su fail-closed, igual que el de `entity()`.
    """
    from neo4j.exceptions import ClientError

    comun = {"assertion_id": ID_ASERCION_COLISION, "workspace": WS_DUR,
             "scope": "juego", "visibility": "player"}
    with con_constraints.session() as s:
        s.run("CREATE (n:V3Assertion $props)",
              {"props": dict(comun, predicate="VENERA")})
        with pytest.raises(ClientError) as exc:
            s.run("CREATE (n:V3Assertion $props)",
                  {"props": dict(comun, predicate="TRAICIONA")}).consume()
        # Se afirma el CODIGO de Neo4j, no una subcadena del mensaje: un
        # `ClientError` cualquiera --sintaxis mala, sesion muerta-- pasaria una
        # comprobacion por texto y este test daria por cortada una restriccion
        # que no corto nada.
        assert "ConstraintValidationFailed" in (exc.value.code or ""), (
            f"murio por otro motivo, no por la restriccion: {exc.value.code}"
        )
        cuantas = s.run(
            "MATCH (n:V3Assertion {assertion_id:$id}) RETURN count(n) AS c",
            {"id": ID_ASERCION_COLISION}).single()["c"]
        s.run("MATCH (n:V3Assertion {assertion_id:$id}) DETACH DELETE n",
              {"id": ID_ASERCION_COLISION})
    assert cuantas == 1, f"quedaron {cuantas} aserciones: no corto la restriccion"


def test_ABLACION_sin_la_restriccion_la_colision_de_ASERCIONES_entra(grafo_dur):
    """Control negativo de la anterior: sin la restriccion, las dos entran."""
    _retirar_constraints(grafo_dur)
    comun = {"assertion_id": ID_ASERCION_COLISION, "workspace": WS_DUR,
             "scope": "juego", "visibility": "player"}
    with grafo_dur.session() as s:
        s.run("CREATE (n:V3Assertion $props)",
              {"props": dict(comun, predicate="VENERA")})
        s.run("CREATE (n:V3Assertion $props)",
              {"props": dict(comun, predicate="TRAICIONA")})
        cuantas = s.run(
            "MATCH (n:V3Assertion {assertion_id:$id}) RETURN count(n) AS c",
            {"id": ID_ASERCION_COLISION}).single()["c"]
        s.run("MATCH (n:V3Assertion {assertion_id:$id}) DETACH DELETE n",
              {"id": ID_ASERCION_COLISION})
    assert cuantas == 2, (
        f"sin la restriccion solo entro {cuantas}: algo mas lo frenaba y la "
        "restriccion no es la defensa que se cobra"
    )


# --- 5.2 Barrera 2: el resolver no escoge -----------------------------------

@pytest.fixture
def grafo_colision(grafo_dur):
    """Dos entidades legitimas y DISTINTAS con la misma identidad durable.

    Se siembran en capa juego a proposito: es el unico camino por el que la
    barrera 1 las dejaria pasar, y es exactamente la forma en que llegaria una
    colision historica o un retro-relleno mal derivado.
    """
    with grafo_dur.session() as s:
        for g in _GEMELAS:
            s.run("CREATE (n:Entity $props)", {"props": g})
        assert s.run(
            "MATCH (n:Entity {entity_id:$id}) RETURN count(n) AS c",
            {"id": ID_COLISION}).single()["c"] == 2, "el arnes no sembro la colision"
        # Una arista desde la gemela: sin ella, `relations_for_entity`
        # devolveria vacio por no haber nada, y el fail-closed no se
        # distinguiria de «no habia relaciones».
        s.run(
            "MATCH (a:Entity {entity_id:$c}), (b:Entity {entity_id:$v}) "
            "CREATE (a)-[:VENERA {visibility:'player', workspace:$ws, scope:'juego', "
            "relation_label_es:'venera'}]->(b)",
            {"c": ID_COLISION, "v": ID_VECINO, "ws": WS_DUR})
    return grafo_dur


def test_DOS_objetos_con_la_misma_identidad_durable_FAIL_CLOSED(grafo_colision):
    """LA REGLA DURA. Con 2+ no se escoge NINGUNO.

    Con el contrapeso dentro del mismo test: la entidad unica del fixture SI
    resuelve. Sin el, un proveedor que devolviera `None` para todo pasaria.
    """
    prov = _proveedor()
    assert prov.entity(ID_DURABLE) is not None, "no partimos de verde: nada resuelve"
    assert prov.entity(ID_FANTASMA) is None, "un id inexistente no puede resolver"

    resuelto = prov.entity(ID_COLISION)
    assert resuelto is None, (
        "el resolver ESCOGIO uno de los dos objetos que comparten identidad "
        f"durable ({resuelto.get('description') if resuelto else None}): eso es "
        "el secuestro de URL, no un empate"
    )


def test_el_fail_closed_tambien_con_el_ambito_de_workspace_puesto(grafo_colision):
    """El acotado por workspace no puede convertirse en un desempate.

    Es la ruta REAL: `PolicyFilteredProvider` siempre llama con el ambito del
    lector. Si el fail-closed solo viviera en la rama sin ambito, en produccion
    no protegeria nunca.
    """
    prov = _proveedor()
    ws = frozenset({WS_DUR})
    assert prov.entity(ID_DURABLE, workspaces=ws) is not None, "no partimos de verde"
    assert prov.entity(ID_COLISION, workspaces=ws) is None


def test_las_relaciones_tambien_fallan_cerradas_con_ancla_ambigua(grafo_colision):
    """Con dos anclas, `relations_for_entity` devolveria la UNION: relaciones de
    un objeto pintadas en la ficha de otro. Fail-closed."""
    prov = _proveedor()
    salientes, _ = prov.relations_for_entity(ID_DURABLE)
    assert salientes, "no partimos de verde: la entidad unica no trae relaciones"

    out, inc = prov.relations_for_entity(ID_COLISION)
    assert (out, inc) == ([], []), (
        f"se sirvieron relaciones de un ancla ambigua: {out} {inc}"
    )


# --- 5.2bis O2: las dos barreras preguntan sobre EL MISMO ambito ------------

#: Identificador AUTORADO, del estilo que ya existe en el repositorio
#: (`entity:ambar:corte-resina`): NO lleva el workspace dentro, al contrario que
#: los derivados por `resolution/provisional.py`. Dos bovedas pueden tener uno
#: igual sin que eso sea una colision de nada.
ID_AUTORADO = "entity:ambar:corte-resina"
WS_VECINO = "juego:otra-boveda"


@pytest.fixture
def grafo_id_autorado(grafo_dur):
    """El mismo id autorado en DOS workspaces distintos. No es una colision:
    son dos entidades legitimas de dos juegos que no se conocen."""
    with grafo_dur.session() as s:
        s.run("MATCH (n:Entity {workspace:$ws}) DETACH DELETE n", {"ws": WS_VECINO})
        for ws in (WS_DUR, WS_VECINO):
            s.run("CREATE (n:Entity $props)", {"props": {
                "entity_id": ID_AUTORADO, "canonical_name": f"Corte de resina ({ws})",
                "entity_type": "Object", "workspace": ws, "scope": "juego",
                "visibility": "player", "review_status": "reviewed", "confidence": 0.9}})
        s.run(
            "MATCH (a:Entity {entity_id:$a, workspace:$ws}), "
            "(b:Entity {entity_id:$b, workspace:$ws}) "
            "CREATE (a)-[:VENERA {visibility:'player', workspace:$ws, scope:'juego', "
            "relation_label_es:'venera'}]->(b)",
            {"a": ID_AUTORADO, "b": ID_VECINO, "ws": WS_DUR})
    yield grafo_dur
    with grafo_dur.session() as s:
        s.run("MATCH (n:Entity {workspace:$ws}) DETACH DELETE n", {"ws": WS_VECINO})


def test_un_id_AUTORADO_repetido_en_otra_boveda_NO_tumba_las_relaciones(grafo_id_autorado):
    """O2. Las dos barreras tienen que preguntar sobre el MISMO conjunto.

    Con la sonda de ambigüedad sin acotar por workspace, aqui pasaba esto:
    `entity()` resolvia la ficha (su Cypher SI filtra por workspace) y
    `relations_for_entity` declaraba el ancla ambigua --porque veia las dos
    bovedas-- y devolvia `[], []`. Ficha legitima con TODAS sus relaciones
    caidas. No era una fuga; era un defecto de disponibilidad causado por la
    propia defensa, y una incoherencia entre las dos barreras.
    """
    prov = _proveedor()
    ws = frozenset({WS_DUR})
    assert prov.entity(ID_AUTORADO, workspaces=ws) is not None, "la ficha ya no resuelve"

    salientes, _ = prov.relations_for_entity(ID_AUTORADO, workspaces=ws)
    assert salientes, (
        "la ficha resuelve pero llega sin relaciones: la sonda de ambigüedad "
        "esta mirando un ambito distinto del que uso el resolver"
    )

    # Y el fail-closed NO se ha aflojado: dentro de UN solo workspace, dos
    # anclas siguen siendo ambiguas. Sin esta linea, «acotar» podria haberse
    # convertido en «dejar de comprobar».
    with grafo_id_autorado.session() as s:
        s.run("CREATE (n:Entity $props)", {"props": {
            "entity_id": ID_AUTORADO, "canonical_name": "Corte de resina (bis)",
            "entity_type": "Object", "workspace": WS_DUR, "scope": "juego",
            "visibility": "player", "review_status": "reviewed", "confidence": 0.9}})
    assert prov.entity(ID_AUTORADO, workspaces=ws) is None
    assert prov.relations_for_entity(ID_AUTORADO, workspaces=ws) == ([], [])


def test_el_camino_REAL_por_HTTP_conserva_las_relaciones(panel_dur, grafo_id_autorado):
    """El mismo caso, pero por la cadena real: `PolicyFilteredProvider` tiene
    que pasar a la sonda EL MISMO ambito que le paso a `entity()`."""
    # CONTRAPESO PRIMERO: `ID_DURABLE` tiene una relacion hacia el MISMO
    # vecino, y su ficha si se pinta. Eso fija el marcador que hay que buscar;
    # sin el, un `not in` podria significar «la plantilla no pinta vecinos».
    control = panel_dur.get(f"/panel/entities/item/{ID_DURABLE}")
    assert control.status_code == 200
    assert "Kitsuki Yaruma" in control.text, (
        "el marcador de vecino no se pinta ni en el caso bueno: este test no "
        "puede distinguir nada"
    )

    r = panel_dur.get(f"/panel/entities/item/{ID_AUTORADO}")
    assert r.status_code == 200, f"la ficha no abre: {r.status_code}"
    assert "Kitsuki Yaruma" in r.text, (
        "la ficha abre sin su relacion: por el camino real, la sonda sigue "
        "preguntando sobre un ambito distinto del que uso el resolver"
    )


# --- 5.3 El secuestro, por HTTP y sobre la URL durable ----------------------

def test_EL_SECUESTRO_DE_URL_NO_OCURRE_POR_HTTP(panel_dur, grafo_dur):
    """De extremo a extremo: se inyecta la colision y la URL durable deja de
    resolver EN VEZ de resolver al objeto equivocado.

    El orden importa: primero se comprueba que la URL resuelve (verde de
    partida), luego se inyecta, y solo entonces se exige el 404. Sin el primer
    paso, un 404 podria significar «esta ruta nunca funciono».
    """
    url = f"/panel/entities/item/{ID_COLISION}"
    with grafo_dur.session() as s:
        s.run("CREATE (n:Entity $props)", {"props": _GEMELAS[0]})
    antes = panel_dur.get(url)
    assert antes.status_code == 200, f"no partimos de verde: {antes.status_code}"
    assert _GEMELAS[0]["description"] in antes.text

    with grafo_dur.session() as s:
        s.run("CREATE (n:Entity $props)", {"props": _GEMELAS[1]})

    despues = panel_dur.get(url)
    assert despues.status_code == 404, (
        f"la URL sigue sirviendo un objeto con la identidad duplicada "
        f"({despues.status_code}): eso es el secuestro"
    )
    for g in _GEMELAS:
        assert g["description"] not in despues.text, (
            "el cuerpo revela cual de las dos gemelas se habria servido"
        )
    # E indistinguible de «no existe»: mismo codigo y mismo cuerpo que un
    # identificador que no se ha sembrado jamas.
    fantasma = panel_dur.get(f"/panel/entities/item/{ID_FANTASMA}")
    assert fantasma.status_code == 404
    assert fantasma.content == despues.content, (
        "la ambiguedad se distingue de la inexistencia: la URL vuelve a ser un "
        "oraculo, ahora de duplicados"
    )

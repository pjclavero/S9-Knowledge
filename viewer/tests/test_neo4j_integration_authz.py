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
    dict(id="a_player", ws=WS, scope="partida", pid=P_A, vis="player"),
    dict(id="a_secret", ws=WS, scope="partida", pid=P_A, vis="secret"),
    dict(id="b_player", ws=WS, scope="partida", pid=P_B, vis="player"),
    dict(id="b_secret", ws=WS, scope="partida", pid=P_B, vis="secret"),
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
]


def _ctx(partida=None, **over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_partida=partida,
        allowed_partida_ids=frozenset({partida}) if partida else frozenset(),
        session_public=True,
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
            "CREATE (a)-[:VENERA {visibility:'player', workspace:$ws, scope:'partida', "
            "partida_id:$p, relation_label_es:'venera'}]->(l)", {"ws": WS, "p": P_A})
        s.run(
            "MATCH (a:Entity {entity_id:'a_player'}), (x:Entity {entity_id:'a_secret'}) "
            "CREATE (a)-[:OCULTA {visibility:'secret', workspace:$ws, scope:'partida', "
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


def _ids(prov, ctx):
    from app.authz.filtered_provider import PolicyFilteredProvider
    items, _ = PolicyFilteredProvider(prov, ctx).list_entities(WS, limit=1000)
    return {i.get("entity_id") or i.get("id") for i in items}


def test_revelacion_pasada_visible_y_futura_oculta(base):
    ids = _ids(base, _jugador_a(5))
    assert {"rev_0", "rev_3"} <= ids
    assert "rev_8" not in ids


def test_known_by_no_salta_la_barrera_historica_en_neo4j(base):
    """La propiedad de T2 que solo vale si se prueba sobre datos reales."""
    ids = _ids(base, _jugador_a(5, active_character="pc:ana"))
    assert "rev_8_conocido" not in ids


def test_can_view_future_si_la_salta(base):
    assert "rev_8" in _ids(base, _jugador_a(5, can_view_future=True))


def test_tope_cero_ve_lo_conocido_desde_el_inicio(base):
    ids = _ids(base, _jugador_a(0))
    assert "rev_0" in ids
    assert "rev_3" not in ids


def test_revelacion_corrupta_deniega_sin_error(base):
    ids = _ids(base, _jugador_a(5))
    assert "rev_corrupta" not in ids


def test_el_conteo_y_el_grafo_respetan_la_revelacion(base):
    from app.authz.filtered_provider import PolicyFilteredProvider

    prov = PolicyFilteredProvider(base, _jugador_a(5))
    n_visibles, _ = prov.counts(WS)
    assert n_visibles == len(_ids(base, _jugador_a(5)))
    nodos, _ = prov.graph(WS, limit=1000)
    assert "rev_8" not in {n.get("entity_id") or n.get("id") for n in nodos}


def test_el_acceso_por_id_no_esquiva_la_revelacion(base):
    """Lista y detalle deben coincidir: un ID directo no es una puerta trasera."""
    from app.authz.filtered_provider import PolicyFilteredProvider

    prov = PolicyFilteredProvider(base, _jugador_a(5))
    with base._driver.session() as s:  # type: ignore[attr-defined]
        eid = s.run(
            "MATCH (n:Entity {entity_id:'rev_8'}) RETURN elementId(n) AS id"
        ).single()["id"]
    assert prov.entity(eid) is None

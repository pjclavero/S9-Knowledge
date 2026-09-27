"""Tests del PolicyFilteredProvider: el filtro se aplica EN LA QUERY.

Demuestra que un viewer/otro personaje NO puede ver secretos, futuro ni
referencias no permitidas, NI por listado, NI por conteo, NI por búsqueda,
NI por acceso directo por ID.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.authz.filtered_provider import PolicyFilteredProvider
from app.policies.models import ViewerContext
from app.providers.mock_provider import MockGraphProvider

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rpg_visibility_graph.json"
WS = "campania_lab"

# IDs sensibles que un viewer del grupo alfa NO debe ver de ninguna forma.
HIDDEN = {
    "secret_villano",          # secreto sin conocimiento
    "secret_conocido_por_arden",  # secreto de OTRO personaje
    "narrator_nota",           # capa narrador
    "future_evento",           # sesión aún no revelada (known_from_session)
    "otra_boveda_node",        # otro workspace
}
# T1: `otro_grupo_npc` pasó de oculto a visible, y es un cambio querido. La
# pertenencia a una party dejó de ser una ACL: no concede acceso ni lo retira.
# Un NPC etiquetado con otro grupo no es material secreto -- si debe estar
# oculto, se declara con `visibility`, no con la etiqueta de grupo.
VISIBLE = {"pc_arden", "pc_bryn", "npc_taverna", "reference_regla", "otro_grupo_npc"}


@pytest.fixture
def base():
    return MockGraphProvider(FIXTURE)


def _viewer_bryn() -> ViewerContext:
    return ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_character="pc_bryn",
        max_visible_session=3,
        can_view_reference=True,
        can_view_lore=True,  # LORE-ANONIMO-DENEGADO: lector autenticado
        party_membership=frozenset({"grupo_alfa"}),
        session_public=True,
    )


def _admin() -> ViewerContext:
    return ViewerContext(role="admin", admin_full=True, session_public=True)


# --- Listado ---------------------------------------------------------------

def test_listado_no_incluye_ocultos(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    items, total = prov.list_entities(WS, limit=1000)
    ids = {i["id"] for i in items}
    assert ids == VISIBLE
    assert total == len(VISIBLE)
    assert not (ids & HIDDEN)


def test_admin_ve_todo_en_listado(base):
    prov = PolicyFilteredProvider(base, _admin())
    items, total = prov.list_entities(WS, limit=1000)
    # En este workspace hay 9 nodos (el 10º está en otra bóveda). Admin los ve
    # todos, incluidos secretos, narrador y futuro.
    assert total == 9
    ids = {i["id"] for i in items}
    assert HIDDEN - {"otra_boveda_node"} <= ids


# --- Conteo ----------------------------------------------------------------

def test_conteo_filtrado(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    n, e = prov.counts(WS)
    assert n == len(VISIBLE)      # no cuenta ocultos
    assert e == 1                 # sólo edge_publica (arden->taverna, ambos visibles)


def test_entity_types_no_filtran_ocultos(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    types = {t["entity_type"]: t["count"] for t in prov.entity_types(WS)}
    # Concept sólo existía en nodos secretos/narrador -> no debe aparecer.
    assert "Concept" not in types
    assert "Event" not in types   # future_evento oculto


# --- Búsqueda / autocomplete ----------------------------------------------

def test_busqueda_no_revela_secreto(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    # "villano" sólo aparece en secret_villano.
    assert prov.search(WS, "villano") == []
    # "sesión 5" / futuro
    assert prov.search(WS, "sesión 5") == []


def test_busqueda_admin_si_encuentra(base):
    prov = PolicyFilteredProvider(base, _admin())
    assert any(n["id"] == "secret_villano" for n in prov.search(WS, "villano"))


# --- Acceso directo por ID -------------------------------------------------

def test_acceso_por_id_secreto_devuelve_none(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    assert prov.entity("secret_villano") is None       # -> 404 en la API
    assert prov.entity("future_evento") is None
    assert prov.entity("narrator_nota") is None
    assert prov.entity("otra_boveda_node") is None


def test_otro_personaje_no_accede_a_secreto_ajeno(base):
    # Bryn NO ve el secreto que conoce Arden.
    bryn = PolicyFilteredProvider(base, _viewer_bryn())
    assert bryn.entity("secret_conocido_por_arden") is None
    # Arden SÍ (character_knowledge vía known_by).
    arden_ctx = ViewerContext(
        can_view_lore=True,  # LORE-ANONIMO-DENEGADO: lector autenticado
        role="viewer", allowed_workspaces=frozenset({WS}),
        active_character="pc_arden", max_visible_session=3,
        can_view_reference=True, party_membership=frozenset({"grupo_alfa"}),
        session_public=True,
    )
    arden = PolicyFilteredProvider(base, arden_ctx)
    assert arden.entity("secret_conocido_por_arden") is not None


# --- Relaciones ------------------------------------------------------------

def test_relaciones_filtran_secretas_y_extremos_ocultos(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    outgoing, incoming = prov.relations_for_entity("pc_arden")
    ids = {e["id"] for e in outgoing}
    assert ids == {"edge_publica"}          # edge_secreta y edge_a_secreto filtradas
    assert "edge_secreta" not in ids


def test_relaciones_de_nodo_oculto_vacias(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    out, inc = prov.relations_for_entity("secret_villano")
    assert out == [] and inc == []


# --- Fuentes / calidad -----------------------------------------------------

def test_fuentes_solo_de_nodos_visibles(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    sources = {s["source_id"] for s in prov.list_sources(WS)}
    assert "notas_dm_lab" not in sources     # sólo contenía secretos/narrador
    assert "guion_futuro_lab" not in sources  # futuro
    assert "sesion_01_lab" in sources


def test_quality_metrics_no_cuentan_ocultos(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn())
    m = prov.quality_metrics(WS)
    assert m["total_entities"] == len(VISIBLE)
    assert m["by_visibility"].get("secret", 0) == 0
    assert m["by_visibility"].get("narrator", 0) == 0


# --- Reautorización del ÁMBITO en `graph()`/`list_entities()` --------------
#
# Corte "el workspace no lo elige el cliente". Antes estos dos métodos
# delegaban el `workspace` recibido DIRECTAMENTE a la query del provider base
# -- a diferencia de `entity()`, que ya reautorizaba con `_scope_workspaces()`
# -- y lo único que impedía servir un workspace ajeno era el filtro nodo a
# nodo de `filter_nodes`. Estas pruebas demuestran que la protección ya NO
# depende solo de esa única capa: comprueban el efecto CON el filtro nodo a
# nodo desactivado (un doble de `VisibilityPolicy` que aprueba todo), que es
# la única forma de que una mutación real (quitar `can_view`) sea detectable.

OTRA_BOVEDA = "otra_boveda"


class _PoliticaQueLoAprueebaTodo:
    """Doble de `VisibilityPolicy`: simula que `can_view` está desactivado.

    Si la reautorización de ámbito de `graph()`/`list_entities()` no
    existiera, con esta política CUALQUIER nodo de CUALQUIER workspace pasaría
    íntegro. Es la mutación que la garantía tiene que sobrevivir sin ayuda del
    filtro nodo a nodo.
    """

    def filter_nodes(self, nodes, ctx):
        return list(nodes)

    def filter_edges(self, edges, visible_ids, ctx):
        return list(edges)


def test_graph_no_consulta_workspace_ajeno_aunque_el_filtro_nodo_a_nodo_este_apagado(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn(), policy=_PoliticaQueLoAprueebaTodo())
    nodes, edges = prov.graph(OTRA_BOVEDA)
    assert nodes == [] and edges == [], (
        "FUGA: con el filtro nodo a nodo desactivado, `graph()` sirvió un "
        "workspace fuera de `allowed_workspaces`. La protección dependía sólo "
        "de `filter_nodes`."
    )


def test_list_entities_no_consulta_workspace_ajeno_aunque_el_filtro_nodo_a_nodo_este_apagado(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn(), policy=_PoliticaQueLoAprueebaTodo())
    items, total = prov.list_entities(OTRA_BOVEDA, limit=1000)
    assert items == [] and total == 0, (
        "FUGA: con el filtro nodo a nodo desactivado, `list_entities()` sirvió "
        "un workspace fuera de `allowed_workspaces`."
    )


def test_graph_control_positivo_workspace_propio_sigue_pasando(base):
    """Simétrico obligatorio: el mismo doble, pero con el workspace PROPIO.

    Sin este control, "devuelve vacío siempre" pasaría la prueba de arriba.
    """
    prov = PolicyFilteredProvider(base, _viewer_bryn(), policy=_PoliticaQueLoAprueebaTodo())
    nodes, edges = prov.graph(WS)
    assert len(nodes) > 0, (
        "el control positivo no ve nada de su propio workspace: el banco no "
        "está midiendo nada"
    )


def test_list_entities_control_positivo_workspace_propio_sigue_pasando(base):
    prov = PolicyFilteredProvider(base, _viewer_bryn(), policy=_PoliticaQueLoAprueebaTodo())
    items, total = prov.list_entities(WS, limit=1000)
    assert total > 0, (
        "el control positivo no ve nada de su propio workspace: el banco no "
        "está midiendo nada"
    )


def test_admin_si_puede_pedir_otro_workspace_por_graph(base):
    """`admin_full` no está sujeto a esta reautorización (docs/75): ve todo."""
    prov = PolicyFilteredProvider(base, _admin())
    nodes, _ = prov.graph(OTRA_BOVEDA)
    assert any(n["id"] == "otra_boveda_node" for n in nodes)


# --- RONDA 2: LOS OCHO CAMINOS, NO DOS ------------------------------------
#
# La ronda 1 cerro `graph()` y `list_entities()`. Un barrido posterior midio
# que los SEIS restantes seguian entregando el workspace ajeno al provider
# base con el filtro de politica apagado: `search`, `entity_types`,
# `list_sources`, `source_detail`, `counts` y `quality_metrics`. Causa: los
# helpers `_visible_nodes` / `_visible_graph` llamaban al base directamente y
# se saltaban las dos guardas nuevas.
#
# La tabla mide los OCHO de una vez, y cada fila trae su CONTROL POSITIVO: sin
# el, "devolver vacio siempre" pasaria por arreglo.

FUENTE_AJENA = "sesion_gamma_lab"
FUENTE_PROPIA = "sesion_01_lab"


def _cuanto_ve(prov, ws, fuente):
    """Cuanto entrega cada metodo para `ws`. 0 = nada."""
    return {
        "graph": lambda: len(prov.graph(ws)[0]),
        "list_entities": lambda: prov.list_entities(ws, limit=1000)[1],
        "search": lambda: len(prov.search(ws, "a")),
        "entity_types": lambda: sum(t["count"] for t in prov.entity_types(ws)),
        "list_sources": lambda: len(prov.list_sources(ws)),
        "source_detail": lambda: (
            0 if prov.source_detail(ws, fuente) is None
            else prov.source_detail(ws, fuente)["entity_count"]
        ),
        "counts": lambda: prov.counts(ws)[0],
        "quality_metrics": lambda: prov.quality_metrics(ws)["total_entities"],
    }


LOS_OCHO_METODOS = [
    "graph", "list_entities", "search", "entity_types",
    "list_sources", "source_detail", "counts", "quality_metrics",
]


@pytest.mark.parametrize("metodo", LOS_OCHO_METODOS)
def test_ningun_metodo_entrega_el_workspace_ajeno_con_el_filtro_apagado(base, metodo):
    prov = PolicyFilteredProvider(base, _viewer_bryn(), policy=_PoliticaQueLoAprueebaTodo())
    visto = _cuanto_ve(prov, OTRA_BOVEDA, FUENTE_AJENA)[metodo]()
    assert visto == 0, (
        f"FUGA DE AMBITO en `{metodo}`: con el filtro nodo a nodo desactivado "
        f"entrego {visto} elementos de un workspace fuera de "
        f"`allowed_workspaces`. La proteccion dependia de una sola capa."
    )


@pytest.mark.parametrize("metodo", LOS_OCHO_METODOS)
def test_control_positivo_los_ocho_siguen_viendo_el_workspace_propio(base, metodo):
    """Sin esta mitad, un `return []` incondicional pasaria la tabla de arriba."""
    prov = PolicyFilteredProvider(base, _viewer_bryn(), policy=_PoliticaQueLoAprueebaTodo())
    visto = _cuanto_ve(prov, WS, FUENTE_PROPIA)[metodo]()
    assert visto > 0, (
        f"el control positivo de `{metodo}` no ve NADA de su propio "
        f"workspace: el banco no esta midiendo una ausencia, esta ciego"
    )


@pytest.mark.parametrize("metodo", LOS_OCHO_METODOS)
def test_admin_full_conserva_el_acceso_por_los_ocho_caminos(base, metodo):
    """`admin_full` no esta sujeto a esta reautorizacion (docs/75)."""
    prov = PolicyFilteredProvider(base, _admin())
    assert _cuanto_ve(prov, OTRA_BOVEDA, FUENTE_AJENA)[metodo]() > 0, (
        f"`{metodo}` le ha retirado a `admin_full` un acceso que la decision "
        f"declarada le concede"
    )

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
    "future_evento",           # sesión futura
    "otro_grupo_npc",          # otra party
    "otra_boveda_node",        # otro workspace
}
VISIBLE = {"pc_arden", "pc_bryn", "npc_taverna", "reference_regla"}


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

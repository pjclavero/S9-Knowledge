"""Tests de aislamiento entre partidas (M5a, docs/v3/49-multipartida-diseno.md
§2.6): motor de política puro + PolicyFilteredProvider en la query.

Cubre: capa juego DECLARADA (`scope="juego"`) visible dentro del workspace;
material de una partida visible SOLO con esa partida activa; nunca visible
cruzando partidas, ni por listado, conteo, grafo o acceso por ID.

M5c cambia una regla de raiz. Antes, "sin `partida_id`" se interpretaba como
capa juego, asi que un nodo al que le faltara el ambito se resolvia hacia lo
MAS abierto. Ahora el ambito se declara y su ausencia deniega. La consecuencia
--el material legacy queda mudo-- es deliberada y esta fijada abajo como test,
no como efecto colateral: `legacy_material_sin_partida` es el testigo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.authz.filtered_provider import PolicyFilteredProvider
from app.policies.engine import VisibilityPolicy
from app.policies.models import ViewerContext
from app.providers.mock_provider import MockGraphProvider

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "multipartida_graph.json"
WS = "juego:lab"
POLICY = VisibilityPolicy()


def _ctx(active_partida=None, **over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_partida=active_partida,
        allowed_partida_ids=frozenset({active_partida}) if active_partida else frozenset(),
        can_view_reference=True,
        session_public=True,
    )
    base.update(over)
    return ViewerContext(**base)


# --- Motor puro --------------------------------------------------------

def test_capa_juego_declarada_visible_sin_partida_activa():
    node = {"id": "n", "workspace": WS, "scope": "juego", "partida_id": None,
            "visibility": "player"}
    assert POLICY.can_view(node, _ctx()).visible


def test_material_legado_sin_scope_ya_no_es_visible():
    """El nucleo de M5c: la ausencia de ambito NO significa "de todos"."""
    node = {"id": "n", "workspace": WS, "visibility": "player"}  # sin scope
    d = POLICY.can_view(node, _ctx())
    assert not d.visible and d.reason == "scope_invalid"


def test_capa_juego_no_puede_arrastrar_una_partida():
    """Decir "soy de todos" y "soy de esta" a la vez es contradiccion, y la
    via "de todos" es la mas abierta: se deniega en vez de elegir una."""
    node = {"id": "n", "workspace": WS, "scope": "juego",
            "partida_id": "partida:uno", "visibility": "player"}
    d = POLICY.can_view(node, _ctx(active_partida="partida:uno"))
    assert not d.visible and d.reason == "scope_contradictorio"


def test_scope_desconocido_deniega():
    node = {"id": "n", "workspace": WS, "scope": "campania", "visibility": "player"}
    assert not POLICY.can_view(node, _ctx()).visible


def test_sin_workspace_legible_deniega():
    """La barrera de workspace tambien era fail-open: sin workspace, pasaba."""
    node = {"id": "n", "scope": "juego", "visibility": "player"}
    d = POLICY.can_view(node, _ctx())
    assert not d.visible and d.reason == "workspace_invalid"


def test_partida_ajena_oculta_sin_partida_activa():
    node = {"id": "n", "workspace": WS, "scope": "partida",
            "partida_id": "partida:uno", "visibility": "player"}
    d = POLICY.can_view(node, _ctx())
    assert not d.visible and d.reason == "partida_not_allowed"


def test_partida_propia_visible_con_partida_activa():
    node = {"id": "n", "workspace": WS, "scope": "partida",
            "partida_id": "partida:uno", "visibility": "player"}
    assert POLICY.can_view(node, _ctx(active_partida="partida:uno")).visible


def test_partida_otra_nunca_visible_aunque_haya_una_activa():
    node = {"id": "n", "workspace": WS, "scope": "partida",
            "partida_id": "partida:dos", "visibility": "player"}
    d = POLICY.can_view(node, _ctx(active_partida="partida:uno"))
    assert not d.visible and d.reason == "partida_not_allowed"


def test_admin_full_salta_barrera_de_partida():
    node = {"id": "n", "workspace": WS, "scope": "partida",
            "partida_id": "partida:uno", "visibility": "player"}
    ctx = ViewerContext(role="admin", admin_full=True)
    assert POLICY.can_view(node, ctx).visible


def test_conocimiento_de_personaje_no_salta_barrera_de_partida():
    # A diferencia de secret/narrator/future/party, la partida es como
    # workspace: ni el conocimiento del personaje la salta.
    node = {
        "id": "n", "workspace": WS, "scope": "partida", "partida_id": "partida:uno",
        "visibility": "player", "known_by": ["pc_conocedor"],
    }
    ctx = _ctx(active_character="pc_conocedor", character_knowledge=frozenset({"n"}))
    d = POLICY.can_view(node, ctx)
    assert not d.visible and d.reason == "partida_not_allowed"


# --- PolicyFilteredProvider: aislamiento real en cada método ------------

@pytest.fixture
def base():
    return MockGraphProvider(FIXTURE)


def _provider(base, active_partida=None):
    return PolicyFilteredProvider(base, _ctx(active_partida=active_partida))


def test_listado_partida_uno_ve_su_capa_mas_juego(base):
    prov = _provider(base, "partida:uno")
    items, total = prov.list_entities(WS, limit=1000)
    ids = {i["id"] for i in items}
    assert ids == {"lore_dios_sol", "partida1_pc_arden"}   # el legacy ya no
    assert total == 2
    assert "partida2_pc_bryn" not in ids


def test_listado_partida_dos_ve_su_capa_mas_juego_nunca_la_uno(base):
    prov = _provider(base, "partida:dos")
    items, _ = prov.list_entities(WS, limit=1000)
    ids = {i["id"] for i in items}
    assert ids == {"lore_dios_sol", "partida2_pc_bryn"}
    assert "partida1_pc_arden" not in ids


def test_sin_partida_activa_solo_capa_juego(base):
    prov = _provider(base, None)
    items, total = prov.list_entities(WS, limit=1000)
    ids = {i["id"] for i in items}
    assert ids == {"lore_dios_sol"}
    assert total == 1


def test_acceso_por_id_a_partida_ajena_es_404_no_visible(base):
    prov = _provider(base, "partida:uno")
    assert prov.entity("partida2_pc_bryn") is None
    assert prov.entity("partida1_pc_arden") is not None


def test_conteo_no_revela_material_de_otra_partida(base):
    prov_uno = _provider(base, "partida:uno")
    prov_dos = _provider(base, "partida:dos")
    n_uno, _ = prov_uno.counts(WS)
    n_dos, _ = prov_dos.counts(WS)
    assert n_uno == 2
    assert n_dos == 2  # simétrico: cada partida ve su propio material + juego


def test_grafo_filtra_relaciones_de_otra_partida(base):
    prov = _provider(base, "partida:uno")
    nodes, edges = prov.graph(WS, limit=1000)
    node_ids = {n["id"] for n in nodes}
    edge_ids = {e["id"] for e in edges}
    assert "partida2_pc_bryn" not in node_ids
    assert "edge_p2_interno" not in edge_ids
    assert "edge_p1_interno" in edge_ids


def test_admin_ve_las_dos_partidas_a_la_vez(base):
    admin_ctx = ViewerContext(role="admin", admin_full=True, session_public=True)
    prov = PolicyFilteredProvider(base, admin_ctx)
    items, total = prov.list_entities(WS, limit=1000)
    ids = {i["id"] for i in items}
    assert {"partida1_pc_arden", "partida2_pc_bryn"} <= ids
    assert total == 4


def test_el_material_legacy_queda_mudo_y_eso_es_la_decision(base):
    """Consecuencia aceptada de M5c, fijada aqui para que nadie la "arregle".

    El material anterior al modelo de ambito deja de ser legible por el visor.
    No se le inventa un scope ni se le concede una excepcion de compatibilidad:
    esa excepcion seria un camino permisivo permanente. Si hay que inspeccionar
    el legacy, se hace por acceso operativo auditado, no relajando la politica.
    """
    prov = _provider(base, None)
    assert prov.entity("legacy_material_sin_partida") is None
    assert prov.entity("lore_dios_sol") is not None   # lo declarado sigue vivo

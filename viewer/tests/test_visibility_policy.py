"""Tests unitarios del motor de política de visibilidad (lógica pura).

Cubre las 10 dimensiones: allowed_workspaces, active_character,
max_visible_session, can_view_secret, can_view_future, can_view_reference,
party_membership, character_knowledge, session_public, admin_full.
"""
from __future__ import annotations

from app.policies.engine import VisibilityPolicy
from app.policies.models import ViewerContext

POLICY = VisibilityPolicy()

WS = "campania_lab"


def _viewer(**over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_character="pc_bryn",
        max_visible_session=3,
        can_view_secret=False,
        can_view_future=False,
        can_view_reference=True,
        party_membership=frozenset({"grupo_alfa"}),
        character_knowledge=frozenset(),
        session_public=True,
    )
    base.update(over)
    return ViewerContext(**base)


def _node(**over):
    n = dict(
        id="n1", workspace=WS, visibility="player", session_index=1,
        party="grupo_alfa", is_public=True, known_by=["pc_bryn"],
    )
    n.update(over)
    return n


def test_admin_full_ve_todo():
    ctx = ViewerContext(role="admin", admin_full=True)
    secret = _node(id="s", visibility="secret", session_index=99, party="grupo_beta", workspace="otra")
    assert POLICY.can_view(secret, ctx).visible


def test_workspace_no_permitido_oculta():
    ctx = _viewer()
    n = _node(workspace="otra_boveda")
    d = POLICY.can_view(n, ctx)
    assert not d.visible and d.reason == "workspace_not_allowed"


def test_secreto_oculto_para_viewer():
    ctx = _viewer()
    n = _node(id="s", visibility="secret", known_by=[])
    assert not POLICY.can_view(n, ctx).visible


def test_secreto_visible_con_can_view_secret():
    ctx = _viewer(can_view_secret=True)
    n = _node(id="s", visibility="secret", known_by=[])
    assert POLICY.can_view(n, ctx).visible


def test_character_knowledge_desbloquea_secreto_propio():
    # El personaje conoce el nodo (known_by) -> lo ve pese a ser secreto.
    ctx = _viewer(active_character="pc_arden")
    n = _node(id="s", visibility="secret", known_by=["pc_arden"])
    assert POLICY.can_view(n, ctx).visible


def test_otro_personaje_no_ve_secreto_ajeno():
    ctx = _viewer(active_character="pc_bryn")
    n = _node(id="s", visibility="secret", known_by=["pc_arden"])
    assert not POLICY.can_view(n, ctx).visible


def test_narrator_oculto_para_viewer():
    ctx = _viewer()
    n = _node(id="nn", visibility="narrator", known_by=[])
    d = POLICY.can_view(n, ctx)
    assert not d.visible and d.reason == "narrator_only"


def test_referencia_requiere_permiso():
    n = _node(id="r", visibility="reference", party=None, known_by=[])
    assert POLICY.can_view(n, _viewer(can_view_reference=False)).reason == "reference_not_allowed"
    assert POLICY.can_view(n, _viewer(can_view_reference=True)).visible


def test_sesion_futura_oculta():
    ctx = _viewer(max_visible_session=3)
    n = _node(id="f", session_index=5, known_by=[])
    d = POLICY.can_view(n, ctx)
    assert not d.visible and d.reason == "future_session"


def test_sesion_futura_visible_con_can_view_future():
    ctx = _viewer(max_visible_session=3, can_view_future=True)
    n = _node(id="f", session_index=5, known_by=[])
    assert POLICY.can_view(n, ctx).visible


def test_party_ajena_oculta():
    ctx = _viewer(party_membership=frozenset({"grupo_alfa"}))
    n = _node(id="p", party="grupo_beta", is_public=False, known_by=[])
    d = POLICY.can_view(n, ctx)
    assert not d.visible and d.reason == "party_scoped"


def test_party_publica_visible_con_session_public():
    ctx = _viewer(party_membership=frozenset(), session_public=True)
    n = _node(id="p", party="grupo_beta", is_public=True, known_by=[])
    assert POLICY.can_view(n, ctx).visible


def test_anonimo_no_ve_protegido():
    anon = ViewerContext(
        role="anonymous", allowed_workspaces=frozenset({WS}),
        max_visible_session=0, session_public=True,
    )
    assert not POLICY.can_view(_node(visibility="secret", known_by=[]), anon).visible
    assert not POLICY.can_view(_node(visibility="narrator", known_by=[]), anon).visible
    assert not POLICY.can_view(_node(visibility="reference", party=None, known_by=[]), anon).visible


def test_filter_edges_requiere_ambos_extremos():
    ctx = _viewer()
    edge = {"id": "e", "from": "a", "to": "b", "workspace": WS, "visibility": "player"}
    assert POLICY.filter_edges([edge], {"a"}, ctx) == []       # falta b
    assert POLICY.filter_edges([edge], {"a", "b"}, ctx) == [edge]
    secret_edge = {"id": "e2", "from": "a", "to": "b", "workspace": WS, "visibility": "secret"}
    assert POLICY.filter_edges([secret_edge], {"a", "b"}, ctx) == []  # relación secreta

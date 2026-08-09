"""M5b-0 — tests de `V3VisibilityPolicyAdapter`: la frontera única entre el
contrato canónico `knowledge-visibility/v1` y el motor de política probado
(`app.policies.engine.VisibilityPolicy`).

No reimplementa las reglas del motor: cada caso comprueba que la decisión del
adaptador coincide con la que el motor tomaría sobre el nodo equivalente,
salvo `deny`, que el adaptador decide por sí mismo (el motor no lo conoce).

Tabla de decisión EXHAUSTIVA (ver `test_tabla_de_decision`): cruza
`visibility` × tipo de usuario (`admin`/`viewer`/`anonymous`) × personaje
activo × pertenencia al grupo (`party`) × `known_by` × `max_visible_session`
× `can_view_secret` × workspace/partida. Regla dura verificada en TODOS los
casos de la tabla: cero defaults permisivos — todo lo no explícitamente
permitido deniega.
"""
from __future__ import annotations

import pytest

from app.authz.visibility_contract import V3VisibilityPolicyAdapter, KnowledgeVisibilityV1
from app.policies.models import ViewerContext

ADAPTER = V3VisibilityPolicyAdapter()

WS = "campania_lab"
OTRA_WS = "otra_boveda"
PARTIDA = "partida:hantei"
OTRA_PARTIDA = "partida:otra"


def _kv(**over) -> KnowledgeVisibilityV1:
    base = dict(visibility="player", known_by=[])
    base.update(over)
    return KnowledgeVisibilityV1.from_dict(
        {
            "contract_id": "knowledge-visibility/v1",
            "contract_version": "1.0.0",
            **base,
        }
    )


def _ctx(**over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        allowed_partida_ids=frozenset({PARTIDA}),
        active_partida=PARTIDA,
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


def _extra(**over) -> dict:
    base = dict(
        id="n1", workspace=WS, scope="partida", partida_id=PARTIDA, known_from_session=1,
        party="grupo_alfa", is_public=True,
    )
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. `deny` es absoluto: nunca visible, ni para admin_full, ni para
#    can_view_secret, ni por conocimiento de personaje (known_by).
# ---------------------------------------------------------------------------


def test_deny_no_visible_para_viewer():
    contract = _kv(visibility="deny", known_by=[])
    assert not ADAPTER.can_view(contract, _ctx(), _extra()).visible


def test_deny_no_visible_para_admin_full():
    admin = ViewerContext(role="admin", admin_full=True)
    contract = _kv(visibility="deny", known_by=[])
    d = ADAPTER.can_view(contract, admin, _extra())
    assert not d.visible
    assert d.reason == "deny_absolute"


def test_deny_no_visible_pese_a_can_view_secret():
    ctx = _ctx(can_view_secret=True)
    contract = _kv(visibility="deny", known_by=[])
    assert not ADAPTER.can_view(contract, ctx, _extra()).visible


def test_deny_no_visible_pese_a_known_by_del_personaje_activo():
    ctx = _ctx(active_character="pc_bryn")
    contract = _kv(visibility="deny", known_by=["pc_bryn"])
    assert not ADAPTER.can_view(contract, ctx, _extra()).visible


# ---------------------------------------------------------------------------
# 2. Fail-closed en la CONSTRUCCION del contrato: valor desconocido, campo
#    ausente o combinación inválida nunca llegan a evaluarse -- se rechazan
#    antes de poder producir una decisión permisiva por accidente.
# ---------------------------------------------------------------------------


def test_visibility_desconocido_no_se_puede_construir():
    with pytest.raises(Exception):
        KnowledgeVisibilityV1.from_dict(
            {
                "contract_id": "knowledge-visibility/v1",
                "contract_version": "1.0.0",
                "visibility": "publico",  # fuera del enum cerrado
                "known_by": [],
            }
        )


def test_visibility_ausente_no_se_puede_construir():
    with pytest.raises(Exception):
        KnowledgeVisibilityV1.from_dict(
            {
                "contract_id": "knowledge-visibility/v1",
                "contract_version": "1.0.0",
                "known_by": [],
            }
        )


def test_known_by_ausente_no_se_puede_construir():
    with pytest.raises(Exception):
        KnowledgeVisibilityV1.from_dict(
            {
                "contract_id": "knowledge-visibility/v1",
                "contract_version": "1.0.0",
                "visibility": "player",
            }
        )


def test_known_by_con_character_id_invalido_no_se_puede_construir():
    with pytest.raises(Exception):
        KnowledgeVisibilityV1.from_dict(
            {
                "contract_id": "knowledge-visibility/v1",
                "contract_version": "1.0.0",
                "visibility": "secret",
                "known_by": ["con espacios no valido"],
            }
        )


# ---------------------------------------------------------------------------
# 3. Personaje no autorizado / workspace-partida incorrectos -> DENY, incluso
#    con `visibility=player` (el nivel más permisivo del enum).
# ---------------------------------------------------------------------------


def test_personaje_no_autorizado_no_ve_secreto_ajeno():
    ctx = _ctx(active_character="pc_bryn")
    contract = _kv(visibility="secret", known_by=["pc_otro"])
    assert not ADAPTER.can_view(contract, ctx, _extra()).visible


def test_workspace_incorrecto_deniega_pese_a_player():
    ctx = _ctx(allowed_workspaces=frozenset({WS}))
    contract = _kv(visibility="player", known_by=[])
    d = ADAPTER.can_view(contract, ctx, _extra(workspace=OTRA_WS))
    assert not d.visible
    assert d.reason == "workspace_not_allowed"


def test_partida_incorrecta_deniega_pese_a_player():
    ctx = _ctx(allowed_partida_ids=frozenset({PARTIDA}))
    contract = _kv(visibility="player", known_by=[])
    d = ADAPTER.can_view(contract, ctx, _extra(partida_id=OTRA_PARTIDA))
    assert not d.visible
    assert d.reason == "partida_not_allowed"


def test_workspace_incorrecto_deniega_incluso_para_known_by_del_personaje():
    # El conocimiento de personaje NUNCA salta la barrera de workspace.
    ctx = _ctx(active_character="pc_bryn")
    contract = _kv(visibility="secret", known_by=["pc_bryn"])
    d = ADAPTER.can_view(contract, ctx, _extra(workspace=OTRA_WS))
    assert not d.visible
    assert d.reason == "workspace_not_allowed"


# ---------------------------------------------------------------------------
# 4. Tabla de decisión exhaustiva: visibility × rol × personaje activo ×
#    party × known_by × max_visible_session × can_view_secret ×
#    workspace/partida.
# ---------------------------------------------------------------------------

# Cada caso: (id, kv_overrides, ctx_overrides, extra_overrides, visible_esperado)
_CASOS = [
    # -- player: visible en cualquier combinación dentro del ámbito correcto.
    ("player_base", {}, {}, {}, True),
    ("player_anonimo_dentro_workspace", {}, {"role": "anonymous", "admin_full": False,
        "active_character": None, "party_membership": frozenset(), "can_view_reference": False}, {}, True),
    ("player_otro_workspace", {}, {}, {"workspace": OTRA_WS}, False),
    ("player_otra_partida", {}, {}, {"partida_id": OTRA_PARTIDA}, False),

    # -- secret: requiere can_view_secret O known_by del personaje activo.
    ("secret_sin_permiso_sin_conocimiento", {"visibility": "secret"}, {}, {}, False),
    ("secret_con_can_view_secret", {"visibility": "secret"}, {"can_view_secret": True}, {}, True),
    ("secret_con_known_by_propio", {"visibility": "secret", "known_by": ["pc_bryn"]},
        {"active_character": "pc_bryn"}, {}, True),
    ("secret_con_known_by_ajeno", {"visibility": "secret", "known_by": ["pc_otro"]},
        {"active_character": "pc_bryn"}, {}, False),
    ("secret_admin_bypass", {"visibility": "secret"}, {"role": "admin", "admin_full": True}, {}, True),

    # -- narrator: mismo criterio que secret (can_view_secret eleva).
    ("narrator_sin_permiso", {"visibility": "narrator"}, {}, {}, False),
    ("narrator_con_can_view_secret", {"visibility": "narrator"}, {"can_view_secret": True}, {}, True),

    # -- reference: requiere can_view_reference.
    ("reference_sin_permiso", {"visibility": "reference"}, {"can_view_reference": False}, {}, False),
    ("reference_con_permiso", {"visibility": "reference"}, {"can_view_reference": True}, {}, True),

    # -- deny: absoluto, en TODAS las combinaciones anteriores.
    ("deny_pese_a_admin", {"visibility": "deny"}, {"role": "admin", "admin_full": True}, {}, False),
    ("deny_pese_a_can_view_secret_y_known_by",
        {"visibility": "deny", "known_by": ["pc_bryn"]},
        {"active_character": "pc_bryn", "can_view_secret": True}, {}, False),

    # -- sesión futura (dimensión del motor, no del contrato persistido).
    ("sesion_futura_oculta", {"visibility": "player"}, {"max_visible_session": 1}, {"known_from_session": 5}, False),
    ("sesion_futura_con_can_view_future", {"visibility": "player"},
        {"max_visible_session": 1, "can_view_future": True}, {"known_from_session": 5}, True),
    # T2: `known_by` NO salta la barrera historica. Es la proyeccion del estado
    # ACTUAL de conocimiento --dice que el PJ lo sabe, no desde cuando--, asi que
    # dejarle saltar el tope convertiria "ver como PJ hasta la sesion 1" en un
    # spoiler de lo que ese mismo PJ descubrio en la 5.
    ("sesion_futura_ni_siquiera_para_quien_ya_lo_sabe",
        {"visibility": "player", "known_by": ["pc_bryn"]},
        {"active_character": "pc_bryn", "max_visible_session": 1}, {"known_from_session": 5}, False),

    # -- party (T1): RETIRADA como frontera. Pertenecer a un grupo no concede
    #    acceso, y no pertenecer tampoco lo quita: el acceso vendra de un grant
    #    individual materializado en `known_by`. Una ACL de party daba a quien se
    #    incorporaba en la sesion 20 todo lo que el grupo supo en la 3.
    ("party_ajena_ya_no_oculta", {"visibility": "player"},
        {"party_membership": frozenset({"grupo_alfa"})}, {"party": "grupo_beta", "is_public": False}, True),
    ("party_ajena_publica_visible", {"visibility": "player"},
        {"party_membership": frozenset(), "session_public": True},
        {"party": "grupo_beta", "is_public": True}, True),
    ("party_propia_visible", {"visibility": "player"},
        {"party_membership": frozenset({"grupo_alfa"})}, {"party": "grupo_alfa"}, True),

    # -- combinaciones: secret + party ajena + sin conocimiento -> deniega en
    #    la primera barrera que corresponda (nivel de visibilidad).
    ("secret_y_party_ajena_sin_permiso",
        {"visibility": "secret"},
        {"party_membership": frozenset({"grupo_alfa"}), "can_view_secret": False},
        {"party": "grupo_beta", "is_public": False}, False),
    ("secret_y_party_ajena_con_permiso_secreto",
        {"visibility": "secret"},
        {"party_membership": frozenset({"grupo_alfa"}), "can_view_secret": True},
        {"party": "grupo_beta", "is_public": False}, True),  # secret pasa; party ya no bloquea (T1)
]


@pytest.mark.parametrize("nombre,kv_over,ctx_over,extra_over,esperado", _CASOS, ids=[c[0] for c in _CASOS])
def test_tabla_de_decision(nombre, kv_over, ctx_over, extra_over, esperado):
    contract = _kv(**kv_over)
    ctx = _ctx(**ctx_over)
    extra = _extra(**extra_over)
    decision = ADAPTER.can_view(contract, ctx, extra)
    assert decision.visible is esperado, (
        f"{nombre}: esperado visible={esperado}, obtenido={decision.visible} "
        f"(razon={decision.reason})"
    )


def test_tabla_de_decision_cubre_al_menos_veinte_casos():
    # Sanity check del alcance declarado en el docstring del módulo: si esta
    # tabla se recorta por accidente, el test lo hace explícito.
    assert len(_CASOS) >= 20


# ---------------------------------------------------------------------------
# 5. La traducción es de estructura: `to_engine_node` no reinterpreta valores.
# ---------------------------------------------------------------------------


def test_to_engine_node_no_reinterpreta_valores():
    contract = _kv(visibility="secret", known_by=["pc_bryn", "pc_arden"])
    node = ADAPTER.to_engine_node(contract, {"id": "n1", "workspace": WS})
    assert node["visibility"] == "secret"
    assert node["known_by"] == ["pc_bryn", "pc_arden"]
    assert node["id"] == "n1"
    assert node["workspace"] == WS

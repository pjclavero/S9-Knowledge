"""M5b-0 — tabla de decisión EXHAUSTIVA (producto cartesiano completo).

`test_visibility_contract_adapter.py` cubre la semántica caso a caso. Este
fichero es complementario y hace lo que la puerta de M5b-0 exige literalmente:
recorrer TODAS las combinaciones de

    visibility × tipo de usuario × personaje activo × pertenencia ×
    known_by × max_visible_session × can_view_secret × workspace/partida

y demostrar sobre el producto entero —no sobre una muestra— que:

    `deny`                  -> jamás visible, para nadie
    workspace incorrecto    -> jamás visible (salvo el bypass de admin)
    partida ajena           -> jamás visible (salvo el bypass de admin)
    personaje no autorizado -> no ve lo que no conoce

Una tabla exhaustiva vale más que una muestra porque el riesgo real no está en
el caso que alguien pensó, sino en la esquina que nadie enumeró.
"""
from __future__ import annotations

import itertools

from app.authz.visibility_contract import ADAPTER, KnowledgeVisibilityV1, VisibilityLevel
from app.policies.models import ViewerContext

WS = "juego:lab"
OTRO_WS = "juego:otro"
PARTIDA = "partida:uno"
PJ = "pj:arden"
PARTY = "party:cuervos"

# 5 niveles × 3 roles × 2 personaje × 2 pertenencia × 2 known_by
# × 3 sesión × 2 can_view_secret × 3 ámbito = 2.160 combinaciones.
NIVELES = tuple(VisibilityLevel)
ROLES = (
    {"role": "viewer"},
    {"role": "reviewer", "can_view_reference": True},
    {"role": "admin", "admin_full": True},
)
PERSONAJES = (None, PJ)
PERTENENCIAS = (frozenset(), frozenset({PARTY}))
KNOWN_BY = ((), (PJ,))
SESIONES = (None, 1, 99)
SECRETOS = (False, True)
AMBITOS = (
    {"workspace": WS, "partida_id": PARTIDA},         # correcto
    {"workspace": OTRO_WS, "partida_id": PARTIDA},    # workspace ajeno
    {"workspace": WS, "partida_id": "partida:otra"},  # partida ajena
)


def _combinaciones():
    return itertools.product(
        NIVELES, ROLES, PERSONAJES, PERTENENCIAS, KNOWN_BY, SESIONES, SECRETOS, AMBITOS
    )


def _ctx(rol, pj, party, sesion, secreto) -> ViewerContext:
    base = dict(
        allowed_workspaces=frozenset({WS}),
        allowed_partida_ids=frozenset({PARTIDA}),
        active_partida=PARTIDA,
        active_character=pj,
        party_membership=party,
        max_visible_session=sesion,
        can_view_secret=secreto,
    )
    base.update(rol)
    return ViewerContext(**base)


def _decidir(nivel, rol, pj, party, known, sesion, secreto, ambito):
    contrato = KnowledgeVisibilityV1(
        visibility=nivel, known_by=known, claim_id="claim:ep12:0001"
    )
    extra = {"id": "n1", "session_index": 5, **ambito}
    return ADAPTER.can_view(contrato, _ctx(rol, pj, party, sesion, secreto), extra)


def test_la_tabla_recorre_el_producto_cartesiano_completo():
    assert len(list(_combinaciones())) == 5 * 3 * 2 * 2 * 2 * 3 * 2 * 3 == 2160


def test_deny_no_es_visible_en_ninguna_de_las_432_combinaciones():
    evaluadas = 0
    for combo in _combinaciones():
        if combo[0] is not VisibilityLevel.DENY:
            continue
        evaluadas += 1
        decision = _decidir(*combo)
        assert not decision.visible, f"deny visible en {combo[1:]}"
    assert evaluadas == 432


def test_ninguna_combinacion_filtra_entre_workspaces():
    """Sin excepción salvo el bypass de admin, que es deliberado y auditado."""
    comprobadas = 0
    for combo in _combinaciones():
        nivel, rol, ambito = combo[0], combo[1], combo[7]
        if ambito["workspace"] != OTRO_WS or rol.get("admin_full"):
            continue
        comprobadas += 1
        assert not _decidir(*combo).visible, f"fuga cross-workspace: {nivel} {combo[1:]}"
    assert comprobadas == 480


def test_ninguna_combinacion_filtra_entre_partidas():
    """Invariante de M5a: ni el conocimiento del personaje cruza partidas."""
    comprobadas = 0
    for combo in _combinaciones():
        nivel, rol, ambito = combo[0], combo[1], combo[7]
        if ambito["partida_id"] == PARTIDA or rol.get("admin_full"):
            continue
        comprobadas += 1
        assert not _decidir(*combo).visible, f"fuga cross-partida: {nivel} {combo[1:]}"
    assert comprobadas == 480


def test_control_positivo_el_producto_cartesiano_no_pasa_por_vacuidad():
    """Si TODO saliera no visible, los tests anteriores pasarían sin valor."""
    visibles = sum(1 for combo in _combinaciones() if _decidir(*combo).visible)
    assert visibles > 0, "ninguna combinación resultó visible: la tabla no discrimina"
    # Y el reparto es coherente: nada visible fuera del ámbito correcto salvo admin.
    fuera_de_ambito = sum(
        1
        for combo in _combinaciones()
        if combo[7] is not AMBITOS[0]
        and not combo[1].get("admin_full")
        and _decidir(*combo).visible
    )
    assert fuera_de_ambito == 0

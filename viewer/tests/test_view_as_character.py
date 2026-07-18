"""Modo admin "ver como personaje": solo lectura, auditado y conforme a contrato.

- El evento emitido valida contra el contrato review-audit-event v1 usando el
  validador ÚNICO (contracts/review-ingest/v1/validator.py), SIN modificarlo.
- La simulación aplica exactamente las restricciones del personaje encarnado:
  el admin NO ve secretos ajenos mientras "ve como" un viewer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.authz.context import context_for_simulated_character
from app.authz.filtered_provider import PolicyFilteredProvider
from app.authz.simulation import build_view_as_character_event
from app.providers.mock_provider import MockGraphProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "contracts" / "review-ingest" / "v1"
if str(CONTRACT_DIR) not in sys.path:
    sys.path.insert(0, str(CONTRACT_DIR))

import validator as contract_validator  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rpg_visibility_graph.json"
WS = "campania_lab"


def test_evento_view_as_character_valida_contra_contrato():
    event = build_view_as_character_event(
        workspace=WS,
        admin_actor_id="s9admin",
        simulated_character="pc_bryn",
        event_id="evt_view_001",
        max_visible_session=3,
        request_id="req_001",
    )
    assert event["event_type"] == "VIEW_AS_CHARACTER"
    assert event["actor_type"] == "HUMAN"
    # No lanza -> conforme a schema + chequeos semánticos del contrato.
    contract_validator.validate_document(event)
    assert contract_validator.is_valid(event)


def test_evento_rechaza_secretos_en_metadata():
    event = build_view_as_character_event(
        workspace=WS, admin_actor_id="s9admin",
        simulated_character="pc_bryn", event_id="evt_view_002",
    )
    event["metadata"]["password"] = "no-deberia-estar"
    with pytest.raises(contract_validator.ContractError):
        contract_validator.validate_document(event)


def test_simulacion_es_solo_lectura_y_respeta_politica():
    # Admin "ve como" el personaje pc_bryn: NO debe ver secretos ni futuro.
    ctx = context_for_simulated_character(
        default_workspace=WS,
        allowed_workspaces={WS},
        active_character="pc_bryn",
        max_visible_session=3,
        party_membership={"grupo_alfa"},
        character_knowledge=None,
    )
    assert ctx.admin_full is False        # el bypass de admin queda desactivado
    assert ctx.simulated is True

    prov = PolicyFilteredProvider(MockGraphProvider(FIXTURE), ctx)
    # El provider filtrado no expone escritura alguna: es GraphProvider read-only.
    assert not hasattr(prov, "write")
    assert prov.entity("secret_villano") is None
    assert prov.entity("future_evento") is None
    items, _ = prov.list_entities(WS, limit=1000)
    ids = {i["id"] for i in items}
    assert "secret_villano" not in ids and "future_evento" not in ids

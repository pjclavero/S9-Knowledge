# -*- coding: utf-8 -*-
"""Modelos Python de los contratos `v3-internal-v1`.

Roundtrip, serializacion estable y pruebas de mutacion sobre los dataclasses.
Los mismos documentos que valida el gate de JSON Schema
(`contracts/knowledge-v3/v1/tests/`) se validan aqui a traves de los modelos:
un solo cuerpo de ejemplos, dos puertas.
"""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import (  # noqa: E402
    CONTRACT_CLASSES,
    CONTRACT_VERSION,
    CONTRACTS_DIR,
    ClaimProposal,
    EntityMention,
    EntityResolution,
    EvidenceFragment,
    FactAssertion,
    GameProfile,
    GraphMutationPlan,
    Provider,
    SourceAsset,
    SourceEpisode,
    V3ContractError,
    canonical_json,
    parse_document,
    provider_step,
    seal_plan,
)


def _load_fixtures():
    path = CONTRACTS_DIR / "tests" / "v3_fixtures.py"
    spec = importlib.util.spec_from_file_location("s9k_v3_fixtures", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s9k_v3_fixtures"] = mod
    spec.loader.exec_module(mod)
    return mod


fixtures = _load_fixtures()

#: Fixture -> clase esperada. Cubre los nueve contratos.
CASES = {
    "source_asset_pdf": SourceAsset,
    "source_asset_personal_audio": SourceAsset,
    "source_episode_text": SourceEpisode,
    "source_episode_audio": SourceEpisode,
    "evidence_fragment_text": EvidenceFragment,
    "evidence_fragment_ocr": EvidenceFragment,
    "entity_mention": EntityMention,
    "claim_proposal": ClaimProposal,
    "claim_proposal_abstained": ClaimProposal,
    "claim_proposal_visual": ClaimProposal,
    "entity_resolution_link": EntityResolution,
    "entity_resolution_provisional": EntityResolution,
    "fact_assertion": FactAssertion,
    "fact_assertion_superseded": FactAssertion,
    "graph_mutation_plan_approved": GraphMutationPlan,
    "graph_mutation_plan_not_approved": GraphMutationPlan,
    "game_profile_generic": GameProfile,
}


def doc(name: str) -> dict:
    return fixtures.VALID_BUILDERS[name]()


# ==========================================================================
# Cobertura de la familia
# ==========================================================================
def test_nine_contracts_registered():
    assert len(CONTRACT_CLASSES) == 9
    assert set(CASES.values()) == set(CONTRACT_CLASSES.values())


def test_contract_ids_match_the_json_schemas():
    from knowledge_v3.contracts.base import schema_validator

    assert set(CONTRACT_CLASSES) == set(schema_validator.CONTRACT_SCHEMAS)


def test_contract_version_is_the_v1_of_the_v3_family():
    assert CONTRACT_VERSION.startswith("1.")
    for name in CASES:
        assert doc(name)["contract_version"] == CONTRACT_VERSION


def test_provider_kinds_are_exactly_three():
    assert {p.value for p in Provider} == {"local", "ollama", "external"}


def test_provider_step_builds_a_valid_entry():
    entry = provider_step("x", Provider.OLLAMA, "s9k.extractor", "3.0.0", ["claim"], model="qwen2.5:7b")
    assert entry["provider"] == "ollama"
    assert entry["produced"] == ["claim"]


# ==========================================================================
# Roundtrip y determinismo
# ==========================================================================
@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_roundtrip_dict_is_exact(name: str):
    cls = CASES[name]
    obj = cls.from_dict(doc(name))
    assert obj.to_dict() == doc(name)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_roundtrip_json_returns_an_identical_object(name: str):
    cls = CASES[name]
    obj = cls.from_dict(doc(name))
    again = cls.from_json(obj.to_json())
    assert again == obj
    assert again.to_json() == obj.to_json()


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_serialization_is_byte_stable(name: str):
    cls = CASES[name]
    obj = cls.from_dict(doc(name))
    first = obj.to_json()
    for _ in range(3):
        assert obj.to_json() == first
    # Reconstruir desde un dict con las claves en otro orden no cambia un byte.
    shuffled = {k: v for k, v in reversed(list(doc(name).items()))}
    assert cls.from_dict(shuffled).to_json() == first


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_json_is_canonical(name: str):
    obj = CASES[name].from_dict(doc(name))
    raw = obj.to_json()
    assert raw == canonical_json(json.loads(raw))
    # Claves ordenadas en el nivel raiz: el orden no depende del dataclass.
    keys = list(json.loads(raw))
    assert keys == sorted(keys)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_parse_document_dispatches_by_contract_id(name: str):
    obj = parse_document(doc(name))
    assert isinstance(obj, CASES[name])


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_document_hash_is_reproducible(name: str):
    a = CASES[name].from_dict(doc(name))
    b = CASES[name].from_dict(doc(name))
    assert a.document_hash() == b.document_hash()


# ==========================================================================
# Mutacion: el contrato es CERRADO
# ==========================================================================
@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_unknown_field_is_rejected(name: str):
    data = doc(name)
    data["campo_que_no_existe"] = 1
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize(
    "field", ["workspace", "contract_version", "source_hash", "provider_trace", "source_asset_id"]
)
@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_missing_envelope_field_is_rejected(name: str, field: str):
    data = doc(name)
    data.pop(field)
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_wrong_contract_id_is_rejected(name: str):
    data = doc(name)
    data["contract_id"] = "source-asset/v3-internal-v2"
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_wrong_major_version_is_rejected(name: str):
    data = doc(name)
    data["contract_version"] = "2.0.0"
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_empty_workspace_is_rejected(name: str):
    data = doc(name)
    data["workspace"] = ""
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_hash_without_algorithm_is_rejected(name: str):
    data = doc(name)
    data["source_hash"] = {"value": "0" * 64}
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_secret_in_metadata_is_rejected(name: str):
    data = doc(name)
    data["metadata"] = {"password": "hunter2"}
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


def test_from_dict_of_another_contract_is_rejected():
    with pytest.raises(V3ContractError):
        SourceAsset.from_dict(doc("entity_mention"))


def test_parse_document_without_contract_id_is_rejected():
    with pytest.raises(V3ContractError):
        parse_document({"workspace": "leyenda"})


def test_from_json_rejects_broken_json():
    with pytest.raises(V3ContractError):
        SourceAsset.from_json("{no es json")


# ==========================================================================
# Reglas semanticas a traves de los modelos
# ==========================================================================
def test_asset_policy_helper():
    asset = SourceAsset.from_dict(doc("source_asset_pdf"))
    assert asset.allows_external_providers() is False


def test_personal_data_asset_cannot_open_external_providers():
    data = doc("source_asset_personal_audio")
    data["processing_policy"]["allow_external_providers"] = True
    with pytest.raises(V3ContractError):
        SourceAsset.from_dict(data)


def test_mention_best_type():
    mention = EntityMention.from_dict(doc("entity_mention"))
    assert mention.best_type() == "Character"


def test_claim_helpers():
    claim = ClaimProposal.from_dict(doc("claim_proposal"))
    assert claim.best_predicate() == "MEMBER_OF"
    assert claim.best_direction() == "SUBJECT_TO_OBJECT"
    assert claim.producing_provider()["provider"] == "ollama"


def test_abstained_claim_cannot_propose_a_predicate():
    data = doc("claim_proposal_abstained")
    data["predicate_candidates"] = [{"predicate": "MEMBER_OF", "confidence": 0.9}]
    with pytest.raises(V3ContractError):
        ClaimProposal.from_dict(data)


def test_provisional_resolution_helper():
    res = EntityResolution.from_dict(doc("entity_resolution_provisional"))
    assert res.is_provisional() is True
    assert res.selected_entity_id is None


def test_assertion_open_interval():
    a = FactAssertion.from_dict(doc("fact_assertion"))
    assert a.is_open_interval() is True
    b = FactAssertion.from_dict(doc("fact_assertion_superseded"))
    assert b.is_open_interval() is False


def test_game_profile_domain_and_range():
    profile = GameProfile.from_dict(doc("game_profile_generic"))
    assert profile.allows("MEMBER_OF", "Character", "Faction") is True
    assert profile.allows("MEMBER_OF", "Location", "Faction") is False
    assert "HAS_MEMBER" in profile.predicate_names()


# ==========================================================================
# GraphMutationPlan: lo que el writer exigira
# ==========================================================================
def test_plan_is_signed_locally_and_intact():
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_approved"))
    assert plan.approved is True
    assert plan.signed_locally() is True
    assert plan.signature_is_intact() is True
    assert plan.idempotency_keys() == ["idem:assertion:0001"]


def test_plan_sealing_is_idempotent():
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_approved"))
    assert plan.sealed().to_json() == plan.to_json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace", "otro"),
        ("source_asset_id", "asset:otro"),
        ("engine_version", "0.0.1"),
        ("ontology_version", "core-0.0.1"),
        ("game_profile", "otro"),
        ("collection_id", "collection:otra"),
    ],
)
def test_tampering_a_signed_field_breaks_the_plan(field, value):
    data = doc("graph_mutation_plan_approved")
    data[field] = value
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(data)


def test_plan_without_signature_is_rejected():
    data = doc("graph_mutation_plan_approved")
    data.pop("local_approval")
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_plan_signed_by_an_external_provider_is_rejected():
    data = doc("graph_mutation_plan_approved")
    data["local_approval"]["approved_by"]["provider"] = "external"
    # Resellado: se prueba la regla del firmante, no la deteccion de manipulacion.
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_plan_with_duplicate_idempotency_key_is_rejected():
    data = doc("graph_mutation_plan_approved")
    op = dict(data["mutation_operations"][0], operation_id="op:0002")
    data["mutation_operations"].append(op)
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_plan_operation_must_hang_from_an_accept_decision():
    data = doc("graph_mutation_plan_approved")
    data["mutation_operations"][0]["decision_id"] = "decision:0002"  # ABSTAIN
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_not_approved_plan_is_a_legitimate_document():
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_not_approved"))
    assert plan.approved is False
    assert plan.signature_is_intact() is True

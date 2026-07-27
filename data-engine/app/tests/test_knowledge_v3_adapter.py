# -*- coding: utf-8 -*-
"""Adaptador V3 -> `relation-candidate/internal-v1`.

La salida se valida contra el contrato v1 REAL (`relations/contracts.py`), no
contra una copia: si el adaptador produjese algo que v1 no acepta, estos tests
se pondrian rojos.

Incluye un cierre explicito: el contrato v1 sigue teniendo exactamente 20 campos
y la misma `SCHEMA_VERSION`. Adaptar no es tocar.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import fields as dataclass_fields

import pytest

pytest.importorskip("jsonschema")

from relations.contracts import (  # noqa: E402
    SCHEMA_VERSION as V1_SCHEMA_VERSION,
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)

from knowledge_v3.adapters import (  # noqa: E402
    V3AdapterError,
    claim_to_relation_candidate,
    claim_with_resolutions_to_relation_candidate,
    entity_id_from_resolution,
)
from knowledge_v3.contracts import (  # noqa: E402
    CONTRACTS_DIR,
    ClaimProposal,
    EntityResolution,
    EvidenceFragment,
)


def _load_fixtures():
    path = CONTRACTS_DIR / "tests" / "v3_fixtures.py"
    spec = importlib.util.spec_from_file_location("s9k_v3_fixtures_adapter", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s9k_v3_fixtures_adapter"] = mod
    spec.loader.exec_module(mod)
    return mod


fixtures = _load_fixtures()


def claim() -> ClaimProposal:
    return ClaimProposal.from_dict(fixtures.claim_proposal())


def visual_claim() -> ClaimProposal:
    return ClaimProposal.from_dict(fixtures.claim_proposal_visual())


def evidence() -> EvidenceFragment:
    return EvidenceFragment.from_dict(fixtures.evidence_fragment())


def ocr_evidence() -> EvidenceFragment:
    return EvidenceFragment.from_dict(fixtures.evidence_fragment_ocr())


def subject_resolution() -> EntityResolution:
    return EntityResolution.from_dict(fixtures.entity_resolution())


def object_resolution() -> EntityResolution:
    return EntityResolution.from_dict(fixtures.entity_resolution_provisional())


def adapt() -> RelationCandidate:
    return claim_with_resolutions_to_relation_candidate(
        claim(), evidence(), subject_resolution(), object_resolution()
    )


# ==========================================================================
# El contrato v1 sigue intacto
# ==========================================================================
def test_v1_contract_is_untouched():
    assert V1_SCHEMA_VERSION == "internal-1.0.0"
    assert len(dataclass_fields(RelationCandidate)) == 20


def test_adapter_output_has_exactly_the_twenty_v1_fields():
    out = adapt().to_dict()
    assert len(out) == 20
    assert set(out) == {f.name for f in dataclass_fields(RelationCandidate)}


# ==========================================================================
# Camino feliz
# ==========================================================================
def test_adapted_candidate_is_valid_under_v1():
    candidate = adapt()
    candidate.validate()  # lanza si no cumple el contrato v1
    assert isinstance(candidate, RelationCandidate)


def test_adapted_candidate_roundtrips_through_v1():
    candidate = adapt()
    again = RelationCandidate.from_json(candidate.to_json())
    assert again.to_dict() == candidate.to_dict()


def test_adaptation_is_deterministic():
    assert adapt().to_json() == adapt().to_json()
    assert json.loads(adapt().to_json()) == adapt().to_dict()


def test_field_mapping_is_the_expected_one():
    c = adapt()
    src_claim = claim()
    ev = evidence()
    assert c.subject_id == "entity:daiki"
    assert c.object_id == "provisional:resolution:consejo-umbra"
    assert c.subject_type == "Character"
    assert c.object_type == "Faction"
    assert c.predicate == "MEMBER_OF"           # primer candidato, ya normalizado
    assert c.direction == Direction.SUBJECT_TO_OBJECT
    assert c.confidence == src_claim.confidence
    assert c.negated is True
    assert c.epistemic_status == EpistemicStatus.ASSERTED
    assert c.workspace == src_claim.workspace
    assert c.source_id == src_claim.source_asset_id
    assert c.source_segment == src_claim.episode_id
    assert c.source_page == ev.page
    assert c.evidence_text == ev.literal_text
    assert (c.evidence_start, c.evidence_end) == (ev.start, ev.end)
    assert c.extraction_method == ExtractionMethod.LLM_LOCAL   # provider=ollama
    assert c.model == "qwen2.5:7b"
    assert c.temporal_scope is None


def test_information_loss_is_flagged_not_silent():
    flags = adapt().validation_flags
    assert flags == sorted(flags), "los flags deben ir ordenados (determinismo)"
    assert "V3_ADAPTED" in flags
    assert "V3_MULTIPLE_PREDICATES" in flags     # habia 2 predicados candidatos
    assert "V3_HAS_ALTERNATIVES" in flags        # habia lecturas alternativas
    assert "V3_REVIEW_REQUIRED" in flags
    assert "V3_PROVISIONAL_OBJECT" in flags
    assert "V3_PROVISIONAL_SUBJECT" not in flags


def test_visual_claim_is_degraded_to_hypothetical_and_flagged():
    candidate = claim_to_relation_candidate(
        visual_claim(),
        ocr_evidence(),
        subject_entity_id="entity:daiki",
        object_entity_id="entity:torre-de-umbra",
        subject_type="Character",
        object_type="Location",
    )
    candidate.validate()
    # VISUAL_INFERRED no existe en v1: se degrada al valor mas conservador.
    assert candidate.epistemic_status == EpistemicStatus.HYPOTHETICAL
    assert "V3_VISUAL_INFERRED" in candidate.validation_flags
    # Y el proveedor externo queda registrado, no disimulado.
    assert candidate.extraction_method == ExtractionMethod.NVIDIA
    assert "V3_EXTERNAL_PROVIDER" in candidate.validation_flags


def test_temporal_expressions_are_carried_into_temporal_scope():
    src = claim()
    src.temporal_expressions = [
        {"text": "durante la Era del Ciervo", "kind": "INTERVAL", "valid_from": None,
         "valid_to": None, "fragment_id": "fragment:p12:0"}
    ]
    src.validate()
    candidate = claim_to_relation_candidate(
        src, evidence(), subject_entity_id="entity:a", object_entity_id="entity:b"
    )
    assert candidate.temporal_scope == src.temporal_expressions


def test_provisional_id_is_derived_not_invented():
    res = object_resolution()
    assert entity_id_from_resolution(res) == f"provisional:{res.resolution_id}"


# ==========================================================================
# Mutacion: lo que el adaptador debe RECHAZAR
# ==========================================================================
def test_abstained_claim_cannot_be_adapted():
    src = ClaimProposal.from_dict(fixtures.claim_proposal_abstained())
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            src, evidence(), subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_claim_without_predicate_cannot_be_adapted():
    src = claim()
    src.predicate_candidates = []
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            src, evidence(), subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_evidence_must_be_cited_by_the_claim():
    ev = evidence()
    ev.fragment_id = "fragment:ajeno"
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            claim(), ev, subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_evidence_from_another_workspace_is_rejected():
    ev = evidence()
    ev.workspace = "otro-workspace"
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            claim(), ev, subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_evidence_from_another_episode_is_rejected():
    ev = evidence()
    ev.episode_id = "episode:otro"
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            claim(), ev, subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_evidence_with_another_source_hash_is_rejected():
    ev = evidence()
    ev.source_hash = fixtures.h("otro-asset")
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            claim(), ev, subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_same_entity_on_both_sides_is_rejected():
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            claim(), evidence(), subject_entity_id="entity:a", object_entity_id="entity:a"
        )


def test_resolution_under_review_does_not_fix_identity():
    res = subject_resolution()
    res.action = "REVIEW"
    res.selected_entity_id = None
    with pytest.raises(V3AdapterError):
        entity_id_from_resolution(res)


def test_resolution_from_another_workspace_is_rejected():
    res = object_resolution()
    res.workspace = "otro-workspace"
    with pytest.raises(V3AdapterError):
        claim_with_resolutions_to_relation_candidate(
            claim(), evidence(), subject_resolution(), res
        )


def test_unknown_provider_in_trace_is_rejected():
    src = claim()
    src.provider_trace = [dict(src.provider_trace[-1], provider="openai")]
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            src, evidence(), subject_entity_id="entity:a", object_entity_id="entity:b"
        )


def test_claim_without_provider_trace_is_rejected():
    src = claim()
    src.provider_trace = []
    with pytest.raises(V3AdapterError):
        claim_to_relation_candidate(
            src, evidence(), subject_entity_id="entity:a", object_entity_id="entity:b"
        )

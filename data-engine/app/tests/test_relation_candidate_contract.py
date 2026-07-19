# -*- coding: utf-8 -*-
"""Tests del contrato interno `relation-candidate/internal-v1`.

Cubren: casos validos + round-trip determinista, un caso invalido por regla,
negacion, temporalidad, direccion y compatibilidad futura (campo desconocido).
No tocan extractor, LLM, ensemble ni Neo4j.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.contracts import (  # noqa: E402
    RelationCandidate,
    RelationContractError,
    Direction,
    ExtractionMethod,
    EpistemicStatus,
    CANONICAL_CONSENSUS_STATES,
    REFLEXIVE_PREDICATES,
    normalize_predicate,
    SCHEMA_VERSION,
    DOCUMENT_TYPE,
)


def _base(**overrides):
    """Construye un candidato valido base; overrides ajustan campos."""
    data = dict(
        subject_id="ent:akodo",
        subject_type="Character",
        predicate="MEMBER_OF",
        object_id="ent:clan_leon",
        object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT,
        confidence=0.82,
        evidence_text="Akodo pertenece al Clan Leon",
        evidence_start=0,
        evidence_end=28,
        source_id="src:doc1",
        source_page=12,
        source_segment="seg:0007",
        extraction_method=ExtractionMethod.LLM_LOCAL,
        model="qwen2.5@7b",
        negated=False,
        temporal_scope=None,
        epistemic_status=EpistemicStatus.ASSERTED,
        workspace="l5r",
        validation_flags=[],
    )
    data.update(overrides)
    return RelationCandidate(**data)


# --------------------------------------------------------------------------
# Casos VALIDOS + round-trip determinista
# --------------------------------------------------------------------------
def test_valid_basic_passes():
    rc = _base()
    assert rc.validate() is rc


def test_valid_ontology_without_evidence_text():
    # Metodo ONTOLOGY no exige evidence_text.
    rc = _base(extraction_method=ExtractionMethod.ONTOLOGY, evidence_text="", evidence_start=0, evidence_end=0)
    rc.validate()


def test_valid_undirected_and_nvidia_and_null_page():
    rc = _base(
        direction=Direction.UNDIRECTED,
        extraction_method=ExtractionMethod.NVIDIA,
        source_page=None,
        model=None,
    )
    rc.validate()


def test_roundtrip_deterministic():
    rc = _base(validation_flags=["low_evidence", "review"])
    rc.validate()
    j1 = rc.to_json()
    rc2 = RelationCandidate.from_json(j1)
    j2 = rc2.to_json()
    assert j1 == j2
    assert rc.to_dict() == rc2.to_dict()


def test_to_json_sorts_keys():
    rc = _base()
    j = rc.to_json()
    keys = list(json.loads(j).keys())
    assert keys == sorted(keys)


def test_contract_has_exactly_20_fields():
    rc = _base()
    assert len(rc.to_dict()) == 20
    from dataclasses import fields
    assert len(fields(RelationCandidate)) == 20


# --------------------------------------------------------------------------
# Casos INVALIDOS: uno por regla
# --------------------------------------------------------------------------
def test_invalid_empty_workspace():
    with pytest.raises(RelationContractError, match="workspace"):
        _base(workspace="").validate()


def test_invalid_confidence_over_one():
    with pytest.raises(RelationContractError, match="confidence"):
        _base(confidence=1.5).validate()


def test_invalid_confidence_below_zero():
    with pytest.raises(RelationContractError, match="confidence"):
        _base(confidence=-0.1).validate()


def test_invalid_subject_equals_object():
    with pytest.raises(RelationContractError, match="reflexivo"):
        _base(subject_id="ent:x", object_id="ent:x").validate()


def test_invalid_offsets_inverted():
    with pytest.raises(RelationContractError, match="evidence_start"):
        _base(evidence_start=30, evidence_end=5).validate()


def test_invalid_negative_offset():
    with pytest.raises(RelationContractError, match=">= 0"):
        _base(evidence_start=-1, evidence_end=5).validate()


def test_invalid_missing_evidence_with_llm_local():
    with pytest.raises(RelationContractError, match="evidence_text"):
        _base(extraction_method=ExtractionMethod.LLM_LOCAL, evidence_text="   ").validate()


def test_invalid_predicate_not_normalized():
    with pytest.raises(RelationContractError, match="normalizado"):
        _base(predicate="member of").validate()


def test_invalid_unknown_extraction_method():
    with pytest.raises(RelationContractError, match="extraction_method"):
        _base(extraction_method="MAGIC").validate()


def test_invalid_direction():
    with pytest.raises(RelationContractError, match="direction"):
        _base(direction="SIDEWAYS").validate()


def test_invalid_epistemic_status():
    with pytest.raises(RelationContractError, match="epistemic_status"):
        _base(epistemic_status="MAYBE").validate()


def test_invalid_missing_source_segment():
    with pytest.raises(RelationContractError, match="source_segment"):
        _base(source_segment="").validate()


def test_invalid_missing_source_id():
    with pytest.raises(RelationContractError, match="source_id"):
        _base(source_id="").validate()


def test_invalid_empty_subject_id():
    with pytest.raises(RelationContractError, match="subject_id"):
        _base(subject_id="").validate()


def test_invalid_negated_not_bool():
    with pytest.raises(RelationContractError, match="negated"):
        _base(negated="yes").validate()


def test_invalid_unknown_subject_type():
    with pytest.raises(RelationContractError, match="subject_type"):
        _base(subject_type="Dragon").validate()


# --------------------------------------------------------------------------
# Negacion, temporalidad, direccion
# --------------------------------------------------------------------------
def test_negation_marks_non_affirmation():
    # "Akodo no pertenece al Clan Grulla" -> negated=True, no afirmacion.
    rc = _base(
        object_id="ent:clan_grulla",
        object_type="Faction",
        evidence_text="Akodo no pertenece al Clan Grulla",
        negated=True,
    )
    rc.validate()
    assert rc.negated is True
    assert rc.is_affirmative() is False


def test_asserted_positive_is_affirmative():
    rc = _base()
    rc.validate()
    assert rc.is_affirmative() is True


def test_rumored_is_not_affirmative():
    # "Se dice que Bayushi traiciono..." -> RUMORED.
    rc = _base(epistemic_status=EpistemicStatus.RUMORED)
    rc.validate()
    assert rc.is_affirmative() is False


def test_temporal_scope_preserved_roundtrip():
    # "Fue vasallo de Hantei antes de la guerra" -> temporal_scope.before.
    scope = {"before": "la_guerra"}
    rc = _base(predicate="VASSAL_OF", object_id="ent:hantei", temporal_scope=scope)
    rc.validate()
    rc2 = RelationCandidate.from_json(rc.to_json())
    assert rc2.temporal_scope == scope


def test_direction_values_roundtrip():
    for d in (Direction.SUBJECT_TO_OBJECT, Direction.OBJECT_TO_SUBJECT, Direction.UNDIRECTED):
        rc = _base(direction=d)
        rc.validate()
        rc2 = RelationCandidate.from_json(rc.to_json())
        assert rc2.direction == d


def test_reflexive_predicates_empty_by_default():
    assert REFLEXIVE_PREDICATES == ()


# --------------------------------------------------------------------------
# Predicado / normalizacion
# --------------------------------------------------------------------------
def test_normalize_predicate_idempotent():
    once = normalize_predicate("member of the clan")
    assert once == "MEMBER_OF_THE_CLAN"
    assert normalize_predicate(once) == once


def test_normalize_predicate_handles_dashes():
    assert normalize_predicate("allied-with") == "ALLIED_WITH"


# --------------------------------------------------------------------------
# Compatibilidad futura: campo desconocido en from_json
# --------------------------------------------------------------------------
def test_unknown_field_rejected_on_from_json():
    rc = _base()
    payload = json.loads(rc.to_json())
    payload["totally_unknown"] = "x"
    with pytest.raises(RelationContractError, match="desconocidos"):
        RelationCandidate.from_json(json.dumps(payload))


def test_missing_required_field_rejected_on_from_dict():
    rc = _base()
    payload = rc.to_dict()
    del payload["workspace"]
    with pytest.raises(RelationContractError, match="faltan campos"):
        RelationCandidate.from_dict(payload)


def test_validation_flags_optional_in_from_dict():
    rc = _base()
    payload = rc.to_dict()
    del payload["validation_flags"]
    rc2 = RelationCandidate.from_dict(payload)
    assert rc2.validation_flags == []


# --------------------------------------------------------------------------
# Reutilizacion de estados de consenso (no duplica external_ai)
# --------------------------------------------------------------------------
def test_reuses_canonical_consensus_states():
    # Debe coincidir con los canonicos definidos en external_ai.models.
    from external_ai.models import CONSENSUS_STATES as EXTERNAL
    assert CANONICAL_CONSENSUS_STATES == tuple(EXTERNAL)
    # Los cinco canonicos STRONG/PARTIAL/CONFLICT/INVALID/HUMAN.
    assert len(CANONICAL_CONSENSUS_STATES) == 5


def test_contract_metadata_constants():
    assert SCHEMA_VERSION == "internal-1.0.0"
    assert DOCUMENT_TYPE == "relation-candidate"

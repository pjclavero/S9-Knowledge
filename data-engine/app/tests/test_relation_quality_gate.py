"""Prioridad 2.1 — Quality gate de relaciones en auto_decider.

El benchmark real (docs/34) demostro F1 de relaciones ~= 0 y 3 relaciones
autoaprobadas erroneamente. Hasta que exista una politica explicita que
confirme F1 rel >= 0.60, P rel >= 0.75 y 0 relaciones invalidas autoaprobadas,
NINGUNA relacion puede ser auto_approve: se desvia a needs_review con motivo
`relation_autoapproval_disabled_quality_gate`. Las entidades siguen su politica
normal. No se bloquea la extraccion de relaciones, solo su autoaprobacion.
"""
from __future__ import annotations
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.auto_decider import decide_one
from review.models import Candidate, ValidationResult, ResolutionResult

GATE_REASON = "relation_autoapproval_disabled_quality_gate"


def _cand(**kw) -> Candidate:
    d = dict(
        candidate_id="rel000000001", source_id="src_reg", segment_id="reg_seg_001",
        workspace="test_ws", kind="entity", name="Doji Satsume", entity_type="Character",
        confidence=0.90, evidence="Doji Satsume llega al castillo con paso firme.",
        timestamp_start="00:01:00", timestamp_end="00:02:00", source_kind="audio",
    )
    d.update(kw)
    return Candidate(**d)


def _rel(**kw) -> Candidate:
    base = dict(
        kind="relation", name=None, entity_type=None,
        from_entity="Doji Satsume", to_entity="Clan Grulla", relation_type="MEMBER_OF",
        confidence=0.90, evidence="Doji Satsume, miembro del Clan Grulla, preside la corte.",
    )
    base.update(kw)
    return _cand(**base)


def _ok_vr(cid="rel000000001") -> ValidationResult:
    return ValidationResult(candidate_id=cid, valid="valid")


def _ok_rr(cid="rel000000001") -> ResolutionResult:
    return ResolutionResult(candidate_id=cid, action="create_new",
                            reason="sin match en Neo4j", neo4j_available=True)


def _decide(c):
    return decide_one(c, _ok_vr(c.candidate_id), _ok_rr(c.candidate_id))


# 1. Relacion valida de esquema → revision
def test_valid_schema_relation_goes_to_review():
    d = _decide(_rel())
    assert d.decision == "needs_review"
    assert GATE_REASON in d.decision_reason


# 2. Relacion de alta confianza → revision
def test_high_confidence_relation_goes_to_review():
    d = _decide(_rel(confidence=0.99))
    assert d.decision == "needs_review"
    assert GATE_REASON in d.decision_reason


# 3. Relacion generada por LLM → revision
def test_llm_relation_goes_to_review():
    d = _decide(_rel(origin="local", confidence=0.95))
    assert d.decision == "needs_review"
    assert GATE_REASON in d.decision_reason


# 4. Relacion generada por heuristico → revision
def test_heuristic_relation_goes_to_review():
    d = _decide(_rel(relation_type="KNOWS", to_entity="Bayushi Kachiko"))
    assert d.decision == "needs_review"
    assert GATE_REASON in d.decision_reason


# 5. Relacion generada por hybrid → revision
def test_hybrid_relation_goes_to_review():
    d = _decide(_rel(relation_type="ALLIED_WITH", to_entity="Clan Leon"))
    assert d.decision == "needs_review"
    assert GATE_REASON in d.decision_reason


# 6. Ninguna relacion aparece en autoaprobados
def test_no_relation_is_ever_autoapproved():
    rels = [
        _rel(relation_type="MEMBER_OF"),
        _rel(relation_type="LOCATED_IN", from_entity="Ciudad Moto", to_entity="Rokugan"),
        _rel(relation_type="FOUGHT_AT", from_entity="Kakita Asuka", to_entity="Ciudad Moto"),
        _rel(relation_type="OWNS", from_entity="Doji Satsume", to_entity="Espada Ancestral"),
    ]
    decisions = [_decide(r) for r in rels]
    assert all(d.decision != "auto_approve" for d in decisions)
    assert all(d.decision == "needs_review" for d in decisions)


# 7. Las entidades siguen su politica normal (una entidad valida se autoaprueba)
def test_entities_follow_normal_policy():
    d = _decide(_cand(kind="entity", name="Kakita Asuka", entity_type="Character"))
    assert d.decision == "auto_approve"
    assert GATE_REASON not in d.decision_reason

"""Tests de endurecimiento del auto_decider, validator y resolver.

Cobertura:
1.  Stopword 'Todo' (Character, conf=0.9) → auto_reject con reason 'stopword'
2.  Single-token débil sin use_existing/glossary → needs_review
3.  Single-token con use_existing exacto → auto_approve
4.  Single-token con glossary_match → auto_approve
5.  Compuesto fuerte + valid + resolver create_new → auto_approve con decision_reason poblado
6.  Duplicado ambiguo (2 matches similares) → needs_review con 'possible_duplicate'
7.  Origin=external → nunca auto_approve (needs_review)
8.  Origin=imported → nunca auto_approve directo (needs_review)
9.  Validator: HAS_FOUGHT → Location → invalid con sugerencia
10. Validator: evidence corta (<= 10 chars) → invalid
11. Validator: workspace ausente → invalid
12. Validator: origin inválido → invalid
13. Decision.to_dict / from_dict conserva decision_reason y origin
14. weak=True en candidato → auto_reject
15. Compuesto fuerte + use_existing exacto → auto_approve con 'resolver_exact_match'
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate, ValidationResult, ResolutionResult, Decision
from review.validator import validate_candidate
from review.auto_decider import decide_one, CONF_AUTO_APPROVE, CONF_NEEDS_REVIEW
from review.resolver import _resolve_one


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cand(
    name="Doji Satsume",
    etype="Character",
    conf=0.92,
    evidence="El personaje aparece en escena con armadura",
    origin="local",
    weak=False,
    glossary_match=False,
    workspace="test",
    kind="entity",
    **kwargs,
) -> Candidate:
    return Candidate(
        candidate_id="test001",
        source_id="src",
        segment_id="seg001",
        workspace=workspace,
        kind=kind,
        name=name,
        entity_type=etype,
        confidence=conf,
        evidence=evidence,
        timestamp_start="00:05:00",
        timestamp_end="00:09:00",
        source_kind="audio",
        origin=origin,
        weak=weak,
        glossary_match=glossary_match,
        **kwargs,
    )


def _valid_vr(cid="test001") -> ValidationResult:
    return ValidationResult(candidate_id=cid, valid="valid")


def _rr(action="create_new", match_type="none", alternatives=None, cid="test001") -> ResolutionResult:
    return ResolutionResult(
        candidate_id=cid,
        action=action,
        match_type=match_type,
        alternatives=alternatives or [],
        reason="test",
        neo4j_available=True,
    )


def _use_existing_rr(match_type="exact", cid="test001") -> ResolutionResult:
    return ResolutionResult(
        candidate_id=cid,
        action="use_existing",
        matched_canonical="Doji",
        match_score=1.0,
        match_type=match_type,
        alternatives=[],
        reason="match exacto",
        neo4j_available=True,
    )


# ── TEST 1: Stopword → auto_reject ────────────────────────────────────────────

def test_stopword_nunca_autoaprueba():
    """'Todo' como Character con conf 0.9 debe ser auto_reject, jamás approve."""
    c = _cand(name="Todo", etype="Character", conf=0.9,
              evidence="El personaje conocido como Todo aparece brevemente")
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision in ("auto_reject", "needs_review"), \
        f"'Todo' stopword nunca debe ser auto_approve, got: {d.decision}"
    assert "stopword" in d.decision_reason, \
        f"decision_reason debe contener 'stopword', got: {d.decision_reason}"


# ── TEST 2: Single-token débil sin use_existing ni glossary → needs_review ────

def test_single_token_debil_sin_match_es_needs_review():
    """Single-token Character sin use_existing exacto ni glossary_match → needs_review."""
    c = _cand(name="Doji", etype="Character", conf=0.92,
              evidence="El personaje Doji actúa decisivamente en la escena",
              glossary_match=False)
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision == "needs_review", \
        f"Single-token 'Doji' sin match exacto debe ser needs_review, got: {d.decision}: {d.reason}"
    assert "single_token_candidate" in d.decision_reason, \
        f"decision_reason debe contener 'single_token_candidate', got: {d.decision_reason}"


# ── TEST 3: Single-token con use_existing exacto → auto_approve ───────────────

def test_single_token_con_use_existing_exacto_autoaprueba():
    """Single-token Character con use_existing match_type=exact → auto_approve."""
    c = _cand(name="Doji", etype="Character", conf=0.92,
              evidence="El personaje Doji actúa decisivamente en la escena",
              glossary_match=False)
    vr = _valid_vr()
    rr = _use_existing_rr(match_type="exact")
    d = decide_one(c, vr, rr)
    assert d.decision == "auto_approve", \
        f"Single-token con use_existing exacto debe ser auto_approve, got: {d.decision}: {d.reason}"
    assert "resolver_exact_match" in d.decision_reason


# ── TEST 4: Single-token con glossary_match → auto_approve ───────────────────

def test_single_token_con_glossary_autoaprueba():
    """Single-token Location con glossary_match=True → auto_approve."""
    c = _cand(name="Kyuden", etype="Location", conf=0.92,
              evidence="El castillo Kyuden domina el horizonte del norte",
              glossary_match=True)
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision == "auto_approve", \
        f"Single-token con glossary_match debe ser auto_approve, got: {d.decision}: {d.reason}"
    assert "glossary_match" in d.decision_reason


# ── TEST 5: Compuesto fuerte + valid + create_new → auto_approve ──────────────

def test_compuesto_fuerte_autoaprueba_con_decision_reason():
    """Nombre compuesto fuerte + valid + create_new → auto_approve con decision_reason."""
    c = _cand(name="Doji Satsume", etype="Character", conf=0.92,
              evidence="El personaje Doji Satsume aparece en la escena del consejo")
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision == "auto_approve", \
        f"Compuesto fuerte debe ser auto_approve, got: {d.decision}: {d.reason}"
    # decision_reason debe tener al menos: valid_schema, timestamp_valid, strong_compound_name, not_stopword
    assert "valid_schema" in d.decision_reason, f"Falta valid_schema en {d.decision_reason}"
    assert "timestamp_valid" in d.decision_reason, f"Falta timestamp_valid en {d.decision_reason}"
    assert "strong_compound_name" in d.decision_reason, f"Falta strong_compound_name en {d.decision_reason}"
    assert "not_stopword" in d.decision_reason, f"Falta not_stopword en {d.decision_reason}"
    assert "resolver_create_new" in d.decision_reason, f"Falta resolver_create_new en {d.decision_reason}"


# ── TEST 6: Duplicado ambiguo (needs_review con possible_duplicate) ───────────

def test_duplicado_ambiguo_es_needs_review_con_reason():
    """2+ alternativas en resolver → needs_review con 'possible_duplicate' en reasons."""
    c = _cand(name="Doji Satsume", conf=0.92)
    vr = _valid_vr()
    rr = ResolutionResult(
        candidate_id="test001",
        action="needs_review",
        alternatives=["Doji Satsume", "Satsume Doji"],
        reason="múltiples matches (2)",
        neo4j_available=True,
    )
    d = decide_one(c, vr, rr)
    assert d.decision == "needs_review", f"Duplicado ambiguo debe ser needs_review, got: {d.decision}"
    assert "possible_duplicate" in d.decision_reason, \
        f"decision_reason debe contener 'possible_duplicate', got: {d.decision_reason}"


# ── TEST 7: Origin=external → needs_review, nunca auto_approve ───────────────

def test_origin_external_nunca_autoaprueba():
    """Candidato origin=external nunca puede ser auto_approve."""
    c = _cand(name="Doji Satsume", conf=0.92, origin="external")
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision != "auto_approve", \
        f"origin=external nunca debe ser auto_approve, got: {d.decision}"
    assert "external_origin" in d.decision_reason, \
        f"decision_reason debe contener 'external_origin', got: {d.decision_reason}"


# ── TEST 8: Origin=imported → needs_review, nunca auto_approve directo ────────

def test_origin_imported_nunca_autoaprueba():
    """Candidato origin=imported nunca puede ser auto_approve directo."""
    c = _cand(name="Doji Satsume", conf=0.92, origin="imported")
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision != "auto_approve", \
        f"origin=imported nunca debe ser auto_approve directo, got: {d.decision}"


# ── TEST 9: Validator HAS_FOUGHT → Location → invalid con sugerencia ──────────

def test_validator_has_fought_location_es_invalid():
    """HAS_FOUGHT con to_type=Location debe producir invalid con sugerencia FOUGHT_AT."""
    c = Candidate(
        candidate_id="rel002",
        source_id="src",
        segment_id="seg001",
        workspace="test",
        kind="relation",
        from_entity="Doji Satsume",
        to_entity="Castillo Norte",
        from_type="Character",
        to_type="Location",
        relation_type="HAS_FOUGHT",
        confidence=0.88,
        evidence="El personaje combatió en las murallas del castillo norte",
        timestamp_start="00:10:00",
        timestamp_end="00:14:00",
        source_kind="audio",
    )
    vr = validate_candidate(c)
    assert vr.valid == "invalid", f"HAS_FOUGHT→Location debe ser invalid, got: {vr.valid}"
    assert any("HAS_FOUGHT" in issue for issue in vr.issues), \
        f"Issue debe mencionar HAS_FOUGHT, got: {vr.issues}"
    assert any("FOUGHT_AT" in issue for issue in vr.issues), \
        f"Issue debe sugerir FOUGHT_AT, got: {vr.issues}"


# ── TEST 10: Validator evidence corta → invalid ───────────────────────────────

def test_validator_evidence_corta_es_invalid():
    """Evidence <= 10 chars debe producir invalid."""
    c = _cand(name="Doji Satsume", evidence="breve")
    vr = validate_candidate(c)
    assert vr.valid == "invalid", f"Evidence corta debe ser invalid, got: {vr.valid} issues={vr.issues}"
    assert any("corta" in issue or "evidence" in issue.lower() for issue in vr.issues), \
        f"Debe haber issue sobre evidence corta, got: {vr.issues}"


# ── TEST 11: Validator workspace ausente → invalid ────────────────────────────

def test_validator_workspace_ausente_es_invalid():
    """Workspace ausente debe producir invalid."""
    c = _cand(name="Doji Satsume", workspace="")
    vr = validate_candidate(c)
    assert vr.valid == "invalid", f"Workspace ausente debe ser invalid, got: {vr.valid}"
    assert any("workspace" in issue.lower() for issue in vr.issues), \
        f"Debe haber issue sobre workspace, got: {vr.issues}"


# ── TEST 12: Validator origin inválido → invalid ──────────────────────────────

def test_validator_origin_invalido_es_invalid():
    """Origin no reconocido debe producir invalid."""
    c = _cand(name="Doji Satsume", origin="unknown_source")
    vr = validate_candidate(c)
    assert vr.valid == "invalid", f"Origin inválido debe ser invalid, got: {vr.valid}"
    assert any("origin" in issue.lower() for issue in vr.issues), \
        f"Debe haber issue sobre origin, got: {vr.issues}"


# ── TEST 13: Decision serialización con decision_reason y origin ───────────────

def test_decision_to_dict_from_dict_preserva_campos():
    """Decision.to_dict() / from_dict() deben conservar decision_reason y origin."""
    d = Decision(
        candidate_id="abc",
        decision="auto_approve",
        reason="test",
        decision_reason=["valid_schema", "not_stopword", "strong_compound_name"],
        origin="local",
    )
    d_dict = d.to_dict()
    assert "decision_reason" in d_dict, "to_dict debe incluir decision_reason"
    assert d_dict["decision_reason"] == ["valid_schema", "not_stopword", "strong_compound_name"]
    assert "origin" in d_dict, "to_dict debe incluir origin"
    assert d_dict["origin"] == "local"

    d2 = Decision.from_dict(d_dict)
    assert d2.decision_reason == d.decision_reason
    assert d2.origin == d.origin


# ── TEST 14: weak=True → auto_reject ─────────────────────────────────────────

def test_weak_flag_en_candidato_es_auto_reject():
    """Candidato con weak=True debe ser auto_reject aunque tenga conf alta."""
    c = _cand(name="Doji Satsume", conf=0.95, weak=True,
              evidence="El personaje Doji Satsume actúa en la segunda escena")
    vr = _valid_vr()
    rr = _rr("create_new")
    d = decide_one(c, vr, rr)
    assert d.decision == "auto_reject", \
        f"weak=True debe ser auto_reject, got: {d.decision}: {d.reason}"
    assert "stopword" in d.decision_reason, \
        f"decision_reason debe contener 'stopword' para weak, got: {d.decision_reason}"


# ── TEST 15: Compuesto fuerte + use_existing exacto → resolver_exact_match ────

def test_compuesto_con_use_existing_exacto_tiene_resolver_exact_match():
    """Compuesto fuerte + use_existing exacto → auto_approve con resolver_exact_match."""
    c = _cand(name="Tamori Shaitung", etype="Character", conf=0.93,
              evidence="La personaje Tamori Shaitung es líder del clan en la sesión")
    vr = _valid_vr()
    rr = ResolutionResult(
        candidate_id="test001",
        action="use_existing",
        matched_canonical="Tamori Shaitung",
        match_score=1.0,
        match_type="exact",
        alternatives=[],
        reason="match exacto único",
        neo4j_available=True,
    )
    d = decide_one(c, vr, rr)
    assert d.decision == "auto_approve", \
        f"Compuesto con use_existing exacto debe ser auto_approve, got: {d.decision}: {d.reason}"
    assert "resolver_exact_match" in d.decision_reason, \
        f"Falta resolver_exact_match en {d.decision_reason}"
    assert "strong_compound_name" in d.decision_reason, \
        f"Falta strong_compound_name en {d.decision_reason}"

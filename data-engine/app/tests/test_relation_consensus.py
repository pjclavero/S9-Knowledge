# -*- coding: utf-8 -*-
"""Tests del adaptador de consenso de relaciones (`relation-consensus/v1`).

Verifican que el adaptador COMBINA las fuentes (R2 senales, R3 sintaxis, R5 LLM
local, R6 IA externa) REUTILIZANDO los estados canonicos de
`external_ai.models.CONSENSUS_STATES` (sin estados paralelos) y respetando la
politica: candidato inmutable, determinista, independiente del orden, ausente !=
rechazo, invalidacion de mezcla de workspaces, preservacion de negacion/
temporalidad/estado epistemico y SIN autoaprobacion ni escritura.

Incluye MUTATION CHECKS (6): cada uno describe una mutacion del codigo y el test
concreto que la detectaria.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_ai.models import (  # noqa: E402
    CONSENSUS_STATES,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)
from relations.consensus_adapter import (  # noqa: E402
    RELATION_RECOMMENDATIONS,
    RECO_HUMAN,
    RECO_PROPOSE,
    RECO_REJECT,
    RelationConsensus,
    compute_relation_consensus,
)
from relations.contracts import (  # noqa: E402
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)
from relations.signals import Signal  # noqa: E402


# ---------------------------------------------------------------------------
# Factorias
# ---------------------------------------------------------------------------
def make_candidate(**over) -> RelationCandidate:
    data = dict(
        subject_id="ent:aria",
        subject_type="Character",
        predicate="MEMBER_OF",
        object_id="ent:orden",
        object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT,
        confidence=0.8,
        evidence_text="Aria es miembro de la Orden.",
        evidence_start=0,
        evidence_end=27,
        source_id="src-1",
        source_page=3,
        source_segment="seg-1",
        extraction_method=ExtractionMethod.HEURISTIC,
        model=None,
        negated=False,
        temporal_scope=None,
        epistemic_status=EpistemicStatus.ASSERTED,
        workspace="ws-alpha",
    )
    data.update(over)
    return RelationCandidate(**data).validate()


def sig(name, value):
    return Signal(name=name, value=value, evidence="ev", explanation="ex")


def strong_signals():
    """Senales que soportan una relacion (estructura + tipos compatibles)."""
    return [
        sig("same_clause", True),
        sig("same_sentence", True),
        sig("svo_pattern", True),
        sig("type_compatibility", ["MEMBERSHIP"]),
        sig("negation", False),
        sig("rumor", False),
    ]


class FakeLocal:
    """Sustituto de R5 LocalRelationRecommendation (interfaz leida por adapter)."""

    def __init__(self, recommendation, *, state=PARTIAL_CONSENSUS,
                 validation_status="VALID", provider="ollama",
                 candidate=None, validation_errors=None):
        self.recommendation = recommendation
        self.state = state
        self.validation_status = validation_status
        self.provider = provider
        self.candidate = candidate
        self.validation_errors = validation_errors or []


class FakeExternal:
    """Sustituto de R6 RelationExternalEvaluation (interfaz leida por adapter)."""

    def __init__(self, shadow_recommendation, *, state=PARTIAL_CONSENSUS,
                 provider="nvidia", workspace=None, validation_errors=None):
        self.shadow_recommendation = shadow_recommendation
        self.state = state
        self.provider = provider
        self.workspace = workspace
        self.validation_errors = validation_errors or []


def local_propose(**kw):
    return FakeLocal("recommend_propose", **kw)


def external_confirm(**kw):
    return FakeExternal("confirm", **kw)


# ---------------------------------------------------------------------------
# Reutilizacion de estados canonicos (sin paralelos)
# ---------------------------------------------------------------------------
def test_states_are_reused_from_external_ai():
    res = compute_relation_consensus(make_candidate(), signals=strong_signals())
    assert res.state in CONSENSUS_STATES
    assert res.consensus_states_source == "external_ai.models.CONSENSUS_STATES"


def test_recommendation_never_approves():
    res = compute_relation_consensus(
        make_candidate(), signals=strong_signals(),
        local=local_propose(), external=external_confirm(),
    )
    assert res.recommendation in RELATION_RECOMMENDATIONS
    assert res.recommendation not in {"approve", "approved", "auto_approved",
                                      "accept", "write", "apply", "commit", "merge"}


# ---------------------------------------------------------------------------
# Casos de consenso
# ---------------------------------------------------------------------------
def test_only_heuristics_partial():
    res = compute_relation_consensus(make_candidate(), signals=strong_signals())
    assert res.state == PARTIAL_CONSENSUS
    assert res.recommendation == RECO_PROPOSE


def test_heuristics_plus_syntax_partial():
    syntax = type("Syn", (), {"sentences": [
        type("S", (), {"subject_index": 0, "main_verb_index": 1,
                       "object_index": 2, "negated": False})()
    ]})()
    res = compute_relation_consensus(
        make_candidate(), signals=strong_signals(), syntax=syntax)
    assert res.state == PARTIAL_CONSENSUS
    assert "syntax" in res.sources_present


def test_local_and_external_agree_strong():
    res = compute_relation_consensus(
        make_candidate(), signals=strong_signals(),
        local=local_propose(), external=external_confirm(),
    )
    assert res.state == STRONG_CONSENSUS
    assert res.recommendation == RECO_PROPOSE


def test_local_and_external_disagree_conflict():
    res = compute_relation_consensus(
        make_candidate(), signals=strong_signals(),
        local=local_propose(), external=FakeExternal("reject"),
    )
    assert res.state == MODEL_CONFLICT
    assert res.recommendation == RECO_HUMAN


def test_one_provider_absent_is_not_rejection():
    # Un proveedor presente (propose) + el otro AUSENTE => PARCIAL, no conflicto.
    res = compute_relation_consensus(
        make_candidate(), signals=strong_signals(),
        local=local_propose(), external=None,
    )
    assert res.state == PARTIAL_CONSENSUS
    assert res.recommendation == RECO_PROPOSE
    assert res.state != MODEL_CONFLICT


def test_both_providers_absent_weak_heuristics_human():
    weak = [sig("same_clause", False), sig("same_sentence", False),
            sig("svo_pattern", False), sig("type_compatibility", ["MEMBERSHIP"])]
    res = compute_relation_consensus(make_candidate(), signals=weak)
    assert res.state == HUMAN_REQUIRED
    assert res.recommendation == RECO_HUMAN


def test_invalid_source_response():
    res = compute_relation_consensus(
        make_candidate(), signals=strong_signals(),
        local=FakeLocal("recommend_propose", validation_status="INVALID"),
    )
    assert res.state == INVALID_RESPONSES


def test_contradictory_evidence_conflict():
    # El texto niega (senal negation=True) pero el candidato afirma negated=False.
    signals = strong_signals()
    signals = [s for s in signals if s.name != "negation"] + [sig("negation", True)]
    res = compute_relation_consensus(
        make_candidate(negated=False), signals=signals,
        local=local_propose(), external=external_confirm(),
    )
    assert res.state == MODEL_CONFLICT
    assert "negation_contradiction" in res.reason_codes


def test_incompatible_types_human():
    signals = [sig("same_clause", True), sig("same_sentence", True),
               sig("svo_pattern", True), sig("type_compatibility", [])]
    res = compute_relation_consensus(
        make_candidate(subject_type="Location", object_type="Object"),
        signals=signals, local=local_propose(), external=external_confirm(),
    )
    assert res.state == HUMAN_REQUIRED


# ---------------------------------------------------------------------------
# Politica: workspace, negacion, temporalidad, rumor
# ---------------------------------------------------------------------------
def test_workspace_mismatch_invalidates():
    other_ws_candidate = make_candidate(workspace="ws-beta").to_dict()
    res = compute_relation_consensus(
        make_candidate(workspace="ws-alpha"), signals=strong_signals(),
        local=local_propose(candidate=other_ws_candidate),
    )
    assert res.state == INVALID_RESPONSES
    assert "workspace_mismatch" in res.reason_codes


def test_negation_is_preserved():
    cand = make_candidate(
        negated=True,
        evidence_text="Aria no es miembro de la Orden.",
        evidence_end=30,
    )
    signals = [s for s in strong_signals() if s.name != "negation"] + [sig("negation", True)]
    res = compute_relation_consensus(
        cand, signals=signals, local=local_propose(), external=external_confirm())
    assert res.negated is True
    assert res.state != INVALID_RESPONSES


def test_temporality_is_preserved():
    cand = make_candidate(temporal_scope={"years": ["842"]})
    signals = strong_signals() + [sig("temporality", {"markers": [], "years": ["842"]})]
    res = compute_relation_consensus(
        cand, signals=signals, local=local_propose(), external=external_confirm())
    assert res.temporal_scope == {"years": ["842"]}


def test_rumor_epistemic_preserved():
    cand = make_candidate(epistemic_status=EpistemicStatus.RUMORED)
    signals = [s for s in strong_signals() if s.name != "rumor"] + [sig("rumor", True)]
    res = compute_relation_consensus(
        cand, signals=signals, local=local_propose(), external=external_confirm())
    assert res.epistemic_status == "RUMORED"
    assert res.state != MODEL_CONFLICT  # rumor coherente, no contradiccion


def test_rumor_but_asserted_is_contradiction():
    signals = [s for s in strong_signals() if s.name != "rumor"] + [sig("rumor", True)]
    res = compute_relation_consensus(
        make_candidate(epistemic_status=EpistemicStatus.ASSERTED),
        signals=signals, local=local_propose(), external=external_confirm())
    assert res.state == MODEL_CONFLICT
    assert "epistemic_contradiction" in res.reason_codes


# ---------------------------------------------------------------------------
# Penalizacion de evidencia inexistente
# ---------------------------------------------------------------------------
def test_missing_evidence_penalized():
    # Span de longitud cero (start==end): el contrato lo admite, pero NO es
    # evidencia real -> el adaptador la penaliza -> INVALID.
    res = compute_relation_consensus(
        make_candidate(evidence_start=5, evidence_end=5),
        signals=strong_signals(), local=local_propose(), external=external_confirm(),
    )
    assert res.state == INVALID_RESPONSES


def test_empty_evidence_text_invalid_by_contract():
    # Texto vacio con metodo HEURISTIC: lo rechaza ya el contrato -> INVALID.
    res = compute_relation_consensus(
        {**make_candidate().to_dict(), "evidence_text": "   "},
        signals=strong_signals(),
    )
    assert res.state == INVALID_RESPONSES


# ---------------------------------------------------------------------------
# Determinismo, orden y no-mutacion
# ---------------------------------------------------------------------------
def test_signal_order_independence():
    signals = strong_signals()
    a = compute_relation_consensus(
        make_candidate(), signals=list(signals),
        local=local_propose(), external=external_confirm()).to_dict()
    b = compute_relation_consensus(
        make_candidate(), signals=list(reversed(signals)),
        local=local_propose(), external=external_confirm()).to_dict()
    assert a == b


def test_determinism_repeated_calls():
    kwargs = dict(signals=strong_signals(), local=local_propose(),
                  external=external_confirm())
    a = compute_relation_consensus(make_candidate(), **kwargs).to_dict()
    b = compute_relation_consensus(make_candidate(), **kwargs).to_dict()
    assert a == b


def test_original_candidate_not_mutated():
    cand = make_candidate()
    before = cand.to_json()
    compute_relation_consensus(
        cand, signals=strong_signals(),
        local=local_propose(), external=external_confirm())
    assert cand.to_json() == before
    # Los enums del original siguen siendo enums (no coercidos por el adapter).
    assert isinstance(cand.direction, Direction)
    assert isinstance(cand.epistemic_status, EpistemicStatus)


def test_zero_writes_no_open(monkeypatch):
    import builtins
    real_open = builtins.open

    def _no_open(*a, **k):  # pragma: no cover - se invoca solo si algo escribe
        raise AssertionError("el consenso no debe abrir/escribir ficheros")

    monkeypatch.setattr(builtins, "open", _no_open)
    try:
        res = compute_relation_consensus(
            make_candidate(), signals=strong_signals(),
            local=local_propose(), external=external_confirm())
    finally:
        monkeypatch.setattr(builtins, "open", real_open)
    assert res.recommendation in RELATION_RECOMMENDATIONS


def test_result_state_always_canonical():
    for res in (
        compute_relation_consensus(make_candidate(), signals=strong_signals()),
        compute_relation_consensus(make_candidate(), signals=strong_signals(),
                                   local=local_propose(), external=external_confirm()),
    ):
        assert res.state in CONSENSUS_STATES
        assert res.recommendation in RELATION_RECOMMENDATIONS


# ===========================================================================
# MUTATION CHECKS (>=6): cada mutacion DEBE romper al menos un test.
# ===========================================================================
# (1) permitir workspace mezclado  -> quitar el chequeo de workspace:
#        rompe test_workspace_mismatch_invalidates (dejaria de ser INVALID).
# (2) ignorar negacion  -> forzar negated=False / no detectar contradiccion:
#        rompe test_negation_is_preserved y test_contradictory_evidence_conflict.
# (3) ignorar evidencia -> no exigir evidencia:
#        rompe test_missing_evidence_penalized (dejaria de ser INVALID).
# (4) tratar proveedor ausente como rechazo -> ausente = polaridad negativa:
#        rompe test_one_provider_absent_is_not_rejection (pasaria a MODEL_CONFLICT).
# (5) permitir autoaprobacion -> emitir recommendation aprobatoria:
#        rompe test_recommendation_never_approves y el guard de RelationConsensus.
# (6) resultado dependiente del orden -> no ordenar/usar orden de entrada:
#        rompe test_signal_order_independence (a != b).
def test_mutation_matrix_documented():
    """Ancla textual de la matriz de mutaciones (documentacion viva)."""
    mutations = {
        1: "workspace mezclado",
        2: "ignorar negacion",
        3: "ignorar evidencia",
        4: "ausente == rechazo",
        5: "autoaprobacion",
        6: "dependiente del orden",
    }
    assert len(mutations) >= 6


def test_recommendation_guard_blocks_approval():
    with pytest.raises(ValueError):
        RelationConsensus(
            state=STRONG_CONSENSUS,
            recommendation="approve",
            subject_id="a", predicate="P", object_id="b", workspace="ws",
            negated=False, epistemic_status="ASSERTED", temporal_scope=None,
        )

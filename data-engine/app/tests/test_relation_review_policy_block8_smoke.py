# -*- coding: utf-8 -*-
"""Bloque 8 - Tests de HUMO de la politica de revision y su medicion.

Estos son los tests MINIMOS del AGENTE-IMPLEMENTADOR; la bateria completa
(mutantes, tabla de verdad exhaustiva, fuzzing de inputs corruptos) la escribe
AGENTE-TESTS por separado. Aqui solo se valida que:

  1. `relations.review_policy` importa y su tabla de verdad basica funciona
     (STRONG + score alto + proveedor + sin conflictos + evidencia ->
     AUTO_PROPOSABLE; quitar CUALQUIERA de esas condiciones -> REVIEW_REQUIRED).
  2. Los labels de la politica NUNCA solapan `CONSENSUS_STATES` ni contienen
     ninguna forma de aprobacion/escritura.
  3. `relations.benchmark.review_policy_metrics` computa gates/dictamen
     correctos sobre un `MatchResult` de juguete con FAR conocido (uno con
     falso-aceptado que fuerza FAIL en muestra pequena, y uno con muestra
     grande y FAR=0 que pasa).
  4. El modulo de metricas corre de verdad sobre el corpus B1 offline
     (`baseline1`/`ensemble_offline`) sin lanzar excepciones, y su resultado es
     consistente con `sample_size == 0` (proveedores apagados: NUNCA puede
     haber `providers_present >= 1`, condicion dura de AUTO_PROPOSABLE).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from external_ai.models import CONSENSUS_STATES  # noqa: E402

from relations.review_policy import (  # noqa: E402
    AUTO_PROPOSABLE,
    REVIEW_REQUIRED,
    REVIEW_POLICY_LABELS,
    ReviewPolicyConfig,
    ReviewPolicyConfigError,
    ReviewPolicyOutcome,
    DEFAULT_REVIEW_POLICY_CONFIG,
    classify_for_review,
)

from relations.benchmark.matching import MatchResult  # noqa: E402
from relations.benchmark.review_policy_metrics import (  # noqa: E402
    MIN_SAMPLE_SIZE,
    build_review_policy_report,
    decide_review_policy_verdict,
    evaluate_review_policy_gates,
    review_policy_safety_metrics,
)


# ---------------------------------------------------------------------------
# (1) Vocabulario: sin solape con CONSENSUS_STATES, sin aprobacion
# ---------------------------------------------------------------------------
def test_review_policy_labels_do_not_overlap_consensus_states():
    assert set(REVIEW_POLICY_LABELS).isdisjoint(set(CONSENSUS_STATES))
    assert REVIEW_POLICY_LABELS == (AUTO_PROPOSABLE, REVIEW_REQUIRED)


@pytest.mark.parametrize("forbidden", [
    "AUTO_APPROVED", "APPROVED", "WRITE", "APPLY", "COMMIT", "ACCEPT",
])
def test_review_policy_outcome_rejects_forbidden_labels(forbidden):
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label=forbidden, reason="x", signals={})


# ---------------------------------------------------------------------------
# (2) Tabla de verdad basica de classify_for_review (fail-closed)
# ---------------------------------------------------------------------------
_BASE_KWARGS = dict(
    state="STRONG_CONSENSUS",
    recommendation="propose",
    score=0.95,
    n_decisive=3,
    providers_present=1,
    has_evidence=True,
    conflicts=(),
)


def test_classify_for_review_all_conditions_met_is_auto_proposable():
    outcome = classify_for_review(**_BASE_KWARGS)
    assert outcome.label == AUTO_PROPOSABLE
    assert outcome.is_auto_proposable is True
    assert outcome.config_hash == DEFAULT_REVIEW_POLICY_CONFIG.config_hash


@pytest.mark.parametrize("override", [
    {"state": "PARTIAL_CONSENSUS"},
    {"state": "MODEL_CONFLICT"},
    {"state": "HUMAN_REQUIRED"},
    {"state": "INVALID_RESPONSES"},
    {"providers_present": 0},
    {"score": 0.89},
    {"conflicts": ({"type": "temporal", "detail": "x", "sources": ["temporality"]},)},
    {"has_evidence": False},
])
def test_classify_for_review_missing_any_condition_requires_review(override):
    kwargs = dict(_BASE_KWARGS)
    kwargs.update(override)
    outcome = classify_for_review(**kwargs)
    assert outcome.label == REVIEW_REQUIRED


@pytest.mark.parametrize("override", [
    {"state": None},
    {"state": 42},
    {"state": "NOT_A_STATE"},
    {"score": None},
    {"score": "high"},
    {"providers_present": None},
    {"providers_present": "1"},
    {"has_evidence": None},
    {"has_evidence": "yes"},
    {"conflicts": None},
    {"conflicts": 5},
])
def test_classify_for_review_corrupt_input_is_fail_closed_not_an_exception(override):
    kwargs = dict(_BASE_KWARGS)
    kwargs.update(override)
    outcome = classify_for_review(**kwargs)  # no debe lanzar
    assert outcome.label == REVIEW_REQUIRED


def test_classify_for_review_score_exactly_at_threshold_is_auto_proposable():
    kwargs = dict(_BASE_KWARGS)
    kwargs["score"] = DEFAULT_REVIEW_POLICY_CONFIG.auto_propose_score_threshold
    outcome = classify_for_review(**kwargs)
    assert outcome.label == AUTO_PROPOSABLE


def test_review_policy_config_rejects_invalid_threshold():
    with pytest.raises(ReviewPolicyConfigError):
        ReviewPolicyConfig(auto_propose_score_threshold=1.5)
    with pytest.raises(ReviewPolicyConfigError):
        ReviewPolicyConfig(auto_propose_score_threshold=0.0)
    with pytest.raises(ReviewPolicyConfigError):
        ReviewPolicyConfig(min_providers_present=0)


def test_review_policy_config_hash_changes_with_threshold():
    a = ReviewPolicyConfig(auto_propose_score_threshold=0.90)
    b = ReviewPolicyConfig(auto_propose_score_threshold=0.95)
    assert a.config_hash != b.config_hash


# ---------------------------------------------------------------------------
# (3) Medicion sobre un MatchResult de juguete con FAR conocido
# ---------------------------------------------------------------------------
def _toy_gt(relation_id, expected_decision="ACCEPT"):
    return {"relation_id": relation_id, "expected_decision": expected_decision}


def _toy_pred(label, candidate_id="c1"):
    return {"candidate_id": candidate_id, "review_policy_label": label}


def test_review_policy_metrics_far_forces_fail_even_with_small_sample():
    """1 falso-aceptado en muestra < MIN_SAMPLE_SIZE -> FAIL, no NOT_MEASURED
    (patron strict_small_sample: el dano observado no se disculpa por la
    muestra)."""
    match = MatchResult(
        true_positives=[
            {"gt": _toy_gt("r1", "ACCEPT"), "pred": _toy_pred(AUTO_PROPOSABLE), "flags": {}},
            {"gt": _toy_gt("r2", "REJECT"), "pred": _toy_pred(AUTO_PROPOSABLE), "flags": {}},
        ],
        false_positives=[],
        false_negatives=[],
    )
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == 2
    assert metrics["false_accepts"] == 1
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_false_accept_rate"]["status"] == "FAIL"
    assert gates["review_policy_precision"]["status"] == "FAIL"
    verdict, _just = decide_review_policy_verdict(gates)
    assert verdict == "POLITICA DE REDUCCION: NO APTA (GATE DE SEGURIDAD EN FAIL)"


def test_review_policy_metrics_small_clean_sample_is_not_measured():
    match = MatchResult(
        true_positives=[
            {"gt": _toy_gt("r1", "ACCEPT"), "pred": _toy_pred(AUTO_PROPOSABLE), "flags": {}},
        ],
        false_positives=[],
        false_negatives=[],
    )
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == 1
    assert metrics["false_accepts"] == 0
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_sample_size"]["status"] == "NOT_MEASURED"
    verdict, _just = decide_review_policy_verdict(gates)
    assert verdict == "POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)"


def test_review_policy_metrics_large_clean_sample_passes():
    true_positives = [
        {"gt": _toy_gt(f"r{i}", "ACCEPT"), "pred": _toy_pred(AUTO_PROPOSABLE, f"c{i}"), "flags": {}}
        for i in range(MIN_SAMPLE_SIZE)
    ]
    match = MatchResult(true_positives=true_positives, false_positives=[], false_negatives=[])
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == MIN_SAMPLE_SIZE
    assert metrics["false_accept_rate"] == 0.0
    assert metrics["precision"] == 1.0
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_false_accept_rate"]["status"] == "PASS"
    assert gates["review_policy_precision"]["status"] == "PASS"
    assert gates["review_policy_sample_size"]["status"] == "PASS"
    verdict, _just = decide_review_policy_verdict(gates)
    assert verdict == "POLITICA DE REDUCCION: APTA (GATES DE SEGURIDAD EN PASS)"


def test_review_policy_metrics_fp_auto_proposed_counts_as_false_accept():
    match = MatchResult(
        true_positives=[],
        false_positives=[_toy_pred(AUTO_PROPOSABLE, "fp1")],
        false_negatives=[],
    )
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == 1
    assert metrics["false_accepts"] == 1
    assert metrics["precision"] == 0.0


def test_review_policy_metrics_always_publishes_fields_even_when_zero():
    match = MatchResult(true_positives=[], false_positives=[], false_negatives=[])
    metrics = review_policy_safety_metrics(match)
    for key in ("false_accept_rate", "coverage", "sample_size", "precision"):
        assert key in metrics


# ---------------------------------------------------------------------------
# (4) Ejecucion REAL offline sobre el corpus B1 (sin proveedores, sin red)
# ---------------------------------------------------------------------------
def test_review_policy_report_runs_offline_on_real_corpus_without_error():
    from relations.benchmark.runner import load_corpus, run_benchmark

    corpus = load_corpus()
    run = run_benchmark(corpus, mode="ensemble_offline",
                        source_ids=["src-01", "src-02", "src-03"])
    report = build_review_policy_report(corpus, run)

    assert report["mode"] == "ensemble_offline"
    assert "false_accept_rate" in report["metrics"]
    assert "sample_size" in report["metrics"]
    assert "coverage" in report["metrics"]
    # DURO: sin proveedores (offline) NUNCA puede haber providers_present >= 1,
    # asi que la muestra auto-proposable es SIEMPRE 0 en modo offline. Si esto
    # deja de cumplirse, alguien ha roto la barrera fail-closed de la politica
    # o ha colado un proveedor real en un modo offline.
    assert report["metrics"]["sample_size"] == 0
    assert report["verdict"] == (
        "POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)"
    )

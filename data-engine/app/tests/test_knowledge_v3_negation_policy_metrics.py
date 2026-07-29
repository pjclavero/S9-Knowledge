# -*- coding: utf-8 -*-
"""Las cinco metricas del gate de politica de negaciones."""
from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.benchmarks.metrics import negation_policy_metrics, negation_split_metrics


def case(**overrides):
    base = {
        "family": "SIMPLE",
        "expected_negated": True,
        "predicted_negated": True,
        "predicted_negation_kind": "SIMPLE",
        "expected_decision": "AUTO_APPROVE",
        "predicted_decision": "ACCEPT",
        "evidence_anchored": True,
        "scope_correct": True,
    }
    base.update(overrides)
    return base


def test_las_cinco_metricas_pasan_con_salidas_perfectas():
    result = negation_policy_metrics(
        [
            case(),
            case(family="NEVER", predicted_negation_kind="NEVER"),
            case(
                family="NEGATED_CESSATION",
                expected_negated=False,
                predicted_negated=False,
                predicted_negation_kind="SCOPE_AMBIGUOUS",
                expected_decision="REVIEW_NEGATION_SCOPE",
                predicted_decision="REVIEW",
            ),
        ]
    )
    assert set(result) == {
        "negative_edge_precision",
        "negated_cessation_safety",
        "evidence_grounding",
        "scope_accuracy",
        "auto_approval_recall",
    }
    assert all(metric["passes"] for metric in result.values())


def test_autoaprobar_cero_suspende_recall_aunque_el_resto_sea_perfecto():
    rows = [case(predicted_decision="REVIEW") for _ in range(10)]
    result = negation_policy_metrics(rows)
    assert all(
        result[name]["passes"]
        for name in (
            "negative_edge_precision",
            "negated_cessation_safety",
            "evidence_grounding",
            "scope_accuracy",
        )
    )
    assert result["auto_approval_recall"] == {
        "auto_approved": 0,
        "auto_approvable": 10,
        "recall": 0.0,
        "passes": False,
    }


def test_no_dejo_de_nunca_cuenta_como_cesacion_segura_si_el_motor_la_cierra():
    result = negation_policy_metrics(
        [
            case(
                family="NEGATED_CESSATION",
                expected_negated=False,
                predicted_negated=True,
                predicted_negation_kind="CESSATION",
                expected_decision="REVIEW_NEGATION_SCOPE",
                predicted_decision="REVIEW",
            )
        ]
    )
    assert result["negated_cessation_safety"]["false_cessations"] == 1
    assert result["negated_cessation_safety"]["passes"] is False


def test_el_adaptador_mide_el_split_negation_sin_modificar_su_gold():
    gold = load_gold("negation")
    contract_decisions = {decision["claim_id"]: decision for decision in gold.decisions}
    predictions = {}
    for claim in gold.claims:
        annotation = claim["metadata"]["negation"]
        decision = contract_decisions[claim["claim_id"]]
        predictions[claim["claim_id"]] = {
            "negated": claim["negated"],
            "negation_kind": annotation["negation_kind"],
            "decision": decision["decision"],
            "evidence_anchored": True,
            "scope_correct": True,
        }
    result = negation_split_metrics(gold, predictions)
    assert result["auto_approval_recall"]["auto_approvable"] == 16
    assert result["auto_approval_recall"]["recall"] == 1.0
    assert all(metric["passes"] for metric in result.values())

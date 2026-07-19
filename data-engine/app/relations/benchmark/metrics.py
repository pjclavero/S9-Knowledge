# -*- coding: utf-8 -*-
"""Metricas DETERMINISTAS del benchmark de relaciones.

Consume el resultado de `matching.match_predictions` (y los contadores
operativos agregados del pipeline REAL) y produce metricas globales, por tipo de
predicado y de calidad estructural. NO ejecuta el pipeline ni reimplementa nada.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from relations.contracts import normalize_predicate

from .matching import MatchResult


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def global_metrics(match: MatchResult) -> dict:
    """P/R/F1 globales sobre el criterio de existencia (par no ordenado)."""
    return _prf(match.tp, match.fp, match.fn)


def strict_metrics(match: MatchResult) -> dict:
    """P/R/F1 con criterio ESTRICTO: par correcto Y predicado exacto.

    Un TP de existencia con predicado incorrecto degrada a FP (prediccion errada)
    y a FN (la relacion de ground truth queda sin cubrir con su predicado).
    """
    tp = sum(1 for m in match.true_positives if m["flags"]["predicate_correct"])
    predicate_wrong = match.tp - tp
    fp = match.fp + predicate_wrong
    fn = match.fn + predicate_wrong
    return _prf(tp, fp, fn)


def per_predicate_metrics(match: MatchResult) -> dict:
    """Metricas por predicado del GROUND TRUTH.

    Para cada predicado del ground truth reporta:
      * support           : nº de relaciones de ground truth con ese predicado.
      * existence_tp      : cuantas fueron emparejadas (par correcto).
      * exact_tp          : cuantas ademas con predicado exacto.
      * recall_existence  : existence_tp / support.
      * recall_exact      : exact_tp / support.
    """
    support: dict[str, int] = defaultdict(int)
    existence_tp: dict[str, int] = defaultdict(int)
    exact_tp: dict[str, int] = defaultdict(int)

    for gt in match.false_negatives:
        support[normalize_predicate(gt["predicate"])] += 1
    for m in match.true_positives:
        p = normalize_predicate(m["gt"]["predicate"])
        support[p] += 1
        existence_tp[p] += 1
        if m["flags"]["predicate_correct"]:
            exact_tp[p] += 1

    out: dict[str, dict] = {}
    for p in sorted(support):
        s = support[p]
        out[p] = {
            "support": s,
            "existence_tp": existence_tp[p],
            "exact_tp": exact_tp[p],
            "recall_existence": round(existence_tp[p] / s, 4) if s else 0.0,
            "recall_exact": round(exact_tp[p] / s, 4) if s else 0.0,
        }
    return out


def predicted_predicate_distribution(predictions: list[dict]) -> dict:
    """Distribucion de predicados PREDICHOS (para ver el sesgo del heuristico)."""
    dist: dict[str, int] = defaultdict(int)
    for pred in predictions:
        dist[normalize_predicate(pred["predicate"])] += 1
    return dict(sorted(dist.items()))


def structural_quality(match: MatchResult) -> dict:
    """Tasas de calidad estructural sobre los TP (par correcto).

    Cada tasa es correctos/total_TP. Ademas subgrupos condicionados (negacion,
    temporalidad, rumor) para los gates.
    """
    tp = match.true_positives
    n = len(tp)

    def rate(flag: str) -> dict:
        ok = sum(1 for m in tp if m["flags"][flag])
        return {"ok": ok, "total": n, "rate": round(ok / n, 4) if n else 0.0}

    # Subgrupos para gates.
    negated_gt = [m for m in tp if bool(m["gt"]["negated"])]
    temporal_gt = [m for m in tp if m["gt"]["temporal_status"] in ("PAST", "FUTURE", "ONGOING", "ENDED")]
    rumor_gt = [m for m in tp if m["gt"]["epistemic_status"] == "RUMORED"]
    simple_gt = [
        m for m in tp
        if not bool(m["gt"]["negated"])
        and m["gt"]["epistemic_status"] == "ASSERTED"
        and m["gt"]["expected_decision"] == "ACCEPT"
    ]

    def subgroup_rate(subset: list, flag: str) -> dict:
        k = len(subset)
        ok = sum(1 for m in subset if m["flags"][flag])
        return {"ok": ok, "total": k, "rate": round(ok / k, 4) if k else 0.0}

    return {
        "predicate_correct": rate("predicate_correct"),
        "direction_correct": rate("direction_correct"),
        "direction_orientation_ok": rate("direction_orientation_ok"),
        "types_correct": rate("types_correct"),
        "negation_correct": rate("negation_correct"),
        "temporal_correct": rate("temporal_correct"),
        "epistemic_correct": rate("epistemic_correct"),
        "evidence_correct": rate("evidence_correct"),
        "offsets_correct": rate("offsets_correct"),
        "workspace_correct": rate("workspace_correct"),
        "decision_correct": rate("decision_correct"),
        "subgroups": {
            "simple_relations": {
                "count": len(simple_gt),
                "evidence_correct": subgroup_rate(simple_gt, "evidence_correct"),
            },
            "negated_relations": {
                "count": len(negated_gt),
                "negation_correct": subgroup_rate(negated_gt, "negation_correct"),
            },
            "temporal_relations": {
                "count": len(temporal_gt),
                "temporal_correct": subgroup_rate(temporal_gt, "temporal_correct"),
            },
            "rumored_relations": {
                "count": len(rumor_gt),
                "epistemic_correct": subgroup_rate(rumor_gt, "epistemic_correct"),
            },
        },
    }


def decision_confusion(match: MatchResult) -> dict:
    """Matriz de confusion decision_pred vs expected_decision (sobre TP)."""
    labels = ["ACCEPT", "REJECT", "REVIEW", None]
    conf: dict[str, dict[str, int]] = {
        str(g): {str(p): 0 for p in labels} for g in ["ACCEPT", "REJECT", "REVIEW"]
    }
    for m in match.true_positives:
        gt_dec = m["gt"]["expected_decision"]
        pred_dec = m["flags"]["decision_pred"]
        conf[str(gt_dec)][str(pred_dec)] += 1
    return conf


def aggregate_operational(source_summaries: list[dict], timings: list[dict]) -> dict:
    """Agrega los contadores OPERATIVOS del resumen del pipeline REAL por fuente.

    `source_summaries` son los `output['summary']` reales de cada ejecucion; no se
    recalcula nada, solo se suman.
    """
    keys = [
        "documents", "segments", "segments_processed", "segments_failed",
        "entities", "pairs_potential", "pairs_generated", "pairs_discarded",
        "candidates_evaluated", "results_strong", "results_partial",
        "results_conflict", "results_invalid", "results_human",
        "local_calls_simulated", "external_calls_simulated",
        "provider_fail_closed", "timeouts", "errors", "chars_processed",
        "bytes_processed",
    ]
    agg = {k: 0 for k in keys}
    for s in source_summaries:
        for k in keys:
            agg[k] += int(s.get(k, 0))

    total_ms = sum(t["elapsed_ms"] for t in timings)
    n_docs = len(timings) or 1
    n_cand = agg["candidates_evaluated"] or 1
    agg_time = {
        "total_ms": round(total_ms, 3),
        "per_doc_ms": round(total_ms / n_docs, 3),
        "per_candidate_ms": round(total_ms / n_cand, 3),
    }

    consensus_total = (
        agg["results_strong"] + agg["results_partial"] + agg["results_conflict"]
        + agg["results_invalid"] + agg["results_human"]
    ) or 1
    rates = {
        "human_rate": round((agg["results_human"]) / consensus_total, 4),
        "conflict_rate": round((agg["results_conflict"]) / consensus_total, 4),
        "invalid_rate": round((agg["results_invalid"]) / consensus_total, 4),
    }
    return {"counters": agg, "timings": agg_time, "consensus_rates": rates}


__all__ = [
    "global_metrics",
    "strict_metrics",
    "per_predicate_metrics",
    "predicted_predicate_distribution",
    "structural_quality",
    "decision_confusion",
    "aggregate_operational",
]

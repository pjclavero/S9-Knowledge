# -*- coding: utf-8 -*-
"""Medicion de SEGURIDAD de la politica de revision (`relations.review_policy`).

Bloque 8. Este modulo NO reimplementa el pipeline, el consenso ni el ensemble:
IMPORTA `relations.benchmark.matching`/`metrics`/`report` (sin modificarlos) y
`relations.ensemble`/`relations.review_policy` para clasificar cada resultado YA
CALCULADO por el pipeline REAL del benchmark de relaciones (Bloque 7).

Que mide
--------
Sobre el subconjunto de predicciones que la politica etiqueta
`AUTO_PROPOSABLE` (ver `relations.review_policy.classify_for_review`):

  * `precision`         : de lo auto-propuesto, que fraccion es realmente
                          correcta (`expected_decision == "ACCEPT"` en el ground
                          truth; un FP auto-propuesto -- sin relacion real en el
                          ground truth -- cuenta SIEMPRE como incorrecto).
  * `false_accept_rate` : fraccion de lo auto-propuesto que NO deberia haberse
                          aceptado (`expected_decision != "ACCEPT"`, o FP).
  * `coverage`          : auto-propuesto / total evaluado (informativa, nunca
                          un minimo exigido). Se reporta tambien sobre TP.
  * `sample_size`       : tamano de la muestra auto-propuesta (TP + FP
                          auto-propuestos).

Gates DUROS (fijados por el Organizador, no se relajan aqui):

  * `review_policy_false_accept_rate <= 0.02`
  * `review_policy_precision >= 0.98`
  * `review_policy_sample_size >= 20` para que los dos gates anteriores puedan
    ser PASS/FAIL; con muestra menor son `NOT_MEASURED` -- SALVO que exista
    algun falso-aceptado, en cuyo caso CUALQUIER falso-aceptado con muestra
    pequena fuerza `FAIL` (patron `strict_small_sample`, analogo al B3 del
    Bloque 7): la muestra insuficiente nunca es una excusa para certificar una
    politica con danio ya observado.

El vocabulario de dictamen de este modulo es CERRADO y ADITIVO al de
`relations.benchmark.report` (no lo sustituye ni lo reutiliza: vive aqui, en un
modulo nuevo, tal como exige el Organizador).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from relations import ensemble as _ensemble
from relations.review_policy import (
    AUTO_PROPOSABLE,
    REVIEW_REQUIRED,
    ReviewPolicyConfig,
    ReviewPolicyOutcome,
    DEFAULT_REVIEW_POLICY_CONFIG,
    classify_for_review,
)

from .matching import MatchResult, match_predictions
from .runner import BenchmarkRun, segment_context

REVIEW_POLICY_METRICS_VERSION = "relation-review-policy-metrics-1.0.0"

# --- Gates DUROS (firmes; NUNCA se relajan por codigo) ----------------------
FALSE_ACCEPT_RATE_MAX = 0.02
PRECISION_MIN = 0.98
MIN_SAMPLE_SIZE = 20

# Vocabulario de dictamen CERRADO y ADITIVO (no toca `report.VERDICTS`).
REVIEW_POLICY_VERDICTS = (
    "POLITICA DE REDUCCION: APTA (GATES DE SEGURIDAD EN PASS)",
    "POLITICA DE REDUCCION: NO APTA (GATE DE SEGURIDAD EN FAIL)",
    "POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)",
)


# ---------------------------------------------------------------------------
# (1) De la salida REAL del pipeline a decisiones del ensemble + politica
# ---------------------------------------------------------------------------
def _providers_present(decision: "_ensemble.EnsembleDecision") -> int:
    """Cuenta proveedores (local/external) con `availability == PRESENT`.

    Se lee del propio `SourceContribution.availability` que `ensemble.combine`
    YA CALCULO (ver `_effective_availability`): no se reinterpreta el payload
    del proveedor, solo se cuenta lo que el ensemble ya decidio.
    """
    present_sources = {
        c.source for c in decision.contributions
        if c.availability == _ensemble.AVAIL_PRESENT
    }
    return sum(1 for s in (_ensemble.SOURCE_LOCAL_LLM, _ensemble.SOURCE_EXTERNAL_AI)
               if s in present_sources)


def _n_decisive(decision: "_ensemble.EnsembleDecision") -> int:
    return sum(1 for c in decision.contributions if c.decisive)


def _has_evidence(candidate: dict) -> bool:
    """Evidencia real: texto no vacio Y span no degenerado.

    Lectura DIRECTA de los campos ya validados del contrato
    (`relation-candidate/internal-v1`), igual que hace `matching.py` al
    acceder a `pred["evidence_start"]`/`pred["evidence_end"]`. No reimplementa
    ninguna etapa del pipeline: solo lee campos ya presentes en el payload.
    """
    text = candidate.get("evidence_text")
    start = candidate.get("evidence_start")
    end = candidate.get("evidence_end")
    if not isinstance(text, str) or not text.strip():
        return False
    if not isinstance(start, int) or isinstance(start, bool):
        return False
    if not isinstance(end, int) or isinstance(end, bool):
        return False
    return end > start


def predictions_with_review_policy(
    run: BenchmarkRun,
    *,
    review_config: ReviewPolicyConfig = DEFAULT_REVIEW_POLICY_CONFIG,
    ensemble_config: Any = None,
) -> list[dict]:
    """Predicciones planas (mismo esquema que `runner.extract_predictions`) mas
    la clasificacion de `relations.review_policy` para CADA candidato.

    Requiere que `run.mode` use el ensemble (`runner.uses_ensemble(run.mode)`):
    solo `EnsembleDecision` expone `score`/`conflicts`/`contributions`, que la
    politica necesita para poder considerar `AUTO_PROPOSABLE` a un candidato.
    En un modo SIN ensemble (p.ej. `baseline1`) no existen esas senales; se
    clasifica igualmente (fail-closed: todo cae en `REVIEW_REQUIRED`
    honestamente, nunca se inventa un score), pero el resultado es trivial y se
    documenta como tal por el llamante del CLI/entrypoint.

    NO ejecuta proveedores, NO abre red: reutiliza `relations.ensemble.combine`
    (mismo import que `runner.extract_predictions_ensemble`) sobre las senales
    y sintaxis YA CALCULADAS por el pipeline REAL.
    """
    kwargs = {}
    if ensemble_config is not None:
        kwargs["config"] = ensemble_config

    out: list[dict] = []
    for sr in run.source_runs:
        ctx = segment_context(sr.output)
        for rec in sr.output.get("results", []):
            c = rec["candidate"]
            base = rec.get("consensus") or {}
            seg_ctx = ctx.get(rec.get("pair_id"), {})
            decision = _ensemble.combine(
                c,
                signals=seg_ctx.get("signals"),
                syntax=seg_ctx.get("syntax"),
                local=rec.get("local"),
                external=rec.get("external"),
                local_availability=rec.get("local_status"),
                external_availability=rec.get("external_status"),
                **kwargs,
            )
            providers_present = _providers_present(decision)
            n_decisive = _n_decisive(decision)
            has_evidence = _has_evidence(c)
            outcome = classify_for_review(
                state=decision.state,
                recommendation=decision.recommendation,
                score=decision.score,
                n_decisive=n_decisive,
                providers_present=providers_present,
                has_evidence=has_evidence,
                conflicts=decision.conflicts,
                config=review_config,
            )
            out.append({
                "candidate_id": rec["candidate_id"],
                "source_id": c["source_id"],
                "workspace": c["workspace"],
                "subject_id": c["subject_id"],
                "object_id": c["object_id"],
                "subject_type": c["subject_type"],
                "object_type": c["object_type"],
                "predicate": c["predicate"],
                "direction": c["direction"],
                "negated": c["negated"],
                "temporal_scope": c["temporal_scope"],
                "epistemic_status": c["epistemic_status"],
                "evidence_text": c["evidence_text"],
                "evidence_start": c["evidence_start"],
                "evidence_end": c["evidence_end"],
                "consensus_state": decision.state,
                "recommendation": decision.recommendation,
                "base_consensus_state": base.get("state"),
                "ensemble_score": round(float(decision.score), 6),
                "review_policy_label": outcome.label,
                "review_policy_reason": outcome.reason,
                "review_policy": outcome.to_dict(),
            })
    return out


# ---------------------------------------------------------------------------
# (2) Metricas de seguridad sobre el subconjunto AUTO_PROPOSABLE
# ---------------------------------------------------------------------------
def review_policy_safety_metrics(match: MatchResult) -> dict:
    """Metricas de seguridad sobre `match` (predicciones YA anotadas con la
    politica, via `predictions_with_review_policy` + `matching.match_predictions`).

    SIEMPRE publica `false_accept_rate`, `coverage` y `sample_size`, incluso en
    0 o desfavorables (transparencia; nunca se omiten en caso de fallo).
    """
    auto_tp = [m for m in match.true_positives
               if m["pred"].get("review_policy_label") == AUTO_PROPOSABLE]
    auto_fp = [p for p in match.false_positives
               if p.get("review_policy_label") == AUTO_PROPOSABLE]

    sample_size = len(auto_tp) + len(auto_fp)
    correct = sum(1 for m in auto_tp if m["gt"]["expected_decision"] == "ACCEPT")
    # Un FP auto-propuesto no tiene relacion real que corroborar: es SIEMPRE un
    # falso-aceptado (se propuso automaticamente algo que el ground truth ni
    # siquiera contiene).
    false_accepts = (len(auto_tp) - correct) + len(auto_fp)

    total_evaluated = len(match.true_positives) + len(match.false_positives)
    tp_total = len(match.true_positives)

    precision = round(correct / sample_size, 4) if sample_size else 0.0
    false_accept_rate = round(false_accepts / sample_size, 4) if sample_size else 0.0
    coverage = round(sample_size / total_evaluated, 4) if total_evaluated else 0.0
    coverage_over_tp = round(sample_size / tp_total, 4) if tp_total else 0.0

    return {
        "sample_size": sample_size,
        "auto_proposable_tp": len(auto_tp),
        "auto_proposable_fp": len(auto_fp),
        "correct": correct,
        "false_accepts": false_accepts,
        "precision": precision,
        "false_accept_rate": false_accept_rate,
        "total_evaluated": total_evaluated,
        "tp_total": tp_total,
        "coverage": coverage,
        "coverage_over_tp": coverage_over_tp,
    }


def evaluate_review_policy_gates(metrics: dict) -> dict:
    """Gates DUROS de seguridad, aplicados sobre `review_policy_safety_metrics`.

    Patron `strict_small_sample` (analogo a B3 del Bloque 7): con muestra por
    debajo de `MIN_SAMPLE_SIZE`, los gates de FAR/precision son `NOT_MEASURED`
    -- EXCEPTO si ya hay algun falso-aceptado, en cuyo caso son `FAIL`
    incondicionalmente (una muestra pequena no exime de un dano observado).
    """
    sample_size = int(metrics["sample_size"])
    false_accepts = int(metrics["false_accepts"])
    far = float(metrics["false_accept_rate"])
    precision = float(metrics["precision"])

    if sample_size < MIN_SAMPLE_SIZE:
        shared_status = "FAIL" if false_accepts > 0 else "NOT_MEASURED"
        far_status = shared_status
        precision_status = shared_status
        sample_status = shared_status
    else:
        far_status = "PASS" if far <= FALSE_ACCEPT_RATE_MAX else "FAIL"
        precision_status = "PASS" if precision >= PRECISION_MIN else "FAIL"
        sample_status = "PASS"

    return {
        "review_policy_false_accept_rate": {
            "status": far_status,
            "hard": True,
            "value": far,
            "threshold": FALSE_ACCEPT_RATE_MAX,
            "sample_size": sample_size,
        },
        "review_policy_precision": {
            "status": precision_status,
            "hard": True,
            "value": precision,
            "threshold": PRECISION_MIN,
            "sample_size": sample_size,
        },
        "review_policy_sample_size": {
            "status": sample_status,
            "hard": True,
            "value": sample_size,
            "threshold": MIN_SAMPLE_SIZE,
        },
        "review_policy_coverage": {
            # SOLO INFORMATIVA: nunca un minimo exigido (mandato del Organizador).
            "status": "INFORMATIVE",
            "hard": False,
            "value": metrics["coverage"],
            "value_over_tp": metrics["coverage_over_tp"],
            "threshold": None,
        },
    }


def decide_review_policy_verdict(gates: dict) -> tuple[str, str]:
    """Dictamen de seguridad de la politica (vocabulario cerrado y aditivo).

    NUNCA "PASS por defecto": si la muestra es insuficiente y no hay dano
    observado, el dictamen es "NO CALIBRABLE", no "APTA".
    """
    hard_names = (
        "review_policy_false_accept_rate",
        "review_policy_precision",
        "review_policy_sample_size",
    )
    statuses = {gates[n]["status"] for n in hard_names}

    if "FAIL" in statuses:
        failed = sorted(n for n in hard_names if gates[n]["status"] == "FAIL")
        return (
            "POLITICA DE REDUCCION: NO APTA (GATE DE SEGURIDAD EN FAIL)",
            f"gate(s) duro(s) en FAIL: {failed}",
        )
    if "NOT_MEASURED" in statuses:
        return (
            "POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)",
            "muestra auto-proposable insuficiente "
            f"({gates['review_policy_sample_size']['value']} < {MIN_SAMPLE_SIZE}) "
            "y sin falso-aceptado observado que fuerce FAIL: no se puede "
            "certificar ni descartar la politica con esta cobertura.",
        )
    return (
        "POLITICA DE REDUCCION: APTA (GATES DE SEGURIDAD EN PASS)",
        f"false_accept_rate={gates['review_policy_false_accept_rate']['value']} <= "
        f"{FALSE_ACCEPT_RATE_MAX} y precision="
        f"{gates['review_policy_precision']['value']} >= {PRECISION_MIN} "
        f"sobre sample_size={gates['review_policy_sample_size']['value']}.",
    )


# ---------------------------------------------------------------------------
# (3) Informe completo para UN modo (glue de alto nivel; aditivo)
# ---------------------------------------------------------------------------
def build_review_policy_report(
    corpus,
    run: BenchmarkRun,
    *,
    review_config: ReviewPolicyConfig = DEFAULT_REVIEW_POLICY_CONFIG,
    ensemble_config: Any = None,
) -> dict:
    """Informe de seguridad de la politica de revision para UN `BenchmarkRun`.

    Reutiliza el runner REAL (ya ejecutado por el llamante) y
    `matching.match_predictions`, SIN modificarlos.
    """
    used = list(getattr(run, "source_ids", []) or sorted(corpus.sources))
    used_set = set(used)
    ground_truth = [r for r in corpus.relations if r["source_id"] in used_set]

    predictions = predictions_with_review_policy(
        run, review_config=review_config, ensemble_config=ensemble_config)
    match = match_predictions(predictions, ground_truth)

    metrics = review_policy_safety_metrics(match)
    gates = evaluate_review_policy_gates(metrics)
    verdict, justification = decide_review_policy_verdict(gates)

    return {
        "review_policy_metrics_version": REVIEW_POLICY_METRICS_VERSION,
        "mode": run.mode,
        "review_policy_config": review_config.to_dict(),
        "review_policy_config_hash": review_config.config_hash,
        "sources_used": used,
        "metrics": metrics,
        "gates": gates,
        "verdict": verdict,
        "verdict_justification": justification,
    }


__all__ = [
    "REVIEW_POLICY_METRICS_VERSION",
    "FALSE_ACCEPT_RATE_MAX",
    "PRECISION_MIN",
    "MIN_SAMPLE_SIZE",
    "REVIEW_POLICY_VERDICTS",
    "predictions_with_review_policy",
    "review_policy_safety_metrics",
    "evaluate_review_policy_gates",
    "decide_review_policy_verdict",
    "build_review_policy_report",
]

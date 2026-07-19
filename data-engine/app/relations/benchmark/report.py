# -*- coding: utf-8 -*-
"""Ensamblado de resultados, GATES y dictamen del benchmark de relaciones.

Los gates se evaluan por SEPARADO (no se declara aptitud solo por el F1 global).
El dictamen pertenece a un vocabulario CERRADO y NUNCA usa "APTO PARA INGESTA
REAL". Los numeros que se reportan son los REALES del pipeline; no se maquillan.
"""
from __future__ import annotations

from typing import Any, Optional

from . import matching as _matching
from . import metrics as _metrics
from .matching import match_predictions
from .runner import BenchmarkRun

# Dictamenes permitidos (vocabulario cerrado). "APTO PARA INGESTA REAL" PROHIBIDO.
VERDICTS = (
    "APTO PARA CONTINUAR EN MODO SOMBRA",
    "APTO CON REVISION DE CASOS CONFLICTIVOS",
    "APTO CON REVISION HUMANA TOTAL",
    "NO APTO",
)

# Umbrales de los gates de calidad (deterministas y documentados en docs/50).
THRESHOLDS = {
    "simple_relations_recall": 0.80,
    "evidence": 0.80,
    "offsets": 0.90,
    "negation": 0.80,
    "temporality": 0.60,
    "rumors": 0.60,
    "predicate_structural": 0.50,
}


def _status(value: float, threshold: float, *, partial: float = 0.6) -> str:
    if value >= threshold:
        return "PASS"
    if value >= threshold * partial:
        return "PARTIAL"
    return "FAIL"


def evaluate_gates(match, struct: dict, contamination: dict, determinism: dict) -> dict:
    """Evalua los gates por separado. Devuelve dict gate -> {status, value, ...}."""
    sub = struct["subgroups"]
    gates: dict[str, dict] = {}

    # --- Gates DUROS (seguridad) ---
    gates["determinism"] = {
        "status": "PASS" if determinism["deterministic"] else "FAIL",
        "hard": True,
        "detail": determinism,
    }
    gates["workspace_contamination"] = {
        "status": "PASS" if contamination["clean"] else "FAIL",
        "hard": True,
        "detail": contamination,
    }

    # --- Gates de CALIDAD ---
    simple = sub["simple_relations"]["evidence_correct"]["rate"]
    gates["simple_relations"] = {
        "status": _status(simple, THRESHOLDS["simple_relations_recall"]),
        "value": simple, "threshold": THRESHOLDS["simple_relations_recall"],
        "detail": sub["simple_relations"],
    }
    gates["evidence"] = {
        "status": _status(struct["evidence_correct"]["rate"], THRESHOLDS["evidence"]),
        "value": struct["evidence_correct"]["rate"], "threshold": THRESHOLDS["evidence"],
        "detail": struct["evidence_correct"],
    }
    gates["offsets"] = {
        "status": _status(struct["offsets_correct"]["rate"], THRESHOLDS["offsets"]),
        "value": struct["offsets_correct"]["rate"], "threshold": THRESHOLDS["offsets"],
        "detail": struct["offsets_correct"],
    }
    neg = sub["negated_relations"]["negation_correct"]["rate"]
    gates["negation"] = {
        "status": _status(neg, THRESHOLDS["negation"]),
        "value": neg, "threshold": THRESHOLDS["negation"],
        "detail": sub["negated_relations"],
    }
    temp = sub["temporal_relations"]["temporal_correct"]["rate"]
    gates["temporality"] = {
        "status": _status(temp, THRESHOLDS["temporality"]),
        "value": temp, "threshold": THRESHOLDS["temporality"],
        "detail": sub["temporal_relations"],
    }
    rum = sub["rumored_relations"]["epistemic_correct"]["rate"]
    gates["rumors"] = {
        "status": _status(rum, THRESHOLDS["rumors"]),
        "value": rum, "threshold": THRESHOLDS["rumors"],
        "detail": sub["rumored_relations"],
    }
    gates["predicate_structural"] = {
        "status": _status(struct["predicate_correct"]["rate"], THRESHOLDS["predicate_structural"]),
        "value": struct["predicate_correct"]["rate"],
        "threshold": THRESHOLDS["predicate_structural"],
        "detail": struct["predicate_correct"],
    }
    return gates


def decide_verdict(gates: dict) -> tuple[str, str]:
    """Deriva el dictamen del benchmark del ESTADO REAL de los gates.

    Devuelve (dictamen, justificacion). No se usa "APTO PARA INGESTA REAL".
    """
    # Gates duros: si fallan, NO APTO.
    for name in ("determinism", "workspace_contamination"):
        if gates[name]["status"] != "PASS":
            return "NO APTO", f"gate duro '{name}' en FAIL"

    quality = ["simple_relations", "evidence", "offsets", "negation",
               "temporality", "rumors", "predicate_structural"]
    passed = [g for g in quality if gates[g]["status"] == "PASS"]
    failed = [g for g in quality if gates[g]["status"] == "FAIL"]

    # La calidad estructural del predicado (heuristica) y la direccion suelen ser
    # bajas: el pipeline es un PROPOSITOR en sombra, no un extractor autonomo.
    evidence_ok = gates["evidence"]["status"] != "FAIL" and gates["offsets"]["status"] == "PASS"
    predicate_ok = gates["predicate_structural"]["status"] == "PASS"

    if not failed and predicate_ok and evidence_ok:
        return ("APTO PARA CONTINUAR EN MODO SOMBRA",
                "sin gates de calidad en FAIL y predicado/evidencia solidos")
    if evidence_ok and not predicate_ok:
        return ("APTO CON REVISION HUMANA TOTAL",
                "evidencia/offsets fiables pero el predicado heuristico es debil: "
                "toda relacion requiere revision humana antes de considerarse")
    if len(failed) <= 2 and evidence_ok:
        return ("APTO CON REVISION DE CASOS CONFLICTIVOS",
                f"gates en FAIL acotados a casos dificiles: {failed}")
    return ("APTO CON REVISION HUMANA TOTAL",
            f"multiples gates de calidad en FAIL ({failed}); revision humana total")


def _contamination_report(run: BenchmarkRun, corpus) -> dict:
    """Comprueba contaminacion entre workspaces (cero cruces permitidos)."""
    cross = []
    for pred in run.predictions:
        expected_ws = corpus.workspace_by_source.get(pred["source_id"])
        if pred["workspace"] != expected_ws:
            cross.append(pred)
    # Errores de mezcla de workspace registrados por el propio pipeline.
    mix_errors = 0
    for sr in run.source_runs:
        for e in sr.output.get("errors", []):
            if e.get("code") == "workspace_mismatch":
                mix_errors += 1
    return {
        "clean": len(cross) == 0,
        "cross_workspace_predictions": len(cross),
        "workspace_mismatch_errors": mix_errors,
    }


def determinism_report(corpus, mode: str, reference: BenchmarkRun) -> dict:
    """Ejecuta el pipeline REAL una segunda vez y compara determinismo."""
    from .runner import run_benchmark

    second = run_benchmark(corpus, mode=mode)
    ref_hashes = reference.result_hashes()
    sec_hashes = second.result_hashes()
    hashes_equal = ref_hashes == sec_hashes

    ref_match = match_predictions(reference.predictions, corpus.relations)
    sec_match = match_predictions(second.predictions, corpus.relations)
    metrics_equal = _metrics.global_metrics(ref_match) == _metrics.global_metrics(sec_match)

    preds_equal = reference.predictions == second.predictions
    return {
        "deterministic": bool(hashes_equal and metrics_equal and preds_equal),
        "hashes_equal": hashes_equal,
        "metrics_equal": metrics_equal,
        "predictions_equal": preds_equal,
        "result_hashes": ref_hashes,
    }


def build_report(corpus, run: BenchmarkRun, *, check_determinism: bool = True) -> dict:
    """Ensambla el informe COMPLETO de resultados del benchmark."""
    match = match_predictions(run.predictions, corpus.relations)

    glob = _metrics.global_metrics(match)
    strict = _metrics.strict_metrics(match)
    per_pred = _metrics.per_predicate_metrics(match)
    pred_dist = _metrics.predicted_predicate_distribution(run.predictions)
    struct = _metrics.structural_quality(match)
    decision_conf = _metrics.decision_confusion(match)
    operational = _metrics.aggregate_operational(run.source_summaries, run.timings)

    contamination = _contamination_report(run, corpus)
    if check_determinism:
        determinism = determinism_report(corpus, run.mode, run)
    else:
        determinism = {"deterministic": None, "skipped": True}

    gates = evaluate_gates(match, struct, contamination, determinism)
    verdict, justification = decide_verdict(gates)

    false_positives = [
        {k: p[k] for k in ("source_id", "workspace", "subject_id", "object_id",
                           "predicate", "direction", "evidence_text", "consensus_state",
                           "recommendation")}
        for p in match.false_positives
    ]
    false_negatives = [
        {k: g[k] for k in ("relation_id", "source_id", "workspace", "subject_id",
                           "object_id", "predicate", "expected_decision", "annotator_notes")}
        for g in match.false_negatives
    ]

    derivation_notes = [n for sr in run.source_runs for n in sr.derivation_notes]

    return {
        "benchmark": "relation-benchmark-runner-v1",
        "mode": run.mode,
        "config": run.config,
        "versions": run.versions,
        "pipeline_version": run.versions.get("pipeline"),
        "code_sha": run.code_sha,
        "corpus": {
            "version": corpus.manifest.get("version"),
            "source_count": corpus.manifest.get("source_count"),
            "relation_count": corpus.manifest.get("relation_count"),
            "corpus_hashes": run.corpus_hashes,
            "ground_truth_sha256": corpus.manifest["ground_truth"]["sha256"],
        },
        "providers": {
            "local_llm": "NOT_EXECUTED (Ollama real jamas ejecutado)",
            "external_ai": "NOT_EXECUTED (NVIDIA real jamas ejecutada)",
            "network": "none",
            "writes": "none (dry-run, sin Neo4j)",
        },
        "metrics": {
            "global_existence": glob,
            "strict_predicate": strict,
            "per_predicate": per_pred,
            "predicted_predicate_distribution": pred_dist,
            "structural_quality": struct,
            "decision_confusion": decision_conf,
            "operational": operational,
        },
        "gates": gates,
        "verdict": verdict,
        "verdict_justification": justification,
        "errors": {
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "derivation_notes": derivation_notes,
        },
        "determinism": determinism,
        "result_hashes": run.result_hashes(),
    }


__all__ = [
    "VERDICTS",
    "THRESHOLDS",
    "evaluate_gates",
    "decide_verdict",
    "determinism_report",
    "build_report",
]

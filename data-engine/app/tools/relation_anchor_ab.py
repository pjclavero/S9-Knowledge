# -*- coding: utf-8 -*-
"""A/B offline del MODO DE ANCLAJE de evidencia (PR#95 V1).

Compara `span` (base, comportamiento historico) frente a `conservative` (anclaje
conservador basado en clausula + marcadores) sobre el corpus B1, usando el RUNNER
REAL del benchmark (`relations.benchmark.runner`): load_corpus / derive_entities /
build_payload / run_pipeline / extract_predictions, y el matching + metricas reales
(`matching.match_predictions`, `metrics.structural_quality`, `metrics.global_metrics`).

SIN red, SIN proveedores, SIN escritura a Neo4j: modo `baseline1` (heuristico puro).
La UNICA diferencia entre carriles es `PipelineConfig.evidence_anchor_mode`.

Uso:
    python3 -m tools.relation_anchor_ab            # imprime tabla + guarda JSON
    python3 -m tools.relation_anchor_ab --no-save  # solo imprime

NO inventa cifras: todo sale del pipeline real ejecutado aqui.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
from pathlib import Path
from typing import Any

from relations.pipeline import run_pipeline
from relations.benchmark import runner, matching, metrics

_APP_DIR = Path(__file__).resolve().parents[1]
_ARTIFACTS = _APP_DIR.parent.parent / "artifacts" / "pr95-variants" / "v1"

MODE = "baseline1"  # heuristico puro, offline, sin proveedores


def _run_mode(corpus: runner.Corpus, anchor_mode: str) -> list[dict]:
    """Ejecuta el pipeline REAL sobre todo el corpus con un `anchor_mode` dado.

    Replica los pasos de `runner.run_source` (mismo modo `baseline1`) pero fija
    `evidence_anchor_mode` en la config via `dataclasses.replace`, sin globales.
    """
    base_config = runner._config_for_mode(MODE)
    config = dataclasses.replace(base_config, evidence_anchor_mode=anchor_mode)
    preds: list[dict] = []
    for source_id in sorted(corpus.sources):
        text = corpus.sources[source_id]
        workspace = corpus.workspace_by_source[source_id]
        entities, _notes = runner.derive_entities(source_id, text, corpus.relations)
        payload = runner.build_payload(source_id, text, workspace, entities)
        output = run_pipeline(payload, config=config)
        preds.extend(runner.extract_predictions(output))
    return preds


def _gt_relations(corpus: runner.Corpus) -> list[dict]:
    return list(corpus.relations)


def _iou_list(match: matching.MatchResult) -> list[float]:
    return [m["flags"]["evidence_overlap_iou"] for m in match.true_positives]


def _summarize(anchor_mode: str, match: matching.MatchResult) -> dict:
    glob = metrics.global_metrics(match)
    sq = metrics.structural_quality(match)
    ious = _iou_list(match)
    mean_iou = round(statistics.mean(ious), 4) if ious else 0.0
    return {
        "anchor_mode": anchor_mode,
        "tp": match.tp,
        "fp": match.fp,
        "fn": match.fn,
        "f1": glob["f1"],
        "precision": glob["precision"],
        "recall": glob["recall"],
        "mean_iou": mean_iou,
        "evidence_correct": sq["evidence_correct"],       # {ok,total,rate}
        "offsets_correct": sq["offsets_correct"],
        "simple_relations": sq["subgroups"]["simple_relations"],
    }


def run_ab(save: bool = True) -> dict:
    corpus = runner.load_corpus(verify=True)
    gt = _gt_relations(corpus)

    results: dict[str, Any] = {"mode": MODE, "iou_threshold": matching.EVIDENCE_IOU_THRESHOLD,
                              "lanes": {}}
    for anchor_mode in ("span", "conservative"):
        preds = _run_mode(corpus, anchor_mode)
        match = matching.match_predictions(preds, gt)
        results["lanes"][anchor_mode] = _summarize(anchor_mode, match)

    if save:
        _ARTIFACTS.mkdir(parents=True, exist_ok=True)
        out_path = _ARTIFACTS / "ab_span_vs_conservative.json"
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        results["_saved_to"] = str(out_path)
    return results


def _fmt_rate(block: dict) -> str:
    return f"{block['ok']}/{block['total']} ({block['rate']:.4f})"


def print_table(results: dict) -> None:
    print(f"# A/B anclaje de evidencia  (modo={results['mode']}, "
          f"IoU>={results['iou_threshold']})")
    header = ["metric", "span", "conservative"]
    span = results["lanes"]["span"]
    cons = results["lanes"]["conservative"]
    rows = [
        ("TP", span["tp"], cons["tp"]),
        ("FP", span["fp"], cons["fp"]),
        ("FN", span["fn"], cons["fn"]),
        ("F1", f"{span['f1']:.4f}", f"{cons['f1']:.4f}"),
        ("mean IoU", f"{span['mean_iou']:.4f}", f"{cons['mean_iou']:.4f}"),
        ("evidence_correct", _fmt_rate(span["evidence_correct"]), _fmt_rate(cons["evidence_correct"])),
        ("offsets_correct", _fmt_rate(span["offsets_correct"]), _fmt_rate(cons["offsets_correct"])),
        ("simple_relations.evidence",
         _fmt_rate(span["simple_relations"]["evidence_correct"]),
         _fmt_rate(cons["simple_relations"]["evidence_correct"])),
    ]
    w0 = max(len(header[0]), *(len(str(r[0])) for r in rows))
    w1 = max(len(header[1]), *(len(str(r[1])) for r in rows))
    w2 = max(len(header[2]), *(len(str(r[2])) for r in rows))
    print(f"| {header[0]:<{w0}} | {header[1]:<{w1}} | {header[2]:<{w2}} |")
    print(f"| {'-'*w0} | {'-'*w1} | {'-'*w2} |")
    for r in rows:
        print(f"| {str(r[0]):<{w0}} | {str(r[1]):<{w1}} | {str(r[2]):<{w2}} |")
    if "_saved_to" in results:
        print(f"\nJSON guardado en: {results['_saved_to']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-save", action="store_true", help="no escribir JSON")
    args = ap.parse_args()
    results = run_ab(save=not args.no_save)
    print_table(results)


if __name__ == "__main__":
    main()

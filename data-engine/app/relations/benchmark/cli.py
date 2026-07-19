# -*- coding: utf-8 -*-
"""CLI del benchmark de relaciones: ejecuta el pipeline R8 REAL y emite salidas.

Salidas:
  * JSON de resultados (informe completo).
  * JSONL de predicciones (una linea por prediccion del pipeline REAL).
  * Resumen Markdown (para docs/50) con metricas globales, por tipo, gates y
    dictamen.

Uso:
    python -m relations.benchmark.cli --mode baseline1 \
        --out-json /tmp/results.json --out-jsonl /tmp/preds.jsonl \
        --out-md docs/50-relation-benchmark-results.md

NUNCA abre red, NUNCA ejecuta Ollama/NVIDIA reales, NUNCA escribe en Neo4j.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .report import build_report
from .runner import DEFAULT_MODE, MODES, load_corpus, run_benchmark


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def render_markdown(report: dict, *, all_modes: Optional[dict] = None) -> str:
    """Renderiza el resumen Markdown determinista del benchmark."""
    m = report["metrics"]
    g = m["global_existence"]
    s = m["strict_predicate"]
    lines: list[str] = []
    A = lines.append

    A("# 50 - Benchmark de extraccion de relaciones: resultados (v1)")
    A("")
    A("Ejecucion del pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el")
    A("corpus B1 **REAL** (`app/tests/data/relation_benchmark/`), comparado contra el")
    A("ground truth. El runner NO reimplementa ninguna etapa de R8 ni simula resultados.")
    A("El plan, el criterio de emparejamiento y la derivacion de entidades se documentan")
    A("en `docs/41-relation-benchmark-plan.md`.")
    A("")
    A("## Confirmacion de seguridad")
    A("")
    A(f"- Ollama real: **NOT_EXECUTED**")
    A(f"- NVIDIA real: **NOT_EXECUTED**")
    A(f"- Red: **ninguna**")
    A(f"- Escritura / Neo4j: **ninguna** (dry-run)")
    A(f"- Pipeline: `{report['pipeline_version']}` | code SHA: `{report['code_sha']}`")
    A("")
    A("## Configuracion")
    A("")
    A(f"- Modo del dictamen: `{report['mode']}` (config real: `{json.dumps(report['config'], sort_keys=True)}`)")
    A(f"- Corpus v{report['corpus']['version']}: {report['corpus']['source_count']} fuentes, "
      f"{report['corpus']['relation_count']} relaciones de ground truth")
    A(f"- Ground truth sha256: `{report['corpus']['ground_truth_sha256']}`")
    A(f"- Versiones de componentes: `{json.dumps(report['versions'], sort_keys=True)}`")
    A("")

    A("## Dictamen del benchmark")
    A("")
    A(f"### **{report['verdict']}**")
    A("")
    A(f"> {report['verdict_justification']}")
    A("")
    A("Nota: el vocabulario de dictamen NO incluye \"APTO PARA INGESTA REAL\". El")
    A("pipeline es un propositor en modo sombra / dry-run: nunca aprueba ni escribe.")
    A("")

    A("## Metricas globales (criterio de existencia: par no ordenado)")
    A("")
    A("| Metrica | Precision | Recall | F1 | TP | FP | FN |")
    A("|---|---|---|---|---|---|---|")
    A(f"| Existencia de relacion | {_fmt_pct(g['precision'])} | {_fmt_pct(g['recall'])} | "
      f"{_fmt_pct(g['f1'])} | {g['tp']} | {g['fp']} | {g['fn']} |")
    A(f"| Estricta (par + predicado exacto) | {_fmt_pct(s['precision'])} | {_fmt_pct(s['recall'])} | "
      f"{_fmt_pct(s['f1'])} | {s['tp']} | {s['fp']} | {s['fn']} |")
    A("")

    if all_modes:
        A("### Comparativa por modo (config real de PipelineConfig)")
        A("")
        A("| Modo | context_mode | P (exist.) | R (exist.) | F1 | pares generados |")
        A("|---|---|---|---|---|---|")
        for mode_name in sorted(all_modes):
            rr = all_modes[mode_name]
            gg = rr["metrics"]["global_existence"]
            cm = rr["config"]["context_mode"]
            pairs = rr["metrics"]["operational"]["counters"]["pairs_generated"]
            A(f"| {mode_name} | {cm} | {_fmt_pct(gg['precision'])} | {_fmt_pct(gg['recall'])} | "
              f"{_fmt_pct(gg['f1'])} | {pairs} |")
        A("")

    A("## Metricas por tipo de relacion (predicado del ground truth)")
    A("")
    A("| Predicado | Soporte | Recall existencia | Recall predicado exacto |")
    A("|---|---|---|---|")
    for pred, d in m["per_predicate"].items():
        A(f"| {pred} | {d['support']} | {_fmt_pct(d['recall_existence'])} | "
          f"{_fmt_pct(d['recall_exact'])} |")
    A("")
    A("### Distribucion de predicados PREDICHOS por el heuristico")
    A("")
    A("| Predicado predicho | Nº |")
    A("|---|---|")
    for pred, cnt in m["predicted_predicate_distribution"].items():
        A(f"| {pred} | {cnt} |")
    A("")

    A("## Calidad estructural (sobre los TP de existencia)")
    A("")
    sq = m["structural_quality"]
    A("| Atributo | Correctos / Total | Tasa |")
    A("|---|---|---|")
    for key in ("predicate_correct", "direction_correct", "direction_orientation_ok",
                "types_correct", "negation_correct", "temporal_correct",
                "epistemic_correct", "evidence_correct", "offsets_correct",
                "workspace_correct", "decision_correct"):
        d = sq[key]
        A(f"| {key} | {d['ok']}/{d['total']} | {_fmt_pct(d['rate'])} |")
    A("")

    A("## Metricas operativas (contadores REALES del pipeline)")
    A("")
    op = m["operational"]
    c = op["counters"]
    A("| Contador | Valor |")
    A("|---|---|")
    for key in ("documents", "segments", "segments_processed", "segments_failed",
                "entities", "pairs_potential", "pairs_generated", "pairs_discarded",
                "candidates_evaluated", "results_strong", "results_partial",
                "results_conflict", "results_invalid", "results_human", "errors"):
        A(f"| {key} | {c[key]} |")
    A(f"| tiempo total (ms) | {op['timings']['total_ms']} |")
    A(f"| tiempo por doc (ms) | {op['timings']['per_doc_ms']} |")
    A(f"| tiempo por candidato (ms) | {op['timings']['per_candidate_ms']} |")
    A(f"| tasa humana | {_fmt_pct(op['consensus_rates']['human_rate'])} |")
    A(f"| tasa conflicto | {_fmt_pct(op['consensus_rates']['conflict_rate'])} |")
    A(f"| tasa invalida | {_fmt_pct(op['consensus_rates']['invalid_rate'])} |")
    A("")

    A("## Gates (evaluados por separado)")
    A("")
    A("| Gate | Estado | Valor | Umbral | Tipo |")
    A("|---|---|---|---|---|")
    for name in ("determinism", "workspace_contamination", "simple_relations",
                 "evidence", "offsets", "negation", "temporality", "rumors",
                 "predicate_structural"):
        gate = report["gates"][name]
        val = gate.get("value")
        val_s = _fmt_pct(val) if isinstance(val, (int, float)) else "-"
        thr = gate.get("threshold")
        thr_s = _fmt_pct(thr) if isinstance(thr, (int, float)) else "-"
        hard = "DURO" if gate.get("hard") else "calidad"
        A(f"| {name} | **{gate['status']}** | {val_s} | {thr_s} | {hard} |")
    A("")

    A("## Determinismo")
    A("")
    det = report["determinism"]
    A(f"- Determinista (2 ejecuciones): **{det.get('deterministic')}**")
    A(f"- Hashes iguales: {det.get('hashes_equal')} | Metricas iguales: {det.get('metrics_equal')} | "
      f"Predicciones iguales: {det.get('predictions_equal')}")
    A("")

    A("## Errores destacados")
    A("")
    fn = report["errors"]["false_negatives"]
    fp = report["errors"]["false_positives"]
    notes = report["errors"]["derivation_notes"]
    A(f"- Falsos negativos (relaciones de GT no cubiertas): **{len(fn)}**")
    A(f"- Falsos positivos (predicciones sin GT): **{len(fp)}**")
    A(f"- Menciones no localizadas en la derivacion de entidades: **{len(notes)}**")
    A("")
    if fn:
        A("### Falsos negativos (primeros 20)")
        A("")
        A("| relation_id | source | predicado | sujeto->objeto | motivo |")
        A("|---|---|---|---|---|")
        for r in fn[:20]:
            A(f"| {r['relation_id']} | {r['source_id']} | {r['predicate']} | "
              f"{r['subject_id']}->{r['object_id']} | {r['annotator_notes'][:60]} |")
        A("")
    if fp:
        A("### Falsos positivos (primeros 20)")
        A("")
        A("| source | predicado | sujeto->objeto | consenso |")
        A("|---|---|---|---|")
        for r in fp[:20]:
            A(f"| {r['source_id']} | {r['predicate']} | {r['subject_id']}->{r['object_id']} | "
              f"{r['consensus_state']} |")
        A("")

    return "\n".join(lines) + "\n"


def render_predictions_jsonl(report_predictions: list[dict]) -> str:
    lines = [json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
             for p in report_predictions]
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de relaciones (pipeline R8 REAL)")
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=sorted(MODES),
                        help="modo (config real de PipelineConfig) para el dictamen")
    parser.add_argument("--all-modes", action="store_true",
                        help="ejecutar tambien los demas modos para la comparativa")
    parser.add_argument("--corpus-dir", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-jsonl", default=None)
    parser.add_argument("--out-md", default=None)
    parser.add_argument("--no-determinism", action="store_true",
                        help="omitir la segunda ejecucion de determinismo (mas rapido)")
    args = parser.parse_args(argv)

    corpus = load_corpus(args.corpus_dir)
    run = run_benchmark(corpus, mode=args.mode)
    report = build_report(corpus, run, check_determinism=not args.no_determinism)

    all_modes = None
    if args.all_modes:
        all_modes = {}
        for mode_name in sorted(MODES):
            r = run if mode_name == args.mode else run_benchmark(corpus, mode=mode_name)
            all_modes[mode_name] = build_report(corpus, r, check_determinism=False)

    predictions = run.predictions

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    if args.out_jsonl:
        Path(args.out_jsonl).write_text(render_predictions_jsonl(predictions), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(render_markdown(report, all_modes=all_modes), encoding="utf-8")

    g = report["metrics"]["global_existence"]
    print(f"mode={report['mode']} verdict={report['verdict']!r}")
    print(f"global P={g['precision']} R={g['recall']} F1={g['f1']} TP={g['tp']} FP={g['fp']} FN={g['fn']}")
    print(f"deterministic={report['determinism'].get('deterministic')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

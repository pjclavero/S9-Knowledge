"""Comparador de métricas del benchmark S9 Knowledge.

Lee los outputs capturados por extractor_benchmark.py y los compara contra
ground-truth para calcular precisión, recall y F1 por fuente y modo.

Uso:
  python data-engine/app/cli/benchmark_comparator.py \\
      --run-dir benchmark-results/20240101-120000 \\
      --ground-truth-dir tests/fixtures/benchmark/

Output:
  benchmark-results/<run_id>/metrics.json
  benchmark-results/<run_id>/report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Normalización y matching
# ---------------------------------------------------------------------------

def normalize(s: str) -> str:
    """Normaliza un nombre para comparación: minúsculas + strip."""
    return s.lower().strip()


def is_match(candidate_name: str, ground_truth_name: str, aliases: list[str]) -> Optional[str]:
    """
    Comprueba si candidate_name coincide con ground_truth_name o sus aliases.

    Returns:
        "exact_match" | "alias_match" | None
    """
    if normalize(candidate_name) == normalize(ground_truth_name):
        return "exact_match"
    if any(normalize(candidate_name) == normalize(a) for a in aliases):
        return "alias_match"
    return None


# ---------------------------------------------------------------------------
# Métricas de entidades
# ---------------------------------------------------------------------------

def _compute_entity_metrics(approved_entities: list[dict], ground_truth: dict) -> dict:
    """
    Calcula TP/FP/FN para entidades.

    Ground truth structure:
      {
        "entities": [{"name": "...", "aliases": [...], "expected": true/false}, ...],
        "negative_entities": ["name1", "name2", ...]
      }
    """
    expected_entities = [
        e for e in ground_truth.get("entities", []) if e.get("expected", True)
    ]
    # Supports both list[str] and list[{"name": ..., "reason": ...}]
    raw_neg = ground_truth.get("negative_entities", [])
    negative_names = {normalize(n["name"] if isinstance(n, dict) else n) for n in raw_neg}

    # Construir lookup: nombre_normalizado → entry de ground truth
    gt_lookup: dict[str, dict] = {}
    for e in expected_entities:
        key = normalize(e["name"])
        gt_lookup[key] = e
        for alias in e.get("aliases", []):
            alias_key = normalize(alias)
            if alias_key not in gt_lookup:
                gt_lookup[alias_key] = e

    matched_gt_names: set[str] = set()  # nombres de GT que tuvieron TP
    tp = 0
    fp = 0

    for cand in approved_entities:
        cand_name = cand.get("name", "")
        matched = False

        for gt_name, gt_entry in gt_lookup.items():
            match_type = is_match(cand_name, gt_entry["name"], gt_entry.get("aliases", []))
            if match_type:
                tp += 1
                matched_gt_names.add(normalize(gt_entry["name"]))
                matched = True
                break

        if not matched:
            # FP: nombre en negative_entities o no en ground truth
            fp += 1

    # FN: entidades esperadas no encontradas en approved
    fn = len(expected_entities) - len(matched_gt_names)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "total_approved": len(approved_entities),
        "total_expected": len(expected_entities),
    }


# ---------------------------------------------------------------------------
# Métricas de relaciones
# ---------------------------------------------------------------------------

def _relation_key(r: dict) -> tuple[str, str, str]:
    """Clave normalizada para una relación: (from_entity, relation_type, to_entity)."""
    return (
        normalize(r.get("from_entity", r.get("from", ""))),
        normalize(r.get("relation_type", r.get("type", ""))),
        normalize(r.get("to_entity", r.get("to", ""))),
    )


def _compute_relation_metrics(approved_relations: list[dict], ground_truth: dict) -> dict:
    """
    Calcula TP/FP/FN para relaciones.

    Ground truth structure:
      {
        "relations": [{"from_entity": "...", "relation_type": "...", "to_entity": "...", "expected": true}, ...],
        "negative_relations": [{"from_entity": "...", "relation_type": "...", "to_entity": "..."}]
      }
    """
    expected_relations = [
        r for r in ground_truth.get("relations", []) if r.get("expected", True)
    ]
    negative_keys = {
        _relation_key(r) for r in ground_truth.get("negative_relations", [])
    }
    expected_keys = {_relation_key(r) for r in expected_relations}

    tp = 0
    fp = 0
    matched_expected: set[tuple] = set()

    for rel in approved_relations:
        key = _relation_key(rel)
        if key in expected_keys:
            tp += 1
            matched_expected.add(key)
        else:
            # FP: está en negatives o simplemente no en ground truth
            fp += 1

    fn = len(expected_keys) - len(matched_expected)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "total_approved": len(approved_relations),
        "total_expected": len(expected_relations),
    }


# ---------------------------------------------------------------------------
# Carga de payloads
# ---------------------------------------------------------------------------

def _load_approved_payload(path: Path) -> dict:
    """Carga approved_payload.json y retorna dict con listas de entities y relations."""
    if not path.exists():
        return {"entities": [], "relations": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        approved = payload.get("approved", [])
        entities = [a for a in approved if a.get("kind") == "entity"]
        relations = [a for a in approved if a.get("kind") == "relation"]
        return {"entities": entities, "relations": relations}
    except Exception as e:
        return {"entities": [], "relations": [], "_error": str(e)}


def _load_duration_ms(path: Path) -> int:
    """Lee duration_ms.txt de un run_dir/source_id/."""
    dur_file = path / "duration_ms.txt"
    if dur_file.exists():
        try:
            return int(dur_file.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------------------
# Varianza de F1 (reproducibilidad LLM/hybrid)
# ---------------------------------------------------------------------------

def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Umbrales
# ---------------------------------------------------------------------------

_THRESHOLDS = {
    "precision_entities_min": 0.85,
    "recall_entities_min": 0.70,
    "f1_entities_min": 0.75,
    "precision_relations_min": 0.75,
    "recall_relations_min": 0.60,
    "duplicate_rate_max": 0.10,
    "invalid_relation_rate_max": 0.05,
}


def _check_thresholds(aggregate: dict) -> dict:
    """Comprueba si los valores agregados pasan los umbrales."""
    results = {}
    for mode in ("heuristic", "llm", "hybrid"):
        mode_agg = aggregate.get(mode, {})
        mode_pass = {}
        mode_pass["precision_entities"] = (
            mode_agg.get("mean_precision_entities", 0.0) >= _THRESHOLDS["precision_entities_min"]
        )
        mode_pass["recall_entities"] = (
            mode_agg.get("mean_recall_entities", 0.0) >= _THRESHOLDS["recall_entities_min"]
        )
        mode_pass["f1_entities"] = (
            mode_agg.get("mean_f1_entities", 0.0) >= _THRESHOLDS["f1_entities_min"]
        )
        mode_pass["precision_relations"] = (
            mode_agg.get("mean_precision_relations", 0.0) >= _THRESHOLDS["precision_relations_min"]
        )
        mode_pass["recall_relations"] = (
            mode_agg.get("mean_recall_relations", 0.0) >= _THRESHOLDS["recall_relations_min"]
        )
        results[mode] = mode_pass
    return results


# ---------------------------------------------------------------------------
# Comparador principal
# ---------------------------------------------------------------------------

def compare(run_dir: Path, ground_truth_dir: Path) -> dict:
    """
    Compara todos los outputs del benchmark contra el ground truth.

    Returns:
        metrics dict listo para serializar.
    """
    run_id = run_dir.name

    # Buscar fuentes disponibles en el run_dir
    # Estructura: run_dir/heuristic/<source_id>/, run_dir/llm-run-1/<source_id>/, etc.
    source_ids: set[str] = set()
    for subdir in run_dir.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("."):
            for source_dir in subdir.iterdir():
                if source_dir.is_dir():
                    source_ids.add(source_dir.name)

    # Excluir directorios que no son de run (archivos de configuración, etc.)
    source_ids.discard("metrics.json")
    source_ids.discard("report.md")

    by_source_and_mode: dict[str, dict] = {}

    for source_id in sorted(source_ids):
        gt_path = ground_truth_dir / f"{source_id}-ground-truth.json"
        if not gt_path.exists():
            # Intentar con nombre alternativo
            alt_path = ground_truth_dir / source_id / "ground-truth.json"
            if alt_path.exists():
                gt_path = alt_path
            else:
                print(
                    f"  [WARN] ground truth no encontrado para {source_id}: {gt_path}",
                    file=sys.stderr,
                )
                continue

        ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
        source_metrics: dict[str, dict] = {}

        # --- heuristic (1 run) ---
        heuristic_dir = run_dir / "heuristic" / source_id
        if heuristic_dir.exists():
            payload = _load_approved_payload(heuristic_dir / "approved_payload.json")
            entity_m = _compute_entity_metrics(payload["entities"], ground_truth)
            relation_m = _compute_relation_metrics(payload["relations"], ground_truth)
            duration = _load_duration_ms(heuristic_dir)
            source_metrics["heuristic"] = {
                "entities": entity_m,
                "relations": relation_m,
                "duration_ms": duration,
            }

        # --- llm (N runs) ---
        llm_runs = []
        for run_n in range(1, 10):  # hasta 9 runs
            llm_dir = run_dir / f"llm-run-{run_n}" / source_id
            if not llm_dir.exists():
                break
            payload = _load_approved_payload(llm_dir / "approved_payload.json")
            entity_m = _compute_entity_metrics(payload["entities"], ground_truth)
            relation_m = _compute_relation_metrics(payload["relations"], ground_truth)
            duration = _load_duration_ms(llm_dir)
            llm_runs.append({
                "run": run_n,
                "entities": entity_m,
                "relations": relation_m,
                "duration_ms": duration,
            })

        if llm_runs:
            f1_ent_values = [r["entities"]["f1"] for r in llm_runs]
            f1_rel_values = [r["relations"]["f1"] for r in llm_runs]
            n_cands_values = [r["entities"]["total_approved"] for r in llm_runs]
            source_metrics["llm"] = {
                "runs": llm_runs,
                "mean_f1_entities": round(_mean(f1_ent_values), 4),
                "variance_f1_entities": round(_variance(f1_ent_values), 6),
                "mean_f1_relations": round(_mean(f1_rel_values), 4),
                "variance_f1_relations": round(_variance(f1_rel_values), 6),
                "mean_n_candidates": round(_mean(n_cands_values), 2),
                "variance_n_candidates": round(_variance(n_cands_values), 4),
            }

        # --- hybrid (N runs) ---
        hybrid_runs = []
        for run_n in range(1, 10):
            hybrid_dir = run_dir / f"hybrid-run-{run_n}" / source_id
            if not hybrid_dir.exists():
                break
            payload = _load_approved_payload(hybrid_dir / "approved_payload.json")
            entity_m = _compute_entity_metrics(payload["entities"], ground_truth)
            relation_m = _compute_relation_metrics(payload["relations"], ground_truth)
            duration = _load_duration_ms(hybrid_dir)
            hybrid_runs.append({
                "run": run_n,
                "entities": entity_m,
                "relations": relation_m,
                "duration_ms": duration,
            })

        if hybrid_runs:
            f1_ent_values = [r["entities"]["f1"] for r in hybrid_runs]
            f1_rel_values = [r["relations"]["f1"] for r in hybrid_runs]
            n_cands_values = [r["entities"]["total_approved"] for r in hybrid_runs]
            source_metrics["hybrid"] = {
                "runs": hybrid_runs,
                "mean_f1_entities": round(_mean(f1_ent_values), 4),
                "variance_f1_entities": round(_variance(f1_ent_values), 6),
                "mean_f1_relations": round(_mean(f1_rel_values), 4),
                "variance_f1_relations": round(_variance(f1_rel_values), 6),
                "mean_n_candidates": round(_mean(n_cands_values), 2),
                "variance_n_candidates": round(_variance(n_cands_values), 4),
            }

        by_source_and_mode[source_id] = source_metrics

    # ---------------------------------------------------------------------------
    # Aggregate
    # ---------------------------------------------------------------------------
    aggregate: dict[str, dict] = {}

    for mode in ("heuristic", "llm", "hybrid"):
        prec_ent, rec_ent, f1_ent = [], [], []
        prec_rel, rec_rel, f1_rel = [], [], []

        for source_id, source_data in by_source_and_mode.items():
            if mode not in source_data:
                continue

            if mode == "heuristic":
                m = source_data[mode]
                prec_ent.append(m["entities"]["precision"])
                rec_ent.append(m["entities"]["recall"])
                f1_ent.append(m["entities"]["f1"])
                prec_rel.append(m["relations"]["precision"])
                rec_rel.append(m["relations"]["recall"])
                f1_rel.append(m["relations"]["f1"])
            else:
                # LLM / hybrid: usar media de runs
                m = source_data[mode]
                runs = m.get("runs", [])
                if runs:
                    prec_ent.append(_mean([r["entities"]["precision"] for r in runs]))
                    rec_ent.append(_mean([r["entities"]["recall"] for r in runs]))
                    f1_ent.append(m.get("mean_f1_entities", 0.0))
                    prec_rel.append(_mean([r["relations"]["precision"] for r in runs]))
                    rec_rel.append(_mean([r["relations"]["recall"] for r in runs]))
                    f1_rel.append(m.get("mean_f1_relations", 0.0))

        if prec_ent:
            aggregate[mode] = {
                "mean_precision_entities": round(_mean(prec_ent), 4),
                "mean_recall_entities": round(_mean(rec_ent), 4),
                "mean_f1_entities": round(_mean(f1_ent), 4),
                "mean_precision_relations": round(_mean(prec_rel), 4),
                "mean_recall_relations": round(_mean(rec_rel), 4),
                "mean_f1_relations": round(_mean(f1_rel), 4),
                "n_sources": len(prec_ent),
            }
        else:
            aggregate[mode] = {}

    threshold_pass = _check_thresholds(aggregate)

    metrics = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ground_truth_dir": str(ground_truth_dir),
        "by_source_and_mode": by_source_and_mode,
        "aggregate": aggregate,
        "thresholds": _THRESHOLDS,
        "threshold_pass": threshold_pass,
    }

    return metrics


# ---------------------------------------------------------------------------
# Generación de report.md
# ---------------------------------------------------------------------------

def _write_report(metrics: dict, run_dir: Path) -> Path:
    """Genera report.md con tablas markdown a partir del dict de métricas."""
    run_id = metrics["run_id"]
    aggregate = metrics["aggregate"]
    threshold_pass = metrics["threshold_pass"]
    lines = [
        f"# Benchmark Report — {run_id}",
        "",
        f"Generado: {metrics['generated_at']}",
        f"Ground truth: {metrics['ground_truth_dir']}",
        "",
        "## Resumen agregado (media entre fuentes)",
        "",
        "| Modo | P_ent | R_ent | F1_ent | P_rel | R_rel | F1_rel | Fuentes |",
        "|------|-------|-------|--------|-------|-------|--------|---------|",
    ]

    for mode in ("heuristic", "llm", "hybrid"):
        m = aggregate.get(mode, {})
        if not m:
            lines.append(f"| {mode} | — | — | — | — | — | — | 0 |")
            continue
        tp_ent = threshold_pass.get(mode, {}).get("f1_entities", False)
        f1_mark = "**" if tp_ent else ""
        lines.append(
            f"| {mode} "
            f"| {m.get('mean_precision_entities', 0):.3f} "
            f"| {m.get('mean_recall_entities', 0):.3f} "
            f"| {f1_mark}{m.get('mean_f1_entities', 0):.3f}{f1_mark} "
            f"| {m.get('mean_precision_relations', 0):.3f} "
            f"| {m.get('mean_recall_relations', 0):.3f} "
            f"| {m.get('mean_f1_relations', 0):.3f} "
            f"| {m.get('n_sources', 0)} |"
        )

    lines += [
        "",
        "_(F1_ent en **negrita** = supera umbral ≥ 0.75)_",
        "",
        "## Umbrales",
        "",
        "| Métrica | Umbral | heuristic | llm | hybrid |",
        "|---------|--------|-----------|-----|--------|",
    ]

    threshold_keys = [
        ("precision_entities_min", "P_ent ≥", "precision_entities"),
        ("recall_entities_min", "R_ent ≥", "recall_entities"),
        ("f1_entities_min", "F1_ent ≥", "f1_entities"),
        ("precision_relations_min", "P_rel ≥", "precision_relations"),
        ("recall_relations_min", "R_rel ≥", "recall_relations"),
    ]
    thresholds = metrics["thresholds"]
    for tkey, label, pass_key in threshold_keys:
        row = f"| {label} {thresholds[tkey]} | {thresholds[tkey]}"
        for mode in ("heuristic", "llm", "hybrid"):
            passed = threshold_pass.get(mode, {}).get(pass_key, False)
            row += f" | {'PASS' if passed else 'FAIL'}"
        row += " |"
        lines.append(row)

    lines += ["", "## Detalle por fuente", ""]

    for source_id, source_data in metrics.get("by_source_and_mode", {}).items():
        lines.append(f"### {source_id}")
        lines.append("")
        lines.append("| Modo | Run | P_ent | R_ent | F1_ent | P_rel | R_rel | F1_rel | ms |")
        lines.append("|------|-----|-------|-------|--------|-------|-------|--------|-----|")

        # heuristic
        if "heuristic" in source_data:
            m = source_data["heuristic"]
            e = m["entities"]
            r = m["relations"]
            lines.append(
                f"| heuristic | 1 "
                f"| {e['precision']:.3f} | {e['recall']:.3f} | {e['f1']:.3f} "
                f"| {r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} "
                f"| {m['duration_ms']} |"
            )

        # llm
        if "llm" in source_data:
            for run_data in source_data["llm"].get("runs", []):
                e = run_data["entities"]
                r = run_data["relations"]
                lines.append(
                    f"| llm | {run_data['run']} "
                    f"| {e['precision']:.3f} | {e['recall']:.3f} | {e['f1']:.3f} "
                    f"| {r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} "
                    f"| {run_data['duration_ms']} |"
                )
            llm_m = source_data["llm"]
            lines.append(
                f"| **llm_mean** | — "
                f"| — | — | **{llm_m.get('mean_f1_entities', 0):.3f}** "
                f"| — | — | **{llm_m.get('mean_f1_relations', 0):.3f}** "
                f"| — | "
            )

        # hybrid
        if "hybrid" in source_data:
            for run_data in source_data["hybrid"].get("runs", []):
                e = run_data["entities"]
                r = run_data["relations"]
                lines.append(
                    f"| hybrid | {run_data['run']} "
                    f"| {e['precision']:.3f} | {e['recall']:.3f} | {e['f1']:.3f} "
                    f"| {r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} "
                    f"| {run_data['duration_ms']} |"
                )
            hybrid_m = source_data["hybrid"]
            lines.append(
                f"| **hybrid_mean** | — "
                f"| — | — | **{hybrid_m.get('mean_f1_entities', 0):.3f}** "
                f"| — | — | **{hybrid_m.get('mean_f1_relations', 0):.3f}** "
                f"| — |"
            )

        lines.append("")

    lines += [
        "---",
        "",
        "_Informe de solo lectura. Ninguna entidad fue modificada ni ingestada._",
        "",
    ]

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Comparador de métricas del benchmark S9 Knowledge. "
            "Lee approved_payload.json capturados por extractor_benchmark.py "
            "y los compara contra ground-truth para calcular P/R/F1."
        ),
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        dest="run_dir",
        help="Directorio de una ejecución del benchmark (ej: benchmark-results/20240101-120000)",
    )
    parser.add_argument(
        "--ground-truth-dir",
        required=True,
        dest="ground_truth_dir",
        help="Directorio con archivos <source_id>-ground-truth.json",
    )

    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        # Calcular repo root relativo al script
        _cli = Path(__file__).resolve().parent
        _repo = _cli.parents[2]
        run_dir = _repo / run_dir

    ground_truth_dir = Path(args.ground_truth_dir)
    if not ground_truth_dir.is_absolute():
        _cli = Path(__file__).resolve().parent
        _repo = _cli.parents[2]
        ground_truth_dir = _repo / ground_truth_dir

    if not run_dir.exists():
        print(f"ERROR: run_dir no encontrado: {run_dir}", file=sys.stderr)
        sys.exit(1)

    if not ground_truth_dir.exists():
        print(f"ERROR: ground_truth_dir no encontrado: {ground_truth_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Comparando benchmark: {run_dir.name}")
    print(f"Ground truth: {ground_truth_dir}")

    metrics = compare(run_dir, ground_truth_dir)

    # Guardar metrics.json
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Métricas guardadas en: {metrics_path}")

    # Generar report.md
    report_path = _write_report(metrics, run_dir)
    print(f"Reporte guardado en:   {report_path}")

    # Mostrar resumen en terminal
    print("\n=== Resumen agregado ===")
    for mode in ("heuristic", "llm", "hybrid"):
        agg = metrics["aggregate"].get(mode, {})
        if agg:
            print(
                f"  {mode:10s}: "
                f"P_ent={agg.get('mean_precision_entities', 0):.3f}  "
                f"R_ent={agg.get('mean_recall_entities', 0):.3f}  "
                f"F1_ent={agg.get('mean_f1_entities', 0):.3f}  "
                f"F1_rel={agg.get('mean_f1_relations', 0):.3f}"
            )
        else:
            print(f"  {mode:10s}: (sin datos)")

    print("\n=== Umbrales ===")
    for mode, mode_pass in metrics["threshold_pass"].items():
        passing = all(mode_pass.values())
        status = "PASS" if passing else "FAIL"
        print(f"  {mode:10s}: {status}  {mode_pass}")


if __name__ == "__main__":
    main()

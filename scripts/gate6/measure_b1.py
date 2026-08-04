# -*- coding: utf-8 -*-
"""Runner del bloque B1 (puerta 6, programa de factividad composicional).

Extiende `measure.py` (B0): mide el MISMO arnes unificado
(`knowledge_v3.eval.gate6_harness.measure_gate6_program`) sobre la politica
YA CORREGIDA por B1 (operador de discurso reportado por tercero, "mientras
no" como condicional, extension de `SCOPE_VERBS`), y lo compara fila a fila
contra `artifacts/gate6-program/b0-baseline.json` para que el informe
resultante muestre, sin cifras a mano, exactamente que cambio: por corpus,
por familia, y caso a caso (que casos empezaron/dejaron de leerse como
hecho, y cuales cambiaron de clase sin cambiar de veredicto de "hecho").

Uso (desde la raiz del repo):

    PYTHONPATH=data-engine/app python3 scripts/gate6/measure_b1.py \
        --baseline artifacts/gate6-program/b0-baseline.json \
        --out-dir artifacts/gate6-program --out-name b1-operators
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from knowledge_v3.eval.gate6_harness import measure_gate6_program


def _rows_by_id(corpus_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["case_id"]: row for row in corpus_report["rows"]}


def _diff_corpus(
    name: str, baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    base_rows = _rows_by_id(baseline)
    cur_rows = _rows_by_id(current)
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    changed_class_same_verdict: list[dict[str, Any]] = []
    for case_id, base_row in base_rows.items():
        cur_row = cur_rows.get(case_id)
        if cur_row is None:
            continue
        if base_row["correct"] and not cur_row["correct"]:
            regressions.append(
                {
                    "case_id": case_id,
                    "family": base_row["family"],
                    "before": base_row["predicted_class"],
                    "after": cur_row["predicted_class"],
                }
            )
        elif not base_row["correct"] and cur_row["correct"]:
            improvements.append(
                {
                    "case_id": case_id,
                    "family": base_row["family"],
                    "before": base_row["predicted_class"],
                    "after": cur_row["predicted_class"],
                }
            )
        elif base_row["predicted_class"] != cur_row["predicted_class"]:
            changed_class_same_verdict.append(
                {
                    "case_id": case_id,
                    "family": base_row["family"],
                    "before": base_row["predicted_class"],
                    "after": cur_row["predicted_class"],
                    "correct_before": base_row["correct"],
                    "correct_after": cur_row["correct"],
                }
            )
    return {
        "corpus": name,
        "metrics_before": baseline["metrics_global"],
        "metrics_after": current["metrics_global"],
        "regressions": regressions,
        "improvements": improvements,
        "changed_class_same_verdict": changed_class_same_verdict,
    }


def _diff_violations(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    def _key(v: dict[str, Any]) -> tuple[str, str]:
        return (v["corpus"], v["case_id"])

    base_v = {_key(v): v for v in baseline["violations"]}
    cur_v = {_key(v): v for v in current["violations"]}
    resolved = [base_v[k] for k in base_v if k not in cur_v]
    new = [cur_v[k] for k in cur_v if k not in base_v]
    still = [cur_v[k] for k in cur_v if k in base_v]
    return {
        "count_before": len(base_v),
        "count_after": len(cur_v),
        "resolved": sorted(resolved, key=lambda v: (v["corpus"], v["case_id"])),
        "new": sorted(new, key=lambda v: (v["corpus"], v["case_id"])),
        "still_violating": sorted(still, key=lambda v: (v["corpus"], v["case_id"])),
    }


def build_b1_report(baseline: dict[str, Any]) -> dict[str, Any]:
    current = measure_gate6_program()
    dev_diff = _diff_corpus(
        "dev", baseline["corpora"]["dev"], current["corpora"]["dev"]
    )
    gen_diff = _diff_corpus(
        "generalization",
        baseline["corpora"]["generalization"],
        current["corpora"]["generalization"],
    )
    violations_diff = _diff_violations(
        baseline["fail_closed_invariant"], current["fail_closed_invariant"]
    )
    return {
        "gate": "6",
        "block": "B1",
        "purpose": (
            "Bloque B1: cierra, por prioridad del dictamen del revisor, el "
            "operador de discurso reportado por tercero (familias "
            "NESTED_REPORT + REPORT_OF_NEGATION, 12/40 violaciones de B0), "
            "'mientras no' como condicional sin convertir usos temporales, "
            "y diagnostica (sin corregir, por riesgo de sobreajuste) el bug "
            "de 'nunca' con objeto locativo. Extiende ademas SCOPE_VERBS con "
            "verbos factivos/de reconocimiento (admitir/reconocer/"
            "verificar/aceptar), bonus de bajo riesgo sobre la misma familia "
            "arquitectonica ya cubierta por 'confirmar'. Compara fila a "
            "fila contra b0-baseline.json: ninguna cifra de esta comparacion "
            "esta escrita a mano."
        ),
        "current": current,
        "comparison_vs_b0": {
            "dev": dev_diff,
            "generalization": gen_diff,
            "fail_closed_violations": violations_diff,
        },
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    cmp = report["comparison_vs_b0"]
    dev = cmp["dev"]
    gen = cmp["generalization"]
    viol = cmp["fail_closed_violations"]

    add("# Puerta 6 — B1: operadores (discurso reportado, 'mientras no', extension de SCOPE_VERBS)")
    add("")
    add(report["purpose"])
    add("")
    add("## 1. Cifras globales, antes (B0) / despues (B1)")
    add("")
    add("| corpus | metrica | B0 | B1 |")
    add("| --- | --- | ---: | ---: |")
    for key in dev["metrics_before"]:
        b = dev["metrics_before"][key]
        a = dev["metrics_after"][key]
        add(f"| dev | `{key}` | {b:.3f} | {a:.3f} |")
    for key in gen["metrics_before"]:
        b = gen["metrics_before"][key]
        a = gen["metrics_after"][key]
        bs = "n/d" if b is None else f"{b:.3f}"
        as_ = "n/d" if a is None else f"{a:.3f}"
        add(f"| generalizacion | `{key}` | {bs} | {as_} |")
    add("")
    add("## 2. Invariante fail-closed: violaciones")
    add("")
    add(f"- Antes (B0): **{viol['count_before']}**")
    add(f"- Despues (B1): **{viol['count_after']}**")
    add(f"- Resueltas: **{len(viol['resolved'])}**")
    add(f"- Nuevas (regresion): **{len(viol['new'])}**")
    add("")
    if viol["new"]:
        add("### Violaciones NUEVAS (regresion, requiere investigar)")
        add("")
        add("| corpus | caso | familia | clase leida |")
        add("| --- | --- | --- | --- |")
        for v in viol["new"]:
            add(f"| {v['corpus']} | {v['case_id']} | {v['family']} | {v['predicted_class']} |")
        add("")
    add("### Violaciones que siguen abiertas")
    add("")
    if viol["still_violating"]:
        by_family: dict[str, int] = {}
        for v in viol["still_violating"]:
            by_family[v["family"]] = by_family.get(v["family"], 0) + 1
        add("| familia | casos |")
        add("| --- | ---: |")
        for fam, n in sorted(by_family.items()):
            add(f"| {fam} | {n} |")
    else:
        add("Ninguna: 0 violaciones fail-closed.")
    add("")
    add("## 3. Cambios caso a caso (dev)")
    add("")
    add(f"Mejoras: {len(dev['improvements'])} · Regresiones: {len(dev['regressions'])} "
        f"· Cambio de clase sin cambio de veredicto: {len(dev['changed_class_same_verdict'])}")
    add("")
    for row in dev["improvements"]:
        add(f"- MEJORA `{row['case_id']}` ({row['family']}): {row['before']} -> {row['after']}")
    for row in dev["regressions"]:
        add(f"- REGRESION `{row['case_id']}` ({row['family']}): {row['before']} -> {row['after']}")
    add("")
    add("## 4. Cambios caso a caso (generalizacion composicional)")
    add("")
    add(f"Mejoras: {len(gen['improvements'])} · Regresiones: {len(gen['regressions'])} "
        f"· Cambio de clase sin cambio de veredicto: {len(gen['changed_class_same_verdict'])}")
    add("")
    for row in gen["improvements"]:
        add(f"- MEJORA `{row['case_id']}` ({row['family']}): {row['before']} -> {row['after']}")
    for row in gen["regressions"]:
        add(f"- REGRESION `{row['case_id']}` ({row['family']}): {row['before']} -> {row['after']}")
    add("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 6 (B1): comparacion contra b0-baseline.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="b1-operators")
    args = parser.parse_args(argv)

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    report = build_b1_report(baseline)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    markdown = to_markdown(report)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.out_name}.json").write_text(payload, encoding="utf-8")
        (out / f"{args.out_name}.md").write_text(markdown, encoding="utf-8")
        print(f"escrito en {out}/{args.out_name}.{{json,md}}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

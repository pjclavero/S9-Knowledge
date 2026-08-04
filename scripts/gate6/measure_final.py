# -*- coding: utf-8 -*-
"""Runner del bloque B2-FINAL (puerta 6, programa de factividad composicional).

Mide el arnes unificado (`knowledge_v3.eval.gate6_harness.measure_gate6_program`)
sobre la politica corregida por B2 (guarda de homografo en
`_reported_speech_cue` + exigencia de 'que' completivo tras SCOPE_VERBS),
y la compara contra los artefactos historicos de B0 y B1 para publicar la
evolucion completa del programa: B0 -> B1 -> B2.

Uso (desde la raiz del repo):

    PYTHONPATH=data-engine/app python3 scripts/gate6/measure_final.py \\
        --baseline artifacts/gate6-program/b0-baseline.json \\
        --b1 artifacts/gate6-program/b1-operators.json \\
        --out-dir artifacts/gate6-program --out-name b2-final
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
    """Compara fila a fila dos mediciones del mismo corpus."""
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


def _family_accuracy_table(metrics_by_family: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for family, vals in sorted(metrics_by_family.items()):
        acc = vals["accuracy"]
        rows.append({
            "family": family,
            "cases": vals["cases"],
            "accuracy": acc,
        })
    return rows


def build_b2_report(
    b0_baseline: dict[str, Any], b1_artifact: dict[str, Any]
) -> dict[str, Any]:
    """Medicion completa B2: actual vs B0 y vs B1."""
    current = measure_gate6_program()

    # Comparacion vs B0 (en toda la superficie comun: dev + gen original)
    dev_diff_vs_b0 = _diff_corpus(
        "dev",
        b0_baseline["corpora"]["dev"],
        current["corpora"]["dev"],
    )
    # Solo se comparan filas comunes (B2 anade casos nuevos a gen)
    gen_diff_vs_b0 = _diff_corpus(
        "generalization",
        b0_baseline["corpora"]["generalization"],
        current["corpora"]["generalization"],
    )
    violations_diff_vs_b0 = _diff_violations(
        b0_baseline["fail_closed_invariant"],
        current["fail_closed_invariant"],
    )

    # Comparacion vs B1
    b1_current = b1_artifact["current"]
    dev_diff_vs_b1 = _diff_corpus(
        "dev",
        b1_current["corpora"]["dev"],
        current["corpora"]["dev"],
    )
    gen_diff_vs_b1 = _diff_corpus(
        "generalization",
        b1_current["corpora"]["generalization"],
        current["corpora"]["generalization"],
    )
    violations_diff_vs_b1 = _diff_violations(
        b1_current["fail_closed_invariant"],
        current["fail_closed_invariant"],
    )

    # Historia de los tres bloques (dev)
    dev_history = [
        {
            "block": "B0",
            "policy_accuracy": b0_baseline["corpora"]["dev"]["metrics_global"][
                "policy_accuracy"
            ],
        },
        {
            "block": "B1",
            "policy_accuracy": b1_current["corpora"]["dev"]["metrics_global"][
                "policy_accuracy"
            ],
        },
        {
            "block": "B2",
            "policy_accuracy": current["corpora"]["dev"]["metrics_global"][
                "policy_accuracy"
            ],
        },
    ]

    # Historia generalizacion (solo overall_accuracy, excluye nuevos casos de B2)
    gen_history = [
        {
            "block": "B0",
            "overall_accuracy": b0_baseline["corpora"]["generalization"][
                "metrics_global"
            ]["overall_accuracy"],
            "cases": b0_baseline["corpora"]["generalization"]["cases"],
        },
        {
            "block": "B1",
            "overall_accuracy": b1_current["corpora"]["generalization"][
                "metrics_global"
            ]["overall_accuracy"],
            "cases": b1_current["corpora"]["generalization"]["cases"],
        },
        {
            "block": "B2",
            "overall_accuracy": current["corpora"]["generalization"]["metrics_global"][
                "overall_accuracy"
            ],
            "cases": current["corpora"]["generalization"]["cases"],
        },
    ]

    violations_history = [
        {
            "block": "B0",
            "count": len(b0_baseline["fail_closed_invariant"]["violations"]),
        },
        {
            "block": "B1",
            "count": len(b1_current["fail_closed_invariant"]["violations"]),
        },
        {
            "block": "B2",
            "count": len(current["fail_closed_invariant"]["violations"]),
        },
    ]

    # Diagnostico de violaciones restantes, por familia
    remaining_violations_by_family: dict[str, list[str]] = {}
    for v in current["fail_closed_invariant"]["violations"]:
        fam = v["family"]
        remaining_violations_by_family.setdefault(fam, []).append(v["case_id"])

    # Generalizacion por familia en B2 (completa)
    gen_family_table = _family_accuracy_table(
        current["corpora"]["generalization"]["metrics_by_family"]
    )

    return {
        "gate": "6",
        "block": "B2",
        "purpose": (
            "Bloque B2-FINAL: cierra el backlog diagnosticado en B1. "
            "Correccion 1 (Bug homografo): guarda de determinante en "
            "_reported_speech_cue para formas de REPORT_VERBS que son "
            "tambien sustantivos ('cuenta', 'relato') -- impide que 'la "
            "cuenta que presento' se lea como reporte de tercero. "
            "Correccion 2 (Bug scope sin 'que'): se exige un 'que' completivo "
            "inmediato tras los verbos de SCOPE_VERBS para disparar "
            "SCOPE_AMBIGUOUS -- 'no reconocio el terreno' es ahora "
            "NEGATED_FACT, no UNKNOWN. Ambas correcciones generalizan a todos "
            "los verbos de su respectiva lista (no solo a los de B1). Se "
            "anaden 6 nuevos casos al corpus de generalizacion composicional "
            "(familias REPORT_FALSE_FRIEND y SCOPE_VERB_DIRECT_OBJ, dataset "
            "version 1.2.0). Criterio NVIDIA (79,17 %): ver seccion de notas."
        ),
        "current": current,
        "dev_history": dev_history,
        "generalization_history": gen_history,
        "violations_history": violations_history,
        "remaining_violations_by_family": remaining_violations_by_family,
        "generalization_by_family_b2": gen_family_table,
        "comparison_vs_b0": {
            "dev": dev_diff_vs_b0,
            "generalization": gen_diff_vs_b0,
            "fail_closed_violations": violations_diff_vs_b0,
        },
        "comparison_vs_b1": {
            "dev": dev_diff_vs_b1,
            "generalization": gen_diff_vs_b1,
            "fail_closed_violations": violations_diff_vs_b1,
        },
        "nvidia_criterion": {
            "original": (
                "El criterio historico F6-3 de la validacion V3 era 'acuerdo "
                "con juez semantico NVIDIA >= 79,17 %'. Ese numero mide el "
                "ACUERDO DE ACCION entre los carriles det+combined+nvidia sobre "
                "el corpus dev: requiere un extractor completo, un reconciliador "
                "y credenciales NVIDIA activas. No es reproducible de forma "
                "determinista y sin red, como exige el programa de la puerta 6. "
                "El arnes de este programa mide la POLITICA SOLA contra el "
                "corpus dev (79/100 en B0, 80/100 en B1 y B2), que SI es "
                "determinista y reproducible sin proveedores externos."
            ),
            "propuesta_del_implementador": "POSTURA_A",
            "razonamiento": (
                "Se propone ABANDONAR FORMALMENTE el criterio NVIDIA (79,17 %) "
                "y sustituirlo por tres metricas deterministas que el arnes ya "
                "mide y reproduce: (1) policy_accuracy sobre el corpus dev "
                "congelado (100 frases, split dev-synthetic/opus-2026-07-30), "
                "(2) overall_accuracy sobre el corpus de generalizacion "
                "composicional (48 frases tras B2), y (3) el invariante "
                "fail-closed (0 casos NON_FACTIVE que se lean como hecho del "
                "mundo). Razon: el criterio NVIDIA mezcla la politica de "
                "factividad con la precision del extractor completo y con el "
                "comportamiento de un modelo externo que puede cambiar sin "
                "aviso. Estas tres metricas son ortogonales, reproducibles y "
                "no dependen de ningun proveedor. Si en el futuro se integra "
                "un ciclo de validacion con el juez NVIDIA, debe tratarse como "
                "un cuarto eje de medicion anadido, no como sustituto de los "
                "tres deterministicos. NOTA: esta propuesta la ratifica el "
                "operador humano con el dictamen del revisor -- el implementador "
                "solo propone."
            ),
        },
        "notes": [
            (
                "El corpus de generalizacion composicional crece en B2 de 42 "
                "(B0/B1) a 48 casos: +3 REPORT_FALSE_FRIEND (ejercen Bug 1) y "
                "+3 SCOPE_VERB_DIRECT_OBJ (ejercen Bug 2). Las familias nuevas "
                "no existian en B0/B1, por lo que la comparacion de overall_accuracy "
                "no es directamente proporcional: B1 acertaba 32/42 = 0.762; B2 "
                "acierta 38/48 = 0.792 sobre el corpus AMPLIADO."
            ),
            (
                "NEGATED_RUMOR_HARD sigue en 0,0 % (6/6 fail): la construccion "
                "'no es cierto el rumor de que' no es substring literal de ninguna "
                "FALSITY_PHRASE porque 'el rumor de' se interpone. Es un limite "
                "arquitectonico documentado desde B0. No se toca: corregirlo "
                "requeriria una busqueda con hueco ('no es cierto ... que') que "
                "aumentaria el riesgo de falsos positivos en otros contextos."
            ),
            (
                "LEXICAL_NEGATION_EDGE sigue en 0,0 % (2/2 fail): 'nunca salio "
                "del' entra en negated_cessation (CESSATION_PHRASES incluye "
                "'salio del') y el gold modela la frase como NEGATED_FACT directo. "
                "Corregirlo sin arriesgar las cesaciones genuinas requiere "
                "distinguir 'salida fisica' de 'pertenencia', que el vocabulario "
                "cerrado actual no hace. Documentado como limite arquitectonico "
                "desde B1 (docs/v3/44)."
            ),
            (
                "gen6:neg_of_factive:04 ('Nadie en la Camara confirmo que...') "
                "sigue en ASSERTED_FACT: 'nadie' no esta en NEGATION_CUES, "
                "por lo que la logica de scope_negation no detecta la negacion "
                "universal. Aniadir 'nadie' a NEGATION_CUES afectaria a muchos "
                "casos no relacionados. Queda diagnosticado como techo restante."
            ),
        ],
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Puerta 6 — B2-FINAL: correcciones de backlog y cierre de medicion")
    add("")
    add(report["purpose"])
    add("")

    add("## 1. Historia B0 -> B1 -> B2")
    add("")
    add("### 1.1 Corpus dev (100 frases congeladas)")
    add("")
    add("| bloque | policy_accuracy |")
    add("| --- | ---: |")
    for row in report["dev_history"]:
        add(f"| {row['block']} | {row['policy_accuracy']:.3f} |")
    add("")

    add("### 1.2 Corpus de generalizacion composicional")
    add("")
    add("| bloque | casos | overall_accuracy |")
    add("| --- | ---: | ---: |")
    for row in report["generalization_history"]:
        add(f"| {row['block']} | {row['cases']} | {row['overall_accuracy']:.3f} |")
    add("")

    add("### 1.3 Invariante fail-closed")
    add("")
    add("| bloque | violaciones |")
    add("| --- | ---: |")
    for row in report["violations_history"]:
        add(f"| {row['block']} | {row['count']} |")
    add("")

    add("## 2. Generalizacion composicional B2 por familia")
    add("")
    add("| familia | casos | exactitud |")
    add("| --- | ---: | ---: |")
    for row in report["generalization_by_family_b2"]:
        acc = row["accuracy"]
        acc_str = "n/d" if acc is None else f"{acc:.3f}"
        add(f"| {row['family']} | {row['cases']} | {acc_str} |")
    add("")

    add("## 3. Violaciones fail-closed restantes por familia")
    add("")
    rbf = report["remaining_violations_by_family"]
    if rbf:
        add("| familia | violaciones |")
        add("| --- | ---: |")
        for fam, ids in sorted(rbf.items()):
            add(f"| {fam} | {len(ids)} |")
    else:
        add("Sin violaciones: invariante CONFORME.")
    add("")

    add("## 4. Comparacion B2 vs B1 (cambios relativos)")
    add("")
    cmp = report["comparison_vs_b1"]
    dev = cmp["dev"]
    gen = cmp["generalization"]
    viol = cmp["fail_closed_violations"]
    add(f"- Dev: mejoras {len(dev['improvements'])}, regresiones {len(dev['regressions'])}")
    add(f"- Gen (filas comunes): mejoras {len(gen['improvements'])}, regresiones {len(gen['regressions'])}")
    add(f"- Violaciones: antes {viol['count_before']}, despues {viol['count_after']}, "
        f"resueltas {len(viol['resolved'])}, nuevas {len(viol['new'])}")
    add("")
    if dev["improvements"]:
        add("### Mejoras en dev (B2 vs B1)")
        for row in dev["improvements"]:
            add(f"- `{row['case_id']}` ({row['family']}): {row['before']} -> {row['after']}")
        add("")
    if dev["regressions"]:
        add("### Regresiones en dev (B2 vs B1)")
        for row in dev["regressions"]:
            add(f"- `{row['case_id']}` ({row['family']}): {row['before']} -> {row['after']}")
        add("")

    add("## 5. Criterio NVIDIA")
    add("")
    nv = report["nvidia_criterion"]
    add(f"**Postura propuesta: {nv['propuesta_del_implementador']}** (decision final: operador humano con dictamen del revisor)")
    add("")
    add(nv["razonamiento"])
    add("")

    add("## 6. Notas")
    add("")
    for note in report["notes"]:
        add(f"- {note}")
    add("")

    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Puerta 6 (B2-FINAL): medicion completa B0->B1->B2."
    )
    parser.add_argument("--baseline", required=True, help="ruta a b0-baseline.json")
    parser.add_argument("--b1", required=True, help="ruta a b1-operators.json")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="b2-final")
    args = parser.parse_args(argv)

    b0 = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    b1 = json.loads(Path(args.b1).read_text(encoding="utf-8"))
    report = build_b2_report(b0, b1)
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

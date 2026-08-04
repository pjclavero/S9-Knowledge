# -*- coding: utf-8 -*-
"""Arnes unificado de la puerta 6 (B0): mide dev y generalizacion composicional.

Dos corpus, la MISMA capa de medicion (la politica de factualidad,
`extraction.cues.analyze_raw_text`), publicados uno al lado del otro y NUNCA
mezclados en un solo numero -- misma disciplina que
`eval/harness.py` (puerta 4, programa de cobertura):

* **Desarrollo** (`benchmarks/datasets/factivity/cases.json`, 100 frases,
  `dev-synthetic/opus-2026-07-30`): reproduce la medida F6-7 de la validacion
  V3 ("la politica, medida de verdad, acierta 79/100"). NO es el 79,17 % de
  `gate6-findings.md` (F6-3): esa cifra es acuerdo de ACCION entre los
  carriles `det`+`combined`+`nvidia` (necesita un extractor completo, un
  reconciliador y credenciales de NVIDIA -- no reproducible sin llamar a un
  proveedor externo). La cifra que este arnes SI reproduce, determinista y
  sin proveedores, es la de la politica sola contra el corpus: 79/100,
  documentada mas abajo en `measure_dev`.
* **Generalizacion composicional** (corpus nuevo de B0,
  `eval/gate6_generalization_corpus.py`, 42 frases): mide la MISMA politica
  sobre composiciones de operadores (condicional dentro de rumor, reporte
  anidado, negacion de un verbo factivo, factivo dentro de condicional, rumor
  negado, reporte de una negacion) con vocabulario y entidades NUEVOS. Es un
  eje distinto del que ya midio `factivity_generalization_probe.py`
  (vocabulario nuevo, un operador por frase, 0,231): aqui el vocabulario de
  cada operador es en su mayoria CONOCIDO por `cues.py` -- lo que se prueba es
  si la precedencia PLANA de `classify_factivity` compone bien cuando dos
  operadores aparecen en la misma frase.

Determinista: ninguna corrida usa red, fecha del sistema ni aleatoriedad. Dos
llamadas seguidas producen el mismo JSON byte a byte
(`tests/test_gate6_harness.py::test_el_arnes_es_determinista_byte_a_byte`).
"""
from __future__ import annotations

from typing import Any

from ..extraction.cues import analyze_raw_text
from .gate6_dev_corpus import FACT_CLASSES, expected_world_fact, load_dev_cases
from .gate6_generalization_corpus import (
    CompositionalItem,
    HARD_FAMILIES,
    load_generalization,
)


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


# --------------------------------------------------------------------------
# 1. Desarrollo: la politica sola, contra las 100 frases congeladas
# --------------------------------------------------------------------------
def _score_dev_case(case: dict[str, Any]) -> dict[str, Any]:
    verdict = analyze_raw_text(case["text"])
    predicted_class = verdict.factivity.factivity_class.value
    read_as_fact = predicted_class in FACT_CLASSES
    want_world_fact = expected_world_fact(case)

    if not want_world_fact:
        # El gold dice ABSTAIN/DIAGNOSTIC: acierto = NO leerlo como hecho.
        correct = not read_as_fact
    elif case["negative"]:
        # El gold dice WRITE_NEGATIVE: acierto = leerlo exactamente como
        # NEGATED_FACT (no basta con "algun hecho").
        correct = predicted_class == "NEGATED_FACT"
    else:
        # El gold dice WRITE_POSITIVE: acierto = leerlo exactamente como
        # ASSERTED_FACT.
        correct = predicted_class == "ASSERTED_FACT"

    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "expected": case["expected"],
        "world_fact_gold": case["world_fact"],
        "predicted_class": predicted_class,
        "read_as_world_fact": read_as_fact,
        "correct": correct,
    }


def measure_dev() -> dict[str, Any]:
    """Politica de factualidad sola, sobre las 100 frases del corpus dev.

    Verifica integridad primero: si alguien edito `cases.json` sin declarar
    el cambio en `manifest.json`, esto rompe ANTES de producir un numero.
    """
    corpus = load_dev_cases(verify=True)
    rows = [_score_dev_case(c) for c in corpus["cases"]]

    overall_accuracy = _ratio(sum(1 for r in rows if r["correct"]), len(rows))

    by_family: dict[str, Any] = {}
    for family in sorted({r["family"] for r in rows}):
        subset = [r for r in rows if r["family"] == family]
        by_family[family] = {
            "cases": len(subset),
            "accuracy": _ratio(sum(1 for r in subset if r["correct"]), len(subset)),
        }

    return {
        "split": corpus["split"],
        "provenance": corpus["provenance"],
        "layer": "factivity_policy",
        "cases": len(rows),
        "metrics_global": {"policy_accuracy": overall_accuracy},
        "metrics_by_family": by_family,
        "rows": rows,
    }


# --------------------------------------------------------------------------
# 2. Generalizacion composicional
# --------------------------------------------------------------------------
def _score_gen_item(item: CompositionalItem) -> dict[str, Any]:
    verdict = analyze_raw_text(item.text)
    predicted_class = verdict.factivity.factivity_class.value
    read_as_fact = predicted_class in FACT_CLASSES

    if item.expected_class == "NON_FACTIVE":
        correct = not read_as_fact
    else:
        correct = predicted_class == item.expected_class

    return {
        "case_id": item.case_id,
        "family": item.family,
        "hard": item.hard,
        "expected_class": item.expected_class,
        "predicted_class": predicted_class,
        "read_as_world_fact": read_as_fact,
        "correct": correct,
    }


def measure_generalization() -> dict[str, Any]:
    """La misma politica, sobre el corpus de generalizacion composicional.

    Verifica integridad primero, igual de exigente con un corpus nuevo que
    con uno viejo.
    """
    items = load_generalization(verify=True)
    rows = [_score_gen_item(item) for item in items]

    overall_accuracy = _ratio(sum(1 for r in rows if r["correct"]), len(rows))

    by_family: dict[str, Any] = {}
    for family in sorted({r["family"] for r in rows}):
        subset = [r for r in rows if r["family"] == family]
        by_family[family] = {
            "cases": len(subset),
            "accuracy": _ratio(sum(1 for r in subset if r["correct"]), len(subset)),
        }

    hard_rows = [r for r in rows if r["hard"]]
    hard_accuracy = _ratio(sum(1 for r in hard_rows if r["correct"]), len(hard_rows))

    non_hard_rows = [r for r in rows if not r["hard"]]
    non_hard_accuracy = _ratio(
        sum(1 for r in non_hard_rows if r["correct"]), len(non_hard_rows)
    )

    return {
        "split": "gate6-generalization-compositional",
        "layer": "factivity_policy",
        "cases": len(rows),
        "metrics_global": {
            "overall_accuracy": overall_accuracy,
            "hard_family_accuracy": hard_accuracy,
            "non_hard_accuracy": non_hard_accuracy,
        },
        "metrics_by_family": by_family,
        "hard_families": sorted(HARD_FAMILIES),
        "rows": rows,
    }


# --------------------------------------------------------------------------
# 3. Invariantes fail-closed
# --------------------------------------------------------------------------
def _check_fail_closed_invariants(
    dev: dict[str, Any], generalization: dict[str, Any]
) -> list[dict[str, Any]]:
    """Nada no-escribible acaba escribible; en caso de duda, no se materializa.

    No comprueba "acierto" (eso ya lo hacen `measure_dev`/`measure_generalization`):
    comprueba una propiedad de SEGURIDAD mas estrecha y no negociable -- que
    ningun caso cuyo gold dice ABSTAIN/DIAGNOSTIC/NON_FACTIVE termine leido
    como `ASSERTED_FACT` o `NEGATED_FACT`. Un caso puede fallar en exactitud
    (leerse con la clase no-factiva equivocada) sin violar el invariante; violar
    el invariante es materializar un hecho donde el gold exige abstenerse.
    """
    violations: list[dict[str, Any]] = []
    for row in dev["rows"]:
        if row["expected"] not in ("WRITE_POSITIVE", "WRITE_NEGATIVE") and row[
            "read_as_world_fact"
        ]:
            violations.append(
                {
                    "corpus": "dev",
                    "case_id": row["case_id"],
                    "family": row["family"],
                    "predicted_class": row["predicted_class"],
                }
            )
    for row in generalization["rows"]:
        if row["expected_class"] == "NON_FACTIVE" and row["read_as_world_fact"]:
            violations.append(
                {
                    "corpus": "generalization",
                    "case_id": row["case_id"],
                    "family": row["family"],
                    "predicted_class": row["predicted_class"],
                }
            )
    return violations


# --------------------------------------------------------------------------
# 4. Arnes unificado
# --------------------------------------------------------------------------
def measure_gate6_program() -> dict[str, Any]:
    dev = measure_dev()
    generalization = measure_generalization()
    violations = _check_fail_closed_invariants(dev, generalization)

    return {
        "gate": "6",
        "block": "B0",
        "purpose": (
            "Arnes de medicion de la factividad composicional: publica la exactitud "
            "de la politica de factualidad sobre el corpus dev congelado y sobre un "
            "corpus NUEVO de composicion de operadores, lado a lado, sin mezclarlas "
            "en un solo numero. No se toca `extraction/factivity.py` ni `cues.py` en "
            "este bloque: B0 mide, no corrige."
        ),
        "corpora": {"dev": dev, "generalization": generalization},
        "fail_closed_invariant": {
            "description": (
                "ningun caso cuyo gold exige abstenerse (dev: ABSTAIN/DIAGNOSTIC; "
                "generalizacion: NON_FACTIVE) debe leerse como ASSERTED_FACT o "
                "NEGATED_FACT"
            ),
            "violations": violations,
            "status": "CONFORME" if not violations else "NO CONFORME",
        },
        "notes": [
            "El numero de desarrollo de este arnes (policy_accuracy sobre las 100 "
            "frases) reproduce F6-7 de `gate6-findings.md` ('79/100 correctas'), "
            "NO el 79,17 % de F6-3 (ese es acuerdo de ACCION entre carriles "
            "det+combined+nvidia, que exige un extractor completo y un proveedor "
            "NVIDIA en vivo -- no reproducible de forma determinista y sin red "
            "por este arnes). Ver docstring del modulo.",
            "El corpus de generalizacion de este bloque mide un eje DISTINTO del "
            "de `factivity_generalization_probe.py` (0,231): aquel prueba "
            "vocabulario nuevo con UN operador por frase; este prueba COMPOSICION "
            "de operadores en su mayoria conocidos. Una exactitud baja aqui no es "
            "el mismo hallazgo que el 0,231 -- es un hallazgo relacionado, sobre "
            "el fallo de la precedencia plana al combinar marcos, no sobre el "
            "vocabulario ausente.",
            "La familia `NEGATED_RUMOR_HARD` se declara HARD por adelantado: se "
            "espera una exactitud baja porque 'no es cierto el rumor de que' no "
            "es substring literal de ninguna FALSITY_PHRASE (la interposicion de "
            "'el rumor de' rompe el match). El gold no se ajusto para que el "
            "sistema acertase.",
            "Regla de aceptacion heredada de la fase 3 de la validacion V3: "
            "ninguna mejora futura de `cues.py`/`factivity.py` se acepta si solo "
            "sube el numero de desarrollo. La sonda de generalizacion (esta, y la "
            "de vocabulario) es el criterio de aceptacion, y debe ejecutarse ANTES "
            "de tocar la politica, no despues.",
        ],
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    inv = report["fail_closed_invariant"]

    add("# Puerta 6 — B0: arnes de medicion (dev vs. generalizacion composicional)")
    add("")
    add(report["purpose"])
    add("")
    add("## 1. Cifras globales")
    add("")
    add("| corpus | casos | metrica | valor |")
    add("| --- | ---: | --- | ---: |")
    for key, val in dev["metrics_global"].items():
        add(f"| dev (`{dev['split']}`) | {dev['cases']} | `{key}` | {val:.3f} |")
    for key, val in gen["metrics_global"].items():
        v = "n/d" if val is None else f"{val:.3f}"
        add(f"| generalizacion | {gen['cases']} | `{key}` | {v} |")
    add("")
    add("## 2. Desarrollo por familia")
    add("")
    add("| familia | casos | exactitud |")
    add("| --- | ---: | ---: |")
    for family, vals in dev["metrics_by_family"].items():
        acc = vals["accuracy"]
        add(f"| {family} | {vals['cases']} | {'n/d' if acc is None else f'{acc:.3f}'} |")
    add("")
    add("## 3. Generalizacion composicional por familia")
    add("")
    add("| familia | casos | exactitud | dura |")
    add("| --- | ---: | ---: | :---: |")
    hard = set(gen["hard_families"])
    for family, vals in gen["metrics_by_family"].items():
        acc = vals["accuracy"]
        marca = "sí" if family in hard else ""
        add(f"| {family} | {vals['cases']} | {'n/d' if acc is None else f'{acc:.3f}'} | {marca} |")
    add("")
    add("## 4. Invariante fail-closed")
    add("")
    add(f"**Estado: {inv['status']}**")
    add("")
    add(inv["description"])
    add("")
    if inv["violations"]:
        add("| corpus | caso | familia | clase leída |")
        add("| --- | --- | --- | --- |")
        for v in inv["violations"]:
            add(f"| {v['corpus']} | {v['case_id']} | {v['family']} | {v['predicted_class']} |")
    else:
        add("Sin violaciones: 0 casos no-escribibles se leyeron como hecho del mundo.")
    add("")
    add("## 5. Notas")
    add("")
    for note in report["notes"]:
        add(f"- {note}")
    add("")
    return "\n".join(lines)


__all__ = [
    "measure_dev",
    "measure_gate6_program",
    "measure_generalization",
    "to_markdown",
]

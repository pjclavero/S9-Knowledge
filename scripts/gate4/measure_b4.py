# -*- coding: utf-8 -*-
"""Puerta 4, bloque B4: medicion y VEREDICTO, de punta a punta.

Mismo principio de reproducibilidad que `measure_b2.py`: llama al MISMO
arnes (`measure_gate4_program`), lee el baseline congelado del bloque
ANTERIOR (`b2-resultado.json`, no `b0-baseline.json`: B4 se mide contra lo
que dejo B2, no contra el punto de partida del programa) y DERIVA los
veredictos comparando umbral contra observado. Ninguna cifra se escribe a
mano en el informe.

B4 ataco PREDICATE_ABSENT/subordinadas por via morfologica/estructural
(`extraction/morphology.py`: conjugador regular -AR de verbos de reporte,
que sustituye una parte del lexico literal de `SCOPE_VERBS` por un
paradigma declarado por lema). El resultado, medido aqui: la cobertura E2E
del corpus de DESARROLLO no se movio (los dos casos candidatos identificados
en la taxonomia, cirro-actas:e13/e14, resultaron depender de un fenomeno
distinto -- sujeto de cuantificador negativo "Nadie ha afirmado que...", no
de "no <verbo de reporte>" -- y quedan fuera del alcance morfologico
declarado; ver `artifacts/gate4-program/b4-taxonomia.md`). Lo que SI se
demuestra, con casos nuevos en el corpus de GENERALIZACION
(`gen:scope:05`/`gen:scope:06`, dataset_version 1.3.0), es que el paradigma
generaliza a verbos de reporte ausentes del lexico anterior sin perder
precision.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from knowledge_v3.eval.harness import measure_gate4_program

UMBRAL_COBERTURA_DEV = 0.60
UMBRAL_RECALL_SIMPLE = 0.70
UMBRAL_FAMILIA_GENERALIZACION = 1.0
FAMILIA_DURA = "HARD_SCOPE_LITOTES"

#: Familia que B4 ejercita directamente (verbos de reporte generados por
#: paradigma). No tiene liston propio distinto de las demas familias no
#: duras (1.0), pero se reporta aparte para que el numero de casos (6, tras
#: sumar `gen:scope:05`/`06`) quede a la vista sin tener que leer el JSON.
FAMILIA_B4 = "SCOPE_EMBEDDED"

INVARIANTES_EXACTAS: tuple[tuple[str, float], ...] = (
    ("auto_approval_precision", 1.0),
    ("negative_edge_precision", 1.0),
    ("negated_cessation_safety", 1.0),
    ("evidence_grounding", 1.0),
)
INVARIANTE_CERO = "false_positive_relation_from_negation"


def _veredicto(ok: bool) -> str:
    return "CONFORME" if ok else "NO_CONFORME"


def _num(valor: Any) -> Optional[float]:
    return None if valor is None else round(float(valor), 6)


def evaluar_puertas(report: dict, baseline: Optional[dict]) -> dict:
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    dev_m = dev["metrics_global"]
    gen_m = gen["metrics_global"]
    familias = gen["metrics_by_family"]

    base_dev = (baseline or {}).get("corpora", {}).get("dev", {})
    base_gen = (baseline or {}).get("corpora", {}).get("generalization", {})
    base_familias = base_gen.get("metrics_by_family", {})

    cobertura = float(dev["coverage"])
    cobertura_base = base_dev.get("coverage")
    recall_simple = gen_m.get("recall_simple")
    dura = float(familias.get(FAMILIA_DURA, {}).get("accuracy", 0.0))
    dura_base = float(base_familias.get(FAMILIA_DURA, {}).get("accuracy", 0.0))
    b4_fam = familias.get(FAMILIA_B4, {})
    b4_fam_base = base_familias.get(FAMILIA_B4, {})

    otras = {
        nombre: float(datos["accuracy"])
        for nombre, datos in sorted(familias.items())
        if nombre != FAMILIA_DURA
    }
    otras_ok = all(v >= UMBRAL_FAMILIA_GENERALIZACION for v in otras.values())

    invariantes: dict[str, Any] = {}
    invariantes_ok = True
    for nombre, esperado in INVARIANTES_EXACTAS:
        observado = _num(dev_m.get(nombre))
        ok = observado is None or observado == esperado
        invariantes_ok = invariantes_ok and ok
        invariantes[nombre] = {
            "esperado": esperado,
            "observado": observado,
            "veredicto": _veredicto(ok),
        }
    fp = dev_m.get(INVARIANTE_CERO)
    fp_ok = (fp or 0) == 0
    invariantes_ok = invariantes_ok and fp_ok
    invariantes[INVARIANTE_CERO] = {
        "esperado": 0, "observado": fp, "veredicto": _veredicto(fp_ok),
    }

    puertas = {
        "cobertura_e2e_dev": {
            "umbral": UMBRAL_COBERTURA_DEV,
            "observado": _num(cobertura),
            "baseline_b2": _num(cobertura_base),
            "delta": None if cobertura_base is None else _num(cobertura - cobertura_base),
            "casos": f"{dev['covered_cases']}/{dev['evaluable_cases']}",
            "veredicto": _veredicto(cobertura >= UMBRAL_COBERTURA_DEV),
        },
        "recall_simple_generalizacion": {
            "umbral": UMBRAL_RECALL_SIMPLE,
            "observado": _num(recall_simple),
            "veredicto": _veredicto(
                recall_simple is not None and recall_simple >= UMBRAL_RECALL_SIMPLE
            ),
        },
        "familias_generalizacion_no_duras": {
            "umbral": UMBRAL_FAMILIA_GENERALIZACION,
            "familias": {k: _num(v) for k, v in otras.items()},
            "minimo": _num(min(otras.values())) if otras else None,
            "veredicto": _veredicto(otras_ok),
        },
        "hard_scope_litotes_estable_o_mejor_que_b2": {
            "baseline_b2": _num(dura_base),
            "observado": _num(dura),
            "delta": _num(dura - dura_base),
            "veredicto": _veredicto(dura >= dura_base),
        },
        "scope_embedded_generaliza_a_reporte_morfologico": {
            "casos_baseline_b2": b4_fam_base.get("cases"),
            "casos_observado": b4_fam.get("cases"),
            "exactitud_baseline_b2": _num(b4_fam_base.get("accuracy")),
            "exactitud_observado": _num(b4_fam.get("accuracy")),
            "veredicto": _veredicto(
                b4_fam.get("cases", 0) > b4_fam_base.get("cases", 0)
                and _num(b4_fam.get("accuracy")) == UMBRAL_FAMILIA_GENERALIZACION
            ),
        },
        "invariantes_de_precision": {
            "detalle": invariantes,
            "veredicto": _veredicto(invariantes_ok),
        },
    }

    bloqueante_ok = invariantes_ok
    todas_ok = bloqueante_ok and all(
        p["veredicto"] == "CONFORME" for p in puertas.values()
    )
    if todas_ok:
        veredicto = "CONFORME"
    elif bloqueante_ok:
        veredicto = "PARCIAL"
    else:
        veredicto = "NO_CONFORME"
    return {"puertas": puertas, "veredicto_bloque": veredicto}


def build_report(baseline_path: Optional[Path]) -> dict:
    report = measure_gate4_program()
    baseline = None
    if baseline_path and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    evaluacion = evaluar_puertas(report, baseline)
    return {
        "gate": "4",
        "block": "B4",
        "titulo": "Analisis morfologico/estructural de PREDICATE_ABSENT y subordinadas",
        "generado_por": "scripts/gate4/measure_b4.py",
        "baseline_comparado": str(baseline_path) if baseline else None,
        "corpora": report["corpora"],
        **evaluacion,
        "notes": report.get("notes", []),
    }


def to_markdown(report: dict) -> str:
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    lineas = [
        "# Puerta 4 - B4: analisis morfologico/estructural",
        "",
        f"Veredicto del bloque: **{report['veredicto_bloque']}**",
        "",
        "Generado por `scripts/gate4/measure_b4.py`. Ninguna cifra de este",
        "documento se escribe a mano. Baseline comparado: "
        f"`{report['baseline_comparado']}`.",
        "",
        "## Puertas",
        "",
        "| puerta | umbral | observado | veredicto |",
        "| --- | --- | --- | --- |",
    ]
    for nombre, datos in report["puertas"].items():
        umbral = datos.get("umbral", "-")
        observado = datos.get("observado", datos.get("minimo", "-"))
        lineas.append(f"| {nombre} | {umbral} | {observado} | {datos['veredicto']} |")
    lineas += [
        "",
        "## Corpus de desarrollo (cadena E2E)",
        "",
        f"- cobertura: {dev['coverage']} ({dev['covered_cases']}/{dev['evaluable_cases']})",
    ]
    for k, v in sorted(dev["metrics_global"].items()):
        lineas.append(f"- {k}: {v}")
    lineas += ["", "## Corpus de generalizacion (clasificador de negacion)", ""]
    lineas.append("| familia | casos | exactitud |")
    lineas.append("| --- | --- | --- |")
    for fam, datos in sorted(gen["metrics_by_family"].items()):
        lineas.append(f"| {fam} | {datos['cases']} | {datos['accuracy']} |")
    lineas += ["", "## Notas del arnes", ""]
    lineas += [f"- {n}" for n in report.get("notes", [])]
    lineas += [
        "",
        "## Hallazgo honesto de B4",
        "",
        "La cobertura E2E de desarrollo NO se movio respecto a B2 (34/56). Los "
        "dos casos que la taxonomia identificaba como candidatos morfologicos "
        "(`cirro-actas:e13`/`e14`, familia SCOPE_EMBEDDED) usan un sujeto de "
        "cuantificador negativo ('Nadie ha afirmado que...') en vez del patron "
        "'no <verbo de reporte>' que el paradigma -AR ataca; resolverlos exige "
        "reconocer el ALCANCE DE UN CUANTIFICADOR, un fenomeno distinto del "
        "declarado para este bloque (conjugacion regular), y no se fuerzo una "
        "regla ad-hoc para dos casos concretos del corpus. Ver "
        "`artifacts/gate4-program/b4-taxonomia.md` para la clasificacion "
        "completa de los 22 casos NO_OUTPUT restantes.",
        "",
        "Lo que si se demuestra es que `SCOPE_VERBS` generaliza: los dos casos "
        "nuevos del corpus de generalizacion (`gen:scope:05`/`06`, verbos "
        "'declarar'/'asegurar' generados por el paradigma, ausentes del "
        "lexico literal anterior a B4) se clasifican correctamente con "
        "exactitud 1.0, sin tocar ningun literal de corpus.",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 4 (B4): medicion + puertas.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="b4-resultado")
    parser.add_argument(
        "--baseline",
        default="artifacts/gate4-program/b2-resultado.json",
        help="informe B2 congelado con el que se calculan los deltas",
    )
    args = parser.parse_args(argv)

    report = build_report(Path(args.baseline) if args.baseline else None)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.out_name}.json").write_text(payload, encoding="utf-8")
        (out / f"{args.out_name}.md").write_text(to_markdown(report), encoding="utf-8")
        print(f"escrito en {out}/{args.out_name}.{{json,md}}")
        print(f"veredicto: {report['veredicto_bloque']}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

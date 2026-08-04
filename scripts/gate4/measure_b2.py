# -*- coding: utf-8 -*-
"""Puerta 4, bloque B2: medicion y VEREDICTO de puertas, de punta a punta.

Existe por un defecto P1 del dictamen: `b2-resultado.json` se habia ensamblado a
mano copiando cifras del arnes y escribiendo los veredictos a ojo. Un artefacto
asi no es reproducible ni auditable -- y en un programa cuyo objetivo declarado
es no premiar el sobreajuste, el informe es justo el sitio donde no se puede
confiar en la buena fe del autor.

Este script no toca ninguna cifra: llama al MISMO arnes (`measure_gate4_program`)
que el runner de B0, lee el baseline congelado de B0 del disco, y DERIVA los
veredictos de cada puerta comparando umbral contra observado. Cambiar una cifra
del informe exige cambiar el extractor, no el informe.

Uso (desde la raiz del repo):

    PYTHONPATH=data-engine/app python3 scripts/gate4/measure_b2.py \
        --out-dir artifacts/gate4-program --out-name b2-resultado
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from knowledge_v3.eval.harness import measure_gate4_program

#: Umbrales del programa (documento de encargo del bloque B2).
UMBRAL_COBERTURA_DEV = 0.60
UMBRAL_RECALL_SIMPLE = 0.70
UMBRAL_FAMILIA_GENERALIZACION = 1.0

#: La familia de construcciones duras se mide APARTE: su liston no es 1.0 sino
#: "mejorar sobre el baseline de B0", que era 0.000.
FAMILIA_DURA = "HARD_SCOPE_LITOTES"

#: Invariantes de precision. No son puertas graduables: o valen exactamente esto
#: o el bloque es NO_CONFORME, por buena que sea la cobertura.
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
    """Deriva los veredictos de todas las puertas del bloque desde el informe."""
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
            "baseline_b0": _num(cobertura_base),
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
        "hard_scope_litotes_mejora_sobre_b0": {
            "baseline_b0": _num(dura_base),
            "observado": _num(dura),
            "delta": _num(dura - dura_base),
            "veredicto": _veredicto(dura > dura_base),
        },
        "invariantes_de_precision": {
            "detalle": invariantes,
            "veredicto": _veredicto(invariantes_ok),
        },
    }

    # La puerta de precision es BLOQUEANTE: sin ella el bloque no es conforme
    # aunque la cobertura pase. Las demas suman.
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
        "block": "B2",
        "titulo": "Ampliacion de reglas deterministas (ronda de rework)",
        "generado_por": "scripts/gate4/measure_b2.py",
        "baseline_comparado": str(baseline_path) if baseline else None,
        "corpora": report["corpora"],
        **evaluacion,
        "notes": report.get("notes", []),
    }


def to_markdown(report: dict) -> str:
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    lineas = [
        "# Puerta 4 - B2: reglas deterministas (rework)",
        "",
        f"Veredicto del bloque: **{report['veredicto_bloque']}**",
        "",
        "Generado por `scripts/gate4/measure_b2.py`. Ninguna cifra de este",
        "documento se escribe a mano.",
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
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 4 (B2): medicion + puertas.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="b2-resultado")
    parser.add_argument(
        "--baseline",
        default="artifacts/gate4-program/b0-baseline.json",
        help="informe B0 congelado con el que se calculan los deltas",
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

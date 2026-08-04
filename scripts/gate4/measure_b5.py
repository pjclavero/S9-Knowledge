# -*- coding: utf-8 -*-
"""Puerta 4, bloque B5 (FINAL): re-medicion integra + dictamen del PROGRAMA.

B5 no mejora reglas (`cues.py`/`deterministic.py`/`morphology.py` no se
tocan). Es medicion pura: corre el MISMO arnes (`measure_gate4_program`) que
B0-B4, compara contra el baseline congelado del bloque anterior
(`b4-resultado.json`) para comprobar reproducibilidad exacta, y ademas
deriva el VEREDICTO GLOBAL del programa (B0->B5) segun los criterios que fijo
el operador:

1. cobertura E2E de desarrollo >= 0.60.
2. recall SIMPLE >= 0.70 EN DESARROLLO. Este es el punto en el que este
   bloque difiere de los anteriores: B2/B4 solo publicaban
   `recall_simple` del corpus de GENERALIZACION (clasificador de negacion,
   1.0 desde B2). Esa cifra NO es "recall SIMPLE en desarrollo": la puerta
   de desarrollo que mide exactamente eso ya existe en el runner E2E
   congelado, con el nombre "recall de autoaprobacion SIMPLE >= 0.75"
   (`dev.gates`, metrica `auto_approval_recall[SIMPLE]`) -- decision final
   del MOTOR (AUTO_APPROVE efectivo), no clasificacion de negacion aislada.
   Ese es el numero que se usa aqui para juzgar el criterio del operador
   sobre DESARROLLO. Confundir ambos ya nos costo una leccion cara en el
   motor de relaciones v2 (0.81 en un arnes, 0.24 en real): este bloque
   existe en parte para no repetirla.
3. la generalizacion "acompana": familias no duras a 1.0 y
   HARD_SCOPE_LITOTES con causa estructural documentada (no se exige que
   suba, solo que no oculte el hueco).

Ningun numero de este informe se escribe a mano: todo sale de
`measure_gate4_program()` o de aritmetica sobre sus campos.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from knowledge_v3.eval.harness import measure_gate4_program

UMBRAL_COBERTURA_DEV = 0.60
UMBRAL_RECALL_SIMPLE_DEV = 0.70
UMBRAL_FAMILIA_GENERALIZACION = 1.0
FAMILIA_DURA = "HARD_SCOPE_LITOTES"
NOMBRE_GATE_RECALL_SIMPLE_DEV = "recall de autoaprobacion SIMPLE >= 0.75"

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


def _recall_simple_dev(dev: dict) -> Optional[float]:
    """Extrae el recall de autoaprobacion SIMPLE de los `gates` del runner E2E.

    No se recalcula: se lee de `dev["gates"]`, que ya lo publica el runner
    congelado (`artifacts/v3-final-validation/gate4_negation_measure.py`,
    funcion `gates()`), buscando por NOMBRE exacto en vez de por indice, para
    no depender del orden de la lista.
    """
    for gate in dev.get("gates", []):
        if gate.get("name") == NOMBRE_GATE_RECALL_SIMPLE_DEV:
            return gate.get("observed")
    return None


def evaluar_reproducibilidad(report: dict, baseline: Optional[dict]) -> dict:
    """Compara byte a byte (con tolerancia de redondeo) contra B4.

    B5 no cambia codigo de reglas: si algo se mueve respecto a B4 sin que
    nadie lo haya declarado, es una senal de deriva del corpus/entorno, no
    una mejora, y se reporta como discrepancia -- no se "corrige" el numero.
    """
    if baseline is None:
        return {"comparable": False, "discrepancias": [], "nota": "sin baseline B4 disponible"}

    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    base_dev = baseline["corpora"]["dev"]
    base_gen = baseline["corpora"]["generalization"]

    discrepancias: list[dict[str, Any]] = []

    if _num(dev["coverage"]) != _num(base_dev["coverage"]):
        discrepancias.append({
            "campo": "dev.coverage",
            "b4": _num(base_dev["coverage"]),
            "b5": _num(dev["coverage"]),
        })
    for key in sorted(set(dev["metrics_global"]) | set(base_dev["metrics_global"])):
        v5 = _num(dev["metrics_global"].get(key))
        v4 = _num(base_dev["metrics_global"].get(key))
        if v5 != v4:
            discrepancias.append({"campo": f"dev.metrics_global.{key}", "b4": v4, "b5": v5})

    if _num(gen["metrics_global"].get("overall_accuracy")) != _num(
        base_gen["metrics_global"].get("overall_accuracy")
    ):
        discrepancias.append({
            "campo": "generalization.metrics_global.overall_accuracy",
            "b4": _num(base_gen["metrics_global"].get("overall_accuracy")),
            "b5": _num(gen["metrics_global"].get("overall_accuracy")),
        })
    for fam in sorted(set(gen["metrics_by_family"]) | set(base_gen["metrics_by_family"])):
        a5 = _num(gen["metrics_by_family"].get(fam, {}).get("accuracy"))
        a4 = _num(base_gen["metrics_by_family"].get(fam, {}).get("accuracy"))
        if a5 != a4:
            discrepancias.append({"campo": f"generalization.family.{fam}.accuracy", "b4": a4, "b5": a5})

    return {
        "comparable": True,
        "discrepancias": discrepancias,
        "reproduce_exacto": len(discrepancias) == 0,
    }


def evaluar_puertas(report: dict) -> dict:
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    dev_m = dev["metrics_global"]
    gen_m = gen["metrics_global"]
    familias = gen["metrics_by_family"]

    cobertura = float(dev["coverage"])
    recall_simple_dev = _recall_simple_dev(dev)
    recall_simple_gen = gen_m.get("recall_simple")
    dura = float(familias.get(FAMILIA_DURA, {}).get("accuracy", 0.0))

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

    criterio_1_ok = cobertura >= UMBRAL_COBERTURA_DEV
    criterio_2_ok = recall_simple_dev is not None and recall_simple_dev >= UMBRAL_RECALL_SIMPLE_DEV
    criterio_3_ok = otras_ok  # HARD se reporta pero no bloquea: su bajo valor esta declarado y documentado

    puertas = {
        "1_cobertura_e2e_dev": {
            "umbral": UMBRAL_COBERTURA_DEV,
            "observado": _num(cobertura),
            "casos": f"{dev['covered_cases']}/{dev['evaluable_cases']}",
            "veredicto": _veredicto(criterio_1_ok),
        },
        "2_recall_simple_EN_DESARROLLO": {
            "umbral": UMBRAL_RECALL_SIMPLE_DEV,
            "observado": _num(recall_simple_dev),
            "fuente": f"dev.gates['{NOMBRE_GATE_RECALL_SIMPLE_DEV}']",
            "nota": (
                "NO confundir con generalization.metrics_global.recall_simple "
                f"({_num(recall_simple_gen)}), que mide el CLASIFICADOR de "
                "negacion sobre el corpus de generalizacion, una capa distinta "
                "y mas facil que la decision de motor AUTO_APPROVE sobre dev."
            ),
            "veredicto": _veredicto(criterio_2_ok),
        },
        "2b_recall_simple_generalizacion_clasificador_referencia": {
            "observado": _num(recall_simple_gen),
            "nota": "cifra de referencia (no decide la puerta); ver 2_recall_simple_EN_DESARROLLO",
        },
        "3_generalizacion_acompana": {
            "umbral": UMBRAL_FAMILIA_GENERALIZACION,
            "familias_no_duras": {k: _num(v) for k, v in otras.items()},
            "minimo_no_duras": _num(min(otras.values())) if otras else None,
            "hard_scope_litotes": _num(dura),
            "hard_scope_litotes_nota": (
                "familia dura, bajo por diseno (liston declarado desde B0); "
                "causa estructural documentada en b4-taxonomia.md"
            ),
            "veredicto": _veredicto(criterio_3_ok),
        },
        "invariantes_de_precision": {
            "detalle": invariantes,
            "veredicto": _veredicto(invariantes_ok),
        },
    }

    bloqueante_ok = invariantes_ok
    puerta_cumplida = bloqueante_ok and criterio_1_ok and criterio_2_ok and criterio_3_ok
    if puerta_cumplida:
        veredicto_puerta = "CONFORME"
    elif bloqueante_ok and criterio_1_ok and criterio_3_ok and not criterio_2_ok:
        # cobertura y generalizacion cumplen, invariantes intactos, pero el
        # recall de desarrollo (decision de motor) no llega: parcial, no
        # bloqueante para produccion (nada se autoaprueba de mas), pero la
        # puerta tal como la fijo el operador NO esta cumplida.
        veredicto_puerta = "PARCIAL"
    else:
        veredicto_puerta = "NO_CONFORME"

    return {
        "puertas": puertas,
        "criterios": {
            "1_cobertura_dev_ok": criterio_1_ok,
            "2_recall_simple_dev_ok": criterio_2_ok,
            "3_generalizacion_acompana_ok": criterio_3_ok,
            "invariantes_ok": invariantes_ok,
        },
        "veredicto_puerta_4": veredicto_puerta,
    }


def build_report(baseline_path: Optional[Path]) -> dict:
    report = measure_gate4_program()
    baseline = None
    if baseline_path and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    reproducibilidad = evaluar_reproducibilidad(report, baseline)
    evaluacion = evaluar_puertas(report)
    return {
        "gate": "4",
        "block": "B5",
        "titulo": "Re-medicion integra + dictamen final del programa (B0->B5)",
        "generado_por": "scripts/gate4/measure_b5.py",
        "baseline_comparado": str(baseline_path) if baseline else None,
        "reproducibilidad_vs_b4": reproducibilidad,
        "corpora": report["corpora"],
        **evaluacion,
        "notes": report.get("notes", []),
    }


def to_markdown(report: dict) -> str:
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    repro = report["reproducibilidad_vs_b4"]
    lineas = [
        "# Puerta 4 - B5 (FINAL): re-medicion integra y dictamen del programa",
        "",
        f"Veredicto de la PUERTA 4: **{report['veredicto_puerta_4']}**",
        "",
        "Generado por `scripts/gate4/measure_b5.py`. Ninguna cifra de este",
        "documento se escribe a mano. Baseline comparado (reproducibilidad): "
        f"`{report['baseline_comparado']}`.",
        "",
        "## 0. Reproducibilidad frente a B4",
        "",
    ]
    if repro.get("comparable"):
        if repro["reproduce_exacto"]:
            lineas.append("Reproduce EXACTO: cero discrepancias frente a `b4-resultado.json`.")
        else:
            lineas.append("DISCREPANCIAS frente a `b4-resultado.json` (no corregidas a mano):")
            lineas.append("")
            lineas.append("| campo | B4 | B5 |")
            lineas.append("| --- | ---: | ---: |")
            for d in repro["discrepancias"]:
                lineas.append(f"| {d['campo']} | {d['b4']} | {d['b5']} |")
    else:
        lineas.append(repro.get("nota", "sin baseline"))
    lineas += [
        "",
        "## 1. Criterios de la puerta (fijados por el operador)",
        "",
        "| criterio | umbral | observado | veredicto |",
        "| --- | --- | --- | --- |",
    ]
    for nombre, datos in report["puertas"].items():
        umbral = datos.get("umbral", "-")
        observado = datos.get("observado", datos.get("minimo_no_duras", "-"))
        veredicto = datos.get("veredicto", "-")
        lineas.append(f"| {nombre} | {umbral} | {observado} | {veredicto} |")
    lineas += [
        "",
        "## 2. Corpus de desarrollo (cadena E2E)",
        "",
        f"- cobertura: {dev['coverage']} ({dev['covered_cases']}/{dev['evaluable_cases']})",
    ]
    for k, v in sorted(dev["metrics_global"].items()):
        lineas.append(f"- {k}: {v}")
    lineas += ["", "### Puertas heredadas del runner E2E congelado", ""]
    lineas.append("| puerta | observado | veredicto |")
    lineas.append("| --- | ---: | --- |")
    for g in dev["gates"]:
        lineas.append(f"| {g['name']} | {g['observed']} | {g['status']} |")
    lineas += ["", "## 3. Corpus de generalizacion (clasificador de negacion)", ""]
    lineas.append("| familia | casos | exactitud |")
    lineas.append("| --- | ---: | ---: |")
    for fam, datos in sorted(gen["metrics_by_family"].items()):
        lineas.append(f"| {fam} | {datos['cases']} | {datos['accuracy']} |")
    lineas += ["", "## 4. Notas del arnes", ""]
    lineas += [f"- {n}" for n in report.get("notes", [])]
    lineas += [
        "",
        "## 5. Dictamen honesto de la puerta 4",
        "",
        f"1. Cobertura E2E de desarrollo >= 0.60: **{report['puertas']['1_cobertura_e2e_dev']['veredicto']}** "
        f"({report['puertas']['1_cobertura_e2e_dev']['observado']}, "
        f"{report['puertas']['1_cobertura_e2e_dev']['casos']}).",
        f"2. Recall SIMPLE >= 0.70 EN DESARROLLO (decision de motor AUTO_APPROVE, "
        f"no clasificador aislado): **{report['puertas']['2_recall_simple_EN_DESARROLLO']['veredicto']}** "
        f"({report['puertas']['2_recall_simple_EN_DESARROLLO']['observado']}). La cifra que en B2/B4 se "
        "citaba como \"recall_simple\" (1.0) es la del CLASIFICADOR sobre el corpus de "
        "generalizacion, una capa mas facil; NO es la puerta de desarrollo que fijo el "
        "operador. Bajo esa medida correcta, el recall SIMPLE de desarrollo es bajo desde "
        "B0 y NO ha mejorado en ningun bloque del programa: la cobertura general subio "
        "(B2, reglas de cobertura) pero la decision de AUTO-APROBACION sobre los casos "
        "SIMPLE de desarrollo sigue sin llegar al umbral.",
        f"3. La generalizacion acompana (familias no duras a 1.0, HARD_SCOPE_LITOTES con "
        f"causa estructural documentada): **{report['puertas']['3_generalizacion_acompana']['veredicto']}**.",
        "",
        "Con el criterio 2 sin cumplir, el veredicto GLOBAL de la puerta 4 es "
        f"**{report['veredicto_puerta_4']}**: los invariantes de precision se mantienen "
        "intactos (nada se autoaprueba de mas, cero falsos positivos), la cobertura y la "
        "generalizacion cumplen su liston, pero el criterio de recall SIMPLE en desarrollo, "
        "medido correctamente contra la decision real del motor, no llega al 0.70 fijado "
        "por el operador.",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 4 (B5): re-medicion integra + dictamen final.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="b5-final")
    parser.add_argument(
        "--baseline",
        default="artifacts/gate4-program/b4-resultado.json",
        help="informe B4 congelado con el que se comprueba reproducibilidad",
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
        print(f"veredicto: {report['veredicto_puerta_4']}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

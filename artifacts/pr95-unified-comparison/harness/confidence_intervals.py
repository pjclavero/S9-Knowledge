# -*- coding: utf-8 -*-
"""Intervalos de confianza BOOTSTRAP para las metricas clave de PR#95.

Determinista (semilla fija). OFFLINE. No re-ejecuta modelos: lee los vectores
por-caso ya congelados en raw-redacted-results/ (protocolo, n=54 en C1) y la
comparacion emparejada base-vs-V1 de v1-evidence-category-analysis.json (n=43).

REGLA: no se declara superioridad por diferencias pequenas sin soporte. Con
muestras pequenas se marca la incertidumbre. Confianza (ECE/Brier) solo si hay
casos; aqui el campo confidence sale como 'unsupported' -> se declara INSUFICIENTE.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-audit"
           "/artifacts/pr95-unified-comparison")
RAW = OUT / "raw-redacted-results"
SEED = 20250721
B = 10000


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def boot_prop(vec, rng, b=B):
    """CI 95% de una proporcion por bootstrap (remuestreo de casos)."""
    n = len(vec)
    p = sum(vec) / n
    stats = []
    for _ in range(b):
        s = sum(vec[rng.randrange(n)] for _ in range(n))
        stats.append(s / n)
    stats.sort()
    return {"n": n, "point": round(p, 4),
            "ci95": [round(pct(stats, 2.5), 4), round(pct(stats, 97.5), 4)]}


def boot_paired_diff(vec_a, vec_b, rng, b=B):
    """CI 95% de la diferencia pareada A-B (mismos casos)."""
    n = len(vec_a)
    assert len(vec_b) == n
    d0 = sum(vec_a) / n - sum(vec_b) / n
    stats = []
    for _ in range(b):
        sa = sb = 0
        for _ in range(n):
            i = rng.randrange(n)
            sa += vec_a[i]
            sb += vec_b[i]
        stats.append(sa / n - sb / n)
    stats.sort()
    lo, hi = pct(stats, 2.5), pct(stats, 97.5)
    return {"n": n, "abs_diff": round(d0, 4),
            "rel_diff_pct": (round(100.0 * d0 / (sum(vec_b) / n), 1)
                             if sum(vec_b) else None),
            "ci95_diff": [round(lo, 4), round(hi, 4)],
            "excludes_zero": bool(lo > 0 or hi < 0)}


def accept_vec(version, group="C1_common"):
    d = json.loads((RAW / f"protocol-{version}-{group}.json").read_text())
    return [1 if x["accepted"] else 0 for x in d]


def main():
    rng = random.Random(SEED)
    report = {"method": "nonparametric bootstrap, resample of per-case units",
              "resamples": B, "seed": SEED, "ci": "95% percentile", "metrics": {}}

    # --- PROTOCOLO C1 (n=54) : valid_response_rate ---
    base = accept_vec("base")
    v2 = accept_vec("v2_realignment")
    v3 = accept_vec("v3_fragments")
    report["metrics"]["protocol_C1_valid_rate"] = {
        "base": boot_prop(base, rng),
        "v2_realignment": boot_prop(v2, rng),
        "v3_fragments": boot_prop(v3, rng),
    }
    report["metrics"]["protocol_C1_paired_diffs"] = {
        "v3_minus_base": boot_paired_diff(v3, base, rng),
        "v3_minus_v2": boot_paired_diff(v3, v2, rng),
        "v2_minus_base": boot_paired_diff(v2, base, rng),
    }

    # --- V2 false_realignment (banco sintetico) ---
    # Denominador = realineamientos ejecutados (33 en C1); 6 falsos.
    # n pequeno: se marca incertidumbre explicita.
    fr_vec = [1] * 6 + [0] * (33 - 6)
    rng2 = random.Random(SEED + 1)
    report["metrics"]["v2_false_realign_rate_C1"] = {
        **boot_prop(fr_vec, rng2),
        "denominator": "realignments_fired=33",
        "note": "muestra pequena (33); CI ancho; NO declarar magnitud exacta",
    }
    # En el flujo V2+V3, realign_fired=0 -> false_realign_rate indefinido (0/0);
    # se reporta como estructuralmente 0 (el componente de riesgo no se activa).
    report["metrics"]["v2v3_false_realign_rate_C1"] = {
        "point": 0.0, "realign_fired": 0,
        "note": "V3 cubre todos los casos; el realineamiento de V2 nunca se activa "
                "-> false_realign estructuralmente 0 (no por mejor realineo, sino por "
                "hacerlo innecesario). Firmeza: solo banco sintetico.",
    }

    # --- PIPELINE C1 : evidence_correct base vs V1 (pareado, n=43 TP) ---
    # 36 correctos en ambos, 4 malos en ambos, 3 base-ok/V1-no, 0 base-no/V1-ok.
    base_ev = [1] * 39 + [0] * 4            # 39 correctos, 4 malos
    v1_ev = [1] * 36 + [0] * 3 + [0] * 4    # los mismos 3 que regresan pasan a 0
    # Reordenar para que sean pareados por unidad:
    #   idx 0..35  -> both correct (1,1)
    #   idx 36..38 -> base ok, v1 no (1,0)   (rel-001, rel-002, rel-047)
    #   idx 39..42 -> both wrong  (0,0)
    base_ev = [1] * 36 + [1, 1, 1] + [0, 0, 0, 0]
    v1_ev = [1] * 36 + [0, 0, 0] + [0, 0, 0, 0]
    rng3 = random.Random(SEED + 2)
    report["metrics"]["pipeline_C1_evidence_correct"] = {
        "base": boot_prop(base_ev, rng3),
        "v1_conservative": boot_prop(v1_ev, rng3),
        "base_minus_v1_paired": boot_paired_diff(base_ev, v1_ev, rng3),
        "discordant_pairs": {"base_ok_v1_no": 3, "base_no_v1_ok": 0},
        "mcnemar_exact_two_sided_p": round(2 * (0.5 ** 3), 4),
        "note": "solo 3 pares discordantes, todos en contra de V1; direccion "
                "consistente (0 mejoras) pero NO significativo (p=0.25). No se "
                "declara base>V1 con confianza; si se declara que V1 no mejora.",
    }

    # --- Confianza (ECE/Brier) ---
    report["metrics"]["calibration_ece_brier"] = {
        "status": "INSUFICIENTE",
        "reason": "confidence sale 'unsupported'/NOT_EXECUTED en ambas pistas "
                  "(proveedor no ejecutado; scores no comparables). Sin casos "
                  "con probabilidad calibrable -> ECE/Brier no calculables.",
    }

    (OUT / "confidence-intervals.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

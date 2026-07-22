# -*- coding: utf-8 -*-
"""Matriz de decision ponderada (§19) para PR#95. Determinista, sin datos nuevos:
solo compone los resultados ya verificados. Seguridad = PUERTA (no ponderable):
si no pasa §18, la opcion queda descalificada antes de puntuar.

Los scores 0..1 estan justificados en los docs 11-14. La comparacion entre
pistas es INDICATIVA (V1/V4 miden evidencia de pipeline; V2/V3 aceptacion de
protocolo): el veredicto (doc 16) respeta la separacion de pistas.
"""
from __future__ import annotations
import json
from pathlib import Path

OUT = Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-audit"
           "/artifacts/pr95-unified-comparison")

WEIGHTS = {  # suman 1.0 (seguridad es puerta aparte)
    "evidencia": 0.25, "estructura": 0.20, "falsos_aceptados": 0.20,
    "recall": 0.10, "rendimiento": 0.10, "mantenibilidad": 0.10, "complejidad": 0.05,
}

# Puerta §18: True = pasa. Opciones que no pasen quedan descalificadas.
GATE = {
    "A_solo_P0": True, "B_P0_V2": True, "C_P0_V3": True,
    "D_P0_V2_V3": True, "E_V4_componentes": True, "F_ninguna": True,
}

# Scores 0..1 (1 mejor). Justificacion en docs 11-14.
SCORES = {
    # opcion:            evid  estr  falsos recall rend  mant  compl
    "A_solo_P0":        [0.90, 0.81, 1.00, 0.19, 0.90, 1.00, 1.00],
    "B_P0_V2":          [0.90, 0.81, 0.72, 0.80, 0.85, 0.60, 0.55],
    "C_P0_V3":          [0.75, 0.81, 1.00, 0.96, 0.80, 0.80, 0.70],
    "D_P0_V2_V3":       [0.78, 0.81, 1.00, 0.96, 0.78, 0.55, 0.45],
    "E_V4_componentes": [0.90, 0.81, 1.00, 0.20, 0.85, 0.75, 0.60],
    "F_ninguna":        [0.90, 0.81, 1.00, 0.19, 0.90, 1.00, 1.00],
}
# Notas de firmeza por opcion.
FIRMEZA = {
    "A_solo_P0": "FIRME: integrable ya (CI+§18 verdes).",
    "B_P0_V2": "PROVISIONAL + riesgo: false_realign 0.182 sin guarda; V2 no aporta unico sobre V3.",
    "C_P0_V3": "PROVISIONAL: recall del banco 0.963, pendiente validacion NVIDIA real.",
    "D_P0_V2_V3": "PROVISIONAL: en banco realign_fired=0 -> V2 no aporta; complejidad mayor.",
    "E_V4_componentes": "hybrid_default == base (habilitador); cross_sentence descartado (F1 0.525).",
    "F_ninguna": "equivale a A en scores pero renuncia a P0 firme -> peor por dejar valor en la mesa.",
}

KEYS = list(WEIGHTS.keys())
W = [WEIGHTS[k] for k in KEYS]


def weighted(scores):
    return round(sum(s * w for s, w in zip(scores, W)), 4)


def pareto(rows):
    # No dominadas: nadie es >= en todo y > en algo.
    names = list(rows.keys())
    nd = []
    for a in names:
        sa = rows[a]
        dominated = False
        for b in names:
            if b == a:
                continue
            sb = rows[b]
            if all(y >= x for x, y in zip(sa, sb)) and any(y > x for x, y in zip(sa, sb)):
                dominated = True
                break
        if not dominated:
            nd.append(a)
    return nd


def main():
    result = {"weights": WEIGHTS, "gate_section18": GATE,
              "dimensions": KEYS, "options": {}}
    for name, sc in SCORES.items():
        result["options"][name] = {
            "gate_pass": GATE[name],
            "scores": dict(zip(KEYS, sc)),
            "weighted_total": weighted(sc) if GATE[name] else None,
            "firmeza": FIRMEZA[name],
        }
    result["pareto_non_dominated"] = pareto(SCORES)
    ranking = sorted(((n, weighted(s)) for n, s in SCORES.items()),
                     key=lambda x: -x[1])
    result["ranking_weighted"] = [{"option": n, "score": s} for n, s in ranking]
    result["note"] = ("Comparacion entre pistas es INDICATIVA. Seguridad es puerta, "
                      "no peso. El veredicto respeta la separacion de pistas y la "
                      "distincion FIRME (P0/§18/V1-neg/V4-compat) vs PROVISIONAL (V2 vs V3).")
    (OUT / "decision-matrix.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ranking": result["ranking_weighted"],
                      "pareto": result["pareto_non_dominated"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

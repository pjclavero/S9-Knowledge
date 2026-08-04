# -*- coding: utf-8 -*-
"""Tests del runner de comparacion B1 (`scripts/gate6/measure_b1.py`).

No repite lo que ya cubre `test_gate6_harness.py` (integridad, determinismo
del arnes subyacente): esto prueba que la comparacion fila a fila contra
`b0-baseline.json` es correcta y determinista, y que el propio artefacto
congelado de B1 (`artifacts/gate6-program/b1-operators.json`) sigue
reproduciendose byte a byte por cifras, no a mano.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "gate6"))

from measure_b1 import build_b1_report  # noqa: E402

BASELINE_PATH = REPO_ROOT / "artifacts" / "gate6-program" / "b0-baseline.json"
B1_ARTIFACT_PATH = REPO_ROOT / "artifacts" / "gate6-program" / "b1-operators.json"


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_el_informe_b1_es_determinista_byte_a_byte():
    baseline = _load_baseline()
    primero = json.dumps(build_b1_report(baseline), ensure_ascii=False, sort_keys=True)
    segundo = json.dumps(build_b1_report(baseline), ensure_ascii=False, sort_keys=True)
    assert primero == segundo


def test_no_hay_regresiones_de_dev_ni_de_generalizacion():
    """Regla de oro del bloque: ninguna violacion NUEVA, ninguna regresion."""
    baseline = _load_baseline()
    report = build_b1_report(baseline)
    cmp = report["comparison_vs_b0"]
    assert cmp["dev"]["regressions"] == []
    assert cmp["generalization"]["regressions"] == []
    assert cmp["fail_closed_violations"]["new"] == []


def test_policy_accuracy_de_dev_no_baja_de_f6_7():
    baseline = _load_baseline()
    report = build_b1_report(baseline)
    dev = report["current"]["corpora"]["dev"]["metrics_global"]["policy_accuracy"]
    assert dev >= 0.79 - 1e-9


def test_las_violaciones_fail_closed_bajan_respecto_de_b0():
    baseline = _load_baseline()
    report = build_b1_report(baseline)
    viol = report["comparison_vs_b0"]["fail_closed_violations"]
    assert viol["count_after"] < viol["count_before"]


def test_el_artefacto_b1_operators_congelado_coincide_con_la_medida_actual():
    """Si esto falla, alguien toco `cues.py`/`factivity.py` despues de
    congelar el artefacto sin regenerarlo -- hay que volver a correr
    `scripts/gate6/measure_b1.py` y commitear el resultado nuevo, nunca
    editar el JSON a mano."""
    assert B1_ARTIFACT_PATH.exists(), "falta artifacts/gate6-program/b1-operators.json"
    frozen = json.loads(B1_ARTIFACT_PATH.read_text(encoding="utf-8"))
    baseline = _load_baseline()
    fresh = build_b1_report(baseline)
    assert frozen["current"]["corpora"]["dev"]["metrics_global"] == (
        fresh["current"]["corpora"]["dev"]["metrics_global"]
    )
    assert frozen["current"]["corpora"]["generalization"]["metrics_global"] == (
        fresh["current"]["corpora"]["generalization"]["metrics_global"]
    )
    assert frozen["current"]["fail_closed_invariant"]["status"] == (
        fresh["current"]["fail_closed_invariant"]["status"]
    )

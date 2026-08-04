# -*- coding: utf-8 -*-
"""Tests del bloque B5 (FINAL): re-medicion + dictamen del programa.

B5 no toca reglas (`cues.py`/`deterministic.py`/`morphology.py`): estos
tests defienden la LOGICA DE DERIVACION del veredicto
(`scripts/gate4/measure_b5.py`), no el extractor. En particular:

1. Que la medicion real reproduce EXACTO frente al baseline congelado de B4
   (ninguna regla se movio).
2. Que el criterio "recall SIMPLE en desarrollo" lee la puerta CORRECTA del
   runner E2E (`auto_approval_recall[SIMPLE]` sobre `dev.gates`), no la cifra
   del clasificador de generalizacion -- que es justo la confusion que este
   bloque existe para no cometer.
3. Que el veredicto se deriva programaticamente de umbrales, nunca a mano.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "gate4"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_b5  # noqa: E402
from knowledge_v3.eval.harness import measure_gate4_program  # noqa: E402


@pytest.fixture(scope="module")
def report():
    return measure_gate4_program()


def test_reproduce_exacto_frente_a_b4(report):
    baseline_path = REPO_ROOT / "artifacts" / "gate4-program" / "b4-resultado.json"
    assert baseline_path.exists()
    import json

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    repro = measure_b5.evaluar_reproducibilidad(report, baseline)
    assert repro["comparable"] is True
    assert repro["discrepancias"] == []
    assert repro["reproduce_exacto"] is True


def test_recall_simple_dev_lee_la_puerta_de_autoaprobacion_no_el_clasificador(report):
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]
    recall_dev = measure_b5._recall_simple_dev(dev)

    # La puerta del runner E2E congelado existe y su nombre no ha cambiado.
    nombres = {g["name"] for g in dev["gates"]}
    assert measure_b5.NOMBRE_GATE_RECALL_SIMPLE_DEV in nombres

    # Es un numero real (no None) y es DISTINTO del recall_simple del
    # clasificador de generalizacion: si algun dia coincidieran por
    # casualidad, este test seguiria pasando, pero la asercion de "vienen de
    # sitios distintos" se defiende comparando contra el origen, no el valor.
    assert recall_dev is not None
    assert recall_dev == pytest.approx(0.1)
    assert gen["metrics_global"]["recall_simple"] == pytest.approx(1.0)
    assert recall_dev != gen["metrics_global"]["recall_simple"]


def test_veredicto_puerta_es_parcial_por_recall_simple_dev(report):
    evaluacion = measure_b5.evaluar_puertas(report)
    criterios = evaluacion["criterios"]
    assert criterios["1_cobertura_dev_ok"] is True
    assert criterios["2_recall_simple_dev_ok"] is False
    assert criterios["3_generalizacion_acompana_ok"] is True
    assert criterios["invariantes_ok"] is True
    assert evaluacion["veredicto_puerta_4"] == "PARCIAL"


def test_veredicto_se_deriva_no_se_escribe_a_mano():
    """Umbrales sinteticos: si los tres criterios cumplen, el veredicto es
    CONFORME; si un invariante bloqueante falla, es NO_CONFORME aunque los
    tres criterios numericos cumplan. Prueba la FUNCION, no datos reales."""
    fake_ok = {
        "corpora": {
            "dev": {
                "coverage": 0.65,
                "covered_cases": 30,
                "evaluable_cases": 46,
                "metrics_global": {
                    "auto_approval_precision": 1.0,
                    "negative_edge_precision": 1.0,
                    "negated_cessation_safety": 1.0,
                    "evidence_grounding": 1.0,
                    "false_positive_relation_from_negation": 0,
                },
                "gates": [
                    {"name": measure_b5.NOMBRE_GATE_RECALL_SIMPLE_DEV, "observed": 0.8},
                ],
            },
            "generalization": {
                "metrics_global": {"recall_simple": 1.0},
                "metrics_by_family": {
                    "SIMPLE": {"cases": 8, "accuracy": 1.0},
                    "HARD_SCOPE_LITOTES": {"cases": 4, "accuracy": 0.5},
                },
            },
        }
    }
    evaluacion = measure_b5.evaluar_puertas(fake_ok)
    assert evaluacion["veredicto_puerta_4"] == "CONFORME"

    fake_bloqueado = {
        "corpora": {
            "dev": {
                "coverage": 0.65,
                "covered_cases": 30,
                "evaluable_cases": 46,
                "metrics_global": {
                    "auto_approval_precision": 0.9,  # invariante rota
                    "negative_edge_precision": 1.0,
                    "negated_cessation_safety": 1.0,
                    "evidence_grounding": 1.0,
                    "false_positive_relation_from_negation": 0,
                },
                "gates": [
                    {"name": measure_b5.NOMBRE_GATE_RECALL_SIMPLE_DEV, "observed": 0.8},
                ],
            },
            "generalization": {
                "metrics_global": {"recall_simple": 1.0},
                "metrics_by_family": {
                    "SIMPLE": {"cases": 8, "accuracy": 1.0},
                    "HARD_SCOPE_LITOTES": {"cases": 4, "accuracy": 0.5},
                },
            },
        }
    }
    evaluacion_bloqueada = measure_b5.evaluar_puertas(fake_bloqueado)
    assert evaluacion_bloqueada["veredicto_puerta_4"] == "NO_CONFORME"

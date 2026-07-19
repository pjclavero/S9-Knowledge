# -*- coding: utf-8 -*-
"""Test LIVE (gateado) del evaluador externo contra NVIDIA NIM REAL en modo sombra.

Solo se ejecuta cuando:
  * `S9K_NVIDIA_LIVE=1`, y
  * `S9K_NVIDIA_ENABLED=true` con `S9K_NVIDIA_API_KEY` presente.

En CI (sin esas variables) se SALTA: no hay red a NVIDIA, no hay flaky, la suite
sigue verde. La validacion real la ejecuta el operador de forma autorizada y su
evidencia se registra en el informe del Bloque 2.

Usa datos SINTETICOS, comprueba invariantes de SOMBRA (nunca AUTO_APPROVED,
shadow_mode=True) y no escribe en Neo4j ni en disco.
"""
from __future__ import annotations

import os

import pytest

_LIVE = os.environ.get("S9K_NVIDIA_LIVE") == "1"
_ENABLED = os.environ.get("S9K_NVIDIA_ENABLED", "").strip().lower() == "true"
_KEY = bool(os.environ.get("S9K_NVIDIA_API_KEY", "").strip())
_MODEL = next(
    (m.strip() for m in os.environ.get("S9K_NVIDIA_REVIEW_MODELS", "").split(",") if m.strip()),
    "meta/llama-3.1-70b-instruct",
)

pytestmark = pytest.mark.skipif(
    not (_LIVE and _ENABLED and _KEY),
    reason="Test live NVIDIA: requiere S9K_NVIDIA_LIVE=1, S9K_NVIDIA_ENABLED=true y API key.",
)


def test_nvidia_live_shadow_invariants():
    """Contra NVIDIA real: el evaluador se mantiene en sombra y nunca auto-aprueba."""
    from relations.calibration.nvidia_shadow_probe import DEFAULT_CANDIDATES, run_probe

    report = run_probe(model=_MODEL, candidates=DEFAULT_CANDIDATES, repetitions=2)
    d = report.to_dict()
    assert d["global_invariants"]["all_shadow"] is True
    assert d["global_invariants"]["no_approvals"] is True
    assert d["api_key_present"] is True
    # El informe nunca contiene la API key.
    assert os.environ["S9K_NVIDIA_API_KEY"].strip() not in report.to_json()
    for case in d["cases"]:
        assert set(case["recommendations"]) <= {"confirm", "refine", "reject", "human"}

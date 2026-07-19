# -*- coding: utf-8 -*-
"""Test LIVE (gateado) del evaluador LLM local contra Ollama REAL en modo sombra.

Este test SOLO se ejecuta cuando se cumplen TODAS estas condiciones:
  * `S9K_OLLAMA_LIVE=1` en el entorno (opt-in explicito del operador), y
  * `S9K_OLLAMA_BASE_URL` apunta a un endpoint alcanzable.

En CI (sin esas variables) se SALTA: no hay red a Ollama, no hay flaky, la suite
sigue verde. La validacion real la ejecuta el operador/organizador de forma
autorizada y aislada, y su evidencia se registra en el informe del Bloque 1.

Aun siendo live, este test:
  * usa datos SINTETICOS (no corpus privado),
  * comprueba invariantes de SOMBRA (nunca aprueba, shadow=True),
  * no escribe en Neo4j ni en disco.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

import pytest

_LIVE = os.environ.get("S9K_OLLAMA_LIVE") == "1"
_ENDPOINT = os.environ.get("S9K_OLLAMA_BASE_URL", "")
_MODEL = os.environ.get("S9K_OLLAMA_MODEL", "qwen2.5:7b")


def _endpoint_reachable(endpoint: str, timeout: float = 2.0) -> bool:
    if not endpoint:
        return False
    parts = urlsplit(endpoint)
    host = parts.hostname
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_LIVE and _endpoint_reachable(_ENDPOINT)),
    reason="Test live de Ollama: requiere S9K_OLLAMA_LIVE=1 y S9K_OLLAMA_BASE_URL alcanzable.",
)


def test_ollama_live_shadow_invariants():
    """Contra Ollama real: el evaluador se mantiene en sombra y nunca aprueba."""
    from relations.calibration.ollama_shadow_probe import DEFAULT_CASES, run_probe

    report = run_probe(
        endpoint=_ENDPOINT,
        model=_MODEL,
        cases=DEFAULT_CASES,
        repetitions=2,
        timeout=180,
        max_retries=1,
    )
    d = report.to_dict()
    # Invariantes duros de modo sombra, verificados contra el proveedor real.
    assert d["global_invariants"]["all_shadow"] is True
    assert d["global_invariants"]["no_approvals"] is True
    # El informe nunca revela el host real del endpoint.
    assert _ENDPOINT.split("//", 1)[-1].split("/")[0] not in report.to_json()
    # Todos los casos produjeron alguna recomendacion valida (nunca aprobacion).
    for case in d["cases"]:
        assert set(case["recommendations"]) <= {
            "recommend_propose", "recommend_reject", "recommend_human_review"
        }

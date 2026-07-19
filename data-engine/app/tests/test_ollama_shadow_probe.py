# -*- coding: utf-8 -*-
"""Tests del probe de calibracion Ollama en modo sombra (`relations.calibration`).

Todos los transportes se inyectan: NO hay red, NO hay Ollama real, NO se escribe
nada. Se importan los modulos REALES (`relations.calibration.ollama_shadow_probe`).
"""
from __future__ import annotations

import json
import socket

import pytest

from external_ai.errors import ConfigError
from relations.calibration.ollama_shadow_probe import (
    DEFAULT_CASES,
    SyntheticCase,
    redact_endpoint_host,
    run_probe,
)


# ---------------------------------------------------------------------------
# Transportes mock (deterministas) — sin red
# ---------------------------------------------------------------------------
def _valid_relation(document: str, evidence: str, **over) -> dict:
    start = document.find(evidence)
    rel = {
        "predicate": "MEMBER_OF",
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.9,
        "evidence_text": evidence,
        "evidence_start": start,
        "evidence_end": start + len(evidence),
        "negated": False,
        "temporal_scope": None,
        "epistemic_status": "ASSERTED",
        "subject_type": "Character",
        "object_type": "Faction",
    }
    rel.update(over)
    return rel


def _fixed_transport(content: str, latency: int = 40):
    def transport(messages):
        assert isinstance(messages, list) and messages[0]["role"] == "system"
        return ({"choices": [{"message": {"content": content}}]}, latency)

    return transport


_CASE = SyntheticCase(
    name="membership_affirmative",
    document="Bayushi Hisao juro lealtad al Clan Escorpion.",
    subject_id="Bayushi Hisao",
    object_id="Clan Escorpion",
    template_id="membership",
    subject_type="Character",
    object_type="Faction",
)


# ---------------------------------------------------------------------------
# Fallo cerrado: sin endpoint ni transporte -> ConfigError, sin abrir socket.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_probe_fails_closed_without_endpoint(monkeypatch):
    """El probe NO debe tocar red sin endpoint explicito ni transporte."""
    def _boom(*a, **k):  # pragma: no cover - solo si algo abre red
        raise AssertionError("el probe no debe abrir socket sin endpoint")

    monkeypatch.setattr(socket, "socket", _boom)
    with pytest.raises(ConfigError):
        run_probe(endpoint=None, model="qwen2.5:7b", cases=[_CASE], repetitions=2)


# ---------------------------------------------------------------------------
# Agregacion determinista: mismo contenido en todas las repeticiones.
# ---------------------------------------------------------------------------
def test_probe_reports_deterministic_when_output_identical():
    content = json.dumps({"relations": [_valid_relation(_CASE.document, "juro lealtad al Clan Escorpion")]})
    report = run_probe(
        endpoint=None,
        model="qwen2.5:7b",
        cases=[_CASE],
        repetitions=3,
        transport=_fixed_transport(content),
    )
    assert len(report.cases) == 1
    cr = report.cases[0]
    assert cr.repetitions == 3
    assert cr.deterministic is True
    assert cr.summary()["distinct_outputs"] == 1
    # Invariantes de sombra globales.
    assert report.to_dict()["global_invariants"] == {"all_shadow": True, "no_approvals": True}


# ---------------------------------------------------------------------------
# Deteccion de NO determinismo: contenido distinto entre repeticiones.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_probe_detects_non_determinism():
    outputs = [
        json.dumps({"relations": [_valid_relation(_CASE.document, "juro lealtad al Clan Escorpion", confidence=0.9)]}),
        json.dumps({"relations": [_valid_relation(_CASE.document, "juro lealtad al Clan Escorpion", confidence=0.6)]}),
    ]
    state = {"i": 0}

    def transport(messages):
        out = outputs[state["i"] % len(outputs)]
        state["i"] += 1
        return ({"choices": [{"message": {"content": out}}]}, 30)

    report = run_probe(
        endpoint=None, model="qwen2.5:7b", cases=[_CASE], repetitions=2, transport=transport,
    )
    cr = report.cases[0]
    assert cr.deterministic is False
    assert cr.summary()["distinct_outputs"] == 2


# ---------------------------------------------------------------------------
# Invariante de sombra: ni siquiera un consenso fuerte produce aprobacion.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_probe_never_approves_even_on_strong_consensus():
    content = json.dumps({"relations": [_valid_relation(_CASE.document, "juro lealtad al Clan Escorpion", confidence=0.99)]})
    report = run_probe(
        endpoint=None, model="qwen2.5:7b", cases=[_CASE], repetitions=1, transport=_fixed_transport(content),
    )
    cr = report.cases[0]
    assert cr.any_approval is False
    assert cr.all_shadow is True
    # La recomendacion mas fuerte posible es 'propose', nunca 'approve'.
    assert set(cr.recommendations) <= {"recommend_propose", "recommend_reject", "recommend_human_review"}


# ---------------------------------------------------------------------------
# JSON invalido del modelo -> validation_status INVALID, pero sigue en sombra.
# ---------------------------------------------------------------------------
def test_probe_records_invalid_when_model_returns_garbage():
    report = run_probe(
        endpoint=None, model="qwen2.5:7b", cases=[_CASE], repetitions=1,
        transport=_fixed_transport("esto no es json"),
    )
    cr = report.cases[0]
    assert "INVALID" in cr.validation_statuses
    assert cr.all_shadow is True
    assert cr.any_approval is False


# ---------------------------------------------------------------------------
# Redaccion del endpoint: nunca revela host/IP en el informe.
# ---------------------------------------------------------------------------
def test_redact_endpoint_hides_host():
    assert redact_endpoint_host("http://192.0.2.1:11434/v1") == "http://<host>/v1"
    assert redact_endpoint_host("https://ollama.internal:443/v1") == "https://<host>/v1"
    # Sin esquema no revela nada.
    assert redact_endpoint_host("no-es-url") == "<host>"


def test_report_endpoint_is_redacted_by_default():
    content = json.dumps({"relations": [_valid_relation(_CASE.document, "juro lealtad al Clan Escorpion")]})
    # endpoint explicito pero transport inyectado: no hay red; el informe ofusca host.
    report = run_probe(
        endpoint="http://192.0.2.1:11434/v1", model="qwen2.5:7b",
        cases=[_CASE], repetitions=1, transport=_fixed_transport(content),
    )
    assert report.endpoint == "http://<host>/v1"
    assert "192.0.2.1" not in report.to_json()


# ---------------------------------------------------------------------------
# repetitions invalido -> ValueError.
# ---------------------------------------------------------------------------
def test_probe_rejects_zero_repetitions():
    with pytest.raises(ValueError):
        run_probe(endpoint=None, model="m", cases=[_CASE], repetitions=0,
                  transport=_fixed_transport("{}"))


# ---------------------------------------------------------------------------
# Corpus por defecto: 3 casos sinteticos (afirmativo, negado, rumor).
# ---------------------------------------------------------------------------
def test_default_cases_cover_affirmative_negated_rumor():
    names = {c.name for c in DEFAULT_CASES}
    assert names == {"membership_affirmative", "alliance_negated", "alliance_rumored"}

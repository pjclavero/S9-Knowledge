# -*- coding: utf-8 -*-
"""Tests del probe de calibracion NVIDIA en modo sombra (`relations.calibration`).

Se inyecta un proveedor FALSO con `_post_chat`: NO hay red, NO hay NVIDIA real,
NO se escribe nada. Se importan los modulos REALES.
"""
from __future__ import annotations

import json
import socket

import pytest

from external_ai.errors import ConfigError
from relations.calibration.nvidia_shadow_probe import (
    DEFAULT_CANDIDATES,
    SyntheticCandidate,
    redact_endpoint_host,
    run_probe,
)
from relations.contracts import EpistemicStatus


# ---------------------------------------------------------------------------
# Proveedor FALSO (sin red). Devuelve un verdicto valido para el candidato dado.
# ---------------------------------------------------------------------------
def _verdict_for(candidate_id, segment, evidence, predicate, verdict="confirm", **over):
    start = segment.find(evidence)
    v = {
        "candidate_id": candidate_id,
        "verdict": verdict,
        "predicate": predicate,
        "subject_type": "Character",
        "object_type": "Character",
        "negated": False,
        "evidence_text": evidence,
        "evidence_start": start,
        "evidence_end": start + len(evidence),
        "confidence": 0.9,
        "reason_codes": [],
        "explanation": "sintetico",
    }
    v.update(over)
    return v


class _FakeProvider:
    """Proveedor OpenAI-compatible falso: responde segun el candidate_id del prompt."""

    provider_name = "nvidia"

    def __init__(self, content_for_cid):
        # content_for_cid: callable(cid) -> str (contenido JSON del modelo)
        self._content_for_cid = content_for_cid
        self.calls = 0

    def _post_chat(self, model, messages):
        self.calls += 1
        # El cid aparece en el mensaje 'user' (schema pide candidate_id="...").
        user = messages[-1]["content"]
        import re
        m = re.search(r'candidate_id="([^"]+)"', user)
        cid = m.group(1) if m else ""
        return ({"choices": [{"message": {"content": self._content_for_cid(cid)}}]}, 11)


_AFF = SyntheticCandidate(
    name="alliance_affirmative",
    segment="Kakita Asuka es aliada de Bayushi Hisao en la corte.",
    evidence="Kakita Asuka es aliada de Bayushi Hisao",
    subject_id="ent_asuka", object_id="ent_hisao", predicate="ALLIED_WITH",
    subject_type="Character", object_type="Character",
)


def _confirm_provider():
    def content(cid):
        return json.dumps({"verdicts": [
            _verdict_for(cid, _AFF.segment, _AFF.evidence, _AFF.predicate, "confirm")
        ]})
    return _FakeProvider(content)


# ---------------------------------------------------------------------------
# Fallo cerrado: sin API key y sin proveedor -> ConfigError, sin abrir socket.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_nvidia_probe_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)

    def _boom(*a, **k):  # pragma: no cover - solo si algo abre red
        raise AssertionError("el probe no debe abrir socket sin API key")

    monkeypatch.setattr(socket, "socket", _boom)
    with pytest.raises(ConfigError):
        run_probe(model="meta/llama-3.1-70b-instruct", candidates=[_AFF], repetitions=2)


# ---------------------------------------------------------------------------
# Determinismo agregado con proveedor inyectado (sin red, sin clave necesaria).
# ---------------------------------------------------------------------------
def test_nvidia_probe_deterministic_with_injected_provider(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)  # no debe hacer falta
    report = run_probe(
        model="meta/llama-3.1-70b-instruct",
        candidates=[_AFF], repetitions=3, provider=_confirm_provider(),
    )
    assert len(report.cases) == 1
    cr = report.cases[0]
    assert cr.repetitions == 3
    assert cr.deterministic is True
    assert cr.summary()["distinct_outputs"] == 1
    assert report.to_dict()["global_invariants"] == {"all_shadow": True, "no_approvals": True}
    # api_key_present refleja el entorno (aqui, ausente), sin revelar la clave.
    assert report.api_key_present is False


# ---------------------------------------------------------------------------
# No-aprobacion: aun con 'confirm', la recomendacion sombra nunca es AUTO_APPROVED.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_nvidia_probe_never_auto_approves(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)
    report = run_probe(
        model="m", candidates=[_AFF], repetitions=1, provider=_confirm_provider(),
    )
    cr = report.cases[0]
    assert cr.any_approval is False
    assert cr.all_shadow is True
    assert set(cr.recommendations) <= {"confirm", "refine", "reject", "human"}
    assert "AUTO_APPROVED" not in cr.recommendations


# ---------------------------------------------------------------------------
# Deteccion de no-determinismo entre repeticiones.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_nvidia_probe_detects_non_determinism(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)
    verdicts = ["confirm", "reject"]
    state = {"i": 0}

    def content(cid):
        v = verdicts[state["i"] % len(verdicts)]
        state["i"] += 1
        return json.dumps({"verdicts": [
            _verdict_for(cid, _AFF.segment, _AFF.evidence, _AFF.predicate, v)
        ]})

    report = run_probe(
        model="m", candidates=[_AFF], repetitions=2, provider=_FakeProvider(content),
    )
    cr = report.cases[0]
    assert cr.deterministic is False
    assert cr.summary()["distinct_outputs"] == 2


# ---------------------------------------------------------------------------
# JSON basura del modelo -> INVALID_RESPONSES, pero sigue en sombra.
# ---------------------------------------------------------------------------
def test_nvidia_probe_records_invalid_on_garbage(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)
    report = run_probe(
        model="m", candidates=[_AFF], repetitions=1,
        provider=_FakeProvider(lambda cid: "no soy json"),
    )
    cr = report.cases[0]
    assert "INVALID_RESPONSES" in cr.states
    assert cr.all_shadow is True
    assert cr.any_approval is False


# ---------------------------------------------------------------------------
# Redaccion del endpoint / no exposicion del secreto.
# ---------------------------------------------------------------------------
def test_nvidia_redact_endpoint_hides_host():
    assert redact_endpoint_host("https://integrate.api.nvidia.com/v1") == "https://<host>/v1"
    assert redact_endpoint_host("no-es-url") == "<host>"


def test_nvidia_report_never_contains_api_key(monkeypatch):
    monkeypatch.setenv("S9K_NVIDIA_API_KEY", "nvapi-SECRETO_NO_DEBE_APARECER")
    report = run_probe(
        model="m", candidates=[_AFF], repetitions=1, provider=_confirm_provider(),
    )
    blob = report.to_json()
    assert "nvapi-SECRETO_NO_DEBE_APARECER" not in blob
    assert "SECRETO" not in blob
    # Con la clave presente en el entorno, el informe lo refleja como booleano.
    assert report.api_key_present is True


# ---------------------------------------------------------------------------
# repetitions invalido -> ValueError.
# ---------------------------------------------------------------------------
def test_nvidia_probe_rejects_zero_repetitions(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)
    with pytest.raises(ValueError):
        run_probe(model="m", candidates=[_AFF], repetitions=0, provider=_confirm_provider())


# ---------------------------------------------------------------------------
# Corpus por defecto: 3 casos (afirmativo, negado, pertenencia).
# ---------------------------------------------------------------------------
def test_nvidia_default_candidates_cover_affirmative_negated():
    names = {c.name for c in DEFAULT_CANDIDATES}
    assert names == {"alliance_affirmative", "alliance_negated", "membership_affirmative"}
    negated = {c.name for c in DEFAULT_CANDIDATES if c.negated}
    assert negated == {"alliance_negated"}

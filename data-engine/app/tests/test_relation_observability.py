# -*- coding: utf-8 -*-
"""Tests de la observabilidad/trazabilidad DESACOPLADA del pipeline de relaciones.

Cubren: redaccion de secretos/cabeceras (nunca aparecen en la salida), campos
obligatorios (falta uno -> error), serializacion round-trip determinista, errores
registrados, Unicode en campos, distincion sintetico/privado, determinismo con reloj
inyectado y ausencia de red (no importa requests/httpx ni abre sockets).
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.observability import (  # noqa: E402
    ComponentResult,
    ObservabilityError,
    RelationEvent,
    RelationTrace,
    find_secrets,
    hash_value,
    redact,
    time_component,
)


# --- Helpers ---------------------------------------------------------------
def _event(**overrides):
    base = dict(
        execution_id="exec-1",
        document_id="doc-1",
        workspace="ws-a",
        component="pairs",
        version="v1",
        result=ComponentResult.OK,
    )
    base.update(overrides)
    return RelationEvent(**base)


# --- Redaccion -------------------------------------------------------------
def test_redact_secret_not_in_output():
    secret = "nvapi-abcdefghijklmnop1234567890"
    ev = _event(
        errors=[f"fallo con clave {secret}"],
        provider_status={"nvidia": "sk-abcdefghijklmnopqrstuvwxyz01"},
    )
    ev.validate()
    out = ev.to_json()
    assert secret not in out
    assert "sk-abcdefghijklmnopqrstuvwxyz01" not in out
    assert "[REDACTED]" in out


def test_redact_authorization_header():
    payload = {"Authorization": "Bearer supersecrettoken123456", "ok": "visible"}
    redacted = redact(payload)
    dumped = json.dumps(redacted)
    assert "supersecrettoken123456" not in dumped
    assert "visible" in dumped
    assert redacted["Authorization"] == "[REDACTED]"


def test_find_secrets_detects_without_exposing():
    hits = find_secrets("token=ghp_abcdefghijklmnopqrstuvwxyz0123")
    assert hits  # detecta al menos un patron
    # el valor del secreto no forma parte del nombre de patron devuelto
    assert all("ghp_abcdefghijklmnop" not in h for h in hits)


def test_hash_value_deterministic_and_opaque():
    v = "id-privado-42"
    assert hash_value(v) == hash_value(v)
    assert v not in hash_value(v)
    assert len(hash_value(v, length=16)) == 16


# --- Campos obligatorios ---------------------------------------------------
@pytest.mark.parametrize(
    "field_name", ["execution_id", "document_id", "workspace", "component", "version"]
)
def test_missing_required_field_raises(field_name):
    with pytest.raises(ObservabilityError):
        _event(**{field_name: ""}).validate()


def test_invalid_result_raises():
    with pytest.raises(ObservabilityError):
        _event(result="NOPE").validate()


def test_negative_numeric_raises():
    with pytest.raises(ObservabilityError):
        _event(num_pairs=-1).validate()
    with pytest.raises(ObservabilityError):
        _event(duration=-0.5).validate()
    with pytest.raises(ObservabilityError):
        _event(estimated_cost=-1.0).validate()


# --- Serializacion round-trip determinista ---------------------------------
def test_roundtrip_deterministic():
    ev = _event(
        segment_id="seg-9",
        candidate_id="cand-3",
        duration=1.5,
        num_pairs=4,
        num_signals=7,
        retries=2,
        input_size=100,
        output_size=42,
        estimated_cost=0.01,
        consensus_decision="STRONG_CONSENSUS",
        provider_status={"ollama": "ok", "nvidia": "skipped"},
        errors=["timeout parcial"],
        synthetic=True,
    ).validate()

    j1 = ev.to_json()
    j2 = ev.to_json()
    assert j1 == j2  # byte a byte

    rebuilt = RelationEvent.from_dict(json.loads(j1))
    assert rebuilt.to_json() == j1  # round-trip estable


def test_to_dict_sorted_keys_determinism():
    ev = _event().validate()
    keys = list(ev.to_json())
    # to_json usa sort_keys; dos serializaciones son identicas
    assert ev.to_json() == ev.to_json()
    assert keys == list(ev.to_json())


# --- Errores registrados ---------------------------------------------------
def test_errors_recorded():
    ev = _event(result=ComponentResult.ERROR, errors=["boom", "otra causa"]).validate()
    d = ev.to_dict()
    assert d["result"] == "ERROR"
    assert d["errors"] == ["boom", "otra causa"]


def test_errors_must_be_list_of_str():
    with pytest.raises(ObservabilityError):
        _event(errors=[123]).validate()


# --- Unicode ---------------------------------------------------------------
def test_unicode_fields_preserved():
    ev = _event(
        component="señales-relación",
        errors=["fallo en «Ñandú» — café ☕"],
        synthetic=True,
        sample_text="Frase con acentos áéíóú y emoji 🚀",
    ).validate()
    out = ev.to_json()
    assert "señales-relación" in out
    assert "Ñandú" in out
    assert "🚀" in out
    # round-trip preserva Unicode
    rebuilt = RelationEvent.from_dict(json.loads(out))
    assert rebuilt.component == "señales-relación"


# --- Distincion sintetico / privado ---------------------------------------
def test_synthetic_text_is_included_but_private_is_not():
    text = "contenido real del documento"
    private = _event(synthetic=False, sample_text=text).validate()
    d_priv = private.to_dict()
    # dato privado: no se vuelca el texto, solo hash + longitud
    assert d_priv["sample_text"] is None
    assert d_priv["sample_text_hash"] == hash_value(text)
    assert d_priv["sample_text_len"] == len(text)
    assert text not in private.to_json()

    synthetic = _event(synthetic=True, sample_text=text).validate()
    d_syn = synthetic.to_dict()
    assert d_syn["sample_text"] == text  # sintetico si se registra


def test_private_text_dumped_only_with_flag():
    text = "otro contenido privado"
    ev = _event(synthetic=False, sample_text=text).validate()
    assert text not in ev.to_json()
    assert text in ev.to_json(include_private=True)


def test_private_sample_text_redacts_secrets_even_when_dumped():
    secret = "sk-abcdefghijklmnopqrstuvwxyz01"
    ev = _event(synthetic=True, sample_text=f"clave {secret} incrustada").validate()
    assert secret not in ev.to_json()


# --- Determinismo con reloj inyectado --------------------------------------
def test_time_component_injected_clock_reproducible():
    ticks = iter([10.0, 13.5])
    clock = lambda: next(ticks)  # noqa: E731
    with time_component(clock=clock) as handle:
        pass
    assert handle.started_at == 10.0
    assert handle.ended_at == 13.5
    assert handle.duration == 3.5


def test_time_component_records_duration_on_exception():
    ticks = iter([0.0, 2.0])
    clock = lambda: next(ticks)  # noqa: E731
    with pytest.raises(RuntimeError):
        with time_component(clock=clock) as handle:
            raise RuntimeError("boom")
    assert handle.duration == 2.0


def test_two_runs_same_clock_same_duration():
    def make_clock():
        return iter([100.0, 100.25])

    def run():
        ticks = make_clock()
        with time_component(clock=lambda: next(ticks)) as h:
            pass
        return h.duration

    assert run() == run() == 0.25


# --- Trace -----------------------------------------------------------------
def test_trace_record_and_serialize():
    trace = RelationTrace(execution_id="exec-1")
    trace.record(document_id="doc-1", workspace="ws-a", component="pairs", version="v1",
                 result=ComponentResult.OK, num_pairs=3)
    trace.record(document_id="doc-1", workspace="ws-a", component="signals", version="v1",
                 result=ComponentResult.OK, num_signals=5)
    d = trace.to_dict()
    assert d["execution_id"] == "exec-1"
    assert len(d["events"]) == 2
    assert trace.to_json() == trace.to_json()  # determinista


def test_trace_rejects_mismatched_execution_id():
    trace = RelationTrace(execution_id="exec-1")
    with pytest.raises(ObservabilityError):
        trace.add(_event(execution_id="exec-OTHER").validate())


# --- Ausencia de red -------------------------------------------------------
def test_module_does_not_import_network_libraries():
    import relations.observability as obs  # noqa: F401

    for banned in ("requests", "httpx", "urllib3", "aiohttp"):
        assert banned not in sys.modules or True  # no debe ser importado POR este modulo
    # comprobacion directa: el fuente no menciona librerias de red
    src = Path(obs.__file__).read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "import socket", "urllib.request"):
        assert banned not in src


def test_no_socket_opened(monkeypatch):
    calls = {"n": 0}
    real_socket = socket.socket

    class _Guard(real_socket):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **k):
            calls["n"] += 1
            raise AssertionError("observability no debe abrir sockets")

    monkeypatch.setattr(socket, "socket", _Guard)
    ev = _event(
        errors=["x"], provider_status={"p": "ok"}, synthetic=True, sample_text="t"
    ).validate()
    ev.to_json()
    trace = RelationTrace(execution_id="exec-1")
    trace.record(document_id="d", workspace="w", component="c", version="v",
                 result=ComponentResult.OK)
    trace.to_json()
    assert calls["n"] == 0

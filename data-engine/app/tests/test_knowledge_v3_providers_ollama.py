# -*- coding: utf-8 -*-
"""Proveedor Ollama: unitarios con transporte simulado + humo real.

Los tests `live_ollama` estan DESACTIVADOS por defecto. Para ejecutarlos:

    S9K_LIVE_OLLAMA=1 pytest data-engine/app/tests/test_knowledge_v3_providers_ollama.py

Ollama es local (VM102, sin coste), asi que el humo real puede lanzarse sin
autorizacion presupuestaria; se mantiene desactivado igualmente porque el CI no
tiene ruta a la LAN.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error

import pytest

from external_processing.errors import (
    InputTooLargeError,
    InvalidResponseError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from external_processing.capabilities import Capability
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.providers.ollama import (
    DEFAULT_BASE_URL,
    OllamaProcessingProvider,
    ollama_config,
)

from tests.test_knowledge_v3_providers_support import (
    FakeResponse,
    FakeTransport,
    http_error,
    ollama_chat_response,
)

LIVE = os.environ.get("S9K_LIVE_OLLAMA", "").strip() == "1"
live_ollama = pytest.mark.skipif(not LIVE, reason="humo real: activar con S9K_LIVE_OLLAMA=1")


def _provider(script, **kw):
    return OllamaProcessingProvider(
        base_url="http://ollama.test:11434",
        model="qwen2.5:7b",
        max_retries=kw.pop("max_retries", 0),
        urlopen=FakeTransport(script),
        **kw,
    )


def _job(task=ExternalTaskType.TEXT_EXTRACT, payload=None, model=None):
    return ProcessingJob(
        batch_id="b",
        workspace="leyenda",
        source_id="s",
        task_type=task,
        payload=payload if payload is not None else {"text": "Daiki juro lealtad."},
        model=model,
    )


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------
def test_la_url_no_esta_cableada_se_lee_del_entorno(monkeypatch):
    """El defecto documentado sigue existiendo, pero el entorno manda."""
    monkeypatch.setenv("S9K_OLLAMA_BASE_URL", "http://otro:1234/")
    assert ollama_config()["base_url"] == "http://otro:1234"
    monkeypatch.delenv("S9K_OLLAMA_BASE_URL")
    assert ollama_config()["base_url"] == DEFAULT_BASE_URL


def test_el_modelo_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("S9K_OLLAMA_MODEL", "llama3.2:3b")
    assert OllamaProcessingProvider(urlopen=FakeTransport([{}])).model == "llama3.2:3b"


def test_embeddings_no_se_declara_sin_confirmacion_explicita():
    """El servidor real NO soporta embeddings: declararlo seria mentir."""
    provider = _provider([{}])
    assert Capability.GENERATE_EMBEDDINGS not in provider.capabilities
    assert Capability.EXTRACT_TEXT_ENTITIES in provider.capabilities


def test_embeddings_se_declara_si_se_activa():
    provider = _provider([{}], embeddings=True)
    assert Capability.GENERATE_EMBEDDINGS in provider.capabilities


def test_vision_se_declara_solo_con_modelo_de_vision():
    assert Capability.DESCRIBE_IMAGE not in _provider([{}]).capabilities
    assert Capability.DESCRIBE_IMAGE in _provider([{}], vision_model="llava:7b").capabilities


def test_las_capacidades_son_de_instancia_no_de_clase():
    """Activar embeddings en una instancia no puede contaminar a la siguiente."""
    _provider([{}], embeddings=True)
    assert Capability.GENERATE_EMBEDDINGS not in _provider([{}]).capabilities


# --------------------------------------------------------------------------
# Chat JSON estricto
# --------------------------------------------------------------------------
def test_chat_json_devuelve_el_objeto_parseado():
    provider = _provider([ollama_chat_response({"mentions": [{"surface": "Daiki"}]})])
    out = provider.chat_json([{"role": "user", "content": "hola"}])
    assert out["parsed"]["mentions"][0]["surface"] == "Daiki"
    assert out["model"] == "qwen2.5:7b"


def test_la_peticion_pide_json_temperatura_cero_y_sin_stream():
    transport = FakeTransport([ollama_chat_response({"ok": True})])
    provider = OllamaProcessingProvider(base_url="http://x:1", urlopen=transport, max_retries=0)
    provider.chat_json([{"role": "user", "content": "hola"}])
    body = transport.requests[0]["body"]
    assert body["format"] == "json"
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert transport.requests[0]["url"].endswith("/api/chat")


def test_contenido_que_no_es_json_estricto_falla():
    provider = _provider([ollama_chat_response("aqui tienes: {mentions: []}")])
    with pytest.raises(InvalidResponseError, match="JSON estricto"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_contenido_json_pero_no_objeto_falla():
    provider = _provider([ollama_chat_response("[1, 2, 3]")])
    with pytest.raises(InvalidResponseError, match="objeto JSON"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_mensaje_vacio_falla():
    provider = _provider([{"model": "qwen2.5:7b", "message": {"content": "  "}}])
    with pytest.raises(InvalidResponseError, match="sin contenido"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_error_declarado_por_ollama_falla():
    provider = _provider([{"error": "model not found"}])
    with pytest.raises(InvalidResponseError, match="model not found"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_respuesta_no_json_del_servidor_falla():
    provider = _provider([FakeResponse(None, raw=b"<html>502</html>")])
    with pytest.raises(InvalidResponseError, match="no es JSON"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_prompt_gigante_no_se_envia():
    transport = FakeTransport([ollama_chat_response({"ok": True})])
    provider = OllamaProcessingProvider(
        base_url="http://x:1", urlopen=transport, max_prompt_chars=100
    )
    with pytest.raises(InputTooLargeError):
        provider.chat_json([{"role": "user", "content": "x" * 500}])
    assert transport.calls == 0, "no debe salir un solo byte a la red"


def test_respuesta_gigante_se_corta_antes_de_parsear():
    enorme = json.dumps({"message": {"content": "{}"}, "relleno": "x" * 5000}).encode()
    provider = OllamaProcessingProvider(
        base_url="http://x:1",
        urlopen=FakeTransport([FakeResponse(None, raw=enorme)]),
        max_response_bytes=1000,
        max_retries=0,
    )
    with pytest.raises(InputTooLargeError):
        provider.chat_json([{"role": "user", "content": "hola"}])


# --------------------------------------------------------------------------
# Errores de red y reintentos
# --------------------------------------------------------------------------
def test_servidor_inalcanzable_es_provider_unavailable():
    provider = _provider([urllib.error.URLError("connection refused")])
    with pytest.raises(ProviderUnavailableError):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_http_404_es_permanente_no_se_reintenta():
    transport = FakeTransport([http_error(404)])
    provider = OllamaProcessingProvider(
        base_url="http://x:1", urlopen=transport, max_retries=3
    )
    with pytest.raises(UnsupportedCapabilityError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert transport.calls == 1


def test_reintenta_los_transitorios_y_acaba_acertando(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    transport = FakeTransport(
        [urllib.error.URLError("boom"), ollama_chat_response({"ok": True})]
    )
    provider = OllamaProcessingProvider(
        base_url="http://x:1", urlopen=transport, max_retries=2
    )
    assert provider.chat_json([{"role": "user", "content": "hola"}])["parsed"] == {"ok": True}
    assert transport.calls == 2


def test_agota_reintentos_y_lanza(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    transport = FakeTransport([http_error(500)])
    provider = OllamaProcessingProvider(
        base_url="http://x:1", urlopen=transport, max_retries=2
    )
    with pytest.raises(ProviderUnavailableError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert transport.calls == 3


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------
def test_embed_devuelve_vectores_y_dimension():
    provider = _provider([{"embeddings": [[0.1, 0.2, 0.3]]}], embeddings=True)
    out = provider.embed(["hola"])
    assert out["dimension"] == 3


def test_servidor_sin_embeddings_falla_explicitamente():
    """Mensaje REAL del servidor de la instalacion (192.168.1.157)."""
    provider = _provider(
        [{"error": "This server does not support embeddings. Start it with `--embeddings`"}],
        embeddings=True,
    )
    with pytest.raises(UnsupportedCapabilityError, match="embeddings"):
        provider.embed(["hola"])


def test_embed_con_vectores_no_numericos_falla():
    provider = _provider([{"embeddings": [["a", "b"]]}], embeddings=True)
    with pytest.raises(InvalidResponseError):
        provider.embed(["hola"])


def test_embed_sin_vectores_falla():
    provider = _provider([{"embeddings": []}], embeddings=True)
    with pytest.raises(InvalidResponseError):
        provider.embed(["hola"])


# --------------------------------------------------------------------------
# execute() y healthcheck
# --------------------------------------------------------------------------
def test_execute_envuelve_la_propuesta_con_proveedor_y_modelo():
    provider = _provider([ollama_chat_response({"mentions": []})])
    out = provider.execute(_job())
    assert out["provider"] == "ollama"
    assert out["model"] == "qwen2.5:7b"
    assert out["payload"] == {"mentions": []}


def test_execute_rechaza_capacidad_no_declarada():
    provider = _provider([{}])
    with pytest.raises(UnsupportedCapabilityError):
        provider.execute(_job(task=ExternalTaskType.TRANSCRIBE_AUDIO))


def test_execute_sin_texto_falla():
    provider = _provider([{}])
    with pytest.raises(InvalidResponseError, match="sin mensajes"):
        provider.execute(_job(payload={}))


def test_execute_no_devuelve_ningun_campo_de_decision():
    """§2: lo que sale de aqui no puede parecerse a una aprobacion."""
    from knowledge_v3.providers import assert_not_a_decision

    provider = _provider([ollama_chat_response({"mentions": []})])
    assert_not_a_decision(provider.execute(_job()))


def test_healthcheck_ok_cuando_el_modelo_esta_presente():
    provider = _provider([{"models": [{"name": "qwen2.5:7b"}]}])
    health = provider.healthcheck()
    assert health["status"] == "ok"
    assert health["model_present"] is True


def test_healthcheck_degraded_si_falta_el_modelo():
    provider = _provider([{"models": [{"name": "otro:1b"}]}])
    assert provider.healthcheck()["status"] == "degraded"


def test_healthcheck_no_lanza_si_el_servidor_esta_caido():
    provider = _provider([urllib.error.URLError("down")])
    assert provider.healthcheck()["status"] == "error"


# --------------------------------------------------------------------------
# Humo REAL contra 192.168.1.157:11434
# --------------------------------------------------------------------------
@live_ollama
def test_live_ollama_healthcheck():
    provider = OllamaProcessingProvider()
    health = provider.healthcheck()
    print(f"\n[live_ollama] healthcheck: {health}")
    assert health["status"] in ("ok", "degraded")
    assert health["models"], "el servidor no declara ningun modelo"


@live_ollama
def test_live_ollama_chat_json_devuelve_json_estricto():
    provider = OllamaProcessingProvider(timeout_seconds=300)
    t0 = time.monotonic()
    out = provider.chat_json(
        [
            {
                "role": "system",
                "content": (
                    "Eres un extractor. Devuelve SOLO JSON con la forma "
                    '{"mentions":[{"surface":str,"type":str,"confidence":num}]}'
                ),
            },
            {"role": "user", "content": "Daiki juro lealtad a la Casa del Ciervo en Umbra."},
        ]
    )
    elapsed = time.monotonic() - t0
    print(f"\n[live_ollama] chat_json en {elapsed:.2f}s -> {out['parsed']}")
    assert isinstance(out["parsed"], dict)


@live_ollama
def test_live_ollama_extremo_a_extremo_produce_propuestas_ancladas():
    """Cadena real: Ollama -> router -> guardas -> documentos V3 validados."""
    from knowledge_v3.providers import (
        ProviderRouter,
        Tier,
        V3Capability,
        mentions_from_extraction,
    )
    from tests.test_knowledge_v3_providers_support import (
        EPISODE_TEXT,
        make_anchor,
        make_attribution,
    )

    provider = OllamaProcessingProvider(timeout_seconds=300)
    router = ProviderRouter()
    router.register(provider, Tier.OLLAMA, cost_units=0.0)

    outcome = router.run(
        V3Capability.EXTRACTION,
        workspace="leyenda",
        source_id="asset:manual-001",
        payload={
            "system": (
                "Extrae menciones de entidad. Devuelve SOLO JSON: "
                '{"mentions":[{"surface":"<texto EXACTO del episodio>",'
                '"type":"Character|Location|Faction|Object|Event|Concept",'
                '"confidence":0.0}]}'
            ),
            "text": EPISODE_TEXT,
        },
        max_attempts=1,
    )
    print(f"\n[live_ollama] outcome ok={outcome.ok} latencia={outcome.latency_ms:.0f} ms")
    print(f"[live_ollama] result={outcome.result}")
    assert outcome.ok, outcome.error_message

    mentions, codes = mentions_from_extraction(
        make_anchor(),
        outcome.result["payload"],
        attribution=make_attribution(step=outcome.attribution_step(), model=outcome.model),
        evidence_fragment_ids=["fragment:p12:0"],
    )
    print(f"[live_ollama] {len(mentions)} menciones ancladas, codigos={codes}")
    for m in mentions:
        m.validate()
        assert EPISODE_TEXT[m.start:m.end] == m.surface

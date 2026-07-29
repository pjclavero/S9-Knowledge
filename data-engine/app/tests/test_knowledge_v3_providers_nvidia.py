# -*- coding: utf-8 -*-
"""Proveedor NVIDIA: unitarios con transporte simulado + humo real opcional.

Los tests `live_nvidia` estan DESACTIVADOS por defecto porque **cuestan
dinero**. Para ejecutarlos hace falta activarlos Y tener la key en el entorno:

    S9K_LIVE_NVIDIA=1 S9K_NVIDIA_API_KEY=... pytest ...

Ningun test de este fichero envia nada a la red sin ese interruptor: el
transporte va inyectado.
"""
from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path

import pytest

from external_processing.capabilities import Capability
from external_processing.errors import (
    AuthError,
    ContentBlockedError,
    InputTooLargeError,
    InvalidResponseError,
    ProviderUnavailableError,
    RateLimitError,
    UnsupportedCapabilityError,
)
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.providers.nvidia import (
    NVIDIA_IMPLEMENTED_CAPABILITIES,
    NvidiaProcessingProvider,
)

from tests.test_knowledge_v3_providers_support import (
    FakeResponse,
    FakeTransport,
    http_error,
    nvidia_chat_response,
)

LIVE = os.environ.get("S9K_LIVE_NVIDIA", "").strip() == "1"
live_nvidia = pytest.mark.skipif(
    not (LIVE and os.environ.get("S9K_NVIDIA_API_KEY")),
    reason="humo real de pago: activar con S9K_LIVE_NVIDIA=1 y S9K_NVIDIA_API_KEY",
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _provider(script, **kw):
    return NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-CLAVE-DE-LABORATORIO",
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
# La regresion que este bloque venia a corregir
# --------------------------------------------------------------------------
def test_execute_ya_no_lanza_not_implemented():
    """La fase B1 dejaba `NotImplementedError`. Ese era el defecto."""
    provider = _provider([nvidia_chat_response({"mentions": []})])
    out = provider.execute(_job())
    assert out["payload"] == {"mentions": []}


def test_rerank_sigue_sin_implementarse_y_se_declara_asi():
    """Honestidad: lo no verificado no se declara soportado."""
    assert Capability.RERANK not in NVIDIA_IMPLEMENTED_CAPABILITIES
    provider = _provider([{}])
    with pytest.raises(UnsupportedCapabilityError):
        provider.execute(_job(task=ExternalTaskType.RERANK))


def test_capacidades_implementadas_son_las_tres_esperadas():
    assert NVIDIA_IMPLEMENTED_CAPABILITIES == {
        Capability.EXTRACT_TEXT_ENTITIES,
        Capability.GENERATE_EMBEDDINGS,
        Capability.REVIEW_CANDIDATES,
    }


# --------------------------------------------------------------------------
# Contrato OpenAI-compatible
# --------------------------------------------------------------------------
def test_la_peticion_va_a_chat_completions_con_temperatura_cero():
    transport = FakeTransport([nvidia_chat_response({"ok": True})])
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=transport,
    )
    provider.chat_json([{"role": "user", "content": "hola"}])
    req = transport.requests[0]
    assert req["url"] == "https://nvidia.test/v1/chat/completions"
    assert req["body"]["temperature"] == 0
    assert req["body"]["stream"] is False
    assert req["body"]["response_format"] == {"type": "json_object"}


def test_la_autorizacion_va_en_bearer():
    transport = FakeTransport([nvidia_chat_response({"ok": True})])
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-SECRETA",
        urlopen=transport,
    )
    provider.chat_json([{"role": "user", "content": "hola"}])
    headers = {k.lower(): v for k, v in transport.requests[0]["headers"].items()}
    assert headers["authorization"] == "Bearer nvapi-SECRETA"


def test_si_el_modelo_no_admite_response_format_se_reintenta_sin_el():
    transport = FakeTransport([http_error(400), nvidia_chat_response({"ok": True})])
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=transport,
    )
    assert provider.chat_json([{"role": "user", "content": "hola"}])["parsed"] == {"ok": True}
    assert "response_format" not in transport.requests[1]["body"]


def test_un_400_sin_json_mode_no_se_reintenta_indefinidamente():
    transport = FakeTransport([http_error(400)])
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=transport,
    )
    with pytest.raises(UnsupportedCapabilityError):
        provider.chat_json([{"role": "user", "content": "hola"}], json_mode=False)
    assert transport.calls == 1


def test_estructura_inesperada_falla():
    provider = _provider([{"choices": []}])
    with pytest.raises(InvalidResponseError, match="estructura inesperada"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_contenido_que_no_es_json_estricto_falla():
    provider = _provider([nvidia_chat_response("Claro, aqui tienes: {a:1}")])
    with pytest.raises(InvalidResponseError, match="JSON estricto"):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_uso_de_tokens_se_propaga():
    provider = _provider([nvidia_chat_response({"ok": True})])
    out = provider.execute(_job())
    assert out["total_tokens"] == 59


# --------------------------------------------------------------------------
# Errores HTTP
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status,esperado", [(401, AuthError), (403, AuthError)])
def test_credenciales_rechazadas(status, esperado):
    provider = _provider([http_error(status)])
    with pytest.raises(esperado):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_rate_limit_lleva_retry_after():
    provider = _provider([http_error(429, headers={"Retry-After": "12"})])
    with pytest.raises(RateLimitError) as exc:
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert exc.value.retry_after == 12.0


def test_413_es_input_too_large():
    provider = _provider([http_error(413)])
    with pytest.raises(InputTooLargeError):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_500_es_proveedor_no_disponible():
    provider = _provider([http_error(500)])
    with pytest.raises(ProviderUnavailableError):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_red_caida_es_proveedor_no_disponible():
    provider = _provider([urllib.error.URLError("dns")])
    with pytest.raises(ProviderUnavailableError):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_sin_api_key_es_auth_error_y_no_sale_a_la_red():
    transport = FakeTransport([nvidia_chat_response({"ok": True})])

    def _sin_key():
        raise RuntimeError("S9K_NVIDIA_API_KEY ausente")

    provider = NvidiaProcessingProvider(
        REPO_ROOT, base_url="https://nvidia.test/v1", api_key_getter=_sin_key, urlopen=transport
    )
    with pytest.raises(AuthError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert transport.calls == 0


def test_respuesta_gigante_se_corta():
    enorme = json.dumps({"relleno": "x" * 5000}).encode()
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=FakeTransport([FakeResponse(None, raw=enorme)]),
        max_response_bytes=1000,
    )
    with pytest.raises(InputTooLargeError):
        provider.chat_json([{"role": "user", "content": "hola"}])


# --------------------------------------------------------------------------
# Secretos
# --------------------------------------------------------------------------
def test_ningun_mensaje_de_error_contiene_la_clave():
    """La key nunca puede acabar en un log, un traceback ni un job fallido."""
    clave = "nvapi-ESTA-NO-DEBE-SALIR-0123456789"
    for script in (http_error(401), http_error(500), urllib.error.URLError("x")):
        provider = NvidiaProcessingProvider(
            REPO_ROOT,
            base_url="https://nvidia.test/v1",
            api_key_getter=lambda: clave,
            urlopen=FakeTransport([script]),
        )
        with pytest.raises(Exception) as exc:
            provider.chat_json([{"role": "user", "content": "hola"}])
        texto = repr(exc.value) + str(exc.value)
        assert clave not in texto
        # Tampoco por la cadena de excepciones encadenadas.
        assert exc.value.__cause__ is None


def test_un_payload_con_credenciales_no_se_envia():
    transport = FakeTransport([nvidia_chat_response({"ok": True})])
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=transport,
    )
    with pytest.raises(ContentBlockedError):
        provider.execute(_job(payload={"text": "mi token es nvapi-abcdefghijklmnopqrs0123"}))
    assert transport.calls == 0, "no debe salir un solo byte a la red"


def test_la_key_no_aparece_en_el_healthcheck():
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-SECRETISIMA-0123456789",
        urlopen=FakeTransport([urllib.error.URLError("down")]),
    )
    health = provider.healthcheck()
    assert "nvapi" not in json.dumps(health)
    assert health["status"] == "error"


def test_healthcheck_ok_lista_modelos():
    provider = _provider([{"data": [{"id": "meta/llama-3.3-70b-instruct"}, {"id": "otro"}]}])
    health = provider.healthcheck()
    assert health["status"] == "ok"
    assert health["chat_model_present"] is True


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------
def test_embeddings_devuelve_vectores():
    provider = _provider([{"data": [{"embedding": [0.1, 0.2]}], "model": "nvidia/nv-embedqa-e5-v5"}])
    out = provider.embed(["hola"])
    assert out["dimension"] == 2


def test_embeddings_envia_input_type():
    transport = FakeTransport([{"data": [{"embedding": [0.1]}]}])
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=transport,
    )
    provider.embed(["hola"])
    assert transport.requests[0]["body"]["input_type"] == "passage"


def test_embeddings_sin_datos_falla():
    provider = _provider([{"data": []}])
    with pytest.raises(InvalidResponseError):
        provider.embed(["hola"])


# --------------------------------------------------------------------------
# Autoridad
# --------------------------------------------------------------------------
def test_lo_que_devuelve_nvidia_no_es_una_decision():
    from knowledge_v3.providers import assert_not_a_decision

    provider = _provider([nvidia_chat_response({"mentions": []})])
    assert_not_a_decision(provider.execute(_job()))


def test_el_router_declara_nvidia_como_external():
    from knowledge_v3.providers import ProviderRouter, Tier, V3Capability

    router = ProviderRouter()
    router.register(_provider([{}]), Tier.EXTERNAL)
    # Externo apagado por defecto: no hay ruta.
    assert not router.route(V3Capability.EXTRACTION).routed


# --------------------------------------------------------------------------
# Humo REAL (de pago)
# --------------------------------------------------------------------------
@live_nvidia
def test_live_nvidia_healthcheck():
    provider = NvidiaProcessingProvider(REPO_ROOT)
    health = provider.healthcheck()
    print(f"\n[live_nvidia] healthcheck: {health}")
    assert health["status"] == "ok"


@live_nvidia
def test_live_nvidia_chat_json():
    provider = NvidiaProcessingProvider(REPO_ROOT, timeout_seconds=120)
    out = provider.chat_json(
        [
            {"role": "system", "content": 'Devuelve SOLO JSON con la forma {"ok": true}'},
            {"role": "user", "content": "responde"},
        ],
        max_tokens=64,
    )
    print(f"\n[live_nvidia] modelo={out['model']} tokens={out['total_tokens']} -> {out['parsed']}")
    assert isinstance(out["parsed"], dict)

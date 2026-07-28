# -*- coding: utf-8 -*-
"""Puerto de inferencia AGNOSTICO del proveedor para el extractor semantico.

El extractor semantico (`semantic.py`) no sabe con quien habla. Recibe un
`ProviderPort` y le pide UNA cosa: "dado este sistema y este prompt, devuelveme
un objeto JSON". Todo lo demas —que ontologia va en el prompt, que forma tiene
la respuesta, que limites se aplican, que se valida localmente— vive fuera del
puerto y es identico para todos los adaptadores.

Por que importa: sin esta separacion, "el extractor semantico no funciona" y
"qwen2.5:7b no da para esto" son la MISMA frase y no se pueden distinguir. Con
ella, se cambia el adaptador y se vuelve a medir sin tocar una linea del
extractor. Es el unico experimento que responde la pregunta del bloque.

Adaptadores incluidos:

- `OllamaProviderPort`  -> `OllamaClient` (qwen2.5:7b, `S9K_OLLAMA_URL`);
- `NvidiaProviderPort`  -> `external_processing.providers.nvidia` (ya
  implementado y validado en vivo; la API key vive en el entorno, nunca aqui);
- `MockProviderPort`    -> respuestas guionizadas, para tests y para ensayar el
  prompt sin gastar una sola llamada.

Reglas del puerto:

1. **fail-closed**: cualquier fallo de transporte o de formato levanta
   `ProviderPortError`. El puerto JAMAS devuelve un payload adivinado;
2. **el puerto no interpreta**: valida que la respuesta sea un objeto JSON y
   nada mas. Anclar, tipar, filtrar por ontologia y decidir es del extractor;
3. **el puerto mide**: latencia, intentos y reintentos por JSON invalido salen
   en la respuesta. El rendimiento se REGISTRA, no se maquilla.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, Sequence

from ..contracts import Provider
from .ollama import OllamaJSONError, parse_strict_json
from .ollama_client import OllamaClient, OllamaConfig, OllamaError

#: Instruccion correctiva del reintento. Puramente sintactica: no aporta
#: contenido ni pistas sobre lo que "deberia" contestar el modelo.
JSON_RETRY_INSTRUCTION = (
    "\n\nLa respuesta anterior NO era un objeto JSON valido. Devuelve EXCLUSIVAMENTE "
    "el objeto JSON pedido, sin texto antes ni despues, sin markdown y sin comentarios."
)


class ProviderPortError(RuntimeError):
    """Fallo del puerto de inferencia. Nunca acompanado de datos utilizables."""


class ProviderUnavailable(ProviderPortError):
    """No se pudo hablar con el proveedor (red, timeout, autenticacion, 5xx)."""


class ProviderBadJSON(ProviderPortError):
    """El proveedor contesto, pero no con un objeto JSON."""


@dataclass(frozen=True)
class ProviderRequest:
    """Peticion al puerto. `purpose` solo sirve para trazar y medir."""

    system: str
    prompt: str
    max_tokens: int = 2048
    purpose: str = "extraction"


@dataclass(frozen=True)
class ProviderReply:
    """Respuesta del puerto, con su coste real medido."""

    payload: dict
    model: str
    provider: str
    latency_ms: int
    attempts: int = 1
    json_retries: int = 0
    usage: dict = field(default_factory=dict)

    def to_metrics(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "json_retries": self.json_retries,
            **{k: v for k, v in self.usage.items() if isinstance(v, (int, float))},
        }


class ProviderPort(Protocol):
    """Contrato minimo que cumple cualquier adaptador de inferencia."""

    #: Nombre corto y estable del adaptador (va a `provider_trace.name`).
    name: str
    #: Clase de proveedor del contrato congelado.
    provider: Provider
    #: Modelo efectivo (va a `provider_trace.model`; nunca se inventa).
    model: str

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        """Devuelve un objeto JSON o levanta `ProviderPortError`."""
        ...


def _parse_or_raise(text: str) -> dict:
    try:
        return parse_strict_json(text)
    except OllamaJSONError as exc:
        raise ProviderBadJSON(str(exc)) from None


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------
class OllamaProviderPort:
    """Adaptador Ollama. Un reintento por JSON invalido, ninguno por contenido."""

    provider = Provider.OLLAMA

    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        *,
        config: Optional[OllamaConfig] = None,
        json_retries: int = 1,
    ) -> None:
        self.client = client or OllamaClient(config=config)
        self.json_retries = max(0, int(json_retries))
        self.name = "s9k.extraction.port.ollama"
        self.model = self.client.config.model

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        last: Optional[Exception] = None
        started = time.monotonic()
        attempts = 0
        for retry in range(self.json_retries + 1):
            prompt = request.prompt if retry == 0 else request.prompt + JSON_RETRY_INSTRUCTION
            try:
                response = self.client.generate(
                    prompt, system=request.system, num_predict=request.max_tokens
                )
            except OllamaError as exc:
                raise ProviderUnavailable(str(exc)) from None
            attempts += response.attempts
            try:
                payload = _parse_or_raise(response.text)
            except ProviderBadJSON as exc:
                last = exc
                continue
            return ProviderReply(
                payload=payload,
                model=response.model,
                provider=self.provider.value,
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempts,
                json_retries=retry,
            )
        raise ProviderBadJSON(str(last or "sin respuesta JSON"))


# --------------------------------------------------------------------------
# NVIDIA
# --------------------------------------------------------------------------
#: Modelo por defecto del carril externo. Es el que la calibracion midio en
#: vivo (docs/42, docs/50); no se cambia sin volver a medir.
DEFAULT_NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"


class NvidiaProviderPort:
    """Adaptador NVIDIA NIM sobre `NvidiaProcessingProvider.chat_json`.

    No reimplementa transporte, ni autenticacion, ni saneado de secretos: todo
    eso ya existe y esta probado en `external_processing/providers/nvidia.py`.
    Aqui solo se traduce `ProviderRequest` a mensajes y la salida a
    `ProviderReply`.
    """

    provider = Provider.EXTERNAL

    def __init__(
        self,
        client: Any = None,
        *,
        repo_root: Optional[str] = None,
        model: str = DEFAULT_NVIDIA_MODEL,
        json_retries: int = 1,
    ) -> None:
        self._client = client
        self._repo_root = repo_root
        self.model = model
        self.json_retries = max(0, int(json_retries))
        self.name = "s9k.extraction.port.nvidia"

    @property
    def client(self) -> Any:
        """Construccion perezosa: importar NVIDIA no puede costar nada si no se usa."""
        if self._client is None:
            from pathlib import Path

            from external_processing.providers.nvidia import NvidiaProcessingProvider

            root = self._repo_root or os.environ.get("S9K_REPO_ROOT") or "."
            self._client = NvidiaProcessingProvider(Path(root), chat_model=self.model)
        return self._client

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        messages = [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.prompt},
        ]
        started = time.monotonic()
        last: Optional[Exception] = None
        for retry in range(self.json_retries + 1):
            if retry:
                messages[-1] = {
                    "role": "user",
                    "content": request.prompt + JSON_RETRY_INSTRUCTION,
                }
            try:
                out = self.client.chat_json(
                    messages, model=self.model, max_tokens=request.max_tokens
                )
            except Exception as exc:  # noqa: BLE001 - la familia real vive en external_processing
                name = type(exc).__name__
                if name in ("InvalidResponseError",):
                    last = ProviderBadJSON(name)
                    continue
                raise ProviderUnavailable(f"{name}") from None
            payload = out.get("parsed")
            if not isinstance(payload, dict):
                last = ProviderBadJSON("la respuesta no es un objeto JSON")
                continue
            return ProviderReply(
                payload=payload,
                model=str(out.get("model") or self.model),
                provider=self.provider.value,
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=retry + 1,
                json_retries=retry,
                usage={
                    "prompt_tokens": out.get("prompt_tokens", 0),
                    "completion_tokens": out.get("completion_tokens", 0),
                    "total_tokens": out.get("total_tokens", 0),
                },
            )
        raise ProviderBadJSON(str(last or "sin respuesta JSON"))


# --------------------------------------------------------------------------
# Mock
# --------------------------------------------------------------------------
class MockProviderPort:
    """Puerto guionizado: devuelve respuestas preparadas y GUARDA los prompts.

    Existe para dos cosas legitimas: los tests (que no tocan la red) y ensayar
    el prompt real sin gastar llamadas. Lo que NO hace es aparecer en una
    medicion disfrazado de proveedor: su `provider` es `local` y su modelo se
    llama `mock`, asi que cualquier informe que lo use lo dice en la traza.
    """

    provider = Provider.LOCAL

    def __init__(
        self,
        responses: Sequence[Any] = (),
        *,
        model: str = "mock",
        handler: Optional[Callable[[ProviderRequest], Any]] = None,
        latency_ms: int = 0,
    ) -> None:
        self._responses = list(responses)
        self._handler = handler
        self.model = model
        self.name = "s9k.extraction.port.mock"
        self.latency_ms = int(latency_ms)
        self.requests: list[ProviderRequest] = []

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        if self._handler is not None:
            item = self._handler(request)
        elif self._responses:
            item = self._responses.pop(0)
        else:
            item = {"mentions": [], "claims": [], "abstentions": []}
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            item = _parse_or_raise(item)
        if not isinstance(item, dict):
            raise ProviderBadJSON(f"respuesta guionizada de tipo {type(item).__name__}")
        return ProviderReply(
            payload=json.loads(json.dumps(item)),
            model=self.model,
            provider=self.provider.value,
            latency_ms=self.latency_ms,
            attempts=1,
        )


__all__ = [
    "DEFAULT_NVIDIA_MODEL",
    "JSON_RETRY_INSTRUCTION",
    "MockProviderPort",
    "NvidiaProviderPort",
    "OllamaProviderPort",
    "ProviderBadJSON",
    "ProviderPort",
    "ProviderPortError",
    "ProviderReply",
    "ProviderRequest",
    "ProviderUnavailable",
]

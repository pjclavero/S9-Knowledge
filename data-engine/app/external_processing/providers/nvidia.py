# -*- coding: utf-8 -*-
"""Adaptador NVIDIA para procesamiento externo — implementacion REAL.

Historia: en la fase B1 este `execute()` terminaba siempre en
`NotImplementedError` ("Fase B2 pendiente"). La auditoria V3
(docs/v3/00-audit-current-system.md §5.4 y D3) lo dejo por escrito: la clave
existe, la configuracion existe, y el proveedor era **inerte**. Aqui deja de
serlo.

Que hace de verdad
------------------
* `EXTRACT_TEXT_ENTITIES` y `REVIEW_CANDIDATES` -> `POST /chat/completions`
  (contrato OpenAI-compatible, el mismo que ya usa `external_ai`), con
  temperatura 0 y JSON estricto.
* `GENERATE_EMBEDDINGS` -> `POST /embeddings`.
* `RERANK` -> **no implementado**. El reranking de NIM no es OpenAI-compatible
  (`/ranking`, esquema propio) y no se ha verificado contra el endpoint real:
  declararlo seria repetir exactamente el error que esta clase venia a
  corregir. Lanza `UnsupportedCapabilityError`, que el dispatcher trata como
  permanente y no reintenta.

Seguridad
---------
* La API key se obtiene por demanda de `external_ai.registry.get_api_key()` y
  **nunca** se guarda como atributo, ni se serializa, ni aparece en un error:
  todas las excepciones de este modulo se construyen con texto propio y se
  lanzan con `from None` para no arrastrar la cabecera original.
* El payload pasa por `sanitize_request` + `assert_no_secrets` ANTES de salir a
  la red.
* La respuesta es un DATO: se parsea, no se ejecuta ni se interpreta como
  instruccion.

Nunca escribe en Neo4j. Nunca produce contratos aprobados: solo propuestas.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from external_processing.capabilities import Capability
from external_processing.errors import (
    AuthError,
    ContentBlockedError,
    InputTooLargeError,
    InvalidResponseError,
    ProviderUnavailableError,
    RateLimitError,
    TimeoutError,
    UnsupportedCapabilityError,
)
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.provider import ExternalProcessingProvider

#: Capacidades IMPLEMENTADAS contra endpoints reales. Es un conjunto distinto
#: de `NVIDIA_VERIFIED_CAPABILITIES` a proposito: aquel declara lo que se midio
#: en la calibracion (docs/42, docs/50), este declara lo que este adaptador
#: sabe ejecutar hoy. RERANK esta en el primero y no en el segundo.
NVIDIA_IMPLEMENTED_CAPABILITIES: Set[Capability] = {
    Capability.EXTRACT_TEXT_ENTITIES,
    Capability.GENERATE_EMBEDDINGS,
    Capability.REVIEW_CANDIDATES,
}

DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MiB
DEFAULT_CHAT_MODEL = "meta/llama-3.3-70b-instruct"
DEFAULT_EMBEDDING_MODEL = "nvidia/nv-embedqa-e5-v5"

_TASK_TO_CAP: Dict[ExternalTaskType, Capability] = {
    ExternalTaskType.TEXT_EXTRACT: Capability.EXTRACT_TEXT_ENTITIES,
    ExternalTaskType.EMBEDDINGS: Capability.GENERATE_EMBEDDINGS,
    ExternalTaskType.RERANK: Capability.RERANK,
    ExternalTaskType.REVIEW: Capability.REVIEW_CANDIDATES,
}


class NvidiaProcessingProvider(ExternalProcessingProvider):
    """Adaptador NVIDIA NIM (OpenAI-compatible) para `external_processing`."""

    provider_name: str = "nvidia"
    capabilities: Set[Capability] = set(NVIDIA_IMPLEMENTED_CAPABILITIES)

    def __init__(
        self,
        repo_root: Path,
        *,
        base_url: Optional[str] = None,
        api_key_getter=None,
        timeout_seconds: Optional[int] = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        chat_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        urlopen=None,
    ) -> None:
        self._repo_root = Path(repo_root)
        self._max_response_bytes = max_response_bytes
        # Transporte inyectable: los tests unitarios NO tocan la red ni
        # necesitan una API key real.
        self._urlopen = urlopen or urllib.request.urlopen

        cfg: Dict[str, Any] = {}
        try:
            from external_ai import registry

            cfg = registry.nvidia_config()
            self._api_key_getter = api_key_getter or registry.get_api_key
        except Exception:  # noqa: BLE001 - sin external_ai el proveedor sigue construyendose
            self._api_key_getter = api_key_getter or _no_key

        self.base_url = (
            base_url or cfg.get("base_url") or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or int(cfg.get("timeout_seconds") or 180)
        self.chat_model = chat_model or DEFAULT_CHAT_MODEL
        self.embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
        self.capabilities = set(NVIDIA_IMPLEMENTED_CAPABILITIES)

    # -- Capa HTTP ---------------------------------------------------------
    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST autenticado. Un solo intento: el dispatcher gestiona reintentos."""
        url = f"{self.base_url}{path}"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            api_key = self._api_key_getter()
        except Exception as exc:  # noqa: BLE001 - el texto del error nunca lleva la key
            raise AuthError(
                f"no hay API key de NVIDIA disponible ({type(exc).__name__})"
            ) from None

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with self._urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read(self._max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise _map_http_error(exc) from None
        except (socket.timeout, TimeoutError):
            raise TimeoutError(f"timeout contra NVIDIA tras {self.timeout_seconds}s") from None
        except urllib.error.URLError as exc:
            reason = type(getattr(exc, "reason", exc)).__name__
            raise ProviderUnavailableError(f"NVIDIA inalcanzable ({reason})") from None

        if len(raw) > self._max_response_bytes:
            raise InputTooLargeError(
                f"respuesta de NVIDIA por encima del tope ({self._max_response_bytes} bytes)"
            )
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(f"NVIDIA devolvio algo que no es JSON: {exc}") from None

    # -- Operaciones -------------------------------------------------------
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        json_mode: bool = True,
    ) -> Dict[str, Any]:
        """Chat completions con salida JSON estricta.

        Si el modelo no admite `response_format` (400), se reintenta UNA vez
        sin el: el catalogo de NIM es heterogeneo y la alternativa seria no
        poder usar la mitad de los modelos.
        """
        used_model = model or self.chat_model
        body: Dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": 0,
            "top_p": 1,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            response = self._post("/chat/completions", body)
        except UnsupportedCapabilityError:
            if not json_mode:
                raise
            body.pop("response_format", None)
            response = self._post("/chat/completions", body)

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidResponseError(
                f"estructura inesperada en la respuesta de NVIDIA: {exc}"
            ) from None
        if not isinstance(content, str) or not content.strip():
            raise InvalidResponseError("NVIDIA devolvio un mensaje sin contenido")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(
                f"el contenido del modelo no es JSON estricto: {exc}"
            ) from None
        if not isinstance(parsed, dict):
            raise InvalidResponseError(
                f"se esperaba un objeto JSON y llego {type(parsed).__name__}"
            )

        usage = response.get("usage") or {}
        return {
            "parsed": parsed,
            "model": response.get("model") or used_model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "finish_reason": (response["choices"][0] or {}).get("finish_reason"),
        }

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        input_type: str = "passage",
    ) -> Dict[str, Any]:
        """Embeddings via `/embeddings`. `input_type` lo exigen los NV-Embed."""
        used_model = model or self.embedding_model
        response = self._post(
            "/embeddings",
            {
                "model": used_model,
                "input": list(texts),
                "encoding_format": "float",
                "input_type": input_type,
                "truncate": "END",
            },
        )
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise InvalidResponseError("respuesta de embeddings sin datos")
        vectors = []
        for item in data:
            vec = (item or {}).get("embedding")
            if not isinstance(vec, list) or not all(isinstance(x, (int, float)) for x in vec):
                raise InvalidResponseError("vector de embedding con elementos no numericos")
            vectors.append(vec)
        return {
            "embeddings": vectors,
            "model": response.get("model") or used_model,
            "dimension": len(vectors[0]),
        }

    # -- Contrato ExternalProcessingProvider -------------------------------
    def execute(self, job: ProcessingJob) -> Dict[str, Any]:
        """Ejecuta el job contra la API real. El resultado es una PROPUESTA."""
        cap = _TASK_TO_CAP.get(job.task_type)
        if cap is None or cap not in self.capabilities:
            raise UnsupportedCapabilityError(str(job.task_type.value), self.provider_name)

        payload = job.payload or {}

        # Guarda de secretos ANTES de que salga un solo byte a la red.
        self._assert_safe_to_send(payload)

        if cap is Capability.GENERATE_EMBEDDINGS:
            texts = payload.get("texts") or ([payload["text"]] if payload.get("text") else [])
            if not texts:
                raise InvalidResponseError("job de embeddings sin textos")
            out = self.embed(texts, model=job.model)
            return {
                "provider": self.provider_name,
                "model": out["model"],
                "embeddings": out["embeddings"],
                "dimension": out["dimension"],
            }

        messages = payload.get("messages")
        if not messages:
            system = payload.get("system") or ""
            user = payload.get("text") or payload.get("prompt") or ""
            if not user:
                raise InvalidResponseError("job sin mensajes ni texto")
            messages = ([{"role": "system", "content": system}] if system else []) + [
                {"role": "user", "content": user}
            ]

        out = self.chat_json(messages, model=job.model)
        return {
            "provider": self.provider_name,
            "model": out["model"],
            "payload": out["parsed"],
            "prompt_tokens": out["prompt_tokens"],
            "completion_tokens": out["completion_tokens"],
            "total_tokens": out["total_tokens"],
        }

    def _assert_safe_to_send(self, payload: dict) -> None:
        """Sanitiza y bloquea el envio si hay credenciales. Fail-closed."""
        try:
            from external_ai.security import assert_no_secrets, sanitize_request
        except Exception:  # noqa: BLE001
            raise ContentBlockedError(
                "guardas de seguridad de external_ai no disponibles; envio bloqueado"
            ) from None
        try:
            sanitized = sanitize_request(dict(payload), self._repo_root)
        except Exception as exc:  # noqa: BLE001
            raise ContentBlockedError(
                f"sanitizacion fallida ({type(exc).__name__}); envio bloqueado"
            ) from None
        try:
            assert_no_secrets(sanitized)
        except Exception as exc:  # noqa: BLE001
            raise ContentBlockedError(
                f"el payload contiene posibles credenciales ({type(exc).__name__}); "
                "envio bloqueado"
            ) from None

    def healthcheck(self) -> Dict[str, Any]:
        """`GET /models`. No lanza y no revela nunca la key."""
        url = f"{self.base_url}/models"
        t0 = time.monotonic()
        try:
            api_key = self._api_key_getter()
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "provider": self.provider_name,
                "base_url": self.base_url,
                "error": f"sin API key ({type(exc).__name__})",
            }
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {api_key}"}, method="GET"
        )
        try:
            with self._urlopen(req, timeout=min(self.timeout_seconds, 30)) as resp:
                raw = resp.read(self._max_response_bytes + 1)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            return {
                "status": "ok",
                "provider": self.provider_name,
                "base_url": self.base_url,
                "models_available": len(ids),
                "chat_model_present": self.chat_model in ids,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "capabilities": sorted(c.value for c in self.capabilities),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "provider": self.provider_name,
                "base_url": self.base_url,
                "error": type(exc).__name__,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }


def _no_key() -> str:
    raise AuthError("S9K_NVIDIA_API_KEY ausente en el entorno")


def _map_http_error(exc: urllib.error.HTTPError):
    """Traduce el status HTTP a un error del subsistema. Nunca incluye la key."""
    status = getattr(exc, "code", 0)
    if status in (401, 403):
        return AuthError(f"NVIDIA rechazo la autenticacion (HTTP {status})")
    if status == 429:
        try:
            retry_after = float(exc.headers.get("Retry-After", "0") or 0)
        except (AttributeError, TypeError, ValueError):
            retry_after = 0.0
        return RateLimitError("NVIDIA: rate limit (HTTP 429)", retry_after=retry_after)
    if status in (400, 404, 422):
        return UnsupportedCapabilityError(f"HTTP {status}", "nvidia")
    if status == 413:
        return InputTooLargeError("NVIDIA: payload demasiado grande (HTTP 413)")
    return ProviderUnavailableError(f"NVIDIA HTTP {status}")

# -*- coding: utf-8 -*-
"""Proveedor genérico OpenAI-compatible para el subsistema de IA externa (Fase A).

Implementa la lógica HTTP reutilizable (reintentos, backoff exponencial, caché,
seguridad) que heredan todos los proveedores OpenAI-compatible (NVIDIA NIM, etc.).

Nunca escribe en Neo4j. Nunca expone la API key en respuestas, logs ni excepciones.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from external_ai.base import ExternalAIProvider
from external_ai.cache import ResponseCache, cache_key, sha256_text
from external_ai.errors import (
    ExternalAIError,
    InvalidResponseError,
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderServerError,
    ProviderTimeoutError,
    RateLimitError,
    SecretLeakError,
    classify_http_status,
)
from external_ai.models import (
    ModelReviewResponse,
    ProviderHealth,
    ReviewBatchRequest,
    TokenUsage,
)


class OpenAICompatibleProvider(ExternalAIProvider):
    """Proveedor HTTP genérico compatible con la API de chat/completions de OpenAI.

    Admite reintentos con backoff exponencial para errores de red, rate-limit y
    errores de servidor. Los errores de autenticación (401/403) y de recurso no
    encontrado (404) no se reintentan.

    La API key NUNCA se almacena como atributo de instancia; se obtiene llamando
    a ``api_key_getter()`` en el momento del envío.
    """

    provider_name: str = "openai_compatible"
    capabilities: set = {"candidate_review", "candidate_adjudication"}

    def __init__(
        self,
        base_url: str,
        api_key_getter: Callable[[], str],
        repo_root: Path,
        timeout: int = 180,
        max_retries: int = 3,
        max_concurrency: int = 2,
        cache_enabled: Optional[bool] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key_getter = api_key_getter
        self._repo_root = Path(repo_root)
        self.timeout = timeout
        self.max_retries = max_retries
        self._semaphore = threading.Semaphore(max_concurrency)
        self._cache = ResponseCache(self._repo_root, enabled=cache_enabled)

    # ------------------------------------------------------------------
    # Capa HTTP privada
    # ------------------------------------------------------------------

    def _post_chat(self, model: str, messages: list) -> tuple[dict, int]:
        """Envía una petición POST a /chat/completions y devuelve (parsed_json, latency_ms).

        Reintenta en caso de RateLimitError, ProviderServerError y
        ProviderTimeoutError con backoff exponencial (1 s, 2 s, 4 s, …, máx 60 s).
        Lanza inmediatamente en 401/403/404.
        """
        url = f"{self._base_url}/chat/completions"
        body_dict = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        body_bytes = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

        last_error: Optional[ExternalAIError] = None
        attempts = self.max_retries + 1

        for attempt in range(attempts):
            # Obtener la key en cada intento (por si rota el entorno).
            api_key = self._api_key_getter()
            req = urllib.request.Request(
                url,
                data=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )

            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                latency_ms = int((time.monotonic() - t0) * 1000)
                try:
                    return json.loads(raw), latency_ms
                except json.JSONDecodeError as exc:
                    raise InvalidResponseError(
                        f"Respuesta no es JSON válido: {exc}"
                    ) from exc

            except urllib.error.HTTPError as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                try:
                    body_text = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body_text = ""
                mapped = classify_http_status(exc.code, body_text)

                # Sin reintento para errores de autenticación/recurso.
                if isinstance(mapped, (ProviderAuthError, ProviderNotFoundError)):
                    raise mapped from exc

                last_error = mapped

            except (socket.timeout, urllib.error.URLError) as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                last_error = ProviderTimeoutError(
                    f"Timeout/red al contactar {self._base_url}: {type(exc).__name__}"
                )

            # Backoff exponencial solo si quedan reintentos.
            if attempt < attempts - 1:
                wait = min(2 ** attempt, 60)
                time.sleep(wait)

        # Se agotaron los reintentos.
        raise last_error  # type: ignore[misc]

    def _get_models(self) -> tuple[list[str], int]:
        """Hace GET /models y devuelve (lista_ids, latency_ms). Puede lanzar."""
        url = f"{self._base_url}/models"
        api_key = self._api_key_getter()
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        latency_ms = int((time.monotonic() - t0) * 1000)
        data = json.loads(raw)
        ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        return ids, latency_ms

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def healthcheck(self) -> ProviderHealth:
        """Comprueba conectividad listando /models. Nunca lanza; devuelve ProviderHealth."""
        t0 = time.monotonic()
        try:
            ids, latency_ms = self._get_models()
            return ProviderHealth(
                provider=self.provider_name,
                ok=True,
                models_available=ids,
                latency_ms=latency_ms,
            )
        except ProviderAuthError:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return ProviderHealth(
                provider=self.provider_name,
                ok=False,
                detail="Autenticación rechazada (401/403)",
                latency_ms=latency_ms,
            )
        except ProviderNotFoundError:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return ProviderHealth(
                provider=self.provider_name,
                ok=False,
                detail="Endpoint /models no encontrado (404)",
                latency_ms=latency_ms,
            )
        except (socket.timeout, urllib.error.URLError):
            latency_ms = int((time.monotonic() - t0) * 1000)
            return ProviderHealth(
                provider=self.provider_name,
                ok=False,
                detail="Timeout o error de red al contactar el proveedor",
                latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - t0) * 1000)
            # Sanitizamos: nunca incluir detalles que puedan contener la key.
            return ProviderHealth(
                provider=self.provider_name,
                ok=False,
                detail=f"Error inesperado: {type(exc).__name__}",
                latency_ms=latency_ms,
            )

    def review_candidates(
        self,
        request: ReviewBatchRequest,
        model: str,
        reviewer_role: str = "reviewer_a",
    ) -> ModelReviewResponse:
        """Envía el lote al modelo y devuelve la revisión validada.

        Flujo:
        1. Construir clave de caché y buscar hit.
        2. Construir mensajes (import perezoso de prompts).
        3. Asegurar ausencia de secretos en el payload (bloquea si los hay).
        4. Adquirir semáforo → _post_chat → liberar semáforo.
        5. Parsear respuesta (import perezoso de response_parser).
        6. Guardar en caché y devolver ModelReviewResponse.
        """
        from external_ai import prompts  # import perezoso

        # --- Hashes para la clave de caché ---
        segment_hash = sha256_text(
            "".join(item.segment_text for item in request.items)
        )
        glossary_snapshot_hash = sha256_text(",".join(request.glossary))

        ck = cache_key(
            provider=self.provider_name,
            model=model,
            prompt_version=request.prompt_version,
            workspace=request.workspace,
            candidate_id="__batch__",
            segment_hash=segment_hash,
            schema_version=request.schema_version,
            glossary_snapshot_hash=glossary_snapshot_hash,
        )

        # --- Consultar caché ---
        cached = self._cache.get(ck)
        if cached is not None:
            raw_text_cached = cached.get("raw_response", "")
            from external_ai import response_parser  # import perezoso
            response = response_parser.parse_review_response(
                raw_text_cached, request, self.provider_name, model, reviewer_role
            )
            response.latency_ms = cached.get("latency_ms", 0)
            return response

        # --- Construir mensajes ---
        messages = prompts.build_review_prompt(request, model)

        # --- Guardia de seguridad (ANTES de cualquier envío de red) ---
        sanitized_request_dict = _sanitize_request_safe(request.to_dict())
        _assert_no_secrets_safe(sanitized_request_dict)
        _assert_no_secrets_safe(messages)

        # --- Envío con control de concurrencia ---
        self._semaphore.acquire()
        try:
            response_json, latency_ms = self._post_chat(model, messages)
        finally:
            self._semaphore.release()

        # --- Extraer texto y uso de tokens ---
        try:
            raw_text = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidResponseError(
                f"Estructura inesperada en la respuesta del modelo: {exc}"
            ) from exc

        usage_dict = response_json.get("usage") or {}
        token_usage = TokenUsage(
            prompt_tokens=usage_dict.get("prompt_tokens", 0),
            completion_tokens=usage_dict.get("completion_tokens", 0),
            total_tokens=usage_dict.get("total_tokens", 0),
        )

        # --- Parsear respuesta ---
        from external_ai import response_parser  # import perezoso
        response = response_parser.parse_review_response(
            raw_text, request, self.provider_name, model, reviewer_role
        )

        # --- Enriquecer con metadatos ---
        response.latency_ms = latency_ms
        response.token_usage = token_usage
        response.request_hash = sha256_text(json.dumps(messages, ensure_ascii=False))
        response.response_hash = sha256_text(raw_text)

        # --- Persistir en caché ---
        self._cache.put(
            key=ck,
            raw_response=raw_text,
            normalized=response.to_dict(),
            latency_ms=latency_ms,
        )

        return response


# ---------------------------------------------------------------------------
# Helpers internos (no exponen la API key en ningún caso)
# ---------------------------------------------------------------------------

def _sanitize_request_safe(obj: dict) -> dict:
    """Llama a security.sanitize_request; si falla, relanza SecretLeakError."""
    from external_ai.security import sanitize_request
    return sanitize_request(obj)


def _assert_no_secrets_safe(obj) -> None:
    """Llama a security.assert_no_secrets; si detecta secretos, relanza."""
    from external_ai.security import assert_no_secrets
    assert_no_secrets(obj)

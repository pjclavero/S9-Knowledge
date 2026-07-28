# -*- coding: utf-8 -*-
"""Proveedor Ollama de primera clase para procesamiento (V3).

Ollama es el proveedor LOCAL principal del rediseno V3: propone, razona y
clasifica, pero NO aprueba, NO firma y NO escribe. Este modulo implementa el
contrato `ExternalProcessingProvider` para que el `BurstDispatcher` ya existente
(concurrencia, backoff, circuit breaker) lo despache sin cambios.

Por que existe otro cliente Ollama teniendo ya dos
--------------------------------------------------
La auditoria (docs/v3/00-audit-current-system.md §5.3 y §8) documenta que hoy
hay dos rutas Ollama independientes y ninguna registrada como proveedor:

  * `review/llm_extractor.py` — API nativa, **IP cableada en el codigo**;
  * `relations/local_llm_shadow.py` — OpenAI-compatible, sin default.

Este modulo unifica ambas ideas en UN proveedor: configuracion por entorno (sin
IP cableada), API nativa de Ollama (`/api/chat`, `/api/embed`, `/api/tags`),
salida JSON estricta y fail-closed. No modifica ni sustituye a los otros dos:
son frontera de otros bloques.

Dependencias: solo la biblioteca estandar (`urllib`). `requests` NO esta en
`data-engine/requirements.in` y este modulo no lo introduce.

Nunca escribe en Neo4j. Nunca ejecuta ni interpreta como instruccion el
contenido devuelto por el modelo: es un DATO.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set

from external_processing.capabilities import Capability
from external_processing.http_safe import read_bounded, safe_urlopen
from external_processing.errors import (
    InputTooLargeError,
    InvalidResponseError,
    ProviderUnavailableError,
    TimeoutError,
    UnsupportedCapabilityError,
)
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.provider import ExternalProcessingProvider

#: Endpoint por defecto. Es la VM102 `ia-server` documentada en la auditoria.
#: Se puede sobreescribir con `S9K_OLLAMA_BASE_URL`; nunca se cablea en el
#: codigo llamante.
DEFAULT_BASE_URL = "http://192.168.1.157:11434"
DEFAULT_MODEL = "qwen2.5:7b"

#: Tope duro de bytes de respuesta. Una respuesta gigante es un vector de
#: agotamiento de memoria, no un resultado util: se corta ANTES de parsear.
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB

#: Tope duro del prompt enviado. Evita mandar un episodio entero por accidente.
DEFAULT_MAX_PROMPT_CHARS = 200_000

#: Capacidades que este proveedor implementa DE VERDAD contra la API nativa.
#: `GENERATE_EMBEDDINGS` esta implementada pero NO se declara por defecto: el
#: servidor real de la instalacion (192.168.1.157) responde
#: "This server does not support embeddings", de modo que declararla seria
#: mentir. Se activa explicitamente con `embeddings=True` cuando el servidor
#: arranque con `--embeddings` o sirva un modelo de embeddings.
OLLAMA_BASE_CAPABILITIES: Set[Capability] = {
    Capability.EXTRACT_TEXT_ENTITIES,
    Capability.REVIEW_CANDIDATES,
}

#: Estados HTTP que NO tiene sentido reintentar. `501 Not Implemented` es el
#: que devuelve de verdad el servidor de la instalacion cuando se le piden
#: embeddings sin `--embeddings`: no es un fallo transitorio, es una capacidad
#: que ese binario no sirve.
PERMANENT_HTTP_STATUS: frozenset = frozenset({400, 404, 405, 422, 501})

_TASK_TO_CAP: Dict[ExternalTaskType, Capability] = {
    ExternalTaskType.TEXT_EXTRACT: Capability.EXTRACT_TEXT_ENTITIES,
    ExternalTaskType.REVIEW: Capability.REVIEW_CANDIDATES,
    ExternalTaskType.EMBEDDINGS: Capability.GENERATE_EMBEDDINGS,
    ExternalTaskType.IMAGE_ANALYSIS: Capability.DESCRIBE_IMAGE,
}


def ollama_config() -> Dict[str, Any]:
    """Configuracion desde entorno. Sin secretos: Ollama local no usa API key."""

    def _env(name: str, default: str = "") -> str:
        return os.environ.get(name, default).strip()

    base = _env("S9K_OLLAMA_BASE_URL") or _env("S9K_OLLAMA_URL") or DEFAULT_BASE_URL
    return {
        "base_url": base.rstrip("/"),
        "model": _env("S9K_OLLAMA_MODEL") or DEFAULT_MODEL,
        "embedding_model": _env("S9K_OLLAMA_EMBEDDING_MODEL") or None,
        "vision_model": _env("S9K_OLLAMA_VISION_MODEL") or None,
        "timeout_seconds": int(_env("S9K_OLLAMA_TIMEOUT_SECONDS", "120") or "120"),
        "max_retries": int(_env("S9K_OLLAMA_MAX_RETRIES", "2") or "2"),
    }


class OllamaProcessingProvider(ExternalProcessingProvider):
    """Cliente Ollama nativo, JSON estricto, fail-closed.

    Reintentos: los transitorios (red, timeout, 5xx) se reintentan aqui con
    backoff exponencial acotado ANTES de devolver el control al dispatcher, que
    a su vez reintenta segun `max_attempts` del job. Los dos niveles son
    deliberados y distintos: este cubre el hipo de red, el del dispatcher cubre
    la indisponibilidad del proveedor y alimenta el circuit breaker.
    """

    provider_name: str = "ollama"
    capabilities: Set[Capability] = set(OLLAMA_BASE_CAPABILITIES)

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        embedding_model: Optional[str] = None,
        vision_model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        max_retries: Optional[int] = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        embeddings: bool = False,
        urlopen=None,
    ) -> None:
        cfg = ollama_config()
        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self.model = model or cfg["model"]
        self.embedding_model = embedding_model or cfg["embedding_model"]
        self.vision_model = vision_model or cfg["vision_model"]
        self.timeout_seconds = timeout_seconds or cfg["timeout_seconds"]
        self.max_retries = cfg["max_retries"] if max_retries is None else max_retries
        self.max_response_bytes = max_response_bytes
        self.max_prompt_chars = max_prompt_chars
        # Inyeccion de transporte: los tests unitarios NO tocan la red. El
        # defecto RECHAZA redirects. Ollama es local y no lleva credenciales,
        # pero un 302 seguido a ciegas sigue siendo inyeccion de respuesta y
        # SSRF hacia la LAN, asi que la postura es la misma que con NVIDIA.
        self._urlopen = urlopen or safe_urlopen

        caps = set(OLLAMA_BASE_CAPABILITIES)
        if embeddings or self.embedding_model:
            caps.add(Capability.GENERATE_EMBEDDINGS)
        if self.vision_model:
            caps.add(Capability.DESCRIBE_IMAGE)
        # Instancia propia: no se pisa el atributo de clase.
        self.capabilities = caps

    # -- Capa HTTP ---------------------------------------------------------
    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST JSON con reintentos acotados. Devuelve el JSON de la respuesta."""
        url = f"{self.base_url}{path}"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        attempts = max(1, self.max_retries + 1)
        last: Optional[Exception] = None

        for attempt in range(attempts):
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Plazo de PARED por intento: el timeout de socket no acota una
            # respuesta que llega a goteo.
            deadline = time.monotonic() + self.timeout_seconds
            try:
                with self._urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = read_bounded(
                        resp,
                        self.max_response_bytes,
                        deadline=deadline,
                        what="respuesta de Ollama",
                    )
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as exc:
                    raise InvalidResponseError(
                        f"Ollama devolvio algo que no es JSON: {exc}"
                    ) from exc

            except urllib.error.HTTPError as exc:
                status = getattr(exc, "code", 0)
                if status in PERMANENT_HTTP_STATUS:
                    # Peticion mal formada, modelo inexistente o capacidad que
                    # el servidor NO tiene compilada. Reintentar 3 veces un 501
                    # y ademas alimentar el circuit breaker con el era gastar
                    # tiempo para llegar a la misma respuesta.
                    raise UnsupportedCapabilityError(
                        f"HTTP {status}", self.provider_name
                    ) from exc
                last = ProviderUnavailableError(f"Ollama HTTP {status}")
            except (socket.timeout, TimeoutError) as exc:
                last = TimeoutError(f"timeout contra Ollama tras {self.timeout_seconds}s")
            except urllib.error.URLError as exc:
                reason = type(getattr(exc, "reason", exc)).__name__
                last = ProviderUnavailableError(f"Ollama inalcanzable ({reason})")

            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt, 8))

        raise last if last is not None else ProviderUnavailableError("Ollama inalcanzable")

    # -- Operaciones -------------------------------------------------------
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        num_predict: int = 1024,
        seed: int = 7,
    ) -> Dict[str, Any]:
        """Chat con `format=json` y temperatura 0. Devuelve el objeto parseado.

        El contenido devuelto es un DATO. Este metodo no lo ejecuta, no lo
        evalua y no lo trata como instruccion: solo lo parsea como JSON.
        """
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars > self.max_prompt_chars:
            raise InputTooLargeError(
                f"prompt de {total_chars} caracteres por encima del tope "
                f"({self.max_prompt_chars})"
            )

        response = self._post(
            "/api/chat",
            {
                "model": model or self.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0, "num_predict": num_predict, "seed": seed},
            },
        )
        if "error" in response:
            raise InvalidResponseError(f"Ollama: {str(response['error'])[:200]}")

        content = (response.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise InvalidResponseError("Ollama devolvio un mensaje sin contenido")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(
                f"el contenido del modelo no es JSON estricto: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise InvalidResponseError(
                f"se esperaba un objeto JSON y llego {type(parsed).__name__}"
            )

        return {
            "parsed": parsed,
            "model": response.get("model") or model or self.model,
            "eval_count": response.get("eval_count"),
            "prompt_eval_count": response.get("prompt_eval_count"),
            "total_duration_ns": response.get("total_duration"),
            "done_reason": response.get("done_reason"),
        }

    def embed(self, texts: List[str], *, model: Optional[str] = None) -> Dict[str, Any]:
        """Embeddings via `/api/embed`.

        Fail-closed por DOS caminos, porque el servidor usa los dos:

        * **`HTTP 501`** — es lo que devuelve de verdad la instalacion real
          (192.168.1.157) cuando el binario no se arranco con `--embeddings`.
          Lo traduce `_post` a `UnsupportedCapabilityError` permanente.
        * **`200` con `{"error": ...}`** — algunas versiones responden asi.
          Se traduce aqui, tambien a error permanente.

        En ninguno de los dos casos se devuelve una lista vacia en silencio.
        """
        used = model or self.embedding_model or self.model
        response = self._post("/api/embed", {"model": used, "input": list(texts)})
        if "error" in response:
            raise UnsupportedCapabilityError(
                f"embeddings: {str(response['error'])[:160]}", self.provider_name
            )
        vectors = response.get("embeddings")
        if not isinstance(vectors, list) or not vectors:
            raise InvalidResponseError("respuesta de embeddings sin vectores")
        for v in vectors:
            if not isinstance(v, list) or not all(isinstance(x, (int, float)) for x in v):
                raise InvalidResponseError("vector de embedding con elementos no numericos")
        return {"embeddings": vectors, "model": used, "dimension": len(vectors[0])}

    # -- Contrato ExternalProcessingProvider -------------------------------
    def execute(self, job: ProcessingJob) -> Dict[str, Any]:
        """Ejecuta el job. El resultado es una PROPUESTA cruda, nunca una decision."""
        cap = _TASK_TO_CAP.get(job.task_type)
        if cap is None or cap not in self.capabilities:
            raise UnsupportedCapabilityError(str(job.task_type.value), self.provider_name)

        payload = job.payload or {}

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
            "eval_count": out["eval_count"],
            "prompt_eval_count": out["prompt_eval_count"],
            "total_duration_ns": out["total_duration_ns"],
        }

    def healthcheck(self) -> Dict[str, Any]:
        """`GET /api/tags`. No lanza nunca: devuelve el diagnostico."""
        url = f"{self.base_url}/api/tags"
        req = urllib.request.Request(url, method="GET")
        t0 = time.monotonic()
        try:
            budget = min(self.timeout_seconds, 15)
            with self._urlopen(req, timeout=budget) as resp:
                raw = read_bounded(
                    resp,
                    self.max_response_bytes,
                    deadline=time.monotonic() + budget,
                    what="respuesta de Ollama",
                )
            latency_ms = int((time.monotonic() - t0) * 1000)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            return {
                "status": "ok" if self.model in models else "degraded",
                "provider": self.provider_name,
                "base_url": self.base_url,
                "models": models,
                "configured_model": self.model,
                "model_present": self.model in models,
                "latency_ms": latency_ms,
                "capabilities": sorted(c.value for c in self.capabilities),
            }
        except Exception as exc:  # noqa: BLE001 - healthcheck no propaga
            return {
                "status": "error",
                "provider": self.provider_name,
                "base_url": self.base_url,
                "error": type(exc).__name__,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

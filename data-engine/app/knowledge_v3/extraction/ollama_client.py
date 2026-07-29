# -*- coding: utf-8 -*-
"""Cliente de Ollama para el subsistema extractor V3.

Configurable por entorno, **sin IP cableada en el codigo** (defecto D12 de la
auditoria: `review/llm_extractor.py:55` tiene una IP fija). Aqui la IP por
defecto vive en una constante documentada y cualquier despliegue la sobrescribe
con `S9K_OLLAMA_URL`.

    S9K_OLLAMA_URL      http://192.168.1.157:11434   (servidor Ollama)
    S9K_OLLAMA_MODEL    qwen2.5:7b                   (unico modelo instalado)
    S9K_OLLAMA_TIMEOUT  300                          (segundos; medido, ver DEFAULT_TIMEOUT)
    S9K_OLLAMA_RETRIES  1                            (reintentos de transporte)
    S9K_LIVE_OLLAMA     0                            (activa los tests de humo)

El transporte es **inyectable**: los tests unitarios no tocan la red nunca. El
transporte real usa `urllib` (sin dependencias nuevas) y pide `format=json` con
`temperature=0`, que es lo mas cerca de determinista que Ollama ofrece.

Fail-closed: cualquier error de red o de decodificacion levanta una excepcion de
esta familia. El extractor la convierte en ABSTENCION; jamas en un resultado.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: Valor por defecto del servidor local. Documentado, no cableado: se sobrescribe
#: con `S9K_OLLAMA_URL` sin tocar codigo.
DEFAULT_OLLAMA_URL = "http://192.168.1.157:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"

#: 300 s, no 60. Medido: una extraccion de UNA frase corta contra qwen2.5:7b en
#: 192.168.1.157 tardo ~190 s (2026-07-27). Con 60 s el extractor se abstenia
#: por timeout aunque el servidor estuviese perfectamente vivo, que es la peor
#: clase de falso negativo: parece un fallo del modelo y es de configuracion.
DEFAULT_TIMEOUT = 300.0

_HOST_RE = re.compile(r"//[^/\s]+")


class OllamaError(RuntimeError):
    """Fallo de comunicacion con Ollama. Fail-closed: nunca devuelve datos."""


class OllamaUnavailable(OllamaError):
    """No se pudo contactar con el servidor (red, timeout, 5xx)."""


class OllamaBadResponse(OllamaError):
    """El servidor respondio algo que no es una respuesta de Ollama."""


def redact_url(url: str) -> str:
    """Oculta el host en los mensajes de error: no se filtran IPs internas."""
    return _HOST_RE.sub("//<host>", url or "")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class OllamaConfig:
    """Configuracion efectiva del cliente. Se lee del entorno en `from_env()`."""

    url: str = DEFAULT_OLLAMA_URL
    model: str = DEFAULT_OLLAMA_MODEL
    timeout: float = DEFAULT_TIMEOUT
    retries: int = 1
    temperature: float = 0.0
    num_predict: int = 1024

    @classmethod
    def from_env(cls, **overrides: Any) -> "OllamaConfig":
        base = cls(
            url=os.environ.get("S9K_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/"),
            model=os.environ.get("S9K_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            timeout=_env_float("S9K_OLLAMA_TIMEOUT", DEFAULT_TIMEOUT),
            retries=_env_int("S9K_OLLAMA_RETRIES", 1),
        )
        if not overrides:
            return base
        data = {**base.__dict__, **overrides}
        return cls(**data)

    @property
    def generate_endpoint(self) -> str:
        return f"{self.url.rstrip('/')}/api/generate"

    @property
    def tags_endpoint(self) -> str:
        return f"{self.url.rstrip('/')}/api/tags"

    def safe_url(self) -> str:
        return redact_url(self.url)


@dataclass(frozen=True)
class OllamaResponse:
    """Respuesta cruda de Ollama. El texto NO se interpreta aqui."""

    text: str
    model: str
    latency_ms: int
    attempts: int = 1
    raw: dict = field(default_factory=dict)


def _urllib_transport(url: str, payload: dict, timeout: float) -> dict:
    """Transporte real. Unico punto del subsistema que abre un socket."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - url del operador
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # pragma: no cover - requiere servidor
        raise OllamaUnavailable(f"HTTP {exc.code} de {redact_url(url)}") from None
    except (urllib.error.URLError, OSError) as exc:  # pragma: no cover - requiere red
        raise OllamaUnavailable(f"sin respuesta de {redact_url(url)}: {type(exc).__name__}") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - requiere servidor raro
        raise OllamaBadResponse(f"respuesta no JSON de {redact_url(url)}: {exc}") from None


class OllamaClient:
    """Cliente minimo de la API nativa de Ollama (`/api/generate`).

    `transport` permite inyectar un doble en los tests: la suite unitaria del
    extractor NO depende de que haya un servidor Ollama vivo.
    """

    def __init__(
        self,
        config: Optional[OllamaConfig] = None,
        transport: Optional[Callable[[str, dict, float], dict]] = None,
    ) -> None:
        self.config = config or OllamaConfig.from_env()
        self._transport = transport or _urllib_transport
        self.calls: int = 0

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        json_mode: bool = True,
        num_predict: Optional[int] = None,
    ) -> OllamaResponse:
        """Una generacion. Reintenta SOLO los fallos de transporte.

        `num_predict` se puede subir por llamada: la respuesta conjunta del
        extractor semantico (menciones + claims + abstenciones) no cabe en los
        1024 tokens del defecto, y una respuesta truncada llega como "JSON
        invalido" cuando en realidad es un limite nuestro. Se sube donde hace
        falta, no en la configuracion global.
        """
        payload: dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": int(num_predict or self.config.num_predict),
            },
        }
        if json_mode:
            payload["format"] = "json"
        if system:
            payload["system"] = system

        last: Optional[Exception] = None
        started = time.monotonic()
        for attempt in range(1, max(1, self.config.retries + 1) + 1):
            self.calls += 1
            try:
                raw = self._transport(self.config.generate_endpoint, payload, self.config.timeout)
            except OllamaError as exc:
                last = exc
                continue
            except Exception as exc:  # transporte inyectado que falla de otro modo
                last = OllamaUnavailable(f"{type(exc).__name__}")
                continue
            if not isinstance(raw, dict) or "response" not in raw:
                last = OllamaBadResponse("la respuesta no trae el campo 'response'")
                continue
            return OllamaResponse(
                text=str(raw.get("response") or ""),
                model=str(raw.get("model") or self.config.model),
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
                raw=raw,
            )
        raise last or OllamaUnavailable("sin intentos ejecutados")

    def list_models(self) -> list[str]:
        """Modelos instalados. Solo lectura; se usa en el test de humo."""
        raw = self._transport_get(self.config.tags_endpoint)
        return [str(m.get("name")) for m in raw.get("models", []) if isinstance(m, dict)]

    def _transport_get(self, url: str) -> dict:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - requiere red
            raise OllamaUnavailable(
                f"no se pudo listar modelos en {redact_url(url)}: {type(exc).__name__}"
            ) from None


__all__ = [
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_TIMEOUT",
    "OllamaBadResponse",
    "OllamaClient",
    "OllamaConfig",
    "OllamaError",
    "OllamaResponse",
    "OllamaUnavailable",
    "redact_url",
]

# -*- coding: utf-8 -*-
"""Adaptador NVIDIA para procesamiento externo (Fase B1).

Reutiliza el cliente HTTP y auth de external_ai (openai_compatible,
registry, security) sin duplicar codigo.

Capacidades verificadas (Fase B1):
  - EXTRACT_TEXT_ENTITIES
  - GENERATE_EMBEDDINGS
  - RERANK
  - REVIEW_CANDIDATES

Para las demas: UnsupportedCapabilityError inmediato.

NO modifica nada en external_ai/.
NO escribe en Neo4j.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Set

from external_processing.capabilities import Capability, NVIDIA_VERIFIED_CAPABILITIES
from external_processing.errors import (
    AuthError,
    InvalidResponseError,
    RateLimitError,
    TimeoutError,
    UnsupportedCapabilityError,
)
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.provider import ExternalProcessingProvider


# Mapa de tarea -> capacidad
_TASK_TO_CAP: Dict[ExternalTaskType, Capability] = {
    ExternalTaskType.TEXT_EXTRACT: Capability.EXTRACT_TEXT_ENTITIES,
    ExternalTaskType.EMBEDDINGS: Capability.GENERATE_EMBEDDINGS,
    ExternalTaskType.RERANK: Capability.RERANK,
    ExternalTaskType.REVIEW: Capability.REVIEW_CANDIDATES,
}


class NvidiaProcessingProvider(ExternalProcessingProvider):
    """Adaptador NVIDIA para procesamiento externo.

    Reutiliza external_ai.openai_compatible y external_ai.registry para
    auth, HTTP y config. Solo declara capacidades verificadas.
    """

    provider_name: str = "nvidia"
    capabilities: Set[Capability] = NVIDIA_VERIFIED_CAPABILITIES

    def __init__(self, repo_root: Path):
        self._repo_root = Path(repo_root)
        self._client: Optional[Any] = None  # Lazy init

    def _get_client(self):
        """Lazy init del cliente NVIDIA NIM reutilizando external_ai."""
        if self._client is None:
            try:
                from external_ai import registry
                from external_ai.openai_compatible import OpenAICompatibleProvider
                cfg = registry.nvidia_config()
                self._client = OpenAICompatibleProvider(
                    base_url=cfg["base_url"],
                    api_key_getter=registry.get_api_key,
                    repo_root=self._repo_root,
                    timeout=cfg["timeout_seconds"],
                    max_retries=cfg["max_retries"],
                    max_concurrency=cfg.get("max_concurrency", 2),
                    cache_enabled=False,  # Cache gestionada por external_processing.cache
                )
            except Exception as exc:
                raise AuthError(f"No se pudo inicializar cliente NVIDIA: {exc}") from exc
        return self._client

    def execute(self, job: ProcessingJob) -> Dict[str, Any]:
        """Ejecuta el job usando la API NVIDIA NIM.

        Solo para capacidades verificadas. Las demas lanzan UnsupportedCapabilityError.
        """
        cap = _TASK_TO_CAP.get(job.task_type)
        if cap is None or cap not in self.capabilities:
            raise UnsupportedCapabilityError(
                str(job.task_type.value), self.provider_name
            )

        # Seguridad: sanitizar payload antes de enviar
        try:
            from external_ai.security import assert_no_secrets, sanitize_request
            sanitized = sanitize_request(job.payload or {}, self._repo_root)
            assert_no_secrets(sanitized)
        except Exception as sec_exc:
            raise AuthError(f"Verificacion de seguridad fallida: {sec_exc}") from sec_exc

        # En Fase B1: implementacion pendiente de endpoints especificos
        # Los endpoints /embeddings, /rerank etc. no son parte del contrato
        # OpenAI-compatible estandar; se implementan en Fase B2.
        raise NotImplementedError(
            f"NvidiaProcessingProvider.execute: Fase B2 pendiente para {job.task_type.value}. "
            f"Capacidad declarada pero endpoint no implementado. "
            f"Usar MockExternalProcessingProvider en tests."
        )

    def healthcheck(self) -> Dict[str, Any]:
        """Comprueba disponibilidad del endpoint NVIDIA."""
        try:
            client = self._get_client()
            # Reutilizar healthcheck del cliente base si existe
            if hasattr(client, "healthcheck"):
                health = client.healthcheck()
                return {
                    "status": "ok",
                    "provider": self.provider_name,
                    "capabilities": [c.value for c in self.capabilities],
                    "base_health": health.status if hasattr(health, "status") else str(health),
                }
            return {
                "status": "ok",
                "provider": self.provider_name,
                "capabilities": [c.value for c in self.capabilities],
                "note": "healthcheck basico (cliente disponible)",
            }
        except Exception as exc:
            return {
                "status": "error",
                "provider": self.provider_name,
                "error": str(exc)[:100],
            }

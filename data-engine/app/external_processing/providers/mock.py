# -*- coding: utf-8 -*-
"""Mock determinista para todos los escenarios de prueba (Fase B1).

Soporta TODAS las capacidades. Nunca llama a APIs reales.

Escenarios configurables:
  - success: respuesta valida (por defecto)
  - timeout: simula timeout en cada intento
  - invalid_schema: respuesta con campos requeridos ausentes
  - partial: resultado parcial (texto truncado)
  - rate_limit_N: N primeros intentos fallan con RateLimitError
  - permanent_error: siempre falla con error permanente
  - retry_once: falla la primera vez, exito en la segunda
"""
from __future__ import annotations

import hashlib
import threading
from typing import Any, Dict, Optional, Set

from external_processing.capabilities import Capability
from external_processing.errors import (
    AuthError,
    ContentBlockedError,
    InputTooLargeError,
    InvalidResponseError,
    RateLimitError,
    TimeoutError,
    UnsupportedCapabilityError,
)
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.provider import ExternalProcessingProvider


class MockExternalProcessingProvider(ExternalProcessingProvider):
    """Proveedor mock determinista. Todas las capacidades. Sin llamadas de red."""

    provider_name: str = "mock"
    capabilities: Set[Capability] = set(Capability)

    def __init__(
        self,
        scenario: str = "success",
        rate_limit_count: int = 0,
        delay_seconds: float = 0.0,
    ):
        """
        Args:
            scenario: "success" | "timeout" | "invalid_schema" | "partial" |
                      "rate_limit" | "permanent_error" | "retry_once" |
                      "auth_error" | "input_too_large" | "content_blocked"
            rate_limit_count: numero de intentos iniciales que fallan con RateLimitError
            delay_seconds: retardo simulado (en tests usar 0)
        """
        self.scenario = scenario
        self.rate_limit_count = rate_limit_count
        self.delay_seconds = delay_seconds
        self._attempt_counters: Dict[str, int] = {}
        self._lock = threading.Lock()

    def _get_attempt(self, job_id: str) -> int:
        with self._lock:
            return self._attempt_counters.get(job_id, 0)

    def _inc_attempt(self, job_id: str) -> int:
        with self._lock:
            count = self._attempt_counters.get(job_id, 0) + 1
            self._attempt_counters[job_id] = count
            return count

    def execute(self, job: ProcessingJob) -> Dict[str, Any]:
        """Ejecuta el job mock segun el escenario configurado."""
        import time
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        attempt = self._inc_attempt(job.job_id)

        # Escenario: timeout
        if self.scenario == "timeout":
            raise TimeoutError(f"Mock timeout en intento {attempt}")

        # Escenario: error permanente
        if self.scenario == "permanent_error":
            raise AuthError("Mock: error permanente de autenticacion")

        # Escenario: auth_error
        if self.scenario == "auth_error":
            raise AuthError("Mock: credenciales invalidas")

        # Escenario: input_too_large
        if self.scenario == "input_too_large":
            raise InputTooLargeError("Mock: input supera limite")

        # Escenario: content_blocked
        if self.scenario == "content_blocked":
            raise ContentBlockedError("Mock: contenido bloqueado")

        # Escenario: rate_limit (N primeros intentos)
        if self.scenario == "rate_limit" or self.rate_limit_count > 0:
            if attempt <= self.rate_limit_count:
                raise RateLimitError(f"Mock: rate limit en intento {attempt}", retry_after=0.01)

        # Escenario: retry_once (falla la primera vez)
        if self.scenario == "retry_once" and attempt == 1:
            raise TimeoutError("Mock: fallo en primer intento (retry_once)")

        # Escenario: schema invalido
        if self.scenario == "invalid_schema":
            return {"unexpected_field": "missing required fields"}

        # Escenario: parcial
        if self.scenario == "partial":
            return self._partial_result(job)

        # Escenario: exito (default)
        return self._success_result(job)

    def _success_result(self, job: ProcessingJob) -> Dict[str, Any]:
        """Genera resultado valido determinista segun tipo de tarea."""
        chunk = job.chunk or {}
        source_hash = chunk.get("source_hash", job.source_id)

        if job.task_type == ExternalTaskType.TRANSCRIBE_AUDIO:
            return {
                "text": f"Transcripcion mock del segmento {chunk.get('chunk_index', 0)}",
                "language": "es",
                "confidence": 0.95,
                "start": chunk.get("chunk_start", 0.0),
                "end": chunk.get("chunk_end", 60.0),
                "source_hash": source_hash,
                "speaker": "speaker_1",
                "provider": "mock",
                "model": "mock-asr-v1",
            }

        if job.task_type == ExternalTaskType.OCR_IMAGE:
            return {
                "text": f"Texto OCR mock de paginas {chunk.get('page_start', 1)}-{chunk.get('page_end', 1)}",
                "blocks": [{"text": "bloque 1", "bbox": [0, 0, 100, 20]}],
                "document_hash": chunk.get("document_hash", source_hash),
                "page_start": chunk.get("page_start", 1),
                "page_end": chunk.get("page_end", 1),
                "provider": "mock",
                "model": "mock-ocr-v1",
            }

        if job.task_type == ExternalTaskType.IMAGE_ANALYSIS:
            return {
                "description": f"Descripcion mock de imagen {chunk.get('image_index', 0)}",
                "objects": ["objeto_1", "objeto_2"],
                "source_hash": source_hash,
                "provider": "mock",
                "model": "mock-vision-v1",
            }

        if job.task_type == ExternalTaskType.TEXT_EXTRACT:
            return {
                "entities": [
                    {"text": "Entidad Mock", "type": "PERSON", "confidence": 0.9},
                ],
                "offset_start": chunk.get("offset_start", 0),
                "offset_end": chunk.get("offset_end", 100),
                "source_hash": source_hash,
                "provider": "mock",
                "model": "mock-ner-v1",
            }

        if job.task_type == ExternalTaskType.EMBEDDINGS:
            # Embedding determinista basado en hash del source
            seed = int(hashlib.sha256(source_hash.encode()).hexdigest()[:8], 16)
            embedding = [float((seed + i) % 1000) / 1000.0 for i in range(8)]
            return {
                "embedding": embedding,
                "text_hash": source_hash,
                "model": "mock-embed-v1",
                "provider": "mock",
            }

        if job.task_type == ExternalTaskType.RERANK:
            return {
                "ranked": [{"id": "item_0", "score": 0.9}, {"id": "item_1", "score": 0.7}],
                "source_hash": source_hash,
                "provider": "mock",
                "model": "mock-rerank-v1",
            }

        if job.task_type == ExternalTaskType.REVIEW:
            return {
                "decision": "APPROVE",
                "confidence": 0.85,
                "evidence": "Evidencia mock",
                "source_hash": source_hash,
                "provider": "mock",
                "model": "mock-review-v1",
            }

        return {
            "result": "mock_success",
            "task_type": job.task_type.value,
            "source_hash": source_hash,
        }

    def _partial_result(self, job: ProcessingJob) -> Dict[str, Any]:
        """Resultado parcial (texto incompleto, campos opcionales ausentes)."""
        chunk = job.chunk or {}
        source_hash = chunk.get("source_hash", job.source_id)
        return {
            "text": "Texto parcial...",
            "source_hash": source_hash,
            "partial": True,
            "provider": "mock",
        }

    def healthcheck(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "provider": "mock",
            "scenario": self.scenario,
            "capabilities": [c.value for c in self.capabilities],
        }

    def reset_attempts(self) -> None:
        """Reinicia contadores de intentos. Util entre tests."""
        with self._lock:
            self._attempt_counters.clear()

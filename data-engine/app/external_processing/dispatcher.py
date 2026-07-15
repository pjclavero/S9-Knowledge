# -*- coding: utf-8 -*-
"""Dispatcher con concurrencia, retry, backoff y circuit breaker (Fase B1).

Features:
  - Concurrencia limitada por semaforo
  - Timeouts configurables
  - Reintentos con backoff exponencial
  - Cancelacion limpia
  - Rate limiting (espera retry_after)
  - Circuit breaker basico (abre tras N fallos consecutivos, se resetea tras cool-down)

Errores no reintentables: AUTH_ERROR, UNSUPPORTED_CAPABILITY, INPUT_TOO_LARGE, CONTENT_BLOCKED
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from external_processing.capabilities import Capability
from external_processing.errors import (
    AuthError,
    CancelledError,
    CircuitOpenError,
    ContentBlockedError,
    ErrorCode,
    ExternalProcessingError,
    InputTooLargeError,
    RateLimitError,
    TimeoutError,
    UnsupportedCapabilityError,
    NON_RETRYABLE_ERRORS,
)
from external_processing.models import (
    ExternalTaskType,
    JobStatus,
    ProcessingJob,
)
from external_processing.provider import ExternalProcessingProvider


# ── Mapa tarea -> capacidad ───────────────────────────────────────────────────

_TASK_TO_CAPABILITY: Dict[ExternalTaskType, Capability] = {
    ExternalTaskType.TRANSCRIBE_AUDIO: Capability.TRANSCRIBE_AUDIO,
    ExternalTaskType.OCR_IMAGE: Capability.OCR_IMAGE,
    ExternalTaskType.IMAGE_ANALYSIS: Capability.DESCRIBE_IMAGE,
    ExternalTaskType.TEXT_EXTRACT: Capability.EXTRACT_TEXT_ENTITIES,
    ExternalTaskType.EMBEDDINGS: Capability.GENERATE_EMBEDDINGS,
    ExternalTaskType.RERANK: Capability.RERANK,
    ExternalTaskType.REVIEW: Capability.REVIEW_CANDIDATES,
}


# ── Circuit breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker simple por proveedor.

    Estados: CLOSED (normal) -> OPEN (demasiados fallos) -> HALF_OPEN (prueba)
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0):
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.time() - self._opened_at >= self._cooldown:
                # Pasar a HALF_OPEN: permitir un intento
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = time.time()

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None


# ── Dispatcher ────────────────────────────────────────────────────────────────

class BurstDispatcher:
    """Despacha jobs de procesamiento externo con control de concurrencia."""

    def __init__(
        self,
        provider: ExternalProcessingProvider,
        max_concurrency: Optional[int] = None,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 60.0,
        dry_run: bool = False,
    ):
        conc = max_concurrency or int(os.environ.get("S9K_EXTERNAL_MAX_CONCURRENCY", "4"))
        self.provider = provider
        self._semaphore = threading.Semaphore(conc)
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self._circuit = CircuitBreaker(circuit_failure_threshold, circuit_cooldown_seconds)
        self.dry_run = dry_run
        self._cancelled_batches: Set[str] = set()
        self._lock = threading.Lock()

        # Metricas
        self.total_dispatched = 0
        self.total_retries = 0
        self.total_failed = 0
        self.total_cache_hits = 0

    def cancel_batch(self, batch_id: str) -> None:
        """Marca un batch para cancelacion limpia."""
        with self._lock:
            self._cancelled_batches.add(batch_id)

    def _is_cancelled(self, batch_id: str) -> bool:
        return batch_id in self._cancelled_batches

    def _backoff_seconds(self, attempt: int) -> float:
        return min(self._base_backoff * (2 ** attempt), self._max_backoff)

    def _verify_capability(self, job: ProcessingJob) -> None:
        """Verifica que el proveedor soporta la capacidad requerida."""
        cap = _TASK_TO_CAPABILITY.get(job.task_type)
        if cap is None:
            raise UnsupportedCapabilityError(str(job.task_type), self.provider.provider_name)
        if not self.provider.supports(cap):
            raise UnsupportedCapabilityError(cap.value, self.provider.provider_name)

    def dispatch_one(self, job: ProcessingJob) -> ProcessingJob:
        """Despacha un solo job. Gestiona reintentos, backoff y circuit breaker.

        Devuelve el job con el estado final actualizado.
        """
        # Cache hit: no hay nada que ejecutar
        if job.cache_hit and job.result is not None:
            self.total_cache_hits += 1
            return job.transition_to(JobStatus.READY) if job.status == JobStatus.DETECTED else job

        # Verificar capacidad antes de intentar
        try:
            self._verify_capability(job)
        except UnsupportedCapabilityError as exc:
            job = job.copy(update={
                "error_code": ErrorCode.UNSUPPORTED_CAPABILITY,
                "error_message": str(exc),
                "status": JobStatus.FAILED,
                "finished_at": datetime.now(timezone.utc),
            })
            self.total_failed += 1
            return job

        current_job = job.transition_to(JobStatus.PLANNED).transition_to(JobStatus.QUEUED)

        while True:
            # Verificar cancelacion
            if self._is_cancelled(current_job.batch_id):
                self.total_failed += 1
                return current_job.copy(update={
                    "status": JobStatus.CANCELLED,
                    "error_code": ErrorCode.CANCELLED,
                    "finished_at": datetime.now(timezone.utc),
                })

            # Verificar circuit breaker
            if self._circuit.is_open:
                self.total_failed += 1
                return current_job.copy(update={
                    "status": JobStatus.FAILED,
                    "error_code": ErrorCode.CIRCUIT_OPEN,
                    "error_message": f"Circuit breaker abierto para {self.provider.provider_name}",
                    "finished_at": datetime.now(timezone.utc),
                })

            # Modo dry-run: simular exito sin llamar al proveedor
            if self.dry_run:
                self.total_dispatched += 1
                return current_job.copy(update={
                    "status": JobStatus.READY,
                    "result": {"dry_run": True},
                    "finished_at": datetime.now(timezone.utc),
                    "progress": 1.0,
                })

            # Adquirir semaforo
            with self._semaphore:
                current_job = current_job.transition_to(JobStatus.DISPATCHING)
                current_job = current_job.transition_to(JobStatus.RUNNING)
                current_job = current_job.copy(update={"attempt": current_job.attempt + 1})

                start_ms = time.time() * 1000
                try:
                    result = self.provider.execute(current_job)
                    latency = time.time() * 1000 - start_ms
                    self._circuit.record_success()
                    self.total_dispatched += 1
                    completed = current_job.transition_to(JobStatus.COMPLETED)
                    return completed.copy(update={
                        "result": result,
                        "latency_ms": latency,
                        "progress": 1.0,
                    })

                except (AuthError, UnsupportedCapabilityError, InputTooLargeError, ContentBlockedError) as exc:
                    # Errores permanentes: no reintentar
                    self._circuit.record_failure()
                    self.total_failed += 1
                    return current_job.copy(update={
                        "status": JobStatus.FAILED,
                        "error_code": exc.code,
                        "error_message": str(exc),
                        "finished_at": datetime.now(timezone.utc),
                    })

                except RateLimitError as exc:
                    self._circuit.record_failure()
                    if current_job.attempt >= current_job.max_attempts:
                        self.total_failed += 1
                        return current_job.copy(update={
                            "status": JobStatus.FAILED,
                            "error_code": exc.code,
                            "error_message": str(exc),
                            "finished_at": datetime.now(timezone.utc),
                        })
                    self.total_retries += 1
                    wait = exc.retry_after if exc.retry_after > 0 else self._backoff_seconds(current_job.attempt)
                    current_job = current_job.copy(update={
                        "status": JobStatus.RETRY_WAIT,
                        "error_code": exc.code,
                    })
                    time.sleep(wait)
                    current_job = current_job.transition_to(JobStatus.QUEUED)
                    continue

                except (TimeoutError, ExternalProcessingError) as exc:
                    self._circuit.record_failure()
                    if current_job.attempt >= current_job.max_attempts:
                        self.total_failed += 1
                        return current_job.copy(update={
                            "status": JobStatus.FAILED,
                            "error_code": exc.code,
                            "error_message": str(exc),
                            "finished_at": datetime.now(timezone.utc),
                        })
                    self.total_retries += 1
                    wait = self._backoff_seconds(current_job.attempt)
                    current_job = current_job.copy(update={
                        "status": JobStatus.RETRY_WAIT,
                        "error_code": exc.code,
                    })
                    time.sleep(wait)
                    current_job = current_job.transition_to(JobStatus.QUEUED)
                    continue

    def dispatch_batch(
        self,
        jobs: List[ProcessingJob],
        sleep_fn: Callable = time.sleep,
    ) -> List[ProcessingJob]:
        """Despacha un batch de jobs en paralelo (hasta max_concurrency simultaneos).

        Devuelve la lista de jobs con estados finales.
        """
        results: List[Optional[ProcessingJob]] = [None] * len(jobs)
        threads = []
        errors = []

        def run(idx: int, job: ProcessingJob) -> None:
            try:
                results[idx] = self.dispatch_one(job)
            except Exception as exc:
                results[idx] = job.copy(update={
                    "status": JobStatus.FAILED,
                    "error_message": str(exc),
                    "finished_at": datetime.now(timezone.utc),
                })

        for i, job in enumerate(jobs):
            t = threading.Thread(target=run, args=(i, job), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        return [r for r in results if r is not None]

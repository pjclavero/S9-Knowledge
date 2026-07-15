# -*- coding: utf-8 -*-
"""Tests del dispatcher: concurrencia, retry, backoff, errores (Fase B1).

Tests 12-17.
"""
import threading
import time
import uuid
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.dispatcher import BurstDispatcher, CircuitBreaker
from external_processing.errors import AuthError, RateLimitError, TimeoutError
from external_processing.models import ExternalTaskType, JobStatus, ProcessingJob, ProcessingMode
from external_processing.providers.mock import MockExternalProcessingProvider


def _make_transcribe_job(batch_id: str = None, max_attempts: int = 3) -> ProcessingJob:
    return ProcessingJob(
        batch_id=batch_id or str(uuid.uuid4()),
        workspace="test_ws",
        source_id="source_001",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
        provider="mock",
        model="mock-asr",
        chunk={
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 60.0,
            "source_hash": "src_hash",
            "overlap_start": 0.0,
            "overlap_end": 0.0,
        },
        max_attempts=max_attempts,
    )


# ── Test 12: concurrencia limitada ───────────────────────────────────────────

def test_dispatcher_concurrencia_limitada():
    """El dispatcher no supera el limite de concurrencia."""
    concurrent_count = []
    lock = threading.Lock()
    max_seen = [0]

    class CountingProvider(MockExternalProcessingProvider):
        def execute(self, job):
            with lock:
                concurrent_count.append(1)
                current = sum(concurrent_count)
                if current > max_seen[0]:
                    max_seen[0] = current
            time.sleep(0.01)
            with lock:
                concurrent_count.pop()
            return super().execute(job)

    provider = CountingProvider()
    dispatcher = BurstDispatcher(provider, max_concurrency=2, base_backoff=0.0)
    jobs = [_make_transcribe_job() for _ in range(5)]
    results = dispatcher.dispatch_batch(jobs)

    assert max_seen[0] <= 2
    assert all(j.status in (JobStatus.READY, JobStatus.COMPLETED) for j in results)


# ── Test 13: rate limit -> retry con backoff ──────────────────────────────────

def test_dispatcher_rate_limit_retry():
    """RateLimitError provoca retry con backoff."""
    provider = MockExternalProcessingProvider(scenario="rate_limit", rate_limit_count=1)
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.01)
    job = _make_transcribe_job(max_attempts=3)

    result = dispatcher.dispatch_one(job)

    # Debe tener exito despues del retry
    assert result.status == JobStatus.COMPLETED
    assert dispatcher.total_retries >= 1


# ── Test 14: timeout -> retry con backoff ────────────────────────────────────

def test_dispatcher_timeout_retry():
    """TimeoutError provoca retry."""
    provider = MockExternalProcessingProvider(scenario="retry_once")
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.01)
    job = _make_transcribe_job(max_attempts=3)

    result = dispatcher.dispatch_one(job)
    assert result.status == JobStatus.COMPLETED
    assert dispatcher.total_retries >= 1


# ── Test 15: retry exitoso (falla 1 vez) ─────────────────────────────────────

def test_dispatcher_retry_exitoso():
    """Mock falla 1 vez (retry_once), luego exito en segunda."""
    provider = MockExternalProcessingProvider(scenario="retry_once")
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.01)
    job = _make_transcribe_job(max_attempts=3)

    result = dispatcher.dispatch_one(job)

    assert result.status == JobStatus.COMPLETED
    assert result.result is not None
    assert result.result.get("text") is not None


# ── Test 16: error permanente no reintenta AUTH_ERROR ─────────────────────────

def test_dispatcher_no_reintenta_auth_error():
    """AuthError es permanente: no se reintenta."""
    provider = MockExternalProcessingProvider(scenario="auth_error")
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.01)
    job = _make_transcribe_job(max_attempts=5)

    result = dispatcher.dispatch_one(job)

    assert result.status == JobStatus.FAILED
    assert dispatcher.total_retries == 0


# ── Test 17: cancelacion limpia ──────────────────────────────────────────────

def test_dispatcher_cancelacion_limpia():
    """Batch cancelado antes de ejecutar no procesa jobs."""
    provider = MockExternalProcessingProvider(scenario="success")
    batch_id = str(uuid.uuid4())
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.01)
    dispatcher.cancel_batch(batch_id)

    job = _make_transcribe_job(batch_id=batch_id)
    result = dispatcher.dispatch_one(job)

    assert result.status == JobStatus.CANCELLED


def test_dispatcher_dry_run_no_llama_proveedor():
    """Modo dry-run devuelve resultado sin llamar al proveedor."""
    class FailProvider(MockExternalProcessingProvider):
        def execute(self, job):
            raise AssertionError("No debe llamarse en dry-run")

    provider = FailProvider()
    dispatcher = BurstDispatcher(provider, max_concurrency=1, dry_run=True)
    job = _make_transcribe_job()
    result = dispatcher.dispatch_one(job)

    assert result.status == JobStatus.READY
    assert result.result == {"dry_run": True}


def test_dispatcher_unsupported_capability_no_ejecuta():
    """UNSUPPORTED_CAPABILITY falla sin ejecutar."""
    from external_processing.providers.nvidia import NvidiaProcessingProvider
    from unittest.mock import patch
    from pathlib import Path

    # Crear proveedor que no soporta TRANSCRIBE_AUDIO
    provider = MockExternalProcessingProvider()
    # Simular proveedor sin capacidad de transcripcion
    from external_processing.capabilities import Capability
    original_caps = provider.capabilities
    provider.capabilities = {Capability.RERANK}  # solo rerank

    dispatcher = BurstDispatcher(provider, max_concurrency=1)
    job = _make_transcribe_job()
    result = dispatcher.dispatch_one(job)

    provider.capabilities = original_caps  # restaurar

    assert result.status == JobStatus.FAILED
    from external_processing.errors import ErrorCode
    assert result.error_code == ErrorCode.UNSUPPORTED_CAPABILITY


def test_circuit_breaker_abre_tras_fallos():
    """Circuit breaker se abre tras N fallos consecutivos."""
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    assert not cb.is_open
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open
    cb.record_failure()  # 3er fallo: abre
    assert cb.is_open


def test_circuit_breaker_reset():
    """Circuit breaker se resetea con exito."""
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open
    cb.record_success()
    assert not cb.is_open

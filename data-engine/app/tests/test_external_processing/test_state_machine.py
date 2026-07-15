# -*- coding: utf-8 -*-
"""Tests de la maquina de estados de ProcessingJob (Fase B1).

Test 18: transicion invalida completed->running debe fallar.
"""
import uuid
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.models import (
    ExternalTaskType, JobStatus, ProcessingJob, ProcessingMode,
    validate_transition, VALID_TRANSITIONS,
)


def _make_job() -> ProcessingJob:
    return ProcessingJob(
        batch_id=str(uuid.uuid4()),
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
    )


# ── Test 18: completed -> running debe fallar ─────────────────────────────────

def test_transicion_invalida_completed_to_running():
    """completed -> running debe lanzar ValueError."""
    with pytest.raises(ValueError, match="Transicion invalida"):
        validate_transition(JobStatus.COMPLETED, JobStatus.RUNNING)


def test_transicion_invalida_failed_to_completed():
    """failed -> completed sin retry explicito debe fallar."""
    with pytest.raises(ValueError, match="Transicion invalida"):
        validate_transition(JobStatus.FAILED, JobStatus.COMPLETED)


def test_transicion_invalida_ready_cualquier_estado():
    """ready es estado terminal: ninguna transicion permitida."""
    for next_status in JobStatus:
        if next_status != JobStatus.READY:
            with pytest.raises(ValueError):
                validate_transition(JobStatus.READY, next_status)


def test_transicion_valida_detected_to_planned():
    """detected -> planned es valida."""
    validate_transition(JobStatus.DETECTED, JobStatus.PLANNED)  # no lanza


def test_transicion_valida_running_to_completed():
    """running -> completed es valida."""
    validate_transition(JobStatus.RUNNING, JobStatus.COMPLETED)


def test_transicion_valida_running_to_retry_wait():
    """running -> retry_wait es valida."""
    validate_transition(JobStatus.RUNNING, JobStatus.RETRY_WAIT)


def test_transicion_valida_retry_wait_to_queued():
    """retry_wait -> queued es valida."""
    validate_transition(JobStatus.RETRY_WAIT, JobStatus.QUEUED)


def test_job_transition_to_actualiza_estado():
    """transition_to() devuelve nuevo job con estado correcto."""
    job = _make_job()
    job2 = job.transition_to(JobStatus.PLANNED)
    assert job2.status == JobStatus.PLANNED
    assert job.status == JobStatus.DETECTED  # inmutable


def test_job_transition_to_invalida_lanza():
    """transition_to() invalida lanza ValueError."""
    job = _make_job().transition_to(JobStatus.PLANNED).transition_to(JobStatus.QUEUED)
    job = job.transition_to(JobStatus.DISPATCHING).transition_to(JobStatus.RUNNING)
    job = job.transition_to(JobStatus.COMPLETED).transition_to(JobStatus.VALIDATING)
    job = job.transition_to(JobStatus.READY)

    with pytest.raises(ValueError):
        job.transition_to(JobStatus.RUNNING)

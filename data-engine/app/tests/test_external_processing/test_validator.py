# -*- coding: utf-8 -*-
"""Tests de validacion de resultados externos (Fase B1).

Tests 19-21: hash incorrecto, rango invalido, timestamps invalidos.
"""
import uuid
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.models import ExternalTaskType, JobStatus, ProcessingJob, ProcessingMode
from external_processing.result_validator import (
    validate_transcription_result,
    validate_ocr_result,
    validate_result,
    _scan_secrets,
    _scan_private_paths,
)


def _make_transcribe_job(chunk: dict = None) -> ProcessingJob:
    return ProcessingJob(
        job_id=str(uuid.uuid4()),
        batch_id=str(uuid.uuid4()),
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
        status=JobStatus.COMPLETED,
        chunk=chunk or {
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 60.0,
            "source_hash": "correct_hash",
            "overlap_start": 0.0,
            "overlap_end": 0.0,
        },
    )


def _make_ocr_job(chunk: dict = None) -> ProcessingJob:
    return ProcessingJob(
        job_id=str(uuid.uuid4()),
        batch_id=str(uuid.uuid4()),
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.OCR_IMAGE,
        processing_mode=ProcessingMode.LOCAL,
        status=JobStatus.COMPLETED,
        chunk=chunk or {
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 10,
            "document_hash": "doc_hash_correct",
        },
    )


# ── Test 19: hash incorrecto -> FAILED_VALIDATION ─────────────────────────────

def test_validacion_hash_incorrecto():
    """source_hash incorrecto en resultado -> validacion falla."""
    job = _make_transcribe_job()
    result = {
        "text": "Texto",
        "source_hash": "HASH_INCORRECTO",  # != correct_hash
        "provider": "mock",
    }
    vr = validate_transcription_result(result, job)
    assert not vr.valid
    assert any("source_hash" in e or "hash" in e.lower() for e in vr.errors)


def test_validacion_hash_correcto():
    """source_hash correcto -> pasa validacion."""
    job = _make_transcribe_job()
    result = {
        "text": "Texto",
        "source_hash": "correct_hash",
        "provider": "mock",
    }
    vr = validate_transcription_result(result, job)
    assert vr.valid, f"Errores: {vr.errors}"


# ── Test 20: rango de paginas invalido -> FAILED_VALIDATION ──────────────────

def test_validacion_rango_paginas_invalido():
    """page_start > page_end en el chunk -> validacion falla."""
    job = _make_ocr_job(chunk={
        "chunk_index": 0,
        "page_start": 20,
        "page_end": 5,  # invalido: inicio > fin
        "document_hash": "doc_hash",
    })
    result = {"text": "OCR", "document_hash": "doc_hash"}
    vr = validate_ocr_result(result, job)
    assert not vr.valid
    assert any("pagina" in e.lower() or "page" in e.lower() for e in vr.errors)


def test_validacion_rango_resultado_invalido():
    """page_start > page_end en el resultado -> validacion falla."""
    job = _make_ocr_job()
    result = {
        "text": "OCR",
        "document_hash": "doc_hash_correct",
        "page_start": 15,
        "page_end": 5,  # invalido
    }
    vr = validate_ocr_result(result, job)
    assert not vr.valid


# ── Test 21: timestamps invalidos -> FAILED_VALIDATION ───────────────────────

def test_validacion_timestamps_invalidos():
    """start > end en resultado -> validacion falla."""
    job = _make_transcribe_job()
    result = {
        "text": "Texto",
        "source_hash": "correct_hash",
        "start": 50.0,
        "end": 10.0,  # invalido: inicio > fin
    }
    vr = validate_transcription_result(result, job)
    assert not vr.valid
    assert any("timestamp" in e.lower() or "start" in e.lower() or "invalido" in e.lower() for e in vr.errors)


def test_validacion_timestamps_correctos():
    """Timestamps validos -> pasa."""
    job = _make_transcribe_job()
    result = {
        "text": "Texto",
        "source_hash": "correct_hash",
        "start": 0.0,
        "end": 60.0,
    }
    vr = validate_transcription_result(result, job)
    assert vr.valid, f"Errores: {vr.errors}"


# ── Tests de secretos y rutas privadas ───────────────────────────────────────

def test_scan_secretos_detecta_nvapi():
    """Detector de secretos encuentra tokens NVIDIA."""
    hits = _scan_secrets("nvapi-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef")
    assert len(hits) > 0


def test_scan_secretos_resultado_limpio():
    """Resultado limpio no activa detector."""
    hits = _scan_secrets({"text": "Texto sin secretos", "source_hash": "abc"})
    assert len(hits) == 0


def test_scan_rutas_privadas_detecta_home():
    """Detector de rutas privadas encuentra /home/user/."""
    hits = _scan_private_paths("/home/ia02/S9-Knowledge/state/data.db")
    assert len(hits) > 0


def test_scan_ip_interna():
    """Detector encuentra IPs de red interna."""
    hits = _scan_private_paths("http://192.168.1.157:8000/api")
    assert len(hits) > 0


def test_validacion_con_secretos_falla():
    """Resultado con secreto detectado -> FAILED_VALIDATION."""
    job = _make_transcribe_job()
    result = {
        "text": "Transcripcion",
        "source_hash": "correct_hash",
        "api_key": "nvapi-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
    }
    vr = validate_transcription_result(result, job)
    assert not vr.valid
    assert any("secreto" in e.lower() or "secret" in e.lower() for e in vr.errors)


def test_validate_result_sin_resultado_falla():
    """Job sin result -> FAILED_VALIDATION."""
    job = _make_transcribe_job()
    job = job.copy(update={"result": None, "status": JobStatus.COMPLETED})
    job_valid, vr = validate_result(job.transition_to(JobStatus.VALIDATING))
    assert not vr.valid
    assert job_valid.status == JobStatus.FAILED_VALIDATION

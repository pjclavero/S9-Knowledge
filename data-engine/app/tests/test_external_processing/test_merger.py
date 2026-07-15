# -*- coding: utf-8 -*-
"""Tests del merger de resultados (Fase B1).

Tests 22-24: union de audio, OCR, resultado parcial.
"""
import uuid
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.models import ExternalTaskType, JobStatus, ProcessingJob, ProcessingMode
from external_processing.result_merger import (
    _merge_transcription_segments,
    _merge_ocr_pages,
    merge_batch_results,
)


def _ready_transcribe_job(chunk_index: int, start: float, end: float, text: str) -> ProcessingJob:
    return ProcessingJob(
        job_id=str(uuid.uuid4()),
        batch_id="batch_001",
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
        status=JobStatus.READY,
        chunk={
            "chunk_index": chunk_index,
            "chunk_start": start,
            "chunk_end": end,
            "overlap_start": 2.0 if chunk_index > 0 else 0.0,
            "overlap_end": 2.0,
            "source_hash": "src_hash",
        },
        result={
            "text": text,
            "source_hash": "src_hash",
            "language": "es",
            "start": start,
            "end": end,
        },
    )


def _ready_ocr_job(chunk_index: int, page_start: int, page_end: int, text: str) -> ProcessingJob:
    return ProcessingJob(
        job_id=str(uuid.uuid4()),
        batch_id="batch_001",
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.OCR_IMAGE,
        processing_mode=ProcessingMode.LOCAL,
        status=JobStatus.READY,
        chunk={
            "chunk_index": chunk_index,
            "page_start": page_start,
            "page_end": page_end,
            "document_hash": "doc_hash",
        },
        result={
            "text": text,
            "document_hash": "doc_hash",
            "page_start": page_start,
            "page_end": page_end,
        },
    )


# ── Test 22: union de audio con overlap correcto ─────────────────────────────

def test_merger_audio_elimina_overlap():
    """Union de segmentos de audio elimina el solapamiento."""
    jobs = [
        _ready_transcribe_job(0, 0.0, 602.0, "Primer segmento"),
        _ready_transcribe_job(1, 600.0, 1200.0, "Segundo segmento"),
    ]

    segments, gaps = _merge_transcription_segments(jobs, overlap_tolerance=0.5)
    assert len(segments) == 2
    # No hay gaps entre segmentos continuos
    # Los segmentos estan ordenados por tiempo
    assert segments[0]["start"] <= segments[1]["start"]


def test_merger_audio_preserva_speaker():
    """Merger preserva el speaker si esta presente en el resultado."""
    job = _ready_transcribe_job(0, 0.0, 60.0, "Texto")
    job = job.copy(update={"result": {**job.result, "speaker": "speaker_a"}})

    segments, _ = _merge_transcription_segments([job])
    assert segments[0]["speaker"] == "speaker_a"


def test_merger_audio_ordena_por_tiempo():
    """Los segmentos se ordenan por chunk_start, no por orden de llegada."""
    jobs = [
        _ready_transcribe_job(1, 600.0, 1200.0, "Segundo"),
        _ready_transcribe_job(0, 0.0, 602.0, "Primero"),
    ]
    segments, _ = _merge_transcription_segments(jobs)
    assert segments[0]["text"] == "Primero"
    assert segments[1]["text"] == "Segundo"


# ── Test 23: union de OCR por paginas ────────────────────────────────────────

def test_merger_ocr_orden_paginas():
    """Union de OCR ordena por pagina."""
    jobs = [
        _ready_ocr_job(1, 21, 40, "Segunda parte"),
        _ready_ocr_job(0, 1, 20, "Primera parte"),
    ]
    segments, gaps = _merge_ocr_pages(jobs)
    assert len(segments) == 2
    assert segments[0]["page_start"] == 1
    assert segments[1]["page_start"] == 21
    assert len(gaps) == 0


def test_merger_ocr_detecta_gap_paginas():
    """Merger detecta paginas faltantes entre chunks."""
    jobs = [
        _ready_ocr_job(0, 1, 10, "Primera parte"),
        _ready_ocr_job(1, 15, 20, "Tercera parte"),  # gap: paginas 11-14
    ]
    segments, gaps = _merge_ocr_pages(jobs)
    assert len(gaps) == 1
    assert gaps[0]["gap_page_start"] == 11
    assert gaps[0]["gap_page_end"] == 14


# ── Test 24: resultado parcial -> merger detecta gaps ────────────────────────

def test_merger_detecta_resultado_parcial():
    """Merger reporta gaps cuando hay jobs fallidos entre completados."""
    jobs_completados = [
        _ready_transcribe_job(0, 0.0, 300.0, "Primer bloque"),
        # Falta chunk 1 (300-600s)
        _ready_transcribe_job(2, 600.0, 900.0, "Tercer bloque"),
    ]
    # El job 1 fallido no tiene resultado, no esta READY
    job_fallido = ProcessingJob(
        job_id=str(uuid.uuid4()),
        batch_id="batch_001",
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
        status=JobStatus.FAILED,
        chunk={
            "chunk_index": 1,
            "chunk_start": 300.0,
            "chunk_end": 600.0,
            "overlap_start": 2.0,
            "overlap_end": 2.0,
            "source_hash": "src_hash",
        },
    )

    merged = merge_batch_results(
        batch_id="batch_001",
        workspace="ws",
        source_id="src",
        source_hash="src_hash",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        jobs=jobs_completados + [job_fallido],
    )

    assert merged.status == "READY_FOR_LOCAL_PIPELINE"
    assert merged.failed_jobs >= 1
    # Los gaps deben detectarse
    assert len(merged.gaps_detected) >= 1


def test_merger_resultado_final_ready_for_pipeline():
    """El estado final siempre es READY_FOR_LOCAL_PIPELINE."""
    jobs = [_ready_transcribe_job(0, 0.0, 60.0, "Test")]
    merged = merge_batch_results("b", "ws", "src", "h", ExternalTaskType.TRANSCRIBE_AUDIO, jobs)
    assert merged.status == "READY_FOR_LOCAL_PIPELINE"


def test_merger_no_invoca_neo4j():
    """Merger no invoca ni importa modulos de Neo4j."""
    import sys
    before_modules = set(sys.modules.keys())
    jobs = [_ready_transcribe_job(0, 0.0, 60.0, "Test")]
    merge_batch_results("b", "ws", "src", "h", ExternalTaskType.TRANSCRIBE_AUDIO, jobs)
    after_modules = set(sys.modules.keys())
    new_modules = after_modules - before_modules
    neo4j_mods = [m for m in new_modules if "neo4j" in m.lower() or "graph" in m.lower()]
    assert len(neo4j_mods) == 0, f"Modulos Neo4j importados: {neo4j_mods}"

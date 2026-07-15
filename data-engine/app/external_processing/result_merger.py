# -*- coding: utf-8 -*-
"""Union de segmentos de procesamiento externo (Fase B1).

Audio: une segmentos por timestamps, elimina duplicados de overlap,
       preserva speaker, detecta gaps.
PDF/OCR: une por documento, pagina, orden de lectura.
Texto: preserva offsets, segment IDs, evidencias.

Estado final: READY_FOR_LOCAL_PIPELINE
NUNCA llama a ingest_approved ni Neo4j.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from external_processing.models import (
    ExternalTaskType,
    JobStatus,
    MergedResult,
    ProcessingJob,
)


# ── Merger de audio ───────────────────────────────────────────────────────────

def _merge_transcription_segments(
    jobs: List[ProcessingJob],
    overlap_tolerance: float = 0.5,
) -> Tuple[List[Dict], List[Dict]]:
    """Une segmentos de transcripcion ordenados por chunk_start.

    Elimina duplicados de overlap (texto repetido al inicio del siguiente chunk).
    Detecta gaps entre segmentos.
    """
    # Ordenar por chunk_start
    timed_jobs = []
    for job in jobs:
        if job.status != JobStatus.READY or job.result is None:
            continue
        chunk = job.chunk or {}
        chunk_start = float(chunk.get("chunk_start", 0.0))
        overlap_end = float(chunk.get("overlap_end", 0.0))
        timed_jobs.append((chunk_start, overlap_end, job))

    timed_jobs.sort(key=lambda x: x[0])

    segments = []
    gaps = []
    prev_end: Optional[float] = None

    for chunk_start, overlap_end, job in timed_jobs:
        result = job.result
        text = result.get("text", "").strip()
        chunk_end = float((job.chunk or {}).get("chunk_end", chunk_start))
        overlap_start = float((job.chunk or {}).get("overlap_start", 0.0))

        # Ajustar inicio para eliminar solapamiento con segmento anterior
        effective_start = chunk_start + overlap_start if chunk_start > 0 else chunk_start
        effective_end = chunk_end - overlap_end

        # Detectar gap
        if prev_end is not None and effective_start > prev_end + overlap_tolerance:
            gaps.append({
                "gap_start": prev_end,
                "gap_end": effective_start,
                "duration_seconds": effective_start - prev_end,
            })

        segments.append({
            "chunk_index": (job.chunk or {}).get("chunk_index", 0),
            "start": effective_start,
            "end": effective_end,
            "text": text,
            "speaker": result.get("speaker"),
            "language": result.get("language"),
            "confidence": result.get("confidence"),
            "source_job_id": job.job_id,
        })

        prev_end = effective_end

    return segments, gaps


# ── Merger de OCR ─────────────────────────────────────────────────────────────

def _merge_ocr_pages(jobs: List[ProcessingJob]) -> Tuple[List[Dict], List[Dict]]:
    """Une paginas de OCR en orden de lectura. Detecta paginas faltantes."""
    paged_jobs = []
    for job in jobs:
        if job.status != JobStatus.READY or job.result is None:
            continue
        chunk = job.chunk or {}
        page_start = int(chunk.get("page_start", 1))
        paged_jobs.append((page_start, job))

    paged_jobs.sort(key=lambda x: x[0])

    segments = []
    gaps = []
    prev_page_end: Optional[int] = None

    for page_start, job in paged_jobs:
        result = job.result
        chunk = job.chunk or {}
        page_end = int(chunk.get("page_end", page_start))

        # Detectar paginas faltantes
        if prev_page_end is not None and page_start > prev_page_end + 1:
            gaps.append({
                "gap_page_start": prev_page_end + 1,
                "gap_page_end": page_start - 1,
                "pages_missing": page_start - prev_page_end - 1,
            })

        segments.append({
            "chunk_index": chunk.get("chunk_index", 0),
            "page_start": page_start,
            "page_end": page_end,
            "text": result.get("text", ""),
            "blocks": result.get("blocks", []),
            "document_hash": result.get("document_hash", ""),
            "source_job_id": job.job_id,
        })

        prev_page_end = page_end

    return segments, gaps


# ── Merger de texto ───────────────────────────────────────────────────────────

def _merge_text_segments(jobs: List[ProcessingJob]) -> Tuple[List[Dict], List[Dict]]:
    """Une chunks de texto preservando offsets y evidencias."""
    offset_jobs = []
    for job in jobs:
        if job.status != JobStatus.READY or job.result is None:
            continue
        chunk = job.chunk or {}
        offset_start = int(chunk.get("offset_start", 0))
        offset_jobs.append((offset_start, job))

    offset_jobs.sort(key=lambda x: x[0])

    segments = []
    gaps = []
    prev_offset_end: Optional[int] = None

    for offset_start, job in offset_jobs:
        result = job.result
        chunk = job.chunk or {}
        offset_end = int(chunk.get("offset_end", offset_start))

        if prev_offset_end is not None and offset_start > prev_offset_end:
            gaps.append({
                "gap_offset_start": prev_offset_end,
                "gap_offset_end": offset_start,
                "chars_missing": offset_start - prev_offset_end,
            })

        segments.append({
            "chunk_index": chunk.get("chunk_index", 0),
            "offset_start": offset_start,
            "offset_end": offset_end,
            "entities": result.get("entities", []),
            "segment_id": chunk.get("segment_id"),
            "source_job_id": job.job_id,
        })

        prev_offset_end = offset_end

    return segments, gaps


# ── Merger principal ──────────────────────────────────────────────────────────

def merge_batch_results(
    batch_id: str,
    workspace: str,
    source_id: str,
    source_hash: str,
    task_type: ExternalTaskType,
    jobs: List[ProcessingJob],
    provider: str = "",
    model: str = "",
) -> MergedResult:
    """Fusiona los resultados de todos los jobs completados del batch.

    Estado final siempre READY_FOR_LOCAL_PIPELINE.
    NUNCA escribe en Neo4j. NUNCA llama a ingest_approved.
    """
    ready_jobs = [j for j in jobs if j.status == JobStatus.READY]
    failed_jobs = [j for j in jobs if j.status in (JobStatus.FAILED, JobStatus.FAILED_VALIDATION)]

    if task_type == ExternalTaskType.TRANSCRIBE_AUDIO:
        segments, gaps = _merge_transcription_segments(ready_jobs)
    elif task_type == ExternalTaskType.OCR_IMAGE:
        segments, gaps = _merge_ocr_pages(ready_jobs)
    elif task_type == ExternalTaskType.TEXT_EXTRACT:
        segments, gaps = _merge_text_segments(ready_jobs)
    else:
        # Merger generico: recopilar resultados como lista
        segments = []
        gaps = []
        for job in ready_jobs:
            if job.result:
                segments.append({
                    "job_id": job.job_id,
                    "task_type": task_type.value,
                    "result": job.result,
                })

    return MergedResult(
        batch_id=batch_id,
        workspace=workspace,
        source_id=source_id,
        source_hash=source_hash,
        status="READY_FOR_LOCAL_PIPELINE",
        task_type=task_type,
        segments=segments,
        gaps_detected=gaps,
        total_jobs=len(jobs),
        completed_jobs=len(ready_jobs),
        failed_jobs=len(failed_jobs),
        provider=provider,
        model=model,
    )

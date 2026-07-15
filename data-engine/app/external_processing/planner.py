# -*- coding: utf-8 -*-
"""Planificador de modo de procesamiento (Fase B1).

Determina si el procesamiento debe ser local, hybrid o burst en base
a la carga de la fuente y los umbrales configurables por entorno.

Variables de entorno:
    S9K_PROCESSING_MODE         auto | local | hybrid | burst
    S9K_LOCAL_MAX_AUDIO_MINUTES  30
    S9K_LOCAL_MAX_PDF_PAGES      20
    S9K_LOCAL_MAX_IMAGES         10
    S9K_BURST_MIN_AUDIO_MINUTES  120
    S9K_BURST_MIN_PDF_PAGES      60
    S9K_BURST_MIN_IMAGES         30
    S9K_EXTERNAL_MAX_CONCURRENCY 4
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from external_processing.models import (
    AudioChunk,
    ExternalTaskType,
    ImageTask,
    PDFChunk,
    ProcessingJob,
    ProcessingMode,
    ProcessingPlan,
    TextChunk,
)
from external_processing.manifests import BatchFile, BatchManifest
from external_processing.chunking import chunk_audio, chunk_pdf, chunk_images, chunk_text, chunk_range_key
from external_processing.cache import ProcessingCache, build_cache_key

# ── Configuracion ─────────────────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _processing_mode() -> ProcessingMode:
    raw = os.environ.get("S9K_PROCESSING_MODE", "auto").strip().lower()
    try:
        return ProcessingMode(raw)
    except ValueError:
        return ProcessingMode.AUTO


class PlannerConfig:
    def __init__(self):
        self.mode = _processing_mode()
        self.local_max_audio_minutes = _env_float("S9K_LOCAL_MAX_AUDIO_MINUTES", 30.0)
        self.local_max_pdf_pages = _env_int("S9K_LOCAL_MAX_PDF_PAGES", 20)
        self.local_max_images = _env_int("S9K_LOCAL_MAX_IMAGES", 10)
        self.burst_min_audio_minutes = _env_float("S9K_BURST_MIN_AUDIO_MINUTES", 120.0)
        self.burst_min_pdf_pages = _env_int("S9K_BURST_MIN_PDF_PAGES", 60)
        self.burst_min_images = _env_int("S9K_BURST_MIN_IMAGES", 30)
        self.max_concurrency = _env_int("S9K_EXTERNAL_MAX_CONCURRENCY", 4)


# ── Calculo de carga ──────────────────────────────────────────────────────────

class SourceLoad:
    """Carga calculada de una fuente."""

    def __init__(self):
        self.audio_minutes: float = 0.0
        self.pdf_pages: int = 0
        self.images: int = 0
        self.total_size_bytes: int = 0

    def add_file(self, bf: BatchFile) -> None:
        if bf.duration_seconds is not None:
            self.audio_minutes += bf.duration_seconds / 60.0
        if bf.pages is not None:
            self.pdf_pages += bf.pages
        if bf.image_count is not None:
            self.images += bf.image_count
        self.total_size_bytes += bf.size_bytes


def _select_mode(load: SourceLoad, cfg: PlannerConfig) -> tuple[ProcessingMode, list[str]]:
    """Selecciona el modo y devuelve (modo, reason_codes)."""
    if cfg.mode != ProcessingMode.AUTO:
        return cfg.mode, [f"MODE_OVERRIDE_{cfg.mode.value.upper()}"]

    reason_codes: list[str] = []

    # Verificar si supera umbral de burst
    if load.audio_minutes >= cfg.burst_min_audio_minutes:
        reason_codes.append("AUDIO_DURATION_EXCEEDS_BURST_THRESHOLD")
    if load.pdf_pages >= cfg.burst_min_pdf_pages:
        reason_codes.append("PDF_PAGES_EXCEEDS_BURST_THRESHOLD")
    if load.images >= cfg.burst_min_images:
        reason_codes.append("IMAGE_COUNT_EXCEEDS_BURST_THRESHOLD")

    if reason_codes:
        return ProcessingMode.BURST, reason_codes

    # Verificar si supera umbral local (-> hybrid)
    if load.audio_minutes > cfg.local_max_audio_minutes:
        reason_codes.append("AUDIO_DURATION_EXCEEDS_LOCAL_LIMIT")
    if load.pdf_pages > cfg.local_max_pdf_pages:
        reason_codes.append("PDF_PAGES_EXCEEDS_LOCAL_LIMIT")
    if load.images > cfg.local_max_images:
        reason_codes.append("IMAGE_COUNT_EXCEEDS_LOCAL_LIMIT")

    if reason_codes:
        return ProcessingMode.HYBRID, reason_codes

    return ProcessingMode.LOCAL, ["WITHIN_LOCAL_LIMITS"]


# ── Estimacion de tiempo ──────────────────────────────────────────────────────

# Velocidades aproximadas locales (segundos de procesamiento por unidad)
_LOCAL_SPEED = {
    "audio_minute": 12.0,    # 12s de CPU por minuto de audio (faster-whisper)
    "pdf_page": 1.5,          # 1.5s por pagina PDF
    "image": 3.0,             # 3s por imagen
}


def _estimate_local_seconds(load: SourceLoad, has_metrics: bool = False) -> tuple[float, str]:
    """Estima el tiempo local. Devuelve (segundos, confidence)."""
    if not has_metrics:
        estimate = (
            load.audio_minutes * _LOCAL_SPEED["audio_minute"] +
            load.pdf_pages * _LOCAL_SPEED["pdf_page"] +
            load.images * _LOCAL_SPEED["image"]
        )
        return estimate, "ESTIMATE_LOW_CONFIDENCE"
    # Con metricas historicas la confianza seria HIGH; en B1 no las tenemos
    estimate = (
        load.audio_minutes * _LOCAL_SPEED["audio_minute"] +
        load.pdf_pages * _LOCAL_SPEED["pdf_page"] +
        load.images * _LOCAL_SPEED["image"]
    )
    return estimate, "HIGH"


# ── Generacion de jobs ────────────────────────────────────────────────────────

def _jobs_for_audio(
    batch_id: str,
    workspace: str,
    source_id: str,
    bf: BatchFile,
    mode: ProcessingMode,
    cache: ProcessingCache,
    provider: str = "mock",
    model: str = "mock-asr",
) -> List[ProcessingJob]:
    duration = bf.duration_seconds or 0.0
    chunks = chunk_audio(bf.file_hash, duration)
    jobs = []
    for chunk in chunks:
        cr = chunk_range_key(chunk)
        cache_k = build_cache_key(bf.file_hash, ExternalTaskType.TRANSCRIBE_AUDIO, cr, provider, model)
        cached = cache.get(cache_k)
        job = ProcessingJob(
            batch_id=batch_id,
            workspace=workspace,
            source_id=source_id,
            task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
            processing_mode=mode,
            provider=provider,
            model=model,
            chunk=chunk.dict(),
            cache_hit=cached is not None,
            result=cached["result"] if cached else None,
        )
        if cached:
            from external_processing.models import JobStatus
            job = job.copy(update={"status": JobStatus.READY})
        jobs.append(job)
    return jobs


def _jobs_for_pdf(
    batch_id: str,
    workspace: str,
    source_id: str,
    bf: BatchFile,
    mode: ProcessingMode,
    cache: ProcessingCache,
    provider: str = "mock",
    model: str = "mock-ocr",
) -> List[ProcessingJob]:
    pages = bf.pages or 0
    chunks = chunk_pdf(bf.file_hash, pages)
    jobs = []
    for chunk in chunks:
        cr = chunk_range_key(chunk)
        cache_k = build_cache_key(bf.file_hash, ExternalTaskType.OCR_IMAGE, cr, provider, model)
        cached = cache.get(cache_k)
        job = ProcessingJob(
            batch_id=batch_id,
            workspace=workspace,
            source_id=source_id,
            task_type=ExternalTaskType.OCR_IMAGE,
            processing_mode=mode,
            provider=provider,
            model=model,
            chunk=chunk.dict(),
            cache_hit=cached is not None,
            result=cached["result"] if cached else None,
        )
        if cached:
            from external_processing.models import JobStatus
            job = job.copy(update={"status": JobStatus.READY})
        jobs.append(job)
    return jobs


def _jobs_for_images(
    batch_id: str,
    workspace: str,
    source_id: str,
    bf: BatchFile,
    mode: ProcessingMode,
    cache: ProcessingCache,
    image_paths: Optional[List[str]] = None,
    provider: str = "mock",
    model: str = "mock-vision",
) -> List[ProcessingJob]:
    image_count = bf.image_count or 0
    paths = image_paths or [f"image_{i}" for i in range(image_count)]
    tasks = chunk_images(bf.file_hash, paths)
    jobs = []
    for task in tasks:
        cr = chunk_range_key(task)
        cache_k = build_cache_key(bf.file_hash, ExternalTaskType.IMAGE_ANALYSIS, cr, provider, model)
        cached = cache.get(cache_k)
        job = ProcessingJob(
            batch_id=batch_id,
            workspace=workspace,
            source_id=source_id,
            task_type=ExternalTaskType.IMAGE_ANALYSIS,
            processing_mode=mode,
            provider=provider,
            model=model,
            chunk=task.dict(),
            cache_hit=cached is not None,
            result=cached["result"] if cached else None,
        )
        if cached:
            from external_processing.models import JobStatus
            job = job.copy(update={"status": JobStatus.READY})
        jobs.append(job)
    return jobs


# ── Planner principal ─────────────────────────────────────────────────────────

class BurstPlanner:
    """Planificador de procesamiento elastico por rafaga."""

    def __init__(self, repo_root: Path, cfg: Optional[PlannerConfig] = None):
        self.repo_root = Path(repo_root)
        self.cfg = cfg or PlannerConfig()
        self.cache = ProcessingCache(self.repo_root)

    def plan(
        self,
        workspace: str,
        source_id: str,
        source_path: str,
        source_hash: str,
        files: List[BatchFile],
        mode_override: Optional[ProcessingMode] = None,
        provider: str = "mock",
        dry_run: bool = True,
    ) -> ProcessingPlan:
        """Genera un plan de procesamiento para la fuente dada."""
        # Calcular carga
        load = SourceLoad()
        for f in files:
            load.add_file(f)

        # Seleccionar modo
        if mode_override and mode_override != ProcessingMode.AUTO:
            selected_mode = mode_override
            reason_codes = [f"MODE_OVERRIDE_{mode_override.value.upper()}"]
        else:
            selected_mode, reason_codes = _select_mode(load, self.cfg)

        # Estimar tiempo local
        est_secs, confidence = _estimate_local_seconds(load, has_metrics=False)

        batch_id = str(uuid.uuid4())

        # Generar jobs para cada archivo
        all_jobs: List[ProcessingJob] = []
        for bf in files:
            mime = bf.mime_type.lower()
            if "audio" in mime or "video" in mime:
                all_jobs.extend(_jobs_for_audio(
                    batch_id, workspace, source_id, bf, selected_mode, self.cache, provider
                ))
            elif "pdf" in mime:
                all_jobs.extend(_jobs_for_pdf(
                    batch_id, workspace, source_id, bf, selected_mode, self.cache, provider
                ))
            elif "image" in mime:
                all_jobs.extend(_jobs_for_images(
                    batch_id, workspace, source_id, bf, selected_mode, self.cache, provider
                ))

        # Construir manifiesto
        manifest = BatchManifest(
            batch_id=batch_id,
            workspace=workspace,
            source_id=source_id,
            mode=selected_mode,
            source_hash=source_hash,
            files=files,
            jobs=[j.job_id for j in all_jobs],
            status="planned",
            dry_run=dry_run,
            total_audio_minutes=load.audio_minutes,
            total_pdf_pages=load.pdf_pages,
            total_images=load.images,
            total_size_bytes=load.total_size_bytes,
        )

        plan = ProcessingPlan(
            batch_id=batch_id,
            workspace=workspace,
            source_id=source_id,
            source_path=source_path,
            source_hash=source_hash,
            mode=self.cfg.mode,
            selected_mode=selected_mode,
            reason_codes=reason_codes,
            estimated_local_seconds=est_secs,
            estimate_confidence=confidence,
            jobs=all_jobs,
            dry_run=dry_run,
        )

        return plan

    def explain(self, plan: ProcessingPlan) -> dict:
        """Devuelve la explicacion del plan en formato serializable."""
        return {
            "batch_id": plan.batch_id,
            "selected_mode": plan.selected_mode.value,
            "reason_codes": plan.reason_codes,
            "estimated_local_seconds": plan.estimated_local_seconds,
            "estimate_confidence": plan.estimate_confidence,
            "total_jobs": len(plan.jobs),
            "cache_hits": sum(1 for j in plan.jobs if j.cache_hit),
            "dry_run": plan.dry_run,
        }

# -*- coding: utf-8 -*-
"""Modelos Pydantic para el subsistema de procesamiento externo (Fase B1).

Separados de external_ai/models.py: contrato independiente para procesamiento
de medios (transcripcion, OCR, analisis de imagen, embeddings, reranking).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

try:
    from pydantic import BaseModel, Field, validator, root_validator
    _PYDANTIC_V2 = False
    try:
        from pydantic import model_validator
        _PYDANTIC_V2 = True
    except ImportError:
        pass
except ImportError:
    raise ImportError("pydantic es requerido para external_processing")

from external_processing.errors import ErrorCode


# ── Tipos de tarea ────────────────────────────────────────────────────────────

class ExternalTaskType(str, Enum):
    TRANSCRIBE_AUDIO = "external_transcribe"
    OCR_IMAGE = "external_ocr"
    IMAGE_ANALYSIS = "external_image_analysis"
    TEXT_EXTRACT = "external_text_extract"
    EMBEDDINGS = "external_embeddings"
    RERANK = "external_rerank"
    REVIEW = "external_review"


# ── Estados y maquina de estados ─────────────────────────────────────────────

class JobStatus(str, Enum):
    DETECTED = "detected"
    PLANNED = "planned"
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    COMPLETED = "completed"
    VALIDATING = "validating"
    READY = "ready"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    FAILED_VALIDATION = "failed_validation"
    CANCELLED = "cancelled"


# Transiciones validas (origen -> conjunto de destinos permitidos)
VALID_TRANSITIONS: Dict[JobStatus, set] = {
    JobStatus.DETECTED:     {JobStatus.PLANNED, JobStatus.CANCELLED},
    JobStatus.PLANNED:      {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.QUEUED:       {JobStatus.DISPATCHING, JobStatus.CANCELLED},
    JobStatus.DISPATCHING:  {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.RUNNING:      {JobStatus.COMPLETED, JobStatus.RETRY_WAIT, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED:    {JobStatus.VALIDATING},
    JobStatus.VALIDATING:   {JobStatus.READY, JobStatus.FAILED_VALIDATION},
    JobStatus.READY:        set(),  # estado terminal: ninguna modificacion permitida
    JobStatus.RETRY_WAIT:   {JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.FAILED:       set(),  # terminal (retry explicito necesario)
    JobStatus.FAILED_VALIDATION: set(),  # terminal
    JobStatus.CANCELLED:    set(),  # terminal
}


def validate_transition(current: JobStatus, next_status: JobStatus) -> None:
    """Lanza ValueError si la transicion no esta permitida."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if next_status not in allowed:
        raise ValueError(
            f"Transicion invalida: {current.value} -> {next_status.value}. "
            f"Permitidas: {[s.value for s in allowed]}"
        )


# ── Modo de procesamiento ──────────────────────────────────────────────────────

class ProcessingMode(str, Enum):
    LOCAL = "local"
    HYBRID = "hybrid"
    BURST = "burst"
    AUTO = "auto"


# ── Modelos de chunk ───────────────────────────────────────────────────────────

class AudioChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chunk_index: int
    chunk_start: float  # segundos
    chunk_end: float    # segundos
    overlap_start: float = 0.0  # solapamiento con chunk anterior (segundos)
    overlap_end: float = 0.0    # solapamiento con chunk siguiente (segundos)
    source_hash: str
    audio_hash: str = ""
    duration_seconds: float = 0.0
    expected_language: Optional[str] = None


class PDFChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chunk_index: int
    page_start: int
    page_end: int
    document_hash: str
    chapter_hint: Optional[str] = None
    page_count: int = 0

    def __init__(self, **data):
        super().__init__(**data)
        if self.page_count == 0:
            object.__setattr__(self, 'page_count', self.page_end - self.page_start + 1)


class TextChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chunk_index: int
    offset_start: int   # caracter
    offset_end: int     # caracter
    source_hash: str
    segment_id: Optional[str] = None
    char_count: int = 0


class ImageTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_index: int
    source_hash: str
    image_hash: str = ""
    mime_type: str = "image/jpeg"


# ── Processing Job ─────────────────────────────────────────────────────────────

class ProcessingJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    workspace: str
    source_id: str
    task_type: ExternalTaskType
    status: JobStatus = JobStatus.DETECTED
    provider: Optional[str] = None
    model: Optional[str] = None
    processing_mode: ProcessingMode = ProcessingMode.LOCAL
    chunk: Optional[Dict[str, Any]] = None
    payload: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempt: int = 0
    max_attempts: int = 3
    next_retry_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    latency_ms: Optional[float] = None
    cache_hit: bool = False
    progress: float = 0.0  # 0.0 - 1.0

    def transition_to(self, new_status: JobStatus) -> "ProcessingJob":
        """Devuelve nueva instancia con estado actualizado, validando la transicion."""
        validate_transition(self.status, new_status)
        now = datetime.now(timezone.utc)
        updates = {"status": new_status, "updated_at": now}
        if new_status == JobStatus.RUNNING and self.started_at is None:
            updates["started_at"] = now
        if new_status in (JobStatus.READY, JobStatus.FAILED, JobStatus.FAILED_VALIDATION,
                          JobStatus.CANCELLED):
            updates["finished_at"] = now
        return self.copy(update=updates)


# ── Resultado normalizado ──────────────────────────────────────────────────────

class TranscriptionResult(BaseModel):
    job_id: str
    chunk_index: int
    chunk_start: float
    chunk_end: float
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    speaker: Optional[str] = None
    source_hash: str
    provider: str
    model: str


class OCRResult(BaseModel):
    job_id: str
    chunk_index: int
    page_start: int
    page_end: int
    text: str
    blocks: List[Dict[str, Any]] = Field(default_factory=list)
    document_hash: str
    provider: str
    model: str


class TextExtractResult(BaseModel):
    job_id: str
    chunk_index: int
    offset_start: int
    offset_end: int
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    source_hash: str
    provider: str
    model: str


class EmbeddingResult(BaseModel):
    job_id: str
    text_hash: str
    embedding: List[float]
    model: str
    provider: str


class MergedResult(BaseModel):
    batch_id: str
    workspace: str
    source_id: str
    source_hash: str
    status: Literal["READY_FOR_LOCAL_PIPELINE"] = "READY_FOR_LOCAL_PIPELINE"
    task_type: ExternalTaskType
    segments: List[Dict[str, Any]] = Field(default_factory=list)
    gaps_detected: List[Dict[str, Any]] = Field(default_factory=list)
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    merged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""


# ── Plan de procesamiento ──────────────────────────────────────────────────────

class ProcessingPlan(BaseModel):
    batch_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace: str
    source_id: str
    source_path: str
    source_hash: str
    mode: ProcessingMode
    selected_mode: ProcessingMode
    reason_codes: List[str] = Field(default_factory=list)
    estimated_local_seconds: Optional[float] = None
    estimate_confidence: str = "HIGH"  # HIGH / ESTIMATE_LOW_CONFIDENCE
    jobs: List[ProcessingJob] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    planner_version: str = "B1.0"
    policy_version: str = "B1.0"
    dry_run: bool = False


# ── Report de batch ────────────────────────────────────────────────────────────

class BatchReport(BaseModel):
    batch_id: str
    workspace: str
    source_id: str
    mode: ProcessingMode
    total_jobs: int
    completed: int
    failed: int
    failed_validation: int
    retried: int
    cache_hits: int
    cancelled: int
    elapsed_seconds: float
    result: Optional[MergedResult] = None
    neo4j_calls: int = 0
    ingest_approved_calls: int = 0
    approved_payload_generated: bool = False

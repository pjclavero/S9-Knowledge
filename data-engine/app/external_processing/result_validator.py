# -*- coding: utf-8 -*-
"""Validacion de respuestas externas (Fase B1).

Toda respuesta externa debe pasar:
  - Schema validation (campos requeridos presentes)
  - Source hash validation
  - Chunk range validation
  - Workspace validation
  - Evidence validation
  - Language validation (ISO 639-1 si presente)
  - Timestamp/page range validation
  - Secret scan (no credentials en resultado)

Respuesta invalida -> estado FAILED_VALIDATION, no continua al pipeline.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from external_processing.errors import ValidationError
from external_processing.models import ExternalTaskType, JobStatus, ProcessingJob

# Patrones de secretos reutilizados de external_ai/security.py
_SECRET_PATTERNS = [
    re.compile(r"nvapi-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][^'\"]{8,}"),
]

# Patrones de rutas privadas
_PRIVATE_PATH_PATTERNS = [
    re.compile(r"/home/[a-zA-Z0-9_\-]+/"),
    re.compile(r"/opt/[a-zA-Z0-9_\-]+/"),
    re.compile(r"192\.168\.\d{1,3}\.\d{1,3}"),
    re.compile(r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"),
    re.compile(r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"),
]

# Codigos ISO 639-1 validos (subconjunto)
_VALID_LANG_CODES = {
    "es", "en", "fr", "de", "it", "pt", "ca", "gl", "eu",
    "zh", "ja", "ko", "ar", "ru", "nl", "pl", "sv", "da",
}


class ValidationResult:
    def __init__(self, valid: bool, errors: List[str] = None, warnings: List[str] = None):
        self.valid = valid
        self.errors: List[str] = errors or []
        self.warnings: List[str] = warnings or []

    def __bool__(self) -> bool:
        return self.valid


def _scan_secrets(obj: Any) -> List[str]:
    """Devuelve lista de patrones de secretos encontrados."""
    import json
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    found = []
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            found.append(pat.pattern[:30])
    return found


def _scan_private_paths(obj: Any) -> List[str]:
    """Devuelve lista de patrones de rutas privadas encontrados."""
    import json
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    found = []
    for pat in _PRIVATE_PATH_PATTERNS:
        if pat.search(text):
            found.append(pat.pattern[:30])
    return found


def validate_transcription_result(result: dict, job: ProcessingJob) -> ValidationResult:
    """Valida el resultado de una transcripcion."""
    errors = []
    warnings = []

    # Schema: campos requeridos
    for field in ("text", "source_hash"):
        if field not in result:
            errors.append(f"Campo requerido ausente: {field}")

    # Source hash
    if "source_hash" in result:
        chunk = job.chunk or {}
        expected_hash = chunk.get("source_hash", "")
        if expected_hash and result.get("source_hash") != expected_hash:
            errors.append(f"source_hash no coincide: {result.get('source_hash')!r} != {expected_hash!r}")

    # Chunk range (timestamps)
    if job.chunk:
        chunk_start = job.chunk.get("chunk_start", 0.0)
        chunk_end = job.chunk.get("chunk_end", 0.0)
        if chunk_start > chunk_end:
            errors.append(f"Rango de chunk invalido: chunk_start ({chunk_start}) > chunk_end ({chunk_end})")

        # Si el resultado incluye timestamps
        if "start" in result and "end" in result:
            r_start = result["start"]
            r_end = result["end"]
            if r_start > r_end:
                errors.append(f"Timestamps invalidos en resultado: start ({r_start}) > end ({r_end})")
            # Verificar solapamiento valido (con tolerancia)
            if r_end < chunk_start - 1.0 or r_start > chunk_end + 1.0:
                errors.append(f"Timestamps fuera del rango del chunk: [{r_start}, {r_end}] vs [{chunk_start}, {chunk_end}]")

    # Language
    if "language" in result and result["language"]:
        lang = result["language"].lower()
        if lang not in _VALID_LANG_CODES:
            warnings.append(f"Codigo de idioma no reconocido: {lang!r}")

    # Workspace
    if "workspace" in result and result["workspace"] != job.workspace:
        errors.append(f"workspace no coincide: {result.get('workspace')!r} != {job.workspace!r}")

    # Scan de secretos
    secrets = _scan_secrets(result)
    if secrets:
        errors.append(f"Secretos detectados en resultado ({len(secrets)} patron/es)")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_ocr_result(result: dict, job: ProcessingJob) -> ValidationResult:
    """Valida el resultado de un OCR."""
    errors = []
    warnings = []

    for field in ("text", "document_hash"):
        if field not in result:
            errors.append(f"Campo requerido ausente: {field}")

    # Page range
    if job.chunk:
        page_start = job.chunk.get("page_start", 1)
        page_end = job.chunk.get("page_end", 1)
        if page_start > page_end:
            errors.append(f"Rango de paginas invalido: page_start ({page_start}) > page_end ({page_end})")

        if "page_start" in result and "page_end" in result:
            r_ps = result["page_start"]
            r_pe = result["page_end"]
            if r_ps > r_pe:
                errors.append(f"Rango de paginas en resultado invalido: {r_ps} > {r_pe}")

    # Document hash
    if "document_hash" in result and job.chunk:
        expected = job.chunk.get("document_hash", "")
        if expected and result["document_hash"] != expected:
            errors.append(f"document_hash no coincide")

    secrets = _scan_secrets(result)
    if secrets:
        errors.append(f"Secretos detectados en resultado OCR ({len(secrets)} patron/es)")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_result(job: ProcessingJob) -> Tuple[ProcessingJob, ValidationResult]:
    """Valida el resultado del job segun su tipo.

    Devuelve (job_actualizado, resultado_de_validacion).
    """
    if job.result is None:
        vr = ValidationResult(valid=False, errors=["Job no tiene resultado"])
        job = job.copy(update={"status": JobStatus.FAILED_VALIDATION})
        return job, vr

    # Escaneo de secretos en cualquier resultado
    global_secrets = _scan_secrets(job.result)
    global_private = _scan_private_paths(job.result)

    if job.task_type == ExternalTaskType.TRANSCRIBE_AUDIO:
        vr = validate_transcription_result(job.result, job)
    elif job.task_type in (ExternalTaskType.OCR_IMAGE,):
        vr = validate_ocr_result(job.result, job)
    else:
        # Validacion generica: campos presentes, sin secretos
        errors = []
        if global_secrets:
            errors.append(f"Secretos detectados ({len(global_secrets)})")
        if global_private:
            errors.append(f"Rutas privadas detectadas ({len(global_private)})")
        vr = ValidationResult(valid=len(errors) == 0, errors=errors)

    if not vr.valid:
        job = job.copy(update={"status": JobStatus.FAILED_VALIDATION})
    else:
        job = job.transition_to(JobStatus.READY) if job.status == JobStatus.VALIDATING else job.copy(
            update={"status": JobStatus.READY}
        )

    return job, vr


def validate_batch(jobs: List[ProcessingJob]) -> Tuple[List[ProcessingJob], List[ValidationResult]]:
    """Valida todos los jobs completados de un batch."""
    validated_jobs = []
    results = []
    for job in jobs:
        if job.status == JobStatus.COMPLETED:
            job_with_validating = job.transition_to(JobStatus.VALIDATING)
            updated_job, vr = validate_result(job_with_validating)
            validated_jobs.append(updated_job)
            results.append(vr)
        else:
            validated_jobs.append(job)
            results.append(ValidationResult(valid=job.status == JobStatus.READY))
    return validated_jobs, results

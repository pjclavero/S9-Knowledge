# -*- coding: utf-8 -*-
"""Division de fuentes en chunks para procesamiento externo (Fase B1).

Audio:
  - Division por duracion maxima configurable
  - Solapamiento configurable (default 2s) para no cortar palabras
  - Preserva chunk_start, chunk_end, overlap, source_hash, audio_hash

PDF:
  - Division por rangos de paginas
  - Mantiene page_start, page_end, document_hash

Imagenes:
  - Una imagen por job (sin batching por defecto)

Texto:
  - Division por tamaño maximo de caracteres
  - Preserva offsets y segment_ids
"""
from __future__ import annotations

import hashlib
import os
from typing import List, Optional

from external_processing.models import AudioChunk, PDFChunk, TextChunk, ImageTask

# ── Configuracion por entorno ─────────────────────────────────────────────────

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


def _max_audio_chunk_seconds() -> float:
    return _env_float("S9K_CHUNK_MAX_AUDIO_SECONDS", 600.0)  # 10 min


def _audio_overlap_seconds() -> float:
    return _env_float("S9K_CHUNK_AUDIO_OVERLAP_SECONDS", 2.0)


def _max_pdf_chunk_pages() -> int:
    return _env_int("S9K_CHUNK_MAX_PDF_PAGES", 20)


def _max_text_chunk_chars() -> int:
    return _env_int("S9K_CHUNK_MAX_TEXT_CHARS", 4000)


# ── Audio ─────────────────────────────────────────────────────────────────────

def chunk_audio(
    source_hash: str,
    duration_seconds: float,
    audio_hash: str = "",
    expected_language: Optional[str] = None,
    max_chunk_seconds: Optional[float] = None,
    overlap_seconds: Optional[float] = None,
) -> List[AudioChunk]:
    """Divide un audio en chunks con solapamiento.

    Si la duracion cabe en un solo chunk, devuelve un unico chunk.
    """
    max_dur = max_chunk_seconds if max_chunk_seconds is not None else _max_audio_chunk_seconds()
    overlap = overlap_seconds if overlap_seconds is not None else _audio_overlap_seconds()

    if duration_seconds <= 0:
        return []

    if duration_seconds <= max_dur:
        return [AudioChunk(
            chunk_index=0,
            chunk_start=0.0,
            chunk_end=duration_seconds,
            overlap_start=0.0,
            overlap_end=0.0,
            source_hash=source_hash,
            audio_hash=audio_hash,
            duration_seconds=duration_seconds,
            expected_language=expected_language,
        )]

    chunks: List[AudioChunk] = []
    start = 0.0
    idx = 0
    step = max(max_dur - overlap, 1.0)  # evitar step <= 0

    while start < duration_seconds:
        end = min(start + max_dur, duration_seconds)
        is_first = (idx == 0)
        is_last = (end >= duration_seconds)

        chunk = AudioChunk(
            chunk_index=idx,
            chunk_start=start,
            chunk_end=end,
            overlap_start=0.0 if is_first else overlap,
            overlap_end=0.0 if is_last else overlap,
            source_hash=source_hash,
            audio_hash=audio_hash,
            duration_seconds=end - start,
            expected_language=expected_language,
        )
        chunks.append(chunk)
        if is_last:
            break
        start += step
        idx += 1

    return chunks


# ── PDF ───────────────────────────────────────────────────────────────────────

def chunk_pdf(
    document_hash: str,
    total_pages: int,
    max_pages_per_chunk: Optional[int] = None,
) -> List[PDFChunk]:
    """Divide un PDF en chunks de paginas."""
    max_pages = max_pages_per_chunk if max_pages_per_chunk is not None else _max_pdf_chunk_pages()

    if total_pages <= 0:
        return []

    chunks: List[PDFChunk] = []
    idx = 0
    page = 1

    while page <= total_pages:
        page_end = min(page + max_pages - 1, total_pages)
        chunks.append(PDFChunk(
            chunk_index=idx,
            page_start=page,
            page_end=page_end,
            document_hash=document_hash,
            page_count=page_end - page + 1,
        ))
        page = page_end + 1
        idx += 1

    return chunks


# ── Imagenes ──────────────────────────────────────────────────────────────────

def chunk_images(
    source_hash: str,
    image_paths: List[str],
    mime_type: str = "image/jpeg",
) -> List[ImageTask]:
    """Genera un ImageTask por imagen (una imagen por job)."""
    tasks = []
    for i, path in enumerate(image_paths):
        # Hash derivado del path (en real seria hash del contenido del archivo)
        image_hash = hashlib.sha256(path.encode("utf-8")).hexdigest()
        tasks.append(ImageTask(
            image_index=i,
            source_hash=source_hash,
            image_hash=image_hash,
            mime_type=mime_type,
        ))
    return tasks


# ── Texto ─────────────────────────────────────────────────────────────────────

def chunk_text(
    source_hash: str,
    text: str,
    max_chars: Optional[int] = None,
) -> List[TextChunk]:
    """Divide texto en chunks por tamaño maximo preservando offsets."""
    max_ch = max_chars if max_chars is not None else _max_text_chunk_chars()

    if not text:
        return []

    if len(text) <= max_ch:
        return [TextChunk(
            chunk_index=0,
            offset_start=0,
            offset_end=len(text),
            source_hash=source_hash,
            char_count=len(text),
        )]

    chunks: List[TextChunk] = []
    idx = 0
    offset = 0

    while offset < len(text):
        end = min(offset + max_ch, len(text))
        # Intentar cortar en espacio para no partir palabras
        if end < len(text):
            last_space = text.rfind(" ", offset, end)
            if last_space > offset:
                end = last_space + 1

        chunks.append(TextChunk(
            chunk_index=idx,
            offset_start=offset,
            offset_end=end,
            source_hash=source_hash,
            char_count=end - offset,
        ))
        offset = end
        idx += 1

    return chunks


# ── Utilidades ────────────────────────────────────────────────────────────────

def chunk_range_key(chunk) -> str:
    """Genera una clave de rango de chunk para usar en la cache."""
    if isinstance(chunk, AudioChunk):
        return f"audio:{chunk.chunk_start:.3f}-{chunk.chunk_end:.3f}"
    if isinstance(chunk, PDFChunk):
        return f"pdf:{chunk.page_start}-{chunk.page_end}"
    if isinstance(chunk, TextChunk):
        return f"text:{chunk.offset_start}-{chunk.offset_end}"
    if isinstance(chunk, ImageTask):
        return f"image:{chunk.image_index}"
    return "unknown"

"""Modelos de datos para el procesado multimedia.

Solo stdlib. Ningún modelo aquí toca Neo4j ni el grafo: describen la fuente
multimedia y el resultado de la transcripción como datos revisables.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# ── Extensiones soportadas ────────────────────────────────────────────────────
VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"})
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Sufijos de archivos temporales/parciales a ignorar durante el escaneo.
IGNORED_SUFFIXES = frozenset({".part", ".tmp", ".crdownload", ".download", ".partial"})

# ── Estados del job multimedia ────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_PROBING = "probing"
STATUS_AUDIO_EXTRACTING = "audio_extracting"
STATUS_TRANSCRIBING = "transcribing"
STATUS_WRITING_MARKDOWN = "writing_markdown"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

MEDIA_STATUSES = frozenset({
    STATUS_PENDING, STATUS_PROBING, STATUS_AUDIO_EXTRACTING, STATUS_TRANSCRIBING,
    STATUS_WRITING_MARKDOWN, STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,
})

SOURCE_KIND_VIDEO = "video"
SOURCE_KIND_AUDIO = "audio"


def now_iso() -> str:
    """Instante actual en ISO-8601 UTC (mismo formato que job_store)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect_source_kind(extension: str) -> str | None:
    """Devuelve 'video'/'audio'/None a partir de la extensión (con punto)."""
    ext = extension.lower()
    if ext in VIDEO_EXTENSIONS:
        return SOURCE_KIND_VIDEO
    if ext in AUDIO_EXTENSIONS:
        return SOURCE_KIND_AUDIO
    return None


def is_supported_media(filename: str) -> bool:
    """True si el nombre de archivo tiene una extensión de vídeo/audio soportada."""
    m = re.search(r"(\.[A-Za-z0-9]+)$", filename)
    if not m:
        return False
    return m.group(1).lower() in MEDIA_EXTENSIONS


def source_id_from_sha256(sha256: str) -> str:
    """ID de fuente estable y determinista derivado del hash del contenido."""
    return f"media_{sha256[:16]}"


def format_timestamp(seconds: float) -> str:
    """Convierte segundos a 'HH:MM:SS' para las marcas de tiempo del Markdown."""
    if seconds is None or seconds < 0:
        seconds = 0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranscriptResult:
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = "es"
    engine: str = "stub"
    model: str = ""
    duration_seconds: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["segments"] = [s.to_dict() for s in self.segments]
        return d


@dataclass
class MediaSource:
    """Metadatos y estado de una fuente multimedia en el pipeline."""
    source_id: str
    source_kind: str            # "video" | "audio"
    workspace: str
    original_path: str
    original_filename: str
    sha256: str
    size_bytes: int = 0
    duration_seconds: float | None = None
    media_format: str = ""
    audio_codec: str = ""
    video_codec: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    status: str = STATUS_PENDING
    error_message: str = ""
    # Rutas de salida (se rellenan durante el procesado)
    audio_path: str = ""
    output_markdown: str = ""
    output_transcript_json: str = ""
    # Trazabilidad de transcripción
    transcriber_engine: str = ""
    transcriber_model: str = ""
    language: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MediaSource":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)

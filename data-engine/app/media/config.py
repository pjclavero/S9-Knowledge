"""Configuración del pipeline multimedia, leída de variables de entorno.

Todas las rutas por defecto son relativas a la raíz del repo (calculada desde
la ubicación de este archivo), NO rutas absolutas de Windows ni de servidor.
En VM105 se sobreescriben con variables S9K_MEDIA_* absolutas.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# data-engine/app/media/config.py → parents[3] = raíz del repo
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_path(var: str, default_rel: str) -> Path:
    """Lee una ruta de entorno; si no está, usa una ruta relativa al repo."""
    val = os.environ.get(var, "").strip()
    if val:
        return Path(val)
    return _REPO_ROOT / default_rel


def _env_bool(var: str, default: bool = False) -> bool:
    val = os.environ.get(var, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on", "si", "sí"}


def _env_int(var: str, default: int) -> int:
    val = os.environ.get(var, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


@dataclass
class MediaConfig:
    staging_dir: Path
    output_dir: Path
    audio_dir: Path
    transcript_dir: Path
    log_dir: Path
    default_workspace: str
    transcriber: str
    language: str
    max_duration_seconds: int
    dry_run: bool
    # faster-whisper (opcional)
    faster_whisper_model: str
    faster_whisper_device: str
    faster_whisper_compute_type: str
    # Integración opcional con el job_store SQLite (jobs.db)
    jobstore_bridge: bool

    @classmethod
    def from_env(cls) -> "MediaConfig":
        return cls(
            staging_dir=_env_path("S9K_MEDIA_STAGING_DIR", "staging/media"),
            output_dir=_env_path("S9K_MEDIA_OUTPUT_DIR", "output/media"),
            audio_dir=_env_path("S9K_MEDIA_AUDIO_DIR", "output/audio"),
            transcript_dir=_env_path("S9K_MEDIA_TRANSCRIPT_DIR", "output/transcriptions"),
            log_dir=_env_path("S9K_MEDIA_LOG_DIR", "logs/media"),
            default_workspace=os.environ.get("S9K_MEDIA_DEFAULT_WORKSPACE", "leyenda"),
            transcriber=os.environ.get("S9K_MEDIA_TRANSCRIBER", "stub"),
            language=os.environ.get("S9K_MEDIA_LANGUAGE", "es"),
            max_duration_seconds=_env_int("S9K_MEDIA_MAX_DURATION_SECONDS", 7200),
            dry_run=_env_bool("S9K_MEDIA_DRY_RUN", False),
            faster_whisper_model=os.environ.get("S9K_FASTER_WHISPER_MODEL", "small"),
            faster_whisper_device=os.environ.get("S9K_FASTER_WHISPER_DEVICE", "cpu"),
            faster_whisper_compute_type=os.environ.get("S9K_FASTER_WHISPER_COMPUTE_TYPE", "int8"),
            jobstore_bridge=_env_bool("S9K_MEDIA_JOBSTORE_BRIDGE", False),
        )

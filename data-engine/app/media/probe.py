"""Sondeo de metadatos multimedia con ffprobe (degradación controlada).

Si ffprobe no está instalado o falla, devuelve metadatos vacíos sin lanzar
excepción: el pipeline puede continuar con lo que tenga (nombre, tamaño, hash).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("media.probe")


@dataclass
class ProbeResult:
    duration_seconds: float | None = None
    media_format: str = ""
    audio_codec: str = ""
    video_codec: str = ""
    ffprobe_available: bool = True


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_media(path: Path, timeout: int = 30) -> ProbeResult:
    """Extrae duración/formato/códecs con ffprobe. Nunca lanza: degrada a vacío."""
    if not ffprobe_available():
        log.warning("ffprobe no disponible; metadatos multimedia degradados a vacío")
        return ProbeResult(ffprobe_available=False)

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            log.warning("ffprobe devolvió código %s para %s", result.returncode, path.name)
            return ProbeResult()
        data = json.loads(result.stdout or "{}")
    except Exception as exc:  # noqa: BLE001 - degradación controlada
        log.warning("ffprobe falló para %s: %s", path.name, exc)
        return ProbeResult()

    fmt = data.get("format", {}) or {}
    duration = None
    dur_raw = fmt.get("duration")
    if dur_raw:
        try:
            duration = float(dur_raw)
        except (TypeError, ValueError):
            duration = None

    audio_codec = ""
    video_codec = ""
    for stream in data.get("streams", []) or []:
        codec_type = stream.get("codec_type")
        if codec_type == "audio" and not audio_codec:
            audio_codec = stream.get("codec_name", "") or ""
            if duration is None and stream.get("duration"):
                try:
                    duration = float(stream["duration"])
                except (TypeError, ValueError):
                    pass
        elif codec_type == "video" and not video_codec:
            video_codec = stream.get("codec_name", "") or ""

    return ProbeResult(
        duration_seconds=duration,
        media_format=(fmt.get("format_name", "") or ""),
        audio_codec=audio_codec,
        video_codec=video_codec,
    )

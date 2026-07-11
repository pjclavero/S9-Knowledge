from __future__ import annotations
import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset({
    ".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".flac",
    ".opus", ".webm", ".aac", ".wma", ".aiff",
})


def validate_audio_path(path: Path, max_mb: float = 500) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Audio no encontrado: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Extensión no soportada: {path.suffix}. "
            f"Permitidas: {sorted(SUPPORTED_EXTENSIONS)}"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        raise ValueError(f"Archivo demasiado grande: {size_mb:.1f} MB (max {max_mb} MB)")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def get_audio_duration(path: Path) -> Optional[float]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            dur = stream.get("duration")
            if dur:
                return float(dur)
    except Exception as e:
        log.warning("No se pudo obtener duración de %s: %s", path.name, e)
    return None


def convert_to_wav(src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-ar", str(sample_rate), "-ac", "1", "-f", "wav", str(dst)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {result.stderr[-500:]}")
    return dst


def detect_speakers_simple(segments) -> list:
    if not segments:
        return []
    result = []
    speaker_idx = 0
    current_speaker = f"Hablante_{speaker_idx + 1}"
    prev_end = 0.0
    for seg in segments:
        if prev_end > 0 and (seg.start - prev_end) > 2.0:
            speaker_idx = (speaker_idx + 1) % 4
            current_speaker = f"Hablante_{speaker_idx + 1}"
        result.append({"start": seg.start, "end": seg.end,
                        "text": seg.text, "speaker": current_speaker})
        prev_end = seg.end
    return result

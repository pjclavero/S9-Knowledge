"""Extracción/normalización de audio con ffmpeg (encapsulada y testeable).

Convierte cualquier vídeo/audio de entrada a un WAV mono 16 kHz PCM s16le,
formato estándar para transcripción. No borra nunca el original. En tests se
mockea `subprocess.run`, no se exige ffmpeg real.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("media.audio_extract")

DEFAULT_TIMEOUT = 3600  # 1 h; audios largos pueden tardar en transcodificar


class AudioExtractionError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _seconds_to_hhmmss(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    max_duration_seconds: int | None = None,
) -> list[str]:
    """Construye el comando ffmpeg (aislado para poder testearlo sin ejecutar)."""
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vn",
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    if max_duration_seconds and max_duration_seconds > 0:
        cmd += ["-t", _seconds_to_hhmmss(max_duration_seconds)]
    cmd.append(str(output_path))
    return cmd


def extract_audio(
    input_path: Path,
    output_path: Path,
    max_duration_seconds: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """Extrae audio de `input_path` a `output_path` (WAV mono 16k). Devuelve la ruta.

    No modifica ni borra el original. Crea las carpetas necesarias. Lanza
    AudioExtractionError si ffmpeg no está o falla.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.is_file():
        raise AudioExtractionError(f"Entrada no encontrada: {input_path}")
    if not ffmpeg_available():
        raise AudioExtractionError("ffmpeg no está instalado o no está en PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_command(input_path, output_path, max_duration_seconds)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AudioExtractionError(f"ffmpeg superó el timeout de {timeout}s") from exc
    except Exception as exc:  # noqa: BLE001
        raise AudioExtractionError(f"ffmpeg no pudo ejecutarse: {exc}") from exc

    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        raise AudioExtractionError(f"ffmpeg falló (código {result.returncode}): {tail}")

    if not output_path.is_file():
        raise AudioExtractionError("ffmpeg terminó sin error pero no generó el archivo de salida")

    log.info("Audio extraído: %s → %s", input_path.name, output_path.name)
    return output_path

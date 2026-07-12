"""Transcriptores de audio con interfaz común y selección por configuración.

- StubTranscriber: sin dependencias, para desarrollo y tests. Devuelve una
  transcripción ficticia con segmentos.
- FasterWhisperTranscriber: import perezoso; solo funciona si `faster_whisper`
  está instalado. Nunca rompe el import del módulo si falta la librería.

Ningún transcriptor descarga modelos en tiempo de import. El modelo de
faster-whisper solo se carga al llamar a `transcribe()`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from media.config import MediaConfig
from media.models import TranscriptResult, TranscriptSegment

log = logging.getLogger("media.transcriber")


class TranscriberError(RuntimeError):
    pass


class Transcriber:
    """Interfaz común de transcripción."""

    name = "base"

    def transcribe(self, audio_path: Path, language: str = "es") -> TranscriptResult:
        raise NotImplementedError


class StubTranscriber(Transcriber):
    """Transcriptor ficticio para desarrollo/tests. No usa Whisper."""

    name = "stub"

    def transcribe(self, audio_path: Path, language: str = "es") -> TranscriptResult:
        audio_path = Path(audio_path)
        text = (
            f"[TRANSCRIPCIÓN DE PRUEBA] Contenido simulado para el archivo "
            f"'{audio_path.name}'. Este texto lo genera StubTranscriber y NO "
            f"corresponde a audio real; sirve para validar el pipeline sin Whisper."
        )
        segments = [
            TranscriptSegment(start=0.0, end=5.0, text=f"Inicio simulado de {audio_path.name}."),
            TranscriptSegment(start=5.0, end=10.0, text="Segundo segmento de prueba."),
            TranscriptSegment(start=10.0, end=15.0, text="Fin de la transcripción simulada."),
        ]
        return TranscriptResult(
            text=text,
            segments=segments,
            language=language,
            engine="stub",
            model="stub",
            duration_seconds=15.0,
        )


class FasterWhisperTranscriber(Transcriber):
    """Transcriptor real basado en faster-whisper (CPU int8 por defecto)."""

    name = "faster-whisper"

    def __init__(self, model: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None  # carga perezosa

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # import perezoso
        except ImportError as exc:
            raise TranscriberError(
                "faster-whisper no está instalado. Instálalo con "
                "`pip install faster-whisper` o usa S9K_MEDIA_TRANSCRIBER=stub."
            ) from exc
        try:
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        except Exception as exc:  # noqa: BLE001
            raise TranscriberError(f"No se pudo cargar el modelo faster-whisper: {exc}") from exc

    def transcribe(self, audio_path: Path, language: str = "es") -> TranscriptResult:
        self._ensure_model()
        try:
            segments_iter, info = self._model.transcribe(str(audio_path), language=language)
            segments: list[TranscriptSegment] = []
            texts: list[str] = []
            for seg in segments_iter:
                segments.append(TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip()))
                texts.append(seg.text.strip())
        except Exception as exc:  # noqa: BLE001
            raise TranscriberError(f"faster-whisper falló al transcribir: {exc}") from exc

        return TranscriptResult(
            text=" ".join(texts).strip(),
            segments=segments,
            language=getattr(info, "language", language) or language,
            engine="faster-whisper",
            model=self.model_name,
            duration_seconds=getattr(info, "duration", None),
        )


def get_transcriber(config: MediaConfig) -> Transcriber:
    """Devuelve el transcriptor según S9K_MEDIA_TRANSCRIBER.

    - "stub" (por defecto): StubTranscriber.
    - "faster-whisper" / "faster_whisper": FasterWhisperTranscriber (lazy).
    - "whisper.cpp" / "external": aún no implementados (solo documentados);
      degradan a un error claro.
    """
    name = (config.transcriber or "stub").strip().lower()
    if name in {"stub", ""}:
        return StubTranscriber()
    if name in {"faster-whisper", "faster_whisper", "fasterwhisper"}:
        return FasterWhisperTranscriber(
            model=config.faster_whisper_model,
            device=config.faster_whisper_device,
            compute_type=config.faster_whisper_compute_type,
        )
    if name in {"whisper.cpp", "whispercpp", "external"}:
        raise TranscriberError(
            f"Transcriptor '{name}' aún no implementado (solo documentado). "
            f"Usa 'stub' o 'faster-whisper'."
        )
    raise TranscriberError(f"Transcriptor desconocido: '{config.transcriber}'")

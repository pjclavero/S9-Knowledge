# -*- coding: utf-8 -*-
"""Adaptadores de audio, video y YouTube: ENVUELVEN transcripciones ya producidas.

Este modulo **no transcribe nada**. Consume la salida real de los subsistemas
existentes, que son de solo lectura para V3:

* `media.models.TranscriptResult` (lo que produce `media.transcriber`);
* `media.multimedia_contract.MultimediaArtifact` de tipo `ASR_TEXT` (lo que
  produce `MultimediaArtifact.from_transcript_result`, que es el envoltorio
  canonico del pipeline `media/`);
* `audio.audio_schema.TranscriptDocument` (que si trae `speaker` y
  `confidence` por segmento);
* un `dict` con `segments`, para la salida de `youtube/`.

La deteccion es por forma (duck typing) y no por import: `media/`, `audio/` y
`youtube/` no se importan aqui, de modo que envolverlos no crea una dependencia
que impida moverlos.

Diarizacion
-----------
Si algun segmento trae hablante, los segmentos consecutivos del mismo hablante
se agrupan en un episodio `SPEAKER_TURN` con `speaker` y `turn`. Si no la hay,
los segmentos se agrupan en ventanas deterministas de `ASR_TEXT`. El contrato
exige `speaker` en `SPEAKER_TURN` justamente porque sin el no se pueden resolver
las correferencias de primera y segunda persona, que es para lo que existe el
turno; por eso no se emite `SPEAKER_TURN` con un hablante inventado.

Timecodes
---------
La evidencia `ASR_TEXT` sin `time_start`/`time_end` la rechaza el contrato: una
cita de audio que no dice en que segundo esta no es verificable. Cuando la
transcripcion de entrada **no trae timecodes** (es el caso real de
`youtube/fetch_youtube.py`, que descarta los tiempos del VTT), este adaptador
NO los inventa: marca el episodio con `NO_TIMECODES` y emite evidencia solo si
el origen es un fichero de subtitulos (`media_type=CAPTION`, que no exige
anclaje temporal). En el resto de casos deja el episodio sin evidencia y lo
declara en el informe. Es una perdida real, y aparece como tal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .. import errors, ids
from ..base import (
    STEP_EXTRACT,
    AdapterOutput,
    EpisodeDraft,
    FragmentDraft,
    IngestOptions,
    Provider,
    SourceAdapter,
    SourceInput,
    provider_step,
)
from ...contracts import canonical_json
from ..quality import (
    LOW_PROVIDER_CONFIDENCE,
    quality,
    transcript_quality,
)

#: Paso de traza del motor ASR. Es un paso PROPIO, distinto del de extraccion:
#: el texto lo produjo el motor de transcripcion, no el normalizador, y
#: `produced_by_step` de los episodios apunta aqui.
STEP_ASR = "asr"

#: Bandera de episodio sin anclaje temporal.
NO_TIMECODES = "NO_TIMECODES"

#: Agrupacion por defecto cuando NO hay diarizacion.
MAX_WINDOW_SECONDS = 60.0
MAX_WINDOW_CHARS = 1200

#: Separador canonico entre segmentos dentro de un episodio.
SEGMENT_SEPARATOR = " "


@dataclass
class SegmentView:
    """Segmento de transcripcion normalizado, venga de donde venga."""

    start: Optional[float]
    end: Optional[float]
    text: str
    speaker: Optional[str] = None
    confidence: Optional[float] = None

    @property
    def timed(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass
class TranscriptView:
    """Transcripcion normalizada de entrada (no es un contrato V3)."""

    segments: list[SegmentView] = field(default_factory=list)
    language: Optional[str] = None
    engine: str = "unknown"
    model: Optional[str] = None
    duration_seconds: Optional[float] = None
    source_method: Optional[str] = None
    full_text: str = ""

    @property
    def diarized(self) -> bool:
        return any(s.speaker for s in self.segments)

    @property
    def timed(self) -> bool:
        return bool(self.segments) and all(s.timed for s in self.segments)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def coerce_transcript(payload: Any) -> TranscriptView:
    """Normaliza cualquiera de las formas de transcripcion reales a `TranscriptView`.

    Acepta `TranscriptResult`, `TranscriptDocument`, `MultimediaArtifact`
    (`ASR_TEXT`) y `dict`. Lo que NO acepta es una entrada sin segmentos y sin
    texto: no hay nada que envolver.
    """
    if payload is None:
        raise errors.NormalizationError(
            errors.MISSING_PAYLOAD,
            "adaptador de transcripcion sin payload: este subsistema envuelve "
            "transcripciones ya producidas, no las genera",
        )

    # MultimediaArtifact ASR_TEXT: los segmentos viven en structured_data.
    structured = _get(payload, "structured_data")
    raw_segments = _get(payload, "segments")
    duration = _get(payload, "duration_seconds")
    if raw_segments is None and isinstance(structured, dict):
        raw_segments = structured.get("segments")
        duration = structured.get("duration_seconds", duration)

    media_type = _get(payload, "media_type")
    media_type = getattr(media_type, "value", media_type)
    if media_type is not None and media_type != "ASR_TEXT":
        raise errors.NormalizationError(
            errors.MISSING_PAYLOAD,
            f"artefacto multimedia de tipo {media_type!r}: el adaptador de "
            "transcripcion solo envuelve ASR_TEXT",
        )

    segments: list[SegmentView] = []
    for raw in raw_segments or []:
        text = (_get(raw, "text") or "").strip()
        if not text:
            continue
        start = _get(raw, "start")
        end = _get(raw, "end")
        segments.append(
            SegmentView(
                start=float(start) if start is not None else None,
                end=float(end) if end is not None else None,
                text=text,
                speaker=(_get(raw, "speaker") or None),
                confidence=_get(raw, "confidence"),
            )
        )

    full_text = (_get(payload, "full_text") or _get(payload, "text") or "").strip()
    if not segments and not full_text:
        raise errors.NormalizationError(
            errors.EMPTY_SOURCE, "transcripcion sin segmentos ni texto"
        )

    extraction_method = _get(payload, "extraction_method") or ""
    engine = _get(payload, "engine") or (
        extraction_method.split(":", 1)[1] if ":" in extraction_method else None
    )
    return TranscriptView(
        segments=segments,
        language=_get(payload, "language") or None,
        engine=str(engine or "unknown"),
        model=_get(payload, "model") or None,
        duration_seconds=float(duration) if duration is not None else None,
        source_method=_get(payload, "source_method"),
        full_text=full_text,
    )


def group_segments(
    segments: Sequence[SegmentView],
    *,
    max_seconds: float = MAX_WINDOW_SECONDS,
    max_chars: int = MAX_WINDOW_CHARS,
) -> list[list[SegmentView]]:
    """Agrupa segmentos en episodios de forma determinista.

    Con diarizacion, corta en cada cambio de hablante (un turno es un turno).
    Sin diarizacion, corta por ventana de duracion o de longitud. En ambos casos
    el corte depende solo de los datos, nunca del orden de llegada ni del reloj.
    """
    groups: list[list[SegmentView]] = []
    current: list[SegmentView] = []
    for segment in segments:
        if not current:
            current = [segment]
            continue
        same_speaker = current[-1].speaker == segment.speaker
        chars = sum(len(s.text) for s in current) + len(segment.text)
        span = (
            (segment.end - current[0].start)
            if (segment.end is not None and current[0].start is not None)
            else 0.0
        )
        if not same_speaker or chars > max_chars or span > max_seconds:
            groups.append(current)
            current = [segment]
        else:
            current.append(segment)
    if current:
        groups.append(current)
    return groups


def _speaker_block(asset_seed: str, label: str, confidence: Optional[float]) -> dict:
    block: dict[str, Any] = {
        "speaker_id": ids.speaker_id_for(asset_seed, label),
        "label": label,
    }
    if confidence is not None:
        block["confidence"] = max(0.0, min(1.0, float(confidence)))
    return block


def episodes_from_transcript(
    view: TranscriptView, *, asset_seed: str, caption_source: bool = False
) -> list[EpisodeDraft]:
    """Transcripcion normalizada -> episodios `SPEAKER_TURN` o `ASR_TEXT`."""
    drafts: list[EpisodeDraft] = []
    if not view.segments:
        # Transcripcion plana (el caso real de youtube/): un solo episodio ASR
        # sin timecodes. Sin tiempos no hay evidencia ASR posible.
        media_type = "CAPTION" if caption_source else None
        fragments: list[FragmentDraft] = []
        if media_type:
            fragments = [
                FragmentDraft(
                    literal_text=view.full_text,
                    start=0,
                    end=len(view.full_text),
                    media_type=media_type,
                    confidence=1.0,
                )
            ]
        return [
            EpisodeDraft(
                modality="ASR_TEXT",
                text=view.full_text,
                quality=quality(0.5, [NO_TIMECODES]),
                fragments=fragments,
                produced_by=STEP_ASR,
                metadata={"transcript_shape": "flat_text"},
            )
        ]

    global_quality = transcript_quality(
        [(s.start or 0.0, s.end or 0.0, s.text) for s in view.segments],
        duration_seconds=view.duration_seconds,
        diarized=view.diarized,
    )
    turn_index = 0
    for group in group_segments(view.segments):
        parts: list[str] = []
        offsets: list[tuple[int, int]] = []
        cursor = 0
        for segment in group:
            if parts:
                cursor += len(SEGMENT_SEPARATOR)
            offsets.append((cursor, cursor + len(segment.text)))
            parts.append(segment.text)
            cursor += len(segment.text)
        text = SEGMENT_SEPARATOR.join(parts)

        timed = all(s.timed for s in group)
        flags = list(global_quality["flags"])
        score = float(global_quality["score"])
        if not timed:
            flags.append(NO_TIMECODES)
            score = min(score, 0.5)
        confidences = [s.confidence for s in group if s.confidence is not None]
        if confidences and min(confidences) < 0.5:
            flags.append(LOW_PROVIDER_CONFIDENCE)

        fragments = []
        for segment, (start, end) in zip(group, offsets):
            if timed:
                media_type = "ASR_TEXT"
            elif caption_source:
                media_type = "CAPTION"
            else:
                continue
            fragments.append(
                FragmentDraft(
                    literal_text=segment.text,
                    start=start,
                    end=end,
                    media_type=media_type,
                    confidence=(
                        float(segment.confidence) if segment.confidence is not None else 1.0
                    ),
                    time_start=segment.start,
                    time_end=segment.end,
                    produced_by=STEP_ASR,
                )
            )

        speaker_label = group[0].speaker
        if speaker_label:
            speaker_confidences = [s.confidence for s in group if s.confidence is not None]
            draft = EpisodeDraft(
                modality="SPEAKER_TURN",
                text=text,
                time_start=group[0].start,
                time_end=group[-1].end,
                speaker=_speaker_block(
                    asset_seed,
                    speaker_label,
                    min(speaker_confidences) if speaker_confidences else None,
                ),
                turn=turn_index,
                quality=quality(score, flags),
                fragments=fragments,
                produced_by=STEP_ASR,
            )
            turn_index += 1
        else:
            draft = EpisodeDraft(
                modality="ASR_TEXT",
                text=text,
                time_start=group[0].start,
                time_end=group[-1].end,
                quality=quality(score, flags),
                fragments=fragments,
                produced_by=STEP_ASR,
            )
        drafts.append(draft)
    return drafts


class _BaseTranscriptAdapter(SourceAdapter):
    """Comun a audio, video y YouTube. No transcribe: envuelve."""

    is_stub = False
    #: `SPEAKER_TURN` exige `speaker` y la evidencia `ASR_TEXT` exige tiempos:
    #: ambas cosas vienen del motor de transcripcion, no de aqui.
    caption_source_methods = ("subtitles", "captions")

    def _view(self, source: SourceInput) -> TranscriptView:
        payload = source.payload or {}
        transcript = payload.get("transcript") if isinstance(payload, dict) else None
        if transcript is None:
            transcript = payload
        return coerce_transcript(transcript)

    def _asr_step(self, view: TranscriptView) -> dict:
        """Paso de traza del motor de transcripcion, con su proveedor real.

        `faster-whisper` o el stub de `media/` son codigo local: `provider=local`.
        Si un dia la transcripcion la hiciera un servicio remoto, el llamante lo
        declara en `payload["provider"]` y la traza lo dice.
        """
        payload_provider = view.source_method or ""
        provider = Provider.LOCAL
        if payload_provider.startswith("external"):
            provider = Provider.EXTERNAL
        return provider_step(
            STEP_ASR,
            provider,
            f"transcriber:{view.engine}",
            str(view.model or view.engine or "unknown"),
            ["text", "segments", "timestamps"] + (["speaker"] if view.diarized else []),
            model=view.model,
        )

    def _build(self, source: SourceInput, kind: str, mime: str) -> AdapterOutput:
        view = self._view(source)
        caption = (view.source_method or "") in self.caption_source_methods
        asset_seed = ids.sha256_bytes(self.content_bytes(source))
        episodes = episodes_from_transcript(
            view, asset_seed=asset_seed, caption_source=caption
        )
        untimed = sum(
            1 for e in episodes if NO_TIMECODES in (e.quality.get("flags") or [])
        )
        return AdapterOutput(
            source_kind=kind,
            mime_type=source.mime_type or mime,
            episodes=episodes,
            trace_steps=[
                self._asr_step(view),
                self.local_step(
                    ["episodes", "sequence", "evidence_fragments"], step=STEP_EXTRACT
                ),
            ],
            report={
                "transcript_engine": view.engine,
                "transcript_model": view.model,
                "transcript_segments": len(view.segments),
                "transcript_diarized": view.diarized,
                "transcript_duration_seconds": view.duration_seconds,
                "episodes_without_timecodes": untimed,
                "speaker_turns": sum(1 for e in episodes if e.modality == "SPEAKER_TURN"),
            },
        )


class AudioTranscriptAdapter(_BaseTranscriptAdapter):
    """`AUDIO`: envuelve la transcripcion del fichero de audio."""

    name = "knowledge_v3.multimodal.adapters.audio"
    source_kinds = ("AUDIO",)
    mime_types = ("audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/ogg")
    extensions = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        return self._build(source, "AUDIO", "audio/mpeg")


class VideoTranscriptAdapter(_BaseTranscriptAdapter):
    """`VIDEO`: misma via que audio (dosier 7.8: el audio del video va al flujo ASR).

    Los keyframes, escenas y OCR de pantalla del dosier 7.8 son trabajo de los
    adaptadores visuales sobre el mismo asset, y hoy estan pendientes de
    proveedor. Este adaptador no los simula.
    """

    name = "knowledge_v3.multimodal.adapters.video"
    source_kinds = ("VIDEO",)
    mime_types = ("video/mp4", "video/x-matroska", "video/webm", "video/quicktime")
    extensions = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v")

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        return self._build(source, "VIDEO", "video/mp4")


class YouTubeTranscriptAdapter(_BaseTranscriptAdapter):
    """`YOUTUBE`: envuelve la salida de `youtube/fetch_youtube.py`.

    No hay fichero local que hashear (el audio de staging se borra), asi que el
    `content_hash` del asset es el sha256 del JSON canonico de la transcripcion
    recibida, que ES el contenido ingerido. Es un hash real de un contenido
    real, no un identificador inventado, y se documenta como tal en el informe.
    """

    name = "knowledge_v3.multimodal.adapters.youtube"
    source_kinds = ("YOUTUBE",)
    mime_types = ("application/vnd.s9k.youtube-transcript+json",)
    extensions = ()

    def content_bytes(self, source: SourceInput) -> bytes:
        if source.data:
            return source.data
        view = self._view(source)
        return canonical_json(
            {
                "engine": view.engine,
                "language": view.language,
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
                    for s in view.segments
                ],
                "full_text": view.full_text,
            }
        ).encode("utf-8")

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        output = self._build(
            source, "YOUTUBE", "application/vnd.s9k.youtube-transcript+json"
        )
        output.report["content_hash_basis"] = (
            "media_bytes" if source.data else "canonical_transcript_json"
        )
        return output

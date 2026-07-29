# -*- coding: utf-8 -*-
"""Cascada de transcripcion manuscrita con decision local y auditable."""
from __future__ import annotations

import base64
import difflib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from .adapters.visual import MODE_HTR, VisualRequest, VisualResult

TRANSCRIPTION_FAMILY = "visual-transcription"
PRIMARY_VISION_MODEL = "meta/llama-3.2-90b-vision-instruct"
SECONDARY_VISION_MODEL = "nvidia/nemotron-nano-12b-v2-vl"
COHERENCE_MODEL = "meta/llama-3.3-70b-instruct"

TRANSCRIPTION_PROMPT = """Transcribe literalmente todo el texto visible de la imagen.
No interpretes ni expliques el contenido.
No resumas, no normalices ortografia, mayusculas, puntuacion ni espaciado.
No completes trazos dudosos ni sustituyas palabras por otras plausibles.
Escribe [ilegible] exactamente donde un trazo no se pueda leer.
Conserva los saltos de linea. Devuelve solo JSON: {"transcription":"..."}.
No devuelvas coordenadas ni posiciones de imagen."""

COHERENCE_PROMPT = """Revisa solo la coherencia interna del texto proporcionado.
No corrijas, completes, normalices ni reescribas el texto.
No uses conocimiento externo. Devuelve solo JSON:
{"coherent":true} o {"coherent":false}."""

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\d+(?:[./:-]\d+)*", re.UNICODE)
_TOKEN_RE = re.compile(r"\S+", re.UNICODE)
_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")


@dataclass(frozen=True)
class TranscriptionRequest:
    data: bytes
    mime_type: str
    language_hint: Optional[str]
    prompt: str = TRANSCRIPTION_PROMPT


@dataclass(frozen=True)
class CoherenceRequest:
    text: str
    prompt: str = COHERENCE_PROMPT


@dataclass(frozen=True)
class TranscriptionReading:
    text: str
    model: str
    provider: str = "external"
    name: str = "unknown"
    version: str = "unknown"
    latency_ms: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


class VisionTranscriber(Protocol):
    model: str

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionReading:
        ...


class CoherenceReviewer(Protocol):
    model: str

    def review(self, request: CoherenceRequest) -> bool:
        ...


@dataclass(frozen=True)
class MarkedSpan:
    start: int
    end: int
    reasons: tuple[str, ...]


@dataclass
class TranscriptionMetrics:
    pages: int = 0
    spans: int = 0
    escalated: int = 0
    disagreed: int = 0
    to_review: int = 0
    tokens: int = 0
    tokens_to_review: int = 0
    duration_seconds: float = 0.0

    @property
    def review_fraction(self) -> float:
        return self.tokens_to_review / self.tokens if self.tokens else 0.0

    def snapshot(self) -> dict[str, float | int]:
        return {
            "s9_transcription_pages_total": self.pages,
            "s9_transcription_spans_total": self.spans,
            "s9_transcription_escalated_total": self.escalated,
            "s9_transcription_disagreed_total": self.disagreed,
            "s9_transcription_to_review_total": self.to_review,
            "s9_transcription_review_fraction": self.review_fraction,
            's9_stage_duration_seconds{stage="transcription"}': self.duration_seconds,
        }


def _is_sentence_start(text: str, start: int) -> bool:
    prefix = text[:start].rstrip()
    return not prefix or bool(_SENTENCE_END_RE.search(prefix))


def risk_spans(text: str, glossary: set[str] | frozenset[str]) -> tuple[MarkedSpan, ...]:
    """Marca nombres, numeros/fechas y palabras ausentes del glosario."""
    known = {item.casefold() for item in glossary}
    found: list[MarkedSpan] = []
    for match in _WORD_RE.finditer(text):
        token = match.group(0)
        reasons: list[str] = []
        if any(char.isdigit() for char in token):
            reasons.append("NUMBER_OR_DATE")
        if token[:1].isupper() and not _is_sentence_start(text, match.start()):
            reasons.append("PROPER_NAME")
        if token.casefold() not in known and not any(char.isdigit() for char in token):
            reasons.append("OUT_OF_GLOSSARY")
        if reasons:
            found.append(MarkedSpan(match.start(), match.end(), tuple(reasons)))
    return tuple(found)


def literal_diff(first: str, second: str) -> tuple[MarkedSpan, ...]:
    """Devuelve exclusivamente los tramos de la primera lectura que difieren."""
    if first == second:
        return ()
    matcher = difflib.SequenceMatcher(a=first, b=second, autojunk=False)
    spans: list[MarkedSpan] = []
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i1 == i2:
            token = next(
                (m for m in _TOKEN_RE.finditer(first) if m.start() <= i1 < m.end()),
                None,
            )
            if token is None:
                token = next((m for m in reversed(list(_TOKEN_RE.finditer(first[:i1])))), None)
            if token is not None:
                i1, i2 = token.span()
        if i1 < i2:
            overlapping = [
                token
                for token in _TOKEN_RE.finditer(first)
                if token.end() > i1 and token.start() < i2
            ]
            if overlapping:
                i1, i2 = overlapping[0].start(), overlapping[-1].end()
            spans.append(MarkedSpan(i1, i2, ("READING_DISAGREEMENT",)))
    return _merge_spans(spans)


def _merge_spans(spans: list[MarkedSpan]) -> tuple[MarkedSpan, ...]:
    if not spans:
        return ()
    ordered = sorted(spans, key=lambda item: (item.start, item.end))
    merged: list[MarkedSpan] = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start <= previous.end:
            merged[-1] = MarkedSpan(
                previous.start,
                max(previous.end, current.end),
                tuple(sorted(set(previous.reasons) | set(current.reasons))),
            )
        else:
            merged.append(current)
    return tuple(merged)


def _line_spans(text: str, review: tuple[MarkedSpan, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    line_start = 0
    for raw_line in text.splitlines(keepends=True):
        line_end = line_start + len(raw_line.rstrip("\r\n"))
        boundaries = {line_start, line_end}
        for marked in review:
            if marked.end > line_start and marked.start < line_end:
                boundaries.add(max(line_start, marked.start))
                boundaries.add(min(line_end, marked.end))
        points = sorted(boundaries)
        for start, end in zip(points, points[1:]):
            if start == end or not text[start:end]:
                continue
            active = [m for m in review if m.end > start and m.start < end]
            records.append(
                {
                    "start": start,
                    "end": end,
                    "text": text[start:end],
                    "review_required": bool(active),
                    "reason_codes": sorted({r for m in active for r in m.reasons}),
                    "confidence": 0.5 if active else 1.0,
                    "line": text.count("\n", 0, start) + 1,
                }
            )
        line_start += len(raw_line)
    if not text.splitlines(keepends=True) and text:
        records.append(
            {
                "start": 0,
                "end": len(text),
                "text": text,
                "review_required": bool(review),
                "reason_codes": sorted({r for m in review for r in m.reasons}),
                "confidence": 0.5 if review else 1.0,
                "line": 1,
            }
        )
    return records


def _reviewed_token_count(text: str, review: tuple[MarkedSpan, ...]) -> int:
    return sum(
        1
        for token in _TOKEN_RE.finditer(text)
        if any(mark.end > token.start() and mark.start < token.end() for mark in review)
    )


class TranscriptionCascade:
    """Proveedor visual compuesto: dos VLM y una revision textual."""

    provider_kind = "external"
    name = "knowledge_v3.multimodal.transcription_cascade"
    version = "1.0.0"

    def __init__(
        self,
        primary: VisionTranscriber,
        secondary: VisionTranscriber,
        coherence: CoherenceReviewer,
        *,
        glossary: set[str] | frozenset[str] = frozenset(),
        metrics: Optional[TranscriptionMetrics] = None,
    ) -> None:
        if primary.model == secondary.model:
            raise ValueError("las dos lecturas deben usar modelos distintos")
        self.primary = primary
        self.secondary = secondary
        self.coherence = coherence
        self.glossary = frozenset(glossary)
        self.metrics = metrics or TranscriptionMetrics()

    def recognize(self, request: VisualRequest) -> Optional[VisualResult]:
        if request.mode != MODE_HTR:
            return None
        started = time.monotonic()
        first = self.primary.transcribe(
            TranscriptionRequest(
                data=request.data,
                mime_type=request.mime_type,
                language_hint=request.language_hint,
            )
        )
        coherent = self.coherence.review(CoherenceRequest(text=first.text))
        risks = risk_spans(first.text, self.glossary)
        escalated = not coherent or bool(risks)
        second: Optional[TranscriptionReading] = None
        review: tuple[MarkedSpan, ...] = ()
        if escalated:
            second = self.secondary.transcribe(
                TranscriptionRequest(
                    data=request.data,
                    mime_type=request.mime_type,
                    language_hint=request.language_hint,
                )
            )
            review = literal_diff(first.text, second.text)

        records = _line_spans(first.text, review)
        total_tokens = len(_TOKEN_RE.findall(first.text))
        reviewed_tokens = _reviewed_token_count(first.text, review)
        elapsed = time.monotonic() - started
        page_review_fraction = reviewed_tokens / total_tokens if total_tokens else 0.0
        self.metrics.pages += 1
        self.metrics.spans += len(records)
        self.metrics.escalated += int(escalated)
        self.metrics.disagreed += len(review)
        self.metrics.to_review += sum(1 for item in records if item["review_required"])
        self.metrics.tokens += total_tokens
        self.metrics.tokens_to_review += reviewed_tokens
        self.metrics.duration_seconds += elapsed

        models = [first.model] + ([second.model] if second else [])
        return VisualResult(
            mode=MODE_HTR,
            region_id=request.region.region_id,
            confidence=1.0 if not review else max(0.0, 1.0 - page_review_fraction),
            text=first.text,
            provider=first.provider,
            name=self.name,
            version=self.version,
            model=" | ".join(models),
            metadata={
                "lane": "TRANSCRIBED_TEXT",
                "family": TRANSCRIPTION_FAMILY,
                "coherent": coherent,
                "escalated": escalated,
                "risk_spans": [vars(item) for item in risks],
                "review_spans": [vars(item) for item in review],
                "transcription_spans": records,
                "transcription_models": models,
                "coherence_model": self.coherence.model,
            },
        )


class NvidiaVisionTranscriber:
    """VLM NVIDIA real; el transporte y la clave siguen en el proveedor comun."""

    provider_kind = "external"

    def __init__(self, client: Any, *, model: str) -> None:
        self.client = client
        self.model = model

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionReading:
        encoded = base64.b64encode(request.data).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": request.prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{request.mime_type};base64,{encoded}"
                        },
                    },
                ],
            }
        ]
        self.client._assert_safe_to_send({"messages": messages})
        started = time.monotonic()
        out = self.client.chat_json(messages, model=self.model, max_tokens=4096)
        payload = out.get("parsed") or {}
        text = payload.get("transcription")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("respuesta VLM sin transcription literal")
        return TranscriptionReading(
            text=text,
            model=str(out.get("model") or self.model),
            provider="external",
            name="nvidia",
            version="1",
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={
                key: out.get(key, 0)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
        )


class NvidiaCoherenceReviewer:
    """Revision de coherencia que recibe texto, nunca imagen ni contexto de grafo."""

    def __init__(self, client: Any, *, model: str = COHERENCE_MODEL) -> None:
        self.client = client
        self.model = model

    def review(self, request: CoherenceRequest) -> bool:
        messages = [
            {"role": "system", "content": request.prompt},
            {"role": "user", "content": request.text},
        ]
        self.client._assert_safe_to_send({"messages": messages})
        out = self.client.chat_json(messages, model=self.model, max_tokens=32)
        coherent = (out.get("parsed") or {}).get("coherent")
        if not isinstance(coherent, bool):
            raise ValueError("respuesta de coherencia sin booleano coherent")
        return coherent


def build_nvidia_transcription_cascade(
    *,
    repo_root: str = ".",
    glossary: set[str] | frozenset[str] = frozenset(),
    client: Any = None,
) -> TranscriptionCascade:
    """Construye la cascada con los tres modelos verificados en docs/v3/28."""
    if client is None:
        from pathlib import Path

        from external_processing.providers.nvidia import NvidiaProcessingProvider

        client = NvidiaProcessingProvider(Path(repo_root))
    return TranscriptionCascade(
        NvidiaVisionTranscriber(client, model=PRIMARY_VISION_MODEL),
        NvidiaVisionTranscriber(client, model=SECONDARY_VISION_MODEL),
        NvidiaCoherenceReviewer(client),
        glossary=glossary,
    )


__all__ = [
    "COHERENCE_MODEL",
    "COHERENCE_PROMPT",
    "PRIMARY_VISION_MODEL",
    "SECONDARY_VISION_MODEL",
    "TRANSCRIPTION_FAMILY",
    "TRANSCRIPTION_PROMPT",
    "CoherenceRequest",
    "MarkedSpan",
    "NvidiaCoherenceReviewer",
    "NvidiaVisionTranscriber",
    "TranscriptionCascade",
    "TranscriptionMetrics",
    "TranscriptionReading",
    "TranscriptionRequest",
    "build_nvidia_transcription_cascade",
    "literal_diff",
    "risk_spans",
]

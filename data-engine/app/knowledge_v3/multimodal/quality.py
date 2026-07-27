# -*- coding: utf-8 -*-
"""Calidad medida de un episodio (`quality` del contrato `source-episode`).

`score` bajo NO invalida el episodio: lo marca. La decision de que hacer con un
episodio de baja calidad es del motor, no del normalizador. Aqui solo se MIDE.

Todas las medidas son deterministas y explicables: cada penalizacion tiene un
`reason_code` asociado, y el score es 1.0 menos la suma de penalizaciones,
acotado a [0, 1]. Nada de puntuaciones opacas.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Sequence

# ── Codigos de bandera (mismo formato que `reason_code` del contrato) ──────────
EMPTY_TEXT = "EMPTY_TEXT"
SHORT_TEXT = "SHORT_TEXT"
REPLACEMENT_CHARS = "REPLACEMENT_CHARS"
CONTROL_CHARS = "CONTROL_CHARS"
REPEATED_CONTENT = "REPEATED_CONTENT"
NO_NATIVE_TEXT = "NO_NATIVE_TEXT"
UNPROCESSED_PENDING_PROVIDER = "UNPROCESSED_PENDING_PROVIDER"
LOW_ASR_COVERAGE = "LOW_ASR_COVERAGE"
TIMELINE_GAP = "TIMELINE_GAP"
TRUNCATED_TAIL = "TRUNCATED_TAIL"
NO_DIARIZATION = "NO_DIARIZATION"
LOW_PROVIDER_CONFIDENCE = "LOW_PROVIDER_CONFIDENCE"
RAGGED_TABLE = "RAGGED_TABLE"

#: Longitud por debajo de la cual un episodio de texto se marca como corto.
SHORT_TEXT_CHARS = 24

#: Cobertura temporal minima (segundos transcritos / duracion declarada) por
#: debajo de la cual el audio se considera mal cubierto.
MIN_ASR_COVERAGE = 0.80

#: Hueco temporal, en segundos, a partir del cual dos segmentos consecutivos se
#: consideran discontinuos (dossier 7.7: "segmentos sin audio", "saltos").
MAX_SEGMENT_GAP_SECONDS = 3.0

#: Fraccion de la duracion total que puede quedar sin transcribir al final antes
#: de marcar truncado (dossier 7.7: "final ausente").
MAX_TAIL_FRACTION = 0.05

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalizacion CANONICA del texto (NFKC + espacios colapsados + strip).

    Es lo que va a `normalized_text` del `EvidenceFragment`. `literal_text` NO
    pasa por aqui jamas: el literal es exacto por definicion del contrato.
    """
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))


def quality(score: float, flags: Iterable[str] = ()) -> dict[str, Any]:
    """Bloque `quality` del contrato, con banderas ordenadas y sin repetir."""
    return {"score": _clamp(score), "flags": sorted(set(flags))}


def text_quality(text: str | None) -> dict[str, Any]:
    """Calidad de un episodio textual (nativo, OCR, HTR o ASR ya proyectado)."""
    flags: list[str] = []
    penalty = 0.0
    raw = text or ""
    if not raw.strip():
        return quality(0.0, [EMPTY_TEXT])
    if len(raw.strip()) < SHORT_TEXT_CHARS:
        flags.append(SHORT_TEXT)
        penalty += 0.10
    if "�" in raw:
        flags.append(REPLACEMENT_CHARS)
        penalty += 0.30
    if _CONTROL.search(raw):
        flags.append(CONTROL_CHARS)
        penalty += 0.20
    if has_repetition_loop(raw):
        flags.append(REPEATED_CONTENT)
        penalty += 0.25
    return quality(1.0 - penalty, flags)


def has_repetition_loop(text: str, *, min_repeats: int = 3) -> bool:
    """True si el texto contiene un bucle de repeticion literal.

    Los motores ASR degradados entran en bucle y repiten la misma frase decenas
    de veces; un episodio asi tiene texto de sobra y contenido nulo, y sin esta
    medida pasaria como "largo, luego bueno".
    """
    parts = [p for p in re.split(r"[.\n]", text) if p.strip()]
    run = 1
    previous: str | None = None
    for part in parts:
        current = normalize_text(part).lower()
        if previous is not None and current == previous:
            run += 1
            if run >= min_repeats:
                return True
        else:
            run = 1
        previous = current
    return False


def transcript_quality(
    segments: Sequence[tuple[float, float, str]],
    *,
    duration_seconds: float | None,
    diarized: bool,
) -> dict[str, Any]:
    """Calidad global de una transcripcion (dossier 7.7).

    `segments` son tuplas `(start, end, text)` ya ordenadas. Mide cobertura,
    huecos, truncado, repeticion y ausencia de diarizacion.
    """
    flags: list[str] = []
    penalty = 0.0
    if not segments:
        return quality(0.0, [EMPTY_TEXT])

    covered = sum(max(0.0, end - start) for start, end, _ in segments)
    if duration_seconds and duration_seconds > 0:
        coverage = covered / duration_seconds
        if coverage < MIN_ASR_COVERAGE:
            flags.append(LOW_ASR_COVERAGE)
            penalty += 0.25
        tail = duration_seconds - segments[-1][1]
        if tail > max(MAX_SEGMENT_GAP_SECONDS, duration_seconds * MAX_TAIL_FRACTION):
            flags.append(TRUNCATED_TAIL)
            penalty += 0.25

    for previous, current in zip(segments, segments[1:]):
        if current[0] - previous[1] > MAX_SEGMENT_GAP_SECONDS:
            flags.append(TIMELINE_GAP)
            penalty += 0.10
            break

    if has_repetition_loop("\n".join(text for _, _, text in segments)):
        flags.append(REPEATED_CONTENT)
        penalty += 0.25

    if not diarized:
        flags.append(NO_DIARIZATION)

    return quality(1.0 - penalty, flags)


def pending_quality(*extra_flags: str) -> dict[str, Any]:
    """Calidad de un episodio que AUN no tiene contenido reconocido.

    Score 0.0 y bandera `UNPROCESSED_PENDING_PROVIDER`. Es la unica respuesta
    honesta de un adaptador declarado pero sin proveedor detras: no se inventa
    una confianza intermedia para que parezca que algo se proceso.
    """
    return quality(0.0, [UNPROCESSED_PENDING_PROVIDER, *extra_flags])

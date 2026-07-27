# -*- coding: utf-8 -*-
"""Extractor TEMPORAL: expresiones de tiempo ancladas a evidencia.

Produce `temporal_expressions` para el contrato `claim-proposal`. Lo que NO
hace, y es deliberado:

- **no convierte** fechas de mundo de juego a UTC. `valid_from` / `valid_to`
  solo se rellenan cuando la expresion es una fecha ISO real e inequivoca. "el
  ano 300 de la Tercera Era" NO tiene traduccion a UTC y fingirla seria inventar
  un dato; se marca con `calendar_id` y se deja que el ledger decida;
- **no decide vigencias**. Eso es del motor local y del ledger temporal;
- **no infiere estado** (`ACTIVE`/`ENDED`): el pasado verbal no implica que algo
  haya terminado (regla explicita del contrato `fact-assertion`).

`calendar_id` se rellena unicamente si el `GameProfile` declara ese calendario:
sin perfil no hay calendario, y sin calendario declarado, `calendars` no tenia
ningun consumidor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from ..contracts import Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    abstention_claim,
    emit,
)
from .text import EvidenceIndex, Token, find_phrase, phrase_tokens

TEMPORAL_STEP = "extract.temporal"

TEMPORAL_INFO = ExtractorInfo(
    step=TEMPORAL_STEP,
    provider=Provider.LOCAL,
    name="s9k.extraction.temporal",
)

_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|"
    "octubre|noviembre|diciembre"
)

#: Patrones ordenados de MAS especifico a menos. El primero que casa gana: si
#: "desde 1200 hasta 1250" casase antes como dos POINT sueltos, se perderia
#: justamente lo unico que importaba, que es que es un intervalo.
TEMPORAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b\d{4}-\d{2}-\d{2}\b", "POINT"),
    (
        r"\b(?:desde|entre)\s+(?:el\s+)?(?:a[nñ]o\s+)?[\wáéíóúñ]+(?:\s+[\wáéíóúñ]+){0,4}?"
        r"\s+(?:hasta|y)\s+(?:el\s+)?(?:a[nñ]o\s+)?[\wáéíóúñ]+(?:\s+[\wáéíóúñ]+){0,4}\b",
        "INTERVAL",
    ),
    (r"\bdurante\s+(?:\w+\s+)?\d+\s+(?:a[nñ]os?|meses|mes|d[ií]as?|siglos?|lunas?)\b", "DURATION"),
    (r"\bdurante\s+(?:\w+\s+){0,2}(?:a[nñ]os?|meses|d[ií]as?|siglos?|lunas?)\b", "DURATION"),
    (r"\bhace\s+\d+\s+(?:a[nñ]os?|meses|d[ií]as?|siglos?|lunas?)\b", "RELATIVE"),
    (rf"\b\d{{1,2}}\s+de\s+(?:{_MONTHS})(?:\s+de\s+\d{{1,4}})?\b", "POINT"),
    (r"\b(?:el\s+)?a[nñ]o\s+\d{1,5}\b", "POINT"),
    (r"\b(?:en\s+)?el\s+(?:siglo|ciclo)\s+[\w]+\b", "POINT"),
    (r"\b(?:ayer|hoy|ma[nñ]ana|anoche|entonces|ahora|antes|despu[eé]s|m[aá]s tarde)\b", "RELATIVE"),
    (r"\b(?:antes|despu[eé]s)\s+de\s+(?:la|el|los|las)\s+[\wáéíóúñ]+\b", "RELATIVE"),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), kind) for p, kind in TEMPORAL_PATTERNS)

#: Cuantos tokens despues de la expresion se busca la marca de calendario
#: ("... del ano 300 **de la Tercera Era**").
CALENDAR_LOOKAHEAD_TOKENS = 6


@dataclass(frozen=True)
class TemporalMatch:
    """Expresion temporal localizada, con su anclaje y su calendario."""

    text: str
    kind: str
    start: int
    end: int
    fragment_id: Optional[str]
    calendar_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None

    def to_contract(self) -> dict:
        """Entrada de `temporal_expressions` tal y como la exige el contrato."""
        out: dict = {"text": self.text, "kind": self.kind}
        if self.valid_from is not None:
            out["valid_from"] = self.valid_from
        if self.valid_to is not None:
            out["valid_to"] = self.valid_to
        if self.calendar_id is not None:
            out["calendar_id"] = self.calendar_id
        if self.fragment_id is not None:
            out["fragment_id"] = self.fragment_id
        return out


def _iso_point(raw: str) -> Optional[str]:
    """Fecha ISO real -> instante UTC. Si no es una fecha valida, None."""
    try:
        parsed = datetime.strptime(raw.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.strftime("%Y-%m-%dT00:00:00Z")


def _calendar_for(
    tokens: Sequence[Token],
    end_token: int,
    calendars: Sequence[dict],
) -> Optional[str]:
    """Calendario declarado en el perfil cuya marca acompana a la expresion."""
    if not calendars:
        return None
    window_end = min(len(tokens), end_token + 1 + CALENDAR_LOOKAHEAD_TOKENS)
    for calendar in calendars:
        needles = [phrase_tokens(calendar.get("epoch_label", ""))]
        needles += [phrase_tokens(u) for u in calendar.get("units", ()) or ()]
        for needle in needles:
            if not needle:
                continue
            if find_phrase(tokens, needle, lo=max(0, end_token - len(needle) + 1), hi=window_end):
                return calendar.get("calendar_id")
    return None


def extract_temporal_expressions(
    index: EvidenceIndex,
    *,
    calendars: Sequence[dict] = (),
    lo: Optional[int] = None,
    hi: Optional[int] = None,
) -> list[TemporalMatch]:
    """Expresiones temporales del episodio (o del rango de offsets `[lo, hi)`).

    Solo devuelve expresiones ANCLADAS: si el fragmento que las contiene no
    existe, la expresion no sale. El rango permite acotar a una frase, que es
    como la usa el extractor determinista al construir un claim.
    """
    text = index.text or ""
    if not text:
        return []
    lo = 0 if lo is None else lo
    hi = len(text) if hi is None else hi
    taken: list[tuple[int, int]] = []
    out: list[TemporalMatch] = []
    for pattern, kind in _COMPILED:
        for m in pattern.finditer(text, lo, hi):
            start, end = m.start(), m.end()
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue  # ya cubierto por un patron mas especifico
            anchor = index.anchor_span(start, end)
            if anchor is None:
                continue
            covered = [t for t in index.tokens if t.start >= start and t.end <= end]
            calendar_id = (
                _calendar_for(index.tokens, covered[-1].index, calendars) if covered else None
            )
            raw = text[start:end]
            valid_from = _iso_point(raw) if kind == "POINT" else None
            taken.append((start, end))
            out.append(
                TemporalMatch(
                    text=raw,
                    kind=kind,
                    start=start,
                    end=end,
                    fragment_id=anchor.fragment_id,
                    calendar_id=calendar_id,
                    valid_from=valid_from,
                    valid_to=None,
                )
            )
    return sorted(out, key=lambda t: (t.start, t.end))


class TemporalExtractor(Extractor):
    """Emite las expresiones temporales sueltas como propuestas ABSTENIDAS.

    Una expresion temporal por si sola no es una afirmacion: no tiene sujeto,
    objeto ni predicado. Emitirla como claim abstenido la conserva, anclada y
    trazada, para que el motor y el ledger la usen sin que nadie la confunda con
    algo aprobable. La alternativa (descartarla) perderia informacion real.
    """

    info = TEMPORAL_INFO

    def __init__(self, *, emit_standalone: bool = True) -> None:
        self.emit_standalone = emit_standalone

    def supports(self, episode: SourceEpisode) -> bool:
        return bool(episode.text)

    def extract_episode(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        index = ctx.index_of(episode)
        matches = extract_temporal_expressions(index, calendars=ctx.calendars())
        if not matches:
            return out
        if not self.emit_standalone:
            out.diagnostics.append(
                Diagnostic(
                    "TEMPORAL_EXPRESSIONS_FOUND",
                    self.info.step,
                    episode.episode_id,
                    f"{len(matches)} expresiones (emision suelta desactivada)",
                )
            )
            return out
        fragment_ids = [m.fragment_id for m in matches if m.fragment_id]
        claim = abstention_claim(
            info=self.info,
            episode=episode,
            evidence_fragment_ids=fragment_ids or index.fragment_ids[:1],
            reason_codes=["TEMPORAL_EXPRESSION_WITHOUT_CLAIM"],
            temporal_expressions=[m.to_contract() for m in matches],
            metadata={"temporal_kinds": sorted({m.kind for m in matches})},
        )
        emit(claim, out, self.info, episode.episode_id)
        return out


__all__ = [
    "CALENDAR_LOOKAHEAD_TOKENS",
    "TEMPORAL_INFO",
    "TEMPORAL_PATTERNS",
    "TEMPORAL_STEP",
    "TemporalExtractor",
    "TemporalMatch",
    "extract_temporal_expressions",
]

# -*- coding: utf-8 -*-
"""Correferencia INTRA-episodio: pronombres y primera persona -> menciones.

Alcance deliberadamente corto:

- **intra-episodio**. Nada de cadenas entre episodios: eso es resolucion de
  identidad y le toca al subsistema de resolucion, con su propio contrato
  (`entity-resolution`). Aqui solo se rellena `coreference_candidates`;
- **pronombres de tercera persona** -> mencion anterior mas cercana dentro de la
  misma frase o la inmediatamente anterior, y solo si esa mencion tiene tipo. Un
  antecedente sin tipo no da ninguna garantia de que el pronombre concuerde;
- **primera persona** ("yo", "me", "mi") -> el HABLANTE del episodio, y solo si
  `speaker` existe y su etiqueta coincide con una mencion real. Sin diarizacion
  no hay primera persona resoluble, y suponerla es inventar quien habla;
- **alias -> canonico** NO se hace aqui: lo resuelve el extractor determinista
  en el momento de emitir la mencion, que es cuando sabe de que entrada del
  lexico viene cada superficie. Rehacerlo aqui obligaria a reescribir documentos
  ya emitidos y a mentir en su `provider_trace`.

Ambiguedad = no resolver. Un pronombre mal resuelto propaga una identidad
equivocada a todo lo que cuelgue de el, y eso es mucho peor que un pronombre sin
antecedente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ..contracts import EntityMention, Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    build_mention,
    emit,
)
from .text import EvidenceIndex, Token, normalize, phrase_tokens

COREFERENCE_STEP = "extract.coreference"

COREFERENCE_INFO = ExtractorInfo(
    step=COREFERENCE_STEP,
    provider=Provider.LOCAL,
    name="s9k.extraction.coreference",
)

#: Pronombres de tercera persona resolubles por proximidad.
#:
#: Se comparan con el texto ORIGINAL en minusculas, **no** con la forma
#: normalizada: la normalizacion quita las tildes y "el" (articulo) pasaria a
#: ser indistinguible de "el" pronombre. Un extractor que confunde el articulo
#: con el pronombre genera una mencion espuria en cada sintagma del texto.
#: Por lo mismo quedan fuera "este"/"esta"/"aquel" sin tilde: como
#: determinantes son mucho mas frecuentes que como pronombres.
THIRD_PERSON: frozenset = frozenset({"él", "ella", "ellos", "ellas", "éste", "ésta",
                                     "aquél", "aquélla"})

#: Pronombres PERSONALES: exigen un antecedente de tipo `Character`. Un
#: demostrativo ("éste", "aquél") puede referirse a cualquier cosa; "él" y
#: "ella", en un texto de campana, se refieren a personas.
PERSONAL_PRONOUNS: frozenset = frozenset({"él", "ella", "ellos", "ellas"})

#: Primera persona: solo resoluble con `speaker`. "mi" (posesivo) queda fuera;
#: solo entra "mi" con tilde, que si es pronombre. "nosotros" tambien queda
#: fuera: un plural no se resuelve a un unico hablante.
FIRST_PERSON: frozenset = frozenset({"yo", "me", "mí", "conmigo"})

#: Distancia maxima (en tokens) entre el pronombre y su antecedente.
MAX_ANTECEDENT_DISTANCE = 40

#: Confianza de un enlace de correferencia. Nunca alta: es la parte del
#: subsistema con menos evidencia dura detras.
PRONOUN_CONFIDENCE = 0.45


@dataclass(frozen=True)
class _Antecedent:
    mention_id: str
    first_token: int
    end_token: int
    typed: bool
    entity_type: Optional[str]
    normalized_surface: str


def _mention_tokens(mention: EntityMention, tokens: Sequence[Token]) -> Optional[tuple[int, int]]:
    """Rango de tokens que ocupa una mencion ya emitida, por sus offsets."""
    inside = [t.index for t in tokens if t.start >= mention.start and t.end <= mention.end]
    if not inside:
        return None
    return inside[0], inside[-1]


class CoreferenceExtractor(Extractor):
    """Emite menciones de pronombre enlazadas a su antecedente."""

    info = COREFERENCE_INFO

    def __init__(self, *, max_distance: int = MAX_ANTECEDENT_DISTANCE) -> None:
        self.max_distance = max_distance

    def supports(self, episode: SourceEpisode) -> bool:
        return bool(episode.text)

    def _antecedents(
        self, episode: SourceEpisode, index: EvidenceIndex, prior: ExtractionOutput
    ) -> list[_Antecedent]:
        out: list[_Antecedent] = []
        for mention in prior.mentions:
            if mention.episode_id != episode.episode_id:
                continue
            span = _mention_tokens(mention, index.tokens)
            if span is None:
                continue
            out.append(
                _Antecedent(
                    mention.mention_id,
                    span[0],
                    span[1],
                    bool(mention.type_candidates),
                    mention.best_type(),
                    mention.normalized_surface,
                )
            )
        return sorted(out, key=lambda a: a.end_token)

    def _speaker_mention(
        self, episode: SourceEpisode, prior: ExtractionOutput
    ) -> Optional[str]:
        speaker = episode.speaker or None
        if not speaker:
            return None
        label = normalize(str(speaker.get("label") or ""))
        if not label:
            return None
        for mention in prior.mentions:
            if mention.episode_id == episode.episode_id and mention.normalized_surface == label:
                return mention.mention_id
        return None

    def extract_episode(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        if prior is None or not prior.mentions:
            out.diagnostics.append(
                Diagnostic(
                    "COREFERENCE_WITHOUT_MENTIONS", self.info.step, episode.episode_id,
                    "la correferencia necesita menciones previas: no resuelve sobre el vacio",
                )
            )
            return out
        index = ctx.index_of(episode)
        antecedents = self._antecedents(episode, index, prior)
        speaker_id = self._speaker_mention(episode, prior)
        # Tokens que YA forman parte de una mencion emitida: un pronombre no
        # puede solaparse con ellas ("la Orden" contiene "la", no un pronombre).
        occupied = {
            i for a in antecedents for i in range(a.first_token, a.end_token + 1)
        }
        for token in index.tokens:
            norm = token.text.lower()
            target: Optional[str] = None
            kind = ""
            if norm in FIRST_PERSON:
                if speaker_id is None:
                    out.diagnostics.append(
                        Diagnostic(
                            "FIRST_PERSON_WITHOUT_SPEAKER", self.info.step, episode.episode_id,
                            f"{token.text!r}: sin diarizacion no se sabe quien habla",
                        )
                    )
                    continue
                target, kind = speaker_id, "SPEAKER"
            elif norm in THIRD_PERSON:
                if token.index in occupied:
                    continue  # forma parte de una mencion ya emitida ("el Rey")
                candidates = [
                    a for a in antecedents
                    if a.typed and 0 < token.index - a.end_token <= self.max_distance
                ]
                if norm in PERSONAL_PRONOUNS:
                    # Un pronombre personal se refiere a una PERSONA. Sin este
                    # filtro, "Kael entro en Valdor. El vive alli" resolveria el
                    # pronombre a Valdor, que es la mencion mas cercana.
                    candidates = [a for a in candidates if a.entity_type == "Character"]
                if not candidates:
                    out.diagnostics.append(
                        Diagnostic(
                            "PRONOUN_WITHOUT_ANTECEDENT", self.info.step, episode.episode_id,
                            token.text,
                        )
                    )
                    continue
                if len({a.normalized_surface for a in candidates}) > 1:
                    # Varios antecedentes compatibles: resolver seria elegir al
                    # azar, y una identidad mal propagada contamina todo lo que
                    # cuelgue de ella.
                    out.diagnostics.append(
                        Diagnostic(
                            "PRONOUN_AMBIGUOUS", self.info.step, episode.episode_id,
                            f"{token.text}: {sorted({a.normalized_surface for a in candidates})}",
                        )
                    )
                    continue
                target, kind = candidates[-1].mention_id, "NEAREST_TYPED"
            else:
                continue

            anchor = index.anchor_span(token.start, token.end)
            if anchor is None:
                out.diagnostics.append(
                    Diagnostic(
                        "MENTION_WITHOUT_EVIDENCE", self.info.step, episode.episode_id, token.text
                    )
                )
                continue
            mention = build_mention(
                info=self.info,
                episode=episode,
                surface=token.text,
                start=token.start,
                end=token.end,
                evidence_fragment_ids=[anchor.fragment_id],
                type_candidates=[],  # un pronombre no aporta tipo: no se copia el del antecedente
                confidence=PRONOUN_CONFIDENCE,
                coreference_candidates=[target],
                basis=anchor.basis,
                metadata={"coreference_kind": kind, "pronoun": True},
            )
            emit(mention, out, self.info, episode.episode_id)
        return out


__all__ = [
    "COREFERENCE_INFO",
    "COREFERENCE_STEP",
    "FIRST_PERSON",
    "MAX_ANTECEDENT_DISTANCE",
    "PERSONAL_PRONOUNS",
    "PRONOUN_CONFIDENCE",
    "THIRD_PERSON",
    "CoreferenceExtractor",
]

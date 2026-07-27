# -*- coding: utf-8 -*-
"""Eje de EVIDENCIA: que lo citado exista y diga lo que se dice que dice.

El motor no cree a nadie. Un claim trae `evidence_fragment_ids`; este modulo
comprueba, contra los documentos de entrada y no contra una promesa:

1. que cada fragmento citado EXISTE;
2. que pertenece al mismo workspace y al mismo asset que el claim (aislamiento
   duro: una evidencia prestada de otro asset es una falsedad demostrable, no
   un descuido);
3. que su episodio existe y es el del claim;
4. que el TEXTO LITERAL del fragmento esta REALMENTE en el texto del episodio,
   en los offsets que el propio fragmento declara.

El punto 4 es el que convierte "hay evidencia" en "la evidencia dice eso". Sin
el, la evidencia es un identificador bonito: basta con que un extractor
alucine una cita para que el hecho pase. Con el, alucinarla no basta —hay que
alucinarla y ademas acertar los offsets del episodio real.

Para modalidades sin texto plano (imagen, mapa, diagrama) el cotejo literal no
es posible; en ese caso el motor **no da por buena** la comprobacion: la marca
como no verificable (`EVIDENCE_NOT_VERIFIABLE`, aviso), y esos claims arrastran
ademas su propio estatus epistemico (`VISUAL_INFERRED`), que ya los manda a
revision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..contracts.claim import ClaimProposal
from ..contracts.episode import SourceEpisode
from ..contracts.evidence import EvidenceFragment
from . import findings as F
from .config import EngineConfig

#: Modalidades con texto plano cotejable por offsets.
TEXTUAL_MODALITIES = frozenset({"TEXT", "OCR_TEXT", "HTR_TEXT", "ASR_TEXT", "SPEAKER_TURN", "MESSAGE"})


@dataclass
class EvidenceIndex:
    """Indice de fragmentos y episodios del lote en proceso."""

    fragments: dict[str, EvidenceFragment]
    episodes: dict[str, SourceEpisode]

    @classmethod
    def build(
        cls, fragments: Iterable[EvidenceFragment], episodes: Iterable[SourceEpisode]
    ) -> "EvidenceIndex":
        return cls(
            fragments={f.fragment_id: f for f in fragments},
            episodes={e.episode_id: e for e in episodes},
        )

    def fragment(self, fragment_id: str) -> Optional[EvidenceFragment]:
        return self.fragments.get(fragment_id)

    def episode(self, episode_id: str) -> Optional[SourceEpisode]:
        return self.episodes.get(episode_id)


def verify_evidence(
    claim: ClaimProposal, index: EvidenceIndex, config: EngineConfig
) -> list[F.Finding]:
    """Comprueba la evidencia de un claim. Devuelve los hallazgos del eje."""
    out: list[F.Finding] = []

    episode = index.episode(claim.episode_id)
    if episode is None:
        out.append(F.EVIDENCE_EPISODE_UNKNOWN(f"episodio {claim.episode_id} no esta en el lote"))
    elif episode.quality.get("score", 0.0) < config.min_episode_quality:
        out.append(
            F.LOW_QUALITY_EPISODE(
                f"calidad {episode.quality.get('score')} < {config.min_episode_quality}"
            )
        )

    verified_any = False
    for fragment_id in claim.evidence_fragment_ids:
        fragment = index.fragment(fragment_id)
        if fragment is None:
            out.append(F.EVIDENCE_FRAGMENT_UNKNOWN(f"fragmento {fragment_id} no esta en el lote"))
            continue
        if (
            fragment.workspace != claim.workspace
            or fragment.source_asset_id != claim.source_asset_id
        ):
            out.append(
                F.EVIDENCE_FOREIGN_ASSET(
                    f"{fragment_id} pertenece a {fragment.workspace}/{fragment.source_asset_id}"
                )
            )
            continue
        if fragment.episode_id != claim.episode_id:
            out.append(
                F.EVIDENCE_EPISODE_UNKNOWN(
                    f"{fragment_id} cita el episodio {fragment.episode_id}, no {claim.episode_id}"
                )
            )
            continue
        if fragment.confidence < config.min_fragment_confidence:
            out.append(
                F.EVIDENCE_LOW_CONFIDENCE(
                    f"{fragment_id}: {fragment.confidence} < {config.min_fragment_confidence}"
                )
            )
        verified = _verify_literal(fragment, index.episode(fragment.episode_id), config, out)
        verified_any = verified_any or verified

    if verified_any:
        out.append(F.EVIDENCE_LITERAL_VERIFIED("al menos una cita cotejada contra el episodio"))
    return out


def _verify_literal(
    fragment: EvidenceFragment,
    episode: Optional[SourceEpisode],
    config: EngineConfig,
    out: list[F.Finding],
) -> bool:
    """Cotejo del texto citado contra el episodio. True si quedo VERIFICADO."""
    if episode is None:
        out.append(F.EVIDENCE_NOT_VERIFIABLE(f"{fragment.fragment_id}: episodio ausente"))
        return False
    if episode.modality not in TEXTUAL_MODALITIES or not episode.text:
        out.append(
            F.EVIDENCE_NOT_VERIFIABLE(
                f"{fragment.fragment_id}: modalidad {episode.modality} sin texto cotejable"
            )
        )
        return False
    if not config.require_literal_evidence:
        out.append(F.EVIDENCE_NOT_VERIFIABLE(f"{fragment.fragment_id}: cotejo literal desactivado"))
        return False

    text = episode.text
    if fragment.start > len(text) or fragment.end > len(text):
        out.append(
            F.EVIDENCE_OFFSETS_OUT_OF_RANGE(
                f"{fragment.fragment_id}: [{fragment.start},{fragment.end}] fuera de "
                f"un episodio de {len(text)} caracteres"
            )
        )
        return False
    if text[fragment.start : fragment.end] != fragment.literal_text:
        out.append(
            F.EVIDENCE_TEXT_MISMATCH(
                f"{fragment.fragment_id}: el episodio dice "
                f"{text[fragment.start:fragment.end]!r}, la cita dice {fragment.literal_text!r}"
            )
        )
        return False
    return True

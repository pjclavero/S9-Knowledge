# -*- coding: utf-8 -*-
"""Adaptador de texto plano y notas.

Un episodio por parrafo (`modality=TEXT`), un fragmento de evidencia por frase
(`media_type=EMBEDDED_TEXT`). Los offsets del fragmento son relativos al TEXTO
DEL EPISODIO, no al fichero: el episodio es la unidad direccionable del
contrato, y un offset relativo al fichero obligaria a reabrir la fuente para
verificar una cita.
"""
from __future__ import annotations

from ..base import AdapterOutput, EpisodeDraft, FragmentDraft, IngestOptions, SourceAdapter, SourceInput
from ..quality import text_quality
from ..textutil import decode_text, split_paragraphs, split_sentences


def episodes_from_text(
    text: str, *, page: int | None = None, media_type: str = "EMBEDDED_TEXT"
) -> list[EpisodeDraft]:
    """Parrafos -> episodios TEXT con un fragmento por frase."""
    drafts: list[EpisodeDraft] = []
    for _, _, paragraph in split_paragraphs(text):
        fragments = [
            FragmentDraft(
                literal_text=sentence,
                start=start,
                end=end,
                media_type=media_type,
                confidence=1.0,
                page=page,
            )
            for start, end, sentence in split_sentences(paragraph)
        ]
        drafts.append(
            EpisodeDraft(
                modality="TEXT",
                text=paragraph,
                page=page,
                quality=text_quality(paragraph),
                fragments=fragments,
            )
        )
    return drafts


class PlainTextAdapter(SourceAdapter):
    """`TEXT` y `NOTE`: el caso base, sin ningun proveedor por medio."""

    name = "knowledge_v3.multimodal.adapters.text"
    source_kinds = ("TEXT", "NOTE")
    mime_types = ("text/plain",)
    extensions = (".txt", ".text", ".note")
    is_stub = False

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        text = decode_text(source.data, where=source.original_name)
        episodes = episodes_from_text(text)
        if not episodes:
            from .. import errors

            raise errors.NormalizationError(
                errors.EMPTY_SOURCE,
                f"{source.original_name} no contiene texto: 0 parrafos",
            )
        return AdapterOutput(
            source_kind=source.source_kind or "TEXT",
            mime_type="text/plain",
            episodes=episodes,
            trace_steps=[self.local_step(["episodes", "text", "evidence_fragments"])],
            report={"paragraphs": len(episodes), "characters": len(text)},
        )

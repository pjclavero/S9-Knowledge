# -*- coding: utf-8 -*-
"""Adaptador Markdown: secciones por encabezado y tablas como episodios `TABLE`.

Dos reglas que no se negocian:

1. **Nada se descarta.** La linea de encabezado se conserva literal dentro del
   texto del episodio, ademas de exponerse como `heading_path` en `metadata`. Si
   se descartara, la evidencia de un titulo no tendria donde anclarse.
2. **Una tabla no se aplana.** Un bloque de tabla Markdown sale del flujo de
   texto y se convierte en un episodio `TABLE` con su estructura, igual que un
   CSV. Aplanarla a texto perderia la relacion fila-columna.
"""
from __future__ import annotations

import re

from .. import errors
from ..base import AdapterOutput, EpisodeDraft, IngestOptions, SourceAdapter, SourceInput
from ..textutil import decode_text
from .table import is_markdown_table_separator, parse_markdown_table, table_episode
from .text import episodes_from_text

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _heading_path(stack: list[str]) -> list[str]:
    return [h for h in stack if h]


def _flush_text(
    buffer: list[str], heading_path: list[str], out: list[EpisodeDraft]
) -> None:
    text = "\n".join(buffer).strip("\n")
    if not text.strip():
        return
    for draft in episodes_from_text(text):
        draft.metadata = {"heading_path": list(heading_path)}
        out.append(draft)


def parse_markdown(text: str) -> list[EpisodeDraft]:
    """Markdown -> borradores de episodio, en orden de aparicion."""
    lines = text.split("\n")
    drafts: list[EpisodeDraft] = []
    stack: list[str] = [""] * 6
    buffer: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = _HEADING.match(line)
        if heading:
            _flush_text(buffer, _heading_path(stack), drafts)
            buffer = []
            level = len(heading.group(1))
            stack[level - 1] = heading.group(2).strip()
            for deeper in range(level, 6):
                stack[deeper] = ""
            buffer.append(line)
            index += 1
            continue
        if (
            line.strip().startswith("|")
            and index + 1 < len(lines)
            and is_markdown_table_separator(lines[index + 1])
        ):
            _flush_text(buffer, _heading_path(stack), drafts)
            buffer = []
            block = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            header, rows = parse_markdown_table(block)
            if rows:
                drafts.append(
                    table_episode(
                        header,
                        rows,
                        metadata={
                            "table_source": "markdown",
                            "heading_path": _heading_path(stack),
                        },
                    )
                )
            continue
        buffer.append(line)
        index += 1
    _flush_text(buffer, _heading_path(stack), drafts)
    return drafts


class MarkdownAdapter(SourceAdapter):
    """`MARKDOWN`: secciones, parrafos y tablas."""

    name = "knowledge_v3.multimodal.adapters.markdown"
    source_kinds = ("MARKDOWN",)
    mime_types = ("text/markdown", "text/x-markdown")
    extensions = (".md", ".markdown")
    is_stub = False

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        text = decode_text(source.data, where=source.original_name)
        episodes = parse_markdown(text)
        if not episodes:
            raise errors.NormalizationError(
                errors.EMPTY_SOURCE,
                f"{source.original_name} no contiene contenido Markdown",
            )
        tables = sum(1 for e in episodes if e.modality == "TABLE")
        return AdapterOutput(
            source_kind="MARKDOWN",
            mime_type="text/markdown",
            episodes=episodes,
            trace_steps=[self.local_step(["episodes", "text", "table", "evidence_fragments"])],
            report={
                "markdown_text_episodes": len(episodes) - tables,
                "markdown_table_episodes": tables,
            },
        )

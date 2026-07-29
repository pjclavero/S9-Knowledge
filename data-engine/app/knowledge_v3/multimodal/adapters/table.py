# -*- coding: utf-8 -*-
"""Adaptador de tablas: CSV y tabla Markdown -> episodio `TABLE`.

El episodio lleva LAS DOS cosas:

* `table`: la representacion estructurada (cabecera + filas). Es lo que hace que
  una tabla sea una tabla, y el contrato la exige para `modality=TABLE`.
* `text`: una renderizacion canonica de esa misma tabla.

No es duplicar informacion por comodidad: sin `text` no hay ningun sitio contra
el que anclar offsets, y una evidencia de tabla sin anclaje no se puede
verificar. Con las dos, no se pierde la estructura ni la trazabilidad. La
renderizacion es determinista (`" | "` entre celdas, `"\\n"` entre filas), asi
que los offsets son reproducibles.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Optional, Sequence

from .. import errors
from ..base import AdapterOutput, EpisodeDraft, FragmentDraft, IngestOptions, SourceAdapter, SourceInput
from ..quality import RAGGED_TABLE, quality
from ..textutil import decode_text

#: Separador canonico de celdas en la renderizacion textual del episodio.
CELL_SEPARATOR = " | "


def render_table(header: Sequence[str], rows: Sequence[Sequence[Optional[str]]]) -> str:
    """Renderizacion canonica y determinista de la tabla."""
    lines = []
    if header:
        lines.append(CELL_SEPARATOR.join(header))
    for row in rows:
        lines.append(CELL_SEPARATOR.join("" if c is None else c for c in row))
    return "\n".join(lines)


def table_episode(
    header: Sequence[str],
    rows: Sequence[Sequence[Optional[str]]],
    *,
    metadata: Optional[dict[str, Any]] = None,
) -> EpisodeDraft:
    """Episodio `TABLE` con estructura, renderizacion y un fragmento por fila."""
    header = [str(c) for c in header]
    text = render_table(header, rows)
    flags: list[str] = []
    penalty = 0.0
    if header and any(len(row) != len(header) for row in rows):
        flags.append(RAGGED_TABLE)
        penalty = 0.2

    fragments: list[FragmentDraft] = []
    cursor = 0
    if header:
        cursor += len(CELL_SEPARATOR.join(header)) + 1
    for row in rows:
        line = CELL_SEPARATOR.join("" if c is None else c for c in row)
        if line.strip():
            fragments.append(
                FragmentDraft(
                    literal_text=line,
                    start=cursor,
                    end=cursor + len(line),
                    media_type="TABLE",
                    confidence=1.0,
                )
            )
        cursor += len(line) + 1

    return EpisodeDraft(
        modality="TABLE",
        text=text,
        table={"header": header, "rows": [[c for c in row] for row in rows]},
        quality=quality(1.0 - penalty, flags),
        fragments=fragments,
        metadata=metadata,
    )


def parse_markdown_table(lines: Sequence[str]) -> tuple[list[str], list[list[str]]]:
    """Cabecera y filas de un bloque de tabla Markdown ya delimitado."""
    def cells(line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [c.strip() for c in stripped.split("|")]

    header = cells(lines[0])
    rows = [cells(line) for line in lines[2:] if line.strip()]
    return header, rows


def is_markdown_table_separator(line: str) -> bool:
    """True si la linea es el separador `|---|:--:|` de una tabla Markdown."""
    stripped = line.strip()
    if not stripped.startswith("|") or "-" not in stripped:
        return False
    body = stripped.strip("|")
    return all(
        cell.strip() and set(cell.strip()) <= set(":- ") and "-" in cell
        for cell in body.split("|")
    )


class CsvTableAdapter(SourceAdapter):
    """`TABLE` desde CSV. Un unico episodio `TABLE` por fichero."""

    name = "knowledge_v3.multimodal.adapters.table"
    source_kinds = ("TABLE",)
    mime_types = ("text/csv",)
    extensions = (".csv",)
    is_stub = False

    #: Delimitador por defecto. Se puede fijar por `payload["delimiter"]`; NO se
    #: adivina: un sniffer que se equivoca convierte una tabla en una columna.
    default_delimiter = ","

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        text = decode_text(source.data, where=source.original_name)
        payload = dict(source.payload or {})
        delimiter = payload.get("delimiter", self.default_delimiter)
        has_header = bool(payload.get("has_header", True))
        rows = [
            row
            for row in csv.reader(io.StringIO(text), delimiter=delimiter)
            if any((cell or "").strip() for cell in row)
        ]
        if not rows:
            raise errors.NormalizationError(
                errors.EMPTY_SOURCE, f"{source.original_name} no contiene filas"
            )
        header = rows[0] if has_header else []
        body = rows[1:] if has_header else rows
        if not body:
            raise errors.NormalizationError(
                errors.NO_CONTENT_EXTRACTED,
                f"{source.original_name} solo tiene cabecera: no hay datos que anclar",
            )
        episode = table_episode(header, body, metadata={"table_source": "csv"})
        return AdapterOutput(
            source_kind="TABLE",
            mime_type="text/csv",
            episodes=[episode],
            trace_steps=[self.local_step(["episodes", "table", "evidence_fragments"])],
            report={"table_rows": len(body), "table_columns": len(header or body[0])},
        )

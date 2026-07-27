# -*- coding: utf-8 -*-
"""Adaptador PDF con texto nativo (pypdf), pagina a pagina.

Implementa la primera rama del flujo del dosier 7.5: **si el texto nativo es
suficiente, no se aplica OCR**. Una pagina con texto nativo produce episodios
`TEXT` con `page` y evidencia `EMBEDDED_TEXT`; una pagina sin texto extraible
produce un episodio `IMAGE` marcado `NO_NATIVE_TEXT` +
`UNPROCESSED_PENDING_PROVIDER`, con bbox de pagina completa y **cero
fragmentos**.

Ese episodio pendiente es el punto de enganche del subsistema de proveedores:
la pagina queda direccionable, ordenada y trazada, y cuando OCR/HTR se ejecute
de verdad producira sus propios episodios sobre el mismo asset. Lo que NO hace
este adaptador es fingir que la pagina se proceso: `score = 0.0`, sin texto y
sin evidencia.

Dependencia: `pypdf`, ya presente y pineada en `data-engine/requirements.lock`
(`pypdf==6.14.2`). No se anade ninguna dependencia nueva.
"""
from __future__ import annotations

import io

from .. import errors
from ..base import AdapterOutput, EpisodeDraft, IngestOptions, SourceAdapter, SourceInput
from ..quality import NO_NATIVE_TEXT, pending_quality
from .text import episodes_from_text

#: Caracteres no blancos minimos para considerar que una pagina tiene texto
#: nativo aprovechable. Por debajo, la pagina se enruta a OCR en vez de dar por
#: buena una linea suelta de cabecera como si fuera el contenido de la pagina.
MIN_NATIVE_CHARS = 16

#: bbox de pagina completa para las paginas pendientes de reconocimiento.
FULL_PAGE_BBOX = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}


class PdfAdapter(SourceAdapter):
    """`PDF`: extraccion de texto por pagina; sin texto -> pendiente de OCR."""

    name = "knowledge_v3.multimodal.adapters.pdf"
    source_kinds = ("PDF",)
    mime_types = ("application/pdf",)
    extensions = (".pdf",)
    is_stub = False

    min_native_chars = MIN_NATIVE_CHARS

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependencia declarada
            raise errors.NormalizationError(
                errors.UNSUPPORTED_SOURCE_KIND, f"pypdf no disponible: {exc}"
            ) from exc

        if not source.data.startswith(b"%PDF-"):
            raise errors.NormalizationError(
                errors.CORRUPT_SOURCE,
                f"{source.original_name} no empieza por %PDF-: no es un PDF",
            )
        try:
            reader = PdfReader(io.BytesIO(source.data))
            pages = list(reader.pages)
        except Exception as exc:  # pypdf lanza varios tipos propios
            raise errors.NormalizationError(
                errors.CORRUPT_SOURCE,
                f"{source.original_name} no se puede abrir como PDF: {exc}",
            ) from exc

        if not pages:
            raise errors.NormalizationError(
                errors.EMPTY_SOURCE, f"{source.original_name} no tiene paginas"
            )

        episodes: list[EpisodeDraft] = []
        with_text = 0
        pending: list[int] = []
        for index, page in enumerate(pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise errors.NormalizationError(
                    errors.CORRUPT_SOURCE,
                    f"pagina {index} de {source.original_name} ilegible: {exc}",
                ) from exc
            if len(text.strip()) >= self.min_native_chars:
                with_text += 1
                episodes.extend(episodes_from_text(text, page=index))
            else:
                pending.append(index)
                episodes.append(
                    EpisodeDraft(
                        modality="IMAGE",
                        text=None,
                        page=index,
                        bbox={**FULL_PAGE_BBOX, "page": index},
                        quality=pending_quality(NO_NATIVE_TEXT),
                        metadata={
                            "pending_reason": "NO_NATIVE_TEXT",
                            "next_adapters": ["OCR_TEXT", "HTR_TEXT", "IMAGE_DESCRIPTION"],
                            "native_characters": len(text.strip()),
                        },
                    )
                )

        return AdapterOutput(
            source_kind="PDF",
            mime_type="application/pdf",
            episodes=episodes,
            trace_steps=[self.local_step(["episodes", "text", "page", "evidence_fragments"])],
            report={
                "pdf_pages": len(pages),
                "pdf_pages_with_native_text": with_text,
                "pdf_pages_pending_recognition": pending,
            },
        )

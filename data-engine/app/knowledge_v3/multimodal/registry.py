# -*- coding: utf-8 -*-
"""Registro de adaptadores por tipo de fuente.

La resolucion es EXPLICITA por `source_kind` y, solo si el llamante no lo
declara, se deduce por MIME y despues por extension. El orden importa: adivinar
el tipo de una fuente cuando el llamante ya lo ha dicho es como se acaba
tratando un PDF escaneado como si tuviera texto nativo.

El registro no tiene estado global mutable escondido: `default_registry()`
construye uno nuevo con los adaptadores de serie, y quien quiera otro conjunto
(por ejemplo, con un proveedor de OCR real inyectado) construye el suyo.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable, Optional

from . import errors
from .base import SourceAdapter, SourceInput


class AdapterRegistry:
    """Adaptadores indexados por `source_kind`, MIME y extension."""

    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        self._by_kind: dict[str, SourceAdapter] = {}
        self._by_mime: dict[str, SourceAdapter] = {}
        self._by_extension: dict[str, SourceAdapter] = {}
        self._adapters: list[SourceAdapter] = []
        for adapter in adapters:
            self.register(adapter)

    # -- Registro ----------------------------------------------------------
    def register(self, adapter: SourceAdapter, *, replace: bool = False) -> SourceAdapter:
        """Registra un adaptador. Sin `replace`, pisar algo ya cubierto es un error.

        Vale para las TRES claves de resolucion: `source_kind`, MIME y
        extension. Una colision de MIME o de extension que se resolviera en
        silencio dejaria el resultado del normalizador a merced del orden de
        importacion, que es exactamente lo que el determinismo prohibe.
        """
        claims = (
            (self._by_kind, adapter.source_kinds, "source_kind", False),
            (self._by_mime, adapter.mime_types, "mime_type", True),
            (self._by_extension, adapter.extensions, "extension", True),
        )
        for table, keys, label, lower in claims:
            for key in keys:
                normalized = key.lower() if lower else key
                current = table.get(normalized)
                if current is not None and current is not adapter and not replace:
                    raise errors.NormalizationError(
                        errors.DUPLICATE_ADAPTER,
                        f"{label} {normalized!r} ya lo cubre {current.name!r}; "
                        "dos adaptadores compitiendo por la misma clave hacen que "
                        "el resultado dependa del orden de registro",
                    )
        for table, keys, _, lower in claims:
            for key in keys:
                table[key.lower() if lower else key] = adapter
        self._adapters = [a for a in self._adapters if a is not adapter] + [adapter]
        return adapter

    # -- Consulta ----------------------------------------------------------
    @property
    def adapters(self) -> list[SourceAdapter]:
        return list(self._adapters)

    def source_kinds(self) -> list[str]:
        return sorted(self._by_kind)

    def get(self, source_kind: str) -> SourceAdapter:
        adapter = self._by_kind.get(source_kind)
        if adapter is None:
            raise errors.NormalizationError(
                errors.UNSUPPORTED_SOURCE_KIND,
                f"sin adaptador para source_kind={source_kind!r}; "
                f"registrados: {self.source_kinds()}",
            )
        return adapter

    def resolve(self, source: SourceInput) -> SourceAdapter:
        """Adaptador que corresponde a la fuente: kind declarado > MIME > extension."""
        if source.source_kind:
            return self.get(source.source_kind)
        if source.mime_type:
            adapter = self._by_mime.get(source.mime_type.lower())
            if adapter is not None:
                return adapter
        extension = PurePosixPath(source.original_name).suffix.lower()
        adapter = self._by_extension.get(extension)
        if adapter is not None:
            return adapter
        raise errors.NormalizationError(
            errors.UNSUPPORTED_SOURCE_KIND,
            f"no se puede determinar el adaptador de {source.original_name!r} "
            f"(mime={source.mime_type!r}, extension={extension!r}); "
            "declara source_kind explicitamente",
        )

    def inventory(self) -> list[dict]:
        """Inventario legible: que hay registrado y que es real frente a stub."""
        return sorted(
            (
                {
                    "name": a.name,
                    "version": a.version,
                    "source_kinds": list(a.source_kinds),
                    "mime_types": list(a.mime_types),
                    "extensions": list(a.extensions),
                    "implementation": "stub" if a.is_stub else "real",
                }
                for a in self._adapters
            ),
            key=lambda entry: entry["name"],
        )


def default_registry(
    *, visual_provider: Optional[object] = None, extra: Iterable[SourceAdapter] = ()
) -> AdapterRegistry:
    """Registro con los adaptadores de serie.

    `visual_provider` se inyecta en los adaptadores visuales (OCR, HTR, imagen,
    dibujo). Si es `None`, esos adaptadores siguen registrados pero producen
    episodios pendientes de proveedor: declarados, no fingidos.
    """
    from .adapters.markdown import MarkdownAdapter
    from .adapters.pdf import PdfAdapter
    from .adapters.table import CsvTableAdapter
    from .adapters.text import PlainTextAdapter
    from .adapters.transcript import (
        AudioTranscriptAdapter,
        VideoTranscriptAdapter,
        YouTubeTranscriptAdapter,
    )
    from .adapters.visual import (
        DrawingAdapter,
        HandwritingAdapter,
        ImageAdapter,
    )

    return AdapterRegistry(
        [
            PlainTextAdapter(),
            MarkdownAdapter(),
            CsvTableAdapter(),
            PdfAdapter(),
            AudioTranscriptAdapter(),
            VideoTranscriptAdapter(),
            YouTubeTranscriptAdapter(),
            ImageAdapter(provider=visual_provider),
            HandwritingAdapter(provider=visual_provider),
            DrawingAdapter(provider=visual_provider),
            *extra,
        ]
    )

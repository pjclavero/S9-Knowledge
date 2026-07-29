# -*- coding: utf-8 -*-
"""Punto de entrada del normalizador multimodal.

    fuente -> SourceAsset -> SourceEpisode(s) -> EvidenceFragment(s)

Todo lo que sale de aqui esta validado contra los contratos congelados
`v3-internal-v1`. Nada de esto escribe en Neo4j, llama a un proveedor externo ni
consulta el reloj: es una funcion pura de (bytes, payload, opciones).

Determinismo
------------
`normalize()` sobre el mismo fichero y las mismas opciones produce documentos
identicos byte a byte, incluidos los identificadores. Se comprueba en los tests
comparando `to_json()` de dos ejecuciones distintas.
"""
from __future__ import annotations

from typing import Optional

from . import errors, ids
from .base import (
    AdapterOutput,
    IngestOptions,
    NormalizationResult,
    SourceAdapter,
    SourceInput,
    assemble,
)
from .registry import AdapterRegistry, default_registry


def normalize(
    source: SourceInput,
    options: IngestOptions,
    *,
    registry: Optional[AdapterRegistry] = None,
) -> NormalizationResult:
    """Normaliza una fuente a documentos `v3-internal-v1` validados."""
    registry = registry if registry is not None else default_registry()
    adapter: SourceAdapter = registry.resolve(source)

    content = adapter.content_bytes(source)
    if not content:
        raise errors.NormalizationError(
            errors.EMPTY_SOURCE,
            f"{source.original_name} no tiene contenido: 0 bytes; un asset sin "
            "contenido no tiene content_hash que valga nada",
        )
    content_hash_hex = ids.sha256_bytes(content)

    output: AdapterOutput = adapter.extract(source, options)
    if not output.episodes:
        raise errors.NormalizationError(
            errors.NO_CONTENT_EXTRACTED,
            f"{adapter.name} no extrajo ningun episodio de {source.original_name!r}",
        )
    result = assemble(source, options, output, content_hash_hex, len(content))
    result.report["adapter"] = adapter.name
    result.report["adapter_version"] = adapter.version
    result.report["adapter_implementation"] = "stub" if adapter.is_stub else "real"
    return result


def normalize_bytes(
    data: bytes,
    *,
    original_name: str,
    original_location: str,
    options: IngestOptions,
    source_kind: Optional[str] = None,
    mime_type: Optional[str] = None,
    payload: Optional[dict] = None,
    registry: Optional[AdapterRegistry] = None,
) -> NormalizationResult:
    """Azucar sobre `normalize()` para el caso corriente de un fichero en memoria."""
    return normalize(
        SourceInput(
            data=data,
            original_name=original_name,
            original_location=original_location,
            mime_type=mime_type,
            source_kind=source_kind,
            payload=payload,
        ),
        options,
        registry=registry,
    )

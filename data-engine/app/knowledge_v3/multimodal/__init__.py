# -*- coding: utf-8 -*-
"""Subsistema A de S9-Knowledge V3: ingesta y normalizacion multimodal.

    fuente -> `SourceAsset` -> `SourceEpisode`(s) -> `EvidenceFragment`(s)

Todo se valida contra los contratos CONGELADOS de `contracts/knowledge-v3/v1/`.
Este subsistema no escribe en Neo4j, no ejecuta proveedores externos y no
consulta el reloj.

Adaptadores REALES: texto, Markdown, PDF nativo, tabla (CSV y Markdown),
transcripcion de audio/video/YouTube (envolviendo la salida existente de
`media/`, `audio/` y `youtube/`, que son de solo lectura para V3).

Adaptadores DECLARADOS con implementacion stub honesta: OCR, HTR, imagen y
dibujo. Tienen puerto (`multimodal.adapters.visual.VisualProvider`), enrutado
por region y proyeccion completa a contratos; lo que no tienen es proveedor. Sin
el, emiten episodios `UNPROCESSED_PENDING_PROVIDER` con `score = 0.0` y sin
evidencia. No devuelven texto que nadie haya leido.

Ver `docs/v3/02-multimodal.md`.
"""
from __future__ import annotations

from . import errors, ids, quality, textutil  # noqa: F401
from .base import (  # noqa: F401
    NORMALIZER_VERSION,
    STEP_ANCHOR,
    STEP_EXTRACT,
    STEP_INGEST,
    AdapterOutput,
    EpisodeDraft,
    FragmentDraft,
    IngestOptions,
    NormalizationResult,
    SourceAdapter,
    SourceInput,
    assemble,
)
from .errors import NormalizationError  # noqa: F401
from .normalizer import normalize, normalize_bytes  # noqa: F401
from .registry import AdapterRegistry, default_registry  # noqa: F401
from .transcription import (  # noqa: F401
    TranscriptionCascade,
    TranscriptionMetrics,
    build_nvidia_transcription_cascade,
)

__all__ = [
    "NORMALIZER_VERSION",
    "STEP_ANCHOR",
    "STEP_EXTRACT",
    "STEP_INGEST",
    "AdapterOutput",
    "AdapterRegistry",
    "EpisodeDraft",
    "FragmentDraft",
    "IngestOptions",
    "NormalizationError",
    "NormalizationResult",
    "SourceAdapter",
    "SourceInput",
    "TranscriptionCascade",
    "TranscriptionMetrics",
    "assemble",
    "build_nvidia_transcription_cascade",
    "default_registry",
    "errors",
    "ids",
    "normalize",
    "normalize_bytes",
    "quality",
    "textutil",
]

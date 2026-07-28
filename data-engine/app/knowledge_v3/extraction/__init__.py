# -*- coding: utf-8 -*-
"""Subsistema EXTRACTOR de S9-Knowledge V3.

Entrada: `SourceEpisode` + `EvidenceFragment` (contratos congelados
`v3-internal-v1`). Salida: `EntityMention` y `ClaimProposal`. **Nunca grafo.**

    determinista  glosario + patrones + reglas de evidencia inequivoca  (local)
    tabla         estructura fila-columna de un episodio TABLE           (local)
    temporal      expresiones de tiempo ancladas, con calendario         (local)
    correferencia pronombres y primera persona -> menciones              (local)
    ollama        LLM local; propone, con tope de confianza y revision   (ollama)
    externo       SOLO punto de enganche; el transporte vive fuera       (external)
    visual        interfaz + stub honesto; VISUAL_INFERRED pendiente     (-)

Tres invariantes atraviesan todo el subsistema:

- **anclaje real**: ninguna propuesta sale sin un fragmento existente que la
  sostenga, y las citas de los modelos se verifican contra el texto literal;
- **traza veraz**: `provider_trace` y `produced_by_step` dicen quien produjo
  cada cosa; una salida externa no se disfraza nunca de local;
- **abstencion legitima**: `abstained=True` con confianza 0 es una salida de
  primera clase. Es preferible por contrato a inventar un predicado.

Ver `docs/v3/03-extractor.md` para la arquitectura y los limites conocidos.
"""
from __future__ import annotations

from .base import (  # noqa: F401
    ALLOWED_ENTITY_TYPES,
    EXTRACTOR_VERSION,
    Diagnostic,
    ExtractionContext,
    ExtractionError,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    abstention_claim,
    build_claim,
    build_mention,
    emit,
    make_id,
)
from .coreference import COREFERENCE_STEP, CoreferenceExtractor  # noqa: F401
from .deterministic import (  # noqa: F401
    DETERMINISTIC_STEP,
    RELATION_RULES,
    DeterministicExtractor,
    RelationRule,
)
from .external import (  # noqa: F401
    EXTERNAL_STEP,
    ExternalExtractionRequest,
    ExternalExtractionResponse,
    ExternalExtractor,
    ExternalProposalPort,
)
from .lexicon import Lexicon, LexiconEntry  # noqa: F401
from .ollama import OLLAMA_STEP, OllamaExtractor, build_prompt, parse_strict_json  # noqa: F401
from .ollama_client import (  # noqa: F401
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    OllamaClient,
    OllamaConfig,
    OllamaError,
    OllamaUnavailable,
)
from .payload import normalize_payload, normalize_predicate  # noqa: F401
from .pipeline import ExtractionPipeline  # noqa: F401
from .table import TABLE_STEP, ColumnRule, TableExtractor  # noqa: F401
from .temporal import (  # noqa: F401
    TEMPORAL_STEP,
    TemporalExtractor,
    extract_temporal_expressions,
)
from .text import EvidenceIndex, normalize, tokenize  # noqa: F401
from .visual import VISUAL_STEP, VisionPort, VisualExtractor  # noqa: F401

__all__ = [
    "ALLOWED_ENTITY_TYPES",
    "COREFERENCE_STEP",
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_OLLAMA_URL",
    "DETERMINISTIC_STEP",
    "EXTERNAL_STEP",
    "EXTRACTOR_VERSION",
    "OLLAMA_STEP",
    "RELATION_RULES",
    "TABLE_STEP",
    "TEMPORAL_STEP",
    "VISUAL_STEP",
    "ColumnRule",
    "CoreferenceExtractor",
    "DeterministicExtractor",
    "Diagnostic",
    "EvidenceIndex",
    "ExternalExtractionRequest",
    "ExternalExtractionResponse",
    "ExternalExtractor",
    "ExternalProposalPort",
    "ExtractionContext",
    "ExtractionError",
    "ExtractionOutput",
    "ExtractionPipeline",
    "Extractor",
    "ExtractorInfo",
    "Lexicon",
    "LexiconEntry",
    "OllamaClient",
    "OllamaConfig",
    "OllamaError",
    "OllamaExtractor",
    "OllamaUnavailable",
    "RelationRule",
    "TableExtractor",
    "TemporalExtractor",
    "VisionPort",
    "VisualExtractor",
    "abstention_claim",
    "build_claim",
    "build_mention",
    "build_prompt",
    "emit",
    "extract_temporal_expressions",
    "make_id",
    "normalize",
    "normalize_payload",
    "normalize_predicate",
    "parse_strict_json",
    "tokenize",
]

# -*- coding: utf-8 -*-
"""Subsistema C de S9-Knowledge V3 — resolucion de identidad.

Convierte `EntityMention` (propuestas del extractor) en `EntityResolution`
(decisiones de identidad del contrato congelado `v3-internal-v1`) mediante una
cascada de senales configurable y determinista:

    workspace (filtro duro) -> exact -> history -> alias -> glossary
                            -> similarity -> context -> types -> decision

Garantias del subsistema:

- **No escribe en ninguna parte.** El catalogo de entidades existentes ENTRA por
  `EntityCatalog`; el resolutor solo emite documentos.
- **Aislamiento por workspace.** Un candidato de otra boveda nunca entra en la
  cascada, ni por catalogo, ni por glosario, ni por historial.
- **Determinismo total.** Dos pasadas sobre la misma entrada producen los mismos
  identificadores, los mismos scores y el mismo orden de candidatos.
- **Contratos congelados.** No se anade ni un campo: lo que el schema no tiene,
  aqui se reporta como bloqueo, no se inventa.

Documentacion: `docs/v3/04-resolution.md`.
"""
from __future__ import annotations

from .cascade import (
    CascadeContext,
    CascadeResult,
    Decision,
    ScoredCandidate,
    SignalHit,
    decide,
    filter_workspace,
    run_cascade,
    types_compatible,
)
from .catalog import (
    ENTITY_TYPES,
    CatalogEntity,
    EntityCatalog,
    InMemoryEntityCatalog,
    Neo4jEntityCatalog,
)
from .config import DEFAULT_CONFIG, GENERATOR_STEPS, MODIFIER_STEPS, ResolutionConfig
from .errors import ResolutionConfigError, ResolutionError, ResolutionInputError
from .glossary import (
    GlossaryHit,
    GlossarySource,
    GlossaryStoreSource,
    InMemoryGlossarySource,
    NullGlossarySource,
)
from .history import HistoryEntry, ResolutionHistory
from .normalization import normalize_surface
from .provisional import derive_entity_id, derive_resolution_id
from .resolver import (
    EntityResolver,
    ResolutionOutcome,
    ResolutionRequest,
    aggregate_confidence,
    aggregate_type,
)
from .similarity import (
    EmbeddingProvider,
    EmbeddingSimilarity,
    NullSimilarity,
    SurfaceSimilarity,
    TrigramJaccardSimilarity,
)

__all__ = [
    # cascada
    "CascadeContext",
    "CascadeResult",
    "Decision",
    "ScoredCandidate",
    "SignalHit",
    "decide",
    "filter_workspace",
    "run_cascade",
    "types_compatible",
    # catalogo
    "ENTITY_TYPES",
    "CatalogEntity",
    "EntityCatalog",
    "InMemoryEntityCatalog",
    "Neo4jEntityCatalog",
    # configuracion
    "DEFAULT_CONFIG",
    "GENERATOR_STEPS",
    "MODIFIER_STEPS",
    "ResolutionConfig",
    # errores
    "ResolutionError",
    "ResolutionInputError",
    "ResolutionConfigError",
    # glosario
    "GlossaryHit",
    "GlossarySource",
    "GlossaryStoreSource",
    "InMemoryGlossarySource",
    "NullGlossarySource",
    # historial
    "HistoryEntry",
    "ResolutionHistory",
    # identificadores
    "derive_entity_id",
    "derive_resolution_id",
    "normalize_surface",
    # resolutor
    "EntityResolver",
    "ResolutionOutcome",
    "ResolutionRequest",
    "aggregate_confidence",
    "aggregate_type",
    # similitud
    "EmbeddingProvider",
    "EmbeddingSimilarity",
    "NullSimilarity",
    "SurfaceSimilarity",
    "TrigramJaccardSimilarity",
]

# -*- coding: utf-8 -*-
"""Orquestador extremo a extremo de S9-Knowledge V3 (bloque CADENA, dosier §8).

    fuente -> normalizacion -> episodios/evidencias -> extractor -> resolucion
           -> motor local -> ledger -> validacion -> GraphMutationPlan
           -> writer controlado -> Neo4j

Este paquete COORDINA. No decide, no valida, no aprueba y no escribe: cada una
de esas cosas la hace el subsistema al que le corresponde. Si algo de aqui
pareciera una regla de negocio, seria un hueco en un subsistema, y esos huecos
estan anotados en `docs/v3/11-e2e.md` en vez de parcheados.

El writer va en DRY-RUN por defecto y no abre driver ninguno.

    from knowledge_v3.pipeline import KnowledgePipeline, PipelineConfig

Documentacion: `docs/v3/11-e2e.md`.
"""
from __future__ import annotations

from .bridge import assertion_from_edge, engine_snapshot, entities_from_catalog  # noqa: F401
from .bundle import peak_rss_mb, to_bundle  # noqa: F401
from .config import (  # noqa: F401
    EXTERNAL_ONLY,
    LOCAL_ONLY,
    LOCAL_PLUS_EXTERNAL,
    NO_OLLAMA,
    GoldInjection,
    PipelineConfig,
)
from .errors import PipelineError  # noqa: F401
from .grouping import mention_groups  # noqa: F401
from .pipeline import (  # noqa: F401
    KnowledgePipeline,
    PipelineResult,
    SourceCase,
    SourceRun,
)
from .sources import (  # noqa: F401
    cases_from_gold,
    catalog_entries,
    entity_catalog,
    from_episodes,
    from_raw,
    profile_of,
    reconstruct_bytes,
    workspace_lexicon,
)

__all__ = [
    "EXTERNAL_ONLY",
    "GoldInjection",
    "KnowledgePipeline",
    "LOCAL_ONLY",
    "LOCAL_PLUS_EXTERNAL",
    "NO_OLLAMA",
    "PipelineConfig",
    "PipelineError",
    "PipelineResult",
    "SourceCase",
    "SourceRun",
    "assertion_from_edge",
    "cases_from_gold",
    "catalog_entries",
    "engine_snapshot",
    "entities_from_catalog",
    "entity_catalog",
    "from_episodes",
    "from_raw",
    "mention_groups",
    "peak_rss_mb",
    "profile_of",
    "reconstruct_bytes",
    "to_bundle",
    "workspace_lexicon",
]

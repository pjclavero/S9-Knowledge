"""Orquestador de extractores → GlossaryStore.

GlossaryBuilder ejecuta los extractores habilitados, calcula prioridad
y hace upsert al store. Opcionalmente puede resetear el workspace antes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from glossary.glossary_extractors import (
    ManualSeedExtractor,
    MarkdownGlossaryExtractor,
    Neo4jGlossaryExtractor,
)
from glossary.glossary_models import GlossaryTerm
from glossary.glossary_ranker import calculate_priority
from glossary.glossary_store import GlossaryStore

log = logging.getLogger("glossary.builder")


@dataclass
class BuildResult:
    workspace: str
    seed_count: int = 0
    neo4j_count: int = 0
    markdown_count: int = 0
    total_upserted: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class GlossaryBuilder:
    """Orquesta extractores y persiste en el store."""

    def __init__(self, store: GlossaryStore):
        self.store = store

    def build(
        self,
        workspace: str,
        from_seed: bool = True,
        from_neo4j: bool = True,
        from_markdown: bool = True,
    ) -> BuildResult:
        result = BuildResult(workspace=workspace)
        terms: list[GlossaryTerm] = []

        if from_seed:
            try:
                ext = ManualSeedExtractor()
                seed_terms = ext.extract(workspace)
                result.seed_count = len(seed_terms)
                terms.extend(seed_terms)
                log.info("Seed: %d términos", result.seed_count)
            except Exception as exc:
                msg = f"ManualSeedExtractor falló: {exc}"
                log.error(msg)
                result.errors.append(msg)

        if from_neo4j:
            try:
                ext = Neo4jGlossaryExtractor()
                neo4j_terms = ext.extract(workspace)
                result.neo4j_count = len(neo4j_terms)
                terms.extend(neo4j_terms)
                log.info("Neo4j: %d términos", result.neo4j_count)
            except Exception as exc:
                msg = f"Neo4jGlossaryExtractor falló: {exc}"
                log.error(msg)
                result.errors.append(msg)

        if from_markdown:
            try:
                ext = MarkdownGlossaryExtractor()
                md_terms = ext.extract(workspace)
                result.markdown_count = len(md_terms)
                terms.extend(md_terms)
                log.info("Markdown: %d términos", result.markdown_count)
            except Exception as exc:
                msg = f"MarkdownGlossaryExtractor falló: {exc}"
                log.error(msg)
                result.errors.append(msg)

        # Calcular prioridad y hacer upsert
        for t in terms:
            t.priority = calculate_priority(t)
            try:
                self.store.upsert_term(t)
                result.total_upserted += 1
            except Exception as exc:
                msg = f"upsert falló para '{t.canonical_term}': {exc}"
                log.warning(msg)
                result.errors.append(msg)

        log.info(
            "Build completado: workspace=%s seed=%d neo4j=%d markdown=%d total=%d",
            workspace, result.seed_count, result.neo4j_count,
            result.markdown_count, result.total_upserted,
        )
        return result

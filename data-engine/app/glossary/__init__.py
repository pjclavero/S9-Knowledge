"""Paquete glossary: glosario de términos para mejorar transcripción L5A.

Módulos:
- glossary_models: dataclass GlossaryTerm
- glossary_store: SQLite store con tabla glossary_terms
- glossary_extractors: extractores de Neo4j, Markdown y semillas manuales
- glossary_builder: orquestador de extractores
- glossary_ranker: cálculo de prioridad
- glossary_matcher: búsqueda exacta/alias/error_form/fuzzy
- glossary_exporter: genera initial_prompt, hotwords, glossary.json
- glossary_cli: CLI build/stats/search/export
"""
from __future__ import annotations

__all__ = [
    "GlossaryTerm",
    "GlossaryStore",
    "GlossaryMatcher",
    "GlossaryExporter",
]

# -*- coding: utf-8 -*-
"""Paquete `relations.benchmark` (B2): runner y comparador del benchmark de relaciones.

Ejecuta el pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el corpus
B1 **REAL** y lo compara contra el ground truth. NO reimplementa ninguna etapa de
R8 y NO simula resultados finales. Ver `docs/41-relation-benchmark-plan.md`.
"""
from __future__ import annotations

from .matching import MatchResult, match_predictions, structural_flags
from .report import build_report, decide_verdict, evaluate_gates
from .runner import (
    DEFAULT_MODE,
    MODES,
    BenchmarkRun,
    Corpus,
    SourceRun,
    build_payload,
    derive_entities,
    extract_predictions,
    load_corpus,
    run_benchmark,
    run_source,
)

__all__ = [
    "MODES",
    "DEFAULT_MODE",
    "Corpus",
    "SourceRun",
    "BenchmarkRun",
    "MatchResult",
    "load_corpus",
    "derive_entities",
    "build_payload",
    "extract_predictions",
    "run_source",
    "run_benchmark",
    "match_predictions",
    "structural_flags",
    "evaluate_gates",
    "decide_verdict",
    "build_report",
]

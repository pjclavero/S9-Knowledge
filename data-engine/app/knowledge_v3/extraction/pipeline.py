# -*- coding: utf-8 -*-
"""Orquestacion de extractores. Ni resuelve identidad ni decide nada.

El orden importa y es explicito:

1. **estructurales y deterministas** (tabla, determinista): producen las
   menciones ancladas de las que todo lo demas cuelga;
2. **modelos** (Ollama, externo, visual): proponen sobre el mismo episodio, con
   sus propias trazas y sus topes de confianza;
3. **correferencia**: necesita las menciones de los pasos anteriores, asi que va
   la ultima y recibe lo acumulado.

El pipeline no deduplica propuestas entre extractores a proposito: que el
determinista y Ollama propongan lo mismo es informacion (acuerdo entre
proveedores) que el motor local querra usar. Fundirlas aqui la destruiria.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .base import ExtractionContext, ExtractionOutput, Extractor
from .coreference import CoreferenceExtractor
from .deterministic import DeterministicExtractor
from .table import TableExtractor
from .temporal import TemporalExtractor


@dataclass
class ExtractionPipeline:
    """Ejecuta extractores en orden y acumula sus propuestas."""

    extractors: Sequence[Extractor] = field(default_factory=tuple)

    def run(self, ctx: ExtractionContext) -> ExtractionOutput:
        accumulated = ExtractionOutput()
        for extractor in self.extractors:
            accumulated.extend(extractor.extract(ctx, prior=accumulated))
        return accumulated

    @classmethod
    def local_default(cls, *, with_temporal: bool = True) -> "ExtractionPipeline":
        """Pipeline 100% local: sin red, sin LLM, reproducible bit a bit.

        Es el que debe usar cualquier gate: si un resultado depende de que un
        servidor este vivo, no es un gate, es una casualidad.
        """
        extractors: list[Extractor] = [DeterministicExtractor(), TableExtractor()]
        if with_temporal:
            extractors.append(TemporalExtractor())
        extractors.append(CoreferenceExtractor())
        return cls(tuple(extractors))


__all__ = ["ExtractionPipeline"]

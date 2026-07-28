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
from typing import Any, Optional, Sequence

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

    @classmethod
    def production_local(cls, port: Any, *, with_temporal: bool = True) -> "ExtractionPipeline":
        """Produccion local: determinista + semantico (LLM local) + tabla + tiempo + correferencia.

        El determinista NO se sustituye: sigue siendo la via barata de alta
        precision, y el semantico se suma con su propio origen y sus propios
        ids. Las dos propuestas conviven como UNION; no hay reconciliador
        todavia y fingirlo aqui esconderia justo lo que hay que medir.
        """
        from .semantic import SemanticEpisodeExtractor

        extractors: list[Extractor] = [
            DeterministicExtractor(),
            TableExtractor(),
            SemanticEpisodeExtractor(port),
        ]
        if with_temporal:
            extractors.append(TemporalExtractor())
        extractors.append(CoreferenceExtractor())
        return cls(tuple(extractors))

    @classmethod
    def production_external(cls, port: Any, *, with_temporal: bool = True) -> "ExtractionPipeline":
        """Produccion con proveedor externo: la MISMA cadena, otro adaptador.

        Que sea literalmente el mismo codigo que `production_local` no es
        pereza: es el resultado. Si hiciese falta un pipeline distinto para el
        modelo externo, el puerto agnostico no lo seria.
        """
        return cls.production_local(port, with_temporal=with_temporal)


__all__ = ["ExtractionPipeline"]

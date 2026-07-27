# -*- coding: utf-8 -*-
"""Similitud de superficies: interfaz limpia + implementacion por defecto honesta.

La implementacion por defecto (`TrigramJaccardSimilarity`) NO es un modelo de
embeddings. Mide parecido ORTOGRAFICO: trigramas de caracteres y tokens
compartidos. Sirve exactamente para lo que se disenó — variantes de ASR/OCR de
un mismo nombre (`Daiki` / `Daiqui`, `Tamori` / `Tamory`) — y no sirve para
sinonimia semantica: `"el magistrado"` y `"Daiki"` puntuan 0. Esa es su
limitacion, esta medida en los tests, y por eso su peso maximo en la cascada
(`similarity_weight`) esta por debajo del umbral de enlace: la similitud de
superficie sola nunca enlaza, como mucho manda a revision.

`EmbeddingSimilarity` si es semantica, pero se apoya en un
`EmbeddingProvider` ABSTRACTO. Aqui no se implementa ningun proveedor: el
proveedor local real (Ollama u otro) lo aporta el subsistema de proveedores.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Sequence

from .normalization import char_ngrams, jaccard, normalize_surface, token_set


class SurfaceSimilarity(ABC):
    """Similitud entre dos superficies, en [0,1]."""

    #: Nombre estable para la traza. No es decorativo: la traza de una decision
    #: debe decir QUE modelo la produjo.
    name: str = "abstract"

    @abstractmethod
    def score(self, a: str, b: str) -> float:
        """Similitud en [0,1]. `score(a, b) == score(b, a)`."""

    def best_score(self, surface: str, forms: Sequence[str]) -> float:
        """Mejor similitud contra un conjunto de formas (nombre + alias)."""
        best = 0.0
        for form in forms:
            value = self.score(surface, form)
            if value > best:
                best = value
        return best


def levenshtein(a: str, b: str) -> int:
    """Distancia de edicion clasica. Iterativa, sin recursion ni dependencias."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,          # borrado
                    current[j - 1] + 1,       # insercion
                    previous[j - 1] + (ca != cb),  # sustitucion
                )
            )
        previous = current
    return previous[-1]


def edit_ratio(a: str, b: str) -> float:
    """Cercania de edicion en [0,1]: `1 - distancia / longitud_mayor`."""
    if not a or not b:
        return 0.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


class TrigramJaccardSimilarity(SurfaceSimilarity):
    """Cercania de edicion + Jaccard de trigramas, con respaldo de tokens.

    Sin dependencias: ni numpy, ni modelos, ni red. Determinista y simetrica.

    Por que las tres senales y no una:

    - la **distancia de edicion** es la unica que ve una errata de una letra
      (`Tamori` / `Tamory`), que es el caso que motiva este paso;
    - los **trigramas** penalizan las transposiciones que la edicion trata con
      demasiada indulgencia y dan estabilidad en nombres largos;
    - el **Jaccard de tokens** rescata los reordenamientos (`Familia Tamori` /
      `Tamori, familia`), donde caracter a caracter no se parecen nada.

    Se toma el MAXIMO entre la mezcla caracter-a-caracter y la de tokens porque
    son dos formas distintas de ser la misma cosa, no dos pruebas que deban
    superarse a la vez.

    Limite honesto y medido en los tests: esto NO es semantica. `"el magistrado"`
    y `"Daiki"` puntuan 0, y `"Daiqui"` / `"Daiki"` se queda a medio camino. Las
    variantes de ASR muy deformadas son trabajo del GLOSARIO (`error_forms`), no
    de este paso; por eso su techo esta por debajo del umbral de enlace.
    """

    name = "trigram-edit-1.0"

    def __init__(
        self, *, ngram: int = 3, edit_weight: float = 0.75
    ) -> None:
        if not 0.0 <= edit_weight <= 1.0:
            raise ValueError("edit_weight fuera de [0,1]")
        self._n = ngram
        self._edit_weight = edit_weight

    def score(self, a: str, b: str) -> float:
        na, nb = normalize_surface(a), normalize_surface(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        char = (
            self._edit_weight * edit_ratio(na, nb)
            + (1.0 - self._edit_weight) * jaccard(char_ngrams(na, self._n), char_ngrams(nb, self._n))
        )
        tok = jaccard(token_set(na), token_set(nb))
        value = max(char, tok)
        # Redondeo explicito: el desempate final compara scores y no puede
        # depender del ultimo bit de un float.
        return round(min(1.0, max(0.0, value)), 6)


class NullSimilarity(SurfaceSimilarity):
    """Similitud siempre 0. Para la ablacion "sin embeddings"."""

    name = "null-1.0"

    def score(self, a: str, b: str) -> float:
        return 0.0


class EmbeddingProvider(ABC):
    """ENGANCHE: proveedor de vectores para superficies.

    Lo implementa el subsistema de proveedores (local/Ollama), no este. La unica
    exigencia desde aqui: `embed` es determinista para el mismo texto y modelo,
    porque si no lo es, dos pasadas sobre el mismo corpus dan grafos distintos.
    """

    name: str = "abstract-embedding"

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Vectores de los textos, en el mismo orden."""


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Coseno en [0,1] (los negativos se recortan a 0: no hay "menos parecido")."""
    if len(a) != len(b):
        raise ValueError("vectores de dimension distinta")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return round(max(0.0, min(1.0, dot / (na * nb))), 6)


class EmbeddingSimilarity(SurfaceSimilarity):
    """Similitud por embeddings reales sobre un `EmbeddingProvider`.

    Esta clase SI esta implementada (es solo coseno con cache); lo que no se
    entrega es ningun proveedor concreto. Enchufar uno es cambiar una linea en
    la construccion del resolutor, sin tocar la cascada.
    """

    def __init__(self, provider: EmbeddingProvider) -> None:
        self._provider = provider
        self._cache: dict[str, tuple[float, ...]] = {}
        self.name = f"embedding:{getattr(provider, 'name', 'unknown')}"

    def _vector(self, text: str) -> tuple[float, ...]:
        key = normalize_surface(text)
        if key not in self._cache:
            vectors = self._provider.embed([key])
            if not vectors:
                raise ValueError("el proveedor de embeddings no devolvio vector")
            self._cache[key] = tuple(float(x) for x in vectors[0])
        return self._cache[key]

    def score(self, a: str, b: str) -> float:
        na, nb = normalize_surface(a), normalize_surface(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        return cosine(self._vector(na), self._vector(nb))


__all__ = [
    "SurfaceSimilarity",
    "TrigramJaccardSimilarity",
    "NullSimilarity",
    "EmbeddingProvider",
    "EmbeddingSimilarity",
    "cosine",
    "levenshtein",
    "edit_ratio",
]

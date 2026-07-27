# -*- coding: utf-8 -*-
"""Normalizacion de superficies para la resolucion de identidad.

Una sola definicion de "misma superficie" para toda la cascada: si el paso de
match exacto y el de alias normalizaran distinto, dos senales que dicen lo mismo
darian resultados distintos y la cascada dejaria de ser explicable.

La normalizacion es PURA y determinista: misma entrada, misma salida, sin
locale, sin estado y sin dependencias externas.
"""
from __future__ import annotations

import re
import unicodedata

#: Caracteres que separan palabras. Se sustituyen por espacio antes de dividir.
_SEPARATORS = re.compile(r"[\s_\-‐-―/\\|,;:.!?¡¿\"'’`()\[\]{}<>*«»]+")
#: Cualquier resto no alfanumerico se elimina (simbolos sueltos, emoji, etc.).
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def strip_accents(text: str) -> str:
    """Quita diacriticos manteniendo el resto de caracteres."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_surface(text: str) -> str:
    """Forma normalizada canonica de una superficie.

    Minusculas, sin diacriticos, sin puntuacion, con separadores colapsados a un
    unico espacio. `"Daiki, el Magistrado"` y `"daiki el magistrado"` colapsan a
    la misma cadena; `"Daiqui"` NO (esa es tarea de las senales difusas, no de la
    normalizacion: normalizar agresivamente esconderia el error de ASR en vez de
    medirlo).
    """
    if not text:
        return ""
    lowered = strip_accents(str(text)).lower()
    spaced = _SEPARATORS.sub(" ", lowered)
    cleaned = _NON_ALNUM.sub(" ", spaced)
    return " ".join(cleaned.split())


def tokens(text: str) -> tuple[str, ...]:
    """Tokens de la forma normalizada, en orden de aparicion."""
    norm = normalize_surface(text)
    return tuple(norm.split()) if norm else ()


def token_set(text: str) -> frozenset[str]:
    """Conjunto de tokens de la forma normalizada."""
    return frozenset(tokens(text))


def char_ngrams(text: str, n: int = 3) -> frozenset[str]:
    """N-gramas de caracteres con relleno de bordes.

    El relleno (`n-1` espacios a cada lado) hace que el principio y el final de
    la cadena cuenten como senal: sin el, `"ilya"` e `"ylia"` compartirian mas
    de lo que deberian.
    """
    if n < 1:
        raise ValueError("n debe ser >= 1")
    norm = normalize_surface(text)
    if not norm:
        return frozenset()
    padded = (" " * (n - 1)) + norm + (" " * (n - 1))
    return frozenset(padded[i : i + n] for i in range(len(padded) - n + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Indice de Jaccard. Dos conjuntos vacios NO son identicos: valen 0."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


__all__ = [
    "strip_accents",
    "normalize_surface",
    "tokens",
    "token_set",
    "char_ngrams",
    "jaccard",
]

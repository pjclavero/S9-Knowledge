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


#: Determinantes iniciales del espanol que un extractor arrastra dentro de la
#: superficie de la mencion (`"la Marea Negra"`, `"del Consejo de Umbra"`) y que
#: NO forman parte del nombre de la entidad en el grafo (`"Marea Negra"`,
#: `"Consejo de Umbra"`).
#:
#: Lista CERRADA y deliberadamente corta: articulos determinados, sus dos
#: contracciones y los indeterminados. No entra ningun posesivo, ningun
#: demostrativo y ninguna preposicion suelta — `"de Ambar"` NO es `"Ambar"`, y
#: recortar por ahi si seria hacer el resolutor mas permisivo.
LEADING_DETERMINERS: frozenset[str] = frozenset(
    {"el", "la", "los", "las", "lo", "del", "al", "un", "una", "unos", "unas"}
)


def strip_leading_determiners(normalized: str) -> str:
    """Quita los determinantes INICIALES de una superficie ya normalizada.

    Solo por delante y solo mientras quede algo detras: `"la marea negra"` ->
    `"marea negra"`, pero `"la"` -> `"la"` (quitarlo dejaria la cadena vacia) y
    `"marea la negra"` -> `"marea la negra"` (el determinante no encabeza).

    NO se aplica dentro de `normalize_surface`: la forma literal debe seguir
    existiendo. Esta es una VARIANTE que se anade, no una sustitucion. Ver
    `surface_variants`.
    """
    parts = normalized.split()
    i = 0
    while i < len(parts) - 1 and parts[i] in LEADING_DETERMINERS:
        i += 1
    return " ".join(parts[i:])


def surface_variants(text: str) -> tuple[str, ...]:
    """Formas normalizadas de una superficie, la literal SIEMPRE primero.

    Existe porque la superficie que produce el extractor y el nombre que guarda
    el grafo no tienen por que coincidir palabra por palabra, y los pasos
    `exact` y `alias` de la cascada comparan por IGUALDAD de cadena. Sin esta
    variante, `"la Marea Negra"` no puede alcanzar a `"Marea Negra"` por ninguna
    senal fuerte: solo le queda `similarity`, cuyo techo (`similarity_weight`,
    0.88) esta por DEBAJO del umbral de enlace (`link_min_score`, 0.90) a
    proposito. Es decir, la resolucion correcta era ESTRUCTURALMENTE
    inalcanzable, no simplemente improbable.

    Anadir una variante NO relaja ninguna decision: no toca umbrales, no toca
    el margen de ambiguedad y no elige candidato. Solo hace que el dato llegue a
    las guardias que ya existian. Si la variante alcanza a DOS entidades, la
    regla de ambiguedad las ve a las dos y la decision sigue siendo `REVIEW`.

    Orden estable y sin duplicados: la literal manda, la variante acompana.
    """
    base = normalize_surface(text)
    if not base:
        return ()
    stripped = strip_leading_determiners(base)
    if stripped and stripped != base:
        return (base, stripped)
    return (base,)


__all__ = [
    "strip_accents",
    "normalize_surface",
    "tokens",
    "token_set",
    "char_ngrams",
    "jaccard",
    "LEADING_DETERMINERS",
    "strip_leading_determiners",
    "surface_variants",
]

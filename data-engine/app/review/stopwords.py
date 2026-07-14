"""Stopwords y filtros de tokens débiles para el extractor S9 Knowledge.

Contrato compartido (agentes A y B):
    STOPWORDS_ES: set[str]         -- normalizado en minúsculas sin tildes
    is_stopword(term) -> bool      -- normaliza y comprueba
    is_weak_single_token(term) -> bool  -- single token además común o corto (<3 chars)

NO modificar la interfaz pública — auto_decider también importa este módulo.
"""
from __future__ import annotations
import unicodedata
import re


def _normalize(text: str) -> str:
    """Minúsculas + elimina tildes/diacríticos para comparación."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


# ── Corpus de stopwords ────────────────────────────────────────────────────────
# Almacenadas en forma normalizada (minúsculas, sin tildes).
# Los callers no tienen que preocuparse: is_stopword() normaliza la entrada.

STOPWORDS_ES: set[str] = {
    # Pronombres / determinantes
    "yo", "tu", "el", "ella", "ellos", "ellas", "nosotros", "vosotros",
    "me", "te", "se", "nos", "os", "le", "les", "lo", "la", "los", "las",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "aquel", "aquella", "aquellos", "aquellas",
    "esto", "eso", "aquello",
    "alguien", "nadie", "algo", "nada", "todo", "toda", "todos", "todas",
    "uno", "una", "unos", "unas",

    # Artículos
    "un", "una", "el", "la", "los", "las", "al", "del",

    # Preposiciones
    "a", "ante", "bajo", "con", "contra", "de", "desde", "durante",
    "en", "entre", "hacia", "hasta", "mediante", "para", "por", "segun",
    "sin", "sobre", "tras", "versus",

    # Conjunciones / nexos
    "y", "e", "o", "u", "pero", "sino", "aunque", "porque", "pues",
    "cuando", "donde", "quien", "quienes", "que", "como", "si", "ni",
    "tanto", "tan", "asi", "tambien", "tampoco", "ademas", "entonces",
    "por tanto", "por eso", "sin embargo", "no obstante",

    # Adverbios comunes
    "no", "si", "ya", "muy", "mas", "menos", "bien", "mal", "aqui",
    "ahi", "alli", "ahora", "antes", "despues", "siempre", "nunca",
    "jamas", "casi", "solo", "sola", "solos", "solas", "algo", "nada",

    # Verbos auxiliares / funcionales (formas conjugadas comunes)
    "es", "era", "fue", "son", "eran", "fueron", "ser", "estar",
    "esta", "estaba", "hay", "haber", "tener", "tiene", "tenia",
    "hacer", "hago", "hace", "haces", "hacemos", "hacen",
    "decir", "dice", "dices", "digo", "dijo", "dijeron",
    "ir", "voy", "vas", "va", "vamos", "van", "iba", "ivan",
    "poder", "puedo", "puede", "pueden", "podia", "podian",
    "querer", "quiero", "quiere", "quieren",
    "saber", "se", "sabe", "sabemos",
    "ver", "veo", "ves", "vemos", "ven",
    "dar", "doy", "da", "das", "dan",
    "jugar", "juego", "juega", "jugamos", "juegan",
    "tirar", "tira", "tiro", "tiramos", "tiran",
    "llevar", "lleva", "llevo", "llevas", "llevamos", "llevan",
    "soy", "eres", "somos", "sois",

    # Conversacionales / muletillas españolas
    "vale", "venga", "bueno", "vamos", "mira", "claro", "oye", "oyes",
    "hombre", "tio", "tia", "tipo", "osea", "o sea", "digamos",
    "momento", "espera", "ahora", "entonces", "pues", "eh", "ah",
    "um", "uh", "mm", "mmm", "hmm", "buenas", "hola", "adios",
    "perdon", "gracias", "por favor",

    # Palabras que aparecen capitalizadas por inicio de frase pero no son entidades
    "todo", "como",
    "cosa", "cosas", "dado", "dados", "tirada", "tiradas",
    "vez", "veces", "forma", "formas", "parte", "partes",
    "tipo", "tipos", "caso", "casos", "punto", "puntos",
    "momento", "momentos", "vez", "veces",
    "aqui", "aqui", "ahi", "alli",

    # Partículas temporales/modales frecuentes
    "igual", "seguro", "claro", "exacto", "correcto", "perfecto",
    "basicamente", "literalmente", "obviamente", "evidentemente",
    "realmente", "bastante", "demasiado", "suficiente",
}


def is_stopword(term: str) -> bool:
    """Normaliza el término (minúsculas, sin tildes) y comprueba si es stopword."""
    if not term or not term.strip():
        return False
    norm = _normalize(term.strip())
    return norm in STOPWORDS_ES


def is_weak_single_token(term: str) -> bool:
    """True si el término es un único token Y (es stopword O tiene menos de 3 chars).

    Un single-token que pasa este filtro es candidato débil: no debe salir
    con confidence alta como entidad nombrada.
    """
    tokens = term.strip().split()
    if len(tokens) != 1:
        return False  # multi-token: no aplica este filtro
    token = tokens[0]
    if len(token) < 3:
        return True
    return is_stopword(token)
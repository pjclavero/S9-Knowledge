"""Calcula la prioridad (priority) de cada GlossaryTerm.

La fórmula combina:
- confidence: 0..1, peso 0.4
- frequency normalizada (log): peso 0.3
- term_type boost: nombres_propios/entidad > palabra_clave > general: peso 0.3

El resultado es un float 0..1 que se almacena en glossary_terms.priority.
"""
from __future__ import annotations

import math
import logging
from glossary.glossary_models import GlossaryTerm

log = logging.getLogger("glossary.ranker")

# Boost por tipo de término (mayor = más prioritario en el prompt)
_TYPE_BOOST: dict[str, float] = {
    "persona": 1.0,
    "personaje": 1.0,
    "lugar": 0.9,
    "organizacion": 0.9,
    "clan": 0.9,
    "arma": 0.8,
    "habilidad": 0.8,
    "concepto": 0.7,
    "objeto": 0.7,
    "criatura": 0.8,
    "deidad": 0.9,
    "titulo": 0.85,
    "termino_rpg": 0.75,
    "general": 0.5,
}

_DEFAULT_TYPE_BOOST = 0.6


def _type_boost(term_type: str | None) -> float:
    if not term_type:
        return _DEFAULT_TYPE_BOOST
    return _TYPE_BOOST.get(term_type.lower(), _DEFAULT_TYPE_BOOST)


def _log_frequency(freq: int) -> float:
    """Normaliza la frecuencia con log; resultado 0..1 para freq 1..1000+."""
    if freq <= 0:
        return 0.0
    return min(math.log1p(freq) / math.log1p(1000), 1.0)


def calculate_priority(term: GlossaryTerm) -> float:
    """Calcula priority para un GlossaryTerm. Devuelve float 0..1."""
    conf_score = max(0.0, min(1.0, term.confidence)) * 0.4
    freq_score = _log_frequency(term.frequency) * 0.3
    type_score = _type_boost(term.term_type) * 0.3
    priority = conf_score + freq_score + type_score
    return round(min(priority, 1.0), 4)


def rank_terms(terms: list[GlossaryTerm]) -> list[GlossaryTerm]:
    """Calcula priority en todos los términos y los devuelve ordenados desc."""
    for t in terms:
        t.priority = calculate_priority(t)
    return sorted(terms, key=lambda t: t.priority, reverse=True)

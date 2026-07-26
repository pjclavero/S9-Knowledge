# -*- coding: utf-8 -*-
"""Selector de predicados v2 ESTRUCTURADO por reglas + ontologia (motor v2, Bloque 2).

Este modulo implementa el selector `v2`, que consume la FUENTE UNICA
`relations/ontology.py` (dominio/rango/familia/simetria/expresiones activas-pasivas/
confundibles) y las senales ya calculadas por `relations/signals.py`. Reutiliza,
NO duplica. NO es un modelo aprendido (el corpus de 54 relaciones es
insuficiente para entrenar nada honesto): es un motor DETERMINISTA por reglas.

Pipeline del selector (spec B2)
-------------------------------
  1. GENERACION de candidatos: predicados canonicos sugeridos por (a) las
     expresiones activas/pasivas de la ontologia que aparecen en la ventana de la
     frase del par, y (b) los predicados cuyo dominio/rango admite los tipos de las
     entidades. NO se limita a los 5 predicados del selector v1.
  2. CLASIFICACION por FAMILIA (ontology.family): se conserva para desempate y para
     detectar ambiguedad entre familias distintas.
  3. FILTRO por dominio/rango: se DESCARTA todo candidato cuyo (domain, range) no
     admita el par de tipos (en cualquiera de las dos orientaciones, porque el par
     textual puede venir invertido y los simetricos no estan orientados). La
     compatibilidad de tipos es un FILTRO, no el selector.
  4. PUNTUACION por senales: evidencia lexica (expresiones de la ontologia) con peso
     alto, cues booleanos de signals.py (membership/possession) con peso medio, y un
     PRIOR por forma de tipos con peso bajo (rompe empates hacia la lectura dominante
     cuando no hay lexico).
  5. COMPARACION de candidatos: si el ganador no tiene evidencia lexica (se sostiene
     solo en el prior/cue) o el margen con el segundo es insuficiente -> ABSTENCION:
     se marca el candidato para revision de predicado (`REVIEW_PREDICATE`), en vez de
     FORZAR una decision con confianza plena.
  6. FALLBACK seguro a `RELATED_TO` SOLO cuando ningun candidato tiene soporte
     (ni lexico, ni cue, ni prior, ni tipo compatible).

DETERMINISTA y puro: sin red, sin disco, sin estado global mutable, sin azar. Mismo
(tipos, ventana, senales) -> misma seleccion, mismo orden, mismos scores.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from relations import ontology, signals
from relations.contracts import normalize_predicate

SELECTOR_VERSION = "relation-predicate-selector-2.0.0"

# Predicado generico de fallback (mismo literal que usa el pipeline v1).
GENERIC_PREDICATE = "RELATED_TO"

# Flag de validacion que marca una seleccion en ABSTENCION (revision de predicado).
REVIEW_PREDICATE_FLAG = "review_predicate"

# Pesos de puntuacion (enteros: puntuacion reproducible byte a byte).
LEX_WEIGHT = 4     # cada expresion de la ontologia hallada en la ventana
CUE_WEIGHT = 2     # cue booleano de signals.py compatible con la familia
PRIOR_WEIGHT = 1   # prior por forma de tipos (lectura dominante)

# Margen minimo de puntuacion del ganador sobre el segundo de OTRA familia para
# COMPROMETERSE sin abstencion cuando el ganador SI tiene evidencia lexica.
COMMIT_MARGIN = LEX_WEIGHT  # una expresion lexica de diferencia

# Grupos semanticos de tipos (reutilizados de la fuente unica, NO redefinidos).
_PERSON = ontology._PERSON
_ORG = ontology._ORG
_PLACE = ontology._PLACE
_THING = ontology._THING
_HAPPENING = ontology._HAPPENING
_CONCEPT = frozenset({"Concept"})

# Familias cuyo cue booleano de signals.py aporta soporte (medio) al predicado.
# El cue de "location" de signals.py se OMITE a proposito: su lexico incluye el
# bare " en ", extremadamente frecuente, que es justo la causa de que el selector
# v1 sobre-emita LOCATED_IN. La ubicacion se decide por dominio/rango + prior.
_CUE_FAMILY_SUPPORT = {
    "membership": "membership",   # signal "membership" -> familia membership
    "possession": "possession",   # signal "possession" -> familia possession
}
_FAMILY_BY_CUE_PREDICATE = {
    "membership": "MEMBER_OF",
    "possession": "OWNS",
}


@dataclass(frozen=True)
class Candidate:
    """Un predicado candidato puntuado (traza auditable, NO va al nodo)."""

    predicate: str
    family: str
    score: int
    lexical_hits: int
    matched_expressions: tuple


@dataclass(frozen=True)
class Selection:
    """Resultado del selector v2 para un par.

    * `predicate`   : predicado CANONICO elegido (string; contrato intacto).
    * `family`      : familia del predicado elegido (o None en fallback).
    * `abstained`   : True si la eleccion es en ABSTENCION (margen insuficiente o
                      sin evidencia lexica): se marca para revision de predicado.
    * `fallback`    : True si se cayo al generico `RELATED_TO` por falta de soporte.
    * `candidates`  : lista de `Candidate` ordenada (traza; vive en validation_flags
                      o en un campo de traza, NUNCA en el nodo).
    * `rationale`   : etiqueta breve de la regla que decidio.
    """

    predicate: str
    family: Optional[str]
    abstained: bool
    fallback: bool
    candidates: tuple
    rationale: str


def _norm(text: str) -> str:
    """Minusculas + sin diacriticos (comparacion lexica robusta y determinista)."""
    if not text:
        return ""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def sentence_window(seg_text: str, subject_start: int, subject_end: int,
                    object_start: int, object_end: int) -> str:
    """Ventana de la(s) frase(s) que contiene(n) ambas menciones.

    Reutiliza `signals._sentence_bounds` (misma definicion de frontera de frase que
    el resto del subsistema) para no duplicar el criterio.
    """
    s_ini, s_fin = signals._sentence_bounds(seg_text, subject_start, subject_end)
    o_ini, o_fin = signals._sentence_bounds(seg_text, object_start, object_end)
    lo, hi = min(s_ini, o_ini), max(s_fin, o_fin)
    return seg_text[lo:hi]


def _type_admits(pred_ont, s_type: Optional[str], o_type: Optional[str]) -> bool:
    """True si (domain, range) del predicado admite el par en ALGUNA orientacion.

    El par textual puede venir invertido (sujeto textual != sujeto semantico) y los
    simetricos no estan orientados: se acepta cualquiera de las dos orientaciones,
    igual que el criterio de existencia del arnes.
    """
    if s_type is None or o_type is None:
        return False
    return ((s_type in pred_ont.domain and o_type in pred_ont.range)
            or (o_type in pred_ont.domain and s_type in pred_ont.range))


def _type_prior(s_type: Optional[str], o_type: Optional[str]) -> Optional[str]:
    """Prior por FORMA de tipos: la lectura dominante cuando no hay lexico.

    Order-independiente (se razona sobre el conjunto de tipos), porque el criterio
    de existencia del arnes es sobre el par NO ordenado. Devuelve el canonico del
    prior o None si la forma es ambigua (kinship persona-persona, alianza/enemistad
    faccion-faccion): en ese caso el prior NO desempata y se exige lexico.
    """
    if s_type is None or o_type is None:
        return None
    types = {s_type, o_type}
    has_thing = bool(types & _THING)
    has_place = bool(types & _PLACE)
    has_happening = bool(types & _HAPPENING)
    has_org = bool(types & _ORG)
    has_person = bool(types & _PERSON)
    has_concept = bool(types & _CONCEPT)

    # Posesion: un agente (o concepto) y una cosa.
    if has_thing and (types & (_PERSON | _ORG | _CONCEPT)):
        return "OWNS"
    # Suceso: participacion (agente), causalidad (suceso/concepto) o, si ademas hay
    # un lugar, ubicacion del suceso. El lugar se comprueba ANTES que el resto para
    # que un par Suceso+Lugar (un evento que se celebra en un sitio) no quede sin
    # prior por preempcion de la rama de sucesos.
    if has_happening:
        other = types - _HAPPENING
        if other & _PLACE:
            return "LOCATED_IN"
        if other & (_PERSON | _ORG):
            return "PARTICIPATED_IN"
        if not other or (other & (_HAPPENING | _CONCEPT)):
            return "CAUSED"
        return None
    # Ubicacion: algo y un lugar (LIVES_IN se decide por lexico; el prior es el
    # generico LOCATED_IN).
    if has_place:
        return "LOCATED_IN"
    # Pertenencia: persona y organizacion.
    if has_org and has_person:
        return "MEMBER_OF"
    # Faccion-faccion / persona-persona / concepto-concepto: ambiguo, sin prior.
    return None


def _score_candidates(window_norm: str, s_type: Optional[str], o_type: Optional[str],
                      sigmap: dict) -> list:
    """Genera, filtra por tipo y PUNTUA los candidatos. Devuelve lista ordenada."""
    prior = _type_prior(s_type, o_type)
    # Cues booleanos de signals.py -> familia soportada (peso medio).
    cue_predicates: set = set()
    for signal_name, _family in _CUE_FAMILY_SUPPORT.items():
        if sigmap.get(signal_name):
            cue_predicates.add(_FAMILY_BY_CUE_PREDICATE[signal_name])

    scored: list[Candidate] = []
    for canonical, ont in ontology.ONTOLOGY.items():
        # FILTRO por dominio/rango (paso 3): descarta tipos incompatibles.
        if not _type_admits(ont, s_type, o_type):
            continue
        # PUNTUACION (paso 4): lexico (alto) + cue (medio) + prior (bajo).
        matched: list[str] = []
        for expr in tuple(ont.active_expressions) + tuple(ont.passive_expressions):
            if expr and _norm(expr) in window_norm:
                matched.append(expr)
        lexical_hits = len(matched)
        score = LEX_WEIGHT * lexical_hits
        if canonical in cue_predicates:
            score += CUE_WEIGHT
        if prior is not None and canonical == prior:
            score += PRIOR_WEIGHT
        if score <= 0:
            continue
        scored.append(Candidate(
            predicate=canonical,
            family=ont.family,
            score=score,
            lexical_hits=lexical_hits,
            matched_expressions=tuple(sorted(matched)),
        ))
    # Orden determinista: score desc, luego mas evidencia lexica, luego canonico asc.
    scored.sort(key=lambda c: (-c.score, -c.lexical_hits, c.predicate))
    return scored


def select(s_type: Optional[str], o_type: Optional[str], window: str,
           sigmap: dict) -> Selection:
    """Selecciona el predicado v2 para un par (funcion pura, determinista).

    `window` es el texto de la(s) frase(s) del par (ver `sentence_window`).
    """
    window_norm = _norm(window)
    scored = _score_candidates(window_norm, s_type, o_type, sigmap)

    # Paso 6: sin ningun candidato con soporte -> fallback seguro a RELATED_TO.
    if not scored:
        return Selection(
            predicate=GENERIC_PREDICATE, family=None, abstained=False,
            fallback=True, candidates=(), rationale="no_support_fallback")

    winner = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None

    # Paso 5: decision COMPROMETIDA vs ABSTENCION.
    #   * Sin evidencia lexica (el ganador se sostiene solo en prior/cue): la lectura
    #     es plausible pero incierta -> ABSTENCION (marca para revision), sin forzar.
    #   * Con evidencia lexica pero margen insuficiente sobre un candidato de OTRA
    #     familia igualmente lexico -> ABSTENCION (predicados confundibles).
    #   * Con evidencia lexica y margen suficiente -> COMPROMETIDO.
    if winner.lexical_hits == 0:
        return Selection(
            predicate=winner.predicate, family=winner.family, abstained=True,
            fallback=False, candidates=tuple(scored),
            rationale="prior_only_abstain")

    if runner_up is not None and runner_up.lexical_hits > 0 \
            and runner_up.family != winner.family \
            and (winner.score - runner_up.score) < COMMIT_MARGIN:
        return Selection(
            predicate=winner.predicate, family=winner.family, abstained=True,
            fallback=False, candidates=tuple(scored),
            rationale="low_margin_confusable_abstain")

    return Selection(
        predicate=winner.predicate, family=winner.family, abstained=False,
        fallback=False, candidates=tuple(scored), rationale="lexical_commit")


def choose_predicate_v2(sigmap: dict, pair, seg_text: str) -> Selection:
    """Adaptador para el pipeline: extrae la ventana y delega en `select`.

    `pair` es un `relations.pairs.CandidatePair` (tiene los offsets y tipos). NO
    muta nada; devuelve la `Selection` con predicado canonico + traza.
    """
    window = sentence_window(
        seg_text, pair.subject_start, pair.subject_end,
        pair.object_start, pair.object_end)
    return select(pair.subject_type, pair.object_type, window, sigmap)


__all__ = [
    "SELECTOR_VERSION",
    "GENERIC_PREDICATE",
    "REVIEW_PREDICATE_FLAG",
    "LEX_WEIGHT",
    "CUE_WEIGHT",
    "PRIOR_WEIGHT",
    "COMMIT_MARGIN",
    "Candidate",
    "Selection",
    "sentence_window",
    "select",
    "choose_predicate_v2",
]

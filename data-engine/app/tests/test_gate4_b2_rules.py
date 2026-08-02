# -*- coding: utf-8 -*-
"""Puerta 4, bloque B2: tests de las reglas deterministas nuevas.

Verifica que cada frase de relacion añadida en B2 dispara el predicado
correcto y que la negacion se clasifica de forma coherente. Ninguno de
estos tests toca el corpus de generalizacion ni el pipeline E2E completo:
operan directamente sobre cues.analyze_raw_text y sobre la presencia de las
frases en RELATION_RULES.
"""
from __future__ import annotations

import pytest

from knowledge_v3.extraction.cues import analyze_raw_text, CESSATION_PHRASES
from knowledge_v3.extraction.deterministic import RELATION_RULES


# ---------------------------------------------------------------------------
# 1. Presencia de frases nuevas en RELATION_RULES
# ---------------------------------------------------------------------------

def _all_phrases() -> set[str]:
    phrases: set[str] = set()
    for rule in RELATION_RULES:
        phrases.update(rule.phrases)
    return phrases


@pytest.mark.parametrize("phrase,predicate", [
    # B2: control (DOUBLE_NEGATION NEG-DOUBLE-02)
    ("bajo el control del", "OWNS"),
    # B2: cesacion de pertenencia
    ("abandono", "MEMBER_OF"),
    ("haya abandonado", "MEMBER_OF"),
    # B2: pertenencia con contraccion
    ("pertenece al", "MEMBER_OF"),
    ("pertenecia al", "MEMBER_OF"),
    ("pertenecio al", "MEMBER_OF"),
    # B2: LOCATED_IN subjuntivo (SCOPE-04 via ASR)
    ("este en", "LOCATED_IN"),
    # B2: LEADS en voz pasiva negada
    ("ha dejado de estar dirigida por", "LEADS"),
    ("ha dejado de estar dirigido por", "LEADS"),
])
def test_frase_presente_en_relation_rules_con_predicado_correcto(phrase, predicate):
    """La frase existe en RELATION_RULES bajo el predicado esperado."""
    found = [r for r in RELATION_RULES if phrase in r.phrases and r.predicate == predicate]
    assert found, (
        f"La frase {phrase!r} no aparece bajo predicado {predicate!r} en RELATION_RULES. "
        f"Predicados actuales con esta frase: "
        f"{[r.predicate for r in RELATION_RULES if phrase in r.phrases]}"
    )


# ---------------------------------------------------------------------------
# 2. Confianza de "bajo el control del" <= 0.54
#    (para forzar review_required=True via confidence < 0.6)
# ---------------------------------------------------------------------------

def test_bajo_el_control_del_confidence_fuerza_review():
    """confidence < 0.54 -> clamp = confidence/0.9 < 0.6 -> review_required=True siempre."""
    for rule in RELATION_RULES:
        if "bajo el control del" in rule.phrases:
            assert rule.confidence < 0.54, (
                f"confidence de 'bajo el control del' debe ser < 0.54 para que "
                f"review_required sea True siempre. Actual: {rule.confidence}"
            )
            break
    else:
        pytest.fail("Frase 'bajo el control del' no encontrada en RELATION_RULES")


# ---------------------------------------------------------------------------
# 3. Clasificacion de negacion para frases de B2 (via analyze_raw_text)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,anchor,expected_negated,desc", [
    # CESSATION: "abandono" -> cesacion, negated=True
    (
        "Goran Ute abandono la Escuela de la Corriente el ciclo pasado.",
        "la Escuela de la Corriente",
        True,
        "abandono directo = cesacion = negated True",
    ),
    # NEGATED_CESSATION: "no dejo de pertenecer a" -> negated=False
    (
        "La Torre Anemos no dejo de pertenecer a la Liga del Viento.",
        "la Liga del Viento",
        False,
        "negacion de cesacion = relacion activa = negated False",
    ),
    # SIMPLE: "no pertenece a" -> negated=True
    (
        "Harun Vell no pertenece a la Orden de la Obsidiana.",
        "la Orden de la Obsidiana",
        True,
        "no + pertenece a = negacion simple = negated True",
    ),
    # "no + verbo_opinion + que + ... este en X": analyze_raw_text ve 'no' en ventana SIMPLE.
    # El clasificador devuelve negated=True (SIMPLE) porque opera a nivel de oracion y el
    # 'no' esta dentro de la ventana NEGATION_WINDOW=3 tokens antes del focus.
    # Esto documenta la limitacion conocida: el clasificador no resuelve el alcance
    # de actitudes epistemicas embebidas; ese caso (zafiro NEG-SCOPE-04) no es cubrible
    # por reglas deterministas sin FP de precision.
    (
        "Andres Lupo no admite que la Sonda Madre este en el Domo Tres.",
        "el Domo Tres",
        True,
        "no + opinion + que: clasificador ve no en ventana -> negated True (limitacion conocida)",
    ),
    # Control positivo: sin negacion, negated=False
    (
        "Vera Luntz pertenece a la Cofradia del Malecon.",
        "la Cofradia del Malecon",
        False,
        "sin negacion = negated False",
    ),
])
def test_classify_negation_b2_frases(text, anchor, expected_negated, desc):
    """analyze_raw_text clasifica correctamente la negacion para frases de B2."""
    focus_char = text.find(anchor)
    assert focus_char >= 0, f"ancla {anchor!r} no encontrada en {text!r}"
    verdict = analyze_raw_text(text, focus_char=focus_char)
    assert bool(verdict.negated) == expected_negated, (
        f"[{desc}] text={text!r} anchor={anchor!r}: "
        f"esperado negated={expected_negated}, obtenido negated={verdict.negated} "
        f"kind={verdict.negation_kind!r}"
    )


# ---------------------------------------------------------------------------
# 4. "bajo el control del" en contexto: scope + negacion
# ---------------------------------------------------------------------------

def test_bajo_el_control_del_con_no_clasifica_como_negado():
    """'X no esta bajo el control del Y' => classify_negation ve 'no' en ventana -> negated=True."""
    text = "El Puerto Escoria no esta bajo el control del Gremio de Fundidores."
    anchor = "el Gremio de Fundidores"
    focus_char = text.find(anchor)
    assert focus_char >= 0
    verdict = analyze_raw_text(text, focus_char=focus_char)
    # La negacion 'no' esta en la ventana antes de la frase de relacion.
    assert verdict.negated is True, (
        f"Esperado negated=True, obtenido negated={verdict.negated} kind={verdict.negation_kind!r}"
    )


def test_bajo_el_control_del_sin_no_clasifica_como_positivo():
    """'X esta bajo el control del Y' => sin negacion -> negated=False."""
    text = "El Puerto Escoria esta bajo el control del Gremio de Fundidores."
    anchor = "el Gremio de Fundidores"
    focus_char = text.find(anchor)
    assert focus_char >= 0
    verdict = analyze_raw_text(text, focus_char=focus_char)
    assert verdict.negated is False, (
        f"Esperado negated=False, obtenido negated={verdict.negated} kind={verdict.negation_kind!r}"
    )


# ---------------------------------------------------------------------------
# 5. Precision: las nuevas frases NO son corpus literals (entidades)
# ---------------------------------------------------------------------------

_NEW_PHRASES_B2 = [
    "bajo el control del",
    "abandono",
    "haya abandonado",
    "pertenece al",
    "pertenecia al",
    "pertenecio al",
    "este en",
    "ha dejado de estar dirigida por",
    "ha dejado de estar dirigido por",
]

_PROPER_NOUN_TOKENS = {
    # entidades del corpus de desarrollo (basalto/cirro/zafiro)
    "harun", "vell", "orden", "obsidiana", "sira", "delantre", "fumarola",
    "hermandad", "mira", "cauce", "gremio", "fundidores", "vera", "luntz",
    "radi", "oster", "hugo", "marlen", "junta", "astilleros", "olmo", "quiral",
    "foso", "humeante", "ilde", "varona", "goran", "ute", "escuela", "corriente",
    "kena", "drovic", "sonda", "madre", "domo", "tres", "fosa", "clara",
    "paz", "ontiveros", "flota", "perlera", "sindicato", "abisal", "tomas",
    "esquil", "lira", "fenn", "pol", "arriaga", "tanit", "pereo", "cofradia",
    "velas", "selva", "ondiz", "carta", "fletes", "consejo", "vientos",
    "anemos", "torre",
}


@pytest.mark.parametrize("phrase", _NEW_PHRASES_B2)
def test_nueva_frase_b2_no_es_nombre_propio_de_corpus(phrase):
    """Las frases de B2 son construcciones de lengua, no literales del corpus."""
    tokens = {t.lower() for t in phrase.split()}
    overlap = tokens & _PROPER_NOUN_TOKENS
    assert not overlap, (
        f"La frase {phrase!r} contiene tokens que parecen nombre propio del corpus: {overlap}. "
        f"Las frases de relacion deben ser marcadores de lengua (morfologia/sintaxis/vocabulario "
        f"cerrado), nunca literales del corpus."
    )

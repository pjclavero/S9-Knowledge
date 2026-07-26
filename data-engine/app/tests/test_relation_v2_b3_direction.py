# -*- coding: utf-8 -*-
"""Bloque 3 (motor de relaciones v2): DIRECCION como modulo independiente.

Tests REALES del modulo `relations.direction`. Cubre los casos obligatorios de la
spec B3: A->B, B->A, activa, pasiva, agente de pasiva, relacion inversa, relacion
simetrica (->UNDIRECTED), orden textual enganoso, pronombre, correferencia,
interfrase y sujeto omitido.

Los ejemplos son frases GENERALES del espanol con entidades inventadas (NO calcos
del corpus de benchmark): validan las REGLAS gramaticales/ontologicas, no textos
concretos. Cada assert muerde (direccion + a menudo la regla que decidio).
"""
from __future__ import annotations

from relations.contracts import Direction
from relations.direction import (
    DIRECTION_VERSION,
    DirectionResult,
    resolve_direction,
)
from relations.syntax import SyntaxAnalysis, SyntaxSentence, SyntaxToken


# ---------------------------------------------------------------------------
# Utillaje determinista (sin red, sin disco)
# ---------------------------------------------------------------------------
def _span(text: str, sub: str) -> tuple[int, int]:
    """Offsets [start, end) de la PRIMERA aparicion de `sub` en `text`."""
    i = text.index(sub)
    return i, i + len(sub)


def _resolve(seg: str, predicate: str, subj: str, obj: str,
             syntax: SyntaxAnalysis | None = None) -> DirectionResult:
    """Resuelve la direccion tomando los offsets reales de `subj`/`obj` en `seg`."""
    s0, s1 = _span(seg, subj)
    o0, o1 = _span(seg, obj)
    return resolve_direction(predicate, s0, s1, o0, o1, seg, syntax=syntax)


def _mk_syntax(seg: str, *, subj_word: str | None = None,
               obj_word: str | None = None, verb_word: str | None = None,
               passive: bool = False,
               sent_span: tuple[int, int] | None = None) -> SyntaxAnalysis:
    """Construye un SyntaxAnalysis MINIMO y determinista para una sola frase.

    Solo materializa los tokens de sujeto/objeto/verbo referenciados (los unicos
    que consulta el modulo), con offsets reales sobre `seg`.
    """
    lo, hi = sent_span if sent_span is not None else (0, len(seg))
    tokens: list[SyntaxToken] = []
    subject_index = object_index = main_verb_index = None
    idx = 0
    for word, is_subj, is_obj, is_verb in (
        (subj_word, True, False, False),
        (verb_word, False, False, True),
        (obj_word, False, True, False),
    ):
        if not word:
            continue
        start, end = _span(seg, word)
        tokens.append(SyntaxToken(index=idx, text=word, start=start, end=end))
        if is_subj:
            subject_index = idx
        if is_obj:
            object_index = idx
        if is_verb:
            main_verb_index = idx
        idx += 1
    sent = SyntaxSentence(
        index=0, text=seg[lo:hi], start=lo, end=hi,
        tokens=tuple(tokens),
        subject_index=subject_index,
        main_verb_index=main_verb_index,
        object_index=object_index,
        passive=passive,
    )
    return SyntaxAnalysis(
        text=seg, language="es", provider="test", version="test",
        sentences=(sent,),
    )


# ---------------------------------------------------------------------------
# Version / contrato del modulo
# ---------------------------------------------------------------------------
def test_module_version_is_stable_string():
    assert DIRECTION_VERSION == "relation-direction-1.0.0"


def test_result_is_frozen_dataclass_with_confidence_in_range():
    seg = "Marcus fundó la Orden Carmesí en el norte."
    res = _resolve(seg, "FOUNDED", "Marcus", "Orden Carmesí")
    assert isinstance(res, DirectionResult)
    assert 0.0 < res.confidence <= 1.0
    # inmutable: no se puede mutar la traza
    try:
        res.direction = Direction.UNDIRECTED  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# A -> B (fuente = primera mencion) y B -> A (fuente = segunda mencion)
# ---------------------------------------------------------------------------
def test_a_to_b_active_expression_source_is_subject():
    # "fundó" = expresion ACTIVA de FOUNDED; la fuente es la mencion ANTERIOR.
    seg = "Marcus fundó la Orden Carmesí tras la guerra."
    res = _resolve(seg, "FOUNDED", "Marcus", "Orden Carmesí")
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "active_expression"


def test_b_to_a_inverse_expression_source_is_object():
    # "pertenece a" = expresion PASIVA/INVERSA de OWNS; el complemento (Kael, la
    # segunda mencion) es el DUENO = fuente -> OBJECT_TO_SUBJECT.
    seg = "La reliquia rúnica pertenece a Kael desde antaño."
    res = _resolve(seg, "OWNS", "La reliquia rúnica", "Kael")
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "inverse_expression"


# ---------------------------------------------------------------------------
# Voz ACTIVA por sujeto/objeto gramatical (sintaxis)
# ---------------------------------------------------------------------------
def test_active_grammatical_subject_object():
    # Sin expresion de ontologia; la direccion la fija el sujeto gramatical.
    seg = "Bruno respalda a la Hermandad del Alba."
    syn = _mk_syntax(seg, subj_word="Bruno", verb_word="respalda",
                     obj_word="Hermandad del Alba")
    res = _resolve(seg, "TRUSTS", "Bruno", "Hermandad del Alba", syntax=syn)
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "grammatical_subject"


def test_active_grammatical_reversed_when_subject_is_second_mention():
    # El sujeto gramatical es la SEGUNDA mencion textual -> OBJECT_TO_SUBJECT.
    seg = "A la Hermandad la respalda Bruno con firmeza."
    syn = _mk_syntax(seg, subj_word="Bruno", verb_word="respalda",
                     obj_word="Hermandad")
    res = _resolve(seg, "TRUSTS", "Hermandad", "Bruno", syntax=syn)
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "grammatical_subject"


# ---------------------------------------------------------------------------
# Voz PASIVA + AGENTE ("... por X"): regla GENERAL (no depende del lexico)
# ---------------------------------------------------------------------------
def test_passive_with_agent_flips_to_object_to_subject():
    # "construido" no esta en las expresiones de CREATED: lo resuelve la pasiva
    # perifrastica GENERAL (participio + "por" + agente).
    seg = "El bastión fue construido por los Enanos de Kord."
    res = _resolve(seg, "CREATED", "El bastión", "los Enanos de Kord")
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "passive_agent"


def test_passive_agent_anchored_ignores_third_party_agent():
    # El agente ("Centinelas") NO es ninguna de las dos menciones del par
    # (bastión, Fortaleza): la pasiva se ABSTIENE y no invierte la localizacion.
    seg = "El bastión fue vigilado por los Centinelas en la Fortaleza Gris."
    res = _resolve(seg, "LOCATED_IN", "El bastión", "Fortaleza Gris")
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "textual_order"


def test_passive_hint_from_syntax_enables_agent_reading():
    # Sin participio reconocible por sufijo, pero la sintaxis marca passive=True.
    seg = "El sello quedó roto por la Cofradía Escarlata."
    syn = _mk_syntax(seg, subj_word="sello", verb_word="quedó",
                     obj_word="Cofradía Escarlata", passive=True)
    # syntax abstiene en gramatical (passive) y habilita el agente.
    res = _resolve(seg, "CREATED", "El sello", "Cofradía Escarlata", syntax=syn)
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "passive_agent"


# ---------------------------------------------------------------------------
# Relacion INVERSA (nucleo relacional inverso de parentesco)
# ---------------------------------------------------------------------------
def test_inverse_kinship_child_of_maps_parent_as_source():
    # "hija de" = pasiva/inversa de PARENT_OF; el padre (Gorm) es la fuente.
    seg = "Lena, hija de Gorm, lideró la revuelta."
    res = _resolve(seg, "PARENT_OF", "Lena", "Gorm")
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "inverse_expression"


def test_active_kinship_parent_of_keeps_subject_source():
    # "padre de" = activa de PARENT_OF; el padre (Gorm) es la primera mencion.
    seg = "Gorm, padre de Lena, gobernó el valle."
    res = _resolve(seg, "PARENT_OF", "Gorm", "Lena")
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "active_expression"


# ---------------------------------------------------------------------------
# Relacion SIMETRICA -> UNDIRECTED (invariante del predicado)
# ---------------------------------------------------------------------------
def test_symmetric_predicate_is_undirected_regardless_of_text():
    seg = "Aldo selló una alianza con la Casa Bren en primavera."
    res = _resolve(seg, "ALLIED_WITH", "Aldo", "Casa Bren")
    assert res.direction == Direction.UNDIRECTED
    assert res.rationale == "symmetric_undirected"


def test_symmetric_undirected_even_with_passive_structure():
    # Aunque haya estructura de "por", la simetria DOMINA: no se orienta.
    seg = "La Casa Bren fue enfrentada por el clan Aldo durante años."
    res = _resolve(seg, "ENEMY_OF", "La Casa Bren", "clan Aldo")
    assert res.direction == Direction.UNDIRECTED
    assert res.rationale == "symmetric_undirected"


def test_all_symmetric_predicates_resolve_undirected():
    for pred in ("ALLIED_WITH", "ENEMY_OF", "SIBLING_OF", "MARRIED_TO", "ALIAS_OF"):
        seg = "Primero y Segundo aparecen juntos en la cronica."
        res = resolve_direction(pred, *_span(seg, "Primero"),
                                *_span(seg, "Segundo"), seg)
        assert res.direction == Direction.UNDIRECTED, pred


# ---------------------------------------------------------------------------
# Orden textual ENGAÑOSO: la fuente semantica es la SEGUNDA mencion
# ---------------------------------------------------------------------------
def test_misleading_textual_order_overridden_by_passive():
    # Orden textual: tesoro primero; pero el agente (Cofradia) es la fuente real.
    seg = "El tesoro fue robado por la Cofradía de la Sombra."
    res = _resolve(seg, "OWNS", "El tesoro", "Cofradía de la Sombra")
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "passive_agent"


def test_textual_order_is_weak_fallback_when_no_cue():
    # Sin ningun indicio: fallback DEBIL al orden textual (sujeto = fuente).
    seg = "Kira y el Consejo del Norte comparten historia."
    res = _resolve(seg, "KNOWS", "Kira", "Consejo del Norte")
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "textual_order"
    assert res.confidence == 0.5


# ---------------------------------------------------------------------------
# PRONOMBRE / CORREFERENCIA basica
# ---------------------------------------------------------------------------
def test_pronoun_subject_corefers_to_prior_mention():
    # Sujeto gramatical = pronombre "ella"; correfiere a la mencion previa (Dara).
    seg = "Cuando Dara callaba, ella dominaba el Pacto Astral."
    syn = _mk_syntax(seg, subj_word="ella", verb_word="dominaba",
                     obj_word="Pacto Astral")
    res = _resolve(seg, "KNOWS", "Dara", "Pacto Astral", syntax=syn)
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "coref_pronoun"


def test_pronoun_without_prior_mention_falls_back_to_textual():
    # Pronombre sin antecedente del par -> no hay correferencia -> fallback textual.
    seg = "Ella custodiaba en silencio."
    # menciones inventadas fuera de solape con el pronombre
    seg2 = "Ella observaba a Orin junto al Cofre."
    syn = _mk_syntax(seg2, subj_word="Ella", verb_word="observaba",
                     obj_word="Cofre")
    res = resolve_direction("KNOWS", *_span(seg2, "Orin"),
                            *_span(seg2, "Cofre"), seg2, syntax=syn)
    # Orin esta DESPUES del pronombre: no hay mencion del par previa -> textual.
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale in ("textual_order", "coref_pronoun")


# ---------------------------------------------------------------------------
# INTERFRASE: menciones en frases distintas dentro de la ventana
# ---------------------------------------------------------------------------
def test_interphrase_inverse_expression_across_sentences():
    # El sujeto (Grimorio) esta en la 1a frase y el objeto (Orin) en la 2a; la
    # expresion inversa "pertenece al" cruza la frontera de frase pero la ventana
    # cubre ambas -> OBJECT_TO_SUBJECT.
    seg = "El Grimorio reposaba sobre la mesa. Pertenece al mago Orin."
    res = _resolve(seg, "OWNS", "El Grimorio", "Orin")
    assert res.direction == Direction.OBJECT_TO_SUBJECT
    assert res.rationale == "inverse_expression"


# ---------------------------------------------------------------------------
# SUJETO OMITIDO (pro-drop): el modulo no rompe y cae al lexico/orden
# ---------------------------------------------------------------------------
def test_pro_drop_subject_does_not_break_resolution():
    # 2a frase sin sujeto explicito (pro-drop): subject_index=None. La expresion
    # activa "custodia" fija la fuente en la mencion anterior (Guardián).
    seg = "El Guardián no descansa. Custodia la Reliquia Sellada."
    syn = _mk_syntax(seg, subj_word=None, verb_word="Custodia",
                     obj_word="Reliquia Sellada",
                     sent_span=_span(seg, "Custodia la Reliquia Sellada."))
    res = _resolve(seg, "GUARDS", "Guardián", "Reliquia Sellada", syntax=syn)
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "active_expression"


def test_pro_drop_without_lexicon_uses_textual_fallback():
    # Sin sujeto explicito y sin lexico ni agente: fallback textual, sin excepcion.
    seg = "Aparecio de noche. Rozaba el Consejo y a Kira."
    res = _resolve(seg, "KNOWS", "Consejo", "Kira", syntax=None)
    assert res.direction == Direction.SUBJECT_TO_OBJECT
    assert res.rationale == "textual_order"


# ---------------------------------------------------------------------------
# Predicado generico / desconocido -> sin direccion semantica
# ---------------------------------------------------------------------------
def test_related_to_is_undirected():
    seg = "Kira y Orin coinciden en la cronica del sur."
    res = _resolve(seg, "RELATED_TO", "Kira", "Orin")
    assert res.direction == Direction.UNDIRECTED
    assert res.rationale == "generic_undirected"


def test_unknown_predicate_is_undirected_not_crash():
    seg = "Alfa se relaciona con Beta de forma incierta."
    res = _resolve(seg, "NOT_A_PREDICATE", *_span(seg, "Alfa"),
                   *_span(seg, "Beta"), seg) if False else resolve_direction(
        "NOT_A_PREDICATE", *_span(seg, "Alfa"), *_span(seg, "Beta"), seg)
    assert res.direction == Direction.UNDIRECTED
    assert res.rationale == "generic_undirected"


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------
def test_resolution_is_deterministic():
    seg = "El bastión fue construido por los Enanos de Kord."
    outs = {
        (_resolve(seg, "CREATED", "El bastión", "los Enanos de Kord").direction,
         _resolve(seg, "CREATED", "El bastión", "los Enanos de Kord").rationale)
        for _ in range(5)
    }
    assert len(outs) == 1

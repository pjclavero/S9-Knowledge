# -*- coding: utf-8 -*-
"""Politica comun y fail-closed de factualidad para todas las extracciones.

Este modulo no contiene vocabulario linguistico. Las marcas viven unicamente
en :mod:`cues`; aqui solo entra el resultado tipado de haberlas detectado.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FactivityClass(str, Enum):
    ASSERTED_FACT = "ASSERTED_FACT"
    NEGATED_FACT = "NEGATED_FACT"
    QUESTION = "QUESTION"
    CONDITIONAL = "CONDITIONAL"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    HYPOTHETICAL = "HYPOTHETICAL"
    DESIRE = "DESIRE"
    COMMAND = "COMMAND"
    REPORTED_FALSEHOOD = "REPORTED_FALSEHOOD"
    FICTION_WITHIN_FICTION = "FICTION_WITHIN_FICTION"
    RUMOR = "RUMOR"
    UNKNOWN = "UNKNOWN"


class FactivityAction(str, Enum):
    EMIT_WORLD_CLAIM = "EMIT_WORLD_CLAIM"
    EMIT_NEGATED_WORLD_CLAIM = "EMIT_NEGATED_WORLD_CLAIM"
    EMIT_EPISTEMIC_PROPOSAL = "EMIT_EPISTEMIC_PROPOSAL"
    EMIT_DIAGNOSTIC = "EMIT_DIAGNOSTIC"
    ABSTAIN = "ABSTAIN"
    REVIEW_SCOPE = "REVIEW_SCOPE"


@dataclass(frozen=True)
class FactivitySignals:
    """Señales ya detectadas por ``cues.py``; no vuelve a leer el texto."""

    negated: bool = False
    question: bool = False
    conditional: bool = False
    counterfactual: bool = False
    hypothetical: bool = False
    desire: bool = False
    command: bool = False
    reported_falsehood: bool = False
    fiction_within_fiction: bool = False
    rumor: bool = False
    ambiguous_scope: bool = False


@dataclass(frozen=True)
class FactivityResult:
    factivity_class: FactivityClass
    cues: tuple[str, ...]
    scope: str
    reasons: tuple[str, ...]
    action: FactivityAction


def classify_factivity(
    signals: FactivitySignals,
    *,
    cues: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    scope: str = "WORLD",
) -> FactivityResult:
    """Clasifica con precedencia conservadora y una accion explicita.

    La ambigüedad gana a cualquier lectura factual. Los marcos que niegan la
    factualidad ganan a una negación gramatical interna: ``es falso que no X``
    no autoriza a invertir dos veces y materializar X.
    """
    if signals.ambiguous_scope or not scope:
        return FactivityResult(
            FactivityClass.UNKNOWN, cues, scope or "AMBIGUOUS", reasons,
            FactivityAction.REVIEW_SCOPE,
        )
    ordered = (
        (signals.question, FactivityClass.QUESTION),
        (signals.counterfactual, FactivityClass.COUNTERFACTUAL),
        (signals.reported_falsehood, FactivityClass.REPORTED_FALSEHOOD),
        (signals.fiction_within_fiction, FactivityClass.FICTION_WITHIN_FICTION),
        (signals.desire, FactivityClass.DESIRE),
        (signals.command, FactivityClass.COMMAND),
        (signals.conditional, FactivityClass.CONDITIONAL),
        (signals.hypothetical, FactivityClass.HYPOTHETICAL),
        (signals.rumor, FactivityClass.RUMOR),
    )
    for present, classification in ordered:
        if not present:
            continue
        action = {
            # No existe aun un contrato epistémico separado y seguro. Hasta
            # entonces la hipótesis conserva su evidencia en el episodio y
            # sale como diagnóstico, nunca como relación factual.
            FactivityClass.HYPOTHETICAL: FactivityAction.EMIT_DIAGNOSTIC,
            FactivityClass.RUMOR: FactivityAction.EMIT_EPISTEMIC_PROPOSAL,
        }.get(classification, FactivityAction.EMIT_DIAGNOSTIC)
        return FactivityResult(classification, cues, scope, reasons, action)
    if signals.negated:
        return FactivityResult(
            FactivityClass.NEGATED_FACT, cues, scope, reasons,
            FactivityAction.EMIT_NEGATED_WORLD_CLAIM,
        )
    return FactivityResult(
        FactivityClass.ASSERTED_FACT, cues, scope, reasons,
        FactivityAction.EMIT_WORLD_CLAIM,
    )


__all__ = [
    "FactivityAction",
    "FactivityClass",
    "FactivityResult",
    "FactivitySignals",
    "classify_factivity",
]

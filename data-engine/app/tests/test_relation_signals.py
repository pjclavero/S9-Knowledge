# -*- coding: utf-8 -*-
"""Tests de las senales heuristicas explicables (`relation-signals/v1`).

Cubren, por senal, casos positivos y negativos; ademas: negacion detectada,
temporalidad preservada, rumor marcado, explicabilidad (value+evidence+
explanation+version en cada resultado) y determinismo. SIN red, SIN Neo4j,
SIN LLM. Solo leen `relations.signals` y `relations.contracts`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.signals import (  # noqa: E402
    Signal,
    SignalContext,
    SIGNALS_VERSION,
    TYPE_ONTOLOGY,
    compute_all_signals,
    signal_distance,
    signal_same_sentence,
    signal_same_clause,
    signal_type_compatibility,
    signal_svo,
    signal_membership,
    signal_possession,
    signal_location,
    signal_negation,
    signal_temporality,
    signal_modality,
    signal_rumor,
    signal_repetition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ctx(segment: str, subj: str, obj: str, **kw) -> SignalContext:
    """Construye un SignalContext localizando subj/obj por su texto literal."""
    s0 = segment.index(subj)
    o0 = segment.index(obj)
    return SignalContext(
        segment=segment,
        subject_start=s0,
        subject_end=s0 + len(subj),
        object_start=o0,
        object_end=o0 + len(obj),
        **kw,
    )


def _assert_explainable(sig: Signal) -> None:
    """Toda senal debe traer los cinco campos con version fijada."""
    assert isinstance(sig.name, str) and sig.name
    assert sig.value is not None
    assert isinstance(sig.evidence, str)
    assert isinstance(sig.explanation, str) and sig.explanation
    assert sig.version == SIGNALS_VERSION


# ---------------------------------------------------------------------------
# Contexto / validacion de offsets
# ---------------------------------------------------------------------------
def test_context_rejects_bad_offsets():
    with pytest.raises(ValueError):
        SignalContext(segment="abc", subject_start=0, subject_end=1,
                      object_start=2, object_end=99)
    with pytest.raises(ValueError):
        SignalContext(segment="abc", subject_start=2, subject_end=1,
                      object_start=0, object_end=1)


def test_context_rejects_bad_type():
    with pytest.raises(ValueError):
        SignalContext(segment="Akodo vive en Rokugan", subject_start=0,
                      subject_end=5, object_start=14, object_end=21,
                      subject_type="NoExiste")


# ---------------------------------------------------------------------------
# distancia
# ---------------------------------------------------------------------------
def test_distance_close_vs_far():
    near = _ctx("Akodo lidera el Clan Leon.", "Akodo", "Clan Leon")
    far = _ctx(
        "Akodo camino durante muchos dias por tierras lejanas hasta el Clan Leon.",
        "Akodo", "Clan Leon",
    )
    s_near = signal_distance(near)
    s_far = signal_distance(far)
    _assert_explainable(s_near)
    assert s_near.value["tokens"] < s_far.value["tokens"]
    assert s_near.value["chars"] >= 0
    # evidencia es el texto literal entre menciones
    assert s_near.evidence in near.segment


# ---------------------------------------------------------------------------
# misma frase / misma clausula
# ---------------------------------------------------------------------------
def test_same_sentence_positive_and_negative():
    pos = _ctx("Akodo pertenece al Clan Leon.", "Akodo", "Clan Leon")
    assert signal_same_sentence(pos).value is True
    neg = _ctx("Akodo medita. El Clan Leon prospera.", "Akodo", "Clan Leon")
    assert signal_same_sentence(neg).value is False


def test_same_clause_positive_and_negative():
    pos = _ctx("Akodo lidera el Clan Leon con honor.", "Akodo", "Clan Leon")
    assert signal_same_clause(pos).value is True
    neg = _ctx("Akodo, un samurai, sirve al Clan Leon.", "Akodo", "Clan Leon")
    # separados por comas -> distinta clausula
    assert signal_same_clause(neg).value is False


# ---------------------------------------------------------------------------
# compatibilidad de tipos (ontologia)
# ---------------------------------------------------------------------------
def test_type_compatibility_membership():
    ctx = _ctx("Akodo pertenece al Clan Leon.", "Akodo", "Clan Leon",
               subject_type="Character", object_type="Faction")
    sig = signal_type_compatibility(ctx)
    _assert_explainable(sig)
    assert "MEMBERSHIP" in sig.value


def test_type_compatibility_incompatible_and_missing():
    incompat = _ctx("Akodo y Bayushi hablan.", "Akodo", "Bayushi",
                    subject_type="Character", object_type="Character")
    assert signal_type_compatibility(incompat).value == []
    missing = _ctx("Akodo y Bayushi hablan.", "Akodo", "Bayushi")
    assert signal_type_compatibility(missing).value == []


def test_ontology_uses_allowed_entity_types_only():
    from relations.contracts import ALLOWED_ENTITY_TYPES
    for pairs in TYPE_ONTOLOGY.values():
        for a, b in pairs:
            assert a in ALLOWED_ENTITY_TYPES
            assert b in ALLOWED_ENTITY_TYPES


# ---------------------------------------------------------------------------
# SVO
# ---------------------------------------------------------------------------
def test_svo_positive_and_negative():
    pos = _ctx("Akodo lidera el Clan Leon.", "Akodo", "Clan Leon")
    sig = signal_svo(pos)
    assert sig.value is True
    assert sig.evidence == "lidera"
    neg = _ctx("Akodo, Clan Leon", "Akodo", "Clan Leon")
    assert signal_svo(neg).value is False


# ---------------------------------------------------------------------------
# pertenencia / posesion / ubicacion
# ---------------------------------------------------------------------------
def test_membership_positive_and_negative():
    pos = _ctx("Akodo es miembro de Clan Leon.", "Akodo", "Clan Leon")
    s = signal_membership(pos)
    assert s.value is True
    assert "miembro de" in s.evidence.lower()
    neg = _ctx("Akodo observa el Clan Leon.", "Akodo", "Clan Leon")
    assert signal_membership(neg).value is False


def test_possession_positive_and_negative():
    pos = _ctx("Akodo posee la Espada Sagrada.", "Akodo", "Espada Sagrada")
    assert signal_possession(pos).value is True
    neg = _ctx("Akodo mira la Espada Sagrada.", "Akodo", "Espada Sagrada")
    assert signal_possession(neg).value is False


def test_location_positive_and_negative():
    pos = _ctx("Akodo vive en Rokugan.", "Akodo", "Rokugan")
    assert signal_location(pos).value is True
    neg = _ctx("Akodo recuerda Rokugan.", "Akodo", "Rokugan")
    assert signal_location(neg).value is False


# ---------------------------------------------------------------------------
# negacion
# ---------------------------------------------------------------------------
def test_negation_detected_and_absent():
    pos = _ctx("Akodo no pertenece al Clan Leon.", "Akodo", "Clan Leon")
    s = signal_negation(pos)
    assert s.value is True
    assert s.evidence.strip().lower().startswith("no")
    neg = _ctx("Akodo pertenece al Clan Leon.", "Akodo", "Clan Leon")
    assert signal_negation(neg).value is False


def test_negation_jamas_variant():
    pos = _ctx("Akodo jamas traiciona al Clan Leon.", "Akodo", "Clan Leon")
    assert signal_negation(pos).value is True


# ---------------------------------------------------------------------------
# temporalidad (preservada)
# ---------------------------------------------------------------------------
def test_temporality_preserves_markers_and_years():
    ctx = _ctx(
        "Antes de 1123 Akodo lidero el Clan Leon.",
        "Akodo", "Clan Leon",
    )
    s = signal_temporality(ctx)
    _assert_explainable(s)
    assert s.value["years"] == ["1123"]
    assert any("antes de" in m.lower() for m in s.value["markers"])


def test_temporality_absent():
    ctx = _ctx("Akodo lidera el Clan Leon.", "Akodo", "Clan Leon")
    s = signal_temporality(ctx)
    assert s.value["markers"] == []
    assert s.value["years"] == []


# ---------------------------------------------------------------------------
# modalidad
# ---------------------------------------------------------------------------
def test_modality_positive_and_negative():
    pos = _ctx("Akodo podria liderar el Clan Leon.", "Akodo", "Clan Leon")
    assert signal_modality(pos).value is True
    neg = _ctx("Akodo lidera el Clan Leon.", "Akodo", "Clan Leon")
    assert signal_modality(neg).value is False


# ---------------------------------------------------------------------------
# rumor
# ---------------------------------------------------------------------------
def test_rumor_marked_and_absent():
    pos = _ctx("Se dice que Akodo traiciono al Clan Leon.", "Akodo", "Clan Leon")
    s = signal_rumor(pos)
    assert s.value is True
    assert "se dice que" in s.evidence.lower()
    neg = _ctx("Akodo traiciono al Clan Leon.", "Akodo", "Clan Leon")
    assert signal_rumor(neg).value is False


# ---------------------------------------------------------------------------
# repeticion documental
# ---------------------------------------------------------------------------
def test_repetition_counts_occurrences():
    ctx = _ctx(
        "Akodo lidera el Clan Leon.", "Akodo", "Clan Leon",
        occurrences=(
            "Akodo lidera el Clan Leon.",
            "El Clan Leon obedece a Akodo.",
            "Akodo funda el Clan Leon.",
        ),
    )
    s = signal_repetition(ctx)
    assert s.value == 3
    assert "||" in s.evidence


def test_repetition_default_single():
    ctx = _ctx("Akodo lidera el Clan Leon.", "Akodo", "Clan Leon")
    assert signal_repetition(ctx).value == 1


# ---------------------------------------------------------------------------
# explicabilidad de TODAS las senales
# ---------------------------------------------------------------------------
def test_all_signals_are_explainable():
    ctx = _ctx(
        "Se dice que antes de 1123 Akodo no vivia en Rokugan.",
        "Akodo", "Rokugan",
        subject_type="Character", object_type="Location",
    )
    sigs = compute_all_signals(ctx)
    assert len(sigs) == 13
    names = [s.name for s in sigs]
    assert len(names) == len(set(names))  # nombres unicos
    for sig in sigs:
        _assert_explainable(sig)


# ---------------------------------------------------------------------------
# determinismo
# ---------------------------------------------------------------------------
def test_determinism_repeated_calls_identical():
    ctx = _ctx(
        "Se dice que Akodo podria pertenecer al Clan Leon en 1123.",
        "Akodo", "Clan Leon",
        subject_type="Character", object_type="Faction",
    )
    first = [s.to_dict() for s in compute_all_signals(ctx)]
    second = [s.to_dict() for s in compute_all_signals(ctx)]
    assert first == second


def test_signal_is_frozen_no_side_effects():
    sig = signal_distance(_ctx("Akodo lidera el Clan Leon.", "Akodo", "Clan Leon"))
    with pytest.raises(Exception):
        sig.value = 999  # frozen dataclass -> inmutable

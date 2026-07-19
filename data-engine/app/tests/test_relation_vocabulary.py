# -*- coding: utf-8 -*-
"""Suite de pruebas del Bloque 3: normalizacion semantica de predicados.

Prueba el modulo REAL `relations.vocabulary` (sin mocks): canonicalizacion de
alias, idempotencia de canonicos, normalizacion tipografica previa, fallback
humano para predicados fuera de vocabulario/desconocidos, emparejamiento por
canonico, simetria, compatibilidad de tipos, versionado y trazabilidad.

Incluye una GUARDIA DE COBERTURA que verifica que todo predicado presente en el
ground truth del benchmark esta cubierto por el vocabulario (canonico, alias o
out_of_vocab). Los tests marcados `@pytest.mark.mutation` son load-bearing:
matan mutantes que rompen invariantes del bloque.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from relations.contracts import SCHEMA_VERSION, normalize_predicate
from relations.vocabulary import (
    CANONICAL_PREDICATES,
    OUT_OF_VOCAB_V1,
    PREDICATE_ALIASES,
    SYMMETRIC_PREDICATES,
    VOCAB_VERSION,
    canonicalize_predicate,
    is_symmetric,
    predicates_match,
    types_compatible,
)

# Ruta al ground truth del benchmark (fuente para la guardia de cobertura).
_GROUND_TRUTH = (
    Path(__file__).resolve().parent
    / "data"
    / "relation_benchmark"
    / "ground_truth"
    / "relations.json"
)


# ---------------------------------------------------------------------------
# 1. alias -> canonico
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_alias_enemy_of_maps_to_enemies_with():
    """Un alias debe resolverse al canonico, NO devolver el raw (mutante)."""
    result = canonicalize_predicate("enemy-of")
    assert result.canonical == "ENEMIES_WITH"
    assert result.status == "alias"
    # Mata el mutante "alias no normalizado": si ignorara el alias devolveria
    # el propio normalized ("ENEMY_OF") como canonical.
    assert result.canonical != result.normalized


def test_alias_succeeded_maps_to_successor_of():
    result = canonicalize_predicate("SUCCEEDED")
    assert result.canonical == "SUCCESSOR_OF"
    assert result.status == "alias"


def test_alias_lives_in_maps_to_located_in():
    result = canonicalize_predicate("lives in")
    assert result.canonical == "LOCATED_IN"
    assert result.status == "alias"


def test_alias_ally_of_maps_to_allied_with():
    result = canonicalize_predicate("ALLY_OF")
    assert result.canonical == "ALLIED_WITH"
    assert result.status == "alias"


def test_alias_member_maps_to_member_of():
    result = canonicalize_predicate("MEMBER")
    assert result.canonical == "MEMBER_OF"
    assert result.status == "alias"


# ---------------------------------------------------------------------------
# 2. canonico idempotente
# ---------------------------------------------------------------------------
def test_canonical_is_idempotent():
    result = canonicalize_predicate("MEMBER_OF")
    assert result.status == "canonical"
    assert result.canonical == "MEMBER_OF"
    assert result.requires_human is False


@pytest.mark.parametrize("pred", sorted(CANONICAL_PREDICATES))
def test_every_canonical_predicate_is_stable(pred):
    """Todos los canonicos se canonizan a si mismos sin revision humana."""
    result = canonicalize_predicate(pred)
    assert result.status == "canonical"
    assert result.canonical == pred
    assert result.requires_human is False


# ---------------------------------------------------------------------------
# 3. normalizacion tipografica ANTES de mapear
# ---------------------------------------------------------------------------
@pytest.mark.mutation
@pytest.mark.parametrize("raw", ["  enemy_of  ", "Enemy-Of", "ENEMY OF", "enemy-of"])
def test_typographic_normalization_before_mapping(raw):
    """Variantes tipograficas del mismo alias deben colapsar a ENEMIES_WITH."""
    result = canonicalize_predicate(raw)
    assert result.canonical == "ENEMIES_WITH"
    assert result.status == "alias"
    # Mata el mutante "alias no normalizado": el raw crudo nunca es el canonical.
    assert result.canonical != raw


# ---------------------------------------------------------------------------
# 4. out_of_vocab -> fallback humano
# ---------------------------------------------------------------------------
@pytest.mark.mutation
@pytest.mark.parametrize("pred", sorted(OUT_OF_VOCAB_V1))
def test_out_of_vocab_requires_human(pred):
    """Cada predicado out_of_vocab: sin canonico, requiere revision humana."""
    result = canonicalize_predicate(pred)
    assert result.canonical is None
    assert result.status == "out_of_vocab"
    assert result.requires_human is True
    # Mata el mutante "desconocido aceptado como valido": jamas es "canonical".
    assert result.status != "canonical"


@pytest.mark.mutation
@pytest.mark.parametrize("pred", ["PARENT_OF", "MENTOR_OF", "MARRIED_TO"])
def test_specific_out_of_vocab_predicates(pred):
    result = canonicalize_predicate(pred)
    assert result.canonical is None
    assert result.status == "out_of_vocab"
    assert result.requires_human is True


# ---------------------------------------------------------------------------
# 5. desconocido total
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_unknown_predicate_requires_human():
    result = canonicalize_predicate("TOTALLY_MADE_UP_XYZ")
    assert result.status == "unknown"
    assert result.canonical is None
    assert result.requires_human is True
    # Mata el mutante "desconocido aceptado como valido".
    assert result.status != "canonical"


# ---------------------------------------------------------------------------
# 6. predicates_match
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "a,b",
    [("ally_of", "ALLIED_WITH"), ("ENEMY_OF", "ENEMIES_WITH"), ("member", "MEMBER_OF")],
)
def test_predicates_match_true_via_alias(a, b):
    assert predicates_match(a, b) is True


@pytest.mark.parametrize(
    "a,b",
    [
        ("MENTOR_OF", "MENTOR_OF"),  # out_of_vocab: no empareja consigo mismo
        ("PARENT_OF", "KIN_OF"),     # no colapsamos parentesco en KIN_OF
        ("MEMBER_OF", "OWNS"),       # canonicos distintos
    ],
)
def test_predicates_match_false(a, b):
    assert predicates_match(a, b) is False


@pytest.mark.mutation
def test_predicates_match_unknown_never_matches():
    """Mata el mutante "match laxo None": None==None NO debe emparejar."""
    assert predicates_match("TOTALLY_MADE_UP_XYZ", "TOTALLY_MADE_UP_XYZ") is False
    # Tampoco dos out_of_vocab distintos ni iguales.
    assert predicates_match("MENTOR_OF", "MENTOR_OF") is False


# ---------------------------------------------------------------------------
# 7. simetricas
# ---------------------------------------------------------------------------
@pytest.mark.mutation
@pytest.mark.parametrize("pred", ["ALLIED_WITH", "ENEMIES_WITH", "KIN_OF"])
def test_symmetric_predicates_are_symmetric(pred):
    """Mata el mutante "simetrica perdida": estas deben ser simetricas."""
    assert is_symmetric(pred) is True


def test_non_symmetric_predicate():
    assert is_symmetric("MEMBER_OF") is False


def test_symmetric_via_alias():
    assert is_symmetric("ally_of") is True


# ---------------------------------------------------------------------------
# 8. compatibilidad de tipos
# ---------------------------------------------------------------------------
def test_member_of_types_compatible():
    assert types_compatible("MEMBER_OF", "Character", "Faction") is True


@pytest.mark.mutation
def test_member_of_types_incompatible():
    """Mata el mutante "type-compat desactivado": tipos ilegales -> False."""
    assert types_compatible("MEMBER_OF", "Location", "Object") is False


def test_kin_of_symmetric_types_both_orders():
    assert types_compatible("KIN_OF", "Character", "Character") is True


def test_non_canonical_types_never_compatible():
    assert types_compatible("MENTOR_OF", "Character", "Character") is False


# ---------------------------------------------------------------------------
# 9. version de vocabulario
# ---------------------------------------------------------------------------
def test_vocab_version_present_and_distinct_from_schema():
    assert VOCAB_VERSION == "relation-vocab-1.0.0"
    assert VOCAB_VERSION != SCHEMA_VERSION


def test_vocab_version_in_canonicalization_trace():
    result = canonicalize_predicate("MEMBER_OF")
    assert result.vocab_version == VOCAB_VERSION


# ---------------------------------------------------------------------------
# 10. trazabilidad
# ---------------------------------------------------------------------------
def test_canonicalization_emits_seven_fields():
    result = canonicalize_predicate("enemy-of")
    for field in (
        "raw",
        "normalized",
        "canonical",
        "status",
        "rule",
        "vocab_version",
        "requires_human",
    ):
        assert hasattr(result, field), f"falta campo {field}"
    assert result.raw == "enemy-of"
    assert result.normalized == normalize_predicate("enemy-of")


def test_rule_describes_applied_decision():
    canonical = canonicalize_predicate("MEMBER_OF")
    assert canonical.rule and isinstance(canonical.rule, str)

    alias = canonicalize_predicate("enemy-of")
    # La regla del alias menciona el mecanismo de alias/sinonimo.
    assert "alias" in alias.rule.lower()

    unknown = canonicalize_predicate("TOTALLY_MADE_UP_XYZ")
    assert unknown.rule and unknown.rule != alias.rule


# ---------------------------------------------------------------------------
# 11. GUARDIA DE COBERTURA DEL GROUND TRUTH
# ---------------------------------------------------------------------------
def _ground_truth_predicates() -> set[str]:
    data = json.loads(_GROUND_TRUTH.read_text(encoding="utf-8"))
    return {rel["predicate"] for rel in data["relations"]}


@pytest.mark.mutation
def test_ground_truth_predicates_are_all_covered():
    """Todo predicado del ground truth esta cubierto por el vocabulario.

    Cubierto = canonico, o alias conocido, o out_of_vocab_v1. Si aparece un
    predicado nuevo en el corpus sin cobertura, este test FALLA listandolo:
    cierra la brecha que hoy nadie detecta. NO modifica el corpus.
    """
    predicates = _ground_truth_predicates()
    assert predicates, "el ground truth no contiene predicados"

    missing = []
    for raw in sorted(predicates):
        normalized = normalize_predicate(raw)
        covered = (
            normalized in CANONICAL_PREDICATES
            or normalized in PREDICATE_ALIASES
            or normalized in OUT_OF_VOCAB_V1
        )
        if not covered:
            missing.append(raw)

    assert not missing, (
        "Predicados del ground truth SIN cobertura en el vocabulario "
        f"(anadir a canonicos, alias u OUT_OF_VOCAB_V1): {missing}"
    )

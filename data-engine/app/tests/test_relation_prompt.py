# -*- coding: utf-8 -*-
"""Prioridad 2.1 — prompt de relaciones (taxonomía + few-shot + reglas) y
validación de relaciones. Sin llamadas a Ollama."""
from __future__ import annotations
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.llm_extractor import _SYSTEM_PROMPT, _validate_relation, _ALLOWED_RELATION_TYPES


# ── Estructura del prompt ─────────────────────────────────────────────────────

def test_prompt_declares_schema_direction():
    assert "origen -> destino" in _SYSTEM_PROMPT
    assert "Character -> Faction" in _SYSTEM_PROMPT


def test_prompt_has_fewshot_for_required_types():
    for rtype in ("MEMBER_OF", "LOCATED_IN", "FOUGHT_AT", "OWNS",
                  "ALLIED_WITH", "ENEMIES_WITH", "PARTICIPATED_IN", "KNOWS"):
        assert rtype in _SYSTEM_PROMPT, f"falta ejemplo/tipo {rtype}"


def test_prompt_has_clan_surname_rule():
    assert "apellido -> clan" in _SYSTEM_PROMPT
    assert "Bayushi" in _SYSTEM_PROMPT and "Clan Escorpión" in _SYSTEM_PROMPT
    assert "Kakita" in _SYSTEM_PROMPT and "Clan Grulla" in _SYSTEM_PROMPT


def test_prompt_has_negative_examples_and_evidence_rule():
    assert "EJEMPLOS NEGATIVOS" in _SYSTEM_PROMPT
    assert "ENEMY_OF" in _SYSTEM_PROMPT  # ejemplo de tipo inválido a evitar
    assert "evidence" in _SYSTEM_PROMPT


def test_prompt_only_uses_existing_relation_types():
    # Ningún tipo del esquema-guía debe estar fuera de la lista permitida real.
    for rtype in ("MEMBER_OF", "LOCATED_IN", "FOUGHT_AT", "OWNS", "ALLIED_WITH",
                  "ENEMIES_WITH", "PARTICIPATED_IN", "KNOWS"):
        assert rtype in _ALLOWED_RELATION_TYPES


# ── _validate_relation ────────────────────────────────────────────────────────

def _rel(**kw):
    d = dict(from_entity="Bayushi Hisao", relation_type="member_of",
             to_entity="Clan Escorpión", evidence="Bayushi Hisao", confidence=0.9)
    d.update(kw)
    return d


def test_validate_accepts_valid_and_uppercases_type():
    out = _validate_relation(_rel())
    assert out is not None
    assert out["relation_type"] == "MEMBER_OF"


def test_validate_rejects_disallowed_type():
    assert _validate_relation(_rel(relation_type="ENEMY_OF")) is None


def test_validate_requires_evidence():
    assert _validate_relation(_rel(evidence="")) is None


def test_validate_requires_identifiable_endpoints():
    assert _validate_relation(_rel(from_entity="")) is None
    assert _validate_relation(_rel(to_entity="A")) is None  # < 2 chars


def test_validate_clamps_confidence():
    assert _validate_relation(_rel(confidence=5.0))["confidence"] == 1.0
    assert _validate_relation(_rel(confidence=-1))["confidence"] == 0.0

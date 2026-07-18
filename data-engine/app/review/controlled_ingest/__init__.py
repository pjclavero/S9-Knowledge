"""Politica de ingesta controlada v1 (motor S9 Knowledge).

Slice vertical que produce y consume los contratos review/ingest v1 SIN tocar
produccion: genera candidatos, consume decisiones con control optimista, resume
la fuente, planifica de forma determinista, ejecuta en DRY_RUN (0 escrituras) y
bloquea APPLY salvo que se cumplan todas las condiciones de politica.

Todos los documentos se validan contra el validador UNICO publicado en
``contracts/review-ingest/v1/validator.py`` (ver ``contracts.py``).
"""
from __future__ import annotations

from .candidate_builder import (
    EngineCandidate,
    SourceContext,
    build_candidate,
    candidate_hash,
)
from .contracts import ContractError, is_valid, validate_document
from .decision import (
    OUTCOME_APPLIED,
    OUTCOME_CONFLICT,
    DecisionOutcome,
    apply_decision,
)
from .executor import blocked_result, dry_run
from .hashing import hash_block, sha256_hex
from .planner import PlanItem, build_plan, plan_hash
from .policy import ApplyGate, ApplyRequest, evaluate_apply
from .summary import build_summary

__all__ = [
    "SourceContext",
    "EngineCandidate",
    "build_candidate",
    "candidate_hash",
    "apply_decision",
    "DecisionOutcome",
    "OUTCOME_APPLIED",
    "OUTCOME_CONFLICT",
    "build_summary",
    "build_plan",
    "PlanItem",
    "plan_hash",
    "dry_run",
    "blocked_result",
    "evaluate_apply",
    "ApplyRequest",
    "ApplyGate",
    "validate_document",
    "is_valid",
    "ContractError",
    "hash_block",
    "sha256_hex",
]

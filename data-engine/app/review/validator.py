"""Validador de candidatos contra el schema RPG.

Comprueba:
- tipo de entidad o relación en schema (ALLOWED_NODE_TYPES, ALLOWED_RELATION_TYPES)
- tipos from/to compatibles para relaciones
- confidence numérica en [0, 1]
- evidence no vacía
- timestamps válidos (HH:MM:SS)
- source_id, source_kind, workspace presentes
- relaciones semánticamente absurdas (HAS_FOUGHT contra Location → sugiere FOUGHT_AT)
"""
from __future__ import annotations
import json
import logging
import re
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate, ValidationResult
from schemas.rpg_schema import ALLOWED_NODE_TYPES, ALLOWED_RELATION_TYPES

log = logging.getLogger(__name__)

TS_RE = re.compile(r'^\d{2}:\d{2}:\d{2}$')

# Relaciones que no tienen sentido contra Location → marcar dubious
_ENTITY_RELATION_CONFLICT: dict[str, set[str]] = {
    "HAS_FOUGHT": {"Location", "Region", "Faction", "Clan"},
    "LOVES": {"Location", "Region", "Faction", "Clan", "Object", "Artifact"},
    "SPOUSE_OF": {"Location", "Region", "Faction", "Clan", "Object"},
    "PARENT_OF": {"Location", "Region", "Faction", "Clan"},
}

# Sugerencias de corrección para relaciones conflictivas
_CONFLICT_SUGGESTION: dict[str, str] = {
    "HAS_FOUGHT": "FOUGHT_AT",
}


def validate_candidate(c: Candidate) -> ValidationResult:
    issues: list[str] = []
    warnings: list[str] = []

    # Campos obligatorios presentes
    if not c.source_id:
        issues.append("source_id ausente")
    if not c.source_kind:
        issues.append("source_kind ausente")
    if not c.workspace:
        issues.append("workspace ausente")

    # Confidence
    if not (0.0 <= c.confidence <= 1.0):
        issues.append(f"confidence fuera de rango: {c.confidence}")

    # Evidence
    if not c.evidence or not c.evidence.strip():
        issues.append("evidence vacía")

    # Timestamps
    for ts_field, ts_val in [("timestamp_start", c.timestamp_start), ("timestamp_end", c.timestamp_end)]:
        if ts_val and not TS_RE.match(ts_val):
            issues.append(f"{ts_field} formato inválido: '{ts_val}'")

    # Validación específica por kind
    if c.kind == "entity":
        if not c.name or not c.name.strip():
            issues.append("name vacío para entidad")
        if c.entity_type and c.entity_type not in ALLOWED_NODE_TYPES:
            issues.append(f"entity_type '{c.entity_type}' no en schema")
            # Clan es válido como alias de Faction/Family
            if c.entity_type == "Clan":
                issues.pop()
                warnings.append("entity_type 'Clan' no en schema; usar 'Faction' o 'Family'")

    elif c.kind == "relation":
        if not c.from_entity:
            issues.append("from_entity ausente en relación")
        if not c.to_entity:
            issues.append("to_entity ausente en relación")
        if not c.relation_type:
            issues.append("relation_type ausente")
        elif c.relation_type not in ALLOWED_RELATION_TYPES:
            issues.append(f"relation_type '{c.relation_type}' no en schema")
        else:
            # Detectar conflictos semánticos
            conflict_types = _ENTITY_RELATION_CONFLICT.get(c.relation_type, set())
            if c.to_type and c.to_type in conflict_types:
                suggestion = _CONFLICT_SUGGESTION.get(c.relation_type, "")
                msg = f"relación '{c.relation_type}' contra tipo '{c.to_type}' semánticamente inválida"
                if suggestion:
                    msg += f"; sugerencia: {suggestion}"
                issues.append(msg)

    # Determinar estado
    if issues:
        valid = "invalid"
    elif warnings:
        valid = "dubious"
    else:
        valid = "valid"

    return ValidationResult(
        candidate_id=c.candidate_id,
        valid=valid,
        issues=issues,
        warnings=warnings,
    )


def validate_candidates(candidates: list[Candidate]) -> list[tuple[Candidate, ValidationResult]]:
    results = []
    for c in candidates:
        vr = validate_candidate(c)
        results.append((c, vr))
    n_valid = sum(1 for _, vr in results if vr.valid == "valid")
    n_dubious = sum(1 for _, vr in results if vr.valid == "dubious")
    n_invalid = sum(1 for _, vr in results if vr.valid == "invalid")
    log.info("Validación: %d válidos, %d dudosos, %d inválidos", n_valid, n_dubious, n_invalid)
    return results


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: valida y guarda validated.json."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "candidates.json"
    if not in_path.exists():
        raise FileNotFoundError(f"candidates.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    candidates = [Candidate.from_dict(d) for d in raw]
    results = validate_candidates(candidates)

    out_records = []
    for c, vr in results:
        out_records.append({
            "candidate": c.to_dict(),
            "validation": vr.to_dict(),
        })

    out_path = in_path.parent / "validated.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out_records, f, ensure_ascii=False, indent=2)

    log.info("validated.json → %s", out_path)
    return out_path

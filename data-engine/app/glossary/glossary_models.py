"""Modelos de datos para el glosario de transcripción.

GlossaryTerm es la representación en memoria de una fila de glossary_terms.
Todos los campos JSON se almacenan como str en SQLite y se convierten
automáticamente a/desde list[str] con los helpers to_dict/from_row.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class GlossaryTerm:
    """Representa un término del glosario con todos sus metadatos.

    Campos JSON (aliases, spoken_forms, error_forms, source_pages) se
    almacenan como list[str] en memoria y se serializan a JSON string
    para SQLite.
    """
    workspace: str
    canonical_term: str
    normalized_term: str
    term_type: str | None = None
    aliases: list[str] = field(default_factory=list)
    spoken_forms: list[str] = field(default_factory=list)
    error_forms: list[str] = field(default_factory=list)
    source_id: str | None = None
    source_kind: str | None = None
    source_document: str | None = None
    source_pages: list[str] = field(default_factory=list)
    confidence: float = 0.5
    frequency: int = 1
    priority: float = 0.0
    edition: str | None = None
    language: str = "es"
    enabled: bool = True
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    # Solo se rellena cuando el término viene de la DB
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace": self.workspace,
            "canonical_term": self.canonical_term,
            "normalized_term": self.normalized_term,
            "term_type": self.term_type,
            "aliases": self.aliases,
            "spoken_forms": self.spoken_forms,
            "error_forms": self.error_forms,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "source_document": self.source_document,
            "source_pages": self.source_pages,
            "confidence": self.confidence,
            "frequency": self.frequency,
            "priority": self.priority,
            "edition": self.edition,
            "language": self.language,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "GlossaryTerm":
        """Construye un GlossaryTerm desde una fila SQLite (dict)."""
        def _json_list(v: Any) -> list[str]:
            if isinstance(v, list):
                return v
            if not v:
                return []
            try:
                result = json.loads(v)
                return result if isinstance(result, list) else []
            except (json.JSONDecodeError, TypeError):
                return []

        return cls(
            id=row.get("id"),
            workspace=row["workspace"],
            canonical_term=row["canonical_term"],
            normalized_term=row["normalized_term"],
            term_type=row.get("term_type"),
            aliases=_json_list(row.get("aliases_json", "[]")),
            spoken_forms=_json_list(row.get("spoken_forms_json", "[]")),
            error_forms=_json_list(row.get("error_forms_json", "[]")),
            source_id=row.get("source_id") or None,
            source_kind=row.get("source_kind"),
            source_document=row.get("source_document"),
            source_pages=_json_list(row.get("source_pages_json", "[]")),
            confidence=float(row.get("confidence", 0.5)),
            frequency=int(row.get("frequency", 1)),
            priority=float(row.get("priority", 0.0)),
            edition=row.get("edition"),
            language=row.get("language", "es"),
            enabled=bool(row.get("enabled", 1)),
            created_at=row.get("created_at", _now_iso()),
            updated_at=row.get("updated_at", _now_iso()),
        )

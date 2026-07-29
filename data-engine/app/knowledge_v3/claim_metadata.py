# -*- coding: utf-8 -*-
"""Frontera tipada para la semantica abierta de ``ClaimProposal.metadata``."""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Mapping

METADATA_BLOCK_VERSION = "1"

NEGATION_KIND_SIMPLE = "SIMPLE"
NEGATION_KINDS = frozenset(
    {"SIMPLE", "NEVER", "CESSATION", "NOT_YET", "SCOPE_AMBIGUOUS"}
)


@dataclass(frozen=True)
class ClaimSemanticMetadata:
    """Campos semanticos que viajan en el bloque abierto del contrato congelado."""

    negation_kind: str = NEGATION_KIND_SIMPLE
    temporal_resolution_required: bool = False
    direction_unresolved: bool = False
    untrusted_origin: bool = False
    metadata_block_version: str = METADATA_BLOCK_VERSION
    #: Estado de frontera: permite distinguir ausencia de un valor presente.
    negation_kind_present: bool = field(default=False, compare=False)
    #: Valor presente pero fuera del vocabulario, conservado para el motor.
    unknown_negation_kind: str = field(default="", compare=False)

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any] | None) -> "ClaimSemanticMetadata":
        raw = dict(metadata or {})
        kind_present = "negation_kind" in raw and raw.get("negation_kind") not in (None, "")
        kind_raw = raw.get("negation_kind")
        kind = str(kind_raw or NEGATION_KIND_SIMPLE).strip().upper()
        unknown_kind = ""
        if kind not in NEGATION_KINDS:
            _warn("negation_kind", kind_raw, NEGATION_KIND_SIMPLE)
            unknown_kind = kind
            kind = NEGATION_KIND_SIMPLE

        def boolean(name: str) -> bool:
            value = raw.get(name, False)
            if isinstance(value, bool):
                return value
            _warn(name, value, False)
            return False

        version_raw = raw.get("metadata_block_version", METADATA_BLOCK_VERSION)
        version = str(version_raw)
        if version != METADATA_BLOCK_VERSION:
            _warn("metadata_block_version", version_raw, METADATA_BLOCK_VERSION)
            version = METADATA_BLOCK_VERSION
        return cls(
            negation_kind=kind,
            temporal_resolution_required=boolean("temporal_resolution_required"),
            direction_unresolved=boolean("direction_unresolved"),
            untrusted_origin=boolean("untrusted_origin"),
            metadata_block_version=version,
            negation_kind_present=kind_present,
            unknown_negation_kind=unknown_kind,
        )

    def to_metadata(self) -> dict[str, Any]:
        """Representacion del mismo bloque abierto, sin cambiar el contrato."""
        out = {
            "metadata_block_version": self.metadata_block_version,
            "temporal_resolution_required": self.temporal_resolution_required,
            "direction_unresolved": self.direction_unresolved,
            "untrusted_origin": self.untrusted_origin,
        }
        if self.negation_kind_present or self.negation_kind != NEGATION_KIND_SIMPLE:
            out["negation_kind"] = self.unknown_negation_kind or self.negation_kind
        return out


def _warn(field: str, value: Any, fallback: Any) -> None:
    warnings.warn(
        f"claim.metadata.{field} desconocido/invalido: {value!r}; se usa {fallback!r}",
        RuntimeWarning,
        stacklevel=3,
    )


__all__ = ["ClaimSemanticMetadata", "METADATA_BLOCK_VERSION"]

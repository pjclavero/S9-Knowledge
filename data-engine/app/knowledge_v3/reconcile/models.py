# -*- coding: utf-8 -*-
"""Modelos internos de resultado y estadisticas."""
from __future__ import annotations

from dataclasses import dataclass

from ..extraction.base import ExtractionOutput


@dataclass(frozen=True)
class ReconcileStats:
    input_mentions: int = 0
    output_mentions: int = 0
    input_claims: int = 0
    output_claims: int = 0
    mention_groups: int = 0
    claim_groups: int = 0
    mentions_merged: int = 0
    claims_merged: int = 0
    preserved_ambiguous: int = 0
    unknown_families: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "input_mentions": self.input_mentions,
            "output_mentions": self.output_mentions,
            "input_claims": self.input_claims,
            "output_claims": self.output_claims,
            "mention_groups": self.mention_groups,
            "claim_groups": self.claim_groups,
            "mentions_merged": self.mentions_merged,
            "claims_merged": self.claims_merged,
            "preserved_ambiguous": self.preserved_ambiguous,
            "unknown_families": self.unknown_families,
            "duration_ms": round(self.duration_ms, 3),
        }


@dataclass(frozen=True)
class ReconcileResult:
    output: ExtractionOutput
    stats: ReconcileStats


__all__ = ["ReconcileResult", "ReconcileStats"]

# -*- coding: utf-8 -*-
"""Registro declarado de familias de independencia."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..contracts.base import V3ContractError, producing_step

REGISTRY_VERSION = "v1"
UNCLASSIFIED_FAMILY = "unclassified"


@dataclass(frozen=True)
class Origin:
    """Origen productor normalizado para conteos y procedencia."""

    step: str
    provider: str
    name: str
    model: str
    family: str

    @property
    def provider_key(self) -> str:
        return "|".join((self.step, self.provider, self.name, self.model))

    def to_dict(self) -> dict:
        out = {
            "step": self.step,
            "provider": self.provider,
            "name": self.name,
            "family": self.family,
        }
        if self.model:
            out["model"] = self.model
        return out


@dataclass(frozen=True)
class FamilyRule:
    """Regla declarada; `model` solo acota cuando se indica explicitamente."""

    step: str
    family: str
    provider: Optional[str] = None
    name: Optional[str] = None
    model: Optional[str] = None

    def matches(self, entry: dict) -> bool:
        if entry.get("step") != self.step:
            return False
        if self.provider is not None and entry.get("provider") != self.provider:
            return False
        if self.name is not None and entry.get("name") != self.name:
            return False
        if self.model is not None and entry.get("model") != self.model:
            return False
        return True


@dataclass(frozen=True)
class IndependenceRegistry:
    """Tabla versionada: no deduce familias a partir del modelo o proveedor."""

    version: str
    rules: tuple[FamilyRule, ...]
    unknown_family: str = UNCLASSIFIED_FAMILY

    def origin_for(self, doc) -> tuple[Origin, bool]:
        """Devuelve el origen declarado y si fue clasificado explicitamente."""
        try:
            entry = producing_step(doc.to_dict())
        except V3ContractError:
            entry = {}
        family = self.unknown_family
        known = False
        for rule in self.rules:
            if rule.matches(entry):
                family = rule.family
                known = True
                break
        return (
            Origin(
                step=str(entry.get("step") or getattr(doc, "produced_by_step", "")),
                provider=str(entry.get("provider") or ""),
                name=str(entry.get("name") or ""),
                model=str(entry.get("model") or ""),
                family=family,
            ),
            known,
        )


DEFAULT_INDEPENDENCE_REGISTRY = IndependenceRegistry(
    version=REGISTRY_VERSION,
    rules=(
        FamilyRule("extract.deterministic", "lexical-rules"),
        FamilyRule("extract.table", "structural-table"),
        FamilyRule("extract.temporal", "temporal-rules"),
        FamilyRule("extract.coreference", "coreference-rules"),
        FamilyRule("extract.semantic", "semantic-prompt-v1.2", name="s9k.extraction.semantic"),
        FamilyRule("extract.semantic", "semantic-prompt-v1.2", name="external.semantic"),
    ),
)


__all__ = [
    "DEFAULT_INDEPENDENCE_REGISTRY",
    "FamilyRule",
    "IndependenceRegistry",
    "Origin",
    "REGISTRY_VERSION",
    "UNCLASSIFIED_FAMILY",
]

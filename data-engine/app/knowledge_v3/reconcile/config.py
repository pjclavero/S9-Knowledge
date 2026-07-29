# -*- coding: utf-8 -*-
"""Configuracion explicita del ProposalReconciler."""
from __future__ import annotations

from dataclasses import dataclass

from .families import DEFAULT_INDEPENDENCE_REGISTRY, IndependenceRegistry

RECONCILER_VERSION = "proposal-reconciler-v1"


@dataclass(frozen=True)
class ReconcilerConfig:
    """Opciones puras y versionadas del reconciliador."""

    version: str = RECONCILER_VERSION
    independence_registry: IndependenceRegistry = DEFAULT_INDEPENDENCE_REGISTRY
    canonical_mention_prefix: str = "mention:reconciled"
    canonical_claim_prefix: str = "claim:reconciled"
    validate_output: bool = True


DEFAULT_RECONCILER_CONFIG = ReconcilerConfig()


__all__ = [
    "DEFAULT_RECONCILER_CONFIG",
    "RECONCILER_VERSION",
    "ReconcilerConfig",
]

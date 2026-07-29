# -*- coding: utf-8 -*-
"""Reconciliacion textual de propuestas V3."""
from __future__ import annotations

from .config import DEFAULT_RECONCILER_CONFIG, ReconcilerConfig
from .families import DEFAULT_INDEPENDENCE_REGISTRY, IndependenceRegistry
from .models import ReconcileResult, ReconcileStats
from .reconciler import ProposalReconciler

__all__ = [
    "DEFAULT_INDEPENDENCE_REGISTRY",
    "DEFAULT_RECONCILER_CONFIG",
    "IndependenceRegistry",
    "ProposalReconciler",
    "ReconcileResult",
    "ReconcileStats",
    "ReconcilerConfig",
]

# -*- coding: utf-8 -*-
"""Adaptadores entre los contratos V3 y las fronteras ya existentes."""
from __future__ import annotations

from .relation_candidate_v1 import (  # noqa: F401
    V3AdapterError,
    claim_to_relation_candidate,
    claim_with_resolutions_to_relation_candidate,
    entity_id_from_resolution,
)

__all__ = [
    "V3AdapterError",
    "claim_to_relation_candidate",
    "claim_with_resolutions_to_relation_candidate",
    "entity_id_from_resolution",
]

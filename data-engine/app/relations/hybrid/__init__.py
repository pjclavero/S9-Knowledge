# -*- coding: utf-8 -*-
"""Motor hibrido por etapas de extraccion de relaciones (PR#95 V4).

Abstracciones puras (`models`), etapas componibles (`stages`) y orquestador con
flags (`engine`). Todo detras de flags; el DEFAULT reproduce la base. NO cambia
el contrato publico de 20 campos de `RelationCandidate`.
"""
from relations.hybrid.models import (
    EvidenceBundle,
    RelationHypothesis,
    SegmentReference,
)

__all__ = ["SegmentReference", "RelationHypothesis", "EvidenceBundle"]

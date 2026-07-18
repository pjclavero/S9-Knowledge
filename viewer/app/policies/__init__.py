"""Motor de política de visibilidad RPG (slice vertical inicial).

Este paquete NO conoce FastAPI ni Neo4j: es lógica pura, determinista y
sin efectos secundarios. Decide, por nodo/relación, si un `ViewerContext`
dado puede verlo. La aplicación real del filtro (provider/query, conteos,
búsquedas, acceso por ID) vive en ``app.authz``.
"""
from __future__ import annotations

from app.policies.models import (
    NARRATOR,
    PLAYER,
    REFERENCE,
    SECRET,
    VisibilityDecision,
    ViewerContext,
)
from app.policies.engine import VisibilityPolicy

__all__ = [
    "ViewerContext",
    "VisibilityDecision",
    "VisibilityPolicy",
    "PLAYER",
    "NARRATOR",
    "SECRET",
    "REFERENCE",
]

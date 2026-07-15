# -*- coding: utf-8 -*-
"""Subsistema de IA externa de S9 Knowledge (Fase A: revisión en modo sombra).

TODA ejecución es shadow_mode=True: los resultados son shadow_recommendation y
NUNCA una decisión productiva. Nada de este paquete escribe en Neo4j ni activa
S9K_ALLOW_REAL_INGEST.
"""
from __future__ import annotations
import os

from external_ai.errors import ShadowModeRequired

PROMPT_VERSION = "1.0"
SCHEMA_VERSION = "1.0"


def require_shadow(shadow: bool) -> None:
    """Aborta si no se pasó --shadow. En Fase A el modo sombra es obligatorio."""
    if not shadow:
        raise ShadowModeRequired(
            "ABORTADO: la integración externa solo está habilitada en modo sombra."
        )


__all__ = ["require_shadow", "PROMPT_VERSION", "SCHEMA_VERSION"]

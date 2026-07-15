# -*- coding: utf-8 -*-
"""Proveedor NVIDIA NIM para el subsistema de IA externa (Fase A).

Especialización de OpenAICompatibleProvider que lee toda su configuración desde
el registro de entorno (external_ai.registry). La API key nunca se almacena como
atributo de instancia.

Modo sombra: nunca escribe en Neo4j; solo produce ModelReviewResponse para el
motor de consenso.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from external_ai import registry
from external_ai.openai_compatible import OpenAICompatibleProvider


class NvidiaNimProvider(OpenAICompatibleProvider):
    """Proveedor NVIDIA NIM (OpenAI-compatible).

    Lee base_url, timeouts, reintentos, modelos y caché desde las variables de
    entorno mediante external_ai.registry. La API key se obtiene por demanda
    llamando a registry.get_api_key() (lanza ConfigError si no está presente).
    """

    provider_name: str = "nvidia"
    capabilities: set = {"candidate_review", "candidate_adjudication"}

    def __init__(self, repo_root: Path) -> None:
        cfg = registry.nvidia_config()
        super().__init__(
            base_url=cfg["base_url"],
            api_key_getter=registry.get_api_key,
            repo_root=Path(repo_root),
            timeout=cfg["timeout_seconds"],
            max_retries=cfg["max_retries"],
            max_concurrency=cfg["max_concurrency"],
            cache_enabled=cfg["cache_enabled"],
        )
        # Guardamos la config (sin key) para los métodos de conveniencia.
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Métodos de conveniencia específicos de NVIDIA NIM
    # ------------------------------------------------------------------

    def available_review_models(self) -> list[str]:
        """Lista de modelos de revisión configurados para este proveedor."""
        return list(registry.nvidia_config()["review_models"])

    def available_adjudicator(self) -> Optional[str]:
        """Modelo adjudicador configurado, o None si no está definido."""
        return registry.nvidia_config()["adjudicator_model"]

# -*- coding: utf-8 -*-
"""Clase base abstracta para proveedores de procesamiento externo (Fase B1).

Contrato independiente de external_ai.base.ExternalAIProvider.
Cada proveedor declara sus capacidades y el dispatcher verifica antes
de intentar ejecutar.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Set

from external_processing.capabilities import Capability
from external_processing.models import ProcessingJob


class ExternalProcessingProvider(ABC):
    """Contrato de un proveedor de procesamiento externo."""

    provider_name: str = "base"
    capabilities: Set[Capability] = set()

    def supports(self, capability: Capability) -> bool:
        """Indica si el proveedor soporta la capacidad solicitada."""
        return capability in self.capabilities

    @abstractmethod
    def execute(self, job: ProcessingJob) -> Dict[str, Any]:
        """Ejecuta un job y devuelve el resultado como dict serializable.

        Lanza ExternalProcessingError (o subclase) en caso de fallo.
        El dispatcher gestiona reintentos y circuit breaker.
        """
        raise NotImplementedError

    def healthcheck(self) -> Dict[str, Any]:
        """Comprueba la disponibilidad del proveedor. No debe lanzar."""
        return {"status": "unknown", "provider": self.provider_name}

    def __repr__(self) -> str:
        caps = [c.value for c in self.capabilities]
        return f"{self.__class__.__name__}(provider={self.provider_name!r}, capabilities={caps})"

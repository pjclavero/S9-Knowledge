# -*- coding: utf-8 -*-
"""Registro de proveedores de procesamiento externo (Fase B1).

Los proveedores se registran por nombre. El dispatcher los busca por nombre
o por capacidad requerida.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from external_processing.capabilities import Capability
from external_processing.provider import ExternalProcessingProvider

_registry: Dict[str, ExternalProcessingProvider] = {}


def register(provider: ExternalProcessingProvider) -> None:
    """Registra una instancia de proveedor."""
    _registry[provider.provider_name] = provider


def get(name: str) -> Optional[ExternalProcessingProvider]:
    """Devuelve el proveedor registrado con ese nombre, o None."""
    return _registry.get(name)


def get_by_capability(capability: Capability) -> List[ExternalProcessingProvider]:
    """Devuelve todos los proveedores que soportan la capacidad indicada."""
    return [p for p in _registry.values() if p.supports(capability)]


def list_providers() -> List[str]:
    """Lista los nombres de todos los proveedores registrados."""
    return list(_registry.keys())


def clear() -> None:
    """Limpia el registro. Solo para tests."""
    _registry.clear()


def default_provider_for_capability(capability: Capability) -> Optional[ExternalProcessingProvider]:
    """Devuelve el primer proveedor disponible para la capacidad, o None."""
    providers = get_by_capability(capability)
    return providers[0] if providers else None

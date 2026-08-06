"""Aplicación de la política de visibilidad (capa de autorización del visor).

- ``context``          : traduce (rol, personaje activo, workspaces) -> ViewerContext.
- ``filtered_provider``: envuelve un GraphProvider y filtra EN LA QUERY
                         (listados, conteos, búsquedas, acceso por ID, relaciones).
- ``scope``          : ámbito (workspace+partida) para material que no viene del
                       GraphProvider (revisión v1/V3, cola de jobs).
- ``visibility_contract``: M5b-0, frontera única entre el contrato canónico
                       `knowledge-visibility/v1` (fuera de `app/`) y el motor.
- ``simulation``       : modo admin "ver como personaje" (solo lectura, auditado).
- ``dependencies``     : dependencias FastAPI (contexto + provider filtrado).

Ninguno de estos módulos ESCRIBE en Neo4j; el provider filtrado sólo delega
lecturas al provider base y descarta lo no visible.

Los símbolos del paquete se resuelven de forma PEREZOSA (PEP 562): importar
``app.authz.scope`` no debe arrastrar el provider filtrado, que a su vez
depende de la configuración del visor y de sus dependencias de terceros.
Sin esto, un consumidor que sólo necesita el ámbito (por ejemplo la suite de
data-engine, que no instala las dependencias del visor) falla al importar.
"""
from __future__ import annotations

from typing import Any

_LAZY = {
    "build_viewer_context": "app.authz.context",
    "PolicyFilteredProvider": "app.authz.filtered_provider",
    "VisibilityScope": "app.authz.scope",
    # M5b-0: frontera unica entre el contrato `knowledge-visibility/v1` y el
    # motor de politica ya probado (docs/v3/51).
    "V3VisibilityPolicyAdapter": "app.authz.visibility_contract",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)

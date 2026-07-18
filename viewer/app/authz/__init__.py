"""Aplicación de la política de visibilidad (capa de autorización del visor).

- ``context``          : traduce (rol, personaje activo, workspaces) -> ViewerContext.
- ``filtered_provider``: envuelve un GraphProvider y filtra EN LA QUERY
                         (listados, conteos, búsquedas, acceso por ID, relaciones).
- ``simulation``       : modo admin "ver como personaje" (solo lectura, auditado).
- ``dependencies``     : dependencias FastAPI (contexto + provider filtrado).

Ninguno de estos módulos ESCRIBE en Neo4j; el provider filtrado sólo delega
lecturas al provider base y descarta lo no visible.
"""
from __future__ import annotations

from app.authz.context import build_viewer_context
from app.authz.filtered_provider import PolicyFilteredProvider

__all__ = ["build_viewer_context", "PolicyFilteredProvider"]

"""test_permissions_e2e.py — E2E de permisos por workspace/personaje (fase 1).

PREPARADOS (skip con motivo). Dependen del modelo de autorización del EQUIPO C
(rutas/authz del viewer) y de la sesión del EQUIPO A. El objetivo cuando A/C
publiquen: comprobar que un operador solo ve/actúa sobre el workspace y el
personaje autorizados, y que conteos/búsqueda llegan filtrados por permiso.

DEPENDENCIAS: D-DEP-1 (sesión, A), D-DEP-5 (permisos + filtrado, C).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

_NEEDS_ABC = "PENDIENTE fase 1: depende de authz por workspace/personaje de A/C"


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-5)")
def test_operator_sees_only_authorized_workspace() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-5)")
def test_view_as_character_filters_visible_entities() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-5)")
def test_counts_and_search_are_permission_filtered() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-1 + D-DEP-5)")
def test_unauthorized_workspace_access_is_denied() -> None:
    raise NotImplementedError

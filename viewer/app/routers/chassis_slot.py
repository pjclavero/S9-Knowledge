"""Fábrica común de los huecos del chasis (ver ``app/chassis.py``).

Monta un hueco VACÍO pero completo: ruta con nombre, guarda de autorización
reutilizada del visor, plantilla que extiende `base.html` y estados de vacío y
de error explícitos. Cero funcionalidad: no consulta Neo4j, no lee ficheros, no
escribe nada.

El carril dueño de cada hueco sustituye el cuerpo de su handler manteniendo el
contrato (prefijo, nombre de ruta, rol, plantilla y contexto mínimo).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.models import User
from app.chassis import FeatureSlot
# La guarda de rol ya existe y ya está probada. Reutilizarla es el punto:
# un chasis con su propia guarda sería una segunda autorización.
from app.routers.readonly import html_role_guard

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

#: Claves mínimas que TODA pantalla de un hueco debe pasar a su plantilla.
#: `auth_user` no es opcional: `base.html` pinta la barra superior con ese
#: nombre exacto, y pasarle otro (`user`, `admin`, ...) deja la barra en blanco
#: sin que falle nada. Ese error ya se cometió en este repo.
SLOT_CONTEXT_KEYS = frozenset({"auth_user", "slot", "items", "error"})


def slot_context(
    slot: FeatureSlot,
    user,
    items: Optional[list] = None,
    error: Optional[str] = None,
) -> dict:
    """Contexto mínimo de una pantalla de hueco."""
    return {
        "auth_user": user if isinstance(user, User) else None,
        "slot": slot,
        "items": list(items or []),
        "error": error,
    }


def build_slot_router(slot: FeatureSlot) -> APIRouter:
    """Router montable para un hueco: una pantalla, vacía y autorizada."""
    router = APIRouter(prefix=slot.prefix, tags=[f"chassis-{slot.key.lower()}"])

    @router.get("", response_class=HTMLResponse, name=slot.route_name)
    @router.get("/", response_class=HTMLResponse, name=slot.route_name)
    def slot_screen(request: Request, user=Depends(html_role_guard(slot.role))):
        # `html_role_guard` devuelve la redirección a /login para el anónimo y
        # levanta 403 si el rol no llega. Aquí sólo hay que respetar su salida.
        if isinstance(user, RedirectResponse):
            return user
        return templates.TemplateResponse(
            request, slot.template, slot_context(slot, user, items=[], error=None)
        )

    return router

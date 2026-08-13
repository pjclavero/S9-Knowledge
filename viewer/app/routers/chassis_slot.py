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

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Las guardas ya existen y ya están probadas. Reutilizarlas es el punto: un
# chasis con su propia guarda sería una segunda autorización.
from app.auth.dependencies import require_admin
from app.auth.models import User
from app.chassis import FeatureSlot, slot_enabled
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


def slot_guard(slot: FeatureSlot):
    """Guarda de un hueco. Siempre una guarda YA EXISTENTE, nunca una nueva.

    Un hueco `admin` usa ``require_admin``, la misma que `/admin/users` y
    `/admin/partidas`. Con ``html_role_guard`` el panel de administración
    quedaba por DEBAJO de sus pares: esa guarda es no-op cuando
    ``S9K_AUTH_ENABLED`` está ausente, así que servía 200 a un anónimo mientras
    el resto del área de administración devolvía 302 a /login. Medido, no
    supuesto. Los huecos por debajo de `admin` conservan ``html_role_guard``,
    que es la postura de sus pares (`/sources`, `/reviews`).
    """
    if slot.role == "admin":
        return require_admin
    return html_role_guard(slot.role)


def build_slot_router(slot: FeatureSlot) -> APIRouter:
    """Router montable para un hueco: una pantalla, vacía, apagable y autorizada."""
    router = APIRouter(prefix=slot.prefix, tags=[f"chassis-{slot.key.lower()}"])

    @router.get("", response_class=HTMLResponse, name=slot.route_name)
    @router.get("/", response_class=HTMLResponse, name=slot.route_name)
    def slot_screen(request: Request, user=Depends(slot_guard(slot))):
        # La guarda devuelve la redirección a /login para el anónimo y levanta
        # 403 si el rol no llega. `Depends` NO deniega por sí solo: devolver su
        # salida es parte de la denegación.
        if isinstance(user, RedirectResponse):
            return user
        # Interruptor del hueco: se comprueba DESPUÉS de autorizar, para que un
        # anónimo reciba la MISMA respuesta esté el panel encendido o apagado y
        # no pueda enumerar cuáles lo están (`test_disabled_slots_are_not_
        # enumerable_by_an_anonymous`). Ausente o con valor raro, el panel no
        # está: 404, igual que una ruta inexistente. El cuerpo no nombra la
        # variable de entorno: quien la necesita ya la tiene en docs/69 y en
        # `.env.example`, y quien no, tampoco necesita saber cómo se llama.
        if not slot_enabled(slot):
            raise HTTPException(
                status_code=404,
                detail=(f"El panel {slot.title} está apagado"),
            )
        return templates.TemplateResponse(
            request, slot.template, slot_context(slot, user, items=[], error=None)
        )

    return router

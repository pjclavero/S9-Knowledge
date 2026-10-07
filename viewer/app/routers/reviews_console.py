"""Panel de revisión v1 (Equipo B) — consola de revisión del visor.

Rutas (reviewer+):
  GET  /review-console                         → bandeja de fuentes (summaries v1)
  GET  /review-console/source/{source_id}      → candidatos + preview del plan
  POST /review-console/source/{source_id}/decide → registra review-decision v1 +
                                                    review-audit-event v1 (control
                                                    optimista). NUNCA escribe Neo4j.

El panel produce ÚNICAMENTE review-decision v1 y review-audit-event v1 en un
almacén LOCAL de laboratorio. No aplica el ingest-plan, no autoriza ingesta y no
modifica el review original.

QUÉ ES Y QUÉ NO ES ESTE PANEL — PR-1 (USABLE-V1)
-------------------------------------------------
Esta consola es de LABORATORIO: revisa ``candidatos de entidad`` servidos
desde fixtures FIJAS del repo (``app.services.review_console_fixtures``,
``src_demo_01``/``src_demo_02``), no el motor real. Eso no es un defecto de
este módulo: lo decide ``docs/v3/25-interfaz-de-revision.md`` por OBJETO —
``/review-console`` revisa candidatos de entidad, ``/v3/review`` revisa
``claims`` del motor, y cada objeto tiene su canónica. La superficie
OPERATIVA para revisar claims reales es ``/v3/review``.

Por eso, y por decisión del operador, esta consola SIGUE montada (el
``include_router`` de ``app/main.py`` no es condicional: el censo de rutas
debe seguir viendo las tres) pero NO SE SIRVE en producción por defecto:
responde 404 de fábrica. Sin el interruptor, un revisor que teclee la URL y
decida sobre ``src_demo_01`` creyendo revisar de verdad sería una falsa
confirmación con efecto de escritura (``POST …/decide`` vive aquí). No se
convierte en consola de producto, no se conecta al motor real y no se enlaza
en ``NAV``; sencillamente no responde salvo que alguien la encienda a
propósito para laboratorio.

INTERRUPTOR: ``S9K_REVIEW_CONSOLE_ENABLED``, con la MISMA autoridad y la MISMA
semántica que ``app.routers.resultado`` ya aplica a ``/panel/resultado``
(``FLAG_ON_VALUES`` del chasis, leído en cada petición vía
``app.config.effective_env_value``: fallo cerrado, se sirve si y sólo si vale
exactamente ``true`` o ``1``). No es un hueco de ``app.chassis.FEATURE_SLOTS``
—por el mismo motivo que ``resultado.py`` tampoco lo es: tiene su propio
prefijo, su propia guarda YA EXISTENTE (``_guard``, reviewer+) y ahora su
propio interruptor, igual que esa pantalla. ``WRITE_CAPABILITIES`` tampoco
aplica: esa tabla sólo declara escrituras DENTRO del espacio de URL de los
cuatro huecos C/B/F/G; este prefijo no pertenece a ninguno, exactamente como
hoy no pertenece ``/panel/resultado``.

Con la bandera apagada (estado de fábrica): las TRES rutas, incluida
``POST …/decide``, dan 404 DESPUÉS de la puerta de rol (ver ``_exigir_encendido``).
Medido: para quien está por debajo de ``reviewer`` el estado del interruptor
es invisible -- la respuesta es IDÉNTICA con la bandera encendida o apagada
(anónimo: 302 a ``/login`` en ambos casos; ``viewer``: 403 en ambos casos),
porque ``_guard`` corta antes de llegar al interruptor. Para ``reviewer``/
``admin`` -- quien sí podría decidir -- apagada da 404, el mismo código que
una ruta inexistente, aunque por una razón distinta (hay guardián estático
que lo emite, no ausencia de ruta). No hay afirmación de que un 404 por
bandera sea indistinguible de "no existe" para todo rol, ni valor de
seguridad en ocultar la EXISTENCIA de la ruta (el repo es público y, apagada,
la ruta es inerte): la propiedad que el código sostiene es sólo que el
interruptor no se revela a quien no tiene ya rol suficiente para decidir.
Con la bandera encendida: sigue funcionando como hoy, para quien la quiera
como laboratorio.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import chassis
from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.services import review_console as rc

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/review-console", tags=["review-console"])

_RANK = {"admin": 3, "reviewer": 2, "viewer": 1}

#: Interruptor de esta consola de laboratorio. Apagado por defecto, que es lo
#: correcto para producción. Misma semántica que `app.routers.resultado`.
FLAG_ENV = "S9K_REVIEW_CONSOLE_ENABLED"

#: Cuerpo único del 404 cuando la bandera está apagada, DESPUÉS de la puerta
#: de rol: para reviewer+ el apagado se confunde con "no existe"; no pretende
#: ocultar la existencia de la ruta a nadie por debajo de reviewer, que ya
#: recibe la misma respuesta (302/403) tenga el interruptor el valor que
#: tenga, sin llegar a ver este cuerpo.
APAGADA = "No encontrado"


def _encendido() -> bool:
    """¿Se sirve esta consola en este despliegue? Fallo cerrado, se lee siempre.

    Se consulta el entorno en CADA petición a propósito: un flag cacheado al
    importar convierte "apagar la pantalla" en "reiniciar el proceso". El
    valor se resuelve con `app.config.effective_env_value` — la misma
    autoridad única que usa `chassis.slot_enabled` para sus cuatro huecos y
    que usa `app.routers.resultado` para `/panel/resultado` — y los valores
    que ENCIENDEN se importan de `chassis.FLAG_ON_VALUES`, no se reescriben
    aquí: dos definiciones de "encendido" acaban divergiendo.
    """
    from app.config import effective_env_value

    raw = effective_env_value(FLAG_ENV)
    if raw is None:
        return False
    valores = getattr(chassis, "FLAG_ON_VALUES", frozenset())
    return raw.strip().lower() in valores


def _exigir_encendido() -> None:
    """El interruptor, DESPUÉS de la puerta de rol.

    El orden no es cosmético: si el interruptor se evaluara antes, un anónimo
    podría averiguar si la consola está encendida comparando 404 contra 302.
    """
    if not _encendido():
        raise HTTPException(status_code=404, detail=APAGADA)


# ---------------------------------------------------------------------------
# Guardias (reviewer+); no tocan el middleware global de permisos (Equipo C)
# ---------------------------------------------------------------------------
def _guard(request: Request):
    """reviewer+: público con auth off; 302 /login anónimo; 403 rol insuficiente."""
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    if _RANK.get(getattr(user, "role", ""), 0) < _RANK["reviewer"]:
        raise HTTPException(status_code=403, detail="Se requiere rol reviewer o admin.")
    return user


def _reviewer_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is not None:
        return getattr(user, "username", None) or getattr(user, "display_name", None) or "reviewer"
    return "reviewer-local"


def _session_id(request: Request) -> int:
    session = getattr(request.state, "session", None)
    return session.id if session is not None else 0


def _csrf_token(request: Request) -> str:
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(_session_id(request), raw, secret=cfg.S9K_CSRF_SECRET)


def _check_csrf(request: Request, token: str) -> bool:
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return True  # auth off: sin sesión ni CSRF (paridad con el resto del visor)
    raw = getattr(request.state, "csrf_raw", "")
    return validate_csrf(token, _session_id(request), raw, secret=cfg.S9K_CSRF_SECRET)


# ---------------------------------------------------------------------------
# GET bandeja
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def inbox(request: Request, scope: VisibilityScope = Depends(get_visibility_scope)):
    guard = _guard(request)
    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _exigir_encendido()
    # Mismo mecanismo de política que el resto del visor: el ámbito de la
    # petición (partida activa + capa juego) decide qué se entrega.
    summaries = rc.list_source_summaries(scope=scope)
    return templates.TemplateResponse(
        request, "reviews_console.html",
        {"summaries": summaries, "auth_user": guard, "csrf_token": _csrf_token(request)},
    )


# ---------------------------------------------------------------------------
# GET detalle de fuente: candidatos + preview del plan
# ---------------------------------------------------------------------------
@router.get("/source/{source_id}", response_class=HTMLResponse)
def source_detail(request: Request, source_id: str, stale: int = 0,
                  scope: VisibilityScope = Depends(get_visibility_scope)):
    guard = _guard(request)
    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _exigir_encendido()
    # Fuera de ámbito -> 404, indistinguible de inexistente (mismo contrato que
    # PolicyFilteredProvider.entity: no se revela la existencia de material
    # de otra partida).
    summary = rc.get_source_summary(source_id, scope=scope)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")
    candidates = [rc.candidate_view(c) for c in rc.list_candidates(source_id, scope=scope)]
    preview = rc.plan_preview(source_id, scope=scope)
    return templates.TemplateResponse(
        request, "reviews_console_source.html",
        {
            "summary": summary, "source_id": source_id, "candidates": candidates,
            "plan_preview": preview, "actions": sorted(rc.VALID_ACTIONS),
            "stale_warning": bool(stale), "auth_user": guard,
            "csrf_token": _csrf_token(request),
        },
    )


# ---------------------------------------------------------------------------
# POST decisión
# ---------------------------------------------------------------------------
@router.post("/source/{source_id}/decide")
async def decide(
    request: Request,
    source_id: str,
    candidate_id: str = Form(...),
    action: str = Form(...),
    expected_candidate_hash: str = Form(...),
    reason_code: str = Form(""),
    comment: str = Form(""),
    after_canonical_name: str = Form(""),
    target_existing_id: str = Form(""),
    csrf_token: str = Form(""),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    guard = _guard(request)
    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _exigir_encendido()
    if not _check_csrf(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF inválido")
    if action not in rc.VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"acción no válida: {action}")

    after = {"canonical_name": after_canonical_name} if after_canonical_name else None
    try:
        result = rc.submit_decision(
            source_id, candidate_id, action, _reviewer_id(request),
            expected_candidate_hash={"algorithm": "sha256", "value": expected_candidate_hash},
            reason_code=reason_code or None, comment=comment or None,
            after=after, target_existing_id=target_existing_id or None,
            request_id=getattr(request.state, "request_id", None),
            scope=scope,
        )
    except rc.ReviewConsoleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Control optimista: si es obsoleta, volver al detalle con aviso.
    if result.stale:
        return RedirectResponse(url=f"/review-console/source/{source_id}?stale=1",
                                status_code=303)
    return RedirectResponse(url=f"/review-console/source/{source_id}", status_code=303)

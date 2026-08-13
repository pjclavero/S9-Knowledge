"""Hueco C del chasis — Review Console, SOLO LECTURA.

FRONTERA DURA: aquí no hay ningún método que no sea GET. Esta pantalla
inspecciona la cola de revisión V3; no aprueba, no rechaza, no corrige y no
escribe. Las decisiones siguen viviendo en ``/v3/review``, que es el único
sitio que toca el ledger. La ausencia de escritura se comprueba por
ENUMERACIÓN de métodos montados, no se promete en prosa.

MONTAJE
-------
Se respeta el contrato publicado del chasis (``app/chassis.py``, docs/69):
prefijo ``/panel/review``, ruta raíz ``chassis_review``, rol ``reviewer``,
plantilla ``chassis/review.html``. La guarda (``slot_guard``), el interruptor
(``slot_enabled``) y el contexto mínimo de plantilla (``slot_context``) se
importan de ``chassis_slot``: no se reescribe ninguno. Lo que este módulo sí
declara es su propio ``APIRouter``, porque el hueco añade una ficha de detalle
que ``build_slot_router`` no contempla.

AUTORIZACIÓN
------------
Ni una regla nueva. La puerta es ``slot_guard(SLOT)`` —la misma que sirve el
hueco vacío— y el ámbito de datos es ``get_visibility_scope``, el mismo que usa
la cola en ``app/routers/v3_review.py``. No hay aquí vocabulario paralelo de
permisos ni ninguna comprobación propia de rol.

Con ``S9K_AUTH_ENABLED`` desactivado no hay principal, así que el contexto es
anónimo de mínimo privilegio: la consola ENTRA y muestra lo que la capa juego
permite, y NADA de ninguna partida. Eso no es un defecto que arreglar; es el
resultado del P0 de autoridad (docs/75). Un test lo fija expresamente para que
revertirlo se ponga rojo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, slot_enabled
from app.routers.chassis_slot import slot_context, slot_guard
from app.services import review_console_v2 as console
from app.services.v3_review import ReviewError, ReviewService

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SLOT = next(s for s in FEATURE_SLOTS if s.key == "C")

#: Plantilla de la ficha. La de la lista es la del contrato (``SLOT.template``).
ITEM_TEMPLATE = "chassis/review_item.html"

#: Nombre de la ruta de detalle. NO entra en ``NAV``: es una ficha a la que se
#: llega desde la lista, no una entrada de menú.
ITEM_ROUTE_NAME = "chassis_review_item"

#: Techo de página. El mismo que el hueco vacío no tenía que declarar; aquí sí,
#: porque una página sin techo es una petición que puede materializar la cola
#: entera en memoria.
MAX_PAGE_SIZE = 200

#: El prefijo y las etiquetas salen del CONTRATO, no de una cadena escrita aquí.
#: Todo lo demás que el hueco vacío aportaba —la guarda, el interruptor y el
#: contexto mínimo de plantilla— se reutiliza importado de `chassis_slot`, que
#: es donde vive. Lo único que no se reutiliza es su `build_slot_router`,
#: porque este hueco declara además una ruta de detalle: construir el router
#: aquí es más honesto que fabricarlo y vaciarlo.
router = APIRouter(prefix=SLOT.prefix, tags=[f"chassis-{SLOT.key.lower()}"])


def _service() -> ReviewService:
    return ReviewService()


def _authorize(request: Request, user):
    """Puerta + interruptor, EN ESE ORDEN, igual que el hueco vacío.

    El orden no es cosmético: si el interruptor se evaluara antes, un anónimo
    podría enumerar qué paneles están encendidos comparando 404 contra 302.
    """
    if isinstance(user, (RedirectResponse, HTMLResponse)):
        return user
    if not slot_enabled(SLOT):
        raise HTTPException(status_code=404, detail=f"El panel {SLOT.title} está apagado")
    return None


def _spec(**kwargs) -> console.FilterSpec:
    try:
        return console.parse_filters(**kwargs)
    except console.ReviewConsoleV2Error as exc:
        # El mensaje es el del validador: nombra el parámetro, nunca una ruta
        # de fichero ni una traza.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load(workspace: Optional[str], scope: VisibilityScope):
    """Cola visible del workspace elegido, ya acotada por ámbito aguas arriba.

    El acotado lo hace ``ReviewService`` con el ``scope`` recibido. Este módulo
    no vuelve a filtrar por visibilidad: filtrar dos veces en dos sitios es
    cómo acaban discrepando.
    """
    service = _service()
    workspaces = service.workspaces(scope=scope)
    selected = workspace or (workspaces[0] if len(workspaces) == 1 else None)
    if selected and selected not in workspaces:
        # Workspace inexistente y workspace fuera de ámbito dan el MISMO 404:
        # distinguirlos convertiría la pantalla en un enumerador.
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    if not selected:
        return workspaces, None, []
    return workspaces, selected, service.queue(selected, include_decided=True, scope=scope).items


def _context(request, user, **extra) -> dict:
    """Contexto de plantilla: el mínimo del chasis + lo propio del panel.

    Se construye sobre ``slot_context`` para no volver a inventar las claves
    que ``base.html`` espera (``auth_user`` en particular: pasarle otro nombre
    deja la barra superior en blanco sin que falle nada, y ese error ya se
    cometió en este repo).
    """
    ctx = slot_context(SLOT, user, items=extra.pop("items", None), error=extra.pop("error", None))
    ctx.update(extra)
    return ctx


@router.get("", response_class=HTMLResponse, name=SLOT.route_name)
@router.get("/", response_class=HTMLResponse, name=SLOT.route_name)
def chassis_review(
    request: Request,
    workspace: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    reason_code: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    extractor: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    disagreements_only: bool = Query(default=False),
    low_confidence_only: bool = Query(default=False),
    low_confidence_threshold: Optional[float] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None),
    max_confidence: Optional[float] = Query(default=None),
    include_decided: bool = Query(default=False),
    sort: str = Query(default="priority"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=console.DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user=Depends(slot_guard(SLOT)),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    denegado = _authorize(request, user)
    if denegado is not None:
        return denegado
    if sort not in console.SORTS:
        raise HTTPException(status_code=400, detail="Orden no soportado")
    spec = _spec(
        decision=decision, reason_code=reason_code, provider=provider, extractor=extractor,
        query=q, disagreements_only=disagreements_only, low_confidence_only=low_confidence_only,
        low_confidence_threshold=low_confidence_threshold, min_confidence=min_confidence,
        max_confidence=max_confidence, include_decided=include_decided,
    )
    try:
        workspaces, selected, items = _load(workspace, scope)
    except ReviewError as exc:
        # Paquete de propuestas ilegible: se dice QUÉ pasa y nada más. Ni la
        # ruta del paquete, ni la traza, ni el mensaje de la excepción (que
        # puede contener una ruta): sólo el nombre del tipo.
        return templates.TemplateResponse(
            request, SLOT.template,
            _context(
                request, user,
                error="No se pudo leer el paquete de propuestas: revisa la exportación del motor.",
                error_detail=type(exc).__name__,
                workspaces=[], workspace=None, view=None, spec=spec, sort=sort,
                page_sizes=console.PAGE_SIZES, sorts=tuple(console.SORTS),
            ),
            status_code=503,
        )
    # build_view FILTRA, ordena y SÓLO ENTONCES pagina. Los contadores salen
    # del conjunto filtrado, no de la página.
    view = console.build_view(items, spec, sort=sort, page=page, page_size=page_size)
    return templates.TemplateResponse(
        request, SLOT.template,
        _context(
            request, user,
            items=view.page.rows,
            workspaces=workspaces, workspace=selected, view=view, spec=spec, sort=sort,
            page_sizes=console.PAGE_SIZES, sorts=tuple(console.SORTS),
        ),
    )


@router.get("/item/{proposal_id}", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)
def chassis_review_item(
    request: Request,
    proposal_id: str,
    workspace: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    reason_code: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    extractor: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    disagreements_only: bool = Query(default=False),
    low_confidence_only: bool = Query(default=False),
    low_confidence_threshold: Optional[float] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None),
    max_confidence: Optional[float] = Query(default=None),
    include_decided: bool = Query(default=True),
    sort: str = Query(default="priority"),
    user=Depends(slot_guard(SLOT)),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    """Ficha de UNA propuesta, con anterior/siguiente dentro del orden filtrado.

    La ficha se busca en el MISMO conjunto filtrado que produjo la lista, y por
    eso el detalle es siempre el de la fila que se abrió: no se vuelve a
    consultar por ID por un camino distinto, que es como lista y detalle acaban
    enseñando cosas diferentes.
    """
    denegado = _authorize(request, user)
    if denegado is not None:
        return denegado
    if sort not in console.SORTS:
        raise HTTPException(status_code=400, detail="Orden no soportado")
    spec = _spec(
        decision=decision, reason_code=reason_code, provider=provider, extractor=extractor,
        query=q, disagreements_only=disagreements_only, low_confidence_only=low_confidence_only,
        low_confidence_threshold=low_confidence_threshold, min_confidence=min_confidence,
        max_confidence=max_confidence, include_decided=include_decided,
    )
    try:
        workspaces, selected, items = _load(workspace, scope)
    except ReviewError as exc:
        return templates.TemplateResponse(
            request, SLOT.template,
            _context(
                request, user,
                error="No se pudo leer el paquete de propuestas: revisa la exportación del motor.",
                error_detail=type(exc).__name__,
                workspaces=[], workspace=None, view=None, spec=spec, sort=sort,
                page_sizes=console.PAGE_SIZES, sorts=tuple(console.SORTS),
            ),
            status_code=503,
        )
    view = console.build_view(items, spec, sort=sort, page=1, page_size=max(1, len(items)))
    previous, current, following, position = console.neighbours(view.rows_all, proposal_id)
    if current is None:
        # INEXISTENTE, FUERA DE ÁMBITO o EXCLUIDA POR FILTRO: el mismo 404, con
        # el mismo cuerpo. Un 403 aquí diría "existe pero no es tuya", que es
        # justo el dato que no se entrega.
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    return templates.TemplateResponse(
        request, ITEM_TEMPLATE,
        _context(
            request, user,
            items=[current],
            workspaces=workspaces, workspace=selected, row=current,
            explanation=console.review_explanation(current),
            previous=previous, next=following, position=position,
            total=view.filtered_total, spec=spec, sort=sort,
        ),
    )

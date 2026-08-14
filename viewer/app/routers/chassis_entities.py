"""Hueco G del chasis — Entities, SOLO LECTURA.

FRONTERA DURA: aquí no hay ningún método que no sea GET. Este panel lista y
muestra entidades que el espectador YA PUEDE ver; no edita, no fusiona, no
renombra y no borra. Ningún efecto lateral, tampoco desde un GET: todo lo que
este módulo hace con el grafo son las lecturas del ``GraphProvider``. La
ausencia de escritura no se promete en prosa: se comprueba por ENUMERACIÓN del
espacio de URL del panel (`test_ninguna_ruta_del_espacio_del_panel_acepta_
escritura`) y por un proveedor espía que registra cada método invocado.

MONTAJE
-------
Se respeta el contrato publicado del chasis (``app/chassis.py``, docs/69):
prefijo ``/panel/entities``, ruta raíz ``chassis_entities``, rol ``viewer``,
plantilla ``chassis/entities.html``. La guarda (``slot_guard``), el interruptor
(``slot_enabled``) y el contexto mínimo de plantilla (``slot_context``) se
importan de ``chassis_slot``: no se reescribe ninguno. Este módulo declara su
propio ``APIRouter`` porque añade una ficha de detalle que ``build_slot_router``
no contempla, exactamente como el hueco C.

AUTORIZACIÓN
------------
Ni una regla nueva. La puerta de ROL es ``slot_guard(SLOT)`` —la misma que
sirve el hueco vacío— y el filtro de CONTENIDO es ``get_filtered_provider``, el
mismo que usan ``/entities`` y ``/api/entities``. Aquí no se compara ningún rol,
no existe ``admin_full`` ni ninguna tabla de rangos, y no se introduce
vocabulario paralelo: ``visibility``, ``known_by``, workspace, partida y tope de
sesión los evalúa ``PolicyFilteredProvider`` aguas arriba y este módulo NO
vuelve a filtrar. Filtrar dos veces en dos sitios es como acaban discrepando.

**Este hueco tiene el rol MÁS BAJO de los cuatro** (`viewer`), así que es el de
mayor superficie de exposición. Dos consecuencias, ambas medidas:

1. Con ``S9K_AUTH_ENABLED`` desactivado no hay principal, luego el contexto es
   ANÓNIMO SIN PERMISOS (docs/75). Lo que un anónimo ve entonces está medido
   celda a celda en la tabla de `docs/77 §3`: **el lore de capa juego con
   visibilidad `player` SÍ es visible, y su ficha responde 200 con el texto
   completo**; todo lo demás (partida, secreto, narrador, referencia, workspace
   ajeno, dato malformado) no. Es la política heredada aplicada de forma
   consistente, no una vía reabierta aquí, y un panel vacío en ese contexto es
   CORRECTO. Se fija con tests bidireccionales para que reabrir el
   comportamiento permisivo se ponga rojo.
2. Un recurso no autorizado es INDISTINGUIBLE de uno inexistente:
   ``PolicyFilteredProvider.entity`` devuelve ``None`` en ambos casos y aquí se
   traduce al MISMO 404, con el mismo cuerpo. Un 403 diría "existe pero no es
   tuya", que es justo el dato que no se entrega.

CONTADORES
----------
Se publican DESPUÉS de la autorización y son propiedad del conjunto
AUTORIZADO: salen del mismo ``provider`` filtrado que produce las filas
(``list_entities`` filtra por política y sólo entonces pagina, así que su
``total`` ya es post-política). Nunca se consulta el proveedor base. Y la
AUSENCIA de un contador no se pinta como cero: si el proveedor falla, la
pantalla entra en estado de error y NO publica ninguna cifra (docs/73).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.authz.dependencies import get_filtered_provider
from app.chassis import FEATURE_SLOTS, slot_enabled
from app.config import get_settings
from app.providers.base import GraphProvider
from app.routers.chassis_slot import slot_context, slot_guard
# Validación y normalización de los parámetros de listado, IMPORTADA de la
# pantalla de solo lectura que ya existe en vez de reescrita: el tope de página,
# la longitud máxima de `q` y la lista blanca de ordenaciones tienen que ser los
# mismos que los de `/entities`. Una segunda copia sería una segunda política de
# recorte capaz de divergir en silencio.
from app.routers.readonly import _validate_query_params as validar_listado
from app.serializers import serialize_edge, serialize_node

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SLOT = next(s for s in FEATURE_SLOTS if s.key == "G")

#: Plantilla de la ficha. La de la lista es la del contrato (``SLOT.template``).
ITEM_TEMPLATE = "chassis/entities_item.html"

#: Nombre de la ruta de detalle. NO entra en ``NAV``: es una ficha a la que se
#: llega desde la lista, no una entrada de menú.
ITEM_ROUTE_NAME = "chassis_entities_item"

#: El prefijo y las etiquetas salen del CONTRATO, no de una cadena escrita aquí.
router = APIRouter(prefix=SLOT.prefix, tags=[f"chassis-{SLOT.key.lower()}"])


def _authorize(user):
    """Puerta + interruptor, EN ESE ORDEN, igual que el hueco vacío.

    El orden no es cosmético: si el interruptor se evaluara antes, un anónimo
    podría enumerar qué paneles están encendidos comparando 404 contra 302.
    """
    if isinstance(user, (RedirectResponse, HTMLResponse)):
        return user
    if not slot_enabled(SLOT):
        raise HTTPException(status_code=404, detail=f"El panel {SLOT.title} está apagado")
    return None


#: Cuerpo ÚNICO del 404 de la ficha. Se nombra una sola vez a propósito: la
#: indistinguibilidad entre "no existe" y "no es tuya" se rompe el día que
#: alguien escribe dos mensajes parecidos en dos ramas distintas.
FICHA_NO_ENCONTRADA = "Entidad no encontrada"


def _context(request, user, **extra) -> dict:
    """Contexto de plantilla: el mínimo del chasis + lo propio del panel.

    Se construye sobre ``slot_context`` para no volver a inventar las claves que
    ``base.html`` espera (``auth_user`` en particular: pasarle otro nombre deja
    la barra superior en blanco sin que falle nada, y ese error ya se cometió en
    este repo).
    """
    ctx = slot_context(SLOT, user, items=extra.pop("items", None), error=extra.pop("error", None))
    ctx.update(extra)
    return ctx


def _error(request, user, exc: Exception, **extra):
    """Estado de error: el motivo, y del fallo sólo el NOMBRE DEL TIPO.

    Nunca ``str(exc)``: el mensaje de una excepción de proveedor puede traer la
    URI de Neo4j, una ruta de fichero o una consulta. Y SIN contadores: una
    pantalla que no pudo leer no publica un `0`, porque ausencia no es cero.
    """
    return templates.TemplateResponse(
        request, SLOT.template,
        _context(
            request, user,
            error="No se pudieron leer las entidades: la fuente de datos no respondió.",
            error_detail=type(exc).__name__,
            listado=None, **extra,
        ),
        status_code=503,
    )


@router.get("", response_class=HTMLResponse, name=SLOT.route_name)
@router.get("/", response_class=HTMLResponse, name=SLOT.route_name)
def chassis_entities(
    request: Request,
    workspace: Optional[str] = Query(default=None),
    q: str = Query(default=""),
    entity_type: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    sort: str = Query(default="canonical_name"),
    order: str = Query(default="asc"),
    limit: Optional[int] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    user=Depends(slot_guard(SLOT)),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    denegado = _authorize(user)
    if denegado is not None:
        return denegado

    settings = get_settings()
    if limit is None:
        limit = settings.S9K_VIEWER_DEFAULT_PAGE_SIZE
    q, limit, offset, sort, order = validar_listado(q, limit, offset, sort, order, settings)
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE

    try:
        # UNA sola fuente: el proveedor FILTRADO. `list_entities` aplica la
        # política sobre el conjunto entero y sólo entonces pagina, así que
        # `total` ya es "cuántas entidades AUTORIZADAS hay", nunca "cuántas hay
        # en la base".
        items, total = provider.list_entities(
            ws, q=q, entity_type=entity_type, review_status=review_status,
            min_confidence=min_confidence, sort=sort, order=order,
            limit=limit, offset=offset,
        )
        # Total del ámbito SIN filtros de presentación, para poder decir
        # "N de M": también post-política, por el mismo camino. Se pide con
        # `limit=1` porque sólo interesa la cifra, no las filas.
        _, autorizadas = provider.list_entities(ws, limit=1, offset=0)
        tipos = provider.entity_types(ws)
    except Exception as exc:  # noqa: BLE001 - el tipo se publica, el mensaje no
        return _error(request, user, exc, workspace=ws)

    filas = [serialize_node(n) for n in items]
    listado = {
        "limit": limit,
        "offset": offset,
        "total": total,
        "autorizadas": autorizadas,
        "mostradas": len(filas),
        "has_next": offset + limit < total,
        "has_previous": offset > 0,
        "primera": (offset + 1) if filas else 0,
        "ultima": offset + len(filas),
    }
    return templates.TemplateResponse(
        request, SLOT.template,
        _context(
            request, user,
            items=filas,
            workspace=ws, q=q, entity_type=entity_type or "", review_status=review_status or "",
            min_confidence=min_confidence, sort=sort, order=order,
            tipos=tipos, listado=listado,
        ),
    )


@router.get("/item/{entity_id}", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)
def chassis_entities_item(
    request: Request,
    entity_id: str,
    user=Depends(slot_guard(SLOT)),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    """Ficha de UNA entidad y sus relaciones VISIBLES.

    El proveedor filtrado devuelve ``None`` tanto para una entidad inexistente
    como para una existente pero no visible, y las dos acaban en el MISMO 404
    con el MISMO cuerpo. Las relaciones se piden a ``relations_for_entity``, que
    ya exige que el nodo propio y el del otro extremo sean visibles: aquí no se
    recorta nada por segunda vez.
    """
    denegado = _authorize(user)
    if denegado is not None:
        return denegado

    try:
        node = provider.entity(entity_id)
    except Exception as exc:  # noqa: BLE001
        return _error(request, user, exc)

    if node is None:
        raise HTTPException(status_code=404, detail=FICHA_NO_ENCONTRADA)

    try:
        outgoing, incoming = provider.relations_for_entity(entity_id)
    except Exception as exc:  # noqa: BLE001
        return _error(request, user, exc)

    def _con_el_otro(edge: dict, other_key: str) -> dict:
        s = serialize_edge(edge)
        try:
            other = provider.entity(edge.get(other_key))
        except Exception:  # noqa: BLE001 - un extremo ilegible es un extremo ausente
            other = None
        s["other_entity"] = serialize_node(other) if other else None
        return s

    ficha = serialize_node(node)
    return templates.TemplateResponse(
        request, ITEM_TEMPLATE,
        _context(
            request, user,
            items=[ficha], entity=ficha,
            outgoing=[_con_el_otro(e, "to") for e in outgoing],
            incoming=[_con_el_otro(e, "from") for e in incoming],
        ),
    )

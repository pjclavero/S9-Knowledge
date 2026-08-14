"""Hueco B del chasis — Operations Dashboard, SOLO LECTURA.

FRONTERA DURA: aquí no hay ningún método que no sea GET, y ninguna lectura con
efecto lateral. Este panel NO aprueba, NO reintenta, NO cancela, NO reinicia y
NO purga nada. Tampoco *ejecuta* los healthchecks: lee el ÚLTIMO INFORME YA
GUARDADO (``app.health.storage.load_last``) en vez de tomar el camino de
``/admin/health``.

PRECISIÓN, porque la frase importa y la primera versión de este docstring
señalaba al culpable equivocado: ``runner.run_report()`` **no escribe**. Quien
escribe es el MANEJADOR de ``/admin/health``, que tras ejecutar el informe llama
a ``storage.save_report(report)`` dentro del propio GET (ver
``app/routers/health_admin.py``). La conclusión operativa no cambia —ese camino,
tomado entero, ejecuta comprobaciones y deja un fichero nuevo en disco, y un GET
que escribe sigue siendo escritura—, pero el efecto lateral es de la RUTA, no de
la función.

La ausencia de escritura no se promete en prosa: se comprueba por ENUMERACIÓN
de los métodos montados bajo el prefijo del contrato
(``test_ninguna_ruta_del_espacio_del_panel_acepta_escritura``), sobre la app
real y no sobre este módulo.

MONTAJE
-------
Se respeta el contrato publicado del chasis (``app/chassis.py``, docs/69):
prefijo ``/panel/operations``, ruta raíz ``chassis_operations``, rol ``admin``,
plantilla ``chassis/operations.html``. La guarda (``slot_guard``), el
interruptor (``slot_enabled``) y el contexto mínimo de plantilla
(``slot_context``) se importan de ``chassis_slot``: no se reescribe ninguno.
Este módulo declara su propio ``APIRouter`` sólo porque el handler necesita
parámetros de consulta que ``build_slot_router`` no contempla.

DE DÓNDE SALE CADA DATO (no hay ninguna capacidad nueva de backend)
------------------------------------------------------------------
* Disponibilidad de la cola: ``app.jobs_client.jobs_db_status`` (comprueba que
  el fichero exista y sea legible; no lo crea).
* Recuentos por estado: ``app.jobs_client.scoped_counts`` — cuenta SOBRE LO
  VISIBLE, es decir DESPUÉS de la autorización. Nunca se llama a
  ``get_counts_by_status`` directamente: ese recuento es de la base entera y
  publicarlo revelaría por diferencia lo que la política acaba de ocultar
  (misma doctrina que ``app/graph_view.py`` y docs/73).
* Filas de la cola: ``app.jobs_client.scoped_jobs`` — filtra por ámbito y
  RECORTA el detalle operativo de quien no es autoridad plena.
* Salud: ``app.health.storage.load_last`` — el último informe guardado.

AUSENCIA != CERO
----------------
Si la cola no está disponible NO se pinta "0 trabajos": se declara que el dato
no está. Lo mismo con el informe de salud ausente o ilegible. Un cero inventado
es una afirmación falsa sobre producción, y este panel existe justamente para
que alguien mire producción.

ESTADOS DESCONOCIDOS: FALLO CERRADO
-----------------------------------
Un estado de trabajo que no esté en el vocabulario del motor
(``jobs.job_store.VALID_STATUSES``) y un estado de salud que no esté en
``HealthStatus`` se marcan como NO RECONOCIDOS y no se pintan como buenos. Y el
vocabulario es TRI-ESTADO: si no se puede leer (data-engine ausente), no se
reconoce ningún estado — no saber no concede.

AUTORIZACIÓN
------------
Ni una regla nueva. La puerta es ``slot_guard(SLOT)`` —que para un hueco
``admin`` es ``require_admin``, la misma de ``/admin/users``— y el ámbito de
datos es ``get_visibility_scope``, el mismo que usa ``/jobs``. No hay aquí
vocabulario paralelo de permisos ni ninguna comprobación propia de rol.

Con ``S9K_AUTH_ENABLED`` desactivado no hay principal, así que no hay autoridad
(docs/75): ``require_admin`` redirige a ``/login`` y el panel no se sirve. Y si
alguien llegara a entrar sin principal, el contexto sería anónimo de mínimo
privilegio, de modo que la consola saldría VACÍA. Ninguna de las dos cosas es
un defecto que arreglar; ambas se fijan en
``test_sin_auth_no_reaparece_el_comportamiento_permisivo``, que es
bidireccional: también se pone rojo si el panel ocultara de más a quien SÍ está
autorizado.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pathlib import Path

from app import jobs_client
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, slot_enabled
from app.health import storage as health_storage
from app.health.models import HealthStatus
from app.routers.chassis_slot import slot_context, slot_guard

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SLOT = next(s for s in FEATURE_SLOTS if s.key == "B")

#: Techo de filas. Una pantalla sin techo es una petición que puede materializar
#: la cola entera en memoria.
MAX_ROWS = 100
DEFAULT_ROWS = 50

router = APIRouter(prefix=SLOT.prefix, tags=[f"chassis-{SLOT.key.lower()}"])


# ---------------------------------------------------------------------------
# Costuras de lectura. Existen para que la suite pueda inyectar material sin
# tocar producción; ninguna añade capacidad al backend.
# ---------------------------------------------------------------------------

def _jobs_status() -> dict:
    return jobs_client.jobs_db_status()


def _jobs_rows(scope: VisibilityScope, **kwargs) -> list[dict]:
    return jobs_client.scoped_jobs(scope, **kwargs)


def _jobs_counts(scope: VisibilityScope, workspace: Optional[str]) -> dict:
    return jobs_client.scoped_counts(scope, workspace=workspace)


def _health_report() -> Optional[dict]:
    return health_storage.load_last()


def _health_report_exists() -> bool:
    return health_storage.default_report_path().exists()


# ---------------------------------------------------------------------------
# Vocabularios: se IMPORTAN del sitio donde viven, y son tri-estado
# ---------------------------------------------------------------------------

def known_job_statuses() -> Optional[frozenset]:
    """Vocabulario de estados del motor, o ``None`` si no se puede leer.

    ``None`` no es "conjunto vacío": es "aquí no se sabe". Un estado que no se
    puede contrastar con nada no se declara conocido, así que con data-engine
    ausente NINGÚN estado se pinta como bueno. Se lee de
    ``jobs.job_store.VALID_STATUSES`` en vez de copiarlo: una copia local
    divergiría en silencio el día que el motor añada un estado.
    """
    # `_load_job_store` es de `jobs_client` a propósito: encapsula el ajuste de
    # `sys.path` que hace falta para importar el paquete `jobs` de data-engine
    # sin colisionar con el paquete `app` del visor. Repetirlo aquí sería
    # copiar el único trozo delicado del puente.
    store = jobs_client._load_job_store()
    if store is None:
        return None
    crudo = getattr(store, "VALID_STATUSES", None)
    if not crudo:
        return None
    try:
        return frozenset(str(s) for s in crudo)
    except TypeError:
        return None


def job_status_known(status: Optional[str], vocabulario: Optional[frozenset]) -> bool:
    """¿Reconoce el motor este estado? FALLA CERRADO ante vocabulario ausente."""
    if vocabulario is None or not status:
        return False
    return status in vocabulario


#: Vocabulario de salud: importado de `app.health.models`, no redefinido.
HEALTH_VALUES = frozenset(s.value for s in HealthStatus)


def health_status_known(status: Optional[str]) -> bool:
    """``UNKNOWN`` es un estado RECONOCIDO que significa "no se sabe".

    No se confunde con un estado que este visor no reconoce: aquél se marca
    aparte (`known=False`) y tampoco se pinta como bueno.
    """
    return bool(status) and status in HEALTH_VALUES


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

def _fila(job: dict, vocabulario: Optional[frozenset]) -> dict:
    """Una fila de la cola, ya recortada aguas arriba por `scoped_jobs`.

    Aquí no se filtra nada por visibilidad: filtrar dos veces en dos sitios es
    cómo acaban discrepando. Sólo se elige QUÉ campos se pintan, y ni `db_path`
    ni `error_message` están entre ellos: son rutas y textos del servidor.
    """
    estado = job.get("status") or None
    return {
        "job_id": job.get("job_id") or None,
        "workspace": job.get("workspace") or None,
        "type": job.get("type") or None,
        "status": estado,
        "status_known": job_status_known(estado, vocabulario),
        "created_at": job.get("created_at") or None,
        "updated_at": job.get("updated_at") or None,
        "attempts": job.get("attempts"),
        "has_error": bool(job.get("has_error") or job.get("error_code")),
    }


def _conteos(crudos: dict, vocabulario: Optional[frozenset]) -> list[dict]:
    """Recuentos por estado, ya calculados sobre lo VISIBLE."""
    return [
        {"status": estado, "count": numero,
         "status_known": job_status_known(estado, vocabulario)}
        for estado, numero in sorted(crudos.items())
    ]


def _salud() -> dict:
    """Último informe de salud GUARDADO. Nunca ejecuta un healthcheck.

    Tres desenlaces distintos, y se distinguen: no hay informe, hay fichero
    pero no se puede leer, o hay informe. Los dos primeros son AUSENCIA
    declarada; ninguno se pinta como "todo bien".
    """
    informe = _health_report()
    if informe is None:
        return {
            "available": False,
            "reason": "unreadable" if _health_report_exists() else "absent",
            "overall": None, "overall_known": False, "components": [],
        }
    overall = informe.get("overall") or None
    componentes = informe.get("components")
    componentes = componentes if isinstance(componentes, list) else []
    return {
        "available": True,
        "reason": None,
        "overall": overall,
        "overall_known": health_status_known(overall),
        "generated_at": informe.get("generated_at") or None,
        # Ni `message` ni `details`: pueden traer rutas, hosts o comandos del
        # servidor. Lo que este panel publica es QUÉ componente y en qué estado.
        "components": [
            {
                "component": (c.get("component") or None) if isinstance(c, dict) else None,
                "status": (c.get("status") or None) if isinstance(c, dict) else None,
                "status_known": health_status_known(
                    c.get("status") if isinstance(c, dict) else None
                ),
            }
            for c in componentes
        ],
    }


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


@router.get("", response_class=HTMLResponse, name=SLOT.route_name)
@router.get("/", response_class=HTMLResponse, name=SLOT.route_name)
def chassis_operations(
    request: Request,
    workspace: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    job_type: Optional[str] = Query(default=None),
    limit: int = Query(default=DEFAULT_ROWS, ge=1, le=MAX_ROWS),
    user=Depends(slot_guard(SLOT)),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    denegado = _authorize(request, user)
    if denegado is not None:
        return denegado

    vocabulario = known_job_statuses()
    if status is not None and not job_status_known(status, vocabulario):
        # No se puede contrastar => no se acepta. Pasar un estado sin validar a
        # `job_store.list_jobs` levanta `ValueError` y sale un 500 con traza.
        raise HTTPException(status_code=400, detail="Parámetro `status` no reconocido")

    estado_cola = _jobs_status()
    disponible = bool(estado_cola.get("ok"))
    filas: list[dict] = []
    conteos: Optional[list[dict]] = None
    total_visible: Optional[int] = None
    if disponible:
        try:
            crudos = _jobs_rows(
                scope, workspace=workspace, status=status, job_type=job_type, limit=limit
            )
            recuento = _jobs_counts(scope, workspace)
        except Exception as exc:
            # QUÉ ha pasado y nada más: ni la ruta de la base, ni el mensaje de
            # la excepción (que puede contenerla), ni la traza. Sólo el tipo.
            return templates.TemplateResponse(
                request, SLOT.template,
                _context(
                    request, user,
                    error="No se pudo leer la cola de trabajos.",
                    error_detail=type(exc).__name__,
                    ops={}, filtros={}, salud=None,
                ),
                status_code=503,
            )
        filas = [_fila(j, vocabulario) for j in crudos]
        conteos = _conteos(recuento, vocabulario)
        # Total = suma de lo VISIBLE. `scoped_counts` ya filtró por ámbito, así
        # que este total no revela nada que el espectador no pueda ver.
        total_visible = sum(c["count"] for c in conteos)

    return templates.TemplateResponse(
        request, SLOT.template,
        _context(
            request, user,
            items=filas,
            ops={
                "jobs_available": disponible,
                "counts": conteos,
                "total_visible": total_visible,
                "shown": len(filas),
                "limit": limit,
                "statuses": sorted(vocabulario) if vocabulario else None,
            },
            filtros={"workspace": workspace, "status": status, "job_type": job_type},
            salud=_salud(),
        ),
    )

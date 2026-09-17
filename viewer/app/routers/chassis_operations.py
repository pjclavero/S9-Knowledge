"""Hueco B del chasis — Operations Dashboard: CONSOLA DE OPERADOR.

EL CONTRATO DE ESTE PANEL HA CAMBIADO, Y SE DICE AQUÍ
-----------------------------------------------------
Hasta el Slice 2 este módulo era SOLO LECTURA y su cabecera lo declaraba como
"frontera dura: aquí no hay ningún método que no sea GET". Ya no es cierto, y
dejar aquella frase habría sido la forma más barata de colar una escritura como
si nada hubiera cambiado. El contrato nuevo, que vive en ``app/chassis.py``
(``WRITE_CAPABILITIES``) y está documentado en ``docs/69-chasis-de-montaje.md``:

    GET                 -> observación
    POST / mutaciones   -> SÓLO capacidades de producto explícitamente
                           declaradas, autenticadas, autorizadas, protegidas
                           con CSRF y AUDITABLES.

Este panel aloja HOY exactamente UNA capacidad de escritura, y está declarada
como dato en el chasis: ``ingesta_de_fuente`` (``POST
/panel/operations/ingestas``). Cualquier otra escritura que aparezca bajo
``/panel/operations`` es un defecto, y lo detecta la enumeración
(``chassis.undeclared_writes``), no una revisión ocular. Los huecos C, F y G no
declaran ninguna capacidad y por eso siguen siendo de solo lectura POR
CONSTRUCCIÓN, con la misma comprobación de antes.

LO QUE SIGUE SIENDO CIERTO: este panel NO aprueba, NO reintenta, NO cancela, NO
reinicia y NO purga nada, y NO aplica nada al grafo. La única mutación que
ofrece es ENCOLAR un trabajo. Tampoco *ejecuta* los healthchecks: lee el ÚLTIMO
INFORME YA GUARDADO (``app.health.storage.load_last``) en vez de tomar el
camino de ``/admin/health``.

LA CAPACIDAD, EN UNA LÍNEA
--------------------------
El operador elige una fuente POR SU NOMBRE (``app.sources_catalog``), el
servidor resuelve fichero, perfil, catálogo y workspace, y se crea un job
``ingest_v3`` en la cola que YA existe (``jobs.job_store.create_job``). El
worker lo recoge y llama al mismo núcleo de ingesta que usa la CLI. Aquí no se
ejecuta ninguna ingesta: este manejador encola y vuelve.

CERO CONOCIMIENTO INTERNO: el formulario no pide ``plan_id``, ni ``workspace``,
ni ``partida_id``, ni rutas, ni mandos de backend. Lo único que viaja es el
identificador opaco de la fuente elegida en el desplegable.

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

from typing import Any, Optional

import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pathlib import Path

from app import jobs_client, panel_errors, sources_catalog
from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.auth.models import User
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, capabilities_for_slot, slot_enabled
from app.health import storage as health_storage
from app.health.models import HealthStatus
from app.routers.chassis_slot import slot_context, slot_guard

#: Registro de AUDITORIA de las capacidades de escritura de este panel.
#: Es la mitad "AUDITABLES" del contrato del chasis: quien, que capacidad, sobre
#: que fuente y con que resultado. Va al log del SERVIDOR, nunca a la respuesta.
audit = logging.getLogger("panel.audit")

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


# ---------------------------------------------------------------------------
# CSRF — la misma pieza que usa el resto del visor, no una nueva
# ---------------------------------------------------------------------------

def _csrf(request: Request) -> str:
    cfg = get_auth_settings()
    session = getattr(request.state, "session", None)
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(
        session.id if session else 0, raw, secret=cfg.S9K_CSRF_SECRET
    )


def _check_csrf(request: Request, token: str) -> None:
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        # Sin auth no hay sesión con la que ligar el token. No es una excepción
        # a la protección: sin auth la guarda `require_admin` ya ha redirigido a
        # /login y este manejador no llega a ejecutarse (ver el docstring del
        # módulo y `test_sin_auth_no_reaparece_el_comportamiento_permisivo`).
        return
    session = getattr(request.state, "session", None)
    raw = getattr(request.state, "csrf_raw", "")
    if not validate_csrf(token, session.id if session else 0, raw,
                         secret=cfg.S9K_CSRF_SECRET):
        raise HTTPException(status_code=403, detail="CSRF inválido")


# ---------------------------------------------------------------------------
# Catálogo de fuentes elegibles. AUSENCIA != LISTA VACÍA
# ---------------------------------------------------------------------------

def _fuentes() -> dict:
    """Fuentes que el operador puede elegir, o la declaración de que no se sabe.

    Misma doctrina que el resto del panel: si el catálogo no se puede consultar
    NO se pinta un desplegable vacío (que se lee como "no hay fuentes"), se
    dice que el dato no está.
    """
    try:
        fuentes = sources_catalog.listar_fuentes()
    except sources_catalog.CatalogoNoDisponible as exc:
        panel_errors.registrar("SOURCE_CATALOG_UNAVAILABLE", exc)
        return {"available": False, "lista": []}
    # La clave es `lista` y NO `items`: en Jinja `fuentes.items` resuelve al
    # METODO `dict.items` antes que a la clave, asi que `{% for f in
    # fuentes.items %}` iteraba sobre un builtin y reventaba la plantilla.
    # Medido, no supuesto.
    return {"available": True, "lista": [f.para_pantalla() for f in fuentes]}


# Estados con DESENLACE. Se declaran una sola vez porque los usan las dos
# funciones que componen la pantalla: la que calla el acuse (`_aviso`) y la que
# explica el final (`_resultado_del_trabajo`). Dos listas separadas volverían a
# permitir el defecto medido —acuse tranquilizador delante de un fallo— en
# cuanto una de las dos añadiese un estado y la otra no.
ESTADOS_OK = frozenset({"complete", "completed"})
ESTADOS_FALLIDOS = frozenset({"failed", "skipped", "cancelled"})
ESTADOS_TERMINALES = ESTADOS_OK | ESTADOS_FALLIDOS


def _job_terminado(job: Optional[dict]) -> bool:
    """¿Este trabajo ya tiene desenlace? Sólo entonces deja de estar «en la cola»."""
    return bool(job) and (job.get("status") in ESTADOS_TERMINALES)


#: Acuses de ÉXITO de las capacidades de plan. No van en `panel_errors.CATALOGO`
#: a propósito: aquel catálogo es el de lo que salió mal, y meter ahí un éxito
#: haría que «código conocido» dejara de significar «fallo conocido».
#:
#: Ninguno dice cuántas cosas se escribieron: eso se lee del estado del plan,
#: que se recalcula en el GET. Un número en la URL sería un número que el
#: operador puede editar.
ACUSES_DE_EXITO = {
    "PLAN_SEALED": (
        "Lo aprobado de esta ingesta ya está preparado. Revísalo abajo y, si "
        "es lo que quieres, añádelo al conocimiento."
    ),
    # EL SELLADO QUE DEJA RELACIONES FUERA, DICHO EN LA PANTALLA
    # (Slice 2 · Corte 5).
    #
    # `sellar()` devuelve `sin_proyeccion` desde el Corte anterior, y hasta
    # ahora esa lista iba SOLO al log del servidor y a auditoría. El operador
    # recibía un `PLAN_SEALED` limpio y cerraba la pantalla creyendo que lo que
    # aprobó estaba entero.
    #
    # Antes del Corte 5 eso pasaba SIEMPRE --ninguna proyección se emitía
    # nunca-- y ahora pasa A VECES, que es peor de detectar: el operador que ve
    # funcionar el caso normal no tiene motivo para sospechar del que no.
    #
    # No se pinta el motivo interno (`PROJECTION_*`): esos códigos son del
    # motor y no son para una persona. Se dice QUÉ se ha perdido y qué hacer.
    "PLAN_SEALED_SIN_PROYECCION": (
        "Lo aprobado de esta ingesta ya está preparado, PERO alguna de las "
        "relaciones que aprobaste no se va a añadir: no se ha podido "
        "comprobar contra el conocimiento que ya existe a qué apuntan. Lo "
        "demás sí se añadirá. Si esperabas esas relaciones, avisa a quien "
        "administra el servicio antes de continuar; el detalle queda "
        "registrado en el servidor."
    ),
    "PLAN_APPLIED": (
        "Lo aprobado ya forma parte del conocimiento."
    ),
}


def _aviso(codigo: Optional[str], job_id: Optional[str], scope: VisibilityScope) -> Optional[dict]:
    """Acuse que se pinta tras un POST, RECONSTRUIDO desde la cola.

    NO es un mensaje efímero guardado en sesión: se deriva del trabajo que está
    en la base de datos. Por eso sobrevive a un refresco Y a un reinicio del
    servicio, que es condición del corte y no un detalle.

    El código de error, en cambio, sí viaja en la URL; se valida contra el
    catálogo cerrado (`panel_errors.CATALOGO`) para que nadie pueda inyectar
    texto arbitrario en la pantalla poniéndolo en el query string.
    """
    if codigo:
        if codigo in ACUSES_DE_EXITO:
            return {"tipo": "ok", "code": codigo,
                    "message": ACUSES_DE_EXITO[codigo], "trabajo": None}
        if codigo not in panel_errors.CATALOGO:
            return None
        return {"tipo": "error", "code": codigo,
                "message": panel_errors.CATALOGO[codigo], "trabajo": None}
    if not job_id:
        return None
    # Se lee POR EL CAMINO DE PRODUCCIÓN, con ámbito: un job que el espectador
    # no puede ver no se convierte en un acuse por haber puesto su id en la URL.
    job = jobs_client.scoped_job(scope, job_id)
    if job is None:
        return None
    # UNA SOLA PRESENTACIÓN, Y EL ESTADO MANDA.
    #
    # Medido antes del Corte 3: con el trabajo en `failed`, la pantalla decía
    # PRIMERO «Se ha solicitado la ingesta. El trabajo ya está en la cola.» y
    # DESPUÉS `estado failed`. El texto tranquilizador iba delante del fallo, y
    # es el que el operador lee. Un acuse de "encolado" sólo es cierto mientras
    # el trabajo sigue en la cola: en cuanto tiene desenlace, quien habla es
    # `_resultado_del_trabajo`, que da estado Y causa juntos.
    if _job_terminado(job):
        return None
    return {
        "tipo": "ok",
        "code": "INGEST_REQUESTED",
        "message": "Se ha solicitado la ingesta. El trabajo ya está en la cola.",
        "trabajo": {
            "job_id": job.get("job_id"),
            "status": job.get("status"),
            "type": job.get("type"),
        },
    }


def _revision_del_resultado(bruto: Any) -> Optional[dict]:
    """La atribución de la corrida, curada para la plantilla.

    `None` cuando el handler no la publicó (corridas anteriores al Corte 4, o
    una ingesta que no exportó cola). La plantilla no pinta entonces ningún
    enlace: ofrecer uno a la cola entera diciendo que son «sus» propuestas
    sería otra vez presentar una cosa por otra.
    """
    if not isinstance(bruto, dict):
        return None
    job_id = bruto.get("job_id")
    if not job_id:
        return None
    propuestas = bruto.get("propuestas")
    return {
        "job_id": str(job_id),
        "workspace": str(bruto.get("workspace") or ""),
        "propuestas": propuestas if isinstance(propuestas, int) else None,
    }


def _resultado_del_trabajo(job: Optional[dict]) -> Optional[dict]:
    """Lo que el operador lee cuando el trabajo TERMINA. Explica el desenlace.

    Se construye SÓLO con material seguro: el `result` que el handler publicó
    (que ya viene curado por lista blanca) o, si falló, el código estable que
    el handler puso en `error_message`. El `error_message` NUNCA se pinta crudo:
    se parte por el separador y se descarta todo lo que no sea un código
    conocido, de modo que si algún día un handler dejara ahí una ruta, la
    pantalla mostraría el mensaje genérico en vez de la ruta.
    """
    if not job:
        return None
    estado = job.get("status")
    if estado in ESTADOS_OK:
        resultado = job.get("result")
        if isinstance(resultado, str):
            try:
                resultado = json.loads(resultado)
            except (TypeError, ValueError):
                resultado = None
        if not isinstance(resultado, dict):
            return {"estado": "ok", "code": "INGEST_OK",
                    "message": "La ingesta ha terminado correctamente.",
                    "resumen": None}
        return {
            "estado": "ok",
            "code": str(resultado.get("code") or "INGEST_OK"),
            "message": str(resultado.get("message")
                           or "La ingesta ha terminado correctamente."),
            "resumen": resultado.get("resumen")
            if isinstance(resultado.get("resumen"), dict) else None,
            # ENLACE A SU REVISIÓN. Por LISTA BLANCA, igual que el resumen: de
            # todo el bloque `revision` del handler sólo pasan las tres piezas
            # con las que se arma el enlace. Nada de rutas ni de nombres de
            # paquete: el `job_id` ya lo conoce el operador, el `workspace`
            # también, y el recuento es el que la corrida declaró.
            "revision": _revision_del_resultado(resultado.get("revision")),
        }
    if estado in ESTADOS_FALLIDOS:
        crudo = job.get("error_message") or ""
        codigo = str(crudo).split(":", 1)[0].strip()
        if codigo not in panel_errors.CATALOGO:
            # Ni el código se reconoce ni se enseña el texto: fallo cerrado.
            codigo = "INGEST_FAILED"
        return {"estado": "error", "code": codigo,
                "message": panel_errors.CATALOGO[codigo], "resumen": None}
    return {"estado": "en_curso", "code": None,
            "message": "El trabajo sigue en la cola.", "resumen": None}


def _plan_de_la_corrida(resultado: Optional[dict]) -> Optional[dict]:
    """El estado de LO APROBADO de esta corrida. Sin conocimiento interno.

    Se deriva de la atribución de corrida que el acuse de la ingesta ya
    publica (`revision`: `job_id` + `workspace`), que es la identidad que el
    Carril A dejó fijada y que el operador ya conoce. No se inventa ninguna
    identidad paralela y no se pide ninguna al operador: `plan_id` es interno y
    no sale de aquí.

    `None` cuando la corrida no atribuyó revisión: sin corrida no hay nada
    sobre lo que sellar, y pintar un botón que no puede funcionar sería fingir
    la acción (requisito 8).
    """
    if not resultado:
        return None
    revision = resultado.get("revision")
    if not isinstance(revision, dict) or not revision.get("job_id"):
        return None
    workspace = str(revision.get("workspace") or "")
    if not workspace:
        return None
    try:
        from app.services.v3_apply import ReviewApplyService  # noqa: PLC0415

        estado = ReviewApplyService().estado(
            workspace=workspace, job_id=str(revision["job_id"])
        )
    except Exception as exc:  # noqa: BLE001 - la pantalla no se cae por esto
        panel_errors.registrar("REVIEW_STORE_UNAVAILABLE", exc)
        return {"estado": "no_disponible", "avisos": ["REVIEW_STORE_UNAVAILABLE"],
                "sellable": False, "aplicable": False, "aprobadas": 0,
                "pendientes": 0, "en_el_plan": 0, "excluidas": [],
                "afirmaciones_escritas": None, "habilitado": False}
    vista = estado.to_dict()
    # La corrida viaja en el formulario, no en el cuerpo del estado: es la
    # única identidad que el POST necesita y ya es pública para el operador.
    vista["job_id"] = str(revision["job_id"])
    return vista


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
    # Acuse del POST (patrón PRG). `solicitado` es el id del trabajo recién
    # encolado y `aviso` un código de error del catálogo cerrado. Ninguno de
    # los dos lleva texto: lo que se pinta se deriva de la cola y del catálogo.
    solicitado: Optional[str] = Query(default=None),
    aviso: Optional[str] = Query(default=None),
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
                    fuentes={"available": False, "lista": []},
                    csrf_token="", aviso=None, resultado=None, plan=None,
                ),
                status_code=503,
            )
        filas = [_fila(j, vocabulario) for j in crudos]
        conteos = _conteos(recuento, vocabulario)
        # Total = suma de lo VISIBLE. `scoped_counts` ya filtró por ámbito, así
        # que este total no revela nada que el espectador no pueda ver.
        total_visible = sum(c["count"] for c in conteos)

    # El DESENLACE del trabajo que el operador acaba de solicitar. Se relee de
    # la cola en cada GET, así que refrescar la pantalla es lo que hace avanzar
    # lo que se ve: pendiente -> en curso -> terminado.
    desenlace = _resultado_del_trabajo(
        jobs_client.scoped_job(scope, solicitado) if solicitado else None
    )
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
            # --- capacidad de escritura declarada ---
            fuentes=_fuentes(),
            csrf_token=_csrf(request),
            aviso=_aviso(aviso, solicitado, scope),
            resultado=desenlace,
            # EL ESTADO DE LO APROBADO. Va aquí y no en un panel aparte porque
            # es la continuación del mismo recorrido: el acuse de la ingesta ya
            # enlaza a SU revisión, y aquí se dice qué se puede hacer con lo
            # que se aprobó allí.
            plan=_plan_de_la_corrida(desenlace),
        ),
    )


# ===========================================================================
# CAPACIDAD DE ESCRITURA DECLARADA: alta de fuente
# ---------------------------------------------------------------------------
# Declarada en `app.chassis.WRITE_CAPABILITIES` como `ingesta_de_fuente`. Si
# esta ruta y aquella declaración dejaran de coincidir, la enumeración del
# chasis lo ve (`undeclared_writes`) y la suite se pone roja: no hay forma de
# que este POST exista sin estar declarado.
#
# NO EJECUTA LA INGESTA. Crea un job y vuelve. El trabajo real lo hace el
# worker, en la cola que ya existía.
#
# PATRÓN PRG (POST -> Redirect -> GET), y es lo que hace que el estado
# sobreviva: la confirmación no es un mensaje en memoria sino un trabajo en
# SQLite, así que recargar no re-envía nada y reiniciar el servicio no pierde
# nada.
# ===========================================================================

#: La capacidad tal y como la declara el chasis. Se lee de allí en vez de
#: repetir la ruta: dos literales acaban divergiendo.
CAPACIDAD_INGESTA = next(
    c for c in capabilities_for_slot(SLOT.key) if c.name == "ingesta_de_fuente"
)

#: Sufijo de la ruta dentro del prefijo del hueco, derivado de la declaración.
_RUTA_INGESTA = CAPACIDAD_INGESTA.path[len(SLOT.prefix):]


def _crear_job(**kwargs) -> str:
    """Costura de escritura en la cola. Una sola, y va a `job_store.create_job`.

    El puente `jobs_client` es de SOLO LECTURA por diseño y así se queda: esta
    es la única escritura del visor hacia la cola, vive aquí, y la suite puede
    sustituirla sin tocar el puente de lectura.
    """
    store = jobs_client._load_job_store()
    if store is None:
        raise panel_errors.de_codigo("QUEUE_UNAVAILABLE")
    db_path = store.resolve_db_path(jobs_client._resolve_db_path())
    store.init_db(db_path)
    return store.create_job(db_path=db_path, **kwargs)


@router.post(_RUTA_INGESTA, name="chassis_operations_ingesta")
def solicitar_ingesta(
    request: Request,
    fuente: str = Form(default=""),
    csrf_token: str = Form(default=""),
    user=Depends(slot_guard(SLOT)),
):
    # 1. AUTORIZADA: la misma guarda del panel (`require_admin`) y el mismo
    #    interruptor, en el mismo orden que el GET. Un anónimo no distingue un
    #    panel apagado de uno encendido.
    denegado = _authorize(request, user)
    if denegado is not None:
        return denegado

    # 2. PROTEGIDA CON CSRF. Antes de mirar siquiera qué se pidió.
    _check_csrf(request, csrf_token)

    quien = getattr(user, "username", None) if isinstance(user, User) else None

    def _fallo(codigo: str, exc: Optional[BaseException] = None) -> RedirectResponse:
        """Vuelve al panel con un CÓDIGO. Nunca con una ruta ni una traza."""
        panel_errors.registrar(codigo, exc, fuente=fuente, operador=quien)
        audit.warning(
            "capacidad=%s operador=%s fuente=%s resultado=RECHAZADO codigo=%s",
            CAPACIDAD_INGESTA.name, quien, fuente, codigo,
        )
        return RedirectResponse(
            url=f"{request.url_for('chassis_operations')}?aviso={codigo}",
            status_code=303,
        )

    # 3. La elección del operador se valida contra el catálogo del SERVIDOR.
    #    `resolver` enumera y compara; no compone ninguna ruta con lo recibido.
    if not fuente.strip():
        return _fallo("SOURCE_NOT_SELECTED")
    try:
        elegida = sources_catalog.resolver(fuente.strip())
    except sources_catalog.CatalogoNoDisponible as exc:
        return _fallo("SOURCE_CATALOG_UNAVAILABLE", exc)
    if elegida is None:
        return _fallo("SOURCE_UNKNOWN")

    # 4. Todo lo interno lo pone el SERVIDOR: perfil, catálogo y workspace. El
    #    operador no los ha escrito ni los ha visto.
    perfil, catalogo = sources_catalog.perfil_y_catalogo()
    if not perfil.is_file():
        return _fallo("SOURCE_PACKAGE_INVALID")
    try:
        workspace = json.loads(perfil.read_text(encoding="utf-8")).get("workspace")
    except (OSError, ValueError, AttributeError) as exc:
        return _fallo("SOURCE_PACKAGE_INVALID", exc)
    if not workspace:
        return _fallo("SOURCE_PACKAGE_INVALID")

    # 5. Se encola en la cola QUE YA EXISTE.
    try:
        job_id = _crear_job(
            workspace=str(workspace),
            job_type="ingest_v3",
            payload={
                "source_path": str(elegida.ruta),
                "profile_path": str(perfil),
                "catalog_path": str(catalogo) if catalogo else None,
                "workspace": str(workspace),
                "source_title": elegida.titulo,
                # ATRIBUCIÓN DURABLE: quién pidió esta ingesta queda en el
                # propio trabajo, no sólo en un log que rota.
                "requested_by": quien,
            },
        )
    except panel_errors.OperatorError as exc:
        return _fallo(exc.code)
    except Exception as exc:  # noqa: BLE001 - la cola no admitió el trabajo
        return _fallo("INGEST_REQUEST_FAILED", exc)

    # 6. AUDITABLE: queda el rastro de quién ejerció qué capacidad y con qué
    #    resultado. Es la mitad del contrato que no se puede omitir.
    audit.info(
        "capacidad=%s operador=%s fuente=%s resultado=ENCOLADO trabajo=%s",
        CAPACIDAD_INGESTA.name, quien, elegida.handle, job_id,
    )
    return RedirectResponse(
        url=f"{request.url_for('chassis_operations')}?solicitado={job_id}",
        status_code=303,
    )


# ===========================================================================
# CAPACIDAD DE ESCRITURA DECLARADA: sellar lo aprobado de una corrida
# ---------------------------------------------------------------------------
# Declarada como `sellado_del_plan_revisado`. NO escribe en el grafo: deja en
# el almacén de revisión el SNAPSHOT INMUTABLE de lo que el operador aprobó.
# Se declara igualmente porque es una escritura durable de esta capacidad, y la
# enumeración del chasis no distingue «escribe poco».
# ===========================================================================

CAPACIDAD_SELLADO = next(
    c for c in capabilities_for_slot(SLOT.key) if c.name == "sellado_del_plan_revisado"
)
_RUTA_SELLADO = CAPACIDAD_SELLADO.path[len(SLOT.prefix):]

CAPACIDAD_APLICACION = next(
    c for c in capabilities_for_slot(SLOT.key)
    if c.name == "aplicacion_del_plan_revisado"
)
_RUTA_APLICACION = CAPACIDAD_APLICACION.path[len(SLOT.prefix):]


def _corrida_visible(scope: VisibilityScope, job_id: str) -> Optional[dict]:
    """La corrida, LEÍDA POR EL CAMINO DE PRODUCCIÓN y con ámbito.

    Un trabajo que el llamante no puede ver no se convierte en una corrida
    sobre la que sellar o aplicar por haber puesto su id en el formulario. El
    `workspace` sale de AQUÍ, del trabajo, no de lo que se recibió: aceptarlo
    del formulario permitiría dirigir la escritura a otro ámbito.
    """
    if not job_id.strip():
        return None
    return jobs_client.scoped_job(scope, job_id.strip())


def _accion(
    request: Request,
    user,
    capacidad,
    job_id: str,
    csrf_token: str,
    scope: VisibilityScope,
    ejecutar,
):
    """El esqueleto COMÚN de las dos acciones. Mismo orden, siempre.

    1. autorización (la guarda del hueco: `require_admin`);
    2. CSRF, antes de mirar siquiera qué se pidió;
    3. la corrida, resuelta y ACOTADA por ámbito en el servidor;
    4. la acción;
    5. auditoría del intento, con su desenlace;
    6. 303 con un código estable.

    Los pasos 1 y 2 están SEPARADOS y cada uno tiene su control negativo: en el
    Corte 1, una prueba de rol pasaba aunque se degradara la guarda porque al
    `reviewer` lo paraba el CSRF.
    """
    denegado = _authorize(request, user)
    if denegado is not None:
        return denegado
    _check_csrf(request, csrf_token)

    quien = getattr(user, "username", None) if isinstance(user, User) else None

    def _fallo(codigo: str, exc: Optional[BaseException] = None) -> RedirectResponse:
        panel_errors.registrar(codigo, exc, trabajo=job_id, operador=quien)
        audit.warning(
            "capacidad=%s operador=%s trabajo=%s resultado=RECHAZADO codigo=%s",
            capacidad.name, quien, job_id, codigo,
        )
        return RedirectResponse(
            url=f"{request.url_for('chassis_operations')}"
                f"?solicitado={job_id}&aviso={codigo}",
            status_code=303,
        )

    corrida = _corrida_visible(scope, job_id)
    if corrida is None:
        return _fallo("SOURCE_UNKNOWN")
    workspace = str(corrida.get("workspace") or "")
    if not workspace:
        return _fallo("SOURCE_PACKAGE_INVALID")

    from app.services.v3_apply import ApplyError  # noqa: PLC0415

    try:
        hecho = ejecutar(workspace, job_id.strip(), quien)
    except ApplyError as exc:
        return _fallo(exc.code)
    except Exception as exc:  # noqa: BLE001 - nada técnico llega al operador
        return _fallo("APPLY_FAILED", exc)

    # AUDITORÍA DEL ÉXITO, con el desenlace REAL ya confirmado.
    audit.info(
        "capacidad=%s operador=%s trabajo=%s workspace=%s resultado=OK detalle=%s",
        capacidad.name, quien, job_id, workspace, hecho,
    )
    return RedirectResponse(
        url=f"{request.url_for('chassis_operations')}"
            f"?solicitado={job_id}&aviso={hecho['aviso']}",
        status_code=303,
    )


@router.post(_RUTA_SELLADO, name="chassis_operations_sellado")
def sellar_plan(
    request: Request,
    trabajo: str = Form(default=""),
    csrf_token: str = Form(default=""),
    user=Depends(slot_guard(SLOT)),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    def _ejecutar(workspace: str, job_id: str, quien):
        from app.services.v3_apply import ReviewApplyService  # noqa: PLC0415

        salida = ReviewApplyService().sellar(workspace=workspace, job_id=job_id)
        # EL ACUSE DICE EL DESENLACE ENTERO, no la mitad buena.
        #
        # `sin_proyeccion` no es un detalle técnico: es conocimiento que el
        # operador aprobó y que NO va a llegar al grafo. Un `PLAN_SEALED`
        # limpio en ese caso es cierto y engañoso a la vez -- el plan está
        # sellado, sí, y le falta algo que el operador pidió.
        aviso = ("PLAN_SEALED_SIN_PROYECCION" if salida.get("sin_proyeccion")
                 else "PLAN_SEALED")
        return {"aviso": aviso, **salida}

    return _accion(request, user, CAPACIDAD_SELLADO, trabajo, csrf_token, scope,
                   _ejecutar)


@router.post(_RUTA_APLICACION, name="chassis_operations_aplicacion")
def aplicar_plan(
    request: Request,
    trabajo: str = Form(default=""),
    csrf_token: str = Form(default=""),
    user=Depends(slot_guard(SLOT)),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    def _ejecutar(workspace: str, job_id: str, quien):
        from app.services.v3_apply import ReviewApplyService  # noqa: PLC0415

        # `operator_id` es QUIÉN aplica, y el gate del writer lo exige con una
        # forma concreta. Se deriva del usuario autenticado; no se acepta del
        # formulario, o el rastro de auditoría lo escribiría el atacante.
        salida = ReviewApplyService().aplicar(
            workspace=workspace, job_id=job_id,
            operator_id=f"panel:{quien}" if quien else "panel:anonimo",
        )
        return {"aviso": "PLAN_APPLIED", **salida}

    return _accion(request, user, CAPACIDAD_APLICACION, trabajo, csrf_token, scope,
                   _ejecutar)

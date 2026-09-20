"""Authenticated HTML routes for the Knowledge V3 human review queue."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.services.v3_review import (
    ProposalStoreUnavailable, ReviewError, ReviewService, StaleReviewError,
    store_unavailable_view,
)
from app.services.v3_review import default_glossary_root
from app.services.v3_glossary_candidates import GlossaryCandidateStore

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/v3/review", tags=["v3-review"])
_RANK = {"admin": 3, "reviewer": 2, "viewer": 1}


def _service() -> ReviewService:
    return ReviewService()


def _detalle_seguro(exc: ProposalStoreUnavailable) -> str:
    """Lo que SÍ puede cruzar al cliente: código estable + frase accionable.

    Nunca `str(exc)`. El mensaje de esta excepción lleva el DIRECTORIO del
    almacén dentro y este repositorio es público:

        {"detail": "almacen de propuestas ausente: /.../reviews-v3/proposals"}

    La fuga preexistía para el paquete corrupto; lo que hizo el Corte 4 fue
    ensancharla del caso raro al que el propio panel llama «lo habitual», y
    justo en la única superficie de ESCRITURA de dominio del producto.

    El formato `CODIGO: frase` es el del resto del producto —`panel_errors`
    recupera el código con `split(":", 1)[0]`—, así que un cliente puede
    ramificar por código sin que nadie tenga que parsear prosa.
    """
    vista = store_unavailable_view(exc)
    return f"{vista['code']}: {vista['message']}"


#: Los filtros DE PANTALLA de la consola. Son exactamente los tres parámetros
#: de consulta que el operador ya puede poner con la mano en la barra del
#: navegador: no hay aquí ningún dato que él no pudiera escribir.
FILTROS_DE_PANTALLA = ("source_id", "engine_decision", "job_id")


def _destino(workspace: str, filtros: dict[str, str | None], **extra: str) -> str:
    """El sitio al que se vuelve tras decidir o deshacer, CON EL CONTEXTO PUESTO.

    EL DEFECTO QUE CIERRA. Medido por efecto sobre la consola:

        GET  /v3/review?workspace=alpha&job_id=job-A  -> 2 fichas, filtro declarado
        POST /v3/review/decide (APPROVE)              -> 303 a /v3/review?workspace=alpha
        GET  de ese destino                           -> 3 fichas, filtro AUSENTE

    La cola se ensanchaba sola de 2 a 3 por un clic del propio operador, y sin
    declararlo. Es la misma enfermedad que el filtro no pegajoso del `<select>`
    —un cambio de estado no declarado provocado por el propio operador— pero
    por la PUERTA PRINCIPAL en vez de por la lateral, y peor: allí al menos
    había tocado un filtro; aquí sólo había aprobado una propuesta.

    El redirect codificaba `workspace` a mano con una f-string, así que tiraba
    también `source_id` y `engine_decision`. Se rehace con `urlencode`, que es
    además lo que impide que un valor con `&`, un espacio o un salto de línea
    fabrique parámetros ajenos o parta la cabecera `Location`.

    LO QUE ESTO **NO** ES: una fuente de autoridad. Estos tres valores viajan
    por el formulario y por la URL, donde el operador puede escribirlos; el
    ámbito se sigue resolviendo EN EL SERVIDOR con `get_visibility_scope`, y el
    recuento se sigue calculando DESPUÉS del recorte. Un identificador que
    viaja en un POST no concede nada: sólo dice qué se estaba mirando.
    """
    parametros = {"workspace": workspace}
    parametros.update(extra)
    for nombre in FILTROS_DE_PANTALLA:
        valor = (filtros.get(nombre) or "").strip()
        # UN FILTRO VACÍO NO SE PEGA. Si el operador lo quitó, se queda quitado:
        # reponerlo sería el error simétrico de perderlo.
        if valor:
            parametros[nombre] = valor
    return f"/v3/review?{urlencode(parametros)}"


def _guard(request: Request):
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        # LA TERCERA PUERTA POR LA QUE SE PERDÍA EL CONTEXTO. Esto mandaba
        # `request.url.path` PELADO: si la sesión caducaba sobre
        # `?workspace=alpha&job_id=job-A`, al reentrar se aterrizaba en
        # `/v3/review` sin nada, y el operador perdía la corrida que estaba
        # revisando. Misma clase que el filtro que no sobrevivía a decidir.
        #
        # SEGURIDAD: `next` es un vector clásico de redirección abierta, así
        # que el destino sigue siendo RELATIVO y VALIDADO. La validación ya
        # existe y no se toca —`auth._safe_next` rechaza esquema, `netloc`
        # (incluido `//host`) y todo lo que no empiece por `/`—; lo único que
        # cambia aquí es que el valor lleva ahora la query. Va por `urlencode`
        # para que sus `?` y `&` no fabriquen parámetros en el propio `/login`.
        destino = request.url.path
        if request.url.query:
            destino = f"{destino}?{request.url.query}"
        return RedirectResponse(
            url=f"/login?{urlencode({'next': destino})}", status_code=302
        )
    if _RANK.get(getattr(user, "role", ""), 0) < _RANK["reviewer"]:
        raise HTTPException(status_code=403, detail="Se requiere rol reviewer o admin.")
    return user


def _reviewer(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "reviewer-local"
    return getattr(user, "username", None) or getattr(user, "display_name", None) or "reviewer"


def _csrf(request: Request) -> str:
    cfg = get_auth_settings()
    session = getattr(request.state, "session", None)
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(session.id if session else 0, raw, secret=cfg.S9K_CSRF_SECRET)


def _check_csrf(request: Request, token: str) -> None:
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return
    session = getattr(request.state, "session", None)
    raw = getattr(request.state, "csrf_raw", "")
    if not validate_csrf(token, session.id if session else 0, raw, secret=cfg.S9K_CSRF_SECRET):
        raise HTTPException(status_code=403, detail="CSRF inválido")


@router.get("/glossary-candidates", response_class=HTMLResponse)
def glossary_candidates(
    request: Request,
    workspace: str | None = Query(default=None),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    # El ámbito de la petición (partida activa + capa juego) decide lo que se
    # entrega, con el mismo motor de política que el resto del visor.
    # EL ALMACÉN PUEDE NO ESTAR, Y ESO NO ES UN CERO.
    #
    # `workspaces()` lee el almacén de propuestas, así que desde el Corte 4
    # puede levantar `ProposalStoreUnavailable`. Sin este manejo la excepción
    # llegaba cruda al servidor y el enlace de la nav devolvía **500** — medido
    # en el contrato de navegador, no deducido.
    #
    # NO se arregla devolviendo `[]`: eso reintroduce «ausencia == cero», que
    # es el defecto que este corte viene a cerrar, y encima en la superficie
    # que tiene las ÚNICAS escrituras de dominio.
    try:
        workspaces = _service().workspaces(scope=scope)
    except ProposalStoreUnavailable as exc:
        return templates.TemplateResponse(
            request, "v3_glossary_candidates.html",
            {"auth_user": guard, "workspaces": [], "workspace": None, "items": [],
             "almacen": store_unavailable_view(exc)},
        )
    selected = workspace or (workspaces[0] if len(workspaces) == 1 else None)
    if selected and selected not in workspaces:
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    items = _service().glossary_candidates(selected, scope=scope) if selected else []
    return templates.TemplateResponse(
        request, "v3_glossary_candidates.html",
        {"auth_user": guard, "workspaces": workspaces, "workspace": selected,
         "items": items, "almacen": None},
    )


@router.get("", response_class=HTMLResponse, name="v3_review_queue")
@router.get("/", response_class=HTMLResponse, name="v3_review_queue_slash")
def queue(
    request: Request,
    workspace: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    # LA CORRIDA, PUESTA POR EL ACUSE (Corte 2). El acuse de la ingesta manda
    # aqui con el `job_id` de SU corrida, para que el operador no tenga que
    # teclear identificadores ni buscar sus propuestas entre las de todas las
    # corridas del workspace. La atribucion ya existia en el sobre del paquete
    # (`package_runs`); lo que faltaba era poder filtrar por ella.
    job_id: str | None = Query(default=None),
    engine_decision: str | None = Query(default=None),
    notice: str | None = Query(default=None),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    service = _service()
    # El enlace de la nav apunta aquí. `workspaces()` y `queue()` leen los dos
    # el almacén de propuestas; ninguno de los dos podía fallar antes del Corte
    # 4 y por eso no había manejo. Ahora sí, y sin esto la pantalla da 500.
    try:
        workspaces = service.workspaces(scope=scope)
        selected_workspace = workspace or (workspaces[0] if len(workspaces) == 1 else None)
        if selected_workspace and selected_workspace not in workspaces:
            raise HTTPException(status_code=404, detail="Workspace no encontrado")
        view = (
            service.queue(
                selected_workspace,
                source_id=source_id,
                engine_decision=engine_decision,
                job_id=job_id,
                scope=scope,
            )
            if selected_workspace else None
        )
        almacen = None
    except ProposalStoreUnavailable as exc:
        # La pantalla ABRE y EXPLICA, igual que el panel B hace con el catálogo
        # de fuentes que no se puede consultar: «no es que no haya; es que el
        # dato no está». Lo que no hace es presentar la ausencia como una cola
        # vacía ni echar al operador con un error sin texto.
        workspaces, selected_workspace, view = [], None, None
        almacen = store_unavailable_view(exc)
    return templates.TemplateResponse(
        request,
        "v3_review.html",
        {
            "auth_user": guard,
            "csrf_token": _csrf(request),
            "workspaces": workspaces,
            "workspace": selected_workspace,
            "source_id": source_id,
            "engine_decision": engine_decision,
            "job_id": job_id,
            "queue": view,
            "almacen": almacen,
            "request_id": str(uuid.uuid4()),
            "notice": notice,
        },
    )


@router.post("/decide")
def decide(
    request: Request,
    workspace: str = Form(...),
    proposal_id: str = Form(...),
    human_decision: str = Form(...),
    request_id: str = Form(...),
    rationale: str = Form(""),
    predicate: str = Form(""),
    direction: str = Form(""),
    negated: str = Form(""),
    scope: str = Form(""),
    expected_proposal_hash: str = Form(""),
    subject_canonical_name: str = Form(""),
    object_canonical_name: str = Form(""),
    subject_alias: str = Form(""),
    object_alias: str = Form(""),
    suggested_entity_type: str = Form(""),
    is_ocr_asr_error: str = Form(""),
    misrecognition: str = Form(""),
    spoken_form: str = Form(""),
    csrf_token: str = Form(""),
    # LOS FILTROS VIGENTES, PARA QUE SOBREVIVAN A LA DECISIÓN. Ver `_destino`:
    # son los tres parámetros de pantalla, no autoridad de nada.
    filtro_source_id: str = Form("", alias="source_id"),
    filtro_engine_decision: str = Form("", alias="engine_decision"),
    filtro_job_id: str = Form("", alias="job_id"),
    # `scope` (arriba) es un campo del formulario de corrección; el ámbito de
    # visibilidad de la petición se llama aparte para no colisionar.
    visibility_scope: VisibilityScope = Depends(get_visibility_scope),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _check_csrf(request, csrf_token)
    filtros = {
        "source_id": filtro_source_id,
        "engine_decision": filtro_engine_decision,
        "job_id": filtro_job_id,
    }
    correction = {
        key: value for key, value in {
            "predicate": predicate.strip(),
            "direction": direction.strip(),
            "negated": negated == "true" if negated else None,
            "scope": scope.strip(),
            "subject_canonical_name": subject_canonical_name.strip(),
            "object_canonical_name": object_canonical_name.strip(),
            "subject_alias": subject_alias.strip(),
            "object_alias": object_alias.strip(),
            "suggested_entity_type": suggested_entity_type.strip(),
            "is_ocr_asr_error": is_ocr_asr_error == "true" if is_ocr_asr_error else None,
            "misrecognition": misrecognition.strip(),
            "spoken_form": spoken_form.strip(),
        }.items()
        if value not in ("", None)
    }
    if human_decision == "CORRECT" and not correction:
        raise HTTPException(status_code=400, detail="CORRECT requiere al menos un cambio")
    # El hash es obligatorio en la superficie HTTP: sin él, el control de
    # revisión obsoleta se autoanularía (el servicio solo admite None para
    # llamadores programáticos internos).
    if not expected_proposal_hash.strip():
        raise HTTPException(status_code=400, detail="expected_proposal_hash es obligatorio")
    try:
        _service().record(
            proposal_id=proposal_id,
            workspace=workspace,
            reviewer=_reviewer(request),
            human_decision=human_decision,
            request_id=request_id,
            rationale=rationale,
            correction=correction,
            expected_proposal_hash=expected_proposal_hash,
            scope=visibility_scope,
        )
    except StaleReviewError:
        # EL AVISO TAMPOCO PIERDE EL CONTEXTO: la propuesta cambió, pero el
        # operador sigue mirando la misma corrida.
        return RedirectResponse(
            url=_destino(workspace, filtros, notice="STALE_REVIEW"), status_code=303
        )
    except ProposalStoreUnavailable as exc:
        # TERCER CONSUMIDOR de `load_proposals`: `record()`. Se captura ANTES
        # que `ReviewError` por dos motivos, y los dos importan.
        #
        # 1. DESENLACE. Un 400 dice «tu petición está mal». El almacén caído no
        #    es culpa de quien decide, y mandarle a corregir su formulario le
        #    hace perder el tiempo: es 503, indisponibilidad del servidor.
        # 2. FUGA. El `detail=str(exc)` de abajo publica el mensaje de la
        #    excepción, y el de ésta lleva el DIRECTORIO dentro. Repositorio
        #    público: sale la frase estable, no la ruta.
        raise HTTPException(status_code=503, detail=_detalle_seguro(exc)) from exc
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=_destino(workspace, filtros), status_code=303)


@router.post("/undo")
def undo(
    request: Request,
    workspace: str = Form(...),
    request_id: str = Form(...),
    csrf_token: str = Form(""),
    # Los mismos tres filtros que `decide`, por la misma razón: deshacer es
    # también una acción de esta consola, y tampoco puede ensanchar la cola
    # sin decirlo.
    filtro_source_id: str = Form("", alias="source_id"),
    filtro_engine_decision: str = Form("", alias="engine_decision"),
    filtro_job_id: str = Form("", alias="job_id"),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _check_csrf(request, csrf_token)
    filtros = {
        "source_id": filtro_source_id,
        "engine_decision": filtro_engine_decision,
        "job_id": filtro_job_id,
    }
    try:
        _service().undo_last(
            workspace=workspace,
            reviewer=_reviewer(request),
            request_id=request_id,
            scope=scope,
        )
    except ProposalStoreUnavailable as exc:
        # MISMO DESENLACE QUE `decide`, y por las mismas dos razones: 503 en vez
        # de culpar al revisor, y código estable en vez de `str(exc)`.
        #
        # Hoy `undo_last` NO es consumidor de `load_proposals` —el censo por AST
        # da exactamente tres: `workspaces`, `queue` y `record`—, así que esta
        # rama no es alcanzable todavía. Se pone igualmente porque la que sí
        # está debajo publica `str(exc)`, y el día que `undo_last` necesite leer
        # el almacén la fuga aparecería aquí sin que nadie la buscara.
        raise HTTPException(status_code=503, detail=_detalle_seguro(exc)) from exc
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=_destino(workspace, filtros), status_code=303)

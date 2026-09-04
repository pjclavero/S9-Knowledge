"""S9 Knowledge — visor mínimo de solo lectura (FastAPI)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import entities as api_entities
from app.api import graph as api_graph
from app.api import jobs as api_jobs
from app.api import status as api_status
from app.auth.config import get_auth_settings
from app.auth.middleware import AuthMiddleware
from app.auth.dependencies import (
    get_current_user,
    require_admin,
    require_api_authenticated_user,
    require_api_role,
    require_authenticated_user,
    require_role,
)
from app.auth.models import User
from app.auth.security import enforce_auth_security
from app.auth import db as auth_db
from app.authz.dependencies import get_filtered_provider, get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, ChassisContractError, install_nav_globals
from app.config import get_settings
from app.deps import get_default_workspace, get_provider
from app.jobs_client import jobs_db_status, scoped_counts, scoped_job, scoped_jobs
from app.providers.base import GraphProvider
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import health_admin as health_router
from app.routers import partida as partida_router
from app.routers import readonly as readonly_router
from app.routers import reviews_console as reviews_console_router
from app.routers import v3_review as v3_review_router
from app.serializers import serialize_edge, serialize_node

BASE_DIR = Path(__file__).resolve().parent

# Directorio raíz del repositorio (dos niveles por encima de viewer/app/)
REPO_ROOT = BASE_DIR.parent.parent

# Las rutas automáticas /docs, /redoc y /openapi.json se desactivan y se
# sustituyen por rutas propias con control de acceso evaluado en tiempo de
# petición (ver más abajo). Así el gating no depende del valor de configuración
# capturado en el momento del import.
app = FastAPI(
    title="S9 Knowledge Viewer",
    version="0.3.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Middleware de autenticación (no-op cuando S9K_AUTH_ENABLED=false)
app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Un formulario incompleto debe repintar la pagina, no escupir JSON.

    Sin esto, un POST a /login sin los campos devolvia el JSON crudo de FastAPI y
    el formulario "desaparecia" para el usuario. La validacion nativa del
    navegador ya lo evita, pero un cliente sin JS o una peticion manual siguen
    llegando aqui.
    """
    if request.url.path == "/login":
        from app.auth.csrf import issue_login_csrf
        from app.routers.auth import LOGIN_CSRF_COOKIE, _login_cookie_kwargs

        cfg = get_auth_settings()
        token = issue_login_csrf(cfg.S9K_CSRF_SECRET)
        response = templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "campos_incompletos", "next": "/", "csrf_token": token},
            status_code=400,
        )
        response.set_cookie(value=token, **_login_cookie_kwargs(cfg))
        return response
    if request.url.path == "/account/change-password":
        # Mismo principio que /login: un formulario incompleto repinta HTML.
        user = getattr(request.state, "user", None)
        if user is None:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)
        from app.auth.csrf import get_csrf_token_for_session

        cfg = get_auth_settings()
        session = getattr(request.state, "session", None)
        csrf_raw = getattr(request.state, "csrf_raw", "")
        csrf_tok = get_csrf_token_for_session(
            session.id if session else 0, csrf_raw, secret=cfg.S9K_CSRF_SECRET
        )
        return templates.TemplateResponse(
            request, "auth/change_password.html",
            {"user": user, "csrf_token": csrf_tok,
             "errors": ["Faltan campos: rellena los tres campos del formulario."]},
            status_code=400,
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# APIs protegidas: viewer+ cuando auth está activa; públicas cuando está off
# (la dependencia es no-op si S9K_AUTH_ENABLED=false).
app.include_router(api_status.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(api_entities.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(api_graph.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(api_jobs.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(health_router.router)
app.include_router(readonly_router.router)
app.include_router(partida_router.router)
# Panel de revision v1 (Equipo B): consola de revision sin escritura en Neo4j.
app.include_router(reviews_console_router.router)
app.include_router(v3_review_router.router)


# ---------------------------------------------------------------------------
# Chasis de montaje: huecos C/B/F/G declarados en `app/chassis.py`
# ---------------------------------------------------------------------------
# Un router definido y no montado es una ruta muerta que no avisa. Aquí el
# montaje se DERIVA del contrato: si un hueco declarado no se puede importar o
# no exporta `router`, la aplicación no arranca. Falla al importar, en el acto,
# no seis semanas después cuando alguien pulsa el enlace del menú.
def _mount_feature_slots() -> None:
    import importlib

    for slot in FEATURE_SLOTS:
        try:
            module = importlib.import_module(slot.module)
        except ImportError as exc:  # pragma: no cover - se prueba desmontando
            raise ChassisContractError(
                f"Hueco {slot.key} ({slot.title}): el contrato declara el módulo "
                f"{slot.module!r}, que no se puede importar ({exc})."
            ) from exc
        router = getattr(module, "router", None)
        if router is None:
            raise ChassisContractError(
                f"Hueco {slot.key} ({slot.title}): {slot.module} no exporta `router`."
            )
        app.include_router(router)


_mount_feature_slots()


# ---------------------------------------------------------------------------
# Navegación: un único global de Jinja en TODOS los entornos de plantillas
# ---------------------------------------------------------------------------
# Cada router construye su propia instancia de Jinja2Templates. Registrar el
# global sólo en el entorno de este módulo dejaría media aplicación con la barra
# de navegación vacía, así que se descubren todos los entornos ya importados.
def _install_navigation() -> None:
    import sys

    envs = []
    for name, module in list(sys.modules.items()):
        if name != "app" and not name.startswith("app."):
            continue
        for attr in vars(module).values() if module else ():
            if isinstance(attr, Jinja2Templates) and attr.env not in envs:
                envs.append(attr.env)
    install_nav_globals(app, envs)


_install_navigation()


# ---------------------------------------------------------------------------
# /docs, /redoc, /openapi.json — control de acceso en tiempo de petición
# ---------------------------------------------------------------------------

def _docs_access(request: Request):
    """Devuelve None si se permite servir la documentación; si no, la respuesta
    de denegación adecuada.

    - auth desactivada → público.
    - auth activada y S9K_AUTH_EXPOSE_DOCS=false → 404 (no existe).
    - auth activada y expose=true → solo admin (401 anónimo / 403 no-admin).
    """
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    if not cfg.S9K_AUTH_EXPOSE_DOCS:
        raise HTTPException(status_code=404, detail="Not Found")
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Solo admin")
    return None


@app.get("/openapi.json", include_in_schema=False)
def _openapi(request: Request):
    _docs_access(request)
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
def _swagger(request: Request):
    from fastapi.openapi.docs import get_swagger_ui_html
    _docs_access(request)
    return get_swagger_ui_html(openapi_url="/openapi.json", title="S9 Knowledge Viewer — API")


@app.get("/redoc", include_in_schema=False)
def _redoc(request: Request):
    from fastapi.openapi.docs import get_redoc_html
    _docs_access(request)
    return get_redoc_html(openapi_url="/openapi.json", title="S9 Knowledge Viewer — API")


# ---------------------------------------------------------------------------
# Helper: validar seguridad e instalar DB de auth al arrancar si está activada
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup_auth() -> None:
    cfg = get_auth_settings()
    # Fail-closed: aborta el arranque si la configuración de auth es insegura
    # (secreto CSRF por defecto/débil, backend no apto, ruta de DB relativa o
    # base inexistente — el visor NO crea la auth DB: eso es de la CLI).
    enforce_auth_security(cfg)
    if cfg.S9K_AUTH_ENABLED:
        p = Path(cfg.S9K_AUTH_DB_PATH)
        auth_db.ensure_migrated(p)
        # Identidad sanitizada de la base realmente abierta: comparable con
        # `cli.auth db-identity` para demostrar que es el mismo fichero.
        import logging
        ident = auth_db.db_identity(p)
        logging.getLogger("s9k.auth").info(
            "auth DB: path=%s device=%s inode=%s schema=%s",
            ident["path"], ident["device"], ident["inode"], ident["schema_version"],
        )


# ---------------------------------------------------------------------------
# Helper: protección de rutas HTML cuando auth está activada
# ---------------------------------------------------------------------------

def _auth_guard(request: Request) -> Optional[User]:
    """
    Cuando S9K_AUTH_ENABLED=true, exige usuario autenticado y lo devuelve.
    Cuando está desactivada, devuelve None (sin restricción).
    No se usa como dependencia directa; cada ruta lo llama explícitamente.
    """
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    return user


def _require_user_or_redirect(request: Request):
    """Para rutas HTML: redirige a /login si auth activada y no autenticado."""
    from fastapi.responses import RedirectResponse as _RR
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        next_url = str(request.url.path)
        return _RR(url=f"/login?next={next_url}", status_code=302)
    return user


def _require_reviewer_or_redirect(request: Request):
    """Para rutas que requieren reviewer o superior."""
    from fastapi.responses import RedirectResponse as _RR
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        next_url = str(request.url.path)
        return _RR(url=f"/login?next={next_url}", status_code=302)
    if not user.can_see_reviews():
        return HTMLResponse(
            content=_render_403(request, "Se requiere rol reviewer o admin."),
            status_code=403,
        )
    return user


def _render_403(request: Request, detail: str = "") -> str:
    try:
        return templates.get_template("auth/403.html").render(
            {"request": request, "detail": detail}
        )
    except Exception:
        return f"<h1>403 Acceso denegado</h1><p>{detail}</p>"


# ---------------------------------------------------------------------------
# Helper: lectura de datos de reviews
# ---------------------------------------------------------------------------

PIPELINE_FILE_NAMES = [
    "segments.json",
    "segments.classified.json",
    "candidates.json",
    "validated.json",
    "resolved.json",
    "approved_payload.json",
    "review_queue.json",
    "rejected.json",
    "review.md",
    "quality_report.json",
    "quality_report.md",
]


def _reviews_root() -> Path:
    """Raíz confinante. Se calcula en cada llamada a propósito: fijarla al
    importar la desacopla de `REPO_ROOT`, que se redirige en pruebas."""
    return (REPO_ROOT / "output" / "reviews").resolve()

#: Forma admisible de un identificador que va a formar parte de una ruta
#: (workspace, source_id). Lista BLANCA a propósito: prohibir `..` o `/` de una
#: en una es una carrera que se pierde con codificaciones y separadores raros.
#: `.` y `..` encajan en la clase de caracteres, así que se excluyen aparte: el
#: confinamiento posterior también los atrapa, pero una sola defensa en una ruta
#: de fichero es poca.
_WORKSPACE_ID_RE = re.compile(r"(?!\.+$)[A-Za-z0-9._-]{1,64}")


def _reviews_dir(workspace: str) -> Path:
    """Directorio de revisión de un workspace, confinado bajo `output/reviews`.

    El nombre llegaba directo a la ruta, así que `workspace=../../secretos`
    salía del árbol y enumeraba directorios arbitrarios del servidor. Se valida
    la FORMA del identificador (no una lista negra de `..`, que siempre se
    esquiva por codificación) y además se comprueba el confinamiento real de la
    ruta ya resuelta.
    """
    if not isinstance(workspace, str) or not _WORKSPACE_ID_RE.fullmatch(workspace):
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    raiz = _reviews_root()
    destino = (raiz / workspace).resolve()
    if destino != raiz and raiz not in destino.parents:
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    return destino


def _reviews_workspace(request: Request, solicitado: str | None) -> str:
    """Workspace efectivo para la cola de revisión, decidido en el SERVIDOR.

    `/reviews` tomaba el workspace del query param sin más defensa que el rol,
    de modo que un `reviewer` de A veía la cola de B cambiando la URL: material
    de entidades y descripciones ANTES de que exista visibilidad o ámbito. El
    resto del visor ya decidía con el ámbito del servidor; este camino no, y esa
    asimetría es la fuga. Un workspace fuera del ámbito responde 404 --no 403--
    para no confirmar su existencia.
    """
    settings = get_settings()
    scope = get_visibility_scope(request)
    ws = solicitado or settings.S9K_DEFAULT_WORKSPACE
    if not scope.ctx.admin_full and ws not in scope.ctx.allowed_workspaces:
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    return ws


def _read_json_safe(path: Path) -> list | dict | None:
    """Lee JSON tolerando ausencia del fichero y errores de parseo."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _count_items(data) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return 0


#: Documentos de una fuente que pueden declarar su ámbito. Se consultan TODOS:
#: quedarse con el primero que sea un dict deja la decisión en manos del orden
#: del listado, y `pipeline_state.json` --que `ReviewStore.save_step` escribe
#: SIEMPRE, indexado por paso y sin `partida_id`-- ensombrecía la declaración
#: real del paquete v1. Un documento que no declara nada no puede tapar a uno
#: que sí declara.
_DOCS_DE_AMBITO = ("approved_payload.json", "pipeline_state.json",
                   "candidates.json", "review_queue.json", "rejected.json")


def _docs_de_ambito(source_dir: Path) -> list[Mapping]:
    """TODOS los registros de la fuente que pueden llevar una declaración.

    Recorre la estructura COMPLETA de cada documento, a profundidad arbitraria,
    y devuelve cada Mapping que encuentra por el camino. La unidad de control es
    "recorrer toda la estructura", no "los sitios donde hemos mirado hasta
    ahora": enumerar claves conocidas es perder, porque las formas reales anidan
    por todas partes --`KnowledgePackage` (`review/export_import.py`) escribe
    `entities`, `relations`, `aliases`, `events`, `other`, `evidence`,
    `review_queue`, un `approved_payload` entero y un `workspace_metadata`
    con el `pipeline_state` dentro, todo en el mismo documento--.

    Esto se aprendió rompiéndolo: una versión anterior descendía a las listas de
    NIVEL SUPERIOR pero no a la lista anidada `approved` de
    `approved_payload.json`, y una fuente propia con ítems aprobados de otra
    partida atravesaba la barrera con sus contadores intactos.

    El recorrido es iterativo a propósito: un documento hondo no puede tumbar el
    visor por límite de recursión.
    """
    docs: list[Mapping] = []
    for nombre in _DOCS_DE_AMBITO:
        raiz = _read_json_safe(source_dir / nombre)
        if raiz is None:
            continue
        pila: list = [raiz]
        while pila:
            nodo = pila.pop()
            if isinstance(nodo, Mapping):
                docs.append(nodo)
                pila.extend(nodo.values())
            elif isinstance(nodo, list):
                pila.extend(nodo)
    return docs


def _sonda_sin_partida() -> VisibilityScope:
    """Ámbito que acepta la capa juego y NINGUNA partida.

    Sirve para preguntar si un documento DECLARA partida sin reimplementar aquí
    las rutas donde puede declararla (`VisibilityScope` las conoce y son suyas):
    la sonda acepta el documento si y sólo si no declara ninguna. Se pide al
    productor de contextos, no se fabrica a mano.
    """
    from app.authz.context import build_viewer_context

    return VisibilityScope(build_viewer_context(
        role="reviewer", auth_enabled=True,
        default_workspace=get_settings().S9K_DEFAULT_WORKSPACE,
    )).partida_only()


def _fuente_en_ambito(source_dir: Path, scope: VisibilityScope) -> bool:
    """¿Cae esta fuente dentro del ámbito del lector?

    Tres reglas, en este orden:

    1. Si ALGUNA declaración de la fuente queda fuera del ámbito, la fuente
       queda fuera: entre varias declaraciones manda la más restrictiva, porque
       un documento no puede ampliar el ámbito que otro acota.
    2. Si hay al menos una declaración y todas caen dentro, la fuente entra.
    3. Si no hay NINGUNA declaración, la partida no se puede determinar. Con una
       partida activa eso no es capa juego por omisión: es material no
       atribuible, y no se publica --«si no podemos calcular el contador con
       seguridad, prefiero no mostrarlo»--. Sin partida activa, el lector está
       pidiendo justamente la capa juego, y la decisión vuelve a la política.

    El corpus de revisión v1 NO lleva `partida_id`: `data-engine/app/review/` no
    escribe esa cadena en ninguna parte. Por eso la barrera efectiva es esta, a
    nivel de fuente, y por eso no puede quedar ensombrecida.
    """
    if scope.ctx.admin_full:
        return True
    docs = _docs_de_ambito(source_dir)
    sonda = _sonda_sin_partida()
    declaraciones = [d for d in docs if not sonda.allows(d)]
    if any(not scope.allows(d) for d in declaraciones):
        return False
    if declaraciones:
        return True
    if scope.ctx.active_partida:
        return False
    return scope.allows_partida(None)


def _items_enumerables(datos, clave: str | None = None):
    """Los ítems de un fichero de revisión, o ``None`` si no son enumerables.

    ``None`` es AUSENCIA HONESTA, no cero: cuando el documento no es una lista
    de registros (un blob, una lista de escalares), no hay ítems que contar y
    la salida legítima es no publicar la cifra. Ponerla a cero mentiría.

    Aquí NO se filtra por ámbito, y es deliberado. Hubo un filtro ítem a ítem
    contra `scope` en esta función; medido con mutaciones sobre las 1589
    pruebas del visor resultó INERTE: `_fuente_en_ambito` ya deniega la fuente
    ENTERA en cuanto uno solo de sus documentos declara una partida fuera del
    ámbito, así que ningún ítem superviviente podía ser ajeno y el filtro no
    podía ponerse rojo jamás. Un control de seguridad que ninguna prueba puede
    tumbar no es una garantía: es una falsa seguridad que invita a debilitar la
    barrera real creyendo que ésta la cubre. La barrera efectiva es la de
    fuente, y vive en `_fuente_en_ambito`.
    """
    registros = datos
    if isinstance(datos, dict) and clave is not None:
        registros = datos.get(clave)
    if not isinstance(registros, list):
        return None
    if not all(isinstance(r, Mapping) for r in registros):
        return None
    return registros


def _source_counters(source_dir: Path) -> dict:
    """Contadores de una fuente YA autorizada: AUTORIZAR y DESPUÉS contar.

    Un contador es un dato. El orden lo impone el llamador: `_list_sources` y
    el detalle sólo llegan aquí con fuentes que `_fuente_en_ambito` ha admitido,
    y esa admisión exige que TODAS las declaraciones de la fuente caigan dentro
    del ámbito. Por eso lo que se cuenta aquí es, por construcción, material del
    lector. Un contador que no se puede calcular vale ``None`` y la pantalla lo
    omite.
    """
    aprobados = _items_enumerables(
        _read_json_safe(source_dir / "approved_payload.json"), "approved")
    pendientes = _items_enumerables(_read_json_safe(source_dir / "review_queue.json"))
    rechazados = _items_enumerables(_read_json_safe(source_dir / "rejected.json"))
    return {
        "approved": None if aprobados is None else len(aprobados),
        "pending": None if pendientes is None else len(pendientes),
        "rejected": None if rechazados is None else len(rechazados),
    }


def _extract_package_meta(source_dir: Path) -> dict:
    """Extrae metadatos del paquete: origin, producer, model si existen."""
    meta: dict = {}

    # Intentar leer desde pipeline_state.json (campo 'package' o 'meta')
    pipeline_state = _read_json_safe(source_dir / "pipeline_state.json")
    if isinstance(pipeline_state, dict):
        pkg = pipeline_state.get("package") or pipeline_state.get("meta") or {}
        if isinstance(pkg, dict):
            for field in ("origin", "producer", "model", "external_confidence",
                          "local_confidence", "decision_reason"):
                if field in pkg:
                    meta[field] = pkg[field]
        # También puede estar en nivel raíz
        for field in ("origin", "producer", "model"):
            if field in pipeline_state and field not in meta:
                meta[field] = pipeline_state[field]

    # Intentar leer desde candidates.json (primer ítem, campos de paquete)
    if not meta.get("origin"):
        candidates = _read_json_safe(source_dir / "candidates.json")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                for field in ("origin", "producer", "model"):
                    if field in first and field not in meta:
                        meta[field] = first[field]

    return meta


def _extract_quality_report(source_dir: Path) -> dict:
    """Extrae info del quality_report si existe (json o md)."""
    qr: dict = {"json_exists": False, "md_exists": False, "summary": None}
    json_path = source_dir / "quality_report.json"
    md_path = source_dir / "quality_report.md"
    qr["json_exists"] = json_path.exists()
    qr["md_exists"] = md_path.exists()

    if qr["json_exists"]:
        data = _read_json_safe(json_path)
        if isinstance(data, dict):
            # Extrae campos de resumen conocidos
            for field in ("score", "summary", "total", "issues", "warnings"):
                if field in data:
                    qr[field] = data[field]
            # Fallback: preview de las primeras claves
            if "summary" not in qr:
                qr["summary"] = {k: v for k, v in list(data.items())[:5]}
    elif qr["md_exists"]:
        try:
            text = md_path.read_text(encoding="utf-8")
            # Extracto: primeras 400 chars
            qr["md_preview"] = text[:400].strip()
        except Exception:
            pass
    return qr


def _list_sources(workspace: str, scope: VisibilityScope) -> list[dict]:
    """Fuentes VISIBLES en el ámbito, con sus contadores del ámbito.

    Recorría el directorio del workspace y publicaba los contadores de cada
    subdirectorio sin pasar por `VisibilityScope`: la guarda de la ruta es de
    ROL, no de ámbito, así que dentro de un workspace autorizado las cifras
    agregaban material de otras partidas y permitían inferir su existencia y su
    volumen. El panel moderno (`routers/reviews_console.py`) ya pasaba el
    ámbito al servicio; éste es el mismo patrón.
    """
    reviews_dir = _reviews_dir(workspace)
    if not reviews_dir.exists():
        return []
    ambito = scope.partida_only()
    sources = []
    for source_dir in sorted(reviews_dir.iterdir()):
        if not source_dir.is_dir():
            continue
        # AUTORIZAR primero: una fuente fuera del ámbito no se lista ni se
        # cuenta, igual que no se entrega por ID.
        if not _fuente_en_ambito(source_dir, ambito):
            continue
        counters = _source_counters(source_dir)
        pkg_meta = _extract_package_meta(source_dir)
        sources.append({
            "source_id": source_dir.name,
            **counters,
            "origin": pkg_meta.get("origin"),
        })
    return sources


# ---------------------------------------------------------------------------
# Rutas HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, provider: GraphProvider = Depends(get_provider)):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "provider_name": provider.name,
            "workspace": settings.S9K_DEFAULT_WORKSPACE,
            "auth_user": guard,
        },
    )


@app.get("/graph", response_class=HTMLResponse)
def graph_view(request: Request):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "graph.html",
        {
            "workspace": settings.S9K_DEFAULT_WORKSPACE,
            "graph_limit": settings.S9K_GRAPH_LIMIT,
            "auth_user": guard,
        },
    )


@app.get("/status", response_class=HTMLResponse)
def status_view(request: Request, provider: GraphProvider = Depends(get_filtered_provider)):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    status_data = api_status.api_status(provider)
    return templates.TemplateResponse(request, "status.html", {"status": status_data, "auth_user": guard})


@app.get("/entity/{entity_id}", response_class=HTMLResponse)
def entity_view(
    request: Request,
    entity_id: str,
    provider: GraphProvider = Depends(get_filtered_provider),
):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    node = provider.entity(entity_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")

    outgoing, incoming = provider.relations_for_entity(entity_id)

    def _with_other_end(edge: dict, other_id_key: str) -> dict:
        serialized = serialize_edge(edge)
        other_node = provider.entity(edge.get(other_id_key))
        serialized["other_entity"] = serialize_node(other_node) if other_node else None
        return serialized

    return templates.TemplateResponse(
        request,
        "entity.html",
        {
            "entity": serialize_node(node),
            "outgoing": [_with_other_end(e, "to") for e in outgoing],
            "incoming": [_with_other_end(e, "from") for e in incoming],
        },
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_view(
    request: Request,
    workspace: str | None = None,
    status: str | None = None,
    job_type: str | None = None,
):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    # Mismo ámbito que /api/jobs: la cola es material de partida (M5a).
    scope = get_visibility_scope(request)
    status_info = jobs_db_status()
    counts = scoped_counts(scope, workspace=workspace) if status_info["ok"] else {}
    jobs = (
        scoped_jobs(scope, workspace=workspace, status=status, job_type=job_type)
        if status_info["ok"]
        else []
    )
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "status": status_info,
            "counts": counts,
            "jobs": jobs,
            "filters": {"workspace": workspace, "status": status, "job_type": job_type},
        },
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_view(request: Request, job_id: str):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    status_info = jobs_db_status()
    job = scoped_job(get_visibility_scope(request), job_id) if status_info["ok"] else None
    error = None if status_info["ok"] else status_info["error"]
    if status_info["ok"] and job is None:
        error = "job_not_found"
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {"job": job, "error": error},
    )


@app.get("/reviews", response_class=HTMLResponse)
def reviews_view(request: Request, workspace: str | None = None):
    guard = _require_reviewer_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    ws = _reviews_workspace(request, workspace)
    sources = _list_sources(ws, get_visibility_scope(request))
    return templates.TemplateResponse(
        request,
        "reviews.html",
        {"workspace": ws, "sources": sources},
    )


@app.get("/reviews/{source_id}", response_class=HTMLResponse)
def reviews_detail_view(request: Request, source_id: str, workspace: str | None = None):
    guard = _require_reviewer_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    ws = _reviews_workspace(request, workspace)
    if not _WORKSPACE_ID_RE.fullmatch(source_id or ""):
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")
    source_dir = _reviews_dir(ws) / source_id

    if not source_dir.exists():
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")

    # Fuera de ámbito -> 404, indistinguible de inexistente (mismo contrato que
    # `reviews_console.source_detail` y que `PolicyFilteredProvider.entity`: no
    # se confirma la existencia de material de otra partida).
    ambito = get_visibility_scope(request).partida_only()
    if not _fuente_en_ambito(source_dir, ambito):
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")

    counters = _source_counters(source_dir)

    # Metadatos del paquete
    pkg_meta = _extract_package_meta(source_dir)

    # Quality report: sus cifras cubren la fuente ENTERA y no traen atribución
    # por ítem. Se pueden publicar porque la fuente ya está autorizada: entrar
    # aquí exige que TODAS sus declaraciones caigan dentro del ámbito, así que
    # el informe no puede estar hablando de material de otra partida.
    quality_report = _extract_quality_report(source_dir)

    # Pipeline files state
    # La ruta absoluta en disco es detalle operativo: un revisor necesita saber
    # QUÉ hay en la cola, no dónde vive el fichero en el servidor. `redact_job`
    # ya aplicaba ese criterio; aquí se entregaba a cualquier reviewer.
    _detalle = get_visibility_scope(request).sees_operational_detail
    pipeline_files = [
        {
            "name": fname,
            "path": str(source_dir / fname) if _detalle else None,
            "exists": (source_dir / fname).exists(),
        }
        for fname in PIPELINE_FILE_NAMES
    ]

    # Review queue (pending items). La tabla publica su longitud ("Cola de
    # revisión (N ítems)"), que es otro contador: se cuenta lo que hay en una
    # fuente ya autorizada, no un total de directorio.
    rq_data = _read_json_safe(source_dir / "review_queue.json")
    if isinstance(rq_data, dict) and "items" in rq_data:
        rq_data = rq_data.get("items")
    review_queue: list[dict] = _items_enumerables(rq_data) or []

    # Approved payload preview
    approved_path = source_dir / "approved_payload.json"
    approved_exists = approved_path.exists()
    approved_items = _items_enumerables(
        _read_json_safe(approved_path), "approved") if approved_exists else None
    approved_count = None if approved_items is None else len(approved_items)
    preview_data = (approved_items or [])[:3]
    approved_preview = (
        json.dumps(preview_data, ensure_ascii=False, indent=2) if preview_data else ""
    )

    return templates.TemplateResponse(
        request,
        "reviews_detail.html",
        {
            "workspace": ws,
            "source_id": source_id,
            "counters": counters,
            "pkg_meta": pkg_meta,
            "quality_report": quality_report,
            "pipeline_files": pipeline_files,
            "review_queue": review_queue,
            "approved_exists": approved_exists,
            "approved_count": approved_count,
            "approved_preview": approved_preview,
        },
    )

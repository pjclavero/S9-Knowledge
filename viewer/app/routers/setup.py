"""Configuracion inicial: crear el PRIMER administrador desde el navegador.

UNA SOLA PANTALLA, a proposito. No es un asistente de varias pantallas ni
toca Nextcloud, bovedas, workspaces, partidas, servicios ni los interruptores
`S9K_PANEL_*`. Cierra la raiz: que una instalacion recien puesta se pueda usar
sin abrir un terminal.

COMO DESAPARECE ESTA RUTA
-------------------------
Por ESTADO PERSISTENTE leido en el SERVIDOR, no ocultando un enlace. El GET y
el POST comprueban lo mismo, por separado: con el bootstrap completado los dos
responden 404, de modo que un POST directo con `curl` tampoco sirve. No se
consulta `count_active_admins()`: ver `app.auth.bootstrap`.

EL ROL NO VIENE DEL NAVEGADOR
-----------------------------
El formulario NO tiene campo `role` y el endpoint NO lo acepta: esta operacion
crea por definicion el primer administrador. Un `role=viewer` (o cualquier
otro) enviado a mano se ignora, porque no hay parametro donde aterrice.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import audit, bootstrap
from app.auth import db as auth_db
from app.auth.config import get_auth_settings
from app.auth.csrf import (
    LOGIN_CSRF_MAX_AGE,
    SETUP_CSRF_COOKIE,
    SETUP_PURPOSE,
    issue_login_csrf,
    validate_login_csrf,
)
from app.auth.passwords import hash_password, validate_password

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

log = logging.getLogger("s9k.auth.setup")

router = APIRouter()

#: Ruta canonica de la configuracion inicial. Un solo sitio la nombra.
SETUP_PATH = "/setup/admin"

#: Frase de la pantalla de fail-closed. Mismo registro que
#: PROPOSALS_STORE_MISSING en /panel/review: dice que NO se sabe, dice que eso
#: no significa «instalacion nueva», y nombra la variable y la causa probable.
#: Ni rutas, ni trazas, ni nombres de maquina: repo publico.
ALMACEN_NO_DISPONIBLE = (
    "El almacen de autenticacion EXISTE pero NO SE PUEDE LEER. Esto no "
    "significa que sea una instalacion nueva: significa que no se sabe, y por "
    "eso no se ofrece crear ningun administrador. Lo habitual es que "
    "S9K_AUTH_DB_PATH apunte a un fichero que no es la base de autenticacion, "
    "a una base escrita por una version mas nueva del producto, o a un "
    "almacenamiento con permisos o dispositivo equivocados."
)


def _db_path() -> Path:
    return Path(get_auth_settings().S9K_AUTH_DB_PATH)


def _cookie_kwargs(cfg) -> dict:
    return {
        "key": SETUP_CSRF_COOKIE,
        "max_age": LOGIN_CSRF_MAX_AGE,
        "httponly": cfg.S9K_SESSION_HTTPONLY,
        "secure": cfg.S9K_SESSION_SECURE,
        "samesite": cfg.S9K_SESSION_SAMESITE,
        "path": "/",
    }


#: El otro desenlace del mismo codigo: la base que ESTABA y ya no esta. Se
#: dice distinto porque la causa es distinta y lo que el operador tiene que
#: mirar tambien: aqui no hay nada que reparar en la base, hay que averiguar
#: quien se la llevo.
ALMACEN_DESAPARECIDO = (
    "El almacen de autenticacion ESTABA y HA DESAPARECIDO con el servicio en "
    "marcha. Esto NO es una instalacion nueva: este proceso arranco con una "
    "base y ya no la encuentra, asi que no se ofrece crear ningun "
    "administrador. Lo habitual es un almacenamiento que se ha desmontado, una "
    "restauracion a medias, o un S9K_AUTH_DB_PATH que ha dejado de resolver al "
    "mismo sitio. Reponga la base y reinicie el servicio."
)


def _pantalla_almacen(request: Request, mensaje: str = ALMACEN_NO_DISPONIBLE) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/setup_error.html",
        {"codigo": bootstrap.AUTH_STORE_UNAVAILABLE, "mensaje": mensaje},
        status_code=503,
    )


def _guarda(request: Request):
    """Comprobacion de estado EN SERVIDOR. La ejecutan GET y POST, las dos.

    Devuelve `None` si se puede continuar; en otro caso, la respuesta con la
    que hay que cortar.
    """
    if not get_auth_settings().S9K_AUTH_ENABLED:
        # Sin autenticacion activa no hay administradores que crear: la
        # pantalla no existe. Si existiese, crearia usuarios en una base que
        # nadie consulta y dejaria el sello puesto para cuando se active.
        raise HTTPException(status_code=404)
    # LA BASE QUE ESTABA Y YA NO ESTA no es una primera instalacion. Va ANTES
    # de `estado_instalacion` porque esa funcion MIGRA, es decir CREA: si se
    # la deja llegar, fabrica una base vacia y la pantalla vuelve a servirse.
    # Y no se comprueba «no existe» a secas, porque el estado A legitimo --la
    # instalacion nueva-- exige justamente que se cree.
    if bootstrap.base_desaparecida(_db_path()):
        log.error(
            "[%s] la base de autenticacion desaparecio con el proceso vivo: "
            "configuracion inicial denegada (fail-closed).",
            bootstrap.AUTH_STORE_UNAVAILABLE,
        )
        return _pantalla_almacen(request, ALMACEN_DESAPARECIDO)

    try:
        estado = bootstrap.estado_instalacion(_db_path())
    except bootstrap.BootstrapStorageError as exc:
        # El detalle tecnico va al log del servidor, nunca al navegador.
        log.error("[%s] %s", exc.code, exc)
        return _pantalla_almacen(request)

    if estado.completado:
        # 404 y no 403: con el bootstrap completado esta ruta NO EXISTE
        # funcionalmente, y no hay nada que un cliente pueda hacer al respecto.
        raise HTTPException(status_code=404)
    return None


def _formulario(request: Request, errores: list[str], status_code: int = 200):
    cfg = get_auth_settings()
    token = issue_login_csrf(cfg.S9K_CSRF_SECRET, purpose=SETUP_PURPOSE)
    resp = templates.TemplateResponse(
        request,
        "auth/setup_admin.html",
        {"csrf_token": token, "errors": errores, "setup_path": SETUP_PATH},
        status_code=status_code,
    )
    resp.set_cookie(value=token, **_cookie_kwargs(cfg))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------------------
# GET /setup/admin
# ---------------------------------------------------------------------------

# `def` y no `async def` A PROPOSITO: el cuerpo es E/S SQLite bloqueante y un
# Argon2id de ~100 ms. En el bucle de eventos serializaria las peticiones (y
# de paso escondería la concurrencia que esta ruta tiene que resistir);
# en el threadpool de Starlette corren de verdad en paralelo, que es la
# situacion contra la que hay que ser atomico.
@router.get(SETUP_PATH, response_class=HTMLResponse)
def setup_admin_page(request: Request):
    cortar = _guarda(request)
    if cortar is not None:
        return cortar
    return _formulario(request, [])


# ---------------------------------------------------------------------------
# POST /setup/admin
# ---------------------------------------------------------------------------

@router.post(SETUP_PATH)
def setup_admin_submit(
    request: Request,
    # NINGUN campo es `Form(...)` obligatorio, y NO es descuido. Un campo
    # obligatorio que falta produce un 422 de validacion ANTES de que corra la
    # guarda, es decir: la comprobacion de estado en servidor no llega a
    # ejecutarse. Medido con el censo de rutas de este repo, que clasifico este
    # POST como «422 validacion antes del guardian» -> sonda inconcluyente. Con
    # los campos opcionales la guarda es SIEMPRE lo primero, y lo que falta se
    # responde con la pantalla y su mensaje, no con un volcado de validacion.
    username: str = Form(default=""),
    display_name: str = Form(default=""),
    password: str = Form(default=""),
    csrf_token: str = Form(default=""),
):
    # El POST NO confia en que el GET se haya hecho: repite la comprobacion.
    cortar = _guarda(request)
    if cortar is not None:
        return cortar

    cfg = get_auth_settings()

    cookie_token: Optional[str] = request.cookies.get(SETUP_CSRF_COOKIE)
    if not validate_login_csrf(
        csrf_token, cookie_token, secret=cfg.S9K_CSRF_SECRET, purpose=SETUP_PURPOSE
    ):
        return _formulario(
            request,
            ["Error de seguridad (CSRF). Recarga la pagina e intentalo de nuevo."],
            status_code=403,
        )

    username = (username or "").strip()
    errores: list[str] = []
    if not username:
        errores.append("El nombre de usuario no puede estar vacio.")
    if not password:
        errores.append("La contrasena no puede estar vacia.")
    # LAS MISMAS REGLAS que /admin/users/new: la misma funcion, no una copia.
    errores += validate_password(password, username)
    if errores:
        return _formulario(request, errores, status_code=400)

    # El hash se calcula FUERA de la transaccion: mantener el candado de
    # escritura durante un Argon2id alargaria la seccion critica sin ganar nada.
    pw_hash = hash_password(password)

    try:
        user = bootstrap.crear_primer_admin(
            _db_path(),
            username=username,
            display_name=display_name.strip() or username,
            password_hash=pw_hash,
            # Quien acaba de elegir esta contrasena no tiene nada que cambiar:
            # no se entrego por ningun canal de reparto. Y un campo `bool` mas
            # en el formulario es un campo mas que puede llegar con un valor
            # que no parsea, y entonces la validacion del cuerpo responde 422
            # ANTES de la guarda de estado.
            must_change_password=False,
        )
    except bootstrap.BootstrapCerrado:
        # Carrera perdida: otro navegador acaba de crear el primer
        # administrador. La ruta ya no existe.
        log.warning("[%s] alta de primer admin rechazada", bootstrap.BOOTSTRAP_YA_COMPLETADO)
        raise HTTPException(status_code=404)
    except ValueError as exc:
        codigo = str(exc)
        if codigo == bootstrap.BOOTSTRAP_USUARIO_DUPLICADO:
            return _formulario(request, ["El nombre de usuario ya existe."], status_code=400)
        return _formulario(request, ["El nombre de usuario no es valido."], status_code=400)

    try:
        with auth_db.get_conn(_db_path()) as conn:
            audit.log(
                conn, audit.USER_CREATED, "success",
                user_id=user.id, username_snapshot=user.username,
                metadata={"created_by": "setup", "role": user.role,
                          "bootstrap": bootstrap.BOOTSTRAP_COMPLETADO},
            )
    except Exception:  # pragma: no cover - la auditoria no revierte el alta
        log.error("no se pudo registrar el alta del primer administrador en auditoria")

    # A iniciar sesion: el bootstrap NO deja una sesion abierta sola. Quien
    # acaba de fijar la credencial la usa; asi la instalacion no queda con una
    # sesion de administrador emitida sin haber demostrado conocerla.
    resp = RedirectResponse(url="/login?message=bootstrap_ok", status_code=303)
    resp.delete_cookie(SETUP_CSRF_COOKIE, path="/")
    return resp

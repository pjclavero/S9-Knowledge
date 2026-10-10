# -*- coding: utf-8 -*-
"""Preflight del PRIMER ADMINISTRADOR: el recorrido completo, POR EFECTO.

ESTADO DE ESTE MODULO (antes de cualquier frase en presente de indicativo)
--------------------------------------------------------------------------
::

    CODE         PASS      el recorrido esta implementado y ejercido
    CALIBRATION  PASS      cada garantia tiene una mutacion que la pone roja
    RC-E2E       PENDING   no hay TLS real, ni navegador, ni VM: ensayo RC

Lo que este modulo demuestra es que SABE DISTINGUIR una instalacion en la que
el primer administrador se puede crear de las formas en que no se puede. NO
demuestra que una instalacion real entregue esa propiedad: eso es el ensayo
RC, cuyo guion esta en ``deploy/README.md`` y que NO se ha ejecutado.

POR QUE EXISTE: LO QUE EL PR-3 **NO** DEMUESTRA
------------------------------------------------
``preflight_https.py`` (PR-3) demuestra que el endpoint CONTESTA: handshake
TLS que verifica, nombre que coincide, y un ``GET`` que devuelve un codigo de
estado. Eso es necesario y NO es suficiente.

Un ``200`` dice que algo respondio. El defecto de rango 1 de este programa era
otro: el **POST** de ``/setup/admin`` entraba en bucle de 403 porque la cookie
CSRF sale con atributo ``Secure`` y sobre ``http://`` ningun cliente la
devuelve. Una instalacion puede tener un ``GET /setup/admin`` que responde
``200`` perfectamente y seguir siendo una instalacion en la que el primer
administrador NO se puede crear.

De ahi el criterio que este modulo implementa, literal:

  * ``/setup/admin`` COMPLETA REALMENTE EL FLUJO usando cookie ``Secure``;
  * **no basta ``GET 200``**;
  * hay que demostrar POST, CSRF, sesion y creacion del administrador;
  * tras completar el setup, el LOGIN funciona;
  * el estado PERSISTE tras reinicio.

El guardian de "no basta ``GET 200``" no es una frase de este docstring: es
``comprobar_recorrido_completo``, que exige que TODAS las fases se hayan
OBSERVADO y devuelve ``RECORRIDO_INCOMPLETO`` si falta una. Sin el, un
``GET`` correcto y cuatro fases sin ejercer darian rc=0.

DECISION D3 — ESTE MODULO NO LA REINTERPRETA
---------------------------------------------
``S9K_SESSION_SECURE=true`` permanece. Este modulo:

  * NO escribe configuracion y NO degrada ninguna cookie;
  * NO habla ``http://`` NUNCA. No hay un parametro para permitirlo, ni una
    rama que lo intente: la puerta estatica de ``preflight_https`` rechaza el
    HTTP plano ANTES de abrir socket alguno, y el cliente de aqui se niega a
    enviar una cookie ``Secure`` por un canal no cifrado -que es justo lo que
    produce el bucle de 403, y la razon por la que el bucle es REAL y no una
    simulacion-;
  * trata una cookie de setup que llega SIN ``Secure`` como un FALLO
    (``COOKIE_SETUP_SIN_SECURE``), porque esa es la forma que tendria la
    degradacion que D3 considero y DESCARTO.

Resolver el defecto debilitando la garantia fue considerado y descartado.
``S9K_SESSION_SECURE=false`` es SOLO opt-out de laboratorio.

AUTORIDADES QUE SE EXTIENDEN, NO SE DUPLICAN
---------------------------------------------
* ``deploy/scripts/preflight_https.py`` (PR-3). Se IMPORTA: su ``Hallazgo``,
  su lector de ``EnvironmentFile`` (``valor_de_env_file``), su lista cerrada
  de valores verdaderos (``es_verdadero``), su contexto TLS que nunca apaga
  la verificacion (``_contexto_o_hallazgo``) y sus dos puertas estaticas
  (``comprobar_esquema_https``, ``comprobar_cookie_secure_coherente``). Aqui
  no se reimplementa ninguna de las dos mitades: este modulo es el HERMANO
  que sigue el recorrido donde aquel lo dejo -el endpoint contesta- y empieza
  donde el criterio del operador exige -el administrador se crea-.
* El SELLO IRREVERSIBLE de ``viewer/app/auth/bootstrap.py``
  (``install_state['bootstrap_completed']``) y el predicado
  ``base_utilizable``. Este preflight **no inventa su propia idea de "el
  setup esta hecho"**: la lee por EFECTO, por donde el producto la publica,
  que es el 404 de ``/setup/admin`` que decide ``routers/setup.py::_guarda``.
  No se abre la base SQLite: sobre una instalacion remota ni se puede, y
  hacerlo seria una SEGUNDA autoridad sobre el mismo hecho.
* La ruta canonica es la del producto: ``routers/setup.py::SETUP_PATH``. Se
  replica como literal por la misma razon que ``preflight_https`` replica el
  criterio de estado -este guion corre FUERA del venv del visor, solo con
  biblioteca estandar- y el testigo CRUZA el literal contra el del producto
  para que no se separen en silencio.

SECRETOS
--------
Las credenciales NO viajan por ``argv`` ni se imprimen. Entran por un fichero
``0600`` (``--credenciales-desde``) o por ``stdin``, y lo unico que sale por
la salida estandar es el nombre de usuario; la contrasena no se registra en
ningun mensaje, ni en los de error.

USO
---
    python3 deploy/scripts/preflight_setup_admin.py \\
        --env-file /etc/s9-knowledge/viewer.env --modo bootstrap < cred.json

    python3 deploy/scripts/preflight_setup_admin.py \\
        --env-file /etc/s9-knowledge/viewer.env --modo persistencia < cred.json

``--modo bootstrap`` ejerce el recorrido completo y ESCRIBE (crea el primer
administrador). ``--modo persistencia`` es de SOLO LECTURA y es el que se
corre DESPUES de un reinicio: exige que el sello siga cerrando
``/setup/admin`` y que el login siga funcionando.

rc=0 solo si TODO el recorrido se observa. Cualquier otro rc significa
INSTALACION NO COMPLETA.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import ssl
import sys
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlsplit

_AQUI = Path(__file__).resolve().parent
if str(_AQUI) not in sys.path:
    sys.path.insert(0, str(_AQUI))

# AUTORIDAD DEL PR-3. Se importa, no se copia.
from preflight_https import (  # noqa: E402
    Hallazgo,
    comprobar_cookie_secure_coherente,
    comprobar_esquema_https,
    comprobar_url_declarada,
    es_verdadero,
    valor_de_env_file,
)
from preflight_https import _contexto_o_hallazgo  # noqa: E402

#: Ruta canonica del setup. MISMO literal que
#: ``viewer/app/routers/setup.py::SETUP_PATH``; el testigo cruza los dos.
SETUP_PATH = "/setup/admin"

#: Ruta de login del producto.
LOGIN_PATH = "/login"

#: Nombre de la cookie CSRF del setup. MISMO literal que
#: ``viewer/app/auth/csrf.py::SETUP_CSRF_COOKIE``; el testigo lo cruza.
SETUP_CSRF_COOKIE = "_s9k_setup_csrf"

#: Nombre de la cookie CSRF del login. MISMO literal que
#: ``viewer/app/auth/csrf.py::LOGIN_CSRF_COOKIE``; el testigo lo cruza.
LOGIN_CSRF_COOKIE = "_s9k_login_csrf"

#: Codigos con los que el producto redirige DESPUES de autenticar. Hoy
#: ``routers/auth.py::login_submit`` emite 302; se admite tambien 303 porque
#: la propiedad es "redirigio tras autenticar", no el numero exacto. El
#: testigo CRUZA esto contra el codigo que devuelve el producto real, de modo
#: que si cambiase a algo fuera del conjunto se veria.
ESTADOS_LOGIN_OK = frozenset({302, 303})

TIEMPO_LIMITE = 15.0

#: Presupuesto APARTE para el POST de ``/setup/admin``, y no es afinar un
#: numero: ese POST calcula un **Argon2id** para el alta del administrador. Su
#: coste nominal es de ~100 ms, pero Argon2id esta disenado para ser costoso y
#: en una maquina cargada -o con los nucleos ocupados por otra cosa- tarda
#: ordenes de magnitud mas. Con el presupuesto general de 15 s, un POST
#: perfectamente sano devolvia ``POST_NO_ALCANZABLE: TimeoutError``: un ROJO
#: FALSO sobre una instalacion correcta, que es justo lo que un preflight no
#: puede permitirse. Medido en este corte, con la suite completa en marcha.
#:
#: El resto de las fases conserva el presupuesto corto: son E/S de red sin
#: criptografia detras, y alargarlas solo retrasaria el diagnostico de un
#: endpoint que de verdad no contesta.
TIEMPO_LIMITE_POST = 180.0

#: Codigo con el que ``routers/setup.py`` responde cuando el almacen de
#: autenticacion existe pero no se puede leer, o estaba y desaparecio. Es el
#: FAIL-CLOSED del producto: no se ofrece crear ningun administrador porque
#: NO SE SABE si hay uno. Un preflight que lo leyese como "instalacion nueva"
#: convertiria el fail-closed del producto en un verde.
ESTADO_FAIL_CLOSED = 503


# ---------------------------------------------------------------------------
# Credenciales: nunca por argv, nunca impresas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Credenciales:
    """Usuario y contrasena de la prueba. ``__repr__`` NO revela la clave."""

    usuario: str
    password: str

    def __repr__(self) -> str:
        return "Credenciales(usuario=%r, password=<oculta>)" % (self.usuario,)

    __str__ = __repr__


def credenciales_desde_json(texto: str) -> Credenciales:
    """Lee ``{"usuario": ..., "password": ...}``.

    Lanza ``ValueError`` con un mensaje que NO incluye el contenido leido: un
    JSON mal formado que se volcase al log llevaria la contrasena consigo.
    """
    try:
        datos = json.loads(texto)
    except ValueError:
        raise ValueError(
            "las credenciales no son un JSON valido (no se muestra el "
            "contenido: llevaria la contrasena)") from None
    if not isinstance(datos, dict):
        raise ValueError("las credenciales no son un objeto JSON")
    usuario = datos.get("usuario") or datos.get("username")
    password = datos.get("password")
    if not isinstance(usuario, str) or not usuario.strip():
        raise ValueError("las credenciales no traen 'usuario'")
    if not isinstance(password, str) or not password:
        raise ValueError("las credenciales no traen 'password'")
    return Credenciales(usuario=usuario.strip(), password=password)


def leer_credenciales(ruta: Optional[str]) -> Credenciales:
    """Del fichero ``0600`` indicado, o de ``stdin``. Nunca de ``argv``.

    Si el fichero es legible por otros, se RECHAZA: un preflight que acepta
    una credencial en un fichero 0644 ensena a dejarla ahi.
    """
    if ruta is None:
        return credenciales_desde_json(sys.stdin.read())
    p = Path(ruta)
    modo = p.stat().st_mode
    if modo & 0o077:
        raise ValueError(
            "el fichero de credenciales tiene permisos %o: tiene que ser "
            "0600. No se lee una credencial que otros pueden leer."
            % (modo & 0o777,))
    return credenciales_desde_json(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Cliente HTTP con tarro de cookies. Se comporta como un cliente de verdad:
# una cookie `Secure` NO se devuelve por un canal sin cifrar.
# ---------------------------------------------------------------------------

@dataclass
class _Galleta:
    valor: str
    secure: bool
    httponly: bool


class ClienteConCookies:
    """Tarro de cookies normal sobre TLS verificado.

    POR QUE RESPETA ``Secure`` EN LUGAR DE IGNORARLO. Un cliente que devuelve
    siempre todas las cookies haria pasar el POST sobre HTTP plano y el
    defecto medido -el bucle de 403- se volveria INOBSERVABLE justo en el
    arnes que tiene que observarlo. Aqui la regla es la del navegador: una
    cookie marcada ``Secure`` solo se envia por ``https``. Esa es la razon por
    la que el negativo de HTTP plano de este corte es un bucle de 403 REAL y
    no una simulacion.
    """

    def __init__(self, url_base: str, ca_file: Optional[str] = None,
                 timeout: float = TIEMPO_LIMITE):
        partes = urlsplit(url_base)
        self.esquema = (partes.scheme or "").lower()
        self.host = partes.hostname or ""
        self.puerto = partes.port or (443 if self.esquema == "https" else 80)
        self.ca_file = ca_file
        self.timeout = timeout
        self.cookies: dict = {}
        self._hallazgo_ctx: Optional[Hallazgo] = None
        self._ctx: Optional[ssl.SSLContext] = None
        if self.esquema == "https":
            self._ctx, self._hallazgo_ctx = _contexto_o_hallazgo(
                ca_file, comprobar_nombre=True)

    # -- cookies ----------------------------------------------------------
    def _guardar(self, respuesta) -> None:
        """Guarda TODAS las cookies de la respuesta.

        POR QUE ``getheaders()`` Y NO ``getheader("Set-Cookie")``. Ese
        devuelve las cabeceras repetidas UNIDAS por ", ", y una respuesta de
        login trae varias (la sesion nueva y el borrado del token CSRF). La
        cadena unida no es un ``Set-Cookie`` valido -las fechas ``expires``
        llevan su propia coma-, asi que al parsearla se perdia la cookie de
        SESION y un login correcto se leia como "no emitio sesion". Medido en
        este corte contra el visor real.
        """
        for nombre_cab, crudo in respuesta.getheaders():
            if nombre_cab.lower() != "set-cookie" or not crudo.strip():
                continue
            galleta = SimpleCookie()
            try:
                galleta.load(crudo)
            except Exception:
                continue
            for nombre, morsel in galleta.items():
                if morsel.value == "":
                    # `delete_cookie` del producto: se va del tarro.
                    self.cookies.pop(nombre, None)
                    continue
                self.cookies[nombre] = _Galleta(
                    valor=morsel.value,
                    secure=bool(morsel["secure"]),
                    httponly=bool(morsel["httponly"]),
                )

    def _cabecera_cookie(self) -> dict:
        enviables = [
            "%s=%s" % (nombre, g.valor)
            for nombre, g in self.cookies.items()
            # LA REGLA DEL NAVEGADOR: `Secure` no viaja por canal sin cifrar.
            if (not g.secure) or self.esquema == "https"
        ]
        return {"Cookie": "; ".join(enviables)} if enviables else {}

    def tiene(self, nombre: str) -> bool:
        return nombre in self.cookies

    def galleta(self, nombre: str) -> Optional[_Galleta]:
        return self.cookies.get(nombre)

    # -- peticiones -------------------------------------------------------
    def _conexion(self):
        if self.esquema == "https":
            return http.client.HTTPSConnection(
                self.host, self.puerto, timeout=self.timeout, context=self._ctx)
        # Esta rama existe SOLO para el control positivo del arnes, que
        # reproduce el bucle de 403 contra un endpoint de laboratorio. El
        # preflight nunca llega aqui: `verificar` rechaza el HTTP plano en la
        # puerta estatica, antes de construir cliente alguno.
        return http.client.HTTPConnection(
            self.host, self.puerto, timeout=self.timeout)

    def _conexion_con(self, timeout: float):
        previo = self.timeout
        self.timeout = timeout
        try:
            return self._conexion()
        finally:
            self.timeout = previo

    def peticion(self, metodo: str, ruta: str, datos: Optional[dict] = None,
                 timeout: Optional[float] = None):
        """Devuelve ``(estado, cuerpo, destino)`` o lanza ``OSError``.

        ``timeout`` permite a una fase pedir su propio presupuesto; sin el se
        usa el general. Lo usa el POST del alta, que lleva un Argon2id detras.
        """
        if self._hallazgo_ctx is not None:
            raise _AlmacenIlegible(self._hallazgo_ctx)
        cabeceras = self._cabecera_cookie()
        cuerpo_env = None
        if datos is not None:
            cuerpo_env = urlencode(datos)
            cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        conexion = self._conexion_con(timeout if timeout else self.timeout)
        try:
            conexion.request(metodo, ruta, body=cuerpo_env, headers=cabeceras)
            respuesta = conexion.getresponse()
            estado = respuesta.status
            texto = respuesta.read().decode("utf-8", errors="replace")
            self._guardar(respuesta)
            destino = respuesta.getheader("Location", "")
        finally:
            conexion.close()
        return estado, texto, destino


class _AlmacenIlegible(Exception):
    def __init__(self, hallazgo: Hallazgo):
        super().__init__(hallazgo.mensaje)
        self.hallazgo = hallazgo


_TOKEN = re.compile(
    r'<input[^>]+name=["\']csrf_token["\'][^>]+value=["\']([^"\']+)["\']',
    re.IGNORECASE)
_TOKEN_INVERSO = re.compile(
    r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']csrf_token["\']',
    re.IGNORECASE)


def token_del_formulario(html: str) -> Optional[str]:
    """Extrae el ``csrf_token`` del formulario servido. ``None`` si no hay."""
    for patron in (_TOKEN, _TOKEN_INVERSO):
        m = patron.search(html)
        if m:
            return m.group(1)
    return None


def hay_cookie_de_sesion(cliente: "ClienteConCookies") -> bool:
    """``True`` si el login emitio ALGUNA cookie que no sea la del CSRF.

    POR QUE NO SE EXIGE EL NOMBRE. ``S9K_SESSION_COOKIE_NAME`` es
    configurable: atar la garantia al literal ``s9k_session`` haria que una
    instalacion que lo renombra -algo legitimo- se leyese como "no emitio
    sesion". Lo que la propiedad necesita es que el cliente salga del login
    con una credencial de sesion NUEVA, cualquiera sea su nombre; las dos
    cookies de CSRF se excluyen porque no autentican a nadie.
    """
    csrf = {LOGIN_CSRF_COOKIE, SETUP_CSRF_COOKIE}
    return any(nombre not in csrf for nombre in cliente.cookies)


# ---------------------------------------------------------------------------
# El recorrido: cada fase se OBSERVA, y se registra que se observo
# ---------------------------------------------------------------------------

@dataclass
class Recorrido:
    """Registro de QUE SE OBSERVO. El guardian de "no basta GET 200".

    Cada campo es una fase del criterio del operador. ``None`` significa NO
    OBSERVADA, que NO es lo mismo que fallida y NO se cuenta a favor.
    """

    get_formulario: Optional[int] = None
    cookie_secure: Optional[bool] = None
    token_presente: Optional[bool] = None
    post_completado: Optional[int] = None
    sello_cierra_setup: Optional[int] = None
    login_funciona: Optional[int] = None
    persistencia_tras_reinicio: Optional[bool] = None

    #: Fases que el modo en curso DEBE observar.
    FASES_BOOTSTRAP = ("get_formulario", "cookie_secure", "token_presente",
                       "post_completado", "sello_cierra_setup",
                       "login_funciona")
    FASES_PERSISTENCIA = ("sello_cierra_setup", "login_funciona",
                          "persistencia_tras_reinicio")

    def no_observadas(self, fases) -> list:
        return [f for f in fases if getattr(self, f) is None]


def comprobar_recorrido_completo(recorrido: Recorrido, fases) -> Optional[Hallazgo]:
    """EL GUARDIAN DE "NO BASTA ``GET 200``".

    Un ``GET`` que responde no es una instalacion en la que el primer
    administrador se puede crear. Si alguna fase del criterio del operador no
    se ha OBSERVADO, esto es un fallo con causa propia, y no un verde con una
    nota al pie. AUSENCIA != CERO.
    """
    faltan = recorrido.no_observadas(fases)
    if not faltan:
        return None
    return Hallazgo(
        "RECORRIDO_INCOMPLETO",
        "el recorrido del primer administrador NO se observo completo: "
        "faltan las fases %s. Un 'GET 200' de /setup/admin dice que algo "
        "respondio, no que el administrador se pueda crear: hay que "
        "demostrar POST, CSRF, sesion, creacion, sello y login. Lo no "
        "observado NO cuenta a favor." % (", ".join(sorted(faltan)),),
    )


def comprobar_get_del_formulario(cliente: ClienteConCookies,
                                 recorrido: Recorrido) -> Optional[Hallazgo]:
    """``GET /setup/admin``: la pantalla se sirve, con token y cookie ``Secure``."""
    try:
        estado, html, _ = cliente.peticion("GET", SETUP_PATH)
    except _AlmacenIlegible as exc:
        return exc.hallazgo
    except (OSError, ssl.SSLError) as exc:
        return Hallazgo(
            "SETUP_NO_ALCANZABLE",
            "no se pudo hacer GET %s: %s. Sin la pantalla de configuracion "
            "inicial no hay instalacion que completar."
            % (SETUP_PATH, type(exc).__name__),
        )
    recorrido.get_formulario = estado

    if estado == ESTADO_FAIL_CLOSED:
        return Hallazgo(
            "ALMACEN_DE_AUTH_NO_DISPONIBLE",
            "%s respondio %d: el producto ha FALLADO CERRADO porque el "
            "almacen de autenticacion existe y no se puede leer, o estaba y "
            "ha desaparecido. Eso NO es una instalacion nueva y NO se cuenta "
            "como instalacion completa: significa que no se sabe."
            % (SETUP_PATH, estado),
        )
    if estado == 404:
        return Hallazgo(
            "SETUP_YA_SELLADO",
            "%s responde 404 ANTES de crear ningun administrador: el sello "
            "de instalacion ya esta puesto (o la autenticacion esta "
            "desactivada). Esta no es una instalacion de fabrica, y este "
            "modo no puede demostrar nada sobre ella: use --modo "
            "persistencia." % (SETUP_PATH,),
        )
    if estado != 200:
        return Hallazgo(
            "SETUP_NO_SE_SIRVE",
            "%s respondio %d, no 200: la pantalla de configuracion inicial "
            "no se esta sirviendo." % (SETUP_PATH, estado),
        )

    galleta = cliente.galleta(SETUP_CSRF_COOKIE)
    if galleta is None:
        recorrido.cookie_secure = False
        return Hallazgo(
            "COOKIE_SETUP_AUSENTE",
            "%s respondio 200 pero NO entrego la cookie %r. Sin ella el POST "
            "no puede validar el CSRF y el recorrido no se puede completar."
            % (SETUP_PATH, SETUP_CSRF_COOKIE),
        )
    recorrido.cookie_secure = galleta.secure
    if not galleta.secure:
        return Hallazgo(
            "COOKIE_SETUP_SIN_SECURE",
            "la cookie %r llego SIN atributo Secure. Esta es exactamente la "
            "forma de la degradacion que la decision D3 considero y "
            "DESCARTO: el defecto no se resuelve quitandole Secure a la "
            "cookie (ni deduciendola de request.scheme), se resuelve "
            "entregando HTTPS. Una instalacion productiva que sirve el setup "
            "con cookie no-Secure NO se acepta." % (SETUP_CSRF_COOKIE,),
        )

    token = token_del_formulario(html)
    recorrido.token_presente = bool(token)
    if not token:
        return Hallazgo(
            "TOKEN_CSRF_AUSENTE",
            "el formulario de %s no trae ningun campo csrf_token. El POST "
            "seria rechazado y el administrador no se podria crear."
            % (SETUP_PATH,),
        )
    cliente._token_setup = token  # type: ignore[attr-defined]
    return None


def comprobar_post_crea_el_administrador(cliente: ClienteConCookies,
                                         cred: Credenciales,
                                         recorrido: Recorrido) -> Optional[Hallazgo]:
    """**EL POST**. Aqui es donde el defecto de rango 1 se manifestaba.

    Con la cookie ``Secure`` sobre HTTPS tiene que FUNCIONAR. Sobre HTTP
    plano, el cliente no devuelve la cookie, el producto no valida el CSRF y
    responde 403: el bucle. Por eso el 403 tiene causa propia y nombra el
    bucle, en vez de confundirse con "credenciales invalidas".
    """
    token = getattr(cliente, "_token_setup", None)
    if not token:
        return Hallazgo(
            "TOKEN_CSRF_AUSENTE",
            "no hay token de %s que enviar: el GET no lo entrego."
            % (SETUP_PATH,),
        )
    try:
        estado, html, destino = cliente.peticion(
            "POST", SETUP_PATH,
            datos={
                "username": cred.usuario,
                "display_name": cred.usuario,
                "password": cred.password,
                "csrf_token": token,
            },
            # Presupuesto propio: aqui dentro hay un Argon2id. Ver
            # TIEMPO_LIMITE_POST.
            timeout=TIEMPO_LIMITE_POST,
        )
    except _AlmacenIlegible as exc:
        return exc.hallazgo
    except (OSError, ssl.SSLError) as exc:
        return Hallazgo(
            "POST_NO_ALCANZABLE",
            "el POST a %s no llego a completarse: %s."
            % (SETUP_PATH, type(exc).__name__),
        )
    recorrido.post_completado = estado

    if estado == 403:
        return Hallazgo(
            "BUCLE_403_CSRF",
            "el POST a %s fue rechazado con 403 por validacion CSRF. Esto es "
            "EL DEFECTO MEDIDO: la cookie CSRF sale con atributo Secure y no "
            "ha vuelto, asi que el token del formulario no tiene con que "
            "compararse: el formulario se repinta y se vuelve a enviar "
            "indefinidamente, que es el BUCLE de 403. El "
            "primer administrador NO se puede crear. Causa habitual: la "
            "instalacion se esta sirviendo por HTTP plano. No se arregla "
            "poniendo S9K_SESSION_SECURE=false en produccion: se arregla "
            "entregando HTTPS." % (SETUP_PATH,),
        )
    if estado == ESTADO_FAIL_CLOSED:
        return Hallazgo(
            "ALMACEN_DE_AUTH_NO_DISPONIBLE",
            "el POST a %s respondio %d: fail-closed del almacen de "
            "autenticacion. No se ha creado ningun administrador y la "
            "instalacion NO esta completa." % (SETUP_PATH, estado),
        )
    if estado == 400:
        return Hallazgo(
            "ALTA_RECHAZADA",
            "el POST a %s respondio 400: el producto rechazo los datos del "
            "alta (usuario vacio o duplicado, o contrasena que no cumple la "
            "politica). No se muestra el detalle para no registrar la "
            "credencial." % (SETUP_PATH,),
        )
    if estado != 303:
        return Hallazgo(
            "ADMIN_NO_CREADO",
            "el POST a %s respondio %d; se esperaba 303 hacia el login, que "
            "es como el producto confirma que el primer administrador quedo "
            "creado dentro de la transaccion que pone el sello."
            % (SETUP_PATH, estado),
        )
    if "bootstrap_ok" not in (destino or ""):
        return Hallazgo(
            "ADMIN_NO_CREADO",
            "el POST a %s redirigio a %r, que no es el destino con el que el "
            "producto confirma el alta del primer administrador."
            % (SETUP_PATH, destino),
        )
    return None


def comprobar_sello_cierra_el_setup(cliente: ClienteConCookies,
                                    recorrido: Recorrido) -> Optional[Hallazgo]:
    """El SELLO del producto cierra ``/setup/admin``: 404 a partir de ahora.

    No se consulta la base: se lee la propiedad por donde el producto la
    publica. ``routers/setup.py::_guarda`` responde 404 -no 403- cuando el
    bootstrap esta completado, y lo hace en el GET y en el POST por separado,
    de modo que un POST directo tampoco sirve.
    """
    try:
        estado, _, _ = cliente.peticion("GET", SETUP_PATH)
    except _AlmacenIlegible as exc:
        return exc.hallazgo
    except (OSError, ssl.SSLError) as exc:
        return Hallazgo(
            "SETUP_NO_ALCANZABLE",
            "no se pudo comprobar el sello con un GET a %s: %s."
            % (SETUP_PATH, type(exc).__name__),
        )
    recorrido.sello_cierra_setup = estado
    if estado == ESTADO_FAIL_CLOSED:
        return Hallazgo(
            "ALMACEN_DE_AUTH_NO_DISPONIBLE",
            "al comprobar el sello, %s respondio %d (fail-closed). No se "
            "puede afirmar que la instalacion quedo sellada."
            % (SETUP_PATH, estado),
        )
    if estado != 404:
        return Hallazgo(
            "SELLO_NO_CIERRA_SETUP",
            "tras crear el primer administrador, %s sigue respondiendo %d en "
            "vez de 404: el sello irreversible de instalacion no esta "
            "cerrando la pantalla. Una instalacion que sigue ofreciendo "
            "crear el primer administrador permite que un desconocido cree "
            "otro." % (SETUP_PATH, estado),
        )
    return None


def comprobar_login_funciona(cliente_nuevo: ClienteConCookies,
                             cred: Credenciales,
                             recorrido: Recorrido) -> Optional[Hallazgo]:
    """TRAS COMPLETAR EL SETUP, EL LOGIN FUNCIONA. Con un cliente LIMPIO.

    El cliente es nuevo a proposito: reutilizar el del setup podria arrastrar
    estado y hacer pasar un login que en realidad no autentica.
    """
    try:
        estado, html, _ = cliente_nuevo.peticion("GET", LOGIN_PATH)
    except _AlmacenIlegible as exc:
        return exc.hallazgo
    except (OSError, ssl.SSLError) as exc:
        return Hallazgo(
            "LOGIN_NO_ALCANZABLE",
            "no se pudo hacer GET %s: %s." % (LOGIN_PATH, type(exc).__name__),
        )
    if estado != 200:
        recorrido.login_funciona = estado
        return Hallazgo(
            "LOGIN_NO_SE_SIRVE",
            "%s respondio %d, no 200: no hay pantalla de login donde usar "
            "las credenciales recien creadas." % (LOGIN_PATH, estado),
        )
    token = token_del_formulario(html)
    if not token:
        recorrido.login_funciona = 0
        return Hallazgo(
            "TOKEN_CSRF_AUSENTE",
            "el formulario de %s no trae csrf_token: el login no se puede "
            "enviar." % (LOGIN_PATH,),
        )
    try:
        estado, _, destino = cliente_nuevo.peticion(
            "POST", LOGIN_PATH,
            datos={"username": cred.usuario, "password": cred.password,
                   "csrf_token": token},
        )
    except (OSError, ssl.SSLError) as exc:
        recorrido.login_funciona = 0
        return Hallazgo(
            "LOGIN_NO_ALCANZABLE",
            "el POST de login no llego a completarse: %s."
            % (type(exc).__name__,),
        )
    recorrido.login_funciona = estado
    if estado == 403:
        return Hallazgo(
            "BUCLE_403_CSRF",
            "el POST de login fue rechazado con 403 por CSRF: la cookie no "
            "ha vuelto. Mismo defecto que en el setup, mismo diagnostico.",
        )
    if estado == 401:
        return Hallazgo(
            "CREDENCIALES_RECHAZADAS",
            "el login respondio 401: el producto NO acepta las credenciales "
            "que acaba de crear el setup. Completar el alta y que la "
            "credencial no sirva es un fallo de la instalacion, no del "
            "operador. (No se registra la credencial usada.)",
        )
    if estado not in ESTADOS_LOGIN_OK:
        return Hallazgo(
            "LOGIN_NO_FUNCIONA",
            "el login con las credenciales del primer administrador "
            "respondio %d; se esperaba una redireccion %s. Completar el "
            "setup y no poder "
            "entrar deja la instalacion inservible. (No se registra la "
            "credencial usada.)" % (estado, sorted(ESTADOS_LOGIN_OK)),
        )
    if not hay_cookie_de_sesion(cliente_nuevo):
        return Hallazgo(
            "SESION_NO_EMITIDA",
            "el login redirigio (%d) pero no entrego ninguna cookie de "
            "sesion: no hay sesion con la que usar la instalacion. Una "
            "redireccion sin sesion se ve en el navegador como un login que "
            "vuelve al login." % (estado,),
        )
    return None


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Entrada:
    url: Optional[str]
    session_secure: bool
    credenciales: Credenciales
    ca_file: Optional[str] = None
    timeout: float = TIEMPO_LIMITE
    modo: str = "bootstrap"


def _puerta_estatica(entrada: Entrada) -> list:
    """Las DOS puertas estaticas del PR-3, reutilizadas tal cual.

    Antes de abrir un socket: si no hay URL declarada, si no es ``https``, o
    si es HTTP plano con cookie ``Secure``, no se sondea NADA. Sondear
    ``http://`` aqui seria el fallback que D3 prohibe.
    """
    falta = comprobar_url_declarada(entrada.url)
    if falta is not None:
        return [falta]
    url = (entrada.url or "").strip()
    hallazgos = [
        h for h in (
            comprobar_esquema_https(url),
            comprobar_cookie_secure_coherente(url, entrada.session_secure),
        ) if h is not None
    ]
    return hallazgos


def verificar_bootstrap(entrada: Entrada) -> tuple:
    """Recorrido COMPLETO: GET, POST, sello y login. ESCRIBE."""
    recorrido = Recorrido()
    estaticos = _puerta_estatica(entrada)
    if estaticos:
        # Sin HTTPS no se sondea. El recorrido queda SIN OBSERVAR, y el
        # guardian lo dira: no se cuenta a favor.
        return estaticos + [comprobar_recorrido_completo(
            recorrido, Recorrido.FASES_BOOTSTRAP)], recorrido

    url = (entrada.url or "").strip()
    cliente = ClienteConCookies(url, entrada.ca_file, entrada.timeout)

    for paso in (
        lambda: comprobar_get_del_formulario(cliente, recorrido),
        lambda: comprobar_post_crea_el_administrador(
            cliente, entrada.credenciales, recorrido),
        lambda: comprobar_sello_cierra_el_setup(cliente, recorrido),
        lambda: comprobar_login_funciona(
            ClienteConCookies(url, entrada.ca_file, entrada.timeout),
            entrada.credenciales, recorrido),
    ):
        hallazgo = paso()
        if hallazgo is not None:
            # Se corta, y el guardian anade lo que quedo sin observar.
            incompleto = comprobar_recorrido_completo(
                recorrido, Recorrido.FASES_BOOTSTRAP)
            return ([hallazgo] + ([incompleto] if incompleto else []),
                    recorrido)

    incompleto = comprobar_recorrido_completo(recorrido, Recorrido.FASES_BOOTSTRAP)
    return ([incompleto] if incompleto else []), recorrido


def verificar_persistencia(entrada: Entrada) -> tuple:
    """SOLO LECTURA, para DESPUES del reinicio.

    El estado persiste si, con el proceso reiniciado: el sello sigue cerrando
    ``/setup/admin`` (404) y el login del administrador sigue funcionando. Las
    dos cosas, porque cada una sola se puede satisfacer por accidente -un 404
    lo da tambien una ruta que no existe, y un login que funciona sin sello
    dejaria la pantalla de alta abierta-.
    """
    recorrido = Recorrido()
    estaticos = _puerta_estatica(entrada)
    if estaticos:
        return estaticos + [comprobar_recorrido_completo(
            recorrido, Recorrido.FASES_PERSISTENCIA)], recorrido

    url = (entrada.url or "").strip()
    sello = comprobar_sello_cierra_el_setup(
        ClienteConCookies(url, entrada.ca_file, entrada.timeout), recorrido)
    if sello is not None:
        if recorrido.sello_cierra_setup == 200:
            # El caso que importa: el reinicio REABRIO la pantalla de alta.
            sello = Hallazgo(
                "ESTADO_NO_PERSISTE",
                "tras el reinicio, %s vuelve a ofrecer crear el primer "
                "administrador (200). El sello de instalacion NO ha "
                "sobrevivido: la base de autenticacion no es durable (ruta "
                "en tmpfs, volumen no montado, o un contenedor que recrea su "
                "almacen en cada arranque). Cualquiera que llegue antes que "
                "el operador se crea el administrador."
                % (SETUP_PATH,),
            )
        recorrido.persistencia_tras_reinicio = False
        incompleto = comprobar_recorrido_completo(
            recorrido, Recorrido.FASES_PERSISTENCIA)
        return [sello] + ([incompleto] if incompleto else []), recorrido

    login = comprobar_login_funciona(
        ClienteConCookies(url, entrada.ca_file, entrada.timeout),
        entrada.credenciales, recorrido)
    if login is not None:
        recorrido.persistencia_tras_reinicio = False
        if recorrido.login_funciona not in (None,) and \
                recorrido.login_funciona not in ESTADOS_LOGIN_OK:
            login = Hallazgo(
                "ESTADO_NO_PERSISTE",
                "tras el reinicio el sello sigue puesto, pero el login del "
                "primer administrador ya NO funciona (%s). La instalacion "
                "queda inservible y sin pantalla de alta a la que volver: es "
                "el peor de los desenlaces. (No se registra la credencial.) "
                "Causa original: %s"
                % (recorrido.login_funciona, login.causa),
            )
        incompleto = comprobar_recorrido_completo(
            recorrido, Recorrido.FASES_PERSISTENCIA)
        return [login] + ([incompleto] if incompleto else []), recorrido

    recorrido.persistencia_tras_reinicio = True
    incompleto = comprobar_recorrido_completo(
        recorrido, Recorrido.FASES_PERSISTENCIA)
    return ([incompleto] if incompleto else []), recorrido


def verificar(entrada: Entrada) -> list:
    """Lista vacia = el recorrido se OBSERVO completo en este momento."""
    if entrada.modo == "persistencia":
        hallazgos, _ = verificar_persistencia(entrada)
    else:
        hallazgos, _ = verificar_bootstrap(entrada)
    return hallazgos


def codigo_de_salida(hallazgos: list) -> int:
    """rc=0 SOLO sin hallazgos. Cualquier fallo => INSTALACION NO COMPLETA."""
    return 0 if not hallazgos else 1


def entrada_desde_env_file(ruta: Path, cred: Credenciales, modo: str,
                           timeout: float = TIEMPO_LIMITE) -> Entrada:
    return Entrada(
        url=valor_de_env_file(ruta, "S9K_PUBLIC_BASE_URL"),
        session_secure=es_verdadero(valor_de_env_file(ruta, "S9K_SESSION_SECURE")),
        ca_file=valor_de_env_file(ruta, "S9K_TLS_CA_FILE") or None,
        credenciales=cred,
        timeout=timeout,
        modo=modo,
    )


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Preflight del primer administrador (por efecto). Las "
                    "credenciales NO se pasan por argv.")
    ap.add_argument("--env-file", help="EnvironmentFile del visor (viewer.env)")
    ap.add_argument("--url", help="URL publica (sobreescribe la del fichero)")
    ap.add_argument("--session-secure", choices=["true", "false"])
    ap.add_argument("--ca-file", help="almacen de confianza declarado")
    ap.add_argument("--credenciales-desde",
                    help="fichero 0600 con {\"usuario\":...,\"password\":...}; "
                         "si se omite, se leen de stdin")
    ap.add_argument("--modo", choices=["bootstrap", "persistencia"],
                    default="bootstrap")
    ap.add_argument("--timeout", type=float, default=TIEMPO_LIMITE)
    args = ap.parse_args(argv)

    try:
        cred = leer_credenciales(args.credenciales_desde)
    except (ValueError, OSError) as exc:
        print("FALLO(CREDENCIALES_NO_LEIDAS): %s" % (exc,))
        print("INSTALACION NO COMPLETA: no se pudo ejercer el recorrido.")
        return 2

    if args.env_file:
        base = entrada_desde_env_file(Path(args.env_file), cred, args.modo,
                                      args.timeout)
    else:
        base = Entrada(url=None, session_secure=True, credenciales=cred,
                       modo=args.modo, timeout=args.timeout)
    entrada = Entrada(
        url=args.url if args.url else base.url,
        session_secure=(es_verdadero(args.session_secure)
                        if args.session_secure else base.session_secure),
        ca_file=args.ca_file or base.ca_file,
        credenciales=cred,
        timeout=args.timeout,
        modo=args.modo,
    )

    hallazgos = verificar(entrada)
    for h in hallazgos:
        print(str(h))
    rc = codigo_de_salida(hallazgos)
    if rc == 0:
        if entrada.modo == "persistencia":
            print("OK: tras el reinicio el sello sigue cerrando %s y el "
                  "login del administrador %r sigue funcionando."
                  % (SETUP_PATH, cred.usuario))
        else:
            print("OK: el recorrido del primer administrador se observo "
                  "COMPLETO (GET, cookie Secure, POST con CSRF, alta, sello "
                  "y login) para el usuario %r." % (cred.usuario,))
        print("    Esto NO es el ensayo RC (ver deploy/README.md).")
    else:
        print("INSTALACION NO COMPLETA: el primer administrador no se pudo "
              "crear y verificar.")
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

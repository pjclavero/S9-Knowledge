# -*- coding: utf-8 -*-
"""Testigo del preflight del PRIMER ADMINISTRADOR (PR-4, USABLE-V1).

ESTADO DE ESTE TESTIGO (antes de cualquier frase en presente de indicativo)
---------------------------------------------------------------------------
::

    CODE         PASS      el recorrido se ejerce contra el visor REAL
    CALIBRATION  PASS      ver scripts/calibracion/mutaciones_pr4_*.py
    RC-E2E       PENDING   sin nginx, sin systemd, sin VM, sin navegador

QUE SE EJERCE DE VERDAD AQUI
----------------------------
El VISOR REAL (``app.main:app``), arrancado como PROCESO SEPARADO por
``uvicorn`` con ``--ssl-certfile``/``--ssl-keyfile`` y un certificado
autofirmado generado en el momento, con ``S9K_AUTH_ENABLED=true`` y
``S9K_SESSION_SECURE=true`` -el default seguro de D3, sin tocar-. Contra el se
recorre el flujo entero: ``GET /setup/admin``, se guarda la cookie ``Secure``
de verdad, se envia el ``POST`` con su token CSRF, se comprueba que el
administrador queda creado, que el SELLO cierra la pantalla con un 404, y que
el login posterior funciona.

El REINICIO es un reinicio de verdad: se mata el proceso del visor y se
arranca OTRO sobre la misma base. Es el mismo criterio que
``viewer/tests/test_auth_persistence.py::test_password_sobrevive_a_un_reinicio_en_proceso_nuevo``,
que mide la durabilidad con un PROCESO nuevo y no con una conexion nueva.

NO SE SIMULA NADA DE LA FRONTERA QUE SE MIDE. No se parchea ``ssl``, ni la
validacion CSRF, ni el estado del bootstrap: la cookie ``Secure`` la pone el
producto, el token lo firma el producto y el 404 posterior lo decide el sello
de ``viewer/app/auth/bootstrap.py``.

EL CONTROL POSITIVO DE RESULTADO CONOCIDO
-----------------------------------------
``test_control_positivo_el_bucle_403_sobre_http_plano_es_real`` arranca el
visor real SIN TLS y con ``S9K_SESSION_SECURE=true``, que es la configuracion
exacta del defecto de rango 1, y comprueba que el ``POST`` entra en 403. Sin
esa fila, un arnes que mide ausencia de defectos podria estar ciego y sus
ceros no valdrian nada. Con ella consta que este instrumento SI VE el defecto
cuando el defecto esta.

EN QUE **NO** SE PARECE AL ESCENARIO REAL
------------------------------------------
Aqui no hay nginx, ni systemd, ni una VM limpia, ni un navegador, ni DNS, ni
una CA real: VM110/VM111 estan apagadas y no se encienden. El TLS es
``uvicorn`` con un autofirmado declarado, no un terminador de produccion. Nada
de esto demuestra que una instalacion real entregue la propiedad; demuestra
que el preflight DISTINGUE una instalacion en la que el primer administrador
se puede crear de las formas en que no se puede. El recorrido completo sobre
maquina real es el ENSAYO RC (guion en ``deploy/README.md``), **PENDIENTE**.

CREDENCIALES
------------
Generadas en el momento con ``secrets``, distintas en cada caso, existentes
solo en la base temporal del caso. No viajan por ``argv`` -el preflight las
lee de un fichero ``0600`` o de ``stdin``- y no se imprimen.
"""
from __future__ import annotations

import http.client
import http.server
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import preflight_setup_admin as ps  # noqa: E402

# REUSO DELIBERADO del andamio del PR-3: el generador de certificados
# autofirmados es exactamente el mismo instrumento, y duplicarlo crearia dos
# andamios que pueden separarse en silencio. Los dos modulos viven en este
# mismo directorio.
from test_preflight_https import _certificado  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"

#: Margen de arranque del visor real. Es generoso a proposito: en una corrida
#: larga con CPU en contencion un margen justo produce un rojo que parece del
#: producto y es del utillaje.
ARRANQUE_MAX = 60.0


def _puerto_libre() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _credenciales() -> ps.Credenciales:
    """Credenciales de LABORATORIO, nuevas en cada caso.

    No corresponden a ninguna credencial real de ningun entorno y solo existen
    en la base temporal del caso que las crea.
    """
    return ps.Credenciales(
        usuario="lab-admin-%s" % secrets.token_hex(3),
        password="lab-%s-%s" % (secrets.token_hex(8), secrets.token_hex(4)),
    )


# ---------------------------------------------------------------------------
# El visor REAL, como proceso separado, con y sin TLS
# ---------------------------------------------------------------------------

class VisorReal:
    """Un proceso ``uvicorn`` sirviendo ``app.main:app``.

    ``reiniciar()`` MATA el proceso y arranca otro sobre LA MISMA base: eso es
    lo que hace del reinicio un reinicio y no una reconexion. El puerto cambia
    a proposito -lo que se mide es que el ESTADO persiste, no el puerto-.
    """

    def __init__(self, db_path: Path, cert=None, extra_env=None):
        self.db_path = db_path
        self.cert = cert
        self.extra_env = dict(extra_env or {})
        self.proc = None
        self.puerto = None
        self._arrancar()

    @property
    def esquema(self) -> str:
        return "https" if self.cert else "http"

    @property
    def base_url(self) -> str:
        return "%s://localhost:%d" % (self.esquema, self.puerto)

    def _entorno(self) -> dict:
        env = dict(os.environ)
        env.update({
            "S9K_AUTH_ENABLED": "true",
            "S9K_AUTH_DB_PATH": str(self.db_path),
            # EL DEFAULT SEGURO DE D3, TAL CUAL. Este testigo no lo degrada ni
            # cuando sirve por HTTP: el caso de HTTP plano es el CONTROL
            # POSITIVO del defecto, y degradar aqui lo haria desaparecer.
            "S9K_SESSION_SECURE": "true",
            "S9K_CSRF_SECRET": "csrf-de-laboratorio-%s" % secrets.token_hex(8),
            "S9K_GRAPH_PROVIDER": "mock",
            "PYTHONPATH": str(VIEWER),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        env.update(self.extra_env)
        return env

    def _arrancar(self) -> None:
        self.puerto = _puerto_libre()
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
               "--host", "127.0.0.1", "--port", str(self.puerto),
               "--log-level", "error"]
        if self.cert:
            cert, clave = self.cert
            cmd += ["--ssl-certfile", str(cert), "--ssl-keyfile", str(clave)]
        self.proc = subprocess.Popen(
            cmd, cwd=str(VIEWER), env=self._entorno(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self._esperar_a_que_conteste()

    def _esperar_a_que_conteste(self) -> None:
        """Espera por el PID explicito y por la CONDICION FINAL.

        No se espera por una cadena de ``pgrep`` ni por un ``sleep`` fijo: se
        comprueba (a) que el proceso sigue vivo por su PID, y (b) que el
        endpoint CONTESTA. Las dos cosas, porque un proceso vivo que no
        escucha y un endpoint que contesta son hechos distintos.
        """
        limite = time.time() + ARRANQUE_MAX
        ultimo = ""
        while time.time() < limite:
            if self.proc.poll() is not None:
                salida = self.proc.stdout.read() if self.proc.stdout else ""
                pytest.fail("el visor real murio al arrancar (rc=%s):\n%s"
                            % (self.proc.returncode, salida[-3000:]))
            try:
                if self.cert:
                    ctx = ssl.create_default_context(cafile=str(self.cert[0]))
                    con = http.client.HTTPSConnection(
                        "localhost", self.puerto, timeout=5, context=ctx)
                else:
                    con = http.client.HTTPConnection(
                        "localhost", self.puerto, timeout=5)
                try:
                    con.request("GET", "/api/status")
                    con.getresponse().read()
                    return
                finally:
                    con.close()
            except Exception as exc:  # noqa: BLE001 - se reintenta
                ultimo = "%s: %s" % (type(exc).__name__, exc)
            time.sleep(0.2)
        pytest.fail("el visor real no contesto en %.0fs (ultimo error: %s)"
                    % (ARRANQUE_MAX, ultimo))

    def reiniciar(self) -> None:
        """REINICIO DE VERDAD: proceso nuevo sobre la misma base."""
        self.parar()
        self._arrancar()

    def parar(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        pid = self.proc.pid
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=15)
        # Se espera por el PID EXPLICITO, no por una cadena de comando.
        limite = time.time() + 10
        while time.time() < limite:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)


def _base_de_fabrica(tmp_path: Path) -> Path:
    """Una base de autenticacion MIGRADA Y VACIA: el estado de fabrica.

    Se crea con la funcion del producto (``app.auth.db.ensure_migrated``), no a
    mano: el fichero tiene que existir porque la guarda de seguridad del visor
    se niega a arrancar con una ruta de base inexistente, y lo que define
    "fabrica" es que no haya usuarios ni sello, no que no haya fichero.
    """
    import app.auth.db as auth_db  # noqa: PLC0415 - viewer en sys.path (conftest raiz)

    db = tmp_path / "auth-fabrica.db"
    auth_db.ensure_migrated(db)
    return db


@pytest.fixture
def cert_localhost(tmp_path):
    return _certificado(tmp_path, "localhost", "setupadmin")


@pytest.fixture
def visor_https_de_fabrica(tmp_path, cert_localhost):
    visor = VisorReal(_base_de_fabrica(tmp_path), cert=cert_localhost)
    try:
        yield visor
    finally:
        visor.parar()


def _entrada(visor: VisorReal, cred: ps.Credenciales, modo: str = "bootstrap",
             ca=None) -> ps.Entrada:
    return ps.Entrada(
        url=visor.base_url,
        session_secure=True,
        credenciales=cred,
        ca_file=str(ca) if ca else None,
        modo=modo,
        # Presupuesto del utillaje para las fases de red. El POST usa el suyo
        # (`TIEMPO_LIMITE_POST`), que el preflight impone por dentro.
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# EL RECORRIDO COMPLETO contra el visor REAL
# ---------------------------------------------------------------------------

def test_el_recorrido_completo_del_primer_admin_sobre_https(
        visor_https_de_fabrica, cert_localhost):
    """GET, cookie Secure, POST con CSRF, admin creado, sello y login.

    Este es el caso que el PR-3 NO podia demostrar: que el POST pasa.
    """
    cred = _credenciales()
    entrada = _entrada(visor_https_de_fabrica, cred, ca=cert_localhost[0])

    hallazgos, recorrido = ps.verificar_bootstrap(entrada)

    assert hallazgos == [], (
        "el recorrido del primer administrador deberia completarse sobre "
        "HTTPS con cookie Secure, y ha dado hallazgos: %s"
        % [str(h) for h in hallazgos])
    # Cada fase, OBSERVADA con su codigo. No basta que la lista este vacia.
    assert recorrido.get_formulario == 200
    assert recorrido.cookie_secure is True, (
        "la cookie de setup del producto tiene que llegar con atributo "
        "Secure: es la decision D3, y aqui se OBSERVA, no se presupone")
    assert recorrido.token_presente is True
    assert recorrido.post_completado == 303, (
        "el POST de /setup/admin sobre HTTPS tiene que completarse con 303; "
        "un 403 aqui seria el bucle del defecto de rango 1")
    assert recorrido.sello_cierra_setup == 404, (
        "tras el alta, el sello irreversible tiene que cerrar /setup/admin")
    assert recorrido.login_funciona in ps.ESTADOS_LOGIN_OK, (
        "tras completar el setup el login tiene que funcionar; el producto "
        "devolvio %s" % (recorrido.login_funciona,))


def test_el_codigo_de_login_del_producto_esta_en_el_conjunto_declarado(
        visor_https_de_fabrica, cert_localhost):
    """CRUCE: el conjunto declarado contiene lo que el producto REALMENTE emite.

    ``ESTADOS_LOGIN_OK`` es una replica de una decision del producto
    (``routers/auth.py::login_submit`` redirige con 302). Si el producto
    cambiase a un codigo fuera del conjunto, el preflight empezaria a decir
    "el login no funciona" sobre un login que funciona. Esta prueba lo cruza
    por EFECTO en vez de por lectura del fuente.
    """
    cred = _credenciales()
    entrada = _entrada(visor_https_de_fabrica, cred, ca=cert_localhost[0])
    hallazgos, recorrido = ps.verificar_bootstrap(entrada)
    assert hallazgos == [], [str(h) for h in hallazgos]
    assert recorrido.login_funciona in ps.ESTADOS_LOGIN_OK, (
        "el producto redirige el login con %s, que NO esta en el conjunto "
        "declarado %s: la replica se ha separado del producto."
        % (recorrido.login_funciona, sorted(ps.ESTADOS_LOGIN_OK)))


def test_tras_el_reinicio_el_sello_y_el_admin_siguen_ahi(
        visor_https_de_fabrica, cert_localhost):
    """PERSISTENCIA con un PROCESO NUEVO sobre la misma base."""
    cred = _credenciales()
    ca = cert_localhost[0]
    hallazgos, _ = ps.verificar_bootstrap(_entrada(visor_https_de_fabrica, cred, ca=ca))
    assert hallazgos == [], [str(h) for h in hallazgos]

    visor_https_de_fabrica.reiniciar()

    hallazgos, recorrido = ps.verificar_persistencia(
        _entrada(visor_https_de_fabrica, cred, modo="persistencia", ca=ca))
    assert hallazgos == [], (
        "tras reiniciar el proceso del visor, el administrador y el sello "
        "deberian seguir ahi; hallazgos: %s" % [str(h) for h in hallazgos])
    assert recorrido.sello_cierra_setup == 404
    assert recorrido.login_funciona in ps.ESTADOS_LOGIN_OK
    assert recorrido.persistencia_tras_reinicio is True


def test_persistencia_sobre_una_instalacion_de_fabrica_dice_que_no_persiste(
        visor_https_de_fabrica, cert_localhost):
    """Control negativo de la persistencia: sin admin, NO persiste.

    Es la forma que tendria una base no durable: tras el reinicio la pantalla
    de alta vuelve a ofrecerse. Aqui se produce sin reinicio -la base nunca
    tuvo admin-, que es el mismo estado observable.
    """
    cred = _credenciales()
    hallazgos, recorrido = ps.verificar_persistencia(
        _entrada(visor_https_de_fabrica, cred, modo="persistencia",
                 ca=cert_localhost[0]))
    causas = [h.causa for h in hallazgos]
    assert "ESTADO_NO_PERSISTE" in causas, (
        "una instalacion que sigue ofreciendo /setup/admin no tiene estado "
        "persistido; causas obtenidas: %s" % causas)
    assert recorrido.persistencia_tras_reinicio is False
    assert ps.codigo_de_salida(hallazgos) != 0


# ---------------------------------------------------------------------------
# CONTROL POSITIVO DE RESULTADO CONOCIDO: el bucle de 403 es real
# ---------------------------------------------------------------------------

def test_control_positivo_el_bucle_403_sobre_http_plano_es_real(tmp_path):
    """El DEFECTO DE RANGO 1, reproducido contra el visor REAL.

    Visor real, ``S9K_SESSION_SECURE=true`` (sin degradar nada) y servido por
    HTTP PLANO: el ``GET`` responde 200 y entrega la cookie con atributo
    ``Secure``; un cliente normal no la devuelve por un canal sin cifrar; el
    ``POST`` no valida el CSRF y responde 403. El administrador NO se puede
    crear.

    POR QUE ESTA FILA ES OBLIGATORIA. Todo lo demas de este testigo mide
    AUSENCIA de defecto. Un instrumento que solo mide ausencia puede estar
    ciego, y entonces sus ceros no valen. Esta fila tiene resultado CONOCIDO y
    demuestra que el instrumento ve el defecto cuando esta.

    Esto NO es un fallback a HTTP del preflight: el preflight nunca habla
    ``http://`` -``verificar`` lo rechaza en la puerta estatica, y eso lo
    comprueba ``test_el_preflight_nunca_sondea_http_plano``-. Aqui se llama al
    CLIENTE directamente, en laboratorio, para fabricar el defecto.
    """
    visor = VisorReal(_base_de_fabrica(tmp_path), cert=None)
    try:
        assert visor.esquema == "http"
        cred = _credenciales()
        cliente = ps.ClienteConCookies(visor.base_url, timeout=20.0)
        recorrido = ps.Recorrido()

        # El GET funciona perfectamente: 200, con token y con cookie Secure.
        hallazgo_get = ps.comprobar_get_del_formulario(cliente, recorrido)
        assert recorrido.get_formulario == 200, (
            "sobre HTTP plano el GET de /setup/admin responde 200: eso es "
            "justo lo que hace enganosa la verificacion por GET")
        assert recorrido.cookie_secure is True, (
            "el producto tiene que seguir poniendo Secure sobre HTTP: si lo "
            "degradase por el esquema de la peticion, D3 estaria violada")
        # Y EL GET NO DA NINGUN HALLAZGO: formulario servido, token
        # presente, cookie Secure. Verificar por GET aqui daria VERDE sobre
        # una instalacion en la que el administrador no se puede crear. Es
        # exactamente lo que este corte existe para cerrar.
        assert hallazgo_get is None, (
            "sobre HTTP plano el GET de /setup/admin es impecable; si diese "
            "hallazgo, el defecto se veria antes del POST y este control "
            "positivo no estaria midiendo lo que dice medir. Dio: %s"
            % (hallazgo_get,))

        # Y AHORA EL POST: el bucle de 403, por efecto.
        cliente2 = ps.ClienteConCookies(visor.base_url, timeout=20.0)
        rec2 = ps.Recorrido()
        ps.comprobar_get_del_formulario(cliente2, rec2)
        hallazgo = ps.comprobar_post_crea_el_administrador(cliente2, cred, rec2)
        assert rec2.post_completado == 403, (
            "EL CONTROL POSITIVO HA FALLADO: sobre HTTP plano con cookie "
            "Secure el POST de /setup/admin deberia dar 403 (bucle CSRF) y "
            "dio %s. Si esto no es 403, este testigo NO puede ver el defecto "
            "de rango 1 y sus verdes no valen." % (rec2.post_completado,))
        assert hallazgo is not None and hallazgo.causa == "BUCLE_403_CSRF", (
            "el 403 tiene que nombrarse como BUCLE_403_CSRF, no como un "
            "error genérico; se obtuvo: %s" % (hallazgo,))
        assert "bucle" in hallazgo.mensaje.lower()
    finally:
        visor.parar()


# ---------------------------------------------------------------------------
# Endpoints de laboratorio: las formas que el visor real no fabrica solo
# ---------------------------------------------------------------------------

class _StubSetup:
    """Endpoint TLS que responde lo que se le diga en cada fase.

    Existe para fabricar estados que el producto correcto NO produce -un
    ``GET`` que va bien y un sello que no cierra, o un 503 de almacen
    corrupto- sin tener que corromper una base de verdad. Lo que se mide con
    el es la CAPACIDAD DE DISTINGUIR del preflight, no el comportamiento del
    producto: eso ya lo miden los casos contra el visor real.
    """

    def __init__(self, cert: Path, clave: Path, *, estado_get=200,
                 estado_post=303, estado_sello=404, con_cookie=True,
                 cookie_secure=True, con_token=True, estado_login_post=302,
                 con_cookie_sesion=True):
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _responder(self, estado, cuerpo=b"", cookie=None, destino=None):
                self.send_response(estado)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                if destino:
                    self.send_header("Location", destino)
                self.end_headers()
                if cuerpo:
                    self.wfile.write(cuerpo)

            def do_GET(self):  # noqa: N802
                if self.path.startswith(ps.LOGIN_PATH):
                    cuerpo = (
                        b'<form method="post"><input type="hidden" '
                        b'name="csrf_token" value="tok-login"></form>')
                    galleta = "%s=tok-login; Path=/; Secure; HttpOnly" % (
                        ps.LOGIN_CSRF_COOKIE,)
                    return self._responder(200, cuerpo, cookie=galleta)
                stub.gets += 1
                if stub.gets > 1:
                    # Segundo GET = comprobacion del sello.
                    return self._responder(stub.estado_sello, b"ya")
                cuerpo = b'<form method="post">'
                if stub.con_token:
                    cuerpo += (b'<input type="hidden" name="csrf_token" '
                               b'value="tok-setup">')
                cuerpo += b"</form>"
                galleta = None
                if stub.con_cookie:
                    galleta = "%s=tok-setup; Path=/" % (ps.SETUP_CSRF_COOKIE,)
                    if stub.cookie_secure:
                        galleta += "; Secure"
                    galleta += "; HttpOnly"
                return self._responder(stub.estado_get, cuerpo, cookie=galleta)

            def do_POST(self):  # noqa: N802
                longitud = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(longitud)
                if self.path.startswith(ps.LOGIN_PATH):
                    if stub.estado_login_post not in ps.ESTADOS_LOGIN_OK:
                        return self._responder(stub.estado_login_post, b"no")
                    galleta_sesion = None
                    if stub.con_cookie_sesion:
                        galleta_sesion = (
                            "s9k_session=sesion-de-laboratorio; Path=/; "
                            "Secure; HttpOnly")
                    return self._responder(
                        stub.estado_login_post, b"", destino="/",
                        cookie=galleta_sesion)
                stub.posts += 1
                destino = ("/login?message=bootstrap_ok"
                           if stub.estado_post == 303 else None)
                return self._responder(stub.estado_post, b"", destino=destino)

            def log_message(self, *a):
                return

        self.gets = 0
        self.posts = 0
        self.estado_get = estado_get
        self.estado_post = estado_post
        self.estado_sello = estado_sello
        self.con_cookie = con_cookie
        self.cookie_secure = cookie_secure
        self.con_token = con_token
        self.estado_login_post = estado_login_post
        self.con_cookie_sesion = con_cookie_sesion

        class _Silencioso(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                return

        self.httpd = _Silencioso(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert), keyfile=str(clave))
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.puerto = self.httpd.server_address[1]
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.hilo.start()

    @property
    def base_url(self) -> str:
        return "https://localhost:%d" % (self.puerto,)

    def cerrar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _entrada_stub(stub, cred, ca, modo="bootstrap") -> ps.Entrada:
    return ps.Entrada(url=stub.base_url, session_secure=True,
                      credenciales=cred, ca_file=str(ca), modo=modo,
                      timeout=10.0)


def test_un_get_200_sin_post_no_basta_para_declarar_la_instalacion_completa(
        tmp_path, cert_localhost):
    """EL GUARDIAN DE «NO BASTA GET 200».

    El endpoint sirve el formulario perfectamente -200, token, cookie
    ``Secure``- y rechaza el ``POST`` con 403. Si "responde" bastase, esto
    seria un verde.
    """
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_get=200, estado_post=403)
    try:
        hallazgos, recorrido = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert recorrido.get_formulario == 200
        assert "BUCLE_403_CSRF" in causas, causas
        assert "RECORRIDO_INCOMPLETO" in causas, (
            "las fases no ejercidas tienen que CONSTAR como no observadas; "
            "causas: %s" % causas)
        assert ps.codigo_de_salida(hallazgos) != 0
        # Y lo que falta se NOMBRA, no se insinua.
        incompleto = [h for h in hallazgos if h.causa == "RECORRIDO_INCOMPLETO"][0]
        assert "sello_cierra_setup" in incompleto.mensaje
        assert "login_funciona" in incompleto.mensaje
    finally:
        stub.cerrar()


def test_el_sello_que_no_cierra_el_setup_es_un_fallo(tmp_path, cert_localhost):
    """El POST va bien pero ``/setup/admin`` sigue sirviendose: 200 != sellado."""
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_post=303, estado_sello=200)
    try:
        hallazgos, recorrido = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert "SELLO_NO_CIERRA_SETUP" in causas, causas
        assert recorrido.sello_cierra_setup == 200
        assert ps.codigo_de_salida(hallazgos) != 0
    finally:
        stub.cerrar()


def test_la_cookie_de_setup_sin_secure_se_rechaza(tmp_path, cert_localhost):
    """La degradacion que D3 descarto, detectada: cookie sin ``Secure``."""
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, cookie_secure=False)
    try:
        hallazgos, recorrido = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert "COOKIE_SETUP_SIN_SECURE" in causas, causas
        assert recorrido.cookie_secure is False
        detalle = [h for h in hallazgos if h.causa == "COOKIE_SETUP_SIN_SECURE"][0]
        assert "D3" in detalle.mensaje
    finally:
        stub.cerrar()


def test_el_fail_closed_de_un_almacen_corrupto_no_se_lee_como_instalacion_nueva(
        tmp_path, cert_localhost):
    """503 del producto = NO SE SABE. Nunca "instalacion nueva", nunca verde."""
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_get=503)
    try:
        hallazgos, _ = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert "ALMACEN_DE_AUTH_NO_DISPONIBLE" in causas, causas
        detalle = [h for h in hallazgos
                   if h.causa == "ALMACEN_DE_AUTH_NO_DISPONIBLE"][0]
        assert "NO es una instalacion nueva" in detalle.mensaje
        assert ps.codigo_de_salida(hallazgos) != 0
    finally:
        stub.cerrar()


def test_sin_token_csrf_en_el_formulario_el_recorrido_falla(tmp_path, cert_localhost):
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, con_token=False)
    try:
        hallazgos, _ = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert "TOKEN_CSRF_AUSENTE" in causas, causas
    finally:
        stub.cerrar()


def test_sin_cookie_de_setup_el_recorrido_falla(tmp_path, cert_localhost):
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, con_cookie=False)
    try:
        hallazgos, _ = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert "COOKIE_SETUP_AUSENTE" in causas, causas
    finally:
        stub.cerrar()


# ---------------------------------------------------------------------------
# D3: HTTP plano, rechazado SIN sondear
# ---------------------------------------------------------------------------

def test_el_preflight_nunca_sondea_http_plano(tmp_path, cert_localhost):
    """HTTP plano -> ROJO con causa, y NI UNA peticion al endpoint.

    El negativo obligatorio de este corte. Que la causa salga no basta: hay
    que comprobar que NO se abrio socket, porque sondear ``http://`` seria
    exactamente el fallback que D3 prohibe.
    """
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave)
    try:
        entrada = ps.Entrada(
            url="http://localhost:%d" % stub.puerto,
            session_secure=True, credenciales=_credenciales(),
            ca_file=str(cert), timeout=5.0)
        hallazgos, recorrido = ps.verificar_bootstrap(entrada)
        causas = [h.causa for h in hallazgos]

        # PRIMERO el hecho mas fuerte, y por eso primero: que NO SE TOCO el
        # endpoint. Si esta comprobacion fuese la ultima, una mutacion que
        # vacia la puerta estatica enrojeceria por "falta la causa
        # ESQUEMA_NO_HTTPS" y el rojo NO nombraria el fallback, que es el
        # defecto real. Cada rojo tiene que decir su causa, no solo el color.
        assert stub.gets == 0 and stub.posts == 0, (
            "FALLBACK A HTTP: el preflight hizo %d GET y %d POST contra una "
            "URL http://. No se sondea HTTP plano: la decision D3 lo "
            "prohibe." % (stub.gets, stub.posts))
        assert recorrido.get_formulario is None, (
            "FALLBACK A HTTP: se registro un codigo de GET (%s) para una URL "
            "http://, luego se hablo con el endpoint."
            % (recorrido.get_formulario,))
        assert "ESQUEMA_NO_HTTPS" in causas, causas
        assert "COOKIE_SECURE_SOBRE_HTTP" in causas, (
            "la causa del HTTP plano tiene que nombrar POR QUE rompe -la "
            "cookie Secure que no vuelve-, no solo que es HTTP; causas: %s"
            % causas)
        assert "RECORRIDO_INCOMPLETO" in causas, (
            "con HTTP plano no se ejerce NADA, y eso tiene que constar como "
            "no observado en vez de contarse a favor; causas: %s" % causas)
        assert ps.codigo_de_salida(hallazgos) != 0
    finally:
        stub.cerrar()


def test_sin_url_publica_declarada_es_un_fallo(tmp_path):
    """AUSENCIA != CERO: sin URL declarada no hay "no aplica"."""
    hallazgos = ps.verificar(ps.Entrada(
        url=None, session_secure=True, credenciales=_credenciales()))
    causas = [h.causa for h in hallazgos]
    assert "URL_PUBLICA_NO_DECLARADA" in causas, causas
    assert ps.codigo_de_salida(hallazgos) != 0


@pytest.mark.parametrize("causa", ["ESQUEMA_NO_HTTPS", "RECORRIDO_INCOMPLETO",
                                   "SELLO_NO_CIERRA_SETUP",
                                   "ALMACEN_DE_AUTH_NO_DISPONIBLE"])
def test_cualquier_hallazgo_impide_declarar_la_instalacion_completa(causa):
    assert ps.codigo_de_salida([ps.Hallazgo(causa, "da igual el texto")]) != 0, (
        "un hallazgo de causa %s tiene que IMPEDIR DECLARAR LA INSTALACION "
        "COMPLETA con rc != 0; con rc=0 el despliegue seguiria adelante sobre "
        "una instalacion en la que el primer administrador no se puede crear."
        % causa)


def test_sin_hallazgos_el_codigo_es_cero():
    assert ps.codigo_de_salida([]) == 0, (
        "sin hallazgos el codigo tiene que ser 0: un preflight que nunca da "
        "verde se desactiva y deja de proteger nada.")


def test_un_login_que_redirige_sin_emitir_sesion_es_un_fallo(cert_localhost):
    """302 sin cookie de sesion: en el navegador, el login vuelve al login."""
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, con_cookie_sesion=False)
    try:
        hallazgos, _ = ps.verificar_bootstrap(
            _entrada_stub(stub, _credenciales(), cert))
        causas = [h.causa for h in hallazgos]
        assert "SESION_NO_EMITIDA" in causas, (
            "una redireccion de login sin cookie de sesion no autentica a "
            "nadie; causas: %s" % causas)
        assert ps.codigo_de_salida(hallazgos) != 0
    finally:
        stub.cerrar()


# ---------------------------------------------------------------------------
# El guardian del recorrido, directamente
# ---------------------------------------------------------------------------

def test_el_guardian_nombra_cada_fase_no_observada():
    recorrido = ps.Recorrido(get_formulario=200, cookie_secure=True,
                             token_presente=True)
    hallazgo = ps.comprobar_recorrido_completo(
        recorrido, ps.Recorrido.FASES_BOOTSTRAP)
    assert hallazgo is not None
    assert hallazgo.causa == "RECORRIDO_INCOMPLETO"
    for fase in ("post_completado", "sello_cierra_setup", "login_funciona"):
        assert fase in hallazgo.mensaje, (
            "la fase %s no observada tiene que NOMBRARSE" % fase)
    assert "GET 200" in hallazgo.mensaje


def test_el_post_del_alta_tiene_presupuesto_propio_por_el_argon2():
    """El POST del alta NO puede compartir el presupuesto corto de la red.

    POR QUE ES UNA PRUEBA Y NO UN COMENTARIO. Con el presupuesto general de
    15 s, un POST perfectamente sano devolvia
    ``POST_NO_ALCANZABLE: TimeoutError`` cuando la maquina estaba cargada,
    porque dentro de ese POST el producto calcula un Argon2id. Un preflight
    que da ROJO FALSO sobre una instalacion correcta es peor que no tenerlo:
    ensena a ignorarlo. Medido en este corte con la suite completa en marcha.

    Lo que se fija es la RELACION -el POST tiene mas presupuesto que el
    resto-, no un numero concreto.
    """
    assert ps.TIEMPO_LIMITE_POST > ps.TIEMPO_LIMITE * 4, (
        "el POST del alta lleva un Argon2id detras y necesita un presupuesto "
        "holgado frente al general (%s vs %s): si se igualan, vuelve el rojo "
        "falso por TimeoutError en una maquina cargada."
        % (ps.TIEMPO_LIMITE_POST, ps.TIEMPO_LIMITE))


def test_el_guardian_calla_cuando_todo_se_observo():
    recorrido = ps.Recorrido(get_formulario=200, cookie_secure=True,
                             token_presente=True, post_completado=303,
                             sello_cierra_setup=404, login_funciona=302)
    assert ps.comprobar_recorrido_completo(
        recorrido, ps.Recorrido.FASES_BOOTSTRAP) is None


# ---------------------------------------------------------------------------
# CRUCES con el producto: los literales replicados no se separan en silencio
# ---------------------------------------------------------------------------

def test_la_ruta_de_setup_es_la_del_producto():
    from app.routers.setup import SETUP_PATH

    assert ps.SETUP_PATH == SETUP_PATH, (
        "la ruta replicada en el preflight se ha separado de "
        "routers/setup.py::SETUP_PATH")


def test_los_nombres_de_cookie_son_los_del_producto():
    from app.auth.csrf import LOGIN_CSRF_COOKIE, SETUP_CSRF_COOKIE

    assert ps.SETUP_CSRF_COOKIE == SETUP_CSRF_COOKIE
    assert ps.LOGIN_CSRF_COOKIE == LOGIN_CSRF_COOKIE


def test_el_estado_de_fail_closed_es_el_del_producto():
    """El 503 no es un numero elegido aqui: es el que sirve `routers/setup.py`."""
    import inspect

    from app.routers import setup as setup_router

    fuente = inspect.getsource(setup_router._pantalla_almacen)
    assert "503" in fuente, (
        "routers/setup.py ya no responde 503 en el fail-closed del almacen: "
        "ESTADO_FAIL_CLOSED del preflight se ha quedado obsoleto")
    assert ps.ESTADO_FAIL_CLOSED == 503


# ---------------------------------------------------------------------------
# Secretos: ni en argv, ni en la salida, ni en ficheros legibles por otros
# ---------------------------------------------------------------------------

def test_las_credenciales_no_se_representan_nunca():
    cred = ps.Credenciales(usuario="u", password="secreto-de-prueba-xyz")
    assert "secreto-de-prueba-xyz" not in repr(cred)
    assert "secreto-de-prueba-xyz" not in str(cred)
    assert "oculta" in repr(cred)


def test_un_fichero_de_credenciales_legible_por_otros_se_rechaza(tmp_path):
    f = tmp_path / "cred.json"
    f.write_text(json.dumps({"usuario": "u", "password": "p" * 12}),
                 encoding="utf-8")
    os.chmod(f, 0o644)
    with pytest.raises(ValueError) as exc:
        ps.leer_credenciales(str(f))
    assert "0600" in str(exc.value)


def test_un_fichero_0600_se_lee(tmp_path):
    f = tmp_path / "cred.json"
    f.write_text(json.dumps({"usuario": "u", "password": "p" * 12}),
                 encoding="utf-8")
    os.chmod(f, 0o600)
    cred = ps.leer_credenciales(str(f))
    assert cred.usuario == "u"


def test_un_json_invalido_no_vuelca_su_contenido():
    with pytest.raises(ValueError) as exc:
        ps.credenciales_desde_json('{"password": "no-deberia-aparecer-aqui')
    assert "no-deberia-aparecer-aqui" not in str(exc.value)


def test_el_cli_no_acepta_credenciales_por_argv():
    """No hay ``--password`` ni ``--usuario``: no se pueden pasar por argv.

    Se comprueba por EFECTO -el parser las rechaza- y ademas sobre la ayuda
    generada, que es el inventario real de opciones del CLI.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout

    # `--credenciales` NO entra en la lista: es abreviatura legitima de
    # `--credenciales-desde`, que es precisamente la via correcta (un fichero
    # 0600), no una credencial en la linea de comandos.
    for opcion in ("--password", "--usuario", "--username", "--clave"):
        with redirect_stderr(io.StringIO()):
            with pytest.raises(SystemExit) as exc:
                ps.main([opcion, "x"])
        assert exc.value.code != 0, (
            "%s deberia ser una opcion DESCONOCIDA: una credencial en argv "
            "queda en la lista de procesos y en el historial" % opcion)

    ayuda = io.StringIO()
    with redirect_stdout(ayuda):
        with pytest.raises(SystemExit):
            ps.main(["--help"])
    texto = ayuda.getvalue()
    assert "--credenciales-desde" in texto
    for prohibida in ("--password", "--usuario", "--username"):
        assert prohibida not in texto


def test_el_mensaje_del_fallo_de_login_no_lleva_la_credencial(tmp_path, cert_localhost):
    """Un rojo que lleve la contrasena al log es una fuga."""
    cert, clave = cert_localhost
    # El stub RECHAZA el login con 401: el camino que produce el hallazgo.
    stub = _StubSetup(cert, clave, estado_login_post=401)
    try:
        cred = ps.Credenciales(usuario="u-lab", password="clave-que-no-debe-salir")
        cliente = ps.ClienteConCookies(stub.base_url, str(cert), timeout=10.0)
        recorrido = ps.Recorrido()
        hallazgo = ps.comprobar_login_funciona(cliente, cred, recorrido)
        assert hallazgo is not None and hallazgo.causa == "CREDENCIALES_RECHAZADAS", (
            "un 401 del login tiene que nombrarse; se obtuvo: %s" % (hallazgo,))
        assert "clave-que-no-debe-salir" not in str(hallazgo), (
            "FUGA: el mensaje del fallo lleva la contrasena")
    finally:
        stub.cerrar()

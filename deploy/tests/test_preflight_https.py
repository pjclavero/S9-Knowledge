# -*- coding: utf-8 -*-
"""Testigo del preflight de la via HTTPS (PR-3, USABLE-V1).

QUE SE EJERCE DE VERDAD AQUI
----------------------------
No se parchea ``ssl`` ni se simula el resultado: cada caso LEVANTA UN
ENDPOINT TLS LOCAL con un certificado autofirmado generado en el momento
(``openssl``) y el preflight abre el socket contra el. La verificacion es por
EFECTO en el sentido literal: handshake real, ``GET`` real, codigo de estado
real.

EN QUE SE PARECE AL ESCENARIO REAL Y EN QUE NO
-----------------------------------------------
Se parece en lo que el preflight mide: TLS de verdad, cadena verificada
contra un almacen declarado, hostname check del modulo ``ssl``, respuesta
HTTP leida del socket. Y en los negativos: un listener TLS que acepta y
cierra sin hablar HTTP es exactamente la forma de un terminador TLS sin
backend.

NO se parece en todo lo demas, y conviene decirlo: aqui no hay nginx, ni
systemd, ni una VM limpia, ni un navegador, ni el recorrido de crear el
primer administrador, ni un reinicio. Nada de esto demuestra que la
instalacion entrega HTTPS; demuestra que el preflight SABE DISTINGUIR una
via HTTPS que contesta de las cinco formas en que no lo hace. El recorrido
completo es el ENSAYO RC (guion en ``deploy/README.md``), PENDIENTE.
"""
from __future__ import annotations

import http.server
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import preflight_https as ph  # noqa: E402

VALIDATE_SH = _SCRIPTS / "validate_deploy.sh"


# ---------------------------------------------------------------------------
# Utillaje: certificados y servidores TLS reales
# ---------------------------------------------------------------------------

def _openssl_o_fallar() -> str:
    import shutil
    ruta = shutil.which("openssl")
    if ruta is None:
        # NO se omite: un `skip` aqui seria un verde que no mide nada, y este
        # testigo es el instrumento de un calibrador. Que falte la herramienta
        # es un fallo del entorno, y tiene que verse.
        pytest.fail("openssl no esta disponible: el testigo de la via HTTPS "
                    "no puede generar certificados y NO puede dar verde.")
    return ruta


def _certificado(tmp: Path, nombre_comun: str, etiqueta: str):
    """Genera un autofirmado con SAN = `nombre_comun`. Devuelve (cert, key)."""
    cert = tmp / ("cert-%s.pem" % etiqueta)
    clave = tmp / ("key-%s.pem" % etiqueta)
    r = subprocess.run(
        [_openssl_o_fallar(), "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(clave), "-out", str(cert), "-days", "2",
         "-subj", "/CN=%s" % nombre_comun,
         "-addext", "subjectAltName=DNS:%s" % nombre_comun],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, "openssl fallo generando el certificado: %s" % r.stderr[-500:]
    return cert, clave


class _ServidorTLS:
    """Servidor HTTPS local que responde `estado` en cualquier ruta."""

    def __init__(self, cert: Path, clave: Path, estado: int = 200):
        clase = self._handler(estado)

        class _Silencioso(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                # El cliente cierra en cuanto ha leido la respuesta; el
                # BrokenPipeError resultante es ruido del utillaje, no un
                # resultado. Silenciarlo aqui evita confundir la salida del
                # calibrador con un fallo del producto.
                return

        self.httpd = _Silencioso(("127.0.0.1", 0), clase)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert), keyfile=str(clave))
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.puerto = self.httpd.server_address[1]
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.hilo.start()

    @staticmethod
    def _handler(estado: int):
        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):  # noqa: N802
                cuerpo = b'{"ok": true}'
                self.send_response(estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *a):  # silencio
                return
        return H

    def cerrar(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.hilo.join(timeout=5)


class _ListenerMudo:
    """Acepta el handshake TLS y CIERRA sin hablar HTTP.

    Es la forma exacta de "el terminador TLS esta levantado pero detras no hay
    nada": la configuracion esta escrita y el endpoint no contesta.
    """

    def __init__(self, cert: Path, clave: Path):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(certfile=str(cert), keyfile=str(clave))
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.puerto = self.sock.getsockname()[1]
        self.parar = threading.Event()
        self.hilo = threading.Thread(target=self._servir, daemon=True)
        self.hilo.start()

    def _servir(self):
        self.sock.settimeout(0.5)
        while not self.parar.is_set():
            try:
                cliente, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            try:
                tls = self.ctx.wrap_socket(cliente, server_side=True)
                tls.close()
            except Exception:
                try:
                    cliente.close()
                except Exception:
                    pass

    def cerrar(self):
        self.parar.set()
        self.hilo.join(timeout=5)
        try:
            self.sock.close()
        except Exception:
            pass


@pytest.fixture
def certificado_localhost(tmp_path):
    return _certificado(tmp_path, "localhost", "localhost")


@pytest.fixture
def certificado_otro_nombre(tmp_path):
    return _certificado(tmp_path, "otro.invalido", "otro")


# ---------------------------------------------------------------------------
# POSITIVO: via HTTPS que verifica y contesta
# ---------------------------------------------------------------------------

def test_https_que_verifica_y_contesta_no_da_hallazgos(certificado_localhost):
    cert, clave = certificado_localhost
    srv = _ServidorTLS(cert, clave, estado=200)
    try:
        hallazgos = ph.verificar(ph.Entrada(
            url="https://localhost:%d" % srv.puerto,
            session_secure=True, ca_file=str(cert), timeout=5.0))
    finally:
        srv.cerrar()
    assert hallazgos == [], [str(h) for h in hallazgos]
    assert ph.codigo_de_salida(hallazgos) == 0


def test_un_401_tambien_cuenta_como_que_contesto(certificado_localhost):
    """Criterio heredado de `check_viewer`: 401 = el visor esta y pide auth."""
    cert, clave = certificado_localhost
    srv = _ServidorTLS(cert, clave, estado=401)
    try:
        hallazgos = ph.verificar(ph.Entrada(
            url="https://localhost:%d" % srv.puerto,
            session_secure=True, ca_file=str(cert), timeout=5.0))
    finally:
        srv.cerrar()
    assert hallazgos == [], [str(h) for h in hallazgos]


# ---------------------------------------------------------------------------
# NEGATIVO OBLIGATORIO: HTTP plano con cookie Secure
# ---------------------------------------------------------------------------

def test_http_plano_con_cookie_secure_es_instalacion_no_valida():
    """EL CASO MEDIDO. El preflight falla y NOMBRA la causa."""
    hallazgos = ph.verificar(ph.Entrada(
        url="http://127.0.0.1:8088", session_secure=True))
    causas = [h.causa for h in hallazgos]
    assert "COOKIE_SECURE_SOBRE_HTTP" in causas, causas
    assert "ESQUEMA_NO_HTTPS" in causas, causas
    assert ph.codigo_de_salida(hallazgos) != 0
    texto = "\n".join(str(h) for h in hallazgos)
    assert "bucle de 403" in texto
    assert "primer administrador" in texto


def test_nunca_se_sondea_http_plano(monkeypatch):
    """D3: PROHIBIDO cualquier fallback a HTTP para hacer pasar la instalacion.

    Si el preflight sondeara la URL HTTP, las comprobaciones por efecto se
    ejecutarian. Se observa que NO se las llama.
    """
    llamadas = []
    for nombre in ("comprobar_cadena_de_certificado",
                   "comprobar_nombre_del_certificado",
                   "comprobar_endpoint_responde"):
        monkeypatch.setattr(ph, nombre,
                            lambda *a, _n=nombre, **k: llamadas.append(_n))
    ph.verificar(ph.Entrada(url="http://127.0.0.1:8088", session_secure=True))
    assert llamadas == [], (
        "FALLBACK_A_HTTP: con una URL http:// el preflight sondeo %s. D3 lo "
        "prohibe: sin HTTPS no hay nada que sondear." % llamadas)


def test_http_plano_sin_cookie_secure_sigue_siendo_no_https():
    """El opt-out de laboratorio NO convierte HTTP plano en instalable."""
    hallazgos = ph.verificar(ph.Entrada(
        url="http://127.0.0.1:8088", session_secure=False))
    causas = [h.causa for h in hallazgos]
    assert causas == ["ESQUEMA_NO_HTTPS"], causas
    assert ph.codigo_de_salida(hallazgos) != 0


# ---------------------------------------------------------------------------
# NEGATIVOS por efecto
# ---------------------------------------------------------------------------

def test_sin_declarar_url_publica_falla_por_ausencia():
    hallazgos = ph.verificar(ph.Entrada(url=None, session_secure=True))
    assert [h.causa for h in hallazgos] == ["URL_PUBLICA_NO_DECLARADA"]
    assert "no se puede verificar" in str(hallazgos[0])


def test_url_publica_vacia_es_ausencia_no_cero():
    hallazgos = ph.verificar(ph.Entrada(url="   ", session_secure=True))
    assert [h.causa for h in hallazgos] == ["URL_PUBLICA_NO_DECLARADA"]


def test_certificado_no_declarado_no_verifica(certificado_localhost):
    """Autofirmado contra el almacen del SISTEMA: cadena invalida."""
    cert, clave = certificado_localhost
    srv = _ServidorTLS(cert, clave)
    try:
        hallazgos = ph.verificar(ph.Entrada(
            url="https://localhost:%d" % srv.puerto,
            session_secure=True, ca_file=None, timeout=5.0))
    finally:
        srv.cerrar()
    assert [h.causa for h in hallazgos] == ["CERTIFICADO_NO_VERIFICABLE"], \
        [str(h) for h in hallazgos]
    assert "almacen de confianza" in str(hallazgos[0])


def test_nombre_del_certificado_que_no_coincide(certificado_otro_nombre):
    """Cadena OK (la CA esta declarada) pero el nombre NO es el publicado."""
    cert, clave = certificado_otro_nombre
    srv = _ServidorTLS(cert, clave)
    try:
        hallazgos = ph.verificar(ph.Entrada(
            url="https://localhost:%d" % srv.puerto,
            session_secure=True, ca_file=str(cert), timeout=5.0))
    finally:
        srv.cerrar()
    assert [h.causa for h in hallazgos] == ["NOMBRE_NO_COINCIDE"], \
        [str(h) for h in hallazgos]
    assert "no ampara el nombre" in str(hallazgos[0])


def test_tls_levantado_pero_el_endpoint_no_contesta(certificado_localhost):
    """LA VERIFICACION POR EFECTO. Handshake OK, cero respuesta HTTP."""
    cert, clave = certificado_localhost
    mudo = _ListenerMudo(cert, clave)
    try:
        hallazgos = ph.verificar(ph.Entrada(
            url="https://localhost:%d" % mudo.puerto,
            session_secure=True, ca_file=str(cert), timeout=5.0))
    finally:
        mudo.cerrar()
    assert [h.causa for h in hallazgos] == ["ENDPOINT_NO_RESPONDE"], \
        [str(h) for h in hallazgos]
    assert "no devolvio ninguna respuesta HTTP" in str(hallazgos[0])


def test_terminador_tls_sin_backend_da_respuesta_inesperada(certificado_localhost):
    cert, clave = certificado_localhost
    srv = _ServidorTLS(cert, clave, estado=502)
    try:
        hallazgos = ph.verificar(ph.Entrada(
            url="https://localhost:%d" % srv.puerto,
            session_secure=True, ca_file=str(cert), timeout=5.0))
    finally:
        srv.cerrar()
    assert [h.causa for h in hallazgos] == ["ENDPOINT_RESPUESTA_INESPERADA"], \
        [str(h) for h in hallazgos]
    assert "502" in str(hallazgos[0])


def test_nada_escuchando_en_el_puerto_declarado():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    hallazgos = ph.verificar(ph.Entrada(
        url="https://localhost:%d" % puerto, session_secure=True, timeout=3.0))
    assert [h.causa for h in hallazgos] == ["ENDPOINT_NO_RESPONDE"], \
        [str(h) for h in hallazgos]


# ---------------------------------------------------------------------------
# El codigo de salida ES la regla "fallo de HTTPS => instalacion NO completa"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("causa", [
    "URL_PUBLICA_NO_DECLARADA", "ESQUEMA_NO_HTTPS", "COOKIE_SECURE_SOBRE_HTTP",
    "CERTIFICADO_NO_VERIFICABLE", "NOMBRE_NO_COINCIDE", "ENDPOINT_NO_RESPONDE",
    "ENDPOINT_RESPUESTA_INESPERADA",
])
def test_cualquier_hallazgo_impide_completar_la_instalacion(causa):
    assert ph.codigo_de_salida([ph.Hallazgo(causa, "x")]) != 0, (
        "codigo_de_salida dio 0 con el hallazgo %s: un fallo de HTTPS tiene "
        "que dejar la INSTALACION NO COMPLETA, no pasar como completa" % causa)


def test_cli_sobre_env_file_de_http_plano_falla_y_nombra_la_causa(tmp_path, capsys):
    env = tmp_path / "viewer-pr3.env"
    env.write_text("S9K_SESSION_SECURE=true\n"
                   "S9K_PUBLIC_BASE_URL=http://127.0.0.1:8088\n",
                   encoding="utf-8")
    rc = ph.main(["--env-file", str(env)])
    salida = capsys.readouterr().out
    assert rc != 0
    assert "COOKIE_SECURE_SOBRE_HTTP" in salida
    assert "INSTALACION NO COMPLETA" in salida


# ---------------------------------------------------------------------------
# COSTURA: el lector de este modulo y el de validate_deploy.sh no se separan
# ---------------------------------------------------------------------------

LINEAS_DIFICILES = [
    ("simple", "S9K_PUBLIC_BASE_URL=https://a.example\n"),
    ("espacios", "  S9K_PUBLIC_BASE_URL = https://b.example  \n"),
    ("comillas-dobles", 'S9K_PUBLIC_BASE_URL="https://c.example"\n'),
    ("comillas-simples", "S9K_PUBLIC_BASE_URL='https://d.example'\n"),
    ("comentada-y-real", "#S9K_PUBLIC_BASE_URL=https://no.example\n"
                         "S9K_PUBLIC_BASE_URL=https://e.example\n"),
    ("duplicada-gana-la-ultima", "S9K_PUBLIC_BASE_URL=https://f1.example\n"
                                 "S9K_PUBLIC_BASE_URL=https://f2.example\n"),
    ("con-comentario-al-final", "S9K_PUBLIC_BASE_URL=https://g.example\n"
                                "S9K_VIEWER_PORT=8088\n"),
    ("ausente", "S9K_VIEWER_PORT=8088\n"),
]


@pytest.mark.parametrize("etiqueta,contenido", LINEAS_DIFICILES,
                         ids=[e for e, _ in LINEAS_DIFICILES])
def test_el_lector_de_env_coincide_con_validate_deploy_sh(tmp_path, etiqueta, contenido):
    """Dos mitades de la MISMA autoridad: se comprueba que dicen lo mismo.

    `validate_deploy.sh::_env_value` es la autoridad estatica del despliegue.
    `preflight_https.valor_de_env_file` es su mitad en Python. Que coincidan
    no se afirma: se mide, sobre las lineas que de verdad divergen.
    """
    env = tmp_path / ("viewer-%s.env" % etiqueta)
    env.write_text(contenido, encoding="utf-8")

    r = subprocess.run(
        ["bash", "-c",
         'source "$1"; _env_value "$2" S9K_PUBLIC_BASE_URL',
         "_", str(VALIDATE_SH), str(env)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-500:]
    del_bash = r.stdout

    del_python = ph.valor_de_env_file(env, "S9K_PUBLIC_BASE_URL") or ""
    assert del_python == del_bash, (
        "las dos mitades de la autoridad divergen en %r: bash=%r python=%r"
        % (etiqueta, del_bash, del_python))

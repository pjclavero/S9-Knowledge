# -*- coding: utf-8 -*-
"""H-05 corte B: autoridad única del host público y frontera de host (400).

PROPIEDAD: el visor sólo atiende peticiones cuyo `Host` está declarado, y
declarado sólo puede estar lo que sale de UNA cadena:

    S9K_PUBLIC_BASE_URL -> hostname canónico -> hosts de confianza
    (hostname público + localhost + 127.0.0.1 + ::1; `testserver` SÓLO en tests)

Un `Host` no declarado recibe 400 ANTES de la sesión, las rutas, los almacenes
y los redirects automáticos. Sin URL pública válida el visor NO arranca.

CONFIGURACIÓN DE ESTE MÓDULO: `viewer/tests/conftest.py` declara un entorno de
tests (URL + `testserver`) para el resto de la suite. Aquí se mide la frontera
REAL: la fixture `config_productiva` lo retira y declara una URL pública
concreta, sin `testserver`.

MAPA CONTRATO -> TEST
  N1..N7   test_host_no_declarado_da_400*, test_host_malformado_da_400*
  N8       test_placeholder_*          N9  test_comodin_*
  N10      test_url_*                  N11 test_host_publico_*
  N12/N13  test_loopback_*             N14 test_loopback_ipv6_*
  N15      test_testserver_*           N16 test_host_malo_no_llega_*
  N17      test_host_malo_no_genera_location_*   N18 test_corte_a_intacto_*
  P1..P5   test_host_publico_*, test_combinado_*, test_loopback_*,
           test_testserver_*, test_arranque_*
  §17      test_gate_unicidad_*

TECHO DECLARADO (ver también el calibrador): el gate de unicidad es estático
(AST) sobre `viewer/app`; no ve aliasing dinámico (`getattr`, `importlib`,
nombres de variable de entorno construidos en tiempo de ejecución) ni vigila
`deploy/` o `scripts/` (el preflight carga la misma interpretación por ruta, y
eso lo mide `deploy/tests`). La frontera mide el `Host` de la CABECERA: detrás
de un proxy que lo reescriba, es el valor reescrito el que se compara.
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app import public_endpoint as pe
from app import public_host_middleware as phm

REPO = Path(__file__).resolve().parents[2]
VIEWER = REPO / "viewer"
APP_DIR = VIEWER / "app"
PLANTILLA = REPO / "deploy" / "config" / "viewer.env.example"

PUBLICO = "public.example"
URL_PUBLICA = "https://public.example"
ESTADO = "/api/status"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def real_app():
    from app.main import app

    return app


@pytest.fixture
def config_productiva(monkeypatch):
    """CONFIG DE PRODUCCIÓN: URL pública declarada, SIN `testserver`.

    Retira lo que declara `conftest.py` (el entorno de tests) y deja
    exactamente lo que vería un despliegue real.
    """
    monkeypatch.setenv("S9K_PUBLIC_BASE_URL", URL_PUBLICA)
    monkeypatch.setattr(phm, "HOSTS_EXTRA_DE_PRUEBAS", ())
    return URL_PUBLICA


def _cliente(app, host: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if host is not None:
        c.headers["host"] = host
    return c


def _status(app, host: str | None) -> int:
    return _cliente(app, host).get(ESTADO).status_code


def _asgi(app, cabeceras: list, path: str = ESTADO) -> int:
    """GET ASGI crudo: permite Host ausente o duplicado, imposibles con httpx."""
    enviados: list = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(mensaje):
        enviados.append(mensaje)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": cabeceras,
        "client": ("203.0.113.9", 5000), "server": ("127.0.0.1", 8088),
    }
    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in enviados if m["type"] == "http.response.start")


# ---------------------------------------------------------------------------
# Autoridad: ÚNICA interpretación de la URL pública
# ---------------------------------------------------------------------------

def test_la_lista_de_confianza_es_exactamente_publico_mas_loopback():
    assert pe.resolve_trusted_hosts(URL_PUBLICA) == (
        "public.example", "localhost", "127.0.0.1", "::1")
    # El puerto, el esquema y el casing de la URL no crean entradas nuevas.
    for url in ("https://public.example:8443", "http://PUBLIC.example:80",
                "https://Public.Example./"):
        assert pe.resolve_trusted_hosts(url) == (
            "public.example", "localhost", "127.0.0.1", "::1"), url


def test_la_lista_de_confianza_no_tiene_comodin_ni_autodeteccion_ni_testserver():
    lista = pe.resolve_trusted_hosts(URL_PUBLICA)
    assert "*" not in lista and "testserver" not in lista
    assert set(lista) == {"public.example", "localhost", "127.0.0.1", "::1"}
    # Sin autodetección: ni el hostname de la máquina ni su IP entran.
    for ajeno in {socket.gethostname(), socket.getfqdn()}:
        assert ajeno not in lista or ajeno == "localhost"
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = None
    if ip:
        assert ip not in lista


def test_el_publico_ya_loopback_no_duplica():
    assert pe.resolve_trusted_hosts("http://127.0.0.1:8088") == (
        "127.0.0.1", "localhost", "::1")


def test_resolve_public_endpoint_lee_la_variable_por_la_autoridad_de_config(
        monkeypatch, config_productiva):
    ep = pe.resolve_public_endpoint()
    assert (ep.hostname, ep.scheme, ep.port) == ("public.example", "https", None)
    monkeypatch.setenv("S9K_PUBLIC_BASE_URL", "http://otro.example:8080")
    ep = pe.resolve_public_endpoint()
    assert (ep.hostname, ep.port) == ("otro.example", 8080)


def test_ausencia_no_es_cero_sin_variable_el_resolvedor_falla(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin .env
    monkeypatch.delenv("S9K_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts()
    assert e.value.code == "PUBLIC_URL_MISSING"
    # `None` explícito es AUSENTE (no «léelo de la config»).
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts(None)
    assert e.value.code == "PUBLIC_URL_MISSING"


def test_variable_vacia_en_el_entorno_gana_al_dotenv_y_falla(monkeypatch, tmp_path):
    """Misma precedencia que `effective_env_value`: vacía en el entorno = vacía."""
    (tmp_path / ".env").write_text("S9K_PUBLIC_BASE_URL=https://desde-dotenv.example\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("S9K_PUBLIC_BASE_URL", "")
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts()
    assert e.value.code == "PUBLIC_URL_MISSING"
    monkeypatch.delenv("S9K_PUBLIC_BASE_URL")
    assert pe.resolve_trusted_hosts()[0] == "desde-dotenv.example"


# N8 --------------------------------------------------------------------------
PLACEHOLDERS = [
    "https://cambiar.por.el.nombre.real",
    "http://cambiar.por.el.nombre.real:8080",
    "https://CAMBIAR.por.el.NOMBRE.real/",
    "https://cambiar.por.el.nombre.real.",
    "https://cambiar.por.el.nombre.real:8443/panel",
]


@pytest.mark.parametrize("url", PLACEHOLDERS)
def test_placeholder_es_stop_aunque_sea_una_url_valida(url):
    # Es una URL sintácticamente impecable: sólo el placeholder la rechaza.
    assert urlsplit(url).hostname
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts(url)
    assert e.value.code == "PUBLIC_URL_PLACEHOLDER"


def test_placeholder_el_valor_literal_de_la_plantilla_de_despliegue_se_detecta():
    """El placeholder REAL, leído de `deploy/config/viewer.env.example`."""
    lineas = [l for l in PLANTILLA.read_text(encoding="utf-8").splitlines()
              if l.startswith("S9K_PUBLIC_BASE_URL=")]
    assert len(lineas) == 1
    valor = lineas[0].split("=", 1)[1]
    assert pe.PLACEHOLDER_HOST in valor
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts(valor)
    assert e.value.code == "PUBLIC_URL_PLACEHOLDER"


def test_placeholder_control_positivo_un_nombre_parecido_no_es_el_placeholder():
    assert pe.resolve_trusted_hosts("https://cambiar.por.el.nombre.real.example")[0] \
        == "cambiar.por.el.nombre.real.example"


# N9 --------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "*", "https://*", "https://*.example.com", "https://public.*",
    "https://*.public.example:8443", "http://*:8080",
])
def test_comodin_es_stop(url):
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts(url)
    assert e.value.code == "PUBLIC_URL_WILDCARD"


def test_comodin_como_host_adicional_tambien_aborta():
    for extra in ("*", "*.example.com", "a*b"):
        with pytest.raises(pe.PublicEndpointError) as e:
            pe.resolve_trusted_hosts(URL_PUBLICA, extra=(extra,))
        assert e.value.code == "TRUSTED_HOST_INVALID"


# N10 -------------------------------------------------------------------------
MALFORMADAS = [
    (None, "PUBLIC_URL_MISSING"),
    ("", "PUBLIC_URL_MISSING"),
    ("   ", "PUBLIC_URL_MISSING"),
    ("https://", "PUBLIC_URL_NO_HOSTNAME"),
    ("https:///solo/ruta", "PUBLIC_URL_NO_HOSTNAME"),
    ("http://:8080", "PUBLIC_URL_NO_HOSTNAME"),
    ("public.example", "PUBLIC_URL_SCHEME"),
    ("/solo/ruta", "PUBLIC_URL_SCHEME"),
    ("ftp://public.example", "PUBLIC_URL_SCHEME"),
    ("javascript://public.example", "PUBLIC_URL_SCHEME"),
    ("file:///etc/passwd", "PUBLIC_URL_SCHEME"),
    (" https://public.example", "PUBLIC_URL_MALFORMED"),
    ("https://public.example ", "PUBLIC_URL_MALFORMED"),
    ("https://pub lic.example", "PUBLIC_URL_MALFORMED"),
    ("https://public.example\n", "PUBLIC_URL_MALFORMED"),
    ("https://pub\x00lic.example", "PUBLIC_URL_MALFORMED"),
    ("https://user:pw@public.example", "PUBLIC_URL_MALFORMED"),
    ("https://public.example?x=1", "PUBLIC_URL_MALFORMED"),
    ("https://public.example#frag", "PUBLIC_URL_MALFORMED"),
    ("https://public.example:notaport", "PUBLIC_URL_MALFORMED"),
    ("https://public.example:99999", "PUBLIC_URL_MALFORMED"),
    ("https://[::1", "PUBLIC_URL_MALFORMED"),
    ("https://pub_lic.example", "PUBLIC_URL_INVALID_HOSTNAME"),
    ("https://-public.example", "PUBLIC_URL_INVALID_HOSTNAME"),
    ("https://public..example", "PUBLIC_URL_INVALID_HOSTNAME"),
    ("https://pub%6Cic.example", "PUBLIC_URL_INVALID_HOSTNAME"),
    ("https://." , "PUBLIC_URL_INVALID_HOSTNAME"),
]


@pytest.mark.parametrize("url,codigo", MALFORMADAS,
                         ids=[repr(u)[:40] for u, _ in MALFORMADAS])
def test_url_malformada_es_stop_con_su_codigo(url, codigo):
    with pytest.raises(pe.PublicEndpointError) as e:
        pe.resolve_trusted_hosts(url)
    assert e.value.code == codigo


def test_url_malformada_nunca_produce_una_lista_parcial():
    for url, _ in MALFORMADAS:
        with pytest.raises(pe.PublicEndpointError):
            pe.resolve_trusted_hosts(url)  # excepción, jamás una lista


@pytest.mark.parametrize("url", [
    "https://public.example", "http://127.0.0.1:8088", "https://[::1]:8443",
    "http://localhost", "https://knowledge.sub.public.example:443/",
    "https://xn--bcher-kva.example",
])
def test_url_control_positivo_las_validas_se_aceptan(url):
    assert pe.resolve_trusted_hosts(url)


# ---------------------------------------------------------------------------
# Normalización del Host de la CABECERA
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cabecera,esperado", [
    ("public.example", "public.example"),
    ("PUBLIC.Example", "public.example"),
    ("public.example.", "public.example"),
    ("public.example:443", "public.example"),
    ("public.example:8443", "public.example"),
    ("localhost:8088", "localhost"),
    ("127.0.0.1", "127.0.0.1"),
    ("127.0.0.1:8088", "127.0.0.1"),
    ("[::1]", "::1"),
    ("[::1]:8088", "::1"),
    ("[0:0:0:0:0:0:0:1]:9", "::1"),
    ("[::FFFF:1.2.3.4]", "::ffff:1.2.3.4"),
])
def test_normaliza_host_de_cabecera(cabecera, esperado):
    assert pe.normalizar_host_cabecera(cabecera) == esperado


@pytest.mark.parametrize("cabecera", [
    None, "", " ", "a b", " public.example", "public.example ", "public.example:",
    "public.example:abc", "public.example:80:90", ":8088", "::1", "[::1",
    "[::1]x", "[::1]:", "[::1]:x", "[127.0.0.1]", "[public.example]",
    "public.example/", "public.example/x", "evil.example@public.example",
    "public.example@evil.example", "public.example,evil.example",
    "public.example\t", "pub\x00lic.example", "*", "*.example", "pub_lic.example",
    "public.example:1234567",
])
def test_host_de_cabecera_malformado_es_invalido(cabecera):
    assert pe.normalizar_host_cabecera(cabecera) is None


def test_el_middleware_estandar_de_starlette_no_sirve_y_por_eso_no_se_usa():
    """Medido por EJECUCIÓN en la Starlette instalada (contrato §9)."""
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    async def ok(scope, receive, send):
        from starlette.responses import PlainTextResponse
        await PlainTextResponse("ok")(scope, receive, send)

    estandar = TrustedHostMiddleware(ok, allowed_hosts=["public.example", "::1"])
    assert _asgi(estandar, [(b"host", b"[::1]:8088")]) == 400      # IPv6 roto
    assert _asgi(estandar, [(b"host", b"Public.Example")]) == 400  # casing
    assert _asgi(estandar, [(b"host", b"public.example.")]) == 400  # punto final
    # El nuestro, con la MISMA lista, acepta las tres.
    assert pe.normalizar_host_cabecera("[::1]:8088") in ("::1",)


# ---------------------------------------------------------------------------
# Frontera de host sobre la APP REAL
# ---------------------------------------------------------------------------

# N1, N2, N3, N4, N5, N6 ------------------------------------------------------
def _hosts_ajenos() -> list:
    hostname = socket.gethostname()
    ajenos = [
        ("N1", "evil.example"),
        ("N2", "evil.example:8443"),
        ("N3", "sub.public.example"),
        ("N3", "www.public.example"),
        ("N3", "public.example.evil.example"),
        ("N3", "xpublic.example"),
        ("N4", "192.168.1.215"),
        ("N4", "192.168.1.215:8088"),
        ("N4", "10.0.0.5"),
        ("N5", "100.64.0.1"),
        ("N5", "100.100.100.100:8088"),
        ("N5", "tailnet-host.tailnet.ts.net"),
        ("N6", "yggdrasil"),
        ("N6", "ia-server"),
        ("N6", "127.0.1.1"),
        ("local", "127.1"),
        ("local", "0.0.0.0"),
        ("local", "[::2]"),
        ("local", "localhost.evil.example"),
        ("local", "0177.0.0.1"),
    ]
    if hostname not in ("localhost",):
        ajenos.append(("N6", hostname))
    return ajenos


@pytest.mark.parametrize("caso,host", _hosts_ajenos(), ids=lambda v: str(v))
def test_host_no_declarado_da_400(real_app, config_productiva, caso, host):
    r = _cliente(real_app, host).get(ESTADO)
    assert r.status_code == 400, (caso, host, r.status_code)
    assert r.text == "Invalid host header"


def test_host_no_declarado_da_400_en_todos_los_metodos_y_rutas(real_app, config_productiva):
    c = _cliente(real_app, "evil.example")
    for metodo in ("get", "post", "put", "delete", "patch", "head", "options"):
        for ruta in ("/", ESTADO, "/login", "/panel/operations/", "/static/x.css",
                     "/no/existe", "/docs"):
            r = getattr(c, metodo)(ruta)
            assert r.status_code == 400, (metodo, ruta, r.status_code)


# N7 --------------------------------------------------------------------------
HOSTS_MALFORMADOS = ["", " ", "a b", "evil.example@public.example", "public.example:abc",
                     "public.example:80:90", "[::1", "public.example/", "*",
                     "public.example,evil.example", "public.example\x01"]


@pytest.mark.parametrize("host", HOSTS_MALFORMADOS, ids=repr)
def test_host_malformado_da_400(real_app, config_productiva, host):
    assert _asgi(real_app, [(b"host", host.encode("latin-1"))]) == 400


def test_host_ausente_da_400(real_app, config_productiva):
    assert _asgi(real_app, []) == 400


def test_host_duplicado_da_400_aunque_uno_sea_valido(real_app, config_productiva):
    assert _asgi(real_app, [(b"host", b"public.example"), (b"host", b"evil.example")]) == 400
    assert _asgi(real_app, [(b"host", b"evil.example"), (b"host", b"public.example")]) == 400
    assert _asgi(real_app, [(b"host", b"public.example"), (b"host", b"public.example")]) == 400


def test_otras_cabeceras_de_host_no_mandan(real_app, config_productiva):
    """`X-Forwarded-Host`/`Forwarded` no sustituyen ni completan al Host."""
    c = _cliente(real_app, "evil.example")
    r = c.get(ESTADO, headers={"x-forwarded-host": PUBLICO, "forwarded": f"host={PUBLICO}"})
    assert r.status_code == 400
    r = _cliente(real_app, PUBLICO).get(ESTADO, headers={"x-forwarded-host": "evil.example"})
    assert r.status_code == 200


# N11 / P1 --------------------------------------------------------------------
@pytest.mark.parametrize("host", [
    "public.example", "PUBLIC.EXAMPLE", "Public.Example", "public.example.",
    "public.example:443", "public.example:8443", "public.example:80",
])
def test_host_publico_pasa_con_cualquier_puerto_casing_y_punto_final(
        real_app, config_productiva, host):
    r = _cliente(real_app, host).get(ESTADO)
    assert r.status_code == 200, (host, r.status_code)


def test_host_publico_flujo_normal_pagina_y_api(real_app, config_productiva):
    c = _cliente(real_app, PUBLICO)
    assert c.get(ESTADO).status_code == 200
    assert c.get("/api/entities").status_code == 200
    assert c.get("/login").status_code in (200, 303, 307, 404)


def test_la_url_publica_con_puerto_se_compara_por_hostname(real_app, monkeypatch, config_productiva):
    monkeypatch.setenv("S9K_PUBLIC_BASE_URL", "https://public.example:8443")
    for host in ("public.example", "public.example:8443", "public.example:443"):
        assert _status(real_app, host) == 200, host
    assert _status(real_app, "other.example:8443") == 400


# N12 / N13 / N14 / P3 --------------------------------------------------------
@pytest.mark.parametrize("host", ["localhost", "localhost:8088", "LOCALHOST",
                                  "127.0.0.1", "127.0.0.1:8088"])
def test_loopback_health_ok(real_app, config_productiva, host):
    assert _status(real_app, host) == 200, host


@pytest.mark.parametrize("host", ["[::1]", "[::1]:8088", "[0:0:0:0:0:0:0:1]:8088"])
def test_loopback_ipv6_ok(real_app, config_productiva, host):
    assert _status(real_app, host) == 200, host


def test_loopback_lo_que_usan_los_consumidores_reales_del_repo(real_app, config_productiva):
    """Inventario de consumidores loopback (contrato §12), leído de su código.

    health runner, lib.sh/verify-deployment.sh y viewer.env.example apuntan a
    `http://127.0.0.1:8088`: el host que mandan está en la lista y no hace
    falta abrir nada más.
    """
    fuentes = {
        "runner": (APP_DIR / "health" / "runner.py").read_text(encoding="utf-8"),
        "lib.sh": (REPO / "deploy" / "scripts" / "lib.sh").read_text(encoding="utf-8"),
        "plantilla": PLANTILLA.read_text(encoding="utf-8"),
    }
    for nombre, texto in fuentes.items():
        urls = re.findall(r"https?://127\.0\.0\.1:8088", texto)
        assert urls, nombre
    # Y la plantilla de despliegue no declara ningún otro destino de health.
    assert re.findall(r"^S9K_HEALTH_VIEWER_URL=(.*)$",
                      fuentes["plantilla"], re.M) == ["http://127.0.0.1:8088"]
    host_de_esas_urls = urlsplit("http://127.0.0.1:8088").netloc
    assert _status(real_app, host_de_esas_urls) == 200


def test_loopback_no_abre_la_lan(real_app, config_productiva):
    for host in ("192.168.1.215", "10.1.2.3", "172.16.0.9", "169.254.1.1", "0.0.0.0"):
        assert _status(real_app, host) == 400, host


# N15 / P4 --------------------------------------------------------------------
def test_testserver_en_el_entorno_de_tests_se_acepta(real_app):
    """TEST ENV: `conftest.py` lo declara de forma explícita."""
    assert "testserver" in phm.HOSTS_EXTRA_DE_PRUEBAS
    assert TestClient(real_app).get(ESTADO).status_code == 200  # Host: testserver


def test_testserver_no_esta_en_la_configuracion_de_produccion(real_app, config_productiva):
    assert phm.HOSTS_EXTRA_DE_PRUEBAS == ()
    assert "testserver" not in pe.resolve_trusted_hosts()
    assert TestClient(real_app, raise_server_exceptions=False).get(ESTADO).status_code == 400
    assert _status(real_app, "testserver") == 400


def test_testserver_en_un_interprete_limpio_sin_la_fixture_da_400():
    """Sin conftest: el visor tal como lo carga un proceso real."""
    codigo = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "from app import public_host_middleware as m\n"
        "c = TestClient(app, raise_server_exceptions=False)\n"
        "print('EXTRA', m.HOSTS_EXTRA_DE_PRUEBAS)\n"
        "print('TESTSERVER', c.get('/api/status').status_code)\n"
        "print('PUBLICO', c.get('/api/status', headers={'host': 'public.example'}).status_code)\n"
    )
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    entorno.update({
        "PYTHONPATH": str(VIEWER), "PYTHONDONTWRITEBYTECODE": "1",
        "S9K_PUBLIC_BASE_URL": URL_PUBLICA, "S9K_AUTH_ENABLED": "false",
        "S9K_GRAPH_PROVIDER": "mock",
        "S9K_SAMPLE_GRAPH_PATH": str(VIEWER / "examples" / "sample_graph.json"),
    })
    r = subprocess.run([sys.executable, "-W", "ignore", "-c", codigo],
                       cwd=str(VIEWER.parent), env=entorno, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "EXTRA ()" in r.stdout, r.stdout
    assert "TESTSERVER 400" in r.stdout, r.stdout
    assert "PUBLICO 200" in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# Arranque fail-closed (P5, N8..N10 sobre el visor real)
# ---------------------------------------------------------------------------

def test_arranque_con_config_valida_arranca_y_atiende(real_app, config_productiva):
    with TestClient(real_app) as c:                     # ejecuta el startup
        assert c.get(ESTADO, headers={"host": PUBLICO}).status_code == 200


@pytest.mark.parametrize("valor,codigo", [
    ("https://cambiar.por.el.nombre.real", "PUBLIC_URL_PLACEHOLDER"),
    ("https://*.example.com", "PUBLIC_URL_WILDCARD"),
    ("https://", "PUBLIC_URL_NO_HOSTNAME"),
    ("not a url", "PUBLIC_URL_MALFORMED"),
    ("", "PUBLIC_URL_MISSING"),
])
def test_arranque_aborta_con_url_publica_invalida(real_app, config_productiva,
                                                  monkeypatch, valor, codigo):
    monkeypatch.setenv("S9K_PUBLIC_BASE_URL", valor)
    with pytest.raises(pe.PublicEndpointError) as e:
        with TestClient(real_app):
            pass
    assert e.value.code == codigo


def test_arranque_aborta_sin_la_variable(real_app, config_productiva, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("S9K_PUBLIC_BASE_URL")
    with pytest.raises(pe.PublicEndpointError) as e:
        with TestClient(real_app):
            pass
    assert e.value.code == "PUBLIC_URL_MISSING"


def test_sin_configuracion_cada_peticion_falla_cerrada_nunca_abierta(
        real_app, config_productiva, monkeypatch, tmp_path):
    """Aunque alguien salte el arranque: ni 200 ni «permitir todo»."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("S9K_PUBLIC_BASE_URL")
    for host in (PUBLICO, "evil.example", "localhost", "testserver"):
        r = _cliente(real_app, host).get(ESTADO)
        assert r.status_code == 503, (host, r.status_code)


def test_el_modo_test_no_se_deduce_de_la_ausencia_de_config_ni_del_hostname(
        real_app, config_productiva, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("S9K_PUBLIC_BASE_URL")
    assert _cliente(real_app, "testserver").get(ESTADO).status_code == 503
    monkeypatch.setenv("S9K_PUBLIC_BASE_URL", URL_PUBLICA)
    assert _cliente(real_app, "testserver").get(ESTADO).status_code == 400


# ---------------------------------------------------------------------------
# Orden: el Host malo no toca NADA (N16)
# ---------------------------------------------------------------------------

class _Cuenta:
    def __init__(self):
        self.n = {"sqlite": 0, "auth_middleware": 0, "provider": 0, "almacen_cola": 0,
                  "servicio_apply": 0}


@pytest.fixture
def contadores(monkeypatch, real_app):
    import sqlite3

    import app.auth.middleware as am
    import app.jobs_client as jc
    import app.services.v3_apply as v3
    from app.deps import get_provider

    c = _Cuenta()
    sqlite_real = sqlite3.connect

    def conectar(*a, **k):
        c.n["sqlite"] += 1
        return sqlite_real(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", conectar)

    llamada_real = am.AuthMiddleware.__call__

    async def llamada(self, scope, receive, send):
        c.n["auth_middleware"] += 1
        return await llamada_real(self, scope, receive, send)

    monkeypatch.setattr(am.AuthMiddleware, "__call__", llamada)

    carga_real = jc._load_job_store

    def carga(*a, **k):
        c.n["almacen_cola"] += 1
        return carga_real(*a, **k)

    monkeypatch.setattr(jc, "_load_job_store", carga)

    real_servicio = v3.ReviewApplyService

    class Servicio(real_servicio):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **k):
            c.n["servicio_apply"] += 1
            super().__init__(*a, **k)

    monkeypatch.setattr(v3, "ReviewApplyService", Servicio)

    from app.providers.mock_provider import MockGraphProvider
    from app.config import get_settings

    real_prov = MockGraphProvider(Path(get_settings().S9K_SAMPLE_GRAPH_PATH))

    def prov():
        c.n["provider"] += 1
        return real_prov

    real_app.dependency_overrides[get_provider] = prov
    yield c
    real_app.dependency_overrides.pop(get_provider, None)


RUTAS_CON_EFECTO = [
    ("get", ESTADO), ("get", "/api/entities"), ("get", "/panel/operations/"),
    ("get", "/panel/operations"), ("get", "/login"),
    ("post", "/login"), ("post", "/setup/admin"),
    ("post", "/panel/operations/ingestas"), ("post", "/panel/operations/planes"),
    ("post", "/panel/operations/aplicaciones"), ("post", "/panel/operations/altas"),
]


def test_host_malo_no_llega_al_endpoint_ni_al_almacen_ni_a_la_sesion(
        real_app, config_productiva, contadores):
    c = _cliente(real_app, "evil.example")
    for metodo, ruta in RUTAS_CON_EFECTO:
        r = getattr(c, metodo)(ruta, **({"data": {"x": "1"}} if metodo == "post" else {}))
        assert r.status_code == 400, (metodo, ruta, r.status_code)
    assert contadores.n == {k: 0 for k in contadores.n}, contadores.n


def test_host_malo_control_positivo_los_contadores_si_cuentan_con_host_valido(
        real_app, config_productiva, contadores):
    """El instrumento no está ciego: con Host válido los mismos contadores suben."""
    c = _cliente(real_app, PUBLICO)
    c.get(ESTADO)
    c.get("/api/entities")
    c.post("/login", data={"username": "x", "password": "y"})
    assert contadores.n["auth_middleware"] >= 3, contadores.n
    assert contadores.n["provider"] >= 1, contadores.n


def test_la_frontera_es_el_middleware_mas_externo(real_app):
    """El orden es estructura, no suerte: PublicHostMiddleware envuelve a Auth."""
    from app.auth.middleware import AuthMiddleware

    clases = [m.cls for m in real_app.user_middleware]
    assert clases.index(phm.PublicHostMiddleware) < clases.index(AuthMiddleware)
    assert clases[0] is phm.PublicHostMiddleware


# ---------------------------------------------------------------------------
# A + B (N17, N18, combinado, P2)
# ---------------------------------------------------------------------------

@pytest.fixture
def panel_con_operador(real_app, tmp_path, monkeypatch, config_productiva):
    import grafo_doble

    from app import jobs_client
    from app.auth import db as auth_db_mod
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    from app.chassis import FEATURE_SLOTS, slot_flag_env
    from app.config import get_settings

    grafo_doble.instalar(monkeypatch)
    slot = next(s for s in FEATURE_SLOTS if s.key == "B")
    monkeypatch.setenv(slot_flag_env(slot), "true")
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(REPO / "examples" / "ingesta-v3"))
    db_jobs = tmp_path / "jobs.db"
    monkeypatch.setenv("S9K_JOBS_DB", str(db_jobs))
    db_auth = tmp_path / "auth.db"
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(db_auth))
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    jobs_client._load_job_store().init_db(str(db_jobs))
    auth_db_mod.ensure_migrated(db_auth)
    with auth_db_mod.get_conn(db_auth) as conn:
        u = auth_db_mod.create_user(conn, username="h05b_op", display_name="Op",
                                    password_hash=hash_password("PanelBH05b_1234567890!"),
                                    role="admin")
        auth_db_mod.update_user(conn, u.id, must_change_password=False)
        u = auth_db_mod.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)

    def fabrica(host: str) -> TestClient:
        c = _cliente(real_app, host)
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
        c.headers["accept"] = "text/html"
        return c

    yield fabrica
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "la pantalla no trae token CSRF"
    return m.group(1)


def test_combinado_host_permitido_post_operations_303_relativo_y_host_malo_400(
        panel_con_operador):
    """P2 + N17 + N18: A y B se complementan, ninguno rompe al otro."""
    bueno = panel_con_operador(PUBLICO)
    html = bueno.get("/panel/operations/").text
    datos = {"fuente": "", "csrf_token": _csrf(html)}
    r = bueno.post("/panel/operations/ingestas", data=datos)
    assert r.status_code == 303, (r.status_code, r.text[:200])
    loc = r.headers["location"]
    assert loc.startswith("/") and not loc.startswith("//") and "://" not in loc, loc
    assert urlsplit(loc).path == "/panel/operations/"

    malo = panel_con_operador("evil.example")
    r = malo.post("/panel/operations/ingestas", data=datos)
    assert r.status_code == 400
    assert "location" not in r.headers
    assert "evil" not in r.text.lower().replace("invalid host header", "")


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8443", "192.168.1.215"])
@pytest.mark.parametrize("ruta", ["ingestas", "planes", "aplicaciones", "altas"])
def test_host_malo_no_genera_location_absoluto(panel_con_operador, host, ruta):
    """N17, en las cuatro rutas POST de A: ni 303 ni Location, ni propio ni ajeno."""
    c = panel_con_operador(host)
    r = c.post(f"/panel/operations/{ruta}", data={"trabajo": "j", "fuente": "",
                                                  "csrf_token": "x"})
    assert r.status_code == 400
    assert "location" not in r.headers


def test_host_malo_no_genera_location_en_el_redirect_automatico_de_barra(
        real_app, config_productiva):
    """O1 de la revisión de A: `redirect_slashes` construía un 307 con el Host
    del cliente; ahora ese Host no pasa la frontera y no hay Location."""
    malo = _cliente(real_app, "evil.example").get(ESTADO + "/")
    assert malo.status_code == 400 and "location" not in malo.headers
    # Control positivo: el mecanismo EXISTE (con Host válido sigue redirigiendo).
    bueno = _cliente(real_app, PUBLICO).get(ESTADO + "/")
    assert bueno.status_code in (307, 308)
    assert urlsplit(bueno.headers["location"]).hostname == PUBLICO


def test_corte_a_intacto_las_redirecciones_siguen_sin_url_for():
    """N18: la propiedad de A sigue medida por su propio testigo; aquí, por AST,
    que B no reintrodujo `url_for` en el router de A."""
    arbol = ast.parse((APP_DIR / "routers" / "chassis_operations.py").read_text("utf-8"))
    llamadas = [n.lineno for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "url_for"]
    assert llamadas == []


# ---------------------------------------------------------------------------
# Gate de unicidad (contrato §17), por AST sobre viewer/app
# ---------------------------------------------------------------------------

AUTORIDAD = "public_endpoint.py"
URLSPLIT_PERMITIDO = {"public_endpoint.py", "next_url.py"}  # next_url: otro concepto (open redirect)
PATRON_VARIABLE = re.compile(r"PUBLIC_(BASE_)?URL|PUBLIC_HOST|TRUSTED_?HOSTS?|ALLOWED_?HOSTS?",
                             re.I)
HOSTS_PRODUCTIVOS_CONOCIDOS = ("seccionnueve", "duckdns", "knowledge.example")


def _hallazgos_de_unicidad(fuentes: dict) -> list:
    """Segunda autoridad en `fuentes` (ruta relativa -> texto). Lista de causas."""
    causas = []
    for ruta, texto in fuentes.items():
        nombre = Path(ruta).name
        arbol = ast.parse(texto)
        for n in ast.walk(arbol):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                v = n.value
                if nombre != AUTORIDAD and len(v) < 80 and PATRON_VARIABLE.search(v) \
                        and " " not in v:
                    causas.append((ruta, n.lineno, "VARIABLE_PUBLICA_FUERA_DE_AUTORIDAD", v))
                if v == "testserver":
                    causas.append((ruta, n.lineno, "TESTSERVER_EN_PRODUCCION", v))
                if v == "*" and nombre == "public_host_middleware.py":
                    causas.append((ruta, n.lineno, "COMODIN_EN_LA_FRONTERA", v))
                if any(h in v.lower() for h in HOSTS_PRODUCTIVOS_CONOCIDOS) and len(v) < 120:
                    causas.append((ruta, n.lineno, "HOST_PRODUCTIVO_HARDCODEADO", v))
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                modulo = getattr(n, "module", None) or ""
                alias = [a.name for a in n.names]
                if modulo == "urllib.parse" and any(a in ("urlsplit", "urlparse") for a in alias) \
                        and nombre not in URLSPLIT_PERMITIDO:
                    causas.append((ruta, n.lineno, "URLSPLIT_FUERA_DE_AUTORIDAD", modulo))
                if "TrustedHostMiddleware" in alias:
                    causas.append((ruta, n.lineno, "SEGUNDA_FRONTERA_DE_HOST", modulo))
            if isinstance(n, ast.Attribute) and n.attr in ("urlsplit", "urlparse") \
                    and nombre not in URLSPLIT_PERMITIDO:
                causas.append((ruta, n.lineno, "URLSPLIT_FUERA_DE_AUTORIDAD", n.attr))
            if isinstance(n, (ast.Name, ast.Attribute)):
                ident = n.id if isinstance(n, ast.Name) else n.attr
                if ident == "HOSTS_EXTRA_DE_PRUEBAS" and nombre != "public_host_middleware.py":
                    causas.append((ruta, n.lineno, "COSTURA_DE_TESTS_TOCADA_EN_PRODUCCION", ident))
        if nombre == "public_host_middleware.py":
            usos = [n for n in ast.walk(arbol)
                    if isinstance(n, ast.Name) and n.id == "HOSTS_EXTRA_DE_PRUEBAS"]
            asignaciones = [n for n in usos if isinstance(n.ctx, ast.Store)]
            if len(asignaciones) != 1:
                causas.append((ruta, 0, "COSTURA_REASIGNADA_EN_PRODUCCION", len(asignaciones)))
            else:
                asig = next(a for a in ast.walk(arbol)
                            if isinstance(a, ast.AnnAssign) and getattr(a.target, "id", "")
                            == "HOSTS_EXTRA_DE_PRUEBAS")
                if not (isinstance(asig.value, ast.Tuple) and asig.value.elts == []):
                    causas.append((ruta, asig.lineno, "COSTURA_NO_VACIA_POR_DEFECTO", ""))
    return causas


def _fuentes_de_produccion() -> dict:
    return {str(p.relative_to(REPO)): p.read_text(encoding="utf-8")
            for p in sorted(APP_DIR.rglob("*.py"))
            if "__pycache__" not in p.parts and p.name != "conftest.py"}


def test_gate_unicidad_el_arbol_real_no_tiene_segunda_autoridad():
    fuentes = _fuentes_de_produccion()
    assert any(r.endswith("public_endpoint.py") for r in fuentes)  # el gate ve la autoridad
    assert len(fuentes) > 50                                       # y el árbol, no un trozo
    assert _hallazgos_de_unicidad(fuentes) == []


PLANTADAS = {
    "VARIABLE_PUBLICA_FUERA_DE_AUTORIDAD": (
        "import os\nX = os.environ.get('S9K_PUBLIC_BASE_URL')\n"),
    "URLSPLIT_FUERA_DE_AUTORIDAD": (
        "from urllib.parse import urlsplit\nh = urlsplit(x).hostname\n"),
    "TESTSERVER_EN_PRODUCCION": "HOSTS = ('testserver', 'localhost')\n",
    "HOST_PRODUCTIVO_HARDCODEADO": "HOSTS = ('knowledge.seccionnueve.duckdns.org',)\n",
    "SEGUNDA_FRONTERA_DE_HOST": (
        "from starlette.middleware.trustedhost import TrustedHostMiddleware\n"),
    "COSTURA_DE_TESTS_TOCADA_EN_PRODUCCION": (
        "import app.public_host_middleware as m\nm.HOSTS_EXTRA_DE_PRUEBAS = ('x',)\n"),
}


@pytest.mark.parametrize("causa", sorted(PLANTADAS))
def test_gate_unicidad_no_esta_ciego_detecta_cada_clase_plantada(causa):
    hallazgos = _hallazgos_de_unicidad({"viewer/app/otro_modulo.py": PLANTADAS[causa]})
    assert causa in [h[2] for h in hallazgos], hallazgos


def test_gate_unicidad_detecta_comodin_y_costura_no_vacia_en_la_frontera():
    base = (APP_DIR / "public_host_middleware.py").read_text(encoding="utf-8")
    assert _hallazgos_de_unicidad({"viewer/app/public_host_middleware.py": base}) == []
    con_comodin = base.replace("HOSTS_EXTRA_DE_PRUEBAS: tuple = ()",
                               'HOSTS_EXTRA_DE_PRUEBAS: tuple = ("*",)')
    assert con_comodin != base
    causas = [h[2] for h in _hallazgos_de_unicidad(
        {"viewer/app/public_host_middleware.py": con_comodin})]
    assert "COSTURA_NO_VACIA_POR_DEFECTO" in causas or "COMODIN_EN_LA_FRONTERA" in causas


def test_gate_unicidad_el_unico_registro_de_frontera_en_main():
    """`main.py` registra exactamente PublicHostMiddleware tras AuthMiddleware."""
    arbol = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))
    registros = [n.value.args[0].id for n in ast.walk(arbol)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Attribute)
                 and n.value.func.attr == "add_middleware" and n.value.args]
    assert registros == ["AuthMiddleware", "PublicHostMiddleware"], registros
    # y el arranque pasa por el resolvedor canónico
    fuente = (APP_DIR / "main.py").read_text(encoding="utf-8")
    assert "resolve_trusted_hosts()" in fuente


def test_gate_unicidad_el_preflight_de_despliegue_usa_la_misma_interpretacion():
    """`deploy/scripts/preflight_https.py` no interpreta la URL: carga este módulo."""
    texto = (REPO / "deploy" / "scripts" / "preflight_https.py").read_text(encoding="utf-8")
    assert "public_endpoint.py" in texto and "interpretar_url_publica" in texto
    assert pe.PLACEHOLDER_HOST not in texto  # no copia el literal del placeholder

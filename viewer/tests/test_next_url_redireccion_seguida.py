# -*- coding: utf-8 -*-
r"""NEGATIVO REAL: un cliente que SIGUE la redirección no sale del producto.

POR QUÉ HACE FALTA ESTE FICHERO
-------------------------------
La suite de cabecera (`test_next_url_open_redirect.py`) comprueba el texto del
`Location`. El fichero de navegador comprueba a dónde va Chromium. Faltaba la
pregunta de en medio, que es la que de verdad define «redirección abierta»:
**¿un cliente que sigue la redirección acaba en otro origen?**

Y hacía falta porque hubo una ronda que se quedó SIN NINGÚN NEGATIVO, apoyándose
en que Chromium no reproducía el escape. Eso era exactamente el razonamiento
—«hoy este navegador no lo explota»— que el propio módulo denuncia.

Aquella premisa, además, resultó ser FALSA: el arnés de navegador estaba ciego
—observaba peticiones abortadas contra un dominio que no resuelve— y por eso
parecía que Chromium no salía. Con el arnés arreglado, **Chromium sale igual
que curl, que `fetch` y que el parser WHATWG**. Se llegó a escribir aquí que
Chromium usaba GURL y no era conforme a WHATWG «en todos los bordes»: esa frase
era una hipótesis para explicar una medición equivocada, la medición ya está
corregida, y la frase se ha borrado por falsa. Ver
`tests/browser/test_browser_next_calibracion.py`.

Este fichero sigue existiendo aunque el negativo de navegador ya exista, y por
un motivo propio: mide la misma propiedad **sin depender de ningún motor**, con
un cliente HTTP real. Dos testigos independientes de familias distintas para la
misma afirmación.

LAS DOS FAMILIAS DE INSTRUMENTO, Y POR QUÉ IMPORTA CUÁL SE USA
---------------------------------------------------------------
Esto se MIDIÓ, con la defensa retirada y el servidor emitiendo
`Location: ///evil.example/x` intacto:

    urllib.parse.urljoin   (RFC 3986)      -> 127.0.0.1   se queda dentro
    httpx                  (RFC 3986)      -> 127.0.0.1   se queda dentro
    Node `new URL()`       (WHATWG)        -> evil.example  SALE
    curl -L                (cliente real)  -> evil.example  SALE
                                              (rc=6, «Could not resolve host:
                                               evil.example»: intentó el DNS)

Los dos estándares difieren **exactamente en `///`**: WHATWG salta todas las
barras al entrar en la autoridad y RFC 3986 no. Los navegadores implementan
WHATWG/Fetch. Citar `urljoin` o `httpx` para una pregunta de navegador —como se
hizo en la ronda anterior— es medir con el instrumento de la familia
equivocada, y esa cita es la que hay que retirar, no la medición.

El instrumento de este fichero es **curl siguiendo la redirección de verdad**:
un cliente HTTP real, no un constructor de URL ni un resolutor de biblioteca.

TECHO DECLARADO — QUÉ NO VE ESTE FICHERO
-----------------------------------------
- Un solo cliente: curl. No es «todos los clientes», es un testigo conforme y
  real. La cobertura de navegador la aportan, con su propio techo y con el
  MISMO resultado, `tests/browser/test_browser_next_open_redirect.py` y su
  calibración.
- Mide `POST /login`. No cubre `GET /login` ni `/partida/select`, que se miden
  por cabecera en `test_next_url_open_redirect.py`.
- Usa `///evil.example/x` como testigo. `////…` NO sirve aquí: curl se niega a
  parsear esa cabecera (`rc=3, Unsupported number of slashes`), así que no
  llega a salir y no discrimina por esta vía aunque SÍ salga bajo WHATWG puro.
  Está medido y por eso no se usa.
- `/\evil.example/x` tampoco sirve **por esta ruta**: bajo WHATWG la backslash
  cruda SÍ saca del sitio (`new URL("/\\evil.example/x", base)` da
  `http://evil.example/x`), pero Starlette la percent-encodea al construir el
  `Location`, de modo que el cliente nunca recibe la backslash. Lo que lo
  neutraliza es el transporte, no el validador — razón de más para que el
  validador siga rechazándola.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
import time
from contextlib import closing
from urllib.parse import urlencode, urlparse

import pytest

HOSTIL = "evil.example"

#: El testigo. Medido: es el que discrimina con este instrumento.
TESTIGO = f"///{HOSTIL}/x"

#: Destinos internos que deben sobrevivir al viaje completo.
INTERNOS = ["/v3/review", "/v3/review?workspace=alpha&job_id=job-A"]

PW = "contrasena-de-laboratorio-1234567890-ABCdef"


def _puerto_libre() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    """Visor real en un puerto de verdad: curl tiene que poder conectarse.

    No sirve `TestClient`: no hay socket, y lo que se quiere medir es
    precisamente qué hace un cliente HTTP externo con la cabecera.
    """
    import uvicorn

    db = tmp_path_factory.mktemp("authdb-curl") / "auth.db"
    previo = {k: os.environ.get(k) for k in (
        "S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_CSRF_SECRET",
        "S9K_SESSION_SECURE", "S9K_GRAPH_PROVIDER",
    )}
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-de-laboratorio-larga-0987654321"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")

    from app.auth.config import get_auth_settings
    from app.config import get_settings
    from app.deps import get_provider
    for cache in (get_auth_settings, get_settings, get_provider):
        cache.cache_clear()

    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    auth_db.ensure_migrated(db)
    with auth_db.get_conn(db) as conn:
        auth_db.create_user(conn, username="lab", display_name="Lab",
                            password_hash=hash_password(PW), role="viewer",
                            must_change_password=False)

    from app.main import app
    puerto = _puerto_libre()
    config = uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error")
    server = uvicorn.Server(config)
    hilo = threading.Thread(target=server.run, daemon=True)
    hilo.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:                                                  # pragma: no cover
        raise RuntimeError("el visor de pruebas no arrancó")

    try:
        yield f"http://127.0.0.1:{puerto}"
    finally:
        server.should_exit = True
        hilo.join(timeout=5)
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for cache in (get_auth_settings, get_settings, get_provider):
            cache.cache_clear()


@pytest.fixture(scope="module")
def curl():
    ruta = shutil.which("curl")
    # NO es un `skip`. curl existe en el runner y en cualquier entorno de
    # desarrollo razonable; si faltara, este fichero dejaría de medir lo único
    # que mide y eso tiene que verse en ROJO, no en verde.
    assert ruta, (
        "curl no está instalado, y es el instrumento de esta prueba: sin él no "
        "se mide si un cliente real sale del producto. Un skip aquí sería un "
        "verde que no prueba nada."
    )
    return ruta


def _login_siguiendo(curl_bin, base, next_valor, galletas):
    """Login real y SIGUIENDO la redirección. Devuelve (rc, url_efectiva).

    `--max-time` acota: el dominio hostil es de ejemplo y no resuelve, así que
    si el cliente se va fuera fallará el DNS — y ese fallo, junto con la
    `url_effective` que curl reporta igualmente, ES la prueba de que salió.
    """
    pagina = subprocess.run(
        [curl_bin, "-sS", "--max-time", "10", "-c", galletas, "-b", galletas,
         f"{base}/login"],
        capture_output=True, text=True, check=True).stdout
    m = re.search(r'name="csrf_token" value="([^"]*)"', pagina)
    assert m, f"no se encontró csrf_token en la página de login: {pagina[:200]!r}"

    datos = urlencode({"username": "lab", "password": PW,
                       "csrf_token": m.group(1), "next": next_valor})
    r = subprocess.run(
        [curl_bin, "-sS", "-L", "--max-time", "10", "-c", galletas, "-b", galletas,
         "-o", os.devnull, "-w", "%{url_effective}", "--data-raw", datos,
         f"{base}/login"],
        capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _host_de(url_efectiva):
    try:
        return urlparse(url_efectiva).hostname
    except ValueError:                                     # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# EL NEGATIVO
# ---------------------------------------------------------------------------

def test_un_cliente_real_que_sigue_la_redireccion_no_sale_del_producto(
        servidor, curl, tmp_path):
    rc, efectiva = _login_siguiendo(curl, servidor, TESTIGO,
                                    str(tmp_path / "galletas.txt"))
    host = _host_de(efectiva)
    assert host != HOSTIL, (
        f"REDIRECCIÓN ABIERTA CONFIRMADA POR UN CLIENTE REAL: con "
        f"next={TESTIGO!r}, curl siguió la redirección y acabó en "
        f"{efectiva!r} (host {host!r}, rc={rc}). El usuario ha salido del "
        f"producto. Este es el testigo que SÍ discrimina sin navegador: "
        f"`Location: ///…` se resuelve contra otra autoridad bajo WHATWG/Fetch "
        f"—que es lo que implementan los navegadores— y curl lo reproduce."
    )
    assert host == "127.0.0.1", (
        f"con next={TESTIGO!r} el cliente acabó en {efectiva!r} (rc={rc}), que "
        f"no es el origen del producto"
    )


@pytest.mark.parametrize("destino", INTERNOS)
def test_el_destino_interno_sobrevive_al_viaje_completo(
        servidor, curl, tmp_path, destino):
    """Simétrico: el cliente real llega EXACTAMENTE a donde debía."""
    rc, efectiva = _login_siguiendo(curl, servidor, destino,
                                    str(tmp_path / "galletas.txt"))
    assert rc == 0, f"curl falló con rc={rc} para un destino interno legítimo"
    assert efectiva == f"{servidor}{destino}", (
        f"REGRESIÓN DE ERGONOMÍA: con next={destino!r} un cliente real acabó "
        f"en {efectiva!r} y se esperaba {servidor + destino!r}. El destino "
        f"interno y su query de filtros deben sobrevivir al viaje entero, no "
        f"sólo a la cabecera."
    )


# ---------------------------------------------------------------------------
# LA CALIBRACIÓN, en el fichero y no en una nota: el negativo de arriba SE PONE
# ROJO cuando la defensa se retira. Sin esto seguiría siendo un testigo cuya
# capacidad de enrojecer es una afirmación, no un hecho.
# ---------------------------------------------------------------------------

def _validador_preexistente(next_url):
    """El criterio EXACTO de la base. Vive aquí y sólo aquí."""
    from urllib.parse import urlparse as _up
    if not next_url:
        return "/"
    parsed = _up(next_url)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_url.startswith("/"):
        return "/"
    return next_url


def test_calibracion_con_la_defensa_retirada_el_cliente_SI_sale(
        servidor, curl, tmp_path, monkeypatch):
    """Control del control: con el validador preexistente, curl se va fuera.

    Nada vulnerable llega a ninguna rama: el criterio viejo se reconstruye aquí
    y se inyecta sólo durante este caso. Si esto NO se pusiera rojo, el negativo
    de arriba estaría verde pase lo que pase.
    """
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "_safe_next", _validador_preexistente)

    rc, efectiva = _login_siguiendo(curl, servidor, TESTIGO,
                                    str(tmp_path / "galletas.txt"))
    assert _host_de(efectiva) == HOSTIL, (
        f"TESTIGO VACUO: con la defensa RETIRADA y next={TESTIGO!r}, curl NO "
        f"salió del producto (acabó en {efectiva!r}, rc={rc}). Si con el "
        f"validador preexistente el cliente no se va fuera, el negativo de "
        f"este fichero no está guardando nada. Dos causas posibles y hay que "
        f"distinguirlas: o la inyección de `_safe_next` no alcanza al "
        f"manejador, o este cliente dejó de reproducir el escape."
    )

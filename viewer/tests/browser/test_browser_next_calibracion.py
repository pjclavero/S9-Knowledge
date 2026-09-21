# -*- coding: utf-8 -*-
r"""CALIBRACION del control de navegador: cuales de sus negativos DISCRIMINAN.

POR QUE EXISTE ESTE FICHERO
---------------------------
Un negativo que sigue verde cuando se retira la defensa no esta guardando nada:
es un testigo vacuo, y se lee exactamente igual que uno que si guarda. La
primera version de `test_browser_next_open_redirect.py` traia cuatro negativos
de navegador y no habia forma —se dijo— de calibrarlos sin empujar codigo
vulnerable. Eso era falso, y este fichero es la prueba: el validador
PREEXISTENTE se reconstruye AQUI DENTRO, se inyecta en el router para la
duracion de un caso, y se mide a donde va Chromium de verdad. Nada vulnerable
llega a ninguna rama.

EL RESULTADO, QUE NO ES EL QUE SE ESPERABA
-------------------------------------------
Se esperaba que `///evil.example/x` sacara al navegador del producto: la WHATWG
URL Standard salta todas las barras iniciales al entrar en la autoridad, de
donde se sigue que `evil.example` deberia leerse como host. CI dijo que no.
Medido con la defensa retirada y con el servidor emitiendo el `Location` hostil
intacto —comprobado con socket crudo, ver `_location_crudo`—, **Chromium no
sale del producto con ninguna de las seis representaciones**:

    ///evil.example/x      ////evil.example/x
    /\evil.example/x       /\\evil.example/x
    /%5Cevil.example/x     /%2F%2Fevil.example/x

Dos lecturas, ambas utiles:

1. Resolver un `Location` NO es lo mismo que construir una URL. `urljoin` y
   `httpx` tambien dejan `///evil.example/x` dentro del origen, y Chromium
   coincide con ellos por esta via. La normalizacion de la backslash, ademas,
   no llega a plantearse: Starlette PERCENT-ENCODEA la backslash y el navegador
   nunca ve una que normalizar.
2. Por tanto **no existe un negativo de navegador para este defecto**, y
   `test_browser_next_open_redirect.py` NO TIENE NEGATIVOS: los cuatro que tuvo
   eran testigos vacuos —verdes pasara lo que pasara— y se han retirado en vez
   de maquillarse. Donde el defecto SI se mide y SI discrimina es en la
   cabecera, en `viewer/tests/test_next_url_open_redirect.py`, cuyo control
   sensible se pone rojo 84 veces al retirar la defensa.

Que Chromium no salga no absuelve al validador: el `Location` seguia llevando
una referencia fuera del sitio, hay clientes HTTP que la resuelven asi —el
propio httpx se NIEGA a parsear `////…`—, y la propiedad que se defiende es
sobre la representacion, no sobre un motor concreto.

TECHO DECLARADO
---------------
- Mide chromium por la cabecera `Location`. NO dice nada de otros motores, ni
  de la misma cadena en un `href`, un `<meta refresh>` o un `location.assign`,
  donde la normalizacion de la backslash SI ocurre.
- Mide `POST /login`. No cubre `/partida/select` ni `GET /login`.
- No prueba la defensa: prueba que las pruebas de navegador de la defensa NO
  podrian ponerse rojas, que es justo por lo que no existen.
"""
from __future__ import annotations

from typing import Iterator, Optional
from urllib.parse import urlparse

import pytest

from e2e_support import ViewerServer, start_viewer

HOSTIL = "evil.example"

#: El destino interno al que cae el validador cuando rechaza.
DESTINO_POR_DEFECTO = "/"


def _validador_preexistente(next_url: Optional[str]) -> str:
    """El criterio EXACTO de la base, reconstruido para retirarlo a voluntad.

    Copia literal de lo que habia en `routers/auth.py` antes del microcarril.
    Vive AQUI y solo aqui: ninguna rama del producto lo contiene.
    """
    if not next_url:
        return "/"
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_url.startswith("/"):
        return "/"
    return next_url


@pytest.fixture(scope="module")
def viewer_calibracion(tmp_path_factory) -> Iterator[ViewerServer]:
    servidor = start_viewer(tmp_path_factory)
    viewer = next(servidor)
    try:
        yield viewer
    finally:
        for _ in servidor:
            pass


@pytest.fixture()
def defensa_retirada(monkeypatch):
    """Sustituye `_safe_next` por el criterio viejo mientras dura el caso.

    El servidor corre en un hilo de ESTE proceso, asi que parchear el atributo
    del modulo alcanza al manejador de la peticion. `monkeypatch` lo restituye
    al terminar, pase lo que pase.
    """
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "_safe_next", _validador_preexistente)
    return _validador_preexistente


def _intentar_login(page, viewer: ViewerServer, next_valor: str) -> list:
    """Login por el formulario real. Devuelve las salidas del origen.

    Aborta y anota toda peticion que no vaya al visor: asi la fuga queda
    registrada sin tocar la red y sin depender de que `evil.example` resuelva
    (no existe: es un dominio de ejemplo).
    """
    from urllib.parse import urlencode

    from playwright.sync_api import Error as PlaywrightError

    fugas: list = []

    def _manejar(route, request):
        if request.url.startswith(viewer.base_url):
            route.continue_()
        else:
            fugas.append(request.url)
            route.abort()

    page.route("**/*", _manejar)
    page.goto(viewer.url("/login?" + urlencode({"next": next_valor})))
    page.fill("#username", "s9reviewer")
    page.fill("#password", viewer.users["s9reviewer"]["password"])
    page.click("#login-submit")
    try:
        # Si el navegador se va a un destino abortado, la navegacion nunca
        # queda «idle» y `goto`/`wait` levantan. Eso NO es el resultado: el
        # resultado es la lista de fugas, que ya esta registrada.
        page.wait_for_load_state("networkidle")
    except PlaywrightError:
        pass
    return fugas


def _salio(fugas: list) -> bool:
    return any(urlparse(u).hostname == HOSTIL for u in fugas)


def _location_crudo(viewer: ViewerServer, next_valor: str) -> str:
    """El `Location` EXACTO que el servidor emite, leido con socket crudo.

    CONTROL DEL CONTROL, y no es ceremonia: sin esto, «Chromium no salio» tiene
    DOS causas indistinguibles —que el caso no escape, o que la defensa no se
    hubiera retirado de verdad— y un rojo con dos causas posibles no dice nada.
    Se usa `http.client` y no un cliente de alto nivel porque los de alto nivel
    intentan RESOLVER la cabecera y algunos se niegan a parsear `////…`: aqui
    hace falta el texto tal cual viaja, no su interpretacion.
    """
    import http.client
    import re as _re
    from urllib.parse import urlencode as _ue

    host = urlparse(viewer.base_url).hostname
    port = urlparse(viewer.base_url).port
    conexion = http.client.HTTPConnection(host, port, timeout=10)

    conexion.request("GET", "/login")
    respuesta = conexion.getresponse()
    cuerpo = respuesta.read().decode("utf-8", "replace")
    galletas = "; ".join(
        c.split(";", 1)[0] for c in respuesta.headers.get_all("set-cookie") or []
    )
    token = _re.search(r'name="csrf_token" value="([^"]*)"', cuerpo).group(1)

    datos = _ue({"username": "s9reviewer",
                 "password": viewer.users["s9reviewer"]["password"],
                 "csrf_token": token, "next": next_valor})
    conexion.request("POST", "/login", body=datos, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": galletas,
    })
    respuesta = conexion.getresponse()
    location = respuesta.getheader("location")
    respuesta.read()
    conexion.close()
    return location


# ---------------------------------------------------------------------------
# LA MEDICION. Para cada representacion: primero se demuestra que la defensa
# esta de verdad retirada (el servidor emite el `Location` hostil), y solo
# despues se le pregunta al navegador a donde va.
# ---------------------------------------------------------------------------

CASOS = [
    ("tres barras", f"///{HOSTIL}/x"),
    ("cuatro barras", f"////{HOSTIL}/x"),
    ("backslash", f"/\\{HOSTIL}/x"),
    ("backslash doble", f"/\\\\{HOSTIL}/x"),
    ("backslash codificada", f"/%5C{HOSTIL}/x"),
    ("barras codificadas", f"/%2F%2F{HOSTIL}/x"),
]


@pytest.mark.parametrize("etiqueta,hostil", CASOS, ids=[e for e, _ in CASOS])
def test_ninguna_de_estas_representaciones_saca_a_chromium_del_producto(
        page, viewer_calibracion, defensa_retirada, etiqueta, hostil):
    """Con la defensa RETIRADA, ¿se va Chromium fuera? MEDIDO: no, ninguna.

    Y por eso `test_browser_next_open_redirect.py` NO TIENE NEGATIVOS: no
    existe, para este defecto y por esta superficie, ningun caso capaz de
    ponerse rojo en un navegador. Presentar cualquiera de estos seis como
    «negativo de navegador» seria exhibir un testigo vacuo.

    Esta prueba es un TRINQUETE EN EL SENTIDO CONTRARIO: afirma la vacuidad. El
    dia que alguna de estas representaciones SI saque a Chromium del producto,
    esto se pondra rojo y habra que reinstaurar el negativo correspondiente.
    """
    # 1. La defensa esta retirada DE VERDAD: el servidor emite el valor hostil.
    location = _location_crudo(viewer_calibracion, hostil)
    # El criterio es «el valor del atacante LLEGO a la cabecera», no «llego
    # literal»: para las backslash, Starlette las percent-encodea al construir
    # el `Location`, asi que `/\evil…` sale como `/%5Cevil…`. Exigir igualdad
    # literal haria fallar esos dos casos por una razon que no es la que se
    # esta midiendo. Lo que distingue «defensa retirada» de «defensa puesta» es
    # que con la defensa puesta el destino cae a `/`, siempre y en los seis.
    assert location != DESTINO_POR_DEFECTO and HOSTIL in location, (
        f"LA CALIBRACION NO ALCANZA AL MANEJADOR: con la defensa supuestamente "
        f"retirada y next={hostil!r} [{etiqueta}], el servidor emitio "
        f"Location={location!r}, que es lo que emitiria con la defensa PUESTA. "
        f"Sin esta comprobacion, un «Chromium no salio» tendria dos causas "
        f"posibles —que el caso no escape, o que la defensa siguiera puesta— y "
        f"no distinguiria ninguna, que es exactamente el rojo sin causa que hay "
        f"que evitar. Arreglar la inyeccion de `_safe_next` antes de leer nada."
    )

    # 2. Ahora si: el navegador tiene la ultima palabra.
    fugas = _intentar_login(page, viewer_calibracion, hostil)
    assert not _salio(fugas), (
        f"CAMBIO DE SUPUESTO, Y HAY QUE ACTUAR: con la defensa retirada y "
        f"next={hostil!r} [{etiqueta}], Chromium SI intento salir del producto "
        f"({fugas!r}). Se habia MEDIDO que ninguna de estas representaciones lo "
        f"conseguia por la cabecera `Location`, y en eso se apoya que "
        f"`test_browser_next_open_redirect.py` no tenga negativos. Si este caso "
        f"ya escapa, la superficie es MAS peligrosa de lo documentado y debe "
        f"ASCENDER a negativo de navegador."
    )

# -*- coding: utf-8 -*-
"""CALIBRACION del control de navegador: cuales de sus negativos DISCRIMINAN.

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

POR QUE LA RESPUESTA LA DA UN NAVEGADOR Y NO UN `urljoin`
---------------------------------------------------------
Esto se midio y conviene dejarlo escrito, porque es el mismo error que causo el
defecto original, una capa mas arriba. Resolviendo `///evil.example/x` contra
`http://127.0.0.1:PUERTO/login`:

    urllib.parse.urljoin  ->  http://127.0.0.1:PUERTO/evil.example/x   (dentro)
    httpx.URL(...).join   ->  http://127.0.0.1:PUERTO/evil.example/x   (dentro)

Los dos resolutores de Python dicen «se queda dentro». La WHATWG URL Standard,
que es la que implementan los navegadores, salta TODAS las barras iniciales al
entrar en la autoridad, asi que un navegador lee `evil.example` como host. Si
se usara `urljoin` como oraculo se concluiria que el caso es vacuo y se estaria
repitiendo el defecto: confundir nuestro parser con el del navegador. El
oraculo de este fichero es Chromium.

LO QUE ESTE FICHERO AFIRMA, CASO A CASO, y por tanto lo que mide
----------------------------------------------------------------
Con la defensa RETIRADA:
  · `///evil.example/x` y `////evil.example/x`  ->  Chromium SALE del producto.
    Son los unicos que hacen de negativo de verdad.
  · `/\evil.example/x`, `/\\…`, `/%5C…`, `/%2F%2F…`  ->  Chromium NO sale,
    porque Starlette PERCENT-ENCODEA la backslash al construir el `Location` y
    el navegador nunca llega a ver una backslash que normalizar. Estos cuatro
    son VACUOS como negativos de navegador, y aqui queda medido que lo son.

Si algun dia Starlette dejara de codificar la backslash, el caso dejaria de ser
vacuo y ESTE FICHERO SE PONDRIA ROJO avisando de ello, en vez de que la suite
siguiera creyendo que aquellos negativos guardaban algo.

TECHO DECLARADO
---------------
- Mide chromium. No dice nada de otros motores.
- Mide `POST /login`. No cubre `/partida/select` ni `GET /login`.
- No prueba la defensa: prueba que la PRUEBA de la defensa puede ponerse roja.
  El verde de este fichero no dice que el producto sea seguro; lo dice
  `test_browser_next_open_redirect.py`, que es a quien esto calibra.
"""
from __future__ import annotations

from typing import Iterator, Optional
from urllib.parse import urlparse

import pytest

from e2e_support import ViewerServer, start_viewer

HOSTIL = "evil.example"


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


# ---------------------------------------------------------------------------
# Los que SI discriminan: con la defensa retirada, el navegador se va fuera.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,hostil", [
    ("tres barras", f"///{HOSTIL}/x"),
    ("cuatro barras", f"////{HOSTIL}/x"),
], ids=["tres barras", "cuatro barras"])
def test_con_la_defensa_retirada_el_navegador_SI_sale(
        page, viewer_calibracion, defensa_retirada, etiqueta, hostil):
    fugas = _intentar_login(page, viewer_calibracion, hostil)
    assert _salio(fugas), (
        f"TESTIGO VACUO: con el validador PREEXISTENTE —es decir, con la "
        f"defensa de este microcarril retirada— y next={hostil!r} [{etiqueta}], "
        f"Chromium NO intento salir del producto (salidas registradas: "
        f"{fugas!r}). Si con la defensa quitada no se va fuera, el negativo "
        f"correspondiente de `test_browser_next_open_redirect.py` esta verde "
        f"pase lo que pase y no esta guardando nada. O el caso ya no escapa "
        f"—y entonces sobra como negativo— o esta calibracion dejo de alcanzar "
        f"al manejador."
    )


# ---------------------------------------------------------------------------
# Los que NO discriminan. Medido, no supuesto: son vacuos COMO NEGATIVOS DE
# NAVEGADOR, y por eso no se usan como tales.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,hostil", [
    ("backslash", f"/\\{HOSTIL}/x"),
    ("backslash doble", f"/\\\\{HOSTIL}/x"),
    ("backslash codificada", f"/%5C{HOSTIL}/x"),
    ("barras codificadas", f"/%2F%2F{HOSTIL}/x"),
], ids=["backslash", "backslash doble", "backslash codificada", "barras codificadas"])
def test_con_la_defensa_retirada_el_navegador_NO_sale(
        page, viewer_calibracion, defensa_retirada, etiqueta, hostil):
    """Estos cuatro NO sirven de negativo de navegador, y conviene que la suite
    lo sepa por medicion y no por una nota en un docstring.

    Starlette percent-encodea la backslash al construir el `Location`, asi que
    el navegador nunca ve la backslash que normalizaria. Siguen siendo rechazos
    obligatorios del validador —eso se mide sobre la cabecera, en
    `viewer/tests/test_next_url_open_redirect.py`—, pero no escapan por si
    solos y por tanto no pueden hacer de negativo AQUI.
    """
    fugas = _intentar_login(page, viewer_calibracion, hostil)
    assert not _salio(fugas), (
        f"CAMBIO DE SUPUESTO: con la defensa retirada y next={hostil!r} "
        f"[{etiqueta}], Chromium SI intento salir ({fugas!r}). Este caso se "
        f"daba por vacuo como negativo de navegador porque Starlette codificaba "
        f"la backslash; si ya no lo hace, la superficie es MAS peligrosa de lo "
        f"documentado y este caso debe ASCENDER a negativo real en "
        f"`test_browser_next_open_redirect.py`."
    )

# -*- coding: utf-8 -*-
r"""CALIBRACION del negativo de navegador: que EL ARNES VE, y que el defecto ESCAPA.

DOS COSAS SE CALIBRAN AQUI, Y LA PRIMERA ES LA QUE FALTABA
-----------------------------------------------------------
1. **Que el arnes no esta ciego.** Con un control de RESULTADO CONOCIDO:
   `//evil.example/x`, protocolo-relativa, que escapa en absolutamente todos
   los instrumentos. Si el arnes lo declarase interno, sus ceros no valdrian
   nada y ningun negativo de este directorio significaria nada.
2. **Que el defecto escapa de verdad**, retirando la defensa y viendo salir al
   navegador.

LA VERSION ANTERIOR DE ESTE FICHERO AFIRMABA UNA FALSEDAD Y NO PODIA PONERSE ROJA
---------------------------------------------------------------------------------
Sostenia que «Chromium no sale del producto con ninguna de las seis
representaciones» y lo cerraba como trinquete. Era falso, y el verde eterno que
lo sostenia venia de un arnes ciego: se observaban las peticiones abortadas
contra un dominio que NO RESUELVE, asi que la navegacion moria en DNS y la
lista quedaba vacia — indistinguible de no haber salido.

Un trinquete que codifica una falsedad y no puede enrojecer no es una prueba
debil: es una GARANTIA FABRICADA, peor que no tener nada.

Con el arnes arreglado (`--host-resolver-rules`, el dominio hostil resuelve a
un servidor trampa propio) y SIN NINGUNA defensa, esto es lo que hace Chromium
de verdad. Medido:

    //evil.example/x        -> SALE   (Host: evil.example en la trampa)
    ///evil.example/x       -> SALE
    ////evil.example/x      -> SALE
    /\evil.example/x        -> dentro (`/%5Cevil.example/x`)
    /%5Cevil.example/x      -> dentro
    /%2F%2Fevil.example/x   -> dentro
    /.//evil.example/x      -> dentro (`//evil.example/x` como RUTA, no autoridad)

**Chromium coincide con WHATWG, con `fetch` y con `curl`. No era un outlier de
motor: no habia outlier, habia un arnes ciego.**

Los unicos que siguen sin discriminar POR ESTA SUPERFICIE son las backslash, y
por una razon concreta y medida: Starlette las PERCENT-ENCODEA al construir el
`Location`, de modo que el navegador nunca recibe una backslash. Bajo WHATWG,
`/\evil.example/x` crudo SI saca del sitio; lo neutraliza el transporte, no el
validador. Razon de mas para que el validador la rechace.

TECHO DECLARADO
---------------
- Mide chromium por la cabecera `Location`, y `POST /login`. No cubre otros
  motores, ni `/partida/select`, ni la misma cadena en un `href`.
- El control de arnes usa un validador IDENTIDAD (sin defensa ninguna), no el
  preexistente: el preexistente ya rechazaba `//evil…`, asi que con el no se
  puede comprobar si el arnes ve una fuga.
"""
from __future__ import annotations

from typing import Iterator, Optional
from urllib.parse import urlencode, urlparse

import pytest

from e2e_support import (
    DOMINIO_HOSTIL,
    ViewerServer,
    navegador_que_resuelve_lo_hostil,
    salio_del_producto,
    servidor_trampa,
    start_viewer,
)

HOSTIL = DOMINIO_HOSTIL


def _validador_preexistente(next_url: Optional[str]) -> str:
    """El criterio EXACTO de la base, reconstruido para retirarlo a voluntad.

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


def _validador_identidad(next_url: Optional[str]) -> str:
    """NINGUNA defensa. Solo para el control de arnes (ver el techo)."""
    return next_url or "/"


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
def trampa():
    with servidor_trampa() as (servidor, puerto):
        yield servidor, puerto


@pytest.fixture()
def pagina_con_trampa(trampa):
    """Chromium propio, con `evil.example` resolviendo a la trampa.

    No se usa la fixture `browser` compartida: necesita `--host-resolver-rules`,
    que es precisamente lo que arregla la ceguera.
    """
    from playwright.sync_api import sync_playwright

    _servidor, puerto = trampa
    with sync_playwright() as p:
        navegador = navegador_que_resuelve_lo_hostil(p, puerto)
        try:
            contexto = navegador.new_context()
            yield contexto.new_page()
        finally:
            navegador.close()


def _login(page, viewer: ViewerServer, next_valor: str):
    from playwright.sync_api import Error as PlaywrightError

    page.goto(viewer.url("/login?" + urlencode({"next": next_valor})))
    page.fill("#username", "s9reviewer")
    page.fill("#password", viewer.users["s9reviewer"]["password"])
    page.click("#login-submit")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightError:
        pass
    return page


# ---------------------------------------------------------------------------
# 1. EL CONTROL DE ARNES. Resultado conocido de antemano.
# ---------------------------------------------------------------------------

def test_el_arnes_VE_una_fuga_de_resultado_conocido(
        pagina_con_trampa, viewer_calibracion, trampa, monkeypatch):
    """`//evil.example/x` escapa en todos los instrumentos. Si este arnes no lo
    ve, sus ceros no valen y ningun negativo de este directorio significa nada.

    Este es EL control que destapo que el arnes anterior estaba ciego, y por eso
    vive dentro de la tabla y no en un comentario.
    """
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "_safe_next", _validador_identidad)
    servidor, _ = trampa

    _login(pagina_con_trampa, viewer_calibracion, f"//{HOSTIL}/x")
    salio, evidencia = salio_del_producto(pagina_con_trampa, servidor)
    assert salio, (
        f"EL ARNES ESTA CIEGO: `//{HOSTIL}/x` es protocolo-relativa y sale del "
        f"sitio en TODOS los instrumentos conocidos, pero este arnes dice que "
        f"el navegador se quedo dentro. Evidencia: {evidencia!r}. Mientras esto "
        f"no pase, NINGUN «no salio» de este directorio significa nada: revisa "
        f"que `--host-resolver-rules` siga instalado y que la trampa reciba "
        f"peticiones. No toques los negativos hasta arreglar esto."
    )


# ---------------------------------------------------------------------------
# 2. EL DEFECTO ESCAPA DE VERDAD, con la defensa preexistente.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,hostil", [
    ("tres barras", f"///{HOSTIL}/x"),
    ("cuatro barras", f"////{HOSTIL}/x"),
], ids=["tres barras", "cuatro barras"])
def test_con_la_defensa_retirada_el_navegador_SI_sale(
        pagina_con_trampa, viewer_calibracion, trampa, monkeypatch,
        etiqueta, hostil):
    """Calibra el negativo de `test_browser_next_open_redirect.py`: con el
    validador PREEXISTENTE, estos dos sacan a Chromium del producto."""
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "_safe_next", _validador_preexistente)
    servidor, _ = trampa

    _login(pagina_con_trampa, viewer_calibracion, hostil)
    salio, evidencia = salio_del_producto(pagina_con_trampa, servidor)
    assert salio, (
        f"TESTIGO VACUO: con el validador PREEXISTENTE y next={hostil!r} "
        f"[{etiqueta}], Chromium NO salio del producto. Evidencia: "
        f"{evidencia!r}. Si con la defensa retirada no se va fuera, el negativo "
        f"correspondiente de `test_browser_next_open_redirect.py` esta verde "
        f"pase lo que pase. Mira primero el control de arnes de este mismo "
        f"fichero: si TAMBIEN fallo, el problema es el arnes y no el caso."
    )


# ---------------------------------------------------------------------------
# 3. LAS BACKSLASH NO DISCRIMINAN POR ESTA SUPERFICIE, y esta medido por que.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,hostil", [
    ("backslash", f"/\\{HOSTIL}/x"),
    ("backslash codificada", f"/%5C{HOSTIL}/x"),
    ("barras codificadas", f"/%2F%2F{HOSTIL}/x"),
], ids=["backslash", "backslash codificada", "barras codificadas"])
def test_las_backslash_no_llegan_a_escapar_por_esta_superficie(
        pagina_con_trampa, viewer_calibracion, trampa, monkeypatch,
        etiqueta, hostil):
    """Sin NINGUNA defensa siguen sin salir, porque Starlette las codifica.

    Ojo con la lectura: esto NO dice que la backslash sea inofensiva. Bajo
    WHATWG `/\evil.example/x` crudo SI saca del sitio. Lo que dice es que POR
    ESTA RUTA el navegador nunca la recibe cruda, asi que no sirve de negativo
    AQUI — y que quien lo impide es el transporte, no el validador.

    Si algun dia Starlette dejara de codificarla, esto se pone rojo y el caso
    debe ASCENDER a negativo de navegador.
    """
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "_safe_next", _validador_identidad)
    servidor, _ = trampa

    _login(pagina_con_trampa, viewer_calibracion, hostil)
    salio, evidencia = salio_del_producto(pagina_con_trampa, servidor)
    assert not salio, (
        f"CAMBIO DE SUPUESTO, Y HAY QUE ACTUAR: sin ninguna defensa y con "
        f"next={hostil!r} [{etiqueta}], Chromium SI salio del producto. "
        f"Evidencia: {evidencia!r}. Se daba por hecho que Starlette "
        f"percent-encodea la backslash antes de que el navegador la vea; si ya "
        f"no lo hace, esta superficie es MAS peligrosa de lo documentado y este "
        f"caso debe ASCENDER a negativo en "
        f"`test_browser_next_open_redirect.py`."
    )

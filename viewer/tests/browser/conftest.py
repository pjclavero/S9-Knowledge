# -*- coding: utf-8 -*-
"""Fixtures de las pruebas de navegador.

La logica reutilizable vive en `e2e_support.py` (importable desde los modulos de
prueba); aqui quedan solo las fixtures, para que `conftest` no tenga que
importarse por nombre desde ningun test.

Alcance de MODULO, deliberadamente: `test_login_browser.py` limpia variables de
entorno y caches de configuracion en su teardown, asi que un servidor compartido
de sesion quedaria hablando con una configuracion que ya no existe. Un servidor
por modulo cuesta ~1 s y elimina el acoplamiento.
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

import pytest

pytest.importorskip("playwright.sync_api", reason="Playwright no instalado: SKIP, no PASS")

from playwright.sync_api import Browser, Error as PlaywrightError, Page, sync_playwright  # noqa: E402

from e2e_support import (  # noqa: E402
    DESKTOP_VIEWPORT,
    ViewerServer,
    attach_recorders,
    start_viewer,
)


@pytest.fixture(scope="module")
def viewer(tmp_path_factory) -> Iterator[ViewerServer]:
    """Visor real con proveedor mock y los cuatro usuarios de laboratorio."""
    yield from start_viewer(tmp_path_factory)


# Los UNICOS motivos que justifican saltarse el modulo: el navegador no esta
# instalado (`playwright install`) o le faltan librerias del sistema
# (`playwright install-deps`). Ambos son «Chromium no esta aqui», no un defecto.
#
# Antes se capturaba `Exception` a secas, asi que cualquier fallo —incluido un
# crash real del navegador— se presentaba como «no disponible», es decir, como un
# SKIP verde. Ahora solo se saltan estos casos y todo lo demas se propaga en rojo.
#
# El mensaje que hay que mirar es `str(exc)`: Playwright adjunta el «Call log» con
# la linea de stderr del proceso, asi que el fallo del cargador dinamico aparece
# ahi aunque el tipo de la excepcion sea un generico `TargetClosedError`.
# (Ojo: NO sirve sondear `browser_type.executable_path`, que apunta al Chromium
# completo mientras que `launch()` arranca `chrome-headless-shell`; son binarios
# distintos con dependencias distintas.)
_CHROMIUM_NO_DISPONIBLE = (
    "executable doesn't exist",
    "please run the following command to download new browsers",
    "error while loading shared libraries",
    "cannot open shared object file",
    "host system is missing dependencies",
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    """Un unico Chromium por modulo; cada prueba usa su propio contexto."""
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except PlaywrightError as exc:
            texto = str(exc).lower()
            if not any(motivo in texto for motivo in _CHROMIUM_NO_DISPONIBLE):
                raise                                 # crash real: que se vea rojo
            pytest.skip(f"chromium no disponible en esta maquina: {exc}")
        try:
            yield b
        finally:
            b.close()


@pytest.fixture()
def new_page(browser) -> Iterator[Callable[..., Page]]:
    """Fabrica de paginas: cada llamada devuelve un contexto limpio y aislado.

    Contextos separados = cookies separadas: asi dos roles pueden estar
    conectados a la vez (el admin revoca, la victima navega) sin compartir
    sesion. Nadie limpia cookies ni cache a mitad de prueba.
    """
    contexts = []

    def _make(viewport: Optional[dict] = None) -> Page:
        ctx = browser.new_context(viewport=viewport or DESKTOP_VIEWPORT)
        contexts.append(ctx)
        return attach_recorders(ctx.new_page())

    try:
        yield _make
    finally:
        for ctx in contexts:
            ctx.close()


@pytest.fixture()
def page(new_page) -> Page:
    return new_page()

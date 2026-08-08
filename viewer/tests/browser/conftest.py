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

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

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


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    """Un unico Chromium por modulo; cada prueba usa su propio contexto."""
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                     # navegador no descargado
            pytest.skip(f"chromium no disponible: {exc}")
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

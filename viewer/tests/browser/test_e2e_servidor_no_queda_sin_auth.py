# -*- coding: utf-8 -*-
"""Guardia SIN NAVEGADOR de que el servidor E2E de este árbol corre con auth
activa de verdad.

Por qué existe: el ancla `S9K_AUTH_ENABLED=false` autouse de
`tests/conftest.py` (pensada para la suite de UNIDAD, ver su docstring) se
coló una vez en este árbol y apagó la autenticación del servidor real que
usan los tests de navegador — no como un fallo con causa, sino como 16 clics
de Playwright que expiraban esperando una redirección que nunca llegaba
(`PYTEST_RC` no lo distinguía de un `SKIP` en una máquina sin Chromium: los
dos son ausencia de evidencia, no evidencia de ausencia). El arreglo vive en
`conftest.py` de este mismo directorio (sobrescribe esa fixture con un
no-op); esta prueba es el testigo BARATO de que sigue sobrescrita: una
petición HTTP directa, sin Playwright, sin cookies, contra el MISMO servidor
de módulo (`viewer`) que arrancan los tests de navegador.

Corre en CUALQUIER máquina con Playwright instalado (la condición de
colección de este directorio, ver `conftest.py`), tenga o no Chromium
utilizable: no lanza ningún navegador.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from e2e_support import ViewerServer


def test_el_servidor_e2e_de_modulo_exige_autenticacion(viewer: ViewerServer) -> None:
    peticion = urllib.request.Request(f"{viewer.base_url}/api/status")
    try:
        with urllib.request.urlopen(peticion, timeout=10) as resp:
            estado = resp.status
    except urllib.error.HTTPError as exc:
        estado = exc.code

    assert estado != 200, (
        "EL SERVIDOR E2E DE MODULO RESPONDE 200 ANONIMO: la autenticacion "
        "del servidor real que usan los tests de navegador esta APAGADA. "
        "Esto pasa cuando algo (por ejemplo, el ancla autouse "
        "S9K_AUTH_ENABLED=false de tests/conftest.py, pensada para la "
        "suite de unidad) se ejecuta DESPUES de que start_viewer() fijara "
        "S9K_AUTH_ENABLED=true para este proceso: el servidor sigue vivo "
        "en un HILO del mismo proceso y comparte os.environ y el "
        "lru_cache de get_auth_settings con el proceso de test."
    )

"""REGRESIÓN: el banco de rendimiento no puede medir un grafo invisible.

Defecto que fija este módulo (14-08-2026)
-----------------------------------------
`benchmarks/perf/calibracion.py` abortaba en la prueba C3 (eje GRADO) con::

    /api/entities/p_0000002 -> 404; no se mide un endpoint que falla

CAUSA RAÍZ, medida y no supuesta: el arnés pone ``S9K_AUTH_ENABLED=false`` para
medir el camino de datos y no el de login. Hasta el commit ``46af55a``
("p0-auth: admin_full deja de tener tres autoridades y ninguna declarada") ese
flag devolvía ``ViewerContext(role="public", admin_full=True)`` y el banco veía
el grafo entero **por accidente**. Desde ``46af55a`` el mismo flag degrada a
``anonymous`` -- lo correcto, y NO se toca. El generador reparte
``visibility = VISIBILITIES[i % 4]`` sobre ``[player, narrator, secret,
reference]``, así que un anónimo sólo ve ``player``: 3 de cada 4 nodos
desaparecen, y los hubs ``p_0000001`` (narrator) y ``p_0000002`` (secret)
devolvían 404.

Lo grave no era el aborto -- ese fue el aviso -- sino que el resto del banco
seguía midiendo un grafo recortado al 25 %: el defecto de v1 (nodos invisibles
por vocabulario) reencarnado por la vía del contexto de autorización.

Por qué vive en `viewer/tests/`
-------------------------------
`benchmarks/**` no está en `testpaths` de `pytest.ini`: **ningún job de CI lo
ejecuta**. Mismo motivo y mismo sitio que
`test_saturacion_grafo_caracterizacion.py`. Y `viewer/tests/` queda FUERA del
hash de `viewer/app/**` que usa la calibración de rendimiento: añadir este
fichero no invalida la calibración.

Este módulo trae su propia CALIBRACIÓN NEGATIVA: reintroduce el defecto en
memoria y comprueba que el guardia se pone ROJO. Un guardia que no puede fallar
no defiende nada.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PERF = RAIZ / "benchmarks" / "perf"
if str(PERF) not in sys.path:
    sys.path.insert(0, str(PERF))

arnes = pytest.importorskip("arnes", reason="laboratorio de rendimiento ausente")
import dataset  # noqa: E402  (queda en sys.path por el bloque de arriba)

# Mismo escenario que usa C3 en `calibracion.main()`.
PARAMS = dataset.Parametros(n_entities=250, hubs=3, grado_hub=120)
# Los cuatro identificadores exactos del eje GRADO de C3.
IDS_C3 = ["p_0000200", "p_0000002", "p_0000001", "p_0000000"]


@pytest.fixture(scope="module", autouse=True)
def _entorno_aislado():
    """El arnés escribe en ``os.environ`` (S9K_DEFAULT_WORKSPACE=perflab, auth
    off) porque `Settings` se cachea con ``lru_cache``. Sin restaurarlo, este
    módulo contamina a los que corren después: medido, tumbaba
    ``test_config.py::test_settings_default_provider_is_mock`` con
    ``'perflab' == 'leyenda'``. Se restaura el entorno ENTERO y se invalidan las
    cachés de configuración.
    """
    import os

    from app.auth.config import get_auth_settings
    from app.config import get_settings

    previo = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previo)
        get_settings.cache_clear()
        try:
            get_auth_settings.cache_clear()
        except AttributeError:  # pragma: no cover - no está cacheada
            pass


@pytest.fixture(scope="module")
def banco():
    cliente, contador, app, entrada = arnes.montar(PARAMS)
    try:
        yield cliente, entrada
    finally:
        app.dependency_overrides.clear()


def test_el_dataset_reparte_los_cuatro_niveles_de_visibilidad(banco):
    """Guardia anti-cero: sin los cuatro niveles, el resto pasaría trivialmente."""
    _, entrada = banco
    grafo = json.loads(entrada.ruta.read_text(encoding="utf-8"))
    presentes = {n["visibility"] for n in grafo["nodes"]}
    assert presentes == set(dataset.VISIBILITIES), presentes
    assert len(presentes) == 4


def test_la_ficha_responde_200_en_los_cuatro_niveles(banco):
    """La propiedad que se rompió: no "responde", sino responde para TODOS."""
    cliente, entrada = banco
    grafo = json.loads(entrada.ruta.read_text(encoding="utf-8"))
    uno_por_nivel: dict[str, str] = {}
    for n in grafo["nodes"]:
        uno_por_nivel.setdefault(n["visibility"], n["id"])
    estados = {
        v: cliente.get(f"/api/entities/{nid}").status_code
        for v, nid in sorted(uno_por_nivel.items())
    }
    assert estados == {v: 200 for v in sorted(dataset.VISIBILITIES)}, estados


@pytest.mark.parametrize("nid", IDS_C3)
def test_los_ids_del_eje_grado_de_c3_no_dan_404(banco, nid):
    """El fallo literal reportado: `/api/entities/p_0000002 -> 404`."""
    cliente, _ = banco
    assert cliente.get(f"/api/entities/{nid}").status_code == 200


def test_el_grafo_medido_no_esta_recortado_por_visibilidad(banco):
    """Con el defecto vivo, `/api/graph` devolvía ~1 de cada 4 nodos."""
    cliente, entrada = banco
    grafo = json.loads(entrada.ruta.read_text(encoding="utf-8"))
    limite = len(grafo["nodes"])
    devuelto = cliente.get(f"/api/graph?limit={limite}").json()
    assert len(devuelto["nodes"]) == limite, (
        f"{len(devuelto['nodes'])} de {limite} nodos: el banco mide un grafo "
        "parcialmente invisible"
    )


def test_calibracion_negativa_el_guardia_sabe_ponerse_rojo(monkeypatch):
    """Reintroducir el defecto EXACTO -> ROJO. Revertir -> VERDE.

    El defecto se reintroduce en memoria (el contexto que la app produce hoy con
    ``S9K_AUTH_ENABLED=false``), sin tocar un byte del árbol. `monkeypatch`
    revierte al salir y el último montaje lo comprueba.
    """
    from app.authz.context import build_viewer_context

    monkeypatch.setattr(
        arnes,
        "contexto_del_banco",
        lambda: build_viewer_context(
            role=None, auth_enabled=False, default_workspace=dataset.WORKSPACE
        ),
    )
    with pytest.raises(RuntimeError, match="PARCIALMENTE INVISIBLE"):
        arnes.montar(PARAMS)

    monkeypatch.undo()
    cliente, _c, app, _e = arnes.montar(PARAMS)  # VERDE de nuevo
    try:
        assert cliente.get("/api/entities/p_0000002").status_code == 200
    finally:
        app.dependency_overrides.clear()

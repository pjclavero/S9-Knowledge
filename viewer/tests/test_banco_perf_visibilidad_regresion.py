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
    # Se afirma el TIPO de fallo, NO el literal del mensaje. Casar contra
    # "PARCIALMENTE INVISIBLE" ataría esta prueba al GRADO del recorte: cuando
    # aterrice el carril de `lore anónimo = denegado`, el anónimo pasará de ver
    # 63 nodos a ver 0 y saltará antes el otro guardia ("El escenario base no
    # devuelve grafo"), con lo que esta prueba se pondría roja **por el motivo
    # equivocado** -- justo la avería que este proyecto ya ha pagado. Ambos
    # guardias lanzan `EscenarioNoMedible`, que es la propiedad real: el
    # escenario no representa al sistema que se va a publicar.
    with pytest.raises(arnes.EscenarioNoMedible) as fallo:
        arnes.montar(PARAMS)
    # El texto sigue siendo diagnóstico útil; se comprueba que dice ALGO de por
    # qué, sin exigir cuál de los dos recortes ocurrió.
    assert str(fallo.value).strip()

    monkeypatch.undo()
    cliente, _c, app, _e = arnes.montar(PARAMS)  # VERDE de nuevo
    try:
        assert cliente.get("/api/entities/p_0000002").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_el_guardia_tambien_enrojece_con_recorte_TOTAL(monkeypatch):
    """El futuro `lore anónimo = denegado`, simulado HOY.

    Ese carril dejará al anónimo viendo **cero** nodos de `perflab` (sus nodos
    no llevan `partida_id` y son `knowledge_layer="book"`). Aquí se fuerza esa
    condición --contexto acotado a otro workspace, 0 nodos visibles-- y se
    comprueba que:

      * el banco **sigue enrojeciendo** (no mide un grafo vacío), y
      * lo hace con el **mismo tipo** `EscenarioNoMedible`, aunque el guardia
        que salta y el texto sean OTROS.

    Es la prueba de que desacoplar el `match` del literal era necesario: se
    afirma explícitamente que el mensaje **no** es el del recorte parcial.
    """
    from app.authz.context import build_viewer_context

    monkeypatch.setattr(
        arnes,
        "contexto_del_banco",
        lambda: build_viewer_context(
            role="viewer", auth_enabled=True, default_workspace="workspace-que-no-existe"
        ),
    )
    with pytest.raises(arnes.EscenarioNoMedible) as fallo:
        arnes.montar(PARAMS)
    assert "PARCIALMENTE INVISIBLE" not in str(fallo.value), (
        "salta OTRO guardia, con OTRO texto: por eso la prueba afirma el tipo"
    )

    monkeypatch.undo()
    _c, _cont, app, _e = arnes.montar(PARAMS)  # VERDE de nuevo
    app.dependency_overrides.clear()


def test_un_montaje_fallido_no_deja_overrides_vivos(monkeypatch):
    """Camino ROJO sin fuga (`construir_cliente` limpia antes de re-lanzar).

    Si los overrides sobrevivieran a un montaje fallido, quedarían instalados en
    la `app` GLOBAL del proceso y **todo test posterior** heredaría un proveedor
    filtrado ajeno -- un rojo por el motivo equivocado, propagado.
    """
    from app.authz.dependencies import get_filtered_provider
    from app.authz.context import build_viewer_context
    from app.deps import get_provider
    from app.main import app

    app.dependency_overrides.clear()
    monkeypatch.setattr(
        arnes,
        "contexto_del_banco",
        lambda: build_viewer_context(
            role=None, auth_enabled=False, default_workspace=dataset.WORKSPACE
        ),
    )
    with pytest.raises(arnes.EscenarioNoMedible):
        arnes.montar(PARAMS)

    fugados = [
        d for d in (get_provider, get_filtered_provider) if d in app.dependency_overrides
    ]
    assert not fugados, f"overrides vivos tras un montaje fallido: {fugados}"


def test_el_arnes_no_fabrica_el_contexto_a_mano():
    """El banco entra por `build_internal_context`, no por la CUARTA vía.

    `authz/context.py` nombra `build_viewer_context(role="admin", ...)` escrito
    a mano fuera del productor como *"una CUARTA vía a la potestad de bypass
    total"*. El guardián AST del P0 escanea **sólo `viewer/app/`**, así que
    `benchmarks/` queda fuera de su vista: este caso cubre ese hueco para el
    único fichero del laboratorio que pide un contexto.
    """
    import ast

    arbol = ast.parse((PERF / "arnes.py").read_text(encoding="utf-8"))
    llamadas = [
        n for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"build_viewer_context", "build_internal_context"}
    ]
    nombres = sorted({n.func.id for n in llamadas})
    assert nombres == ["build_internal_context"], (
        f"`arnes.py` llama a {nombres}: el contexto del banco debe pedirse por la "
        "puerta declarada, no fabricarse a mano"
    )
    # Y el motivo no puede ir en blanco: es lo único que hace revisable la
    # concesión. `build_internal_context` ya lo exige; aquí se ejercita.
    from app.authz.context import build_internal_context

    with pytest.raises(ValueError):
        build_internal_context(motivo="   ")
    assert arnes.contexto_del_banco().admin_full is True

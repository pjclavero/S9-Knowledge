"""Arnés de medida: monta el visor sobre un dataset sintético y mide.

Comparte una sola implementación entre la calibración y la línea base, para que
sea imposible calibrar un instrumento y medir con otro.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"
if str(VIEWER) not in sys.path:
    sys.path.insert(0, str(VIEWER))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import cache  # noqa: E402
import dataset  # noqa: E402
from dataset import Parametros  # noqa: E402
from instrumentation import CountingProvider  # noqa: E402


class EscenarioNoMedible(RuntimeError):
    """El escenario que el banco iba a medir NO representa al sistema medido.

    Un TIPO, no un mensaje. Los dos guardias de montaje --"¿hay grafo?" y
    "¿se ve entero?"-- son la misma propiedad vista desde dos alturas, y qué
    guardia salta primero depende de cuánto recorte haya: con el grafo al 25 %
    salta el de visibilidad; si un día el recorte llega al 100 %, salta antes
    el de "no hay grafo", con otro texto.

    Por eso existe esta clase. Una prueba que casara contra el LITERAL
    ("PARCIALMENTE INVISIBLE") se pondría roja **por el motivo equivocado** en
    cuanto el recorte cambiara de grado -- que es exactamente lo que va a pasar
    cuando aterrice el carril de `lore anónimo = denegado`: el dataset de
    `perflab` no lleva `partida_id` y es `knowledge_layer="book"`, o sea, justo
    el material que ese carril deniega, y el anónimo pasará de ver 63 nodos a
    ver 0. Se afirma el TIPO de fallo; el texto sigue siendo diagnóstico, no
    contrato.
    """


def preparar_entorno(ruta_grafo: Path) -> None:
    """Variables de entorno ANTES de importar la app (Settings usa lru_cache)."""
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    os.environ["S9K_SAMPLE_GRAPH_PATH"] = str(ruta_grafo)
    os.environ["S9K_DEFAULT_WORKSPACE"] = dataset.WORKSPACE
    # Autenticación desactivada: se mide el camino de DATOS, no el de login.
    os.environ["S9K_AUTH_ENABLED"] = "false"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ.setdefault("S9K_CSRF_SECRET", "perf-lab-secret-no-produccion-000000")
    os.environ["S9K_ALLOW_REAL_INGEST"] = ""


def contexto_del_banco():
    """ViewerContext con el que mide el banco: visibilidad COMPLETA, declarada.

    Por qué existe (defecto del banco, 14-08-2026)
    ----------------------------------------------
    ``preparar_entorno`` pone ``S9K_AUTH_ENABLED=false`` para medir el camino de
    DATOS y no el de login. Hasta el commit ``46af55a`` ("p0-auth: admin_full
    deja de tener tres autoridades y ninguna declarada") ese flag devolvía
    ``ViewerContext(role="public", admin_full=True)``: el banco veía el grafo
    entero **por accidente**, apoyado en una concesión de autoridad que era
    justamente el defecto de seguridad que ese commit cerró.

    Desde ``46af55a`` el mismo flag degrada a ``anonymous`` (mínimo privilegio,
    que es lo correcto y NO se toca). El generador reparte
    ``visibility = VISIBILITIES[i % 4]`` sobre
    ``[player, narrator, secret, reference]``, así que un anónimo sólo ve
    ``player``: **3 de cada 4 nodos desaparecen**. Los hubs ``p_0000001``
    (narrator) y ``p_0000002`` (secret) daban 404 y el eje GRADO abortaba.

    El banco no puede medir un grafo parcialmente invisible: es el defecto
    histórico de v1 (25 % de nodos invisibles) reencarnado por otra vía. Y no
    puede recuperar la visibilidad reactivando un atajo de autoridad.

    LA PUERTA, y por qué es ÉSTA
    ----------------------------
    ``build_internal_context(motivo=...)`` es la vía que ``authz/context.py``
    declara para un llamador sin usuario, y exige escribir POR QUÉ. La primera
    versión de esta función llamaba a ``build_viewer_context(role="admin",
    auth_enabled=True)`` a mano: exactamente el patrón que el docstring de
    ``context.py`` nombra como **«una CUARTA vía a la potestad de bypass
    total»**, y el único sitio del repo que lo escribía fuera del propio
    ``context.py`` --el llamador interno del producto (``authz/scope.py``) sí
    usa la puerta--. Que el guardián AST del P0 escanee sólo ``viewer/app/``
    y por tanto no viera esto **no lo hacía correcto**: es el mismo argumento
    del hash del sistema medido, en sentido inverso.

    Es una decisión del INSTRUMENTO, no del sistema medido: no cambia una línea
    de ``viewer/app/**``.
    """
    from app.authz.context import build_internal_context

    return build_internal_context(
        motivo=(
            "banco de rendimiento (benchmarks/perf): mide el camino de DATOS "
            "del visor sobre un dataset sintético, sin usuario ni sesión. "
            "Necesita ver el grafo COMPLETO porque medir un grafo recortado "
            "por visibilidad da cifras de un sistema que no es el que se "
            "publica (docs/67 §0.2). No toca producción ni datos reales."
        )
    )


def construir_cliente(ruta_grafo: Path):
    from fastapi.testclient import TestClient

    from app.authz.dependencies import get_filtered_provider
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.config import get_settings
    from app.deps import get_provider
    from app.main import app
    from app.providers.mock_provider import MockGraphProvider

    get_settings.cache_clear()
    contador = CountingProvider(MockGraphProvider(ruta_grafo))
    app.dependency_overrides[get_provider] = lambda: contador
    # LÍMITE DECLARADO: este contexto es `admin_full`, y `admin_full` es bypass
    # total de la política (`policies/engine.py`: "visible siempre"). Es decir,
    # el banco NO mide el coste de evaluar la política -- exactamente igual que
    # antes de `46af55a`, cuando el bypass llegaba solo por el flag. Se elige a
    # propósito para que las cifras publicadas sigan siendo comparables con las
    # de `main = 0979b8a`; el coste de la política es una medida aparte que este
    # banco no cubre hoy.
    app.dependency_overrides[get_filtered_provider] = (
        lambda: PolicyFilteredProvider(contador, contexto_del_banco())
    )
    cliente = TestClient(app)
    # Camino ROJO sin fuga: si una comprobación lanza, los overrides ya están
    # instalados en la `app` GLOBAL del proceso y nadie los quita -- el llamador
    # no tiene todavía el objeto `app` para limpiarlos en su `finally`. Todo
    # test posterior del mismo proceso heredaría un proveedor filtrado ajeno.
    # Se limpia AQUÍ, antes de re-lanzar, para que un fallo del arnés no
    # contamine lo que venga detrás.
    try:
        comprobar_que_hay_datos(cliente)
        comprobar_visibilidad_completa(cliente, ruta_grafo)
    except BaseException:
        app.dependency_overrides.pop(get_provider, None)
        app.dependency_overrides.pop(get_filtered_provider, None)
        raise
    return cliente, contador, app


def comprobar_visibilidad_completa(cliente, ruta_grafo: Path) -> None:
    """PRUEBA DE REGRESIÓN del 404 del eje GRADO, en el propio arnés.

    Se pone ROJA si el banco vuelve a medir un grafo recortado por la política
    de visibilidad, por el motivo que sea (cambio en el generador, en el
    contexto, en la política, o el que venga). No basta con "el endpoint
    responde 200": se comprueba que responde 200 para **los cuatro niveles de
    visibilidad**, que es la propiedad que se rompió.

    Se ejecuta en TODO montaje, así que cubre calibración y línea base.

    LÍMITE DECLARADO de este guardia (medido por construcción, no por lectura)
    -------------------------------------------------------------------------
    Muestrea **un solo representante por nivel**. Por construcción, entonces,
    **no detecta un recorte que deje al menos un nodo de cada nivel**: si la
    política empezara a ocultar el 90 % de cada nivel, los cuatro representantes
    podrían seguir respondiendo 200 y este guardia pasaría. El que sí lo caza es
    el **conteo** (`len(nodes) == len(grafo["nodes"])`), y ese vive SÓLO en
    `viewer/tests/test_banco_perf_visibilidad_regresion.py`: **ninguna corrida
    del banco lo ejecuta**. Se muestrea así a propósito --el conteo pide una
    petición del tamaño del grafo en cada montaje-- pero el hueco queda escrito
    aquí y en docs/67, no descubierto por el siguiente.
    """
    import json as _json

    grafo = _json.loads(ruta_grafo.read_text(encoding="utf-8"))
    # Un representante por nivel de visibilidad presente en el dataset.
    representantes: dict[str, str] = {}
    for n in grafo["nodes"]:
        representantes.setdefault(n["visibility"], n["id"])
    faltan = sorted(set(dataset.VISIBILITIES) - set(representantes))
    if faltan:
        raise EscenarioNoMedible(
            f"El dataset no contiene nodos de {faltan}: la comprobación de "
            "visibilidad pasaría con menos casos de los que dice cubrir."
        )
    invisibles = {
        v: (nid, cliente.get(f"/api/entities/{nid}").status_code)
        for v, nid in sorted(representantes.items())
        if cliente.get(f"/api/entities/{nid}").status_code != 200
    }
    if invisibles:
        raise EscenarioNoMedible(
            "El banco mediría un grafo PARCIALMENTE INVISIBLE: la ficha de "
            f"entidad no responde 200 para {invisibles} (nivel -> (id, status)). "
            "Medir así da cifras de un sistema que no es el que se publica; fue "
            "el defecto de v1 (25 % de nodos invisibles) y volvió por la vía del "
            "contexto de autorización. Revisa `arnes.contexto_del_banco`."
        )


def montar(p: Parametros):
    """Dataset (con huella) + cliente listo para medir."""
    entrada = cache.obtener(p)
    preparar_entorno(entrada.ruta)
    cliente, contador, app = construir_cliente(entrada.ruta)
    return cliente, contador, app, entrada


def comprobar_que_hay_datos(cliente) -> None:
    """Un grafo vacío se mide rapidísimo y no mide nada.

    Ya pasó en v1: con un nivel de visibilidad fuera de vocabulario la política
    descartaba los nodos y `/api/graph` devolvía 44 bytes en 5 ms. Sin esta
    comprobación, esa cifra habría entrado en la tabla como "excelente".
    """
    r = cliente.get("/api/graph?limit=300")
    datos = r.json() if r.status_code == 200 else {}
    if not datos.get("nodes") or not datos.get("edges"):
        raise EscenarioNoMedible(
            f"El escenario base no devuelve grafo (status={r.status_code}, "
            f"nodos={len(datos.get('nodes', []))}, aristas={len(datos.get('edges', []))}). "
            "Medir esto no tendría sentido."
        )
    filtrado = cliente.get("/api/graph?limit=300&entity_type=Character").json()
    if not filtrado.get("nodes"):
        raise EscenarioNoMedible("El filtro por tipo devuelve 0 nodos: el dataset o el filtro están mal.")


# ---------------------------------------------------------------------------
# Primitivas de medida
# ---------------------------------------------------------------------------

def llamadas_de(cliente, contador: CountingProvider, url: str) -> int:
    """Llamadas a la fuente de datos de UNA petición (con calentamiento)."""
    cliente.get(url)
    contador.reset()
    r = cliente.get(url)
    if r.status_code != 200:
        raise RuntimeError(f"{url} -> {r.status_code}; no se mide un endpoint que falla")
    return contador.snapshot().total_llamadas


def muestra_de(cliente, contador: CountingProvider, url: str):
    cliente.get(url)
    contador.reset()
    r = cliente.get(url)
    return r, contador.snapshot()


def tiempos_de(cliente, url: str, repeticiones: int, calentamiento: int = 5) -> list[float]:
    for _ in range(calentamiento):
        cliente.get(url)
    muestras: list[float] = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        cliente.get(url)
        muestras.append(time.perf_counter() - t0)
    return muestras


CLAVES_LISTA = ("items", "nodes", "edges", "results", "outgoing", "incoming", "sources", "jobs")


def elementos_en(resp) -> int:
    if "application/json" not in resp.headers.get("content-type", ""):
        return 0
    try:
        datos = resp.json()
    except Exception:
        return 0
    if not isinstance(datos, dict):
        return len(datos) if isinstance(datos, list) else 0
    return sum(len(datos[k]) for k in CLAVES_LISTA if isinstance(datos.get(k), list))


def entorno() -> dict[str, Any]:
    import subprocess

    def _cmd(c: str) -> str:
        try:
            return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return "?"

    return {
        "commit": _cmd(f"git -C {RAIZ} rev-parse HEAD"),
        "rama": _cmd(f"git -C {RAIZ} rev-parse --abbrev-ref HEAD"),
        "arbol_limpio": _cmd(f"git -C {RAIZ} status --porcelain") == "",
        "python": sys.version.split()[0],
        "cpu": _cmd("nproc"),
        "modelo_cpu": _cmd("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip(),
        "ram_total": _cmd("grep MemTotal /proc/meminfo"),
        "carga": _cmd("cat /proc/loadavg"),
        "so": _cmd("uname -sr"),
        "advertencia": (
            "Máquina de desarrollo compartida, proveedor mock en memoria, cliente "
            "en proceso. NO es rendimiento de producción: no hay Neo4j, ni red, "
            "ni nginx, ni concurrencia."
        ),
    }

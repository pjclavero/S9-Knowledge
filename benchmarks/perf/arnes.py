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


def construir_cliente(ruta_grafo: Path):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.deps import get_provider
    from app.main import app
    from app.providers.mock_provider import MockGraphProvider

    get_settings.cache_clear()
    contador = CountingProvider(MockGraphProvider(ruta_grafo))
    app.dependency_overrides[get_provider] = lambda: contador
    cliente = TestClient(app)
    comprobar_que_hay_datos(cliente)
    return cliente, contador, app


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
        raise RuntimeError(
            f"El escenario base no devuelve grafo (status={r.status_code}, "
            f"nodos={len(datos.get('nodes', []))}, aristas={len(datos.get('edges', []))}). "
            "Medir esto no tendría sentido."
        )
    filtrado = cliente.get("/api/graph?limit=300&entity_type=Character").json()
    if not filtrado.get("nodes"):
        raise RuntimeError("El filtro por tipo devuelve 0 nodos: el dataset o el filtro están mal.")


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

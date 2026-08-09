"""Medición en NAVEGADOR local del visor de grafo, sobre datos sintéticos.

Arranca el visor real (uvicorn, 127.0.0.1, proveedor mock con el dataset
sintético), entra con un usuario de laboratorio y mide en Chromium:

  * tiempo hasta que el grafo está pintado (fin de la petición ``/api/graph``
    más la estabilización de vis-network),
  * ``DOMContentLoaded`` y ``load`` del documento,
  * número de nodos del DOM y tamaño del payload del grafo,
  * errores de JavaScript y peticiones fallidas,
  * memoria del montón de JS (``performance.memory``), que Chromium sólo da de
    forma aproximada: se anota como indicativo, no como medida fiable.

No toca producción: servidor local efímero, base de auth en un temporal.
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "viewer"))
sys.path.insert(0, str(RAIZ / "viewer" / "tests" / "browser"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dataset  # noqa: E402
import run_bench  # noqa: E402

TAMANOS = [100, 1000, 10000]
LIMITES_GRAFO = [300, 1000]
REPETICIONES = 3


class _FabricaTmp:
    """Sustituto mínimo de ``tmp_path_factory`` para usar `start_viewer` fuera de pytest."""

    def __init__(self) -> None:
        self._raiz = Path(tempfile.mkdtemp(prefix="s9k-perf-nav-"))
        self._n = 0

    def mktemp(self, nombre: str) -> Path:
        self._n += 1
        destino = self._raiz / f"{nombre}{self._n}"
        destino.mkdir(parents=True, exist_ok=True)
        return destino


def _medir_pagina(page, url_grafo: str) -> dict:
    errores: list[str] = []
    fallos_red: list[str] = []
    page.on("pageerror", lambda e: errores.append(str(e)))
    page.on("requestfailed", lambda r: fallos_red.append(f"{r.url}"))

    bytes_grafo = {"n": 0}

    def _anotar(resp):
        if "/api/graph" in resp.url:
            try:
                bytes_grafo["n"] = len(resp.body())
            except Exception:
                pass

    page.on("response", _anotar)

    page.goto(url_grafo, wait_until="load")
    # El grafo se pinta tras `loadEntityTypes().then(loadGraph)`: se espera al
    # lienzo de vis-network con contenido, no a un temporizador arbitrario.
    page.wait_for_function(
        "() => document.querySelector('#graph-canvas canvas') !== null",
        timeout=60000,
    )
    metricas = page.evaluate(
        """() => {
            const nav = performance.getEntriesByType('navigation')[0] || {};
            const grafo = performance.getEntriesByName
                ? performance.getEntriesByType('resource').filter(r => r.name.includes('/api/graph'))
                : [];
            return {
                dom_content_loaded_ms: nav.domContentLoadedEventEnd || 0,
                load_ms: nav.loadEventEnd || 0,
                api_graph_ms: grafo.length ? grafo[grafo.length - 1].duration : null,
                nodos_dom: document.getElementsByTagName('*').length,
                heap_mb: (performance.memory ? performance.memory.usedJSHeapSize : 0) / 1048576,
            };
        }"""
    )
    metricas["errores_js"] = errores
    metricas["peticiones_fallidas"] = fallos_red
    metricas["bytes_api_graph"] = bytes_grafo["n"]
    return metricas


def main() -> int:
    from playwright.sync_api import sync_playwright

    import e2e_support

    resultados: dict[str, dict] = {}
    fabrica = _FabricaTmp()

    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch()
        except Exception as exc:
            # En la máquina donde se tomó la línea base, Chromium está descargado
            # pero le faltan bibliotecas del sistema (libnspr4, libnss3, …) y no
            # hay privilegios para instalarlas. Es "no medido", no "medido bien":
            # se dice, no se disimula con un 0.
            print(f"NO MEDIDO: Chromium no arranca en esta máquina: {str(exc)[:200]}")
            salida = RAIZ / "benchmarks" / "perf" / "resultados" / "navegador.json"
            salida.parent.mkdir(parents=True, exist_ok=True)
            salida.write_text(
                json.dumps(
                    {
                        "entorno": run_bench.entorno(),
                        "medidas": {},
                        "no_medido": "chromium sin bibliotecas del sistema (libnspr4/libnss3); "
                                     "sin privilegios para instalarlas",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return 2
        for n in TAMANOS:
            ruta = run_bench.TMP / f"grafo_{n}.json"
            if not ruta.exists():
                dataset.write(n, ruta)

            gen = e2e_support.start_viewer(
                fabrica,
                env={
                    "S9K_GRAPH_PROVIDER": "mock",
                    "S9K_SAMPLE_GRAPH_PATH": str(ruta),
                    "S9K_DEFAULT_WORKSPACE": dataset.WORKSPACE,
                },
            )
            visor = next(gen)
            try:
                for limite in LIMITES_GRAFO:
                    muestras = []
                    for _ in range(REPETICIONES):
                        ctx = navegador.new_context(viewport=e2e_support.DESKTOP_VIEWPORT)
                        page = ctx.new_page()
                        e2e_support.login_as(page, visor, "s9admin")
                        muestras.append(_medir_pagina(page, visor.url(f"/graph?limit={limite}")))
                        ctx.close()

                    clave = f"{n}_limite{limite}"
                    resultados[clave] = {
                        "entidades": n,
                        "limite_grafo": limite,
                        "load_ms_p50": round(statistics.median(m["load_ms"] for m in muestras), 1),
                        "load_ms_max": round(max(m["load_ms"] for m in muestras), 1),
                        "api_graph_ms_p50": round(
                            statistics.median(m["api_graph_ms"] or 0 for m in muestras), 1
                        ),
                        "api_graph_ms_max": round(max(m["api_graph_ms"] or 0 for m in muestras), 1),
                        "bytes_api_graph": max(m["bytes_api_graph"] for m in muestras),
                        "nodos_dom": max(m["nodos_dom"] for m in muestras),
                        "heap_mb_p50": round(statistics.median(m["heap_mb"] for m in muestras), 1),
                        "errores_js": sorted({e for m in muestras for e in m["errores_js"]}),
                        "peticiones_fallidas": sorted(
                            {f for m in muestras for f in m["peticiones_fallidas"]}
                        ),
                        "muestras": REPETICIONES,
                    }
                    r = resultados[clave]
                    print(
                        f"{n:>6} entidades limite={limite:<5} load_p50={r['load_ms_p50']:>8.1f}ms "
                        f"api_graph_p50={r['api_graph_ms_p50']:>8.1f}ms "
                        f"{r['bytes_api_graph']:>9d}B dom={r['nodos_dom']:>5d} "
                        f"heap={r['heap_mb_p50']:>6.1f}MB errores={len(r['errores_js'])}",
                        flush=True,
                    )
            finally:
                for _ in gen:  # cierra el servidor y restaura el entorno
                    pass
        navegador.close()

    salida = RAIZ / "benchmarks" / "perf" / "resultados" / "navegador.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps({"entorno": run_bench.entorno(), "medidas": resultados}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nInforme: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Línea base de rendimiento del visor sobre datos SINTÉTICOS.

Qué mide
--------
Por cada escenario HTTP: latencia (p50/p95/máx), tamaño de la respuesta, y
—vía ``CountingProvider``— cuántas llamadas hace la aplicación a la fuente de
datos y cuántas filas materializa. La última pareja es la que delata N+1 y
lecturas completas ocultas tras una paginación.

Qué NO mide
-----------
* Latencia real de Neo4j: no hay servidor disponible en esta máquina.
* Concurrencia: todo es secuencial, un cliente.
* Red, TLS, nginx, disco de producción.
Un microbenchmark en un portátil NO es rendimiento productivo. Los números
sirven para comparar commits y detectar crecimientos anómalos, no para
prometer tiempos a un usuario.

Uso:
    python benchmarks/perf/run_bench.py --sizes 100 1000 10000
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"
sys.path.insert(0, str(VIEWER))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dataset  # noqa: E402
from instrumentation import CountingProvider  # noqa: E402

TMP = Path(os.environ.get("PERF_TMP", "/tmp/s9k-perf"))


def _preparar_entorno(ruta_grafo: Path) -> None:
    """Variables de entorno ANTES de importar la app (Settings usa lru_cache)."""
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    os.environ["S9K_SAMPLE_GRAPH_PATH"] = str(ruta_grafo)
    os.environ["S9K_DEFAULT_WORKSPACE"] = dataset.WORKSPACE
    # Autenticación desactivada: se mide el camino de DATOS, no el de login.
    # Con auth off el contexto es admin_full, es decir, el caso MÁS BARATO de
    # política. El coste con un lector no-admin se mide aparte (ver
    # `medir_politica`), sin HTTP.
    os.environ["S9K_AUTH_ENABLED"] = "false"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ.setdefault("S9K_CSRF_SECRET", "perf-lab-secret-no-produccion-000000")
    os.environ["S9K_ALLOW_REAL_INGEST"] = ""


def _construir_cliente(ruta_grafo: Path):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.deps import get_provider
    from app.main import app
    from app.providers.mock_provider import MockGraphProvider

    get_settings.cache_clear()
    contador = CountingProvider(MockGraphProvider(ruta_grafo))
    app.dependency_overrides[get_provider] = lambda: contador
    cliente = TestClient(app)
    _comprobar_que_hay_datos(cliente)
    return cliente, contador, app


def _comprobar_que_hay_datos(cliente) -> None:
    """Un grafo vacío se mide rapidísimo y no mide nada.

    Ya pasó: con un nivel de visibilidad fuera de vocabulario la política
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
# Escenarios
# ---------------------------------------------------------------------------

def escenarios(n: int) -> list[tuple[str, str]]:
    """(nombre, url). Los ids sintéticos son estables por construcción."""
    ultimo_offset = max(0, n - 50)
    medio = f"p_{n // 2:07d}"
    return [
        ("home", "/"),
        ("api_status", "/api/status"),
        ("api_workspaces", "/api/workspaces"),
        ("api_entity_types", "/api/entity-types"),
        ("api_graph_300", "/api/graph?limit=300"),
        ("api_graph_300_filtro_tipo", "/api/graph?limit=300&entity_type=Character"),
        ("api_graph_300_busqueda", "/api/graph?limit=300&q=sintetico"),
        ("api_search", "/api/search?q=sintetico"),
        ("api_entities_pag1", "/api/entities?limit=50&offset=0"),
        ("api_entities_ultima_pag", f"/api/entities?limit=50&offset={ultimo_offset}"),
        ("api_entities_filtro", "/api/entities?limit=50&entity_type=Character"),
        ("api_entity_detalle", f"/api/entities/{medio}"),
        ("api_entity_detalle_legacy", f"/api/entity/{medio}"),
        ("api_sources", "/api/sources"),
        ("api_quality", "/api/quality"),
        ("api_jobs", "/api/jobs"),
        ("html_entities", "/entities?limit=50"),
        ("html_graph", "/graph"),
        ("html_entity_detalle", f"/entities/{medio}"),
        ("html_sources", "/sources"),
        ("html_quality", "/quality"),
        ("html_reviews", "/reviews"),
    ]


def _percentiles(muestras: list[float]) -> dict[str, float]:
    orden = sorted(muestras)
    def pct(p: float) -> float:
        if not orden:
            return 0.0
        k = min(len(orden) - 1, max(0, int(round((p / 100) * (len(orden) - 1)))))
        return orden[k]
    return {
        "p50_ms": round(pct(50) * 1000, 3),
        "p95_ms": round(pct(95) * 1000, 3),
        "max_ms": round(max(orden) * 1000, 3) if orden else 0.0,
        "media_ms": round(statistics.fmean(orden) * 1000, 3) if orden else 0.0,
        "n": len(orden),
    }


_CLAVES_LISTA = ("items", "nodes", "edges", "results", "outgoing", "incoming", "sources", "jobs")


def _elementos_en_respuesta(resp) -> int:
    """Cuántos elementos de dominio devuelve la respuesta (0 si no es JSON)."""
    if "application/json" not in resp.headers.get("content-type", ""):
        return 0
    try:
        datos = resp.json()
    except Exception:
        return 0
    if not isinstance(datos, dict):
        return len(datos) if isinstance(datos, list) else 0
    return sum(len(datos[k]) for k in _CLAVES_LISTA if isinstance(datos.get(k), list))


def medir_escenario(cliente, contador: CountingProvider, url: str, repeticiones: int,
                    calentamiento: int = 3) -> dict[str, Any]:
    for _ in range(calentamiento):
        cliente.get(url)

    # Una pasada aislada para los contadores de fuente de datos.
    contador.reset()
    resp = cliente.get(url)
    muestra = contador.snapshot()

    tiempos: list[float] = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        r = cliente.get(url)
        tiempos.append(time.perf_counter() - t0)
        if r.status_code != resp.status_code:
            resp = r

    return {
        "url": url,
        "status": resp.status_code,
        "bytes": len(resp.content),
        "elementos": _elementos_en_respuesta(resp),
        "llamadas_fuente": muestra.total_llamadas,
        "filas_materializadas": muestra.total_filas,
        "llamadas_por_metodo": dict(muestra.llamadas),
        "filas_por_metodo": dict(muestra.filas),
        **_percentiles(tiempos),
    }


def repeticiones_para(n: int) -> int:
    return {100: 30, 1000: 15}.get(n, 7)


# ---------------------------------------------------------------------------
# Coste de la política con un lector NO admin (sin HTTP)
# ---------------------------------------------------------------------------

def medir_politica(ruta_grafo: Path, n: int) -> list[dict[str, Any]]:
    from app.authz.context import build_viewer_context
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.policies.models import NO_APLICA
    from app.providers.mock_provider import MockGraphProvider

    base = CountingProvider(MockGraphProvider(ruta_grafo))
    # Contexto construido por el MISMO código que usa la aplicación: un lector
    # autenticado de rol `viewer`, sin partida activa. No se falsifica ningún
    # permiso ni se saltan comprobaciones; sólo se evita el login HTTP.
    ctx = build_viewer_context(
        role="viewer",
        auth_enabled=True,
        default_workspace=dataset.WORKSPACE,
        active_partida=None,
        max_visible_session=NO_APLICA,
        active_character=None,
    )
    prov = PolicyFilteredProvider(base, ctx)

    operaciones: list[tuple[str, Callable[[], Any]]] = [
        ("politica_list_entities_p1", lambda: prov.list_entities(dataset.WORKSPACE, limit=50, offset=0)),
        ("politica_graph_300", lambda: prov.graph(dataset.WORKSPACE, limit=300)),
        ("politica_counts", lambda: prov.counts(dataset.WORKSPACE)),
        ("politica_search", lambda: prov.search(dataset.WORKSPACE, "sintetico")),
        ("politica_list_sources", lambda: prov.list_sources(dataset.WORKSPACE)),
        ("politica_quality", lambda: prov.quality_metrics(dataset.WORKSPACE)),
        ("politica_relaciones_entidad", lambda: prov.relations_for_entity(f"p_{n // 2:07d}")),
    ]

    reps = repeticiones_para(n)
    filas = []
    for nombre, op in operaciones:
        op()  # calentamiento
        base.reset()
        op()
        muestra = base.snapshot()
        tiempos = []
        for _ in range(reps):
            t0 = time.perf_counter()
            op()
            tiempos.append(time.perf_counter() - t0)
        filas.append({
            "escenario": nombre,
            "llamadas_fuente": muestra.total_llamadas,
            "filas_materializadas": muestra.total_filas,
            "llamadas_por_metodo": dict(muestra.llamadas),
            **_percentiles(tiempos),
        })
    return filas


# ---------------------------------------------------------------------------
# Consultas Cypher (driver doble)
# ---------------------------------------------------------------------------

def _ficha_entidad(prov, entity_id: str):
    """Reproduce lo que hace ``GET /api/entities/{id}`` sobre el proveedor dado."""
    from app.authz.context import build_viewer_context
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.policies.models import NO_APLICA

    ctx = build_viewer_context(
        role="admin",
        auth_enabled=True,
        default_workspace=dataset.WORKSPACE,
        active_partida=None,
        max_visible_session=NO_APLICA,
        active_character=None,
    )
    filtrado = PolicyFilteredProvider(prov, ctx)
    nodo = filtrado.entity(entity_id)
    salientes, entrantes = filtrado.relations_for_entity(entity_id)
    for arista in salientes:
        filtrado.entity(arista.get("to"))
    for arista in entrantes:
        filtrado.entity(arista.get("from"))
    return nodo, salientes, entrantes


def medir_cypher(n: int) -> list[dict[str, Any]]:
    from fake_neo4j import proveedor_neo4j_falso

    grafo = dataset.generate(n)
    prov, driver = proveedor_neo4j_falso(grafo)
    medio = f"p_{n // 2:07d}"

    operaciones: list[tuple[str, Callable[[], Any]]] = [
        ("cypher_counts", lambda: prov.counts(dataset.WORKSPACE)),
        ("cypher_entity_types", lambda: prov.entity_types(dataset.WORKSPACE)),
        ("cypher_graph_300", lambda: prov.graph(dataset.WORKSPACE, limit=300)),
        ("cypher_list_entities_p1", lambda: prov.list_entities(dataset.WORKSPACE, limit=50)),
        ("cypher_entity", lambda: prov.entity(medio)),
        ("cypher_relations_for_entity", lambda: prov.relations_for_entity(medio)),
        ("cypher_list_sources", lambda: prov.list_sources(dataset.WORKSPACE)),
        ("cypher_quality", lambda: prov.quality_metrics(dataset.WORKSPACE)),
        # La ficha de entidad TAL COMO la sirve el endpoint: nodo, relaciones y
        # el otro extremo de cada relación, con la política en medio. Es la
        # cifra que importa, porque suma el N+1 del endpoint y el de
        # `PolicyFilteredProvider.relations_for_entity`.
        ("cypher_ficha_entidad_completa", lambda: _ficha_entidad(prov, medio)),
    ]
    filas = []
    for nombre, op in operaciones:
        driver.reset()
        op()
        filas.append({
            "operacion": nombre,
            "consultas_cypher": driver.n_consultas,
            "filas_leidas": sum(r.filas for r in driver.registros),
        })
    return filas


# ---------------------------------------------------------------------------
# Detección de N+1 por crecimiento
# ---------------------------------------------------------------------------

UMBRAL_CRECIMIENTO = 1.5  # llamadas x1.5 al multiplicar por 10 el dataset => sospecha


def detectar_n_mas_1(resultados: dict[str, dict[str, dict]], tamanos: list[int]) -> list[dict[str, Any]]:
    """Compara llamadas a la fuente entre el dataset menor y el mayor.

    Un endpoint sano hace un número CONSTANTE de llamadas: no depende de
    cuántas entidades haya. Si el número crece con el dataset, hay una llamada
    por elemento en alguna parte.
    """
    if len(tamanos) < 2:
        return []
    menor, mayor = str(min(tamanos)), str(max(tamanos))
    hallazgos = []
    for nombre in resultados.get(menor, {}):
        a = resultados[menor][nombre]["llamadas_fuente"]
        b = resultados.get(mayor, {}).get(nombre, {}).get("llamadas_fuente")
        if b is None or a == 0:
            continue
        ratio = b / a
        hallazgos.append({
            "escenario": nombre,
            f"llamadas@{menor}": a,
            f"llamadas@{mayor}": b,
            "ratio": round(ratio, 2),
            "veredicto": "N+1" if ratio >= UMBRAL_CRECIMIENTO else "constante",
        })
    return sorted(hallazgos, key=lambda h: h["ratio"], reverse=True)


# Endpoints cuyo tamaño de página se puede variar por parámetro. El eje del
# dataset NO basta: un N+1 por elemento de la PÁGINA (50 elementos, 50 consultas
# extra) da el mismo número de llamadas con 100 que con 10.000 entidades y el
# primer detector lo declararía "constante". Lo descubrió la calibración.
PAGINABLES = {
    "api_entities": "/api/entities?offset=0&limit={k}",
    "api_graph": "/api/graph?limit={k}",
}
PAGINAS = (10, 100)


def detectar_n_mas_1_por_pagina(cliente, contador: CountingProvider) -> list[dict[str, Any]]:
    """¿Crecen las llamadas a la fuente al pedir una página más grande?"""
    hallazgos = []
    for nombre, plantilla in PAGINABLES.items():
        medidas = {}
        for k in PAGINAS:
            url = plantilla.format(k=k)
            cliente.get(url)
            contador.reset()
            cliente.get(url)
            medidas[k] = contador.snapshot().total_llamadas
        pequeno, grande = medidas[PAGINAS[0]], medidas[PAGINAS[1]]
        ratio = grande / pequeno if pequeno else 0.0
        hallazgos.append({
            "escenario": nombre,
            f"llamadas@pagina{PAGINAS[0]}": pequeno,
            f"llamadas@pagina{PAGINAS[1]}": grande,
            "ratio": round(ratio, 2),
            "veredicto": "N+1" if ratio >= UMBRAL_CRECIMIENTO else "constante",
        })
    return hallazgos


def llamadas_por_elemento(filas: dict[str, dict]) -> list[dict[str, Any]]:
    """Llamadas a la fuente por elemento devuelto, para una respuesta dada.

    Tercer eje, el que caza el N+1 de la ficha de entidad: ahí el número de
    consultas no depende del dataset ni de un parámetro de página, sino de
    cuántas relaciones tenga ESA entidad.
    """
    salida = []
    for nombre, r in filas.items():
        elementos = r.get("elementos", 0)
        llamadas = r.get("llamadas_fuente", 0)
        if elementos <= 1 or llamadas <= 2:
            continue
        por_elemento = llamadas / elementos
        salida.append({
            "escenario": nombre,
            "llamadas_fuente": llamadas,
            "elementos_devueltos": elementos,
            "llamadas_por_elemento": round(por_elemento, 3),
            "veredicto": "una consulta por elemento" if por_elemento >= 0.5 else "agregado",
        })
    return sorted(salida, key=lambda h: h["llamadas_por_elemento"], reverse=True)


# ---------------------------------------------------------------------------

def entorno() -> dict[str, Any]:
    def _cmd(c: str) -> str:
        try:
            return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return "?"
    return {
        "commit": _cmd("git -C %s rev-parse --short HEAD" % RAIZ),
        "rama": _cmd("git -C %s rev-parse --abbrev-ref HEAD" % RAIZ),
        "python": sys.version.split()[0],
        "cpu": _cmd("nproc"),
        "modelo_cpu": _cmd("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip(),
        "ram_total": _cmd("grep MemTotal /proc/meminfo"),
        "so": _cmd("uname -sr"),
        "advertencia": (
            "Máquina de desarrollo compartida, proveedor mock en memoria, "
            "cliente en proceso. NO es rendimiento de producción."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    ap.add_argument("--salida", default=str(RAIZ / "benchmarks" / "perf" / "resultados" / "baseline.json"))
    ap.add_argument(
        "--solo-cypher",
        action="store_true",
        help="Recalcula únicamente el recuento de consultas Cypher sobre un "
             "informe ya existente (no vuelve a medir latencias).",
    )
    args = ap.parse_args()

    if args.solo_cypher:
        salida = Path(args.salida)
        informe = json.loads(salida.read_text(encoding="utf-8"))
        _preparar_entorno(TMP / "grafo_100.json")
        for n in args.sizes:
            informe["cypher"][str(n)] = medir_cypher(n)
            print(f"cypher recalculado para {n}", flush=True)
        salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    TMP.mkdir(parents=True, exist_ok=True)
    informe: dict[str, Any] = {
        "entorno": entorno(),
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dataset": {
            "generador": "benchmarks/perf/dataset.py",
            "semilla": 20260809,
            "relaciones_por_entidad": dataset.EDGES_PER_NODE,
            "sintetico": True,
        },
        "http": {},
        "politica_no_admin": {},
        "cypher": {},
    }

    for n in args.sizes:
        ruta = TMP / f"grafo_{n}.json"
        if not ruta.exists():
            dataset.write(n, ruta)
        _preparar_entorno(ruta)

        # Cada tamaño en un proceso limpio sería lo ideal; aquí basta con
        # reconstruir el cliente y limpiar la caché de Settings.
        for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
            if "viewer" not in str(getattr(sys.modules[mod], "__file__", "")):
                sys.modules.pop(mod, None)

        cliente, contador, app = _construir_cliente(ruta)
        reps = repeticiones_para(n)
        print(f"== dataset {n} entidades / {n * dataset.EDGES_PER_NODE} relaciones "
              f"({reps} repeticiones) ==", flush=True)
        filas = {}
        for nombre, url in escenarios(n):
            r = medir_escenario(cliente, contador, url, reps)
            filas[nombre] = r
            print(f"  {nombre:32s} {r['status']} p50={r['p50_ms']:9.2f}ms "
                  f"p95={r['p95_ms']:9.2f}ms max={r['max_ms']:9.2f}ms "
                  f"{r['bytes']:>9d}B llamadas={r['llamadas_fuente']:>5d} "
                  f"filas={r['filas_materializadas']:>8d}", flush=True)
        informe["http"][str(n)] = filas
        informe.setdefault("n_mas_1_por_pagina", {})[str(n)] = detectar_n_mas_1_por_pagina(cliente, contador)
        informe.setdefault("llamadas_por_elemento", {})[str(n)] = llamadas_por_elemento(filas)
        app.dependency_overrides.clear()

        informe["politica_no_admin"][str(n)] = medir_politica(ruta, n)
        informe["cypher"][str(n)] = medir_cypher(n)

    informe["n_mas_1"] = detectar_n_mas_1(informe["http"], args.sizes)
    print("\n== detección de N+1 (crecimiento de llamadas a la fuente) ==")
    for h in informe["n_mas_1"]:
        if h["veredicto"] == "N+1":
            print(f"  [N+1] {h['escenario']:32s} ratio={h['ratio']}", flush=True)

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nInforme: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

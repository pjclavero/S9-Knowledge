"""Línea base de rendimiento y escala del visor (v2), sobre datos SINTÉTICOS.

PUERTA: este guion se NIEGA a emitir cifras si el instrumento no está calibrado.
Comprueba ``resultados/calibracion.json``: que exista, que diga
``instrumento_calibrado: true`` y que el hash de los módulos del arnés coincida
con el que se calibró. Un número producido por un instrumento sin calibrar no es
evidencia; es ruido con aspecto de resultado.

Qué mide
--------
Por escenario HTTP y por tamaño de grafo:
  * latencia: MEDIANA y DISPERSIÓN (MAD, IQR, p05/p95) sobre N repeticiones;
  * coste absoluto: número de llamadas a la fuente de datos y filas
    materializadas;
  * consultas Cypher reales emitidas por ``Neo4jGraphProvider`` (driver doble).

Además:
  * los tres ejes de N+1 (dataset, página, grado) en cada tamaño;
  * casos con HUBS (nodos de grado muy alto), que es donde el coste por
    elemento explota;
  * búsqueda de DISCONTINUIDADES entre tamaños consecutivos —10, 50, 100, 101,
    250, 500— con 101 puesto a propósito justo después de 100.

Qué NO mide (declarado, no omitido)
-----------------------------------
  * Latencia real de Neo4j: no hay servidor en esta máquina.
  * Concurrencia: todo secuencial, un solo cliente en proceso.
  * Red, TLS, nginx, disco, caché de sistema operativo de producción.
  * Coste del camino de autenticación: se mide con auth desactivada.
  * Consumo de memoria.
Un microbenchmark en una máquina de desarrollo compartida NO es rendimiento
productivo. Sirve para comparar commits y detectar crecimientos anómalos.

Uso:
    python benchmarks/perf/calibracion.py     # primero, obligatorio
    python benchmarks/perf/run_bench.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "viewer"))
sys.path.insert(0, str(AQUI))

import arnes  # noqa: E402
import calibracion  # noqa: E402
import dataset  # noqa: E402
import detector  # noqa: E402
import estadistica  # noqa: E402
from dataset import Parametros  # noqa: E402

TAMANOS = [10, 50, 100, 101, 250, 500]
REPETICIONES = 30
PAGINAS = (10, 50, 100)
# Hubs: mismo tamaño de grafo, distinto grado máximo.
GRADOS_HUB = [0, 30, 120, 400]
TAMANO_HUB = 250


# ---------------------------------------------------------------------------
# PUERTA DE CALIBRACIÓN
# ---------------------------------------------------------------------------

def exigir_instrumento_calibrado() -> dict[str, Any]:
    ruta = AQUI / "resultados" / "calibracion.json"
    if not ruta.exists():
        raise SystemExit(
            "No hay calibración. Ejecuta primero benchmarks/perf/calibracion.py.\n"
            "Un instrumento que nunca se ha visto rojo no mide nada."
        )
    inf = json.loads(ruta.read_text(encoding="utf-8"))
    if not inf.get("instrumento_calibrado"):
        raise SystemExit("La calibración existe pero NO pasó. No se emiten cifras.")
    sha_actual = calibracion.sha_del_instrumento()
    if inf.get("sha_del_instrumento") != sha_actual:
        raise SystemExit(
            "La calibración corresponde a otra versión del arnés "
            f"({str(inf.get('sha_del_instrumento'))[:12]} != {sha_actual[:12]}). "
            "Recalibra antes de medir."
        )
    # La calibración avala un INSTRUMENTO sobre un SISTEMA. Si el visor cambió,
    # la calibración caducó aunque el laboratorio no se haya tocado: sin esto,
    # un `calibracion.json` commiteado diciendo `calibrado: true` avala para
    # siempre cifras de un sistema que ya es otro.
    sistema_actual = calibracion.sha_del_sistema_medido()
    if inf.get("sha_del_sistema_medido") != sistema_actual:
        raise SystemExit(
            "La calibración se hizo sobre otro estado de viewer/app/** "
            f"({str(inf.get('sha_del_sistema_medido'))[:12]} != {sistema_actual[:12]}). "
            "Recalibra antes de medir."
        )
    return inf


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------

def escenarios(n: int) -> list[tuple[str, str]]:
    ultimo_offset = max(0, n - 50)
    medio = f"p_{n // 2:07d}"
    return [
        ("api_status", "/api/status"),
        ("api_entity_types", "/api/entity-types"),
        ("api_graph_300", "/api/graph?limit=300"),
        ("api_graph_300_filtro_tipo", "/api/graph?limit=300&entity_type=Character"),
        ("api_search", "/api/search?q=sintetico"),
        ("api_entities_p50", "/api/entities?limit=50&offset=0"),
        ("api_entities_ultima_pag", f"/api/entities?limit=50&offset={ultimo_offset}"),
        ("api_entity_detalle", f"/api/entities/{medio}"),
        ("api_sources", "/api/sources"),
        ("api_quality", "/api/quality"),
        ("html_entities", "/entities?limit=50"),
        ("html_graph", "/graph"),
        ("html_entity_detalle", f"/entities/{medio}"),
    ]


def medir_escenario(cliente, contador, url: str, reps: int) -> dict[str, Any]:
    resp, muestra = arnes.muestra_de(cliente, contador, url)
    resumen = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    return {
        "url": url,
        "status": resp.status_code,
        "bytes": len(resp.content),
        "elementos": arnes.elementos_en(resp),
        "llamadas_fuente": muestra.total_llamadas,
        "filas_materializadas": muestra.total_filas,
        "llamadas_por_metodo": dict(muestra.llamadas),
        "desglose_respuesta": _desglose(resp),
        "latencia": resumen.como_dict(),
    }


def _desglose(resp) -> dict[str, int]:
    """Cuántos nodos/aristas/ítems devuelve, por clave.

    Hace falta para ver la SATURACIÓN: ``/api/graph?limit=300`` deja de crecer a
    partir de ~300 nodos, así que a partir de ahí la serie ya no compara la
    misma carga y la curva no es interpretable como escala.
    """
    if "application/json" not in resp.headers.get("content-type", ""):
        return {}
    try:
        datos = resp.json()
    except Exception:
        return {}
    if not isinstance(datos, dict):
        return {}
    return {k: len(datos[k]) for k in arnes.CLAVES_LISTA if isinstance(datos.get(k), list)}


# ---------------------------------------------------------------------------
# Los tres ejes de N+1, sobre el sistema tal cual está
# ---------------------------------------------------------------------------

def eje_pagina(cliente, contador) -> list[dict[str, Any]]:
    plantillas = {
        "api_entities": "/api/entities?offset=0&limit={k}",
        "api_graph": "/api/graph?limit={k}",
    }
    salida = []
    for nombre, plantilla in plantillas.items():
        medidas = {k: arnes.llamadas_de(cliente, contador, plantilla.format(k=k))
                   for k in PAGINAS}
        salida.append(detector.dictaminar("pagina", nombre, medidas).como_dict())
    return salida


def eje_grado(cliente, contador, grafo, ids: list[str]) -> list[dict[str, Any]]:
    grados = {}
    for nid in ids:
        g = sum(1 for e in grafo["edges"] if e["from"] == nid or e["to"] == nid)
        grados[g] = arnes.llamadas_de(cliente, contador, f"/api/entities/{nid}")
    return [detector.dictaminar("grado", "api_entity_detalle", grados).como_dict()]


def eje_dataset(por_tamano: dict[str, dict[str, dict]]) -> list[dict[str, Any]]:
    tamanos = sorted(int(t) for t in por_tamano)
    nombres = por_tamano[str(tamanos[0])].keys()
    salida = []
    for nombre in nombres:
        medidas = {}
        for t in tamanos:
            fila = por_tamano[str(t)].get(nombre)
            if fila:
                medidas[t] = fila["llamadas_fuente"]
        if len(medidas) >= 2:
            salida.append(detector.dictaminar("dataset", nombre, medidas).como_dict())
    return sorted(salida, key=lambda d: d["pendiente"], reverse=True)


# ---------------------------------------------------------------------------
# Consultas Cypher absolutas (driver doble, sin servidor)
# ---------------------------------------------------------------------------

def medir_cypher(p: Parametros, id_objetivo: str | None = None) -> list[dict[str, Any]]:
    from fake_neo4j import proveedor_neo4j_falso

    grafo = dataset.generate(
        p.n_entities, seed=p.seed, workspace=p.workspace,
        edges_per_node=p.edges_per_node, hubs=p.hubs, grado_hub=p.grado_hub,
    )
    prov, driver = proveedor_neo4j_falso(grafo)
    medio = id_objetivo or f"p_{p.n_entities // 2:07d}"

    operaciones = [
        ("cypher_counts", lambda: prov.counts(dataset.WORKSPACE)),
        ("cypher_entity_types", lambda: prov.entity_types(dataset.WORKSPACE)),
        ("cypher_graph_300", lambda: prov.graph(dataset.WORKSPACE, limit=300)),
        ("cypher_list_entities_p50", lambda: prov.list_entities(dataset.WORKSPACE, limit=50)),
        ("cypher_entity", lambda: prov.entity(medio)),
        ("cypher_relations_for_entity", lambda: prov.relations_for_entity(medio)),
        ("cypher_list_sources", lambda: prov.list_sources(dataset.WORKSPACE)),
        ("cypher_quality", lambda: prov.quality_metrics(dataset.WORKSPACE)),
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
# Discontinuidades entre tamaños consecutivos
# ---------------------------------------------------------------------------

def discontinuidades(por_tamano: dict[str, dict[str, dict]], tamanos: list[int]) -> list[dict[str, Any]]:
    """Saltos entre tamaños consecutivos, con el ruido en la mano.

    Un salto de latencia sólo se declara si el efecto supera 3 MAD combinados.
    Si no, se etiqueta "indistinguible del ruido": el instrumento no puede
    afirmarlo y no se afirma.

    OJO al alcance del veredicto: ``veredicto_latencia`` habla SÓLO de
    milisegundos. Las llamadas a la fuente son deterministas y no tienen ruido,
    así que se juzgan aparte en ``veredicto_llamadas``. En v2.0 ambas cosas
    aparecían bajo una sola etiqueta y una fila con ``delta_llamadas: 10``
    lucía "indistinguible del ruido", que era falso para las llamadas.
    """
    salida = []
    for a, b in zip(tamanos, tamanos[1:]):
        fa, fb = por_tamano.get(str(a), {}), por_tamano.get(str(b), {})
        for nombre in fa:
            if nombre not in fb:
                continue
            la, lb = fa[nombre]["llamadas_fuente"], fb[nombre]["llamadas_fuente"]
            ra = estadistica.Resumen(**fa[nombre]["latencia"])
            rb = estadistica.Resumen(**fb[nombre]["latencia"])
            comp = estadistica.comparar(ra, rb).como_dict()
            comp["veredicto_latencia"] = comp.pop("veredicto")
            da, db = fa[nombre].get("desglose_respuesta", {}), fb[nombre].get("desglose_respuesta", {})
            salida.append({
                "escenario": nombre,
                "de": a,
                "a": b,
                "llamadas": [la, lb],
                "delta_llamadas": lb - la,
                "veredicto_llamadas": ("sin cambio" if lb == la else
                                       f"cambian {lb - la:+d} (determinista, no es ruido)"),
                "mediana_ms": [ra.mediana_ms, rb.mediana_ms],
                "desglose_respuesta": [da, db],
                "saturado": bool(da) and da == db,
                **comp,
            })
    return salida


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", type=int, default=TAMANOS)
    ap.add_argument("--reps", type=int, default=REPETICIONES)
    ap.add_argument("--salida", default=str(AQUI / "resultados" / "baseline_v2.json"))
    args = ap.parse_args()

    calib = exigir_instrumento_calibrado()
    print(f"Instrumento calibrado ({calib['sha_del_instrumento'][:12]}), "
          f"{len(calib['pruebas'])} pruebas de calibración superadas.\n", flush=True)

    informe: dict[str, Any] = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "entorno": arnes.entorno(),
        "calibracion": {
            "sha_del_instrumento": calib["sha_del_instrumento"],
            "generada": calib["generado"],
            "pruebas": [{"nombre": p["nombre"], "superada": p["superada"]}
                        for p in calib["pruebas"]],
        },
        "parametros": {
            "tamanos": args.sizes,
            "repeticiones": args.reps,
            "relaciones_por_entidad": dataset.EDGES_PER_NODE,
            "semilla": dataset.SEMILLA,
            "sintetico": True,
        },
        "no_medido": [
            "latencia real de Neo4j (no hay servidor en esta máquina)",
            "concurrencia (un solo cliente, secuencial)",
            "red, TLS, nginx, disco de producción",
            "coste del camino de autenticación (auth desactivada)",
            "consumo de memoria",
            "datos reales (todo es sintético y determinista)",
        ],
        "http": {},
        "cache": {},
        "n_mas_1": {"pagina": {}, "grado": {}, "dataset": []},
        "cypher": {},
        "hubs": {},
    }

    for n in args.sizes:
        p = Parametros(n_entities=n)
        cliente, contador, app, entrada = arnes.montar(p)
        informe["cache"][str(n)] = {"estado": entrada.estado, "huella": entrada.huella}
        print(f"== {n} entidades / {n * dataset.EDGES_PER_NODE} relaciones "
              f"(caché: {entrada.estado}, {args.reps} repeticiones) ==", flush=True)
        filas = {}
        for nombre, url in escenarios(n):
            r = medir_escenario(cliente, contador, url, args.reps)
            filas[nombre] = r
            lat = r["latencia"]
            print(f"  {nombre:28s} {r['status']} mediana={lat['mediana_ms']:8.3f}ms "
                  f"±MAD {lat['mad_ms']:7.3f} p95={lat['p95_ms']:8.3f} "
                  f"llamadas={r['llamadas_fuente']:>4d} filas={r['filas_materializadas']:>7d} "
                  f"{r['bytes']:>8d}B", flush=True)
        informe["http"][str(n)] = filas
        informe["n_mas_1"]["pagina"][str(n)] = eje_pagina(cliente, contador)
        informe["cypher"][str(n)] = medir_cypher(p)
        app.dependency_overrides.clear()

    informe["n_mas_1"]["dataset"] = eje_dataset(informe["http"], )
    informe["discontinuidades"] = discontinuidades(informe["http"], args.sizes)

    # --- HUBS ---------------------------------------------------------------
    print("\n== hubs: mismo grafo (250 entidades), distinto grado del nodo pedido ==", flush=True)
    for grado in GRADOS_HUB:
        p = Parametros(n_entities=TAMANO_HUB, hubs=1 if grado else 0, grado_hub=grado)
        cliente, contador, app, entrada = arnes.montar(p)
        grafo = json.loads(entrada.ruta.read_text(encoding="utf-8"))
        nid = "p_0000000"
        g_real = sum(1 for e in grafo["edges"] if e["from"] == nid or e["to"] == nid)
        url = f"/api/entities/{nid}"
        r = medir_escenario(cliente, contador, url, args.reps)
        r["grado_real"] = g_real
        r["aristas_totales"] = len(grafo["edges"])
        informe["hubs"][str(grado)] = r
        print(f"  grado={g_real:5d}  mediana={r['latencia']['mediana_ms']:9.3f}ms "
              f"±MAD {r['latencia']['mad_ms']:7.3f}  llamadas={r['llamadas_fuente']:>5d} "
              f"{r['bytes']:>9d}B", flush=True)
        # Eje del grado DENTRO de un mismo grafo: cuatro nodos de grados
        # distintos. Dos puntos no demuestran una pendiente; el detector exige
        # tres o más y responde "insuficiente" si no los hay.
        informe["n_mas_1"]["grado"][str(grado)] = eje_grado(
            cliente, contador, grafo,
            [nid, f"p_{TAMANO_HUB - 1:07d}", f"p_{TAMANO_HUB // 2:07d}",
             f"p_{TAMANO_HUB // 4:07d}"])
        app.dependency_overrides.clear()

    grados_medidos = {r["grado_real"]: r["llamadas_fuente"] for r in informe["hubs"].values()}
    informe["n_mas_1"]["grado_global"] = detector.dictaminar(
        "grado", "api_entity_detalle", grados_medidos).como_dict()

    print("\n== N+1 detectados ==", flush=True)
    for d in informe["n_mas_1"]["dataset"]:
        if d["veredicto"] == "N+1":
            print(f"  [dataset] {d['escenario']:28s} pendiente={d['pendiente']}", flush=True)
    for t, ds in informe["n_mas_1"]["pagina"].items():
        for d in ds:
            if d["veredicto"] == "N+1":
                print(f"  [pagina@{t}] {d['escenario']:24s} pendiente={d['pendiente']}", flush=True)
    g = informe["n_mas_1"]["grado_global"]
    print(f"  [grado] {g['escenario']:28s} pendiente={g['pendiente']} -> {g['veredicto']}", flush=True)

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nInforme: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

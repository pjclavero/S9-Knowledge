"""Convierte `resultados/baseline.json` en las tablas Markdown del informe.

Se mantiene aparte del guion de medida para que regenerar el documento no
implique volver a medir (y para que nadie edite una tabla a mano).

    python3 benchmarks/perf/tablas.py            # imprime las tres tablas
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASELINE = RAIZ / "benchmarks" / "perf" / "resultados" / "baseline.json"


def tabla_http(datos: dict) -> str:
    tamanos = sorted(datos["http"], key=int)
    filas = ["| Escenario | Dataset | p50 (ms) | p95 (ms) | máx (ms) | n | Bytes | llam. | filas |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for nombre in datos["http"][tamanos[0]]:
        for t in tamanos:
            r = datos["http"][t].get(nombre)
            if not r:
                continue
            filas.append(
                f"| `{nombre}` | {int(t):,} | {r['p50_ms']:.1f} | {r['p95_ms']:.1f} | "
                f"{r['max_ms']:.1f} | {r['n']} | {r['bytes']:,} | {r['llamadas_fuente']} | "
                f"{r['filas_materializadas']:,} |"
            )
    return "\n".join(filas).replace(",", ".")


def tabla_politica(datos: dict) -> str:
    tamanos = sorted(datos["politica_no_admin"], key=int)
    filas = ["| Operación (lector `viewer`) | Dataset | p50 (ms) | p95 (ms) | máx (ms) | llam. | filas |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    nombres = [r["escenario"] for r in datos["politica_no_admin"][tamanos[0]]]
    for nombre in nombres:
        for t in tamanos:
            r = next((x for x in datos["politica_no_admin"][t] if x["escenario"] == nombre), None)
            if not r:
                continue
            filas.append(
                f"| `{nombre}` | {int(t):,} | {r['p50_ms']:.2f} | {r['p95_ms']:.2f} | "
                f"{r['max_ms']:.2f} | {r['llamadas_fuente']} | {r['filas_materializadas']:,} |"
            )
    return "\n".join(filas).replace(",", ".")


def tabla_cypher(datos: dict) -> str:
    tamanos = sorted(datos["cypher"], key=int)
    filas = ["| Operación | " + " | ".join(f"consultas @{int(t):,}".replace(",", ".") for t in tamanos) + " |",
             "| --- | " + " | ".join("---:" for _ in tamanos) + " |"]
    nombres = [r["operacion"] for r in datos["cypher"][tamanos[0]]]
    for nombre in nombres:
        celdas = []
        for t in tamanos:
            r = next((x for x in datos["cypher"][t] if x["operacion"] == nombre), None)
            celdas.append(str(r["consultas_cypher"]) if r else "-")
        filas.append(f"| `{nombre}` | " + " | ".join(celdas) + " |")
    return "\n".join(filas)


def main() -> int:
    datos = json.loads(BASELINE.read_text(encoding="utf-8"))
    print("### 4.1 Endpoints HTTP\n")
    print(tabla_http(datos))
    print("\n### 4.2 Política con lector no administrador\n")
    print(tabla_politica(datos))
    print("\n### 4.3 Consultas Cypher\n")
    print(tabla_cypher(datos))
    return 0


if __name__ == "__main__":
    sys.exit(main())

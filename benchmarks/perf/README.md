# Laboratorio de rendimiento del visor (carril H)

Mide. No optimiza. Ninguna de estas piezas se ejecuta en producción ni se
conecta a VM105: datos sintéticos, servidor local, base de autenticación
temporal.

## Piezas

| Fichero | Qué hace |
| --- | --- |
| `dataset.py` | Genera el grafo sintético determinista (100 / 1.000 / 10.000 entidades, 3 relaciones por entidad). |
| `instrumentation.py` | `CountingProvider`: proxy que cuenta llamadas y filas materializadas contra la fuente de datos, por petición. |
| `fake_neo4j.py` | Driver doble que ejecuta el código real de `Neo4jGraphProvider` y **cuenta consultas Cypher** sin necesitar servidor. |
| `run_bench.py` | Línea base: latencias p50/p95/máx, bytes, llamadas y filas por endpoint; tres detectores de N+1. |
| `calibrar_n_mas_1.py` | Calibración obligatoria: inyecta un N+1 conocido y comprueba que el arnés lo marca. |
| `bench_navegador.py` | Medición en Chromium (tiempo de carga, DOM, errores JS, montón). Requiere las bibliotecas de sistema de Chromium. |

## Uso

```bash
python3 benchmarks/perf/run_bench.py --sizes 100 1000 10000
python3 benchmarks/perf/calibrar_n_mas_1.py     # sale 0 si el arnés distingue
python3 benchmarks/perf/bench_navegador.py      # sale 2 si no hay navegador
```

Resultados en `benchmarks/perf/resultados/*.json`. Informe en
`docs/61-perf-viewer-scale-baseline.md`.

## Los tres detectores de N+1

Ninguno basta por sí solo; la calibración demostró por qué.

1. **Crecimiento con el dataset** — llamadas a la fuente con 100 vs 10.000
   entidades. Caza el "una consulta por entidad del workspace".
2. **Crecimiento con el tamaño de página** — llamadas con `limit=10` vs
   `limit=100`. Caza el "una consulta por elemento de la página", que el
   detector 1 declara *constante* porque la página mide lo mismo con cualquier
   dataset. Este eje se añadió **porque la calibración falló sin él**.
3. **Llamadas por elemento devuelto** — caza el caso de la ficha de entidad,
   donde el número de consultas no depende del dataset ni de un parámetro sino
   de cuántas relaciones tenga esa entidad concreta.

## Advertencia que acompaña a cualquier cifra de aquí

Un microbenchmark en una máquina de desarrollo compartida, con el proveedor
mock en memoria y el cliente en el mismo proceso, **no es rendimiento
productivo**. Sirve para comparar commits y para detectar formas de crecimiento
anómalas (lineal donde debería ser constante), no para prometer tiempos.

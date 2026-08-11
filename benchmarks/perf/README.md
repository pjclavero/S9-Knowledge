# Laboratorio de rendimiento del visor (v2)

Datos **sintéticos y deterministas**. Nunca toca producción, ni Neo4j, ni
credenciales, ni la red.

## Orden de ejecución (no es opcional)

```bash
python benchmarks/perf/calibracion.py     # 1. calibrar el instrumento
python benchmarks/perf/run_bench.py       # 2. medir
```

`run_bench.py` **se niega a emitir cifras** si `resultados/calibracion.json` no
existe, no está calibrado, o corresponde a otra versión del arnés (se compara el
hash de los módulos). Un instrumento que nunca se ha visto rojo no mide nada.

## Piezas

| Fichero | Qué es |
|---|---|
| `dataset.py` | Generador sintético determinista. Soporta **hubs** y calcula la **huella** (código + parámetros + vocabulario). |
| `cache.py` | Caché de datasets **con huella**: se invalida sola cuando cambian los datos o el generador. |
| `instrumentation.py` | `CountingProvider`: proxy transparente que cuenta llamadas a la fuente y filas materializadas. |
| `fake_neo4j.py` | Driver doble para contar **consultas Cypher** sin servidor. |
| `detector.py` | Detector de N+1 de **tres ejes** (dataset, página, grado) con criterio de **pendiente por elemento**. |
| `estadistica.py` | Mediana, MAD, IQR y `comparar()` — que responde "indistinguible del ruido" cuando lo es. |
| `arnes.py` | Montaje del visor sobre un dataset y primitivas de medida. |
| `calibracion.py` | **C1–C6**: rojo/verde demostrado de cada mecanismo. Sale 1 si algo no se pudo poner rojo. |
| `run_bench.py` | Línea base: 10/50/100/101/250/500 entidades + casos con hubs. |

## Qué NO mide

Neo4j real, concurrencia, red/TLS/nginx, disco de producción, el camino de
autenticación (se mide con auth desactivada) y el consumo de memoria. Es un
microbenchmark en una máquina de desarrollo compartida: sirve para comparar
commits y cazar crecimientos anómalos, **no** para prometer tiempos a un usuario.

Ver `docs/67-rendimiento-visor-v2.md`.

# Laboratorio de rendimiento del visor (v2.1)

Datos **sintéticos y deterministas**. Nunca toca producción, ni Neo4j, ni
credenciales, ni la red.

## Orden de ejecución (no es opcional)

```bash
python benchmarks/perf/calibracion.py     # 1. calibrar el instrumento
python benchmarks/perf/run_bench.py       # 2. medir
```

`run_bench.py` **se niega a emitir cifras** si `resultados/calibracion.json` no
existe, no está calibrado, o no corresponde a lo que va a medir. "Corresponder"
son dos hashes:

* **`sha_del_instrumento`** — todos los módulos del laboratorio, **incluidos el
  juez (`calibracion.py`), el guion de medida (`run_bench.py`) y el doble de
  driver (`fake_neo4j.py`)**. Si el hash sólo cubre lo medido, se puede
  neutralizar al juez y la puerta sigue contenta.
* **`sha_del_sistema_medido`** — el árbol `viewer/app/**`. Una calibración vieja
  no avala cifras de un sistema que ya es otro.

Cambia cualquiera de los dos y hay que **recalibrar**. Es a propósito.

## Piezas

| Fichero | Qué es |
|---|---|
| `dataset.py` | Generador sintético determinista, con **hubs**, y huella de generador. |
| `cache.py` | Caché con huella de **generador y de contenido** (`sha256_fichero`). |
| `instrumentation.py` | `CountingProvider`: cuenta llamadas a la fuente y filas materializadas. |
| `fake_neo4j.py` | Driver doble para contar consultas Cypher sin servidor. Calibrado en C8. |
| `detector.py` | N+1 en **tres ejes** (dataset, página, grado) por **crecimiento**, sin umbral inventado. ≥ 3 puntos o "insuficiente". |
| `estadistica.py` | Mediana, MAD, IQR y `comparar()` — "indistinguible del ruido" cuando lo es. |
| `arnes.py` | Montaje del visor sobre un dataset y primitivas de medida. |
| `calibracion.py` | **C0–C8**: rojo/verde demostrado de cada mecanismo, el juez incluido. Sale 1 si algo no se pudo poner rojo. |
| `run_bench.py` | Línea base: 10/50/100/101/250/500 entidades + casos con hubs. |

## Veredictos del detector

| Veredicto | Significa |
|---|---|
| `constante` | la serie es **plana**: no crece nada |
| `N+1` | crece de forma no decreciente, al menos `CRECIMIENTO_MINIMO` llamadas |
| `no concluyente` | la serie sube y baja (eje confundido con otra variable) o crece muy poco. **No es "sano"** |
| `insuficiente` | menos de tres puntos: un par de puntos no demuestra una pendiente |

## Qué NO mide

Neo4j real (el conteo de **filas** del doble sigue **sin calibrar**), concurrencia,
red/TLS/nginx, disco de producción, el camino de autenticación (se mide con auth
desactivada), memoria, tamaños > 500 y el navegador. Es un microbenchmark en una
máquina de desarrollo compartida: sirve para comparar commits y cazar
crecimientos anómalos, **no** para prometer tiempos a un usuario.

Ver `docs/67-rendimiento-visor-v2.md`.

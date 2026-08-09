# 61 — Línea base de rendimiento y escala del visor (carril H)

Rama `perf/viewer-scale-baseline-v1`, base `28320bd`. **Esta ronda mide; no
optimiza.** No hay ni un cambio en el código del visor: todo lo añadido vive en
`benchmarks/perf/` y en este documento.

Nada de lo que sigue tocó producción, VM105 ni Neo4j real. Datos sintéticos
generados en el momento, servidor en el propio proceso de la prueba.

---

## 0. Aviso que acompaña a todas las cifras

Un microbenchmark en una máquina de desarrollo compartida (Xeon E5-2680 v4,
8 vCPU, 8,7 GiB de RAM, Debian 13), con el **proveedor mock en memoria** y el
cliente HTTP dentro del mismo proceso Python, **no es rendimiento productivo**.
No mide disco, ni red, ni nginx, ni Neo4j, ni concurrencia.

Lo que sí mide, y para lo que sirve:

* **la forma del crecimiento** — si un endpoint pasa de 4 ms a 90 ms al
  multiplicar por 100 el dataset, eso es una propiedad del código, no de la
  máquina;
* **cuántas veces habla la aplicación con la fuente de datos** y cuántas filas
  materializa por petición, que es independiente del hardware y es lo que se
  convierte en consultas a Neo4j en producción.

Las latencias absolutas son ruidosas (la máquina está compartida): entre dos
ejecuciones de la misma medida se han visto diferencias de 2-3× en los
escenarios más baratos. Los conteos de llamadas y filas son deterministas.

---

## 1. El dataset

`benchmarks/perf/dataset.py`. Determinista (semilla `20260809 ^ N`), sin una
sola cadena procedente de material real.

| Tamaño | Entidades | Relaciones | Documentos fuente |
| --- | --- | --- | --- |
| pequeño | 100 | 300 | 4 |
| medio | 1.000 | 3.000 | 40 |
| grande | 10.000 | 30.000 | 400 |

Cada entidad lleva los campos que el visor lee de verdad, incluidos los de
autorización (`workspace`, `scope`, `visibility`, …) y ~40 palabras de
descripción, para que el coste de serialización sea representativo.

> **Un tropiezo que merece quedar escrito.** La primera versión del generador
> usaba `visibility: "public"`. Ese valor **no está en el vocabulario cerrado
> del motor** (`app/policies/models.py:25`), así que `can_view` lo resolvía como
> `visibility_invalid` y descartaba el 25 % de los nodos *antes incluso del
> bypass de administrador*. `/api/graph?entity_type=Character` devolvía 44 bytes
> en 5 ms: una cifra excelente para un grafo vacío. Ahora
> `dataset.verificar_visibilidad_valida()` contrasta el generador con el
> vocabulario real, y `run_bench._comprobar_que_hay_datos()` aborta la medición
> si el escenario base no devuelve nodos y aristas. El fallo era del dataset,
> pero la lección es del arnés: **una medida que no puede fallar tampoco puede
> acertar**.

---

## 2. El arnés

| Pieza | Qué aporta |
| --- | --- |
| `instrumentation.CountingProvider` | Proxy transparente entre la cadena de autorización y la fuente: cuenta llamadas y filas por método y por petición. No altera resultados. |
| `fake_neo4j.FakeDriver` | Ejecuta el código **real** de `Neo4jGraphProvider` contra un driver doble y registra cada `session.run`. Permite contar consultas Cypher sin servidor. |
| `run_bench.py` | Escenarios HTTP, percentiles, bytes, y los tres detectores de N+1. |
| `calibrar_n_mas_1.py` | Demuestra que el arnés distingue lo bueno de lo malo. |
| `bench_navegador.py` | Medición en Chromium. **No ejecutada**: ver §7. |

---

## 3. Calibración obligatoria: ¿detecta el arnés un N+1 conocido?

Se inyectó en memoria, sobre `PolicyFilteredProvider.list_entities`, una consulta
por cada elemento de la página devuelta — la misma forma que tiene el N+1 real
de la ficha de entidad — y se midió `/api/entities?limit=50`.

```
Llamadas a la fuente en /api/entities?limit=50
  sin parche : {'100': 1, '1000': 1}  -> constante
  con N+1    : {'100': 51, '1000': 51} -> constante   <-- eje 1: CIEGO
  eje 2 (tamaño de página) sin parche: constante / con parche: N+1
Llamadas extra introducidas por el parche (dataset 1000): 50 (esperado 50)
Arnés calibrado: SÍ
```

**El detector original falló y por eso hay tres.** El primer eje comparaba
llamadas entre datasets de 100 y 10.000 entidades; un N+1 *por elemento de la
página* hace exactamente 51 llamadas con cualquier dataset, así que el eje 1 lo
declaraba «constante». Sin la calibración, este informe habría dicho que no hay
N+1 en el listado y habría sido falso. Los ejes son:

1. **crecimiento con el dataset** (100 → 10.000 entidades);
2. **crecimiento con el tamaño de página** (`limit=10` → `limit=100`);
3. **llamadas por elemento devuelto** (caza la ficha de entidad, donde el coste
   depende de las relaciones de *esa* entidad, no de un parámetro).

El parche se revierte en el mismo proceso y la comprobación de vuelta a la línea
base es una aserción del propio guion. Salida completa en
`benchmarks/perf/resultados/calibracion_n_mas_1.json`.

---

## 4. Mediciones

Ejecución: `python3 benchmarks/perf/run_bench.py --sizes 100 1000 10000`.
Commit `28320bd`, 3 peticiones de calentamiento por escenario, tamaño de muestra
30 / 15 / 7 según dataset. Datos crudos completos (incluidos los desgloses por
método) en `benchmarks/perf/resultados/baseline.json`.

Columnas: `llam.` = llamadas a la fuente de datos por petición; `filas` = filas
materializadas por petición (lo que en producción se lee de Neo4j).

### 4.1 Endpoints HTTP

| Escenario | Dataset | p50 (ms) | p95 (ms) | máx (ms) | n | Bytes | llam. | filas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `home` | 100 | 3.3 | 3.9 | 4.4 | 30 | 983 | 0 | 0 |
| `home` | 1.000 | 10.0 | 17.5 | 26.0 | 15 | 983 | 0 | 0 |
| `home` | 10.000 | 12.3 | 16.2 | 16.2 | 7 | 983 | 0 | 0 |
| `api_status` | 100 | 4.4 | 4.8 | 4.9 | 30 | 110 | 4 | 403 |
| `api_status` | 1.000 | 19.9 | 25.8 | 27.2 | 15 | 112 | 4 | 4.003 |
| `api_status` | 10.000 | 158.4 | 210.9 | 210.9 | 7 | 114 | 4 | 40.003 |
| `api_workspaces` | 100 | 4.0 | 4.7 | 6.2 | 30 | 26 | 1 | 1 |
| `api_workspaces` | 1.000 | 16.2 | 30.0 | 34.0 | 15 | 26 | 1 | 1 |
| `api_workspaces` | 10.000 | 17.4 | 21.6 | 21.6 | 7 | 26 | 1 | 1 |
| `api_entity_types` | 100 | 4.5 | 6.6 | 10.5 | 30 | 338 | 1 | 101 |
| `api_entity_types` | 1.000 | 20.1 | 25.9 | 29.4 | 15 | 346 | 1 | 1.001 |
| `api_entity_types` | 10.000 | 50.6 | 65.0 | 65.0 | 7 | 354 | 1 | 10.001 |
| `api_graph_300` | 100 | 20.6 | 23.2 | 24.4 | 30 | 218.335 | 1 | 400 |
| `api_graph_300` | 1.000 | 71.4 | 89.0 | 96.4 | 15 | 410.515 | 1 | 4.000 |
| `api_graph_300` | 10.000 | 118.7 | 194.6 | 194.6 | 7 | 312.549 | 1 | 40.000 |
| `api_graph_300_filtro_tipo` | 100 | 5.4 | 7.0 | 7.8 | 30 | 14.576 | 1 | 16 |
| `api_graph_300_filtro_tipo` | 1.000 | 35.2 | 42.3 | 44.3 | 15 | 147.492 | 1 | 173 |
| `api_graph_300_filtro_tipo` | 10.000 | 42.4 | 56.6 | 56.6 | 7 | 319.758 | 1 | 1.745 |
| `api_graph_300_busqueda` | 100 | 21.3 | 30.2 | 72.1 | 30 | 218.335 | 1 | 400 |
| `api_graph_300_busqueda` | 1.000 | 70.2 | 144.9 | 151.7 | 15 | 410.515 | 1 | 4.000 |
| `api_graph_300_busqueda` | 10.000 | 64.9 | 82.9 | 82.9 | 7 | 312.549 | 1 | 40.000 |
| `api_search` | 100 | 7.8 | 12.8 | 13.7 | 30 | 50.391 | 1 | 100 |
| `api_search` | 1.000 | 21.0 | 37.4 | 41.9 | 15 | 50.708 | 1 | 1.000 |
| `api_search` | 10.000 | 25.8 | 26.9 | 26.9 | 7 | 50.560 | 1 | 10.000 |
| `api_entities_pag1` | 100 | 8.7 | 13.1 | 13.9 | 30 | 50.806 | 1 | 101 |
| `api_entities_pag1` | 1.000 | 44.1 | 55.7 | 55.9 | 15 | 51.883 | 1 | 1.001 |
| `api_entities_pag1` | 10.000 | 20.5 | 21.1 | 21.1 | 7 | 51.731 | 1 | 10.001 |
| `api_entities_ultima_pag` | 100 | 8.0 | 9.6 | 10.3 | 30 | 50.647 | 1 | 101 |
| `api_entities_ultima_pag` | 1.000 | 19.4 | 27.3 | 37.1 | 15 | 51.155 | 1 | 1.001 |
| `api_entities_ultima_pag` | 10.000 | 19.4 | 21.3 | 21.3 | 7 | 51.106 | 1 | 10.001 |
| `api_entities_filtro` | 100 | 5.7 | 7.5 | 8.1 | 30 | 13.684 | 1 | 14 |
| `api_entities_filtro` | 1.000 | 14.0 | 20.2 | 21.2 | 15 | 51.889 | 1 | 126 |
| `api_entities_filtro` | 10.000 | 14.3 | 21.2 | 21.2 | 7 | 51.737 | 1 | 1.251 |
| `api_entity_detalle` | 100 | 5.1 | 6.5 | 6.5 | 30 | 6.778 | 11 | 14 |
| `api_entity_detalle` | 1.000 | 14.9 | 22.5 | 25.5 | 15 | 9.618 | 15 | 20 |
| `api_entity_detalle` | 10.000 | 35.5 | 43.2 | 43.2 | 7 | 2.466 | 5 | 5 |
| `api_entity_detalle_legacy` | 100 | 5.0 | 6.8 | 8.0 | 30 | 6.778 | 11 | 14 |
| `api_entity_detalle_legacy` | 1.000 | 18.0 | 31.2 | 32.2 | 15 | 9.618 | 15 | 20 |
| `api_entity_detalle_legacy` | 10.000 | 23.9 | 38.9 | 38.9 | 7 | 2.466 | 5 | 5 |
| `api_sources` | 100 | 4.7 | 5.3 | 5.4 | 30 | 263 | 1 | 101 |
| `api_sources` | 1.000 | 19.0 | 28.0 | 31.8 | 15 | 2.315 | 1 | 1.001 |
| `api_sources` | 10.000 | 56.3 | 88.2 | 88.2 | 7 | 22.835 | 1 | 10.001 |
| `api_quality` | 100 | 5.4 | 6.3 | 7.6 | 30 | 543 | 1 | 400 |
| `api_quality` | 1.000 | 23.9 | 31.8 | 33.2 | 15 | 565 | 1 | 4.000 |
| `api_quality` | 10.000 | 113.2 | 123.8 | 123.8 | 7 | 587 | 1 | 40.000 |
| `api_jobs` | 100 | 4.9 | 6.0 | 6.0 | 30 | 40 | 0 | 0 |
| `api_jobs` | 1.000 | 14.0 | 21.5 | 21.9 | 15 | 40 | 0 | 0 |
| `api_jobs` | 10.000 | 17.5 | 27.9 | 27.9 | 7 | 40 | 0 | 0 |
| `html_entities` | 100 | 6.1 | 6.9 | 7.3 | 30 | 22.479 | 2 | 202 |
| `html_entities` | 1.000 | 22.1 | 33.5 | 34.8 | 15 | 22.879 | 2 | 2.002 |
| `html_entities` | 10.000 | 49.5 | 104.2 | 104.2 | 7 | 22.557 | 2 | 20.002 |
| `html_graph` | 100 | 3.4 | 4.8 | 6.3 | 30 | 1.857 | 0 | 0 |
| `html_graph` | 1.000 | 10.9 | 18.4 | 24.6 | 15 | 1.857 | 0 | 0 |
| `html_graph` | 10.000 | 11.4 | 12.4 | 12.4 | 7 | 1.857 | 0 | 0 |
| `html_entity_detalle` | 100 | 5.2 | 7.5 | 7.6 | 30 | 5.592 | 11 | 14 |
| `html_entity_detalle` | 1.000 | 10.1 | 20.1 | 20.4 | 15 | 7.067 | 15 | 20 |
| `html_entity_detalle` | 10.000 | 28.4 | 37.7 | 37.7 | 7 | 3.826 | 5 | 5 |
| `html_sources` | 100 | 4.7 | 5.1 | 5.1 | 30 | 2.362 | 1 | 101 |
| `html_sources` | 1.000 | 16.2 | 18.9 | 19.7 | 15 | 13.378 | 1 | 1.001 |
| `html_sources` | 10.000 | 63.3 | 77.5 | 77.5 | 7 | 123.538 | 1 | 10.001 |
| `html_quality` | 100 | 5.1 | 6.0 | 6.1 | 30 | 7.678 | 1 | 400 |
| `html_quality` | 1.000 | 24.7 | 31.5 | 32.5 | 15 | 7.695 | 1 | 4.000 |
| `html_quality` | 10.000 | 178.7 | 273.6 | 273.6 | 7 | 7.712 | 1 | 40.000 |
| `html_reviews` | 100 | 3.7 | 4.7 | 8.0 | 30 | 1.027 | 0 | 0 |
| `html_reviews` | 1.000 | 14.3 | 17.9 | 19.2 | 15 | 1.027 | 0 | 0 |
| `html_reviews` | 10.000 | 5.7 | 17.3 | 17.3 | 7 | 1.027 | 0 | 0 |

### 4.2 Coste de la política con un lector NO administrador

Con la autenticación desactivada el contexto es `admin_full`, que es el caso
**más barato** de la política. Para no medir sólo el camino fácil, se midió
aparte —sin HTTP, con el contexto construido por el código real de la
aplicación— un lector de rol `viewer` sin partida activa:

| Operación (lector `viewer`) | Dataset | p50 (ms) | p95 (ms) | máx (ms) | llam. | filas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `politica_list_entities_p1` | 100 | 0.17 | 0.23 | 0.25 | 1 | 101 |
| `politica_list_entities_p1` | 1.000 | 3.67 | 6.12 | 8.09 | 1 | 1.001 |
| `politica_list_entities_p1` | 10.000 | 23.68 | 24.60 | 24.60 | 1 | 10.001 |
| `politica_graph_300` | 100 | 0.40 | 0.46 | 0.96 | 1 | 400 |
| `politica_graph_300` | 1.000 | 7.74 | 16.65 | 20.61 | 1 | 4.000 |
| `politica_graph_300` | 10.000 | 47.47 | 47.73 | 47.73 | 1 | 40.000 |
| `politica_counts` | 100 | 0.41 | 0.43 | 3.00 | 1 | 400 |
| `politica_counts` | 1.000 | 9.87 | 14.57 | 22.10 | 1 | 4.000 |
| `politica_counts` | 10.000 | 64.21 | 65.75 | 65.75 | 1 | 40.000 |
| `politica_search` | 100 | 0.23 | 0.24 | 0.25 | 1 | 100 |
| `politica_search` | 1.000 | 2.46 | 4.79 | 10.74 | 1 | 1.000 |
| `politica_search` | 10.000 | 29.36 | 30.53 | 30.53 | 1 | 10.000 |
| `politica_list_sources` | 100 | 0.18 | 0.20 | 0.20 | 1 | 101 |
| `politica_list_sources` | 1.000 | 1.96 | 2.10 | 2.18 | 1 | 1.001 |
| `politica_list_sources` | 10.000 | 24.82 | 26.07 | 26.07 | 1 | 10.001 |
| `politica_quality` | 100 | 0.47 | 0.53 | 0.54 | 1 | 400 |
| `politica_quality` | 1.000 | 5.28 | 6.17 | 6.87 | 1 | 4.000 |
| `politica_quality` | 10.000 | 80.05 | 82.08 | 82.08 | 1 | 40.000 |
| `politica_relaciones_entidad` | 100 | 0.00 | 0.01 | 0.01 | 1 | 1 |
| `politica_relaciones_entidad` | 1.000 | 0.44 | 0.72 | 1.05 | 6 | 11 |
| `politica_relaciones_entidad` | 10.000 | 6.69 | 8.35 | 8.35 | 3 | 3 |

### 4.3 Consultas Cypher por operación (driver doble)

Cuenta de `session.run` que emitiría `Neo4jGraphProvider` en producción.

| Operación | consultas @100 | consultas @1.000 | consultas @10.000 |
| --- | ---: | ---: | ---: |
| `cypher_counts` | 2 | 2 | 2 |
| `cypher_entity_types` | 1 | 1 | 1 |
| `cypher_graph_300` | 2 | 1 | 1 |
| `cypher_list_entities_p1` | 2 | 2 | 2 |
| `cypher_entity` | 1 | 1 | 1 |
| `cypher_relations_for_entity` | 2 | 2 | 2 |
| `cypher_list_sources` | 1 | 1 | 1 |
| `cypher_quality` | 13 | 13 | 13 |
| `cypher_ficha_entidad_completa` | 12 | 16 | 6 |

---

## 5. Hallazgos, por impacto

### H1 — Cada petición materializa el workspace entero (`_ALL = 10_000_000`)

`viewer/app/authz/filtered_provider.py:28`, usado en `_visible_nodes` (:55),
`_visible_graph` (:59), `counts` (:67), `search` (:88), `graph` (:94),
`list_entities` (:150), `list_sources` (:186) y `quality_metrics` (:209).

Medido: `GET /api/entities?limit=50` materializa **10.001 filas** con 10.000
entidades para devolver 50. `GET /api/graph?limit=300` materializa **40.000**
para devolver 300. `/api/status`, que responde 114 bytes, materializa **40.003**.

El coste es lineal en el tamaño del workspace **en cada petición**, y el
`SKIP`/`LIMIT` que `neo4j_provider.list_entities` (:253-311) empuja a la base
queda anulado: la política pide `limit=_ALL`. Con Neo4j real esto es un barrido
completo del workspace por petición.

**No es un descuido: es deliberado y está documentado en el propio fichero.** El
filtro tiene que aplicarse sobre el conjunto completo *antes* de paginar, porque
si no los totales y los conteos filtrarían mal y se podría inferir contenido
oculto por diferencia. Cualquier propuesta de arreglo tiene que preservar esa
propiedad. **Ninguna caché de autorización**: ese camino ya costó siete rondas
de revisión en este proyecto. La vía razonable es empujar el predicado de
visibilidad al Cypher, y eso es un carril propio, con su propia batería de
pruebas de autorización — no una optimización que se cuele aquí.

### H2 — N+1 real en la ficha de entidad

Tres capas lo suman:

* `viewer/app/api/entities.py:53-56` — `_with_other_end` llama a `provider.entity()`
  **por cada relación**;
* `viewer/app/routers/readonly.py:205` — `_with_other`, el mismo patrón en el
  endpoint vigente;
* `viewer/app/main.py:486` y `viewer/app/routers/readonly.py:321` — otra vez, en
  las dos vistas HTML de la ficha;
* `viewer/app/authz/filtered_provider.py:126-148` — `relations_for_entity`
  vuelve a pedir el otro extremo de cada arista para decidir su visibilidad.

Medido (dataset 1.000): **15 llamadas a la fuente para 6 elementos devueltos**
(2,5 por elemento). Contado en Cypher con el driver doble, la ficha completa
emite **3 consultas fijas más 2 por cada relación mostrada** (12, 16 y 6 en los tres datasets: la entidad del medio tiene distinto grado en cada uno). Una entidad muy conectada multiplica eso
linealmente: es el caso que peor escala del visor, y el que un usuario nota
antes porque es la página que más se visita.

### H3 — `/api/status` y `/quality` pagan el grafo entero para devolver agregados

`filtered_provider.counts` (:67) y `quality_metrics` (:209) recorren
`_visible_graph` de cada workspace. `/api/status` devuelve **114 bytes** tras materializar **40.003 filas** (p50 158 ms); `/api/quality` tarda p50 113 ms / p95 124 ms y la página `/quality` p50 179 ms / p95 274 ms con 10.000 entidades — los peores tiempos de toda la tabla.
`neo4j_provider.quality_metrics` (:375-460) además emite **13 consultas Cypher**
que la base podría resolver en una sola con agregación.

### H4 — Payload del grafo: ~1 KB por nodo

`GET /api/graph?limit=300` devuelve **~410 KB** (dataset 1.000). El serializador
(`viewer/app/serializers.py:44-78`) emite descripción completa, alias, etiquetas
traducidas y bloque `technical` **para cada nodo del lienzo**, cuando el lienzo
sólo pinta `id`, `label`, `title` y color (`viewer/app/static/js/graph.js:178`).
El resto del payload existe únicamente para rellenar el panel lateral del nodo
que el usuario acabe pulsando — uno de trescientos.

### H5 — `/sources` no pagina

`viewer/app/routers/readonly.py:392-414` lista todas las fuentes del workspace.
Con 400 documentos sintéticos el HTML pesa **123 KB**; el listado de entidades,
que sí pagina, se queda en 22 KB con cualquier dataset. Es el único listado del
visor sin paginación.

### H6 — El grafo se recarga entero en cada cambio de filtro, sin debounce ni cancelación

`viewer/app/static/js/graph.js:233-236`: `reload`, `Enter` en la búsqueda,
cambio de tipo y cambio de límite llaman todos a `loadGraph()`, que vuelve a
pedir `/api/graph` completo, **destruye la red** (`network.destroy()`, :203) y
reconstruye vis-network con estabilización física (:207). No hay `AbortController`
ni retardo: dos cambios seguidos lanzan dos peticiones y **gana la que conteste
la última**, que no tiene por qué ser la última pedida. Con 300 nodos y 410 KB
por respuesta, eso es medio megabyte y dos estabilizaciones por cada duda del
usuario. (Hallazgo por lectura de código: no se pudo confirmar en navegador,
ver §7.)

### H7 — `/api/search` no acota la búsqueda

`filtered_provider.search` (:88) pide `limit=_ALL` a la fuente y recorta a 50
*después* de filtrar — necesario por lo mismo que H1 — pero el proveedor mock
recorre además todos los campos de todos los nodos
(`viewer/app/providers/mock_provider.py:59-71`). Medido: 10.000 filas materializadas para devolver 50.

---

## 6. Presupuestos propuestos (informativos, no son puerta)

Propuesta para discusión; **no se activan como gate en esta ronda** y ninguna de
estas cifras debería convertirse en puerta hasta medirse contra Neo4j real.

| Métrica | Presupuesto propuesto | Dónde estamos hoy (10.000 entidades, mock) |
| --- | --- | --- |
| Llamadas a la fuente por petición de listado | ≤ 3, constante | 1 ✅ |
| Llamadas a la fuente por ficha de entidad | ≤ 3, constante | 5-15, crece con las relaciones ❌ |
| Filas materializadas por petición | ≤ 10 × elementos devueltos | 200× en `/api/entities` ❌ |
| Payload de `/api/graph` con `limit=300` | ≤ 150 KB | ~312-410 KB ❌ |
| Payload HTML de cualquier listado | ≤ 50 KB | 123 KB en `/sources` ❌ |
| Consultas Cypher por endpoint | ≤ 5 | 13 en `/quality` ❌ |

Los dos primeros son los que de verdad recomiendo convertir en puerta cuando
haya arreglo, porque son deterministas: no dependen de la máquina ni del ruido.

---

## 7. Qué NO se midió, y por qué

* **Neo4j real (latencia, planes, índices).** El socket de Docker está denegado
  para este usuario y no hay `sudo` en la máquina; no se puede levantar un Neo4j
  efímero. Se midió lo que sí es medible sin servidor —**el número y la forma de
  las consultas**— ejecutando el código real del proveedor contra un driver
  doble. Los conteos de consultas son fiables; **no hay ni una cifra de latencia
  de base de datos en este informe**.
* **Navegador (tiempo hasta interactivo, DOM, memoria, errores JS).** Chromium
  está descargado pero le faltan bibliotecas del sistema (`libnspr4.so`,
  `libnss3.so`, `libatk`, `libcups`…) y no hay privilegios para instalarlas.
  `bench_navegador.py` queda escrito y probado hasta el punto de arranque; sale
  con código 2 y deja constancia de «no medido» en vez de fingir un cero. H6 es,
  por tanto, un hallazgo de lectura de código, no una medición.
* **Concurrencia.** Todo secuencial, un cliente. Nada de lo aquí medido dice qué
  pasa con diez usuarios a la vez, que es justo donde un barrido completo por
  petición (H1) duele de verdad.
* **El camino de autenticación por HTTP.** Se midió con `S9K_AUTH_ENABLED=false`
  (contexto `admin_full`, el caso más barato de la política) y, aparte, el coste
  de la política con un lector `viewer` sin HTTP (§4.2). No se midió el coste de
  login, sesión, CSRF ni las consultas a `auth.db` que
  `authz/dependencies.py:34-101` hace **por petición** cuando hay partida activa.
* **`data-engine`, ingesta y consola de revisión con volumen.** Fuera del
  encargo.
* **Memoria del proceso del visor.** Sin navegador y con el mock en memoria, la
  cifra habría medido el dataset, no la aplicación.

---

## 8. Asunto de CI: `perf/**` no dispara nada

**Comprobado, y con una corrección al enunciado del encargo.** En `28320bd`:

* `.github/workflows/ci.yml:5` y `supply-chain.yml:5` disparan en
  `main, fix/**, feat/**, audit/**, docs/**, chore/**`. **Sólo esos seis.** El
  encargo daba por cubiertos también `test/**`, `ops/**` y `dependabot/**`: no lo
  están, aunque existen ramas remotas `dependabot/pip/...` y el repositorio ha
  usado `test/**` (`test/viewer-browser-e2e-v1`, mergeada en `d496c08`).
* **No existe `.github/scripts/check_ci_config.py`.** El único guion en esa
  carpeta es `check_unicode.py`. Así que no hay nada que esta rama pueda poner en
  rojo: no es que el comprobador pase, es que no hay comprobador.

Consecuencia inmediata: **esta rama no ejecuta CI en `push`**. Comprobado
empíricamente tras publicarla: `gh run list --branch perf/viewer-scale-baseline-v1`
no devuelve ninguna ejecución. Sí lo hará
cualquier PR que abra contra `main` (el disparador `pull_request` no filtra por
rama de origen), pero el encargo prohíbe abrir PR en esta ronda.

**No se ha renombrado la rama**, que es la decisión ya tomada en un caso
idéntico, y **no se ha tocado `ci.yml`**: el encargo pide proponer y coordinar,
no imponer. Las dos opciones, con su coste:

| Opción | A favor | En contra |
| --- | --- | --- |
| **A. Añadir los prefijos que faltan** (`perf/**`, `test/**`, `ops/**`, `dependabot/**`) | Cambio mínimo y explícito; la lista sigue documentando qué prefijos se consideran legítimos. | Vuelve a pasar en cuanto alguien invente un prefijo nuevo; es la tercera vez que se toca esta lista. |
| **B. Disparar en `'**'`** | Se acaba el problema de raíz: ninguna rama vuelve a quedarse sin CI en silencio. | Gasta minutos de CI en ramas de borrador; hay que confirmar que ningún job asume estar en una rama «de trabajo». |

**Recomendación:** B, con A como parche inmediato si B necesita más discusión. El
fallo que se repite no es «faltaba `perf`», es que *la lista tiene que
adivinar el futuro*. Y si se quiere que el desajuste se note solo, el
`check_ci_config.py` que el encargo daba por existente merece escribirse de
verdad: comparar los prefijos de las ramas remotas vivas con los del disparador y
fallar si alguno no está cubierto. Las tres cosas —cambio del disparador, guion
comprobador y su prueba— son trabajo de un carril de CI, no de éste, y quedan
**propuestas, no hechas**.

---

## 9. Reproducir

```bash
python3 benchmarks/perf/run_bench.py --sizes 100 1000 10000   # línea base
python3 benchmarks/perf/calibrar_n_mas_1.py                   # sale 0 si el arnés vale
python3 benchmarks/perf/bench_navegador.py                    # sale 2 aquí: sin navegador
```

# 67 — Rendimiento y escala del visor (v2): arreglar el instrumento antes de medir

**Repositorio**: S9-Knowledge · **Rama**: `perf/viewer-scale-baseline-v2` ·
**Base medida**: `e9c66dc9a00d0d48cb51d42767ccba1b6e618a38` (main)

Todo lo que sigue se midió sobre datos **sintéticos**, con el proveedor *mock* en
memoria y el cliente en proceso. Nunca se tocó producción, ni VM105, ni Neo4j,
ni credencial alguna.

---

## 0. Por qué hubo una v2

La v1 de este laboratorio produjo una tabla de números. Dos de sus piezas
estaban rotas, y ambas rompían el número, no el adorno:

1. **El detector de N+1 falló su propia calibración.** Su único eje comparaba el
   número de llamadas a la fuente entre el dataset pequeño y el grande. Ese eje
   es ciego al N+1 más común: el que hace **una consulta por elemento
   devuelto**. Con `limit=50`, ese defecto añade 50 llamadas *sea cual sea* el
   tamaño del grafo — pendiente 0 en el eje del dataset, veredicto "constante".
   La calibración de v1 lo dejó registrado (`llamadas_con_defecto_a_pagina_fija:
   51` frente a 1 sano) y aun así el detector siguió declarando salud.
2. **La caché del dataset no tenía huella.** Reutilizaba
   `/tmp/…/grafo_<n>.json` con un `if not ruta.exists()`. Cuando se arregló el
   generador —emitía un nivel de visibilidad fuera del vocabulario del motor y
   el 25 % de los nodos era invisible—, los ficheros ya cacheados seguían
   conteniendo el grafo malo. Una caché sin huella es una máquina de resucitar
   defectos.

Un instrumento que nunca se ha visto rojo no mide nada. Así que v2 empieza por
el instrumento y **sólo después** mide.

---

## 1. El instrumento de v2

| Pieza | Cambio respecto a v1 |
|---|---|
| `detector.py` | **Tres ejes** (dataset, página, grado) y criterio de **pendiente por elemento** (`llamadas extra / elemento extra ≥ 0.5`), no un cociente. Un cociente es ciego a las constantes y absurdo cuando la base es 1. |
| `dataset.py` | Calcula la **huella**: SHA-256 de (código fuente del generador + parámetros + vocabulario emitido + versión de formato). Soporta **hubs**. |
| `cache.py` | Caché **con huella** en un *sidecar* `*.huella.json`. Estados explícitos: `generado`, `reutilizado`, `regenerado_por_huella`, `regenerado_sin_huella`. |
| `estadistica.py` | Mediana + MAD + IQR + p05/p95 sobre ≥ 5 repeticiones (aquí 30–40). `comparar()` devuelve **"indistinguible del ruido"** si el efecto no supera 3 MAD combinados. |
| `calibracion.py` | C1–C6: rojo y verde demostrados. Sale con código 1 si algún mecanismo no se pudo poner rojo. |
| `run_bench.py` | **Puerta**: se niega a emitir cifras si no hay calibración, si no pasó, o si el hash de los módulos del arnés no coincide con el calibrado. |

### El tercer eje, el que faltaba

Hay tres formas de N+1 y ninguna tapa a las otras:

* **eje DATASET** — una llamada por entidad del grafo. Crece con `n` a página fija.
* **eje PÁGINA** — una llamada por elemento devuelto. Crece con `limit`, **invisible en el eje del dataset**.
* **eje GRADO** — una llamada por relación del nodo pedido. No depende ni de `n` ni de `limit`, sólo del **grado**. Es el que caza el defecto real de la ficha de entidad, y por eso los hubs son el caso que revienta.

---

## 2. Tabla de calibración (salidas reales)

Fichero completo: `benchmarks/perf/resultados/calibracion.json`
(SHA del instrumento `7e6e0250…`, Python 3.13.5, Xeon E5-2680 v4, 8 vCPU).

| # | Afirmación | Violación introducida | Estado con violación | Tras revertir | ¿Superada? |
|---|---|---|---|---|---|
| **C1** | El eje PÁGINA detecta un N+1 por elemento devuelto | `PolicyFilteredProvider.list_entities` + 1 `entity()` por elemento de la página | llamadas 10→100 elementos: **11 → 101**, pendiente **1.0**, veredicto **N+1** | 1 → 1, pendiente 0.0, **constante** (idéntico al de antes) | **SÍ** |
| **C1b** | *(ceguera de v1, documentada)* El eje DATASET **no** ve ese N+1 | la misma | con `limit=50` fijo: **51 llamadas** con el defecto, y pendiente 0 en el eje del dataset → "constante" | — | *hallazgo* |
| **C2** | El eje DATASET detecta un N+1 por entidad del grafo | `list_entities` + 1 `entity()` por entidad del *workspace* | n=10→500: **0 → 501**, pendiente **1.0224**, veredicto **N+1** | 0 → 1, pendiente 0.002, **constante** | **SÍ** |
| **C3** | El eje GRADO detecta un N+1 por relación | *ninguna: el defecto ya está en el código real* (`/api/entities/{id}` pide una entidad por arista) | grado 4→125: **11 → 253 llamadas**, pendiente **2.0**, veredicto **N+1** | control sin relaciones: 3 → 3, pendiente 0.0, **constante**; al revertir el control, vuelve a **N+1** idéntico | **SÍ** |
| **C4** | La caché se invalida sola cuando cambian datos o generador | se estropea el generador (nivel `public`, fuera de vocabulario) y se fabrica el fichero rancio | estados observados: `generado`, `reutilizado`, **`regenerado_por_huella`**, `regenerado_por_huella`, **`regenerado_sin_huella`**, `reutilizado`. Huellas distintas: `2da727cf…` (sano) vs `164ba1f2…` (roto). El fichero cacheado **contenía** el defecto y **la regla de v1 lo habría reutilizado** | tras v2 el defecto desaparece del fichero | **SÍ** |
| **C5** | Un presupuesto absoluto de llamadas se rompe con una regresión | 5 consultas extra por petición | presupuesto `llamadas_fuente ≤ 1`, medido **6.0** → 1 incumplimiento | lista de incumplimientos **vacía** | **SÍ** |
| **C6** | La estadística distingue efecto de ruido | retardo real de **5 ms** por petición | mediana 8.55 → **14.19 ms**, ruido 0.85 ms, factor efecto/ruido **6.64** → **"peor"** | 8.55 → 8.56 ms, factor **0.01** → **"indistinguible del ruido"** | **SÍ** |

Control negativo de C6, el que evita el instrumento que grita siempre: medir dos
veces lo mismo da factor **0.02** y veredicto "indistinguible del ruido".

C4 añade una segunda defensa independiente: el generador se **niega** a escribir
un nivel de visibilidad fuera del vocabulario del motor (`guardia_de_vocabulario_
tambien_salta: true`); la calibración la desactiva a propósito para poder
fabricar el fichero rancio que necesita.

**Instrumento calibrado: SÍ** (6/6). `run_bench.py` sólo mide después de esto.

---

## 3. Cifras medidas

`benchmarks/perf/resultados/baseline_v2.json`. 30 repeticiones por escenario,
5 de calentamiento. Formato: **mediana ± MAD (ms) / llamadas a la fuente**.

| escenario | n=10 | n=50 | n=100 | n=101 | n=250 | n=500 |
|---|---|---|---|---|---|---|
| api_status | 4.1±0.08 / 4 | 4.5±0.07 / 4 | 5.0±0.16 / 4 | 5.2±0.07 / 4 | 6.1±0.14 / 4 | 7.3±0.06 / 4 |
| api_entity_types | 4.1±0.09 / 1 | 4.5±0.07 / 1 | 4.9±0.14 / 1 | 5.1±0.12 / 1 | 5.7±0.11 / 1 | 6.1±0.08 / 1 |
| api_graph_300 | 6.0±0.19 / 1 | 13.3±0.31 / 1 | 21.7±0.64 / 1 | 21.9±0.72 / 1 | 47.5±1.60 / 1 | 45.0±0.65 / 1 |
| api_graph_300_filtro_tipo | 4.5±0.14 / 1 | 6.1±1.04 / 1 | 6.1±0.17 / 1 | 6.3±0.17 / 1 | 8.1±0.10 / 1 | 10.8±0.13 / 1 |
| api_search | 4.9±0.11 / 1 | 8.4±0.31 / 1 | 8.3±0.19 / 1 | 8.4±0.12 / 1 | 9.0±0.25 / 1 | 9.6±0.14 / 1 |
| api_entities_p50 | 5.7±0.32 / 1 | 8.4±0.10 / 1 | 8.6±0.14 / 1 | 8.8±0.17 / 1 | 9.4±0.18 / 1 | 9.7±0.19 / 1 |
| api_entities_ultima_pag | 6.1±0.48 / 1 | 8.9±0.52 / 1 | 8.8±0.25 / 1 | 9.0±0.22 / 1 | 9.7±0.37 / 1 | 9.8±0.24 / 1 |
| api_entity_detalle | 5.3±0.20 / 11 | 6.0±0.23 / 19 | 5.9±0.34 / 11 | 6.6±0.18 / 21 | 6.3±0.16 / 11 | 6.7±0.10 / 11 |
| api_sources | 4.7±0.13 / 1 | 4.8±0.06 / 1 | 5.2±0.09 / 1 | 5.5±0.10 / 1 | 6.0±0.10 / 1 | 6.6±0.09 / 1 |
| api_quality | 4.7±0.12 / 1 | 5.1±0.18 / 1 | 5.8±0.11 / 1 | 6.0±0.11 / 1 | 7.1±0.20 / 1 | 8.6±0.13 / 1 |
| html_entities | 5.1±0.14 / 2 | 6.1±0.11 / 2 | 6.4±0.15 / 2 | 6.7±0.17 / 2 | 7.4±0.19 / 2 | 7.9±0.14 / 2 |
| html_graph | 3.2±0.04 / 0 | 3.6±0.16 / 0 | 3.8±0.10 / 0 | 4.1±0.12 / 0 | 4.5±0.12 / 0 | 4.7±0.09 / 0 |
| html_entity_detalle | 4.8±0.09 / 11 | 5.3±0.24 / 19 | 5.5±0.13 / 11 | 6.0±0.15 / 21 | 6.1±0.11 / 11 | 6.5±0.11 / 11 |

La dispersión relativa (MAD/mediana) se queda entre el 1 % y el 5 % en casi
todos los escenarios; la excepción es `api_graph_300_filtro_tipo` a n=50
(±1.04 ms sobre 6.1, ~17 %), donde el ruido de la máquina se come el efecto.

### Consultas Cypher absolutas (driver doble, n=250)

No hay servidor Neo4j en esta máquina, así que no se mide latencia de base de
datos; sí se cuenta **cuántas consultas emite el proveedor real**:

| operación | consultas Cypher | filas leídas |
|---|---|---|
| `counts` | 2 | 2 |
| `entity_types` | 1 | 8 |
| `graph(limit=300)` | 2 | 550 |
| `list_entities(limit=50)` | 2 | 51 |
| `entity(id)` | 1 | 1 |
| `relations_for_entity(id)` | 2 | 4 |
| `list_sources` | 1 | 8 |
| `quality_metrics` | **13** | 41 |

`quality_metrics` emite 13 consultas para una sola pantalla. Es constante (no
crece con el dataset), pero es el número absoluto más alto del visor.

---

## 4. Hubs: donde revientan las consultas

Mismo grafo (250 entidades), variando el **grado** del nodo pedido en
`/api/entities/{id}`:

| grado del nodo | llamadas a la fuente | mediana ± MAD | bytes |
|---|---|---|---|
| 3 | 9 | 6.65 ± 0.11 ms | 5 364 |
| 33 | 69 | 9.86 ± 0.18 ms | 48 177 |
| 125 | 253 | 19.83 ± 0.48 ms | 179 836 |
| **406** | **815** | **50.57 ± 1.45 ms** | 583 167 |

Pendiente medida: **2.0 llamadas a la fuente por cada relación del nodo**
(veredicto `N+1` en el eje GRADO). Son dos porque el endpoint resuelve la
entidad del otro extremo de cada arista, entrante y saliente, una a una.

Coste absoluto, no relativo: **un nodo de grado 406 cuesta 815 llamadas y 50 ms**
frente a 9 llamadas y 6.6 ms de un nodo normal. En un grafo de lore real, los
nodos de grado alto son precisamente los que más se consultan (la ciudad
principal, el dios del panteón, la facción central). No hay tope: el grado no
está paginado.

**Este es el hallazgo de rendimiento de v2.** No se ha arreglado en esta rama —
el arreglo vive en `viewer/app/routers/readonly.py` y en la cadena de
autorización, zona de otros carriles.

---

## 5. Discontinuidades (10 → 50 → 100 → **101** → 250 → 500)

`101` está en la lista a propósito, para buscar un salto justo pasado 100.

* **No hay discontinuidad en 100 → 101.** Ningún escenario da un salto de
  latencia que supere el ruido (el mayor factor efecto/ruido es 1.79, por debajo
  del umbral de 3).
* El único cambio grande de 100 a 101 es `api_entity_detalle`: **11 → 21
  llamadas**. No es un umbral del sistema: el nodo medido (`p_0000050`) tiene
  grado **4** en el grafo de 100 y grado **9** en el de 101, porque son grafos
  distintos. Es el eje GRADO otra vez, no una discontinuidad de escala. Se
  comprueba recontando los grados del generador.
* Saltos reales de latencia que **sí** superan el ruido: `api_graph_300`
  (6.0 → 13.3 → 21.7 → 47.5 ms) y `api_graph_300_filtro_tipo` /
  `api_quality` / `api_status`, todos con **0** llamadas extra a la fuente:
  el coste está en serializar y transferir más filas, no en consultar más veces.
* **Anomalía sin explicar**: `api_graph_300` mide **47.5 ms a n=250 y 45.0 ms a
  n=500**, con el mismo número de llamadas y menos bytes (523 KB vs 550 KB). El
  efecto supera el ruido, así que no es jitter; lo más probable es la interacción
  entre el `limit=300` y la composición del grafo generado. **No se investigó.**
  Se deja anotado en vez de maquillado.

---

## 6. Qué NO se midió (declarado, no omitido)

* **Neo4j real.** No hay servidor accesible desde esta máquina. Todo el conteo
  de Cypher sale de un driver doble que ejecuta el código real del proveedor
  pero **no ejecuta Cypher**: los recuentos de filas son plausibles, no exactos.
  No hay plan de ejecución, ni índices, ni latencia de red a la base.
* **Producción.** Ni una petición a VM105. Ni ingestas, ni backups, ni despliegue.
* **Concurrencia.** Un solo cliente, secuencial. Nada dice este informe sobre
  qué pasa con 10 usuarios a la vez.
* **Red, TLS, nginx, disco de producción.**
* **El camino de autenticación**: se mide con `S9K_AUTH_ENABLED=false`, es decir,
  el caso más barato de política (contexto de administrador). El coste con un
  lector no-admin y con partida activa **no se midió en v2**.
* **Memoria.** Ni pico ni residente.
* **Tamaños por encima de 500 entidades.** El grafo real de producción es mayor;
  extrapolar desde aquí sería inventar.
* **El navegador.** Render, JS, *layout* del grafo: fuera de alcance.

Y una limitación del propio método: la máquina es de desarrollo y **compartida**
(carga observada durante la medición: `3.31 2.36 1.33`). Por eso todo va con
mediana y MAD, y por eso el informe dice "indistinguible del ruido" cuando lo
es en vez de reportar una mejora.

---

## 7. Supervivientes clasificados

**Defectos reales confirmados con el instrumento calibrado**

1. **N+1 por grado en la ficha de entidad** (`GET /api/entities/{id}` y
   `/entities/{id}`): 2 llamadas por relación, sin tope. 815 llamadas y 50 ms
   para un nodo de grado 406. *Severidad: alta en cuanto haya hubs.*
2. **`quality_metrics` emite 13 consultas Cypher** por pantalla. Constante, pero
   es el número absoluto más alto. *Severidad: baja-media.*

**Defectos del instrumento, corregidos en esta rama**

3. Detector de N+1 de un solo eje, ciego al N+1 por página → tres ejes con
   criterio de pendiente (C1, C1b, C2, C3).
4. Caché de datasets sin huella → huella + *sidecar* + invalidación automática (C4).
5. Cifras de una sola pasada → mediana, MAD, IQR y veredicto de ruido (C6).
6. Nada obligaba a calibrar antes de medir → puerta con hash del arnés en
   `run_bench.py`.

**Sin evidencia (no afirmado)**

7. Ninguna discontinuidad al cruzar 100 entidades.
8. La anomalía de `api_graph_300` entre 250 y 500 no está explicada.

**Deuda declarada**

9. `benchmarks/**` no está en `testpaths` de `pytest.ini`, así que la
   calibración **no corre en CI**: hoy es una puerta manual (`calibracion.py`
   sale 1 si falla). Añadirla a CI toca ficheros compartidos con otros carriles
   y no se ha hecho aquí.
10. El coste de la política con un lector no-admin no se midió.

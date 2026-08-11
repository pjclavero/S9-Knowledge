# 67 — Rendimiento y escala del visor (v2): arreglar el instrumento antes de medir

**Repositorio**: S9-Knowledge · **Rama**: `perf/viewer-scale-baseline-v2` ·
**Base medida**: `cb874fe1141e4a17008c362c0aa404a90889128d` (main)

Todo lo que sigue se midió sobre datos **sintéticos**, con el proveedor *mock* en
memoria y el cliente en proceso. Nunca se tocó producción, ni VM105, ni Neo4j,
ni credencial alguna.

---

## 0. Por qué hubo una v2, y por qué hubo que rehacer la v2

La **v1** produjo una tabla de números con dos piezas rotas: un detector de N+1
de un solo eje —ciego al N+1 por elemento de página— y una caché sin huella,
capaz de resucitar el defecto del 25 % de nodos invisibles que se acababa de
arreglar.

La **v2.0** arregló esas dos y, en la revisión, resultó tener tres agujeros del
mismo tipo. Se documentan porque el patrón se repite: *el instrumento afirmaba
más de lo que podía demostrar*.

| Agujero de v2.0 | Cómo se demostró | Corrección en v2.1 |
|---|---|---|
| Umbral fijo de **0.5 llamadas/elemento**, inventado y sin justificar | 1 consulta cada 3 elementos → pendiente 0.333 → **"constante"**. Igual 1/5 (0.20) y √n (0.078). Tres N+1 reales declarados sanos | Se elimina el umbral. Criterio de **crecimiento**: una serie plana es constante, una serie que crece de forma no decreciente es N+1, una serie que sube y baja es **"no concluyente"** — nunca "sana" |
| La **huella de la caché no cubría el fichero** | Se genera el dataset, se **trunca a 2 nodos con `visibility: "public"`** y se deja el sidecar intacto → estado `reutilizado`, defecto resucitado, cero avisos | El sidecar guarda también `sha256_fichero`; discrepancia → `regenerado_por_contenido` |
| El **doble de driver Cypher nunca se vio rojo** y estaba **fuera del hash**; y neutralizar `_ok()` hacía pasar las 6 calibraciones vacuamente | Se saboteó `fake_neo4j` para contar la mitad de consultas y la puerta imprimió "instrumento calibrado" y emitió la tabla falseada | `fake_neo4j.py`, `calibracion.py` y `run_bench.py` entran en el hash del instrumento; **C8** calibra el driver contra un contador independiente; **C0** exige que el juez sepa fallar |
| La puerta **no fijaba el commit del sistema medido** | Un cambio en `viewer/app/**` no movía ningún hash: una calibración caduca seguía avalando cifras | La calibración registra `sha_del_sistema_medido` (árbol `viewer/app/**`) y la puerta lo compara |
| **C2 pasaba por el motivo equivocado** | `dependency_overrides` es un diccionario del `app` global y la prueba mantenía dos clientes vivos: ganaba el último, el "cliente de n=10" leía el grafo de 500 y su contador marcaba **0**. El rojo `1.0224` era `501/490`, aritmética sobre un cero fantasma | Los clientes se montan y miden **secuencialmente**, uno vivo a la vez, y C2 exige además que ningún contador base valga 0 |

Un instrumento que nunca se ha visto rojo no mide nada. Y un instrumento cuyo
**juez** nunca se ha visto rojo, tampoco.

---

## 1. El instrumento de v2.1

| Pieza | Qué hace |
|---|---|
| `detector.py` | Tres ejes (dataset, página, **grado**). Criterio de **crecimiento**, sin umbral. Exige **≥ 3 puntos** para afirmar una pendiente; con dos dice "insuficiente". Veredictos: `constante` / `N+1` / `no concluyente` / `insuficiente`. |
| `dataset.py` | Generador determinista con **hubs**. Huella = SHA-256 de (código + parámetros + vocabulario + versión de formato). |
| `cache.py` | Huella de generador **y** `sha256_fichero`. Cinco estados de invalidación. |
| `estadistica.py` | Mediana, MAD, IQR, p05/p95 sobre ≥ 5 repeticiones. `comparar()` dice **"indistinguible del ruido"** si el efecto no supera 3 MAD combinados. |
| `fake_neo4j.py` | Driver doble para contar consultas Cypher sin servidor. **Ahora calibrado (C8) y dentro del hash.** |
| `calibracion.py` | C0–C8. Sale 1 si algún mecanismo no se pudo poner rojo. **Dentro del hash.** |
| `run_bench.py` | Puerta doble: hash del **instrumento** y hash del **sistema medido**. **Dentro del hash.** |

### Por qué "crecimiento" y no "umbral"

El número de llamadas a la fuente es **determinista**: mismo código y mismos
datos dan el mismo número, sin ruido. La pregunta correcta no es "¿la pendiente
supera 0.5?" sino **"¿crece o no crece?"**. Un endpoint sano no crece nada.
La *forma* del crecimiento (lineal o sublineal) se informa, pero no decide.

Y "no concluyente" no es "constante". Es el veredicto de las series que suben y
bajan, donde el eje está confundido con otra variable — el caso real de la ficha
de entidad en el eje del dataset, cuyo coste depende del **grado** del nodo, que
cambia de un grafo generado a otro. Declararla sana sería repetir el error de v1.

---

## 2. Tabla de calibración (salidas reales, 10/10)

`benchmarks/perf/resultados/calibracion.json` ·
instrumento `d6c012ea5ddc` · sistema medido `487ff8e007e5` ·
Python 3.13.5, Xeon E5-2680 v4, 8 vCPU.

| # | Afirmación | Violación introducida | Estado con violación | Tras revertir | ¿Superada? |
|---|---|---|---|---|---|
| **C0** | El **juez** sabe fallar | se le da una afirmación deliberadamente falsa | la marca como **fallida** | la verdadera, superada | **SÍ** |
| **C1** | Eje PÁGINA ve un N+1 por elemento devuelto | 1 `entity()` por elemento de la página | páginas 10/50/100 → **11 / 51 / 101**, crecimiento 90, **N+1** | 1 / 1 / 1, plana, **constante**, idéntico al previo | **SÍ** |
| **C1b** | *(ceguera de v1)* el eje DATASET **no** ve ese N+1 — **medido, no afirmado** | la misma, con `limit=50` fijo | n = 100 / 250 / 500 → **51 / 51 / 51**, pendiente **0.0**, **constante** en el eje dataset frente a **N+1** en el de página | — | **SÍ** |
| **C2** | Eje DATASET ve un N+1 por entidad del grafo *(clientes secuenciales)* | 1 `entity()` por entidad del *workspace* | n = 100 / 250 / 500 → **101 / 251 / 501**, crecimiento 400, **N+1** | 1 / 1 / 1, **constante**, y ningún contador base a 0 | **SÍ** |
| **C3** | Eje GRADO ve un N+1 por relación | *ninguna: el defecto ya está en el código real* | grados 3/33/125/406 → **9 / 69 / 253 / 815**, pendiente 2.0, **N+1** | control sin relaciones: **constante**; al quitar el control, **N+1** idéntico | **SÍ** |
| **C4** | La caché se invalida por generador **y por contenido** | (a) generador roto (`public`); (b) **fichero truncado a 2 nodos con el defecto, sidecar intacto** | (a) `regenerado_por_huella`; (b) **`regenerado_por_contenido`** — v2.0 decía `reutilizado` | fichero restaurado a 20 nodos, sin el defecto | **SÍ** |
| **C5** | Un presupuesto absoluto de llamadas se rompe | 5 consultas extra | techo 1, medido **6.0** → 1 incumplimiento | lista vacía | **SÍ** |
| **C6** | La estadística distingue efecto de ruido | retardo real de **5 ms** | factor efecto/ruido **> 3** → **"peor"** | factor ~0.01 → **"indistinguible del ruido"** | **SÍ** |
| **C7** | Se ven los **N+1 parciales** | 1 consulta cada **2**, **3**, **5** y **√n** elementos | pendientes **0.50 / 0.3333 / 0.20 / 0.0778** → las **cuatro** salen **N+1** (puntos 6/26/51, 5/18/35, 3/11/21, …) | sin defecto: 1/1/1, **constante** | **SÍ** |
| **C8** | El contador de consultas Cypher mide de verdad | driver saboteado para registrar una de cada dos | driver **11** frente a contador independiente **23** → **discrepancia detectada** | 23 = 23; control directo: 3 `run` cuentan **3** | **SÍ** |

### Sabotajes verificados contra la puerta

Además de C0–C8, se comprobó a mano que la puerta reacciona:

| Sabotaje | Resultado real |
|---|---|
| `_ok()` neutralizado (`condicion = True`) | **C0 falla**, `instrumento_calibrado: false`, C1–C8 pasan vacuamente como se esperaba |
| `fake_neo4j.py` modificado para contar la mitad | `run_bench` **se niega**: "La calibración corresponde a otra versión del arnés (d6c012ea5ddc != 9d7f49ae5861)" |
| Una línea añadida a `viewer/app/serializers.py` | `run_bench` **se niega**: "La calibración se hizo sobre otro estado de viewer/app/** (487ff8e007e5 != 795cdbda9b84)" |

---

## 3. Cifras medidas

`benchmarks/perf/resultados/baseline_v2.json`. 30 repeticiones, 5 de
calentamiento. Formato: **mediana ± MAD (ms) / llamadas a la fuente**.

| escenario | n=10 | n=50 | n=100 | n=101 | n=250 | n=500 |
|---|---|---|---|---|---|---|
| api_status | 4.0±0.06 / 4 | 4.6±0.08 / 4 | 5.0±0.08 / 4 | 5.3±0.06 / 4 | 6.0±0.09 / 4 | 7.4±0.08 / 4 |
| api_entity_types | 4.2±0.12 / 1 | 4.6±0.07 / 1 | 4.8±0.07 / 1 | 5.2±0.08 / 1 | 5.5±0.12 / 1 | 6.1±0.11 / 1 |
| api_graph_300 *(satura, §5)* | 6.0±0.08 / 1 | 13.2±0.52 / 1 | 21.7±0.67 / 1 | 22.4±0.53 / 1 | 47.0±0.80 / 1 | 44.5±0.74 / 1 |
| api_graph_300_filtro_tipo | 4.5±0.08 / 1 | 5.4±0.30 / 1 | 6.1±0.12 / 1 | 6.3±0.12 / 1 | 8.2±0.13 / 1 | 10.9±0.12 / 1 |
| api_search | 5.1±0.08 / 1 | 8.2±0.26 / 1 | 8.3±0.09 / 1 | 8.5±0.15 / 1 | 9.4±0.36 / 1 | 9.6±0.09 / 1 |
| api_entities_p50 | 5.4±0.07 / 1 | 8.6±0.22 / 1 | 8.6±0.12 / 1 | 8.9±0.13 / 1 | 9.4±0.20 / 1 | 9.7±0.10 / 1 |
| api_entities_ultima_pag | 5.4±0.08 / 1 | 8.6±0.34 / 1 | 8.6±0.15 / 1 | 9.1±0.24 / 1 | 9.3±0.15 / 1 | 9.8±0.14 / 1 |
| api_entity_detalle | 5.0±0.11 / 11 | 5.9±0.26 / 19 | 5.7±0.12 / 11 | 6.5±0.09 / 21 | 6.5±0.20 / 11 | 6.7±0.07 / 11 |
| api_sources | 4.5±0.10 / 1 | 4.9±0.11 / 1 | 5.2±0.11 / 1 | 5.4±0.09 / 1 | 6.0±0.10 / 1 | 6.6±0.12 / 1 |
| api_quality | 4.7±0.08 / 1 | 5.3±0.15 / 1 | 5.7±0.08 / 1 | 5.9±0.08 / 1 | 7.1±0.09 / 1 | 8.6±0.13 / 1 |
| html_entities | 5.2±0.08 / 2 | 6.0±0.15 / 2 | 6.4±0.14 / 2 | 6.8±0.20 / 2 | 7.3±0.10 / 2 | 8.1±0.23 / 2 |
| html_graph | 3.3±0.07 / 0 | 3.5±0.07 / 0 | 3.8±0.09 / 0 | 4.1±0.07 / 0 | 4.5±0.13 / 0 | 4.6±0.10 / 0 |
| html_entity_detalle | 4.8±0.09 / 11 | 5.3±0.08 / 19 | 5.4±0.08 / 11 | 5.8±0.15 / 21 | 6.1±0.12 / 11 | 6.5±0.08 / 11 |

Dispersión relativa (MAD/mediana) entre el 1 % y el 5 %.

### Veredictos del eje DATASET

Once escenarios salen **constante** (serie plana). Dos —`api_entity_detalle` y
`html_entity_detalle`— salen **"no concluyente"**: su serie es
11 / 19 / 11 / 21 / 11 / 11, sube y baja, porque el coste depende del **grado**
del nodo consultado y no del tamaño del grafo. El eje está confundido; el
detector lo dice en vez de declararlas sanas. Ejes página y grado: ver §4.

### Consultas Cypher absolutas (driver doble **calibrado en C8**, n=250)

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

C8 calibra el **recuento de consultas**. El número de **filas** sigue siendo
plausible y no exacto: el doble no ejecuta Cypher. Esa columna sigue **sin
calibrar** y así se marca.

---

## 4. Hubs: donde revientan las consultas

Mismo grafo (250 entidades), variando el **grado** del nodo pedido en
`/api/entities/{id}`:

| grado del nodo | llamadas a la fuente | mediana ± MAD | bytes |
|---|---|---|---|
| 3 | 9 | 6.45 ± 0.10 ms | 5 364 |
| 33 | 69 | 10.33 ± 0.49 ms | 48 177 |
| 125 | 253 | 19.19 ± 0.19 ms | 179 836 |
| **406** | **815** | **50.14 ± 1.22 ms** | 583 167 |

Pendiente **2.0 llamadas por relación**, constante y **sin tope**: el endpoint
resuelve la entidad del otro extremo de cada arista, entrante y saliente, una a
una. La revisión independiente forzó grado **1505 → 3013 llamadas** y derivó la
fórmula exacta:

> **llamadas = 2 · grado + 3**

que también explica al dígito el escalón de §5 (grado 4 → 11, grado 9 → 21).

En un grafo de lore real, los nodos de grado alto son precisamente los que más
se consultan. **Este es el hallazgo de rendimiento.** No se arregla en esta
rama: el arreglo vive en `viewer/app/routers/readonly.py` y en la cadena de
autorización, zona de otros carriles.

---

## 5. Discontinuidades (10 → 50 → 100 → **101** → 250 → 500)

`101` está a propósito, para buscar un salto justo pasado 100.

* **No hay discontinuidad en 100 → 101.** Ningún escenario da un salto de
  latencia que supere el ruido (mayor factor efecto/ruido: 1.79 < 3).
* El cambio de **11 → 21 llamadas** en la ficha de entidad **no es ruido y no es
  un umbral**: `p_0000050` tiene grado 4 en el grafo de 100 y grado 9 en el de
  101, y 2·4+3 = 11, 2·9+3 = 21. Es el eje GRADO otra vez.
  *(En v2.0 esa fila lucía `delta_llamadas: 10` bajo la etiqueta "indistinguible
  del ruido", que sólo hablaba de milisegundos. Ahora hay dos campos separados:
  `veredicto_latencia` y `veredicto_llamadas`.)*

### `api_graph_300` **satura** a partir de n ≈ 300 — la curva no es continua

| n | nodos devueltos | aristas | bytes | mediana |
|---|---|---|---|---|
| 10 | 10 | 30 | 22 140 | 6.0 ms |
| 50 | 50 | 150 | 110 044 | 13.2 ms |
| 100 | 100 | 300 | 219 835 | 21.7 ms |
| 101 | 101 | 303 | 222 333 | 22.4 ms |
| 250 | 250 | 750 | 550 187 | 47.0 ms |
| **500** | **300 (tope)** | **550** | **523 136** | **44.5 ms** |

El `limit=300` **satura sobre los nodos**: a n=500 la respuesta trae 300 nodos y
sólo 550 aristas (las que caen entre nodos seleccionados), es **más pequeña** que
la de n=250, y la latencia sigue al *payload*. **La serie de este escenario sólo
es interpretable como curva de escala hasta n ≈ 300**; de ahí en adelante ya no
compara la misma carga. El informe JSON marca cada tramo con `saturado: true`
cuando el desglose de la respuesta no cambia entre dos tamaños.

Esto no era un artefacto de medida — era una propiedad del endpoint, y v2.0 la
presentó como una serie continua (6.0 → 13.3 → 21.7 → 47.5 → 45.0). Corregido.

---

## 6. Qué NO se midió (declarado, no omitido)

* **Neo4j real.** No hay servidor accesible. El conteo de consultas está
  calibrado (C8); el conteo de **filas** del doble **no**. Sin plan de
  ejecución, sin índices, sin latencia de red a la base.
* **Producción.** Ni una petición a VM105. Ni ingestas, ni backups, ni despliegue.
* **Concurrencia.** Un solo cliente, secuencial.
* **Red, TLS, nginx, disco de producción.**
* **El camino de autenticación**: se mide con `S9K_AUTH_ENABLED=false`, el caso
  más barato de política. El coste con un lector no-admin y partida activa no se
  midió.
* **Memoria**, **tamaños > 500 entidades** y **el navegador**.
* **Datos reales**: todo es sintético y determinista.

Máquina de desarrollo **compartida**. Por eso todo va con mediana y MAD, y por
eso el informe dice "indistinguible del ruido" cuando lo es.

---

## 7. Supervivientes clasificados

**Defectos reales del visor, confirmados con instrumento calibrado**

1. **N+1 por grado en la ficha de entidad** — `llamadas = 2·grado + 3`, sin
   tope, verificado hasta grado 1505 (3013 llamadas). *Alta en cuanto haya hubs.*
   No se arregla aquí (zona de otros carriles).
2. **`quality_metrics` emite 13 consultas Cypher** por pantalla. Constante, pero
   es el absoluto más alto. *Baja-media.*
3. **`/api/graph?limit=300` satura sobre nodos**: a partir de ~300 entidades la
   respuesta deja de representar el grafo y trae menos aristas de las que hay.
   Es un asunto de **producto**, no sólo de rendimiento. *Media.*

**Defectos del instrumento, corregidos aquí**

4. Detector de un solo eje (v1) → tres ejes.
5. Umbral fijo de 0.5, ciego a N+1 parciales (v2.0) → criterio de crecimiento,
   calibrado contra 1/2, 1/3, 1/5 y √n (C7).
6. Caché sin huella (v1) y con huella sólo del generador (v2.0) → huella de
   generador **y** de contenido (C4).
7. Driver Cypher nunca visto en rojo y fuera del hash (v2.0) → C8 y hash ampliado.
8. Juez neutralizable (v2.0) → C0 y `calibracion.py` dentro del hash.
9. Puerta sin anclaje al sistema medido (v2.0) → `sha_del_sistema_medido`.
10. C2 verde por un cero fantasma (v2.0) → clientes secuenciales y comprobación
    explícita de que ningún contador base vale 0.

**Sin evidencia (no afirmado)**

11. Ninguna discontinuidad al cruzar 100 entidades.
12. Los dos escenarios de ficha de entidad quedan **"no concluyentes"** en el eje
    del dataset: el eje está confundido con el grado. No se declaran sanos.

**Deuda declarada**

13. `benchmarks/**` no está en `testpaths` de `pytest.ini`: la calibración es una
    **puerta manual** (`calibracion.py` sale 1 si falla). Ahora al menos no puede
    pudrirse en silencio: cualquier cambio en `viewer/app/**` o en el propio
    laboratorio hace que `run_bench.py` se niegue a medir hasta recalibrar.
    Meterla en CI toca ficheros compartidos con los carriles L y M.
14. El coste de la política con un lector no-admin sigue sin medirse.

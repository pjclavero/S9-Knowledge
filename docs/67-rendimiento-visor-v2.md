# 67 — Rendimiento y escala del visor (v2): arreglar el instrumento antes de medir

**Repositorio**: S9-Knowledge · **Rama**: `perf/viewer-scale-baseline-v2` ·
**Base medida**: `0979b8a` (main) · **artefactos recalibrados y remedidos en v2.2**

Todo lo que sigue se midió sobre datos **sintéticos**, con el proveedor *mock* en
memoria y el cliente en proceso. Nunca se tocó producción, ni VM105, ni Neo4j,
ni credencial alguna.

> **Dónde se midió.** Todas las cifras de este documento salen de una única
> máquina: Debian 13 (Linux 6.12.90), **Intel Xeon E5-2680 v4, 8 vCPU**, 8,7 GiB
> de RAM, Python 3.13.5, máquina de desarrollo **compartida y con carga ajena**.
> Los milisegundos no son transportables a otra máquina; los **recuentos de
> llamadas y los tamaños de respuesta sí**, porque son deterministas. El bloque
> `entorno` de cada artefacto JSON repite este dato en el propio fichero.

> **Lo que este carril NO mide, pese a su título.** El rendimiento **en el
> navegador** no se mide en absoluto: ver §6.4.

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

### 0.1 Y de la v2.1 salieron otros cuatro, del mismo tipo

La revisión independiente de v2.1 encontró que el patrón seguía vivo en el
propio arnés. Se corrigen aquí, cada uno con su prueba C\*:

| Agujero de v2.1 | Cómo se demostró (medido) | Corrección en v2.2 |
|---|---|---|
| El **detector de saturación estaba ciego en el endpoint que le da nombre**. `saturado = bool(da) and da == db` comparaba los desgloses ENTEROS | En el tramo real 250→500 el desglose pasa de `{nodes:250, edges:750}` a `{nodes:300, edges:550}`: **difieren**, luego `saturado=False`. Barrido de las 65 filas: `api_graph_300` **no salía saturado ni una vez**, mientras `api_sources` —que no satura, crece 4→10→20— salía `saturado=True` **3 veces**, y `api_entity_detalle` una por coincidencia numérica entre dos grafos distintos | `detector.analizar_saturacion`: saturación **por componente y sobre la serie entera**, con dos criterios —**tocar un techo declarado** que además **acote** a ese componente, o **meseta en su propio máximo** tras haber crecido. Las tres cláusulas están **ablacionadas** en C9b. **Cero pruebas cubrían `saturado` en v2.1; ahora son C9a y C9b** |
| El detector firmaba **"constante"** un N+1 **con tope** | Inyectado `min(2·g+3, 40)` sobre nodos de grado 125/132/134: llamadas **83 / 83 / 83**, serie plana, veredicto **"constante", pendiente 0.0** — para un endpoint que hacía **83 consultas por petición** | `dictaminar()` acepta la **carga devuelta**; si la respuesta viene recortada y ha dejado de crecer, el veredicto es **"no concluyente"**, no "constante" (C11) |
| `comprobar_presupuestos` —**el único guardia de magnitud absoluta**— **no se invocaba nunca desde `run_bench.py`**: vivía sólo dentro de la calibración C5 | El informe no tenía ni un campo de presupuesto | Conectado al informe (`presupuestos.por_tamano` y `presupuestos.por_grado`), con **techos medidos**, no inventados |
| El **hash del sistema medido no cubría lo que su nombre promete**: filtraba por `suffix in (".py", ".html")` | Mutar **`viewer/app/static/js/graph.js`** —el motor de pintado del grafo, o sea el objeto de este carril— dejaba el hash **intacto** en `a505a170f4d1` y `run_bench.py` medía tan tranquilo. Quedaban fuera **16 ficheros**: 4 `.js`, 3 `.css`, 9 `.json` | Sin filtro de extensión: **todo** `viewer/app/**` (**119 ficheros** hoy; eran 107 cuando se corrigió). Con la misma mutación el hash se mueve — verificado en cada base (C10) |

### 0.2 v2.3 — el banco medía un grafo invisible, y sólo se notó porque abortó

Sobre `main = 420f626`, con el árbol limpio y **sin cambios de ningún carril**,
`benchmarks/perf/calibracion.py` abortaba en la prueba C3 (eje GRADO):

```
RuntimeError: /api/entities/p_0000002 -> 404; no se mide un endpoint que falla
```

**Causa raíz, medida y no supuesta.** El arnés pone `S9K_AUTH_ENABLED=false`
para medir el camino de datos y no el de login. Hasta el commit **`46af55a`**
(*«p0-auth: admin_full deja de tener tres autoridades y ninguna declarada»*,
13-08-2026) ese flag devolvía `ViewerContext(role="public", admin_full=True)`
y el banco veía el grafo entero **por accidente**: apoyado justamente en la
concesión de autoridad que ese commit cerró. Desde `46af55a` el mismo flag
degrada a `anonymous` —mínimo privilegio, que es **lo correcto y no se toca**—.
El generador reparte `visibility = VISIBILITIES[i % 4]` sobre
`[player, narrator, secret, reference]`, así que un anónimo **sólo ve `player`**.

**Diferencial de árbol** (mismo dataset, mismos ids, `/api/entities/{id}`):

| árbol | `p_0000200` (player) | `p_0000002` (secret) | `p_0000001` (narrator) | `p_0000000` (player) |
|---|---|---|---|---|
| `533e074` (= `46af55a^`) | 200 | **200** | **200** | 200 |
| `420f626` (main de hoy) | 200 | **404** | **404** | 200 |

Los hubs del escenario de C3 son `p_0000000..2`: **dos de los tres hubs eran
invisibles**, y por eso reventaba el eje del grado y no otro.

**Lo grave no era el aborto: el aborto fue el aviso.** El resto del banco seguía
midiendo, y medía un grafo recortado al 25 %: `/api/graph?limit=250` sobre un
grafo de 250 nodos devolvía **63 nodos**. Es el defecto de v1 —nodos invisibles
por vocabulario de visibilidad— reencarnado por la vía del contexto de
autorización. `comprobar_que_hay_datos` no lo veía porque **sí** había nodos:
un cuarto.

**Corrección — sólo en el instrumento, ni una línea de `viewer/app/**`.**
`arnes.contexto_del_banco()` pide la visibilidad completa **por la puerta
declarada** del único productor de contextos (`authz.context.build_viewer_context`,
`role="admin"`), y `construir_cliente` la inyecta con
`dependency_overrides[get_filtered_provider]`. Queda escrito por qué. **No** se
reactiva ningún atajo de autoridad en el producto.

**Prueba de regresión + calibración negativa.**
`viewer/tests/test_banco_perf_visibilidad_regresion.py` (8 casos) exige 200 en
**los cuatro niveles de visibilidad** —no un simple "responde"—, incluye un
guardia anti-cero (los cuatro niveles deben existir en el dataset) y una
calibración negativa que reintroduce el defecto en memoria: **ROJO**
(`PARCIALMENTE INVISIBLE`) → revertir → **VERDE**. Vive en `viewer/tests/`
porque `benchmarks/**` **no está en `testpaths`** y ningún job de CI lo ejecuta
—mismo motivo y mismo sitio que `test_saturacion_grafo_caracterizacion.py`—, y
porque `viewer/tests/` queda **fuera** del hash de `viewer/app/**`: añadirlo no
invalida la calibración.

**Ablación (necesidad del arreglo).** Con `arnes.py` revertido a `origin/main` y
el test nuevo intacto: **5 fallos / 3 pasan**, entre ellos
`p_0000002 → assert 404 == 200` y `63 de 250 nodos`. Restaurado `arnes.py`:
**8/8 verdes**, con la reversión verificada por hash
(`sha256(arnes.py) = 2be31c0b5576…` antes y después, idéntico).

**Los hallazgos deterministas no se movieron ni un dígito** (era la comprobación
de que el arreglo restaura las condiciones de medida de `main = 0979b8a`, no
otras):

| hallazgo publicado | remedido en v2.3 |
|---|---|
| `llamadas = 2·grado + 3` | 4→**11**, 125→**253**, 132→**267**, 134→**271**, 406→**815**, 812→**1 627** |
| presupuestos por grado (techo 9.0) | **69 / 253 / 815** incumplimientos, idénticos |
| saturación de `/api/graph?limit=300` | 250→750 (100 %), 500→**550** (36.7 %), 1000→**275** (9.2 %), 2000→**151 de 6 000** (**2.5 %**) |
| bytes de la ficha de grado 406 | **586 319 B**, al byte |

**Limitación declarada, nueva.** El contexto del banco es `admin_full`, y
`admin_full` es **bypass total** de la política (`policies/engine.py`). O sea:
el banco **no mide el coste de evaluar la política** — exactamente igual que
antes de `46af55a`, cuando el bypass llegaba solo por el flag. Se elige a
propósito para que las cifras sigan siendo comparables; medir el coste de la
política con un lector no-admin sigue pendiente (limitación 14).

---

## 1. El instrumento de v2.2

| Pieza | Qué hace |
|---|---|
| `detector.py` | Tres ejes (dataset, página, **grado**). Criterio de **crecimiento**, sin umbral. Exige **≥ 3 puntos** para afirmar una pendiente; con dos dice "insuficiente". Veredictos: `constante` / `N+1` / `no concluyente` / `insuficiente`. **Detección de saturación por componente** (`analizar_saturacion`) y **presupuestos absolutos** (`comprobar_presupuestos`). |
| `dataset.py` | Generador determinista con **hubs**. Huella = SHA-256 de (código + parámetros + vocabulario + versión de formato). |
| `cache.py` | Huella de generador **y** `sha256_fichero`. Cinco estados de invalidación. **`verificar_a_fondo()` recalcula el sha esperado** sin fiarse del sidecar. |
| `estadistica.py` | Mediana, MAD, IQR, p05/p95 sobre ≥ 5 repeticiones. `comparar()` dice **"indistinguible del ruido"** si el efecto no supera 3 MAD combinados, y **"sin dispersión medible"** si el MAD combinado es 0. |
| `fake_neo4j.py` | Driver doble para contar consultas Cypher sin servidor. **Calibrado (C8) y dentro del hash.** |
| `calibracion.py` | C0–C11 (**15 pruebas**). Sale 1 si algún mecanismo no se pudo poner rojo. **Dentro del hash.** |
| `run_bench.py` | Puerta doble: hash del **instrumento** y hash del **sistema medido** (`viewer/app/**` **entero**). **Dentro del hash.** |

### Por qué el criterio de saturación no es "los dos desgloses son iguales"

Porque medido no funciona: en el único tramo donde `/api/graph?limit=300` satura
de verdad los dos desgloses **no** son iguales —uno de los componentes topa y el
otro **se desploma**— y el criterio de igualdad respondía "no saturado". Y al
revés, una planicie inicial (`{sources: 4}` en los dos extremos, antes de que la
serie empiece a crecer) lo daba por saturado.

La saturación es una propiedad de **cada componente a lo largo de la serie
entera**. Un componente está saturado en un tramo si:

1. **toca un techo declarado** en la URL (`limit=N`) que además **le acota** —el
   componente nunca lo supera en toda la serie: sin esta condición, el
   `limit=300` de los **nodos** se le achacaría a las **aristas**, que llegan a
   750, y aparecería saturación donde no la hay; o
2. **mesetea en su propio máximo** habiendo crecido antes y sin bajar nunca —lo
   que distingue un techo implícito (`/api/search` corta en 50 sin decirlo) de
   un componente que simplemente aún no ha empezado a moverse.

Un componente que **decrece** no basta por sí solo para declarar saturación —dos
grafos distintos dan grados distintos, y eso es confusión, no techo— pero si la
fila ya está saturada por otro componente, se registra como **colapso**. Es el
caso de las aristas de `/api/graph?limit=300`: ver §5.

Las tres cláusulas están ablacionadas una a una en **C9b**, sobre el mismo código
que corre en producción del laboratorio, no sobre una copia.

#### Precondición del criterio (declarada, y comprobada — no supuesta)

El criterio **no ve una saturación que empiece antes de la ventana de medida**.
La cláusula "creció antes" exige haber visto subir al componente para creerse su
meseta; si todos los tamaños medidos están ya por encima de un tope
**implícito** (el que no aparece como `limit=` en la URL), no hay crecimiento
que ver:

| serie medida | ¿se marca? | por qué |
|---|---|---|
| `[10, 50, 50, 50]` | **sí** | se la vio subir y luego topar |
| `[50, 50, 50, 50]` | **no** | jamás se la vio crecer, y no hay techo declarado |

> **El criterio es correcto sólo si el tamaño más pequeño medido está por debajo
> de todos los topes implícitos de los escenarios.**

**Hoy se cumple**: `TAMANOS` empieza en **10** y el tope implícito más bajo
observado es el de `/api/search`, en **50**. Por eso el defecto no muerde. Pero
es una precondición, no un teorema, y la causa **justo la cláusula que elimina
el falso positivo de `api_sources`**: es un intercambio consciente —se prefiere
no inventarse techos, a costa de no ver los que empiezan antes de la ventana.

Dos cosas evitan que esto se pudra en silencio:

* el caso ciego **no se da por sano**: los componentes planos en toda la ventana
  y sin techo declarado salen en **`componentes_no_evaluables`**, con el motivo
  escrito. No se declaran saturados —eso sería inventarse un techo que no
  consta— pero tampoco limpios. *(En este baseline: **0 componentes**; ninguno
  es plano en los seis tamaños.)*
* **C9c** comprueba la precondición **contra la ventana real** de
  `run_bench.TAMANOS`. Verificado poniéndola roja: si se deja de marcar el caso
  ciego, C9c falla; si se sube la ventana a `[100, 250, 500]` —por encima del
  tope de 50— C9c falla también. Revertido, verde.

### Por qué "plano" no es lo mismo que "sano"

Un endpoint con tope produce una serie de llamadas **plana** en cuanto los puntos
superan el tope. El criterio de crecimiento, solo, firma eso como
**"constante", pendiente 0.0** — y así se declara sano un endpoint que hace
decenas o cientos de consultas por petición. Hacen falta **dos** guardias:

* el de **crecimiento**, que ahora recibe también la **carga devuelta** y
  responde "no concluyente" cuando la respuesta viene recortada y ha dejado de
  crecer (C11);
* el de **magnitud absoluta** (`comprobar_presupuestos`), que en v2.1 existía
  pero **no se invocaba desde `run_bench.py`**. Ahora se invoca, con techos
  **medidos**: el coste con el dataset más pequeño para los escenarios cuyo
  coste no debe depender del tamaño, y el coste del hub de menor grado para la
  ficha de entidad.

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

## 2. Tabla de calibración (salidas reales, **15/15**)

`benchmarks/perf/resultados/calibracion.json` ·
instrumento `f85994e78842` · sistema medido `f118e4b71afc` ·
**máquina declarada**: Python 3.13.5, Intel Xeon E5-2680 v4 @ 2.40 GHz, 8 vCPU,
9 156 844 kB de RAM, Linux 6.12.90+deb13.1-amd64, **compartida** (`loadavg`
registrado en cada artefacto). La máquina acota los **milisegundos**, no los
**conteos**: los conteos son deterministas y se reproducen al dígito en
cualquier máquina.

*(los hashes de v2.2 eran `2d3255e6ddf1` / `23a5b1cafd33`, sobre
`main = 0979b8a`)*

> **Los artefactos de este documento se regeneraron por completo, dos veces, y
> las dos por el mismo motivo.** La puerta no es un formalismo: rehusó medir en
> las dos ocasiones y en las dos tenía razón.
>
> 1. Al rebasar sobre `e2e8214`, `main` aportó **3 ficheros de `viewer/app/**`**
>    y `run_bench.py` se negó (`487ff8e0 != a505a170`). Los hashes de v2.1
>    (`d6c012ea5ddc` / `487ff8e007e5`) dejaron de valer, y no se conservaron
>    como si valieran.
> 2. Al rebasar sobre `695035f`, `main` aportó **5 ficheros de `viewer/app/**`**
>    —`labels.py`, `review_status_contract.py`, `routers/readonly.py`,
>    `templates/quality.html`, `templates/source_detail.html`— y `run_bench.py`
>    **se negó otra vez** (`9ee38c2c2984 != d0fe380d5d98`).
>
> Y la segunda vez quedó demostrado que no era burocracia: esos cambios
> **movieron de verdad lo medido**. El detalle de una entidad de grado 406 pasó
> de **583 167 a 586 319 bytes**. Con una calibración vieja, esas cifras habrían
> quedado avaladas por un instrumento que decía corresponder a otro sistema.
>
> `calibracion.json` y `baseline_v2.json` están **recalibrados y remedidos**
> sobre `main = 0979b8a`: **15/15**, instrumento `2d3255e6ddf1`, sistema
> `23a5b1cafd33`, con el árbol limpio.
>
> 3. Al rebasar sobre `0979b8a` —que trae el **chasis**— `main` aportó **13
>    ficheros de `viewer/app/**`** (`chassis.py`, 5 `routers/chassis_*.py`, 5
>    plantillas nuevas, y sendas modificaciones de `main.py` y
>    `templates/base.html`), y `run_bench.py` **se negó por tercera vez**
>    (`d0fe380d5d98 != 23a5b1cafd33`). El sistema medido pasó de **107 a 119
>    ficheros**.
>
> Y por tercera vez la puerta tenía razón, esta vez de forma exactamente
> atribuible: **las 18 filas HTML crecieron 147 bytes clavados**, en los seis
> tamaños, mientras los endpoints JSON no se movieron ni un byte. La firma
> —constante e idéntica en todas las filas HTML, indiferente al tamaño del
> grafo— señala a `templates/base.html`, que el chasis reescribió para generar
> la navegación desde el registro en vez de a mano, añadiendo un atributo
> `data-nav` por enlace. **Ningún conteo determinista cambió**: ni una llamada
> a la fuente, ni un desglose de respuesta, ni un byte en los hubs.
>
> 4. Y una **cuarta** vez, sobre `main = 420f626`: `run_bench.py` volvió a
>    rehusar (`sha_del_sistema_medido` caduco) porque `main` había vuelto a
>    tocar `viewer/app/**`. Se comprobó que **dejar el artefacto caduco es lo
>    correcto**: borrarlo también hace rehusar, pero con peor mensaje. Y esta
>    vez la puerta escondía además el defecto de §0.2, que sólo salió a la luz
>    al recalibrar. **Cuatro de cuatro: siempre tenía razón.**
>
> *(Al rebasar de `695035f` a `dda9822` la puerta **no** rehusó, y con razón:
> `main` no tocó ni un fichero de `viewer/app/**`, así que
> `sha_del_sistema_medido` salió idéntico. Se remidió de todas formas para que
> `entorno.commit` apunte a un commit vivo de la rama y no a uno que el rebase
> dejó huérfano: la procedencia de un artefacto tiene que poder seguirse.)*
>
> **Los dos hallazgos se reprodujeron idénticos** sobre la base nueva:
> `2·grado+3` exacto en los 5 puntos (812 → 1 627) y la saturación de
> `/api/graph?limit=300` con las mismas cifras (n=2000 → 151 de 6 000, 2,5 %).
> Son deterministas: no dependen ni de la máquina ni de la tanda.

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
| **C9a** | El detector de saturación **ve** la saturación real y **deja de inventarse** la falsa | *ninguna: se contrastan los dos criterios sobre datos medidos a n = 10/100/250/500* | criterio de v2.1 sobre `api_graph_300`: **`[false, false, false]`** — ciego en el tramo real (`{nodes:250, edges:750}` → `{nodes:300, edges:550}`); y `api_sources` **`[true, false, false]`**, falso positivo | criterio de v2.2: `api_graph_300` **`[false, false, true]`**, con el **colapso de aristas 750 → 550** registrado, y `api_sources` **`[false, false, false]`** | **SÍ** |
| **C9b** | Las **tres** cláusulas del criterio son necesarias | se ablaciona cada una **sobre el mismo código** | sin *acotado*: `[true, true, true]` (el `limit=300` de los nodos se achaca a las aristas, que llegan a 750). Sin *creció antes*: una serie constante `[4,4,4]` pasa a saturada. Sin *en su máximo*: la meseta `[2,13,13,63]` pasa a saturada | con las tres: `false` en los tres casos | **SÍ** |
| **C9c** | La **precondición** del criterio: la ventana de medida empieza por debajo de todos los topes implícitos | *ninguna: se contrasta la misma serie en dos ventanas, y la precondición contra `run_bench.TAMANOS`* | ventana `[50,50,50,50]` (empieza **encima** del tope): **no se marca** — el superviviente. Puesta roja de dos formas: si se deja de marcar el caso ciego, falla; si la ventana sube a `[100,250,500]`, falla | ventana `[10,50,50,50]`: **se marca**; el caso ciego sale como `componentes_no_evaluables`; mínimo real **10** < tope implícito más bajo **50** | **SÍ** |
| **C10** | El hash del sistema medido cubre **todo** `viewer/app/**` (**119 ficheros**) | se muta **`static/js/graph.js`** en disco | el hash pasa de `23a5b1cafd33` a `e2e1489ef2cb`. *(Con el filtro de v2.1 la misma mutación lo dejaba clavado: **no se movía**. Medido en esta misma base: `832f9a30f644` → `832f9a30f644`.)* | fichero restaurado byte a byte, hash de vuelta en `23a5b1cafd33` | **SÍ** |
| **C11** | Una serie plana **por saturación** no se firma como "constante" | `min(2·g+3, 40)` sobre grados 125/132/134 | llamadas **83 / 83 / 83** (plana). Sin señal de carga: **"constante", pendiente 0.0**. Con señal de carga: **"no concluyente"**. Presupuesto absoluto: **83.0 > 10.0**, incumplido | quitado el tope: **N+1**, pendiente 2.0 | **SÍ** |

### Sabotajes verificados contra la puerta

Además de C0–C8, se comprobó a mano que la puerta reacciona:

| Sabotaje | Resultado real |
|---|---|
| `_ok()` neutralizado (`condicion = True`) | **C0 falla**, `instrumento_calibrado: false`, C1–C8 pasan vacuamente como se esperaba |
| `fake_neo4j.py` modificado para contar la mitad | `run_bench` **se niega**: "La calibración corresponde a otra versión del arnés (d6c012ea5ddc != 9d7f49ae5861)" |
| Una línea añadida a `viewer/app/serializers.py` | `run_bench` **se niega**: "La calibración se hizo sobre otro estado de viewer/app/** (487ff8e007e5 != 795cdbda9b84)" |
| **Rebase real sobre `main`** (3 ficheros de `viewer/app/**` llegados de `main`) | `run_bench` **se negó**: "La calibración se hizo sobre otro estado de viewer/app/** (`487ff8e0` != `a505a170`)". No es un sabotaje de laboratorio: es la puerta funcionando en el caso que la justifica |
| **`viewer/app/static/js/graph.js` mutado** | v2.1 (filtro `.py`/`.html`): hash **`832f9a30f644` → `832f9a30f644`**, no se movía, `run_bench` medía. v2.2: **`23a5b1cafd33` → `e2e1489ef2cb`**, `run_bench` se niega. *(Comprobado de nuevo sobre cada base rebasada.)* |

---

## 3. Cifras medidas

`benchmarks/perf/resultados/baseline_v2.json`. 30 repeticiones, 5 de
calentamiento. Formato: **mediana ± MAD (ms) / llamadas a la fuente**.

| escenario | n=10 | n=50 | n=100 | n=101 | n=250 | n=500 |
|---|---|---|---|---|---|---|
| api_status | 4.1±0.11 / 4 | 4.5±0.07 / 4 | 4.9±0.06 / 4 | 5.4±0.10 / 4 | 6.2±0.12 / 4 | 7.4±0.13 / 4 |
| api_entity_types | 4.2±0.07 / 1 | 4.6±0.06 / 1 | 4.8±0.09 / 1 | 5.1±0.14 / 1 | 5.6±0.11 / 1 | 6.1±0.11 / 1 |
| api_graph_300 *(satura, §5)* | 6.1±0.11 / 1 | 13.2±0.16 / 1 | 22.8±0.48 / 1 | 23.2±0.25 / 1 | 50.7±0.66 / 1 | 47.4±1.01 / 1 |
| api_graph_300_filtro_tipo | 4.5±0.09 / 1 | 5.3±0.08 / 1 | 6.1±0.11 / 1 | 6.4±0.13 / 1 | 8.4±0.21 / 1 | 14.0±1.03 / 1 |
| api_search *(satura en 50)* | 5.0±0.08 / 1 | 8.0±0.11 / 1 | 8.5±0.12 / 1 | 8.8±0.14 / 1 | 9.2±0.10 / 1 | 9.9±0.16 / 1 |
| api_entities_p50 | 5.5±0.08 / 1 | 8.5±0.12 / 1 | 8.9±0.12 / 1 | 9.2±0.14 / 1 | 9.5±0.14 / 1 | 10.0±0.12 / 1 |
| api_entities_ultima_pag | 5.5±0.09 / 1 | 8.6±0.21 / 1 | 8.9±0.18 / 1 | 9.2±0.20 / 1 | 9.7±0.13 / 1 | 10.0±0.14 / 1 |
| api_entity_detalle | 5.1±0.10 / 11 | 5.8±0.10 / 19 | 5.8±0.05 / 11 | 6.7±0.08 / 21 | 6.4±0.12 / 11 | 6.9±0.12 / 11 |
| api_sources | 4.5±0.09 / 1 | 4.9±0.07 / 1 | 5.3±0.12 / 1 | 5.6±0.13 / 1 | 6.0±0.09 / 1 | 6.6±0.08 / 1 |
| api_quality | 4.6±0.07 / 1 | 5.1±0.10 / 1 | 5.8±0.13 / 1 | 6.1±0.13 / 1 | 7.1±0.15 / 1 | 8.8±0.09 / 1 |
| html_entities | 5.3±0.09 / 2 | 6.4±0.18 / 2 | 6.9±0.14 / 2 | 7.1±0.15 / 2 | 7.7±0.20 / 2 | 8.5±0.28 / 2 |
| html_graph | 3.5±0.11 / 0 | 3.8±0.11 / 0 | 3.9±0.09 / 0 | 4.4±0.11 / 0 | 4.7±0.08 / 0 | 5.0±0.16 / 0 |
| html_entity_detalle | 5.0±0.12 / 11 | 5.4±0.08 / 19 | 5.7±0.12 / 11 | 6.2±0.13 / 21 | 6.4±0.13 / 11 | 6.9±0.15 / 11 |

Dispersión relativa (MAD/mediana) entre el 1 % y el 5 %.

### Presupuestos absolutos (el guardia que en v2.1 no se invocaba)

Dos techos, los dos **medidos**, no elegidos a ojo:

| presupuesto | techo | incumplimientos |
|---|---|---|
| **por tamaño** — el coste de estos escenarios no debe depender del tamaño del grafo; techo = llamadas medidas con **n = 10** | 1–4 llamadas según escenario | **ninguno** |
| **por grado** — una ficha no debería costar más por tener el nodo más relaciones; techo = llamadas del hub de **menor grado (3) = 9** | 9.0 | **3**: grado 33 → **69.0**, grado 125 → **253.0**, grado 406 → **815.0** |

Quedan **fuera del presupuesto por tamaño, y se declara por qué**: `api_sources`
(crece con el número de fuentes del corpus, no con el grafo) y los dos escenarios
de ficha de entidad (su coste depende del **grado**, no del tamaño). El informe
**registra** los incumplimientos; no aborta la medición, porque el N+1 por grado
es un hallazgo conocido y declarado, no una sorpresa que deba tumbar la tabla.

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

| grado del nodo | llamadas a la fuente | **2·grado+3** | ¿coincide? | mediana ± MAD | bytes |
|---|---|---|---|---|---|
| 3 | 9 | 9 | **sí** | 6.71 ± 0.10 ms | 5 396 |
| 33 | 69 | 69 | **sí** | 10.03 ± 0.13 ms | 48 481 |
| 125 | 253 | 253 | **sí** | 20.52 ± 0.38 ms | 180 924 |
| **406** | **815** | 815 | **sí** | **51.88 ± 1.21 ms** | 586 319 |
| **812** | **1 627** | 1 627 | **sí** | *(medida aparte)* | — |

Pendiente **2.0 llamadas por relación**, constante y **sin tope**: el endpoint
resuelve la entidad del otro extremo de cada arista, entrante y saliente, una a
una. La fórmula es exacta en los **cinco** puntos medidos:

> **llamadas = 2 · grado + 3**

y también explica al dígito el escalón de §5 (grado 4 → 11, grado 9 → 21). El
punto de grado **812 → 1 627 llamadas** se midió expresamente para comprobar que
**no aparece ningún tope** al subir: no lo hay.

En un grafo de lore real, los nodos de grado alto son precisamente los que más
se consultan. **Este es el hallazgo de rendimiento.** No se arregla en esta
rama: el arreglo vive en `viewer/app/routers/readonly.py` y en la cadena de
autorización, zona de otros carriles. Queda para **decisión del operador**.

### Nota de método: el eje del grado pierde puntos por empate

`eje_grado` indexa las medidas **por grado**, así que dos nodos con el mismo
grado se pisan. Medido en este baseline: de los **4 ids** pedidos en cada uno de
los 4 grafos de hub salen **3 puntos**, uno perdido por empate en los cuatro
casos. Como el detector exige **3 puntos** como mínimo, un empate más habría
degradado el veredicto a "insuficiente" sin que nadie se enterara. Ahora los
puntos perdidos se **deduplican explícitamente y se declaran** en el informe
(`puntos_perdidos_por_empate_de_grado`), en vez de desaparecer en silencio.

---

## 5. Discontinuidades (10 → 50 → 100 → **101** → 250 → 500)

`101` está a propósito, para buscar un salto justo pasado 100.

* **El hecho determinista: nadie cambia de trabajo al cruzar 100, salvo la ficha
  de entidad.** De los 13 escenarios, **11 no cambian ni una llamada**
  (`delta_llamadas: 0`). Los dos que sí —`api_entity_detalle` y
  `html_entity_detalle`— pasan de **11 a 21 llamadas**, y **no es un umbral**:
  es el eje GRADO. `p_0000050` tiene grado 4 en el grafo de 100 y grado 9 en el
  de 101, y 2·4+3 = 11, 2·9+3 = 21. Esto es reproducible tanda tras tanda.
  *(En v2.0 esa fila lucía `delta_llamadas: 10` bajo la etiqueta "indistinguible
  del ruido", que sólo hablaba de milisegundos. Ahora hay dos campos separados:
  `veredicto_latencia` y `veredicto_llamadas`.)*

* **Los veredictos de LATENCIA de este tramo NO son reproducibles, y hay que
  decirlo.** El mismo código, los mismos datos y las mismas 30 repeticiones
  dieron cuatro respuestas distintas en cuatro tandas de esta misma máquina
  (factor efecto/ruido; el corte para declarar algo es **3**):

  | escenario | ¿cambia de trabajo? | tanda 1 | tanda 2 | tanda 3 | tanda 4 |
  |---|---|---|---|---|---|
  | `api_entity_detalle` | sí (+10 llamadas) | 2.04 *ruido* | 3.52 **peor** | 4.87 **peor** | 6.85 **peor** |
  | `html_entity_detalle` | sí (+10 llamadas) | 1.58 *ruido* | 2.65 *ruido* | 1.25 *ruido* | 1.99 *ruido* |
  | `api_sources` | **no** (0 llamadas) | 1.47 *ruido* | 1.34 *ruido* | **3.01 peor** | 0.97 *ruido* |
  | `api_quality` | **no** (0 llamadas) | 1.17 *ruido* | 1.76 *ruido* | **3.01 peor** | 1.21 *ruido* |
  | `api_status` | **no** (0 llamadas) | 1.89 *ruido* | 1.19 *ruido* | 1.18 *ruido* | **3.00 peor** |

  Léase con cuidado, porque es concluyente: **tres escenarios distintos que no
  hacen ni una consulta de más se han turnado para cruzar la línea**, y ninguno
  repite. `api_sources` y `api_quality` salieron "peor" a 3.01 en la tanda 3 y
  volvieron al ruido en la 4; `api_status` no se había movido en tres tandas y en
  la cuarta marca **3.00**, clavado en el corte. Mientras tanto, dos escenarios
  que hacen **exactamente las mismas 10 consultas de más** salen uno a **6.85** y
  el otro a **1.99**.

  La conclusión honesta no es "hay una regresión en 100 → 101": es que **el corte
  de 3 MAD sobre efectos de décimas de milisegundo, en una máquina de desarrollo
  compartida, produce veredictos inestables**. Cerca del umbral, la etiqueta la
  decide el jitter, no el sistema. Que la fila de `api_entity_detalle` crezca
  tanda tras tanda (2.04 → 3.52 → 4.87 → 6.85) tampoco es una regresión del
  visor: es carga ajena de la máquina, y se nota más justo en el escenario que
  más trabajo hace.

* **Qué se sostiene, entonces.** Que **no hay evidencia de ningún umbral en 100**:
  ningún escenario cambia de trabajo por cruzar la centena. Lo que sí cambia
  —11 → 21 llamadas— tiene causa medida y nombre propio, el grado del nodo. Los
  milisegundos de este tramo **no soportan ninguna afirmación**, ni a favor ni en
  contra, y así quedan declarados (ver §6 y la deuda 19).

### `api_graph_300` **satura** a partir de n ≈ 300 — la curva no es continua

| n | nodos devueltos | aristas | bytes | mediana |
|---|---|---|---|---|
| 10 | 10 | 30 | 22 140 | 6.1 ms |
| 50 | 50 | 150 | 110 044 | 13.2 ms |
| 100 | 100 | 300 | 219 835 | 22.8 ms |
| 101 | 101 | 303 | 222 333 | 23.2 ms |
| 250 | 250 | 750 | 550 187 | 50.7 ms |
| **500** | **300 (tope)** | **550** | **523 136** | **47.4 ms** |

El `limit=300` **satura sobre los nodos**: a n=500 la respuesta trae 300 nodos y
sólo 550 aristas (las que caen entre nodos seleccionados), es **más pequeña** que
la de n=250, y la latencia sigue al *payload*. **La serie de este escenario sólo
es interpretable como curva de escala hasta n ≈ 300**; de ahí en adelante ya no
compara la misma carga.

El informe JSON marca ese tramo con `saturado: true` y nombra el componente
culpable en `componentes_saturados` (`nodes`, *toca el techo declarado
limit=300*) y el que se desploma en `componentes_que_decrecen` (`edges`,
750 → 550). **En v2.1 esa frase era falsa como afirmación**: el criterio era
"el desglose no cambia entre dos tamaños" y, como aquí el desglose **sí** cambia
(uno topa, el otro cae), este escenario **no salía marcado ni una sola vez**.
Ver §0.1.

Esto no era un artefacto de medida — era una propiedad del endpoint, y v2.0 la
presentó como una serie continua (6.0 → 13.3 → 21.7 → 47.5 → 45.0). Corregido.

### Y es **peor** de lo que decía la v2.1: el visor no enseña un grafo recortado, enseña polvo

`limit=300` no recorta el grafo a un subgrafo de 300 nodos con sus aristas: se
queda con 300 nodos y **sólo sobreviven las aristas cuyos dos extremos están
entre esos 300**. Como el muestreo no es local, la probabilidad de que ambos
extremos caigan dentro **se desploma** al crecer el grafo. Medido, en esta misma
máquina, hasta n = 2000:

| n | aristas que **existen** | nodos devueltos | aristas devueltas | aristas por nodo | **% de aristas** |
|---|---|---|---|---|---|
| 250 | 750 | 250 | 750 | 3.00 | **100.0 %** |
| 500 | 1 500 | 300 *(tope)* | 550 | 1.83 | **36.7 %** |
| 1 000 | 3 000 | 300 *(tope)* | 275 | 0.92 | **9.2 %** |
| 2 000 | 6 000 | 300 *(tope)* | **151** | **0.50** | **2.5 %** |

La densidad cae de **3,0 a 0,5 aristas por nodo**. Con 2 000 entidades, la
pantalla del grafo recibe 300 nodos y **151 de las 6 000 aristas**: la mitad de
los nodos no tiene ni una sola conexión visible.

> **El visor no muestra un grafo recortado: muestra polvo desconectado.**

Esto es un asunto de **producto**, no de milisegundos, y no se arregla en esta
rama. Queda para **decisión del operador**. El arreglo natural —muestreo por
vecindad, o `limit` sobre aristas y no sobre nodos— vive en el proveedor y en
`viewer/app/routers/`, fuera del alcance de este carril.

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
* **Memoria** y **tamaños > 500 entidades** en la tabla principal (§5 sí llega a
  2 000, pero sólo para el desglose de `/api/graph`, no para latencias).
* **Datos reales**: todo es sintético y determinista.

Máquina de desarrollo **compartida**. Por eso todo va con mediana y MAD, y por
eso el informe dice "indistinguible del ruido" cuando lo es. Y cuando el MAD
combinado es **0**, ya no dice "peor" ni "mejor": dice **"sin dispersión
medible"** y no afirma nada. *(Es una corrección **latente**: en este baseline el
MAD combinado mínimo es **0.1268 ms** y hay **0 filas** con ruido 0. Se cierra
antes de que deje de serlo, porque con umbral 0 la regla se invertía y una
diferencia de 0,0005 ms se declaraba "peor" con `factor = inf`.)*

### 6.4 El rendimiento **en el navegador** no se mide. En absoluto.

Hay que decirlo con todas las letras porque el carril se llama *rendimiento del
visor* y podría entenderse lo contrario:

* **Todo lo medido aquí es servidor.** Mediana, MAD, llamadas a la fuente,
  consultas Cypher, bytes de respuesta: todo se toma con un cliente **en
  proceso**, antes de que exista un navegador.
* **Los 4 ficheros `.js` de `viewer/app/static/js/` nunca se ejecutan** durante
  la medición — incluido **`vendor/vis-network.min.js`**, que es quien realmente
  paga el coste de pintar el grafo, y **`graph.js`**, que lo orquesta.
* No hay, por tanto, ni una cifra sobre: tiempo de *layout* de la red, FPS al
  arrastrar, memoria del navegador, coste de *parsear* los 550 KB de JSON,
  tiempo hasta el primer pintado, ni el comportamiento con 300 nodos y 151
  aristas del caso de §5.
* Lo único que este carril hace con esos ficheros, desde v2.2, es **vigilar que
  no cambien sin invalidar la calibración** (C10). Vigilar no es medir.

**Medir el navegador exige otro instrumento** (navegador sin cabeza,
*trazas* de rendimiento, presupuestos de *frame*) y es un carril distinto. Aquí
queda **declarado como no medido**, que es lo que corresponde.

---

## 7. Supervivientes clasificados

**Defectos reales del visor, confirmados con instrumento calibrado**

1. **N+1 por grado en la ficha de entidad** — `llamadas = 2·grado + 3`, exacto en
   los **5 puntos medidos** y **sin tope**: grado **812 → 1 627 llamadas**.
   *Alta en cuanto haya hubs.* Rompe además el presupuesto absoluto por grado
   (9 → 69 → 253 → 815). No se arregla aquí (zona de otros carriles).
   **→ decisión del operador.**
2. **`quality_metrics` emite 13 consultas Cypher** por pantalla. Constante, pero
   es el absoluto más alto. *Baja-media.*
3. **`/api/graph?limit=300` satura sobre nodos, y es peor de lo declarado en
   v2.1**: no devuelve un grafo recortado sino **polvo desconectado**. Medido:
   n=500 → 550 de 1 500 aristas (36,7 %); n=1000 → 275 de 3 000 (9,2 %);
   n=2000 → **151 de 6 000 (2,5 %)**, con la densidad cayendo de **3,0 a 0,5
   aristas por nodo**. Asunto de **producto**, no sólo de rendimiento. *Media.*
   **→ decisión del operador.**

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
11. **Detector de saturación ciego en el endpoint que le da nombre** (v2.1) →
    criterio por componente sobre la serie entera, con las 3 cláusulas
    ablacionadas (C9a, C9b). *Cero pruebas lo cubrían antes.*
12. **"Constante, pendiente 0.0" para un N+1 con tope** (v2.1) → señal de carga
    en `dictaminar()` (C11).
13. **`comprobar_presupuestos` nunca invocado desde `run_bench.py`** (v2.1) →
    conectado al informe con techos medidos.
14. **El hash del sistema medido no cubría `.js`/`.css`/`.json`** (v2.1) —
    16 ficheros invisibles, entre ellos `graph.js` → hash sobre **todos** los
    ficheros de `viewer/app/**` (**119** hoy; 107 cuando se corrigió) (C10).
15. **`comparar()` se invertía con MAD = 0** (v2.1) → veredicto "sin dispersión
    medible". *Latente: 0 filas afectadas en este baseline.*
15b. **El banco medía un grafo invisible al 75 %** (v2.2, §0.2): al cerrarse en
    `46af55a` el atajo `S9K_AUTH_ENABLED=false → admin_full`, el arnés pasó a
    medir como anónimo y sólo veía `visibility=player`. Se manifestó como un
    404 que abortaba C3; el resto del banco no abortaba, medía mal.
    → `arnes.contexto_del_banco()` pide la visibilidad por la puerta declarada,
    con prueba de regresión y calibración negativa en
    `viewer/tests/test_banco_perf_visibilidad_regresion.py` (8 casos).
16. **`_nombre()` de la caché omitía el `workspace`** (v2.1): dos parámetros
    distintos, un mismo `grafo_20.json`. La huella lo detectaba y regeneraba
    —las cifras eran correctas— pero **la caché no cacheaba**. Medido tras el
    arreglo: los 19 usos del laboratorio → **11 juegos de parámetros distintos →
    11 nombres distintos, 0 colisiones**.
17. **El eje del grado perdía puntos por empate** (v2.1): 4 ids → 3 puntos, en
    los 4 grafos de hub. Ahora se deduplica y se declara (§4).

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
14. El coste de la política con un lector no-admin sigue sin medirse. **Y ahora
    está declarado por qué**: `arnes.contexto_del_banco()` es `admin_full`, que
    es bypass total en `policies/engine.py`. Es la misma condición de medida que
    antes de `46af55a` —por eso las cifras siguen siendo comparables al dígito—
    pero significa que el banco mide el visor **sin** el coste de evaluar la
    política. Medirlo pide un segundo perfil de contexto y su propia
    calibración; no se hace aquí (§0.2).
14b. La **prueba de regresión** de §0.2 sí está en CI (vive en `viewer/tests/`),
    pero el resto del banco sigue siendo puerta manual: ver deuda 13.
15. **El rendimiento en el navegador no se mide** (§6.4). Es la limitación más
    grande de este carril y no se cierra aquí: exige otro instrumento.
16. **La huella de la caché sólo detecta manipulación incoherente.** Si alguien
    trunca `grafo_N.json` **y recalcula el sidecar**, `obtener()` responde
    `reutilizado` y el defecto revive. Como el generador es **determinista**, el
    sha correcto es **calculable** y no hace falta creerse el apuntado:
    `cache.verificar_a_fondo()` lo hace y **C4c demuestra que caza el ataque
    coherente** (`el_sidecar_miente: true`). No se hace en cada `obtener()` con
    razón declarada: recalcularlo exige **regenerar el dataset entero**, que es
    justo lo que la caché evita.
17. **El número de FILAS del driver doble sigue sin calibrar** (sólo el recuento
    de consultas lo está, C8).
18. **El criterio de saturación no ve un tope que empiece antes de la ventana de
    medida.** Precondición declarada y **comprobada en C9c**: el tamaño mínimo
    medido (10) debe estar por debajo de todos los topes implícitos (el más bajo
    observado, 50). Se cumple hoy; si alguien sube la ventana, la calibración se
    pone roja. El caso ciego sale marcado como `componentes_no_evaluables`, no
    como sano.
19. **Los veredictos de LATENCIA del tramo 100 → 101 no son reproducibles.**
    Tres tandas del mismo código en la misma máquina dieron tres respuestas
    (ver §5): dos escenarios con **0 llamadas de diferencia** llegaron a salir
    "peor" a **3.01**, rozando el corte de 3. El corte de 3 MAD sobre efectos
    de décimas de milisegundo en una máquina compartida **no discrimina**. Lo
    que sostiene los hallazgos de este documento son los **conteos
    deterministas**, no los milisegundos. Arreglarlo pide más repeticiones,
    máquina dedicada, o subir `k` — y calibrar el cambio, no elegirlo a ojo.

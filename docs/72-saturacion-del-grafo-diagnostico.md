# 72 — Saturación del grafo en `/api/graph`: diagnóstico por capas

**Repo**: `pjclavero/S9-Knowledge` · **Rama**: `fix/graph-saturation-diagnostico` ·
**Árbol medido**: `e0305cc` (= `origin/main`), `git status --porcelain` limpio antes de medir.
**Carril**: GRAPH-SATURATION. Entrega: **diagnóstico + opciones**. No se implementa el cambio de
selección (ver §6). No se toca `viewer/app/**`, ni `benchmarks/perf/**`, ni `.github/workflows/ci.yml`.

---

## 1. Resumen

En el camino de producción (el único que atraviesa `/api/graph`), el desplome de aristas **no está
en la consulta Cypher, ni en el provider, ni en la autorización, ni en la serialización, ni en el
cliente**. Está en un único punto:

(La consulta Cypher *sí* tiene un defecto propio —acota las relaciones en vez de los nodos— pero
está **inerte** en el camino autorizado y no contribuye a esta pérdida; se demuestra por ablación
en §4.)

> **Causa raíz: `/api/graph` devuelve el SUBGRAFO INDUCIDO sobre los primeros `limit` nodos
> en orden de almacenamiento.** Los nodos se recortan primero y las aristas se recogen sólo
> entre los supervivientes, así que la retención de relaciones cae con el **cuadrado** de la
> fracción de nodos mostrada: `p ≈ (limit / N)²`.

A 2.000 entidades con `limit=300` la fracción de nodos es 300/2000 = 15 %, y la de relaciones
15 %² = 2,25 %. **Medido: 171 de 6.000 = 2,85 %.**

**Pero ese 2,85 % es el PEOR CASO, no una predicción de producción.** La severidad depende de la
**alineación** entre el orden de almacenamiento y la topología: con la misma densidad real, si las
entidades del mismo documento se almacenan consecutivas y están densamente interconectadas —el
caso plausible en producción— la cobertura sube a **15,33 %** y la **densidad mostrada se conserva
(3,07 frente a 3,00 real), con 1 nodo suelto en vez de 118**. Es decir: la caracterización de
«polvo desconectado» es real en el peor caso y **no sobrevive** al caso alineado; lo que sobrevive
siempre es que **la vista es parcial**. La severidad real **está sin medir**: exige el grafo de
producción. Todo esto, con cifras, en **§6**.

El punto exacto, en `viewer/app/authz/filtered_provider.py:101-104`:

```python
nodes, edges = self._base.graph(workspace, limit=_ALL, entity_type=entity_type, q=q)
vnodes = self._policy.filter_nodes(nodes, self._ctx)[:limit]   # <-- se trunca AQUI
vids = {n["id"] for n in vnodes if "id" in n}
vedges = self._policy.filter_edges(edges, vids, self._ctx)     # <-- y aqui mueren las aristas
```

`MockGraphProvider.graph` (`viewer/app/providers/mock_provider.py:96-103`) y
`Neo4jGraphProvider.graph` (`viewer/app/providers/neo4j_provider.py:206-207`) repiten
exactamente el mismo patrón `nodes[:limit]` + intersección de extremos.

---

## 2. Balance por capa (cifras MEDIDAS)

Grafo sintético, grado medio 3 (`E = 3N`), aristas entre pares al azar, todo `visibility:
reference`, espectador `reviewer` **sin** `admin_full`. `limit=300`.
Instrumento: bancos en `docs/measurements/72-saturacion-grafo/` — `harness_gsat.py` (mock), `harness_http.py` (HTTP), `harness_neo4j.py`,
`harness_cliente.js`. Reproduce el hecho reportado (550/275/151) con otra semilla.

| Capa | n=500 (E=1500) | n=1000 (E=3000) | n=2000 (E=6000) | Pérdida |
|---|---|---|---|---|
| **L0** almacén | 1500 | 3000 | 6000 | — |
| **L1** provider base, `limit=_ALL` | 1500 | 3000 | 6000 | **0** |
| **L2** política: nodos visibles | 500 | 1000 | 2000 | **0** |
| **L2b** truncado `[:limit]` → nodos | 300 | 300 | 300 | (nodos: −40/−70/−85 %) |
| **L3** `filter_edges` entran | 1500 | 3000 | 6000 | |
| **L3** muertas por **truncado de nodos** | **929** | **2682** | **5829** | **100 % de la pérdida** |
| **L3** muertas por **política de arista** | 0 | 0 | 0 | **0** |
| **L3** salen | 571 | 318 | **171** | |
| **L4** `serialize_graph` | 571 | 318 | 171 | **0** |
| **L5a** HTTP 200, auth **desactivada** (`admin_full`) | 571 | 318 | 171 | volumen sí, **autorización NO ejercida** |
| **L5b** HTTP 200, espectador `reviewer` real | 571 | 318 | 171 | **0** |
| **L6** cliente `filterGraph` sin filtros | 171 → 171 | | | **0** |
| Densidad (aristas/nodo) | 1,90 | 1,06 | **0,57** | (real: 3,00) |
| Bytes en el cable | 305 KB | 237 KB | 197 KB | |
| Predicción `E·(limit/N)²` | 540 | 270 | 135 | vs 571 / 318 / 171 |

La predicción cuadrática acierta el orden y la tendencia en las tres bases; el pequeño exceso
sobre la predicción es el sesgo de que los ids consecutivos comparten aristas por construcción.

**Aviso de lectura**: las dos filas del desglose «muertas por truncado» / «muertas por política»
son una **descomposición local del banco de medida**, no dos pasos separados del código de
producción — en `filter_edges` ambas condiciones se evalúan en el mismo bucle. El resto de las
filas (L0, L1, L3 entran/salen, L4, L5a, L5b, L6) sí son salidas directas del código real.

**Además**: con `hideIsolated` el propio cliente revela que de los 300 nodos entregados a
n=2000, **sólo 182 tienen alguna arista**: 118 nodos (39 %) son puntos sueltos.

### Autorización: no pierde nada, y está comprobado que sabría perderlo

Cero pérdida por política **no es** un instrumento apagado: ver §3, control B.

---

## 3. Calibración del instrumento (obligatoria, y falló dos veces)

Una cifra no vale hasta que el medidor demuestra que sabe ponerse rojo.

- **Control A (positivo)** — base donde *todas* las aristas caen entre los 300 primeros nodos.
  Esperado: retención 100 %. **Medido: 900/900, 1500/1500, 3000/3000, 6000/6000; truncado = 0.**
  El medidor no inventa pérdida donde no la hay.
- **Control B (violación)** — mismas bases con las aristas marcadas `visibility: secret`.
  La columna «muertas por política» **debe** ponerse roja.
  **Primer intento: NO se puso roja (0 de 6000).** El contexto de espectador llevaba
  `admin_full=True`, que es un *bypass total*: la política no se evaluaba y esa columna era
  un instrumento muerto que habría «demostrado» que la autorización no pierde nada sin haberla
  ejecutado jamás. Corregido a un espectador `reviewer` real →
  **Medido: 900/1500/3000/6000 muertas por política, salida 0.** Rojo. Revertido → verde.
- **Tercer fallo del medidor**: en el banco de Neo4j los nodos sintéticos salían sin `scope` ni
  `workspace` y la política los denegaba en cierre seguro; el banco marcaba `(0, 0)` y habría
  parecido «el grafo entero se pierde». Corregido el generador, no el código medido.
- **Control del cliente** — `filterGraph` con un tipo de relación inexistente devuelve
  **0 aristas**; sin filtros devuelve **171 → 171**. La capa cliente sabe ponerse roja y no pierde.
- **Cuarta avería, y es la misma otra vez** (la encontró el revisor, no yo). `harness_http.py`
  —la fila L5— **nunca fijaba `S9K_AUTH_ENABLED`**, cuyo valor por defecto es `False`
  (`viewer/app/auth/config.py:13`); entonces `viewer/app/authz/context.py:84-88` devuelve
  `ViewerContext(role="public", admin_full=True)`. **La fila del cuerpo HTTP estaba medida con el
  bypass total puesto**: exactamente la avería nº 1, un fichero más allá, en el único banco que
  no volví a revisar tras corregirla. Las cifras no eran falsas (la fixture es toda `reference`,
  que un `reviewer` con `can_view_reference=True` deja pasar igual), pero **la afirmación de
  alcance sí lo era**: no certificaba «la autorización no pierde nada de extremo a extremo».
  Corregido midiendo **dos filas declaradas**, L5a (auth desactivada, volumen sí / autorización
  no ejercida) y L5b (espectador `reviewer` real inyectado), con un control: el mismo espectador
  **sin** `can_view_reference` debe colapsar la respuesta. **Medido: 0 nodos, 0 aristas.**
  Al calibrar ese control salió además un **quinto fallo del banco**: sobrescribir
  `get_visibility_context` **no surte ningún efecto** sobre `/api/graph`, porque
  `get_filtered_provider` lo llama como función normal y no vía `Depends`; con ese punto de
  inyección el control NO colapsaba (seguía dando 300/171) y habría certificado en falso.

Cinco averías, **todas del instrumento**, ninguna del sistema. Y no afirmo que la lista sea
exhaustiva: la cuarta apareció después de que yo diera por cerrada la calibración, y la quinta
sólo apareció porque un control se negó a ponerse rojo. Lo único que puedo sostener es que cada
fila que afirma «0 pérdidas» tiene detrás un control que **se ha visto ponerse rojo**.

---

## 4. Ablación: el `LIMIT` de la consulta de relaciones de Neo4j es adorno

`neo4j_provider.graph` acota la consulta de relaciones con `LIMIT $limit` **sobre las relaciones**,
no sobre los nodos. Pero el único camino de producción es
`PolicyFilteredProvider.graph`, que invoca al base **siempre con `limit=_ALL` (10.000.000)**
(`filtered_provider.py:101`). Ablacionando ese `LIMIT` (`harness_ablacion.py`):

| n | camino autorizado, con `LIMIT` | ablacionado | veredicto |
|---|---|---|---|
| 300 | (300 nodos, 900 aristas) | (300, 900) | idéntico |
| 500 | (300, 669) | (300, 669) | idéntico |
| 1000 | (300, 402) | (300, 402) | idéntico |
| 2000 | (300, 285) | (300, 285) | idéntico |

**Puede desaparecer sin cambiar ningún resultado del camino autorizado: no es una defensa.**
Que la ablación *sabe* mover la aguja se comprueba en el camino directo (sin política), donde
sí muerde y de forma dañina: n=300 → **300 aristas con `LIMIT` frente a 900 sin él**, es decir,
el provider Neo4j llamado directamente satura ya **a 300 entidades** (densidad 1,00 en vez de 3,00).

Consecuencias que quedan en pie:

- **Superviviente 1**: como el filtro llama al base con `_ALL`, cada `GET /api/graph` **materializa
  el workspace entero** (todos los nodos y todas las relaciones) desde Neo4j en memoria del
  servidor para después quedarse con 300. No es la causa del desplome, pero es la factura que
  pagará cualquier opción, y crece linealmente con el grafo.
- **Superviviente 2**: `Neo4jGraphProvider.graph` **acepta `q` y lo ignora por completo** — el
  parámetro no aparece en ninguna de sus dos consultas Cypher, mientras que `MockGraphProvider`
  sí filtra por `q`. La búsqueda del visor se comporta distinto contra mock y contra Neo4j.
  Es un defecto **independiente** de este carril; se documenta, no se corrige aquí.

---

## 5. Honestidad de la respuesta: hoy el visor **no puede** decir que la vista es parcial

`serialize_graph` (`viewer/app/serializers.py:118`) devuelve `{workspace, nodes, edges}` y nada
más: **ni totales reales, ni marca de truncado**. El cliente calcula su contador «mostrado /
total» con `total = graphStats(loaded)` (`viewer/app/static/js/graph.js:145-146`), donde `loaded`
es *lo que la API devolvió*. Resultado medido a n=2000: la interfaz muestra **300** y **171**
como si fueran el grafo, sin `/ 2000` ni `/ 6000` en ninguna parte, porque nunca se le contó que
faltan 1.700 entidades y 5.829 relaciones.

Esto es lo más grave del hallazgo, y es lo único que **no depende de la alineación** (§6): sea la
cobertura 2,9 % o 15,3 %, la vista es parcial y **se presenta como completa**. Quien la mire
tomará por el grafo entero lo que es un trozo cuyo tamaño nadie le dice.

---

## 6. Cuánto de esto le pasa a producción: manda la ALINEACIÓN

**Corrección a una versión anterior de esta nota.** Decía que con comunidades densas B/C/D
mejorarían «pero la opción 0 no, porque su pérdida depende del orden de almacenamiento, no de la
topología». **Las dos mitades de esa frase son falsas, y está medido.** No manda el orden ni la
topología por separado, sino **su alineación**.

Misma densidad real (grado medio 3), mismo `limit=300`, n=2000, mismo medidor:

| Base | relaciones mostradas | cobertura | densidad mostrada | nodos sueltos |
|---|---|---|---|---|
| Uniforme (orden sin relación con la topología) | 171 / 6000 | **2,85 %** | 0,57 | 118 |
| **Comunidades con orden alineado** | **920 / 6000** | **15,33 %** | **3,07** | **1** |
| Comunidades barajadas (misma topología, otro orden) | 139 / 6000 | 2,32 % | 0,46 | 123 |

Alineado frente a barajado: **×6,6 con la topología idéntica**. Y lo importante no es sólo el
factor:

- Bajo alineación la **densidad mostrada es 3,07 frente a 3,00 real**, y quedan **1** nodo suelto
  de 300. Es decir, **la mitad del impacto que se reportó —«densidad 3,0 → 0,5», «polvo
  desconectado», 118 nodos sueltos— NO sobrevive al caso plausible de producción.**
- Lo que sí sobrevive es la **cobertura**: 15,33 % sigue siendo una vista **parcial** de las
  relaciones.

Por tanto **2,85 % es el peor caso sintético, no una predicción de producción.** En producción las
entidades de un mismo documento se crean consecutivas *y* están densamente interconectadas, que es
justo el caso alineado. **La severidad real está SIN MEDIR** —medirla exige el grafo de
producción, prohibido para este carril— y puede estar en cualquier punto entre 2,85 % y 15,33 %,
o fuera si la alineación es distinta de la que supongo.

Mi afirmación «un panorama de 300 sobre 2.000 es semánticamente imposible» **sobrevive como
afirmación sobre cobertura** (15,3 % sigue siendo parcial) pero **no sobre densidad ni sobre nodos
sueltos**.

Esto **refuerza la recomendación** en vez de debilitarla: si la severidad de lo que ve el usuario
depende de una alineación entre orden de almacén y topología que **nadie mide ni garantiza**, y
que cualquier reindexado o migración puede romper sin previo aviso, entonces que la respuesta
**declare que es una vista parcial** deja de ser una mejora y pasa a ser obligatorio.

---

## 7. Opciones, con coste y efecto MEDIDO

Todas las opciones operan **sobre el conjunto ya filtrado por política**, así que ninguna amplía
lo que un usuario ve: `visibility`, `known_by`, workspace y tope de sesión siguen mandando.
Medido con `harness_opciones.py`, `limit=300`, mismas bases **uniformes** (peor caso: véase §6).

### n=2000 entidades, 6.000 relaciones visibles

| Opción | nodos | aristas | densidad | cobertura de relaciones | nodos sueltos | bytes |
|---|---|---|---|---|---|---|
| **0** actual (subgrafo inducido) | 300 | 171 | 0,57 | **2,9 %** | 118 | 219 KB |
| **A** subir `limit` a 2000 | 2000 | 6000 | 3,00 | **100 %** | 7 | **2,95 MB** |
| **B** sembrar por aristas | 300 | 290 | 0,97 | 4,8 % | 0 | 256 KB |
| **C** top-grado | 300 | 376 | 1,25 | 6,3 % | 20 | 282 KB |
| **D** vecindario (BFS desde un foco) | 300 | 404 | 1,35 | 6,7 % | 0 | 291 KB |

### n=500 / n=1000 (mismo orden: 0 / A / B / C / D)

- n=500: cobertura 38,1 % / 100 % / 44,6 % / 56,7 % / 48,9 % — densidad 1,90 / 3,00 / 2,23 / 2,83 / 2,45
- n=1000: cobertura 10,6 % / 100 % / 13,5 % / 18,5 % / 18,0 % — densidad 1,06 / 3,00 / 1,35 / 1,85 / 1,80

### Lectura honesta de la tabla

**Ninguna selección de 300 nodos arregla esto, y ése es el resultado principal de la fase 2.**
B, C y D multiplican las aristas por 1,7–2,4 respecto al estado actual, pero a n=2000 la mejor
sigue enseñando **6,7 % de las relaciones con densidad 1,35 frente a 3,00 real**. Es aritmética,
no implementación: en un grafo **uniforme** de grado medio 3, cualquier subconjunto de 300 de
2.000 nodos contiene una fracción pequeña de las aristas. **Un panorama global de 300 nodos sobre
un grafo de 2.000 no puede ser completo en COBERTURA**, se elijan como se elijan los nodos —ni
siquiera en el caso alineado de §6, que llega al 15,3 %—.

Matiz obligado por §6: esta tabla es el **peor caso**. En el caso alineado, la opción 0 sube a
15,33 % con densidad 3,07 y 1 nodo suelto, así que **el orden de mérito entre 0/B/C/D podría
cambiar sobre datos reales** y no lo he medido. Lo que no cambia en ningún caso es que la vista
sigue siendo parcial y que el visor no lo dice.

Por tanto las opciones reales no son «qué 300 nodos elijo» sino **qué pregunta responde el visor**:

| # | Opción | Coste | Semántica | Volumen al navegador |
|---|---|---|---|---|
| **A** | Subir `limit` (ya admite hasta 2000) | Nulo en código; el servidor ya materializa todo el workspace de todos modos | Fiel: 100 % de relaciones **hasta 2000**. A 2.001 entidades el precipicio vuelve idéntico | **2,95 MB** a n=2000, ×13,5 respecto a hoy. **No se puede afirmar que el navegador lo aguante: en este proyecto el rendimiento del cliente no se mide — `vis-network` y `graph.js` nunca se ejecutan en pruebas** (sólo `graph-core.js`, que es lógica pura). |
| **D** | Cambiar la pregunta: vecindario de un foco (BFS acotado), no panorama | Medio: endpoint/parámetro de foco + UI de selección de foco | **Honesta por construcción**: «el entorno de X a profundidad k» es una afirmación verdadera y completa dentro de su alcance; 0 nodos sueltos | 291 KB, del orden de hoy |
| **C** | Top-grado como panorama por defecto | Bajo | Sesgada hacia los concentradores; sigue siendo parcial y hay que declararlo | 282 KB |
| **H** | **Declarar la parcialidad** (totales reales + marca de truncado en la respuesta, y contador «300 / 2000 · 171 / 6000» en el visor) | Bajo, y **ortogonal**: no cambia qué se envía | No cambia la semántica de los datos; cambia que **dejen de mentir sobre sí mismos** | +unas decenas de bytes |

`counts()` del provider filtrado ya calcula los totales visibles correctamente
(`filtered_provider.py:67-74`), así que **H no necesita ninguna consulta nueva** ni relaja nada:
son exactamente los totales que ese espectador ya tiene derecho a ver.

---

## 7bis. El defecto pasa de narrado a aseverado en CI

Los bancos de `docs/measurements/` **no los ejecuta ningún job** (`grep -rn measurements
.github/workflows/` → vacío). Un defecto que sólo vive en un documento no enciende ninguna luz
cuando una refactorización lo mueve, lo mejora o lo empeora.

Se añade `viewer/tests/test_saturacion_grafo_caracterizacion.py`, que **fija el desplome
cuadrático** y va con su calibración **dentro de CI, no en prosa**:

- `test_la_retencion_de_relaciones_se_desploma_con_el_cuadrado` — banda de retención por tamaño,
  más la comprobación de que la retención acompaña a `(limit/N)²` dentro de un factor 2.
- `test_calibracion_..._si_alguien_arregla_el_truncado` — ablación del `[:limit]` en una subclase
  local (no se toca `viewer/app/authz/**`): la retención vuelve al **100 %** y se exige que la
  comprobación anterior **falle**. Rojo por arriba.
- `test_calibracion_..._si_el_desplome_empeora` — rojo por abajo.
- `test_la_severidad_depende_de_la_alineacion_entre_orden_y_topologia` — fija el hallazgo de §6.

**Ciclo verificado contra el código de producción**, no sólo contra la subclase: mutando de verdad
`filtered_provider.py:102` (quitar `[:limit]`) → **4 de 6 tests en ROJO**; revertido → **6/6 en
VERDE**, con `sha256` idéntico antes y después
(`6a0a85ea1cb559b7af2484e8981914c30d989034d802866a9a105369b8f870a5`) y la zona prohibida limpia.

`viewer/tests/` está **fuera** del hash de `viewer/app/**` que usa
`benchmarks/perf/calibracion.py:105`, así que **no invalida la calibración de rendimiento**.

---

## 8. Recomendación

1. **H primero, y por separado** (bajo riesgo, no cambia ni la semántica ni el volumen): que la
   respuesta lleve totales visibles y marca de truncado, y que el visor muestre «300 / 2000» y
   «171 / 6000» con un aviso de vista parcial. Mientras esto no exista, cualquier otro arreglo
   deja al visor afirmando cosas que no sabe. **No convierte la vista en fiel; hace que sea
   honesta.**
2. **D después** como forma correcta de mirar un grafo grande: vecindario de un foco en lugar de
   panorama truncado. Es la única opción medida que produce una afirmación verdadera.
3. **A sólo como paliativo consciente y con tope declarado**, nunca como «la solución»: multiplica
   por 13,5 el volumen, no se ha medido qué hace el navegador con ello, y a 2.001 entidades el
   problema vuelve intacto.
4. **No adoptar B ni C como arreglo**: mejoran el número lo justo para tapar el síntoma y dejan la
   vista igual de infiel (≤6,3 % de las relaciones), con el riesgo añadido de parecer arreglada.
5. Aparte de este carril: el `LIMIT` inerte del `rel_query` de Neo4j (§4) y el parámetro `q`
   ignorado por el provider Neo4j (§4, superviviente 2).

## 9. Limitaciones declaradas

- Medido sobre **grafos sintéticos** de grado medio 3, no sobre el grafo real de producción
  (prohibido para este carril). **La severidad real está sin medir** y depende de la alineación
  entre orden de almacén y topología (§6): entre 2,85 % y 15,33 % de cobertura en lo medido, y
  fuera de ese rango si la alineación real es otra. **El orden de mérito de las opciones 0/B/C/D
  podría cambiar sobre datos reales.**
- El camino Neo4j se midió con un **driver de pega**. Es fiel en la semántica de `LIMIT`, que es
  lo que se quería medir, pero **ignora los predicados `workspace` y `entity_type`** de las
  consultas Cypher: no sirve para afirmar nada sobre el acotado por workspace en el provider.
- El **test de caracterización** (`viewer/tests/test_saturacion_grafo_caracterizacion.py`) fija el
  desplome en CI, pero lo hace sobre la **misma fixture sintética**: asevera que el defecto sigue
  ahí y que su magnitud no se mueve, no que la magnitud sea la de producción.
- **El rendimiento en el navegador no se mide en absoluto en este proyecto**; todas las cifras de
  volumen son bytes de carga útil, no comportamiento del cliente. Ninguna afirmación de esta
  nota depende de suponer lo que aguanta el navegador.
- No se ha tocado `viewer/app/**`, así que **la puerta de calibración de `benchmarks/perf/` no
  se invalida y no procede recalibrar**. Si se implementa A, D o H habrá que recalibrarla.

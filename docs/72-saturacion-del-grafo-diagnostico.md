# 72 — Saturación del grafo en `/api/graph`: diagnóstico por capas

**Repo**: `pjclavero/S9-Knowledge` · **Rama**: `fix/graph-saturation-diagnostico` ·
**Árbol medido**: `e0305cc` (= `origin/main`), `git status --porcelain` limpio antes de medir.
**Carril**: GRAPH-SATURATION. Entrega: **diagnóstico + opciones**. No se implementa el cambio de
selección (ver §6). No se toca `viewer/app/**`, ni `benchmarks/perf/**`, ni `.github/workflows/ci.yml`.

---

## 1. Resumen

El desplome de aristas **no está en la consulta Cypher, ni en el provider, ni en la autorización,
ni en la serialización, ni en el cliente**. Está en un único punto:

> **Causa raíz: `/api/graph` devuelve el SUBGRAFO INDUCIDO sobre los primeros `limit` nodos
> en orden de almacenamiento.** Los nodos se recortan primero y las aristas se recogen sólo
> entre los supervivientes, así que la retención de relaciones cae con el **cuadrado** de la
> fracción de nodos mostrada: `p ≈ (limit / N)²`.

A 2.000 entidades con `limit=300` la fracción de nodos es 300/2000 = 15 %, y la de relaciones
15 %² = 2,25 %. **Medido: 171 de 6.000 = 2,85 %.** El visor no enseña un grafo recortado:
enseña el polvo que queda tras elevar al cuadrado.

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
| **L5** HTTP 200, cuerpo real | 571 | 318 | 171 | **0** |
| **L6** cliente `filterGraph` sin filtros | 171 → 171 | | | **0** |
| Densidad (aristas/nodo) | 1,90 | 1,06 | **0,57** | (real: 3,00) |
| Bytes en el cable | 305 KB | 237 KB | 197 KB | |
| Predicción `E·(limit/N)²` | 540 | 270 | 135 | vs 571 / 318 / 171 |

La predicción cuadrática acierta el orden y la tendencia en las tres bases; el pequeño exceso
sobre la predicción es el sesgo de que los ids consecutivos comparten aristas por construcción.

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

Las tres averías fueron **del instrumento**, no del sistema. Se declaran porque las dos primeras
habrían producido conclusiones opuestas a la verdadera.

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

Esto es lo más grave del hallazgo: no es sólo que la vista sea parcial, es que **se presenta como
completa**. Quien la mire sacará conclusiones falsas sobre la topología del grafo de conocimiento.

---

## 6. Opciones, con coste y efecto MEDIDO

Todas las opciones operan **sobre el conjunto ya filtrado por política**, así que ninguna amplía
lo que un usuario ve: `visibility`, `known_by`, workspace y tope de sesión siguen mandando.
Medido con `harness_opciones.py`, `limit=300`, mismas bases.

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
no implementación: en un grafo de grado medio 3, cualquier subconjunto de 300 de 2.000 nodos
contiene una fracción pequeña de las aristas. **Un panorama global de 300 nodos sobre un grafo
de 2.000 es semánticamente imposible**, se elijan como se elijan los nodos.

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

## 7. Recomendación

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

## 8. Limitaciones declaradas

- Medido sobre **grafos sintéticos** de grado medio 3 y aristas uniformes al azar, no sobre el
  grafo real de producción (prohibido para este carril). Un grafo real con comunidades densas
  daría a B/C/D mejores resultados que los de aquí; **la opción 0 no mejoraría**, porque su
  pérdida depende del orden de almacenamiento, no de la topología.
- El camino Neo4j se midió con un **driver de pega que ejecuta la semántica de `LIMIT`**, no
  contra un Neo4j real.
- **El rendimiento en el navegador no se mide en absoluto en este proyecto**; todas las cifras de
  volumen son bytes de carga útil, no comportamiento del cliente. Ninguna afirmación de esta
  nota depende de suponer lo que aguanta el navegador.
- No se ha tocado `viewer/app/**`, así que **la puerta de calibración de `benchmarks/perf/` no
  se invalida y no procede recalibrar**. Si se implementa A, D o H habrá que recalibrarla.

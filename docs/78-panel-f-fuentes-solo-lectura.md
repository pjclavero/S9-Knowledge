# 78 — Panel F (Fuentes) de solo lectura sobre el chasis

Carril **F — SOURCES**. Rama `feat/panel-sources-f`, rebasada sobre `main@e4bcc62`
(base original `main@1f70726`).

> **Numeración.** Este documento nació como `docs/77` y pasó a `78` al rebasar: el carril G reclamó
> el 77 y fusionó antes. El gate `tests/test_docs_numbering.py` lo cazó — comprueba contra la unión
> de `main` **más todas las ramas abiertas**, que es justo el caso en el que cuatro carriles
> paralelos numeran mirando sólo `main`. Renumerado tras medir los números ocupados en las 49 ramas
> remotas: `78` y `79` eran los únicos libres por debajo de `80` (de B).

Hueco **F** del chasis de montaje (`docs/69`), montado con el mismo patrón que el hueco C
(`docs/76`). Prefijo `/panel/sources`, ruta raíz `chassis_sources`, rol y plantilla los del
contrato publicado, interruptor `S9K_PANEL_F_ENABLED` (apagado por defecto, sólo `true` o `1`).

**El contrato publicado no se ha tocado.** La tabla escrita a mano
`CONTRATO_PUBLICADO` de `viewer/tests/test_chassis_mount_contract.py` sigue byte a byte igual, y
`FEATURE_SLOTS` también.

---

## 1. Qué muestra y de dónde sale cada dato

Dos pantallas, las dos GET y las dos de lectura:

| Pantalla | Ruta | Qué enseña |
|---|---|---|
| Listado | `/panel/sources` | Una fila por fuente visible: nombre, entidades, procedencia, reparto por estado de revisión |
| Ficha | `/panel/sources/ficha/{handle}` | Una fuente: workspace, entidades visibles, procedencia, estados, reparto por tipo de entidad |

**Todo sale de una sola llamada autorizada**: `provider.list_entities(workspace)` sobre el
proveedor que entrega `get_filtered_provider`, es decir sobre `PolicyFilteredProvider`, que aplica
la política **antes** de devolver nada. La agregación (`agregar_fuentes`) ocurre sobre ese conjunto
ya filtrado, dentro del router.

| Dato en pantalla | Origen |
|---|---|
| Lista de workspaces | `provider.workspaces()` (filtrado por `allowed_workspaces`) |
| Fuente (nombre) | último segmento de `source_document`, o de `source_id` si falta |
| Entidades por fuente | recuento de nodos **visibles** con ese identificador |
| Procedencia | `source_kind` de los nodos visibles; ausente ⇒ «no disponible» |
| Estado de revisión | `review_status` de los nodos visibles, etiquetado por `app.labels.review_status_label` contra `contracts/review-status/v1` |
| Tipo de entidad (ficha) | `type` / `entity_type`, etiquetado por `entity_type_label` |

### Por qué `list_entities` y no `list_sources`

Porque `PolicyFilteredProvider.list_sources` devuelve **sólo** `source_id` y un recuento: pierde
`source_kind` y el estado de revisión, que son justo «procedencia» y «estado».
`PolicyFilteredProvider.source_detail` tampoco los trae. Pedírselos al proveedor **sin filtrar**
los recuperaría a costa de contar lo invisible, que es precisamente lo que no se hace aquí. Se
agrega sobre lo visible y **se declara en pantalla** que eso es lo que se está contando.

No se ha añadido ningún endpoint, ninguna consulta nueva al backend ni ninguna capacidad nueva.
Lo que **queda fuera por eso**: fecha de ingesta, tamaño, checksum, número de páginas, historial de
reprocesado y estado del pipeline. Nada de eso existe hoy en la interfaz `GraphProvider`; sacarlo
exigiría un endpoint nuevo y está fuera del alcance de este carril.

---

## 2. La frontera de solo lectura, y cómo se garantiza

Un panel de fuentes es el sitio donde más tienta colgar «reingestar», «reprocesar» o «subir». Aquí
no hay nada de eso, y la ausencia se comprueba por **tres** vías independientes, no en prosa:

1. **Espacio de URL, no módulo.** `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` enumera
   las rutas **de la app** bajo `/panel/sources` con `iter_mounted_routes` y exige que ninguna
   declare método de escritura. Enumerar `panel.router.routes` no valdría: un
   `@app.post("/panel/sources/subir")` escrito desde otro fichero cuelga escritura en este prefijo
   sin tocar el mío (calibrado en **F13**, inyectado desde `main.py`).
2. **Suelo de plausibilidad.** `test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia`
   cuenta sólo rutas con **path resoluble** (si contara las irresolubles, el fallo cerrado de
   `route_in_prefix` haría que el suelo se autocumpliera) y **nombra mis tres paths concretos**:
   `/panel/sources`, `/panel/sources/` y `/panel/sources/ficha/{handle}`. Un gate que enumera cero
   elementos habría «demostrado» cualquier cosa (calibrado en **F14**).
3. **Por debajo del HTTP.** `test_el_panel_solo_invoca_metodos_de_LECTURA_del_proveedor` registra
   qué métodos se invocan **sobre el proveedor base inyectado** y exige que estén dentro de
   `{workspaces, list_entities}`, lista escrita a mano. Un GET que llame a un método de escritura
   del backend no lo caza ninguna enumeración de métodos HTTP (calibrado en **F18**).
   **Ojo al alcance**, que es más estrecho de lo que parece y está medido: **§8.1**.

Y un control de **falso positivo**: `test_el_gate_no_acusa_a_un_vecino_de_prefijo` exige que
`/panel/sources-legacy/borrar` y `/panel/sourcesXYZ/borrar` **no** se reclamen como propios (la
frontera es de segmento), con su contrapeso `test_el_gate_si_reclama_lo_que_es_suyo` para que la
frontera de segmento no pueda apagar el gate entero.

Las vías 1 y 2 vienen del patrón del hueco C. **La vía 3 es de este carril y no está en C, B ni G**:
por qué hace falta, en **§8.1**.

---

## 3. Con la autenticación desactivada

> **ACTUALIZADO — decisión del operador, 2026-08-14 (V3 RC).**
> **LORE_ANÓNIMO = DENEGADO.** La medida de este apartado era **1 de 11**; ahora
> es **0 de 11**. La capa juego dejó de concederse por la AUSENCIA de partida y
> pasó a exigir llave propia (`can_view_lore`, declarada en el registro M5b).
> Ver `docs/81`.

Sin `S9K_AUTH_ENABLED` no hay principal, luego no hay autoridad: `build_viewer_context` degrada a
**anónimo de mínimo privilegio** (P0 de autoridad, `docs/75`). El panel **entra** —la guarda
`html_role_guard` es no-op en ese banco— y, desde la decisión, **no muestra nada**: ni material de
partida ni capa juego.

**Un panel vacío ahí es el resultado CORRECTO**, no una pantalla que arreglar. Y ahora es vacío
**absoluto**, no contingente: antes dependía de que el material tuviera partida, y ese matiz es
justamente el que se cerró. Se fija en las dos direcciones, y sobre el camino real (se sustituye el
proveedor **base**, no el contexto ni el proveedor filtrado, de modo que la política y el contexto
que deciden son los de verdad):

- `test_sin_auth_no_reaparece_el_comportamiento_permisivo`: material de partida no aparece ni en la
  lista, ni en los contadores (`sources=0`, `entities=0`), ni por su asa (404).
- `test_sin_auth_la_capa_juego_TAMPOCO_es_visible`: el lore compartido **ya no** se entrega. Este
  test decía lo contrario y decía verdad; se **invirtió**, no se borró, y su docstring conserva por
  qué decía lo que decía.
- `test_pero_un_lector_legitimo_SI_ve_ese_mismo_lore`: **el contrapeso que hacía falta al invertir el
  anterior**. Mismo material, misma ruta; lo único distinto es que hay principal. Sin él, «el panel
  sale vacío» volvería a ser compatible con un panel roto que no muestra nada nunca.
- `test_la_barrera_de_partida_es_real_no_un_panel_siempre_vacio`: la **misma** fuente de partida que
  el rol publicado no ve, una sesión de administrador **sí** la ve. Lo que separa los dos
  resultados es la autoridad, no un defecto de la pantalla.

### La tabla, MEDIDA caso por caso

No es una cita de la política: es lo que **este panel** entrega, medido contra la app real con el
proveedor base sustituido (`test_tabla_medida_del_anonimo_con_auth_desactivada`).

| Material | Anónimo | Lector legítimo |
|---|---|---|
| capa juego, `player` | **no** *(antes VISIBLE)* | **sí** |
| capa juego, `reference` | no | **sí** |
| capa juego, `secret` | no | no |
| capa juego, `narrator` | no | no |
| capa juego, `deny` | no | no |
| visibilidad inválida (`verde`) | no | no |
| sin ámbito declarado | no | no |
| partida ajena | no | no |
| partida sin sesión de revelación | no | no |
| sesión futura | no | **sí** (`can_view_future` del rol revisor) |
| workspace ajeno | no | no |
| | **0 de 11** | **4 de 11** |

**0 de 11** para el anónimo. La segunda columna se añadió al invertir el veredicto y **no es
adorno**: la columna del anónimo es ahora unánime a propósito, así que el suelo «que no sea unánime»
ya no sirve —se autocumpliría—. El suelo pasa a ser: la columna del anónimo tiene que ser CERO, y la
del lector legítimo ni cero ni todo (`test_la_tabla_tiene_las_dos_direcciones_representadas`).

La medición anterior, **1 de 11**, tenía una segunda medición independiente: el carril G midió la
suya sobre su propio hueco, sin que ninguno de los dos viera la del otro mientras medía. Esa
coincidencia es la que demostró que no era el defecto de un panel sino la política —y por tanto que
la corrección tenía que ir en la política, que es donde ha ido—.

**Con la precisión exacta**, porque «coincide caso por caso» era demasiado fuerte y se corrigió tras
la revisión: **mismo veredicto y misma proporción —1 de 11, y el mismo caso visible— sobre conjuntos
solapados pero NO idénticos**. Nueve celdas son comunes; G cubre además `lore-futuro` y `known_by`
malformado, y esta tabla cubre `partida sin sesión de revelación` y `sesión futura`.

El argumento de fondo se sostiene igual, y es el que importa: **una medición aislada puede estar
midiendo el defecto de su propio arnés; dos arneses distintos, sobre huecos distintos y con material
distinto, no comparten el mismo defecto por casualidad**. Y es justo lo que había que comprobar: dos
huecos sobre la misma autorización tienen que dar el mismo veredicto, o uno de los dos está
aplicando una política suya.

La tabla sigue trayendo los **dos** veredictos a propósito —once «no visible» se satisfarían con un
panel roto que no pintara nunca nada—, sólo que ahora los dos veredictos viven en **columnas**
distintas de la misma fila en vez de en filas distintas: una fila por caso, y cada fila falla en las
dos direcciones. `test_tabla_la_misma_fila_para_un_lector_legitimo` es la mitad que se pone roja si
se oculta de más.

Si algún día aparece ahí un «VISIBLE» nuevo, **no se arregla el panel**: se mide, se declara y se
pregunta.

---

## 4. Rutas y nombres de fichero

El identificador de una fuente suele ser un nombre de fichero y a veces una ruta del servidor: dice
dónde vive el material y cómo se llama el árbol de directorios de la máquina. **No sale del
servidor.**

- La pantalla pinta **sólo el último segmento** (`etiqueta_de`), tratando `/` y `\` por igual: un
  identificador escrito en Windows no se escapa de la redacción por usar el otro separador.
- Si tras recortar no queda nada legible se dice «(nombre de fuente no legible)»; **no** se cae
  hacia atrás publicando la ruta entera, que sería el degradado permisivo.
- El enlace a la ficha usa un **asa opaca** (`sha256` truncado a 16 hex), no el identificador: la
  ruta tampoco viaja en la URL, ni al historial del navegador, ni a los logs de un proxy.
- La fila que llega a la plantilla **no contiene** el identificador crudo (`_publicar` lo retira).
  Que Jinja no pueda imprimir lo que no tiene es más fuerte que acordarse de no imprimirlo:
  `test_la_fila_publicada_no_contiene_el_identificador_crudo` lo comprueba sobre el agregado.
- El marcador `data-path-redacted` es **bidireccional**: `true` cuando se recortó,
  `false` cuando no había ruta que ocultar. Ponerlo siempre a `true` pasaría la prueba de fuga y
  vaciaría de significado el aviso; es el falso positivo calibrado en **F5**.

El criterio de la tercera viñeta —**la plantilla no puede filtrar lo que no tiene**— y por qué es
más fuerte que las otras dos, en **§8.2**.

---

## 5. Contadores, ausencias y estados desconocidos

- **Todo contador va después de la autorización.** Salen de agregar el conjunto ya filtrado, nunca
  de preguntar un total al proveedor crudo: un total del sistema junto a una lista recortada revela
  por diferencia lo que el espectador no ve. `test_los_contadores_no_incluyen_lo_que_el_espectador_no_ve`
  usa una **misma fuente** con una entidad de capa juego y otra de partida ajena, y exige `1`, no `2`.
- **Y se declara de qué son.** La pantalla lleva `data-scope="visible"` y un párrafo que dice que
  los recuentos son de lo que ese lector puede ver y **no** los totales del sistema (misma doctrina
  que `docs/73`: un recuento parcial sin declararlo es una afirmación falsa de producto).
- **Ausencia ≠ cero.** Las entidades que no declaran fuente **no se descartan**: van a un cubo
  declarado («sin fuente declarada», `data-source-declared="false"`). Descartarlas en silencio haría
  que la suma de las filas no cuadrase con la realidad sin que nadie se entere. Un
  `source_document` que no es texto (un número, una lista) tampoco inventa una fuente: va al mismo
  cubo.
- **Fallo cerrado en lo desconocido.** Un `review_status` fuera de `contracts/review-status/v1` se
  marca `data-status-known="false"` y se pinta «no reconocido (x)»: no se agrega ni se cuenta como
  si fuera un estado legítimo del sistema. Ausente ⇒ «no declarado», que no es lo mismo que
  «pendiente». `source_kind` ausente ⇒ «no disponible».
- **No autorizado indistinguible de inexistente.** Un asa desconocida y una fuente fuera de ámbito
  dan el **mismo** 404 con el **mismo** cuerpo, y lo dan por construcción: la ficha resuelve el asa
  sólo contra el agregado autorizado, así que el router no tiene manera de saber si esa fuente
  existe para otro. Igual con el workspace: fuera de ámbito e inexistente son el mismo 404.
- **Errores sin fuga.** Un fallo del proveedor da 503 con `type(exc).__name__` y **nunca**
  `str(exc)`, que en un `OSError` trae la ruta del fichero y en un fallo de driver el URI del
  servidor. El test usa un proveedor que revienta con ambas cosas en el mensaje.

---

## 6. Calibración: 20/20, cada garantía puesta en rojo

`scripts/calibrar_panel_sources.py`. Por caso: hash del fichero, mutación efímera, ejecución de los
tests **nombrados uno a uno**, restauración y hash de vuelta. Se exige VERDE sin mutar (diferencial),
ROJO con el defecto, rojo **en la comprobación declarada y no en otra**, y reversión byte a byte.

```
20/20 garantías calibradas: verdes sin mutar, rojas con el defecto, reversión idéntica por hash.
```

| Caso | Garantía |
|---|---|
| F1 | El interruptor apaga el panel |
| F2 | El interruptor se evalúa DESPUÉS de la guarda (si no, el anónimo enumera comparando 404 contra 302) |
| F3 | Los datos salen del proveedor **filtrado**, no del crudo |
| F4 | La pantalla no publica la ruta de origen |
| F5 | *(falso positivo)* El marcador de redacción no se pone cuando no hay ruta que ocultar |
| F6 | El asa de la URL es opaca |
| F7 | Un estado de revisión desconocido no se declara bueno |
| F8 | Las entidades sin fuente se declaran, no se pierden |
| F9 | Un `source_document` que no es texto no inventa una fuente |
| F10 | Recurso no autorizado indistinguible de inexistente |
| F11 | 503 sin volcar rutas ni URIs |
| F12 | El módulo no monta escritura |
| F13 | La frontera es del **espacio de URL**, no del módulo (inyectado desde `main.py`) |
| F14 | *(instrumento)* La enumeración del espacio no puede quedarse vacía |
| F15 | *(falso positivo)* El gate no acusa a un vecino de prefijo |
| F16 | Las plantillas resuelven por nombre de ruta |
| F17 | El router no declara vocabulario propio de autorización |
| F18 | El panel no invoca métodos del proveedor fuera de la lectura |
| F19 | *(control del control)* El test de inercia de `get_visibility_context` detecta que dejara de ser inerte |
| F20 | *(superviviente cazado en revisión)* El asa se deriva del identificador COMPLETO: dos fuentes homónimas no colisionan |

### El punto de inyección congelado

`get_visibility_context` se llama como **función normal** desde `get_filtered_provider`, así que
sustituirlo con `dependency_overrides` es **inerte**: sale verde sin morder. Esto no se advierte en
un comentario, se **demuestra** (`test_sustituir_get_visibility_context_es_inerte`) y además se
calibra el propio control negativo (**F19**): si el punto de inyección dejara de ser inerte, ese
test se pone rojo.

Lo que sí se sustituye es `get_filtered_provider`, con control de colapso
(`test_la_sustitucion_del_proveedor_muerde`: con la sustitución la fuente aparece, sin ella no).

Por qué **demostrarlo** y no advertirlo, y por qué hay que calibrar también la demostración: **§8.3**.

---

## 7. El choque con el test compartido — RESUELTO a favor del carril G

> **CERRADO.** Este carril **ya no toca** `viewer/tests/test_chassis_mount_contract.py`. El carril G
> resolvió el mismo choque con un bloque **aditivo** que monta la premisa «sin datos» sin debilitar
> ninguna aserción; es mejor que lo que había aquí, fusionó antes (PR #183, `main@e4bcc62`) y **es
> la que queda**. Al rebasar, la versión de este carril se descartó y el fichero quedó **byte a byte
> idéntico a `main`** (comprobado: `git diff origin/main -- <fichero>` = 0 líneas).
>
> Comprobación de conjuntos, mecánica y no a ojo: de los 7 ficheros que tocaba este carril quedan
> **6**, el perdido es exactamente el compartido, **cero ficheros ganados**, y los 6 son byte a byte
> los de antes del rebase. Ninguno de los tests de este hueco dependía de la reescritura descartada:
> viven en la suite propia con su propio proveedor sustituido, y siguen verdes.
>
> Se deja escrito el diagnóstico porque el hallazgo sigue siendo válido y explica por qué el test
> compartido tenía que cambiar.

### El diagnóstico medido

`viewer/tests/test_chassis_mount_contract.py`:
`test_slot_renders_empty_state_instead_of_exploding` →
`test_slot_renders_a_declared_state_instead_of_exploding`.

**Motivo, medido.** Exigía literalmente `data-state="empty"` para los cuatro huecos. Era correcto
mientras los cuatro servían una pantalla vacía: el banco no tiene material para ninguno. El hueco F
lee del proveedor `mock` del visor, que **sí** trae entidades con fuente (`examples/sample_graph.json`:
11 nodos, 2 fuentes), así que con el rol publicado la pantalla legítima es `ready`. Con la
aserción anterior, F sólo pasaba **mintiendo**.

La versión estricta («sin datos → vacío; con datos → listo») vive de todas formas en la suite de
este hueco, que es la única que puede controlar si hay material
(`test_sin_material_se_pinta_el_estado_vacio_no_una_excepcion` y
`test_con_material_se_pinta_el_estado_listo`). Por eso descartar la reescritura no costó nada: la
garantía no estaba allí.

**Lección de la ronda**, y vale para el siguiente que monte un hueco: cuatro carriles en paralelo
sobre un test compartido que asume «todos los huecos están vacíos» van a chocar **todos** contra él
en cuanto el primero se llene de verdad. La forma correcta es la de G —**añadir** la premisa que el
test necesita, no relajar la aserción—, y la forma correcta de descubrirlo es avisar al coordinador
en vez de resolverlo cada uno por su cuenta. Aquí se hizo lo segundo tarde: el aviso llegó después
de empujar, y por eso hubo dos ediciones compitiendo por el mismo fichero.

---

## 8. Tres piezas que este carril añade al patrón (no están en C, B ni G)

Quien copie el patrón de los huecos se llevará de C el montaje, la guarda, el interruptor tras la
guarda y el gate del espacio de URL. **Estas tres no vienen de ahí**: son de este carril, y sin
ellas el patrón tiene tres huecos concretos.

### 8.1 La tercera vía de la frontera: qué se le pide al BACKEND

C, B y G comprueban la frontera de solo lectura por el lado del **espacio de URL**: qué rutas hay
montadas bajo el prefijo y qué métodos declaran. Eso es necesario y no es suficiente.

**Un GET que llame a reingesta no lo caza ninguna enumeración de métodos HTTP.** El handler declara
`GET`, la ruta pasa el gate, la enumeración sale limpia — y por debajo el panel invoca un método del
proveedor que escribe. En un panel de fuentes ese es *el* fallo probable, porque «reprocesar esta
fuente» es lo primero que alguien querrá colgar de la ficha.

Por eso aquí se enumera también **hacia abajo**: el proveedor de pruebas registra cada método que se
le invoca y `test_el_panel_solo_invoca_metodos_de_LECTURA_del_proveedor` lo comprueba. Calibrado en
**F18**: se inyecta una llamada de más y el test se pone rojo.

**Alcance exacto de esa garantía** — corregido tras la revisión independiente, porque la primera
redacción de esta sección **sobrevendía** y eso está medido:

> El panel no invoca, **sobre el proveedor BASE inyectado**, ningún método fuera de
> `{workspaces, list_entities}`.

Y **no** afirma, como decía antes, que «cualquier método nuevo obligue a una decisión visible». Dos
límites, los dos medidos sobre los 7 métodos del proveedor filtrado:

- `list_sources()` y `source_detail()` **sobreviven en verde (70/70)**: el registro vive en el
  proveedor **base**, y esos dos se recomputan desde `_visible_nodes → _base.list_entities`, que
  está en la lista blanca.
- Más serio: **un método que no exista en el doble es invisible del todo**.
  `getattr(provider, "reingest_source", noop)(ws)` desde el GET pasaría **verde** — es decir, el
  escenario mismo que esta sección usa para justificar el mecanismo es el que no cazaría si
  `reingest_source` llegara al proveedor real.

**Hoy no es un defecto vivo**: `GraphProvider` no declara ni un método de escritura en toda la
jerarquía, y el único extra del proveedor real es `close()`. Y hay una **mitigación real que
conviene declarar**: si `reingest_source` llegara como `@abstractmethod`, el doble tendría que
implementarlo y **sí** quedaría registrado. Es **deuda de instrumento, no defecto**, y se escribe
aquí para que nadie herede la garantía más ancha de lo que es.

Recomendación de fondo, que **sigue en pie y es lo valioso de esta sección**: **las dos
enumeraciones, no una**. La de arriba dice qué se le puede pedir al panel; la de abajo, qué pide el
panel. Quien la herede que la monte sobre el objeto que de verdad quiere vigilar —si lo que
preocupa es el proveedor real, el registro va ahí, no en un doble que sólo tiene los métodos que
alguien se acordó de escribir.

### 8.2 El asa opaca, y por qué la plantilla no debe tener el dato

El identificador de una fuente es un nombre de fichero y a veces una ruta del servidor. Tres capas,
en orden de fuerza creciente:

1. se pinta **sólo el último segmento** (`/` y `\` por igual);
2. el enlace usa un identificador **derivado por hash** (`sha256[:16]`), no el real, así que la ruta
   no acaba en la URL, ni en el historial del navegador, ni en los logs de acceso de un proxy;
3. y la fila que llega a Jinja **no contiene el identificador crudo**: `_publicar` lo retira.

La tercera es la que importa, y el criterio es éste:

> **La plantilla no puede filtrar lo que no tiene.**

Las dos primeras capas dependen de que nadie escriba `{{ f.clave }}` en un `<td>` dentro de seis
meses. La tercera no depende de nadie. `test_la_fila_publicada_no_contiene_el_identificador_crudo`
lo comprueba sobre el agregado, no sobre el HTML: la garantía vive donde se construye el dato, no
donde se pinta.

Y el marcador de redacción es **bidireccional** a propósito (**F5**): ponerlo siempre a `true`
pasaría la prueba de fuga y dejaría el aviso «(ruta oculta)» sin significado.

### 8.3 F19: demostrar el control negativo en vez de advertirlo

`get_visibility_context` se llama como **función normal** desde `get_filtered_provider`, así que
sustituirlo con `dependency_overrides` es **inerte**: un test que lo sustituya sale verde sin morder
nada. Ese hecho estaba escrito en un comentario de la suite de C.

Un comentario no impide que el siguiente carril fabrique un arnés que no muerde creyéndose
protegido. Así que aquí el hecho **se demuestra**
(`test_sustituir_get_visibility_context_es_inerte`) y, un paso más, **se calibra la demostración**
(**F19**): se hace que el punto de inyección SÍ muerda —el router pasa a recibirlo por `Depends`— y
se exige que el test lo note. Sin F19, la afirmación de inercia sería un test negativo que pasa por
accidente, que es la forma más fácil de tener una garantía imaginaria.

Es la lección que este proyecto ha aprendido a golpes, aplicada al propio instrumento: **una
afirmación no cuenta hasta que existe una prueba capaz de ponerse roja, y eso vale también para las
afirmaciones sobre el arnés.**

---

## 9. Supervivientes y limitaciones

**Supervivientes (mutaciones que NO ponen rojo lo que uno esperaría):**

- `test_los_metodos_de_escritura_son_rechazados_por_http` **sobrevive a F12**: sondea sólo el
  prefijo raíz, así que un POST colgado en cualquier subruta lo deja verde. No es una garantía; se
  conserva como redundancia inofensiva y la defensa real es la enumeración del espacio de URL.
- `test_el_panel_no_monta_ningun_metodo_de_escritura` es **redundante por construcción** con el
  test del espacio de URL (F12 pone rojos los dos; F13 sólo el segundo). Se conserva porque
  **localiza** el fallo: dice que el POST lo puso este fichero y no otro carril.

**Limitaciones declaradas:**

- **Sin techo de página**, y es una limitación *compartida con los otros huecos*. El panel
  materializa el conjunto visible del workspace para agregarlo; no es una pasada nueva
  —`PolicyFilteredProvider` ya lo materializa por dentro en cada llamada, igual que hace `/sources`
  hoy—, pero el «sin tope» es `_ALL = 10_000_000` viajando como `LIMIT $limit` hasta Neo4j. Eso **no
  abre ningún canal** (el filtro sigue aplicándose antes de entregar), pero **puede degradar** con un
  corpus grande. **Sigue sin medirse**: no hay aquí ninguna cifra de rendimiento, y no se afirma
  ninguna.
- No hay filtros ni paginación en el listado: se muestran todas las fuentes visibles. Un workspace
  con miles de fuentes daría una tabla larga.
- **Los estados y la procedencia se calculan sobre entidades, no sobre la fuente.** Una fuente cuyas
  entidades sean todas invisibles para el lector **no existe** para este panel, y eso es
  deliberado: la alternativa es contar lo invisible.
- **Contra base viva.** Conviene ser preciso, porque las dos redacciones anteriores de este punto se
  desplazaron, y la segunda hacia el lado conservador.

  Lo que **sí** está cubierto: los tests de integración se saltan **sólo en local**; el job
  `Authz integration (Neo4j efímero)` los ejecuta contra **Neo4j 5.26 vivo**, y ese job **falla si
  algo se omite y falla si no se ejecutó ninguna prueba**, así que un verde por omisión ahí no es
  posible. Y `list_entities` **sí** se ejercita contra base viva: unas 8 pruebas de
  `test_neo4j_integration_authz.py` pasan por ella a través del proveedor filtrado.

  Lo que **nadie** mide contra base viva, y es el residuo real de este carril: que la **proyección
  Cypher entregue `source_document`, `source_kind` y `review_status`** — que es exactamente de lo
  que vive este panel. Es plausible que los entregue (`RETURN n` + `_node_to_dict` devuelve todas
  las propiedades del nodo), **pero no está medido**. Ni la política ni la agregación entran en ese
  residuo: son código puro y sí están medidas.
- El hueco sigue **apagado por defecto**. Encenderlo en producción es una decisión del operador,
  fuera de este carril.
- Nada de esto se ha ejecutado contra producción, VM105 ni Neo4j productivo. Todas las cifras salen
  del banco de pruebas.

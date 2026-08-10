# 61 — Visor de grafo: UX V2

Rama: `feat/viewer-graph-ux-v2` (desde `origin/main` @ `d169052`).
Carril A. Sin PR abierta a propósito.

> **Segunda ronda.** El primer dictamen fue **NO CONFORME**. Esta versión
> incorpora las correcciones: Node obligatorio en CI, batería de navegador para
> `graph.js`, coherencia transversal de `visibility`/`knowledge_layer`, expandir
> vecinos sin delatar lo oculto, "sin acceso" resuelto contra el contrato real de
> M5b, y los hallazgos H3/H4/H5. La rama **no se ha fusionado con `main`**
> (sigue sobre `d169052`, anterior a M5b `b6b0803`): el contrato de M5b se ha
> verificado leyéndolo y midiéndolo, no mezclándolo, porque el encargo prohíbe
> fusiones. Zonas congeladas intactas: no se ha tocado `viewer/app/policies/**`,
> `viewer/app/authz/**` ni `providers/neo4j_provider.py`.

## Problema

El visor del grafo (`/graph`) era una prueba de concepto: una barra con cuatro
controles, un lienzo y un panel de ficha. En concreto:

- **Sin panel de filtros.** Un único `<select>` de tipo de entidad, de selección
  simple, que además reconsultaba el backend en cada cambio.
- **Sin filtros de relación** de ninguna clase.
- **Sin leyenda.** Los nodos venían coloreados por tipo, pero en ninguna parte
  se decía qué significaba cada color.
- **La búsqueda no buscaba: recargaba.** Escribir texto mandaba `q=` a la API y
  redibujaba el grafo entero con el subconjunto. No localizaba, no centraba y no
  resaltaba nada; se perdía el contexto de lo que se estaba mirando.
- **Sin fit/reset zoom, sin contadores** de nodos y relaciones.
- **Estados invisibles.** Un grafo vacío y un grafo cargando se veían igual:
  lienzo negro. Un error se escribía en el panel lateral como
  `Error cargando el grafo (503)`, es decir, filtrando el código HTTP al usuario.
- **Sin expandir vecinos.** Lo que no cabía en el `limit` no existía.
- **Sin estado en la URL:** una vista filtrada no se podía compartir ni recargar.
- **Sin teclado** más allá del Intro en la caja de búsqueda.
- Toda la lógica vivía enredada con el DOM y con `vis-network`, así que **no
  había forma de probarla**.

Lo que **no** era problema, y conviene registrarlo porque el encargo lo daba por
dudoso: `vis-network` **ya estaba vendorizado** en
`viewer/app/static/js/vendor/vis-network.min.js` (v9.1.9, 688 KB, con `integrity`
declarado). No hay ninguna dependencia de CDN ni de Internet. No se ha tocado.

## Solución

Separación en dos capas y reescritura de la página:

1. **`graph-core.js` (nuevo): lógica pura**, sin DOM y sin red. Búsqueda,
   filtros, inventario de tipos, contadores, estados de vista, mensajes de error
   y estado de URL. Se carga como script clásico (`window.S9KGraphCore`) y
   también se puede `require()` desde Node, que es lo que permite probarlo.
2. **`graph.js`: solo pegamento** — eventos, pintado y llamadas a la API.

### Funcionalidad entregada

| Requisito | Estado |
|---|---|
| Panel lateral de filtros | Sí, columna izquierda plegable |
| Filtro por tipo de entidad | Sí, casillas multiselección con recuento |
| Filtro por tipo de relación | Sí, casillas multiselección con recuento |
| Leyenda visual | Sí, color + nombre por tipo presente |
| Búsqueda que localiza, centra y resalta | Sí, lista de coincidencias; Intro centra la primera |
| Ficha lateral sin salir del grafo | Sí, nodos y relaciones |
| Expandir vecinos | Sí, botón, doble clic y tecla `E` |
| Mostrar/ocultar etiquetas de relación | Sí |
| Fit / reset zoom | Sí ("Encajar" y "Reiniciar vista") |
| Contador de nodos y relaciones | Sí, `visibles / totales` |
| Estados claros | Sí: cargando, vacío, sin resultados, sin acceso, error |
| Responsive | Sí, tres cortes (1100 / 900 / 560 px) |
| Teclado | Sí: `/`, `Esc`, `F`, `E`, `Intro` |
| URL reproducible | Sí, solo parámetros de presentación |
| Vendorizar vis-network | Ya lo estaba; verificado por test |

## Decisiones

**El filtrado es de cliente, no de servidor.** Antes, cambiar de tipo disparaba
una petición nueva. Ahora se pide el grafo una vez (hasta `limit`) y los filtros
se aplican sobre lo recibido. Motivos: es instantáneo, permite combinar filtros
sin multiplicar consultas y —lo importante— **no cambia qué datos salen del
backend**. El filtro de cliente solo puede enseñar *menos* de lo que el backend
ya autorizó, nunca más. El precio es que los filtros operan sobre la ventana de
`limit` nodos, no sobre el grafo completo (ver Limitaciones).

**Una relación solo se dibuja si sus dos extremos están visibles.** Al filtrar
por tipo de entidad no quedan aristas colgando ni nodos fantasma implícitos.

**El estado de la URL tiene lista blanca.** Solo viajan `q`, `types`, `rels`,
`limit`, `labels`, `iso`. Cualquier otra clave se ignora al parsear. Esto es
deliberado: la barra de direcciones no debe poder pedir un punto de vista
distinto. Hay un test que intenta colar `view_as`, `visibility`, `known_by`,
`scope`, `character_id` y `partida_id` y comprueba que se descartan.

**Todas marcadas ≠ todas desmarcadas** (hallazgo H5). El filtro tiene ahora
tres estados, no dos: `null` = sin filtro (pasa todo, y la URL queda limpia),
`[]` = el usuario ha desmarcado todas las casillas (no pasa nada), y una lista
con elementos = pasa lo listado. Antes, `[]` se trataba como "no filtrar", así
que desmarcarlo todo mostraba el grafo entero: un estado imposible de alcanzar
a propósito. El `[]` viaja en la URL como `types=` vacío para que sobreviva a
una recarga.

**"Quitar filtros" quita todos los filtros** (hallazgo H5). Antes limpiaba los
tipos pero se dejaba puestas la búsqueda y la casilla "ocultar nodos sueltos".
Ahora `clearAllFilters()` es una sola función que comparten ese botón y
"Reiniciar vista"; el segundo además reencuadra el lienzo y cierra la ficha
abierta (volver a la vista inicial incluye la selección).

**Un vendor que no carga no es un fallo de red** (hallazgo H3). Si el navegador
bloquea `vis-network.min.js` porque el `integrity` no cuadra —o el fichero no
está—, el servidor sigue perfectamente vivo y los datos llegan. Decirle a la
persona "No se ha podido contactar con el servidor" la manda a mirar donde no
es. Hay una familia de estado propia, `renderer`, que gana a todas las demás:
`graph.js` detecta al arrancar que `vis.Network` no existe, `drawGraph()` se
convierte en no-op (el resto de la página sigue funcionando en vez de morir con
un `ReferenceError`) y el mensaje pide recargar y avisar a quien administra.

**Los mensajes de error son de familia, no de código.** `errorMessageForStatus`
mapea el status HTTP a uno de siete mensajes fijos en castellano. El usuario no
ve el código, ni rutas, ni trazas, ni identificadores. Un test recorre todos los
mensajes y falla si alguno contiene una barra, un número de tres cifras o
palabras como `Traceback` o `neo4j`.

**Expandir vecinos reutiliza `/api/entities/{id}`**, que ya pasa por el proveedor
filtrado. No se ha creado ningún endpoint nuevo, y por tanto no hay una segunda
puerta por la que puedan salir datos.

**`visibility` y `knowledge_layer` no se pintan en ninguna ficha del usuario
normal.** Decisión del operador tras la revisión. El razonamiento: el frontend
no debe razonar sobre `visibility`, `known_by`, `scope` ni `knowledge_layer`
como si fueran atributos de presentación, porque la autorización se resuelve
*antes* de que el contenido llegue a la plantilla. Si estás leyendo una ficha es
porque puedes; etiquetarla "Secreto" no añade nada y sugiere que hay fichas que
se sirven a medias.

La primera versión de este carril lo aplicó solo a la ficha lateral del grafo, y
el revisor señaló —con razón— la incoherencia: `entity.html` y
`entity_detail.html` seguían pintando esos labels, y a `entity_detail.html` se
llega desde el botón "Ficha completa" **de esa misma ficha lateral**. Ahora la
regla es transversal: ninguna de las tres plantillas los renderiza. Lo que **no**
se ha retirado es `review_status_label`, que es calidad del dato ("¿está
revisado?") y no autorización; sigue en las dos fichas completas y en el panel.
El backend no se ha tocado: los campos siguen viajando en el JSON, simplemente
no se presentan. Una vista diagnóstica separada y protegida para admin podría
existir en el futuro; pastillas normales, no.

Tests que lo sostienen: `test_las_fichas_de_entidad_no_pintan_vocabulario_de_
visibilidad` (paramétrico sobre las dos plantillas × cuatro campos, mirando solo
las expresiones `{{ ... }}` que de verdad se renderizan),
`test_la_ficha_servida_no_menciona_ninguna_etiqueta_de_visibilidad` (sobre el
HTML ya servido, por si el dato llegase por otro camino),
`test_las_fichas_de_entidad_conservan_el_estado_de_revision` (control de que la
limpieza no se llevó información funcional) y, en navegador,
`test_la_ficha_completa_tampoco_habla_de_visibilidad_ni_de_capa`, que entra
**como admin** a un nodo `secret` —el único rol al que el backend se lo sirve, o
sea el único caso en el que la plantilla tiene el dato y podría pintarlo.

**Expandir vecinos no dice nunca cuántos faltan.** Regla explícita del operador:
la UI no decide qué está autorizado; pide expandir X y representa exactamente lo
que el backend devuelve. El mensaje es siempre el mismo —"Se muestran los
elementos disponibles para tu vista."— tanto si llegaron vecinos nuevos como si
no. La versión anterior decía "Se han añadido N entidad(es) vecina(s)", que es
un número derivado de la respuesta y, comparado entre dos usuarios, una pista de
lo que uno no ve. No hay contador, ni hueco, ni "3 de 7".

## Ficheros

| Fichero | Cambio |
|---|---|
| `viewer/app/static/js/graph-core.js` | **Nuevo.** Lógica pura, ~380 líneas |
| `viewer/app/static/js/graph.js` | Reescrito: capa de UI |
| `viewer/app/templates/graph.html` | Reescrito: layout de tres columnas |
| `viewer/app/static/css/app.css` | Bloque de grafo sustituido (`/* Graph page layout (UX V2) */`) |
| `viewer/tests/test_graph_ux_v2.py` | **Nuevo.** 60 casos |
| `viewer/tests/js/graph_core_spec.js` | **Nuevo.** 47 casos de lógica pura |
| `viewer/tests/browser/test_browser_graph_ux.py` | **Nuevo.** 17 casos en Chromium real |
| `viewer/tests/browser/{conftest,e2e_support}.py` | Traídos del carril D `test/viewer-browser-e2e-v1` (`67c1758`), sin modificar |
| `viewer/app/templates/entity.html` | Se retiran visibilidad y capa de conocimiento |
| `viewer/app/templates/entity_detail.html` | Ídem |
| `.github/workflows/ci.yml` | Jobs `check-ci-config` y `test-graph-js` |
| `.github/scripts/check_ci_config.py` | Traído de `chore/ci-test-branches-y-node`, sin modificar |
| `.github/ci-fragments/test-graph-js.yml` | Ídem: se conserva verbatim para que el merge con esa rama sea limpio |

`viewer/app/main.py` no ha necesitado cambios: la ruta `/graph` ya pasaba
`workspace` y `graph_limit`, que es todo lo que la plantilla nueva consume.

### Node deja de ser opcional en CI

`viewer/tests/test_graph_ux_v2.py` se auto-omite si falta Node
(`shutil.which("node")` + `skipif`). El job requerido `test-viewer` **no tiene
Node**, así que las aserciones de la especificación JS se saltaban en silencio y
el job pasaba en verde sin haberlas ejecutado. Se instalan dos jobs, ambos
traídos verbatim de `chore/ci-test-branches-y-node`:

- **`test-graph-js`** — el fragmento que esa rama dejó preparado en
  `.github/ci-fragments/test-graph-js.yml`. Instala Node 20, ejecuta el fichero
  y falla si aparece un solo `skipped` o si no llega a ejecutar nada.
- **`check-ci-config`** — el gate que impide que se olvide: falla si existe un
  test que dependa de Node sin un job que lo ejecute *por nombre*, y también si
  alguna rama de `origin` no está cubierta por `on.push.branches`.

Comprobado en las dos direcciones, en el worktree:

```
$ python3 .github/scripts/check_ci_config.py          # con el job instalado
OK: prefijos de rama cubiertos y sin tests que se omitan por falta de Node
rc=0

$ git show HEAD:.github/workflows/ci.yml > .github/workflows/ci.yml  # sin el job
$ python3 .github/scripts/check_ci_config.py
::error::la rama `test/viewer-browser-e2e-v1` existe en origin y NO dispara CI…
::error::viewer/tests/test_graph_ux_v2.py se auto-omite si falta Node y ningun
         job de ci.yml usa actions/setup-node…
FALLO: 2 problema(s) de configuracion de CI
rc=1
```

El fragmento se conserva sin editar aunque ya esté instalado: el mensaje de
error de `check_ci_config.py` apunta a él, y dejarlo byte a byte igual hace que
el merge con `chore/ci-test-branches-y-node` no tenga conflictos.

## UX

Barra superior: plegar filtros · workspace · búsqueda · límite · Encajar ·
Reiniciar vista · Recargar · contadores.

Columna izquierda: tipos de entidad (con su color), tipos de relación,
visualización (etiquetas, ocultar nodos sueltos, quitar filtros) y leyenda.

Centro: franja de estado + lienzo.

Columna derecha: ficha del nodo o de la relación seleccionada, con acciones
Centrar / Expandir vecinos / Ficha completa.

Teclado: `/` enfoca la búsqueda, `Intro` centra la primera coincidencia, `Esc`
cierra la ficha o limpia la búsqueda, `F` encaja la vista, `E` expande los
vecinos del nodo seleccionado. `vis-network` aporta además navegación con
flechas sobre el lienzo enfocado.

Regla del desplegable de resultados: **mientras se escribe se ofrece, y en
cuanto se elige se cierra** — por `Intro` y por clic, exactamente igual. Un
menú de elección que sigue abierto después de haber elegido no informa de nada
y sí estorba: es `position:absolute` con `z-index:60`, cae sobre el lienzo,
tapa el grafo que se acaba de centrar y se come el clic siguiente. Con el ratón
era peor que con `Intro`, porque el puntero se queda justo encima de la lista.
Cerrar **no** cancela la búsqueda: el término sigue en el campo y en la URL, y
volver a teclear reabre la lista. Con cero coincidencias la lista se queda
abierta con «Sin coincidencias», y eso es deliberado: es lo que iguala un nodo
no autorizado a uno inexistente (huella de 17 canales en
`tests/browser/test_browser_navigation.py`).

En pantallas ≤900 px los dos paneles pasan a superponerse y la ficha entra por
la derecha con el botón de cierre visible. **Por encima de 900 px ese botón está
`display:none`** (es una columna fija, no un panel que tape nada): en escritorio
la ficha se cierra con `Esc` o pinchando en zona vacía del lienzo. Las pruebas
de navegador usan la vía real de cada tamaño en vez de fingir que hay un botón
donde no lo hay.

## Tests

Tres capas, cada una en su sitio:

| Capa | Fichero | Qué puede ver | Qué NO puede ver |
|---|---|---|---|
| Lógica pura (Node) | `tests/js/graph_core_spec.js` | búsqueda, filtros, URL, estados | nada del DOM |
| Página y contrato (pytest) | `tests/test_graph_ux_v2.py` | plantilla servida, rutas, fronteras | que los eventos estén atados |
| Navegador (Playwright) | `tests/browser/test_browser_graph_ux.py` | cableado real, pintado, recorridos | — |

**1. Especificación JS de la lógica pura**

```
$ cd viewer && node tests/js/graph_core_spec.js
47 pasados, 0 fallidos   ·   exit 0
```

Antes 38; los nueve nuevos son el ranking de búsqueda que sí discrimina (H4),
la separación entre "sin filtro" y "nada seleccionado" (H5) y la familia de
estado `renderer` (H3).

**2. Tests de la página y del contrato**

```
$ cd viewer && python3 -m pytest -q tests/test_graph_ux_v2.py
65 passed, 3 warnings in 1.37s   ·   exit 0
```

Antes 46. Los nuevos: `aria-live` en el elemento correcto, la coherencia
transversal de las fichas, el 404 que no habla de acceso, expandir vecinos sin
recuento, el job de CI con Node, la existencia de la batería de navegador y la
ausencia de bytes de control en los estáticos.

**3. Navegador (Chromium real)**

```
$ cd viewer && python3 -m pytest -q tests/browser      # carriles D + A juntos
155 passed, 12 xfailed, 3 warnings in 248.32s   ·   exit 0
```

**Cero saltados**: el navegador estaba presente. (Para que lo estuviera en esta
máquina hubo que extraer a mano las librerías del sistema; ver Limitaciones.)

### Las dos pruebas del carril D que la V2 invalidó

`test_la_busqueda_del_grafo_filtra_de_verdad` y
`test_seleccionar_un_nodo_abre_su_ficha_lateral` exigían que teclear en el
buscador disparase una petición `/api/graph?...&q=...`. Eso no era un requisito
de producto sino la implementación de entonces: la V2 busca **en el cliente**,
sobre lo que el backend ya entregó, así que ambas se rompían sin que hubiera
ningún defecto.

Se han reescrito como **tres casos** que congelan el *resultado de seguridad* y
no la implementación —«la búsqueda solo puede encontrar lo que ya existe en la
vista autorizada»—, y que seguirían valiendo tal cual si algún día se decidiera
una búsqueda remota autorizada:

| Caso | Prueba | Qué garantiza |
|---|---|---|
| 1 | `test_la_busqueda_encuentra_centra_y_resalta_un_nodo_visible` | Un nodo que el backend **sí** entregó a ese rol se encuentra, queda centrado en el lienzo (medido en píxeles) y resaltado con su ficha abierta. |
| 2 | `test_la_busqueda_de_algo_inexistente_no_encuentra_nada` (×2: nombre e id) | Un nombre o un id que no existe da cero resultados, mensaje «Sin coincidencias» y ninguna ficha. |
| 3 | `test_un_nodo_no_autorizado_es_indistinguible_de_uno_inexistente` | Un `viewer` que busca el **nombre exacto** y el **id exacto** del nodo `secret` obtiene una huella observable *idéntica* a la de un nombre y un id inventados. |

#### La huella observable (corrección H1)

La primera versión de la huella miraba cuatro cosas —la lista de resultados, el
contador de nodos y si la ficha estaba abierta— y por eso **no valía**: un
revisor escribió fugas en el contador de **aristas**, en el mensaje de
`#graph-status` (visible y anunciado por `aria-live`) y en la **URL**, y la
prueba siguió verde.

Una versión anterior de este documento decía que la huella abarcaba «**todo el
estado observable**». **Era falso**, y una afirmación falsa en una prueba de
seguridad es peor que una limitación escrita. La huella cubre **diecisiete
canales concretos**, y estos son:

| # | Canal | Qué se lee |
|---|---|---|
| 1 | `resultados` | lista de resultados pinchables |
| 2 | `texto_lista` | texto de `#search-results` |
| 3 | `lista_oculta` | visibilidad de `#search-results` |
| 4 | `contador_nodos` | `#counter-nodes` |
| 5 | `contador_aristas` | `#counter-edges` |
| 6 | `estado_texto` | texto de `#graph-status` (anunciado por `aria-live`) |
| 7 | `estado_visible` | visibilidad de `#graph-status` |
| 8 | `ficha_texto` | texto de la ficha lateral |
| 9 | `ficha_abierta` | si la ficha está desplegada |
| 10 | `ficha_aria` | `aria-label` + `aria-hidden` de la ficha lateral |
| 11 | `titulo` | `document.title` |
| 12 | `contadores_filtro` | todos los `.filter-count` del panel de filtros |
| 13 | `leyenda` | texto de cada fila de `#graph-legend` |
| 14 | `url` | la URL completa |
| 15 | `seleccion` | selección real de vis-network (vía `S9KGraphView`) |
| 16 | `encuadre` | zoom y centro del lienzo (vía `S9KGraphView`) |
| 17 | `lienzo` | el `<canvas>` píxel a píxel, con la física ya parada |

**Los cuatro canales que el segundo revisor encontró escapados —10, 11, 12 y
13— se han incorporado.** Son lecturas de DOM baratas y deterministas (no
dependen del término buscado, así que no introducen intermitencia) y las tres
primeras se derivan de *los datos cargados*, que es exactamente por donde
entraría una fuga de autorización. El coste de añadirlas era casi nulo y el
argumento para dejarlas fuera, ninguno.

**Lo que sigue fuera, nominalmente** (ver también Limitaciones):

- **Detalles de implementación**, a propósito: si hubo petición de red, qué
  función se llamó, en qué orden se pintaron los filtros. La prueba habla de lo
  que una persona percibe, no de cómo está hecho el visor.
- **Canales fuera del `<body>` de `/graph`**: cabeceras HTTP, cookies,
  `localStorage`, tiempos de respuesta. La promesa es sobre la *vista
  ordinaria*, no frente a un atacante con herramientas de red.
- **Lo que la normalización del término borra.** Es el límite intrínseco de la
  técnica y tiene su propia entrada en Limitaciones.

Dos decisiones de método:

- **Normalización del término.** Dos búsquedas siempre se distinguen en algo
  trivial: el texto tecleado, que viaja al campo y a `?q=…`. Antes de comparar
  se sustituye el término por `<TERMINO>` (también en sus formas
  *percent-encoded*): lo que sobreviva a esa sustitución y siga siendo distinto
  solo puede venir de los datos, no de la consulta. **Tiene un precio exacto,
  descrito en Limitaciones.**
- **Estabilización del lienzo.** Comparar capturas con la física en marcha da
  una prueba que falla al azar, y eso es peor que no tenerla. Se espera a *dos*
  señales: el evento `stabilized` de vis-network (expuesto en
  `S9KGraphView.isStabilized`, ventana de observación **de solo lectura**) y que
  dos capturas consecutivas del `<canvas>` sean idénticas —lo segundo cubre las
  animaciones de `focus`/`fit`, que mueven la cámara *después* de que la física
  pare—.

**La ventana de observación está congelada.** `window.S9KGraphView` se publica
con `Object.freeze` y `defineProperty({writable: false, configurable: false})`.
No es confidencialidad —solo devuelve lo ya dibujado y no alcanza `loaded`—,
sino **integridad de la prueba**: tres de los diecisiete canales (15, 16 y la
espera de estabilización) se leen a través de ese objeto, y mientras fue
reemplazable cualquier script de la página podía devolver constantes y dejar la
huella demostrando el vacío. Lo cubre
`test_la_ventana_de_observacion_no_se_puede_reescribir`, que intenta las tres
puertas: sustituir el objeto entero, sustituir un método y añadir uno nuevo.

#### Buscar por identificador (decisión de producto, H4)

El caso «buscar por id» era **vacuo**: el identificador no estaba en el índice,
así que no encontraba nada *ni para el admin*. El índice pasa a ser **nombre ·
alias · tipo · resumen · `entity_id`**, donde `entity_id` es el identificador
**estable de dominio** que entrega el backend (`serialize_node`, campo nuevo).

> **Ojo:** esto está entregado **con el proveedor `mock`**. Con Neo4j la
> búsqueda por identificador queda **inerte** hasta que su proyección incluya
> `entity_id`; ver Limitaciones.

Lo que **no** entra, y hay una prueba por cada mitad:

- el `elementId` de Neo4j (hoy `node.id` con ese proveedor): no es identidad
  durable, se regenera al restaurar un dump;
- cualquier identificador que el backend no haya entregado en ese nodo.

**La regla se comprueba en los dos lados.** `graph_core_spec.js` demuestra que
el *cliente* no indexa `node.id`, pero es **ciego a un servidor que copie el
`elementId` dentro de `entity_id`**: el revisor añadió ese *fallback* en
`serialize_node` y las 960 pruebas de servidor, las de navegador y las de JS
siguieron verdes. Cuatro pruebas nuevas en `viewer/tests/test_serializers.py`
congelan ahora que `entity_id` **no cae** hacia `id` ni hacia `element_id`, que
el `elementId` crudo no aparece en **ninguno** de los cinco campos que el visor
indexa, y —como contrapeso, para que la regla no se cumpla devolviendo siempre
vacío— que `entity_id` sí se entrega tal cual cuando el proveedor lo da.

Lo que se congela no es «búsqueda de cliente», sino: **solo se puede encontrar
por ID aquello que la vista autorizada ya contiene**. El admin encuentra el nodo
secreto por su `entity_id`; el `viewer`, a quien no se le entregó, obtiene una
huella indistinguible de la de un id inventado.

#### La leyenda tiene red (corrección H2)

No había nada que comprobase que la leyenda sobrevive a la interacción: un
revisor la vació dentro de `selectNode` y la suite dio *220 passed, 0 failed*.
`test_seleccionar_un_nodo_no_altera_la_leyenda` congela que la leyenda depende
de **los datos cargados** y no de la selección: leyenda inicial → seleccionar A
→ seleccionar B → reiniciar vista, idéntica en filas, orden y colores reales.

El caso 3 **no puede aprobar por vacío**: antes de nada comprueba con un `admin`
que el nodo existe (11 nodos, `/api/entity/{id}` → 200) y que ese mismo buscador
**sí** lo encuentra; y comprueba que al `viewer` el backend le entrega 9 nodos y
le responde 404 al id. Si alguien borrase el nodo del fixture, la prueba se pone
roja en vez de aprobar. Verificado además por mutación: apuntar la constante a
un nodo visible (`Kimi`) pone la prueba en rojo.

Y las correcciones H1/H2/H4 se han verificado una a una por mutación:

| Mutación introducida | Prueba que enrojece | Canal que la delata |
|---|---|---|
| Mensaje solo para el nombre exacto del nodo `secret` en `#graph-status` | caso 3 | `estado_texto`, `estado_visible` (y de rebote `lienzo`) |
| `&hit=1` añadido a la URL tras `syncUrl()` | caso 3 | `url` |
| Contador de aristas alterado al buscar el secreto | caso 3 | `contador_aristas` |
| `network.moveTo({scale: 2.5})` al buscar el secreto | caso 3 | `encuadre`, `lienzo` |
| Vaciar la leyenda dentro de `selectNode` | `test_seleccionar_un_nodo_no_altera_la_leyenda` | leyenda ≠ inicial |
| Quitar `entity_id` del índice | caso 3 (control positivo) | el admin deja de encontrar el nodo por su id |
| Meter `node.id` (elementId) en el índice | `graph_core_spec.js` | «NO encuentra por el elementId de Neo4j» |

Una tercera prueba del carril D quedó invalidada **por mejora**:
`test_los_controles_del_grafo_estan_etiquetados` llevaba `xfail(strict=True)`
por el defecto ACC-02 y la V2 lo corrigió, produciendo un XPASS. Siguiendo la
doctrina del propio fichero (un XPASS estricto obliga a quitar la marca), se ha
retirado el `xfail` y la prueba pasa a proteger el arreglo en verde; el defecto
hermano de `/entities` sigue abierto como ACC-02b.

**4. Suite del visor** (tras integrar `main` d496c08, con M5b y el carril D)

```
$ cd viewer && python3 -m pytest -q
1115 passed, 19 skipped, 12 xfailed, 14 warnings in 271.44s   ·   exit 0

$ python3 -m pytest -q tests/                       # raíz del repo
196 passed, 2 skipped, 3 warnings in 3.35s   ·   exit 0
```

Los 19 saltados son **todos** de `tests/test_neo4j_integration_authz.py`, que
exige un Neo4j efímero (`NEO4J_TEST_URI`); vienen de `main` y no los toca este
carril. En `tests/browser` los saltados son **cero**.

El único fallo es `tests/test_auth_core.py::test_login_unknown_user_generic_message`
(`assert 403 in (401, 200)`) y **es previo a esta rama y ajeno a ella**: ya se
documentó en la primera ronda reproduciéndolo sobre el árbol limpio, y aislado
sigue pasando (`python3 -m pytest -q tests/test_auth_core.py` → `18 passed`).
Es contaminación entre tests, no una regresión de este carril. No se ha tocado.

**5. Suite raíz**

```
$ python3 -m pytest -q tests/
196 passed, 2 skipped, 3 warnings in 3.51s   ·   exit 0
```

### Control positivo: se repite el ataque del revisor

El revisor demostró el agujero de dos maneras. Se han repetido las dos, una cada
vez, y **ahora las dos dan rojo**. Ambas revertidas; no queda ningún marcador en
el árbol (`grep -rn MUTACION viewer/app viewer/tests` → nada).

**Ataque 1 — renombrar seis ids del DOM** en `graph.html`: `search-input`,
`fit-btn`, `reset-btn`, `reload-btn`, `labels-toggle`, `side-panel-close`, todos
con sufijo `-x`.

```
navegador : 5 failed, 2 passed, 10 errors   (246 s)   ROJO
pytest    : 4 failed, 42 passed                       ROJO
node      : 47 pasados, 0 fallidos                    VERDE (correcto: no ve el DOM)
```

Antes de este trabajo, ese mismo ataque dejaba la suite entera en verde con la
página en negro. Nótese que la parte de pytest solo caza cuatro de los seis: su
lista de ids no incluye `reload-btn` ni `side-panel-close`. Los seis los caza el
navegador.

**Ataque 2 — neutralizar `bindEvents()`** con `if (true) return;` en su primera
línea. Es el peor caso: la página *carga* y *dibuja*, pero ningún control
responde.

```
navegador : 8 failed, 9 passed   (119 s)   ROJO
```

Fallan exactamente las pruebas de interacción (buscar, centrar, resultados,
quitar filtros, reiniciar, cerrar ficha, móvil, expandir, 403/404) y siguen
verdes las que solo miran el arranque y el pintado, que es lo correcto: esa
mutación no rompe el arranque.

**Ataque 3 — quitar la ordenación por score** en `searchNodes`
(`if (a.score !== b.score) return a.score - b.score;` borrado), que es el
hallazgo H4: con la especificación anterior esto pasaba en verde.

```
node : 3 fallidos   ROJO
```

## Limitaciones (honestas)

- **La búsqueda por identificador queda inerte con el proveedor de Neo4j.** El
  índice del visor busca por `entity_id`, y `entity_id` solo existe si el
  proveedor lo entrega. La proyección de `neo4j_provider._node_to_dict` **no
  incluye hoy `entity_id`** (pone el `element_id` técnico en `id`, que
  deliberadamente *no* se indexa), así que contra Neo4j real teclear un
  identificador no encuentra nada: **la función descrita más arriba como
  entregada solo está viva con el proveedor `mock`**. Para activarla en
  producción hace falta añadir `entity_id` a esa proyección —zona congelada en
  este carril, no tocada—. Mientras tanto, el resultado de seguridad *sí* se
  mantiene con ambos proveedores: lo que no se entrega, no se encuentra.
- **La huella observable cubre diecisiete canales, no «todo».** La lista exacta
  está en la tabla de más arriba y en el docstring de `_huella_de_busqueda`.
  Fuera quedan, a sabiendas, los detalles de implementación y todo lo que no
  esté en el `<body>` de `/graph` (cabeceras, cookies, `localStorage`, tiempos).
- **La normalización del término borra cualquier fuga que se distinga *solo* por
  cómo se renderiza el término buscado.** Es el límite **intrínseco** de la
  técnica, no un descuido: para poder comparar dos búsquedas distintas hay que
  borrar antes el texto tecleado en todas sus formas (tal cual, minúsculas,
  *percent-encoded*, sin acentos). El precio es que si el visor mostrase el
  nombre **canónico** del nodo autorizado allí donde para un término inventado
  repite lo tecleado —distinta capitalización, acentos restituidos, forma
  canónica—, la sustitución taparía la diferencia y las dos huellas saldrían
  iguales. Un canal de ese tipo necesita una prueba dedicada que compare la
  forma **literal**; `_huella_de_busqueda` no puede detectarlo por construcción.
- **Los filtros trabajan sobre la ventana de `limit`**, no sobre el grafo entero.
  Con `limit=300` en un workspace de 5.000 nodos, filtrar por `Faction` enseña
  las facciones *de esos 300*, no todas. El contador lo hace visible
  (`visibles / totales`) pero el "totales" es el del lote, no el del grafo. Un
  filtrado global exigiría empujar los filtros al proveedor.
- **Las pruebas de navegador no cubren el lienzo entero.** Se ejercen 17
  recorridos, no todas las combinaciones; y como el grafo se pinta en `<canvas>`
  no hay un elemento DOM por nodo, así que "está centrado" se comprueba por el
  centroide de los píxeles de ese color. Eso obliga a elegir nodos de tipo único
  (aquí `Creature`) y el fixture falla en voz alta si deja de serlo, en vez de
  saltarse la prueba.
- **`limitSelect`, el plegado de filtros y los atajos `/`, `F` y `E` siguen sin
  prueba de navegador propia.** Están cubiertos indirectamente (si `bindEvents`
  no llega al final, todo lo demás cae), pero no de forma específica.
- **El proveedor sigue siendo `mock`.** La autenticación, las sesiones, los
  guardas de rol y el filtrado por política son los reales; el origen de datos
  del grafo, no. Un defecto que solo aparezca con Neo4j no se ve aquí.
- **En esta máquina Chromium necesita librerías del sistema que no están
  instaladas** (`libnss3`, `libatk`, `libasound2`, …) y no hay `sudo`. Se han
  resuelto extrayendo los `.deb` a `/tmp/pwroot` y ejecutando con
  `LD_LIBRARY_PATH`. **Eso es un apaño local, no forma parte del repositorio**:
  en CI el job `test-login-browser` usa `playwright install --with-deps chromium`
  y no necesita nada de esto. Cualquiera que repita las cifras en local tendrá
  que hacer lo mismo o los 17 casos se le saltarán.
- **El responsive se ha razonado por CSS, no medido en dispositivos.**
- **Expandir vecinos no tiene tope.** Expandir repetidamente sobre un nodo muy
  conectado puede degradar el rendimiento del lienzo. No hay límite ni aviso.
- **Sin persistencia de preferencias**: lo que no viaja en la URL se pierde al
  recargar.

## Dependencias

- **Externas: ninguna nueva.** `vis-network` ya estaba vendorizado y no se ha
  tocado. Un test comprueba que la página no referencia ningún `http(s)://`.
- **Node** solo como herramienta de test, no en tiempo de ejecución.
- **API consumida:** `GET /api/graph` y `GET /api/entities/{id}`. Ambos
  preexistentes y ambos servidos por el proveedor filtrado.

- **De otras ramas, sin modificar:** `viewer/tests/browser/{conftest,e2e_support}.py`
  de `test/viewer-browser-e2e-v1` (`67c1758`) y
  `.github/scripts/check_ci_config.py` + `.github/ci-fragments/test-graph-js.yml`
  de `chore/ci-test-branches-y-node` (`6c1a8c6`). Copiados byte a byte para que,
  cuando esas ramas se fusionen, no haya conflicto. **No se ha montado una
  segunda infraestructura de navegador.**

  Aviso para quien integre: los tests de grafo del carril D
  (`test_browser_navigation.py::test_la_busqueda_del_grafo_filtra_de_verdad` y
  `::test_seleccionar_un_nodo_abre_su_ficha_lateral`) esperan que buscar dispare
  una petición `/api/graph?...&q=...`. En la V2 la búsqueda es **de cliente** y
  ya no consulta al backend, así que esos dos casos habrá que reescribirlos al
  juntar los carriles. No están en esta rama, así que aquí no fallan.

### Verificado contra M5b (sin tocar la zona congelada)

Los dos puntos que en la primera ronda quedaron como hipótesis. **No se ha
implementado nada en `policies/`, `authz/` ni `neo4j_provider.py`** ni se ha
copiado lógica de autorización a la UI; lo que ha cambiado es que ahora están
medidos contra el contrato real.

1. **"Sin acceso" es indistinguible de "no existe" — y así se queda.**
   Ya no es una hipótesis: con M5b fusionado (`b6b0803`) se ha medido el
   contrato real contra el servidor, arrancando el visor con autenticación
   verdadera y consultando con dos roles. Para el nodo `n_culto_pozo_viejo`
   (`visibility: secret`):

   | ruta | `s9viewer` | `s9admin` |
   |---|---|---|
   | `GET /api/graph` | 9 nodos (no está) | 11 nodos (está) |
   | `GET /entities/n_culto_pozo_viejo` | **404** | 200 |
   | `GET /entities/id-que-no-existe` | **404** | 404 |

   Un nodo oculto y un id inexistente producen exactamente la misma respuesta,
   sin nada en el cuerpo que los separe. **La UI no intenta distinguirlos**:
   `errorKindForStatus` traduce 404 a `not_found` ("No se ha encontrado lo
   solicitado.") y reserva el vocabulario de acceso para 401/403, que vienen
   del guarda y no del contenido. Decir "no tienes acceso" ante un 404
   confirmaría que el elemento existe, que es justo la fuga que M5b evita.
   Cubierto por `test_la_ui_solo_habla_de_acceso_ante_401_y_403`,
   `test_una_entidad_oculta_y_una_inexistente_son_indistinguibles_para_la_ui` y,
   en navegador, `test_un_403_dice_falta_de_acceso_y_un_404_no`.
   **Sigue sin tocarse nada de `policies/`, `authz/` ni `neo4j_provider.py`.**

2. **Expandir vecinos puede quedarse corto, y no lo dice: es lo correcto.**
   `/api/entities/{id}` devuelve las relaciones que el proveedor filtrado
   autoriza. Si un vecino está oculto, la UI no dibuja nada y **no informa**.
   Antes el mensaje llevaba un número ("Se han añadido N…"); ahora es constante.
   Un indicador de completitud tendría que venir del backend como dato ya
   decidido por la política, y no se ha inventado en el cliente.

## Pendientes

- Decidir si los filtros deben empujarse al proveedor para operar sobre el grafo
  completo en lugar de sobre la ventana de `limit`.
- Reescribir los dos casos de grafo del carril D que asumen búsqueda de servidor
  (ver Dependencias) cuando los dos carriles se junten.
- Si algún día hace falta ver `visibility`/`knowledge_layer`, hacerlo en una
  vista diagnóstica separada y protegida para admin, no como pastilla normal.
- Cobertura de navegador para `limit`, el plegado de filtros y los atajos
  `/`, `F`, `E` de forma específica.
- El fallo previo `test_login_unknown_user_generic_message` en corrida completa
  (contaminación entre tests) no es de este carril; ver cifras en Tests.

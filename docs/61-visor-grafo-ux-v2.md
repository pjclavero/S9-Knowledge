# 61 — Visor de grafo: UX V2

Rama: `feat/viewer-graph-ux-v2` (desde `origin/main` @ `d169052`).
Carril A. Sin PR abierta a propósito.

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

**Los mensajes de error son de familia, no de código.** `errorMessageForStatus`
mapea el status HTTP a uno de siete mensajes fijos en castellano. El usuario no
ve el código, ni rutas, ni trazas, ni identificadores. Un test recorre todos los
mensajes y falla si alguno contiene una barra, un número de tres cifras o
palabras como `Traceback` o `neo4j`.

**Expandir vecinos reutiliza `/api/entities/{id}`**, que ya pasa por el proveedor
filtrado. No se ha creado ningún endpoint nuevo, y por tanto no hay una segunda
puerta por la que puedan salir datos.

**Se ha quitado de la ficha lateral el pill de visibilidad y la fila de "Capa de
conocimiento"** que el panel antiguo pintaba. Son etiquetas del modelo de
visibilidad, que es exactamente la zona que este carril no toca; mostrarlas
invitaba a que la UI empezara a razonar sobre ellas. El backend sigue enviando
esos campos y las fichas completas (`/entities/{id}`) siguen mostrando lo que
corresponda: no se ha modificado nada del backend.

## Ficheros

| Fichero | Cambio |
|---|---|
| `viewer/app/static/js/graph-core.js` | **Nuevo.** Lógica pura, ~380 líneas |
| `viewer/app/static/js/graph.js` | Reescrito: capa de UI |
| `viewer/app/templates/graph.html` | Reescrito: layout de tres columnas |
| `viewer/app/static/css/app.css` | Bloque de grafo sustituido (`/* Graph page layout (UX V2) */`) |
| `viewer/tests/test_graph_ux_v2.py` | **Nuevo.** 46 casos |
| `viewer/tests/js/graph_core_spec.js` | **Nuevo.** 38 casos de lógica pura |

`viewer/app/main.py` no ha necesitado cambios: la ruta `/graph` ya pasaba
`workspace` y `graph_limit`, que es todo lo que la plantilla nueva consume.

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

En pantallas ≤900 px los dos paneles pasan a superponerse y la ficha entra por
la derecha con el botón de cierre visible.

## Tests

Ejecutados en el worktree, en este orden.

**1. Especificación JS de la lógica pura**

```
$ node viewer/tests/js/graph_core_spec.js
38 pasados, 0 fallidos   ·   exit 0
```

Cubre: búsqueda (prefijo, tildes/macrones, alias, orden por calidad de
coincidencia, sin coincidencias, query vacía, límite), filtros (entidad,
relación, combinado, con búsqueda, tipo inexistente, nodos sueltos, no mutación
del original), leyenda y recuentos, estados (cargando / vacío / sin resultados /
listo / error), errores saneados, estado de URL (ida y vuelta, lista blanca,
límite inválido) y expansión de vecinos (merge sin duplicados).

**2. Tests nuevos de la página**

```
$ cd viewer && python3 -m pytest -q tests/test_graph_ux_v2.py
46 passed, 3 warnings in 1.89s   ·   exit 0
```

**3. Suite del visor**

```
$ cd viewer && python3 -m pytest -q
1 failed, 720 passed, 24 skipped, 13 warnings in 43.27s   ·   exit 1
```

El fallo es `tests/test_auth_core.py::test_login_unknown_user_generic_message`
(`assert 403 in (401, 200)`) y **es previo a esta rama**: se reprodujo con
`git stash -u` sobre el árbol limpio de `origin/main` (`1 failed, 674 passed,
24 skipped`, 54,42 s). Aislado pasa (`18 passed`), así que es contaminación
entre tests, no una regresión de este carril. No se ha tocado.

Antes de esta rama: 674 pasados. Después: 720 pasados. +46, que son exactamente
los del fichero nuevo.

**4. Suite raíz**

```
$ python3 -m pytest -q tests/
196 passed, 2 skipped, 3 warnings in 19.63s   ·   exit 0
```

### Control positivo (mutación deliberada)

Se rompieron dos cosas, una cada vez, y se comprobó que los tests se ponían en
rojo. Ambas revertidas después; no queda ningún marcador `MUTACIÓN` en el árbol.

**Mutación 1 — filtro por tipo de relación.** En `filterGraph`, se neutralizó
la comprobación del conjunto de tipos de relación
(`if (false && !inSet(relSet, e.type)) return false;`).

```
36 pasados, 2 fallidos
FAIL - filtro por tipo de relación: descarta las relaciones de otro tipo
FAIL - filtro: ocultar nodos sueltos elimina los que quedan sin relación
$ pytest -q tests/test_graph_ux_v2.py → 1 failed, 45 passed (exit 1)
```

**Mutación 2 — búsqueda por alias.** En `searchNodes`, se anuló la rama que
busca en el "pajar" del nodo (`else if (false) score = 3;`).

```
37 pasados, 1 fallidos
FAIL - búsqueda: encuentra por alias
```

Tras revertir ambas: `38 pasados, 0 fallidos`.

## Limitaciones (honestas)

- **Los filtros trabajan sobre la ventana de `limit`**, no sobre el grafo entero.
  Con `limit=300` en un workspace de 5.000 nodos, filtrar por `Faction` enseña
  las facciones *de esos 300*, no todas. El contador lo hace visible
  (`visibles / totales`) pero el "totales" es el del lote, no el del grafo. Un
  filtrado global exigiría empujar los filtros al proveedor.
- **No hay tests de navegador.** `graph.js` (el pegamento con el DOM y con
  `vis-network`) no está cubierto por ninguna aserción de comportamiento: solo
  se verifica que la plantilla contiene los identificadores que ese código
  espera y que el fichero pasa `node --check`. Lo probado de verdad es
  `graph-core.js`. Un fallo de cableado (un listener mal enganchado) pasaría los
  tests. Haría falta Playwright o jsdom, que no están en el proyecto.
- **La página nueva no se ha visto en un navegador real** en esta sesión: no hay
  entorno gráfico disponible. Es una verificación pendiente.
- **El puente a Node se salta si no hay `node`** en la máquina
  (`pytest.mark.skipif`). Si el CI no tuviera Node, los 38 casos de lógica pura
  se saltarían en silencio y la suite seguiría verde. Aquí Node 20.19.2 está
  presente y se ejecutan.
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

### Dependencias detectadas con M5b (no implementadas)

Durante la auditoría aparecieron dos puntos que tocan la zona congelada
(`policies/`, `authz/`, `neo4j_provider.py`, PRs #152/#153). **No se ha
implementado ninguno** ni se ha copiado lógica de autorización a la UI.

1. **El estado "sin acceso" es indistinguible de "no existe".** La UI puede
   mostrar el mensaje correcto si recibe 401 o 403, y así lo hace. Pero cuando
   la política oculta un nodo, `/api/graph` simplemente no lo devuelve y
   `/api/entities/{id}` responde 404. Desde el visor, "esto no te toca ver" y
   "esto no existe" son el mismo hecho observable. Es probablemente **lo
   correcto** (distinguirlos filtraría la existencia del nodo), pero significa
   que el estado "sin acceso" solo se pinta de verdad cuando cae la sesión o
   falta el rol, no cuando la política oculta contenido concreto. *Qué haría
   falta:* una decisión explícita del dueño de M5b sobre si algún caso debe
   señalarse como "oculto" en vez de "inexistente". **No lo he tocado.**

2. **Expandir vecinos puede quedarse corto sin decirlo.** `/api/entities/{id}`
   devuelve las relaciones que el proveedor filtrado autoriza. Si un vecino está
   oculto, la relación puede llegar con `other_entity: null` y la UI no dibuja
   nada. No se avisa —"hay más, pero no para ti" sería precisamente la fuga que
   el modelo evita—, pero el usuario puede creer que expandió del todo. *Qué
   haría falta:* si M5b quisiera un indicador de completitud, tendría que venir
   del backend como un dato ya decidido por la política. **No lo he inventado
   en el cliente.**

Adicionalmente, la ficha lateral ha dejado de pintar los pills de `visibility` y
`knowledge_layer` (ver Decisiones): esos campos son vocabulario de M5b y su
presentación debería decidirla quien cierre ese modelo.

## Pendientes

- Verificación visual en navegador real (móvil y escritorio).
- Decidir si los filtros deben empujarse al proveedor para operar sobre el grafo
  completo en lugar de sobre la ventana de `limit`.
- Cobertura de la capa DOM (Playwright o jsdom) si el proyecto quiere pagar esa
  dependencia.
- Respuesta del dueño de M5b a los dos puntos de la sección anterior.
- El fallo previo `test_login_unknown_user_generic_message` en corrida completa
  (contaminación entre tests) sigue ahí y no es de este carril.

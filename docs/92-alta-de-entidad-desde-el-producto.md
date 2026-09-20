# 92 · El alta de entidad, decidida desde el producto

## El defecto, medido

El recorrido `revisión -> apply` terminaba dejando en el grafo `V3Assertion`,
`V3Evidence` y `V3Source`, y **ninguna `:Entity`**. El panel ofrecía entonces un
enlace al resultado que acababa en **404**, porque el ámbito del lector se
deriva de las entidades: sin ninguna, el workspace no aparecía en
`workspaces()`.

La causalidad está demostrada por intervención, no deducida: inyectando **una
sola** `:Entity` con `entity_id`, el workspace apareció y el mismo destino pasó
de 404 a 200.

## Lo que NO era

No era una tubería accidentalmente desconectada. La ausencia de `CREATE_ENTITY`
en el plan sellado era una **decisión existente y documentada**, en la cabecera
de `review_plan.py`:

> Un extremo `pending_creation` exige un `CREATE_ENTITY`, y eso sólo lo autoriza
> un alta aprobada (`pipeline/entity_decisions.py`): aprobar una propuesta de
> revisión NO es aprobar el alta de una entidad, y esa frontera la cruza una
> persona, no este módulo.

Lo que faltaba era la **segunda decisión**, que hasta aquí sólo se podía tomar
desde la línea de comandos (`ingest_cli --revisar --aprobar-alta <id>`) y de una
en una.

## Lo que este corte añade, pieza a pieza

### 1. La ranura del sobre (`entity_altas`)

`entity_decisions.reconcile` es la definición canónica de «esto es un alta», y
por el camino de la cola de trabajos **no se invocaba nunca**: sólo lo llamaba
el CLI. La corrida hacía la pregunta y tiraba la respuesta.

Ahora `review_export.run_entity_altas` la llama con los mismos insumos que le
pasa el CLI —las filas de resolución (`ingest_report.resolution_rows`, extraída
para que haya **una sola** derivación), lo observado en el snapshot, las
superficies de las menciones y el catálogo de identidades— y publica sus
`CREATE_ENTITY_REQUIRED` en el sobre del paquete, bajo `plan_context`.

Viaja como **pregunta**: ninguna entrada lleva campo de aprobación. Y
`entity_type` puede salir ausente (en un grafo nuevo el resolutor no tiene con
qué inferirlo): se publica como ausencia, no se rellena.

La **ausencia de la clave** significa «esta corrida no publicó altas» —una
corrida anterior a este corte— y se distingue de un diccionario vacío.

### 2. La autoridad canónica

La decisión vive en la tabla `entity_altas` del **almacén de revisión**, que ya
es la autoridad de las decisiones de propuesta y de los planes sellados. No en
un fichero aparte, por dos razones:

- reabriría el problema de las dos verdades que el Corte 2 cerró;
- un alta aprobada **tiene que invalidar el plan sellado**, y eso sólo es
  atómico si las dos cosas se tocan en la misma transacción.

La aprobación es idempotente **por la base** (clave primaria
`(workspace, job_id, entity_id)`), conserva el autor y el momento de la primera,
y deja evento `ENTITY_ALTA_APPROVED` en la cadena encadenada del workspace.

### 3. La pantalla

`GET /panel/operations/altas?trabajo=<corrida>`: la entidad, su tipo (o su
ausencia declarada, que se pide), sus alias, y el **fragmento soportante** de
cada propuesta de esa corrida que la nombra.

- La corrida se resuelve **contra la cola y con ámbito**; el workspace sale de
  ahí, nunca del query string.
- El filtro de visibilidad se aplica **en el servidor, sobre las propuestas**,
  antes de componer nada: lo que la política oculta no llega al navegador.
- **Un formulario por entidad.** No hay «aprobar todas», igual que en el CLI.

La escritura está declarada en el chasis como capacidad `alta_de_entidad`
(`POST /panel/operations/altas`, rol `admin`, auditada).

### 4. El `CREATE_ENTITY`, con tres condiciones

`seal_review_plan` emite un alta si y sólo si:

1. una persona la **aprobó**, en la autoridad;
2. **esta corrida la declaró** en su sobre (es lo que hace que un id de otro
   workspace, de otra corrida o inventado no se cuele);
3. alguna afirmación **que entra en el plan la menciona** (crear un nodo suelto
   que nada sostiene sería escribir algo que nadie revisó).

Lo que no entra se dice con código enumerado y cerrado por construcción
(`ALTA_CODES`): `ALTA_NOT_DECLARED_IN_RUN`, `ALTA_NOT_REFERENCED`,
`ALTA_WITHOUT_TYPE`.

## Ningún contrato congelado se versiona

`CREATE_ENTITY` ya estaba en el enum del `graph-mutation-plan-v3.schema.json`,
el planificador del motor ya lo emitía por el camino del CLI, y el executor y el
validador ya sabían tratarlo. Lo que este corte añade viaja en `plan_context`,
que es el sobre interno del paquete de propuestas, y en una tabla nueva del
almacén de revisión. El plan sellado se valida contra el schema de `main`, y hay
una prueba que lo **comprueba** en vez de afirmarlo.

## Lo que este corte NO hace, dicho en voz alta

- **No proyecta relaciones sobre la entidad recién creada.** Las altas no están
  en el snapshot de la corrida, así que no tienen ancla, y `_proyeccion` sigue
  omitiendo con `PROJECTION_NO_ANCHOR`. La afirmación entra; su arista, no. La
  segunda ingesta de la misma fuente sí puede proyectarla, porque entonces la
  entidad ya está observada.
- **No unifica el CLI con la autoridad del visor.** Son dos superficies y se
  declara como deuda en la cabecera de `ingest_cli.py`: el motor no puede leer
  el almacén del visor sin invertir la dirección de dependencia, y eso es un
  carril aparte.
- **No está ejercido contra infraestructura real.** Que el nodo quede escrito en
  un Neo4j de verdad lo cubre el recorrido con grafo, que se salta sin
  `S9K_WRITER_NEO4J_REAL=1`.

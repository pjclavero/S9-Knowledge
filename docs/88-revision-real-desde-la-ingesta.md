# 88 · La ingesta del panel produce revisión de verdad

**Slice 2 · Corte 3.** Base: `origin/main` = `86e4efae`.

## El defecto

Medido ejecutando, no leyendo:

```
job complete · episodios 7 · menciones 10 · claims 5
por_veredicto {ABSTAIN: 2, ACCEPT: 1, REVIEW: 2}
PROPUESTAS ESCRITAS POR LA INGESTA DEL PANEL: []
/panel/review -> «Sin propuestas visibles»
```

`REVIEW = 2` en el informe y **cero propuestas revisables**. El operador ve
`complete`, concluye que no hay nada que revisar y **da por buena una ingesta
cuyas ambigüedades nunca vio**.

## La causa, con nombre

`review_proposals_dir` existía **sólo** como parámetro de `Pipeline.run`
(`pipeline.py:598,617,622`). No aparecía ni una vez en `ingest_cli.run_ingest`
ni en `jobs/handlers/ingest_v3.py` — la cadena que el panel usa. Los únicos
escritores de propuestas eran `scripts/dev/gen_review_proposals.py` (script de
desarrollo, fuera de la suite por su propia docstring) y `pipeline/runner.py`,
**un CLI distinto del que el panel invoca**.

Es **el mismo patrón del Corte 2 por tercera vez**: una capacidad completa y
**sin llamador** en el camino del producto. Desde el código se lee igual que
una viva.

## El cambio

```
panel -> ingest_v3 -> run_ingest -> Pipeline.run(review_proposals_dir=...)
      -> proposals persistidas -> /panel/review
```

- **`data-engine/app/knowledge_v3/pipeline/ingest_cli.py`** — `run_ingest`
  acepta `review_proposals_dir` y **siempre** se lo pasa a `Pipeline.run`. Era
  el llamador que faltaba. El handler de la cola no cambia ni una línea: no
  necesita saber nada de rutas.
- **`data-engine/app/knowledge_v3/review_paths.py`** (nuevo) — el resolvedor.

## Un único resolvedor canónico

> Si hay **dos derivaciones de una ruta, hay dos verdades.**

Al enchufar el llamador aparecía el riesgo de siempre: el motor derivando una
ruta y `default_proposals_dir()` del visor derivando otra. El síntoma habría
sido **idéntico al defecto que se acababa de arreglar** —motor escribiendo en
una carpeta, visor mirando otra, ambos «funcionando»— y sin un solo error.

La resolución vive ahora en `knowledge_v3.review_paths.default_proposals_dir` y
**sólo ahí**. `app.services.v3_review.default_proposals_dir` **delega**; no
deriva. Falla cerrado: sin motor montado no inventa una ruta de repuesto,
porque una ruta de repuesto *es* la segunda verdad.

**Dirección de la importación.** Motor → visor no se puede: ambos publican un
paquete `app` distinto (ya declarado en `review_decisions.py`). Visor → motor sí,
y ya se hacía: es el puente de `viewer/app/jobs_client.py` hacia
`jobs.job_store`. Por eso el resolvedor vive en el motor y lo importa el visor.

Que sólo haya uno **no se promete en prosa**: un caso recorre por AST todo
`viewer/app` y `data-engine/app` y exige que el literal
`S9K_V3_REVIEW_PROPOSALS_DIR` **no aparezca en ningún otro módulo del
producto**. Y otro caso comprueba que ambos lados resuelven la MISMA ruta, con
y sin variable declarada: que el nombre aparezca una sola vez no basta.

## El invariante de despliegue

`S9K_V3_REVIEW_PROPOSALS_DIR` la comparten **escritor** (el worker de la cola) y
**lector** (el visor). Queda declarada en **`deploy/README.md`**, que es donde
vive la documentación de despliegue, con las tres reglas: declararla en los dos
lados con el mismo valor, o en ninguno; declararla **en uno solo** es el peor
caso, porque el defecto del otro lado es una ruta válida y todo parece
funcionar.

Es la misma exigencia que el Corte 2 impuso a `review.sqlite3`.

## La prueba insignia

`viewer/tests/test_panel_review_cola_desde_ingesta.py`

```
almacén de propuestas VACÍO al empezar (comprobado, no supuesto)
 -> ingesta lanzada DESDE EL PANEL (formulario y CSRF reales, cola real,
    worker real)
 -> fuente que produce REVIEW > 0 (se afirma leyendo el informe del job)
 -> esperar a complete
 -> ESAS propuestas, de ESA ejecución y ESE workspace, en /panel/review
```

No puede ponerse verde por basura anterior: el almacén es `tmp_path` y se
comprueba vacío, y lo que se afirma no es un recuento —«hay algún fichero» se
pondría verde con restos ajenos— sino la **identidad**: cada `proposal_id` que
escribió esta ejecución tiene que aparecer en la pantalla.

## Los dos defectos de lenguaje

Entran porque **sin ellos el paso 5 no es usable**, no como tercer frente.

### `REASON_LABELS`

Medido: mapeaba 7 códigos y **ninguno de los que el motor emite de verdad**. El
**100 % de los motivos reales** caía al código crudo, y además duplicado
(`CESSATION_WITHOUT_ACTIVE_ASSERTION: CESSATION_WITHOUT_ACTIVE_ASSERTION`).

Ahora la tabla cubre **los 82 códigos emitibles**, en castellano. La cobertura
no se vigila a ojo: `engine.findings.emittable_reason_codes()` **deriva** el
universo del catálogo del motor —invoca cada entrada, recoge su `code` y su
`canonical`, y suma los dos canónicos de ACCEPT que `reason_codes_for` añade sin
hallazgo detrás— y un caso exige que emitibles y presentables sean **el mismo
conjunto**, en los dos sentidos: un código sin etiqueta sería un motivo crudo, y
una etiqueta sin código es texto muerto que aparenta cobertura.

Derivar es el punto. Una lista copiada a mano es exactamente cómo se
desalinearon.

### Job `failed`

Medido: con el job en `failed` la pantalla mostraba **primero** «Se ha
solicitado la ingesta. El trabajo ya está en la cola.» y **después** `estado
failed`. El texto tranquilizador iba delante, y es el que se lee.

El acuse de encolado sólo es cierto **mientras el trabajo está en la cola**: en
cuanto hay desenlace, calla, y habla `_resultado_del_trabajo`, que da **estado y
causa como una sola presentación**. El detalle técnico sigue fuera de la UI: el
`error_message` se parte y sólo sobrevive el código estable, traducido por el
catálogo cerrado.

Los estados terminales se declaran **una vez** (`ESTADOS_TERMINALES`) porque los
usan las dos funciones; dos listas separadas reabrirían el defecto en cuanto una
añadiese un estado y la otra no.

Hay un **control del control**: un caso comprueba que con el trabajo aún
pendiente el acuse legítimo **sigue apareciendo**. Sin él, silenciar el acuse
siempre dejaría el caso anterior verde por la razón equivocada.

## Qué NO hace este corte

`/panel/review` **sigue siendo sólo-lectura por diseño declarado**. Este corte
sólo hace que tenga algo que mostrar; **decidir sigue en `/v3/review`** hasta el
corte que lo absorba. No entran `apply`, `rollback`, rediseño visual, consola
nueva, refactor de `review` ni gates nuevos.

## El contrato de escritura del chasis

La capacidad `ingesta_de_fuente` de `chassis.WRITE_CAPABILITIES` declara ahora
que el trabajo, al correr, deja una escritura **fuera del grafo**: la cola de
revisión. Se declara aunque la haga el worker y no la petición, porque es una
escritura de esa capacidad.

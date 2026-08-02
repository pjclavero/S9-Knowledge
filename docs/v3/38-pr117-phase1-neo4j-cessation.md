# PR117 — fase 1: Neo4j e idempotencia de cesaciones

Base: `55daf6cdafefbbdd5d6735e13e97d88e4c5d20a0`.

La validación se ejecutó realmente en VM105 con Docker 29.5.2 y un contenedor
`neo4j:5.26-community` efímero, ligado a un puerto aleatorio de loopback, sin
volúmenes ni credenciales externas. Neo4j productivo no fue usado.

## Esquema e idempotencia

El módulo `knowledge_v3.writer.schema` versiona un bootstrap explícito para la
restricción única de `(workspace, idempotency_key)` en
`V3AppliedOperation`. El fixture real la crea antes de ejecutar. La marca y la
mutación siguen dentro de la misma transacción; Neo4j es la autoridad y el
almacén local solo una caché.

ID-01..ID-08 cubren primera aplicación, replay, conflicto, fallos antes y
durante la mutación, caída tras commit, concurrencia e aislamiento. El gate
observado fue: cero duplicados, marcas huérfanas, mutaciones sin marca y
escrituras cruzadas.

## Cesación

La regresión de operaciones vacías era un defecto del test. El escenario
declaraba una cesación “anclada”, pero construía un pipeline nuevo cuyo snapshot
tenía cero positivas activas. El resultado correcto es `REVIEW`, con
`EXTRACTOR_REQUESTED_REVIEW` y `CESSATION_WITHOUT_ACTIVE_ASSERTION`, y cero
operaciones efectivas.

El control con una positiva activa demuestra que el motor conserva
`supersedes`, pero la política graduada mantiene la autoridad en revisión y
expone `CESSATION_SHADOW_PLAN`; no se fuerza un plan aplicable. Por separado,
el writer real demuestra el cierre histórico, la creación negativa, el replay
idempotente y los rollbacks por hash y versión.

## Gates y límites

Puerta 3: CONFORME. Puerta 4: NO CONFORME. Puerta 5: CONFORME. Puerta 6:
NO CONFORME. Puerta 6B: CONFORME. Puerta 7: validada en esta fase contra Neo4j
efímero. No se ejecutó held-out ni se realizó despliegue productivo.

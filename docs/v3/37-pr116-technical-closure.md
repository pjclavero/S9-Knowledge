# PR #116 — cierre técnico

## Base y alcance

Base auditada: `ee71dce374efc040003003e7d684254162f37db5`, rama
`integration/v3-final-core-validation`. La rama de trabajo es
`fix/pr116-technical-closure`.

## Correcciones

- La exportación usa `EngineResult.shadow_decisions`, indexado por `claim_id`.
- El panel diferencia decisión efectiva/sombra, findings, operaciones
  hipotéticas, proveedor y modelo.
- `has_semantic_origin()` usa pasos y familias declaradas, traza y metadata del
  reconciliador; nunca infiere por nombre de modelo.
- `proposal_id` identifica workspace/source/episode/claim y `proposal_hash`
  identifica la versión canónica mostrada.
- Paquetes idénticos se deduplican conservando procedencias; versiones
  diferentes mantienen una sola activa y activan `STALE_REVIEW`.
- SQLite WAL almacena propuestas/versiones, decisiones, auditoría, outbox y
  candidatos. `request_id` y candidatos tienen unicidad transaccional.
- Decisión y solicitud de candidato se confirman en una transacción; el
  proyector es reintentable y sólo crea estado `PROPOSED`.
- El writer reclama `V3AppliedOperation` dentro de la misma transacción Neo4j.
  Neo4j es autoridad; `AppliedKeyStore` queda como caché compatible.

## Tests

Suite combinada: **5193 passed, 36 skipped, 3 xfailed, 0 failed** en 112.41 s.
Seeds 1, 7, 42 y 123: 10 tests deterministas verdes por seed.
Ollama live (`qwen2.5:7b`): 58 passed. NVIDIA live: 29 passed.

Skips: Neo4j efímero (socket Docker sin permisos), Tesseract, Playwright,
spaCy/Stanza y pruebas live no activadas en la corrida combinada. Las pruebas
live Ollama/NVIDIA se ejecutaron aparte.

## Servicios y panel

`uvicorn` temporal escuchó sólo en `127.0.0.1:8080`. `/v3/review` y
`/v3/review/glossary-candidates` respondieron 200. El proceso se detuvo al
terminar. No se usaron servicios productivos.

## Gates

| Gate | Estado |
|---|---|
| Puerta 3 | CONFORME |
| Puerta 4 | NO CONFORME |
| Puerta 5 | CONFORME |
| Puerta 6 | NO CONFORME |
| Puerta 6B | CONFORME |
| Puerta 7 | BLOQUEADO |

Puerta 4 conserva alcance 0.875 y recall SIMPLE 0.10. Puerta 6 conserva el
hallazgo de generalización 0.231. No se ejecutó held-out ni se alteraron
umbrales/expected. Neo4j real nuevo no pudo validarse por permisos de Docker y
la prueba activada de cesación mostró operaciones vacías.

## Revisión y glosario

Artefactos conservan 2 pendientes, 0 decisiones persistentes y 0 candidatos
persistentes. Los tests de corrección generaron candidatos `PROPOSED` en
entornos temporales y verificaron que el glosario efectivo no muta.

## Dictamen

**NO CONFORME — QUEDAN DEFECTOS TÉCNICOS**. La implementación corrige los
defectos revisables en código, pero puerta 7 no está validada contra Neo4j real
y las puertas funcionales 4 y 6 siguen rojas.

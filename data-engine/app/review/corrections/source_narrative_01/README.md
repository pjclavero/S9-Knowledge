# Corrección de datos — review de `source_narrative_01` (workspace `leyenda`)

Corrige un **conflicto de datos** detectado por el dry-run conectado del writer
seguro (PR #25) contra el Neo4j real. **No es un defecto del writer**: el writer
lo detectó correctamente y abortaría el lote (`safe_to_write=false`).

## Conflicto original
`review_recommendations.json` (informe original, **intacto**, SHA-256
`5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540`) contenía
**dos decisiones en conflicto** para la misma entidad `Clan Escorpión`, que ya
existe en el grafo (match exacto):

| candidate_id | type | recomendación | motivo |
|---|---|---|---|
| `6a36f2884a46` | Clan | REJECT | duplicado con tipo inválido 'Clan' |
| `482f601e5b7a` | Faction | APPROVE_UNCHANGED | conf=0.92 |

El dry-run real las clasificó como **1 CONFLICT_EXISTING** (APPROVE_UNCHANGED de una
entidad preexistente).

## Corrección (versión superseding v2)
Generada con `supersede_review.py` (transformación **explícita y revisable**, no
edición manual). El original **no se modifica**.

- Archivo: `review_recommendations.v2.json`
- `supersedes_sha256`: `5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540`
- `new_sha256`: `f8006b982678ccded6858783da18c12b14c538e3cdbfd69773cc83c8cd481b59`
- `Clan Escorpión`: consolidado en **UNA** decisión activa
  `DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE` (nunca CREATE_NEW; sin SET
  sobre el nodo existente; procedencia intacta). Historial de las dos decisiones
  originales conservado en `consolidated_from`.
- `Akodo Toturi` (USE_EXISTING), `clan León`, `clan Grulla` (EDIT): revisados
  **sin cambio automático** de su recomendación (`reviewed=manual`).
- Relaciones: **excluidas** (5 propuestas, 0 autorizadas).

## Dry-run conectado real de v2 (solo lectura, Neo4j productivo)
```
Neo4j antes:  199 nodos / 140 relaciones
Neo4j después: 199 nodos / 140 relaciones   (invariante)
WOULD_CREATE: 4   USE_EXISTING_SAFE: 1   CONFLICT_EXISTING: 0
AMBIGUOUS_EXISTING: 0   DEFERRED: 4   REJECTED: 0
relaciones autorizadas: 0   escrituras: 0   execute_write: no invocado
```

## Estado
La **primera ingesta sigue SIN autorizar**, aunque el dry-run de v2 esté limpio.
Regenerar por el flujo de revisión oficial antes de cualquier ingesta real.

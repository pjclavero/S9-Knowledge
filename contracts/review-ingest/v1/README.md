# Contratos review/ingest v1

**Fuente ÚNICA y compartida** de los contratos entre el motor (`data-engine`) y el
visor (`viewer`). Ninguno de los dos componentes duplica estos esquemas: ambos
leen los `*.schema.json` de este directorio y validan con
[`validator.py`](validator.py).

## Objetivo

Definir, versionar y validar los documentos que atraviesan el flujo de revisión
humana asistida e ingesta controlada, **sin** incluir lógica de autoaprobación,
rutas FastAPI, plantillas, JavaScript ni escritura en SQLite/Neo4j. Es un PR de
contratos: solo esquemas, ejemplos, validador y tests.

## Documentos (v1)

| document_type | schema | propósito |
|---|---|---|
| `review-candidate` | `review-candidate-v1.schema.json` | candidato producido por el motor a partir de un segmento |
| `review-decision` | `review-decision-v1.schema.json` | decisión inmutable sobre un candidato (control optimista) |
| `review-source-summary` | `review-source-summary-v1.schema.json` | resumen por fuente para el panel |
| `ingest-plan` | `ingest-plan-v1.schema.json` | plan determinista; autorización separada |
| `ingest-plan-result` | `ingest-plan-result-v1.schema.json` | resultado de DRY_RUN / APPLY |
| `review-audit-event` | `review-audit-event-v1.schema.json` | evento de auditoría append-only |

`_common-v1.schema.json` contiene los `$defs` compartidos (envelope, hash,
procedencia, enums de estados/acciones/resultados). No es un tipo de documento.

## Consumidores

- **Motor** (`data-engine`): produce `review-candidate`, `review-source-summary`,
  `ingest-plan` e `ingest-plan-result`; consume `review-decision`.
- **Visor** (`viewer`): consume candidatos/summary/plan; produce `review-decision`
  y `review-audit-event`; nunca escribe en Neo4j desde el panel.

## Versionado y compatibilidad

- `schema_version` semántica `1.x.y`.
- Los consumidores **rechazan una versión mayor desconocida** (forward-safe).
- `additionalProperties=false` en la raíz de todos los documentos. La
  extensibilidad libre se confina a los bloques `attributes` y `metadata`.

## Estados (catálogo único, sin strings libres)

- **Candidato:** PENDING · AUTO_APPROVABLE · REQUIRES_REVIEW · APPROVED · EDITED · USE_EXISTING · DEFERRED · CONFLICT · REJECTED
- **Plan:** DRAFT · READY_TO_APPLY · BLOCKED · APPLIED · FAILED · SUPERSEDED
- **Acción de revisión:** APPROVE · EDIT · USE_EXISTING · DEFER · REJECT · RESOLVE_CONFLICT
- **Resultado dry-run:** WOULD_CREATE · WOULD_UPDATE · WOULD_LINK_EXISTING · DEFERRED · CONFLICT_EXISTING · AMBIGUOUS · BLOCKED · NO_OP

## Idempotencia y determinismo

- Identificadores estables, no dependientes del orden de arrays, sin información
  sensible, con el `workspace` como espacio de nombres que evita colisiones.
- Cada operación del plan lleva `operation_id` único e `idempotency_key` única.
- Los hashes siempre declaran algoritmo (`{algorithm, value}`); no se aceptan
  hashes sin algoritmo. Fechas en UTC ISO-8601 (terminadas en `Z`).

## Control de concurrencia

- `review-decision` incluye `expected_candidate_hash`: si el candidato cambió, la
  decisión es obsoleta (CONFLICT / STALE_REVIEW) y **no** se sobrescribe en
  silencio. Las revisiones son inmutables por `review_generation`.

## Separación plan / autorización

- La **creación** de un `ingest-plan` **no autoriza** su aplicación.
- `authorization.granted=true` es imposible sin `operator_id`, `authorized_at` y
  `authorization_hash` (impuesto por el schema).
- `EXTERNAL_AI_SHADOW` solo puede emitir `DEFER` (recomendación): nunca APPROVED,
  EDITED, USE_EXISTING ni READY_TO_APPLY.
- En v1 las relaciones pueden quedar deshabilitadas (`relations_enabled=false`).
- `PARTIAL` está prohibido para `APPLY` salvo rollback transaccional demostrado.

## Prohibición de escritura productiva

Estos contratos no escriben en Neo4j ni en SQLite y no autorizan ingesta. La
primera ingesta real sigue requiriendo revisión humana y autorización explícita
del operador. Los tests usan SQLite temporal, fixtures anonimizadas y
directorios temporales; nunca datos ni endpoints de producción.

## Validación

```bash
python -m pytest contracts/review-ingest/v1/tests/ -q
```

`validator.py` combina validación JSON Schema con comprobaciones semánticas que
el esquema no expresa (suma de conteos = total, unicidad de IDs, ausencia de
secretos en `metadata`/`attributes`, coherencia de `ready_to_plan`).

# Data Review y Aprobación de Ingesta — S9 Knowledge

## Filosofía: revisión humana mínima

El humano revisa **solo lo dudoso**, no todo. La autoaprobación segura es la norma; `needs_review` es la excepción.

> **Prioridad 2.1 — revisión humana total:** con `S9K_REVIEW_POLICY=full_human_review` (docs/37) TODO candidato va a `needs_review` (0 autoaprobados) y `ingest-approved` rechaza sin escribir cualquier payload sin procedencia de revisión humana (`reviewed_by`/`reviewed_at`). CLI mínima `review_manual.py` (approve/reject/edit/use-existing) con log append-only. Modo previsto para la primera ingesta controlada.

El pipeline clasifica automáticamente la transcripción, extrae entidades/relaciones, las valida contra el schema RPG y las resuelve contra Neo4j. Solo los candidatos con ambigüedad real (varios matches, confianza media, tipo contradictorio) llegan a la cola de revisión humana.

## Cadena de evidencia

```
transcript.md  →  candidates.json  →  approved_payload.json  →  Neo4j
(fuente)          (candidato)          (aprobado)               (consolidado)
```

## Flujo del pipeline

```
segment → classify → extract → validate → resolve → decide → approved_writer
```

1. **segment** — Divide la transcripción en bloques de ~4 min con timestamps estables (`<source_id>_seg_0001`).
2. **classify** — Asigna categoría narrativa (lore, combat, travel, dialogue, intro_outro, noise, table_talk, …) y decide `should_extract`.
3. **extract** — Extrae candidatos de los segmentos extractables. Usa heurísticas + glosario (glossary.db). Sin LLM obligatorio.
4. **validate** — Valida tipos, relaciones, timestamps, evidence y campos requeridos contra el schema RPG (rpg_schema.py).
5. **resolve** — Busca en Neo4j (solo lectura): exacto, alias, normalizado. Degrada con gracia si Neo4j no responde.
6. **decide** — Auto-decide: `auto_approve` / `needs_review` / `auto_reject`.
7. **approved_writer** — Genera `approved_payload.json`, `review_queue.json`, `rejected.json`, `review.md`.

## Estados de candidato

| Estado | Condición |
|--------|-----------|
| `auto_approve` | conf ≥ 0.85 AND valid AND resolver claro AND evidence AND timestamps válidos |
| `needs_review` | 0.60 ≤ conf < 0.85 OR duplicado ambiguo OR varios matches OR evidence débil |
| `auto_reject` | conf < 0.60 OR schema inválido OR sin evidence OR relación imposible OR noise/intro_outro |

## Outputs

`output/reviews/<workspace>/<source_id>/`

| Fichero | Contenido |
|---------|-----------|
| `segments.json` | Segmentos con timestamps |
| `segments.classified.json` | Segmentos con categoría y `should_extract` |
| `candidates.json` | Candidatos extraídos |
| `validated.json` | Candidatos + resultado de validación |
| `resolved.json` | Candidatos + validación + resolución Neo4j |
| `decisions.json` | Decisiones finales |
| `approved_payload.json` | Payload listo para ingest (auto_approve) |
| `review_queue.json` | Cola de revisión humana (needs_review) |
| `rejected.json` | Candidatos auto-rechazados |
| `review.md` | Solo los pendientes + resumen de contadores |
| `pipeline_state.json` | Estado de cada paso |

`output/reviews/<workspace>/graph_quality/` (audit-graph)

| Fichero | Contenido |
|---------|-----------|
| `duplicate_candidates.json` | Nodos con nombres normalizados iguales |
| `bad_relations.json` | Relaciones con tipo no en schema |
| `missing_metadata.json` | Nodos sin source_id/source_kind, violaciones de schema, baja confianza |
| `graph_quality_review.md` | Informe de auditoría (solo lectura) |

## CLI

```bash
# Desde la raíz del repo, con el venv
VENV=/opt/knowledge-services/property-graph/.venv/bin/python

# Pipeline completo (dry-run obligatorio)
$VENV data-engine/app/cli/data_review.py run \
  --workspace leyenda --source-id media_2bdf6005fcffd476 --dry-run

# Pasos individuales
$VENV data-engine/app/cli/data_review.py segment  --workspace leyenda --source-id <id>
$VENV data-engine/app/cli/data_review.py classify --workspace leyenda --source-id <id>
$VENV data-engine/app/cli/data_review.py extract  --workspace leyenda --source-id <id>
$VENV data-engine/app/cli/data_review.py validate --workspace leyenda --source-id <id>
$VENV data-engine/app/cli/data_review.py resolve  --workspace leyenda --source-id <id>
$VENV data-engine/app/cli/data_review.py decide   --workspace leyenda --source-id <id>

# Ingesta aprobada (dry-run obligatorio en esta fase)
$VENV data-engine/app/cli/data_review.py ingest-approved \
  --workspace leyenda --source-id media_2bdf6005fcffd476 --dry-run

# Estado del pipeline
$VENV data-engine/app/cli/data_review.py summary \
  --workspace leyenda --source-id media_2bdf6005fcffd476

# Auditoría del grafo (solo lectura)
$VENV data-engine/app/cli/data_review.py audit-graph --workspace leyenda
```

## Ingesta aprobada

`ingest-approved` lee `approved_payload.json` y construye las queries Cypher para escribir nodos/relaciones en Neo4j con provenance completa:

- `source_id`, `source_kind`, `source_document`, `source_timestamp_start/end`
- `workspace`, `review_status=auto_approved`, `knowledge_layer=transcript`
- `visibility`, `confidence`, `evidence`

**EN ESTA FASE: `--dry-run` es obligatorio.** Sin él, el comando aborta con mensaje de autorización requerida. La escritura real requiere autorización explícita del administrador.

## Cómo probar con 1 audio real

```bash
# 1. Verificar que existe la transcripción
ls output/transcriptions/leyenda/media_2bdf6005fcffd476.md

# 2. Ejecutar pipeline completo en dry-run
/opt/knowledge-services/property-graph/.venv/bin/python \
  data-engine/app/cli/data_review.py run \
  --workspace leyenda --source-id media_2bdf6005fcffd476 --dry-run

# 3. Revisar solo los pendientes
cat output/reviews/leyenda/media_2bdf6005fcffd476/review.md

# 4. Simular ingesta
/opt/knowledge-services/property-graph/.venv/bin/python \
  data-engine/app/cli/data_review.py ingest-approved \
  --workspace leyenda --source-id media_2bdf6005fcffd476 --dry-run
```

## Cómo NO llenar Neo4j de basura

1. **El pipeline rechaza automáticamente** candidatos con confidence < 0.60, sin evidence, con timestamps inválidos o de segmentos noise/intro_outro.
2. **La ingesta solo lee `approved_payload.json`** — sin ese fichero, no escribe nada.
3. **dry-run obligatorio** en esta fase: el comando aborta sin `--dry-run`.
4. **Cada nodo/relación incluye provenance** completa: si algo se cuela, se puede rastrear y eliminar por source_id.
5. **audit-graph** detecta duplicados, relaciones inválidas y nodos sin metadata antes de que se consoliden.

## Auditoría de calidad (audit-graph)

Detecta issues en el grafo existente (SOLO LECTURA, nunca corrige):

- `duplicate_candidate` — nodos con nombre normalizado igual
- `bad_relation` — relación no en ALLOWED_RELATION_TYPES
- `missing_source_id` — nodo sin source_id
- `missing_source_kind` — nodo sin source_kind
- `schema_violation` — tipo de nodo no en ALLOWED_NODE_TYPES
- `low_confidence` — confidence < 0.5

## Límites del pipeline actual

- La extracción usa heurísticas, no LLM. Confidence máxima ~0.95 vía glosario. Para RPG con terminología específica, los alias no en glosario pueden quedar como `needs_review`.
- El resolver detecta duplicados exactos/normalizados; similitud cross-idioma (Familia Tamori / Tamori Family) requiere revisión manual.
- La clasificación de segmentos es por keywords; puede haber falsos positivos/negativos en segmentos mixtos.
- Panel `/reviews` de revisión humana asistida: implementado por otro agente (viewer/).


## Limitación crítica (verificada 2026-07-12)

El extractor actual (`extractor.py`) es **heurístico** y produce **falsos positivos**: en la
prueba real con `media_2bdf6005fcffd476` autoaprobó entidades como `Llevás`, `Todo`, `Como`
(verbos y palabras comunes en mayúscula) como `Character` con confidence 0.85. El framework
es seguro (nada se ingiere sin `--dry-run` desactivado + autorización explícita), pero
**NO debe ejecutarse `ingest-approved` real hasta sustituir el extractor heurístico por uno
basado en LLM** con validación de entidad. De lo contrario Neo4j se llenaría de ruido.

Recomendación: mantener `ingest-approved` en dry-run; iterar el extractor (LLM + glosario +
lista de stopwords españolas) hasta que la tasa de falsos positivos en autoaprobados sea baja;
recién entonces autorizar una ingesta controlada de una fuente.

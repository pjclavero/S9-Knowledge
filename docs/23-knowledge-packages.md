# 23 · Knowledge Packages: export/import y procesamiento externo

> Relacionado: IA externa NVIDIA en modo sombra (revisión/consenso/calibración) — ver [docs/42](42-external-ai-calibration-and-burst-processing.md). Nada externo escribe en Neo4j.

Actualizado 2026-07-12. Módulo: `data-engine/app/review/export_import.py`.

## Regla de oro

```
Externo propone. S9 Knowledge valida. Neo4j solo recibe aprobado.
```

Nada externo escribe jamás directamente en Neo4j. Todo paquete entrante pasa por:
`validate → resolve → auto_decide → approved_payload → ingest-approved (dry-run/guard)`.

## Tipos de paquete

### 1. KnowledgePackage (export)
Backup lógico / compartir una ambientación procesada / alimentar otro grafo.
Contiene: manifest (package_type, version, created_at, workspace, producer, schema_version),
metadata del workspace, sources, entities, relations, aliases, evidence, approved_payload
embebido y quality_report si existe. Se construye desde los JSON del pipeline
(`output/reviews/...`), sin tocar Neo4j. Salida en `output/exports/<workspace>/`.

### 2. ExternalReviewRequest (S9K → sistema externo)
Paquete para pedir ayuda a un sistema más potente (LLM grande, OCR pesado, revisión semántica).
Incluye: source metadata, transcript/segments, candidates, review_queue, snapshot del glosario,
resumen de schema e instrucciones. **Sanitización obligatoria**: se redactan rutas internas
(`/opt/...`, `/mnt/...`), IPs privadas (`192.168.*`), tokens y credenciales. Nunca incluir secretos.

### 3. ExternalReviewResponse (sistema externo → S9K)
El externo devuelve **propuestas**, no conocimiento aprobado: suggested_entities,
suggested_relations, suggested_aliases, suggested_merges, suggested_rejections,
suggested_type_changes, warnings, confidence, evidence, timestamps.
`load_external_response()` valida el JSON y lo convierte en candidatos con `origin="external"`,
que el auto_decider **nunca autoaprueba directamente** (razón `external_origin`).

### 4. ImportedCandidatePackage
Candidatos generados fuera del servidor. Se validan (schema, workspace, timestamps, evidence),
se marcan `origin="imported"` y entran al pipeline como cualquier candidato local — con la
misma regla: nunca directo a Neo4j.

## Los dos modos de procesamiento

| Modo | Qué hace |
|---|---|
| **Local** | VM105 transcribe, normaliza, segmenta, extrae, valida, resuelve, genera review_queue/approved_payload y dry-run. Siempre disponible. |
| **Externo asistido** | El externo ayuda con transcripción pesada, OCR, LLM grande, extracción avanzada, duplicados, glosario. S9K siempre revalida localmente. |

## Guard de ingesta

`ingest-approved` exige `--dry-run` por defecto **y** `S9K_ALLOW_REAL_INGEST=true` para
escritura real. Además rechaza: paquetes sin workspace o schema_version, entidades sin
evidence, relaciones inválidas, timestamps rotos, y `origin=external` sin validación local
(`validated_by_s9k=true`).

# 43 · Writer de ingesta controlada — semántica create-only y segura

**Fecha:** 2026-07-15
**Rama:** `fix/safe-controlled-ingest-writer`
**Ámbito:** `data-engine/app/review/ingest_approved.py` (documento técnico; sin datos del ensayo).

> Corrige la semántica de escritura y del dry-run **antes** de autorizar el ensayo E2E de la
> primera ingesta controlada. Ningún cambio activa escritura por sí mismo: la ingesta real
> sigue bajo doble guard (`--dry-run` + `S9K_ALLOW_REAL_INGEST=true`) y política de revisión.

---

## 1. Entidades nuevas: CREATE-only (no MERGE)

Antes: `MERGE (n:Type {canonical_name}) SET n += $props` — un `MERGE` sobre un nombre existente
**actualizaba** el nodo (riesgo de sobrescritura). Ahora:

- `_build_create_entity(item)` valida el `entity_type` contra una **allowlist**
  (`Character|Location|Faction|Object|Event|Concept`) — nunca se interpola un tipo arbitrario en
  Cypher — y construye las propiedades **solo** con valores explícitos del item.
- La creación usa `CREATE (n:Entity:`Label`) SET n = $props` dentro de una transacción que
  **verifica la no-existencia primero**. Si el nodo existe, se **aborta toda la transacción**
  (rollback), no se actualiza ni se continúa.

`_neo4j_preflight` clasifica cada entidad nueva por número de coincidencias:
`0 → would_create`, `1 → conflict_existing`, `>1 → ambiguous_existing`.

## 2. USE_EXISTING: verificación sin mutación

`MATCH` por `canonical_name`, exige exactamente 1 coincidencia, **cero `SET`**, cero cambios de
propiedades. `0` o `>1` coincidencias → error. Un candidato USE_EXISTING sin procedencia
multifuente se marca `DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE` y **se excluye del payload**.

## 3. Dry-run conectado a Neo4j en lectura

El dry-run consulta el estado real del grafo y reporta:
`would_create`, `would_verify_existing`, `conflict_existing`, `ambiguous_existing`,
`would_update`, `would_overwrite`, `relations`, `deferred`, `safe_to_write`.
CREATE-only nunca actualiza ni sobrescribe → `would_update=0` y `would_overwrite=0` siempre.
Condición para escritura segura:
```
would_update=0  would_overwrite=0  conflict_existing=0  ambiguous_existing=0  relations=0
```
Si Neo4j no está disponible, el dry-run degrada a `neo4j_unavailable` con `safe_to_write=False`
(sin crash); la **escritura real** exige Neo4j y reverifica de forma atómica.

## 4. Procedencia explícita (sin defaults inventados)

Bajo `S9K_REVIEW_POLICY=full_human_review`, cada entidad nueva debe declarar explícitamente:
`source_id, source_kind, source_document, workspace, knowledge_layer, visibility, review_status,
reviewed_by, reviewed_at, review_action, evidence, confidence`. Prohibidos los defaults
`source_kind=audio`, `knowledge_layer=transcript`, `visibility=player`, y `review_status=auto_approved`
para candidatos de revisión humana. Falta de un campo → **PAQUETE RECHAZADO**. El writer distingue
`approval_mode=human_approved` de `risk_autoapproved` (en el ensayo solo se permite `human_approved`).

## 5. Transacción atómica

`preflight de todos los candidatos → si todos son seguros → CREATE de todos → commit`. Cualquier
conflicto revierte **toda** la transacción (`execute_write`); no queda una ingesta parcial.
La primera ingesta controlada admite **cero relaciones** (un payload con relaciones se rechaza).

## 6. Tests

- `test_use_existing.py` (16): USE_EXISTING sin mutación, fallos por 0/>1 coincidencias, dry-run.
- `test_safe_writer.py` (18): CREATE-no-MERGE, bloqueo por 1/varias coincidencias, dry-run conectado,
  dry-run no llama al writer, detección de nodo existente mal clasificado, sin defaults audio/transcript/
  auto_approved, `reviewed_by`/`reviewed_at` escritos, rechazo por falta de `source_kind`/`visibility`,
  tipo no permitido, cero relaciones, rollback atómico ante conflicto, Neo4j intacto en dry-run,
  candidato aplazado excluido.

Suite completa: **360 tests** verdes.

# Graph Migrations and Rollback by Source

**Status:** Design documented, implementation pending testing  
**Last Updated:** 2026-07-13  
**Author:** AgentC  
**Related:** docs/26 (backup), docs/27 (controlled ingest), docs/29 (readiness)

## Modelo de Procedencia y Trazabilidad

### Propiedades Críticas

Cada nodo de entidad y relación contiene información de procedencia:

```cypher
// Nodo Entity
Node:Entity {
  canonical_name: String,
  entity_type: String,           // "Character", "Location", "Event", "Organization", "Concept"
  workspace: String,
  
  // Procedencia (fuente singular)
  source_id: String,             // ID único del documento que generó este nodo
  source_kind: String,           // "rpg-session", "pdf", "video", "ingest_approved", etc.
  source_path: String,           // Ruta del archivo de origen
  source_hash: String,           // Hash del archivo (detección de cambios)
  
  // Procedencia (múltiples fuentes)
  source_ids: [String],          // Lista de source_ids si el nodo es compartido
  
  // Metadatos de ingesta
  created_at: DateTime,
  updated_at: DateTime,
  extractor_version: String,     // Versión del ingester
  prompt_version: String,        // Versión de prompt si fue IA
  review_status: String,         // "auto_extracted", "approved", "rejected", etc.
  confidence: Float,             // Confianza en la extracción
}

// Relación
Relationship {
  type: String,                  // "RELATED_TO", "FOUGHT_AT", "MENTIONED_IN", etc.
  
  // Procedencia (igual al nodo)
  source_id: String,             // ID del documento que generó esta relación
  source_kind: String,
  source_path: String,
  source_hash: String,
  
  // Propiedades específicas
  confidence: Float,
  evidence: String,
  reviewed: Boolean,
}
```

### Estrategia de Ingesta

#### Escenario 1: Nodo Exclusivo a Ingesta Actual

```cypher
// Ingesta A crea nuevo nodo
MERGE (c:Entity:Character {
  canonical_name: "Aragorn",
  workspace: "default"
})
SET c += {
  source_id: "ingesta-a-001",      // Único source_id
  source_kind: "rpg-session",
  source_ids: null,                // No compartido
  created_at: now(),
  review_status: "auto_extracted",
  confidence: 0.92
}
```

**Rollback:** Eliminar nodo completamente
```cypher
MATCH (n:Entity)
WHERE n.source_id = "ingesta-a-001"
DETACH DELETE n;
```

#### Escenario 2: Nodo Compartido entre Varias Ingestas

```cypher
// Ingesta A crea nodo
MERGE (l:Entity:Location {
  canonical_name: "Moria",
  workspace: "default"
})
SET l += {
  source_id: "ingesta-a-001",
  source_ids: null,
  confidence: 0.88
}

// Ingesta B encuentra la misma ubicación
MATCH (l:Entity:Location {canonical_name: "Moria"})
SET l.source_ids = coalesce(l.source_ids, []) + ["ingesta-b-002"],
    l.updated_at = now(),
    l.confidence = max(l.confidence, 0.95)  // Tomar mejor confianza
RETURN l;
```

**Rollback:** Solo eliminar referencias a la ingesta, mantener nodo si es referenciado por otra:

```cypher
MATCH (n:Entity)
WHERE "ingesta-b-002" IN coalesce(n.source_ids, [])
SET n.source_ids = filter(x IN n.source_ids WHERE x <> "ingesta-b-002")

// Si n.source_ids quedó vacío y n.source_id == "ingesta-b-002", eliminar
WITH n
WHERE (n.source_ids IS NULL OR size(n.source_ids) = 0)
      AND n.source_id = "ingesta-b-002"
DETACH DELETE n;
```

#### Escenario 3: Relaciones Compartidas

```cypher
// Ingesta A crea relación
MATCH (a:Entity {canonical_name: "Frodo"}), (b:Entity {canonical_name: "Moria"})
CREATE (a)-[r:VISITED {
  source_id: "ingesta-a-001",
  source_kind: "rpg-session",
  confidence: 0.85,
  evidence: "Frodo visited Moria in session 1"
}]->(b)

// Ingesta B refuerza la misma relación (con diferente evidencia)
MATCH (a:Entity {canonical_name: "Frodo"}), (b:Entity {canonical_name: "Moria"})
OPTIONAL MATCH (a)-[existing:VISITED]->(b)
WHERE existing.source_id = "ingesta-a-001"  // Relación existente

CALL {
  // Si existe, actualizar
  WITH existing
  SET existing.source_ids = coalesce(existing.source_ids, []) + ["ingesta-b-002"],
      existing.evidence = existing.evidence + "; " + "Evidence from ingesta-b"
  RETURN existing as rel
  UNION
  // Si no existe, crear nueva
  WITH a, b
  CREATE (a)-[new:VISITED {
    source_id: "ingesta-b-002",
    source_ids: null,
    confidence: 0.90,
    evidence: "Confirmation from session 2"
  }]->(b)
  RETURN new as rel
}
RETURN rel;
```

## Procedimiento de Rollback

### Fase 1: Análisis Previo (Dry-Run)

```cypher
// Query 1: Identificar qué va a borrarse
MATCH (n)
WHERE n.source_id = "INGESTA_TARGET"
      OR "INGESTA_TARGET" IN coalesce(n.source_ids, [])
RETURN
  labels(n)[0] as node_type,
  n.canonical_name as name,
  n.source_id as exclusive_source,
  CASE WHEN "INGESTA_TARGET" IN coalesce(n.source_ids, []) THEN "SHARED" ELSE "EXCLUSIVE" END as ownership,
  count(*) as count
ORDER BY ownership;

// Resultado esperado:
// | node_type | name          | exclusive_source      | ownership | count |
// |-----------|---------------|-----------------------|-----------|-------|
// | Entity    | Character1    | INGESTA_TARGET        | EXCLUSIVE | 1     |
// | Entity    | Location1     | OTHER_INGESTA         | SHARED    | 1     |
// | Entity    | Concept1      | INGESTA_TARGET        | EXCLUSIVE | 1     |

// Query 2: Relaciones que se van a afectar
MATCH ()-[r]->()
WHERE r.source_id = "INGESTA_TARGET"
      OR "INGESTA_TARGET" IN coalesce(r.source_ids, [])
RETURN
  type(r) as rel_type,
  CASE WHEN "INGESTA_TARGET" IN coalesce(r.source_ids, []) THEN "SHARED" ELSE "EXCLUSIVE" END as ownership,
  count(*) as count
ORDER BY ownership;

// Query 3: Densidad - conectividad de nodos a eliminar
MATCH (n)
WHERE n.source_id = "INGESTA_TARGET"
WITH n
OPTIONAL MATCH (n)-[r]->()
OPTIONAL MATCH ()-[r2]->(n)
RETURN
  n.canonical_name as entity,
  count(DISTINCT r) as outgoing_rels,
  count(DISTINCT r2) as incoming_rels,
  count(DISTINCT r) + count(DISTINCT r2) as total_rels
ORDER BY total_rels DESC;
```

### Fase 2: Validación de Integridad

**Antes de ejecutar rollback, validar:**

```cypher
// 1. Contar estado pre-rollback
MATCH (n) RETURN count(n) as pre_rollback_nodes;
MATCH ()-[r]->() RETURN count(r) as pre_rollback_rels;

// 2. Verificar que INGESTA_TARGET existe
MATCH (n)
WHERE n.source_id = "INGESTA_TARGET" OR "INGESTA_TARGET" IN coalesce(n.source_ids, [])
RETURN count(n) as target_node_count;
// Debe ser > 0

// 3. Validar ausencia de inconsistencias (nodos huérfanos)
MATCH (n)
WHERE NOT (n)-[]-()
RETURN count(n) as orphan_nodes;
// Anotar para comparación post-rollback
```

### Fase 3: Ejecutar Rollback Selectivo

#### Opción A: Eliminar Nodos Exclusivos + Actualizar Compartidos

```cypher
// Paso 3A.1: Eliminar nodos con source_id exclusivo
MATCH (n)
WHERE n.source_id = "INGESTA_TARGET"
      AND (n.source_ids IS NULL OR size(n.source_ids) = 0)
DETACH DELETE n;

// Paso 3A.2: Eliminar relaciones exclusivas
MATCH ()-[r]->()
WHERE r.source_id = "INGESTA_TARGET"
      AND (r.source_ids IS NULL OR size(r.source_ids) = 0)
DELETE r;

// Paso 3A.3: Limpiar referencias en nodos compartidos
MATCH (n)
WHERE "INGESTA_TARGET" IN coalesce(n.source_ids, [])
SET n.source_ids = filter(x IN n.source_ids WHERE x <> "INGESTA_TARGET"),
    n.updated_at = datetime()
RETURN count(n) as updated_shared_nodes;

// Paso 3A.4: Limpiar referencias en relaciones compartidas
MATCH ()-[r]->()
WHERE "INGESTA_TARGET" IN coalesce(r.source_ids, [])
SET r.source_ids = filter(x IN r.source_ids WHERE x <> "INGESTA_TARGET"),
    r.updated_at = datetime()
RETURN count(r) as updated_shared_rels;
```

#### Opción B: Rollback Completo (Más Agresivo)

```cypher
// Eliminar TODOS los nodos y relaciones asociados, incluso compartidos
// ⚠️ ADVERTENCIA: Esto puede afectar integridad si hay dependencias

// Paso 3B.1: Eliminar relaciones
MATCH ()-[r]->()
WHERE r.source_id = "INGESTA_TARGET"
      OR "INGESTA_TARGET" IN coalesce(r.source_ids, [])
DELETE r;

// Paso 3B.2: Eliminar nodos
MATCH (n)
WHERE n.source_id = "INGESTA_TARGET"
      OR "INGESTA_TARGET" IN coalesce(n.source_ids, [])
DETACH DELETE n;
```

### Fase 4: Validación Post-Rollback

```cypher
// 1. Contar estado post-rollback
MATCH (n) RETURN count(n) as post_rollback_nodes;
MATCH ()-[r]->() RETURN count(r) as post_rollback_rels;

// 2. Verificar que INGESTA_TARGET está completamente limpio
MATCH (n)
WHERE n.source_id = "INGESTA_TARGET" OR "INGESTA_TARGET" IN coalesce(n.source_ids, [])
RETURN count(n) as remaining_target_nodes;
// Debe ser 0 si Opción B, >0 si Opción A (compartidos)

// 3. Buscar relaciones huérfanas (endpoints eliminados)
MATCH (n)-[r]->()
WHERE NOT EXISTS((n)-[]-())
      OR NOT EXISTS(()-[]->(n))
RETURN n.canonical_name, type(r), count(*);

// 4. Integridad de referencias
MATCH (n)
WHERE n.source_ids IS NOT NULL
WITH n
WHERE any(id IN n.source_ids WHERE NOT EXISTS(
  MATCH (m) WHERE m.source_id = id
))
RETURN n.canonical_name as orphaned_reference;
// Lista de nodos que referencian ingestas no existentes (error)
```

### Fase 5: Revertir el Rollback (Si Falla)

Si el rollback causó problemas:

#### Opción 1: Usar Backup Pre-Rollback

```bash
# (Ver docs/26, Opción B para disaster recovery)
# Restaurar desde backup anterior al rollback
docker stop neo4j-knowledge
# ... restore procedure
docker compose up -d
```

#### Opción 2: Re-ingestar

Si el rollback fue incompleto o incorrecto:

```bash
# Re-ejecutar la ingesta que se rollbacked
# (Asume que el ingester es idempotente o usa MERGE)

export S9K_ALLOW_REAL_INGEST=true
python app/ingest_rpg.py \
  --document "$DOC_PATH" \
  --source-id "INGESTA_TARGET" \
  --source-kind "rpg-session" \
  --workspace "default"
unset S9K_ALLOW_REAL_INGEST
```

## Casos de Uso Específicos

### Caso 1: Rollback Parcial — Eliminar Solo Nodos Erróneos

```cypher
// Si la ingesta A creó una entidad "Gandalf" pero debería ser "Gandalf the Grey"

// Pre-análisis
MATCH (n:Entity {canonical_name: "Gandalf"})
WHERE n.source_id = "ingesta-a-001"
RETURN n;

// Opción A: Eliminar y re-crear (si es exclusivo)
MATCH (n:Entity {canonical_name: "Gandalf"})
WHERE n.source_id = "ingesta-a-001"
DETACH DELETE n;

// Re-ingestar con nombre correcto

// Opción B: Actualizar in-place (si posible)
MATCH (n:Entity {canonical_name: "Gandalf"})
WHERE n.source_id = "ingesta-a-001"
SET n.canonical_name = "Gandalf the Grey",
    n.updated_at = datetime(),
    n.review_status = "corrected"
RETURN n;
```

### Caso 2: Resolución de Duplicados

```cypher
// Ingesta A y B crearon "Moria" y "Mines of Moria" (mismo lugar)
// Decisión: mantener "Moria", eliminar "Mines of Moria"

// Análisis
MATCH (a:Entity {canonical_name: "Moria"}),
      (b:Entity {canonical_name: "Mines of Moria"})
RETURN a.source_id, b.source_id;

// Rollback selectivo: eliminar solo la versión de ingesta-b
MATCH (n:Entity {canonical_name: "Mines of Moria"})
WHERE n.source_id = "ingesta-b-002"
DETACH DELETE n;

// Actualizar todas las relaciones que apuntaban a "Mines of Moria"
// para que apunten a "Moria" (manual o con script)
MATCH (x)-[r]->(old:Entity {canonical_name: "Mines of Moria"})
MATCH (new:Entity {canonical_name: "Moria"})
CREATE (x)-[new_rel:visited]->(new)
SET new_rel += properties(r)
DELETE r;
```

## Limitaciones y Consideraciones

### Limitaciones Técnicas

1. **Sin transacciones ACID en Cypher puro:** Si un query de rollback falla a mitad, pueden quedar inconsistencias. Solución: usar drivers con soporte de transacciones (Neo4j Python driver).

2. **Relaciones sin source_id heredado:** Si las relaciones antiguas no tienen source_id, no se pueden rastrear. Solución: migración de datos pre-Prioridad 1 (documentada en docs/30).

3. **Cascade delete complejo:** Eliminar un nodo elimina todas sus relaciones, pero no actualiza nodos remoto que tenían referencias. Solución: usar OPTIONAL MATCH en queries de validación post-rollback.

4. **No hay rollback automático de índices:** Si se crearon índices en nodos de ingesta-a, permanecen incluso después del rollback. Solución: documen tación manual de índices por ingesta (future work).

### Consideraciones de Diseño

| Consideración | Impacto | Mitigación |
|---|---|---|
| Falta source_id en datos legados | Imposible rollback selectivo | Migración pre-ingesta; docs/30 |
| Ingesta parcialmente completada | Inconsistencia | Transacciones en driver Neo4j |
| Nodos compartidos complejos | Rollback incompleto | Análisis exhaustivo pre-rollback |
| Índices y constraints | Desempeño post-rollback | Auditoría de índices (future) |

## Procedimiento Completo de Ejecución

```bash
#!/bin/bash
set -e

INGESTA_ID="$1"
NEO4J_USER="neo4j"
NEO4J_PASS="$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password)"
NEO4J_URL="http://127.0.0.1:7474/db/neo4j/sync"

# Paso 1: Análisis previo (dry-run)
echo "=== Analyzing rollback target: $INGESTA_ID ==="
curl -s -u "$NEO4J_USER:$NEO4J_PASS" "$NEO4J_URL" \
  -H "Content-Type: application/json" \
  -d "{\"statements\":[{\"statement\":\"MATCH (n) WHERE n.source_id = '$INGESTA_ID' OR '$INGESTA_ID' IN coalesce(n.source_ids, []) RETURN count(n) as count;\"}]}" \
  | python -m json.tool

# Paso 2: Validar integridad pre-rollback
echo "=== Pre-rollback integrity check ==="
curl -s -u "$NEO4J_USER:$NEO4J_PASS" "$NEO4J_URL" \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (n) RETURN count(n) as node_count; MATCH ()-[r]->() RETURN count(r) as rel_count;"}]}' \
  | python -m json.tool | tee "/tmp/rollback_pre_$INGESTA_ID.json"

# Paso 3: Ejecutar rollback (OPCIÓN A: selectivo)
echo "=== Executing selective rollback ==="
curl -s -u "$NEO4J_USER:$NEO4J_PASS" "$NEO4J_URL" \
  -H "Content-Type: application/json" \
  -d "{\"statements\":[{\"statement\":\"MATCH (n) WHERE n.source_id = '$INGESTA_ID' AND (n.source_ids IS NULL OR size(n.source_ids) = 0) DETACH DELETE n; MATCH ()-[r]->() WHERE r.source_id = '$INGESTA_ID' AND (r.source_ids IS NULL OR size(r.source_ids) = 0) DELETE r;\"}]}" \
  | python -m json.tool

# Paso 4: Limpiar referencias compartidas
echo "=== Cleaning shared references ==="
curl -s -u "$NEO4J_USER:$NEO4J_PASS" "$NEO4J_URL" \
  -H "Content-Type: application/json" \
  -d "{\"statements\":[{\"statement\":\"MATCH (n) WHERE '$INGESTA_ID' IN coalesce(n.source_ids, []) SET n.source_ids = filter(x IN n.source_ids WHERE x <> '$INGESTA_ID') RETURN count(n) as updated_nodes;\"}]}" \
  | python -m json.tool

# Paso 5: Validar post-rollback
echo "=== Post-rollback validation ==="
curl -s -u "$NEO4J_USER:$NEO4J_PASS" "$NEO4J_URL" \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (n) RETURN count(n) as node_count; MATCH ()-[r]->() RETURN count(r) as rel_count;"}]}' \
  | python -m json.tool | tee "/tmp/rollback_post_$INGESTA_ID.json"

echo "=== Rollback of $INGESTA_ID completed ==="
```

## Próximos Pasos

1. ✅ **Completado:** Modelo de procedencia documentado
2. ✅ **Completado:** Queries de rollback diseñadas
3. ⏳ **Pendiente:** Implementar script rollback en Python (transaccional)
4. ⏳ **Pendiente:** Tests de rollback (create-rollback-validate)
5. ⏳ **Pendiente:** Integración en docs/27 (runbook ingesta)
6. ⏳ **Pendiente:** Post-ingesta real, ejecutar y documentar en docs/30

## Referencias

- docs/26: Backup and Restore
- docs/27: Controlled Ingest Runbook
- docs/23: Knowledge Packages Schema
- app/ingest_rpg.py: Entity/Relationship creation logic
- Schema: source_id, source_kind, source_ids properties

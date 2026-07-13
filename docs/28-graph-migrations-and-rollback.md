# 28 · Migraciones del Grafo y Rollback por source_id

**Estado: DISEÑO COMPLETO / IMPLEMENTACIÓN PENDIENTE**
**Aplicable a: Neo4j producción en VM105**

---

## Modelo de procedencia

Cada nodo y relación en el grafo tiene propiedades de trazabilidad asignadas durante la ingesta:

### Propiedades de procedencia

| Propiedad | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `source_id` | String | Identificador único de la fuente | `audio_l5a_s03e01` |
| `source_kind` | String | Tipo de fuente | `audio`, `pdf`, `book`, `youtube`, `text` |
| `workspace` | String | Espacio de conocimiento | `leyenda` |

### Cómo se asignan (código: `ingest_rpg.py`)

El método `set_doc_context()` establece el contexto para toda una sesión de ingesta. Todos los nodos y relaciones escritos en esa sesión heredan el `source_id` y `source_kind` del contexto activo.

```python
# Extracto de data-engine/app/ingest_rpg.py
def set_doc_context(self, *, source_id: str, source_kind: str, workspace: str):
    # Todos los writes posteriores usarán estos valores
    ctx["source_id"] = source_id
    ctx["source_kind"] = source_kind
    ctx["workspace"] = workspace
```

**Invariante clave:** Si `source_id` está vacío, el pipeline emite WARNING y los nodos quedan sin trazabilidad.

---

## Tipos de nodos y su relación con source_id

### Categoría 1: Nodos exclusivos de una fuente

Nodos que existen únicamente porque fueron mencionados en una fuente específica. Su eliminación en un rollback es segura.

Ejemplo: un personaje secundario que solo aparece en el episodio S03E01.

```cypher
-- Nodos exclusivos de un source_id
MATCH (n) WHERE n.source_id = $source_id
AND NOT EXISTS {
  MATCH (n) WHERE n.source_id <> $source_id
}
RETURN labels(n)[0] as tipo, n.name, n.source_id
```

### Categoría 2: Nodos compartidos entre fuentes

Nodos mencionados en múltiples fuentes. Un rollback de una fuente puede requerir actualizar propiedades pero NO eliminar el nodo.

Ejemplo: un personaje principal mencionado en 5 episodios.

```cypher
-- Nodos que tienen referencias en otras fuentes además de la que queremos deshacer
MATCH (n) WHERE n.source_id = $source_id
WITH n
MATCH (n)-[r]-()
WHERE r.source_id <> $source_id
RETURN labels(n)[0] as tipo, n.name, count(r) as refs_otras_fuentes
```

### Categoría 3: Nodos históricos sin source_id (~87 nodos estimados)

Nodos creados antes de que el sistema de procedencia estuviera implementado. No tienen `source_id` asignado y **no son afectados por el rollback selectivo**.

```cypher
-- Inventario de nodos históricos sin trazabilidad
MATCH (n) WHERE n.source_id IS NULL OR n.source_id = ""
RETURN labels(n)[0] as tipo, count(*) as cnt
ORDER BY cnt DESC;
```

**Riesgo:** Estos nodos solo pueden eliminarse mediante restore completo desde backup.

---

## Diseño del rollback en 5 fases

### Fase 1: Análisis previo (dry-run)

Ejecutar ANTES de cualquier decisión de rollback. Solo lectura, no modifica datos.

```cypher
-- Análisis completo del source_id a deshacer
// 1. Nodos directamente asociados
MATCH (n) WHERE n.source_id = $source_id
RETURN labels(n)[0] as tipo, count(*) as nodos_a_evaluar;

// 2. Relaciones directamente asociadas
MATCH ()-[r]->() WHERE r.source_id = $source_id
RETURN type(r) as tipo, count(*) as rels_a_evaluar;

// 3. Nodos exclusivos (candidatos a eliminación)
MATCH (n) WHERE n.source_id = $source_id
WHERE NOT EXISTS {
  MATCH ()-[r]-(n) WHERE r.source_id <> $source_id
}
RETURN labels(n)[0] as tipo, n.name as nombre, 'ELIMINAR' as accion;

// 4. Nodos compartidos (candidatos a desvincular, no eliminar)
MATCH (n) WHERE n.source_id = $source_id
WHERE EXISTS {
  MATCH ()-[r]-(n) WHERE r.source_id <> $source_id
}
RETURN labels(n)[0] as tipo, n.name as nombre, 'DESVINCULAR' as accion;
```

### Fase 2: Listado de impacto

Generar un informe legible antes de actuar:

```
source_id: audio_l5a_s03e01
=== IMPACTO DEL ROLLBACK ===

ELIMINAR (nodos exclusivos de esta fuente):
  Person: TestChar
  Location: TestPlace
  ...

DESVINCULAR (relaciones a eliminar, nodo se mantiene):
  PersonA -[KNOWS]-> PersonB (ambos existen en otras fuentes)
  ...

NODOS SIN CAMBIO (no tienen source_id o tienen otro source_id):
  ~87 nodos históricos (sin source_id)
  ...

TOTAL: N nodos a eliminar, M relaciones a eliminar
```

### Fase 3: Aprobación explícita

El rollback nunca se ejecuta automáticamente. Requiere confirmación explícita del operador tras revisar el informe de la Fase 2.

**Mecanismo propuesto:** argumento `--confirm` en el script de rollback (implementación pendiente).

### Fase 4: Ejecución del rollback (IMPLEMENTACIÓN PENDIENTE)

```cypher
-- Eliminar relaciones del source_id (siempre primero)
MATCH ()-[r]->() WHERE r.source_id = $source_id
DELETE r;

-- Eliminar nodos exclusivos (sin otras relaciones)
MATCH (n) WHERE n.source_id = $source_id
  AND NOT EXISTS { MATCH (n)-[r]-() WHERE r.source_id <> $source_id }
DETACH DELETE n;

-- Para nodos compartidos: solo actualizar source_id al primer source_id alternativo
-- (conservar el nodo, solo eliminar la vinculación con la fuente desechada)
MATCH (n) WHERE n.source_id = $source_id
  AND EXISTS { MATCH (n)-[r]-() WHERE r.source_id <> $source_id }
SET n.source_id = 'OTRO_SOURCE_ID'  -- requiere lógica de prioridad
```

**Estado: DISEÑO COMPLETO — Implementación del script de ejecución PENDIENTE.**

### Fase 5: Auditoría post-rollback

```cypher
-- Verificar que no quedan rastros del source_id eliminado
MATCH (n) WHERE n.source_id = $source_id RETURN count(n) as residuo_nodos;
MATCH ()-[r]->() WHERE r.source_id = $source_id RETURN count(r) as residuo_rels;
-- Ambos deben retornar 0

-- Integridad general
MATCH (n) RETURN count(n) as total_nodos;
MATCH ()-[r]->() RETURN count(r) as total_rels;
```

---

## Script de dry-run (disponible)

El script `scripts/backup/neo4j-rollback-dryrun.sh` implementa las Fases 1 y 2:

- Acepta `--source-id` como argumento obligatorio
- Es **solo lectura** (nunca escribe en Neo4j)
- Genera informe en `/tmp/rollback-dryrun-<source_id>-<timestamp>.txt`
- Exit 0 si el análisis fue exitoso, 1 si hubo errores

---

## Casos especiales

### Rollback de source_id que no existe

```cypher
MATCH (n) WHERE n.source_id = $source_id RETURN count(n) as total;
-- Si retorna 0: no hay nada que deshacer
```

El script de dry-run detecta este caso y termina con aviso.

### Rollback que eliminaría nodos con muchas referencias cruzadas

Si un nodo tiene relaciones con muchos otros `source_id`, su eliminación puede dejar "huérfanos" en el grafo. El dry-run informa de estas dependencias para que el operador decida.

### Los ~87 nodos históricos sin source_id

Estos nodos fueron creados antes de que el sistema de procedencia estuviera operativo (posiblemente en la carga inicial del grafo). Características:

- `source_id IS NULL` o `source_id = ""`
- Representan entidades del lore histórico de la campaña
- **No son afectados por ningún rollback selectivo**
- Solo eliminables mediante `DETACH DELETE` manual o restore completo
- Candidatos a recibir `source_id = 'historical_legacy'` en una migración futura

```cypher
-- Inventario completo de nodos históricos
MATCH (n) WHERE n.source_id IS NULL OR n.source_id = ""
RETURN labels(n)[0] as tipo, n.name as nombre
ORDER BY tipo, nombre;
```

---

## Migraciones de esquema

### Migración propuesta: asignar source_id a nodos históricos

```cypher
-- Asignar source_id retroactivo a nodos históricos (PENDIENTE DE APROBACIÓN)
-- Esta migración es irreversible sin backup previo
MATCH (n) WHERE n.source_id IS NULL OR n.source_id = ""
SET n.source_id = 'historical_legacy',
    n.source_kind = 'legacy'
RETURN count(n) as actualizados;
```

**Estado: PROPUESTO — No ejecutar sin backup verificado y aprobación explícita.**

### Historial de migraciones

| Fecha | Descripción | Ejecutada | Rollbackable |
|---|---|---|---|
| (pendiente) | Asignar source_id a ~87 nodos históricos | No | Solo con backup |

---

## Resumen del estado

| Componente | Estado |
|---|---|
| Modelo de procedencia (source_id/source_kind) | IMPLEMENTADO en data-engine |
| Dry-run de rollback (fases 1-2) | IMPLEMENTADO (`neo4j-rollback-dryrun.sh`) |
| Ejecución de rollback (fases 3-5) | DISEÑADO, implementación PENDIENTE |
| Automatización de backup | DISEÑADA, implementación PENDIENTE |
| Migración de nodos históricos | PROPUESTA, sin fecha |

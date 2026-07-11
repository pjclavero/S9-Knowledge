# Actualización del modelo de grafo RPG — Informe

Documento de trabajo para la ampliación del modelo de datos del grafo de campañas
de rol (workspace `leyenda` y futuros). Registra el **estado ANTES del cambio** y
sirve como referencia de las fases de actualización.

- Fecha inicio: 2026-07-10
- VM: 192.168.1.205 (`common`)
- Archivos afectados:
  - `app/schemas/rpg_schema.py`
  - `app/prompts/rpg_extraction_prompt.py`
  - `app/ingest_rpg.py`
- Backups en: `backups/*.2026-07-10-210845.bak`

---

## 1. Estado ANTES del cambio

### 1.1 Versiones

| Componente | Versión previa |
|---|---|
| `SCHEMA_VERSION` (rpg_schema.py) | `1.3.0` |
| `PROMPT_VERSION` (rpg_extraction_prompt.py) | `1.2.0` |
| `extractor_version` (ingest) | `ingest_rpg` |
| Modelo LLM | `qwen2.5:7b` (Ollama en 192.168.1.157) |

### 1.2 Tipos de entidad existentes (`ALLOWED_NODE_TYPES`)

```
Document, Chapter, Character, Location, Faction, Clan, Family, School,
Creature, Object, Spell, Rule, Event, Concept, Task
```

Total: **15 tipos**. No existen todavía: Region, Session, Combat, Encounter,
Image, Group, Artifact, Transcript, Spirit, Demon, Beast, NonHuman.

### 1.3 Relaciones existentes (`ALLOWED_RELATION_TYPES`)

```
CONTAINS, MENTIONS, APPEARS_IN, BELONGS_TO, MEMBER_OF, ALLIED_WITH, ENEMY_OF,
RELATED_TO, LOCATED_IN, OCCURS_IN, OWNS, USES, TEACHES, LEARNS, CREATED_BY,
DESCENDANT_OF, PARENT_OF, SERVES, GOVERNS, AFFECTS, REQUIRES, CONTRADICTS,
DECIDES, SUSPECTS, AGREES_TO, HAS_VISION_OF, SEES_IN_VISION, WARNED_BY, WARNS,
INVESTIGATES, SEARCHES_FOR, INTERROGATES, CHECKS, HAS_SYMBOL_OF, HOLDS,
DISAPPEARED_NEAR, TASK_ASSIGNED_TO, TASK_TARGETS, MEETS, KNOWS, ORDERS,
FALLS_TO, PLOTS_AGAINST
```

Total: **43 tipos**.

### 1.4 Normalizadores existentes

`_RAW_NORMALIZE` (rpg_schema.py) cubre ~90 entradas de frases libres en español
e inglés hacia los tipos canónicos anteriores. `normalize_relation_type_full()`
aplica además desambiguación contextual (source/target/evidence) para
`SEES_IN_VISION` / `HAS_SYMBOL_OF` / `HAS_VISION_OF`.

### 1.5 Campos de trazabilidad actuales

**En nodos** (`write_entity` + `_ensure_node`):
`workspace, canonical_name, display_name, aliases, description, entity_type,
source_document, source_pages, confidence, source_id, source_kind, source_path,
source_hash, created_at, updated_at` (+ `created_from_relation` en auto-creados).

**En relaciones** (`write_relationship`):
`evidence, source_document, source_pages, confidence, relation_label_es,
workspace, source_id, source_kind, source_path, source_hash, extractor_version,
prompt_version, created_at, updated_at`.

**Faltan** (objetivo de esta fase): `source_pages` normalizado, `extractor_version`
y `prompt_version` en nodos, y todos los campos temporales/estado:
`first_seen_session, first_seen_date, last_seen_session, last_seen_date,
source_session, source_date, chronology_order, visibility, knowledge_layer,
review_status, manual_review_required, subtype, species, role, attitude, status,
danger_level, is_human, is_unique, image_path, thumbnail_path`.

### 1.6 Estado de Neo4j (workspace `leyenda`) antes del cambio

Nodos por tipo (total **191**):

| entity_type | n |
|---|---|
| Character | 87 |
| Concept | 36 |
| Location | 22 |
| Clan | 14 |
| Faction | 13 |
| Object | 7 |
| Task | 4 |
| Event | 4 |
| Creature | 2 |
| School | 1 |
| Spell | 1 |

Trazabilidad de nodos: `191 total / 99 con source_id / 140 con source_kind`
→ 92 nodos sin source_id y 51 sin source_kind (históricos, previos a los fixes de
trazabilidad; **no se tocan** en esta fase salvo revalorización futura).

Relaciones por tipo (principales): BELONGS_TO 66, LOCATED_IN 9, RELATED_TO 6,
OWNS 6, MEMBER_OF 4, PARENT_OF 3, LEARNS 3, AGREES_TO 3, SERVES 3, TEACHES 2,
CREATED_BY 2, OCCURS_IN 2, ORDERS 2, y varias con 1 (ENEMY_OF, WARNED_BY,
SEES_IN_VISION, HAS_SYMBOL_OF, INVESTIGATES, DISAPPEARED_NEAR, CONTAINS,
REQUIRES).

### 1.7 Perfiles y flujo (sin cambios estructurales)

- Perfiles: `short`, `transcript`, `book`, `image-text`.
- `transcript` usa doble pasada (entidades → eventos+relaciones).
- Escritura incremental por chunk; validación por ítem; descarte de relaciones
  no mapeables sin abortar chunk; entidad colectiva "Grupo de la sesión";
  resolución de referencias de entidad; `semantic_warnings.md`; `[AUDIT]` final.

---

## 2. Objetivo de la actualización

Soportar en Neo4j (no solo en el visor): personajes, criaturas/no-humanos,
enemigos/aliados, lugares y encuentros, combates, sesiones y cronología,
evolución temporal, relaciones sociales, imágenes asociadas, estado de entidades
y visibilidad jugador/narrador/secreto/referencia.

El detalle de tipos, relaciones, campos y reglas se implementa en las fases 2–14
(ver sección "Cambios aplicados" más abajo, que se completa al finalizar).

---

## 3. Cambios aplicados

_(Esta sección se rellena al completar cada fase — ver informe de entrega final.)_

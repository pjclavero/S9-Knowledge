# Diseño del visor de grafo — S9 Knowledge (modelo de datos)

Documento de diseño. **No implementa el visor**: define qué datos deja el pipeline
en Neo4j y qué vistas podrá construir el visor futuro sobre ellos.

- Fecha: 2026-07-10
- Estado: modelo de datos preparado (schema 1.4.0). Visor: pendiente.
- Fuente de verdad: Neo4j (`neo4j-knowledge`, bolt 7687), no la interfaz.

---

## 1. Principio

Toda la información vive en Neo4j con trazabilidad completa. El visor es solo una
capa de presentación: **lee**, filtra y dibuja. Nunca es la fuente de verdad.

## 2. Tipos de nodo disponibles (schema 1.4.0)

Personajes/seres: `Character, Creature, NonHuman, Spirit, Demon, Beast`
Lugares: `Location, Region`
Grupos: `Faction, Clan, Family, School, Group`
Objetos/saber: `Object, Artifact, Spell, Rule, Concept`
Acontecimientos: `Event, Encounter, Combat, Task`
Campaña/fuentes: `Session, Document, Chapter, Transcript, Image`

Cada nodo lleva (según disponibilidad): `entity_type, canonical_name, display_name,
aliases, description, workspace, source_id, source_kind, source_document,
source_path, source_hash, source_pages, confidence, extractor_version,
prompt_version, created_at, updated_at` y los campos opcionales:
`subtype, species, role, attitude, status, danger_level, is_human, is_unique,
visibility, knowledge_layer, first_seen_session, last_seen_session, source_session,
source_date, chronology_order, session_number/title/date, campaign_arc, summary,
image_path, thumbnail_path, media_source, review_status, manual_review_required,
created_from_relation`.

## 3. Vistas previstas del visor

| Vista | Cómo se obtiene de Neo4j |
|---|---|
| Grafo global | Todos los nodos/relaciones del `workspace`. |
| Solo personajes | `entity_type IN [Character, NonHuman]`. |
| Criaturas / Bestiario | `entity_type IN [Creature, Spirit, Demon, Beast, NonHuman]`. |
| Enemigos activos | `attitude='enemy' AND status IN [active, escaped, hostile]`. |
| Lugares con encuentros | `Location`/`Region` con aristas entrantes `FOUGHT_AT/SEEN_IN/ENCOUNTERED_AT/OCCURS_IN`. |
| Sesiones / cronología | Nodos `Session` ordenados por `session_number`; entidades por `first_seen_session`. |
| Evolución temporal | Filtrar por `source_session`/`chronology_order`; comparar `first_seen` vs `last_seen`. |
| Novedades por sesión | Entidades/relaciones con `source_session = N`. |
| Red social de personajes | Relaciones entre `Character`: `ALLY_OF/ENEMY_OF/FRIEND_OF/RIVAL_OF/FAMILY_OF/SPOUSE_OF/MENTOR_OF/...`. |
| Vista por documento | Filtrar por `source_id`. |
| Vista por lugar | Nodo `Location` + vecindario. |
| Vista por criatura | Nodo `Creature`/... + `FOUGHT_AT/SEEN_IN/SUMMONED_BY/...`. |

## 4. Filtros transversales (obligatorios en el visor)

- **workspace**: separación dura por campaña (siempre presente).
- **visibility**: `player` / `narrator` / `secret` / `reference`. El visor debe
  poder ocultar `secret`/`narrator` en un "modo jugador".
- **knowledge_layer**: `campaign` / `book` / `transcript` / `manual` / `inferred`
  / `reviewed` / `test`. Permite separar lore de manual de lo ocurrido en mesa.
- **review_status / manual_review_required**: resaltar lo que necesita revisión
  (`needs_review`, nodos `created_from_relation`).

## 5. Consultas Cypher de referencia

```cypher
// Bestiario del workspace
MATCH (n:Entity {workspace:'leyenda'})
WHERE n.entity_type IN ['Creature','Spirit','Demon','Beast','NonHuman']
RETURN n.canonical_name, n.attitude, n.status, n.danger_level, n.image_path
ORDER BY n.danger_level DESC;

// Novedades de una sesión
MATCH (n:Entity {workspace:'leyenda', source_session:4})
RETURN n.entity_type, n.canonical_name ORDER BY n.entity_type;

// Red social de personajes (modo narrador)
MATCH (a:Character {workspace:'leyenda'})-[r]->(b:Character {workspace:'leyenda'})
WHERE type(r) IN ['ALLY_OF','ENEMY_OF','FRIEND_OF','RIVAL_OF','SPOUSE_OF',
                  'FAMILY_OF','MENTOR_OF','STUDENT_OF','TRUSTS','DISTRUSTS']
RETURN a.canonical_name, r.relation_label_es, b.canonical_name;

// Lugares con encuentros/combates
MATCH (x)-[r]->(l:Entity {workspace:'leyenda'})
WHERE l.entity_type IN ['Location','Region']
  AND type(r) IN ['FOUGHT_AT','SEEN_IN','ENCOUNTERED_AT','OCCURS_IN']
RETURN l.canonical_name, collect(DISTINCT x.canonical_name) AS seres;
```

## 6. Imágenes

Los nodos pueden llevar `image_path`/`thumbnail_path` (detección local por
convención `/mnt/nextcloud-rol/<workspace>/_media/<categoria>/<slug>.<ext>`).
El visor sirve esas imágenes; el pipeline nunca descarga ni genera imágenes.

## 7. Fuentes externas (futuro)

Ver `EXTERNAL_SOURCES_DESIGN.md`: YouTube/web/audio se representarán como
`Document`/`Transcript` con `source_kind` y `source_url`, enlazados con
`EXTRACTED_FROM`, `APPEARS_IN`, `SOURCE_OF`, `HAS_TRANSCRIPT`. El panel de gestión
("Fuentes / Importar") alimentará la cola `state/jobs.db`.

## 8. Fuera de alcance de esta fase

No se implementa: servidor del visor, autenticación, render del grafo, endpoints
REST. Solo queda definido el modelo de datos y las consultas que el visor usará.

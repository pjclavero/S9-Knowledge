# Informe de entrega — Actualización del grafo RPG + fuentes externas + conocimiento por personaje

- Fecha: 2026-07-10/11
- VM: 192.168.1.205 (`common`), proyecto `/opt/knowledge-services/property-graph`
- Modelo LLM: qwen2.5:7b (Ollama en 192.168.1.157)
- Neo4j: `neo4j-knowledge` (bolt 127.0.0.1:7687)

No se procesaron más páginas del GM Guide. No se borró nada de Neo4j. No se tocó
Nextcloud en escritura. Todos los cambios con backup previo.

---

## 1. Archivos modificados

| Archivo | Cambio | Versión |
|---|---|---|
| `app/schemas/rpg_schema.py` | Tipos, relaciones, labels ES, vocabularios, normalizadores, campos opcionales (temporales/estado/imagen/conocimiento) | SCHEMA 1.5.0 |
| `app/prompts/rpg_extraction_prompt.py` | Perfil transcript ampliado (criaturas/espíritus/combate), SYSTEM_PROMPT_BOOK, sección CONOCIMIENTO DE PERSONAJES | PROMPT 1.4.0 |
| `app/ingest_rpg.py` | Writer Neo4j: LABEL_MAP, SET dinámico opcional, metadatos temporales, nodo Session + APPEARS_IN, imágenes, semántica ok/dubious/invalid, review_status, [AUDIT] ampliada, CLI nuevas | — |

## 2. Archivos NUEVOS

| Archivo | Contenido |
|---|---|
| `app/jobs/__init__.py`, `app/jobs/job_store.py` | Cola de trabajos SQLite (`state/jobs.db`) para fuentes externas |
| `app/access/__init__.py`, `app/access/access_store.py` | Usuario-personaje + permisos por workspace + audit log (`state/access.db`) |
| `docs/RPG_GRAPH_MODEL_UPDATE.md` | Auditoría del estado previo |
| `docs/VISOR_DESIGN.md` | Modelo de datos para el visor futuro |
| `docs/EXTERNAL_SOURCES_DESIGN.md` | Diseño YouTube/web/audio + cola |
| `docs/KNOWLEDGE_VISIBILITY_DESIGN.md` | Conocimiento y visibilidad por personaje |
| `docs/USERS_CHARACTERS_DESIGN.md` | Usuario-personaje multi-campaña + permisos |
| `tests/data/test_creatures_locations_timeline.md` | Datos de prueba |

## 3. Backups creados (antes de tocar)

- `backups/ingest_rpg.py.2026-07-10-210845.bak`
- `backups/rpg_schema.py.2026-07-10-210845.bak`
- `backups/rpg_extraction_prompt.py.2026-07-10-210845.bak`
- `backups/rpg_extraction_prompt.py.2026-07-10-211316.agentA.bak`
- `app/prompts/backups/rpg_extraction_prompt.py.2026-07-10-215140.agentC.bak`

## 4. Tipos de entidad añadidos (27 en total)

Nuevos: `Creature`(ya existía), `NonHuman, Spirit, Demon, Beast, Region, Group,
Artifact, Encounter, Combat, Session, Transcript, Image`. Se conservan los previos.

## 5. Tipos de relación añadidos (113 en total)

- Personajes: ALLY_OF, RIVAL_OF, FRIEND_OF, FAMILY_OF, SPOUSE_OF, PROTECTS,
  MENTOR_OF, STUDENT_OF, BETRAYS, OWES_DEBT_TO, COMMANDS, WORKS_FOR, THREATENS,
  BLACKMAILS, LOVES, FEARS, TRUSTS, DISTRUSTS.
- Criaturas/lugares: SEEN_IN, ENCOUNTERED_AT, FOUGHT_AT, DEFEATED_AT, KILLED_AT,
  ESCAPED_FROM, GUARDS, HAUNTS, SUMMONED_BY, CORRUPTED_BY, ATTACKED, HELPED,
  TALKED_TO, FOUND_IN, HIDDEN_IN, TRAVELS_TO, COMES_FROM, RULES_OVER.
- Eventos/sesiones/tareas: OCCURS_DURING, PARTICIPATES_IN, CAUSES, LEADS_TO,
  DISCOVERS, REVEALS, CHANGES_STATUS_OF, STARTS_TASK, COMPLETES_TASK, FAILS_TASK,
  ASSIGNED_TO, BLOCKED_BY, COMPLETED_BY.
- Fuentes: SOURCE_OF, EXTRACTED_FROM, HAS_IMAGE, HAS_TRANSCRIPT.
- Conocimiento por personaje: KNOWS_ABOUT, HAS_SEEN, HAS_MET, HAS_HEARD_ABOUT,
  HAS_FOUGHT, HAS_TALKED_TO, DISCOVERED, WAS_PRESENT_AT, PARTICIPATED_IN,
  WITNESSED, WAS_TOLD_BY, TELLS, TELLS_ABOUT, SHARED_WITH, KNOWN_BY_PARTY,
  KNOWN_PUBLICLY, INVOLVES.

## 6. Etiquetas en español

113 etiquetas en `RELATION_LABELS_ES` (todas las relaciones tienen etiqueta ES).
Verificado: prompt ⊆ schema → 0 relaciones que el LLM pueda emitir sin mapear.

## 7. Normalizadores añadidos

~200 mapeos ES/inglés → código canónico (p.ej. `luchó contra`→ATTACKED,
`luchó dentro del`→FOUGHT_AT, `atacó a`→ATTACKED, `HAS_WIFE`→SPOUSE_OF,
`RESEARCHES`→INVESTIGATES, `le contó a`→TELLS, `ha combatido contra`→HAS_FOUGHT).

## 8. Cambios en prompt transcript / book

- Transcript: extrae criaturas/espíritus/demonios/no-humanos con `attitude`;
  crea Combat + relaciones FOUGHT_AT/OCCURS_IN; sección CONOCIMIENTO DE PERSONAJES
  con reglas y ejemplo del Oni (Hisao ausente → no genera su conocimiento).
- Book: `SYSTEM_PROMPT_BOOK` marca `knowledge_layer=book`, `visibility=reference`,
  sin asignar sesión. El extractor selecciona el prompt según perfil.

## 9. Cambios en el writer Neo4j

- Campos opcionales con **SET dinámico** (solo se escriben si tienen valor: no
  sobrescriben nodos antiguos con null).
- Trazabilidad completa en nodos y relaciones (source_id/kind/path/hash,
  extractor_version, prompt_version, knowledge_layer, visibility).
- Nodo `Session` + `APPEARS_IN` + sellado temporal (source_session/first_seen).
- Detección de imágenes locales (`/mnt/nextcloud-rol/<ws>/_media/<cat>/<slug>.<ext>`),
  solo lectura, sin descargar ni generar.
- Semántica ok/dubious/invalid: inválidas se descartan; dudosas se escriben con
  `manual_review_required=true`.
- `review_status` en todos los nodos/relaciones.

## 10. Cambios en auditoría [AUDIT]

Añade: nodes_created/updated, auto_created_nodes, relationships_written,
relaciones normalizadas/descartadas_sin_mapeo/inválidas_semántica/dudosas,
semantic_warnings, y conteo por tipo (characters/creatures/locations/events/
tasks/sessions/combats + detalle completo), knowledge_layer/visibility.

## 11. Resultado py_compile

`PY_COMPILE_ALL_OK` para rpg_schema.py, ingest_rpg.py, rpg_extraction_prompt.py,
job_store.py, access_store.py.

## 12. Resultado pytest

`8 passed` (app/tests/). Sin regresiones.

## 13. Resultado prueba creatures/locations/timeline

Perfil transcript, source-id `test_creatures_locations_timeline`, source-kind
`test`, con `--session-number 4 --session-title "El Santuario abandonado"`.
Estado del documento: **complete (1/1 chunks ok)**.

## 14. Nodos creados por tipo (prueba)

Character=3 (Kakita Asuka, Kimi, Bayushi Hisao), Creature=1 (Oni de la Montaña
Negra), Spirit=1 (Espíritu del Río), Location=3 (Bosque Viejo, Santuario
abandonado, Puente Viejo), Clan=1 (Clan Escorpión), Object=1 (Máscara rota),
Concept=2 (Grupo de la sesión, Culto del Pozo Viejo), Session=1 (El Santuario
abandonado, nº 4). Todos con `knowledge_layer=test`, `visibility=narrator`,
`review_status=auto_extracted`, `source_session=4`.

## 15. Relaciones creadas por tipo (prueba)

Narrativas/conocimiento (con etiqueta ES): HAS_FOUGHT (Asuka→Oni), ATTACKED
(Oni→Asuka), SUSPECTS (Kimi→Oni), HAS_HEARD_ABOUT (Kimi→Culto), HAS_TALKED_TO
(Kimi→Espíritu del Río), DISCOVERED (Espíritu→Máscara; Grupo→Culto), INVESTIGATES
(Grupo→Culto). Más 12 `APPEARS_IN` hacia la Session. Todas con source_id,
source_kind, review_status. Nodo Session enlazado correctamente.

## 16. Warnings semánticos

0 en la prueba final. El registro de dudosas/inválidas se escribe en
`output/review/semantic_warnings.md`.

## 17. Consulta Cypher de verificación

```cypher
MATCH (n:Entity {workspace:'leyenda', source_id:'test_creatures_locations_timeline'})
RETURN n.entity_type, count(n) ORDER BY count(n) DESC;

MATCH (a:Entity {workspace:'leyenda'})-[r]->(b:Entity {workspace:'leyenda'})
WHERE r.source_id='test_creatures_locations_timeline'
RETURN a.canonical_name, type(r), r.relation_label_es, b.canonical_name,
       r.source_kind, r.review_status;

MATCH (s:Session {workspace:'leyenda'})
RETURN s.canonical_name, s.session_number, s.session_date, s.knowledge_layer;
```

## 18. Qué queda pendiente

- **Recall del modelo 7B**: qwen2.5:7b extrae bien entidades pero de forma
  volátil las relaciones (entre ejecuciones varía). Para producción conviene un
  modelo mayor o few-shot reforzado. No es un fallo del pipeline.
- **Refinamiento semántico**: `HAS_FOUGHT` con destino Lugar (visto una vez)
  debería degradarse a `FOUGHT_AT`/dudosa. Añadir HAS_FOUGHT a las reglas de
  destino-lugar en `_check_relation_semantics`.
- **Nodos históricos** (pp.1-40): 92 sin source_id / 51 sin source_kind previos a
  los fixes. No se tocan en esta fase (requiere re-proceso controlado).
- **Duplicados previos** (Uso/Mirumoto Uso, City of Gold ×2) pendientes de fusión.
- **Fuentes externas web/youtube en cola**: diseño + cola listos; falta el worker
  que consume `jobs.db` y la integración web (trafilatura no instalado aún).
- **Visor, panel de fuentes, panel usuarios/visibilidad**: solo diseño; sin
  implementar (API/UI futuras).
- **Reglas de visibilidad por personaje**: schema y relaciones soportadas; la
  aplicación de filtros vive en el visor/API (futuro).

## 19. Confirmación

**No se procesaron más libros ni páginas del GM Guide.** Solo se ejecutó la prueba
mínima sobre datos de test. Neo4j de campaña intacto salvo los nodos de test.

## 20. Siguiente paso recomendado

1. Añadir HAS_FOUGHT/HAS_SEEN a las reglas de destino-lugar (semántica).
2. Probar el perfil `book` en 5–10 páginas del GM Guide (marca knowledge_layer=book)
   y revisar recall.
3. Implementar el worker de la cola `jobs.db` para audio Nextcloud (una prueba
   individual antes de lotes).
4. Cuando el modelo de datos esté aceptado, empezar el visor de solo lectura
   (vistas de `VISOR_DESIGN.md`).

---

## Anexo A — Fuentes externas (YouTube / web / audio)

- **Cómo se representan**: nodos `Document`/`Transcript` con `source_kind`
  (`youtube`/`web`/`audio`) y `source_url`/`source_title`/`source_author`;
  relaciones `EXTRACTED_FROM`, `APPEARS_IN`, `SOURCE_OF`, `HAS_TRANSCRIPT`.
- **Campos nuevos**: la CLI de `ingest_rpg.py` acepta `--source-kind
  {youtube,web,audio,...}`, `--source-url/--source-title/--source-author`. La cola
  `job_store.py` guarda job_id, workspace, source_kind, URLs, estado, sesión,
  salidas y contadores Neo4j.
- **Cómo se evita procesar sin confirmar**: todo entra como trabajo `pending`/
  `needs_metadata` en `state/jobs.db`; nada se descarga/procesa hasta acción
  explícita. Nextcloud en solo lectura. Validación de rutas/dominios documentada.
- **Panel**: sección "Fuentes / Importar" (formulario URL/ruta + workspace + tipo
  + sesión + visibilidad + capa) y estados por trabajo. Endpoints REST
  documentados en `EXTERNAL_SOURCES_DESIGN.md`.
- **Qué falta para la prueba real**: worker de cola + `property-graph-youtube`
  (ya existe) integrado en cola + extractor web (dependencia no instalada).
- **Comandos de prueba previstos**:
  - Audio: `property-graph-audio <audio> --workspace leyenda` → cola → transcribe → `--source-kind audio`.
  - YouTube: `property-graph-youtube <url> --workspace leyenda` → `--source-kind youtube`, `--source-url`.
  - Web: (pendiente) `property-graph-web <url> --workspace leyenda` → `--source-kind web`.

## Anexo B — Conocimiento por personaje y usuarios

- **Schema**: 17 relaciones de conocimiento + propiedades (`known_by_scope`,
  `knowledge_quality`, `known_from_session`, `known_by_party`, `known_publicly`,
  `shared_from/to_character`, `shared_at_session`) en nodos y relaciones.
- **Extracción**: el prompt detecta conocimiento explícito (HAS_SEEN/HAS_FOUGHT/
  HAS_HEARD_ABOUT/TELLS…) y NO asume conocimiento no explícito. Validado en la
  prueba (Asuka HAS_FOUGHT Oni; Kimi HAS_TALKED_TO Espíritu; Kimi HAS_HEARD_ABOUT
  Culto). No creó conocimiento para personajes ausentes.
- **Usuarios-personajes**: `access_store.py` (SQLite `state/access.db`) con
  `user_character_link` (estados pending/approved/rejected/revoked/assigned,
  admin-assign y user-request, personaje activo por workspace),
  `user_workspace_permission` (permisos granulares por bóveda) y `access_audit_log`
  (7 eventos). Selftest OK.
- **Modos de visualización** y **reglas de visibilidad** (por sesión y por
  personaje) documentados en `KNOWLEDGE_VISIBILITY_DESIGN.md` y
  `USERS_CHARACTERS_DESIGN.md`. La aplicación de filtros es responsabilidad del
  visor/API (futuro); el grafo ya guarda todo lo necesario.

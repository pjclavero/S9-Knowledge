# CHANGELOG — S9 Knowledge

Formato basado en Keep a Changelog. Fechas en ISO-8601.

## [Unreleased]

### Documentación — 2026-07-13

- Auditoría completa de VM105 y cierre documental de fases 0A y 0B.
- Commit auditado: `1fd94b85` (v0.2.5b). Estado verificado: Neo4j 199 nodos / 140 relaciones,
  visor HTTP 200 en todos los endpoints, 2 servicios systemd activos, guard de ingesta confirmado.
- Tests verificados: 196 recopilados, 155 aprobados, 41 fallidos (deuda técnica funcional — semántica del grafo, jobs, multimedia, visor; guard de ingesta 16/16 confirmado).
- Nuevo informe de baseline: [`docs/24-vm105-baseline-and-verification.md`](docs/24-vm105-baseline-and-verification.md).
- Corrección: `docs/06-viewer-panel.md` — visor marcado como en producción (no "no implementado").
- Corrección: `docs/05-data-engine.md` — cifra de tests actualizada (196/155 vs histórico 8/8).

### Added (inicial)
- Repositorio Git inicial con instantánea del proyecto (`data-engine/` + `docs/`).
- Documentación base: README, ROADMAP, `docs/00-vision` … `docs/10-clone-on-windows`.
- `.gitignore` y `.env.example` seguros.

## data-engine — 2026-07-10/11

### Added
- Schema RPG **1.5.0**: nuevos tipos de nodo (Creature, NonHuman, Spirit, Demon,
  Beast, Region, Group, Artifact, Encounter, Combat, Session, Transcript, Image);
  113 tipos de relación con etiquetas en español; vocabularios controlados
  (attitude, status, danger_level, visibility, knowledge_layer, review_status,
  known_by_scope, knowledge_quality); ~200 normalizadores ES/inglés.
- Campos opcionales de entidad/relación: metadatos temporales y de sesión,
  imágenes, estado de revisión y **capa de conocimiento por personaje**.
- Prompt RPG **1.4.0**: perfil transcript ampliado (criaturas/espíritus/combate),
  `SYSTEM_PROMPT_BOOK`, sección "CONOCIMIENTO DE PERSONAJES".
- Writer Neo4j: SET dinámico de campos opcionales, nodo `Session` + `APPEARS_IN`,
  sellado temporal, detección de imágenes locales, validación semántica
  (ok/dubious/invalid), `review_status`, auditoría `[AUDIT]` ampliada, nuevas CLI
  (`--source-kind`, `--session-*`, `--visibility`, `--knowledge-layer`, `--source-url/title/author`).
- Cola de trabajos `app/jobs/job_store.py` (SQLite `state/jobs.db`).
- Acceso `app/access/access_store.py` (usuario-personaje + permisos + audit log).
- Documentos de diseño: VISOR, EXTERNAL_SOURCES, KNOWLEDGE_VISIBILITY,
  USERS_CHARACTERS, RPG_GRAPH_MODEL_UPDATE, INFORME_ENTREGA.

### Verified
- `py_compile` OK en todos los módulos; `pytest` 8/8.
- Prueba end-to-end (source_id `test_creatures_locations_timeline`, perfil
  transcript, sesión 4): estado `complete`; Session + APPEARS_IN + relaciones de
  conocimiento (HAS_FOUGHT, HAS_TALKED_TO, HAS_HEARD_ABOUT, DISCOVERED) escritas
  con trazabilidad completa.

### Notes
- Recall de relaciones limitado por el modelo qwen2.5:7b (volátil entre
  ejecuciones); no es un fallo del pipeline.
- Nodos históricos (pp.1-40) sin source_id/kind previos a los fixes: no tocados.

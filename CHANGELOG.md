# CHANGELOG — S9 Knowledge

Formato basado en Keep a Changelog. Fechas en ISO-8601.

## [Unreleased]

### 2026-07-13 — Prioridad 1: Backup real, restore aislado, rollback laboratorio

#### Operaciones
- Primer backup real de Neo4j producción ejecutado (parada ~25 s, 132 KB, SHA256 c3179c01...)
- Restore en instancia aislada verificado: 199 nodos, 140 relaciones, 14 labels, 2 índices — idéntico a producción
- Rollback por `source_id` validado en laboratorio con datos sintéticos (patrón Cypher transaccional)
- Copia externa a yggdrasil completada y verificada: 2026-07-14 01:07 UTC, SHA256 coincide en destino

#### Limpieza de repositorio
- PRs obsoletos #4, #7, #8 cerrados con justificación documentada
- Ramas remotas huérfanas eliminadas: audit/test-failures-20260713, feat/neo4j-backup-restore-foundation, docs/session-final-report-20260713, docs/coordinator-final-report-20260713, docs/phase-0a-0b-baseline-20260713
- Repositorio: 0 PRs abiertos, ramas activas solo con trabajo en curso

#### Documentación
- docs/32: informe completo de validación de Prioridad 1
- docs/29, docs/26, docs/02, ROADMAP, CHANGELOG, INDEX, dossier: actualizados
- docs/33: plan de evaluación para Prioridad 2

### 2026-07-13 — Tests y CI (commit cef9233)

#### Fixed

- Eliminar `data-engine/app/__init__.py` vacío: registraba el directorio
  como paquete Python `app`, colisionando con `viewer/app` en corrida combinada y
  causando 5 errores de colección.
- Eliminar `data-engine/app/tests/__init__.py` y `viewer/tests/__init__.py` vacíos:
  causaban `ImportPathMismatchError` en corrida combinada.
- Reescribir `conftest.py` raíz con rutas relativas (Path(__file__).parent).
- Suite combinada: 220 passed, 0 errores de colección, 0 fallidos.
- `export_silverbullet.py`: ruta sys.path relativa (antes hardcoded /opt/).

#### Added

- `.github/workflows/ci.yml`: 4 jobs (data-engine, viewer, combined, check-imports), Python 3.13.
- `docs/31-test-remediation-and-ci-report.md`: informe de remediación y CI.

### 2026-07-13 — Auditoría inicial (historial)

#### Auditoría inicial de VM105 (estado antes de correcciones)
- Estado verificado en commit `1fd94b85` (v0.2.5b): 196 recopilados, 155 aprobados, 41 fallidos.
- Los 41 fallos eran deuda técnica funcional (semántica del grafo, jobs, multimedia, visor).
- Guard de ingesta 16/16 confirmado en estado histórico.
- Baseline: [`docs/24-vm105-baseline-and-verification.md`](docs/24-vm105-baseline-and-verification.md).
- Estado corregido posteriormente a 220/220 (commit cef9233).

### Fixed — 2026-07-13 (rama fix/tests-imports-cache-and-ci)

- Eliminar `data-engine/app/__init__.py` vacío: el archivo registraba el directorio
  como paquete Python `app`, colisionando con `viewer/app` en corrida combinada y
  causando 5 errores de colección.
- Eliminar `data-engine/app/tests/__init__.py` y `viewer/tests/__init__.py` vacíos:
  causaban `ImportPathMismatchError` en corrida combinada.
- Reescribir `conftest.py` raíz con documentación clara de por qué se insertan
  `data-engine/app` y `viewer/` en sys.path.
- Suite combinada: 220 passed, 0 errores de colección, 0 fallidos.

### Added — 2026-07-13 (rama fix/tests-imports-cache-and-ci)

- `.github/workflows/ci.yml`: 4 jobs (data-engine, viewer, combined, check-imports).
  Sin dependencias externas (no Neo4j real, no Ollama, no Nextcloud).
- `docs/31-test-remediation-and-ci-report.md`: informe de remediación y CI.

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

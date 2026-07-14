# Índice de documentación — S9 Knowledge

## Documentación del repositorio (`docs/`)

- [00 · Visión](00-vision.md)
- [01 · Arquitectura](01-architecture.md)
- [02 · Estado actual](02-current-state.md) y [project dossier and checklist.md](docs/project%20dossier%20and%20checklist.md)— qué está HECHO y qué NO
- [03 · Fases](03-phases.md)
- [04 · Estructura del repositorio](04-repository-structure.md)
- [05 · Motor de datos (data-engine)](05-data-engine.md)
- [06 · Visor y panel](06-viewer-panel.md)
- [07 · Usuarios, personajes y permisos](07-users-permissions.md)
- [08 · Despliegue en VM105](08-deployment-vm105.md)
- [09 · Auditar antes de trabajar](09-audit-before-work.md)
- [10 · Clonar en el PC (Windows)](10-clone-on-windows.md)
- [11 · Revisión de calidad de datos](11-data-quality-review.md)
- [13 · Prueba de transcripción de vídeo](13-video-transcription-test.md)
- [14 · Worker de ingesta multimedia](14-multimedia-ingestion-worker.md)
- [15 · Jobs worker y panel](15-jobs-worker-panel.md)
- [18 · Glosario L5A: transcripción, normalización y corrección](18-l5a-transcription-glossary-plan-and-test.md)
- [20 · Revisión de datos e ingesta aprobada](20-data-review-and-approved-ingest.md)
- [21 · Acceso externo y seguridad](21-external-access-and-security.md)
- [22 · Instalación y replicabilidad](22-installation-and-replicability.md)
- [23 · Knowledge Packages: export/import](23-knowledge-packages.md)
- [24 · Baseline VM105 y Verificación Fase 0A](24-vm105-baseline-and-verification.md) — **Informe de auditoría verificable 2026-07-13**
- [30 · Informe coordinador — Cierre Fase 0 y Prioridad 1](30-coordinator-final-report.md) — Consolidado: PR #3, VM105 sync, tests (2 causas raíz), backup/restore lab, rollback diseño
- [31 · Remediación de tests y CI](31-test-remediation-and-ci-report.md) — **220/220 passed, 0 errores de colección; CI añadido 2026-07-13**
- [32 · Backup y restore de producción — Validación P1](32-production-backup-restore-validation.md) — Backup real 132 KB, restore verificado, copia externa completada
- [33 · Plan de evaluación del extractor — Prioridad 2](33-extractor-quality-benchmark-plan.md) — Plan de benchmark: corpus, métricas, umbrales, criterios de ingesta
- [34 · Resultados del benchmark del extractor — Prioridad 2](34-extractor-quality-benchmark-results.md) — 35/35 runs sin fallos; métricas F1 pendientes (fix formato corpus requerido)

## Documentos de diseño generados en el servidor (`docs/current/`)

- **INFORME_ENTREGA.md** — informe de entrega de la actualización del grafo.
- **RPG_GRAPH_MODEL_UPDATE.md** — actualización del modelo RPG (auditoría previa).
- **VISOR_DESIGN.md** — diseño del visor y modelo de datos para vistas.
- **EXTERNAL_SOURCES_DESIGN.md** — fuentes externas (YouTube/web/audio) + cola.
- **KNOWLEDGE_VISIBILITY_DESIGN.md** — visibilidad por conocimiento de personaje.
- **USERS_CHARACTERS_DESIGN.md** — usuarios/personajes multi-campaña + permisos.

## Estado y pendientes

- Estado consolidado: [02 · Estado actual](02-current-state.md).
- Infraestructura/servidor (dominio, Basic Auth, seguridad, CPU): repo `pjclavero/s9-server`.
- [26 · Operaciones: Backup y Restore de Neo4j](26-operations-backup-and-restore.md) — Método verificado, backup real ejecutado 2026-07-13
- [27 · Runbook de Ingesta Controlada](27-controlled-ingest-runbook.md) — Checklist + guard doble + rollback de emergencia
- [28 · Migraciones del Grafo y Rollback por source_id](28-graph-migrations-and-rollback.md) — Diseño completo, patrón Cypher validado en lab
- [29 · Informe de Preparación y Ejecución Prioridad 1](29-priority-1-readiness-report.md) — Historial de lab + **dictamen de ejecución: ver docs/32**
- [32 · Validación de Backup Real en Producción 2026-07-13](32-production-backup-restore-validation.md) — Backup, restore aislado, rollback lab, copia externa — **COMPLETADA ✅**
- [33 · Plan de evaluación del extractor — Prioridad 2](33-extractor-quality-benchmark-plan.md) — Corpus, métricas, criterios, condiciones para ingesta real

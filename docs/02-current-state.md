# 02 · Estado actual

> Última verificación en VM105: **2026-07-13–14** — commit `cef9233` desplegado (fix: make test suite reproducible and add CI).
> Tests: **249 recopilados, 249 aprobados**, 0 fallidos, 0 errores de colección (rama `feat/priority-2-extractor-benchmark`, commit `13fcab9`).
> Benchmark del extractor (Prioridad 2) — ver [docs/34](34-extractor-quality-benchmark-results.md). Mejora Prioridad 2.1 (ver [docs/36](36-extractor-quality-improvement-results.md)): hybrid pasa los umbrales de entidad (F1 0.806, P 0.851, R 0.775); relaciones aún <0.60 y excluidas de autoaprobación. Confirmatorio de 7 fuentes (docs/37, run 20260714-151119, 49 OK): hybrid P 0.878 / R 0.823 / F1 0.846 (pasa umbrales de entidad); relaciones F1 0.163 (<0.60). Revisión humana total (`S9K_REVIEW_POLICY=full_human_review`) impuesta por código (0 autoaprobados, procedencia exigida en ingest). Dictamen 2.1: **COMPLETADA — PREPARADA PARA INGESTA CONTROLADA CON REVISIÓN TOTAL; primera ingesta PREPARADA, NO EJECUTADA.**
> CI: GitHub Actions activa, 4 jobs verdes (data-engine, viewer, combined, check-imports).
> Informe de auditoría histórica (v0.2.5b): [docs/24-vm105-baseline-and-verification.md](24-vm105-baseline-and-verification.md) — estado anterior a cef9233.
> Informe de remediación de tests y CI: [docs/31-test-remediation-and-ci-report.md](31-test-remediation-and-ci-report.md).
> Backup y validación de Prioridad 1: [docs/32-production-backup-restore-validation.md](32-production-backup-restore-validation.md).
> Revisar también [project dossier and checklist.md](project%20dossier%20and%20checklist.md).

Instantánea verificada a 2026-07-13 (basada en auditoría de VM105 del mismo día).
> Transcripción de vídeo (docs/40, 2026-07-15): faster-whisper medium APTA CON REVISIÓN DE SEGMENTOS CONFLICTIVOS (91% auto-aceptable; conflictos = nombres propios). Referencia humana pendiente. Sin ingesta.

> IA externa NVIDIA (docs/42, 2026-07-15): paquete `external_ai` + CLI en **modo sombra** (revisión multi-modelo, consenso, calibración). shadow_mode obligatorio, sin escritura en Neo4j. 22 tests. Validación real pendiente de API key.

## HECHO

### Motor de datos y grafo
- `data-engine/app/schemas/rpg_schema.py` — **schema v1.5.0** (27 tipos de nodo,
  113 relaciones, 113 etiquetas ES, vocabularios controlados, normalizadores).
- `data-engine/app/prompts/rpg_extraction_prompt.py` — prompt v1.4.0.
- `data-engine/app/ingest_rpg.py` — writer Neo4j (trazabilidad, metadatos, Session).
- `data-engine/app/jobs/job_store.py` + `jobs/worker.py` — cola SQLite **con worker** (echo/noop).
- `data-engine/app/access/access_store.py` — usuario-personaje + permisos + audit (no aplicado en UI).

### Visor
- **Visor web desplegado** (FastAPI/uvicorn, `s9-knowledge-viewer.service`, puerto 8088).
- `/graph` (vis.js), `/jobs` (panel de cola), `/reviews` (panel de revisión enriquecido).
- `/reviews`: lista de fuentes con badge de origen (local/external/manual/imported),
  contadores por estado. Detalle de fuente: metadatos del paquete (origin, producer,
  model, confidence externa/local), cola de revisión con confianza y motivo de decisión
  por ítem, informe de calidad (`quality_report.json/.md`) cuando existe, estado de
  todos los ficheros del pipeline.
- Fix móvil: la ficha lateral ya no tapa el grafo (se cierra/abre al tocar).

### Multimedia y transcripción
- Worker de ingesta multimedia (`data-engine/app/media/`) — escanea Nextcloud, extrae audio, transcribe.
- faster-whisper operativo con audios reales de Nextcloud. **`medium` recomendado** (0% error en nombres L5A vs 67% en `small`); no paralelizar (RAM).
- Glosario L5A + normalizador determinista (`data-engine/app/glossary/`) — ver [18](18-l5a-transcription-glossary-plan-and-test.md).

### Pipeline de revisión de datos (rama feat/data-processing-final-v0.2.5)
- `data-engine/app/review/` — segment → classify → extract → validate → resolve → decide → approved_payload.
- CLI `data_review.py`, `audit-graph`, ingesta **solo dry-run**:
  - `ingest_approved.py` aborta con mensaje de autorización si se invoca sin `--dry-run`.
  - Sin `--dry-run`, no hay escritura en Neo4j bajo ninguna circunstancia.
  - Doble guard: (1) el propio CLI requiere `--dry-run`; (2) el writer aborta si
    no lo recibe. Ver [20](20-data-review-and-approved-ingest.md).
- Revisión humana mínima: solo los candidatos dudosos llegan a `review.md`.

## Bloque de tratamiento de datos — cerrado (v0.2.5b)

El bloque de tratamiento de datos está completo y protegido:

- **Transcripción/fuente** — faster-whisper medium, rclone mount Nextcloud, pipeline multimedia
- **Segmentación** — por tiempo/silencio antes de extraer
- **Extracción endurecida** — heurística con anti-falsos-positivos; LLM/hybrid disponibles
- **Stopwords** — lista ES, filtra términos vacíos antes de aprobar
- **Glosario por workspace** — SQLite, 1044 términos L5A, normalizador determinista
- **Validación** — schema, evidence, origin, workspace, schema_version
- **Resolución** — similitud con Neo4j, delta ambigüedad 0.10, variantes EN/ES
- **decision_reason** — 21 razones vocabulario controlado por decisión
- **approved_payload** — schema_version 1.0, origin, source_kind, generated_at
- **review_queue** — candidatos que requieren revisión humana antes de ingestar
- **ingest-approved protegido** — doble guard: `--dry-run` + `S9K_ALLOW_REAL_INGEST=true`
- **`/reviews`** — panel web con origin, decision_reason, quality_report por fuente
- **audit-graph** — solo lectura, detecta anomalías en Neo4j sin escribir
- **export/import** — 4 tipos de paquete, sanitización de rutas/IPs/tokens
- **Soporte procesamiento externo** — ExternalReviewRequest/Response, ImportedCandidatePackage
- **Replicabilidad preparada** — variables documentadas, modos A/B/C, hardcode audit
- **Neo4j protegido** — puertos cerrados a 127.0.0.1, sin escritura sin doble guard
- **Sin escritura accidental** — external/imported → needs_review, nunca auto_approve

### Infraestructura y seguridad (ver [21](21-external-access-and-security.md))
- Acceso externo: `https://knowledge.seccionnueve.duckdns.org` (nginx VM104 + Basic Auth).
- Neo4j cerrado a solo 127.0.0.1 (antes expuesto en LAN/Tailscale).
- VM105 ampliada a 6 vCPUs.

### Integración
- **main** (cef9233): 220/220 tests, CI 4 jobs verdes, scripts de backup operativos, docs/26–32.
- Ramas activas: `feat/l5a-transcription-glossary` (glosario), `feat/data-processing-final-v0.2.5` (pipeline de revisión) y otras — pendientes de integración en la secuencia correcta.

## NO HECHO / pendiente

- **Calidad del extractor (Prioridad 2).** El pipeline implementa tres modalidades: heurístico, LLM (qwen2.5:7b vía Ollama) e híbrido. El modo heurístico produce falsos positivos conocidos (`Llevás`/`Todo`/`Como` como Character). Los modos LLM/híbrido se evaluaron con el benchmark real (run `20260714-094125`, ver docs/34): F1 entidades agregado hybrid 0.728 / llm 0.718 (precisión llm 0.810, recall hybrid 0.856); relaciones F1≈0; precisión de autoaprobación 0.85. Ningún modo alcanza los umbrales de autoaprobación. **La ingesta real a Neo4j sigue bloqueada** (dictamen Prioridad 2: PARCIAL — REQUIERE CORRECCIONES). Ver docs/34 para las métricas y docs/33 para el plan.
- Gestión de usuarios y aplicación real de filtros de visibilidad en API/UI.
- Login propio del visor (hoy solo Basic Auth en el proxy).
- Importación web real (trafilatura/readability) e integración de YouTube en la cola.
- Fusión de duplicados del grafo (audit-graph los detecta, no los corrige).
- Export/import externo de paquetes de revisión: preparado, no completado (ver docs/22
  cuando esté disponible).

## Backup y recuperación

**Backup real de Neo4j**: ✅ Ejecutado y verificado 2026-07-13
- Método: neo4j-admin database dump (Community Edition, único método consistente)
- Parada real del contenedor: ~25 segundos
- Archivo: neo4j-20260713-174909/neo4j.dump — 132 KB — SHA256: c3179c01...
- Checksum SHA256 generado y verificado en origen
- Restore en instancia aislada: VERIFICADO (199 nodos / 140 relaciones / 14 labels — idéntico a producción)
- Rollback por source_id: VALIDADO en laboratorio con datos sintéticos
- Copia externa a yggdrasil: VERIFICADA 2026-07-14 (SHA256 coincide, permisos 700 root:root)
- Scripts: scripts/backup/neo4j-backup.sh, neo4j-restore.sh, neo4j-rollback-dryrun.sh
- Documentación completa: [docs/32-production-backup-restore-validation.md](32-production-backup-restore-validation.md)

## Limitaciones conocidas

- Extractor heurístico con falsos positivos (ver arriba) — no ingestar sin revisar.
- Recall de **relaciones** limitado con qwen2.5:7b; entidades estables.
- Nodos históricos sin `source_id`/`source_kind` (~87/~51) detectados por audit-graph.
- Corrección LLM de transcripción (qwen2.5:7b, bloque completo) no preserva timestamps → queda deshabilitada; se usa el normalizador determinista.
- `HAS_FOUGHT` con destino Lugar debería degradarse a `FOUGHT_AT`.

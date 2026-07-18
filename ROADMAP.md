# ROADMAP — S9 Knowledge

Ver [project dossier and checklist.md](docs/project%20dossier%20and%20checklist.md) para el estado detallado por componente.

---

## Secuencia de prioridades

Estados: **COMPLETADO · PARCIAL · PENDIENTE · BLOQUEADO · DEPRECADO**.

```
Auditoría inicial (v0.2.5b):       COMPLETADO
Schema RPG:                        COMPLETADO
Data engine / pipeline revisión:   COMPLETADO
Benchmark del extractor:           COMPLETADO (dictamen: relaciones por debajo de umbral)
Revisión externa (NVIDIA sombra):  COMPLETADO (validación real de proveedor: PENDIENTE)
Writer de ingesta controlada:      COMPLETADO (doble guard)
Visor web:                         COMPLETADO (desplegado por releases)
Login propio del visor:            COMPLETADO (Basic Auth retirada)
Roles y sesiones:                  PARCIAL (login+roles ok; visibilidad por personaje PENDIENTE)
Acceso externo (HTTPS):            COMPLETADO
Despliegue por releases:           COMPLETADO (RC5.1 activa; resolución forward-ref corregida)
Healthcheck operativo:             COMPLETADO
Timer horario del healthcheck:     COMPLETADO (OnCalendar=hourly, Persistent)
Panel de revisión:                 PARCIAL (lectura ok; acciones desde UI PENDIENTE)
Permisos RPG en backend:           PENDIENTE
Visibilidad por personaje:         PENDIENTE
Worker multimedia:                 PARCIAL (transcripción manual ok; handlers automáticos PENDIENTE)
OCR:                               PENDIENTE
ASR (integración en cola):         PENDIENTE
External burst B2/B3:              PENDIENTE
Primera ingesta real:             BLOQUEADO (doble guard; no autorizada)
Limpieza histórica del grafo:      PENDIENTE
Backup/restore periódico:          PARCIAL (backup+restore validados; automatización periódica PENDIENTE)
```

### Prioridades siguientes

- **P0** — contratos de review/ingest.
- **P1** — panel de revisión operativo (acciones desde UI).
- **P1** — permisos RPG en backend.
- **P2** — primera ingesta controlada (requiere autorización explícita).
- **P2** — worker real y external burst (B2/B3).
- **P3** — limpieza histórica del grafo.
- **P3** — restore periódico programado.

---

## Prioridad 0 — Motor de datos y repositorio (COMPLETADA ✅)

- Schema RPG v1.5.0: 27 tipos de nodo, 113 relaciones, vocabularios controlados.
- Pipeline de revisión: segment → classify → extract → validate → resolve → decide → approved_payload.
- Extractor: modos heurístico, LLM (qwen2.5:7b) e híbrido implementados.
- Tests: suite verde (recuento actual en [docs/project-status.yaml](docs/project-status.yaml)).
- CI: GitHub Actions en verde (Python 3.13).
- Producción: RC5.1 (`47bc314`) desplegada por releases; ver [docs/02-current-state.md](docs/02-current-state.md).

---

## Prioridad 1 — Backup, Restore y Rollback (COMPLETADA ✅)

- [x] Backup/restore de Neo4j verificado en lab (2026-07-13)
- [x] Scripts backup/restore en main (`scripts/backup/`)
- [x] Backup real de producción ejecutado (2026-07-13 21:49 UTC, 132 KB, 25 s parada)
- [x] Restore real en instancia aislada verificado (199 nodos, 140 relaciones, idéntico a producción)
- [x] Rollback por source_id validado en laboratorio con datos sintéticos
- [x] Documentación de operaciones actualizada (docs/26–32)
- [x] Copia externa a yggdrasil verificada (2026-07-14, SHA256 coincide)

**Dictamen:** COMPLETADA — ver [docs/32-production-backup-restore-validation.md](docs/32-production-backup-restore-validation.md)

### P1.1 — Endurecimiento operativo pendiente

- [x] Copia externa verificada a yggdrasil (2026-07-14)
- [ ] Automatización de copia en neo4j-backup.sh
- [ ] Timer systemd para backup semanal
- [ ] Script transaccional de rollback con --dry-run
- [ ] Prueba periódica programada de restore

---

Transcripción de vídeo (docs/40): faster-whisper medium APTA CON REVISIÓN DE SEGMENTOS CONFLICTIVOS (91% auto-aceptable; conflictos = nombres propios). Referencia humana pendiente para WER definitivo.

IA externa NVIDIA (docs/42): revisión multi-modelo + consenso + calibración en **modo sombra** (implementado, sin escritura). Fase B (lotes externos) diseñada, pendiente. Validación real pendiente de API key.

## Prioridad 2 — Calidad del extractor y del pipeline (EN DEFINICIÓN)

El bloqueo real no es ausencia de LLM — los tres modos (heurístico, LLM, híbrido) están implementados. El bloqueo es la falta de validación de calidad sobre un corpus representativo.

- [ ] Corpus de evaluación: fuentes representativas con verdad esperada
- [ ] Métricas: precisión, recall, F1, falsos positivos, falsos negativos, duplicados, relaciones inválidas
- [ ] Comparativa: heurístico vs LLM vs híbrido por tipo de fuente
- [ ] Criterio de autoaprobado: umbral verificable
- [ ] Criterio de envío a revisión humana
- [ ] Criterio de rechazo
- [ ] Pruebas de regresión
- [ ] Condiciones para habilitar la primera ingesta real

Ver [docs/33-extractor-quality-benchmark-plan.md](docs/33-extractor-quality-benchmark-plan.md) para el plan de evaluación.

---

## Prioridad 3 — Primera ingesta real controlada (PENDIENTE)

Requiere: Prioridad 1 completa + Prioridad 2 con criterios aceptados.

- [ ] Fuente pequeña y representativa seleccionada
- [ ] Auditoría pre-ingesta del grafo
- [ ] Dry-run completo del pipeline
- [ ] Backup inmediatamente antes
- [ ] Ingesta real con S9K_ALLOW_REAL_INGEST
- [ ] Auditoría post-ingesta
- [ ] Verificación de que el resto del grafo no cambió

---

## Prioridad 4 — Limpieza del grafo histórico (PENDIENTE)

- [ ] Migración controlada de ~87 nodos sin source_id/source_kind
- [ ] Corrección de relaciones semánticamente inválidas (HAS_FOUGHT → FOUGHT_AT)
- [ ] Eliminación de duplicados detectados por audit-graph

---

## Prioridad 5 — Autenticación y seguridad del visor (PARCIAL)

- [x] **Login propio del visor** (formulario con submit explícito, sesiones, CSRF). Basic Auth retirada del proxy. — COMPLETADO
- [x] Usuarios y roles en la app (1 administrador activo). — COMPLETADO
- [ ] Acciones de revisión desde el visor. — PENDIENTE
- [ ] Permisos RPG aplicados en consultas (visibilidad por personaje). — PENDIENTE

---

## Prioridad 6 — Despliegue y operación (COMPLETADA ✅)

- [x] Despliegue por releases inmutables + symlink atómico `current`. — COMPLETADO
- [x] deploy-tools versionados e independientes de la release. — COMPLETADO
- [x] Retención fail-closed y verify-deployment fail-closed. — COMPLETADO
- [x] Resolución de refs remotas (regresión forward-ref corregida, [docs/51](docs/51-deploy-forward-ref-regression.md)). — COMPLETADO
- [x] Healthcheck operativo + timer horario (`OnCalendar=hourly`, Persistent). — COMPLETADO
- [x] RC5.1 (`47bc314`) activa en producción; RC5 conservada como candidata no desplegada. — COMPLETADO

---

## Estado del visor actual (IMPLEMENTADO Y DESPLEGADO)

- `/graph`: vis.js — operativo ✅
- `/jobs`: panel de cola — implementado como base ✅
- `/reviews`: panel de revisión en lectura ✅
- Login propio: **COMPLETADO** (Basic Auth retirada)
- Acciones de revisión desde UI: PENDIENTE
- Permisos RPG en API/UI: PENDIENTE
- Acceso externo: https://knowledge.seccionnueve.duckdns.org (HTTPS, autenticación en la app) ✅

---

## Componentes transversales activos

- Worker genérico: base implementada (job_store.py + worker.py con echo/noop)
- Handlers multimedia completos: PENDIENTE (transcripción faster-whisper operativa en manual)
- Nextcloud mount: rclone-nextcloud-rol.service activo (solo lectura) ✅
- Ollama: qwen2.5:7b en ia-server (192.168.1.157:11434) ✅

# ROADMAP — S9 Knowledge

Ver [project dossier and checklist.md](docs/project%20dossier%20and%20checklist.md) para el estado detallado por componente.

---

## Secuencia de prioridades

```
Prioridad 0: COMPLETADA — Motor de datos, pipeline de revisión, tests, CI
Prioridad 1: COMPLETADA (ver dictamen) — Backup, restore, rollback
Prioridad 2: PARCIAL — REQUIERE CORRECCIONES. Benchmark real ejecutado (run 20260714-094125): F1 ent hybrid 0.728 / llm 0.718 (P llm 0.810, recall hybrid 0.856); relaciones F1≈0; autoaprobación 0.85<0.95. Ver docs/34.
Prioridad 2.1: PARCIAL — MEJORA DEMOSTRADA (run 20260714-121026): hybrid F1 ent 0.806, P 0.851, R 0.775 → **pasa los umbrales de entidad**; relaciones F1 0.089 (<0.60, excluidas de autoaprobación por gate). Primera ingesta DESBLOQUEADA PARA ENTIDADES CON REVISIÓN HUMANA TOTAL. Ver docs/36.
Prioridad 3: PENDIENTE — Primera ingesta real controlada
Prioridad 4: PENDIENTE — Limpieza del grafo histórico
Prioridad 5: PENDIENTE — Autenticación y seguridad del visor
```

---

## Prioridad 0 — Motor de datos y repositorio (COMPLETADA ✅)

- Schema RPG v1.5.0: 27 tipos de nodo, 113 relaciones, vocabularios controlados.
- Pipeline de revisión: segment → classify → extract → validate → resolve → decide → approved_payload.
- Extractor: modos heurístico, LLM (qwen2.5:7b) e híbrido implementados.
- Tests: 220/220 en corrida combinada, 0 errores de colección.
- CI: GitHub Actions con 4 jobs verdes (Python 3.13).
- VM105: commit cef9233 desplegado, working tree limpio.
- Commit: `cef9233`

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

## Prioridad 5 — Autenticación y seguridad del visor (PENDIENTE)

- [ ] Login propio (hoy solo Basic Auth en proxy nginx)
- [ ] Usuarios y roles en API/UI
- [ ] Acciones de revisión desde visor
- [ ] Permisos RPG aplicados en consultas

---

## Estado del visor actual (IMPLEMENTADO Y DESPLEGADO)

- `/graph`: vis.js — operativo ✅
- `/jobs`: panel de cola — implementado como base ✅
- `/reviews`: panel de revisión en lectura ✅
- Login propio: PENDIENTE (Prioridad 5)
- Acciones de revisión desde UI: PENDIENTE
- Permisos RPG en API/UI: PENDIENTE
- Acceso externo: https://knowledge.seccionnueve.duckdns.org (nginx + Basic Auth) ✅

---

## Componentes transversales activos

- Worker genérico: base implementada (job_store.py + worker.py con echo/noop)
- Handlers multimedia completos: PENDIENTE (transcripción faster-whisper operativa en manual)
- Nextcloud mount: rclone-nextcloud-rol.service activo (solo lectura) ✅
- Ollama: qwen2.5:7b en ia-server (192.168.1.157:11434) ✅

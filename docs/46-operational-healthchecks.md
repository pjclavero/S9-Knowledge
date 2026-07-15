# 46 · Observabilidad y healthchecks operacionales (Tarea A)

> Estado: **AUDITORÍA INICIAL / EN CURSO**. Rama `feat/operational-healthchecks` desde `main@40cf75d`.
> Sistema de solo lectura para detectar fallos. **No reinicia servicios ni escribe en Neo4j.**

---

## Auditoría inicial (estado actual)

- Un único servicio systemd en el repo: `viewer/systemd/s9-knowledge-viewer.service` (uvicorn :8088). No hay unit de healthcheck.
- Job store: SQLite en `state/jobs.db` (`data-engine/app/jobs/job_store.py`). Cliente de lectura en `viewer/app/jobs_client.py`.
- Grafo: Neo4j en contenedor (`bolt://127.0.0.1:7687`), password por fichero. Proveedor `viewer/app/providers/neo4j_provider.py` (solo lectura).
- Auth: `viewer/app/auth/db.py` (SQLite `viewer/state/auth.db`), ya desplegada.
- External AI (`data-engine/app/external_ai/`) y burst (`data-engine/app/external_processing/`): desactivados por defecto.
- Nextcloud/rclone: mount `rclone-nextcloud-rol.service` en `/mnt/nextcloud-rol` (fuera del repo).
- Backups: `scripts/backup/neo4j-backup.sh`; docs/26 y docs/32.
- No existe endpoint ni CLI de salud.

## Declaración de ámbito

**Archivos que se crearán/modificarán (solo esta tarea):**
- `data-engine/app/health/` — paquete de checks (viewer, neo4j, ollama, nextcloud/rclone, job_store, auth_db, external_ai, burst, filesystem, backups, systemd) + agregador + modelos de estado.
- `viewer/app/routers/admin.py` (o nuevo router) — `GET /api/admin/health` y `GET /admin/health` (solo `admin`, reutilizando `require_admin`/`require_api_role("admin")`).
- CLI `s9k-health` (`data-engine/app/cli/health.py`): `check`, `check --component`, `report`, `json`; exit codes 0/1/2/3.
- `viewer/systemd/s9-knowledge-healthcheck.{service,timer}` (cada 5 min).
- `docs/46-operational-healthchecks.md` (este documento).
- Tests: `data-engine/app/tests/test_health/` y tests de la API admin en `viewer/tests/`.

**Módulos que NO se tocan:** writer de ingesta (`review/ingest_approved.py`), runtime de `external_processing`, escrituras en Neo4j, internals de auth (solo lectura de `auth.db`), templates de datos.

**Documentos:** solo `docs/46`. **No** se editan README/CHANGELOG/ROADMAP/`docs/INDEX` (reconciliación global en Tarea E).

**Dependencias:** ninguna nueva (stdlib + `neo4j`/`httpx` ya presentes).

**Límites duros:** 0 escrituras en Neo4j, 0 reinicios de servicios, 0 secretos en salida, `details` sanitizados.

## Contratos (estado por componente)

```
component, status(HEALTHY|DEGRADED|UNHEALTHY|UNKNOWN), checked_at, latency_ms, message, details
```

Umbrales disco: warning ≥ 80 %, critical ≥ 90 %. Exit codes CLI: 0 healthy · 1 degraded · 2 unhealthy · 3 configuration error.

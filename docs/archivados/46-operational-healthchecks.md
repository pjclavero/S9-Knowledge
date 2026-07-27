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

**Decisión de ubicación:** el paquete vive en **`viewer/app/health/`** (no en `data-engine/`) porque el visor es el servicio siempre activo, con el venv que tiene las dependencias, y así la API/panel y la CLI comparten el mismo módulo sin trucos de `sys.path` en producción.

**Archivos creados (commit funcional inicial):**
- `viewer/app/health/` — `models.py` (contratos), `checks.py` (11 componentes), `runner.py` (agregador + config desde entorno), `storage.py` (último informe JSON 0600).
- `viewer/app/routers/health_admin.py` — `GET /api/admin/health` (`require_api_role("admin")`, JSON) y `GET /admin/health` (`require_admin`, panel); registrado en `viewer/app/main.py`.
- `viewer/app/templates/auth/admin/health.html` — panel específico (extiende `base.html`, sin modificarlo).
- CLI `viewer/app/cli/health.py` (`python -m app.cli.health`): `check [--component]`, `report`, `json`; exit codes 0/1/2/3.
- `viewer/systemd/s9-knowledge-healthcheck.{service,timer}` (oneshot + timer **horario** con `OnCalendar=hourly`, `Persistent=true`, `RandomizedDelaySec=5m`; frecuencia nunca inferior a una hora; **no instalado en producción todavía**).
- `docs/46-operational-healthchecks.md`.
- Tests: `viewer/tests/test_health.py` (34 tests).

**Contrato público fijado (JSON):**
```json
{"overall":"HEALTHY|DEGRADED|UNHEALTHY|UNKNOWN","generated_at":"<iso>",
 "components":[{"component":"<str>","status":"<HealthStatus>","checked_at":"<iso>",
               "latency_ms":<float|null>,"message":"<str>","details":{...sanitizado...}}]}
```
Nombres de componentes: `viewer, neo4j, ollama, nextcloud_rclone, job_store, auth_db, external_ai, burst, filesystem, backups, systemd`.
Rutas API: `GET /api/admin/health` (admin, JSON), `GET /admin/health` (admin, HTML).
Autorización: `require_api_role("admin")` / `require_admin` (reutilizadas de auth).

**Módulos que NO se tocan:** writer de ingesta (`review/ingest_approved.py`), runtime de `external_processing`, escrituras en Neo4j, internals de auth (solo lectura de `auth.db`), templates de datos.

**Documentos:** solo `docs/46`. **No** se editan README/CHANGELOG/ROADMAP/`docs/INDEX` (reconciliación global en Tarea E).

**Dependencias:** ninguna nueva (stdlib + `neo4j`/`httpx` ya presentes).

**Límites duros:** 0 escrituras en Neo4j, 0 reinicios de servicios, 0 secretos en salida, `details` sanitizados.

## Contratos (estado por componente)

```
component, status(HEALTHY|DEGRADED|UNHEALTHY|UNKNOWN), checked_at, latency_ms, message, details
```

Umbrales disco: warning ≥ 80 %, critical ≥ 90 %. Exit codes CLI: 0 healthy · 1 degraded · 2 unhealthy · 3 configuration error.

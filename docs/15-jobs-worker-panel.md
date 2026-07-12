# 15 · Worker y panel de jobs (v0.2.4)

## Qué problema resuelve

Antes de automatizar del todo vídeo/audio/transcripciones/ingesta, el proyecto
necesita una **infraestructura de cola de trabajos genérica**: crear un job,
que un worker lo reclame y procese, ver su estado desde un panel web, y que
nada se pierda si el worker se cae a mitad. Esta fase deja esa base lista
(job_store, worker, CLI, API read-only, panel `/jobs`), **sin implementar
todavía** la lógica real de transcripción/ingesta.

## Auditoría previa (resumen)

- `data-engine/app/jobs/job_store.py` ya existía: cola SQLite para el
  pipeline de fuentes externas (PDF/audio/YouTube/web → Neo4j), con su propio
  vocabulario de estados y campos (`source_kind`, `session_number`,
  `neo4j_nodes_created`, ...). **No se ha duplicado**: esta fase amplía la
  misma tabla `jobs` de forma aditiva.
- `data-engine/app/access/access_store.py` ya existía, completo y con su
  propio `--selftest`, pero sin test pytest. Se añadió cobertura básica
  (`test_access_store.py`) sin tocar el módulo.
- No existía ningún worker que reclamara jobs, ni CLI de gestión, ni endpoints
  ni panel en el visor. Nada de esto estaba conectado al viewer.

## Modelo de jobs (tabla `jobs`, SQLite)

La tabla `jobs` ahora sirve **dos usos** sobre el mismo archivo:

1. **Ingesta de fuentes** (histórico, sin cambios de comportamiento):
   `source_kind` (book/pdf/audio/youtube/...), estados ricos
   (`needs_metadata`, `processing`, `transcribing`, `extracting`, `completed`,
   `ignored`, ...), campos de sesión/Neo4j.
2. **Cola genérica** (esta fase): `job_type`, `priority`, `payload_json`,
   `result_json`, `attempts`/`max_attempts`, `locked_by`/`locked_at`.
   Internamente usa `source_kind='generic'` para satisfacer la restricción
   heredada, pero se identifica por `job_type`.

Las bases de datos `jobs.db` creadas con el esquema antiguo se migran solas
(`ALTER TABLE ADD COLUMN`, idempotente) la próxima vez que se llame a
`init_db()` — no hace falta borrar ni recrear nada.

### Estados

Unión de los dos vocabularios (ver `job_store.VALID_STATUSES`):

- Compartidos: `pending`, `failed`, `cancelled`.
- Cola genérica (esta fase): `running`, `complete`, `skipped`.
- Ingesta de fuentes (histórico): `needs_metadata`, `ready`, `processing`,
  `transcribing`, `extracting`, `completed`, `ignored`.

### Tipos de job previstos (`job_store.KNOWN_JOB_TYPES`)

Solo **`noop`** y **`echo`** tienen handler implementado en
`jobs/worker.py` en esta fase. El resto son placeholders documentados para
fases futuras:

```
noop, echo                                    ← implementados (prueba)
media_probe, audio_extract, transcribe,
write_markdown, ingest_text, audit_duplicates  ← previstos, sin handler aún
```

`job_type` no se valida contra una lista cerrada al crear el job: así el
worker multimedia (fase futura) podrá crear `media_probe`/`audio_extract`/...
sin tener que tocar `job_store.py`. Un job con `job_type` sin handler se marca
**`skipped`** (no es un fallo, solo "todavía no implementado"), con un mensaje
claro en `error_message`.

## Variables de entorno

```env
S9K_JOBS_DB=/opt/knowledge-services/s9-knowledge-repo/state/jobs.db
```

En desarrollo local, si no se define `S9K_JOBS_DB`, se usa
`data-engine/state/jobs.db` (relativo al repo, vía `job_store.DEFAULT_DB_PATH`).
`state/` está en `.gitignore`; **`jobs.db` nunca se commitea**.

## Cómo crear un job `echo` (CLI)

```bash
python data-engine/app/cli/jobs.py create --type echo --workspace leyenda \
    --payload '{"message":"prueba worker"}'
python data-engine/app/cli/jobs.py list --workspace leyenda
```

## Cómo ejecutar el worker una vez

```bash
python data-engine/app/jobs/worker.py --once --limit 1
python data-engine/app/cli/jobs.py list --workspace leyenda
```

El job pasa de `pending` → `running` (reclamado) → `complete`
(`result_json` contiene `{"echo": {"message": "prueba worker"}}`).

Modo continuo opcional (no es un daemon "de verdad", solo un bucle con
`time.sleep` entre sondeos; pensado para pruebas o cron externo, no para
producción todavía):

```bash
python data-engine/app/jobs/worker.py --loop --sleep-seconds 5
```

Otras opciones: `--job-type TYPE` (filtrar), `--workspace WS` (filtrar),
`--dry-run` (no reclama nada, solo informa), `--release-stale-seconds N`
(recupera jobs `running` colgados antes de procesar), `--worker-id NAME`,
`--db PATH` (override explícito de la ruta de la DB).

## Cómo listar/ver jobs por CLI

```bash
python data-engine/app/cli/jobs.py list --workspace leyenda --status pending
python data-engine/app/cli/jobs.py show --id <JOB_ID>
python data-engine/app/cli/jobs.py counts --workspace leyenda
python data-engine/app/cli/jobs.py retry --id <JOB_ID>     # vuelve a pending, attempts=0
python data-engine/app/cli/jobs.py cancel --id <JOB_ID>
```

`retry`/`cancel` son las únicas acciones de escritura, y solo existen en la
CLI — **el panel del visor es de solo lectura** (ver más abajo).

## Cómo abrir el panel `/jobs`

```bash
cd viewer
uvicorn app.main:app --host 127.0.0.1 --port 8088 --reload
```

Abrir:

```
http://127.0.0.1:8088/jobs
http://127.0.0.1:8088/jobs/<JOB_ID>
http://127.0.0.1:8088/api/jobs
http://127.0.0.1:8088/api/jobs/counts
http://127.0.0.1:8088/api/jobs/<JOB_ID>
```

El visor lee `S9K_JOBS_DB` (o el default de `job_store` si no está definida).
Si la base de datos no existe todavía, la API responde:

```json
{"ok": false, "error": "jobs_db_not_found"}
```

y el panel muestra un aviso en vez de romperse. `/graph` no se ve afectado en
absoluto: el panel de jobs es un módulo aparte (`app/jobs_client.py`) que
importa `job_store` de forma perezosa y degrada con seguridad si falla.

## Qué NO hace todavía

- No implementa los handlers reales de `media_probe`/`audio_extract`/
  `transcribe`/`write_markdown`/`ingest_text`/`audit_duplicates` (solo
  `noop`/`echo` de prueba).
- No escribe en Neo4j, no procesa PDFs ni vídeos/audio reales.
- No tiene botones de acción en el panel (crear/cancelar/reintentar desde la
  web): eso queda para una fase posterior, junto con permisos/login.
- No implementa login ni permisos por personaje (`access_store` se revisó y
  se le añadió un test básico, pero no se amplía en esta fase).
- No es un daemon systemd todavía (`--loop` es un bucle de proceso, no un
  servicio administrado).

## Cómo se integrará con multimedia

El worker de multimedia (fase `feat/multimedia-ingestion-worker`, todavía sin
fusionar a `main`) ya tiene su propio `MediaJobStore` (JSON) y un
`job_store_bridge.py` opcional. En una fase de integración posterior, ese
bridge puede crear jobs `media_probe`/`audio_extract`/`transcribe`/
`write_markdown` en **esta** cola genérica (vía `create_job(job_type=...)`),
y el worker genérico de esta fase (`jobs/worker.py`) podría despachar a los
handlers reales de `data-engine/app/media/` en vez de solo a `noop`/`echo`.
El panel `/jobs` los mostraría automáticamente sin cambios, porque ya lista
cualquier `job_type`.

## Cómo se desplegará en VM105

Ver también `deployments/local-vm105/README.md` (sección "Jobs panel / worker
manual"). Resumen:

```bash
cd /opt/knowledge-services/s9-knowledge-repo
git pull
export S9K_JOBS_DB=/opt/knowledge-services/s9-knowledge-repo/state/jobs.db
python data-engine/app/cli/jobs.py create --type echo --workspace leyenda \
    --payload '{"message":"prueba vm105"}'
python data-engine/app/jobs/worker.py --once --limit 1
python data-engine/app/cli/jobs.py list --workspace leyenda
```

Y en el visor ya desplegado, añadir `S9K_JOBS_DB` a `viewer/.env` para que el
panel `/jobs` vea la misma base de datos.

## Cómo podría ir a systemd/timer en una fase posterior

Igual que se documentó para el worker multimedia
(`docs/14-multimedia-ingestion-worker.md`), un `systemd.timer` podría disparar
`scripts/run-jobs-worker.sh` periódicamente:

```ini
# /etc/systemd/system/s9-jobs-worker.service (oneshot, NO daemon)
[Unit]
Description=S9 Knowledge jobs worker (oneshot)
[Service]
Type=oneshot
WorkingDirectory=/opt/knowledge-services/s9-knowledge-repo
EnvironmentFile=/opt/knowledge-services/s9-knowledge-repo/jobs.env
ExecStart=/opt/knowledge-services/s9-knowledge-repo/scripts/run-jobs-worker.sh
```

```ini
# /etc/systemd/system/s9-jobs-worker.timer
[Unit]
Description=Ejecuta el jobs worker periódicamente
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```

**No se instala nada de esto en esta fase.** Solo queda documentado y el
script (`scripts/run-jobs-worker.sh`) preparado para cuando se decida activarlo.

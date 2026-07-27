# 02 · Estado actual

> **Documento canónico de estado.** Se deriva de la fuente de verdad (ver la
> sección final). El estado estructurado y verificable está en
> [`docs/project-status.yaml`](project-status.yaml); este documento lo narra.

- **Fecha de actualización:** 2026-07-18
- **Versión productiva:** `0.3.0-rc5.1`
- **Tag:** `deploy-v0.3.0-rc5.1`
- **Commit:** `47bc3147fdab6b642ab72ffe0cf84133e3a57b2e` (= `main`)
- **release_id activo:** `deploy--20260718-133409`

## Producción (VM105, verificado por SSH 2026-07-18)

| Área | Estado |
|------|--------|
| **Visor** | `s9-knowledge-viewer.service` **active/running**, PID 1479559, NRestarts=0. FastAPI/uvicorn en `127.0.0.1:8088`. |
| **Autenticación** | **Login propio del visor** (formulario con submit explícito, sesiones, CSRF, roles). Basic Auth **retirada** del proxy. 1 administrador activo (`s9admin`), `must_change_password=false`. |
| **Acceso externo** | `https://knowledge.seccionnueve.duckdns.org` -> nginx VM104 -> `:8088`. HTTPS. Sin Basic Auth (autenticación en la app). |
| **Neo4j** | Contenedor `neo4j-knowledge`, **199 nodos / 140 relaciones**. Puertos 7474/7687 solo `127.0.0.1`. |
| **Jobs** | Cola SQLite externa (`/var/lib/s9-knowledge/jobs/jobs.db`): **1 job**. |
| **Workers** | Worker de cola disponible (echo/noop) y worker multimedia implementados; sin ejecución de ingesta real. |
| **Healthcheck** | `s9-knowledge-healthcheck.service` (solo lectura) instalado; 2 ejecuciones manuales con `Result=success`. |
| **Timer** | `s9-knowledge-healthcheck.timer` **enabled + active**: `OnCalendar=hourly`, `Persistent=true`, `RandomizedDelaySec=5m`. Sin timer de 5 min ni duplicados. |
| **Backups** | `/var/lib/s9-knowledge/backups/` (0700). Backup Neo4j validado (restore 199/140). Los backups de auth/jobs quedan 0700/0600. |
| **Ingestas aplicadas** | **0**. `S9K_ALLOW_REAL_INGEST` sin definir (off). Ingesta real bloqueada por doble guard. |

## Despliegue

- **Modelo de releases inmutables** bajo `/opt/s9-knowledge/releases/<id>/`, activadas por symlink atómico `current`.
- **deploy-tools** versionados e independientes de la release:
  `/opt/s9-knowledge/deploy-tools/47bc314/` con `deploy-tools/current -> 47bc314`.
- **Estado externo a la release**: `auth.db` y `jobs.db` viven en
  `/var/lib/s9-knowledge/`; la contraseña **no** la gestiona el despliegue.
- **Rollback**: la release anterior (`91bdc51-...`, RC4) se conserva como destino
  de rollback. Retención fail-closed (protege current/previous/tags/proceso vivo).
- **Resolución de refs** endurecida (RC5.1): `resolve_release_commit` resuelve
  tags/commits remotos aún no materializados sin duplicar la referencia
  (regresión forward-ref corregida — ver [docs/51](51-deploy-forward-ref-regression.md)).

### Historial de candidatas

- **RC4** (`deploy-v0.3.0-rc4`, `91bdc51`) — desplegada 2026-07-17; hoy **previous**/rollback.
- **RC5** (`deploy-v0.3.0-rc5`, `bcc3a59`) — **candidata NO desplegada**: el cutover se abortó antes de activarse; se conserva para auditoría.
- **RC5.1** (`deploy-v0.3.0-rc5.1`, `47bc314`) — **ACTIVA en producción**.

## Motor de datos y grafo

- `data-engine/app/schemas/rpg_schema.py` — schema RPG (tipos de nodo, relaciones, vocabularios controlados, normalizadores).
- `data-engine/app/ingest_rpg.py` — writer Neo4j (trazabilidad, procedencia).
- Pipeline de revisión (`data-engine/app/review/`): segment -> classify -> extract -> validate -> resolve -> decide -> approved_payload.
- Ingesta controlada **solo dry-run** salvo doble guard (`--dry-run` + `S9K_ALLOW_REAL_INGEST=true`).
- IA externa (`external_ai`, NVIDIA) en **modo sombra** (sin escritura en Neo4j).
- Burst orchestrator (Fase B1): planner/dispatcher/mock/CLI; proveedores reales (B2/B3) pendientes.

## Visor

- FastAPI desplegado por releases (a través de `current`). Provider Neo4j, auth DB y jobs DB externas.
- Rutas: `/login`, `/graph` (vis.js), `/jobs`, `/reviews` (panel de revisión enriquecido).
- Login propio, roles, sesiones, CSRF. Diferencias local/producción documentadas en [viewer/README](../viewer/README.md).

## Seguridad

- Basic Auth retirada; autenticación propia del visor con submit explícito (evita autoenvío del navegador/autofill).
- Neo4j cerrado a `127.0.0.1`. HTTPS en el dominio público.
- Healthcheck de solo lectura (no reinicia servicios, no escribe en Neo4j/auth/jobs).

## Tests y CI

- **Suite verde.** A fecha de corte, `pytest --collect-only` recopila **912 tests**
  (deploy 149, viewer 296, data-engine 467). CI de GitHub Actions en verde en `main`.
- El número exacto de tests cambia con el desarrollo; la referencia estable es
  `docs/project-status.yaml` y la ejecución real de CI.

## Deuda técnica y limitaciones conocidas

- Nombre de `release_id` con doble guion (`deploy--<ts>`) en deploy hacia delante por tag: cosmético; el commit y la verificación son correctos y la retención lo protege.
- Healthcheck: `ollama` y `nextcloud_rclone` aparecen como `UNKNOWN` ("no configurado") — integraciones opcionales no usadas en este despliegue; el unit las acepta (`SuccessExitStatus=0 1`).
- Calidad del extractor (Prioridad 2): entidades sobre umbral; **relaciones** aún por debajo -> ingesta real bloqueada.
- Nodos históricos sin `source_id`/`source_kind` detectados por `audit-graph` (no corregidos).
- Fusión de duplicados del grafo: detectada por `audit-graph`, no corregida.

## Bloqueos

- **Primera ingesta real: NO autorizada** (doble guard activo).
- Proveedores reales de external burst (B2/B3): pendientes.

## Siguiente prioridad

- P0: contratos de review/ingest.
- P1: panel de revisión operativo + permisos RPG en backend + visibilidad por personaje.
- P2: primera ingesta controlada (con autorización) + worker real / external burst.
- P3: limpieza histórica + restore periódico.

## FUENTE DE VERDAD

El estado de este documento **no** se copia de informes anteriores: se deriva de

1. **`main`** del repositorio (`47bc3147...`).
2. **Tags** de release (`deploy-v0.3.0-rc4/rc5/rc5.1`).
3. **Manifiestos** de la release activa (`manifest.json`, `deployment-state.json`).
4. **CI** de GitHub Actions (estado de los jobs).
5. **Producción** en VM105, verificada por SSH en solo lectura (systemctl, CLI de
   auth, consultas Neo4j de solo lectura, healthcheck).

El estado estructurado y verificable está en
[`docs/project-status.yaml`](project-status.yaml), validado por
[`scripts/check_docs_consistency.py`](../scripts/check_docs_consistency.py).

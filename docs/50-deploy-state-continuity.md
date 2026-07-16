# 50 — Continuidad de estado y activación correcta de releases

Corrige los defectos estructurales que llevaron a **rechazar RC1** (`deploy-v0.3.0-rc1`
/ `d9af2d3`, marcada `DO NOT DEPLOY`):

1. La unit systemd versionada seguía ejecutando el **layout legacy**
   (`/opt/knowledge-services/s9-knowledge-repo`).
2. `deploy.sh` no garantizaba que el proceso vivo usara `current`.
3. El flujo podía inicializar una `auth.db` **vacía** durante una actualización.
4. No existía un `viewer.env` productivo compatible con el nuevo layout.
5. No existía una migración legacy → state root **validada y atómica**.

> No se adapta producción alrededor de una release defectuosa: se corrige el
> mecanismo de despliegue y se preparará una RC2 nueva.

## Componentes

| Archivo | Rol |
|---|---|
| `deploy/scripts/detect_state.py` | Clasifica el estado (6 estados) y decide proceder/bloquear. |
| `deploy/scripts/migrate_sqlite.py` | Migrador SQLite atómico (auth.db / jobs.db) plan/apply. |
| `deploy/scripts/validate_deploy.sh` | Gates de `viewer.env` y de la unit systemd. |
| `deploy/scripts/verify_release_identity.py` | Verifica que el **proceso vivo** ejecuta la release autorizada. |
| `viewer/systemd/s9-knowledge-viewer.service` | Unit basada en `current` + `EnvironmentFile`. |
| `deploy/config/viewer.env.example` | Plantilla versionada sin secretos. |
| `deploy/scripts/deploy.sh` | Orquestación en 17 pasos con gates. |
| `deploy/scripts/rollback-release.sh` | Rollback con distinción pre/post externalización + bridge. |
| `deploy/tests/test_state_continuity.py` | Laboratorio de 25 escenarios. |

## Estados de continuidad (detect_state.py)
`LEGACY_STATE`, `NEW_STATE`, `MIXED_EQUIVALENT_STATE`, `CONFLICTING_STATE`,
`EMPTY_STATE`, `CORRUPT_STATE`.

Bloqueo en `--mode upgrade`:
- **auth** (crítica): `EMPTY`, `CONFLICTING`, `CORRUPT` **bloquean**.
- **jobs** (opcional, puede estar vacía): `CONFLICTING`, `CORRUPT` bloquean; `EMPTY` no.
- **0 administradores activos** (`role='admin' AND is_active=1`) **bloquea**.
- Nunca se crea automáticamente una `auth.db` vacía.
- Nunca se elige en silencio entre la DB legacy y la nueva.

## Migrador SQLite (migrate_sqlite.py)
- Modo **PLAN** por defecto; escribe solo con `--apply --confirm`.
- Copia consistente con la API `.backup` de SQLite a un temporal.
- `PRAGMA integrity_check` del temporal + comparación de conteos (schema_version,
  usuarios, admins activos, jobs) antes de aceptar.
- `os.replace` atómico; permisos `0600`.
- **Idempotente** (`ALREADY_DONE` si el destino ya equivale al origen).
- Base legacy **intacta**; rechaza symlinks y path traversal; nunca imprime filas
  sensibles (solo conteos).

## systemd + viewer.env
La unit resuelve todo a través de `current`:
```
WorkingDirectory=/opt/s9-knowledge/current/viewer
EnvironmentFile=/etc/s9-knowledge/viewer.env
ExecStart=/opt/s9-knowledge/current/viewer/.venv/bin/uvicorn app.main:app ...
```
`validate_deploy.sh` bloquea si la unit referencia el layout legacy, si
`WorkingDirectory`/`ExecStart`/venv no cuelgan de `current`, o si falta
`EnvironmentFile`. El despliegue bloquea si faltan variables críticas en
`viewer.env` (`S9K_VIEWER_HOST/PORT`, `S9K_GRAPH_PROVIDER`, `S9K_NEO4J_URI/USER`,
`S9K_AUTH_DB_PATH`, `S9K_JOBS_DB`, `S9K_AUTH_ENABLED`, `S9K_CSRF_SECRET`).

## Identidad de release (verify_release_identity.py)
No basta con que el symlink `current` haya cambiado. Se comprueba:
- `manifest.json`: `release_id`, `git_commit`, `schema_versions`.
- `current` resuelve a la release esperada.
- Del **proceso vivo** (PID del servicio): `/proc/<pid>/cwd` cuelga de la release,
  el ejecutable Python pertenece al `.venv` de `current`, y (si es legible) los
  módulos mapeados referencian `current` y no el layout legacy.

Si el proceso no ejecuta la release autorizada → `deploy.sh` hace **auto-revert**.

## Orden de deploy.sh (17 pasos)
1 lock · 2 verificar/construir release · 3 detectar layout · 4 migrar/validar
estado · 5 validar continuidad · 6 validar `viewer.env` · 7 validar unidad ·
8 respaldar unidad instalada · 9 instalar unidad nueva · 10 `systemd-analyze
verify` · 11 `daemon-reload` solo si cambió · 12 `current` atómico · 13 reiniciar
servicios afectados · 14 comprobar commit ejecutado · 15 comprobar admin y jobs ·
16 healthcheck · 17 liberar lock.

**Dry-run** (por defecto): 0 archivos, 0 migraciones, 0 cambios de symlink,
0 `daemon-reload`, 0 reinicios.

## Rollback y punto de no retorno
- **Antes de externalizar** el estado (no existe `${S9K_STATE_ROOT}/auth/auth.db`):
  rollback simple compatible.
- **Después de externalizar** (punto de no retorno cruzado): el destino debe
  **entender el state root externo** (unit basada en `current`). Un rollback directo
  a una release legacy dejaría la app leyendo DBs obsoletas → **BLOQUEADO**.
  Para volver a esa release hay que crear una **bridge release** (misma app pero con
  unit/config apuntando al state root externo) y usar `--bridge-release`.

## Laboratorio (25 escenarios)
`deploy/tests/test_state_continuity.py` cubre: detección LEGACY, migración
auth/jobs, integridad, conservación de usuario/admin/job, unidad basada en current,
activación, commit ejecutado, idempotencia, mixed equivalente/divergente, DB
ausente/corrupta, 0 admins, fallo de backup, fallo antes de rename, fallo de unidad,
fallo de arranque, auto-revert, rollback compatible/incompatible y dry-run sin
cambios. Usa fixtures equivalentes al esquema real; **nunca** toca producción.

## Estado
Corrección **lista para revisión**. NO despliega, NO crea tag nuevo, NO toca
producción. La RC2 (`deploy-v0.3.0-rc2`) solo se creará tras aprobación y merge.

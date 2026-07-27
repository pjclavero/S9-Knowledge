# 47 · Despliegue reproducible y recuperacion (Tarea B)

> Estado: **IMPLEMENTADO**. Rama `feat/reproducible-deployment`.
> Modelo de releases con symlinks atomicos. Sin despliegue automatico. Sin secretos en el repo.

---

## Arquitectura de releases

El sistema usa un modelo de **releases inmutables** con symlink atomico, similar a Capistrano o Kamal:

```
/opt/s9-knowledge/
├── releases/
│   ├── abc1234-20260716-120000/   <- release inmutable (clon del repo en ese commit)
│   │   ├── viewer/
│   │   │   ├── app/
│   │   │   ├── .venv/             <- venv de Python instalado en la release
│   │   │   └── requirements.txt
│   │   ├── data-engine/
│   │   └── manifest.json          <- metadatos sin secretos
│   └── def5678-20260715-090000/   <- release anterior (conservada para rollback)
├── current -> releases/abc1234-20260716-120000   <- symlink atomico
└── .repo-cache/                   <- repo base para clones locales rapidos

/var/lib/s9-knowledge/             <- estado mutable FUERA de releases
├── auth/
│   └── auth.db                    <- base de datos SQLite de autenticacion
├── jobs/                          <- estado de jobs del data-engine
├── state/                         <- estado de procesamiento
├── output/                        <- salidas generadas
├── staging/                       <- staging area
└── backups/                       <- backups pre-migracion

/etc/s9-knowledge/                 <- configuracion y secretos FUERA del repo
├── viewer.env                     <- EnvironmentFile del servicio (0600, con secretos)
├── data-engine.env                <- variables del data-engine (0600)
└── deploy.env                     <- variables del proceso de deploy (0600)
```

**Por que este modelo:**
- `git merge --ff-only` en produccion crea ventanas de inconsistencia durante el despliegue.
- Con releases inmutables, el symlink se cambia atomicamente: en ningun momento el servicio ve un estado a medias.
- Rollback = cambiar el symlink de vuelta. Instant. Sin reinstalar dependencias.
- Las releases antiguas se conservan (configurable, default: 3) para rollback inmediato.

---

## Directorios y permisos

| Directorio | Propietario | Modo | Proposito |
|---|---|---|---|
| `/opt/s9-knowledge/` | root | 0755 | Raiz del despliegue |
| `/opt/s9-knowledge/releases/` | root | 0755 | Releases inmutables |
| `/opt/s9-knowledge/current` | root | symlink | Release activa |
| `/var/lib/s9-knowledge/` | www-data | 0750 | Estado mutable |
| `/var/lib/s9-knowledge/auth/` | www-data | 0750 | auth.db |
| `/var/lib/s9-knowledge/backups/` | www-data | 0750 | Backups pre-deploy |
| `/etc/s9-knowledge/` | root | 0700 | Secretos y config |
| `/etc/s9-knowledge/*.env` | root | 0600 | EnvironmentFiles |
| `/var/log/s9-knowledge/` | www-data | 0750 | Logs del servicio |

---

## Variables de configuracion

Todas sobreescribibles por variable de entorno. Sin valores hardcodeados en produccion.

| Variable | Default | Descripcion |
|---|---|---|
| `S9K_ROOT` | `/opt/s9-knowledge` | Raiz del despliegue |
| `S9K_STATE_ROOT` | `/var/lib/s9-knowledge` | Estado mutable |
| `S9K_CONFIG_ROOT` | `/etc/s9-knowledge` | Configuracion y secretos |
| `S9K_LOG_ROOT` | `/var/log/s9-knowledge` | Logs |
| `S9K_VIEWER_URL` | `http://127.0.0.1:8088` | URL del visor para healthcheck |
| `S9K_RELEASES_TO_KEEP` | `3` | Releases a conservar |
| `S9K_OLLAMA_URL` | (vacio) | URL de Ollama (omitido si vacio) |
| `S9K_RCLONE_MOUNT` | (vacio) | Mountpoint rclone (omitido si vacio) |
| `S9K_BACKUP_DIR` | (vacio) | Dir de backups (omitido si vacio) |
| `S9K_AUTH_ENABLED` | (vacio) | Habilitar auth (`true`/`1`) |

---

## Scripts de operacion

### preflight.sh — verificacion previa (solo lectura)

Comprueba el entorno antes de desplegar. **No modifica nada**.

```bash
# Verificar el entorno de lab
bash deploy/scripts/preflight.sh --environment lab

# Verificar el entorno de produccion
bash deploy/scripts/preflight.sh --environment production
```

Codigos de salida:
- `0` = apto para desplegar
- `1` = advertencias no bloqueantes (despliegue posible con cautela)
- `2` = bloqueo operativo (no desplegar)
- `3` = configuracion invalida

Comprueba: distro Debian 13+, Python 3.11+, git, espacio libre >= 2 GB, RAM >= 512 MB, systemd, usuario no root, S9K_ROOT, /etc/s9-knowledge/deploy.env, /var/lib/s9-knowledge/, Neo4j bolt 7687, Ollama (opcional), rclone (opcional), backup reciente (opcional).

### deploy.sh — despliegue con releases atomicas

**Por defecto: DRY-RUN**. Sin `--confirm` no se aplica ningun cambio.

```bash
# Dry-run (ver el plan sin ejecutar nada)
bash deploy/scripts/deploy.sh \
    --environment lab \
    --release-ref abc1234

# Aplicar en lab
bash deploy/scripts/deploy.sh \
    --environment lab \
    --release-ref abc1234 \
    --confirm

# Aplicar en produccion (requiere SHA o tag, no rama)
bash deploy/scripts/deploy.sh \
    --environment production \
    --release-ref abc1234def5678 \
    --confirm-production
```

Flujo de despliegue:
1. Validar argumentos y entorno
2. Resolver commit exacto del ref
3. Generar release ID: `<short-sha>-<timestamp>`
4. Adquirir lock de concurrencia (`flock`)
5. Ejecutar `preflight.sh`
6. Mostrar plan sin secretos
7. Crear `releases/<release-id>/` y clonar el repo
8. Instalar `.venv` con `pip install` desde `requirements.txt` fijado
9. Crear `manifest.json` (sin secretos)
10. Backup de `auth.db` + migraciones SQLite (idempotentes)
11. Cambiar symlink `current` **atomicamente** (`ln -sfn + mv -T`)
12. Recargar systemd si cambiaron las units
13. Reiniciar `s9-knowledge-viewer.service`
14. Ejecutar `verify-deployment.sh`
15. **Rollback automatico del symlink** si la verificacion falla
16. Limpiar releases antiguas (conservar `S9K_RELEASES_TO_KEEP`)

Protecciones:
- Rechaza arbol Git sucio en produccion
- Rechaza branch ambigua en produccion (debe ser SHA o tag)
- No sobrescribe release existente con mismo ID
- Lock de concurrencia: una sola instancia simultanea
- Trap de limpieza de temporales
- No copia `.env` dentro de releases
- No muestra secretos en logs

### verify-deployment.sh — verificacion post-despliegue

Comprueba el estado del sistema. **No modifica nada**.

```bash
# Verificar estado actual
bash deploy/scripts/verify-deployment.sh

# Verificar que una release concreta esta activa
bash deploy/scripts/verify-deployment.sh --expected-release abc1234-20260716-120000
```

Checks realizados:
1. Symlink `current` existe y apunta a directorio valido
2. Release activa coincide con la esperada (si se pasa `--expected-release`)
3. `.venv` presente y ejecutable en la release
4. Imports Python basicos: `fastapi`, `neo4j`, `argon2`
5. Servicio `s9-knowledge-viewer.service` activo
6. `/var/lib/s9-knowledge/` accesible
7. `auth.db` presente si `S9K_AUTH_ENABLED=true`
8. Neo4j bolt 7687 escuchando
9. Endpoint HTTP `/api/status` respondiendo (con timeout de 10s)

Salida:
- `0` = HEALTHY o DEGRADED
- `1` = UNHEALTHY (symlink roto, servicio caido, verificacion critica fallida)
- `2` = ERROR de verificacion (no se pudo ejecutar correctamente)

### rollback-release.sh — revertir a release anterior

**Por defecto: DRY-RUN**. Sin `--confirm` no se aplica nada.

```bash
# Ver que releases hay disponibles (dry-run)
bash deploy/scripts/rollback-release.sh \
    --environment lab

# Rollback a la penultima release (sin especificar cual)
bash deploy/scripts/rollback-release.sh \
    --environment lab \
    --confirm

# Rollback a una release concreta
bash deploy/scripts/rollback-release.sh \
    --environment lab \
    --to-release abc1234-20260715-090000 \
    --confirm

# Produccion
bash deploy/scripts/rollback-release.sh \
    --environment production \
    --to-release abc1234-20260715-090000 \
    --confirm-production
```

Flujo:
1. Identificar release activa
2. Listar releases disponibles
3. Determinar release destino (especificada o penultima)
4. Validar manifiesto de la release destino
5. Verificar compatibilidad de esquema
6. Lock de concurrencia
7. Cambiar symlink atomicamente
8. Reiniciar servicio
9. Ejecutar `verify-deployment.sh`
10. Si falla: volver a la release anterior

**Limitaciones del rollback:**
- Neo4j NO se restaura automaticamente. El grafo queda en el estado actual.
- SQLite (auth.db) NO se restaura automaticamente.
- Si hay migraciones de esquema incompatibles, el rollback puede dejar la BD en estado inconsistente. Restaurar el backup manualmente de `/var/lib/s9-knowledge/backups/`.

---

## Manifiesto de release

Cada release genera un `manifest.json` **sin secretos**:

```json
{
  "release_id": "abc1234-20260716-120000",
  "git_commit": "abc1234def5678901234567890123456789012345",
  "environment": "production",
  "created_at": "2026-07-16T12:00:00Z",
  "created_by": "deploy.sh",
  "python_version": "3.13.5",
  "dependency_fingerprint": "sha256:abcdef...",
  "schema_versions": {"auth_db": 1, "job_store": 1},
  "compatible_rollback_to": [],
  "files_checksum": "sha256:fedcba..."
}
```

El campo `compatible_rollback_to` lista los commits SHA con los que esta release es compatible para rollback (esquemas de BD compatibles). Si esta vacio, el rollback puede necesitar restauracion manual de la BD.

---

## Instalacion limpia (primera vez)

```bash
# 1. Preparar el host (como root o con sudo)
mkdir -p /opt/s9-knowledge/releases
mkdir -p /var/lib/s9-knowledge/{auth,jobs,state,output,staging,backups}
mkdir -p /etc/s9-knowledge
mkdir -p /var/log/s9-knowledge
chown -R www-data:www-data /var/lib/s9-knowledge /var/log/s9-knowledge
chmod 700 /etc/s9-knowledge

# 2. Crear los EnvironmentFiles (SECRETOS — no versionar)
# /etc/s9-knowledge/deploy.env:
#   S9K_REPO_URL=https://github.com/pjclavero/S9-Knowledge.git
#   S9K_VIEWER_URL=http://127.0.0.1:8088
# /etc/s9-knowledge/viewer.env:
#   S9K_CSRF_SECRET=<secreto-real>
#   S9K_NEO4J_URI=bolt://localhost:7687
#   ... (ver viewer/.env.example)

# 3. Verificar requisitos
bash deploy/scripts/preflight.sh --environment production

# 4. Primer deploy (dry-run primero)
bash deploy/scripts/deploy.sh \
    --environment production \
    --release-ref <commit-sha>

# 5. Aplicar si el dry-run se ve correcto
bash deploy/scripts/deploy.sh \
    --environment production \
    --release-ref <commit-sha> \
    --confirm-production
```

---

## Upgrade (version existente -> nueva version)

```bash
# 1. Verificar estado actual
bash deploy/scripts/verify-deployment.sh

# 2. Preflight
bash deploy/scripts/preflight.sh --environment production

# 3. Deploy de la nueva version (dry-run primero)
bash deploy/scripts/deploy.sh \
    --environment production \
    --release-ref <nuevo-commit-sha>

# 4. Aplicar
bash deploy/scripts/deploy.sh \
    --environment production \
    --release-ref <nuevo-commit-sha> \
    --confirm-production

# 5. El script verifica automaticamente y hace rollback si algo falla
```

---

## Rollback manual

```bash
# Ver releases disponibles
ls -lt /opt/s9-knowledge/releases/

# Ver release activa
readlink /opt/s9-knowledge/current

# Dry-run del rollback
bash deploy/scripts/rollback-release.sh \
    --environment production \
    --to-release <release-id-anterior>

# Aplicar rollback
bash deploy/scripts/rollback-release.sh \
    --environment production \
    --to-release <release-id-anterior> \
    --confirm-production

# Si el rollback falla por incompatibilidad de BD:
# Restaurar backup manualmente
cp /var/lib/s9-knowledge/backups/auth.db.pre-<release-id>.bak \
   /var/lib/s9-knowledge/auth/auth.db
# Reiniciar el servicio
systemctl restart s9-knowledge-viewer.service
```

---

## Migraciones SQLite

El `deploy.sh` ejecuta migraciones SQLite automaticamente antes de activar la release:

1. **Backup previo**: copia `auth.db` a `backups/auth.db.pre-<release-id>.bak`
2. **Migracion**: llama a `app.auth.db.ensure_migrated()` (idempotente)
3. **Si la migracion falla**: el deploy se detiene; la release anterior sigue activa

Las migraciones son idempotentes: ejecutarlas dos veces no produce datos duplicados ni errores.

**Migraciones NO automatizadas:**
- Esquema de Neo4j: ninguna migracion automatica. Los cambios de schema del grafo son responsabilidad del operador.
- Jobs de data-engine: el estado de jobs es inmutable; no se migra.

---

## Roles Ansible

El directorio `deploy/ansible/` contiene un playbook Ansible para preparar el host:

```bash
# Syntax check (sin conectar al host):
ansible-playbook -i deploy/ansible/inventory.example deploy/ansible/site.yml --syntax-check

# Check mode (conecta pero no aplica):
ansible-playbook -i inventory.ini deploy/ansible/site.yml --check --diff

# Aplicar:
ansible-playbook -i inventory.ini deploy/ansible/site.yml
```

Roles:
- **common**: paquetes de sistema, estructura de directorios
- **data_engine**: clonar/actualizar repo base (cache local)
- **viewer**: instalar .venv en la release activa, verificar que .env no esta en la release
- **auth**: migraciones de auth.db (solo si `s9k_auth_enabled: true`)
- **systemd**: instalar units systemd, habilitar/arrancar servicio
- **healthchecks**: instalar units de healthcheck (timer deshabilitado por defecto)

Los roles son idempotentes, declaran `changed_when`, usan `no_log` para variables sensibles (si las hubiera) y etiquetan todas las tareas.

---

## Validacion y CI

```bash
# Validacion local completa
bash deploy/tests/validate.sh
```

El CI ejecuta un job `deployment-validation` que verifica:
- `bash -n` (sintaxis de todos los scripts)
- `shellcheck` (si disponible)
- `yamllint` (si disponible)
- `ansible-playbook --syntax-check`
- `validate.sh` completo
- Unicode check
- No hay secretos hardcodeados

---

## Limitaciones conocidas

- **Neo4j no se restaura en rollback**: el grafo de datos no tiene rollback automatico. Si una migracion del schema de Neo4j es incompatible con la release anterior, el rollback puede dejar el sistema en estado inconsistente. Planificar migraciones de Neo4j separadamente.
- **SQLite no se restaura en rollback automatico**: se genera un backup pre-deploy, pero el rollback no lo restaura. Si hay incompatibilidad de schema de auth.db, restaurar manualmente.
- **Primer deploy requiere preparacion manual del host**: los directorios y EnvironmentFiles deben existir antes del primer `deploy.sh --confirm`.
- **Sin despliegue automatico**: los scripts son herramientas manuales. No hay CD automatico desde CI. El operador debe ejecutarlos.

---

## Despliegue productivo (NO ejecutar todavia)

El despliegue en VM105 (192.168.1.205) **no esta ejecutado**. Antes de desplegar:

1. Revisar y aprobar este PR con el equipo
2. Preparar el host VM105 con la estructura de directorios (via Ansible o manual)
3. Crear los EnvironmentFiles en `/etc/s9-knowledge/` (con secretos reales del entorno)
4. Ejecutar `preflight.sh --environment production` y resolver cualquier bloqueo
5. Ejecutar `deploy.sh --dry-run` y revisar el plan
6. Confirmar con el operador autorizado antes de `--confirm-production`

**No modificar `/opt/knowledge-services/` en VM105 hasta aprobacion explicita.**

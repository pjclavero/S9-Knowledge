# 47 · Despliegue reproducible y recuperación (Tarea B)

> Estado: **AUDITORÍA INICIAL / EN CURSO**. Rama `feat/reproducible-deployment` desde `main@40cf75d`.
> Instalar/actualizar/verificar/revertir sin comandos memorizados. **No despliega automáticamente ni contiene secretos.**

---

## Auditoría inicial (estado actual)

- **No existe** directorio `deploy/`. El despliegue en VM105 es manual (git ff + `pip install` + reinicio del visor), como se hizo en la integración de #19/#20.
- Servicio systemd: `viewer/systemd/s9-knowledge-viewer.service` (WorkingDirectory `viewer/`, `EnvironmentFile=viewer/.env`, `viewer/.venv/bin/uvicorn`).
- Dependencias bloqueadas: `data-engine/requirements.lock`, `viewer/requirements.txt`.
- Backups: `scripts/backup/neo4j-backup.sh`; docs/26, docs/32.
- `.env` de producción es un `EnvironmentFile` con config (sin la contraseña real de Neo4j: usa `_FILE`). Contiene el secreto CSRF → **nunca** debe versionarse ni copiarse a git.

## Declaración de ámbito

**Archivos que se crearán (solo esta tarea):**
```
deploy/
├── ansible/ (inventory.example, site.yml, roles/{common,data_engine,viewer,auth,systemd,healthchecks})
└── scripts/ (preflight.sh, deploy.sh, verify-deployment.sh, rollback-release.sh)
docs/47-reproducible-deployment.md
```
Modos: `preflight`, `install`, `upgrade`, `verify`, `rollback`.

**Módulos que NO se tocan:** ningún código de aplicación (`data-engine/app`, `viewer/app`), Neo4j, estados existentes. No se ejecuta ingesta.

**Documentos:** solo `docs/47`. **No** README/CHANGELOG/ROADMAP/`docs/INDEX` (Tarea E).

**Dependencias (solo dev/CI):** `ansible`, `ansible-lint`, `shellcheck`. No se añaden al runtime.

**Límites duros:** sin secretos en el repo (solo `.env.example`), sin despliegue automático (los playbooks se ejecutan manualmente), sin contraseñas predecibles, sin modificar Neo4j, sin borrar estados.

## Contratos

- `preflight`: distro, Python, disco, RAM, puertos, Ollama, Neo4j, mountpoint, usuario, permisos, commit actual → informe, sin cambios.
- `upgrade`: backup config → código → deps → migraciones → reinicio necesario → healthcheck → confirmar.
- `rollback`: parar servicio → restaurar release anterior → (config si procede) → reiniciar → healthcheck. **Neo4j no se restaura automáticamente.**
- Idempotencia: segunda ejecución sin cambios.

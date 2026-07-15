# deploy/ — Instalación y despliegue reproducible de S9 Knowledge

Herramientas para **instalar, actualizar, verificar y revertir** sin comandos memorizados.
No se despliega automáticamente: todo se ejecuta manualmente por el operador.

## Scripts (`deploy/scripts/`)
- `preflight.sh` — verifica requisitos **sin cambios** (distro, python, disco, RAM, puertos, Neo4j, Ollama, mount, repo/permisos, commit).
- `deploy.sh` — instala/actualiza. **Dry-run por defecto**; aplica solo con `--confirm`. Orquesta: preflight → backup config → ff de código → deps → migraciones → reinicio del visor → verify.
- `verify-deployment.sh` — usa `s9k-health` si está disponible; si no, cae a `/api/status` (compatibilidad mientras la Tarea A no esté fusionada).
- `rollback-release.sh` — revierte a una release anterior. **No restaura Neo4j.** Dry-run por defecto.

## Ansible (`deploy/ansible/`)
`inventory.example` (sin secretos) + `site.yml` + roles `common/data_engine/viewer/auth/systemd/healthchecks`.
Los secretos viven en el `EnvironmentFile` del host (`viewer/.env`, 0600), **nunca** en el repo.

## Validación
`deploy/tests/validate.sh` — `bash -n` + `shellcheck` + `ansible-lint` (los dos últimos se exigen en CI en la Tarea E).

## Límites
No incluye `.env` real · no despliega automáticamente · no ejecuta migraciones en producción por sí mismo · no modifica Neo4j ni borra estados · no toca código funcional de viewer/data-engine.

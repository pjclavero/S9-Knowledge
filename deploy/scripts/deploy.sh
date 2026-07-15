#!/usr/bin/env bash
# deploy — instala/actualiza S9 Knowledge de forma reproducible.
# Por seguridad NO aplica cambios salvo --confirm (dry-run por defecto).
# NO despliega automáticamente: debe invocarse manualmente por el operador.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "$HERE/lib.sh"

MODE="upgrade"; REF="origin/main"; CONFIRM=0
usage() { echo "uso: deploy.sh [--mode install|upgrade] [--ref <git-ref>] [--confirm]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "argumento desconocido: $1" ;;
  esac
done

run() { if [ "$CONFIRM" -eq 1 ]; then log "· $*"; "$@"; else log "(dry-run) $*"; fi; }

log "=== DEPLOY mode=$MODE ref=$REF confirm=$CONFIRM ==="
[ "$CONFIRM" -eq 1 ] || warn "DRY-RUN: no se aplicará ningún cambio (usa --confirm para ejecutar)"

# 0. Preflight (bloquea si hay errores duros)
"$HERE/preflight.sh" || { rc=$?; [ "$rc" -ge 2 ] && die "preflight bloqueó el despliegue"; warn "preflight con avisos (rc=$rc)"; }

VENV_PY="$S9K_ROOT/viewer/.venv/bin/python"
ENVF="$S9K_ROOT/viewer/.env"

# 1. Backup de configuración (nunca a git; nunca secretos fuera del host)
if [ -f "$ENVF" ]; then run cp -a "$ENVF" "$ENVF.bak.$(date +%Y%m%d-%H%M%S)"; fi

# 2. Actualizar código (fast-forward al ref indicado)
run git -C "$S9K_ROOT" fetch --all --prune
run git -C "$S9K_ROOT" merge --ff-only "$REF"

# 3. Dependencias bloqueadas
run "$S9K_ROOT/viewer/.venv/bin/pip" install -q -r "$S9K_ROOT/viewer/requirements.txt"

# 4. Migraciones SQLite (idempotentes; auth solo si está activa)
run bash -c "cd '$S9K_ROOT/viewer' && '$VENV_PY' -c 'import sys; sys.path.insert(0,\".\"); from app.auth.config import get_auth_settings; from app.auth import db; c=get_auth_settings(); (db.ensure_migrated(__import__(\"pathlib\").Path(c.S9K_AUTH_DB_PATH)) if c.S9K_AUTH_ENABLED else None)'"

# 5. Reinicio controlado (solo el visor)
run systemctl restart s9-knowledge-viewer.service

# 6. Healthcheck posterior
"$HERE/verify-deployment.sh" || die "verify-deployment falló tras el despliegue"

log "=== DEPLOY completado (commit $(repo_commit)) ==="

#!/usr/bin/env bash
# verify-deployment — comprueba que el despliegue está sano.
# Usa s9k-health si está disponible; si no, cae a /api/status por compatibilidad
# (para funcionar mientras la Tarea A / PR #21 no esté fusionada).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "$HERE/lib.sh"

VENV_PY="$S9K_ROOT/viewer/.venv/bin/python"

log "=== VERIFY DEPLOYMENT ==="

# 1. Preferente: CLI s9k-health (Tarea A) cuando exista en el código desplegado.
if [ -f "$S9K_ROOT/viewer/app/cli/health.py" ] && [ -x "$VENV_PY" ]; then
  log "usando s9k-health (app.cli.health)"
  cd "$S9K_ROOT/viewer"
  set +e
  "$VENV_PY" -m app.cli.health check
  rc=$?
  set -e
  log "s9k-health exit=$rc (0 healthy · 1 degraded · 2 unhealthy · 3 config)"
  exit "$rc"
fi

# 2. Compatibilidad: /api/status mientras A no esté integrada.
warn "s9k-health no disponible; usando /api/status como compatibilidad"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$S9K_VIEWER_URL/api/status" || echo 000)"
case "$code" in
  200|401) log "visor responde (HTTP $code)"; exit 0 ;;
  *) err "visor NO responde correctamente (HTTP $code)"; exit 2 ;;
esac

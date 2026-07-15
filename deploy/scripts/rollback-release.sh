#!/usr/bin/env bash
# rollback-release — revierte a una release anterior del código.
# NO restaura Neo4j automáticamente. Dry-run por defecto (--confirm para aplicar).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "$HERE/lib.sh"

REF=""; CONFIRM=0
usage() { echo "uso: rollback-release.sh --ref <git-ref-anterior> [--confirm]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="$2"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "argumento desconocido: $1" ;;
  esac
done
[ -n "$REF" ] || { usage; die "se requiere --ref"; }

run() { if [ "$CONFIRM" -eq 1 ]; then log "· $*"; "$@"; else log "(dry-run) $*"; fi; }

log "=== ROLLBACK a $REF (confirm=$CONFIRM) ==="
[ "$CONFIRM" -eq 1 ] || warn "DRY-RUN: no se aplicará ningún cambio"
warn "Neo4j NO se restaura automáticamente en el rollback."

# 1. Parar el servicio afectado
run systemctl stop s9-knowledge-viewer.service

# 2. Restaurar la release anterior
run git -C "$S9K_ROOT" checkout --detach "$REF"

# 3. Reinstalar dependencias de esa release
run "$S9K_ROOT/viewer/.venv/bin/pip" install -q -r "$S9K_ROOT/viewer/requirements.txt"

# 4. Reiniciar
run systemctl start s9-knowledge-viewer.service

# 5. Verificar
"$HERE/verify-deployment.sh" || die "verify-deployment falló tras el rollback"

log "=== ROLLBACK completado (commit $(repo_commit)) ==="

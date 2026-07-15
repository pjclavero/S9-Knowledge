#!/usr/bin/env bash
# Validación de los scripts de despliegue: sintaxis bash y (si existe) shellcheck.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
rc=0
echo "== bash -n (sintaxis) =="
for f in "$ROOT"/scripts/*.sh "$ROOT"/tests/*.sh; do
  bash -n "$f" && echo "OK  $f" || { echo "ERR $f"; rc=1; }
done
if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck =="
  shellcheck -x "$ROOT"/scripts/*.sh || rc=1
else
  echo "(shellcheck no instalado; se ejecutará en CI — Tarea E)"
fi
if command -v ansible-lint >/dev/null 2>&1; then
  echo "== ansible-lint =="
  ansible-lint "$ROOT/ansible/site.yml" || rc=1
else
  echo "(ansible-lint no instalado; se ejecutará en CI — Tarea E)"
fi
exit "$rc"

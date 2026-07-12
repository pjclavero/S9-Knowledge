#!/usr/bin/env bash
# Ejecuta un ciclo de escaneo + procesado del pipeline multimedia S9 Knowledge.
# Pensado para VM105 (o cualquier entorno Linux con el repo desplegado).
# NO escribe en Neo4j: genera fuentes revisables en output/transcriptions/.
set -euo pipefail

REPO_ROOT="${S9K_REPO_ROOT:-/opt/knowledge-services/s9-knowledge-repo}"
cd "$REPO_ROOT"

# Activar el venv disponible (viewer o data-engine); si no hay, usar python del sistema.
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.venv/bin/activate"
elif [ -f "$REPO_ROOT/data-engine/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "$REPO_ROOT/data-engine/.venv/bin/activate"
fi

WORKSPACE="${S9K_MEDIA_DEFAULT_WORKSPACE:-leyenda}"
LIMIT="${S9K_MEDIA_WORKER_LIMIT:-1}"

# La CLI vive en data-engine/app/cli/media_jobs.py y hace bootstrap de sys.path,
# así que se invoca por ruta de archivo (el paquete "data-engine" lleva guion y
# no es importable como "data_engine").
CLI="$REPO_ROOT/data-engine/app/cli/media_jobs.py"

echo "[run-media-worker] scan (workspace=$WORKSPACE)"
python "$CLI" scan --workspace "$WORKSPACE"

echo "[run-media-worker] worker (workspace=$WORKSPACE, limit=$LIMIT)"
python "$CLI" worker --workspace "$WORKSPACE" --limit "$LIMIT"

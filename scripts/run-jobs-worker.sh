#!/usr/bin/env bash
# Ejecuta el worker genérico de jobs una vez (uso manual o cron/timer futuro).
# NO escribe en Neo4j. Solo procesa handlers de prueba (noop/echo) por ahora.
set -euo pipefail

REPO_ROOT="${S9K_REPO_ROOT:-/opt/knowledge-services/s9-knowledge-repo}"
cd "$REPO_ROOT"

export S9K_JOBS_DB="${S9K_JOBS_DB:-$REPO_ROOT/state/jobs.db}"

if [ -d "$REPO_ROOT/.venv" ]; then
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.venv/bin/activate"
elif [ -d "$REPO_ROOT/data-engine/.venv" ]; then
  # shellcheck disable=SC1091
  . "$REPO_ROOT/data-engine/.venv/bin/activate"
fi

# La CLI del worker vive en data-engine/app/jobs/worker.py y hace bootstrap
# de sys.path, así que se invoca por ruta de archivo (el paquete "data-engine"
# lleva guion y no es importable como "data_engine" / "app.jobs.worker").
WORKER="$REPO_ROOT/data-engine/app/jobs/worker.py"

echo "[run-jobs-worker] worker --once --limit ${S9K_WORKER_LIMIT:-1} (db=$S9K_JOBS_DB)"
python "$WORKER" --once --limit "${S9K_WORKER_LIMIT:-1}"

#!/usr/bin/env bash
# Ejecuta el worker genérico de jobs una vez (uso manual o cron/timer futuro).
#
# LEE Neo4j, NO escribe (Slice 2 · Corte 5). La línea anterior decía «NO
# escribe en Neo4j. Solo procesa handlers de prueba (noop/echo) por ahora» y
# las dos mitades dejaron de ser ciertas: `ingest_v3` es un handler REAL y
# abre una conexión de sólo lectura al grafo para observar el catálogo del
# workspace. Un comentario que afirma lo contrario de lo que hace el código
# manda a perseguir un fantasma, y en este repositorio ya pasó.
#
# La escritura la gobierna `apply=False` en el handler, por separado.
set -euo pipefail

REPO_ROOT="${S9K_REPO_ROOT:-/opt/knowledge-services/s9-knowledge-repo}"
cd "$REPO_ROOT"

export S9K_JOBS_DB="${S9K_JOBS_DB:-$REPO_ROOT/state/jobs.db}"

# EL ENTORNO DEL WORKER, SI EL OPERADOR LO HA DEPOSITADO.
#
# `ingest_v3` necesita `S9K_NEO4J_URI`, `S9K_NEO4J_USER` y
# `S9K_NEO4J_PASSWORD_FILE` (el CAMINO de un fichero 0600, nunca la contraseña
# dentro de una variable). Sin ellas el handler falla cerrado con
# `GRAPH_OBSERVATION_UNCONFIGURED`, que es lo correcto: no hay ruta de
# repuesto silenciosa. Ver `deploy/README.md`.
#
# El fichero es OPCIONAL aquí a propósito: quien decide si este despliegue
# puede observar el grafo es el handler, no este lanzador. Si no está, el job
# termina en ERROR con su código, no con un fallo de shell que nadie sabría
# leer.
S9K_WORKER_ENV="${S9K_WORKER_ENV:-/etc/s9-knowledge/worker.env}"
if [ -f "$S9K_WORKER_ENV" ]; then
  echo "[run-jobs-worker] entorno: $S9K_WORKER_ENV"
  set -a
  # shellcheck disable=SC1090
  . "$S9K_WORKER_ENV"
  set +a
else
  echo "[run-jobs-worker] AVISO: no hay $S9K_WORKER_ENV; si este despliegue" \
       "corre 'ingest_v3', fallará con GRAPH_OBSERVATION_UNCONFIGURED"
fi

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

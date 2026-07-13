#!/usr/bin/env bash
# neo4j-restore.sh — Restore de Neo4j desde dump
#
# Uso:
#   neo4j-restore.sh --backup-file <ruta/al/neo4j.dump> [--dry-run]
#
# Variables de entorno:
#   NEO4J_CONTAINER   Nombre del contenedor (default: neo4j-knowledge)
#   NEO4J_DATA_DIR    Ruta del bind mount /data en host (default: /opt/knowledge-services/neo4j/data)
#   NEO4J_IMAGE       Imagen Docker de Neo4j (default: neo4j:5.26.0-community)
#   NEO4J_PASSWORD    Contraseña de Neo4j (para validación post-restore)
#
# Salida:
#   Exit 0: restore completado y validado con éxito
#   Exit 1: error en algún paso
#
# ADVERTENCIA: Este script para el contenedor de Neo4j y SOBREESCRIBE /data.
#              Ejecutar solo tras verificar checksum y en ventana de mantenimiento.

set -euo pipefail

# --- Configuración ---
DRY_RUN=false
BACKUP_FILE=""
NEO4J_CONTAINER="${NEO4J_CONTAINER:-neo4j-knowledge}"
NEO4J_DATA_DIR="${NEO4J_DATA_DIR:-/opt/knowledge-services/neo4j/data}"
NEO4J_IMAGE="${NEO4J_IMAGE:-neo4j:5.26.0-community}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="/tmp/neo4j-restore-$TIMESTAMP.log"

# --- Parsear argumentos ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-file)
      BACKUP_FILE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      grep '^#' "$0" | head -20 | sed 's/^# //'
      exit 0
      ;;
    *)
      echo "Argumento desconocido: $1"
      exit 1
      ;;
  esac
done

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

die() {
  log "ERROR: $*"
  exit 1
}

# --- Validaciones ---
log "=== Neo4j Restore ==="
log "Backup file: $BACKUP_FILE"
log "Contenedor: $NEO4J_CONTAINER"
log "Directorio datos: $NEO4J_DATA_DIR"
log "DRY-RUN: $DRY_RUN"

[ -z "$BACKUP_FILE" ] && die "Debes indicar --backup-file <ruta>"
[ -f "$BACKUP_FILE" ] || die "Fichero de backup no encontrado: $BACKUP_FILE"

BACKUP_DIR=$(dirname "$BACKUP_FILE")
CHECKSUM_FILE="${BACKUP_FILE}.sha256"

# Verificar checksum si existe
if [ -f "$CHECKSUM_FILE" ]; then
  log "Verificando checksum..."
  if sha256sum -c "$CHECKSUM_FILE" >> "$LOG_FILE" 2>&1; then
    log "Checksum verificado: OK"
  else
    die "Checksum FALLIDO — el fichero de backup puede estar corrupto"
  fi
else
  log "ADVERTENCIA: No se encontró fichero .sha256 — continuando sin verificación de integridad"
fi

# Verificar que el contenedor existe
docker inspect "$NEO4J_CONTAINER" &>/dev/null || die "Contenedor '$NEO4J_CONTAINER' no encontrado"

if [ "$DRY_RUN" = "true" ]; then
  log "[DRY-RUN] Se pararía: docker stop $NEO4J_CONTAINER"
  log "[DRY-RUN] Se ejecutaría: docker run --rm -v $NEO4J_DATA_DIR:/data -v $BACKUP_DIR:/backup:ro $NEO4J_IMAGE neo4j-admin database load --from-path=/backup/ --overwrite-destination=true neo4j"
  log "[DRY-RUN] Se arrancaría: docker start $NEO4J_CONTAINER"
  log "[DRY-RUN] Se validaría: conteo de nodos"
  log "[DRY-RUN] Restore completado (simulación)"
  exit 0
fi

# --- Ejecución del restore ---

# Parar Neo4j
log "Parando $NEO4J_CONTAINER..."
docker stop "$NEO4J_CONTAINER" || die "No se pudo parar $NEO4J_CONTAINER"
log "$NEO4J_CONTAINER parado"

# Ejecutar load
log "Ejecutando load desde $BACKUP_FILE..."
if docker run --rm \
    -v "$NEO4J_DATA_DIR":/data \
    -v "$BACKUP_DIR":/backup:ro \
    "$NEO4J_IMAGE" \
    neo4j-admin database load --from-path=/backup/ --overwrite-destination=true neo4j >> "$LOG_FILE" 2>&1; then
  log "Load completado con éxito"
else
  LOAD_EXIT=$?
  log "ERROR: load falló (exit $LOAD_EXIT)"
  log "Arrancando Neo4j con datos previos al intento de restore..."
  docker start "$NEO4J_CONTAINER" || log "ADVERTENCIA: No se pudo arrancar $NEO4J_CONTAINER"
  die "Load falló. Ver log: $LOG_FILE"
fi

# Arrancar Neo4j
log "Arrancando $NEO4J_CONTAINER..."
docker start "$NEO4J_CONTAINER" || die "ERROR CRÍTICO: No se pudo arrancar $NEO4J_CONTAINER. Intervención manual requerida."
log "$NEO4J_CONTAINER arrancado"

# Esperar que esté healthy
log "Esperando que $NEO4J_CONTAINER esté healthy..."
sleep 15
for i in $(seq 1 30); do
  STATUS=$(docker inspect "$NEO4J_CONTAINER" --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
  log "[$i/30] Status: $STATUS"
  if [ "$STATUS" = "healthy" ]; then
    log "$NEO4J_CONTAINER está healthy"
    break
  fi
  sleep 5
done

# Validar conteo de nodos (si se proporcionó contraseña)
if [ -n "$NEO4J_PASSWORD" ]; then
  log "Validando conteo de nodos post-restore..."
  NODE_COUNT=$(docker exec "$NEO4J_CONTAINER" cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
    "MATCH (n) RETURN count(n) as total;" 2>/dev/null | grep -Eo '[0-9]+' | tail -1 || echo "unknown")
  log "Nodos totales post-restore: $NODE_COUNT"
else
  log "NEO4J_PASSWORD no configurada — saltando validación de nodos"
fi

log "=== Restore completado ==="
log "Log: $LOG_FILE"
exit 0

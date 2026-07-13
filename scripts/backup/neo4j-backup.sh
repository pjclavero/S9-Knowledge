#!/usr/bin/env bash
# neo4j-backup.sh — Backup de Neo4j producción (Community Edition)
#
# Uso:
#   neo4j-backup.sh [--dry-run]
#
# Variables de entorno (leer desde .env o entorno):
#   NEO4J_CONTAINER   Nombre del contenedor (default: neo4j-knowledge)
#   NEO4J_DATA_DIR    Ruta del bind mount /data en host (default: /opt/knowledge-services/neo4j/data)
#   NEO4J_BACKUP_DIR  Directorio raíz para backups (default: /opt/knowledge-services/backups)
#   NEO4J_IMAGE       Imagen Docker de Neo4j (default: neo4j:5.26.0-community)
#
# Salida:
#   Exit 0: backup completado con éxito
#   Exit 1: error en algún paso
#
# ADVERTENCIA: Este script para el contenedor de Neo4j (~2-5 min de inactividad).
#              Ejecutar solo en ventana de mantenimiento acordada.

set -euo pipefail

# --- Configuración ---
DRY_RUN=false
NEO4J_CONTAINER="${NEO4J_CONTAINER:-neo4j-knowledge}"
NEO4J_DATA_DIR="${NEO4J_DATA_DIR:-/opt/knowledge-services/neo4j/data}"
NEO4J_BACKUP_ROOT="${NEO4J_BACKUP_DIR:-/opt/knowledge-services/backups}"
NEO4J_IMAGE="${NEO4J_IMAGE:-neo4j:5.26.0-community}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$NEO4J_BACKUP_ROOT/neo4j-$TIMESTAMP"
LOG_FILE="/tmp/neo4j-backup-$TIMESTAMP.log"

# --- Parsear argumentos ---
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      grep '^#' "$0" | head -20 | sed 's/^# //'
      exit 0
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

# --- Validaciones previas ---
log "=== Neo4j Backup ==="
log "Contenedor: $NEO4J_CONTAINER"
log "Directorio datos: $NEO4J_DATA_DIR"
log "Directorio backup destino: $BACKUP_DIR"
log "DRY-RUN: $DRY_RUN"

# Verificar que el contenedor existe
if ! docker inspect "$NEO4J_CONTAINER" &>/dev/null; then
  die "Contenedor '$NEO4J_CONTAINER' no encontrado"
fi

# Verificar que el directorio de datos existe
if [ ! -d "$NEO4J_DATA_DIR" ]; then
  die "Directorio de datos no encontrado: $NEO4J_DATA_DIR"
fi

# Calcular espacio requerido (2x datos actuales)
DATA_SIZE_KB=$(du -sk "$NEO4J_DATA_DIR" | cut -f1)
DATA_SIZE_MB=$((DATA_SIZE_KB / 1024))
REQUIRED_KB=$((DATA_SIZE_KB * 2))
log "Tamaño actual /data/: ${DATA_SIZE_MB} MB"
log "Espacio requerido estimado: $((REQUIRED_KB / 1024)) MB"

# Verificar espacio disponible en el directorio padre
PARENT_DIR=$(dirname "$NEO4J_BACKUP_ROOT")
AVAIL_KB=$(df -k "$PARENT_DIR" 2>/dev/null | awk 'NR==2{print $4}' || echo 0)
if [ "$AVAIL_KB" -lt "$REQUIRED_KB" ]; then
  die "Espacio insuficiente: disponible=${AVAIL_KB} KB, requerido=${REQUIRED_KB} KB"
fi
log "Espacio disponible: $((AVAIL_KB / 1024)) MB — OK"

if [ "$DRY_RUN" = "true" ]; then
  log "[DRY-RUN] Se crearía: $BACKUP_DIR"
  log "[DRY-RUN] Se pararía: docker stop $NEO4J_CONTAINER"
  log "[DRY-RUN] Se ejecutaría: docker run --rm -v $NEO4J_DATA_DIR:/data -v $BACKUP_DIR:/backup $NEO4J_IMAGE neo4j-admin database dump neo4j --to-path=/backup/"
  log "[DRY-RUN] Se arrancaría: docker start $NEO4J_CONTAINER"
  log "[DRY-RUN] Backup completado (simulación)"
  exit 0
fi

# --- Ejecución del backup ---

# Crear directorio de backup
mkdir -p "$BACKUP_DIR"
chmod 777 "$BACKUP_DIR"
log "Directorio de backup creado: $BACKUP_DIR"

# Parar Neo4j
log "Parando $NEO4J_CONTAINER..."
docker stop "$NEO4J_CONTAINER" || die "No se pudo parar $NEO4J_CONTAINER"
log "$NEO4J_CONTAINER parado"

# Ejecutar dump
log "Ejecutando dump..."
if docker run --rm \
    -v "$NEO4J_DATA_DIR":/data \
    -v "$BACKUP_DIR":/backup \
    "$NEO4J_IMAGE" \
    neo4j-admin database dump neo4j --to-path=/backup/ >> "$LOG_FILE" 2>&1; then
  log "Dump completado con éxito"
else
  DUMP_EXIT=$?
  log "ERROR: dump falló (exit $DUMP_EXIT) — arrancando Neo4j de nuevo"
  docker start "$NEO4J_CONTAINER" || log "ADVERTENCIA: No se pudo arrancar $NEO4J_CONTAINER automáticamente"
  die "Dump falló. Ver log: $LOG_FILE"
fi

# Calcular checksum
if [ -f "$BACKUP_DIR/neo4j.dump" ]; then
  sha256sum "$BACKUP_DIR/neo4j.dump" > "$BACKUP_DIR/neo4j.dump.sha256"
  log "Checksum: $(cat "$BACKUP_DIR/neo4j.dump.sha256")"
  DUMP_SIZE=$(du -sh "$BACKUP_DIR/neo4j.dump" | cut -f1)
  log "Tamaño dump: $DUMP_SIZE"
else
  log "ADVERTENCIA: neo4j.dump no encontrado en $BACKUP_DIR"
fi

# Arrancar Neo4j
log "Arrancando $NEO4J_CONTAINER..."
docker start "$NEO4J_CONTAINER" || die "ERROR CRÍTICO: No se pudo arrancar $NEO4J_CONTAINER. Intervención manual requerida."
log "$NEO4J_CONTAINER arrancado"

# Esperar que esté healthy
log "Esperando que $NEO4J_CONTAINER esté healthy..."
for i in $(seq 1 30); do
  STATUS=$(docker inspect "$NEO4J_CONTAINER" --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
  log "[$i/30] Status: $STATUS"
  if [ "$STATUS" = "healthy" ]; then
    log "$NEO4J_CONTAINER está healthy"
    break
  fi
  if [ "$i" -eq 30 ]; then
    log "ADVERTENCIA: $NEO4J_CONTAINER no alcanzó estado healthy en tiempo esperado"
  fi
  sleep 5
done

log "=== Backup completado ==="
log "Fichero: $BACKUP_DIR/neo4j.dump"
log "Log: $LOG_FILE"
exit 0

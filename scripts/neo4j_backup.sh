#!/bin/bash
################################################################################
# neo4j_backup.sh — Backup Neo4j database with validation and checksum
#
# Usage:
#   neo4j_backup.sh [--dry-run] [--container NAME] [--dest DIR]
#
# Options:
#   --dry-run       Show what would be done without executing
#   --container     Docker container name (default: neo4j-knowledge)
#   --dest          Backup destination dir (default: /opt/knowledge-services/backups/neo4j)
#
# Example:
#   neo4j_backup.sh --dry-run
#   neo4j_backup.sh --container neo4j-knowledge --dest /opt/backups
#
# Exit codes:
#   0: Success
#   1: Error (invalid args, container not found, insufficient space, etc.)
#   2: Dry-run mode (no actual changes)
#
# Author: AgentC
# Date: 2026-07-13
################################################################################

set -o pipefail

# Defaults
DRY_RUN=false
CONTAINER_NAME="neo4j-knowledge"
BACKUP_DEST="/opt/knowledge-services/backups/neo4j"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Logging
log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --container)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --dest)
      BACKUP_DEST="$2"
      shift 2
      ;;
    *)
      log_error "Unknown option: $1"
      echo "Usage: $0 [--dry-run] [--container NAME] [--dest DIR]"
      exit 1
      ;;
  esac
done

# Create backup directory if needed
if ! $DRY_RUN; then
  mkdir -p "$BACKUP_DEST" || { log_error "Failed to create $BACKUP_DEST"; exit 1; }
fi

log_info "Neo4j Backup Script"
log_info "Container: $CONTAINER_NAME"
log_info "Destination: $BACKUP_DEST"
if $DRY_RUN; then log_info "Mode: DRY-RUN (no changes will be made)"; fi

# Step 1: Validate container exists and is running
log_info "Validating container..."
if ! docker ps | grep -q "^[^ ]* .* $CONTAINER_NAME"; then
  log_error "Container $CONTAINER_NAME not found or not running"
  docker ps | grep "$CONTAINER_NAME" || log_error "No container matches $CONTAINER_NAME"
  exit 1
fi
log_info "✓ Container found and running"

# Step 2: Get Docker image
log_info "Retrieving Docker image..."
PROD_IMAGE=$(docker inspect "$CONTAINER_NAME" --format '{{.Config.Image}}')
if [ -z "$PROD_IMAGE" ]; then
  log_error "Failed to get Docker image for $CONTAINER_NAME"
  exit 1
fi
log_info "✓ Image: $PROD_IMAGE"

# Step 3: Check disk space
log_info "Checking disk space..."
AVAILABLE_KB=$(df "$BACKUP_DEST" | tail -1 | awk '{print $4}')
DATA_SIZE_KB=$(docker exec "$CONTAINER_NAME" du -sk /data 2>/dev/null | awk '{print $1}')
NEEDED_KB=$((DATA_SIZE_KB * 2))

if [ "$AVAILABLE_KB" -lt "$NEEDED_KB" ]; then
  log_error "Insufficient disk space"
  log_error "Available: $(($AVAILABLE_KB / 1024))MB, Needed: $(($NEEDED_KB / 1024))MB"
  exit 1
fi
log_info "✓ Disk space OK ($(($AVAILABLE_KB / 1024))MB available)"

# Define backup file path
BACKUP_FILE="$BACKUP_DEST/neo4j_${TIMESTAMP}.dump"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"

if $DRY_RUN; then
  log_info "[DRY-RUN] Would backup to: $BACKUP_FILE"
  log_info "[DRY-RUN] Would generate checksum: $CHECKSUM_FILE"
  exit 2
fi

# Step 4: Stop container
log_info "Stopping container $CONTAINER_NAME..."
if ! docker stop "$CONTAINER_NAME"; then
  log_error "Failed to stop container"
  exit 1
fi
sleep 5

if docker ps | grep -q "$CONTAINER_NAME"; then
  log_error "Container still running after stop"
  exit 1
fi
log_info "✓ Container stopped"

# Step 5: Execute backup
log_info "Creating backup dump..."
if ! docker run --rm \
  -v /opt/knowledge-services/neo4j/data:/data \
  -v "$BACKUP_DEST":/backup \
  --entrypoint neo4j-admin \
  "$PROD_IMAGE" \
  database dump neo4j --to-path=/backup/ 2>&1 | tee "$BACKUP_DEST/dump_${TIMESTAMP}.log"; then
  log_error "Backup dump failed; restarting container"
  docker compose -C /opt/knowledge-services/neo4j up -d "$CONTAINER_NAME" 2>/dev/null || \
    docker start "$CONTAINER_NAME"
  exit 1
fi

# Rename dump to timestamped file
if ! mv "$BACKUP_DEST/neo4j.dump" "$BACKUP_FILE"; then
  log_error "Failed to rename dump file"
  exit 1
fi
log_info "✓ Backup dump created: $(basename "$BACKUP_FILE")"

# Step 6: Generate checksum
log_info "Generating SHA256 checksum..."
if ! sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"; then
  log_error "Failed to generate checksum"
  exit 1
fi
log_info "✓ Checksum: $(cat "$CHECKSUM_FILE")"

# Step 7: Restart container
log_info "Restarting container..."
if ! docker compose -f /opt/knowledge-services/neo4j/compose.yaml up -d; then
  log_error "Failed to restart container via compose"
  if ! docker start "$CONTAINER_NAME"; then
    log_error "Failed to start container via docker start"
    exit 1
  fi
fi

sleep 30 # Wait for healthcheck

if ! docker ps | grep -q "$CONTAINER_NAME"; then
  log_error "Container failed to start"
  exit 1
fi
log_info "✓ Container restarted"

# Step 8: Validate Neo4j is responding
log_info "Validating Neo4j connectivity..."
MAX_RETRIES=10
for i in $(seq 1 $MAX_RETRIES); do
  if docker exec "$CONTAINER_NAME" cypher-shell --version &>/dev/null; then
    log_info "✓ Neo4j is responding"
    break
  fi
  if [ $i -eq $MAX_RETRIES ]; then
    log_error "Neo4j failed to respond after restart"
    exit 1
  fi
  sleep 10
done

# Step 9: Log summary
log_info "Backup completed successfully!"
log_info "File: $BACKUP_FILE"
log_info "Size: $(ls -lh "$BACKUP_FILE" | awk '{print $5}')"
log_info "Checksum: $(cat "$CHECKSUM_FILE")"

# Log to backup journal
{
  echo "Timestamp: $(date)"
  echo "Status: SUCCESS"
  echo "File: $BACKUP_FILE"
  echo "Size: $(ls -lh "$BACKUP_FILE" | awk '{print $5}')"
  echo "Checksum: $(cat "$CHECKSUM_FILE")"
  echo "Container: $CONTAINER_NAME"
  echo "Image: $PROD_IMAGE"
} >> "$BACKUP_DEST/backup.log"

exit 0

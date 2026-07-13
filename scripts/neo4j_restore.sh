#!/bin/bash
################################################################################
# neo4j_restore.sh — Restore Neo4j database from dump file
#
# Usage:
#   neo4j_restore.sh [--dry-run] [--dump FILE] [--to-new-instance]
#
# Options:
#   --dry-run              Show what would be done without executing
#   --dump FILE            Path to .dump file (required)
#   --to-new-instance      Restore to new instance for validation (default: false)
#   --new-instance-path    Path for new instance data (default: /tmp/neo4j-restore-test)
#
# Example:
#   neo4j_restore.sh --dry-run --dump /opt/backups/neo4j/neo4j_20260713_120000.dump
#   neo4j_restore.sh --dump /opt/backups/neo4j/neo4j_20260713_120000.dump --to-new-instance
#
# Exit codes:
#   0: Success
#   1: Error
#   2: Dry-run mode
#
# Author: AgentC
# Date: 2026-07-13
################################################################################

set -o pipefail

# Defaults
DRY_RUN=false
DUMP_FILE=""
TO_NEW_INSTANCE=false
NEW_INSTANCE_PATH="/tmp/neo4j-restore-test"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

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
    --dump)
      DUMP_FILE="$2"
      shift 2
      ;;
    --to-new-instance)
      TO_NEW_INSTANCE=true
      shift
      ;;
    --new-instance-path)
      NEW_INSTANCE_PATH="$2"
      shift 2
      ;;
    *)
      log_error "Unknown option: $1"
      echo "Usage: $0 [--dry-run] --dump FILE [--to-new-instance]"
      exit 1
      ;;
  esac
done

# Validate dump file argument
if [ -z "$DUMP_FILE" ]; then
  log_error "Dump file required: --dump FILE"
  exit 1
fi

# Validate dump file exists
if ! [ -f "$DUMP_FILE" ]; then
  log_error "Dump file not found: $DUMP_FILE"
  exit 1
fi

log_info "Neo4j Restore Script"
log_info "Dump file: $DUMP_FILE"
log_info "Dump size: $(ls -lh "$DUMP_FILE" | awk '{print $5}')"
if $TO_NEW_INSTANCE; then
  log_info "Target: New instance at $NEW_INSTANCE_PATH"
else
  log_info "Target: Production container (neo4j-knowledge)"
fi
if $DRY_RUN; then log_info "Mode: DRY-RUN"; fi

# Step 1: Validate checksum
log_info "Validating dump checksum..."
DUMP_DIR=$(dirname "$DUMP_FILE")
CHECKSUM_FILE="${DUMP_FILE}.sha256"

if ! [ -f "$CHECKSUM_FILE" ]; then
  log_warn "Checksum file not found: $CHECKSUM_FILE"
  log_warn "Skipping integrity check (file unverified)"
else
  if ! sha256sum -c "$CHECKSUM_FILE" &>/dev/null; then
    log_error "Checksum validation failed!"
    log_error "Dump file may be corrupted: $DUMP_FILE"
    exit 1
  fi
  log_info "✓ Checksum validated: $(cat "$CHECKSUM_FILE")"
fi

# Step 2: Get Docker image
log_info "Retrieving Docker image..."
PROD_IMAGE=$(docker inspect neo4j-knowledge --format '{{.Config.Image}}' 2>/dev/null)
if [ -z "$PROD_IMAGE" ]; then
  PROD_IMAGE="neo4j:5.26.0-community"
  log_warn "Container neo4j-knowledge not found; using default image: $PROD_IMAGE"
fi
log_info "Image: $PROD_IMAGE"

if $DRY_RUN; then
  log_info "[DRY-RUN] Would load dump from: $DUMP_FILE"
  if $TO_NEW_INSTANCE; then
    log_info "[DRY-RUN] Would create new instance at: $NEW_INSTANCE_PATH"
    log_info "[DRY-RUN] Would start container with ports 7577 (HTTP) and 7478 (Bolt)"
  else
    log_error "[DRY-RUN] Production restore not recommended in dry-run (missing disaster context)"
  fi
  exit 2
fi

if $TO_NEW_INSTANCE; then
  # Restore to new instance (validation mode)
  log_info "Preparing new instance..."
  mkdir -p "$NEW_INSTANCE_PATH/data" "$NEW_INSTANCE_PATH/logs" || {
    log_error "Failed to create instance directories"
    exit 1
  }
  chmod -R 755 "$NEW_INSTANCE_PATH" || {
    log_error "Failed to set permissions"
    exit 1
  }

  log_info "Loading dump to new instance..."
  if ! docker run --rm \
    -v "$NEW_INSTANCE_PATH/data":/data \
    -v "$DUMP_DIR":/backup \
    --entrypoint neo4j-admin \
    "$PROD_IMAGE" \
    database load neo4j --from-path=/backup/ --overwrite-destination=true 2>&1 | tee "$NEW_INSTANCE_PATH/load.log"; then
    log_error "Dump load failed"
    exit 1
  fi
  log_info "✓ Dump loaded to instance"

  log_info "Starting new Neo4j instance..."
  NEW_CONTAINER_NAME="neo4j-restore-test-$(date +%s)"
  if ! docker run -d \
    --name "$NEW_CONTAINER_NAME" \
    -p 7577:7474 \
    -p 7478:7687 \
    -e NEO4J_AUTH=neo4j/restore_test_pass_change_me \
    -e NEO4J_server_memory_heap_max__size=512m \
    -v "$NEW_INSTANCE_PATH/data":/data \
    -v "$NEW_INSTANCE_PATH/logs":/logs \
    "$PROD_IMAGE"; then
    log_error "Failed to start new instance"
    exit 1
  fi
  log_info "Container started: $NEW_CONTAINER_NAME"
  log_info "HTTP: http://localhost:7577"
  log_info "Bolt: bolt://localhost:7478"
  log_info "Auth: neo4j / restore_test_pass_change_me"

  log_warn "IMPORTANT: Change password before connecting!"
  log_warn "To clean up: docker stop $NEW_CONTAINER_NAME && docker rm $NEW_CONTAINER_NAME"
  log_info "Waiting 60s for startup..."
  sleep 60

  log_info "Validating restore..."
  if docker exec "$NEW_CONTAINER_NAME" cypher-shell -u neo4j -p restore_test_pass_change_me \
    --format plain "MATCH (n) RETURN count(n) as node_count;" 2>&1 | grep -q "node_count"; then
    log_info "✓ Restore successful; node count query executed"
    log_info "✓ Next step: verify data integrity in HTTP console or cypher-shell"
  else
    log_error "Failed to validate restore"
    exit 1
  fi

else
  # Restore to production (dangerous, requires explicit approval)
  log_error "Restoring to production (neo4j-knowledge) requires explicit approval"
  log_error "This operation will:"
  log_error "  1. Stop neo4j-knowledge"
  log_error "  2. Backup current /data"
  log_error "  3. Load dump (DESTRUCTIVE)"
  log_error "  4. Restart Neo4j"
  log_error ""
  log_error "Use ONLY for disaster recovery!"
  log_error "Better approach: use --to-new-instance first for validation"
  exit 1
fi

log_info "Restore completed successfully!"
exit 0

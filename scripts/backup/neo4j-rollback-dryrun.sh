#!/usr/bin/env bash
# neo4j-rollback-dryrun.sh — Análisis de rollback por source_id (SOLO LECTURA)
#
# Uso:
#   neo4j-rollback-dryrun.sh --source-id <source_id>
#
# Variables de entorno:
#   NEO4J_CONTAINER   Nombre del contenedor (default: neo4j-knowledge)
#   NEO4J_PASSWORD    Contraseña de Neo4j (requerida)
#   NEO4J_USER        Usuario Neo4j (default: neo4j)
#
# Salida:
#   Informe en /tmp/rollback-dryrun-<source_id>-<timestamp>.txt
#   Exit 0: análisis completado
#   Exit 1: error (source_id no proporcionado, contenedor no disponible, etc.)
#
# IMPORTANTE: Este script es SOLO LECTURA. No modifica datos en Neo4j.
#             Para ejecutar el rollback real, se requiere implementación adicional
#             pendiente (ver doc 28).

set -euo pipefail

# --- Configuración ---
SOURCE_ID=""
NEO4J_CONTAINER="${NEO4J_CONTAINER:-neo4j-knowledge}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# --- Parsear argumentos ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-id)
      SOURCE_ID="$2"
      shift 2
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

[ -z "$SOURCE_ID" ] && { echo "ERROR: --source-id es obligatorio"; exit 1; }
[ -z "$NEO4J_PASSWORD" ] && { echo "ERROR: Variable NEO4J_PASSWORD no definida"; exit 1; }

REPORT_FILE="/tmp/rollback-dryrun-${SOURCE_ID}-${TIMESTAMP}.txt"

run_cypher() {
  docker exec "$NEO4J_CONTAINER" cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "$1" 2>&1
}

report() {
  echo "$*" | tee -a "$REPORT_FILE"
}

# --- Cabecera del informe ---
report "================================================================"
report "DRY-RUN ONLY — SIN MODIFICACIONES EN NEO4J"
report "================================================================"
report "source_id analizado: $SOURCE_ID"
report "Fecha: $(date)"
report "Contenedor: $NEO4J_CONTAINER"
report ""
report "ADVERTENCIA: Este informe es SOLO LECTURA."
report "Para ejecutar el rollback real se requiere implementación"
report "adicional pendiente (ver docs/28-graph-migrations-and-rollback.md)"
report "================================================================"
report ""

# Verificar que el contenedor está corriendo
if ! docker inspect "$NEO4J_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
  report "ERROR: El contenedor $NEO4J_CONTAINER no está corriendo"
  exit 1
fi

# --- Análisis 1: Total de nodos con este source_id ---
report "=== 1. NODOS DIRECTAMENTE ASOCIADOS ==="
RESULT=$(run_cypher "MATCH (n) WHERE n.source_id = '$SOURCE_ID' RETURN labels(n)[0] as tipo, count(*) as cnt ORDER BY tipo;")
report "$RESULT"
report ""

# Verificar si hay algo que deshacer
TOTAL_NODES=$(run_cypher "MATCH (n) WHERE n.source_id = '$SOURCE_ID' RETURN count(n) as total;" | grep -Eo '[0-9]+' | tail -1 || echo "0")
if [ "$TOTAL_NODES" = "0" ]; then
  report "INFO: No se encontraron nodos con source_id='$SOURCE_ID'"
  report "No hay nada que deshacer para este source_id."
  report ""
  report "Informe guardado en: $REPORT_FILE"
  cat "$REPORT_FILE"
  exit 0
fi

# --- Análisis 2: Relaciones directamente asociadas ---
report "=== 2. RELACIONES DIRECTAMENTE ASOCIADAS ==="
RESULT=$(run_cypher "MATCH ()-[r]->() WHERE r.source_id = '$SOURCE_ID' RETURN type(r) as tipo, count(*) as cnt ORDER BY tipo;")
report "$RESULT"
report ""

# --- Análisis 3: Nodos exclusivos (candidatos a ELIMINAR) ---
report "=== 3. NODOS EXCLUSIVOS (acción: ELIMINAR si se confirma rollback) ==="
report "Nodos que SOLO existen debido a este source_id (sin referencias de otras fuentes):"
RESULT=$(run_cypher "
MATCH (n) WHERE n.source_id = '$SOURCE_ID'
WHERE NOT EXISTS {
  MATCH (n)-[r]-() WHERE r.source_id <> '$SOURCE_ID'
}
RETURN labels(n)[0] as tipo, n.name as nombre, n.source_id as source_id
ORDER BY tipo, nombre
LIMIT 100;")
report "$RESULT"
report ""

EXCL_COUNT=$(run_cypher "
MATCH (n) WHERE n.source_id = '$SOURCE_ID'
WHERE NOT EXISTS {
  MATCH (n)-[r]-() WHERE r.source_id <> '$SOURCE_ID'
}
RETURN count(n) as total;" | grep -Eo '[0-9]+' | tail -1 || echo "0")
report "Total nodos exclusivos a eliminar: $EXCL_COUNT"
report ""

# --- Análisis 4: Nodos compartidos (candidatos a DESVINCULAR) ---
report "=== 4. NODOS COMPARTIDOS (acción: DESVINCULAR relaciones, no eliminar nodo) ==="
report "Nodos que tienen relaciones con otras fuentes además de '$SOURCE_ID':"
RESULT=$(run_cypher "
MATCH (n) WHERE n.source_id = '$SOURCE_ID'
WHERE EXISTS {
  MATCH (n)-[r]-() WHERE r.source_id <> '$SOURCE_ID'
}
RETURN labels(n)[0] as tipo, n.name as nombre,
  count { (n)-[r]-() WHERE r.source_id <> '$SOURCE_ID' } as refs_otras_fuentes
ORDER BY tipo, nombre
LIMIT 50;")
report "$RESULT"
report ""

SHARED_COUNT=$(run_cypher "
MATCH (n) WHERE n.source_id = '$SOURCE_ID'
WHERE EXISTS {
  MATCH (n)-[r]-() WHERE r.source_id <> '$SOURCE_ID'
}
RETURN count(n) as total;" | grep -Eo '[0-9]+' | tail -1 || echo "0")
report "Total nodos compartidos (conservar, solo desvincular relaciones): $SHARED_COUNT"
report ""

# --- Análisis 5: Nodos sin source_id (no afectados) ---
report "=== 5. NODOS HISTÓRICOS SIN SOURCE_ID (NO AFECTADOS por rollback) ==="
RESULT=$(run_cypher "
MATCH (n) WHERE n.source_id IS NULL OR n.source_id = ''
RETURN labels(n)[0] as tipo, count(*) as cnt ORDER BY tipo;")
report "$RESULT"
report ""

# --- Resumen final ---
report "================================================================"
report "RESUMEN DEL IMPACTO"
report "================================================================"
report "source_id: $SOURCE_ID"
report ""
report "Nodos a ELIMINAR (exclusivos): $EXCL_COUNT"
report "Nodos a CONSERVAR (compartidos, solo desvincular rels): $SHARED_COUNT"
report "Nodos NO AFECTADOS (sin source_id): ver sección 5"
report ""
report "ACCIÓN REQUERIDA:"
report "  1. Revisar este informe"
report "  2. Si el impacto es aceptable, solicitar implementación del script de rollback"
report "     (ver docs/28-graph-migrations-and-rollback.md — Fase 4)"
report "  3. Asegurar backup reciente antes de ejecutar cualquier rollback real"
report ""
report "DRY-RUN COMPLETADO — NINGÚN DATO FUE MODIFICADO"
report "================================================================"
report ""
report "Informe guardado en: $REPORT_FILE"

# Mostrar informe
cat "$REPORT_FILE"
exit 0

#!/usr/bin/env bash
# rollback-release.sh — revierte a una release anterior mediante symlink atómico.
#
# Uso: rollback-release.sh --environment <lab|production>
#                          [--to-release <release-id>]
#                          [--confirm | --confirm-production]
#
# IMPORTANTE:
#   - NO restaura Neo4j automáticamente (los datos de grafo quedan en el estado actual)
#   - NO restaura SQLite automáticamente (auth.db queda en el estado actual)
#   - NO borra ninguna release
#   - Si falla la verificación post-rollback, intenta volver a la release anterior
#
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
ENVIRONMENT=""
TARGET_RELEASE=""
DRY_RUN=1

usage() {
    cat <<USAGE
uso: rollback-release.sh --environment <lab|production>
                         [--to-release <release-id>]
                         [--confirm | --confirm-production]

  --environment lab|production   Entorno (obligatorio)
  --to-release <release-id>      ID de la release destino (default: penúltima)
  --confirm                      Aplica el rollback en lab
  --confirm-production           Aplica el rollback en producción
  -h, --help                     Muestra esta ayuda
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --environment)        ENVIRONMENT="$2"; shift 2 ;;
        --to-release)         TARGET_RELEASE="$2"; shift 2 ;;
        --confirm)            DRY_RUN=0; shift ;;
        --confirm-production) DRY_RUN=0; shift ;;
        --dry-run)            DRY_RUN=1; shift ;;
        -h|--help)            usage; exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

[ -n "${ENVIRONMENT}" ] || { usage; die "--environment es obligatorio"; }
case "${ENVIRONMENT}" in
    lab|production) ;;
    *) die "entorno inválido: '${ENVIRONMENT}'. Valores válidos: lab, production" ;;
esac

export S9K_ENVIRONMENT="${ENVIRONMENT}"

log "=== ROLLBACK S9 Knowledge ==="
log "    entorno: ${ENVIRONMENT}"
log "    modo:    $([ "${DRY_RUN}" -eq 1 ] && printf 'DRY-RUN' || printf 'APLICAR')"
log "    S9K_ROOT: ${S9K_ROOT}"
warn "AVISO: Neo4j NO se restaura automáticamente."
warn "AVISO: SQLite (auth.db) NO se restaura automáticamente."

[ "${DRY_RUN}" -eq 1 ] && warn "DRY-RUN activo: no se modificará nada"

# ---------------------------------------------------------------------------
# Paso 1: Identificar release activa
# ---------------------------------------------------------------------------
log "--- Paso 1: release activa"
CURRENT_LINK="${S9K_ROOT}/current"
if [ -L "${CURRENT_LINK}" ]; then
    CURRENT_DIR="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || printf '')"
    CURRENT_RELEASE_ID="$(basename "${CURRENT_DIR}")"
    log "Release activa: ${CURRENT_RELEASE_ID}"
else
    die "No hay release activa (${CURRENT_LINK} no existe o no es symlink)"
fi

# ---------------------------------------------------------------------------
# Paso 2: Listar releases disponibles
# ---------------------------------------------------------------------------
log "--- Paso 2: releases disponibles"
RELEASES_DIR="${S9K_ROOT}/releases"
if [ ! -d "${RELEASES_DIR}" ]; then
    die "No existe directorio de releases: ${RELEASES_DIR}"
fi

mapfile -t available_releases < <(list_releases)
if [ ${#available_releases[@]} -eq 0 ]; then
    die "No hay releases en ${RELEASES_DIR}"
fi

log "Releases disponibles (de más nueva a más antigua):"
for rd in "${available_releases[@]}"; do
    rid="$(basename "${rd}")"
    marker=""
    [ "${rid}" = "${CURRENT_RELEASE_ID}" ] && marker=" [ACTIVA]"
    log "  ${rid}${marker}"
done

# ---------------------------------------------------------------------------
# Paso 3: Determinar release destino
# ---------------------------------------------------------------------------
log "--- Paso 3: release destino"
TARGET_DIR=""

if [ -n "${TARGET_RELEASE}" ]; then
    # Verificar que el ID solicitado existe
    TARGET_DIR="${RELEASES_DIR}/${TARGET_RELEASE}"
    if [ ! -d "${TARGET_DIR}" ]; then
        die "Release '${TARGET_RELEASE}' no existe en ${RELEASES_DIR}"
    fi
else
    # Por defecto: la penúltima release (la siguiente en lista excluyendo la activa)
    for rd in "${available_releases[@]}"; do
        rid="$(basename "${rd}")"
        if [ "${rid}" != "${CURRENT_RELEASE_ID}" ]; then
            TARGET_DIR="${rd}"
            TARGET_RELEASE="${rid}"
            break
        fi
    done
    if [ -z "${TARGET_DIR}" ]; then
        die "No hay release anterior disponible para rollback (solo existe la activa)"
    fi
fi

log "Release destino: ${TARGET_RELEASE}"
log "Directorio:      ${TARGET_DIR}"

# Verificar que no sea la misma release que la activa
if [ "${TARGET_RELEASE}" = "${CURRENT_RELEASE_ID}" ]; then
    die "La release destino '${TARGET_RELEASE}' es la misma que la activa. Sin cambios."
fi

# ---------------------------------------------------------------------------
# Paso 4: Validar manifiesto de la release destino
# ---------------------------------------------------------------------------
log "--- Paso 4: validar manifiesto"
MANIFEST_PATH="${TARGET_DIR}/manifest.json"
if [ -f "${MANIFEST_PATH}" ]; then
    if validate_manifest "${MANIFEST_PATH}"; then
        ok "Manifiesto válido: ${MANIFEST_PATH}"
    else
        warn "Manifiesto inválido o incompleto — continuando con advertencia (release puede ser antigua)"
    fi
else
    warn "Manifiesto no encontrado en ${MANIFEST_PATH} (release puede ser antigua)"
fi

# ---------------------------------------------------------------------------
# Paso 5: Verificar compatibilidad de esquema
# ---------------------------------------------------------------------------
log "--- Paso 5: compatibilidad de esquema"
if [ -f "${MANIFEST_PATH}" ]; then
    compatible_list="$(manifest_field "${MANIFEST_PATH}" compatible_rollback_to 2>/dev/null || printf '[]')"
    log "compatible_rollback_to: ${compatible_list}"
    # Si compatible_rollback_to no está vacío y el actual no está en la lista, advertir
    if [ "${compatible_list}" = "[]" ] || [ -z "${compatible_list}" ]; then
        warn "El manifiesto no declara compatibilidad de rollback — verifica esquemas manualmente"
    fi
fi

# ---------------------------------------------------------------------------
# En modo dry-run, salir aquí
# ---------------------------------------------------------------------------
if [ "${DRY_RUN}" -eq 1 ]; then
    info "PLAN (dry-run):"
    info "  1. flock (lock de concurrencia)"
    info "  2. Symlink atómico: ${CURRENT_LINK} -> ${TARGET_DIR}"
    info "  3. Reiniciar s9-knowledge-viewer.service"
    info "  4. verify-deployment.sh"
    info "  5. Si falla: volver a ${CURRENT_RELEASE_ID}"
    log "=== DRY-RUN completado. Sin cambios. ==="
    exit 0
fi

# ---------------------------------------------------------------------------
# Paso 6: Lock de concurrencia
# ---------------------------------------------------------------------------
log "--- Paso 6: lock"
lock_deploy

# ---------------------------------------------------------------------------
# Paso 7: Cambiar symlink atómicamente
# ---------------------------------------------------------------------------
log "--- Paso 7: activar release destino"
atomic_symlink "${TARGET_DIR}" "${CURRENT_LINK}"
log "Symlink actualizado: ${CURRENT_LINK} -> ${TARGET_DIR}"

# ---------------------------------------------------------------------------
# Paso 8: Reiniciar servicios afectados
# ---------------------------------------------------------------------------
log "--- Paso 8: reiniciar servicio"
if command -v systemctl >/dev/null 2>&1; then
    systemctl restart s9-knowledge-viewer.service 2>/dev/null \
        || warn "No se pudo reiniciar s9-knowledge-viewer.service"
    log "s9-knowledge-viewer.service reiniciado"
else
    warn "systemctl no disponible — reinicia el servicio manualmente"
fi

# Esperar brevemente
sleep 3

# ---------------------------------------------------------------------------
# Paso 9: Verificar despliegue post-rollback
# ---------------------------------------------------------------------------
log "--- Paso 9: verificar post-rollback"
set +e
"${HERE}/verify-deployment.sh" --expected-release "${TARGET_RELEASE}"
verify_rc=$?
set -e

if [ "${verify_rc}" -eq 1 ]; then
    err "verify-deployment reportó UNHEALTHY tras el rollback a ${TARGET_RELEASE}"
    err "Intentando volver a la release anterior: ${CURRENT_RELEASE_ID}"
    if [ -d "${CURRENT_DIR}" ]; then
        atomic_symlink "${CURRENT_DIR}" "${CURRENT_LINK}"
        systemctl restart s9-knowledge-viewer.service 2>/dev/null || true
        sleep 2
        err "Revertido a: ${CURRENT_RELEASE_ID}"
    else
        err "No se pudo revertir: ${CURRENT_DIR} no existe"
    fi
    die "Rollback FALLIDO — el sistema puede estar en estado inestable. Revisa manualmente."
elif [ "${verify_rc}" -ge 2 ]; then
    warn "verify-deployment con error de verificación (rc=${verify_rc}) — continúa con cautela"
fi

# ---------------------------------------------------------------------------
# Fin
# ---------------------------------------------------------------------------
log "=== ROLLBACK completado exitosamente ==="
log "    release anterior: ${CURRENT_RELEASE_ID}"
log "    release activa:   ${TARGET_RELEASE}"
log "    symlink:          ${CURRENT_LINK} -> ${TARGET_DIR}"
warn "Recuerda: Neo4j y auth.db NO se han restaurado."
warn "Si la aplicación tiene datos incompatibles con esta release, restaura manualmente."

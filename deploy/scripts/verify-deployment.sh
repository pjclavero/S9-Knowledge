#!/usr/bin/env bash
# verify-deployment.sh — verifica el estado del despliegue activo.
#
# Distingue:
#   HEALTHY   = todos los checks pasan
#   DEGRADED  = servicio responde pero algún check opcional falla
#   UNHEALTHY = servicio crítico no responde o release rota
#   UNKNOWN   = no se puede determinar el estado
#
# Salida:
#   0 = HEALTHY o DEGRADED (aceptable)
#   1 = UNHEALTHY
#   2 = ERROR de verificación (no se pudo ejecutar correctamente)
#
# NO modifica Neo4j, NO limpia jobs, NO reinicia servicios.
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
EXPECTED_RELEASE="${S9K_EXPECTED_RELEASE:-}"

while [ $# -gt 0 ]; do
    case "$1" in
        --expected-release) EXPECTED_RELEASE="$2"; shift 2 ;;
        -h|--help)
            printf 'uso: verify-deployment.sh [--expected-release <release-id>]\n'
            exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Estado interno
# ---------------------------------------------------------------------------
STATUS="HEALTHY"
degraded_reasons=()
unhealthy_reasons=()
check_errors=()

mark_degraded() { STATUS="DEGRADED"; degraded_reasons+=("$*"); warn "DEGRADED: $*"; }
mark_unhealthy() { STATUS="UNHEALTHY"; unhealthy_reasons+=("$*"); err "UNHEALTHY: $*"; }
mark_error()    { STATUS="UNKNOWN"; check_errors+=("$*"); err "CHECK ERROR: $*"; }

log "=== VERIFY DEPLOYMENT S9 Knowledge ==="
log "    S9K_ROOT:        ${S9K_ROOT}"
log "    S9K_STATE_ROOT:  ${S9K_STATE_ROOT}"
log "    S9K_VIEWER_URL:  ${S9K_VIEWER_URL}"

# ---------------------------------------------------------------------------
# Check 1: release activa (symlink current)
# ---------------------------------------------------------------------------
log "--- [1/9] symlink current"
CURRENT_LINK="${S9K_ROOT}/current"
if [ -L "${CURRENT_LINK}" ]; then
    ACTIVE_DIR="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || printf '')"
    if [ -d "${ACTIVE_DIR}" ]; then
        ACTIVE_RELEASE_ID="$(basename "${ACTIVE_DIR}")"
        ok "release activa: ${ACTIVE_RELEASE_ID}"
    else
        mark_unhealthy "symlink ${CURRENT_LINK} apunta a directorio inexistente: ${ACTIVE_DIR}"
        ACTIVE_DIR=""
        ACTIVE_RELEASE_ID=""
    fi
else
    mark_unhealthy "symlink ${CURRENT_LINK} no existe — sin release activa"
    ACTIVE_DIR=""
    ACTIVE_RELEASE_ID=""
fi

# ---------------------------------------------------------------------------
# Check 2: commit activo coincide con expected (si se pasó)
# ---------------------------------------------------------------------------
log "--- [2/9] commit release"
if [ -n "${EXPECTED_RELEASE}" ] && [ -n "${ACTIVE_RELEASE_ID}" ]; then
    if [ "${ACTIVE_RELEASE_ID}" = "${EXPECTED_RELEASE}" ]; then
        ok "release activa coincide con esperada: ${ACTIVE_RELEASE_ID}"
    else
        mark_unhealthy "release activa '${ACTIVE_RELEASE_ID}' != esperada '${EXPECTED_RELEASE}'"
    fi
elif [ -n "${ACTIVE_RELEASE_ID}" ]; then
    # Verificar manifiesto
    if [ -f "${ACTIVE_DIR}/manifest.json" ]; then
        manifest_commit="$(manifest_field "${ACTIVE_DIR}/manifest.json" git_commit 2>/dev/null || printf 'unknown')"
        ok "manifiesto: release=${ACTIVE_RELEASE_ID} commit=${manifest_commit}"
    else
        mark_degraded "manifiesto no encontrado en ${ACTIVE_DIR}/manifest.json"
    fi
fi

# ---------------------------------------------------------------------------
# Check 3: .venv presente en la release
# ---------------------------------------------------------------------------
log "--- [3/9] .venv"
if [ -n "${ACTIVE_DIR}" ]; then
    VENV_PY="${ACTIVE_DIR}/viewer/.venv/bin/python"
    if [ -x "${VENV_PY}" ]; then
        py_ver="$("${VENV_PY}" --version 2>&1 | awk '{print $2}' || printf 'unknown')"
        ok ".venv presente: Python ${py_ver}"
    else
        mark_unhealthy ".venv no encontrado o no ejecutable: ${ACTIVE_DIR}/viewer/.venv/bin/python"
        VENV_PY=""
    fi
else
    mark_error "no hay release activa; skip check .venv"
    VENV_PY=""
fi

# ---------------------------------------------------------------------------
# Check 4: imports Python básicos
# ---------------------------------------------------------------------------
log "--- [4/9] imports Python"
if [ -n "${VENV_PY:-}" ] && [ -x "${VENV_PY}" ]; then
    set +e
    "${VENV_PY}" -c "import fastapi, neo4j, argon2" 2>/dev/null
    import_rc=$?
    set -e
    if [ "${import_rc}" -eq 0 ]; then
        ok "imports Python: fastapi, neo4j, argon2 OK"
    else
        # Intentar diagnóstico más fino
        missing=()
        for pkg in fastapi neo4j argon2; do
            if ! "${VENV_PY}" -c "import ${pkg}" 2>/dev/null; then
                missing+=("${pkg}")
            fi
        done
        mark_degraded "imports fallidos: ${missing[*]+"${missing[*]}"}"
    fi
else
    mark_error "skip imports: .venv no disponible"
fi

# ---------------------------------------------------------------------------
# Check 5: servicio systemd activo
# ---------------------------------------------------------------------------
log "--- [5/9] servicio systemd"
if command -v systemctl >/dev/null 2>&1; then
    set +e
    svc_active="$(systemctl is-active s9-knowledge-viewer.service 2>/dev/null || printf 'unknown')"
    set -e
    case "${svc_active}" in
        active)
            ok "s9-knowledge-viewer.service: ${svc_active}" ;;
        activating)
            mark_degraded "s9-knowledge-viewer.service arrancando (${svc_active})" ;;
        failed|inactive)
            mark_unhealthy "s9-knowledge-viewer.service: ${svc_active}" ;;
        *)
            mark_degraded "s9-knowledge-viewer.service: estado desconocido (${svc_active})" ;;
    esac
else
    mark_degraded "systemctl no disponible — servicio no verificado"
fi

# ---------------------------------------------------------------------------
# Check 6: /var/lib/s9-knowledge/ accesible
# ---------------------------------------------------------------------------
log "--- [6/9] directorio de estado"
if [ -d "${S9K_STATE_ROOT}" ] && [ -r "${S9K_STATE_ROOT}" ]; then
    ok "estado accesible: ${S9K_STATE_ROOT}"
else
    mark_unhealthy "directorio de estado no accesible: ${S9K_STATE_ROOT}"
fi

# ---------------------------------------------------------------------------
# Check 7: auth.db presente si auth activada
# ---------------------------------------------------------------------------
log "--- [7/9] auth.db"
AUTH_DB_PATH="${S9K_STATE_ROOT}/auth/auth.db"
# Verificamos si auth está habilitada mirando la config (sin cargar secretos)
AUTH_ENABLED="${S9K_AUTH_ENABLED:-}"
if [ "${AUTH_ENABLED}" = "true" ] || [ "${AUTH_ENABLED}" = "1" ]; then
    if [ -f "${AUTH_DB_PATH}" ]; then
        ok "auth.db presente (auth habilitada)"
    else
        mark_unhealthy "auth.db no encontrado en ${AUTH_DB_PATH} (auth habilitada)"
    fi
else
    if [ -f "${AUTH_DB_PATH}" ]; then
        ok "auth.db presente (auth deshabilitada pero db existe)"
    else
        ok "auth.db no requerido (auth deshabilitada o S9K_AUTH_ENABLED no definida)"
    fi
fi

# ---------------------------------------------------------------------------
# Check 8: Neo4j respondiendo
# ---------------------------------------------------------------------------
log "--- [8/9] Neo4j"
if port_listening 7687; then
    ok "Neo4j bolt 7687 escuchando"
else
    mark_degraded "Neo4j bolt 7687 no responde (puede ser remoto o parado)"
fi

# ---------------------------------------------------------------------------
# Check 9: endpoint HTTP /api/status (con timeout)
# ---------------------------------------------------------------------------
log "--- [9/9] endpoint HTTP"
if command -v curl >/dev/null 2>&1; then
    set +e
    http_code="$(curl -s -o /dev/null -w '%{http_code}' \
        --max-time 10 \
        --connect-timeout 5 \
        "${S9K_VIEWER_URL}/api/status" 2>/dev/null || printf '000')"
    set -e
    case "${http_code}" in
        200|401)
            ok "endpoint HTTP /api/status: HTTP ${http_code}" ;;
        000)
            mark_unhealthy "endpoint HTTP no responde (timeout/conexión rechazada) — ${S9K_VIEWER_URL}/api/status" ;;
        *)
            mark_degraded "endpoint HTTP responde con código inesperado: ${http_code}" ;;
    esac
else
    mark_degraded "curl no disponible — endpoint HTTP no verificado"
fi

# ---------------------------------------------------------------------------
# Resumen final
# ---------------------------------------------------------------------------
log "=== RESULTADO VERIFY: ${STATUS} ==="

if [ ${#unhealthy_reasons[@]} -gt 0 ]; then
    err "Razones UNHEALTHY:"
    for r in "${unhealthy_reasons[@]}"; do err "  - ${r}"; done
fi
if [ ${#degraded_reasons[@]} -gt 0 ]; then
    warn "Razones DEGRADED:"
    for r in "${degraded_reasons[@]}"; do warn "  - ${r}"; done
fi
if [ ${#check_errors[@]} -gt 0 ]; then
    err "Errores de verificación:"
    for r in "${check_errors[@]}"; do err "  - ${r}"; done
fi

case "${STATUS}" in
    HEALTHY|DEGRADED) exit 0 ;;
    UNHEALTHY)        exit 1 ;;
    UNKNOWN)          exit 2 ;;
    *)                exit 2 ;;
esac

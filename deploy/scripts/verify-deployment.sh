#!/usr/bin/env bash
# verify-deployment.sh — verifica el estado del despliegue activo.
#
# RESULTADO FINAL impreso en stdout:
#   VERIFICATION_OK      = todos los gates críticos pasaron
#   VERIFICATION_FAILED  = al menos un gate crítico falló
#   VERIFICATION_BLOCKED = no se pudo ejecutar la verificación correctamente
#
# Códigos de salida:
#   0 = VERIFICATION_OK
#   1 = VERIFICATION_FAILED
#   2 = VERIFICATION_BLOCKED
#
# NO modifica Neo4j, NO limpia jobs, NO reinicia servicios.
# shellcheck shell=bash
set -euo pipefail
# Nota: NO usamos -E (errtrace) porque impediría que `set +e` funcione
# correctamente en los bloques donde capturamos salidas de herramientas
# opcionales que pueden fallar (systemctl, curl). Sin -E, el ERR trap sigue
# activo en el script principal pero no se hereda en sustituciones de comando.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"

# ---------------------------------------------------------------------------
# Trap seguro en EXIT: informa del estado final cuando el script termina
# de forma inesperada (antes de llegar al case final). No filtra secretos
# porque no imprime valores de variables sensibles, solo nombres y códigos.
# ---------------------------------------------------------------------------
_VERIFY_PHASE="init"
_VERIFY_DONE=0
# shellcheck disable=SC2329  # función invocada exclusivamente vía `trap ... EXIT`
_trap_verify_exit() {
    local exit_code="${?:-?}"
    local line="${BASH_LINENO[0]:-?}"
    local cmd="${BASH_COMMAND:-?}"
    # Solo actúa si el script NO llegó a su propio final limpio
    if [ "${_VERIFY_DONE}" -eq 0 ] && [ "${exit_code}" -ne 0 ]; then
        # Saneado: truncar a 120 chars, sin expansiones adicionales
        cmd="${cmd:0:120}"
        err "VERIFY ERROR inesperado: fase=${_VERIFY_PHASE} linea=${line} rc=${exit_code}"
        err "  cmd=[${cmd}]"
        printf 'VERIFICATION_BLOCKED\n'
    fi
}
trap '_trap_verify_exit' EXIT

# ---------------------------------------------------------------------------
# Funciones de resultado de check.
# Las funciones son explícitas: el texto de un resultado NUNCA se ejecuta
# como comando (causa raíz del bug histórico con `ok` indefinida).
# ok() también está en lib.sh; se redefine localmente para claridad.
# ---------------------------------------------------------------------------
pass()       { log "PASS  $*"; }
fail_check() { err  "FAIL  $*"; }
skip_check() { warn "SKIP  $*"; }

# ---------------------------------------------------------------------------
# Estado interno
# ---------------------------------------------------------------------------
FINAL_STATUS="OK"            # OK | FAILED | BLOCKED
_critical_failed=0
_degraded_reasons=()
_failed_reasons=()
_check_errors=()

mark_failed() {
    FINAL_STATUS="FAILED"
    _critical_failed=$((_critical_failed + 1))
    _failed_reasons+=("$*")
    fail_check "$*"
}

mark_degraded() {
    _degraded_reasons+=("$*")
    warn "DEGRADED: $*"
}

mark_blocked() {
    FINAL_STATUS="BLOCKED"
    _check_errors+=("$*")
    err "BLOCKED: $*"
}

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
EXPECTED_RELEASE="${S9K_EXPECTED_RELEASE:-}"

_VERIFY_PHASE="args"
while [ $# -gt 0 ]; do
    case "$1" in
        --expected-release) EXPECTED_RELEASE="$2"; shift 2 ;;
        -h|--help)
            printf 'uso: verify-deployment.sh [--expected-release <release-id>]\n'
            exit 0 ;;
        *) mark_blocked "argumento desconocido: $1"; exit 2 ;;
    esac
done

log "=== VERIFY DEPLOYMENT S9 Knowledge ==="
log "    S9K_ROOT:        ${S9K_ROOT}"
log "    S9K_STATE_ROOT:  ${S9K_STATE_ROOT}"
log "    S9K_VIEWER_URL:  ${S9K_VIEWER_URL}"
[ -n "${EXPECTED_RELEASE}" ] && log "    EXPECTED_RELEASE: ${EXPECTED_RELEASE}"

# ---------------------------------------------------------------------------
# Check 1: release activa (symlink current)  [CRÍTICO]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check1-symlink"
log "--- [1/9] symlink current"
CURRENT_LINK="${S9K_ROOT}/current"
ACTIVE_DIR=""
ACTIVE_RELEASE_ID=""

if [ -L "${CURRENT_LINK}" ]; then
    _resolved="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
    if [ -n "${_resolved}" ] && [ -d "${_resolved}" ]; then
        ACTIVE_DIR="${_resolved}"
        ACTIVE_RELEASE_ID="$(basename "${ACTIVE_DIR}")"
        pass "release activa: ${ACTIVE_RELEASE_ID}"
    else
        mark_failed "symlink ${CURRENT_LINK} apunta a directorio inexistente: ${_resolved}"
    fi
else
    mark_failed "symlink ${CURRENT_LINK} no existe — sin release activa"
fi

# ---------------------------------------------------------------------------
# Check 2: commit activo coincide con expected  [CRÍTICO si aplica]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check2-commit"
log "--- [2/9] commit release"
if [ -n "${EXPECTED_RELEASE}" ] && [ -n "${ACTIVE_RELEASE_ID}" ]; then
    if [ "${ACTIVE_RELEASE_ID}" = "${EXPECTED_RELEASE}" ]; then
        pass "release activa coincide con esperada: ${ACTIVE_RELEASE_ID}"
    else
        mark_failed "release activa '${ACTIVE_RELEASE_ID}' != esperada '${EXPECTED_RELEASE}'"
    fi
elif [ -n "${ACTIVE_DIR}" ]; then
    _manifest="${ACTIVE_DIR}/manifest.json"
    if [ -f "${_manifest}" ]; then
        _manifest_commit="$(manifest_field "${_manifest}" git_commit 2>/dev/null || true)"
        [ -n "${_manifest_commit}" ] || _manifest_commit="unknown"
        pass "manifiesto: release=${ACTIVE_RELEASE_ID} commit=${_manifest_commit}"
    else
        mark_failed "manifiesto no encontrado en ${ACTIVE_DIR}/manifest.json"
    fi
fi

# ---------------------------------------------------------------------------
# Check 3: .venv presente en la release  [CRÍTICO]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check3-venv"
log "--- [3/9] .venv"
VENV_PY=""
if [ -n "${ACTIVE_DIR}" ]; then
    _venv_py="${ACTIVE_DIR}/viewer/.venv/bin/python"
    if [ -x "${_venv_py}" ]; then
        _py_ver=""
        _py_ver="$("${_venv_py}" --version 2>&1 || true)"
        _py_ver="${_py_ver:-unknown}"
        pass ".venv presente: ${_py_ver}"
        VENV_PY="${_venv_py}"
    else
        mark_failed ".venv no encontrado o no ejecutable: ${ACTIVE_DIR}/viewer/.venv/bin/python"
    fi
else
    skip_check "skip check .venv: no hay release activa"
fi

# ---------------------------------------------------------------------------
# Check 4: imports Python básicos  [DEGRADED si fallan]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check4-imports"
log "--- [4/9] imports Python"
if [ -n "${VENV_PY}" ] && [ -x "${VENV_PY}" ]; then
    _import_rc=0
    "${VENV_PY}" -c "import fastapi, neo4j, argon2" 2>/dev/null || _import_rc=$?
    if [ "${_import_rc}" -eq 0 ]; then
        pass "imports Python: fastapi, neo4j, argon2 OK"
    else
        _missing=()
        for _pkg in fastapi neo4j argon2; do
            "${VENV_PY}" -c "import ${_pkg}" 2>/dev/null || _missing+=("${_pkg}")
        done
        mark_degraded "imports fallidos: ${_missing[*]+"${_missing[*]}"}"
    fi
else
    skip_check "skip imports: .venv no disponible"
fi

# ---------------------------------------------------------------------------
# Check 5: servicio systemd activo  [CRÍTICO: inactive/failed = FAILED]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check5-systemd"
log "--- [5/9] servicio systemd"
if command -v systemctl >/dev/null 2>&1; then
    _svc_active=""
    # || true: expected to fail (service may not exist); captured via stdout
    _svc_active="$(systemctl is-active s9-knowledge-viewer.service 2>/dev/null || true)"
    # Take only the first line (systemctl may print multiple lines on some systems)
    _svc_active="$(printf '%s' "${_svc_active}" | head -1 || true)"
    [ -n "${_svc_active}" ] || _svc_active="unknown"
    # Validate output: systemctl is-active returns known keywords
    case "${_svc_active}" in
        active)
            pass "s9-knowledge-viewer.service: ${_svc_active}" ;;
        activating)
            mark_degraded "s9-knowledge-viewer.service arrancando (${_svc_active})" ;;
        failed|inactive)
            mark_failed "s9-knowledge-viewer.service: ${_svc_active}" ;;
        unknown|deactivating|reloading|*)
            mark_degraded "s9-knowledge-viewer.service: estado inesperado (${_svc_active})" ;;
    esac
else
    skip_check "systemctl no disponible (herramienta opcional) — servicio no verificado"
fi

# ---------------------------------------------------------------------------
# Check 6: /var/lib/s9-knowledge/ accesible  [CRÍTICO]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check6-state-dir"
log "--- [6/9] directorio de estado"
if [ -d "${S9K_STATE_ROOT}" ] && [ -r "${S9K_STATE_ROOT}" ]; then
    pass "estado accesible: ${S9K_STATE_ROOT}"
else
    mark_failed "directorio de estado no accesible: ${S9K_STATE_ROOT}"
fi

# ---------------------------------------------------------------------------
# Check 7: auth.db presente si auth activada  [CRÍTICO si auth=true]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check7-auth-db"
log "--- [7/9] auth.db"
_auth_db_path="${S9K_STATE_ROOT}/auth/auth.db"
_auth_enabled="${S9K_AUTH_ENABLED:-}"
if [ "${_auth_enabled}" = "true" ] || [ "${_auth_enabled}" = "1" ]; then
    if [ -f "${_auth_db_path}" ]; then
        pass "auth.db presente (auth habilitada)"
    else
        mark_failed "auth.db no encontrado en ${_auth_db_path} (auth habilitada)"
    fi
else
    if [ -f "${_auth_db_path}" ]; then
        pass "auth.db presente (auth deshabilitada pero db existe)"
    else
        pass "auth.db no requerido (auth deshabilitada o S9K_AUTH_ENABLED no definida)"
    fi
fi

# ---------------------------------------------------------------------------
# Check 8: Neo4j respondiendo  [DEGRADED si no responde — puede ser remoto]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check8-neo4j"
log "--- [8/9] Neo4j"
if port_listening 7687; then
    pass "Neo4j bolt 7687 escuchando"
else
    mark_degraded "Neo4j bolt 7687 no responde (puede ser remoto o parado)"
fi

# ---------------------------------------------------------------------------
# Check 9: endpoint HTTP /api/status (con timeout)  [CRÍTICO si no responde]
# ---------------------------------------------------------------------------
_VERIFY_PHASE="check9-http"
log "--- [9/9] endpoint HTTP"
if command -v curl >/dev/null 2>&1; then
    # curl writes %{http_code} ('000' on error) then exits non-zero on errors.
    # || true prevents the ERR trap from firing when curl fails to connect.
    _http_code=""
    _http_code="$(curl -s -o /dev/null -w '%{http_code}' \
        --max-time 10 \
        --connect-timeout 5 \
        "${S9K_VIEWER_URL}/api/status" 2>/dev/null || true)"
    # If curl wrote nothing, fall back to '000'
    [ -n "${_http_code}" ] || _http_code="000"
    # Validate output is a 3-digit numeric code — reject any injection attempt
    if printf '%s' "${_http_code}" | grep -qE '^[0-9]{3}$'; then
        case "${_http_code}" in
            200|401)
                pass "endpoint HTTP /api/status: HTTP ${_http_code}" ;;
            000)
                mark_failed "endpoint HTTP no responde (timeout/conexión rechazada) — ${S9K_VIEWER_URL}/api/status" ;;
            *)
                mark_degraded "endpoint HTTP responde con código inesperado: ${_http_code}" ;;
        esac
    else
        mark_blocked "endpoint HTTP: respuesta de curl no parseable: '${_http_code}'"
    fi
else
    skip_check "curl no disponible (herramienta opcional) — endpoint HTTP no verificado"
fi

# ---------------------------------------------------------------------------
# Resumen final
# ---------------------------------------------------------------------------
_VERIFY_PHASE="summary"
log "=== RESULTADO VERIFY: ${FINAL_STATUS} ==="

if [ ${#_failed_reasons[@]} -gt 0 ]; then
    err "Gates críticos fallidos (${#_failed_reasons[@]}):"
    for _r in "${_failed_reasons[@]}"; do err "  - ${_r}"; done
fi
if [ ${#_degraded_reasons[@]} -gt 0 ]; then
    warn "Razones DEGRADED (${#_degraded_reasons[@]}):"
    for _r in "${_degraded_reasons[@]}"; do warn "  - ${_r}"; done
fi
if [ ${#_check_errors[@]} -gt 0 ]; then
    err "Errores de verificación (${#_check_errors[@]}):"
    for _r in "${_check_errors[@]}"; do err "  - ${_r}"; done
fi

# Mark as done so the EXIT trap knows we completed normally
_VERIFY_DONE=1

# Print the final result keyword — never execute it as a command
case "${FINAL_STATUS}" in
    OK)      printf 'VERIFICATION_OK\n';      exit 0 ;;
    FAILED)  printf 'VERIFICATION_FAILED\n';  exit 1 ;;
    BLOCKED) printf 'VERIFICATION_BLOCKED\n'; exit 2 ;;
    *)       printf 'VERIFICATION_BLOCKED\n'; exit 2 ;;
esac

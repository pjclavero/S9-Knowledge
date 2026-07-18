#!/usr/bin/env bash
# deploy.sh — despliegue reproducible de S9 Knowledge con CONTINUIDAD DE ESTADO.
#
# Uso: deploy.sh --environment <lab|production> --release-ref <commit|tag|branch>
#                [--confirm | --confirm-production] [--dry-run]
#                [--mode upgrade|fresh]
#
# Por defecto: DRY-RUN. Sin --confirm (lab) o --confirm-production (producción)
# no se aplica ningún cambio: 0 archivos, 0 migraciones, 0 cambios de symlink,
# 0 daemon-reload, 0 reinicios.
#
# Orden de activación (obligatorio, corrección RC1):
#   1 lock - 2 verificar release - 3 detectar layout - 4 migrar/validar estado -
#   5 validar continuidad - 6 validar viewer.env - 7 validar unidad -
#   8 respaldar unidad instalada - 9 instalar unidad nueva - 10 systemd-analyze -
#   11 daemon-reload solo si cambió - 12 current atómico - 13 reiniciar afectados -
#   14 comprobar commit ejecutado - 15 comprobar admin y jobs - 16 healthcheck -
#   17 liberar lock.
#
# NO despliega automáticamente. NO contiene secretos (van en /etc/s9-knowledge/*.env).
# shellcheck shell=bash
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"
# shellcheck source=deploy/scripts/validate_deploy.sh
source "${HERE}/validate_deploy.sh"

# ---------------------------------------------------------------------------
# Valores por defecto
# ---------------------------------------------------------------------------
ENVIRONMENT=""
RELEASE_REF=""
DRY_RUN=1
MODE="upgrade"
_CLEANUP_TMPDIR=""

# Rutas del layout LEGACY (solo lectura; nunca se modifican).
LEGACY_ROOT="/opt/knowledge-services/s9-knowledge-repo"
LEGACY_AUTH_DB="${S9K_LEGACY_AUTH_DB:-${LEGACY_ROOT}/viewer/state/auth.db}"
LEGACY_JOBS_DB="${S9K_LEGACY_JOBS_DB:-${LEGACY_ROOT}/viewer/state/jobs.db}"
NEW_AUTH_DB="${S9K_STATE_ROOT}/auth/auth.db"
NEW_JOBS_DB="${S9K_STATE_ROOT}/jobs/jobs.db"
VIEWER_ENV="${S9K_CONFIG_ROOT}/viewer.env"
UNIT_DEST="/etc/systemd/system/s9-knowledge-viewer.service"

usage() {
    cat <<USAGE
uso: deploy.sh --environment <lab|production> --release-ref <ref>
               [--confirm | --confirm-production] [--dry-run] [--mode upgrade|fresh]
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --environment)        ENVIRONMENT="$2"; shift 2 ;;
        --release-ref)        RELEASE_REF="$2"; shift 2 ;;
        --mode)               MODE="$2"; shift 2 ;;
        --confirm)            DRY_RUN=0; shift ;;
        --confirm-production) DRY_RUN=0; shift ;;
        --dry-run)            DRY_RUN=1; shift ;;
        -h|--help)            usage; exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

[ -n "${ENVIRONMENT}" ] || { usage; die "--environment es obligatorio"; }
[ -n "${RELEASE_REF}" ] || { usage; die "--release-ref es obligatorio"; }
case "${ENVIRONMENT}" in lab|production) ;; *) die "entorno inválido: '${ENVIRONMENT}'";; esac
case "${MODE}" in upgrade|fresh) ;; *) die "modo inválido: '${MODE}'";; esac
export S9K_ENVIRONMENT="${ENVIRONMENT}"

_trap_cleanup() {
    local exit_code=$?
    if [ -n "${_CLEANUP_TMPDIR}" ] && [ -d "${_CLEANUP_TMPDIR}" ]; then
        rm -rf "${_CLEANUP_TMPDIR}"
    fi
    [ "${exit_code}" -ne 0 ] && err "deploy.sh salió con código ${exit_code}"
    return 0
}
trap '_trap_cleanup' EXIT

# En dry-run, `run` solo describe; en apply, ejecuta.
run() {
    if [ "${DRY_RUN}" -eq 0 ]; then log "- $*"; "$@"; else info "(dry-run) $*"; fi
}

log "=== DEPLOY S9 Knowledge (continuidad de estado) ==="
log "    entorno=${ENVIRONMENT} ref=${RELEASE_REF} modo=${MODE} $([ "${DRY_RUN}" -eq 1 ] && echo DRY-RUN || echo APLICAR)"
[ "${DRY_RUN}" -eq 1 ] && warn "DRY-RUN: no se modificará nada."

# Resolver commit + release id (sin efectos secundarios)
RESOLVED_COMMIT="${RELEASE_REF}"
SHORT_COMMIT="${RELEASE_REF:0:7}"
if [ -d "${S9K_ROOT}/current/.git" ] || [ -d "${S9K_ROOT}/.git" ]; then
    _git_dir="${S9K_ROOT}/current"; [ -d "${_git_dir}/.git" ] || _git_dir="${S9K_ROOT}"
    # `git rev-parse <ref>` imprime el propio argumento en stdout aunque falle,
    # de modo que `$(rev-parse ... || printf ...)` DUPLICA el ref cuando el
    # commit todavía no está en `current` (caso normal de deploy hacia delante:
    # el objetivo se trae por fetch en el paso 2). Se usa `--verify -q`, que es
    # silencioso y no emite nada al fallar; si no resuelve, se conserva el ref
    # literal (una sola vez) para que el fetch posterior lo materialice.
    if _resolved="$(git -C "${_git_dir}" rev-parse --verify -q "${RELEASE_REF}^{commit}" 2>/dev/null)"; then
        RESOLVED_COMMIT="${_resolved}"
        SHORT_COMMIT="$(git -C "${_git_dir}" rev-parse --short "${_resolved}" 2>/dev/null || printf '%s' "${_resolved:0:7}")"
    fi
fi
TS="$(date -u '+%Y%m%d-%H%M%S')"
RELEASE_ID="${SHORT_COMMIT}-${TS}"
RELEASE_DIR="${S9K_ROOT}/releases/${RELEASE_ID}"
log "    release_id=${RELEASE_ID} commit=${RESOLVED_COMMIT}"

# ---------------------------------------------------------------------------
# PLAN (dry-run): describe el orden y las comprobaciones, sin tocar nada.
# ---------------------------------------------------------------------------
detect_layout_report() {
    python3 "${HERE}/detect_state.py" \
        --legacy-auth "${LEGACY_AUTH_DB}" --legacy-jobs "${LEGACY_JOBS_DB}" \
        --new-auth "${NEW_AUTH_DB}" --new-jobs "${NEW_JOBS_DB}" --mode "${MODE}"
}

if [ "${DRY_RUN}" -eq 1 ]; then
    log "--- PLAN (17 pasos; 0 cambios) ---"
    info "  3. Detectar layout/estado:"
    set +e
    detect_layout_report
    detect_rc=$?
    set -e
    if [ "${detect_rc}" -eq 3 ]; then
        warn "  -> En APLICAR, el estado BLOQUEARÍA el despliegue (ver 'decision: BLOCK')."
    fi
    log "=== DRY-RUN completado. 0 archivos, 0 migraciones, 0 symlink, 0 daemon-reload, 0 reinicios. ==="
    exit 0
fi

# ===========================================================================
# MODO APLICAR
# ===========================================================================
# Paso 1: lock
log "--- 1. lock de concurrencia"
lock_deploy

# Paso 2: verificar release (construir + manifiesto + integridad)
log "--- 2. verificar/construir release"
[ -d "${RELEASE_DIR}" ] && die "release ${RELEASE_ID} ya existe"
mkdir -p "${S9K_ROOT}/releases" "${RELEASE_DIR}"
_CLEANUP_TMPDIR="${RELEASE_DIR}"
if [ -f "${S9K_CONFIG_ROOT}/deploy.env" ]; then set +u; . "${S9K_CONFIG_ROOT}/deploy.env" 2>/dev/null || true; set -u; fi
S9K_REPO_URL="${S9K_REPO_URL:-}"
if [ -d "${S9K_ROOT}/current/.git" ]; then
    git clone --local --no-hardlinks "${S9K_ROOT}/current" "${RELEASE_DIR}" 2>/dev/null \
        || git clone --no-local "${S9K_ROOT}/current" "${RELEASE_DIR}"
    # Un commit posterior a la release activa no está en su object store. Se
    # trae DENTRO de la release nueva: hacer fetch en `current` modificaría la
    # release desplegada e invalidaría su checksum (que cubre .git).
    if ! git -C "${RELEASE_DIR}" cat-file -e "${RESOLVED_COMMIT}^{commit}" 2>/dev/null; then
        [ -n "${S9K_REPO_URL}" ] || die "commit ${RESOLVED_COMMIT} no presente en current y sin S9K_REPO_URL para traerlo"
        # Fetch por SHA crudo suele fallar (los servidores no sirven objetos
        # arbitrarios por defecto); el fallback trae todas las tags/HEAD, con lo
        # que un commit alcanzable por una tag (p.ej. deploy-v0.3.0-rcN) queda
        # disponible. Tras traerlo, se re-resuelve con --verify (sin duplicar).
        git -C "${RELEASE_DIR}" fetch --tags "${S9K_REPO_URL}" "${RESOLVED_COMMIT}" 2>/dev/null \
            || git -C "${RELEASE_DIR}" fetch --tags "${S9K_REPO_URL}"
        RESOLVED_COMMIT="$(git -C "${RELEASE_DIR}" rev-parse --verify -q "${RESOLVED_COMMIT}^{commit}" 2>/dev/null)" \
            || die "commit ${RELEASE_REF} no resoluble tras fetch desde ${S9K_REPO_URL}"
    fi
    git -C "${RELEASE_DIR}" checkout --detach "${RESOLVED_COMMIT}"
elif [ -n "${S9K_REPO_URL}" ]; then
    git clone --no-local "${S9K_REPO_URL}" "${RELEASE_DIR}"
    git -C "${RELEASE_DIR}" checkout --detach "${RESOLVED_COMMIT}"
else
    die "sin origen de repo (S9K_REPO_URL o ${S9K_ROOT}/current/.git)"
fi
[ -f "${RELEASE_DIR}/viewer/.env" ] && { warn "eliminando .env de la release (secretos van en ${S9K_CONFIG_ROOT})"; rm -f "${RELEASE_DIR}/viewer/.env"; }
python3 -m venv "${RELEASE_DIR}/viewer/.venv"
"${RELEASE_DIR}/viewer/.venv/bin/pip" install --quiet --upgrade pip
"${RELEASE_DIR}/viewer/.venv/bin/pip" install --quiet -r "${RELEASE_DIR}/viewer/requirements.txt"
create_manifest "${RELEASE_DIR}" "${RELEASE_ID}" "${RESOLVED_COMMIT}" "${ENVIRONMENT}"
validate_manifest "${RELEASE_DIR}/manifest.json" || die "manifiesto inválido"

# Paso 3: detectar layout/estado
log "--- 3. detectar layout/estado"
STATE_JSON="$(detect_layout_report || true)"
GLOBAL_STATE="$(printf '%s' "${STATE_JSON}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["global_state"])')"
DECISION="$(printf '%s' "${STATE_JSON}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["decision"])')"
log "    estado=${GLOBAL_STATE} decision=${DECISION}"

# Paso 4: migrar o validar estado (según el estado detectado)
log "--- 4. migrar o validar estado"
case "${GLOBAL_STATE}" in
    LEGACY_STATE)
        log "    migrando legacy -> state root (controlado, atómico, .backup)"
        python3 "${HERE}/migrate_sqlite.py" --kind auth --src "${LEGACY_AUTH_DB}" --dst "${NEW_AUTH_DB}" --apply --confirm \
            || die "migración auth falló/bloqueó"
        if [ -f "${LEGACY_JOBS_DB}" ]; then
            python3 "${HERE}/migrate_sqlite.py" --kind jobs --src "${LEGACY_JOBS_DB}" --dst "${NEW_JOBS_DB}" --apply --confirm \
                || die "migración jobs falló/bloqueó"
        fi
        ;;
    NEW_STATE|MIXED_EQUIVALENT_STATE)
        log "    estado nuevo ya presente y equivalente; sin migración"
        ;;
    EMPTY_STATE|CONFLICTING_STATE|CORRUPT_STATE)
        die "estado ${GLOBAL_STATE}: BLOQUEA (nunca crear auth.db vacía ni elegir DB en silencio)"
        ;;
    *) die "estado desconocido: ${GLOBAL_STATE}" ;;
esac

# Paso 5: validar continuidad (re-detección; debe permitir proceder y >=1 admin)
log "--- 5. validar continuidad"
set +e
detect_layout_report >/dev/null
cont_rc=$?
set -e
[ "${cont_rc}" -eq 0 ] || die "validación de continuidad BLOQUEA (rc=${cont_rc})"

# Paso 6: validar viewer.env (bloquea si faltan variables críticas o el secreto
# CSRF / fichero de contraseña son inseguros; nunca se imprime el valor)
log "--- 6. validar viewer.env"
validate_viewer_env "${VIEWER_ENV}" || die "viewer.env inválido/incompleto"
validate_viewer_secrets "${VIEWER_ENV}" || die "viewer.env: secretos inválidos (CSRF/fichero)"

# Paso 7: validar unidad nueva (antes de instalarla)
log "--- 7. validar unidad systemd nueva"
UNIT_SRC="${RELEASE_DIR}/viewer/systemd/s9-knowledge-viewer.service"
validate_viewer_unit "${UNIT_SRC}" "${S9K_ROOT}/current" || die "unit nueva inválida"

# Paso 8-9: respaldar unidad instalada + instalar nueva (solo si difiere)
UNIT_CHANGED=0
if ! diff -q "${UNIT_SRC}" "${UNIT_DEST}" >/dev/null 2>&1; then
    log "--- 8. respaldar unidad instalada"
    [ -f "${UNIT_DEST}" ] && cp -a "${UNIT_DEST}" "${UNIT_DEST}.bak-${RELEASE_ID}"
    log "--- 9. instalar unidad nueva"
    cp "${UNIT_SRC}" "${UNIT_DEST}"
    UNIT_CHANGED=1
else
    log "--- 8-9. unidad sin cambios"
fi

# Paso 10: systemd-analyze verify
log "--- 10. systemd-analyze verify"
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "${UNIT_DEST}" || die "systemd-analyze verify falló"
else
    warn "systemd-analyze no disponible; omitido"
fi

# Paso 11: daemon-reload solo si cambió
if [ "${UNIT_CHANGED}" -eq 1 ]; then
    log "--- 11. daemon-reload (unidad cambió)"
    systemctl daemon-reload
else
    log "--- 11. sin daemon-reload (unidad no cambió)"
fi

# Paso 11b: el contenido de la release debe seguir siendo el validado.
# Va ANTES de activar `current`: detecta cualquier deriva entre la construcción
# y el cutover. Las cachés de bytecode y demás derivados quedan fuera del
# checksum, así que importar módulos o pasar tests no lo invalida.
log "--- 11b. verificar checksum de la release"
verify_release_checksum "${RELEASE_DIR}" || die "checksum de release no coincide: release alterada tras su validación"

# Paso 12: cambiar current atómicamente
log "--- 12. activar release (symlink atómico)"
PREV_RELEASE_DIR=""; [ -L "${S9K_ROOT}/current" ] && PREV_RELEASE_DIR="$(readlink -f "${S9K_ROOT}/current" 2>/dev/null || true)"
atomic_symlink "${RELEASE_DIR}" "${S9K_ROOT}/current"
_CLEANUP_TMPDIR=""

# Paso 12b: registrar el estado del despliegue (atómico, fail-open para no bloquear)
log "--- 12b. registrar deployment-state.json"
PREV_RELEASE_ID=""; [ -n "${PREV_RELEASE_DIR}" ] && PREV_RELEASE_ID="$(basename "${PREV_RELEASE_DIR}")"
PREV_COMMIT=""; [ -n "${PREV_RELEASE_DIR}" ] && [ -f "${PREV_RELEASE_DIR}/manifest.json" ] && \
    PREV_COMMIT="$(manifest_field "${PREV_RELEASE_DIR}/manifest.json" git_commit 2>/dev/null || true)"
write_deployment_state \
    "${RELEASE_ID}" \
    "${RESOLVED_COMMIT}" \
    "${PREV_RELEASE_ID:--}" \
    "${PREV_COMMIT:--}" \
    "${RELEASE_ID}"

# Paso 13: reiniciar solo servicios afectados
log "--- 13. reiniciar servicio visor"
systemctl restart s9-knowledge-viewer.service || die "no se pudo reiniciar el visor"
sleep 3

# Paso 14: comprobar commit ejecutado (proceso vivo, no solo el symlink)
log "--- 14. verificar identidad de la release ejecutada"
python3 "${HERE}/verify_release_identity.py" --root "${S9K_ROOT}" \
    --expected-release "${RELEASE_ID}" --expected-commit "${RESOLVED_COMMIT}" \
    --unit s9-knowledge-viewer.service || {
        err "el proceso vivo NO ejecuta la release autorizada — rollback"
        [ -n "${PREV_RELEASE_DIR}" ] && [ -d "${PREV_RELEASE_DIR}" ] && {
            atomic_symlink "${PREV_RELEASE_DIR}" "${S9K_ROOT}/current"
            systemctl restart s9-knowledge-viewer.service || true
        }
        die "activación no verificable; rollback ejecutado"
    }

# Paso 15: comprobar admin y jobs preservados
log "--- 15. comprobar admin y jobs"
python3 "${HERE}/detect_state.py" --new-auth "${NEW_AUTH_DB}" --new-jobs "${NEW_JOBS_DB}" --mode fresh >/dev/null \
    || warn "conteos post-activación con avisos (revisar)"

# Paso 16: healthcheck funcional
log "--- 16. healthcheck"
set +e
"${HERE}/verify-deployment.sh" --expected-release "${RELEASE_ID}"
verify_rc=$?
set -e
# Fail-closed: cualquier resultado != 0 (FAILED o BLOCKED) activa rollback.
# Antes solo se comprobaba verify_rc==1, dejando pasar BLOCKED (rc=2) como verde.
if [ "${verify_rc}" -ne 0 ]; then
    err "healthcheck FALLIDO (rc=${verify_rc}) — rollback"
    [ -n "${PREV_RELEASE_DIR}" ] && [ -d "${PREV_RELEASE_DIR}" ] && {
        atomic_symlink "${PREV_RELEASE_DIR}" "${S9K_ROOT}/current"
        systemctl restart s9-knowledge-viewer.service || true
    }
    die "despliegue FALLIDO tras healthcheck (verify_rc=${verify_rc})"
fi

# Retention fail-closed: activa borrado real solo tras deploy verificado
S9K_RETENTION_APPLY=1 cleanup_old_releases

# Paso 17: liberar lock (implícito al cerrar el FD/proceso)
log "--- 17. liberar lock"
log "=== DEPLOY completado === release=${RELEASE_ID} estado=${GLOBAL_STATE}"

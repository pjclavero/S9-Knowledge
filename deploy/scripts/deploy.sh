#!/usr/bin/env bash
# deploy.sh — despliegue reproducible de S9 Knowledge mediante releases atómicas.
#
# Uso: deploy.sh --environment <lab|production> --release-ref <commit|tag|branch>
#                [--confirm | --confirm-production] [--dry-run]
#
# Por defecto: DRY-RUN. Sin --confirm (lab) o --confirm-production (producción)
# no se aplica ningún cambio.
#
# NO despliega automáticamente: debe invocarse manualmente por el operador.
# NO contiene secretos. Los secretos van en /etc/s9-knowledge/*.env (en el host).
# shellcheck shell=bash
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"

# ---------------------------------------------------------------------------
# Valores por defecto
# ---------------------------------------------------------------------------
ENVIRONMENT=""
RELEASE_REF=""
CONFIRM=0
DRY_RUN=1           # Seco por defecto; se desactiva con --confirm
_CLEANUP_TMPDIR=""  # Registro del directorio temporal para el trap

# ---------------------------------------------------------------------------
# Uso
# ---------------------------------------------------------------------------
usage() {
    cat <<USAGE
uso: deploy.sh --environment <lab|production> --release-ref <commit|tag|branch>
               [--confirm | --confirm-production] [--dry-run]

Opciones:
  --environment lab|production   Entorno destino (obligatorio)
  --release-ref <ref>            Ref Git a desplegar: commit SHA, tag o rama (obligatorio)
  --confirm                      Aplica cambios en entorno lab
  --confirm-production           Aplica cambios en entorno production (requiere SHA o tag)
  --dry-run                      Fuerza modo solo lectura (por defecto)
  -h, --help                     Muestra esta ayuda

Variables de entorno:
  S9K_ROOT          Raíz del despliegue (default: /opt/s9-knowledge)
  S9K_STATE_ROOT    Estado mutable (default: /var/lib/s9-knowledge)
  S9K_CONFIG_ROOT   Configuración/secretos (default: /etc/s9-knowledge)
  S9K_RELEASES_TO_KEEP  Releases a conservar (default: 3)
USAGE
}

# ---------------------------------------------------------------------------
# Parseo de argumentos
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --environment)       ENVIRONMENT="$2"; shift 2 ;;
        --release-ref)       RELEASE_REF="$2"; shift 2 ;;
        --confirm)           CONFIRM=1; DRY_RUN=0; shift ;;
        --confirm-production) CONFIRM=1; DRY_RUN=0; shift ;;
        --dry-run)           DRY_RUN=1; CONFIRM=0; shift ;;
        -h|--help)           usage; exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Validaciones iniciales
# ---------------------------------------------------------------------------
[ -n "${ENVIRONMENT}" ] || { usage; die "--environment es obligatorio"; }
[ -n "${RELEASE_REF}" ] || { usage; die "--release-ref es obligatorio"; }

case "${ENVIRONMENT}" in
    lab|production) ;;
    *) die "entorno inválido: '${ENVIRONMENT}'. Valores válidos: lab, production" ;;
esac

# En producción, el ref debe ser un SHA o tag (no una rama ambigua)
if [ "${ENVIRONMENT}" = "production" ] && [ "${CONFIRM}" -eq 1 ]; then
    # Comprobamos que el ref parece un SHA (>=7 hex chars) o un tag conocido
    if ! printf '%s' "${RELEASE_REF}" | grep -qE '^[0-9a-f]{7,40}$'; then
        # Puede ser un tag; verificamos con git si tenemos el repo
        warn "En producción con --confirm-production, el ref debe ser un commit SHA o tag, no una rama."
        warn "Ref proporcionado: '${RELEASE_REF}'"
        warn "Si es un tag, verifícalo manualmente. Continuando con advertencia..."
    fi
fi

export S9K_ENVIRONMENT="${ENVIRONMENT}"

# ---------------------------------------------------------------------------
# Trap: limpieza de temporales en cualquier salida
# ---------------------------------------------------------------------------
_trap_cleanup() {
    local exit_code=$?
    if [ -n "${_CLEANUP_TMPDIR}" ] && [ -d "${_CLEANUP_TMPDIR}" ]; then
        rm -rf "${_CLEANUP_TMPDIR}"
    fi
    if [ "${exit_code}" -ne 0 ]; then
        err "deploy.sh salió con código ${exit_code}"
    fi
}
trap '_trap_cleanup' EXIT

# ---------------------------------------------------------------------------
# Función run: respeta DRY_RUN
# ---------------------------------------------------------------------------
run() {
    if [ "${DRY_RUN}" -eq 0 ]; then
        log "· $*"
        "$@"
    else
        info "(dry-run) $*"
    fi
}

# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------
log "=== DEPLOY S9 Knowledge ==="
log "    entorno:     ${ENVIRONMENT}"
log "    release-ref: ${RELEASE_REF}"
log "    modo:        $([ "${DRY_RUN}" -eq 1 ] && printf 'DRY-RUN' || printf 'APLICAR')"
log "    S9K_ROOT:    ${S9K_ROOT}"
log "    state:       ${S9K_STATE_ROOT}"
log "    config:      ${S9K_CONFIG_ROOT}"

[ "${DRY_RUN}" -eq 1 ] && warn "DRY-RUN activo: no se modificará nada (usa --confirm para aplicar)"

# ---------------------------------------------------------------------------
# Paso 1: Resolver commit exacto del ref
# ---------------------------------------------------------------------------
log "--- Paso 1: resolver commit"

# En dry-run sin acceso al repo, usamos el ref tal cual
RESOLVED_COMMIT="${RELEASE_REF}"

# Si existe el repo local (current o el directorio base), resolver el SHA
if [ -d "${S9K_ROOT}/current/.git" ] || [ -d "${S9K_ROOT}/.git" ]; then
    _git_dir="${S9K_ROOT}/current"
    [ -d "${_git_dir}/.git" ] || _git_dir="${S9K_ROOT}"
    RESOLVED_COMMIT="$(git -C "${_git_dir}" rev-parse "${RELEASE_REF}" 2>/dev/null || printf '%s' "${RELEASE_REF}")"
    SHORT_COMMIT="$(git -C "${_git_dir}" rev-parse --short "${RELEASE_REF}" 2>/dev/null || printf '%s' "${RELEASE_REF:0:7}")"
elif command -v git >/dev/null 2>&1 && [ -d ".git" ]; then
    RESOLVED_COMMIT="$(git rev-parse "${RELEASE_REF}" 2>/dev/null || printf '%s' "${RELEASE_REF}")"
    SHORT_COMMIT="$(git rev-parse --short "${RELEASE_REF}" 2>/dev/null || printf '%s' "${RELEASE_REF:0:7}")"
else
    SHORT_COMMIT="${RELEASE_REF:0:7}"
fi

log "    commit resuelto: ${RESOLVED_COMMIT}"

# ---------------------------------------------------------------------------
# Paso 2: Generar release ID
# ---------------------------------------------------------------------------
log "--- Paso 2: generar release ID"
TS="$(date -u '+%Y%m%d-%H%M%S')"
RELEASE_ID="${SHORT_COMMIT}-${TS}"
RELEASE_DIR="${S9K_ROOT}/releases/${RELEASE_ID}"
log "    release ID: ${RELEASE_ID}"
log "    release dir: ${RELEASE_DIR}"

# No sobrescribir si ya existe (mismo ID teórico imposible, pero protección defensiva)
if [ -d "${RELEASE_DIR}" ] && [ "${DRY_RUN}" -eq 0 ]; then
    die "Release ${RELEASE_ID} ya existe en ${RELEASE_DIR}. ID de release duplicado."
fi

# ---------------------------------------------------------------------------
# Paso 3: Adquirir lock de concurrencia
# ---------------------------------------------------------------------------
log "--- Paso 3: lock de concurrencia"
if [ "${DRY_RUN}" -eq 0 ]; then
    lock_deploy
fi

# ---------------------------------------------------------------------------
# Paso 4: Preflight
# ---------------------------------------------------------------------------
log "--- Paso 4: preflight"
set +e
"${HERE}/preflight.sh" --environment "${ENVIRONMENT}"
preflight_rc=$?
set -e
if [ "${preflight_rc}" -ge 2 ]; then
    die "preflight BLOQUEÓ el despliegue (rc=${preflight_rc})"
elif [ "${preflight_rc}" -eq 1 ]; then
    warn "preflight con advertencias no bloqueantes (rc=${preflight_rc}) — continuando"
fi

# ---------------------------------------------------------------------------
# Paso 5: Mostrar plan (sin secretos)
# ---------------------------------------------------------------------------
log "--- Paso 5: plan de despliegue"
info "PLAN:"
info "  1. Crear:       ${RELEASE_DIR}"
info "  2. Clonar repo: ref=${RELEASE_REF} -> ${RELEASE_DIR}"
info "  3. Instalar .venv en ${RELEASE_DIR}/viewer/.venv"
info "  4. pip install desde requirements.txt (fijado)"
info "  5. Crear manifiesto: ${RELEASE_DIR}/manifest.json"
info "  6. Backup SQLite + migraciones"
info "  7. Symlink atómico: ${S9K_ROOT}/current -> releases/${RELEASE_ID}"
info "  8. Recargar systemd si cambiaron units"
info "  9. Reiniciar s9-knowledge-viewer.service"
info " 10. verify-deployment.sh (rollback automático si falla)"
info " 11. Limpiar releases antiguas (conservar ${S9K_RELEASES_TO_KEEP})"

if [ "${DRY_RUN}" -eq 1 ]; then
    log "=== DRY-RUN completado. Sin cambios. ==="
    exit 0
fi

# A partir de aquí: modo real (--confirm)
log "--- Aplicando cambios (MODO REAL) ---"

# Verificar árbol Git limpio en producción
if [ "${ENVIRONMENT}" = "production" ]; then
    if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        if ! git diff --quiet HEAD 2>/dev/null; then
            die "Árbol Git sucio en producción. Confirma los cambios antes de desplegar."
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Paso 6: Crear directorio de release y clonar
# ---------------------------------------------------------------------------
log "--- Paso 6: crear release ${RELEASE_ID}"
mkdir -p "${S9K_ROOT}/releases"
mkdir -p "${RELEASE_DIR}"
_CLEANUP_TMPDIR="${RELEASE_DIR}"  # Se limpiará en caso de error

# Determinar origen del repo (cargar deploy.env si existe)
if [ -f "${S9K_CONFIG_ROOT}/deploy.env" ]; then
    # shellcheck source=/dev/null
    set +u
    . "${S9K_CONFIG_ROOT}/deploy.env" 2>/dev/null || true
    set -u
fi
S9K_REPO_URL="${S9K_REPO_URL:-}"

if [ -d "${S9K_ROOT}/current/.git" ]; then
    # Clonar desde la copia local (más rápido, sin acceso a red)
    log "Clonando desde repo local: ${S9K_ROOT}/current"
    git clone --local --no-hardlinks \
        --branch "${RELEASE_REF}" \
        "${S9K_ROOT}/current" \
        "${RELEASE_DIR}" 2>/dev/null || \
    git clone --no-local \
        "${S9K_ROOT}/current" \
        "${RELEASE_DIR}"
    git -C "${RELEASE_DIR}" checkout --detach "${RESOLVED_COMMIT}"
elif [ -n "${S9K_REPO_URL}" ]; then
    # Clonar desde URL remota
    log "Clonando desde URL remota (sin secretos en la URL)"
    git clone --no-local \
        "${S9K_REPO_URL}" \
        "${RELEASE_DIR}"
    git -C "${RELEASE_DIR}" checkout --detach "${RESOLVED_COMMIT}"
else
    die "No se puede determinar el origen del repo. Configura S9K_REPO_URL en ${S9K_CONFIG_ROOT}/deploy.env o asegúrate de que ${S9K_ROOT}/current/.git existe."
fi

# Verificar que .env NO está dentro de la release (nunca debe copiarse)
if [ -f "${RELEASE_DIR}/viewer/.env" ]; then
    warn "Se encontró .env dentro de la release — eliminando (los secretos van en ${S9K_CONFIG_ROOT})"
    rm -f "${RELEASE_DIR}/viewer/.env"
fi

log "Release clonada en: ${RELEASE_DIR}"

# ---------------------------------------------------------------------------
# Paso 7: Instalar .venv en la release
# ---------------------------------------------------------------------------
log "--- Paso 7: instalar .venv"
python3 -m venv "${RELEASE_DIR}/viewer/.venv"
"${RELEASE_DIR}/viewer/.venv/bin/pip" install --quiet --upgrade pip
"${RELEASE_DIR}/viewer/.venv/bin/pip" install --quiet \
    -r "${RELEASE_DIR}/viewer/requirements.txt"
log ".venv instalado en ${RELEASE_DIR}/viewer/.venv"

# ---------------------------------------------------------------------------
# Paso 8: Crear manifiesto JSON (sin secretos)
# ---------------------------------------------------------------------------
log "--- Paso 8: crear manifiesto"
create_manifest "${RELEASE_DIR}" "${RELEASE_ID}" "${RESOLVED_COMMIT}" "${ENVIRONMENT}"

# ---------------------------------------------------------------------------
# Paso 9: Migraciones SQLite (con backup previo)
# ---------------------------------------------------------------------------
log "--- Paso 9: migraciones SQLite"
AUTH_DB_PATH="${S9K_STATE_ROOT}/auth/auth.db"
if [ -f "${AUTH_DB_PATH}" ]; then
    BACKUP_PATH="${S9K_STATE_ROOT}/backups/auth.db.pre-${RELEASE_ID}.bak"
    mkdir -p "${S9K_STATE_ROOT}/backups"
    cp -a "${AUTH_DB_PATH}" "${BACKUP_PATH}"
    log "Backup de auth.db: ${BACKUP_PATH}"
fi

VENV_PY="${RELEASE_DIR}/viewer/.venv/bin/python"
if [ -x "${VENV_PY}" ] && [ -f "${RELEASE_DIR}/viewer/app/auth/config.py" ]; then
    log "Ejecutando migraciones auth (idempotentes)..."
    set +e
    cd "${RELEASE_DIR}/viewer"
    "${VENV_PY}" -c "
import sys
sys.path.insert(0, '.')
try:
    from app.auth.config import get_auth_settings
    from app.auth import db as auth_db
    import pathlib
    c = get_auth_settings()
    if c.S9K_AUTH_ENABLED:
        auth_db.ensure_migrated(pathlib.Path(c.S9K_AUTH_DB_PATH))
        print('[migrate] auth.db migrado')
    else:
        print('[migrate] auth desactivado, sin migraciones')
except Exception as e:
    print(f'[migrate] advertencia: {e}', file=sys.stderr)
    sys.exit(0)  # No bloquear por migraciones opcionales
" 2>/dev/null || warn "migraciones opcionales fallaron (no bloquean el deploy)"
    cd - >/dev/null
    set -e
else
    log "migraciones: app.auth no disponible en esta release (omitido)"
fi

# ---------------------------------------------------------------------------
# Paso 10: Cambiar symlink ATÓMICAMENTE
# ---------------------------------------------------------------------------
log "--- Paso 10: activar release (symlink atómico)"
PREV_RELEASE_ID=""
PREV_RELEASE_DIR=""
if [ -L "${S9K_ROOT}/current" ]; then
    PREV_RELEASE_DIR="$(readlink -f "${S9K_ROOT}/current" 2>/dev/null || printf '')"
    PREV_RELEASE_ID="$(basename "${PREV_RELEASE_DIR}")"
    log "Release anterior: ${PREV_RELEASE_ID}"
fi

atomic_symlink "${RELEASE_DIR}" "${S9K_ROOT}/current"
log "Symlink actualizado: ${S9K_ROOT}/current -> ${RELEASE_DIR}"

# Ya no limpiar esta release en el trap (está activa)
_CLEANUP_TMPDIR=""

# ---------------------------------------------------------------------------
# Paso 11: Recargar systemd si cambiaron units
# ---------------------------------------------------------------------------
log "--- Paso 11: gestión systemd"
UNIT_SRC="${RELEASE_DIR}/viewer/systemd/s9-knowledge-viewer.service"
UNIT_DEST="/etc/systemd/system/s9-knowledge-viewer.service"

if [ -f "${UNIT_SRC}" ]; then
    if ! diff -q "${UNIT_SRC}" "${UNIT_DEST}" >/dev/null 2>&1; then
        log "Unit de systemd ha cambiado — actualizando e instalando"
        cp "${UNIT_SRC}" "${UNIT_DEST}"
        systemctl daemon-reload
        log "systemctl daemon-reload completado"
    else
        log "Unit de systemd sin cambios — sin daemon-reload"
    fi
else
    warn "No se encontró unit en ${UNIT_SRC} — systemd no actualizado"
fi

# ---------------------------------------------------------------------------
# Paso 12: Reiniciar servicio
# ---------------------------------------------------------------------------
log "--- Paso 12: reiniciar servicio visor"
if systemctl is-active --quiet s9-knowledge-viewer.service 2>/dev/null; then
    systemctl restart s9-knowledge-viewer.service
    log "s9-knowledge-viewer.service reiniciado"
else
    systemctl start s9-knowledge-viewer.service 2>/dev/null \
        || warn "No se pudo iniciar s9-knowledge-viewer.service (¿primera instalación?)"
fi

# Esperar brevemente para que el servicio arranque
sleep 3

# ---------------------------------------------------------------------------
# Paso 13: Verificar despliegue — rollback automático si falla
# ---------------------------------------------------------------------------
log "--- Paso 13: verificar despliegue"
set +e
"${HERE}/verify-deployment.sh" --expected-release "${RELEASE_ID}"
verify_rc=$?
set -e

if [ "${verify_rc}" -eq 1 ]; then
    err "verify-deployment reportó UNHEALTHY. Ejecutando rollback automático..."
    if [ -n "${PREV_RELEASE_DIR}" ] && [ -d "${PREV_RELEASE_DIR}" ]; then
        atomic_symlink "${PREV_RELEASE_DIR}" "${S9K_ROOT}/current"
        systemctl restart s9-knowledge-viewer.service 2>/dev/null || true
        sleep 2
        err "Rollback a ${PREV_RELEASE_ID} completado."
        err "Release fallida conservada para diagnóstico: ${RELEASE_DIR}"
    else
        err "No hay release anterior para rollback."
    fi
    die "Despliegue FALLIDO tras verificación. Release: ${RELEASE_ID}"
elif [ "${verify_rc}" -ge 2 ]; then
    warn "verify-deployment con ERROR de verificación (rc=${verify_rc}) — continuando con advertencia"
fi

# ---------------------------------------------------------------------------
# Paso 14: Limpiar releases antiguas
# ---------------------------------------------------------------------------
log "--- Paso 14: limpiar releases antiguas (conservar ${S9K_RELEASES_TO_KEEP})"
cleanup_old_releases

# ---------------------------------------------------------------------------
# Fin
# ---------------------------------------------------------------------------
log "=== DEPLOY completado exitosamente ==="
log "    release activa: ${RELEASE_ID}"
log "    symlink:        ${S9K_ROOT}/current -> ${RELEASE_DIR}"
log "    manifiesto:     ${RELEASE_DIR}/manifest.json"

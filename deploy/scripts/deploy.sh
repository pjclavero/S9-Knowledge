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
#   5 validar continuidad - 6 validar viewer.env y worker.env - 7 validar unidades -
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
# B3 · H-37: la ruta de `jobs.db` del despliegue la decide `job_store` (UNA
# autoridad), no un literal de este guion. Solo stdlib: no necesita venv.
JOB_STORE_PY="${HERE}/../../data-engine/app/jobs/job_store.py"
NEW_JOBS_DB="$(python3 "${JOB_STORE_PY}" --ruta-despliegue --state-root "${S9K_STATE_ROOT}")" \
    || die "job_store no resolvió la ruta de jobs.db del despliegue"
VIEWER_ENV="${S9K_CONFIG_ROOT}/viewer.env"
UNIT_DEST="/etc/systemd/system/s9-knowledge-viewer.service"
# B3 · H-02: el worker de la cola, como SERVICIO. Una sola plantilla de unidad
# (data-engine/systemd/), la misma que instala el rol Ansible `systemd`.
WORKER_UNIT_NAME="s9-knowledge-worker.service"
WORKER_UNIT_DEST="/etc/systemd/system/${WORKER_UNIT_NAME}"

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

# En lab se admiten branches como ref; en producción solo tags deploy-* o SHA.
ALLOW_BRANCH_ARGS=()
[ "${ENVIRONMENT}" = "lab" ] && ALLOW_BRANCH_ARGS=(--allow-branch)

# Resolver commit + release id (sin efectos secundarios). La resolución
# definitiva (con fetch) ocurre en el paso 2 sobre la copia nueva; aquí solo se
# intenta resolver en LOCAL para nombrar la release. resolve_release_commit
# emite EXCLUSIVAMENTE un SHA en stdout (o nada + rc!=0): nunca duplica el ref.
RESOLVED_COMMIT="${RELEASE_REF}"
SHORT_COMMIT="${RELEASE_REF:0:7}"
if [ -d "${S9K_ROOT}/current/.git" ] || [ -d "${S9K_ROOT}/.git" ]; then
    _git_dir="${S9K_ROOT}/current"; [ -d "${_git_dir}/.git" ] || _git_dir="${S9K_ROOT}"
    if _resolved="$(resolve_release_commit "${RELEASE_REF}" --work-dir "${_git_dir}" "${ALLOW_BRANCH_ARGS[@]}" 2>/dev/null)"; then
        RESOLVED_COMMIT="${_resolved}"
        SHORT_COMMIT="${_resolved:0:7}"
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
REPO_URL_ARGS=()
[ -n "${S9K_REPO_URL}" ] && REPO_URL_ARGS=(--repo-url "${S9K_REPO_URL}")
if [ -d "${S9K_ROOT}/current/.git" ]; then
    git clone --local --no-hardlinks "${S9K_ROOT}/current" "${RELEASE_DIR}" 2>/dev/null \
        || git clone --no-local "${S9K_ROOT}/current" "${RELEASE_DIR}"
    # Resolución definitiva del commit objetivo DENTRO de la copia nueva (nunca
    # en `current`: un fetch ahí invalidaría su checksum, que cubre .git). Un
    # commit posterior a la release activa no está en su object store; en ese
    # caso resolve_release_commit hace un fetch seguro desde S9K_REPO_URL. La
    # función emite SOLO un SHA (nunca duplica el ref) y falla con rc!=0.
    if ! RESOLVED_COMMIT="$(resolve_release_commit "${RELEASE_REF}" \
            --work-dir "${RELEASE_DIR}" "${REPO_URL_ARGS[@]}" "${ALLOW_BRANCH_ARGS[@]}")"; then
        die "commit ${RELEASE_REF} no resoluble a un commit (¿deploy hacia delante sin S9K_REPO_URL?)"
    fi
    git -C "${RELEASE_DIR}" checkout --detach "${RESOLVED_COMMIT}"
elif [ -n "${S9K_REPO_URL}" ] || [ -d "${S9K_ROOT}/.repo-cache/.git" ]; then
    # PRIMERA release (B2, H-01): sin `current` todavía, el origen es
    # S9K_REPO_URL (deploy.env) o, si no se declaró, la copia de referencia
    # que el rol Ansible `data_engine` deja en ${S9K_ROOT}/.repo-cache.
    git clone --no-local "${S9K_REPO_URL:-${S9K_ROOT}/.repo-cache}" "${RELEASE_DIR}"
    if ! RESOLVED_COMMIT="$(resolve_release_commit "${RELEASE_REF}" \
            --work-dir "${RELEASE_DIR}" "${REPO_URL_ARGS[@]}" "${ALLOW_BRANCH_ARGS[@]}")"; then
        die "commit ${RELEASE_REF} no resoluble a un commit desde ${S9K_REPO_URL:-${S9K_ROOT}/.repo-cache}"
    fi
    git -C "${RELEASE_DIR}" checkout --detach "${RESOLVED_COMMIT}"
else
    die "sin origen de repo (S9K_REPO_URL, ${S9K_ROOT}/current/.git o ${S9K_ROOT}/.repo-cache)"
fi
[ -f "${RELEASE_DIR}/viewer/.env" ] && { warn "eliminando .env de la release (secretos van en ${S9K_CONFIG_ROOT})"; rm -f "${RELEASE_DIR}/viewer/.env"; }
python3 -m venv "${RELEASE_DIR}/viewer/.venv"
"${RELEASE_DIR}/viewer/.venv/bin/pip" install --quiet --upgrade pip
"${RELEASE_DIR}/viewer/.venv/bin/pip" install --quiet -r "${RELEASE_DIR}/viewer/requirements.txt"
# B3 · H-02 (deuda heredada de B2): el venv del MOTOR, que es el intérprete de
# la unidad del worker. Nadie lo creaba: `run-jobs-worker.sh` buscaba un venv
# que no existía y caía al python del sistema, sin las dependencias bloqueadas.
python3 -m venv "${RELEASE_DIR}/data-engine/.venv"
"${RELEASE_DIR}/data-engine/.venv/bin/pip" install --quiet --upgrade pip
"${RELEASE_DIR}/data-engine/.venv/bin/pip" install --quiet -r "${RELEASE_DIR}/data-engine/requirements.lock"
create_manifest "${RELEASE_DIR}" "${RELEASE_ID}" "${RESOLVED_COMMIT}" "${ENVIRONMENT}"
validate_manifest "${RELEASE_DIR}/manifest.json" || die "manifiesto inválido"

# Paso 3: detectar layout/estado
log "--- 3. detectar layout/estado"
STATE_JSON="$(detect_layout_report || true)"
# `global_state` es INFORMATIVO (B2, H-43): solo se registra. Quien decide si
# se puede seguir es `decision`, y lo aplica el paso 4.
GLOBAL_STATE="$(_campo_json "${STATE_JSON}" global_state)"
DECISION="$(_campo_json "${STATE_JSON}" decision)"
PRIMER_ADMIN_PENDIENTE="$(_campo_json "${STATE_JSON}" primer_admin_pendiente)"
log "    auth=$(_campo_json "${STATE_JSON}" per_kind auth state) jobs=$(_campo_json "${STATE_JSON}" per_kind jobs state) modo=${MODE} decision=${DECISION} (global informativo=${GLOBAL_STATE})"

# Paso 4: migrar o validar estado. UNA autoridad: `decision` (lib.sh).
log "--- 4. migrar o validar estado"
paso4_migrar_o_validar_estado "${STATE_JSON}"
# --- fin del paso 4 ---

# Paso 5: validar continuidad (re-detección con el MISMO modo: en upgrade exige
# >=1 admin; en fresh, que la máquina siga limpia)
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
# B2 · USABLE-V1 (H-04/H-18, LADO DEPLOY): el estado de revisión V3 tiene que
# vivir FUERA de la release y lo tienen que resolver igual visor y motor. No se
# reimplementa: es el MISMO guion del ensayo RC, restringido a su grupo de
# comprobaciones de despliegue y leyendo el EnvironmentFile del visor.
python3 "${HERE}/preflight_ensayo_rc.py" --grupo despliegue \
    --env-file "${VIEWER_ENV}" --state-root "${S9K_STATE_ROOT}" \
    || die "estado de revisión V3 no persistente o no compartido (causa arriba): un redespliegue lo perdería"
# Slice 2 · Corte 5 + B3 · H-02: el entorno del WORKER. Desde B3 este guion
# instala y arranca el worker como servicio, así que `worker.env` (su
# EnvironmentFile) es OBLIGATORIO, y su cola y su almacén de propuestas tienen
# que ser los MISMOS que los del visor.
WORKER_ENV="${S9K_WORKER_ENV:-${S9K_CONFIG_ROOT}/worker.env}"
validate_worker_env "${WORKER_ENV}" "${VIEWER_ENV}" || die "worker.env ausente o inválido (causa arriba)"
# PR-3 · USABLE-V1: mitad ESTÁTICA del contrato de la vía HTTPS. En
# `production` bloquea; en `lab` avisa. La mitad POR EFECTO va en el paso 16b,
# cuando ya hay un servicio al que preguntar.
validate_https_contract "${VIEWER_ENV}" "${ENVIRONMENT}" \
    || die "contrato HTTPS no satisfecho: la instalación NO está completa"
# --- fin del paso 6 ---

# Paso 7: validar unidad nueva (antes de instalarla)
log "--- 7. validar unidad systemd nueva"
UNIT_SRC="${RELEASE_DIR}/viewer/systemd/s9-knowledge-viewer.service"
validate_viewer_unit "${UNIT_SRC}" "${S9K_ROOT}/current" || die "unit nueva inválida"
# B3 · H-02: la unidad del worker, POR EFECTO: su intérprete y su script tienen
# que existir en la release que se va a activar, y su secreto ser el de
# worker.env. El usuario del servicio se lee de la unidad (una sola fuente).
WORKER_UNIT_SRC="${RELEASE_DIR}/data-engine/systemd/${WORKER_UNIT_NAME}"
validate_worker_unit "${WORKER_UNIT_SRC}" "${S9K_ROOT}/current" "${RELEASE_DIR}" "${WORKER_ENV}" \
    || die "unidad del worker inválida (causa arriba)"
WORKER_USER="$(_unit_value "${WORKER_UNIT_SRC}" User)"
WORKER_GROUP="$(_unit_value "${WORKER_UNIT_SRC}" Group)"
# --- fin del paso 7 ---

# Paso 8-9: respaldar unidad instalada + instalar nueva (solo si difiere)
UNIT_CHANGED=0
for _par in "${UNIT_SRC}|${UNIT_DEST}" "${WORKER_UNIT_SRC}|${WORKER_UNIT_DEST}"; do
    _src="${_par%%|*}"; _dst="${_par##*|}"
    if ! diff -q "${_src}" "${_dst}" >/dev/null 2>&1; then
        log "--- 8. respaldar unidad instalada ($(basename "${_dst}"))"
        [ -f "${_dst}" ] && cp -a "${_dst}" "${_dst}.bak-${RELEASE_ID}"
        log "--- 9. instalar unidad nueva ($(basename "${_dst}"))"
        cp "${_src}" "${_dst}"
        UNIT_CHANGED=1
    else
        log "--- 8-9. unidad sin cambios ($(basename "${_dst}"))"
    fi
done

# Paso 10: systemd-analyze verify
log "--- 10. systemd-analyze verify"
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "${UNIT_DEST}" || die "systemd-analyze verify falló"
    systemd-analyze verify "${WORKER_UNIT_DEST}" || die "systemd-analyze verify falló (worker)"
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
log "--- 13. reiniciar servicios (worker y visor)"
# B3 · H-02: el estado que COMPARTEN visor y worker (cola y almacén de
# propuestas) pasa a ser del usuario del servicio del worker ANTES de
# arrancarlo. El visor de `deploy.sh` sigue como root (H-08) y puede leer y
# escribir igual; al revés no: un `jobs.db` creado por root (0644) deja al
# worker en "attempt to write a readonly database".
preparar_estado_del_worker "${WORKER_USER}" "${WORKER_GROUP}" "${NEW_JOBS_DB}" \
    "$(_env_value "${WORKER_ENV}" S9K_V3_REVIEW_PROPOSALS_DIR)" \
    || die "no se pudo preparar el estado compartido del worker"
# El worker se HABILITA siempre, no solo en fresh: hasta B3 no existía ninguna
# unidad de worker, así que todo upgrade es también su primera instalación.
systemctl enable "${WORKER_UNIT_NAME}" || die "no se pudo habilitar el worker"
systemctl restart "${WORKER_UNIT_NAME}" || die "no se pudo reiniciar el worker"
if [ "${MODE}" = "fresh" ]; then
    # Primera release: la unidad acaba de instalarse y nadie la ha habilitado;
    # sin esto el visor no volvería tras reiniciar la máquina (B2, H-01).
    systemctl enable s9-knowledge-viewer.service || die "no se pudo habilitar el visor"
fi
systemctl restart s9-knowledge-viewer.service || die "no se pudo reiniciar el visor"
sleep 3
# --- fin del paso 13 ---

# Paso 14: comprobar commit ejecutado (proceso vivo, no solo el symlink)
log "--- 14. verificar identidad de la release ejecutada"
python3 "${HERE}/verify_release_identity.py" --root "${S9K_ROOT}" \
    --expected-release "${RELEASE_ID}" --expected-commit "${RESOLVED_COMMIT}" \
    --unit s9-knowledge-viewer.service || {
        err "el proceso vivo NO ejecuta la release autorizada — rollback"
        [ -n "${PREV_RELEASE_DIR}" ] && [ -d "${PREV_RELEASE_DIR}" ] && {
            atomic_symlink "${PREV_RELEASE_DIR}" "${S9K_ROOT}/current"
            systemctl restart "${WORKER_UNIT_NAME}" || true
            systemctl restart s9-knowledge-viewer.service || true
        }
        die "activación no verificable; rollback ejecutado"
    }
# Paso 14b (B3 · H-02): el worker tiene que estar VIVO, no solo instalado. Con
# `Restart=always` una unidad rota no se queda en `failed` de inmediato: entra
# en bucle de reinicios, así que se exige `active` en varias lecturas.
log "--- 14b. verificar que el worker está activo"
if ! worker_activo "${WORKER_UNIT_NAME}"; then
    err "el worker no está activo tras el arranque — rollback"
    [ -n "${PREV_RELEASE_DIR}" ] && [ -d "${PREV_RELEASE_DIR}" ] && {
        atomic_symlink "${PREV_RELEASE_DIR}" "${S9K_ROOT}/current"
        systemctl restart "${WORKER_UNIT_NAME}" || true
        systemctl restart s9-knowledge-viewer.service || true
    }
    die "worker no activo (journalctl -u ${WORKER_UNIT_NAME}); rollback ejecutado"
fi

# Paso 15: comprobar admin y jobs preservados
log "--- 15. comprobar admin y jobs"
python3 "${HERE}/detect_state.py" --new-auth "${NEW_AUTH_DB}" --new-jobs "${NEW_JOBS_DB}" --mode "${MODE}" >/dev/null \
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
        systemctl restart "${WORKER_UNIT_NAME}" || true
        systemctl restart s9-knowledge-viewer.service || true
    }
    die "despliegue FALLIDO tras healthcheck (verify_rc=${verify_rc})"
fi

# Paso 16b: vía HTTPS, VERIFICADA POR EFECTO. No que la configuración esté
# escrita: que el endpoint HTTPS declarado verifique certificado y nombre y
# CONTESTE. Si falla, la instalación NO está completa (decisión D3) y este
# guion NO llega a la línea de estado final.
#
# NO hay rollback aquí a propósito: la release activada es correcta --el paso
# 14 lo verificó contra el proceso vivo-- y lo que falta es el terminador TLS,
# que no pertenece a la release. Volver atrás no lo arreglaría y sí perdería
# una activación válida. Lo que sí se hace es NEGARSE a llamar completa a la
# instalación.
log "--- 16b. vía HTTPS (por efecto)"
set +e
python3 "${HERE}/preflight_https.py" --env-file "${VIEWER_ENV}"
https_rc=$?
set -e
if [ "${https_rc}" -ne 0 ]; then
    if [ "${ENVIRONMENT}" = "lab" ]; then
        warn "vía HTTPS no verificada (rc=${https_rc}); en laboratorio no bloquea,"
        warn "pero una instalación productiva con esto NO está completada."
    else
        die "vía HTTPS no verificada (rc=${https_rc}): INSTALACIÓN NO COMPLETA. La release está activa y verificada, pero sin HTTPS no se puede crear el primer administrador."
    fi
fi

# Paso 16c (B2 · USABLE-V1): GATE A, solo con el primer administrador
# PENDIENTE (estado del producto: sin usuarios y sin sello). Un POST
# deliberadamente INVÁLIDO con el CSRF correcto tiene que devolver la
# validación EXACTA (400): demuestra que el CSRF funciona sobre la vía HTTPS
# declarada sin crear nada. NO crea el administrador: eso exige una contraseña
# que elige una persona (GATE B, ver deploy/README.md).
REGISTRO_INSTALACION="${S9K_STATE_ROOT}/deploy/instalacion.json"
https_ok=false; [ "${https_rc}" -eq 0 ] && https_ok=true
# El registro se REINICIA en CADA despliegue, upgrade incluido (corrección
# R2-a de #271): la evidencia de los gates pertenece a la release que la
# observó. Sin esto, un upgrade heredaba la evidencia de GATE A y GATE B de
# otra release y declaraba INSTALLATION_COMPLETE sin haber observado nada. En
# upgrade el GATE A no corre (el setup está sellado), así que la línea final
# se queda en lo observado aquí: DEPLOY_OK.
REGISTRO_ARGS=(--registro "${REGISTRO_INSTALACION}" --reiniciar --anotar deploy_ok=true --anotar "https_verificado=${https_ok}")
python3 "${HERE}/estado_instalacion.py" "${REGISTRO_ARGS[@]}" >/dev/null \
    || warn "no se pudo anotar la evidencia de instalación en ${REGISTRO_INSTALACION}"
if [ "${PRIMER_ADMIN_PENDIENTE}" = "true" ] && [ "${https_rc}" -eq 0 ]; then
    log "--- 16c. GATE A: CSRF funcional en /setup/admin (no escribe)"
    set +e
    python3 "${HERE}/preflight_setup_admin.py" --env-file "${VIEWER_ENV}" --modo gate-a \
        --registro "${REGISTRO_INSTALACION}"
    gate_a_rc=$?
    set -e
    if [ "${gate_a_rc}" -ne 0 ]; then
        if [ "${ENVIRONMENT}" = "lab" ]; then
            warn "GATE A no pasa (rc=${gate_a_rc}); en laboratorio no bloquea, pero el primer administrador NO se podría crear."
        else
            die "GATE A no pasa (rc=${gate_a_rc}): el primer administrador NO se podría crear. INSTALACIÓN NO COMPLETA."
        fi
    fi
fi

# Retention fail-closed: activa borrado real solo tras deploy verificado
S9K_RETENTION_APPLY=1 cleanup_old_releases

# Paso 17: liberar lock (implícito al cerrar el FD/proceso)
log "--- 17. liberar lock"
# «deploy.sh terminó» NO es «instalación completa». Dos líneas (O-A):
# ESTADO_OBSERVADO = lo que vio ESTA ejecución (nunca anota evidencia de gates
# que no observó); ESTADO_DEL_PRODUCTO = lo que la auth DB dice de sí misma
# (sello + admins), sin mirar el registro.
log "=== DEPLOY terminado === release=${RELEASE_ID} modo=${MODE} decision=${DECISION}"
python3 "${HERE}/estado_instalacion.py" --registro "${REGISTRO_INSTALACION}" --auth-db "${NEW_AUTH_DB}" \
    | while IFS= read -r _linea_estado; do log "    ${_linea_estado}"; done
if [ "${PRIMER_ADMIN_PENDIENTE}" != "true" ]; then
    log "    (upgrade: ESTADO_OBSERVADO es solo lo observado en ESTA ejecución; la"
    log "    instalación ya sellada no re-ejecuta GATE A/B. Su estado real lo da"
    log "    ESTADO_DEL_PRODUCTO, leído de la auth DB, no heredado del registro)"
fi
if [ "${PRIMER_ADMIN_PENDIENTE}" = "true" ]; then
    log "    Siguiente: crear el primer administrador en /setup/admin y ejecutar el GATE B"
    log "    (preflight_setup_admin.py --modo bootstrap|persistencia --registro ${REGISTRO_INSTALACION})."
    log "    INSTALLATION_COMPLETE solo tras el GATE B --modo persistencia DESPUÉS de un reinicio."
fi

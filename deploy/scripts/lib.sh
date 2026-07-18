#!/usr/bin/env bash
# Librería común para los scripts operativos de S9 Knowledge.
# Sin secretos. Solo funciones de apoyo.
# shellcheck shell=bash
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Raíces configurables (sobreescribibles por variables de entorno)
# ---------------------------------------------------------------------------
S9K_ROOT="${S9K_ROOT:-/opt/s9-knowledge}"
S9K_STATE_ROOT="${S9K_STATE_ROOT:-/var/lib/s9-knowledge}"
S9K_CONFIG_ROOT="${S9K_CONFIG_ROOT:-/etc/s9-knowledge}"
S9K_LOG_ROOT="${S9K_LOG_ROOT:-/var/log/s9-knowledge}"
S9K_VIEWER_URL="${S9K_VIEWER_URL:-http://127.0.0.1:8088}"

# Número de releases a conservar (las más antiguas se eliminan automáticamente)
S9K_RELEASES_TO_KEEP="${S9K_RELEASES_TO_KEEP:-3}"

# ---------------------------------------------------------------------------
# Colores de terminal
# ---------------------------------------------------------------------------
_c_reset='\033[0m'
_c_red='\033[31m'
_c_grn='\033[32m'
_c_yel='\033[33m'
_c_blu='\033[34m'

# ---------------------------------------------------------------------------
# Funciones de log (siempre a stderr excepto log que va a stdout también)
# Las variables se pasan a printf de forma segura (sin eval, sin expansión no controlada)
# ---------------------------------------------------------------------------
log()  { printf '%b[s9k]%b %s\n'  "$_c_grn"  "$_c_reset" "$*"; }
warn() { printf '%b[s9k]%b %s\n'  "$_c_yel"  "$_c_reset" "$*" >&2; }
err()  { printf '%b[s9k]%b %s\n'  "$_c_red"  "$_c_reset" "$*" >&2; }
info() { printf '%b[s9k]%b %s\n'  "$_c_blu"  "$_c_reset" "$*"; }
die()  { err "$*"; exit 1; }
# ok: resultado satisfactorio de un check. Definida aquí para que todos los
# scripts que sourcean lib.sh puedan usarla sin que el texto del argumento
# se ejecute como comando (el bug histórico de verify-deployment.sh).
ok()   { log "PASS $*"; }

# ---------------------------------------------------------------------------
# Comprueba que existe un comando.
# ---------------------------------------------------------------------------
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "falta el comando requerido: $1"
}

# ---------------------------------------------------------------------------
# Comprueba un puerto TCP escuchando localmente (ss con fallback a netstat).
# ---------------------------------------------------------------------------
port_listening() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${1}$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${1}$"
    else
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Devuelve el commit corto del repo actual (o 'unknown').
# ---------------------------------------------------------------------------
repo_commit() {
    git -C "${S9K_ROOT}/current" rev-parse --short HEAD 2>/dev/null \
        || git rev-parse --short HEAD 2>/dev/null \
        || printf 'unknown'
}

# ---------------------------------------------------------------------------
# Genera un ID único de release: <git-short-sha>-<timestamp>
# Requiere que el directorio de trabajo tenga un .git accesible.
# ---------------------------------------------------------------------------
create_release_id() {
    local repo_dir="${1:-.}"
    local short_sha
    short_sha="$(git -C "${repo_dir}" rev-parse --short HEAD 2>/dev/null || printf 'nogit')"
    local ts
    ts="$(date -u '+%Y%m%d-%H%M%S')"
    printf '%s-%s' "${short_sha}" "${ts}"
}

# ---------------------------------------------------------------------------
# Symlink atómico: reemplaza <link> apuntando a <target> sin ventana de rotura.
# Usa un nombre temporal + mv -T (Linux) o mv con overwrite.
# ---------------------------------------------------------------------------
atomic_symlink() {
    local target="${1}"
    local link="${2}"
    local tmp_link
    tmp_link="${link}.tmp.$$"
    ln -sfn "${target}" "${tmp_link}"
    # mv -T fuerza que el destino sea exactamente el nombre dado (no dentro de él)
    if mv -T "${tmp_link}" "${link}" 2>/dev/null; then
        return 0
    else
        # Fallback: mv sin -T (algunos sistemas no lo soportan)
        mv "${tmp_link}" "${link}"
    fi
}

# ---------------------------------------------------------------------------
# Adquiere un lock exclusivo en /var/lock/s9k-deploy.lock.
# El FD 200 se hereda por el proceso que llama; el lock se libera al salir.
# ---------------------------------------------------------------------------
lock_deploy() {
    local lockfile="/var/lock/s9k-deploy.lock"
    # Intentamos crear el lockfile; si no tenemos permisos en /var/lock usamos /tmp
    if ! touch "${lockfile}" 2>/dev/null; then
        lockfile="/tmp/s9k-deploy.lock"
    fi
    exec 200>"${lockfile}"
    if ! flock -n 200; then
        die "Otro proceso de deploy/rollback está en ejecución (${lockfile}). Espera o elimina el lock."
    fi
    log "Lock adquirido: ${lockfile}"
}

# ---------------------------------------------------------------------------
# Valida que un fichero JSON de manifiesto tiene los campos obligatorios.
# No imprime el contenido completo (puede tener rutas). Solo valida estructura.
# ---------------------------------------------------------------------------
validate_manifest() {
    local manifest_path="${1}"
    if [ ! -f "${manifest_path}" ]; then
        err "Manifiesto no encontrado: ${manifest_path}"
        return 1
    fi
    local required_fields="release_id git_commit created_at created_by python_version schema_versions compatible_rollback_to"
    for field in ${required_fields}; do
        if ! python3 -c "
import json, sys
try:
    d = json.load(open('${manifest_path}'))
    sys.exit(0 if '${field}' in d else 1)
except Exception:
    sys.exit(2)
" 2>/dev/null; then
            err "Manifiesto inválido: falta campo '${field}' en ${manifest_path}"
            return 1
        fi
    done
    return 0
}

# ---------------------------------------------------------------------------
# Checksum de contenido de una release.
#
# Lista de exclusión ÚNICA y COMPARTIDA entre generación (create_manifest) y
# verificación (verify_release_checksum). Si divergen, el checksum es inútil.
#
# Solo se excluye contenido DERIVADO o MUTABLE (bytecode, cachés de test,
# cobertura, logs, temporales). Nunca código, templates, static, units, scripts
# ni el resto del contenido versionado.
#
# manifest.json se excluye porque contiene el propio checksum (autorreferencia).
#
# `-type f` deja fuera por construcción sockets, FIFOs, dispositivos y symlinks.
# ---------------------------------------------------------------------------
S9K_CHECKSUM_EXCLUDE_DIRS="${S9K_CHECKSUM_EXCLUDE_DIRS:-.venv __pycache__ .pytest_cache .mypy_cache .ruff_cache .tox htmlcov node_modules}"
# OJO: no excluir *.bak — data-engine/backups/*.bak es contenido VERSIONADO real,
# no un artefacto derivado. Excluirlo dejaría código fuera del checksum.
S9K_CHECKSUM_EXCLUDE_GLOBS="${S9K_CHECKSUM_EXCLUDE_GLOBS:-manifest.json *.pyc *.pyo *.pyd *.log *.tmp *.temp *.swp *.swo .coverage .coverage.* coverage.xml}"

# Lista los ficheros que ENTRAN en el checksum (NUL-separados).
_checksum_file_list() {
    local dir="${1}"
    local -a args=( "${dir}" )
    local d g first=1

    args+=( '(' )
    for d in ${S9K_CHECKSUM_EXCLUDE_DIRS}; do
        [ "${first}" -eq 1 ] || args+=( -o )
        args+=( -name "${d}" )
        first=0
    done
    args+=( ')' -prune -o -type f )

    for g in ${S9K_CHECKSUM_EXCLUDE_GLOBS}; do
        args+=( ! -name "${g}" )
    done
    args+=( -print0 )

    find "${args[@]}"
}

# Algoritmo declarado en los manifiestos NUEVOS. Los emitidos antes del hotfix
# no llevan campo `checksum_algo` y se verifican con la fórmula v1.
S9K_CHECKSUM_ALGO="v2"

# release_files_checksum_v1 <release_dir> -> imprime "sha256:<hex>"
#
# Verificador de compatibilidad para manifiestos emitidos ANTES del hotfix.
#
# Conserva el flujo original (rutas absolutas, `sort` del locale, `xargs
# sha256sum`) para reproducir el valor declarado, pero PODA los artefactos
# derivados. Esa poda no altera el resultado: los artefactos no existían cuando
# se emitió el manifiesto. Sin ella, v1 es inverificable en produccion, porque el
# propio servicio en marcha regenera __pycache__ y se invalida solo.
#
# Comprobado contra la release real de RC2: con 172 cachés presentes reproduce
# exactamente el files_checksum del manifiesto.
#
# LIMITACIÓN CONOCIDA — v1 NO es un control antimanipulación:
#
#   `xargs` sin -0 parte los nombres por los espacios, así que sha256sum nunca
#   ve los ficheros cuyo nombre los contiene: quedan FUERA del hash. En la
#   release de RC2 eso afecta a un fichero real y versionado:
#       docs/project dossier and checklist.md
#   (la fórmula original hashea 431 ficheros; la correcta, 432).
#
#   Es decir: ese fichero puede alterarse sin que v1 lo detecte. El defecto es
#   del manifiesto emitido, no de este verificador; corregirlo aquí solo haría
#   que v1 dejara de reproducir lo declarado y abortara despliegues sanos.
#
#   v2 sí lo cubre (-print0/-0). Cada release nueva nace con manifiesto v2, con
#   lo que el punto ciego desaparece en cuanto RC2 deje de ser la release activa.
#
# NO usar para releases nuevas: además, el `sort` del locale no es reproducible
# entre entornos. Para eso está v2.
release_files_checksum_v1() {
    local dir="${1}"
    if [ ! -d "${dir}" ]; then
        err "release_files_checksum_v1: no es un directorio: ${dir}"
        return 1
    fi
    need_cmd find; need_cmd sha256sum
    local hash
    # `xargs` SIN -0 y `sort` SIN LC_ALL=C: ambos defectos se conservan a
    # propósito. v1 no es un algoritmo que se elija, es el que ya se usó: su
    # único trabajo es reproducir lo que declara un manifiesto ya emitido.
    # "Arreglarlo" haría que dejara de coincidir y la compuerta abortaría
    # despliegues de releases sanas.
    #
    # `set +o pipefail` en la subshell: ante un nombre con espacios, xargs parte
    # la ruta, sha256sum falla sobre los trozos y xargs sale 123. El hash que
    # imprime awk es correcto igualmente (es justo el que declara el manifiesto),
    # pero con pipefail la pipeline se da por fallida. Sin esto la función solo
    # "funcionaba" cuando se la llamaba dentro de un `||`, porque ahí bash
    # suprime errexit: dependía del contexto de llamada.
    # shellcheck disable=SC2038  # fidelidad deliberada con la fórmula original
    hash="$(set +o pipefail
        find "${dir}" \
            \( -name .venv -o -name __pycache__ -o -name .pytest_cache \
               -o -name .mypy_cache -o -name .ruff_cache \) -prune -o \
            -type f ! -name 'manifest.json' ! -name '*.pyc' ! -name '*.pyo' -print \
            | sort | xargs sha256sum 2>/dev/null | sha256sum | awk '{print $1}')"
    if [ -z "${hash}" ]; then
        err "release_files_checksum_v1: no se pudo calcular el hash en ${dir}"
        return 1
    fi
    printf 'sha256:%s' "${hash}"
}

# release_files_checksum <release_dir> -> imprime "sha256:<hex>"  (algoritmo v2)
#
# Se fija LC_ALL=C porque el `sort` de v1 dependía del locale y por tanto no era
# reproducible entre entornos. Eso, junto con las exclusiones ampliadas, hace que
# v2 NO reproduzca los checksums de v1: por eso el algoritmo va versionado en el
# manifiesto en vez de romper los ya emitidos.
release_files_checksum() {
    local dir="${1}"
    if [ ! -d "${dir}" ]; then
        err "release_files_checksum: no es un directorio: ${dir}"
        return 1
    fi
    need_cmd find; need_cmd sha256sum
    local hash
    hash="$(_checksum_file_list "${dir}" \
        | LC_ALL=C sort -z \
        | xargs -0 -r sha256sum 2>/dev/null \
        | sha256sum | awk '{print $1}')"
    printf 'sha256:%s' "${hash}"
}

# verify_release_checksum <release_dir> [manifest_path]
#   0 = coincide · 1 = NO coincide o no se puede comprobar.
#   Nunca reescribe el manifiesto: solo compara e informa.
verify_release_checksum() {
    local dir="${1}"
    local manifest="${2:-${dir}/manifest.json}"
    if [ ! -f "${manifest}" ]; then
        err "verify_release_checksum: manifiesto no encontrado: ${manifest}"
        return 1
    fi
    local expected actual algo
    expected="$(manifest_field "${manifest}" files_checksum)"
    if [ -z "${expected}" ] || [ "${expected}" = "unknown" ]; then
        err "verify_release_checksum: el manifiesto no declara files_checksum utilizable"
        return 1
    fi

    # Sin campo `checksum_algo` el manifiesto es anterior al hotfix: se verifica
    # con v1, que es la fórmula con la que se emitió. Verificarlo con v2 daría un
    # falso "release alterada" en releases perfectamente sanas (RC2 incluida).
    algo="$(manifest_field "${manifest}" checksum_algo)"
    [ -n "${algo}" ] || algo="v1"

    case "${algo}" in
        v1) actual="$(release_files_checksum_v1 "${dir}")" || return 1 ;;
        v2) actual="$(release_files_checksum "${dir}")" || return 1 ;;
        *)  err "verify_release_checksum: algoritmo desconocido '${algo}'"; return 1 ;;
    esac

    if [ "${expected}" = "${actual}" ]; then
        log "checksum de release OK (${dir}, algoritmo ${algo})"
        return 0
    fi
    err "checksum de release NO coincide en ${dir} (algoritmo ${algo})"
    err "  declarado:   ${expected}"
    err "  recalculado: ${actual}"
    if [ "${algo}" = "v1" ]; then
        err "  v1 es sensible a __pycache__ y al locale: si se ejecutaron tests"
        err "  dentro de la release, borrar los artefactos derivados y reintentar."
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Genera un manifiesto JSON en <release_dir>/manifest.json.
# NO incluye secretos, variables de entorno ni tokens.
# ---------------------------------------------------------------------------
create_manifest() {
    local release_dir="${1}"
    local release_id="${2}"
    local git_commit="${3}"
    local environment="${4}"

    local python_version
    python_version="$(python3 --version 2>&1 | awk '{print $2}' || printf 'unknown')"

    local dep_hash="unknown"
    if [ -f "${release_dir}/viewer/requirements.txt" ]; then
        dep_hash="sha256:$(sha256sum "${release_dir}/viewer/requirements.txt" | awk '{print $1}')"
    fi

    # Usa la MISMA lista de exclusión que verify_release_checksum.
    local files_hash="unknown"
    if command -v find >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
        files_hash="$(release_files_checksum "${release_dir}")"
    fi

    local created_at
    created_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    python3 - <<PYEOF
import json
manifest = {
    "release_id": "${release_id}",
    "git_commit": "${git_commit}",
    "environment": "${environment}",
    "created_at": "${created_at}",
    "created_by": "deploy.sh",
    "python_version": "${python_version}",
    "dependency_fingerprint": "${dep_hash}",
    "schema_versions": {"auth_db": 1, "job_store": 1},
    "compatible_rollback_to": [],
    "files_checksum": "${files_hash}",
    "checksum_algo": "${S9K_CHECKSUM_ALGO}"
}
with open("${release_dir}/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
print("Manifiesto creado: ${release_dir}/manifest.json")
PYEOF
}

# ---------------------------------------------------------------------------
# Lee un campo del manifiesto JSON de forma segura.
# ---------------------------------------------------------------------------
manifest_field() {
    local manifest_path="${1}"
    local field="${2}"
    python3 -c "
import json, sys
try:
    d = json.load(open('${manifest_path}'))
    print(d.get('${field}', ''))
except Exception as e:
    print('', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || printf ''
}

# ---------------------------------------------------------------------------
# Lista las releases disponibles ordenadas de más nueva a más antigua.
# ---------------------------------------------------------------------------
list_releases() {
    local releases_dir="${S9K_ROOT}/releases"
    if [ ! -d "${releases_dir}" ]; then
        warn "No existe directorio de releases: ${releases_dir}"
        return 0
    fi
    find "${releases_dir}" -maxdepth 1 -mindepth 1 -type d | sort -r
}

# ---------------------------------------------------------------------------
# Devuelve el ID de la release actualmente activa (symlink current).
# ---------------------------------------------------------------------------
current_release_id() {
    local current_link="${S9K_ROOT}/current"
    if [ -L "${current_link}" ]; then
        basename "$(readlink -f "${current_link}")"
    else
        printf ''
    fi
}

# ---------------------------------------------------------------------------
# Escribe /var/lib/s9-knowledge/deploy/deployment-state.json de forma atómica.
# Uso: write_deployment_state <active_release> <active_commit>
#                             <previous_release|-> <previous_commit|->
#                             <deployment_id>
# Los campos prev* aceptan '-' para indicar "no aplica".
# ---------------------------------------------------------------------------
write_deployment_state() {
    local active_release="${1}"
    local active_commit="${2}"
    local previous_release="${3:-}"
    local previous_commit="${4:-}"
    local deployment_id="${5:-}"
    local state_file="${S9K_DEPLOY_STATE_FILE:-${S9K_STATE_ROOT}/deploy/deployment-state.json}"
    local here_scripts
    here_scripts="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "${here_scripts}/retention.py" \
        --state-file "${state_file}" \
        --write-state \
        "${active_release}" \
        "${active_commit}" \
        "${previous_release:--}" \
        "${previous_commit:--}" \
        "${deployment_id}" \
    || warn "write_deployment_state: fallo al escribir ${state_file} (no bloquea el deploy)"
}

# ---------------------------------------------------------------------------
# Elimina releases antiguas de forma FAIL-CLOSED usando retention.py.
# POR DEFECTO: dry-run. Para borrar de verdad: S9K_RETENTION_APPLY=1.
# ---------------------------------------------------------------------------
cleanup_old_releases() {
    local here_scripts
    here_scripts="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local state_file="${S9K_DEPLOY_STATE_FILE:-${S9K_STATE_ROOT}/deploy/deployment-state.json}"
    local mode="--dry-run"
    [ "${S9K_RETENTION_APPLY:-0}" = "1" ] && mode="--apply"

    log "Retención de releases (${mode}): invocando retention.py"
    python3 "${here_scripts}/retention.py" \
        --releases-root "${S9K_ROOT}/releases" \
        --current-link  "${S9K_ROOT}/current" \
        --state-file    "${state_file}" \
        --keep          "${S9K_RELEASES_TO_KEEP}" \
        "${mode}" \
    || warn "retention.py salió con error — ninguna release borrada (fail-closed)"
}

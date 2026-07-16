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

    local files_hash="unknown"
    if command -v find >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
        files_hash="sha256:$(find "${release_dir}" -type f -not -path '*/.venv/*' -not -name 'manifest.json' \
            | sort | xargs sha256sum 2>/dev/null | sha256sum | awk '{print $1}')"
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
    "files_checksum": "${files_hash}"
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
# Elimina releases antiguas conservando las S9K_RELEASES_TO_KEEP más recientes.
# La release activa nunca se elimina aunque sea antigua.
# ---------------------------------------------------------------------------
cleanup_old_releases() {
    local active_id
    active_id="$(current_release_id)"
    local releases_dir="${S9K_ROOT}/releases"
    local count=0
    local to_delete=()

    while IFS= read -r release_dir; do
        local rid
        rid="$(basename "${release_dir}")"
        count=$((count + 1))
        if [ "${count}" -gt "${S9K_RELEASES_TO_KEEP}" ] && [ "${rid}" != "${active_id}" ]; then
            to_delete+=("${release_dir}")
        fi
    done < <(list_releases)

    for dir in "${to_delete[@]+"${to_delete[@]}"}"; do
        warn "Eliminando release antigua: ${dir}"
        rm -rf "${dir}"
    done
}

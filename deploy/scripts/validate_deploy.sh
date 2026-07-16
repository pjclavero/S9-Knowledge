#!/usr/bin/env bash
# validate_deploy.sh — gates de validación de viewer.env y de la unit systemd para
# la corrección de continuidad de estado (RC1). Sin secretos: solo comprueba
# PRESENCIA de variables críticas, nunca imprime sus valores.
# shellcheck shell=bash
set -Eeuo pipefail

LEGACY_LAYOUT="/opt/knowledge-services/s9-knowledge-repo"

# Variables cuya ausencia BLOQUEA el despliegue (nombres verbatim del código).
# S9K_CSRF_SECRET NO va aquí: tiene su propia validación profunda (validate_csrf_secret),
# que además exige que esté presente y sea fuerte.
CRITICAL_ENV_VARS="S9K_VIEWER_HOST S9K_VIEWER_PORT S9K_GRAPH_PROVIDER S9K_NEO4J_URI S9K_NEO4J_USER S9K_AUTH_DB_PATH S9K_JOBS_DB S9K_AUTH_ENABLED"

# Placeholders prohibidos para un secreto (case-insensitive, coincidencia exacta).
CSRF_PLACEHOLDERS="change-me change-me-in-host changeme replace-me example default password secret s9k-csrf-change-me s9k-csrf-default"

# Longitud/entropía mínimas (alineadas con viewer/app/auth/security.py).
CSRF_MIN_LEN=32
CSRF_MIN_UNIQUE=8

# Rutas que NO deben contener secretos (la release es efímera/versionada).
RELEASE_PREFIXES="/opt/s9-knowledge/releases /opt/s9-knowledge/current"

# ---------------------------------------------------------------------------
# _env_value <env_file> <VAR>  -> imprime el valor (sin comillas envolventes).
#   No expone el valor por logs; solo lo devuelve por stdout para uso interno.
# ---------------------------------------------------------------------------
_env_value() {
    local env_file="${1}" var="${2}" line val
    line="$(grep -E "^[[:space:]]*${var}[[:space:]]*=" "${env_file}" 2>/dev/null | grep -vE '^[[:space:]]*#' | tail -1 || true)"
    val="${line#*=}"
    # recorta espacios de borde y comillas envolventes simples/dobles
    val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
    printf '%s' "${val}"
}

# ---------------------------------------------------------------------------
# validate_csrf_secret <env_file>
#   Rechaza: ausente/vacío; placeholder conocido; < CSRF_MIN_LEN; entropía baja
#   (< CSRF_MIN_UNIQUE caracteres distintos); igual al usuario Neo4j; secreto
#   guardado dentro de una release. NUNCA imprime el valor.
# ---------------------------------------------------------------------------
validate_csrf_secret() {
    local env_file="${1}"
    [ -f "${env_file}" ] || { printf 'BLOCK(csrf): viewer.env no existe\n' >&2; return 1; }
    local val lower ph user
    val="$(_env_value "${env_file}" S9K_CSRF_SECRET)"
    if [ -z "${val}" ]; then
        printf 'BLOCK(csrf): S9K_CSRF_SECRET ausente o vacío\n' >&2; return 1
    fi
    lower="$(printf '%s' "${val}" | tr '[:upper:]' '[:lower:]')"
    for ph in ${CSRF_PLACEHOLDERS}; do
        if [ "${lower}" = "${ph}" ]; then
            printf 'BLOCK(csrf): S9K_CSRF_SECRET es un placeholder prohibido\n' >&2; return 1
        fi
    done
    case "${lower}" in *change-me*|*changeme*|*replace-me*|*placeholder*)
        printf 'BLOCK(csrf): S9K_CSRF_SECRET contiene un placeholder\n' >&2; return 1 ;;
    esac
    if [ "${#val}" -lt "${CSRF_MIN_LEN}" ]; then
        printf 'BLOCK(csrf): S9K_CSRF_SECRET demasiado corto (< %d)\n' "${CSRF_MIN_LEN}" >&2; return 1
    fi
    local uniq
    uniq="$(printf '%s' "${val}" | fold -w1 | sort -u | wc -l)"
    if [ "${uniq}" -lt "${CSRF_MIN_UNIQUE}" ]; then
        printf 'BLOCK(csrf): S9K_CSRF_SECRET con entropía insuficiente (< %d distintos)\n' "${CSRF_MIN_UNIQUE}" >&2; return 1
    fi
    user="$(_env_value "${env_file}" S9K_NEO4J_USER)"
    if [ -n "${user}" ] && [ "${val}" = "${user}" ]; then
        printf 'BLOCK(csrf): S9K_CSRF_SECRET igual al usuario Neo4j\n' >&2; return 1
    fi
    local pfx
    for pfx in ${RELEASE_PREFIXES}; do
        case "${val}" in "${pfx}"*)
            printf 'BLOCK(csrf): el secreto apunta dentro de una release\n' >&2; return 1 ;;
        esac
    done
    return 0
}

# ---------------------------------------------------------------------------
# validate_secret_file <path>
#   Para ficheros de secreto referenciados (p. ej. S9K_NEO4J_PASSWORD_FILE):
#   debe existir, no ser symlink, tener permisos 0600 (sin lectura grupo/otros),
#   y no estar dentro de una release. NUNCA imprime el contenido.
# ---------------------------------------------------------------------------
validate_secret_file() {
    local path="${1}" pfx perms
    if [ -z "${path}" ]; then return 0; fi
    for pfx in ${RELEASE_PREFIXES}; do
        case "${path}" in "${pfx}"*)
            printf 'BLOCK(secret-file): fichero de secreto dentro de una release: %s\n' "${path}" >&2; return 1 ;;
        esac
    done
    if [ -L "${path}" ]; then
        printf 'BLOCK(secret-file): es un symlink (rechazado): %s\n' "${path}" >&2; return 1
    fi
    if [ ! -f "${path}" ]; then
        printf 'BLOCK(secret-file): no existe: %s\n' "${path}" >&2; return 1
    fi
    perms="$(stat -c '%a' "${path}" 2>/dev/null || printf '')"
    # rechaza cualquier bit de grupo/otros (perms de 3 dígitos con 2º/3er != 0)
    case "${perms}" in
        [0-7]00) ;;  # solo dueño
        *) printf 'BLOCK(secret-file): permisos inseguros (%s) en %s\n' "${perms}" "${path}" >&2; return 1 ;;
    esac
    return 0
}

# ---------------------------------------------------------------------------
# validate_viewer_secrets <env_file>
#   Combina CSRF + fichero de contraseña Neo4j (si se usa *_FILE).
# ---------------------------------------------------------------------------
validate_viewer_secrets() {
    local env_file="${1}" rc=0 pwfile
    validate_csrf_secret "${env_file}" || rc=1
    pwfile="$(_env_value "${env_file}" S9K_NEO4J_PASSWORD_FILE)"
    validate_secret_file "${pwfile}" || rc=1
    return "${rc}"
}

# ---------------------------------------------------------------------------
# validate_viewer_env <viewer.env>
#   Falla (rc=1) si el fichero no existe o si falta/está vacía una variable crítica.
#   No imprime valores; solo el NOMBRE de las variables ausentes.
# ---------------------------------------------------------------------------
validate_viewer_env() {
    local env_file="${1}"
    if [ ! -f "${env_file}" ]; then
        printf 'BLOCK: viewer.env no existe: %s\n' "${env_file}" >&2
        return 1
    fi
    local missing=()
    local var
    for var in ${CRITICAL_ENV_VARS}; do
        # Línea var=valor con valor no vacío (ignora comentarios y espacios)
        if ! grep -qE "^[[:space:]]*${var}[[:space:]]*=[[:space:]]*[^[:space:]#].*$" "${env_file}"; then
            missing+=("${var}")
        fi
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        printf 'BLOCK: faltan variables críticas en viewer.env: %s\n' "${missing[*]}" >&2
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# validate_viewer_unit <unit_file> [<expected_current>]
#   Falla si la unit referencia el layout legacy, si WorkingDirectory/ExecStart no
#   cuelgan de current, si el venv no es de current, o si falta EnvironmentFile.
# ---------------------------------------------------------------------------
validate_viewer_unit() {
    local unit_file="${1}"
    local current_path="${2:-/opt/s9-knowledge/current}"
    if [ ! -f "${unit_file}" ]; then
        printf 'BLOCK: unit no existe: %s\n' "${unit_file}" >&2
        return 1
    fi
    local errs=()
    if grep -q "${LEGACY_LAYOUT}" "${unit_file}"; then
        errs+=("referencia layout legacy ${LEGACY_LAYOUT}")
    fi
    local wd
    wd="$(grep -E '^WorkingDirectory=' "${unit_file}" | head -1 | cut -d= -f2- || true)"
    case "${wd}" in
        "${current_path}"/*) ;;
        *) errs+=("WorkingDirectory no cuelga de ${current_path}: '${wd}'") ;;
    esac
    local exec_line
    exec_line="$(grep -E '^ExecStart=' "${unit_file}" | head -1 || true)"
    case "${exec_line}" in
        *"${current_path}/"*) ;;
        *) errs+=("ExecStart no cuelga de ${current_path}") ;;
    esac
    case "${exec_line}" in
        *"${current_path}/viewer/.venv/"*) ;;
        *) errs+=("venv no pertenece a ${current_path}") ;;
    esac
    if ! grep -qE '^EnvironmentFile=/etc/s9-knowledge/viewer\.env' "${unit_file}"; then
        errs+=("falta EnvironmentFile=/etc/s9-knowledge/viewer.env")
    fi
    if [ "${#errs[@]}" -gt 0 ]; then
        local e
        for e in "${errs[@]}"; do printf 'BLOCK(unit): %s\n' "${e}" >&2; done
        return 1
    fi
    return 0
}

# Permite ejecutar como CLI: validate_deploy.sh env <file> | unit <file> [current]
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    case "${1:-}" in
        env)     validate_viewer_env "${2:?falta ruta viewer.env}" ;;
        unit)    validate_viewer_unit "${2:?falta ruta unit}" "${3:-/opt/s9-knowledge/current}" ;;
        csrf)    validate_csrf_secret "${2:?falta ruta viewer.env}" ;;
        secrets) validate_viewer_secrets "${2:?falta ruta viewer.env}" ;;
        secret-file) validate_secret_file "${2:?falta ruta fichero}" ;;
        *) printf 'uso: validate_deploy.sh env|csrf|secrets <viewer.env> | unit <unit> [current] | secret-file <path>\n' >&2; exit 2 ;;
    esac
fi

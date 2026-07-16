#!/usr/bin/env bash
# validate_deploy.sh — gates de validación de viewer.env y de la unit systemd para
# la corrección de continuidad de estado (RC1). Sin secretos: solo comprueba
# PRESENCIA de variables críticas, nunca imprime sus valores.
# shellcheck shell=bash
set -Eeuo pipefail

LEGACY_LAYOUT="/opt/knowledge-services/s9-knowledge-repo"

# Variables cuya ausencia BLOQUEA el despliegue (nombres verbatim del código).
CRITICAL_ENV_VARS="S9K_VIEWER_HOST S9K_VIEWER_PORT S9K_GRAPH_PROVIDER S9K_NEO4J_URI S9K_NEO4J_USER S9K_AUTH_DB_PATH S9K_JOBS_DB S9K_AUTH_ENABLED S9K_CSRF_SECRET"

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
        env)  validate_viewer_env "${2:?falta ruta viewer.env}" ;;
        unit) validate_viewer_unit "${2:?falta ruta unit}" "${3:-/opt/s9-knowledge/current}" ;;
        *) printf 'uso: validate_deploy.sh env <viewer.env> | unit <unit> [current]\n' >&2; exit 2 ;;
    esac
fi

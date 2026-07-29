#!/usr/bin/env bash
# rollback-full.sh — rollback coordinado de release y dump Neo4j.
# Dry-run por defecto. --apply es la única autorización de escritura.
# shellcheck shell=bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
APP_ROLLBACK="${S9K_ROLLBACK_RELEASE_SCRIPT:-${HERE}/rollback-release.sh}"
DATA_RESTORE="${S9K_NEO4J_RESTORE_SCRIPT:-${REPO_ROOT}/scripts/backup/neo4j-restore.sh}"
VERIFY="${S9K_VERIFY_DEPLOYMENT_SCRIPT:-${HERE}/verify-deployment.sh}"

target=""
dump=""
environment="${S9K_ENVIRONMENT:-production}"
apply=0

usage() {
    printf '%s\n' \
        "uso: rollback-full.sh --to <release> --neo4j-dump <ruta> [--environment lab|production] [--apply]" \
        "Dry-run por defecto; --apply ejecuta primero los dos dry-runs y solo continúa si ambos pasan."
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
run_dry_runs() {
    printf '%s\n' "--- dry-run aplicación"
    "${APP_ROLLBACK}" --environment "${environment}" --to-release "${target}" --dry-run
    printf '%s\n' "--- dry-run datos"
    "${DATA_RESTORE}" --backup-file "${dump}" --dry-run
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --to) [ "$#" -ge 2 ] || die "falta valor para --to"; target="$2"; shift 2 ;;
        --neo4j-dump) [ "$#" -ge 2 ] || die "falta valor para --neo4j-dump"; dump="$2"; shift 2 ;;
        --environment) [ "$#" -ge 2 ] || die "falta valor para --environment"; environment="$2"; shift 2 ;;
        --apply) apply=1; shift ;;
        --dry-run) apply=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

[ -n "${target}" ] || { usage >&2; die "--to es obligatorio"; }
[ -n "${dump}" ] || { usage >&2; die "--neo4j-dump es obligatorio"; }
[ -f "${dump}" ] || die "dump no encontrado: ${dump}"
case "${environment}" in lab|production) ;; *) die "entorno inválido: ${environment}" ;; esac

# Esta fase es obligatoria también con --apply. set -e garantiza que no se
# modifica ninguna pata si cualquiera de los dos planes falla.
run_dry_runs
if [ "${apply}" -eq 0 ]; then
    printf 'ROLLBACK_FULL_DRY_RUN_OK\n'
    exit 0
fi

printf '%s\n' "--- aplicar restore de datos"
"${DATA_RESTORE}" --backup-file "${dump}"
printf '%s\n' "--- aplicar rollback de aplicación"
if [ "${environment}" = "production" ]; then
    "${APP_ROLLBACK}" --environment production --to-release "${target}" --confirm-production
else
    "${APP_ROLLBACK}" --environment lab --to-release "${target}" --confirm
fi
printf '%s\n' "--- verificación conjunta final"
"${VERIFY}" --expected-release "${target}"
printf 'ROLLBACK_FULL_OK\n'

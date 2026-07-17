#!/usr/bin/env bash
# release_checksum.sh — calcula o verifica el checksum de contenido de una release.
#
# Solo lectura: nunca escribe en la release ni reescribe el manifiesto.
#
# Uso:
#   release_checksum.sh compute <release_dir>          # imprime sha256:<hex>
#   release_checksum.sh verify  <release_dir> [manifest]
#   release_checksum.sh list    <release_dir>          # ficheros que entran
#
# Salida: 0 = OK/coincide · 1 = no coincide o error de uso.
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"

case "${1:-}" in
    compute)
        release_files_checksum "${2:?falta release_dir}"; printf '\n'
        ;;
    verify)
        verify_release_checksum "${2:?falta release_dir}" "${3:-}"
        ;;
    list)
        _checksum_file_list "${2:?falta release_dir}" | tr '\0' '\n'
        ;;
    *)
        printf 'uso: release_checksum.sh compute|list <release_dir> | verify <release_dir> [manifest]\n' >&2
        exit 1
        ;;
esac

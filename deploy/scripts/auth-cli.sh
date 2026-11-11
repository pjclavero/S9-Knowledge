#!/usr/bin/env bash
# auth-cli.sh — la forma CANONICA de ejecutar la CLI de auth (H-06 + H-08, §12).
#
# Uso (como root o con sudo, en el host):
#     deploy/scripts/auth-cli.sh status
#     deploy/scripts/auth-cli.sh create-admin
#     deploy/scripts/auth-cli.sh set-password --username <usuario>
#
# Ejecuta `python -m app.cli.auth <comando>` como el usuario de servicio con
# `runuser -u <usuario> --` (el usuario lo fija la autoridad
# `data-engine/app/knowledge_v3/service_state.py`; aqui no se escribe). Root NO
# puede usar la CLI directamente: abriria auth.db en WAL y crearia `-wal`/`-shm`
# como root:root, ilegibles para el servicio. El entorno sale de
# /etc/s9-knowledge/viewer.env, que lo analiza root y exporta (nunca en argv).
#
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"
[ "$(id -u)" -eq 0 ] || die "ejecute con sudo/root: este guion cambia al usuario de servicio"
[ $# -ge 1 ] || die "uso: $0 <comando> [opciones]   (status | create-admin | set-password ...)"
auth_cli "$@"

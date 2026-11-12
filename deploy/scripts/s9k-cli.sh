#!/usr/bin/env bash
# s9k-cli.sh — la forma CANONICA de ejecutar una CLI que crea o escribe estado del
# servicio (H-06 + H-08 §12; H-1 de la ronda 2). UN envoltorio para todas.
#
# Uso (como root o con sudo, en el host):
#     deploy/scripts/s9k-cli.sh auth status
#     deploy/scripts/s9k-cli.sh auth create-admin
#     deploy/scripts/s9k-cli.sh health check
#     deploy/scripts/s9k-cli.sh jobs counts
#     deploy/scripts/s9k-cli.sh glossary stats --workspace <ws>
#     deploy/scripts/s9k-cli.sh <herramienta> [argumentos]
#
# Herramientas: las de `s9k_cli_destino` (lib.sh) — una por cada CLI que llama a
# `reject_root_cli("<herramienta>")` en la autoridad
# (`data-engine/app/knowledge_v3/service_state.py`); un test cruza las dos listas.
#
# Que hace: cambia al usuario de servicio con `runuser -u <usuario> --` (lo fija la
# autoridad; aqui no se escribe), con umask 0077, desde la release activa
# (`/opt/s9-knowledge/current`), con el entorno de /etc/s9-knowledge/viewer.env (y,
# para las del motor, worker.env encima), que analiza ROOT y EXPORTA (nunca en argv).
#
# Por que: como root, esas CLIs crearian `auth.db-wal`, `health.json`, `jobs.db`,
# `glossary.db`... como root:root dentro del estado vivo, y el servicio dejaria de
# arrancar. Por eso cada una RECHAZA a root (rc 4) y muestra este comando.
#
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"
[ "$(id -u)" -eq 0 ] || die "ejecute con sudo/root: este guion cambia al usuario de servicio (runuser)"
[ $# -ge 1 ] || die "uso: $0 <herramienta> [argumentos]   (auth | health | jobs | glossary | ...)"
s9k_cli "$@"

#!/usr/bin/env bash
# Librería común para los scripts operativos de S9 Knowledge.
# Sin secretos. Solo funciones de apoyo (log, checks, ejecución idempotente).
set -euo pipefail

# Raíz del despliegue (configurable). Por defecto, la de VM105.
S9K_ROOT="${S9K_ROOT:-/opt/knowledge-services/s9-knowledge-repo}"
S9K_VIEWER_URL="${S9K_VIEWER_URL:-http://127.0.0.1:8088}"

_c_reset='\033[0m'; _c_red='\033[31m'; _c_grn='\033[32m'; _c_yel='\033[33m'

log()  { printf '%b[deploy]%b %s\n' "$_c_grn" "$_c_reset" "$*"; }
warn() { printf '%b[deploy]%b %s\n' "$_c_yel" "$_c_reset" "$*" >&2; }
err()  { printf '%b[deploy]%b %s\n' "$_c_red" "$_c_reset" "$*" >&2; }
die()  { err "$*"; exit 1; }

# Comprueba que existe un comando.
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "falta el comando: $1"; }

# Comprueba un puerto TCP escuchando localmente (ss).
port_listening() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"; }

# Devuelve el commit actual del repo (o 'unknown').
repo_commit() { git -C "$S9K_ROOT" rev-parse HEAD 2>/dev/null || echo unknown; }

#!/usr/bin/env bash
# preflight — verificación de requisitos SIN realizar cambios.
# Salida: 0 si todo apto; 1 si hay avisos; 2 si hay bloqueos.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "$HERE/lib.sh"

warns=0; blocks=0
ok()    { log "OK   $*"; }
avso()  { warn "WARN $*"; warns=$((warns+1)); }
bloq()  { err  "STOP $*"; blocks=$((blocks+1)); }

log "=== PREFLIGHT S9 Knowledge (solo lectura) ==="

# Distribución
if [ -r /etc/os-release ]; then . /etc/os-release; ok "distro: ${PRETTY_NAME:-desconocida}"; else avso "sin /etc/os-release"; fi

# Python
if command -v python3 >/dev/null 2>&1; then ok "python: $(python3 --version 2>&1)"; else bloq "python3 no encontrado"; fi

# Disco (>=2GB libres en la raíz del despliegue)
free_kb="$(df -Pk "${S9K_ROOT%/*}" 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "${free_kb:-}" ] && [ "$free_kb" -ge 2097152 ]; then ok "disco libre: $((free_kb/1024)) MB"; else avso "disco libre bajo: $(( ${free_kb:-0}/1024 )) MB"; fi

# RAM
mem_mb="$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "$mem_mb" -ge 512 ]; then ok "RAM disponible: ${mem_mb} MB"; else avso "RAM disponible baja: ${mem_mb} MB"; fi

# Puerto del visor
if port_listening 8088; then ok "puerto 8088 en uso (visor activo)"; else avso "puerto 8088 libre (visor no activo)"; fi

# Neo4j bolt local
if port_listening 7687; then ok "Neo4j bolt 7687 escuchando"; else avso "Neo4j 7687 no escuchando"; fi

# Ollama (opcional)
if [ -n "${S9K_OLLAMA_URL:-}" ]; then
  if curl -fsS --max-time 4 "${S9K_OLLAMA_URL%/}/api/tags" >/dev/null 2>&1; then ok "Ollama accesible"; else avso "Ollama no accesible"; fi
else ok "Ollama no configurado (omitido)"; fi

# Mountpoint rclone (opcional)
if [ -n "${S9K_RCLONE_MOUNT:-}" ]; then
  if mountpoint -q "${S9K_RCLONE_MOUNT}" 2>/dev/null; then ok "mountpoint rclone activo"; else avso "mountpoint rclone NO montado"; fi
fi

# Usuario y permisos del repo
if [ -d "$S9K_ROOT" ]; then ok "repo presente: $S9K_ROOT (commit $(repo_commit))"; else bloq "repo no encontrado en $S9K_ROOT"; fi
if [ -w "$S9K_ROOT" ]; then ok "permisos de escritura en el repo"; else avso "sin escritura en el repo (¿usuario correcto?)"; fi

log "=== Resumen: $warns avisos, $blocks bloqueos ==="
[ "$blocks" -gt 0 ] && exit 2
[ "$warns" -gt 0 ] && exit 1
exit 0

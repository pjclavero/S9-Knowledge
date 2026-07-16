#!/usr/bin/env bash
# preflight — verificación de requisitos SIN realizar cambios (solo lectura).
#
# Códigos de salida:
#   0 = apto para desplegar
#   1 = advertencias no bloqueantes
#   2 = bloqueo operativo (no desplegar)
#   3 = configuración inválida
#
# Uso: preflight.sh [--environment lab|production]
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/lib.sh
source "${HERE}/lib.sh"

ENVIRONMENT="${S9K_ENVIRONMENT:-lab}"
while [ $# -gt 0 ]; do
    case "$1" in
        --environment) ENVIRONMENT="$2"; shift 2 ;;
        -h|--help)
            printf 'uso: preflight.sh [--environment lab|production]\n'
            exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

warns=0
blocks=0

ok()   { log "OK   $*"; }
avso() { warn "WARN $*"; warns=$((warns + 1)); }
bloq() { err  "STOP $*"; blocks=$((blocks + 1)); }

log "=== PREFLIGHT S9 Knowledge (solo lectura) [entorno: ${ENVIRONMENT}] ==="

# ---------------------------------------------------------------------------
# 1. Distribución: Debian 13+
# ---------------------------------------------------------------------------
if [ -r /etc/os-release ]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    os_id="${ID:-unknown}"
    os_ver="${VERSION_ID:-0}"
    if [ "${os_id}" = "debian" ]; then
        if [ "${os_ver}" -ge 13 ] 2>/dev/null; then
            ok "distro: ${PRETTY_NAME:-Debian ${os_ver}}"
        else
            avso "Debian ${os_ver} detectado; se recomienda Debian 13+ (Trixie)"
        fi
    else
        avso "distro no Debian: ${PRETTY_NAME:-${os_id}} (puede funcionar, no garantizado)"
    fi
else
    avso "sin /etc/os-release — distro no verificada"
fi

# ---------------------------------------------------------------------------
# 2. Python 3.11+
# ---------------------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
    py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    py_major="$(python3 -c 'import sys; print(sys.version_info.major)')"
    py_minor="$(python3 -c 'import sys; print(sys.version_info.minor)')"
    if [ "${py_major}" -ge 3 ] && [ "${py_minor}" -ge 11 ]; then
        ok "Python ${py_ver}"
    else
        bloq "Python ${py_ver} demasiado antiguo; se requiere 3.11+"
    fi
else
    bloq "python3 no encontrado"
fi

# ---------------------------------------------------------------------------
# 3. Git
# ---------------------------------------------------------------------------
if command -v git >/dev/null 2>&1; then
    ok "git: $(git --version)"
else
    bloq "git no encontrado"
fi

# ---------------------------------------------------------------------------
# 4. Espacio libre >= 2 GB en S9K_ROOT
# ---------------------------------------------------------------------------
check_dir="${S9K_ROOT}"
if [ ! -d "${check_dir}" ]; then
    check_dir="$(dirname "${S9K_ROOT}")"
fi
if [ -d "${check_dir}" ]; then
    free_kb="$(df -Pk "${check_dir}" 2>/dev/null | awk 'NR==2{print $4}' || printf '0')"
    free_kb="${free_kb:-0}"
    if [ "${free_kb}" -ge 2097152 ]; then
        ok "espacio libre: $((free_kb / 1024)) MB en ${check_dir}"
    else
        bloq "espacio libre insuficiente: $((free_kb / 1024)) MB en ${check_dir} (mínimo 2048 MB)"
    fi
else
    avso "directorio base no existe aún: ${check_dir}"
fi

# ---------------------------------------------------------------------------
# 5. RAM disponible >= 512 MB
# ---------------------------------------------------------------------------
if [ -r /proc/meminfo ]; then
    mem_mb="$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)"
    if [ "${mem_mb:-0}" -ge 512 ]; then
        ok "RAM disponible: ${mem_mb} MB"
    else
        avso "RAM disponible baja: ${mem_mb:-0} MB (mínimo recomendado: 512 MB)"
    fi
else
    avso "no se puede leer /proc/meminfo — RAM no verificada"
fi

# ---------------------------------------------------------------------------
# 6. systemd disponible
# ---------------------------------------------------------------------------
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-system-running --quiet 2>/dev/null || \
       systemctl list-units >/dev/null 2>&1; then
        ok "systemd disponible"
    else
        avso "systemctl existe pero systemd puede no estar activo (¿contenedor?)"
    fi
else
    avso "systemctl no encontrado — systemd no disponible"
fi

# ---------------------------------------------------------------------------
# 7. Usuario (advertencia si es root)
# ---------------------------------------------------------------------------
current_user="$(id -un)"
if [ "${current_user}" = "root" ]; then
    avso "ejecutando como root — se recomienda usuario dedicado (s9k o similar)"
else
    ok "usuario: ${current_user} (no root)"
fi

# ---------------------------------------------------------------------------
# 8. S9K_ROOT existe y es accesible
# ---------------------------------------------------------------------------
if [ -d "${S9K_ROOT}" ]; then
    ok "S9K_ROOT existe: ${S9K_ROOT}"
    if [ -r "${S9K_ROOT}" ]; then
        ok "S9K_ROOT legible"
    else
        bloq "S9K_ROOT no legible: ${S9K_ROOT}"
    fi
    # Verificar estructura de releases
    if [ -d "${S9K_ROOT}/releases" ]; then
        ok "directorio releases existe: ${S9K_ROOT}/releases"
    else
        avso "directorio releases no existe aún: ${S9K_ROOT}/releases (se creará en el primer deploy)"
    fi
    # Verificar symlink current
    if [ -L "${S9K_ROOT}/current" ]; then
        current_target="$(readlink -f "${S9K_ROOT}/current" 2>/dev/null || printf 'roto')"
        if [ -d "${current_target}" ]; then
            ok "symlink current -> ${current_target}"
        else
            bloq "symlink current apunta a un destino inexistente: ${current_target}"
        fi
    else
        avso "symlink current no existe aún (primer deploy)"
    fi
else
    avso "S9K_ROOT no existe aún: ${S9K_ROOT} (se creará en el primer deploy)"
fi

# ---------------------------------------------------------------------------
# 9. /etc/s9-knowledge/ existe y tiene deploy.env
# ---------------------------------------------------------------------------
if [ -d "${S9K_CONFIG_ROOT}" ]; then
    ok "directorio de configuración: ${S9K_CONFIG_ROOT}"
    if [ -f "${S9K_CONFIG_ROOT}/deploy.env" ]; then
        ok "deploy.env presente"
    else
        if [ "${ENVIRONMENT}" = "production" ]; then
            bloq "deploy.env no encontrado en ${S9K_CONFIG_ROOT} (requerido en producción)"
        else
            avso "deploy.env no encontrado en ${S9K_CONFIG_ROOT} (requerido antes de desplegar)"
        fi
    fi
else
    if [ "${ENVIRONMENT}" = "production" ]; then
        bloq "directorio de configuración no existe: ${S9K_CONFIG_ROOT}"
    else
        avso "directorio de configuración no existe: ${S9K_CONFIG_ROOT} (lab: se puede crear)"
    fi
fi

# ---------------------------------------------------------------------------
# 10. /var/lib/s9-knowledge/ existe
# ---------------------------------------------------------------------------
if [ -d "${S9K_STATE_ROOT}" ]; then
    ok "directorio de estado: ${S9K_STATE_ROOT}"
    for subdir in auth jobs state output staging backups; do
        if [ -d "${S9K_STATE_ROOT}/${subdir}" ]; then
            ok "  ${subdir}/ presente"
        else
            avso "  ${subdir}/ no existe en ${S9K_STATE_ROOT} (se creará en el primer deploy)"
        fi
    done
else
    if [ "${ENVIRONMENT}" = "production" ]; then
        bloq "directorio de estado no existe: ${S9K_STATE_ROOT}"
    else
        avso "directorio de estado no existe: ${S9K_STATE_ROOT} (lab: se puede crear)"
    fi
fi

# ---------------------------------------------------------------------------
# 11. Neo4j bolt 7687 accesible
# ---------------------------------------------------------------------------
if port_listening 7687; then
    ok "Neo4j bolt 7687 escuchando"
else
    avso "Neo4j bolt 7687 no responde (¿servicio parado o remoto?)"
fi

# ---------------------------------------------------------------------------
# 12. Ollama (solo si S9K_OLLAMA_URL configurada)
# ---------------------------------------------------------------------------
if [ -n "${S9K_OLLAMA_URL:-}" ]; then
    if curl -fsS --max-time 4 "${S9K_OLLAMA_URL%/}/api/tags" >/dev/null 2>&1; then
        ok "Ollama accesible en ${S9K_OLLAMA_URL}"
    else
        avso "Ollama no accesible en ${S9K_OLLAMA_URL}"
    fi
else
    ok "Ollama: no configurado (S9K_OLLAMA_URL no definida — omitido)"
fi

# ---------------------------------------------------------------------------
# 13. rclone mount (solo si S9K_RCLONE_MOUNT configurada)
# ---------------------------------------------------------------------------
if [ -n "${S9K_RCLONE_MOUNT:-}" ]; then
    if mountpoint -q "${S9K_RCLONE_MOUNT}" 2>/dev/null; then
        ok "mountpoint rclone activo: ${S9K_RCLONE_MOUNT}"
    else
        avso "mountpoint rclone NO montado: ${S9K_RCLONE_MOUNT}"
    fi
else
    ok "rclone: no configurado (S9K_RCLONE_MOUNT no definida — omitido)"
fi

# ---------------------------------------------------------------------------
# 14. Backup reciente (solo si S9K_BACKUP_DIR configurada)
# ---------------------------------------------------------------------------
if [ -n "${S9K_BACKUP_DIR:-}" ]; then
    if [ -d "${S9K_BACKUP_DIR}" ]; then
        # Buscar backup de las últimas 24h
        recent="$(find "${S9K_BACKUP_DIR}" -maxdepth 1 -newer /proc/version -type f 2>/dev/null | head -1 || printf '')"
        if [ -n "${recent}" ]; then
            ok "backup reciente encontrado en ${S9K_BACKUP_DIR}"
        else
            avso "no se encontró backup reciente en ${S9K_BACKUP_DIR} (últimas 24h)"
        fi
    else
        avso "directorio de backups no existe: ${S9K_BACKUP_DIR}"
    fi
else
    ok "backup: no configurado (S9K_BACKUP_DIR no definida — omitido)"
fi

# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
log "=== Resumen preflight: ${warns} advertencias, ${blocks} bloqueos ==="
[ "${blocks}" -gt 0 ] && exit 2
[ "${warns}" -gt 0 ] && exit 1
exit 0

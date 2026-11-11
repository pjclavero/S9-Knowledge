#!/usr/bin/env bash
# 99_limpiar.sh — DESHACE todo lo que crean los guiones de laboratorio de H-06 + H-08.
#
# Lee el registro CREADO.txt (y borra ademas la lista fija conocida): unidades systemd,
# el usuario y grupo s9knowledge y el usuario de prueba, /opt/s9-knowledge, /etc/s9-knowledge,
# /var/lib/s9-knowledge, /var/backups/s9-knowledge, el clon, el venv y el bundle. NO toca ~diana,
# s9-ai-arena ni toolchain. Es DESTRUCTIVO: exige S9K_LAB_LIMPIAR=SI y la guarda completa.
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 S9K_LAB_LIMPIAR=SI deploy/tests/lab/99_limpiar.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

lab_guard
[ "${S9K_LAB_LIMPIAR:-}" = "SI" ] || lab_stop "limpieza destructiva: confirme con S9K_LAB_LIMPIAR=SI"
lab_tomar_cerrojo

lab_log "99.1 servicios y unidades"
for u in s9-knowledge-healthcheck.timer s9-knowledge-healthcheck.service s9-knowledge-viewer.service s9-knowledge-worker.service; do
    sudo systemctl disable --now "${u}" 2>/dev/null || true
done
sudo rm -f /etc/systemd/system/s9-knowledge-viewer.service* /etc/systemd/system/s9-knowledge-worker.service* \
    /etc/systemd/system/s9-knowledge-healthcheck.service* /etc/systemd/system/s9-knowledge-healthcheck.timer*
sudo rm -rf /etc/systemd/system/s9-knowledge-viewer.service.d
sudo systemctl daemon-reload
sudo systemctl reset-failed 's9-knowledge-*' 2>/dev/null || true

lab_log "99.2 estado, releases, configuracion y backups de laboratorio"
sudo rm -rf /opt/s9-knowledge /var/lib/s9-knowledge /var/backups/s9-knowledge /var/log/s9-knowledge /etc/s9-knowledge
sudo rm -rf /run/s9-knowledge-viewer /run/s9-knowledge-worker /run/s9-knowledge-healthcheck

lab_log "99.3 usuarios y grupos"
if getent passwd s9knowledge >/dev/null 2>&1; then sudo userdel s9knowledge || true; fi
if getent group s9knowledge >/dev/null 2>&1; then sudo groupdel s9knowledge || true; fi
while read -r u; do
    if getent passwd "${u}" >/dev/null 2>&1; then sudo userdel -r "${u}" || true; fi
done < <(grep -E ' usuario-prueba ' "${LAB_CREADO}" 2>/dev/null | awk '{print $NF}' | sort -u)

lab_log "99.4 clon, venv, bundle y trabajo (el registro CREADO.txt se conserva)"
rm -rf "${LAB_BASE}" "${LAB_REPO}" /srv/s9-test/h06h08.bundle /srv/s9-test/prep.log /srv/s9-test/pip.log
lab_registrar "LIMPIEZA ejecutada (99_limpiar.sh)"
lab_log "limpieza completa. Quedan: ${LAB_LOGS} (logs y CREADO.txt)"

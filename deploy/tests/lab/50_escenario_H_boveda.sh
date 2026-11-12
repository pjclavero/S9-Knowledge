#!/usr/bin/env bash
# 50_escenario_H_boveda.sh — ESCENARIO H (fase 2b §12): BOVEDA EXTERNA (EXTERNAL OPERATOR CONTENT).
#
# La boveda (S9K_VAULT_ROOT) es contenido del OPERADOR, fuera del state root. Caso 1: el sistema de
# ficheros concede a `s9knowledge` escribir el perfil -> se actualiza. Caso 2: NO lo concede
# (directorio root:root 0755 y perfil root:root 0600) -> error CONTROLADO, perfil INTACTO por
# hash/inodo/modo/propietario, sin chmod/chown de la aplicacion, sin copia bajo el state root, y el
# visor sigue ARRANCADO (la boveda opcional no impide arrancar).
#
# Pre: instalacion funcional (escenario A). Usa el escritor REAL (`h_vault_probe.py`) como el
# usuario de servicio con `runuser`.
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 deploy/tests/lab/50_escenario_H_boveda.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

STATE=/var/lib/s9-knowledge
VAULT=/srv/s9-test/h06h08-vault
WS=juego-h06h08
PY="${LAB_BASE}/venv/bin/python"

huella() { sudo sh -c "sha256sum '$1' | cut -d' ' -f1; stat -c '%i %a %U:%G' '$1'" | tr '\n' ' '; }
sonda() { sudo runuser -u s9knowledge -- "${PY}" "${HERE}/h_vault_probe.py" "${LAB_REPO}" "$1" "$2"; }
resultado_es() { [ "$(printf '%s' "$1" | "${PY}" -c 'import json,sys; print(json.load(sys.stdin)["resultado"])')" = "$2" ]; }
visor_activo() { systemctl is-active --quiet s9-knowledge-viewer.service; }
sin_copias_bajo_state() { [ -z "$(sudo find "${STATE}" -name 'perfil-operador*' 2>/dev/null)" ]; }
igual() { [ "$1" = "$2" ]; }

lab_guard
lab_tomar_cerrojo
[ -L /opt/s9-knowledge/current ] || lab_stop "no hay instalacion previa: ejecute antes el escenario A"
lab_registrar "dir ${VAULT} (boveda de laboratorio, fuera del state root)"

lab_log "H.0 fixture: boveda externa fuera del state root"
sudo rm -rf "${VAULT}"
sudo env "PYTHONPATH=${LAB_REPO}/viewer/tests" "${PY}" -c "
from pathlib import Path
from boveda_seis_a import crear_boveda_minima
crear_boveda_minima(Path('${VAULT}'), '${WS}', 'partida:alfa')"
CARPETA="$(sudo find "${VAULT}" -name perfil-operador.json -printf '%h\n' | head -1)"
[ -n "${CARPETA}" ] || lab_fail "la fixture de boveda no creo perfil-operador.json"
PERFIL="${CARPETA}/perfil-operador.json"

lab_log "H.1 CASO 1: el FS concede a s9knowledge (propietario s9knowledge)"
sudo chown -R s9knowledge:s9knowledge "${VAULT}"
ANTES="$(huella "${PERFIL}")"
R1="$(sonda "${CARPETA}" "Nombre desde H caso 1")"
lab_log "caso 1 -> ${R1}"
lab_assert "H.1 caso escribible: resultado OK" resultado_es "${R1}" OK
lab_assert "H.1 el perfil cambio (hash distinto) y contiene el nombre" bash -c "sudo grep -q 'Nombre desde H caso 1' '${PERFIL}'"
DESPUES1="$(huella "${PERFIL}")"
lab_assert "H.1 el hash cambia con la actualizacion" test "${ANTES}" != "${DESPUES1}"

lab_log "H.2 CASO 2: el FS NO concede (carpeta y perfil root:root; perfil 0600)"
sudo chown -R root:root "${VAULT}"
sudo chmod 0755 "${CARPETA}"
sudo chmod 0600 "${PERFIL}"
INTACTO="$(huella "${PERFIL}")"
MODO_CARPETA="$(sudo stat -c '%a %U:%G' "${CARPETA}")"
R2="$(sonda "${CARPETA}" "Nombre desde H caso 2")"
lab_log "caso 2 -> ${R2}"
lab_assert "H.2 caso NO escribible: error CONTROLADO (no excepcion)" resultado_es "${R2}" CONTROLADO
lab_assert "H.2 perfil INTACTO (hash, inodo, modo, propietario)" igual "$(huella "${PERFIL}")" "${INTACTO}"
lab_assert "H.2 la aplicacion no cambio el modo/propietario de la carpeta (sin chmod/chown)" igual "$(sudo stat -c '%a %U:%G' "${CARPETA}")" "${MODO_CARPETA}"
lab_assert "H.2 sin copia silenciosa bajo el state root (sin fallback)" sin_copias_bajo_state
lab_assert "H.2 sin temporales en la carpeta de la boveda" bash -c "[ -z \"\$(sudo find '${CARPETA}' -name '.*' -o -name '*.tmp')\" ]"

lab_log "H.3 el visor sigue ARRANCADO con una boveda opcional no escribible"
sudo systemctl restart s9-knowledge-viewer.service
sleep 5
lab_assert "H.3 visor activo tras reiniciar con la boveda no escribible" visor_activo
lab_assert "H.3 procesos como s9knowledge" lab_procesos_como_servicio
lab_assert "H.3 estado interno conforme" lab_estado_conforme

lab_log "ESCENARIO H: PASS"

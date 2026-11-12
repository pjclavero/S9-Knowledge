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
lab_assert "H.1 (ronda 2, H-2a) el perfil PROPIO conserva su modo y su grupo (no se endurece a 0600)" \
    igual "$(printf '%s' "${DESPUES1}" | awk '{print $3, $4}')" "$(printf '%s' "${ANTES}" | awk '{print $3, $4}')"

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

lab_log "H.2b CASO 3 (ronda 2, H-2): perfil de OTRO dueño REAL (s9test), grupo s9knowledge 0664, carpeta 2775"
TERCERO="${S9K_LAB_TERCERO:-s9test}"
getent passwd "${TERCERO}" >/dev/null || lab_stop "falta el usuario de laboratorio ${TERCERO}"
sudo chown -R "${TERCERO}:s9knowledge" "${VAULT}"
sudo find "${VAULT}" -type d -exec chmod 0755 {} +
sudo chmod 2775 "${CARPETA}"
sudo chmod 0664 "${PERFIL}"
meta() { sudo stat -c '%i %U:%G %a' "$1"; }
ANTES3="$(meta "${PERFIL}")"
HASH3="$(lab_sha256 "${PERFIL}")"
R3="$(sonda "${CARPETA}" "Nombre desde H caso 3")"
lab_log "caso 3 -> ${R3}"
lab_assert "H.2b caso 3: resultado OK (el FS concede escritura por el grupo)" resultado_es "${R3}" OK
lab_assert "H.2b caso 3: MISMO inodo, dueño (${TERCERO}), grupo y modo 0664 (no se apropia)" igual "$(meta "${PERFIL}")" "${ANTES3}"
lab_assert "H.2b caso 3: el contenido cambio y contiene el nombre" bash -c "[ \"\$(sudo sha256sum '${PERFIL}' | cut -d' ' -f1)\" != '${HASH3}' ] && sudo grep -q 'Nombre desde H caso 3' '${PERFIL}'"
lab_assert "H.2b caso 3: sin respaldo ni temporales en la carpeta" bash -c "[ -z \"\$(sudo find '${CARPETA}' -maxdepth 1 \( -name '.*s9k-respaldo' -o -name '.s9k-probe-*' \))\" ]"
lab_assert "H.2b caso 3: sin copia silenciosa bajo el state root" sin_copias_bajo_state
lab_log "H.2c CASO 3b: perfil ajeno escribible pero carpeta NO escribible (no cabe el respaldo) -> 409 sin tocar"
sudo chmod 0755 "${CARPETA}"
ANTES3B="$(meta "${PERFIL}") $(lab_sha256 "${PERFIL}")"
R3B="$(sonda "${CARPETA}" "Nombre desde H caso 3b")"
lab_log "caso 3b -> ${R3B}"
lab_assert "H.2c caso 3b: error CONTROLADO" resultado_es "${R3B}" CONTROLADO
lab_assert "H.2c caso 3b: perfil INTACTO (inodo, dueño, grupo, modo, hash)" igual "$(meta "${PERFIL}") $(lab_sha256 "${PERFIL}")" "${ANTES3B}"

lab_log "H.4 (ronda 2b, H-R2-1) caso (i): SIGKILL con el temporal del respaldo creado y sin publicar"
sonda_matar() { sudo runuser -u s9knowledge -- env "S9K_LAB_MATAR=$3" "${PY}" "${HERE}/h_vault_probe.py" "${LAB_REPO}" "$1" "$2" || true; }
sin_restos() { [ -z "$(sudo find "${CARPETA}" -maxdepth 1 \( -name '.*s9k-respaldo' -o -name '.s9k-probe-*' \))" ]; }
json_valido() { sudo "${PY}" -c "import json,sys; json.load(open(sys.argv[1]))" "${PERFIL}"; }
sudo chown -R "${TERCERO}:s9knowledge" "${VAULT}"; sudo chmod 2775 "${CARPETA}"; sudo chmod 0664 "${PERFIL}"
META4="$(meta "${PERFIL}")"; HASH4="$(lab_sha256 "${PERFIL}")"
sonda_matar "${CARPETA}" "Nombre H4" tmp_respaldo
lab_assert "H.4 tras el corte: perfil INTACTO (hash, inodo, dueño, grupo, modo)" igual "$(meta "${PERFIL}") $(lab_sha256 "${PERFIL}")" "${META4} ${HASH4}"
lab_assert "H.4 tras el corte: NO hay respaldo con el nombre definitivo" bash -c "! sudo test -e '${CARPETA}/.perfil-operador.json.s9k-respaldo'"
R4="$(sonda "${CARPETA}" "Nombre tras H4")"
lab_assert "H.4 la siguiente escritura funciona (OK)" resultado_es "${R4}" OK
lab_assert "H.4 perfil JSON valido con el nombre, mismo inodo/dueño/grupo/modo" bash -c "sudo grep -q 'Nombre tras H4' '${PERFIL}' && [ \"\$(sudo stat -c '%i %U:%G %a' '${PERFIL}')\" = '${META4}' ]"
lab_assert "H.4 sin restos (el temporal huerfano del proceso muerto se limpio)" sin_restos
lab_assert "H.4 json valido" json_valido

lab_log "H.5 (ronda 2b, H-R2-1) caso (iii): SIGKILL tras escribir y antes de borrar el respaldo + el OPERADOR edita a mano"
META5="$(meta "${PERFIL}")"
sonda_matar "${CARPETA}" "Nombre H5" escrito
lab_assert "H.5 tras el corte: respaldo publicado y perfil con lo escrito" bash -c "sudo test -s '${CARPETA}/.perfil-operador.json.s9k-respaldo' && sudo grep -q 'Nombre H5' '${PERFIL}'"
sudo runuser -u "${TERCERO}" -- "${PY}" -c "
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d.setdefault('metadata', {})['nota_del_operador'] = 'EDITADO A MANO'
with open(p, 'r+') as fh:
    fh.truncate(0); fh.write(json.dumps(d, indent=2))" "${PERFIL}"
EDITADO="$(lab_sha256 "${PERFIL}")"
R5="$(sonda "${CARPETA}" "Nombre tras H5")"
lab_log "caso (iii) -> ${R5}"
lab_assert "H.5 la siguiente escritura de S9K NO restaura a ciegas: error CONTROLADO (respaldo pendiente)" bash -c "printf '%s' '${R5}' | grep -q 'RespaldoPendienteError'"
lab_assert "H.5 la edicion del operador SE CONSERVA (mismo hash) y mismo inodo/dueño/grupo/modo" igual "$(lab_sha256 "${PERFIL}") $(meta "${PERFIL}")" "${EDITADO} ${META5}"
lab_assert "H.5 el respaldo sigue ahi para que decida el operador" sudo test -e "${CARPETA}/.perfil-operador.json.s9k-respaldo"
sudo rm -f "${CARPETA}/.perfil-operador.json.s9k-respaldo"   # el operador revisa y lo retira
R5B="$(sonda "${CARPETA}" "Nombre tras revisar")"
lab_assert "H.5 tras retirar el respaldo el operador, la escritura vuelve a funcionar y conserva su edicion" bash -c "printf '%s' '${R5B}' | grep -q OK && sudo grep -q 'EDITADO A MANO' '${PERFIL}' && sudo grep -q 'Nombre tras revisar' '${PERFIL}'"

lab_log "H.6 (ronda 2b, Y3) un efimero AJENO (del operador real) con PID muerto NO se borra"
AJENO=".s9k-probe-999999-del-operador.tmp"
sudo runuser -u "${TERCERO}" -- sh -c "echo mio > '${CARPETA}/${AJENO}'"
sudo chmod 2775 "${CARPETA}"
R6="$(sonda "${CARPETA}" "Nombre H6")"
lab_assert "H.6 la escritura funciona" bash -c "printf '%s' '${R6}' | grep -q OK"
lab_assert "H.6 el efimero del operador SIGUE ahi (la limpieza solo borra lo de s9knowledge)" sudo test -e "${CARPETA}/${AJENO}"
sudo rm -f "${CARPETA}/${AJENO}"

lab_log "H.3 el visor sigue ARRANCADO con una boveda opcional no escribible"
sudo systemctl restart s9-knowledge-viewer.service
sleep 5
lab_assert "H.3 visor activo tras reiniciar con la boveda no escribible" visor_activo
lab_assert "H.3 procesos como s9knowledge" lab_procesos_como_servicio
lab_assert "H.3 estado interno conforme" lab_estado_conforme

lab_log "ESCENARIO H: PASS"

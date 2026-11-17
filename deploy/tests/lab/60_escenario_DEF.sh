#!/usr/bin/env bash
# 60_escenario_DEF.sh — ESCENARIOS D (otro usuario), E (healthcheck) y F (CLIs como root REAL)
# de H-06 + H-08, ronda 2 (H-1 y C-6), en VM112.
#
#   D  otro usuario local REAL (s9k-otro-lab) y `nobody` (la sonda `deny` de deploy.sh) NO
#      leen el estado; la sonda SE PONE ROJA si un fichero es legible (R10, por efecto) sobre
#      una COPIA del estado. ACL real (R12): solo si hay setfacl; si no, TECHO declarado.
#   E  el healthcheck REAL (unidad, como s9knowledge) deja health.json 0600 y su componente
#      `state_validation` HEALTHY; con un drop-in que mete la excepcion de tests en el visor
#      -> `verificar_entorno_efectivo` (lib.sh, la de deploy.sh) rc!=0 y el healthcheck
#      UNHEALTHY (C-6). Se retira el drop-in y vuelve a HEALTHY.
#   F  CLIs como ROOT REAL sobre el estado VIVO (auth, health, glossary, jobs): rc 4, mensaje
#      con `s9k-cli.sh <herramienta>` y NADA nuevo de root en el estado; por el envoltorio
#      canonico (`s9k-cli.sh`) funcionan y lo que crean es s9knowledge 0700/0600 (H-1).
#
# Pre: instalacion funcional del commit a probar (escenario A).
# Uso:  S9K_LAB_CONFIRMADO=VM112 deploy/tests/lab/60_escenario_DEF.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

STATE=/var/lib/s9-knowledge
CUR=/opt/s9-knowledge/current
OTRO=s9k-otro-lab
SS="${LAB_REPO}/data-engine/app/knowledge_v3/service_state.py"
DROPIN_DIR=/etc/systemd/system/s9-knowledge-viewer.service.d
DROPIN="${DROPIN_DIR}/zz-lab-excepcion.conf"

fuera_de_contrato() {   # lo que NO es s9knowledge:s9knowledge 0700/0600 (salvo deploy/)
    sudo find "${STATE}" -path "${STATE}/deploy" -prune -o \( ! -user s9knowledge -o ! -group s9knowledge \
        -o -type f ! -perm 0600 -o -type d ! -perm 0700 \) -printf '%u:%g %m %p\n'
}
nada_fuera_de_contrato() { [ -z "$(fuera_de_contrato)" ] || { fuera_de_contrato >&2; return 1; }; }
otro_no_accede() { ! sudo -u "${OTRO}" cat "$1" >/dev/null 2>&1; }
componente() {
    sudo python3 -c "import json,sys; d=json.load(open('${STATE}/health/health.json')); print({c['component']: c['status'] for c in d['components']}.get(sys.argv[1], 'AUSENTE'))" "$1"
}
componente_es() { [ "$(componente "$1")" = "$2" ] || { echo "$1=$(componente "$1") (esperado $2)" >&2; return 1; }; }
salud() { sudo systemctl start s9-knowledge-healthcheck.service || true; }
rc_y_mensaje() {   # rc_y_mensaje <herramienta> <rc> <fichero-err>
    [ "$2" = "4" ] && grep -q "s9k-cli.sh $1" "$3"
}
root_cli() {   # root_cli <env> <dir> <comando...>: CLI como ROOT con el entorno del servicio exportado
    local env="$1" dir="$2"; shift 2
    sudo bash -c "set -a; . /etc/s9-knowledge/${env}.env; set +a; cd '${dir}'; exec \"\$@\"" _ "$@"
}

lab_guard
lab_tomar_cerrojo
[ -L "${CUR}" ] || lab_stop "no hay instalacion previa: ejecute antes el escenario A"
getent passwd "${OTRO}" >/dev/null 2>&1 || lab_stop "falta el usuario de prueba ${OTRO} (lo crea el escenario A)"
SALIDA="${LAB_LOGS}/escenario-DEF-$(lab_sha | cut -c1-12).log"
exec > >(tee "${SALIDA}") 2>&1

# --- D ---------------------------------------------------------------------------
lab_log "D.1 otro usuario REAL no lee auth.db, review.sqlite3, jobs.db ni lista el state root"
for f in "${STATE}/auth/auth.db" "${STATE}/reviews-v3/review.sqlite3" "${STATE}/jobs/jobs.db"; do
    lab_assert "D.1 ${OTRO} no lee ${f}" otro_no_accede "${f}"
done
lab_assert "D.1 ${OTRO} no lista ${STATE}" bash -c "! sudo -u ${OTRO} ls ${STATE} >/dev/null 2>&1"
lab_log "D.2 la sonda de deploy.sh (nobody) sobre el estado VIVO: verde"
RUTAS="$(sudo python3 "${SS}" paths --env-file /etc/s9-knowledge/viewer.env)"
lab_assert "D.2 deny como nobody rc=0 sobre el estado vivo" bash -c "printf '%s\n' \"${RUTAS}\" | sudo runuser -u nobody -- python3 '${SS}' deny --state-root ${STATE} --paths-stdin"
lab_log "D.3 R10 por efecto: en una COPIA con auth.db 0644 y directorios atravesables, la sonda se pone ROJA"
COPIA=/srv/s9-test/h06h08-r2/d-copia
lab_registrar "dir ${COPIA} (copia del estado para R10)"
sudo rm -rf "${COPIA}"; sudo cp -a "${STATE}" "${COPIA}"; sudo rm -rf "${COPIA}/deploy"
sudo chmod 0755 "${COPIA}" "${COPIA}/auth"; sudo chmod 0644 "${COPIA}/auth/auth.db"
set +e
printf 'auth_db=%s\n' "${COPIA}/auth/auth.db" | sudo runuser -u nobody -- python3 "${SS}" deny --state-root "${COPIA}" --paths-stdin > "${LAB_LOGS}/d3.err" 2>&1
rc=$?
set -e
lab_assert "D.3 R10 deny rc!=0 y NOMBRA el fichero legible" bash -c "[ ${rc} -ne 0 ] && grep -q '${COPIA}/auth/auth.db \[MODE\]' '${LAB_LOGS}/d3.err'"
if command -v setfacl >/dev/null 2>&1; then
    sudo chmod 0700 "${COPIA}" "${COPIA}/auth"; sudo chmod 0600 "${COPIA}/auth/auth.db"
    sudo setfacl -m "u:${OTRO}:r" "${COPIA}/auth/auth.db"
    lab_assert "D.4 R12 una ACL real en un 0600 es un hallazgo" bash -c "sudo python3 '${SS}' check --state-root '${COPIA}' 2>&1 | grep -q '\[ACL\]'"
else
    lab_log "D.4 R12 TECHO DECLARADO: setfacl no esta instalado en VM112 (no se instalan paquetes); la deteccion de ACL se atestigua en CI simulando el xattr"
fi
sudo rm -rf "${COPIA}"

# --- E ---------------------------------------------------------------------------
lab_log "E.1 healthcheck REAL como s9knowledge"
salud
lab_assert "E.1 health.json s9knowledge 0600" bash -c "[ \"\$(sudo stat -c '%U:%G %a' ${STATE}/health/health.json)\" = 's9knowledge:s9knowledge 600' ]"
lab_assert "E.1 state_validation HEALTHY (sin excepcion de tests en el entorno efectivo)" componente_es state_validation HEALTHY
lab_log "E.2 C-6: drop-in con la excepcion de tests en el visor"
lab_registrar "dropin ${DROPIN} (C-6, se retira en el propio escenario)"
sudo install -d -m 0755 "${DROPIN_DIR}"
printf '[Service]\nEnvironment=S9K_STATE_VALIDATION=disabled-explicit-for-tests\n' | sudo tee "${DROPIN}" >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart s9-knowledge-viewer.service
sleep 4
lab_assert "E.2 la funcion de deploy.sh (verificar_entorno_efectivo) PARA (rc!=0)" bash -c "! sudo bash -c 'source ${LAB_REPO}/deploy/scripts/lib.sh; verificar_entorno_efectivo s9-knowledge-viewer.service'"
salud
lab_assert "E.2 el healthcheck REAL reporta state_validation UNHEALTHY" componente_es state_validation UNHEALTHY
sudo rm -f "${DROPIN}"; sudo rmdir "${DROPIN_DIR}" 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl restart s9-knowledge-viewer.service
sleep 4
salud
lab_assert "E.3 sin el drop-in vuelve a HEALTHY" componente_es state_validation HEALTHY
lab_assert "E.3 verificar_entorno_efectivo rc=0" sudo bash -c "source ${LAB_REPO}/deploy/scripts/lib.sh; verificar_entorno_efectivo s9-knowledge-viewer.service s9-knowledge-worker.service s9-knowledge-healthcheck.service"

# --- F ---------------------------------------------------------------------------
lab_log "F.0 estado vivo de partida: conforme"
lab_assert "F.0 nada fuera de contrato" nada_fuera_de_contrato
VPY="${CUR}/viewer/.venv/bin/python"
WPY="${CUR}/data-engine/.venv/bin/python"
sudo rm -f "${STATE}/health/health.json"
f_root() {   # f_root <herramienta> <env> <dir> <cmd...>
    local h="$1"; shift
    set +e; root_cli "$@" > "${LAB_LOGS}/f-${h}.err" 2>&1; local rc=$?; set -e
    lab_log "F root ${h}: rc=${rc} :: $(head -c 160 "${LAB_LOGS}/f-${h}.err" | tr '\n' '|')"
    lab_assert "F ${h} como ROOT: rc 4 y comando canonico s9k-cli.sh ${h}" rc_y_mensaje "${h}" "${rc}" "${LAB_LOGS}/f-${h}.err"
    lab_assert "F ${h} como ROOT: NADA de root ni fuera de modo en el estado" nada_fuera_de_contrato
}
f_root auth viewer "${CUR}/viewer" "${VPY}" -m app.cli.auth status
f_root health viewer "${CUR}/viewer" "${VPY}" -m app.cli.health check
lab_assert "F health como ROOT no creo health.json" bash -c "! sudo test -e ${STATE}/health/health.json"
f_root glossary worker "${CUR}/data-engine" "${WPY}" app/glossary/glossary_cli.py stats --workspace leyenda
lab_assert "F glossary como ROOT no creo glossary/" bash -c "! sudo test -e ${STATE}/glossary"
f_root jobs worker "${CUR}/data-engine" "${WPY}" app/cli/jobs.py counts
lab_log "F.2 por el envoltorio CANONICO (root -> runuser, umask 0077)"
lab_assert "F.2 s9k-cli.sh health check (rc 0/1/2)" bash -c "sudo '${CUR}/deploy/scripts/s9k-cli.sh' health check >/dev/null 2>&1; [ \$? -le 2 ]"
lab_assert "F.2 health.json creado por s9knowledge 0600" bash -c "[ \"\$(sudo stat -c '%U:%G %a' ${STATE}/health/health.json)\" = 's9knowledge:s9knowledge 600' ]"
lab_assert "F.2 s9k-cli.sh glossary stats" sudo "${CUR}/deploy/scripts/s9k-cli.sh" glossary stats --workspace leyenda
lab_assert "F.2 glossary/ 0700 y glossary.db 0600 de s9knowledge" bash -c "[ \"\$(sudo stat -c '%U:%G %a' ${STATE}/glossary ${STATE}/glossary/glossary.db | tr '\n' ' ')\" = 's9knowledge:s9knowledge 700 s9knowledge:s9knowledge 600 ' ]"
lab_assert "F.2 s9k-cli.sh jobs counts" sudo "${CUR}/deploy/scripts/s9k-cli.sh" jobs counts
lab_assert "F.2 s9k-cli.sh auth status" sudo "${CUR}/deploy/scripts/s9k-cli.sh" auth status
lab_assert "F.2 tras las CLIs canonicas, NADA fuera de contrato (find ! -user s9knowledge vacio salvo deploy/)" nada_fuera_de_contrato
lab_assert "F.2 el estado sigue conforme (la comprobacion de arranque)" lab_estado_conforme
lab_assert "F.2 visor y worker siguen activos" bash -c "systemctl is-active --quiet s9-knowledge-viewer.service && systemctl is-active --quiet s9-knowledge-worker.service"

lab_log "ESCENARIOS D/E/F: PASS (log en ${SALIDA})"

#!/usr/bin/env bash
# 20_escenario_A_fresh.sh — ESCENARIO A del contrato (§19): FRESH en VM112.
#
# instalar -> usuario existe -> viewer/worker como s9knowledge -> state 0700 ->
# ficheros 0600 -> health verde -> flujo minimo de auth -> decision/revision si aplica.
#
# Pre: maquina SIN instalacion previa de S9 Knowledge (si hay una, PARA; use una
# restauracion del snapshot base-limpia de VM112). Cubre P1 P2 P3 P4 P5 P6 P7 P8 P11
# y N10 N15 N16.
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 deploy/tests/lab/20_escenario_A_fresh.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

STATE=/var/lib/s9-knowledge

# --- comprobaciones (funciones: sin trampas de comillas) -----------------------
usuario_de_sistema_sin_login() {
    local linea uid shell
    linea="$(getent passwd s9knowledge)" || return 1
    uid="$(cut -d: -f3 <<<"${linea}")"; shell="$(cut -d: -f7 <<<"${linea}")"
    [ "${uid}" -lt 1000 ] || return 1
    case "${shell}" in */nologin|*/false) return 0 ;; *) return 1 ;; esac
}
sin_grupos_de_privilegio() {
    ! id -nG s9knowledge | tr ' ' '\n' | grep -Eq '^(sudo|wheel|adm|root|docker)$'
}
servicios_activos() {
    systemctl is-active --quiet s9-knowledge-viewer.service && systemctl is-active --quiet s9-knowledge-worker.service
}
owner_modo_es() { [ "$(sudo stat -c '%U:%G %a' "$1")" = "$2" ]; }
sin_desviaciones_de_modo() {
    [ -z "$(sudo find "${STATE}" -path "${STATE}/deploy" -prune -o \( -type f ! -perm 0600 -o -type d ! -perm 0700 \) -print)" ]
}
nada_de_root_en_el_estado() {
    [ -z "$(sudo find "${STATE}" -path "${STATE}/deploy" -prune -o -user root -print)" ]
}
nobody_no_accede() { ! sudo -u nobody cat "$1" >/dev/null 2>&1; }
nobody_no_lista() { ! sudo -u nobody ls "$1" >/dev/null 2>&1; }
cli_como_root_rechazada() {
    ! sudo env S9K_AUTH_DB_PATH="${STATE}/auth/auth.db" \
        /opt/s9-knowledge/current/viewer/.venv/bin/python -m app.cli.auth status >/dev/null 2>&1
}
healthcheck_sin_error_de_config() {
    local rc
    rc="$(systemctl show -p ExecMainStatus --value s9-knowledge-healthcheck.service)"
    [ "${rc}" = "0" ] || [ "${rc}" = "1" ]
}

lab_guard
lab_tomar_cerrojo
[ -d "${LAB_REPO}/.git" ] || lab_stop "no hay clon: ejecute antes 00_preparar.sh"
if [ -e /opt/s9-knowledge/current ] || getent passwd s9knowledge >/dev/null 2>&1; then
    lab_stop "ya hay una instalacion o el usuario s9knowledge existe: el escenario A parte de una maquina limpia (restaure el snapshot)"
fi
SHA="$(lab_sha)"
SALIDA="${LAB_LOGS}/escenario-A-${SHA:0:12}.log"

lab_log "A.0 estado previo: sin usuario, sin /opt/s9-knowledge"
# Raices que en una instalacion real deja Ansible (rol common). El state root lo crea,
# 0700 y de s9knowledge, el paso 5b de deploy.sh.
sudo install -d -m 0755 /opt/s9-knowledge /opt/s9-knowledge/releases
lab_configurar "${SHA}"

lab_log "A.1 deploy.sh --mode fresh (el usuario se crea en el paso 3b)"
lab_deploy fresh 2>&1 | tee "${SALIDA}"

lab_assert "A.1 el usuario s9knowledge existe, es de sistema y no tiene login" usuario_de_sistema_sin_login
lab_assert "A.1 s9knowledge no pertenece a grupos de privilegio" sin_grupos_de_privilegio
lab_assert "A.2 visor y worker activos" servicios_activos
lab_assert "A.2 P1/P2 los procesos VIVOS corren como s9knowledge" lab_procesos_como_servicio
lab_assert "A.3 P3/P4 el state root es s9knowledge:s9knowledge 0700" owner_modo_es "${STATE}" "s9knowledge:s9knowledge 700"
lab_assert "A.4 P3 auth.db existe, 0600 y de s9knowledge" owner_modo_es "${STATE}/auth/auth.db" "s9knowledge:s9knowledge 600"
lab_assert "A.4 P4 review.sqlite3 existe, 0600 y de s9knowledge" owner_modo_es "${STATE}/reviews-v3/review.sqlite3" "s9knowledge:s9knowledge 600"
lab_assert "A.4 TODO el estado cumple el contrato (la comprobacion de arranque)" lab_estado_conforme
lab_assert "A.4 ningun fichero fuera de 0600 ni directorio fuera de 0700" sin_desviaciones_de_modo

# P6: la salud como s9knowledge (el servicio de salud, no una ejecucion como root)
lab_log "A.5 P6 healthcheck como s9knowledge"
sudo cp "${LAB_REPO}/viewer/systemd/s9-knowledge-healthcheck.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start s9-knowledge-healthcheck.service || true   # SuccessExitStatus=0 1
lab_assert "A.5 el healthcheck dejo health.json 0600 de s9knowledge" owner_modo_es "${STATE}/health/health.json" "s9knowledge:s9knowledge 600"
lab_assert "A.5 el healthcheck no devolvio 2 (unhealthy) ni 3 (config)" healthcheck_sin_error_de_config

# P7: el visor crea una sesion / autentica. Primer admin por la CLI canonica (como s9knowledge).
lab_log "A.6 P7 flujo minimo de auth: admin por la CLI CANONICA"
ADMIN_PW="$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-20)Aa1_"
printf 'labadmin\nLab Admin\n%s\n%s\n' "${ADMIN_PW}" "${ADMIN_PW}" \
    | sudo "${LAB_REPO}/deploy/scripts/auth-cli.sh" create-admin >/dev/null
lab_assert "A.6 N10 la CLI ejecutada como root se RECHAZA" cli_como_root_rechazada
lab_assert "A.6 N10 no se creo nada como root en el estado" nada_de_root_en_el_estado
lab_assert "A.6 sigue todo conforme tras crear el admin (auth.db-wal/-shm incluidos)" lab_estado_conforme

lab_log "A.7 P11 restart conserva owner y modos"
sudo systemctl restart s9-knowledge-viewer.service s9-knowledge-worker.service
sleep 5
lab_assert "A.7 tras reiniciar, visor y worker activos" servicios_activos
lab_assert "A.7 procesos vivos como s9knowledge" lab_procesos_como_servicio
lab_assert "A.7 estado conforme" lab_estado_conforme

lab_log "A.8 N15/N16 otro usuario local NO lee auth.db ni review.sqlite3"
lab_assert "A.8 nobody no lee auth.db" nobody_no_accede "${STATE}/auth/auth.db"
lab_assert "A.8 nobody no lee review.sqlite3" nobody_no_accede "${STATE}/reviews-v3/review.sqlite3"
lab_assert "A.8 nobody no lista el state root" nobody_no_lista "${STATE}"

lab_log "ESCENARIO A: PASS (log en ${SALIDA}). Para el B continue con este estado o restaure el snapshot."

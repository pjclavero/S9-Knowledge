#!/usr/bin/env bash
# 40_escenario_C_negativo.sh — ESCENARIO C del contrato (§19): NEGATIVO.
#
# Fuerza el fallo de chown/chmod, de la copia/movimiento y del retiro del original y
# comprueba, en cada caso: deploy.sh PARA con rc != 0 -> SIN exito falso (ni
# «DEPLOY terminado» ni release activada) -> estado anterior PRESERVADO (SHA-256 de
# cada original) -> tras corregir la causa, el MISMO despliegue converge (idempotente).
#
#   C1 chown/chmod imposible : bind mount de SOLO LECTURA sobre `reviews-v3/proposals`
#                              (EROFS en chmod/chown, funciona en cualquier FS)
#   C2 movimiento imposible  : un FICHERO donde el destino necesita un DIRECTORIO
#                              (`glossary-candidates`)  -> TIPO / MOVIMIENTO_PARCIAL
#   C3 retiro del original   : `chattr +i` sobre decisions.jsonl de la release (el
#                              rename del original falla tras copiar y verificar)
#   C4 conflicto de estado   : decisions.jsonl distinto en release y en state root
#   --- ronda 2 ---
#   C5 (C-1) <state>/backups con contenido      -> STOP en 2b, ANTES de parar nada
#   C6 (C-1) S9K_BACKUP_ROOT dentro del state   -> STOP en 2b
#   C7 (C-5) entrada AJENA en el state root     -> STOP en 2b
#   C8 (C-2) symlink legacy                     -> STOP en 5b SIN mover el primer fichero
#   C9 (C-3) estado legacy en DOS sitios (distinto) -> STOP en 5b sin mover nada
#   C10 (C-4) rollback automatico a una release con unidades ANTERIORES a H-06 -> NO se
#        reactiva; visor y worker PARADOS; «rollback NO ejecutado»
#
# Pre: instalacion funcional del commit nuevo (escenario A). Cada caso reconstruye la
# fixture LEGACY con `lab_convertir_en_legacy`. Cubre N5 N6 N11 N12 N13(parcial).
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 [S9K_LAB_BASE_SHA=4916e90] deploy/tests/lab/40_escenario_C_negativo.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

STATE=/var/lib/s9-knowledge

# --- comprobaciones ------------------------------------------------------------
sha_es()  { [ "$(lab_sha256 "$1")" = "$2" ]; }
sin_exito_falso() { ! grep -q 'DEPLOY terminado' "$1"; }
release_sin_cambiar() { [ "$(readlink -f /opt/s9-knowledge/current)" = "$1" ]; }
servicios_parados() {
    ! systemctl is-active --quiet s9-knowledge-viewer.service && ! systemctl is-active --quiet s9-knowledge-worker.service
}
# El original esta INTACTO donde estaba, o -si la migracion llego a copiarlo y
# verificarlo antes de fallar mas tarde- renombrado a `.migrado-*` con el MISMO
# contenido y con su copia verificada bajo el state root. Nunca perdido.
original_conservado() {
    local sha="$1" f
    if [ -e "${RV3_REL}/decisions.jsonl" ]; then
        [ "$(lab_sha256 "${RV3_REL}/decisions.jsonl")" = "${sha}" ]
        return
    fi
    for f in "${RV3_REL}"/decisions.jsonl.migrado-*; do
        [ -e "${f}" ] || return 1
        [ "$(lab_sha256 "${f}")" = "${sha}" ] || return 1
        [ "$(lab_sha256 "${STATE}/reviews-v3/decisions.jsonl")" = "${sha}" ] || return 1
    done
}

# caso <nombre> <preparar> <deshacer> <fichero a conservar> : ejecuta el ciclo completo.
caso() {
    local nombre="$1" preparar="$2" deshacer="$3" sha_dec actual salida rc
    salida="${LAB_LOGS}/escenario-C-${nombre}-$(lab_sha | cut -c1-12).log"
    lab_log "=== caso ${nombre}: fixture legacy + fallo forzado (${preparar})"
    lab_convertir_en_legacy "${BASE_SHA}"
    sha_dec="$(lab_sha256 "${RV3_REL}/decisions.jsonl")"
    actual="$(readlink -f /opt/s9-knowledge/current)"
    "${preparar}"

    set +e
    lab_deploy upgrade > "${salida}" 2>&1
    rc=$?
    set -e
    lab_log "${nombre}: deploy.sh rc=${rc} (esperado != 0)"
    lab_assert "${nombre}: deploy.sh PARO (rc != 0)" test "${rc}" -ne 0
    lab_assert "${nombre}: SIN exito falso (no hay 'DEPLOY terminado')" sin_exito_falso "${salida}"
    lab_assert "${nombre}: la release NO se activo" release_sin_cambiar "${actual}"
    lab_assert "${nombre}: visor y worker siguen PARADOS (no se relanzan a ciegas)" servicios_parados
    lab_assert "${nombre}: el original de decisions.jsonl se conserva (intacto o retirado SOLO tras verificar su copia)" original_conservado "${sha_dec}"
    lab_assert "${nombre}: el diagnostico nombra la causa (STOP[...])" grep -Eq 'STOP\[[A-Z_]+\]' "${salida}"

    "${deshacer}"
    lab_log "${nombre}: causa corregida; el MISMO despliegue tiene que converger"
    lab_deploy upgrade 2>&1 | tee -a "${salida}"
    lab_assert "${nombre}: tras corregir, el estado es conforme" lab_estado_conforme
    lab_assert "${nombre}: procesos vivos como s9knowledge" lab_procesos_como_servicio
    lab_assert "${nombre}: decisions.jsonl preservado bajo el state root" sha_es "${STATE}/reviews-v3/decisions.jsonl" "${sha_dec}"
}

# C1 ---------------------------------------------------------------------------
c1_preparar() {
    sudo mount --bind "${STATE}/reviews-v3/proposals" "${STATE}/reviews-v3/proposals"
    sudo mount -o remount,bind,ro "${STATE}/reviews-v3/proposals"
}
c1_deshacer() { sudo umount "${STATE}/reviews-v3/proposals"; }

# C2 ---------------------------------------------------------------------------
c2_preparar() {
    sudo rm -rf "${STATE}/reviews-v3/glossary-candidates"
    printf 'estorbo' | sudo tee "${STATE}/reviews-v3/glossary-candidates" >/dev/null
}
c2_deshacer() { sudo rm -f "${STATE}/reviews-v3/glossary-candidates"; }

# C3 ---------------------------------------------------------------------------
c3_preparar() { sudo chattr +i "${RV3_REL}/decisions.jsonl"; }
c3_deshacer() { sudo chattr -i "${RV3_REL}/decisions.jsonl"; }

# C4 ---------------------------------------------------------------------------
c4_preparar() { printf 'OTRO CONTENIDO\n' | sudo tee "${STATE}/reviews-v3/decisions.jsonl" >/dev/null; }
c4_deshacer() {
    # El operador decide: aqui se descarta el destino divergente para que el original gane.
    sudo rm -f "${STATE}/reviews-v3/decisions.jsonl"
}

# =============================================================================
# RONDA 2 (C-1, C-2, C-3, C-4, C-5)
# =============================================================================
# Precondiciones del DISCO (2b): el despliegue PARA ANTES de parar nada (no llega al
# paso 3b) y sin tocar el estado.
foto_estado() { sudo find "${STATE}" -path "${STATE}/deploy" -prune -o -printf '%p %m %u:%g %s\n' | sort | sha256sum; }
no_paro_nada() { ! grep -q -- '--- 3b\.' "$1"; }
caso_pre() {   # caso_pre <nombre> <preparar> <deshacer> <patron del STOP>
    local nombre="$1" preparar="$2" deshacer="$3" patron="$4" salida rc antes actual
    salida="${LAB_LOGS}/escenario-C-${nombre}-$(lab_sha | cut -c1-12).log"
    lab_log "=== caso ${nombre}: fixture legacy + precondicion del disco rota (${preparar})"
    lab_convertir_en_legacy "${BASE_SHA}"
    actual="$(readlink -f /opt/s9-knowledge/current)"
    "${preparar}"
    antes="$(foto_estado)"
    set +e
    lab_deploy upgrade > "${salida}" 2>&1
    rc=$?
    set -e
    lab_log "${nombre}: deploy.sh rc=${rc} (esperado != 0)"
    lab_assert "${nombre}: deploy.sh PARO (rc != 0)" test "${rc}" -ne 0
    lab_assert "${nombre}: SIN exito falso" sin_exito_falso "${salida}"
    lab_assert "${nombre}: la release NO se activo" release_sin_cambiar "${actual}"
    lab_assert "${nombre}: PARO en 2b, ANTES de parar servicios (no llego al paso 3b)" no_paro_nada "${salida}"
    lab_assert "${nombre}: el estado NO se toco (misma foto de rutas/modos/dueños/tamaños)" test "$(foto_estado)" = "${antes}"
    lab_assert "${nombre}: el diagnostico nombra la causa (${patron})" grep -Eq "${patron}" "${salida}"
    "${deshacer}"
    lab_log "${nombre}: causa corregida; el MISMO despliegue tiene que converger"
    lab_deploy upgrade 2>&1 | tee -a "${salida}"
    lab_assert "${nombre}: tras corregir, el estado es conforme" lab_estado_conforme
    lab_assert "${nombre}: procesos vivos como s9knowledge" lab_procesos_como_servicio
}

# C5 · C-1: <state>/backups con contenido
c5_preparar() { sudo install -d -m 0755 "${STATE}/backups"; printf 'copia' | sudo tee "${STATE}/backups/copia-lab.tar" >/dev/null; }
c5_deshacer() { sudo rm -rf "${STATE}/backups"; }
# C6 · C-1: S9K_BACKUP_ROOT (el alias que no se validaba) dentro del state root
c6_preparar() { printf 'S9K_BACKUP_ROOT=%s/copias\n' "${STATE}" | sudo tee -a /etc/s9-knowledge/viewer.env >/dev/null; }
c6_deshacer() { sudo sed -i '/^S9K_BACKUP_ROOT=/d' /etc/s9-knowledge/viewer.env; }
# C7 · C-5: entrada de primer nivel AJENA en el state root
c7_preparar() { sudo install -d -m 0755 "${STATE}/otra-aplicacion"; }
c7_deshacer() { sudo rmdir "${STATE}/otra-aplicacion"; }

# C8 · C-2: un symlink legacy -> STOP en 5b SIN haber movido el primer fichero
nada_movido() {
    [ -f "${RV3_REL}/decisions.jsonl" ] && [ -z "$(sudo find "${RV3_REL}" -maxdepth 1 -name '*.migrado-*' -print)" ]
}
c8_preparar() { sudo rm -f "${RV3_REL}/audit.jsonl"; sudo ln -s /etc/hostname "${RV3_REL}/audit.jsonl"; }
c8_deshacer() { sudo rm -f "${RV3_REL}/audit.jsonl"; printf '{"event":"STALE_REVIEW","n":1}\n' | sudo tee "${RV3_REL}/audit.jsonl" >/dev/null; }
# C9 · C-3: el mismo estado legacy en DOS sitios con contenido distinto -> STOP
LEGACY_LAB=/opt/knowledge-services/s9-knowledge-repo
c9_preparar() {
    [ -e /opt/knowledge-services ] && lab_stop "ya existe /opt/knowledge-services: este caso no lo toca"
    lab_registrar "dir /opt/knowledge-services (arbol legacy de laboratorio, caso C9; se retira en el caso)"
    sudo install -d -m 0755 "${LEGACY_LAB}/viewer/output/reviews-v3"
    printf '{"decision_id":"legacy:OTRA"}\n' | sudo tee "${LEGACY_LAB}/viewer/output/reviews-v3/decisions.jsonl" >/dev/null
}
c9_deshacer() { sudo rm -rf /opt/knowledge-services; }
caso_5b_sin_mover() {   # como `caso`, y ademas: nada se movio
    local nombre="$1" preparar="$2" deshacer="$3" patron="$4" salida rc actual
    salida="${LAB_LOGS}/escenario-C-${nombre}-$(lab_sha | cut -c1-12).log"
    lab_log "=== caso ${nombre}: fixture legacy + ${preparar}"
    lab_convertir_en_legacy "${BASE_SHA}"
    actual="$(readlink -f /opt/s9-knowledge/current)"
    "${preparar}"
    set +e
    lab_deploy upgrade > "${salida}" 2>&1
    rc=$?
    set -e
    lab_assert "${nombre}: deploy.sh PARO (rc != 0)" test "${rc}" -ne 0
    lab_assert "${nombre}: SIN exito falso" sin_exito_falso "${salida}"
    lab_assert "${nombre}: la release NO se activo" release_sin_cambiar "${actual}"
    lab_assert "${nombre}: visor y worker PARADOS (no se relanzan a ciegas)" servicios_parados
    lab_assert "${nombre}: NADA se movio (pre-escaneo antes del primer fichero)" nada_movido
    lab_assert "${nombre}: el diagnostico nombra la causa (${patron})" grep -Eq "${patron}" "${salida}"
    "${deshacer}"
    lab_deploy upgrade 2>&1 | tee -a "${salida}"
    lab_assert "${nombre}: tras corregir, el estado es conforme" lab_estado_conforme
    lab_assert "${nombre}: procesos vivos como s9knowledge" lab_procesos_como_servicio
}

# C10 · C-4: el rollback AUTOMATICO no reactiva una release anterior a H-06
WORKER_DROPIN_DIR=/etc/systemd/system/s9-knowledge-worker.service.d
c10_caso() {
    local nombre=C10-rollback-a-release-pre-h06 salida rc previa
    salida="${LAB_LOGS}/escenario-C-${nombre}-$(lab_sha | cut -c1-12).log"
    lab_log "=== caso ${nombre}: release activa con unidades ANTERIORES a H-06 + fallo forzado tras activar"
    previa="/opt/s9-knowledge/releases/zz-lab-pre-h06-$(date -u +%H%M%S)"
    lab_registrar "release ${previa} (copia con las unidades de ${BASE_SHA}, caso C10)"
    sudo cp -a "$(readlink -f /opt/s9-knowledge/current)" "${previa}"
    sudo git -C "${LAB_REPO}" show "${BASE_SHA}:viewer/systemd/s9-knowledge-viewer.service" | sudo tee "${previa}/viewer/systemd/s9-knowledge-viewer.service" >/dev/null
    sudo git -C "${LAB_REPO}" show "${BASE_SHA}:data-engine/systemd/s9-knowledge-worker.service" | sudo tee "${previa}/data-engine/systemd/s9-knowledge-worker.service" >/dev/null
    sudo ln -sfn "${previa}" /opt/s9-knowledge/current
    lab_registrar "dropin ${WORKER_DROPIN_DIR}/zz-lab-fallo.conf (caso C10; se retira en el caso)"
    sudo install -d -m 0755 "${WORKER_DROPIN_DIR}"
    # el worker ARRANCA (el paso 13 no falla) y muere a los 2 s: lo detectan 14a/14b, que
    # disparan el rollback automatico (la puerta de C-4).
    printf '[Service]\nExecStart=\nExecStart=/bin/sh -c "sleep 2; exit 1"\n' | sudo tee "${WORKER_DROPIN_DIR}/zz-lab-fallo.conf" >/dev/null
    sudo systemctl daemon-reload
    set +e
    lab_deploy upgrade > "${salida}" 2>&1
    rc=$?
    set -e
    lab_assert "${nombre}: deploy.sh PARO (rc != 0)" test "${rc}" -ne 0
    lab_assert "${nombre}: SIN exito falso" sin_exito_falso "${salida}"
    lab_assert "${nombre}: el die dice «rollback NO ejecutado» (nunca «rollback ejecutado»)" grep -q 'rollback NO ejecutado' "${salida}"
    lab_assert "${nombre}: la release previa (pre-H06) NO se reactivo" bash -c "[ \"\$(readlink -f /opt/s9-knowledge/current)\" != '${previa}' ]"
    lab_assert "${nombre}: visor y worker PARADOS con el diagnostico" servicios_parados
    sudo rm -f "${WORKER_DROPIN_DIR}/zz-lab-fallo.conf"; sudo rmdir "${WORKER_DROPIN_DIR}" 2>/dev/null || true
    sudo systemctl daemon-reload
    lab_deploy upgrade 2>&1 | tee -a "${salida}"
    lab_assert "${nombre}: tras retirar el fallo, converge (estado conforme)" lab_estado_conforme
    lab_assert "${nombre}: procesos vivos como s9knowledge" lab_procesos_como_servicio
    sudo rm -rf "${previa}"
}

# C11 · C-5 ronda 2b (POSITIVO): `lost+found` de un FS dedicado (root:root 0700) en el state
# root NO para el despliegue ni se toca; un `lost+found` con otro modo SI para (ajeno).
c11_caso() {
    local salida="${LAB_LOGS}/escenario-C-C11-lost-found-$(lab_sha | cut -c1-12).log" rc
    lab_log "=== caso C11-lost-found: lost+found root:root 0700 en el state root"
    lab_registrar "dir ${STATE}/lost+found (caso C11; se retira en el caso)"
    sudo install -d -m 0700 -o root -g root "${STATE}/lost+found"
    printf 'bloque' | sudo tee "${STATE}/lost+found/#123" >/dev/null
    lab_deploy upgrade > "${salida}" 2>&1 || true
    lab_assert "C11: el despliegue TERMINA con lost+found root 0700 presente" grep -q 'DEPLOY terminado' "${salida}"
    lab_assert "C11: lost+found intacto (root:root 0700)" bash -c "[ \"\$(sudo stat -c '%U:%G %a' '${STATE}/lost+found')\" = 'root:root 700' ]"
    lab_assert "C11: estado conforme (el arranque ignora lost+found)" lab_estado_conforme
    lab_assert "C11: procesos vivos como s9knowledge" lab_procesos_como_servicio
    sudo chmod 0755 "${STATE}/lost+found"
    set +e; lab_deploy upgrade >> "${salida}" 2>&1; rc=$?; set -e
    lab_assert "C11: un lost+found 0755 (no el del FS) SI para en 2b (AJENAS)" bash -c "[ ${rc} -ne 0 ] && grep -q 'AJENAS' '${salida}'"
    sudo rm -rf "${STATE}/lost+found"
    lab_deploy upgrade >> "${salida}" 2>&1
    lab_assert "C11: sin lost+found vuelve a converger" lab_estado_conforme
}

lab_guard
lab_tomar_cerrojo
BASE_SHA="${S9K_LAB_BASE_SHA:-4916e90}"
[ -L /opt/s9-knowledge/current ] || lab_stop "no hay instalacion previa: ejecute antes el escenario A"
git -C "${LAB_REPO}" cat-file -e "${BASE_SHA}^{commit}" || lab_stop "el commit base ${BASE_SHA} no esta en el clon"
command -v chattr >/dev/null 2>&1 || lab_stop "falta chattr (e2fsprogs): el caso C3 necesita un atributo inmutable"
RV3_REL=""   # lo fija lab_convertir_en_legacy

if [ "${S9K_LAB_C_SOLO_LF:-}" = "1" ]; then
    c11_caso
    lab_log "ESCENARIO C (solo C11): PASS"
    exit 0
fi
# S9K_LAB_C_SOLO_R2=1 salta C1-C4 (ya PASS en la ronda 1 y repetidos aparte) y corre solo los de la ronda 2.
if [ "${S9K_LAB_C_SOLO_R2:-}" != "1" ]; then
    caso C1-chown-chmod-imposible c1_preparar c1_deshacer
    caso C2-movimiento-imposible  c2_preparar c2_deshacer
    caso C3-retiro-del-original   c3_preparar c3_deshacer
    caso C4-conflicto-de-estado   c4_preparar c4_deshacer
fi
# ronda 2
caso_pre C5-backups-en-el-state       c5_preparar c5_deshacer 'backups viven FUERA'
caso_pre C6-backup-root-en-el-state   c6_preparar c6_deshacer 'S9K_BACKUP_ROOT=.*DENTRO'
caso_pre C7-state-root-no-dedicado    c7_preparar c7_deshacer 'AJENAS'
caso_5b_sin_mover C8-symlink-legacy   c8_preparar c8_deshacer 'STOP\[SYMLINK\]'
caso_5b_sin_mover C9-legacy-duplicado c9_preparar c9_deshacer 'STOP\[ESTADO_LEGACY_DUPLICADO\]'
c10_caso
c11_caso

lab_log "ESCENARIO C: PASS (logs en ${LAB_LOGS}/escenario-C-*)"

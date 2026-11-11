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

lab_guard
lab_tomar_cerrojo
BASE_SHA="${S9K_LAB_BASE_SHA:-4916e90}"
[ -L /opt/s9-knowledge/current ] || lab_stop "no hay instalacion previa: ejecute antes el escenario A"
git -C "${LAB_REPO}" cat-file -e "${BASE_SHA}^{commit}" || lab_stop "el commit base ${BASE_SHA} no esta en el clon"
command -v chattr >/dev/null 2>&1 || lab_stop "falta chattr (e2fsprogs): el caso C3 necesita un atributo inmutable"
RV3_REL=""   # lo fija lab_convertir_en_legacy

caso C1-chown-chmod-imposible c1_preparar c1_deshacer
caso C2-movimiento-imposible  c2_preparar c2_deshacer
caso C3-retiro-del-original   c3_preparar c3_deshacer
caso C4-conflicto-de-estado   c4_preparar c4_deshacer

lab_log "ESCENARIO C: PASS (logs en ${LAB_LOGS}/escenario-C-*)"

#!/usr/bin/env bash
# 30_escenario_B_upgrade_legacy.sh — ESCENARIO B del contrato (§19): UPGRADE LEGACY.
#
# Simula una instalacion ANTERIOR a H-06/H-08 (root owner, 0644/0660, decisions y
# audit DENTRO de la release, unidad del visor sin User=, unidad del worker con
# www-data, visor corriendo como root, bases con datos REALES), ejecuta
# `deploy.sh --mode upgrade` con el commit nuevo y comprueba: servicios PARADOS
# durante la migracion -> migrado -> owner/modos -> datos PRESERVADOS (SHA-256) ->
# release nueva activa -> health verde -> decisiones presentes -> idempotencia (P12).
#
# Pre: una instalacion funcional del commit nuevo (escenario A ejecutado) o, mejor,
# restaure el snapshot de A. El guion la CONVIERTE en legacy y la vuelve a subir.
# Las unidades legacy son las REALES del commit base (4916e90): `git show`, no una copia.
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 [S9K_LAB_BASE_SHA=4916e90] deploy/tests/lab/30_escenario_B_upgrade_legacy.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

STATE=/var/lib/s9-knowledge

# --- comprobaciones ------------------------------------------------------------
# Cuenta filas de una tabla con la base abierta INMUTABLE (no crea -wal/-shm ni
# toca la base): valido como root antes y despues de migrar.
filas() {
    sudo python3 -c "import sqlite3,sys; c=sqlite3.connect('file:%s?mode=ro&immutable=1' % sys.argv[1], uri=True); print(c.execute('select count(*) from %s' % sys.argv[2]).fetchone()[0])" "$1" "$2"
}
parada_antes_de_migrar() {
    local a b
    a="$(grep -n 'parados y verificados' "${SALIDA}" | head -1 | cut -d: -f1)"
    b="$(grep -n 'movido' "${SALIDA}" | head -1 | cut -d: -f1)"
    [ -n "${a}" ] && { [ -z "${b}" ] || [ "${a}" -lt "${b}" ]; }
}
original_retirado_y_conservado() {
    [ ! -e "${RV3_REL}/decisions.jsonl" ] && ls "${RV3_REL}"/decisions.jsonl.migrado-* >/dev/null
}
release_nueva_activa() {
    [ "$(basename "$(readlink -f /opt/s9-knowledge/current)")" != "$(basename "${ACTUAL}")" ]
}
unidades_con_identidad_nueva() {
    grep -q '^User=s9knowledge$' /etc/systemd/system/s9-knowledge-viewer.service \
        && grep -q '^User=s9knowledge$' /etc/systemd/system/s9-knowledge-worker.service
}
modo_es() { [ "$(lab_modo "$1")" = "$2" ]; }
sha_es()  { [ "$(lab_sha256 "$1")" = "$2" ]; }
igual() { [ "$1" = "$2" ]; }
review_abre_como_servicio() {
    sudo runuser -u s9knowledge -- python3 -c "import sqlite3,sys; c=sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True); c.execute('select count(*) from human_decisions').fetchone()" "${STATE}/reviews-v3/review.sqlite3"
}
huella_del_estado() {
    sudo find "${STATE}" -path "${STATE}/deploy" -prune -o -type f -printf '%p %m %U\n' | sort | sha256sum
}

lab_guard
lab_tomar_cerrojo
BASE_SHA="${S9K_LAB_BASE_SHA:-4916e90}"
[ -L /opt/s9-knowledge/current ] || lab_stop "no hay instalacion previa: ejecute antes el escenario A"
git -C "${LAB_REPO}" cat-file -e "${BASE_SHA}^{commit}" || lab_stop "el commit base ${BASE_SHA} no esta en el clon (git fetch)"
SHA="$(lab_sha)"
SALIDA="${LAB_LOGS}/escenario-B-${SHA:0:12}.log"
ACTUAL="$(readlink -f /opt/s9-knowledge/current)"
RV3_REL=""   # lo fija lab_convertir_en_legacy

lab_log "B.1 detener todo y convertir la instalacion en LEGACY"
lab_convertir_en_legacy "${BASE_SHA}"

# HUELLAS de lo que tiene que sobrevivir (antes de migrar)
USUARIOS_ANTES="$(filas "${STATE}/auth/auth.db" users)"
JOBS_ANTES="$(filas "${STATE}/jobs/jobs.db" jobs)"
SHA_DEC="$(lab_sha256 "${RV3_REL}/decisions.jsonl")"
SHA_AUD="$(lab_sha256 "${RV3_REL}/audit.jsonl")"
SHA_GLO="$(lab_sha256 "${RV3_REL}/glossary-candidates/ws/candidates.jsonl")"
lab_log "B.1 fixture legacy lista: visor legacy $(systemctl is-active s9-knowledge-viewer.service); usuarios=${USUARIOS_ANTES} jobs=${JOBS_ANTES}"

lab_log "B.2 deploy.sh --mode upgrade (parada -> migracion -> activacion)"
lab_deploy upgrade 2>&1 | tee "${SALIDA}"

lab_assert "B.3 el log muestra la parada verificada ANTES de migrar" parada_antes_de_migrar
lab_assert "B.3 migrado: el estado mutable ya no esta en la release (original conservado como .migrado-*)" original_retirado_y_conservado
lab_assert "B.4 P9 decisions.jsonl preservado (mismo SHA-256) bajo el state root" sha_es "${STATE}/reviews-v3/decisions.jsonl" "${SHA_DEC}"
lab_assert "B.4 P9 audit.jsonl preservado" sha_es "${STATE}/reviews-v3/audit.jsonl" "${SHA_AUD}"
lab_assert "B.4 P9 candidatos de glosario preservados" sha_es "${STATE}/reviews-v3/glossary-candidates/ws/candidates.jsonl" "${SHA_GLO}"
lab_assert "B.4 P9 los usuarios de auth.db se conservan" igual "$(filas "${STATE}/auth/auth.db" users)" "${USUARIOS_ANTES}"
lab_assert "B.4 P9 los jobs de jobs.db se conservan" igual "$(filas "${STATE}/jobs/jobs.db" jobs)" "${JOBS_ANTES}"
lab_assert "B.5 owner s9knowledge:s9knowledge y modos 0600/0700 en TODO el estado (P3 P4)" lab_estado_conforme
lab_assert "B.5 review.sqlite3 paso de 0660 a 0600" modo_es "${STATE}/reviews-v3/review.sqlite3" 600
lab_assert "B.5 auth.db paso de 0644 a 0600" modo_es "${STATE}/auth/auth.db" 600
lab_assert "B.6 la release NUEVA esta activa" release_nueva_activa
lab_assert "B.6 visor y worker activos y como s9knowledge (P1 P2)" lab_procesos_como_servicio
lab_assert "B.6 las unidades instaladas son las del commit nuevo (User=s9knowledge)" unidades_con_identidad_nueva
lab_assert "B.7 health verde (verify-deployment)" \
    sudo "${LAB_REPO}/deploy/scripts/verify-deployment.sh" --expected-release "$(basename "$(readlink -f /opt/s9-knowledge/current)")"
lab_assert "B.8 C1/P10 review.sqlite3 abre y conserva su tabla de decisiones (como s9knowledge)" review_abre_como_servicio

# P12: el SEGUNDO despliegue es idempotente (mismos ficheros, mismos modos)
lab_log "B.9 P12 segundo despliegue idempotente"
ANTES="$(huella_del_estado)"
lab_deploy upgrade 2>&1 | tee -a "${SALIDA}"
DESPUES="$(huella_del_estado)"
lab_assert "B.9 el segundo despliegue no cambia ni un modo ni un propietario del estado" igual "${ANTES}" "${DESPUES}"
lab_assert "B.9 servicios vivos como s9knowledge" lab_procesos_como_servicio
lab_assert "B.9 estado conforme" lab_estado_conforme

lab_log "ESCENARIO B: PASS (log en ${SALIDA})"

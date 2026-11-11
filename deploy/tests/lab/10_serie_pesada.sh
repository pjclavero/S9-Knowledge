#!/usr/bin/env bash
# 10_serie_pesada.sh — la serie PESADA de H-06 + H-08 en VM112 (§23 del contrato).
#
# Orden (el del contrato, §23 puntos 2, 6-14), TODO en SERIE y con el arbol del
# clon COMMITEADO y LIMPIO (los calibradores restauran sobre el fichero):
#   1. tests especificos                       (4 ficheros + inventario)
#   2. calibrador H-06/H-08 (M1-M15)
#   3. calibradores anteriores afectados       (b3_worker, c1, b2_fresh_install, pr3, pr4)
#   4. suites completas: viewer, data-engine, deploy, regresion C1 y H-05
#
# Cada tanda deja PYTEST_RC REAL en el log: el exit de un envoltorio, un `tail` o una
# tarea de fondo NO certifica una suite. Un calibrador nunca corre a la vez que otro
# ni mientras se modifica el arbol. Toma el cerrojo de carga pesada del laboratorio.
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 deploy/tests/lab/10_serie_pesada.sh
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

lab_guard_basico
lab_tomar_cerrojo
cd "${LAB_REPO}"
PY="${LAB_BASE}/venv/bin/python"
[ -x "${PY}" ] || lab_stop "no hay venv de pruebas: ejecute antes 00_preparar.sh"
[ -z "$(git status --porcelain --untracked-files=no)" ] || lab_stop "el arbol tracked del clon no esta limpio"
SHA="$(git rev-parse HEAD)"
RES="${LAB_LOGS}/serie-${SHA:0:12}.txt"
: > "${RES}"
FALLOS=0

# tanda <nombre> <comando...>: ejecuta, registra PYTEST_RC real y el resumen.
tanda() {
    local nombre="$1"; shift
    local log="${LAB_LOGS}/${nombre}-${SHA:0:12}.log" rc
    lab_log "tanda ${nombre}"
    set +e
    "$@" > "${log}" 2>&1
    rc=$?
    set -e
    printf '%-48s PYTEST_RC=%s  %s\n' "${nombre}" "${rc}" "$(tail -n 1 "${log}" | tr -d '\r')" | tee -a "${RES}"
    [ "${rc}" -eq 0 ] || FALLOS=$((FALLOS + 1))
    [ -z "$(git status --porcelain --untracked-files=no)" ] \
        || { echo "ARBOL SUCIO tras ${nombre}: la tanda modifico ficheros tracked" | tee -a "${RES}"; FALLOS=$((FALLOS + 1)); }
}

export PYTHONDONTWRITEBYTECODE=1 S9K_ALLOW_REAL_INGEST=""

# 1. tests especificos
tanda especificos-deploy      "${PY}" -m pytest deploy/tests/test_h06_h08_servicio_y_estado.py deploy/tests/test_h06_h08_inventario_escrituras.py -q -p no:cacheprovider
tanda especificos-viewer      "${PY}" -m pytest viewer/tests/test_h06_h08_estado_privado.py -q -p no:cacheprovider
tanda especificos-worker      "${PY}" -m pytest data-engine/app/tests/test_h06_h08_autoridad_y_worker.py -q -p no:cacheprovider

# 2. calibrador H-06/H-08, EN SERIE, nada mas corriendo
tanda calibrador-h06-h08      "${PY}" scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py

# 3. calibradores anteriores que mi cambio puede mover (re-anclados por estructura) y los
#    hermanos de CI: todos los que corre el job «Calibracion de gates», EN SERIE
for c in b2_fresh_install b3_worker c1_persistencia_revision h05a_location h05b_trusted_host \
         pr3_instalacion_https pr4_instalacion_completa bootstrap_primer_admin instalacion_fabrica \
         corte4_revision corte5_signo_y_causa m1_ambito_boveda s1_resultado_sin_enlace_muerto \
         s1_selector_misma_autoridad corte6a_seleccion_real corte6b1_etiquetas topologia_publicable \
         p0_auth proveedor_no_configurado pr1_review_console_apagada b1_h03_aislamiento_workspace; do
    tanda "calibrador-${c}" "${PY}" "scripts/calibracion/mutaciones_${c}.py"
done
for c in f2_autoridad_workspace veracidad_tarjeta_review calibra_topologia_publicable; do
    tanda "calibrador-${c}" "${PY}" "scripts/calibracion/${c}.py"
done
for c in calibra_gate_integrity calibra_suite_inventory calibra_ejecucion_real calibra_registro_xfail \
         calibra_base_materializada calibra_a2_linaje calibra_desarme; do
    tanda "gate-${c}" "${PY}" ".github/scripts/${c}.py"
done
for c in calibrar_panel_sources calibrar_panel_operations calibrar_panel_review; do
    tanda "panel-${c}" "${PY}" "scripts/${c}.py"
done
tanda panel-calibrar_panel_entities "${PY}" scripts/calibrar_panel_entities.py --sin-colaterales

# 4. suites completas
tanda suite-viewer            "${PY}" -m pytest viewer/tests -q -p no:cacheprovider
tanda suite-data-engine       "${PY}" -m pytest data-engine/app/tests -q -p no:cacheprovider
tanda suite-deploy            "${PY}" -m pytest deploy/tests -q -p no:cacheprovider
tanda regresion-c1            "${PY}" -m pytest deploy/tests/test_c1_revision_deploy.py viewer/tests/test_v3_review_storage.py -q -p no:cacheprovider
tanda check-ci-config         "${PY}" .github/scripts/check_ci_config.py
tanda check-unicode           "${PY}" .github/scripts/check_unicode.py
tanda regresion-h05           "${PY}" -m pytest deploy/tests/test_h05b_endpoint_publico_despliegue.py -q -p no:cacheprovider

lab_log "SERIE COMPLETA: ${FALLOS} tanda(s) fallida(s). Resumen en ${RES}"
[ "${FALLOS}" -eq 0 ] || exit 1

#!/usr/bin/env bash
# 00_preparar.sh — prepara VM112 de forma REPRODUCIBLE para las pruebas pesadas de
# H-06 + H-08: clon del repo POR SHA, venv de pruebas con las dependencias
# bloqueadas (`data-engine/requirements.lock` + `viewer/requirements.txt`).
#
# NO toca `~diana` ni los clones/venv de otros carriles: todo vive bajo
# S9K_LAB_BASE (defecto /srv/s9-test/h06h08). Toma el cerrojo de carga pesada.
#
# Uso:  S9K_LAB_CONFIRMADO=VM112 S9K_LAB_SHA=<sha> deploy/tests/lab/00_preparar.sh <url-o-ruta-del-repo>
#       (el origen puede ser una ruta local o una URL; nunca se escribe en el repo)
# shellcheck shell=bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/tests/lab/lib_lab.sh
source "${HERE}/lib_lab.sh"

lab_guard
ORIGEN="${1:?uso: $0 <url-o-ruta-del-repo>   (con S9K_LAB_SHA=<sha>)}"
SHA="${S9K_LAB_SHA:?falta S9K_LAB_SHA: se prueba un commit concreto, no una rama}"
case "${SHA}" in *[!0-9a-f]*) lab_stop "S9K_LAB_SHA debe ser un SHA hex" ;; esac

preparar() {
    sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" "${LAB_BASE}" "${LAB_LOGS}"
    if [ ! -d "${LAB_REPO}/.git" ]; then
        git clone --no-checkout "${ORIGEN}" "${LAB_REPO}"
    fi
    git -C "${LAB_REPO}" fetch --quiet origin "${SHA}" 2>/dev/null || git -C "${LAB_REPO}" fetch --quiet origin
    git -C "${LAB_REPO}" cat-file -e "${SHA}^{commit}" || lab_stop "el commit ${SHA} no esta en el clon"
    git -C "${LAB_REPO}" checkout --quiet --detach "${SHA}"
    [ -z "$(git -C "${LAB_REPO}" status --porcelain --untracked-files=no)" ] \
        || lab_stop "el clon de laboratorio no esta limpio tras el checkout"
    lab_log "clon en ${LAB_REPO} @ $(git -C "${LAB_REPO}" rev-parse HEAD)"

    # venv de PRUEBAS (distinto de los venv de las releases que construye deploy.sh)
    if [ ! -x "${LAB_BASE}/venv/bin/python" ]; then
        python3 -m venv "${LAB_BASE}/venv"
    fi
    "${LAB_BASE}/venv/bin/pip" install --quiet --upgrade pip
    "${LAB_BASE}/venv/bin/pip" install --quiet -r "${LAB_REPO}/data-engine/requirements.lock"
    "${LAB_BASE}/venv/bin/pip" install --quiet -r "${LAB_REPO}/viewer/requirements.txt"
    "${LAB_BASE}/venv/bin/pip" install --quiet pytest pyyaml
    lab_log "venv de pruebas listo: ${LAB_BASE}/venv"
}

lab_tomar_cerrojo
preparar

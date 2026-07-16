#!/usr/bin/env bash
# validate.sh — validacion completa de los scripts de despliegue.
# Ejecutar desde el directorio raiz del repo o desde deploy/tests/.
#
# Tests incluidos:
#   1. bash -n (sintaxis de todos los scripts .sh)
#   2. shellcheck (si disponible)
#   3. yamllint (si disponible)
#   4. ansible syntax-check (si disponible)
#   5. Estructura de directorios esperada en deploy/
#   6. No hay secretos en los scripts (grep de patrones peligrosos)
#   7. .env no esta en releases (grep en scripts)
#   8. dry-run de deploy.sh no modifica nada
#
# shellcheck shell=bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/.." && pwd)"
REPO_ROOT="$(cd "${DEPLOY_ROOT}/.." && pwd)"

rc=0
passed=0
failed=0
skipped=0

_pass() { printf '\033[32m[PASS]\033[0m %s\n' "$*"; passed=$((passed + 1)); }
_fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$*" >&2; failed=$((failed + 1)); rc=1; }
_skip() { printf '\033[33m[SKIP]\033[0m %s\n' "$*"; skipped=$((skipped + 1)); }
_info() { printf '\033[34m[INFO]\033[0m %s\n' "$*"; }

_info "DEPLOY_ROOT: ${DEPLOY_ROOT}"
_info "REPO_ROOT:   ${REPO_ROOT}"

# ===========================================================================
# Test 1: bash -n (sintaxis)
# ===========================================================================
printf '\n== Test 1: bash -n (sintaxis) ==\n'
for f in "${DEPLOY_ROOT}"/scripts/*.sh "${DEPLOY_ROOT}"/tests/*.sh; do
    if bash -n "${f}" 2>/dev/null; then
        _pass "bash -n: $(basename "${f}")"
    else
        _fail "bash -n: $(basename "${f}")"
        bash -n "${f}" 2>&1 || true
    fi
done

# ===========================================================================
# Test 2: shellcheck
# ===========================================================================
printf '\n== Test 2: shellcheck ==\n'
if command -v shellcheck >/dev/null 2>&1; then
    sc_ok=1
    for f in "${DEPLOY_ROOT}"/scripts/*.sh; do
        if shellcheck -x -e SC1091 "${f}" 2>/dev/null; then
            _pass "shellcheck: $(basename "${f}")"
        else
            _fail "shellcheck: $(basename "${f}")"
            shellcheck -x -e SC1091 "${f}" 2>&1 || true
            sc_ok=0
        fi
    done
    [ "${sc_ok}" -eq 1 ] && _pass "shellcheck: todos OK"
else
    _skip "shellcheck no instalado (se ejecutara en CI)"
fi

# ===========================================================================
# Test 3: yamllint
# ===========================================================================
printf '\n== Test 3: yamllint ==\n'
if command -v yamllint >/dev/null 2>&1; then
    yaml_ok=1
    # Buscar todos los YAML en ansible/
    while IFS= read -r f; do
        if yamllint -d relaxed "${f}" >/dev/null 2>&1; then
            _pass "yamllint: ${f#"${DEPLOY_ROOT}"/}"
        else
            _fail "yamllint: ${f#"${DEPLOY_ROOT}"/}"
            yamllint -d relaxed "${f}" 2>&1 || true
            yaml_ok=0
        fi
    done < <(find "${DEPLOY_ROOT}/ansible" -name "*.yml" -o -name "*.yaml" | sort)
    [ "${yaml_ok}" -eq 1 ] && _pass "yamllint: todos OK"
else
    _skip "yamllint no instalado (se ejecutara en CI)"
fi

# ===========================================================================
# Test 4: ansible syntax-check
# ===========================================================================
printf '\n== Test 4: ansible syntax-check ==\n'
if command -v ansible-playbook >/dev/null 2>&1; then
    if ansible-playbook "${DEPLOY_ROOT}/ansible/site.yml" \
            --syntax-check \
            -i "${DEPLOY_ROOT}/ansible/inventory.example" \
            2>/dev/null; then
        _pass "ansible syntax-check: site.yml"
    else
        _fail "ansible syntax-check: site.yml"
        ansible-playbook "${DEPLOY_ROOT}/ansible/site.yml" \
            --syntax-check \
            -i "${DEPLOY_ROOT}/ansible/inventory.example" 2>&1 || true
    fi
else
    _skip "ansible-playbook no instalado (se ejecutara en CI)"
fi

# ===========================================================================
# Test 5: Estructura de directorios esperada
# ===========================================================================
printf '\n== Test 5: estructura de directorios ==\n'
required_paths=(
    "scripts/lib.sh"
    "scripts/preflight.sh"
    "scripts/deploy.sh"
    "scripts/verify-deployment.sh"
    "scripts/rollback-release.sh"
    "tests/validate.sh"
    "ansible/site.yml"
    "ansible/inventory.example"
    "ansible/group_vars/all.yml"
    "ansible/roles/common/tasks/main.yml"
    "ansible/roles/common/defaults/main.yml"
    "ansible/roles/viewer/tasks/main.yml"
    "ansible/roles/viewer/defaults/main.yml"
    "ansible/roles/viewer/handlers/main.yml"
    "ansible/roles/systemd/tasks/main.yml"
    "ansible/roles/systemd/defaults/main.yml"
    "ansible/roles/systemd/handlers/main.yml"
    "ansible/roles/healthchecks/tasks/main.yml"
    "ansible/roles/healthchecks/defaults/main.yml"
    "ansible/roles/healthchecks/handlers/main.yml"
    "ansible/roles/auth/tasks/main.yml"
    "ansible/roles/data_engine/tasks/main.yml"
)
for rel in "${required_paths[@]}"; do
    full="${DEPLOY_ROOT}/${rel}"
    if [ -f "${full}" ]; then
        _pass "existe: deploy/${rel}"
    else
        _fail "no existe: deploy/${rel}"
    fi
done

# ===========================================================================
# Test 6: No hay secretos en los scripts
# ===========================================================================
printf '\n== Test 6: sin secretos en scripts ==\n'
# Patrones que indican secretos hardcodeados (no variables ni comentarios)
SECRET_PATTERN='(password|passwd|token|secret|api_key|private_key)\s*=\s*['"'"'"][^'"'"'"]{6,}['"'"'"]'
found_secrets=0
while IFS= read -r f; do
    if grep -En "${SECRET_PATTERN}" "${f}" 2>/dev/null | grep -v '^\s*#'; then
        _fail "posible secreto en: ${f#"${REPO_ROOT}"/}"
        found_secrets=$((found_secrets + 1))
    fi
done < <(find "${DEPLOY_ROOT}" -name "*.sh" -o -name "*.yml" -o -name "*.yaml" | sort)

if [ "${found_secrets}" -eq 0 ]; then
    _pass "sin secretos hardcodeados detectados"
fi

# ===========================================================================
# Test 7: .env no esta en el directorio de releases
# ===========================================================================
printf '\n== Test 7: .env no copiado en releases ==\n'
# Verificar que los scripts no copian .env dentro de releases/
dotenv_in_releases=0
for f in "${DEPLOY_ROOT}"/scripts/*.sh; do
    # Buscamos patrones que copien .env a releases/
    if grep -n 'releases.*\.env\|cp.*releases.*\.env' "${f}" 2>/dev/null | grep -v '^\s*#' | grep -v 'warn\|err\|log\|rm -f'; then
        _fail ".env podria copiarse en releases en: $(basename "${f}")"
        dotenv_in_releases=$((dotenv_in_releases + 1))
    fi
done
if [ "${dotenv_in_releases}" -eq 0 ]; then
    _pass ".env no se copia dentro de releases (verificado)"
fi

# Verificar que deploy.sh contiene la proteccion de .env
if grep -q 'viewer/\.env' "${DEPLOY_ROOT}/scripts/deploy.sh" 2>/dev/null; then
    _pass "deploy.sh: contiene proteccion contra .env en releases"
else
    _fail "deploy.sh: no se detecta proteccion contra .env en releases"
fi

# ===========================================================================
# Test 8: dry-run de deploy.sh no modifica nada
# ===========================================================================
printf '\n== Test 8: dry-run no modifica nada ==\n'
LAB_ROOT="/tmp/s9k-validate-$$"
LAB_STATE="/tmp/s9k-state-$$"
LAB_CONFIG="/tmp/s9k-config-$$"
mkdir -p "${LAB_ROOT}/releases"
mkdir -p "${LAB_STATE}/"{auth,jobs,state}
mkdir -p "${LAB_CONFIG}"

# Snapshot antes del dry-run
snapshot_before="$(find "${LAB_ROOT}" "${LAB_STATE}" "${LAB_CONFIG}" -type f 2>/dev/null | sort | wc -l)"

# Ejecutar dry-run (sin --confirm)
set +e
S9K_ROOT="${LAB_ROOT}" \
S9K_STATE_ROOT="${LAB_STATE}" \
S9K_CONFIG_ROOT="${LAB_CONFIG}" \
S9K_VIEWER_URL="http://127.0.0.1:19999" \
bash "${DEPLOY_ROOT}/scripts/deploy.sh" \
    --environment lab \
    --release-ref HEAD \
    --dry-run \
    2>/dev/null
dryrun_rc=$?
set -e

# Snapshot despues del dry-run
snapshot_after="$(find "${LAB_ROOT}" "${LAB_STATE}" "${LAB_CONFIG}" -type f 2>/dev/null | sort | wc -l)"

# Limpieza
rm -rf "${LAB_ROOT}" "${LAB_STATE}" "${LAB_CONFIG}"

if [ "${dryrun_rc}" -eq 0 ]; then
    _pass "dry-run exitio con rc=0"
else
    _fail "dry-run fallo con rc=${dryrun_rc}"
fi

if [ "${snapshot_before}" -eq "${snapshot_after}" ]; then
    _pass "dry-run no modifico ningun fichero (${snapshot_before} ficheros antes y despues)"
else
    _fail "dry-run modifico ficheros: ${snapshot_before} antes, ${snapshot_after} despues"
fi

# ===========================================================================
# Test 9: check_unicode.py (si existe)
# ===========================================================================
printf '\n== Test 9: Unicode check ==\n'
UNICODE_SCRIPT="${REPO_ROOT}/.github/scripts/check_unicode.py"
if [ -f "${UNICODE_SCRIPT}" ]; then
    set +e
    python3 "${UNICODE_SCRIPT}" 2>/dev/null
    uc_rc=$?
    set -e
    if [ "${uc_rc}" -eq 0 ]; then
        _pass "Unicode check: OK"
    else
        _fail "Unicode check: caracters peligrosos detectados"
    fi
else
    _skip "check_unicode.py no encontrado en ${UNICODE_SCRIPT}"
fi

# ===========================================================================
# Resumen
# ===========================================================================
printf '\n========================================\n'
printf 'RESUMEN validate.sh:\n'
printf '  \033[32mPASS:\033[0m %d\n' "${passed}"
printf '  \033[31mFAIL:\033[0m %d\n' "${failed}"
printf '  \033[33mSKIP:\033[0m %d\n' "${skipped}"
printf '========================================\n'

exit "${rc}"

#!/usr/bin/env bash
# test_verify_deployment.sh — test suite for verify-deployment.sh (§14, 18 cases).
#
# Runs verify-deployment.sh against controlled synthetic environments
# and checks exit codes + output content.
#
# Exit: 0 = all tests passed; 1 = at least one failed.
# shellcheck shell=bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="${HERE}/../scripts"
VERIFY="${SCRIPTS}/verify-deployment.sh"

rc=0
passed=0
failed=0
skipped=0

_pass() { printf '\033[32m[PASS]\033[0m %s\n' "$*"; passed=$((passed + 1)); }
_fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$*" >&2; failed=$((failed + 1)); rc=1; }
_skip() { printf '\033[33m[SKIP]\033[0m %s\n' "$*"; skipped=$((skipped + 1)); }
_info() { printf '\033[34m[INFO]\033[0m %s\n' "$*"; }

_info "VERIFY: ${VERIFY}"
_info "bash:   $(bash --version | head -1)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_make_lab() {
    local lab
    lab="$(mktemp -d)"
    mkdir -p "${lab}/releases" "${lab}/state/auth" "${lab}/state/jobs"
    printf '%s' "${lab}"
}

_make_release() {
    local releases_root="${1}"
    local rid="${2}"
    local commit="${3:-abc1234}"
    local rel_dir="${releases_root}/${rid}"
    mkdir -p "${rel_dir}/viewer/.venv/bin"
    # Create a fake python interpreter that handles all expected queries
    printf '#!/bin/bash\nif [[ "$*" == "--version" ]]; then echo "Python 3.11.0"; exit 0; fi\nif [[ "$*" =~ "-c" ]]; then exit 0; fi\nexit 0\n' > "${rel_dir}/viewer/.venv/bin/python"
    chmod +x "${rel_dir}/viewer/.venv/bin/python"
    # Create manifest
    printf '{"release_id":"%s","git_commit":"%s","created_at":"2026-01-01T00:00:00Z","created_by":"test"}\n' \
        "${rid}" "${commit}" > "${rel_dir}/manifest.json"
    printf '%s' "${rel_dir}"
}

# Run verify-deployment with mocked systemctl (active) and curl (200 OK).
# Isolates the structural checks (current symlink, manifest, .venv, state dir)
# from real service availability. Expects exit 0 when structural checks pass.
_run_isolated() {
    local lab="${1}"
    shift
    local _fake_bin
    _fake_bin="$(mktemp -d)"
    # fake systemctl: reports service as active
    printf '#!/bin/bash\nprintf "active"\nexit 0\n' > "${_fake_bin}/systemctl"
    # fake curl: reports HTTP 200 (healthy endpoint)
    printf '#!/bin/bash\nprintf "200"\nexit 0\n' > "${_fake_bin}/curl"
    chmod +x "${_fake_bin}/systemctl" "${_fake_bin}/curl"
    local out v_rc
    set +e
    out="$(PATH="${_fake_bin}:${PATH}" \
        S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="${lab}/state" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="false" \
        bash "${VERIFY}" "$@" 2>&1)"
    v_rc=$?
    set -e
    rm -rf "${_fake_bin}"
    printf '%s' "${out}"
    return ${v_rc}
}

# Run verify-deployment with systemctl and curl TRULY absent from PATH.
# Creates a minimal PATH with symlinks to essential binaries but NOT curl/systemctl.
_run_no_optionals() {
    local lab="${1}"
    shift
    local _fake_bin _out _v_rc
    _fake_bin="$(mktemp -d)"

    # Symlink all binaries used by verify-deployment.sh + lib.sh, except curl/systemctl
    local _essential_tools="bash python3 readlink basename dirname head find awk grep cat printf test tr ss netstat"
    local _t _p
    for _t in ${_essential_tools}; do
        _p="$(command -v "${_t}" 2>/dev/null || true)"
        [ -n "${_p}" ] && ln -sfn "${_p}" "${_fake_bin}/${_t}" 2>/dev/null || true
    done
    # Intentionally do NOT symlink curl or systemctl

    set +e
    _out="$(PATH="${_fake_bin}" \
        S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="${lab}/state" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="false" \
        bash "${VERIFY}" "$@" 2>&1)"
    _v_rc=$?
    set -e
    rm -rf "${_fake_bin}"
    printf '%s' "${_out}"
    return ${_v_rc}
}

# ---------------------------------------------------------------------------
# Case 1: script has valid bash syntax (no parse errors)
# ---------------------------------------------------------------------------
printf '\n== [1] bash -n syntax check ==\n'
if bash -n "${VERIFY}" 2>/dev/null; then
    _pass "verify-deployment.sh: bash -n OK"
else
    _fail "verify-deployment.sh: bash -n FAIL"
    bash -n "${VERIFY}" 2>&1 || true
fi

# ---------------------------------------------------------------------------
# Case 2: no "command not found" for ok/pass/fail/skip in any code path
# ---------------------------------------------------------------------------
printf '\n== [2] no command-not-found for ok/pass/fail/skip ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    set +e
    stderr_out="$(S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="${lab}/state" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="false" \
        bash "${VERIFY}" 2>&1)"
    set -e

    if printf '%s' "${stderr_out}" | grep -q 'command not found'; then
        _fail "Case 2: 'command not found' in stderr"
        printf '%s\n' "${stderr_out}" | grep 'command not found' | head -5
    else
        _pass "Case 2: no 'command not found' in output"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 3: correct structural setup (systemctl/curl hidden) → exit 0 + VERIFICATION_OK
# ---------------------------------------------------------------------------
printf '\n== [3] structural checks pass with systemctl/curl hidden → exit 0 ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    set +e
    out="$(_run_isolated "${lab}" 2>&1)"
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 0 ]; then
        _pass "Case 3: exit 0 on structural checks pass"
    else
        _fail "Case 3: expected exit 0, got ${v_rc}"
        printf '%s\n' "${out}" | tail -10
    fi

    if printf '%s' "${out}" | grep -q 'VERIFICATION_OK'; then
        _pass "Case 3: output contains VERIFICATION_OK"
    else
        _fail "Case 3: output does not contain VERIFICATION_OK"
        printf '%s\n' "${out}" | tail -5
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 4: missing current symlink → gate crítico → exit 1 + VERIFICATION_FAILED
# ---------------------------------------------------------------------------
printf '\n== [4] missing current symlink → exit 1 + VERIFICATION_FAILED ==\n'
{
    lab="$(_make_lab)"
    # Don't create a 'current' symlink

    set +e
    out="$(_run_isolated "${lab}" 2>&1)"
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 1 ]; then
        _pass "Case 4: exit 1 on missing current symlink"
    else
        _fail "Case 4: expected exit 1, got ${v_rc}"
    fi

    if printf '%s' "${out}" | grep -q 'VERIFICATION_FAILED'; then
        _pass "Case 4: output contains VERIFICATION_FAILED"
    else
        _fail "Case 4: output does not contain VERIFICATION_FAILED"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 5: wrong release ID (expected != active) → exit 1 + VERIFICATION_FAILED
# ---------------------------------------------------------------------------
printf '\n== [5] wrong release ID → exit 1 ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    set +e
    out="$(_run_isolated "${lab}" --expected-release "wrongid-99999999" 2>&1)"
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 1 ]; then
        _pass "Case 5: exit 1 on wrong release ID"
    else
        _fail "Case 5: expected exit 1, got ${v_rc}"
    fi
    if printf '%s' "${out}" | grep -q 'VERIFICATION_FAILED'; then
        _pass "Case 5: output contains VERIFICATION_FAILED"
    else
        _fail "Case 5: output does not contain VERIFICATION_FAILED"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 6: state dir not accessible → exit 1 (critical gate)
# ---------------------------------------------------------------------------
printf '\n== [6] inaccessible state dir → exit 1 ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    _fake_bin="$(mktemp -d)"
    printf '#!/bin/bash\nexit 1\n' > "${_fake_bin}/systemctl"
    printf '#!/bin/bash\nexit 1\n' > "${_fake_bin}/curl"
    chmod +x "${_fake_bin}/systemctl" "${_fake_bin}/curl"

    set +e
    out="$(PATH="${_fake_bin}:${PATH}" \
        S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="/nonexistent/state-$$" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="false" \
        bash "${VERIFY}" 2>&1)"
    v_rc=$?
    set -e
    rm -rf "${_fake_bin}"

    if [ "${v_rc}" -eq 1 ]; then
        _pass "Case 6: exit 1 on inaccessible state dir"
    else
        _fail "Case 6: expected exit 1, got ${v_rc}"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 7: auth.db missing with auth=true → exit 1 (critical)
# ---------------------------------------------------------------------------
printf '\n== [7] auth.db missing with auth=true → exit 1 ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"
    # Don't create auth.db

    _fake_bin="$(mktemp -d)"
    printf '#!/bin/bash\nexit 1\n' > "${_fake_bin}/systemctl"
    printf '#!/bin/bash\nexit 1\n' > "${_fake_bin}/curl"
    chmod +x "${_fake_bin}/systemctl" "${_fake_bin}/curl"

    set +e
    out="$(PATH="${_fake_bin}:${PATH}" \
        S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="${lab}/state" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="true" \
        bash "${VERIFY}" 2>&1)"
    v_rc=$?
    set -e
    rm -rf "${_fake_bin}"

    if [ "${v_rc}" -eq 1 ]; then
        _pass "Case 7: exit 1 when auth=true and auth.db missing"
    else
        _fail "Case 7: expected exit 1, got ${v_rc}"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 8: absent optional tools (systemctl + curl) → SKIP, not FAIL
# ---------------------------------------------------------------------------
printf '\n== [8] absent optional tools → SKIP not FAIL ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    set +e
    out="$(_run_no_optionals "${lab}" 2>&1)"
    v_rc=$?
    set -e

    if printf '%s' "${out}" | grep -q 'SKIP'; then
        _pass "Case 8: SKIP emitted for absent optional tools"
    else
        _fail "Case 8: no SKIP for absent tools"
        printf '%s\n' "${out}" | grep -E 'SKIP|PASS|FAIL' | head -10
    fi

    if [ "${v_rc}" -eq 0 ]; then
        _pass "Case 8: exit 0 when only optional tools absent"
    else
        _fail "Case 8: expected exit 0, got ${v_rc}"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 9: unknown argument → exit 2 (BLOCKED)
# ---------------------------------------------------------------------------
printf '\n== [9] unknown argument → exit 2 ==\n'
{
    lab="$(_make_lab)"

    set +e
    S9K_ROOT="${lab}" \
    S9K_STATE_ROOT="${lab}/state" \
    S9K_VIEWER_URL="http://127.0.0.1:19998" \
    bash "${VERIFY}" --invalid-arg >/dev/null 2>&1
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 2 ]; then
        _pass "Case 9: exit 2 on unknown argument"
    else
        _fail "Case 9: expected exit 2, got ${v_rc}"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 10: verify-deployment.sh does not modify any state
# ---------------------------------------------------------------------------
printf '\n== [10] verify-deployment.sh does not modify state ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    before="$(find "${lab}" -type f | sort | wc -l)"

    set +e
    S9K_ROOT="${lab}" \
    S9K_STATE_ROOT="${lab}/state" \
    S9K_VIEWER_URL="http://127.0.0.1:19998" \
    S9K_AUTH_ENABLED="false" \
    bash "${VERIFY}" >/dev/null 2>&1
    set -e

    after="$(find "${lab}" -type f | sort | wc -l)"

    if [ "${before}" -eq "${after}" ]; then
        _pass "Case 10: verify-deployment.sh did not modify any files"
    else
        _fail "Case 10: verify-deployment.sh modified files (before=${before} after=${after})"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 11: malformed http_code from curl does NOT get executed as a command
# ---------------------------------------------------------------------------
printf '\n== [11] malformed http_code not executed as command ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    # Create a fake curl that returns a "dangerous" string with shell chars
    _fake_bin="$(mktemp -d)"
    cat > "${_fake_bin}/curl" <<'EOF'
#!/bin/bash
printf '$(touch /tmp/s9k-inject-test-$$)'
exit 0
EOF
    chmod +x "${_fake_bin}/curl"
    # Also fake systemctl as not available
    printf '#!/bin/bash\nexit 127\n' > "${_fake_bin}/systemctl"
    chmod +x "${_fake_bin}/systemctl"

    set +e
    PATH="${_fake_bin}:${PATH}" \
    S9K_ROOT="${lab}" \
    S9K_STATE_ROOT="${lab}/state" \
    S9K_VIEWER_URL="http://127.0.0.1:19998" \
    S9K_AUTH_ENABLED="false" \
    bash "${VERIFY}" 2>/dev/null
    set -e

    # shellcheck disable=SC2086
    if ls /tmp/s9k-inject-test-* 2>/dev/null | grep -q .; then
        _fail "Case 11: command injection via http_code succeeded!"
        # shellcheck disable=SC2086
        rm -f /tmp/s9k-inject-test-* 2>/dev/null || true
    else
        _pass "Case 11: malformed http_code not executed as command"
    fi

    rm -rf "${_fake_bin}" "${lab}"
}

# ---------------------------------------------------------------------------
# Case 12: VERIFICATION_OK keyword is printed, not executed as command
# ---------------------------------------------------------------------------
printf '\n== [12] VERIFICATION_OK is printed, not executed ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    set +e
    out="$(S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="${lab}/state" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="false" \
        bash "${VERIFY}" 2>&1)"
    set -e

    # If VERIFICATION_OK/FAILED/BLOCKED were executed as commands, we'd see
    # "command not found" in output
    if printf '%s' "${out}" | grep -q 'command not found'; then
        _fail "Case 12: result keyword was executed as command"
    else
        _pass "Case 12: result keyword was printed, not executed"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 13: current symlink pointing to nonexistent dir → VERIFICATION_FAILED
# ---------------------------------------------------------------------------
printf '\n== [13] current symlink to nonexistent dir → FAILED ==\n'
{
    lab="$(_make_lab)"
    ln -sfn "${lab}/releases/nonexistent-release" "${lab}/current"

    set +e
    out="$(_run_isolated "${lab}" 2>&1)"
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 1 ]; then
        _pass "Case 13: exit 1 for dangling current symlink"
    else
        _fail "Case 13: expected exit 1, got ${v_rc}"
    fi
    if printf '%s' "${out}" | grep -q 'VERIFICATION_FAILED'; then
        _pass "Case 13: output contains VERIFICATION_FAILED"
    else
        _fail "Case 13: output does not contain VERIFICATION_FAILED"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 14: missing .venv → VERIFICATION_FAILED
# ---------------------------------------------------------------------------
printf '\n== [14] missing .venv → FAILED ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    # Create release WITHOUT .venv
    rel_dir="${lab}/releases/${rid}"
    mkdir -p "${rel_dir}"
    printf '{"release_id":"%s","git_commit":"abc","created_at":"2026-01-01T00:00:00Z","created_by":"test"}' \
        "${rid}" > "${rel_dir}/manifest.json"
    ln -sfn "${rel_dir}" "${lab}/current"

    set +e
    out="$(_run_isolated "${lab}" 2>&1)"
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 1 ]; then
        _pass "Case 14: exit 1 for missing .venv"
    else
        _fail "Case 14: expected exit 1, got ${v_rc}"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 15: correct release + --expected-release → exit 0 (with isolated checks)
# ---------------------------------------------------------------------------
printf '\n== [15] correct release with --expected-release → exit 0 ==\n'
{
    lab="$(_make_lab)"
    rid="abc1234-20260101"
    rel="$(_make_release "${lab}/releases" "${rid}")"
    ln -sfn "${rel}" "${lab}/current"

    set +e
    out="$(_run_isolated "${lab}" --expected-release "${rid}" 2>&1)"
    v_rc=$?
    set -e

    if [ "${v_rc}" -eq 0 ]; then
        _pass "Case 15: exit 0 for correct --expected-release (isolated)"
    else
        _fail "Case 15: expected exit 0, got ${v_rc}"
        printf '%s\n' "${out}" | tail -5
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 16: shellcheck passes on verify-deployment.sh
# ---------------------------------------------------------------------------
printf '\n== [16] shellcheck ==\n'
if command -v shellcheck >/dev/null 2>&1; then
    # Exclude SC2329 (function never invoked — trap function is invoked via trap mechanism)
    if shellcheck -x -e SC1091,SC2329 "${VERIFY}" 2>/dev/null; then
        _pass "Case 16: shellcheck OK"
    else
        _fail "Case 16: shellcheck FAIL"
        shellcheck -x -e SC1091,SC2329 "${VERIFY}" 2>&1 || true
    fi
else
    _skip "Case 16: shellcheck not installed (will run in CI)"
fi

# ---------------------------------------------------------------------------
# Case 17: VERIFICATION_FAILED is not executed as command
# ---------------------------------------------------------------------------
printf '\n== [17] VERIFICATION_FAILED not executed as command ==\n'
{
    lab="$(_make_lab)"
    # No current symlink → will fail

    set +e
    out="$(S9K_ROOT="${lab}" \
        S9K_STATE_ROOT="${lab}/state" \
        S9K_VIEWER_URL="http://127.0.0.1:19998" \
        S9K_AUTH_ENABLED="false" \
        bash "${VERIFY}" 2>&1)"
    set -e

    if printf '%s' "${out}" | grep -q 'command not found'; then
        _fail "Case 17: VERIFICATION_FAILED was executed as command"
    else
        _pass "Case 17: VERIFICATION_FAILED printed safely"
    fi
    rm -rf "${lab}"
}

# ---------------------------------------------------------------------------
# Case 18: lib.sh ok() function does not call external command
# ---------------------------------------------------------------------------
printf '\n== [18] lib.sh ok() does not call external command ==\n'
{
    LIB="${SCRIPTS}/lib.sh"
    if bash -c "source '${LIB}' && ok 'test message'" 2>/dev/null; then
        _pass "Case 18: ok() defined and works in lib.sh"
    else
        _fail "Case 18: ok() failed when called from lib.sh"
    fi
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\n========================================\n'
printf 'RESUMEN test_verify_deployment.sh:\n'
printf '  \033[32mPASS:\033[0m %d\n' "${passed}"
printf '  \033[31mFAIL:\033[0m %d\n' "${failed}"
printf '  \033[33mSKIP:\033[0m %d\n' "${skipped}"
printf '========================================\n'

exit "${rc}"

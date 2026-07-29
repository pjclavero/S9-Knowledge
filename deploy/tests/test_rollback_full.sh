#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HERE}/../scripts/rollback-full.sh"
lab="$(mktemp -d)"
trap 'rm -rf "${lab}"' EXIT
dump="${lab}/neo4j.dump"
: > "${dump}"
calls="${lab}/calls"

make_stub() {
    local path="$1" body="$2"
    printf '#!/usr/bin/env bash\n%s\n' "${body}" > "${path}"
    chmod +x "${path}"
}
# shellcheck disable=SC2016 # contenido literal del script stub
make_stub "${lab}/app" 'printf "app %s\n" "$*" >> "$CALLS"; [[ "$*" != *"--dry-run"* ]] || exit "${APP_DRY_RC:-0}"'
# shellcheck disable=SC2016 # contenido literal del script stub
make_stub "${lab}/data" 'printf "data %s\n" "$*" >> "$CALLS"; [[ "$*" != *"--dry-run"* ]] || exit "${DATA_DRY_RC:-0}"'
# shellcheck disable=SC2016 # contenido literal del script stub
make_stub "${lab}/verify" 'printf "verify %s\n" "$*" >> "$CALLS"'

run() {
    CALLS="${calls}" S9K_ROLLBACK_RELEASE_SCRIPT="${lab}/app" \
      S9K_NEO4J_RESTORE_SCRIPT="${lab}/data" S9K_VERIFY_DEPLOYMENT_SCRIPT="${lab}/verify" \
      bash "${SCRIPT}" --to r1 --neo4j-dump "${dump}" "$@"
}

out="$(run)"
grep -q ROLLBACK_FULL_DRY_RUN_OK <<<"${out}"
[ "$(wc -l < "${calls}")" -eq 2 ]
if grep -q verify "${calls}"; then
    echo "FAIL: verify se ejecutó durante dry-run" >&2
    exit 1
fi

: > "${calls}"
APP_DRY_RC=1
export APP_DRY_RC
if run --apply >/dev/null 2>&1; then
    echo "FAIL: apply continuó tras dry-run fallido" >&2
    exit 1
fi
[ "$(wc -l < "${calls}")" -eq 1 ]
unset APP_DRY_RC

: > "${calls}"
out="$(run --environment lab --apply)"
grep -q ROLLBACK_FULL_OK <<<"${out}"
[ "$(wc -l < "${calls}")" -eq 5 ]
grep -q -- '--confirm' "${calls}"
grep -q 'verify --expected-release r1' "${calls}"
printf 'test_rollback_full: OK\n'

#!/usr/bin/env bash
# =============================================================================
# PR#95 - Driver de corrida con PROVEEDOR REAL (NVIDIA). GATEADO.
#
# NO EJECUTA el proveedor por si solo: la linea de ejecucion esta COMENTADA.
# Descomentarla requiere AUTORIZACION HUMANA EXPLICITA (consume cuota real y red).
#
# Objetivo: aislar cuantos rechazos del evaluador externo desaparecen SOLO por P0
# (commit dcded31 pre-fix vs 92583f4 base), y luego medir +V2 y +V3 REALES.
#
# Doble llave obligatoria:  --enable-providers  Y  S9K_BENCH_PROVIDERS=1
# Key:   S9K_NVIDIA_API_KEY desde /home/ia02/.config/s9k/nvidia.env (nunca impresa)
# Modelo: meta/llama-3.3-70b-instruct  (el meta/llama-3.1-70b-instruct esta RETIRADO)
# =============================================================================
set -euo pipefail

MODEL="meta/llama-3.3-70b-instruct"
KEY_FILE="/home/ia02/.config/s9k/nvidia.env"
CORPUS="data-engine/app/tests/data/relation_benchmark"
TEMPERATURE="0.0"
MAX_RETRIES="2"
TIMEOUT_S="30"
REPS="3"
SEED="20250721"
OUTDIR="/home/ia02/S9-Knowledge/.claude/worktrees/pr95-audit/artifacts/pr95-unified-comparison/real-provider"

# --- Guardas de doble llave (fail-closed) ------------------------------------
if [[ "${S9K_BENCH_PROVIDERS:-0}" != "1" ]]; then
  echo "ABORTA: falta la llave de entorno S9K_BENCH_PROVIDERS=1" >&2; exit 3
fi
if [[ ! -f "${KEY_FILE}" ]]; then
  echo "ABORTA: no existe el fichero de key ${KEY_FILE}" >&2; exit 3
fi

# --- Sourcear la key SIN ecoarla ---------------------------------------------
set +x
# shellcheck disable=SC1090
. "${KEY_FILE}"
if [[ -z "${S9K_NVIDIA_API_KEY:-}" ]]; then
  echo "ABORTA: S9K_NVIDIA_API_KEY ausente tras sourcear (fail-closed)" >&2; exit 3
fi
set -x

mkdir -p "${OUTDIR}"

# --- Funcion de corrida (worktree desechable por commit) ---------------------
# Uso: run_variant <nombre> <commit> <extra-flags...>
run_variant () {
  local name="$1"; shift
  local commit="$1"; shift
  local wt="/home/ia02/S9-Knowledge/.claude/worktrees/pr95-real-${name}"
  git -C /home/ia02/S9-Knowledge worktree add --detach "${wt}" "${commit}"
  local app="${wt}/data-engine/app"

  # ------------------------------------------------------------------------
  # LINEA DE EJECUCION REAL: DESCOMENTAR SOLO TRAS AUTORIZACION HUMANA.
  # Consume cuota NVIDIA y abre red. Logs redactados (sin key, sin doc crudo).
  # ------------------------------------------------------------------------
  # ( cd "${app}" && \
  #   S9K_NVIDIA_API_KEY="${S9K_NVIDIA_API_KEY}" \
  #   python3 -m relations.benchmark.cli \
  #     --mode external_shadow \
  #     --enable-providers \
  #     --external-model "${MODEL}" \
  #     --corpus-dir "${CORPUS}" \
  #     --repeat "${REPS}" --seed "${SEED}" \
  #     "$@" \
  #   2> >(sed -E 's/(S9K_NVIDIA_API_KEY=)[^ ]*/\1[REDACTED]/g' >"${OUTDIR}/${name}.stderr") \
  #   1>"${OUTDIR}/${name}.json" )

  echo "[GATEADO] corrida '${name}' @ ${commit} preparada (ejecucion comentada)."
  git -C /home/ia02/S9-Knowledge worktree remove --force "${wt}" || true
}

# Matriz: PRE-FIX vs BASE aisla P0; +V2/+V3 sobre BASE miden el incremento real.
run_variant "prefix"  "dcded31"
run_variant "base_p0" "92583f4"
run_variant "v2"      "92583f4"  # + flag realignment (via cli/env de la version V2)
run_variant "v3"      "92583f4"  # + flag fragment_protocol (via cli/env de la version V3)

echo "Plan preparado. Ninguna llamada real emitida (lineas de ejecucion comentadas)."

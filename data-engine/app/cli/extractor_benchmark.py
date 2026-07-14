"""Benchmark runner aislado para extractores S9 Knowledge.

Modo aislado (por defecto): usa tests/fixtures/benchmark/<source_id>/segments.classified.json
como entrada directa al paso de extracción, saltando segmentación y clasificación.

Validación estricta:
  - INVALID_RUN si segments_extractables == 0
  - INVALID_RUN si candidates == 0 cuando había segmentos extraíbles
  - INVALID_RUN_FALLBACK si modo LLM/hybrid pero duración < LLM_MIN_DURATION_MS (posible fallback)
  - FAIL si exit_code != 0

Garantías de seguridad:
  - NUNCA define S9K_ALLOW_REAL_INGEST=true
  - Siempre pasa --dry-run al pipeline
  - seed=42 para runs LLM/hybrid (reproducibilidad)

Uso:
  python data-engine/app/cli/extractor_benchmark.py \\
      --manifest tests/fixtures/benchmark/corpus-manifest.json \\
      --mode all \\
      --output-dir benchmark-results
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas del repo
# ---------------------------------------------------------------------------
_CLI_DIR = Path(__file__).resolve().parent
_APP_DIR = _CLI_DIR.parent
_REPO_ROOT = _APP_DIR.parents[1]

_PIPELINE_CLI = _CLI_DIR / "data_review.py"
_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "benchmark"

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_LLM_RUNS = 3
_HYBRID_RUNS = 3
_EXTRACTORS = ("heuristic", "llm", "hybrid")
_LLM_MIN_DURATION_MS = 5_000  # menos de esto = LLM probablemente no llamado
_BENCHMARK_SEED = 42           # semilla fija para reproducibilidad LLM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _load_settings() -> dict:
    settings_path = _REPO_ROOT / "data-engine" / "config" / "settings.yaml"
    try:
        import yaml  # type: ignore
        with settings_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _build_configuration(run_id: str) -> dict:
    settings = _load_settings()
    ollama_cfg = settings.get("ollama", {})
    return {
        "run_id": run_id,
        "generated_at": _now_iso(),
        "commit": _git_commit(),
        "python": sys.version,
        "mode": "isolated",
        "ollama": {
            "base_url": ollama_cfg.get("base_url", "http://192.168.1.157:11434"),
            "model": ollama_cfg.get("model", "qwen2.5:7b"),
            "temperature": ollama_cfg.get("temperature", 0),
            "request_timeout": ollama_cfg.get("request_timeout", 900),
            "seed": _BENCHMARK_SEED,
        },
        "pipeline_cli": str(_PIPELINE_CLI),
        "dry_run": True,
        "llm_runs": _LLM_RUNS,
        "hybrid_runs": _HYBRID_RUNS,
        "llm_min_duration_ms": _LLM_MIN_DURATION_MS,
    }


def _count_extractable(segs_path: Path) -> int:
    """Lee segments.classified.json y devuelve el número con should_extract=True."""
    try:
        data = json.loads(segs_path.read_text(encoding="utf-8"))
        return sum(1 for s in data if s.get("should_extract"))
    except Exception:
        return -1


def _run_isolated(
    source: dict,
    extractor: str,
    dest_dir: Path,
) -> dict:
    """
    Ejecuta el paso de extracción aislado para un source+extractor.

    - Copia segments.classified.json del fixture al directorio de output del pipeline.
    - Llama a data_review.py extract (no run) con --dry-run.
    - Lee candidates.json para contar candidatos reales.

    Returns dict con:
      exit_code, duration_ms, stdout, stderr,
      extractable_segments, candidates_count, status, validation_reason
    """
    source_id = source["id"]
    workspace = source.get("workspace", "leyenda")
    source_file = source.get("file", "")

    # Ruta al segments.classified.json del fixture
    fixture_segs = _FIXTURES_DIR / source_id / "segments.classified.json"
    if not fixture_segs.exists():
        return {
            "exit_code": -3,
            "duration_ms": 0,
            "stdout": "",
            "stderr": f"FIXTURE NOT FOUND: {fixture_segs}",
            "extractable_segments": 0,
            "candidates_count": 0,
            "source_file": source_file,
            "status": "FAIL",
            "validation_reason": f"segments.classified.json no encontrado: {fixture_segs}",
        }

    extractable = _count_extractable(fixture_segs)
    if extractable == 0:
        return {
            "exit_code": -4,
            "duration_ms": 0,
            "stdout": "",
            "stderr": "INVALID: 0 segmentos extraíbles",
            "extractable_segments": 0,
            "candidates_count": 0,
            "source_file": source_file,
            "status": "INVALID_RUN",
            "validation_reason": "0 segmentos con should_extract=True — benchmark sin datos",
        }

    # Copiar segments.classified.json al directorio de output del pipeline
    out_dir = _REPO_ROOT / "output" / "reviews" / workspace / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_segs, out_dir / "segments.classified.json")

    # Env limpio: NUNCA S9K_ALLOW_REAL_INGEST; seed para LLM
    env = os.environ.copy()
    env.pop("S9K_ALLOW_REAL_INGEST", None)
    if extractor in ("llm", "hybrid"):
        env["S9K_LLM_SEED"] = str(_BENCHMARK_SEED)

    cmd = [
        sys.executable,
        str(_PIPELINE_CLI),
        "extract",
        "--workspace", workspace,
        "--source-id", source_id,
        "--extractor", extractor,
    ]

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, env=env, cwd=str(_REPO_ROOT), timeout=1800,
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        exit_code, stdout, stderr = -1, "", f"TIMEOUT: {e}"
    except Exception as e:
        exit_code, stdout, stderr = -2, "", f"EXCEPTION: {e}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    # Leer candidates.json para validación real
    cands_path = out_dir / "candidates.json"
    candidates_count = 0
    if cands_path.exists():
        try:
            candidates_count = len(json.loads(cands_path.read_text(encoding="utf-8")))
        except Exception:
            candidates_count = -1

    # Determinar status
    status = "OK"
    validation_reason = ""

    if exit_code != 0:
        status = "FAIL"
        validation_reason = f"exit_code={exit_code}"
    elif candidates_count == 0 and extractable > 0:
        status = "INVALID_RUN"
        validation_reason = f"0 candidatos extraídos con {extractable} segmentos extraíbles"
    elif extractor in ("llm", "hybrid") and duration_ms < _LLM_MIN_DURATION_MS:
        if "Ollama no disponible" in stderr or "degradando" in stderr:
            status = "INVALID_RUN_FALLBACK"
            validation_reason = f"Fallback a heurístico detectado en stderr ({duration_ms}ms)"
        elif candidates_count == 0:
            status = "INVALID_RUN"
            validation_reason = f"LLM duración sospechosa ({duration_ms}ms < {_LLM_MIN_DURATION_MS}ms) y 0 candidatos"

    return {
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "extractable_segments": extractable,
        "candidates_count": candidates_count,
        "source_file": source_file,
        "status": status,
        "validation_reason": validation_reason,
    }


def _save_run_outputs(result: dict, dest_dir: Path, source_id: str, workspace: str) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)

    log_content = (
        f"=== STDOUT ===\n{result['stdout']}\n"
        f"=== STDERR ===\n{result['stderr']}\n"
        f"=== EXIT CODE: {result['exit_code']} ===\n"
        f"=== DURATION: {result['duration_ms']}ms ===\n"
        f"=== STATUS: {result['status']} ===\n"
        f"=== CANDIDATES: {result['candidates_count']} ===\n"
        f"=== EXTRACTABLE SEGMENTS: {result['extractable_segments']} ===\n"
    )
    (dest_dir / "run_log.txt").write_text(log_content, encoding="utf-8")
    (dest_dir / "duration_ms.txt").write_text(str(result["duration_ms"]), encoding="utf-8")
    (dest_dir / "status.txt").write_text(result["status"], encoding="utf-8")

    # Copiar candidates.json si existe
    cands_src = _REPO_ROOT / "output" / "reviews" / workspace / source_id / "candidates.json"
    if cands_src.exists():
        shutil.copy2(cands_src, dest_dir / "candidates.json")


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def run_benchmark(
    manifest_path: Path,
    modes: list[str],
    base_output_dir: Path,
    filter_source_id: str | None = None,
) -> Path:
    if not manifest_path.exists():
        print(f"ERROR: manifest no encontrado: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("sources", [])

    if not sources:
        print("ERROR: el manifest no contiene fuentes ('sources: []')", file=sys.stderr)
        sys.exit(1)

    if filter_source_id:
        sources = [s for s in sources if s.get("id") == filter_source_id]
        if not sources:
            print(f"ERROR: source_id '{filter_source_id}' no encontrado", file=sys.stderr)
            sys.exit(1)

    run_id = _run_id()
    run_dir = base_output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Benchmark S9 Knowledge (modo aislado) ===")
    print(f"  Run ID:    {run_id}")
    print(f"  Commit:    {_git_commit()}")
    print(f"  Fuentes:   {len(sources)}")
    print(f"  Modos:     {modes}")
    print(f"  Seed LLM:  {_BENCHMARK_SEED}")
    print(f"  Output:    {run_dir}")
    print()

    (run_dir / "manifest.json").write_text(
        json.dumps({"sources": sources, "modes": modes, "filter_source_id": filter_source_id,
                    "original_manifest": str(manifest_path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config = _build_configuration(run_id)
    (run_dir / "configuration.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text("{}", encoding="utf-8")
    (run_dir / "report.md").write_text(
        f"# Benchmark {run_id}\n\n_Pendiente de ejecutar benchmark_comparator.py_\n",
        encoding="utf-8",
    )

    summary_rows: list[dict] = []

    for source in sources:
        source_id = source.get("id")
        workspace = source.get("workspace", "leyenda")
        source_file = source.get("file", "")
        print(f"[{source_id}] workspace={workspace} file={source_file}")

        for mode in modes:
            if mode == "heuristic":
                dest_dir = run_dir / "heuristic" / source_id
                print(f"  → heuristic ...", end="", flush=True)
                result = _run_isolated(source, "heuristic", dest_dir)
                _save_run_outputs(result, dest_dir, source_id, workspace)
                print(f" {result['status']} [{result['duration_ms']}ms] cands={result['candidates_count']}")
                summary_rows.append({
                    "source_id": source_id, "source_file": source_file,
                    "mode": "heuristic", "run": 1,
                    "exit_code": result["exit_code"],
                    "duration_ms": result["duration_ms"],
                    "extractable_segments": result["extractable_segments"],
                    "candidates_count": result["candidates_count"],
                    "status": result["status"],
                    "validation_reason": result.get("validation_reason", ""),
                })

            elif mode == "llm":
                for run_n in range(1, _LLM_RUNS + 1):
                    dest_dir = run_dir / f"llm-run-{run_n}" / source_id
                    print(f"  → llm run {run_n}/{_LLM_RUNS} ...", end="", flush=True)
                    result = _run_isolated(source, "llm", dest_dir)
                    _save_run_outputs(result, dest_dir, source_id, workspace)
                    print(f" {result['status']} [{result['duration_ms']}ms] cands={result['candidates_count']}")
                    summary_rows.append({
                        "source_id": source_id, "source_file": source_file,
                        "mode": "llm", "run": run_n,
                        "exit_code": result["exit_code"],
                        "duration_ms": result["duration_ms"],
                        "extractable_segments": result["extractable_segments"],
                        "candidates_count": result["candidates_count"],
                        "status": result["status"],
                        "validation_reason": result.get("validation_reason", ""),
                    })

            elif mode == "hybrid":
                for run_n in range(1, _HYBRID_RUNS + 1):
                    dest_dir = run_dir / f"hybrid-run-{run_n}" / source_id
                    print(f"  → hybrid run {run_n}/{_HYBRID_RUNS} ...", end="", flush=True)
                    result = _run_isolated(source, "hybrid", dest_dir)
                    _save_run_outputs(result, dest_dir, source_id, workspace)
                    print(f" {result['status']} [{result['duration_ms']}ms] cands={result['candidates_count']}")
                    summary_rows.append({
                        "source_id": source_id, "source_file": source_file,
                        "mode": "hybrid", "run": run_n,
                        "exit_code": result["exit_code"],
                        "duration_ms": result["duration_ms"],
                        "extractable_segments": result["extractable_segments"],
                        "candidates_count": result["candidates_count"],
                        "status": result["status"],
                        "validation_reason": result.get("validation_reason", ""),
                    })

        print()

    summary_path = run_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps({"run_id": run_id, "rows": summary_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_ok = sum(1 for r in summary_rows if r["status"] == "OK")
    total_invalid = sum(1 for r in summary_rows if r["status"].startswith("INVALID"))
    total_fail = sum(1 for r in summary_rows if r["status"] == "FAIL")
    print(f"\nBenchmark completado: {total_ok} OK / {total_invalid} INVALID / {total_fail} FAIL")
    print(f"Resultados en: {run_dir}")
    print()
    print("Siguiente paso — comparador de métricas:")
    print(
        f"  python data-engine/app/cli/benchmark_comparator.py"
        f" --run-dir {run_dir}"
        f" --ground-truth-dir tests/fixtures/benchmark/"
    )

    return run_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark aislado reproducible de extractores S9 Knowledge. "
            "Usa segments.classified.json pre-clasificados; llama solo al paso extract. "
            "Nunca define S9K_ALLOW_REAL_INGEST."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--manifest",
        default="tests/fixtures/benchmark/corpus-manifest.json",
    )
    parser.add_argument(
        "--mode",
        choices=["heuristic", "llm", "hybrid", "all"],
        default="all",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark-results",
        dest="output_dir",
    )
    parser.add_argument(
        "--source-id",
        dest="source_id",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview: muestra configuración sin llamar al pipeline",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = _REPO_ROOT / manifest_path

    base_output_dir = Path(args.output_dir)
    if not base_output_dir.is_absolute():
        base_output_dir = _REPO_ROOT / base_output_dir

    modes: list[str] = list(_EXTRACTORS) if args.mode == "all" else [args.mode]

    if args.dry_run:
        print("[DRY-RUN] Configuración del benchmark (no se llama al pipeline):")
        print(f"  manifest:              {manifest_path}")
        print(f"  modos:                 {modes}")
        print(f"  output_dir:            {base_output_dir}/<run_id>/")
        print(f"  source_id (filtro):    {args.source_id or '(todas las fuentes del manifest)'}")
        print(f"  modo:                  aislado (segments.classified.json como input)")
        print(f"  S9K_ALLOW_REAL_INGEST: NUNCA definido por este script")
        print(f"  seed LLM:              {_BENCHMARK_SEED}")
        sys.exit(0)

    run_benchmark(
        manifest_path=manifest_path,
        modes=modes,
        base_output_dir=base_output_dir,
        filter_source_id=args.source_id,
    )


if __name__ == "__main__":
    main()

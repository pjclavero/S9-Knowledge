"""Benchmark runner reproducible para extractores S9 Knowledge.

Ejecuta el pipeline (con --dry-run siempre activo) en un corpus de fuentes
definido por un manifest JSON y captura métricas de duración, exit code y output.

Uso:
  python data-engine/app/cli/extractor_benchmark.py \\
      --manifest tests/fixtures/benchmark/corpus-manifest.json \\
      --mode all \\
      --output-dir benchmark-results

  # Solo una fuente, solo heurístico:
  python data-engine/app/cli/extractor_benchmark.py \\
      --manifest tests/fixtures/benchmark/corpus-manifest.json \\
      --mode heuristic \\
      --source-id transcript_clean_01

NUNCA define S9K_ALLOW_REAL_INGEST=true. El runner siempre ejecuta --dry-run.
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

# Ruta al CLI del pipeline
_PIPELINE_CLI = _CLI_DIR / "data_review.py"

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_LLM_RUNS = 3
_HYBRID_RUNS = 3

# Extractores soportados
_EXTRACTORS = ("heuristic", "llm", "hybrid")


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
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _load_settings() -> dict:
    """Carga settings.yaml como dict (sin dependencia de PyYAML si no está)."""
    settings_path = _REPO_ROOT / "data-engine" / "config" / "settings.yaml"
    try:
        import yaml  # type: ignore
        with settings_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
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
        "ollama": {
            "base_url": ollama_cfg.get("base_url", "http://192.168.1.157:11434"),
            "model": ollama_cfg.get("model", "qwen2.5:7b"),
            "temperature": ollama_cfg.get("temperature", 0),
            "request_timeout": ollama_cfg.get("request_timeout", 900),
        },
        "pipeline_cli": str(_PIPELINE_CLI),
        "dry_run": True,
        "llm_runs": _LLM_RUNS,
        "hybrid_runs": _HYBRID_RUNS,
    }


def _run_pipeline(
    workspace: str,
    source_id: str,
    extractor: str,
    dest_dir: Path,
) -> dict:
    """
    Ejecuta el pipeline para un source+extractor.

    Returns dict con:
      - exit_code
      - duration_ms
      - stdout
      - stderr
      - approved_payload_path (Path | None)
      - quality_report_path  (Path | None)
    """
    # Preparar env limpio: NUNCA poner S9K_ALLOW_REAL_INGEST
    env = os.environ.copy()
    env.pop("S9K_ALLOW_REAL_INGEST", None)  # garantía de seguridad

    cmd = [
        sys.executable,
        str(_PIPELINE_CLI),
        "run",
        "--workspace", workspace,
        "--source-id", source_id,
        "--extractor", extractor,
        "--dry-run",
    ]

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_REPO_ROOT),
            timeout=1800,  # 30 min (cold start LLM ~63s)
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        exit_code = -1
        stdout = ""
        stderr = f"TIMEOUT: {e}"
    except Exception as e:
        exit_code = -2
        stdout = ""
        stderr = f"EXCEPTION: {e}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    # Rutas de output generadas por el pipeline
    out_dir = _REPO_ROOT / "output" / "reviews" / workspace / source_id
    approved_path = out_dir / "approved_payload.json"
    quality_path = out_dir / "quality_report.json"

    return {
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "approved_payload_path": approved_path if approved_path.exists() else None,
        "quality_report_path": quality_path if quality_path.exists() else None,
    }


def _save_run_outputs(result: dict, dest_dir: Path) -> None:
    """Copia los outputs del pipeline al directorio de resultados del benchmark."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Log de ejecución
    log_path = dest_dir / "run_log.txt"
    log_content = (
        f"=== STDOUT ===\n{result['stdout']}\n"
        f"=== STDERR ===\n{result['stderr']}\n"
        f"=== EXIT CODE: {result['exit_code']} ===\n"
        f"=== DURATION: {result['duration_ms']}ms ===\n"
    )
    log_path.write_text(log_content, encoding="utf-8")

    # Duración en fichero separado (fácil de leer desde el comparador)
    (dest_dir / "duration_ms.txt").write_text(
        str(result["duration_ms"]), encoding="utf-8"
    )

    # Copiar outputs del pipeline si existen
    if result.get("approved_payload_path"):
        shutil.copy2(result["approved_payload_path"], dest_dir / "approved_payload.json")
    if result.get("quality_report_path"):
        shutil.copy2(result["quality_report_path"], dest_dir / "quality_report.json")


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def run_benchmark(
    manifest_path: Path,
    modes: list[str],
    base_output_dir: Path,
    filter_source_id: str | None = None,
) -> Path:
    """
    Ejecuta el benchmark completo.

    Returns:
        Path al directorio de la ejecución (base_output_dir/<run_id>/).
    """
    if not manifest_path.exists():
        print(f"ERROR: manifest no encontrado: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("sources", [])

    if not sources:
        print("ERROR: el manifest no contiene fuentes ('sources: []')", file=sys.stderr)
        sys.exit(1)

    # Filtrar por source_id si se especifica
    if filter_source_id:
        sources = [s for s in sources if s.get("id") == filter_source_id]
        if not sources:
            print(
                f"ERROR: source_id '{filter_source_id}' no encontrado en el manifest",
                file=sys.stderr,
            )
            sys.exit(1)

    run_id = _run_id()
    run_dir = base_output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Benchmark S9 Knowledge ===")
    print(f"  Run ID:    {run_id}")
    print(f"  Commit:    {_git_commit()}")
    print(f"  Fuentes:   {len(sources)}")
    print(f"  Modos:     {modes}")
    print(f"  Output:    {run_dir}")
    print()

    # Guardar manifest y configuración en el run_dir
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "sources": sources,
                "modes": modes,
                "filter_source_id": filter_source_id,
                "original_manifest": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    config = _build_configuration(run_id)
    (run_dir / "configuration.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Reservar placeholders para el comparador
    (run_dir / "metrics.json").write_text("{}", encoding="utf-8")
    (run_dir / "report.md").write_text(
        f"# Benchmark {run_id}\n\n_Pendiente de ejecutar benchmark_comparator.py_\n",
        encoding="utf-8",
    )

    # ---------------------------------------------------------------------------
    # Ejecución por fuente y modo
    # ---------------------------------------------------------------------------
    summary_rows: list[dict] = []

    for source in sources:
        source_id = source.get("id")
        workspace = source.get("workspace", "leyenda")
        print(f"[{source_id}] workspace={workspace}")

        for mode in modes:
            if mode == "heuristic":
                dest_dir = run_dir / "heuristic" / source_id
                print(f"  → heuristic ...", end="", flush=True)
                result = _run_pipeline(workspace, source_id, "heuristic", dest_dir)
                _save_run_outputs(result, dest_dir)
                status = "OK" if result["exit_code"] == 0 else f"FAIL(exit={result['exit_code']})"
                print(f" {status} [{result['duration_ms']}ms]")
                summary_rows.append({
                    "source_id": source_id,
                    "mode": "heuristic",
                    "run": 1,
                    "exit_code": result["exit_code"],
                    "duration_ms": result["duration_ms"],
                })

            elif mode == "llm":
                for run_n in range(1, _LLM_RUNS + 1):
                    dest_dir = run_dir / f"llm-run-{run_n}" / source_id
                    print(f"  → llm run {run_n}/{_LLM_RUNS} ...", end="", flush=True)
                    result = _run_pipeline(workspace, source_id, "llm", dest_dir)
                    _save_run_outputs(result, dest_dir)
                    status = "OK" if result["exit_code"] == 0 else f"FAIL(exit={result['exit_code']})"
                    print(f" {status} [{result['duration_ms']}ms]")
                    summary_rows.append({
                        "source_id": source_id,
                        "mode": "llm",
                        "run": run_n,
                        "exit_code": result["exit_code"],
                        "duration_ms": result["duration_ms"],
                    })

            elif mode == "hybrid":
                for run_n in range(1, _HYBRID_RUNS + 1):
                    dest_dir = run_dir / f"hybrid-run-{run_n}" / source_id
                    print(f"  → hybrid run {run_n}/{_HYBRID_RUNS} ...", end="", flush=True)
                    result = _run_pipeline(workspace, source_id, "hybrid", dest_dir)
                    _save_run_outputs(result, dest_dir)
                    status = "OK" if result["exit_code"] == 0 else f"FAIL(exit={result['exit_code']})"
                    print(f" {status} [{result['duration_ms']}ms]")
                    summary_rows.append({
                        "source_id": source_id,
                        "mode": "hybrid",
                        "run": run_n,
                        "exit_code": result["exit_code"],
                        "duration_ms": result["duration_ms"],
                    })

        print()

    # Resumen de ejecución
    summary_path = run_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps({"run_id": run_id, "rows": summary_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_ok = sum(1 for r in summary_rows if r["exit_code"] == 0)
    total_fail = len(summary_rows) - total_ok
    print(f"\nBenchmark completado: {total_ok} OK / {total_fail} FAIL")
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
            "Benchmark reproducible de extractores S9 Knowledge. "
            "Siempre ejecuta el pipeline con --dry-run. "
            "Nunca define S9K_ALLOW_REAL_INGEST."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--manifest",
        default="tests/fixtures/benchmark/corpus-manifest.json",
        help=(
            "Ruta al manifest de corpus JSON "
            "(default: tests/fixtures/benchmark/corpus-manifest.json)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["heuristic", "llm", "hybrid", "all"],
        default="all",
        help="Modo(s) a ejecutar (default: all → heuristic×1 + llm×3 + hybrid×3)",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark-results",
        dest="output_dir",
        help=(
            "Directorio raíz de resultados. "
            "Se crea <output-dir>/<YYYYMMDD-HHMMSS>/ (default: benchmark-results)"
        ),
    )
    parser.add_argument(
        "--source-id",
        dest="source_id",
        default=None,
        help="Ejecutar solo esta fuente (debe existir en el manifest)",
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
        print(f"  S9K_ALLOW_REAL_INGEST: NUNCA definido por este script")
        print(f"  Cada subprocess usa:   --dry-run (obligatorio)")
        sys.exit(0)

    run_benchmark(
        manifest_path=manifest_path,
        modes=modes,
        base_output_dir=base_output_dir,
        filter_source_id=args.source_id,
    )


if __name__ == "__main__":
    main()

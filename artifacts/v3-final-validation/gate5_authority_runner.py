# -*- coding: utf-8 -*-
"""Puerta 5: registro de AUTORIDAD por claim, con proveedores REALES.

Tres escenarios sobre el MISMO corpus, la misma ontologia y el mismo prompt:

* ``C1``  — extractor semantico contra **Ollama local** (qwen2.5:7b);
* ``C2``  — extractor semantico contra **NVIDIA NIM** (llama-3.3-70b-instruct);
* ``D-R`` — **determinista + semantico** pasados por el reconciliador.

Por cada claim se emite el registro YAML del encargo. Ademas se anota, por
ejecucion, lo que hace falta para saber si la medida es creible: modelo real
devuelto por el proveedor, latencia, si el JSON fue valido, cuantos claims y
abstenciones salieron, RAM del proceso y errores.

Los tests de la suite (`tests/test_knowledge_v3_gate5_authority.py`) usan dobles
y sirven de REGRESION. Este guion es la evidencia de que los carriles reales
funcionan de verdad. Los dos hacen falta: un doble no demuestra que Ollama
responda, y una llamada de red no puede vivir en la suite.

NUNCA imprime ni guarda credenciales: del proveedor solo salen modelo, latencia,
codigos de error y recuentos.

Uso:
    set -a; . ~/.config/s9k/nvidia.env; set +a
    S9K_REPO_ROOT=$PWD PYTHONPATH=data-engine/app \
      python3 artifacts/v3-final-validation/gate5_authority_runner.py \
        --scenarios C1,C2,D-R --episodes 6
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import time
from pathlib import Path
from typing import Any

from knowledge_v3.contracts import EvidenceFragment, GameProfile, SourceEpisode
from knowledge_v3.extraction.base import ExtractionContext, ExtractionOutput
from knowledge_v3.extraction.deterministic import DeterministicExtractor
from knowledge_v3.extraction.lexicon import Lexicon, LexiconEntry
from knowledge_v3.extraction.semantic import SemanticEpisodeExtractor
from knowledge_v3.reconcile import ProposalReconciler

import sys

sys.path.insert(0, str(Path(__file__).resolve()))

# Reutiliza perfil/lexico/episodios del runner de la puerta 6: mismo corpus,
# misma ontologia y mismo prompt en los tres escenarios, que es justo lo que la
# puerta 5 exige para que la comparacion signifique algo.
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
from gate6_factivity_runner import (  # noqa: E402
    CORPUS,
    WORKSPACE,
    build_lexicon,
    build_profile,
    episode_for,
)


def rss_mb() -> float:
    """RAM maxima del proceso. Informativo: no condiciona ningun gate."""
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def claim_records(out: ExtractionOutput, scenario: str, provider: str, model: str | None):
    """Registro YAML-izable por claim, tal y como pide el encargo.

    Los campos de decision (`effective_decision`, `shadow_decision`,
    `would_emit_operations`...) se rellenan en la fase de motor; aqui se deja
    explicitamente `null` en vez de inventarlos, porque este guion mide la
    EXTRACCION y la autoridad del proveedor sobre ella.
    """
    rows = []
    for claim in out.claims:
        rows.append(
            {
                "claim_id": claim.claim_id,
                "scenario": scenario,
                "provider": provider,
                "model": model,
                "abstained": bool(claim.abstained),
                "review_required": bool(claim.review_required),
                "evidence_verified": bool(claim.evidence_fragment_ids),
                "evidence_fragment_ids": list(claim.evidence_fragment_ids),
                "predicate_selected": [
                    p.get("predicate") for p in claim.predicate_candidates
                ],
                "direction_selected": [
                    d.get("direction") for d in claim.direction_candidates
                ],
                "negated": bool(claim.negated),
                "negation_kind": (claim.metadata or {}).get("negation_kind", ""),
                "epistemic_status_hint": claim.epistemic_status_hint,
                "confidence": claim.confidence,
                "produced_by_step": claim.produced_by_step,
                # Se rellenan en la fase de motor; no se inventan aqui.
                "effective_decision": None,
                "shadow_decision": None,
                "ignored_findings": None,
                "blocking_findings": None,
                "identity_resolved": None,
                "temporal_status": None,
                "would_emit_operations": None,
                "operation_kinds": None,
            }
        )
    return rows


def run_scenario(name: str, cases: list[dict], profile, lexicon) -> dict[str, Any]:
    started = time.monotonic()
    records: list[dict] = []
    errors: list[dict] = []
    latencies: list[int] = []
    model: str | None = None
    provider = "local"

    semantic = None
    if name in ("C1", "C2", "D-R"):
        if name == "C1":
            from knowledge_v3.extraction.ollama_client import OllamaConfig
            from knowledge_v3.extraction.provider_port import OllamaProviderPort

            port = OllamaProviderPort(config=OllamaConfig(model="qwen2.5:7b"))
            provider = "ollama"
        elif name == "C2":
            from knowledge_v3.extraction.provider_port import NvidiaProviderPort

            port = NvidiaProviderPort()
            provider = "external"
        else:
            from knowledge_v3.extraction.ollama_client import OllamaConfig
            from knowledge_v3.extraction.provider_port import OllamaProviderPort

            port = OllamaProviderPort(config=OllamaConfig(model="qwen2.5:7b"))
            provider = "ollama+local"
        semantic = SemanticEpisodeExtractor(port)
        model = getattr(port, "model", None)

    for case in cases:
        episode, frags = episode_for(case["case_id"], case["text"])
        ctx = ExtractionContext(
            workspace=WORKSPACE,
            episodes=[episode],
            fragments=frags,
            profile=profile,
            lexicon=lexicon,
        )
        t0 = time.monotonic()
        try:
            sem_out = semantic.extract_episode(ctx, episode)
            if name == "D-R":
                det_out = DeterministicExtractor().extract_episode(ctx, episode)
                combined = ExtractionOutput(
                    mentions=tuple(list(det_out.mentions) + list(sem_out.mentions)),
                    claims=tuple(list(det_out.claims) + list(sem_out.claims)),
                )
                combined.diagnostics.extend(det_out.diagnostics)
                combined.diagnostics.extend(sem_out.diagnostics)
                out = ProposalReconciler().reconcile(combined)
            else:
                out = sem_out
        except Exception as exc:  # noqa: BLE001 - se registra el tipo, jamas el secreto
            errors.append({"case_id": case["case_id"], "error": type(exc).__name__})
            continue
        latencies.append(int((time.monotonic() - t0) * 1000))
        records.extend(claim_records(out, name, provider, model))

    runs = [
        {
            "episode_id": r.episode_id,
            "ok": r.ok,
            "model": r.model,
            "latency_ms": r.latency_ms,
            "calls": r.calls,
            "json_retries": r.json_retries,
            "claims": r.claims,
            "abstentions": r.abstentions,
            "error": r.error,
        }
        for r in (semantic.runs if semantic else ())
    ]
    ordered = sorted(latencies)
    return {
        "scenario": name,
        "provider": provider,
        "model": model,
        "episodes": len(cases),
        "claims_recorded": len(records),
        "abstentions": len([r for r in records if r["abstained"]]),
        "json_valid_runs": len([r for r in runs if r["ok"]]),
        "runs": runs,
        "records": records,
        "errors": errors,
        "latency_ms": (
            {
                "min": ordered[0],
                "median": ordered[len(ordered) // 2],
                "max": ordered[-1],
                "mean": int(sum(ordered) / len(ordered)),
            }
            if ordered
            else None
        ),
        "wall_seconds": round(time.monotonic() - started, 1),
        "max_rss_mb": rss_mb(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default="C1,C2,D-R")
    parser.add_argument("--episodes", type=int, default=6)
    parser.add_argument("--out", default="artifacts/v3-final-validation")
    args = parser.parse_args()

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    # Muestra ESTRATIFICADA: un caso por familia hasta agotar el cupo. Coger los
    # N primeros daria diez hechos afirmados seguidos y ninguna pregunta.
    by_family: dict[str, list[dict]] = {}
    for case in corpus["cases"]:
        by_family.setdefault(case["family"], []).append(case)
    cases: list[dict] = []
    round_index = 0
    while len(cases) < args.episodes:
        added = False
        for family in sorted(by_family):
            if round_index < len(by_family[family]) and len(cases) < args.episodes:
                cases.append(by_family[family][round_index])
                added = True
        if not added:
            break
        round_index += 1

    profile, lexicon = build_profile(), build_lexicon()
    result: dict[str, Any] = {
        "gate": "5",
        "generated_by": "opus-gate5",
        "corpus": {"path": str(CORPUS), "episodes": len(cases),
                   "sampling": "estratificada por familia"},
        "environment": {
            "ollama_host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            "nvidia_configured": bool(os.environ.get("S9K_NVIDIA_API_KEY")),
        },
        "scenarios": {},
    }
    for scenario in [s.strip() for s in args.scenarios.split(",") if s.strip()]:
        print(f"[gate5] escenario {scenario}...", flush=True)
        result["scenarios"][scenario] = run_scenario(scenario, cases, profile, lexicon)
        info = result["scenarios"][scenario]
        print(
            f"[gate5] {scenario}: {info['claims_recorded']} claims, "
            f"{info['abstentions']} abstenciones, {info['wall_seconds']}s",
            flush=True,
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "gate5-authority.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    print(f"[gate5] escrito {target}")


if __name__ == "__main__":
    main()

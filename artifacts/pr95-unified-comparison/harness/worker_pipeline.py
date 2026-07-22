# -*- coding: utf-8 -*-
"""Worker de la PISTA PIPELINE (evidencia heuristica) para la comparativa PR#95.

Se ejecuta DENTRO del worktree de una version concreta (cwd = <wt>/data-engine/app),
con el `relations` de ESA version en sys.path. Lee un job JSON por stdin y emite,
por stdout, las predicciones planas producidas por el pipeline REAL de la version.

NO calcula metricas: el matching y las metricas los hace el orquestador con UNA
sola vara (los modulos matching/metrics de la base), para que la comparacion sea
homogenea. Aqui solo se ejecuta el pipeline de la version con SU flag activado.

Contrato de entrada (stdin JSON):
  {
    "corpus_dir": "<ruta absoluta al corpus C1>",
    "config_overrides": { ... campos de PipelineConfig propios de la version ... },
    "source_ids": [opcional] lista de fuentes a procesar
  }

Contrato de salida (stdout JSON):
  {
    "predictions": [ ...extract_predictions... ],
    "timings": [ {"source_id","elapsed_ms"} ],
    "result_hashes": { source_id: hash },
    "config_effective": { ...to_dict... },
    "providers_offline": bool,   # local_llm_enabled==False and external_ai_enabled==False
    "n_sources": int
  }

Seguridad: NO se inyecta transporte ni proveedor => run_pipeline JAMAS abre red ni
llama a Ollama/NVIDIA. Se verifica que la config efectiva tiene ambos flags en False.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

# El cwd debe ser <wt>/data-engine/app; garantizamos que ese dir esta en sys.path.
sys.path.insert(0, str(Path.cwd()))

from relations.benchmark import runner  # noqa: E402
from relations.pipeline import PipelineConfig, run_pipeline  # noqa: E402


def main() -> None:
    job = json.loads(sys.stdin.read())
    corpus_dir = Path(job["corpus_dir"])
    overrides = job.get("config_overrides", {})
    source_ids = job.get("source_ids")

    corpus = runner.load_corpus(corpus_dir, verify=True)
    # Config base = preset offline baseline1 (context_mode="sentence"), + overrides
    # propios de la version (evidence_anchor_mode / hybrid_*). Proveedores OFF.
    base_cfg = runner._config_for_mode("baseline1")
    cfg = dataclasses.replace(base_cfg, **overrides)

    # Verificacion dura de offline ANTES de ejecutar nada.
    assert cfg.local_llm_enabled is False, "local_llm debe estar OFF"
    assert cfg.external_ai_enabled is False, "external_ai debe estar OFF"

    ids = runner.select_sources(corpus, source_ids)
    predictions: list[dict] = []
    timings: list[dict] = []
    result_hashes: dict[str, str] = {}

    for sid in ids:
        text = corpus.sources[sid]
        workspace = corpus.workspace_by_source[sid]
        entities, _notes = runner.derive_entities(sid, text, corpus.relations)
        payload = runner.build_payload(sid, text, workspace, entities)
        t0 = time.perf_counter()
        # SIN local_transport / external_provider => sin red, sin proveedores.
        output = run_pipeline(payload, config=cfg,
                              local_transport=None, external_provider=None)
        elapsed = (time.perf_counter() - t0) * 1000.0
        preds = runner.extract_predictions(output)
        predictions.extend(preds)
        timings.append({"source_id": sid, "elapsed_ms": round(elapsed, 4)})
        result_hashes[sid] = output.get("result_hash")

    out = {
        "predictions": predictions,
        "timings": timings,
        "result_hashes": result_hashes,
        "config_effective": cfg.to_dict(),
        "providers_offline": (not cfg.local_llm_enabled) and (not cfg.external_ai_enabled),
        "n_sources": len(ids),
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UNA sola pasada de la cadena: informe del arnes + recuento por etapa.

Existe para no pagar dos veces la misma tanda contra el modelo. `runner.py` da el
informe del arnes y `v3_stage_counts.py` da el recuento por etapa; contra Ollama
real cada pasada cuesta minutos por episodio, asi que aqui se hace una sola y se
escriben los dos artefactos.

    export PYTHONPATH=data-engine/app
    python3 scripts/dev/v3_chain_report.py local_only dev-local_only-chain
    python3 scripts/dev/v3_chain_report.py local_plus_external dev-lpe-chain --ollama

Split cableado a `dev`. Writer en dry-run: no se pasa driver.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-engine" / "app"))

from knowledge_v3.benchmarks.harness import run as score
from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.benchmarks.matching import MatchConfig
from knowledge_v3.benchmarks.report import to_json, to_markdown
from knowledge_v3.pipeline import KnowledgePipeline, cases_from_gold, catalog_entries
from knowledge_v3.pipeline.bridge import entities_from_catalog
from knowledge_v3.pipeline.bundle import to_bundle
from knowledge_v3.pipeline.runner import build_config

ablation = sys.argv[1]
stem = sys.argv[2]
client = None
if "--ollama" in sys.argv:
    from knowledge_v3.extraction.ollama_client import OllamaClient, OllamaConfig
    client = OllamaClient(config=OllamaConfig.from_env())

gold = load_gold("dev")
cfg = build_config(gold, ablation=ablation, workspace="bench-dev", ollama_client=client)
p = KnowledgePipeline(cfg)
res = p.run(cases_from_gold(gold, entry="episodes"),
            catalog_entities=entities_from_catalog(catalog_entries(gold)))

bundle = to_bundle(res, split="dev", run_id=f"dev-{ablation}-chain", ablation=ablation,
                   extra_metadata={"entry": "episodes", "engine_isolated": False})
report = score(gold, bundle, config=MatchConfig(symmetric_predicates=gold.symmetric_predicates),
               ablation=ablation)

out = Path("docs/v3/measurements/runs")
out.mkdir(parents=True, exist_ok=True)
(out / f"{stem}.json").write_text(to_json(report), encoding="utf-8")
(out / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")

tot = res.summary()["totals"]
claims = res.claims
activos = [c for c in claims if not c.abstained]
dec = res.decisions
kind = lambda c: (c.metadata or {}).get("negation_kind", "")
etapas = {
    "ablation": ablation,
    "config": res.config_declared,
    "etapas": {
        "episodios": tot["episodes"], "fragmentos": tot["fragments"],
        "menciones": tot["mentions"], "claims_extraidos": tot["claims"],
        "claims_activos": len(activos), "claims_abstenidos": len(claims) - len(activos),
        "resoluciones": tot["resolutions"], "decisiones_del_motor": tot["decisions"],
        "ACCEPT": sum(1 for d in dec if d.decision == "ACCEPT"),
        "REVIEW": sum(1 for d in dec if d.decision == "REVIEW"),
        "ABSTAIN": sum(1 for d in dec if d.decision == "ABSTAIN"),
        "REJECT_INVALID": sum(1 for d in dec if d.decision == "REJECT_INVALID"),
        "afirmaciones": tot["assertions"], "planes": tot["plans"],
        "planes_aprobados": tot["approved_plans"],
        "entradas_de_ledger": tot["ledger_entries"],
    },
    "fuentes_paradas": [{"source": r.source_id, "stage": r.stopped_at, "reason": r.stop_reason}
                        for r in res.runs if r.stopped_at],
    "negacion": {
        "claims_negados": sum(1 for c in activos if c.negated),
        "tipos": {k: sum(1 for c in activos if kind(c) == k)
                  for k in ("SIMPLE", "NEVER", "CESSATION", "NOT_YET", "SCOPE_AMBIGUOUS")},
        "decisiones_negadas": sum(1 for d in dec if d.negated),
        "cierres_de_vigencia_propuestos": sum(1 for d in dec if d.supersedes is not None),
        "afirmaciones_negativas": sum(1 for a in res.assertions if a.negated),
    },
    "latency_ms": round(res.latency_ms, 1),
    "provider_calls": res.provider_calls,
    "diagnosticos": sorted({d["code"] for r in res.runs for d in r.diagnostics}),
}
(out / f"etapas-{ablation}.json").write_text(
    json.dumps(etapas, ensure_ascii=False, indent=1), encoding="utf-8")
print("OK", stem)

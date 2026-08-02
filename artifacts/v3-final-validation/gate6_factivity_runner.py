# -*- coding: utf-8 -*-
"""Puerta 6: mide el corpus de no-factividad contra los carriles REALES.

Cuatro carriles sobre las MISMAS 100 frases:

* ``policy``   — politica de factualidad sola (`cues.analyze_raw_text`), sin
  extractor: dice que clase de factualidad lee el sistema en el texto;
* ``det``      — extractor DETERMINISTA completo;
* ``ollama``   — extractor SEMANTICO contra Ollama local (qwen2.5:7b), REAL;
* ``nvidia``   — extractor SEMANTICO contra NVIDIA NIM, REAL;
* ``combined`` — determinista + semantico pasados por el RECONCILIADOR.

Por frase y carril se registra: `factivity_class`, `policy_action`,
`world_claims`, `epistemic_proposals`, `diagnostics` y `abstentions`.

TRAMPA QUE ESTE GUION EVITA A PROPOSITO
---------------------------------------
El gate "0 hechos del mundo en preguntas" lo aprueba trivialmente un sistema que
no extrae NADA de ninguna frase. Por eso el corpus lleva controles positivos
(HECHO_AFIRMADO, NEGACION_FACTUAL) y el guion construye un lexico que cubre las
entidades del corpus: si los controles no producen hechos, el resultado se marca
VACUO y ningun gate puede darse por bueno. Un verde por inanicion no es un verde.

El lexico y el perfil son ARTEFACTOS DE MEDIDA, no gold: viven aqui, no en
`benchmarks/datasets/`, y no se cargan en ninguna suite.

Uso:
    set -a; . ~/.config/s9k/nvidia.env; set +a
    PYTHONPATH=data-engine/app python3 artifacts/v3-final-validation/gate6_factivity_runner.py \
        --lanes policy,det,combined,ollama,nvidia --out artifacts/v3-final-validation

Nunca imprime ni guarda credenciales: del proveedor solo salen modelo, latencia
y codigos de error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from knowledge_v3.contracts import EvidenceFragment, GameProfile, SourceEpisode
from knowledge_v3.extraction.base import ExtractionContext, ExtractionOutput
from knowledge_v3.extraction.cues import analyze_raw_text
from knowledge_v3.extraction.deterministic import DeterministicExtractor
from knowledge_v3.extraction.lexicon import Lexicon, LexiconEntry
from knowledge_v3.extraction.semantic import SemanticEpisodeExtractor
from knowledge_v3.reconcile import ProposalReconciler

WORKSPACE = "factivity-bench"
CONTRACT_VERSION = "1.0.0"
CORPUS = Path("data-engine/app/knowledge_v3/benchmarks/datasets/factivity/cases.json")


def h(seed: str) -> dict[str, str]:
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


def trace(step: str, produced: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "step": step,
            "provider": "local",
            "name": "s9k.gate6.runner",
            "version": "3.0.0",
            "model": None,
            "produced": list(produced),
        }
    ]


# --------------------------------------------------------------------------
# Perfil y lexico de medida: cubren las entidades REALES del corpus
# --------------------------------------------------------------------------
#: (superficie, tipo). Sacadas del propio corpus; sin esto el determinista no
#: encuentra menciones y todo abstendria por inanicion.
ENTITIES: tuple[tuple[str, str], ...] = (
    ("Toturi", "Character"),
    ("Harun Vell", "Character"),
    ("Sira Delantre", "Character"),
    ("Olmo Quiral", "Character"),
    ("Nerea Tossa", "Character"),
    ("Beltrán Osk", "Character"),
    ("Mira Cauce", "Character"),
    ("Teo Ravasi", "Character"),
    ("Ilde Varona", "Character"),
    ("Dagna Hoill", "Character"),
    ("Kaspar Nune", "Character"),
    ("Runa Belisa", "Character"),
    ("Pol Arriaga", "Character"),
    ("Noa Quimper", "Character"),
    ("Hugo Marlén", "Character"),
    ("Clan del León", "Faction"),
    ("Casa Verrant", "Faction"),
    ("Casa del Ciervo", "Faction"),
    ("Consejo de Umbra", "Faction"),
    ("Consejo de los Vientos", "Faction"),
    ("Cónclave de la Ceniza", "Faction"),
    ("Gremio de Fundidores", "Faction"),
    ("Orden de la Obsidiana", "Faction"),
    ("Hermandad de la Fumarola", "Faction"),
    ("Compañía del Arrecife", "Faction"),
    ("Cofradía de las Velas", "Faction"),
    ("Junta de Astilleros", "Faction"),
    ("Sociedad de Aerostatos", "Faction"),
    ("Puerto Escoria", "Location"),
    ("Isla Tenaza", "Location"),
    ("Foso Humeante", "Location"),
    ("Muelle Alto", "Location"),
    ("Torre Anemos", "Location"),
    ("Yunque Negro", "Object"),
    ("Sello de Lava", "Object"),
    ("Carta de Fletes", "Object"),
)

PREDICATES = [
    {"predicate": "MEMBER_OF", "domain": ["Character"], "range": ["Faction"]},
    {"predicate": "LEADS", "domain": ["Character"], "range": ["Faction"]},
    {"predicate": "SERVES", "domain": ["Character"], "range": ["Faction"]},
    {"predicate": "ALLY_OF", "domain": ["Character", "Faction"], "range": ["Character", "Faction"]},
    {"predicate": "OWES_TO", "domain": ["Character", "Faction"], "range": ["Character", "Faction"]},
    {"predicate": "LOCATED_IN", "domain": ["Character", "Object", "Location"], "range": ["Location"]},
    {"predicate": "OWNS", "domain": ["Character", "Faction"], "range": ["Object"]},
]


def build_profile() -> GameProfile:
    return GameProfile.from_dict(
        {
            "contract_id": GameProfile.CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "workspace": WORKSPACE,
            "source_asset_id": "profile:factivity",
            "source_hash": h("profile:factivity"),
            "provider_trace": trace("profile.load", ("predicates",)),
            "produced_by_step": "profile.load",
            "profile_id": "generic",
            "profile_version": "1.0.0",
            "core_ontology_version": "core-1.4.0",
            "entity_types": ["Character", "Location", "Faction", "Object", "Event", "Concept"],
            "predicates": [
                {
                    "symmetric": p["predicate"] == "ALLY_OF",
                    "transitive": False,
                    "functional": False,
                    "inverse_of": None,
                    **p,
                }
                for p in PREDICATES
            ],
            "aliases": [],
            "titles": [],
            "factions": [n for n, t in ENTITIES if t == "Faction"],
            "calendars": [],
            "identity_rules": [],
            "ambiguous_terms": [],
            "source_priorities": [],
            "evaluation_examples": [],
        }
    )


def build_lexicon() -> Lexicon:
    return Lexicon(
        [LexiconEntry(name, kind, (), 0.9, "glossary") for name, kind in ENTITIES]
    )


def episode_for(case_id: str, text: str) -> tuple[SourceEpisode, list[EvidenceFragment]]:
    episode_id = f"episode:{case_id}"
    episode = SourceEpisode.from_dict(
        {
            "contract_id": SourceEpisode.CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "workspace": WORKSPACE,
            "source_asset_id": "asset:factivity",
            "source_hash": h("asset:factivity"),
            "provider_trace": trace("pdf.text", ("text",)),
            "produced_by_step": "pdf.text",
            "episode_id": episode_id,
            "asset_id": "asset:factivity",
            "sequence": 1,
            "modality": "TEXT",
            "text": text,
            "page": 1,
            "bbox": None,
            "time_start": None,
            "time_end": None,
            "previous_episode_id": None,
            "next_episode_id": None,
            "speaker": None,
            "turn": None,
            "table": None,
            "quality": {"score": 0.95, "flags": []},
            "content_hash": h(episode_id),
        }
    )
    fragment = EvidenceFragment.from_dict(
        {
            "contract_id": EvidenceFragment.CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "workspace": WORKSPACE,
            "source_asset_id": "asset:factivity",
            "source_hash": h("asset:factivity"),
            "provider_trace": trace("anchor", ("literal_text",)),
            "produced_by_step": "anchor",
            "fragment_id": f"fragment:{case_id}:0",
            "episode_id": episode_id,
            "literal_text": text,
            "normalized_text": text.lower(),
            "start": 0,
            "end": len(text),
            "bbox": None,
            "time_start": None,
            "time_end": None,
            "frame_id": None,
            "page": 1,
            "media_type": "EMBEDDED_TEXT",
            "confidence": 0.95,
        }
    )
    return episode, [fragment]


# --------------------------------------------------------------------------
# Resumen de una salida de extraccion
# --------------------------------------------------------------------------
def summarize(out: ExtractionOutput) -> dict[str, Any]:
    """Cuenta lo que de verdad importa para la puerta.

    `world_claims` es la cifra vinculante: un claim NO abstenido cuenta como
    hecho del mundo que el sistema propone escribir. Se separa el positivo del
    negativo porque negar un hecho SI es informacion del mundo, y el corpus lo
    exige en NEGACION_FACTUAL.
    """
    claims = list(out.claims)
    active = [c for c in claims if not c.abstained]
    positives = [c for c in active if not c.negated]
    negatives = [c for c in active if c.negated]
    abstentions = [c for c in claims if c.abstained]
    return {
        "world_claims": len(positives),
        "negated_world_claims": len(negatives),
        "epistemic_proposals": len(
            [c for c in active if c.epistemic_status_hint not in ("ASSERTED", "")]
        ),
        "diagnostics": len(out.diagnostics),
        "abstentions": len(abstentions),
        "claim_ids": [c.claim_id for c in claims],
        "predicates": sorted(
            {p.get("predicate") for c in active for p in c.predicate_candidates if p.get("predicate")}
        ),
        "diagnostic_codes": sorted({d.code for d in out.diagnostics}),
    }


def policy_row(text: str) -> dict[str, Any]:
    verdict = analyze_raw_text(text)
    fact = verdict.factivity
    return {
        "factivity_class": fact.factivity_class.value,
        "policy_action": fact.action.value,
        "scope": fact.scope,
        "negated": verdict.negated,
        "negation_kind": verdict.negation_kind,
        "hint": verdict.hint,
        "reason_codes": sorted(verdict.reason_codes),
    }


# --------------------------------------------------------------------------
# Carriles
# --------------------------------------------------------------------------
def run_lane(lane: str, cases: list[dict], profile, lexicon, port_factory) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    errors: list[dict] = []
    latencies: list[int] = []
    model_seen: str | None = None
    extractor = None
    if lane == "det":
        extractor = DeterministicExtractor()
    elif lane in ("ollama", "nvidia"):
        extractor = SemanticEpisodeExtractor(port_factory())
        model_seen = getattr(extractor.port, "model", None)
    elif lane == "combined":
        extractor = DeterministicExtractor()

    started_lane = time.monotonic()
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
            if lane == "combined":
                det_out = DeterministicExtractor().extract_episode(ctx, episode)
                merged = ProposalReconciler().reconcile(det_out)
                out = merged
            else:
                out = extractor.extract_episode(ctx, episode)
        except Exception as exc:  # noqa: BLE001 - se registra el tipo, nunca el secreto
            errors.append({"case_id": case["case_id"], "error": type(exc).__name__})
            rows[case["case_id"]] = {"error": type(exc).__name__}
            continue
        latencies.append(int((time.monotonic() - t0) * 1000))
        rows[case["case_id"]] = summarize(out)

    out_lane: dict[str, Any] = {
        "lane": lane,
        "rows": rows,
        "errors": errors,
        "wall_seconds": round(time.monotonic() - started_lane, 1),
    }
    if latencies:
        ordered = sorted(latencies)
        out_lane["latency_ms"] = {
            "min": ordered[0],
            "median": ordered[len(ordered) // 2],
            "max": ordered[-1],
            "mean": int(sum(ordered) / len(ordered)),
        }
    if model_seen:
        out_lane["model"] = model_seen
    return out_lane


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lanes", default="policy,det,combined")
    parser.add_argument("--out", default="artifacts/v3-final-validation")
    parser.add_argument("--limit", type=int, default=0, help="0 = corpus entero")
    parser.add_argument(
        "--stratified",
        action="store_true",
        help="con --limit, reparte la muestra entre familias en vez de coger las N primeras",
    )
    parser.add_argument("--tag", default="", help="sufijo del fichero de salida")
    args = parser.parse_args()

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = corpus["cases"]
    if args.limit and args.stratified:
        # Un caso de cada familia antes de repetir ninguna. Coger las N primeras
        # daria diez hechos afirmados seguidos y ni una sola pregunta, que es
        # justo lo que la puerta mide.
        by_family: dict[str, list[dict]] = {}
        for case in cases:
            by_family.setdefault(case["family"], []).append(case)
        picked: list[dict] = []
        depth = 0
        while len(picked) < args.limit:
            added = False
            for family in sorted(by_family):
                if depth < len(by_family[family]) and len(picked) < args.limit:
                    picked.append(by_family[family][depth])
                    added = True
            if not added:
                break
            depth += 1
        cases = picked
    elif args.limit:
        cases = cases[: args.limit]

    profile, lexicon = build_profile(), build_lexicon()
    lanes = [lane.strip() for lane in args.lanes.split(",") if lane.strip()]
    result: dict[str, Any] = {
        "gate": "6",
        "corpus": {
            "path": str(CORPUS),
            "split": corpus["split"],
            "provenance": corpus["provenance"],
            "cases": len(cases),
        },
        "generated_by": "opus-gate6",
        "lanes": {},
    }

    if "policy" in lanes:
        result["lanes"]["policy"] = {
            "lane": "policy",
            "rows": {c["case_id"]: policy_row(c["text"]) for c in cases},
        }
        lanes = [lane for lane in lanes if lane != "policy"]

    def ollama_port():
        from knowledge_v3.extraction.ollama_client import OllamaConfig
        from knowledge_v3.extraction.provider_port import OllamaProviderPort

        return OllamaProviderPort(config=OllamaConfig(model="qwen2.5:7b"))

    def nvidia_port():
        from knowledge_v3.extraction.provider_port import NvidiaProviderPort

        return NvidiaProviderPort()

    factories = {"ollama": ollama_port, "nvidia": nvidia_port}
    for lane in lanes:
        print(f"[gate6] carril {lane}...", flush=True)
        result["lanes"][lane] = run_lane(
            lane, cases, profile, lexicon, factories.get(lane, lambda: None)
        )
        print(f"[gate6] carril {lane} listo", flush=True)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"gate6-raw-lanes{args.tag}.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    print(f"[gate6] escrito {target}")


if __name__ == "__main__":
    main()

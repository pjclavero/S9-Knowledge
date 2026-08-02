# -*- coding: utf-8 -*-
"""Sonda del PLANNER ejecutada en procesos nuevos para verificar PYTHONHASHSEED.

Hermana de `reconcile_hashseed_probe.py`, pero sobre el artefacto que de verdad
llega al grafo: el `GraphMutationPlan`.

Importa porque el plan se SELLA. `plan_hash`, `decision_hash` e
`idempotency_key` se derivan de la serializacion del plan, y el operador
confirma el `plan_hash` a mano antes de un apply. Si el orden de iteracion de un
`set` o un `dict` se colase en esa serializacion, dos procesos con distinta
semilla firmarian el mismo plan con hashes distintos: la confirmacion del
operador dejaria de significar nada y la idempotencia se romperia entre
reinicios.

Se imprime UN solo sha256 por ejecucion. El test compara esa salida entre
semillas; cualquier diferencia es un fallo de reproducibilidad.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_v3.engine import DEFAULT_CONFIG  # noqa: E402
from knowledge_v3.engine.ontology import ProfileIndex  # noqa: E402
from knowledge_v3.engine.planner import PlanContext, build_plan  # noqa: E402

from test_knowledge_v3_engine_gold import (  # noqa: E402,I100
    ASSET_ID,
    COLLECTION_ID,
    NOW,
    ONTOLOGY,
    PROFILE_ID,
    SOURCE_HASH,
    WORKSPACE,
    claim,
    profile,
    run,
    snapshot,
    vigente,
)


def _context(snap) -> PlanContext:
    return PlanContext(
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=SOURCE_HASH,
        collection_id=COLLECTION_ID,
        game_profile=PROFILE_ID,
        ontology_version=ONTOLOGY,
        snapshot=snap,
        now=NOW,
    )


def _scenarios():
    """Escenarios deterministas que cubren las ramas del planner.

    Positivo simple, negativo (sin proyeccion), cesacion (con supersesion) y un
    lote de varios claims — que es donde un orden de iteracion inestable tendria
    mas sitio para colarse.
    """
    positive = claim()
    negative = claim(
        claim_id="claim:gold:neg",
        negated=True,
        metadata={"negation_kind": "SIMPLE"},
        evidence_fragment_ids=["fragment:gold:1"],
        object_mentions=["mention:consejo"],
        predicate_candidates=[{"predicate": "SERVES", "confidence": 0.84}],
        relation_phrase="jamas sirvio al",
    )
    cessation = claim(
        claim_id="claim:gold:cese",
        negated=True,
        metadata={"negation_kind": "CESSATION"},
        evidence_fragment_ids=["fragment:gold:1"],
    )
    plain = snapshot()
    with_active = snapshot([vigente()])

    yield "positivo", [positive], plain
    yield "negativo", [negative], plain
    yield "cesacion", [cessation], with_active
    yield "lote", [positive, negative], plain


def canonical_result() -> bytes:
    payload = {}
    for name, claims, snap in _scenarios():
        decisions = run(claims, snap=snap).decisions
        build = build_plan(_context(snap), decisions, ProfileIndex(profile()), DEFAULT_CONFIG)
        payload[name] = {
            "plan": build.plan.to_dict() if build.plan else None,
            "assertions": [a.to_dict() for a in build.assertions],
            "validator_chain": list(build.validator_chain),
        }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


if __name__ == "__main__":
    print(hashlib.sha256(canonical_result()).hexdigest())

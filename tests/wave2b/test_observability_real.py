# -*- coding: utf-8 -*-
"""Q — observabilidad/trazabilidad REAL (`relations.observability`).

Cubre:
  * Punto 12: "dry-run genera escritura". Las capas disponibles del pipeline NO
    escriben a disco: se ejercita `observability` (eventos/trazas), el evaluador
    LOCAL real y el analizador sintactico real con `builtins.open` MINADO; cero
    aperturas de escritura. Como R8 (el pipeline de escritura en Neo4j) aun no
    existe, se documenta que esta comprobacion debe EXTENDERSE a esa capa cuando
    se integre (ver docs/coordination/wave2b/qa-lote2-matrix.md).
  * Punto 3 (capa de redaccion): un secreto inyectado en un evento NO aparece en
    `to_dict`/`to_json`; se sustituye por su hash/placeholder.

Importa el modulo REAL: no reimplementa la observabilidad.
"""
from __future__ import annotations

import builtins
import json

import pytest

from relations.observability import (
    ComponentResult,
    RelationEvent,
    RelationTrace,
    find_secrets,
    redact,
)

FAKE_KEY = "nvapi-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"


def _event(**over):
    base = dict(
        execution_id="exec-1", document_id="doc-1", workspace="ws-alpha",
        component="consensus", version="relation-consensus-1.0.0",
        result=ComponentResult.OK,
    )
    base.update(over)
    return RelationEvent(**base).validate()


# ---------------------------------------------------------------------------
# Control: evento valido serializa de forma determinista.
# ---------------------------------------------------------------------------
def test_event_roundtrip_deterministic():
    ev = _event(num_pairs=3, duration=0.01)
    j1 = ev.to_json()
    ev2 = RelationEvent.from_dict(json.loads(j1))
    assert ev2.to_json() == j1


# ---------------------------------------------------------------------------
# Punto 3 (redaccion): el secreto no viaja en claro en la traza.
# ---------------------------------------------------------------------------
def test_secret_is_redacted_in_event_output():
    ev = _event(
        provider_status={"authorization": f"Bearer {FAKE_KEY}"},
        errors=[f"fallo con api_key={FAKE_KEY}"],
        sample_text=f"texto con {FAKE_KEY} dentro",
        synthetic=True,
    )
    dumped = ev.to_json()
    assert FAKE_KEY not in dumped
    assert find_secrets(FAKE_KEY)  # el detector real reconoce la forma


# ---------------------------------------------------------------------------
# MUTATION 12 (punto 12): las capas disponibles NO escriben (cero `open` de escritura).
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_layers_perform_zero_writes(monkeypatch):
    """La ausencia de escritura es load-bearing en las capas de sombra/consenso.

    Mutacion: si alguna capa volcara un "artefacto dry-run" a disco, abriria un
    fichero en modo escritura. Aqui `builtins.open` esta minado para CUALQUIER
    modo de escritura ('w','a','x','+') y ABORTA. Las capas reales (observability,
    LLM local sombra, sintaxis) no escriben. Nota: R8 (escritura en Neo4j) aun no
    existe; esta comprobacion debe EXTENDERSE al pipeline de escritura cuando se
    integre.
    """
    real_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"escritura prohibida en modo sombra/consenso: open({file!r}, {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guarded_open)

    # (a) observability: eventos/trazas se serializan en memoria, sin escribir.
    trace = RelationTrace(execution_id="exec-1")
    trace.record(document_id="doc-1", workspace="ws-alpha", component="pairs",
                 version="v1", result=ComponentResult.OK, num_pairs=2)
    assert json.loads(trace.to_json())["execution_id"] == "exec-1"

    # (b) evaluador LOCAL real (modo sombra): evalua sin escribir cache/ficheros.
    import json as _json
    from relations.local_llm_shadow import (
        LocalLLMConfig, RelationEvalInput, evaluate_relation_local,
    )
    doc = "Bayushi Hisao juro lealtad al Clan Escorpion."
    ev = "juro lealtad al Clan Escorpion"
    rel = {"predicate": "MEMBER_OF", "direction": "SUBJECT_TO_OBJECT", "confidence": 0.9,
           "evidence_text": ev, "evidence_start": doc.find(ev), "evidence_end": doc.find(ev) + len(ev),
           "negated": False, "temporal_scope": None, "epistemic_status": "ASSERTED",
           "subject_type": "Character", "object_type": "Faction"}

    def _transport(messages):
        return ({"choices": [{"message": {"content": _json.dumps({"relations": [rel]})}}]}, 5)

    rec = evaluate_relation_local(
        RelationEvalInput(document=doc, subject_id="Bayushi Hisao", object_id="Clan Escorpion",
                          template_id="membership", subject_type="Character",
                          object_type="Faction", workspace="leyenda"),
        config=LocalLLMConfig(model="ollama/llama3", transport=_transport),
    )
    assert rec.shadow is True

    # (c) sintaxis real: analiza sin escribir nada.
    from relations import syntax
    assert syntax.analyze("Akodo lidera el Clan.").provider == "heuristic"


# ---------------------------------------------------------------------------
# redact es recursivo y no expone claves sensibles ni con clave anidada.
# ---------------------------------------------------------------------------
def test_redact_recursive_on_nested_structures():
    payload = {"headers": {"Authorization": f"Bearer {FAKE_KEY}"},
               "items": [f"token={FAKE_KEY}", "ok"]}
    red = redact(payload)
    assert FAKE_KEY not in json.dumps(red, ensure_ascii=False)

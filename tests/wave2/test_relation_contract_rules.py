"""Q — reglas del contrato REAL de relaciones (`relations.contracts`).

Importa `RelationCandidate` de la implementación fusionada (A1) y comprueba sus
invariantes de seguridad. El MUTATION check demuestra que la regla de `workspace`
es load-bearing: el validador real la rechaza, y un documento por lo demás válido
SÍ se acepta (si se relajara la regla, el documento inválido pasaría).
"""
from __future__ import annotations

import json

import pytest

from relations.contracts import RelationCandidate, RelationContractError


def _valid_relation() -> dict:
    return {
        "subject_id": "e_akodo",
        "subject_type": "Character",
        "predicate": "MEMBER_OF",
        "object_id": "e_clan_leon",
        "object_type": "Faction",
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.9,
        "evidence_text": "Akodo pertenece al Clan del Leon.",
        "evidence_start": 0,
        "evidence_end": 33,
        "source_id": "src_lab_01",
        "source_page": 12,
        "source_segment": "seg_003",
        "extraction_method": "HEURISTIC",
        "model": None,
        "negated": False,
        "temporal_scope": None,
        "epistemic_status": "ASSERTED",
        "workspace": "leyenda",
        "validation_flags": [],
    }


def test_valid_relation_is_accepted():
    rel = RelationCandidate.from_dict(_valid_relation(), validate=True)
    assert rel.workspace == "leyenda"


@pytest.mark.parametrize("mutate,label", [
    (lambda d: d.update(confidence=1.5), "confidence>1"),
    (lambda d: d.update(evidence_start=40, evidence_end=10), "offsets invertidos"),
    (lambda d: d.update(object_id=d["subject_id"]), "subject==object"),
    (lambda d: d.update(direction="SIDEWAYS"), "direccion invalida"),
    (lambda d: d.update(epistemic_status="GOSSIP"), "epistemic invalido"),
    (lambda d: d.update(extraction_method="MAGIC"), "metodo invalido"),
    (lambda d: d.update(evidence_text="", extraction_method="LLM_LOCAL"), "evidencia ausente"),
    (lambda d: d.update(source_segment=""), "procedencia incompleta"),
])
def test_invalid_relations_are_rejected(mutate, label):
    d = _valid_relation()
    mutate(d)
    with pytest.raises(RelationContractError):
        RelationCandidate.from_dict(d, validate=True)


@pytest.mark.mutation
def test_mutation_empty_workspace_is_rejected_by_real_contract():
    """La regla `workspace` del contrato REAL es load-bearing.

    Si se relajara (aceptar workspace vacío), un documento sin workspace pasaría;
    el validador real DEBE rechazarlo. Control: con workspace válido, se acepta.
    """
    d = _valid_relation()
    d["workspace"] = "   "  # vacío efectivo
    with pytest.raises(RelationContractError):
        RelationCandidate.from_dict(d, validate=True)
    d["workspace"] = "leyenda"
    assert RelationCandidate.from_dict(d, validate=True).workspace == "leyenda"


def test_negation_and_temporal_are_preserved():
    d = _valid_relation()
    d["negated"] = True
    d["temporal_scope"] = {"before": "guerra_hantei"}
    rel = RelationCandidate.from_dict(d, validate=True)
    assert rel.negated is True
    assert rel.temporal_scope == {"before": "guerra_hantei"}


def test_deterministic_serialization_roundtrip():
    rel = RelationCandidate.from_dict(_valid_relation(), validate=True)
    j1 = rel.to_json()
    rel2 = RelationCandidate.from_dict(json.loads(j1), validate=True)
    assert rel2.to_json() == j1

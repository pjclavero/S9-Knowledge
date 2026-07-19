"""test_relation_contract_rules.py — invariantes del contrato interno de RELACIONES.

Contrato de referencia: docs/coordination/contract-proposals.md §1
(`relation-candidate/internal-v1`, Equipo A / A-REL-1).

AUTOCONTENIDO: el pipeline real de A vive en `data-engine/app/relations/**` en una
rama paralela NO fusionada. Aquí definimos un validador de REFERENCIA mínimo que
codifica las reglas esperadas y fija las invariantes que el contrato real deberá
cumplir en la integración. Q no importa código de A ni corrige producto.

Cada `test_*_mutation` demuestra que RELAJAR la regla (validador mutado) haría PASAR
un documento que el validador estricto rechaza -> la regla es load-bearing.
"""
from __future__ import annotations

import copy

import pytest

# ---------------------------------------------------------------------------
# Validador de REFERENCIA (mínimo). Devuelve la lista de códigos de veto.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "internal-1.0.0"
DOCUMENT_TYPE = "relation-candidate"

DIRECTIONS = frozenset({"SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT", "UNDIRECTED"})
EPISTEMIC = frozenset({"ASSERTED", "RUMORED", "HYPOTHETICAL", "INTENDED"})
METHODS = frozenset({"HEURISTIC", "LLM_LOCAL", "NVIDIA", "ONTOLOGY"})

REQUIRED_FIELDS = (
    "schema_version", "document_type", "relation_id", "subject_id", "predicate",
    "object_id", "direction", "confidence", "evidence_text", "evidence_span",
    "source_id", "extraction_method", "negated", "epistemic_status", "workspace",
)


def validate_relation(doc: object, *, check_workspace: bool = True) -> list[str]:
    """Valida un relation-candidate. Devuelve códigos de veto (vacío == válido).

    `check_workspace` existe SOLO para los tests de mutación: al ponerlo en False
    se relaja deliberadamente la regla de workspace no vacío.
    """
    v: list[str] = []
    if not isinstance(doc, dict):
        return ["SCHEMA_NOT_OBJECT"]

    if doc.get("schema_version") != SCHEMA_VERSION:
        v.append("SCHEMA_VERSION_INVALID")
    if doc.get("document_type") != DOCUMENT_TYPE:
        v.append("DOCUMENT_TYPE_INVALID")

    for f in REQUIRED_FIELDS:
        if f not in doc:
            v.append(f"MISSING_FIELD:{f}")

    # confidence en [0,1]
    conf = doc.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0.0 <= conf <= 1.0):
        v.append("CONFIDENCE_OUT_OF_RANGE")

    # evidence_text obligatorio y literal (no vacío)
    ev = doc.get("evidence_text")
    if not isinstance(ev, str) or not ev.strip():
        v.append("EVIDENCE_MISSING")

    # offsets: start <= end, ambos >= 0
    span = doc.get("evidence_span")
    if not isinstance(span, dict) or "start" not in span or "end" not in span:
        v.append("SPAN_MALFORMED")
    else:
        s, e = span.get("start"), span.get("end")
        if not isinstance(s, int) or not isinstance(e, int) or isinstance(s, bool) or isinstance(e, bool):
            v.append("SPAN_MALFORMED")
        elif s < 0 or e < 0 or s > e:
            v.append("SPAN_OFFSETS_INVALID")

    # direction / epistemic / method enums
    if doc.get("direction") not in DIRECTIONS:
        v.append("DIRECTION_INVALID")
    if doc.get("epistemic_status") not in EPISTEMIC:
        v.append("EPISTEMIC_INVALID")
    if doc.get("extraction_method") not in METHODS:
        v.append("METHOD_INVALID")

    # negación EXPLÍCITA: `negated` debe ser un bool presente (no None, no str).
    if not isinstance(doc.get("negated"), bool):
        v.append("NEGATION_NOT_EXPLICIT")

    # workspace no vacío (aislamiento por workspace)
    if check_workspace:
        ws = doc.get("workspace")
        if not isinstance(ws, str) or not ws.strip():
            v.append("WORKSPACE_EMPTY")

    return v


# ---------------------------------------------------------------------------
# Fixtures de referencia
# ---------------------------------------------------------------------------
@pytest.fixture()
def valid_relation() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": DOCUMENT_TYPE,
        "relation_id": "rel-0001",
        "subject_id": "ent-akodo",
        "predicate": "MEMBER_OF",
        "object_id": "ent-clan-leon",
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.82,
        "evidence_text": "Akodo lidera el Clan del Leon.",
        "evidence_span": {"start": 0, "end": 30},
        "source_id": "src-sanitized-01",
        "source_page": None,
        "source_segment": "seg-12",
        "extraction_method": "LLM_LOCAL",
        "model": "local-model@1",
        "negated": False,
        "temporal_scope": None,
        "epistemic_status": "ASSERTED",
        "workspace": "l5r",
        "validation_flags": [],
    }


def test_reference_relation_is_valid(valid_relation):
    assert validate_relation(valid_relation) == []


def test_reject_invalid_schema(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["schema_version"] = "internal-9.9.9"
    assert "SCHEMA_VERSION_INVALID" in validate_relation(doc)


def test_reject_document_type_wrong(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["document_type"] = "entity-candidate"
    assert "DOCUMENT_TYPE_INVALID" in validate_relation(doc)


def test_reject_missing_required_field(valid_relation):
    doc = copy.deepcopy(valid_relation)
    del doc["subject_id"]
    assert "MISSING_FIELD:subject_id" in validate_relation(doc)


def test_reject_offsets_start_gt_end(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["evidence_span"] = {"start": 30, "end": 5}
    assert "SPAN_OFFSETS_INVALID" in validate_relation(doc)


def test_reject_negative_offset(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["evidence_span"] = {"start": -1, "end": 5}
    assert "SPAN_OFFSETS_INVALID" in validate_relation(doc)


def test_reject_evidence_absent(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["evidence_text"] = "   "
    assert "EVIDENCE_MISSING" in validate_relation(doc)


def test_reject_empty_workspace(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["workspace"] = ""
    assert "WORKSPACE_EMPTY" in validate_relation(doc)


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, "0.5", True])
def test_reject_confidence_out_of_range(valid_relation, bad):
    doc = copy.deepcopy(valid_relation)
    doc["confidence"] = bad
    assert "CONFIDENCE_OUT_OF_RANGE" in validate_relation(doc)


@pytest.mark.parametrize("bad", [None, "false", "no", 0, 1])
def test_reject_negation_not_explicit(valid_relation, bad):
    doc = copy.deepcopy(valid_relation)
    doc["negated"] = bad
    assert "NEGATION_NOT_EXPLICIT" in validate_relation(doc)


def test_reject_epistemic_invalid(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["epistemic_status"] = "MAYBE"
    assert "EPISTEMIC_INVALID" in validate_relation(doc)


def test_reject_direction_invalid(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["direction"] = "SIDEWAYS"
    assert "DIRECTION_INVALID" in validate_relation(doc)


# ---------------------------------------------------------------------------
# MUTATION CHECK
# Mutación: "aceptar workspace vacío". Se relaja la regla (check_workspace=False).
# Si el contrato real dejara de exigir workspace no vacío, un documento con
# workspace="" pasaría -> fuga de aislamiento. El validador estricto DEBE vetarlo.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_accepting_empty_workspace_breaks(valid_relation):
    doc = copy.deepcopy(valid_relation)
    doc["workspace"] = ""
    strict = validate_relation(doc)  # regla activa
    relaxed = validate_relation(doc, check_workspace=False)  # regla relajada (mutante)
    # La regla estricta captura la violación...
    assert "WORKSPACE_EMPTY" in strict
    # ...y relajarla la deja pasar: la mutación cambia el resultado (rompería el test).
    assert "WORKSPACE_EMPTY" not in relaxed

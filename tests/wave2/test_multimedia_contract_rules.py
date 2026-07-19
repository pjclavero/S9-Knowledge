"""test_multimedia_contract_rules.py — invariantes del contrato MULTIMEDIA.

Contrato de referencia: docs/coordination/contract-proposals.md §3
(`multimedia-artifact/internal-v1`, Equipo B / B-IMG-1).

AUTOCONTENIDO: el pipeline OCR/visión real de B vive en `data-engine/app/ocr/**` y
`data-engine/app/media/**` en rama paralela NO fusionada. Aquí definimos un
validador de REFERENCIA mínimo. Q no importa código de B ni corrige producto.

Reglas: bounding box normalizado dentro de [0,1] y dentro de página; tipos
conocidos; confianza en [0,1]; orientación válida; procedencia (file/hash/model)
presente; solapamientos = WARNING (no error).
"""
from __future__ import annotations

import copy

import pytest

ARTIFACT_TYPES = frozenset({
    "OCR_TEXT", "IMAGE_DESCRIPTION", "TABLE", "MAP", "DIAGRAM",
    "CHARACTER_SHEET", "UNKNOWN_VISUAL",
})
ORIENTATIONS = frozenset({0, 90, 180, 270})


def _bbox_errors(bb: object, *, check_bounds: bool = True) -> list[str]:
    """bbox = {x0,y0,x1,y1} normalizado a [0,1], con x0<x1 y y0<y1."""
    if not isinstance(bb, dict) or not all(k in bb for k in ("x0", "y0", "x1", "y1")):
        return ["BBOX_MALFORMED"]
    x0, y0, x1, y1 = bb["x0"], bb["y0"], bb["x1"], bb["y1"]
    errs: list[str] = []
    coords = [x0, y0, x1, y1]
    if not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coords):
        return ["BBOX_MALFORMED"]
    if check_bounds and not all(0.0 <= c <= 1.0 for c in coords):
        errs.append("BBOX_OUT_OF_RANGE")  # fuera de [0,1] == fuera de página normalizada
    if x0 >= x1 or y0 >= y1:
        errs.append("BBOX_DEGENERATE")
    return errs


def _overlap(a: dict, b: dict) -> bool:
    return not (a["x1"] <= b["x0"] or b["x1"] <= a["x0"]
                or a["y1"] <= b["y0"] or b["y1"] <= a["y0"])


def validate_artifact(art: object, *, check_bbox_bounds: bool = True) -> list[str]:
    """Valida un multimedia-artifact. Devuelve códigos de ERROR (no warnings)."""
    if not isinstance(art, dict):
        return ["ARTIFACT_NOT_OBJECT"]
    errs: list[str] = []

    if art.get("type") not in ARTIFACT_TYPES:
        errs.append("TYPE_UNKNOWN")

    conf = art.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0.0 <= conf <= 1.0):
        errs.append("CONFIDENCE_OUT_OF_RANGE")

    if art.get("orientation") not in ORIENTATIONS:
        errs.append("ORIENTATION_INVALID")

    # procedencia: file, hash y model obligatorios
    for f in ("file", "hash", "model"):
        val = art.get(f)
        if not isinstance(val, str) or not val.strip():
            errs.append(f"PROVENANCE_MISSING:{f}")

    # página >= 1
    page = art.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        errs.append("PAGE_INVALID")

    errs.extend(_bbox_errors(art.get("bounding_box"), check_bounds=check_bbox_bounds))
    return errs


def validate_artifact_set(arts: list) -> tuple[list[str], list[str]]:
    """Devuelve (errores, warnings). Los solapamientos son WARNING, no error."""
    errors: list[str] = []
    warnings: list[str] = []
    for a in arts:
        errors.extend(validate_artifact(a))
    boxes = [a["bounding_box"] for a in arts
             if isinstance(a, dict) and isinstance(a.get("bounding_box"), dict)
             and all(k in a["bounding_box"] for k in ("x0", "y0", "x1", "y1"))]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap(boxes[i], boxes[j]):
                warnings.append(f"BBOX_OVERLAP:{i},{j}")
    return errors, warnings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def valid_artifact() -> dict:
    return {
        "type": "OCR_TEXT",
        "file": "img/page1.png",
        "page": 1,
        "region": "top",
        "bounding_box": {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4},
        "method": "TESSERACT",
        "model": "tesseract@5",
        "confidence": 0.91,
        "language": "es",
        "orientation": 0,
        "visual_evidence": "crop-ref-1",
        "hash": "sha256:abc",
    }


def test_reference_artifact_is_valid(valid_artifact):
    assert validate_artifact(valid_artifact) == []


@pytest.mark.parametrize("bb", [
    {"x0": -0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4},   # fuera por debajo
    {"x0": 0.1, "y0": 0.1, "x1": 1.5, "y1": 0.4},    # fuera por encima (fuera de página)
    {"x0": 0.1, "y0": -0.2, "x1": 0.5, "y1": 0.4},
])
def test_reject_bbox_out_of_range(valid_artifact, bb):
    art = copy.deepcopy(valid_artifact)
    art["bounding_box"] = bb
    assert "BBOX_OUT_OF_RANGE" in validate_artifact(art)


def test_reject_bbox_degenerate(valid_artifact):
    art = copy.deepcopy(valid_artifact)
    art["bounding_box"] = {"x0": 0.5, "y0": 0.5, "x1": 0.2, "y1": 0.2}
    assert "BBOX_DEGENERATE" in validate_artifact(art)


def test_reject_unknown_type(valid_artifact):
    art = copy.deepcopy(valid_artifact)
    art["type"] = "HOLOGRAM"
    assert "TYPE_UNKNOWN" in validate_artifact(art)


@pytest.mark.parametrize("bad", [-0.01, 1.5, "0.9", True])
def test_reject_confidence_out_of_range(valid_artifact, bad):
    art = copy.deepcopy(valid_artifact)
    art["confidence"] = bad
    assert "CONFIDENCE_OUT_OF_RANGE" in validate_artifact(art)


@pytest.mark.parametrize("bad", [45, 360, "UP", None])
def test_reject_orientation_invalid(valid_artifact, bad):
    art = copy.deepcopy(valid_artifact)
    art["orientation"] = bad
    assert "ORIENTATION_INVALID" in validate_artifact(art)


@pytest.mark.parametrize("field", ["file", "hash", "model"])
def test_reject_provenance_absent(valid_artifact, field):
    art = copy.deepcopy(valid_artifact)
    art[field] = ""
    assert f"PROVENANCE_MISSING:{field}" in validate_artifact(art)


def test_reject_page_invalid(valid_artifact):
    art = copy.deepcopy(valid_artifact)
    art["page"] = 0
    assert "PAGE_INVALID" in validate_artifact(art)


def test_overlap_is_warning_not_error(valid_artifact):
    a = copy.deepcopy(valid_artifact)
    b = copy.deepcopy(valid_artifact)
    b["bounding_box"] = {"x0": 0.2, "y0": 0.2, "x1": 0.6, "y1": 0.5}  # solapa con a
    errors, warnings = validate_artifact_set([a, b])
    assert errors == []                       # solapamiento no es error
    assert any(w.startswith("BBOX_OVERLAP") for w in warnings)


# ---------------------------------------------------------------------------
# MUTATION CHECK
# Mutación: aceptar bbox fuera de rango (check_bbox_bounds=False). Una caja con
# coordenadas > 1 (fuera de página) pasaría. La regla estricta DEBE vetarla.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_accepting_out_of_range_bbox_breaks(valid_artifact):
    art = copy.deepcopy(valid_artifact)
    art["bounding_box"] = {"x0": 0.1, "y0": 0.1, "x1": 1.4, "y1": 0.4}
    strict = validate_artifact(art)
    relaxed = validate_artifact(art, check_bbox_bounds=False)
    assert "BBOX_OUT_OF_RANGE" in strict
    assert "BBOX_OUT_OF_RANGE" not in relaxed

"""Tests del contrato interno multimedia `multimedia-artifact/internal-v1`.

Cubre:
- Casos válidos por tipo (EMBEDDED_TEXT, ASR_TEXT, OCR_TEXT, IMAGE_DESCRIPTION,
  TABLE, CHARACTER_SHEET, low-confidence).
- Casos inválidos: bbox fuera de rango, confianza fuera de [0,1], orientación
  inválida, tipo desconocido, OCR sin texto, procedencia ausente.
- Bounding box normalizada [0,1] y su sistema de coordenadas.
- Deduplicación por contenido y anotación de solapes (warnings).
- Separación estricta OCR (texto reconocido) vs IMAGE_DESCRIPTION (visión).
- Compatibilidad con el pipeline ASR existente (media.transcriber / models).

Usa las fixtures sintéticas sanitizadas de tests/data/multimedia/.
NO ejecuta OCR real, NO carga modelos, NO usa imágenes privadas.
"""
import json
from pathlib import Path

import pytest

from media.multimedia_contract import (
    CONTRACT_ID,
    LOW_CONFIDENCE_THRESHOLD,
    VALID_ORIENTATIONS,
    BoundingBox,
    ContractValidationError,
    MediaType,
    MultimediaArtifact,
    annotate_overlaps,
    content_dedup_key,
    deduplicate,
)

DATA_DIR = Path(__file__).resolve().parent / "data" / "multimedia"


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _artifact(name: str) -> MultimediaArtifact:
    return MultimediaArtifact.from_dict(_load(name))


# ── Fixtures presentes ────────────────────────────────────────────────────────
def test_synthetic_fixtures_exist():
    files = sorted(p.name for p in DATA_DIR.glob("*.json"))
    assert files, "no hay fixtures sintéticas"
    # Al menos un valid_* y un invalid_* por robustez.
    assert any(f.startswith("valid_") for f in files)
    assert any(f.startswith("invalid_") for f in files)


# ── Enum de tipos ─────────────────────────────────────────────────────────────
def test_all_media_types_present():
    names = {m.name for m in MediaType}
    assert names == {
        "EMBEDDED_TEXT", "ASR_TEXT", "OCR_TEXT", "IMAGE_DESCRIPTION",
        "TABLE", "MAP", "DIAGRAM", "CHARACTER_SHEET", "CAPTION", "UNKNOWN_VISUAL",
    }


def test_ocr_and_image_description_are_distinct_types():
    # Regla central: OCR (texto reconocido) != comprensión visual (descripción).
    assert MediaType.OCR_TEXT is not MediaType.IMAGE_DESCRIPTION
    assert MediaType.OCR_TEXT.value == "OCR_TEXT"
    assert MediaType.IMAGE_DESCRIPTION.value == "IMAGE_DESCRIPTION"


# ── Bounding box ──────────────────────────────────────────────────────────────
def test_bounding_box_valid():
    bb = BoundingBox(0.1, 0.1, 0.5, 0.5)
    assert bb.is_valid()
    assert bb.validate() == []


@pytest.mark.parametrize(
    "bb",
    [
        BoundingBox(0.8, 0.1, 0.5, 0.1),   # x+width > 1
        BoundingBox(0.1, 0.8, 0.1, 0.5),   # y+height > 1
        BoundingBox(-0.1, 0.1, 0.2, 0.2),  # x < 0
        BoundingBox(0.1, -0.1, 0.2, 0.2),  # y < 0
        BoundingBox(0.1, 0.1, 0.0, 0.2),   # width == 0
        BoundingBox(0.1, 0.1, 0.2, 0.0),   # height == 0
        BoundingBox(0.1, 0.1, -0.2, 0.2),  # width < 0
    ],
)
def test_bounding_box_invalid(bb):
    assert not bb.is_valid()
    assert bb.validate()


def test_bounding_box_full_page_is_valid():
    assert BoundingBox(0.0, 0.0, 1.0, 1.0).is_valid()


def test_bounding_box_intersection_and_overlap():
    a = BoundingBox(0.0, 0.0, 0.5, 0.5)
    b = BoundingBox(0.25, 0.25, 0.5, 0.5)
    c = BoundingBox(0.6, 0.6, 0.3, 0.3)
    assert a.intersection_area(b) == pytest.approx(0.0625)
    assert a.overlaps(b)
    assert not a.overlaps(c)


# ── Casos válidos por tipo (fixtures) ─────────────────────────────────────────
@pytest.mark.parametrize(
    "fixture",
    [
        "valid_embedded_text.json",
        "valid_ocr_text.json",
        "valid_image_description.json",
        "valid_table.json",
        "valid_asr_text.json",
        "valid_character_sheet_hierarchy.json",
        "valid_low_confidence.json",
    ],
)
def test_valid_fixtures_pass(fixture):
    art = _artifact(fixture)
    errors = art.validate()
    assert errors == [], f"{fixture} debería ser válido: {errors}"
    assert art.contract == CONTRACT_ID


def test_ocr_fixture_has_text_not_description():
    art = _artifact("valid_ocr_text.json")
    assert art.media_type is MediaType.OCR_TEXT
    assert art.text.strip()
    assert not art.description.strip()


def test_image_description_fixture_has_description_not_text():
    art = _artifact("valid_image_description.json")
    assert art.media_type is MediaType.IMAGE_DESCRIPTION
    assert art.description.strip()
    assert not art.text.strip()


def test_table_fixture_has_structured_data():
    art = _artifact("valid_table.json")
    assert art.media_type is MediaType.TABLE
    assert art.structured_data
    assert "rows" in art.structured_data


# ── Casos inválidos (fixtures) ────────────────────────────────────────────────
def test_invalid_bbox_out_of_range():
    art = _artifact("invalid_bbox_out_of_range.json")
    errors = art.validate()
    assert any("bounding_box" in e for e in errors)


def test_invalid_ocr_empty_text():
    art = _artifact("invalid_ocr_empty_text.json")
    errors = art.validate()
    assert any("text" in e for e in errors)


def test_invalid_missing_provenance():
    art = _artifact("invalid_missing_provenance.json")
    errors = art.validate()
    assert any("source_id" in e for e in errors)
    assert any("file_hash" in e for e in errors)


def test_invalid_orientation():
    art = _artifact("invalid_orientation.json")
    errors = art.validate()
    assert any("orientation" in e for e in errors)


def test_invalid_confidence_out_of_range():
    art = _artifact("invalid_confidence_out_of_range.json")
    errors = art.validate()
    assert any("confidence" in e for e in errors)


def test_invalid_unknown_media_type_strict_errors():
    data = _load("invalid_unknown_media_type.json")
    art = MultimediaArtifact.from_dict(data)
    # from_dict degrada el string desconocido a UNKNOWN_VISUAL en el enum,
    # pero conservamos el string original crudo para la prueba estricta.
    art.media_type = data["media_type"]  # "HOLOGRAM"
    errors = art.validate(strict=True)
    assert any("media_type" in e for e in errors)


def test_unknown_media_type_non_strict_degrades():
    art = MultimediaArtifact(
        source_id="s", file_hash="h", media_type="HOLOGRAM",
        description="algo", bounding_box=BoundingBox(0.1, 0.1, 0.2, 0.2),
    )
    errors = art.validate(strict=False)
    assert errors == [] or all("media_type" not in e for e in errors)
    assert art.media_type is MediaType.UNKNOWN_VISUAL


# ── Requisitos por tipo (construidos en código) ───────────────────────────────
def test_embedded_text_requires_text():
    art = MultimediaArtifact(source_id="s", file_hash="h", media_type=MediaType.EMBEDDED_TEXT)
    assert any("text" in e for e in art.validate())


def test_image_description_requires_description():
    art = MultimediaArtifact(source_id="s", file_hash="h", media_type=MediaType.IMAGE_DESCRIPTION)
    assert any("description" in e for e in art.validate())


def test_table_requires_structured_data():
    art = MultimediaArtifact(source_id="s", file_hash="h", media_type=MediaType.TABLE)
    assert any("structured_data" in e for e in art.validate())


@pytest.mark.parametrize("orientation", sorted(VALID_ORIENTATIONS))
def test_valid_orientations_accepted(orientation):
    art = MultimediaArtifact(
        source_id="s", file_hash="h", media_type=MediaType.CAPTION,
        text="", description="", orientation=orientation,
    )
    # CAPTION no exige text/description; orientación válida no aporta error.
    assert all("orientation" not in e for e in art.validate())


# ── Baja confianza → revisión humana ──────────────────────────────────────────
def test_low_confidence_flags_human_review():
    art = _artifact("valid_low_confidence.json")
    assert art.confidence < LOW_CONFIDENCE_THRESHOLD
    art.validate()
    assert art.requires_human_review()
    assert any("revisión humana" in w for w in art.warnings)


# ── Deduplicación ─────────────────────────────────────────────────────────────
def test_deduplicate_removes_identical_content():
    arts = [MultimediaArtifact.from_dict(d) for d in _load("dedup_pair.json")]
    assert len(arts) == 2
    assert content_dedup_key(arts[0]) == content_dedup_key(arts[1])
    deduped = deduplicate(arts)
    assert len(deduped) == 1


# ── Solapes → warning (no bloqueante) ─────────────────────────────────────────
def test_overlap_annotation_adds_warning():
    arts = [MultimediaArtifact.from_dict(d) for d in _load("overlap_pair.json")]
    for a in arts:
        assert a.validate() == []
    annotate_overlaps(arts, min_iou=0.0)
    assert all(any("solape" in w for w in a.warnings) for a in arts)


def test_overlap_hierarchy_not_flagged():
    parent = MultimediaArtifact(
        source_id="s", file_hash="h", media_type=MediaType.CHARACTER_SHEET,
        description="ficha", structured_data={"a": 1}, page=1, region_id="parent",
        bounding_box=BoundingBox(0.1, 0.1, 0.8, 0.8),
    )
    child = MultimediaArtifact(
        source_id="s", file_hash="h", media_type=MediaType.TABLE,
        structured_data={"rows": []}, page=1, region_id="child",
        parent_region="parent", bounding_box=BoundingBox(0.2, 0.2, 0.3, 0.3),
    )
    annotate_overlaps([parent, child], min_iou=0.0)
    assert not any("solape" in w for w in parent.warnings)
    assert not any("solape" in w for w in child.warnings)


# ── Serialización round-trip ──────────────────────────────────────────────────
def test_round_trip_to_dict_from_dict():
    art = _artifact("valid_ocr_text.json")
    d = art.to_dict()
    assert d["media_type"] == "OCR_TEXT"
    assert d["bounding_box"]["width"] == pytest.approx(0.60)
    art2 = MultimediaArtifact.from_dict(d)
    assert art2.media_type is MediaType.OCR_TEXT
    assert art2.bounding_box == art.bounding_box


# ── Compatibilidad con el pipeline ASR existente ──────────────────────────────
def test_from_transcript_result_compat():
    # No importamos WhisperModel; usamos el StubTranscriber ya existente.
    from media.transcriber import StubTranscriber

    result = StubTranscriber().transcribe(Path("charla.wav"), language="es")
    art = MultimediaArtifact.from_transcript_result(
        result, source_id="media_abc", file_hash="sha256:deadbeef"
    )
    assert art.media_type is MediaType.ASR_TEXT
    assert art.text == result.text
    assert art.validate() == []
    assert art.structured_data["segments"]

"""Q — invariantes del contrato REAL MULTIMEDIA (`media.multimedia_contract`).

Importa `BoundingBox` / `MediaType` de la implementación fusionada (B3). MUTATION
check: la validación de bounding box (dentro de [0,1] y de página) es load-bearing.
"""
from __future__ import annotations

import pytest

from media.multimedia_contract import BoundingBox, MediaType


def test_valid_bbox_accepted():
    assert BoundingBox(0.1, 0.1, 0.4, 0.4).is_valid() is True


@pytest.mark.parametrize("box", [
    BoundingBox(-0.1, 0.1, 0.4, 0.4),   # x < 0
    BoundingBox(0.1, -0.1, 0.4, 0.4),   # y < 0
    BoundingBox(0.8, 0.1, 0.5, 0.4),    # x+width > 1 (fuera de página)
    BoundingBox(0.1, 0.8, 0.4, 0.5),    # y+height > 1
    BoundingBox(0.1, 0.1, 0.0, 0.4),    # width == 0
    BoundingBox(0.1, 0.1, 0.4, -0.2),   # height < 0
])
def test_invalid_bboxes_rejected(box):
    assert box.validate()  # lista de errores no vacía
    assert box.is_valid() is False


@pytest.mark.mutation
def test_mutation_out_of_range_bbox_rejected_by_real_model():
    """Si se relajara el rango, una caja fuera de página pasaría; el modelo real
    la rechaza. Control: una caja dentro de [0,1] es válida."""
    assert BoundingBox(0.9, 0.9, 0.5, 0.5).is_valid() is False   # fuera de página
    assert BoundingBox(0.0, 0.0, 1.0, 1.0).is_valid() is True    # control (página completa)


def test_ocr_and_image_description_are_distinct_media_types():
    assert MediaType.OCR_TEXT.value != MediaType.IMAGE_DESCRIPTION.value
    # ambos existen en el catálogo (OCR != comprensión visual)
    values = {m.value for m in MediaType}
    assert {"OCR_TEXT", "IMAGE_DESCRIPTION"} <= values


def test_overlap_detection_available():
    a = BoundingBox(0.0, 0.0, 0.5, 0.5)
    b = BoundingBox(0.25, 0.25, 0.5, 0.5)
    assert a.overlaps(b) is True
    c = BoundingBox(0.6, 0.6, 0.2, 0.2)
    assert a.overlaps(c) is False

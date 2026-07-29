from __future__ import annotations

import pytest

from knowledge_v3.claim_metadata import ClaimSemanticMetadata


def test_typo_degrada_a_valor_seguro_y_avisa():
    with pytest.warns(RuntimeWarning, match="negation_kind"):
        metadata = ClaimSemanticMetadata.from_metadata({"negation_kind": "CESSATOIN"})
    assert metadata.negation_kind == "SIMPLE"
    assert metadata.negation_kind_present is True
    assert metadata.unknown_negation_kind == "CESSATOIN"


def test_campos_ausentes_reciben_defaults_seguros():
    metadata = ClaimSemanticMetadata.from_metadata({})
    assert metadata == ClaimSemanticMetadata()
    assert metadata.negation_kind_present is False
    assert metadata.unknown_negation_kind == ""


def test_roundtrip_del_bloque_versionado():
    original = ClaimSemanticMetadata(
        negation_kind="CESSATION",
        temporal_resolution_required=True,
        direction_unresolved=True,
        untrusted_origin=True,
    )
    encoded = original.to_metadata()
    assert encoded["metadata_block_version"] == "1"
    assert ClaimSemanticMetadata.from_metadata(encoded) == original

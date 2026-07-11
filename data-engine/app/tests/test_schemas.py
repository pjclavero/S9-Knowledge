"""Tests unitarios para rpg_schema."""
import pytest
import sys
sys.path.insert(0, "/opt/knowledge-services/property-graph/app")

from schemas.rpg_schema import EntityBase, RelationshipBase, ExtractionResult


def make_entity(**kwargs):
    defaults = dict(
        canonical_name="Test Entity",
        display_name="Test Entity",
        entity_type="Character",
        workspace="leyenda",
        source_document="test.pdf",
        source_pages=[1],
        confidence=0.9,
    )
    defaults.update(kwargs)
    return EntityBase(**defaults)


def test_entity_valid_type():
    e = make_entity(entity_type="Character")
    assert e.entity_type == "Character"


def test_entity_invalid_type():
    with pytest.raises(Exception):
        make_entity(entity_type="INVALID_TYPE")


def test_relation_valid():
    r = RelationshipBase(
        source_canonical="A",
        relation_type="BELONGS_TO",
        target_canonical="B",
    )
    assert r.relation_type == "BELONGS_TO"


def test_relation_invalid():
    with pytest.raises(Exception):
        RelationshipBase(
            source_canonical="A",
            relation_type="HATES",
            target_canonical="B",
        )


def test_confidence_out_of_range():
    with pytest.raises(Exception):
        make_entity(confidence=1.5)


def test_empty_extraction_result():
    r = ExtractionResult()
    assert r.entities == []
    assert r.relationships == []


def test_to_neo4j_params():
    e = make_entity()
    params = e.to_neo4j_params()
    assert "canonical_name" in params
    assert "workspace" in params
    assert params["entity_type"] == "Character"


def test_workspace_separation():
    e1 = make_entity(workspace="leyenda", canonical_name="Akodo")
    e2 = make_entity(workspace="trudvang", canonical_name="Akodo")
    p1 = e1.to_neo4j_params()
    p2 = e2.to_neo4j_params()
    assert p1["workspace"] != p2["workspace"]
    assert p1["canonical_name"] == p2["canonical_name"]

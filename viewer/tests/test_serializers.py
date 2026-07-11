from app.serializers import serialize_edge, serialize_node


def test_confidence_0_9_becomes_90_percent():
    node = {"id": "n1", "label": "Test", "type": "Character", "confidence": 0.9}
    result = serialize_node(node)
    assert result["confidence_label"] == "90%"


def test_serialize_node_survives_missing_fields():
    result = serialize_node({"id": "n1"})
    assert result["label"] == ""
    assert result["aliases"] == []
    assert result["confidence_label"] == ""
    assert result["technical"] == {}


def test_serialize_node_hides_technical_fields_from_top_level():
    node = {"id": "n1", "label": "Test", "created_at": "2026-01-01", "extractor_version": "1.4.0"}
    result = serialize_node(node)
    assert "created_at" not in result
    assert result["technical"]["created_at"] == "2026-01-01"
    assert result["technical"]["extractor_version"] == "1.4.0"


def test_serialize_edge_translates_relation_type():
    edge = {"id": "e1", "from": "a", "to": "b", "type": "APPEARS_IN", "confidence": 0.75}
    result = serialize_edge(edge)
    assert result["label"] == "aparece en"
    assert result["confidence_label"] == "75%"

from pathlib import Path

from app.providers.mock_provider import MockGraphProvider

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "sample_graph.json"


def _provider() -> MockGraphProvider:
    return MockGraphProvider(SAMPLE_PATH)


def test_mock_provider_loads_sample_graph():
    provider = _provider()
    assert provider.is_connected() is True
    assert "leyenda" in provider.workspaces()
    nodes, rels = provider.counts("leyenda")
    assert nodes > 0
    assert rels > 0


def test_mock_provider_search_finds_tamori():
    provider = _provider()
    results = provider.search("leyenda", "Tamori")
    assert any(n["label"] == "Agasha Tamori" for n in results)


def test_mock_provider_graph_filters_by_entity_type():
    provider = _provider()
    nodes, _edges = provider.graph("leyenda", limit=300, entity_type="Session")
    assert all(n["type"] == "Session" for n in nodes)
    assert len(nodes) == 1

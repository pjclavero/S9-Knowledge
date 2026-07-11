from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_status_ok_with_mock_provider():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "mock"
    assert data["neo4j_connected"] is False
    assert "leyenda" in data["workspaces"]
    assert data["nodes"] > 0


def test_api_search_finds_tamori():
    response = client.get("/api/search", params={"workspace": "leyenda", "q": "Tamori"})
    assert response.status_code == 200
    data = response.json()
    labels = [r["label"] for r in data["results"]]
    assert "Agasha Tamori" in labels


def test_api_graph_returns_nodes_and_edges():
    response = client.get("/api/graph", params={"workspace": "leyenda", "limit": 100})
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) > 0
    assert len(data["edges"]) > 0


def test_home_page_renders():
    response = client.get("/")
    assert response.status_code == 200
    assert "S9 Knowledge" in response.text

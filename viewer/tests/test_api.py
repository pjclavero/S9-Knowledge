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


def test_api_search_sin_autenticacion_no_entrega_material_de_referencia():
    """P0-AUTH: con `S9K_AUTH_ENABLED=false` el visor YA NO es `admin_full`.

    Este test afirmaba lo contrario: buscaba `Tamori` --un nodo
    `visibility: reference`-- y exigia encontrarlo. Solo pasaba porque desactivar
    la autenticacion concedia la potestad de bypass total, es decir, porque un
    flag de despliegue decidia sobre la dimension mas potente del sistema. Sin
    autenticacion no hay principal, luego no hay autoridad: se aplica minimo
    privilegio (contexto anonimo), que no ve `reference`.

    Se conserva como testigo de que la busqueda SIGUE funcionando --devuelve el
    material de nivel `player` que menciona a Tamori-- y de que el nodo de
    referencia ya no sale. Si alguien reintroduce el bypass, este test se pone
    rojo.
    """
    response = client.get("/api/search", params={"workspace": "leyenda", "q": "Tamori"})
    assert response.status_code == 200
    data = response.json()
    labels = [r["label"] for r in data["results"]]
    assert labels, "la busqueda ha dejado de devolver resultados visibles"
    assert "Agasha Tamori" not in labels, (
        "FUGA: material `visibility=reference` entregado a un visitante sin "
        "autenticar. Solo puede ocurrir si `auth_enabled=False` vuelve a "
        "conceder potestad (admin_full o can_view_reference)."
    )


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

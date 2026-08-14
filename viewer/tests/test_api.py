from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_status_ok_with_mock_provider(cliente_lector):
    # LORE-ANONIMO-DENEGADO: los conteos son los del CONJUNTO AUTORIZADO de
    # quien pregunta, y un visitante sin principal ya no tiene ninguno. Que un
    # anonimo reciba 0 se mide en test_lore_anonimo_denegado_http.py; aqui lo
    # que se comprueba es la FORMA de /api/status, que necesita material.
    response = cliente_lector(app).get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "mock"
    assert data["neo4j_connected"] is False
    assert "leyenda" in data["workspaces"]
    assert data["nodes"] > 0


def test_api_search_sin_autenticacion_no_entrega_NADA(cliente_lector):
    """P0-AUTH + LORE-ANONIMO-DENEGADO: la busqueda no es una puerta lateral.

    Historia de este test, porque explica por que ahora dice algo mas fuerte:

      1. Originalmente buscaba `Tamori` --un nodo `visibility: reference`-- y
         exigia ENCONTRARLO. Solo pasaba porque `S9K_AUTH_ENABLED=false`
         concedia `admin_full`: un flag de despliegue decidiendo sobre la
         dimension mas potente del sistema.
      2. P0-AUTH cerro eso y el test paso a exigir que el nodo `reference` no
         saliera, pero que la busqueda SI devolviera el material `player`.
      3. Ahora (decision del operador, V3 RC, 2026-08-14) tampoco eso: ese
         material `player` era capa juego, y la unica llave que lo abria a un
         anonimo era no tener partida. La ausencia de partida no concede
         visibilidad adicional.

    De modo que un visitante sin autenticar no recibe NINGUN resultado. El
    contrapeso --que la busqueda sigue funcionando de verdad-- va en la mitad
    de abajo, con un lector legitimo: sin el, "no devuelve nada" seria
    compatible con una busqueda rota.
    """
    sin_principal = client.get(
        "/api/search", params={"workspace": "leyenda", "q": "Tamori"})
    assert sin_principal.status_code == 200
    assert sin_principal.json()["results"] == [], (
        "FUGA: la busqueda entrega material a un visitante sin autenticar"
    )

    legitimo = cliente_lector(app).get(
        "/api/search", params={"workspace": "leyenda", "q": "Tamori"})
    assert legitimo.status_code == 200
    labels = [r["label"] for r in legitimo.json()["results"]]
    assert labels, (
        "ni un lector legitimo obtiene resultados: entonces el cero de arriba "
        "no dice nada sobre la autorizacion, dice que la busqueda esta rota"
    )


def test_api_graph_returns_nodes_and_edges(cliente_lector):
    # Idem: /api/graph a un anonimo devuelve 0 nodos por autorizacion, no por
    # un fallo de forma. Se pide como lector legitimo.
    response = cliente_lector(app).get("/api/graph", params={"workspace": "leyenda", "limit": 100})
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) > 0
    assert len(data["edges"]) > 0


def test_home_page_renders():
    response = client.get("/")
    assert response.status_code == 200
    assert "S9 Knowledge" in response.text

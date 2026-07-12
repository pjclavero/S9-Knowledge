"""Tests del panel /reviews del visor."""
import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_reviews_returns_200_with_no_reviews():
    """El panel /reviews responde 200 aunque no haya ninguna fuente."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/reviews")
    assert response.status_code == 200
    assert "Revisiones pendientes" in response.text


def test_reviews_returns_200_with_empty_workspace(tmp_path, monkeypatch):
    """Con un workspace vacío, /reviews sigue respondiendo 200 (lista vacía)."""
    from app.main import app, _reviews_dir

    # Override REPO_ROOT so _reviews_dir points to tmp_path
    import app.main as main_module
    fake_root = tmp_path / "repo"
    (fake_root / "output" / "reviews" / "leyenda").mkdir(parents=True)
    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    client = TestClient(app)
    response = client.get("/reviews?workspace=leyenda")
    assert response.status_code == 200
    assert "No hay fuentes" in response.text


def test_reviews_lists_sources(tmp_path, monkeypatch):
    """Con un workspace que contiene fuentes, /reviews las lista correctamente."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_01"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([{"id": "n1"}]))
    (source_dir / "review_queue.json").write_text(json.dumps([{"id": "n2", "type": "Character"}]))
    (source_dir / "rejected.json").write_text(json.dumps([]))

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews?workspace=leyenda")
    assert response.status_code == 200
    assert "fuente_01" in response.text


def test_reviews_detail_404_for_missing_source(tmp_path, monkeypatch):
    """El detalle de una fuente inexistente devuelve 404."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    (fake_root / "output" / "reviews" / "leyenda").mkdir(parents=True)
    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_inexistente?workspace=leyenda")
    assert response.status_code == 404


def test_reviews_detail_200_for_existing_source(tmp_path, monkeypatch):
    """El detalle de una fuente existente devuelve 200 con la información correcta."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "mi_fuente"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([{"id": "e1"}, {"id": "e2"}]))
    (source_dir / "review_queue.json").write_text(
        json.dumps([{"id": "r1", "type": "Character", "label": "Tamori", "reason": "ambiguo"}])
    )
    (source_dir / "rejected.json").write_text(json.dumps([]))

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/mi_fuente?workspace=leyenda")
    assert response.status_code == 200
    text = response.text
    assert "mi_fuente" in text
    assert "Tamori" in text
    # 2 approved, 1 pending
    assert "2" in text
    assert "1" in text

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


# ---------------------------------------------------------------------------
# Tests de campos nuevos: origin, decision_reason, quality_report
# ---------------------------------------------------------------------------


def test_reviews_list_shows_origin_badge_when_present(tmp_path, monkeypatch):
    """La lista /reviews muestra el badge de origen cuando pipeline_state lo incluye."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_ext"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))
    # pipeline_state con campo origin en nivel raíz
    (source_dir / "pipeline_state.json").write_text(
        json.dumps({"origin": "external", "segment": {"status": "done", "details": {}}})
    )

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews?workspace=leyenda")
    assert response.status_code == 200
    assert "external" in response.text
    assert "origin-external" in response.text


def test_reviews_list_no_origin_badge_when_absent(tmp_path, monkeypatch):
    """La lista /reviews funciona sin campo origin (no rompe)."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_local"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([{"id": "x"}]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews?workspace=leyenda")
    assert response.status_code == 200
    assert "fuente_local" in response.text
    # No debe aparecer clase de badge de origen si no hay dato
    assert "origin-badge" not in response.text


def test_reviews_detail_shows_pkg_meta_fields(tmp_path, monkeypatch):
    """El detalle muestra producer, model y confidence externa cuando existen."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_meta"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))
    (source_dir / "pipeline_state.json").write_text(
        json.dumps({
            "origin": "external",
            "package": {
                "producer": "s9-extractor-v2",
                "model": "qwen2.5:7b",
                "external_confidence": 0.88,
                "local_confidence": 0.72,
            },
            "segment": {"status": "done", "details": {}},
        })
    )

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_meta?workspace=leyenda")
    assert response.status_code == 200
    text = response.text
    assert "s9-extractor-v2" in text
    assert "qwen2.5:7b" in text
    assert "0.88" in text
    assert "0.72" in text


def test_reviews_detail_decision_reason_shown(tmp_path, monkeypatch):
    """La cola de revisión muestra decision_reason cuando existe en el ítem."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_reason"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([
        {
            "candidate_id": "abc123",
            "decision": "needs_review",
            "reason": "confidence media (0.65)",
            "decision_reason": "sin match en grafo",
            "candidate": {"name": "Tamori Doji", "entity_type": "Character", "confidence": 0.65},
        }
    ]))
    (source_dir / "rejected.json").write_text(json.dumps([]))

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_reason?workspace=leyenda")
    assert response.status_code == 200
    text = response.text
    assert "Tamori Doji" in text
    # el reason del ítem principal
    assert "confidence media" in text


def test_reviews_detail_quality_report_json(tmp_path, monkeypatch):
    """El detalle muestra el quality_report.json cuando existe."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_qr"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))
    (source_dir / "quality_report.json").write_text(
        json.dumps({"score": 0.91, "total": 93, "issues": 2, "warnings": 5,
                    "summary": "Pipeline completado sin errores críticos."})
    )

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_qr?workspace=leyenda")
    assert response.status_code == 200
    text = response.text
    assert "quality_report.json" in text
    assert "0.91" in text
    assert "93" in text


def test_reviews_detail_quality_report_md_only(tmp_path, monkeypatch):
    """El detalle muestra el quality_report.md si no hay .json."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_qrmd"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))
    (source_dir / "quality_report.md").write_text(
        "# Quality Report\n\nPipeline OK. Entidades: 89 aprobadas."
    )

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_qrmd?workspace=leyenda")
    assert response.status_code == 200
    text = response.text
    assert "quality_report.md" in text


def test_reviews_detail_no_quality_report_no_section(tmp_path, monkeypatch):
    """Sin quality_report, la sección de informe de calidad no aparece."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_noqr"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_noqr?workspace=leyenda")
    assert response.status_code == 200
    assert "Informe de calidad" not in response.text


def test_reviews_detail_pipeline_state_without_quality_report(tmp_path, monkeypatch):
    """pipeline_state.json sin quality_report no rompe la vista de detalle."""
    import app.main as main_module

    fake_root = tmp_path / "repo"
    source_dir = fake_root / "output" / "reviews" / "leyenda" / "fuente_noqr2"
    source_dir.mkdir(parents=True)
    (source_dir / "approved_payload.json").write_text(json.dumps([]))
    (source_dir / "review_queue.json").write_text(json.dumps([]))
    (source_dir / "rejected.json").write_text(json.dumps([]))
    (source_dir / "pipeline_state.json").write_text(
        json.dumps({"segment": {"status": "done", "details": {"count": 30}}})
    )

    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    from app.main import app
    client = TestClient(app)
    response = client.get("/reviews/fuente_noqr2?workspace=leyenda")
    assert response.status_code == 200
    assert "Informe de calidad" not in response.text

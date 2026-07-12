"""Tests del CLI de revisión S9 Knowledge.

Cubre:
  - ingest-approved sin --dry-run y sin S9K_ALLOW_REAL_INGEST → aborta (exit code != 0)
  - ingest-approved con S9K_ALLOW_REAL_INGEST=false → aborta igualmente
  - payload con origin=external sin validated_by_s9k → rechazado
  - quality-report detecta stopword en autoaprobados de un fixture
  - audit-graph no escribe (verificación de solo lectura via mock/patch)
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Asegurar que el path de la app está disponible
_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_REPO_ROOT = _APP_DIR.parents[1]
_CLI = _APP_DIR / "cli" / "data_review.py"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_payload(
    approved: list[dict] | None = None,
    workspace: str = "test_ws",
    source_id: str = "test_src",
    schema_version: str = "1.0",
    origin: str = "local",
) -> dict:
    return {
        "metadata": {
            "workspace": workspace,
            "source_id": source_id,
            "schema_version": schema_version,
            "origin": origin,
            "generated_at": "2026-07-12T00:00:00+00:00",
            "total_approved": len(approved or []),
        },
        "approved": approved or [],
    }


def _make_entity(
    name: str = "TestEntity",
    entity_type: str = "Character",
    confidence: float = 0.9,
    evidence: str = "Some context evidence text here for testing purposes",
    origin: str = "local",
    validated_by_s9k: bool | None = None,
) -> dict:
    e = {
        "candidate_id": "aabbccdd",
        "kind": "entity",
        "name": name,
        "entity_type": entity_type,
        "confidence": confidence,
        "evidence": evidence,
        "source_id": "test_src",
        "source_kind": "audio",
        "source_document": "test_src",
        "source_timestamp_start": "00:01:00",
        "source_timestamp_end": "00:02:00",
        "workspace": "test_ws",
        "review_status": "auto_approved",
        "origin": origin,
    }
    if validated_by_s9k is not None:
        e["validated_by_s9k"] = validated_by_s9k
    return e


# ─────────────────────────────────────────────────────────────────────────────
# TAREA 1: Guard doble en ingest_approved
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestApprovedGuards:
    """Guard doble: --dry-run + S9K_ALLOW_REAL_INGEST."""

    def test_no_dry_run_no_env_raises(self, tmp_path):
        """Sin --dry-run y sin S9K_ALLOW_REAL_INGEST → RuntimeError."""
        from review.ingest_approved import ingest
        payload = _make_payload([_make_entity()])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k != "S9K_ALLOW_REAL_INGEST"}
        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="S9K_ALLOW_REAL_INGEST"):
                ingest(payload_path, dry_run=False)

    def test_no_dry_run_env_false_raises(self, tmp_path):
        """Sin --dry-run y S9K_ALLOW_REAL_INGEST=false → RuntimeError."""
        from review.ingest_approved import ingest
        payload = _make_payload([_make_entity()])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        with mock.patch.dict(os.environ, {"S9K_ALLOW_REAL_INGEST": "false"}):
            with pytest.raises(RuntimeError, match="S9K_ALLOW_REAL_INGEST"):
                ingest(payload_path, dry_run=False)

    def test_no_dry_run_env_true_reaches_neo4j_attempt(self, tmp_path):
        """Con S9K_ALLOW_REAL_INGEST=true y sin neo4j → falla en neo4j (no en el guard)."""
        from review.ingest_approved import ingest
        payload = _make_payload([_make_entity()])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        with mock.patch.dict(os.environ, {"S9K_ALLOW_REAL_INGEST": "true"}):
            # Debe pasar los guards y llegar a Neo4j (que fallará en test sin servicio)
            with pytest.raises(Exception):
                ingest(payload_path, dry_run=False, neo4j_uri="bolt://127.0.0.1:19999")

    def test_dry_run_always_ok(self, tmp_path):
        """Con --dry-run, nunca falla por el guard de entorno."""
        from review.ingest_approved import ingest
        payload = _make_payload([_make_entity()])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k != "S9K_ALLOW_REAL_INGEST"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = ingest(payload_path, dry_run=True)
        assert result.get("dry_run") is True
        assert result.get("entities", 0) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# TAREA 1: Guard de paquete — origin=external sin validated_by_s9k
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestApprovedPackageGuards:
    """Validación del paquete antes de ingestar."""

    def test_external_without_validated_raises(self, tmp_path):
        """origin=external sin validated_by_s9k=true → ValueError."""
        from review.ingest_approved import ingest
        entity = _make_entity(origin="external")  # sin validated_by_s9k
        payload = _make_payload([entity])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="validated_by_s9k"):
            ingest(payload_path, dry_run=True)

    def test_external_with_validated_ok(self, tmp_path):
        """origin=external con validated_by_s9k=true → OK en dry-run."""
        from review.ingest_approved import ingest
        entity = _make_entity(origin="external", validated_by_s9k=True)
        payload = _make_payload([entity])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        result = ingest(payload_path, dry_run=True)
        assert result.get("dry_run") is True

    def test_missing_workspace_raises(self, tmp_path):
        """Payload sin workspace → ValueError."""
        from review.ingest_approved import ingest
        payload = _make_payload([_make_entity()], workspace="")
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="workspace"):
            ingest(payload_path, dry_run=True)

    def test_missing_schema_version_raises(self, tmp_path):
        """Payload sin schema_version → ValueError."""
        from review.ingest_approved import ingest
        payload = _make_payload([_make_entity()], schema_version="")
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="schema_version"):
            ingest(payload_path, dry_run=True)

    def test_entity_without_evidence_raises(self, tmp_path):
        """Entidad sin evidence → ValueError."""
        from review.ingest_approved import ingest
        entity = _make_entity(evidence="")
        payload = _make_payload([entity])
        payload_path = tmp_path / "approved_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="evidence"):
            ingest(payload_path, dry_run=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAREA 3: quality-report detecta stopwords
# ─────────────────────────────────────────────────────────────────────────────

class TestQualityReport:
    """Comprueba que quality_report detecta sospechosos correctamente."""

    def _build_source_dir(self, tmp_path: Path, approved: list[dict]) -> Path:
        """Crea estructura de directorios con approved_payload.json."""
        ws = "test_ws"
        src = "test_src_001"
        src_dir = tmp_path / "output" / "reviews" / ws / src
        src_dir.mkdir(parents=True)
        payload = _make_payload(approved, workspace=ws, source_id=src)
        (src_dir / "approved_payload.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        # review_queue vacío
        (src_dir / "review_queue.json").write_text("[]", encoding="utf-8")
        (src_dir / "rejected.json").write_text("[]", encoding="utf-8")
        return src_dir

    def test_stopword_detected(self, tmp_path):
        """Un autoaprobado con nombre que es stopword → aparece como suspect con flag stopword."""
        from review.quality_report import generate

        # "todo" y "como" son stopwords en español
        approved = [
            _make_entity(name="Todo", confidence=0.92),
            _make_entity(name="Como", confidence=0.88),
            _make_entity(name="Hanzo", confidence=0.9),  # no stopword
        ]
        src_dir = self._build_source_dir(tmp_path, approved)
        repo_root = tmp_path

        md_path = generate("test_ws", "test_src_001", repo_root)
        assert md_path.exists()

        report_json = src_dir / "quality_report.json"
        assert report_json.exists()
        report = json.loads(report_json.read_text(encoding="utf-8"))

        suspect_names = [s["name"] for s in report["suspects"]]
        stopword_suspects = [s for s in report["suspects"] if "stopword" in s["flags"]]
        assert len(stopword_suspects) >= 1, f"Se esperaba al menos 1 stopword; suspects={suspect_names}"

        # Veredicto debe ser al menos MEDIUM o HIGH por stopwords
        assert report["risk"]["level"] in ("MEDIUM", "HIGH")

    def test_lowercase_single_word_detected(self, tmp_path):
        """Nombre en minúscula de una palabra → detectado como suspect."""
        from review.quality_report import generate

        approved = [
            _make_entity(name="solo", confidence=0.9),
            _make_entity(name="Hanzo", confidence=0.9),
        ]
        src_dir = self._build_source_dir(tmp_path, approved)
        repo_root = tmp_path

        generate("test_ws", "test_src_001", repo_root)
        report = json.loads((src_dir / "quality_report.json").read_text(encoding="utf-8"))

        lowercase_suspects = [s for s in report["suspects"] if "lowercase_single_word" in s["flags"]]
        assert len(lowercase_suspects) >= 1

    def test_short_evidence_detected(self, tmp_path):
        """Evidence corta (< 30 chars) → detectada."""
        from review.quality_report import generate

        approved = [
            _make_entity(name="Kitsune", evidence="breve"),  # muy corta
            _make_entity(name="Hanzo", confidence=0.9),
        ]
        src_dir = self._build_source_dir(tmp_path, approved)
        repo_root = tmp_path

        generate("test_ws", "test_src_001", repo_root)
        report = json.loads((src_dir / "quality_report.json").read_text(encoding="utf-8"))

        short_ev = [s for s in report["suspects"] if "short_evidence" in s["flags"]]
        assert len(short_ev) >= 1

    def test_no_suspects_low_risk(self, tmp_path):
        """Payload limpio → risk LOW."""
        from review.quality_report import generate

        approved = [
            _make_entity(name="Hanzo Hirano", confidence=0.95,
                         evidence="Hanzo se acerca al trono con pasos deliberados buscando la audiencia del daimyo"),
            _make_entity(name="Clan del Dragón", confidence=0.91,
                         evidence="El clan del dragón lleva generaciones controlando las rutas comerciales del norte"),
        ]
        src_dir = self._build_source_dir(tmp_path, approved)
        repo_root = tmp_path

        generate("test_ws", "test_src_001", repo_root)
        report = json.loads((src_dir / "quality_report.json").read_text(encoding="utf-8"))

        assert report["risk"]["level"] == "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# TAREA 4: audit-graph solo lectura
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditGraphReadOnly:
    """Verifica que audit-graph no escribe en Neo4j."""

    def test_audit_graph_no_write_when_neo4j_unavailable(self, tmp_path):
        """Cuando Neo4j no está disponible, genera informe vacío sin intentar escritura."""
        from review.audit_graph import audit

        # Usamos una URI que seguro no existe
        md_path = audit(
            workspace="test_ws",
            repo_root=tmp_path,
            neo4j_uri="bolt://127.0.0.1:29999",
            neo4j_user="neo4j",
            neo4j_password="wrong",
        )
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "no disponible" in content.lower() or "Neo4j no disponible" in content

    def test_audit_graph_does_not_call_write(self, tmp_path):
        """Verifica que audit() nunca llama a session.run() con queries de escritura."""
        from review import audit_graph

        write_queries_called = []

        class FakeSession:
            def run(self, query, *args, **kwargs):
                query_upper = query.strip().upper()
                if any(kw in query_upper for kw in ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE")):
                    write_queries_called.append(query[:80])
                # Retornar datos vacíos simulados
                return _FakeResult([])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        class _FakeResult:
            def __init__(self, data):
                self._data = data
            def data(self):
                return self._data

        class FakeDriver:
            def session(self):
                return FakeSession()
            def close(self):
                pass

        with mock.patch.object(audit_graph, "_get_driver", return_value=FakeDriver()):
            audit_graph.audit(
                workspace="test_ws",
                repo_root=tmp_path,
                neo4j_uri="bolt://127.0.0.1:7687",
                neo4j_user="neo4j",
                neo4j_password="test",
            )

        assert write_queries_called == [], (
            f"audit_graph emitió queries de escritura: {write_queries_called}"
        )

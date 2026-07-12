"""Tests para data-engine/app/review/export_import.py

1. build_knowledge_package produce manifest valido con workspace/schema_version
2. sanitizacion elimina rutas internas/IPs/tokens de un request con datos sensibles
3. external_response invalida (JSON roto, sin evidence, tipo desconocido) -> rechazada
4. external response valida -> candidatos con origin='external' (nunca payload aprobado directo)
5. imported package sin workspace -> rechazado
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap sys.path
_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.export_import import (
    KnowledgePackage,
    ExternalReviewRequest,
    ExternalReviewResponse,
    ImportedCandidatePackage,
    build_knowledge_package,
    build_external_review_request,
    load_external_response,
    external_response_to_candidates,
    load_imported_package,
    validate_imported_package,
    sanitize_text,
    sanitize_object,
    PACKAGE_SCHEMA_VERSION,
    PRODUCER,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_pipeline_state() -> dict:
    return {
        "segment": {"status": "done", "updated_at": "2026-07-12T10:00:00+00:00", "details": {"count": 5}},
        "classify": {"status": "done", "updated_at": "2026-07-12T10:01:00+00:00", "details": {"extractable": 3}},
        "extract": {"status": "done", "updated_at": "2026-07-12T10:02:00+00:00", "details": {"count": 10}},
        "validate": {"status": "done", "updated_at": "2026-07-12T10:03:00+00:00", "details": {"valid": 10, "invalid": 0}},
        "resolve": {"status": "done", "updated_at": "2026-07-12T10:04:00+00:00", "details": {}},
        "decide": {"status": "done", "updated_at": "2026-07-12T10:05:00+00:00", "details": {}},
        "approved_writer": {"status": "done", "updated_at": "2026-07-12T10:06:00+00:00", "details": {"auto_approve": 8, "needs_review": 2}},
    }


def _make_approved_item(name: str = "Clan Cangrejo", kind: str = "entity") -> dict:
    return {
        "candidate_id": "abc001",
        "kind": kind,
        "name": name,
        "entity_type": "Clan",
        "from_entity": None,
        "to_entity": None,
        "relation_type": None,
        "event_description": None,
        "confidence": 0.9,
        "evidence": "el clan cangrejo aparece en la sala",
        "source_id": "media_test",
        "source_kind": "audio",
        "source_document": "media_test",
        "source_timestamp_start": "00:10:00",
        "source_timestamp_end": "00:15:00",
        "workspace": "test_ws",
        "review_status": "auto_approved",
        "knowledge_layer": "transcript",
        "visibility": "player",
        "resolver_action": "create_new",
        "matched_canonical": None,
    }


def _make_repo_dir(tmp_path: Path, workspace: str = "test_ws", source_id: str = "media_test") -> Path:
    """Crea estructura minima de repo en tmp_path para tests."""
    ws_dir = tmp_path / "output" / "reviews" / workspace / source_id
    ws_dir.mkdir(parents=True)

    # pipeline_state.json
    (ws_dir / "pipeline_state.json").write_text(
        json.dumps(_make_pipeline_state(), ensure_ascii=False), encoding="utf-8"
    )

    # approved_payload.json
    approved = {
        "metadata": {"workspace": workspace, "source_id": source_id, "generated_at": "2026-07-12T10:06:00+00:00", "total_approved": 2},
        "approved": [_make_approved_item("Clan Cangrejo"), _make_approved_item("Clan Dragon", "entity")],
    }
    (ws_dir / "approved_payload.json").write_text(
        json.dumps(approved, ensure_ascii=False), encoding="utf-8"
    )

    # review_queue.json (vacio)
    (ws_dir / "review_queue.json").write_text("[]", encoding="utf-8")

    # segments.json
    segments = [
        {
            "segment_id": f"{source_id}_seg_0001",
            "source_id": source_id,
            "source_kind": "audio",
            "workspace": workspace,
            "timestamp_start": "00:00:00",
            "timestamp_end": "00:05:00",
            "text": "Texto de prueba del segmento uno.",
            "lines": [],
        }
    ]
    (ws_dir / "segments.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

    # candidates.json
    candidates = [
        {
            "candidate_id": "abc001",
            "source_id": source_id,
            "segment_id": f"{source_id}_seg_0001",
            "workspace": workspace,
            "kind": "entity",
            "name": "Clan Cangrejo",
            "entity_type": "Clan",
            "from_entity": None,
            "to_entity": None,
            "from_type": None,
            "to_type": None,
            "relation_type": None,
            "event_description": None,
            "confidence": 0.9,
            "evidence": "el clan cangrejo aparece en la sala",
            "timestamp_start": "00:00:00",
            "timestamp_end": "00:05:00",
            "source_kind": "audio",
            "status": "pending",
        }
    ]
    (ws_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")

    return tmp_path


def _make_valid_external_response(workspace: str = "test_ws") -> dict:
    return {
        "package_type": "external_review_response",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": workspace,
        "source_id": "media_test",
        "suggested_entities": [
            {
                "kind": "entity",
                "name": "Maestro Hanzo",
                "entity_type": "Character",
                "confidence": 0.9,
                "evidence": "El maestro Hanzo se presenta ante el consejo.",
                "timestamp_start": "00:05:00",
                "timestamp_end": "00:10:00",
            }
        ],
        "suggested_relations": [],
        "suggested_aliases": [],
        "suggested_merges": [],
        "suggested_rejections": [],
        "suggested_type_changes": [],
        "warnings": [],
        "confidence": 0.85,
        "timestamps": {"created_at": "2026-07-12T10:00:00Z"},
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: build_knowledge_package produce manifest valido
# ─────────────────────────────────────────────────────────────────────────────

def test_build_knowledge_package_manifest_valido(tmp_path):
    """build_knowledge_package produce manifest valido con workspace, schema_version y producer."""
    repo_root = _make_repo_dir(tmp_path)
    pkg = build_knowledge_package("test_ws", "media_test", repo_root)

    manifest = pkg["manifest"]
    assert manifest["package_type"] == "knowledge_package"
    assert manifest["workspace"] == "test_ws"
    assert manifest["schema_version"] == PACKAGE_SCHEMA_VERSION
    assert manifest["producer"] == PRODUCER
    assert "created_at" in manifest
    assert "counts" in manifest
    assert manifest["counts"]["total_approved"] == 2
    assert manifest["pipeline_completed"] is True


def test_build_knowledge_package_estructura_completa(tmp_path):
    """El paquete tiene todas las secciones esperadas."""
    repo_root = _make_repo_dir(tmp_path)
    pkg = build_knowledge_package("test_ws", "media_test", repo_root)

    assert "manifest" in pkg
    assert "workspace_metadata" in pkg
    assert "entities" in pkg
    assert "relations" in pkg
    assert "evidence" in pkg
    assert "approved_payload" in pkg
    # Entidades deben ser 2
    assert len(pkg["entities"]) == 2


def test_build_knowledge_package_guarda_fichero(tmp_path):
    """Si se pasa output_path, el paquete se persiste en disco."""
    repo_root = _make_repo_dir(tmp_path)
    out_file = tmp_path / "exports" / "pkg.json"
    build_knowledge_package("test_ws", "media_test", repo_root, output_path=out_file)

    assert out_file.exists()
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["manifest"]["workspace"] == "test_ws"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: sanitizacion elimina rutas internas, IPs y tokens
# ─────────────────────────────────────────────────────────────────────────────

def test_sanitize_text_rutas_internas():
    """sanitize_text redacta rutas /opt/ y /mnt/."""
    texto = "El archivo esta en /opt/knowledge-services/s9-knowledge-repo/state/glossary.db"
    resultado = sanitize_text(texto)
    assert "/opt/" not in resultado
    assert "[RUTA_INTERNA]" in resultado


def test_sanitize_text_ip_privada():
    """sanitize_text redacta IPs 192.168.x.x."""
    texto = "Servidor en 192.168.1.205 puerto 7474"
    resultado = sanitize_text(texto)
    assert "192.168.1.205" not in resultado
    assert "[IP_INTERNA]" in resultado


def test_sanitize_text_mnt():
    """sanitize_text redacta rutas /mnt/."""
    texto = "Datos en /mnt/nextcloud-rol/leyenda/sesion01.json"
    resultado = sanitize_text(texto)
    assert "/mnt/" not in resultado
    assert "[RUTA_INTERNA]" in resultado


def test_sanitize_object_recursivo():
    """sanitize_object redacta en estructuras anidadas."""
    obj = {
        "workspace": "leyenda",
        "info": {
            "ruta": "/opt/knowledge-services/repo",
            "servidor": "192.168.1.205",
            "lista": ["/mnt/datos/archivo.json", "texto_ok"],
        },
        "token": "mi_token_secreto",
    }
    result = sanitize_object(obj)
    assert result["workspace"] == "leyenda"
    assert "/opt/" not in result["info"]["ruta"]
    assert "192.168.1.205" not in result["info"]["servidor"]
    assert "/mnt/" not in result["info"]["lista"][0]
    assert "texto_ok" in result["info"]["lista"]


def test_external_review_request_sanitizado(tmp_path):
    """build_external_review_request no contiene /opt/, 192.168. ni /mnt/."""
    # Plantamos datos sensibles en los segmentos
    repo_root = _make_repo_dir(tmp_path)
    ws_dir = repo_root / "output" / "reviews" / "test_ws" / "media_test"
    # Inyectar ruta interna en segmentos
    segments_con_secreto = [
        {
            "segment_id": "media_test_seg_0001",
            "source_id": "media_test",
            "source_kind": "audio",
            "workspace": "test_ws",
            "timestamp_start": "00:00:00",
            "timestamp_end": "00:05:00",
            "text": "Archivo en /opt/knowledge-services/secret.db y servidor 192.168.1.205",
            "lines": [],
        }
    ]
    (ws_dir / "segments.json").write_text(json.dumps(segments_con_secreto), encoding="utf-8")

    # Tambien en candidates
    candidates_con_secreto = [
        {
            "candidate_id": "x001",
            "source_id": "media_test",
            "segment_id": "media_test_seg_0001",
            "workspace": "test_ws",
            "kind": "entity",
            "name": "NPC",
            "entity_type": "Character",
            "from_entity": None,
            "to_entity": None,
            "from_type": None,
            "to_type": None,
            "relation_type": None,
            "event_description": None,
            "confidence": 0.8,
            "evidence": "ruta /mnt/nextcloud-rol/leyenda y IP 192.168.1.205",
            "timestamp_start": "00:00:00",
            "timestamp_end": "00:05:00",
            "source_kind": "audio",
            "status": "pending",
        }
    ]
    (ws_dir / "candidates.json").write_text(json.dumps(candidates_con_secreto), encoding="utf-8")

    req = build_external_review_request("test_ws", "media_test", repo_root)
    req_str = json.dumps(req)

    assert "/opt/" not in req_str, "Ruta /opt/ encontrada en request externo!"
    assert "192.168." not in req_str, "IP interna encontrada en request externo!"
    assert "/mnt/" not in req_str, "Ruta /mnt/ encontrada en request externo!"
    assert "[RUTA_INTERNA]" in req_str or "[IP_INTERNA]" in req_str


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: ExternalReviewResponse invalida -> rechazada
# ─────────────────────────────────────────────────────────────────────────────

def test_external_response_invalida_json_no_dict():
    """Una lista (no dict) es invalida."""
    valid, errors = ExternalReviewResponse.validate([])
    assert valid is False
    assert any("dict" in e for e in errors)


def test_external_response_invalida_sin_evidence():
    """Candidato sin evidence -> invalido."""
    data = {
        "package_type": "external_review_response",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": "leyenda",
        "suggested_entities": [
            {
                "kind": "entity",
                "name": "Alguien",
                "entity_type": "Character",
                "confidence": 0.8,
                # SIN evidence -> invalido
            }
        ],
    }
    valid, errors = ExternalReviewResponse.validate(data)
    assert valid is False
    assert any("evidence" in e for e in errors)


def test_external_response_invalida_tipo_desconocido():
    """Candidato con kind desconocido -> invalido."""
    data = {
        "package_type": "external_review_response",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": "leyenda",
        "suggested_entities": [
            {
                "kind": "TIPO_INVENTADO",
                "name": "X",
                "entity_type": "Character",
                "confidence": 0.8,
                "evidence": "texto",
            }
        ],
    }
    valid, errors = ExternalReviewResponse.validate(data)
    assert valid is False
    assert any("kind" in e.lower() for e in errors)


def test_external_response_invalida_sin_workspace():
    """Sin workspace -> invalido."""
    data = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "suggested_entities": [],
    }
    valid, errors = ExternalReviewResponse.validate(data)
    assert valid is False
    assert any("workspace" in e for e in errors)


def test_external_response_load_invalida_lanza_valueerror():
    """load() con respuesta invalida lanza ValueError."""
    data = {"schema_version": PACKAGE_SCHEMA_VERSION}  # sin workspace ni suggested_entities
    with pytest.raises(ValueError, match="invalida"):
        load_external_response(data)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: external response valida -> candidatos con origin='external'
# ─────────────────────────────────────────────────────────────────────────────

def test_external_response_valida_origin_external():
    """Respuesta externa valida produce candidatos con origin='external'."""
    data = _make_valid_external_response()
    candidates = load_external_response(data)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["origin"] == "external"
    assert cand["name"] == "Maestro Hanzo"
    assert cand["status"] == "pending"


def test_external_response_nunca_approved_directo():
    """Los candidatos de una respuesta externa NO tienen review_status=auto_approved.
    Tienen status='pending' para pasar por el pipeline."""
    data = _make_valid_external_response()
    candidates = load_external_response(data)

    for cand in candidates:
        # Nunca deben venir pre-aprobados
        assert cand.get("review_status") is None
        assert cand["status"] == "pending"


def test_external_response_to_candidates_multiples_tipos():
    """external_response_to_candidates procesa entidades, relaciones y aliases."""
    data = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": "leyenda",
        "source_id": "media_test",
        "suggested_entities": [
            {"kind": "entity", "name": "Hanzo", "entity_type": "Character", "confidence": 0.9, "evidence": "texto"}
        ],
        "suggested_relations": [
            {"kind": "relation", "from_entity": "Hanzo", "to_entity": "Clan", "relation_type": "pertenece_a", "confidence": 0.8, "evidence": "texto"}
        ],
        "suggested_aliases": [
            {"kind": "alias", "name": "Han", "evidence": "forma corta de Hanzo", "confidence": 0.7}
        ],
    }
    candidates = external_response_to_candidates(data)
    assert len(candidates) == 3
    origins = {c["origin"] for c in candidates}
    assert origins == {"external"}


def test_external_response_workspace_mismatch():
    """load con workspace distinto al del paquete lanza ValueError."""
    data = _make_valid_external_response(workspace="leyenda")
    with pytest.raises(ValueError, match="Workspace no coincide"):
        load_external_response(data, workspace="otro_workspace")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: ImportedCandidatePackage sin workspace -> rechazado
# ─────────────────────────────────────────────────────────────────────────────

def test_imported_package_sin_workspace_rechazado():
    """ImportedCandidatePackage sin workspace -> invalido."""
    data = {
        "package_type": "imported_candidate_package",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        # SIN workspace
        "source_id": "media_ext",
        "candidates": [
            {"kind": "entity", "name": "X", "evidence": "texto", "confidence": 0.8}
        ],
    }
    valid, errors = validate_imported_package(data)
    assert valid is False
    assert any("workspace" in e for e in errors)


def test_imported_package_sin_candidates_rechazado():
    """ImportedCandidatePackage sin campo candidates -> invalido."""
    data = {
        "package_type": "imported_candidate_package",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": "leyenda",
        "source_id": "media_ext",
        # SIN candidates
    }
    valid, errors = validate_imported_package(data)
    assert valid is False
    assert any("candidates" in e for e in errors)


def test_imported_package_valido_origin_imported():
    """ImportedCandidatePackage valido produce candidatos con origin='imported'."""
    data = {
        "package_type": "imported_candidate_package",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": "leyenda",
        "source_id": "media_ext",
        "candidates": [
            {
                "kind": "entity",
                "name": "Ronin Externo",
                "entity_type": "Character",
                "evidence": "El personaje externo aparece en la escena",
                "confidence": 0.75,
                "timestamp_start": "00:01:00",
                "timestamp_end": "00:02:00",
            }
        ],
    }
    candidates = load_imported_package(data)
    assert len(candidates) == 1
    assert candidates[0]["origin"] == "imported"
    assert candidates[0]["status"] == "pending"
    assert candidates[0]["name"] == "Ronin Externo"


def test_imported_package_candidato_sin_evidence_rechazado():
    """Candidato sin evidence -> paquete invalido."""
    data = {
        "package_type": "imported_candidate_package",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "workspace": "leyenda",
        "source_id": "media_ext",
        "candidates": [
            {
                "kind": "entity",
                "name": "Sin evidencia",
                "entity_type": "Character",
                "confidence": 0.8,
                # SIN evidence
            }
        ],
    }
    valid, errors = validate_imported_package(data)
    assert valid is False
    assert any("evidence" in e for e in errors)


def test_imported_package_load_invalido_lanza_valueerror():
    """load() de paquete invalido lanza ValueError."""
    data = {"workspace": "leyenda"}  # incompleto
    with pytest.raises(ValueError, match="invalido"):
        load_imported_package(data)

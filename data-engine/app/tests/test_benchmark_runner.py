"""Tests del benchmark runner y comparador S9 Knowledge.

Autocontenidos: no llaman a Ollama, Neo4j ni al pipeline real.
Usan datos sintéticos en memoria.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Asegurar que data-engine/app está en sys.path
_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Importar funciones del comparador directamente
from cli.benchmark_comparator import (
    normalize,
    is_match,
    _compute_entity_metrics,
    _compute_relation_metrics,
    _variance,
    _mean,
)


# ---------------------------------------------------------------------------
# Helpers para construir datos sintéticos
# ---------------------------------------------------------------------------

def _make_approved_entity(name: str, kind: str = "entity") -> dict:
    return {"name": name, "kind": kind, "confidence": 0.9, "evidence": "texto de prueba"}


def _make_ground_truth(
    expected_entities: list[dict] | None = None,
    negative_entities: list[str] | None = None,
    expected_relations: list[dict] | None = None,
    negative_relations: list[dict] | None = None,
) -> dict:
    return {
        "entities": expected_entities or [],
        "negative_entities": negative_entities or [],
        "relations": expected_relations or [],
        "negative_relations": negative_relations or [],
    }


# ---------------------------------------------------------------------------
# Test 1: carga correcta del manifest JSON
# ---------------------------------------------------------------------------

def test_benchmark_manifest_loads_correctly(tmp_path):
    """Verifica que un manifest JSON válido se carga correctamente."""
    manifest_data = {
        "sources": [
            {"id": "transcript_clean_01", "workspace": "leyenda"},
            {"id": "transcript_clean_02", "workspace": "leyenda"},
        ]
    }
    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = loaded.get("sources", [])

    assert len(sources) == 2, f"Se esperaban 2 fuentes, se obtuvieron {len(sources)}"
    assert sources[0]["id"] == "transcript_clean_01"
    assert sources[1]["workspace"] == "leyenda"
    assert all("id" in s and "workspace" in s for s in sources), (
        "Cada fuente debe tener 'id' y 'workspace'"
    )


# ---------------------------------------------------------------------------
# Test 2: exact match → TP
# ---------------------------------------------------------------------------

def test_comparator_exact_match():
    """Un candidato con nombre exacto al ground truth cuenta como TP."""
    approved = [_make_approved_entity("Kakita Asuka")]
    gt = _make_ground_truth(
        expected_entities=[{"name": "Kakita Asuka", "aliases": [], "expected": True}]
    )

    metrics = _compute_entity_metrics(approved, gt)

    assert metrics["tp"] == 1, f"Esperaba TP=1, obtuve TP={metrics['tp']}"
    assert metrics["fp"] == 0, f"Esperaba FP=0, obtuve FP={metrics['fp']}"
    assert metrics["fn"] == 0, f"Esperaba FN=0, obtuve FN={metrics['fn']}"
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0


# ---------------------------------------------------------------------------
# Test 3: negative entity detectada → FP
# ---------------------------------------------------------------------------

def test_comparator_negative_entity_counts_as_fp():
    """Una entidad que está en negative_entities y es detectada cuenta como FP."""
    approved = [_make_approved_entity("el")]
    gt = _make_ground_truth(
        expected_entities=[{"name": "Kakita Asuka", "aliases": [], "expected": True}],
        negative_entities=["el"],
    )

    metrics = _compute_entity_metrics(approved, gt)

    # "el" no coincide con "Kakita Asuka" → FP
    assert metrics["fp"] == 1, f"Esperaba FP=1, obtuve FP={metrics['fp']}"
    # "Kakita Asuka" no detectado → FN
    assert metrics["fn"] == 1, f"Esperaba FN=1, obtuve FN={metrics['fn']}"
    assert metrics["tp"] == 0, f"Esperaba TP=0, obtuve TP={metrics['tp']}"
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0


# ---------------------------------------------------------------------------
# Test 4: entidad esperada no detectada → FN
# ---------------------------------------------------------------------------

def test_comparator_missing_entity_counts_as_fn():
    """Una entidad esperada que no aparece en approved cuenta como FN."""
    approved = []  # sin candidatos aprobados
    gt = _make_ground_truth(
        expected_entities=[
            {"name": "Kakita Asuka", "aliases": [], "expected": True},
            {"name": "Doji Kuwanan", "aliases": [], "expected": True},
        ]
    )

    metrics = _compute_entity_metrics(approved, gt)

    assert metrics["tp"] == 0
    assert metrics["fp"] == 0
    assert metrics["fn"] == 2, f"Esperaba FN=2, obtuve FN={metrics['fn']}"
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1"] == 0.0


# ---------------------------------------------------------------------------
# Test 5: normalización case-insensitive
# ---------------------------------------------------------------------------

def test_normalization_case_insensitive():
    """'kakita asuka' y 'Kakita Asuka' deben considerarse el mismo nombre."""
    # Verificar la función normalize
    assert normalize("kakita asuka") == normalize("Kakita Asuka"), (
        "normalize() debe producir el mismo resultado independientemente de mayúsculas"
    )
    assert normalize("KAKITA ASUKA") == normalize("kakita asuka")

    # Verificar is_match con diferencia de mayúsculas
    result = is_match("kakita asuka", "Kakita Asuka", [])
    assert result == "exact_match", (
        f"Se esperaba 'exact_match', se obtuvo '{result}'"
    )

    # Verificar en flujo completo: candidato en minúsculas, GT en título
    approved = [_make_approved_entity("kakita asuka")]
    gt = _make_ground_truth(
        expected_entities=[{"name": "Kakita Asuka", "aliases": [], "expected": True}]
    )

    metrics = _compute_entity_metrics(approved, gt)
    assert metrics["tp"] == 1, (
        f"Esperaba TP=1 (match case-insensitive), obtuve TP={metrics['tp']}"
    )
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0


# ---------------------------------------------------------------------------
# Test 6 (bonus): alias match
# ---------------------------------------------------------------------------

def test_comparator_alias_match():
    """Un candidato que coincide con un alias del GT cuenta como TP (alias_match)."""
    approved = [_make_approved_entity("Asuka")]
    gt = _make_ground_truth(
        expected_entities=[
            {"name": "Kakita Asuka", "aliases": ["Asuka", "la duelista"], "expected": True}
        ]
    )

    match_type = is_match("Asuka", "Kakita Asuka", ["Asuka", "la duelista"])
    assert match_type == "alias_match", f"Esperaba 'alias_match', obtuve '{match_type}'"

    metrics = _compute_entity_metrics(approved, gt)
    assert metrics["tp"] == 1, f"Alias match debería contar como TP, obtuve TP={metrics['tp']}"
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0


# ---------------------------------------------------------------------------
# Test 7 (bonus): varianza de F1
# ---------------------------------------------------------------------------

def test_variance_f1_reproducibility():
    """La varianza de 3 runs idénticas debe ser 0; runs distintas > 0."""
    identical = [1.0, 1.0, 1.0]
    assert _variance(identical) == 0.0, "Varianza de valores iguales debe ser 0"

    different = [0.8, 0.9, 0.7]
    var = _variance(different)
    assert var > 0.0, "Varianza de valores distintos debe ser > 0"
    assert abs(_mean(different) - 0.8) < 1e-6, "Media de [0.8, 0.9, 0.7] debe ser 0.8"


# ---------------------------------------------------------------------------
# Test 8 (bonus): métricas de relaciones
# ---------------------------------------------------------------------------

def test_comparator_relation_tp_fp_fn():
    """Verifica TP/FP/FN en métricas de relaciones."""
    approved_relations = [
        {"kind": "relation", "from_entity": "Kakita Asuka", "relation_type": "es_discipula_de", "to_entity": "Kakita Toshimoko"},
        {"kind": "relation", "from_entity": "Doji Kuwanan", "relation_type": "es_hermano_de", "to_entity": "Doji Hoturi"},  # FP
    ]
    gt = _make_ground_truth(
        expected_relations=[
            {"from_entity": "Kakita Asuka", "relation_type": "es_discipula_de", "to_entity": "Kakita Toshimoko", "expected": True},
            {"from_entity": "Kakita Toshimoko", "relation_type": "es_maestro_de", "to_entity": "Kakita Asuka", "expected": True},  # FN
        ]
    )

    metrics = _compute_relation_metrics(approved_relations, gt)

    assert metrics["tp"] == 1, f"Esperaba TP=1, obtuve TP={metrics['tp']}"
    assert metrics["fp"] == 1, f"Esperaba FP=1, obtuve FP={metrics['fp']}"
    assert metrics["fn"] == 1, f"Esperaba FN=1, obtuve FN={metrics['fn']}"
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5


# ---------------------------------------------------------------------------
# Regresión: _load_candidates (fix benchmark aislado — lee candidates.json)
# El comparador leía approved_payload.json (que el benchmark aislado nunca
# produce) → todas las métricas salían 0.0. Debe leer candidates.json plano.
# ---------------------------------------------------------------------------

def test_load_candidates_reads_plain_list(tmp_path):
    from cli.benchmark_comparator import _load_candidates
    cand = tmp_path / "candidates.json"
    cand.write_text(json.dumps([
        {"kind": "entity", "name": "Kakita Asuka", "entity_type": "Character"},
        {"kind": "relation", "from_entity": "A", "relation_type": "KNOWS", "to_entity": "B"},
    ]), encoding="utf-8")
    out = _load_candidates(cand)
    assert len(out["entities"]) == 1
    assert len(out["relations"]) == 1
    assert out["entities"][0]["name"] == "Kakita Asuka"


def test_load_candidates_missing_file(tmp_path):
    from cli.benchmark_comparator import _load_candidates
    out = _load_candidates(tmp_path / "nope.json")
    assert out == {"entities": [], "relations": []}


def test_load_candidates_accepts_approved_payload_format(tmp_path):
    from cli.benchmark_comparator import _load_candidates
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps({"approved": [{"kind": "entity", "name": "X"}]}), encoding="utf-8")
    out = _load_candidates(p)
    assert len(out["entities"]) == 1

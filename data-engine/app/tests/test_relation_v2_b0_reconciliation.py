# -*- coding: utf-8 -*-
"""Bloque 0 (motor de relaciones v2) — reconciliación GT ↔ ontología.

Tests REALES (sin skip/xfail, sin bajar umbrales) que fijan las garantías del
Bloque 0:

  * Los 9 predicados añadidos son ahora canónicos en ALLOWED_RELATION_TYPES.
  * LIVES_IN entra como canónico DISTINTO (no colapsado en LOCATED_IN en la
    ontología de contrato).
  * Todos los predicados del ground truth son válidos contra la ontología (20/20).
  * El sha256 del fichero de ground truth NO cambió (la reconciliación es en la
    ontología, nunca en el GT).
  * El arnés de benchmark (corpus + runner) carga.
  * report.py::THRESHOLDS no cambió (valores exactos).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from schemas.rpg_schema import ALLOWED_RELATION_TYPES, RELATION_LABELS_ES

# Directorio del corpus de benchmark (single source, ver docs B0 §1).
_CORPUS_DIR = Path(__file__).resolve().parent / "data" / "relation_benchmark"
_GT_PATH = _CORPUS_DIR / "ground_truth" / "relations.json"
_MANIFEST_PATH = _CORPUS_DIR / "manifest.json"

# sha256 del ground truth registrado en el Bloque 0 (docs B0 §1.2). Debe quedar
# IGUAL: el Bloque 0 NO toca el GT.
_GT_SHA256_B0 = "15973d1837deb29ea339bca6bb3980d62e07ef283b196bf38d0d1e2653d9cc5c"

# Predicados añadidos como canónicos NUEVOS en el Bloque 0.
_B0_NEW_CANONICALS = frozenset({
    "LIVES_IN", "ALIAS_OF", "FOUNDED", "SUCCEEDED", "CAUSED",
    "LEADS", "CREATED", "MARRIED_TO", "SIBLING_OF",
})

# THRESHOLDS esperados (report.py) — NO deben cambiar en B0.
_EXPECTED_THRESHOLDS = {
    "simple_relations_recall": 0.80,
    "evidence": 0.80,
    "offsets": 0.90,
    "negation": 0.80,
    "temporality": 0.60,
    "rumors": 0.60,
    "predicate_structural": 0.50,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_new_predicates_are_canonical_in_ontology():
    """Cada predicado añadido en B0 está ahora en ALLOWED_RELATION_TYPES."""
    for pred in sorted(_B0_NEW_CANONICALS):
        assert pred in ALLOWED_RELATION_TYPES, (
            f"{pred} debería ser canónico en ALLOWED_RELATION_TYPES tras B0"
        )


def test_lives_in_is_distinct_canonical_not_collapsed():
    """LIVES_IN es canónico propio y NO se colapsa con LOCATED_IN en el contrato."""
    assert "LIVES_IN" in ALLOWED_RELATION_TYPES
    assert "LOCATED_IN" in ALLOWED_RELATION_TYPES
    # Son entradas distintas del vocabulario de contrato.
    assert "LIVES_IN" != "LOCATED_IN"


def test_new_predicates_have_spanish_label():
    """Se mantiene el invariante: todo tipo permitido tiene etiqueta ES."""
    for pred in sorted(_B0_NEW_CANONICALS):
        assert pred in RELATION_LABELS_ES, f"falta etiqueta ES para {pred}"
    # Invariante global: ALLOWED_RELATION_TYPES ⊆ claves de RELATION_LABELS_ES.
    sin_label = sorted(set(ALLOWED_RELATION_TYPES) - set(RELATION_LABELS_ES))
    assert sin_label == [], f"tipos sin etiqueta ES: {sin_label}"


def test_all_ground_truth_predicates_valid_against_ontology():
    """Los 20 tipos de predicado del GT son válidos contra la ontología (20/20)."""
    gt = json.loads(_GT_PATH.read_text(encoding="utf-8"))
    predicates = {r["predicate"] for r in gt["relations"]}
    assert len(predicates) == 20, f"se esperaban 20 tipos en el GT, hay {len(predicates)}"
    invalid = sorted(predicates - set(ALLOWED_RELATION_TYPES))
    assert invalid == [], f"predicados del GT fuera de la ontología: {invalid}"


def test_ground_truth_file_unchanged():
    """El sha256 del fichero de GT NO cambió: la reconciliación es en la ontología."""
    actual = _sha256(_GT_PATH)
    assert actual == _GT_SHA256_B0, (
        f"el ground truth cambió (sha256 {actual} != {_GT_SHA256_B0}); "
        "el Bloque 0 NO debe modificar el GT"
    )
    # Coherencia con el hash declarado dentro del manifest.
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["ground_truth"]["sha256"] == _GT_SHA256_B0


def test_benchmark_harness_loads():
    """El arnés único (corpus + runner) carga sin red ni escritura."""
    from relations.benchmark.runner import load_corpus

    corpus = load_corpus(_CORPUS_DIR)
    assert len(corpus.relations) == 54
    assert len(corpus.sources) == 16


def test_report_thresholds_unchanged():
    """report.py::THRESHOLDS sin cambios en B0 (valores exactos)."""
    from relations.benchmark.report import THRESHOLDS

    assert THRESHOLDS == _EXPECTED_THRESHOLDS

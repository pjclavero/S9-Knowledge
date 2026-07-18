"""
test_docs_consistency.py — pruebas del validador de coherencia documental.

Verifica que scripts/check_docs_consistency.py:
  1. detecta afirmaciones obsoletas;
  2. respeta los bloques históricos marcados;
  3. respeta las negaciones ("Basic Auth retirada" no es un fallo);
  4. da coherente sobre el repositorio real (los docs versionados están al día).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "check_docs_consistency.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_consistency", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_repo_docs_are_coherent():
    """El estado versionado no debe contener contradicciones conocidas."""
    mod = _load()
    assert mod.main() == 0


def test_detects_obsolete_basic_auth(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("El acceso externo usa nginx + Basic Auth como autenticación.\n")
    findings = mod.scan_doc(doc)
    assert any("basic-auth-vigente" in f for f in findings), findings


def test_negation_suppresses_basic_auth(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("Basic Auth retirada del proxy; autenticación en la app.\n")
    assert mod.scan_doc(doc) == []


def test_historical_block_is_ignored(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text(
        "# Guía vigente\n"
        "Todo correcto.\n"
        "## HISTÓRICO — diseño inicial\n"
        "En su día el visor solo tenía Basic Auth y 220 tests.\n"
    )
    # La frase obsoleta vive bajo un encabezado histórico -> no se marca.
    assert mod.scan_doc(doc) == []


def test_inline_ignore_marker(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("Antes: Basic Auth en el proxy. <!-- consistency:ignore -->\n")
    assert mod.scan_doc(doc) == []


def test_detects_fixed_test_count(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("La suite tiene 220 tests verdes.\n")
    findings = mod.scan_doc(doc)
    assert any("tests-fijos" in f for f in findings), findings

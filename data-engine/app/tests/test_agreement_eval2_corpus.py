# -*- coding: utf-8 -*-
"""ACUERDO-2: integridad del corpus nuevo `agreement-eval2` y de su medicion
(`scripts/agreement/measure_agreement2.py`), ver docs/v3/48.

SIN RED: toda respuesta "de NVIDIA" en este fichero es un `MockProviderPort`
guionizado (via `--mock`), la misma disciplina que `test_agreement_shadow.py`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP.parents[1]
_SCRIPTS = _REPO_ROOT / "scripts" / "agreement"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from knowledge_v3.benchmarks.loader import load_gold  # noqa: E402
from knowledge_v3.eval.dev_corpus import verify_integrity  # noqa: E402

SPLIT = "agreement-eval2"


def test_manifiesto_declara_el_split_correcto():
    manifest = json.loads(
        (_APP / "knowledge_v3" / "benchmarks" / "datasets" / SPLIT / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["split"] == SPLIT
    assert manifest["totals"]["claims"] >= 30
    assert manifest["totals"]["episodes"] >= 30
    assert len(manifest["sources"]) == 3


def test_integridad_del_corpus_por_hash():
    """Recalcula el hash de cada fichero del split contra su manifiesto: rompe
    si algo del corpus se toco a mano sin regenerar via build_agreement_eval2.py."""
    verify_integrity(SPLIT)


def test_el_corpus_carga_con_el_cargador_generico_de_benchmarks():
    gold = load_gold(SPLIT)
    assert len(gold.episodes) >= 30
    assert len(gold.claims_for("extractor")) >= 30


def test_entidades_no_se_solapan_con_negation_ni_dev_ni_heldout():
    """Regla de autoria del bloque: ningun entity_id, ningun nombre propio,
    de `agreement-eval2` puede coincidir con los de `negation` (el split que
    este corpus amplia). No se pretende exhaustividad total del repo, solo la
    comprobacion automatizable y barata: los mundos declarados."""
    ours = json.loads(
        (_APP / "knowledge_v3" / "benchmarks" / "datasets" / SPLIT / "catalog" / "entities.json").read_text(encoding="utf-8")
    )
    negation = json.loads(
        (_APP / "knowledge_v3" / "benchmarks" / "datasets" / "negation" / "catalog" / "entities.json").read_text(encoding="utf-8")
    )
    our_ids = {e["entity_id"] for e in ours["entities"]}
    their_ids = {e["entity_id"] for e in negation["entities"]}
    assert our_ids.isdisjoint(their_ids)
    our_worlds = set(ours["worlds"])
    their_worlds = set(negation["worlds"])
    assert our_worlds.isdisjoint(their_worlds)
    assert our_worlds.isdisjoint({"leyenda", "mareas", "kestrel", "ferrovia", "micelio", "liga"})


def test_measure_agreement2_mock_run_end_to_end_no_escribe_fuera_del_directorio_de_salida(tmp_path):
    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    before = {p for p in _REPO_ROOT.rglob("*") if ".git" not in p.parts and "worktrees" not in p.parts}
    result = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "measure_agreement2.py"),
            "--mock", "--out-dir", str(out_dir), "--out-name", "mock-run",
            "--cache", str(cache_dir),
        ],
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(_APP)},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    after = {p for p in _REPO_ROOT.rglob("*") if ".git" not in p.parts and "worktrees" not in p.parts}
    nuevos = after - before
    inesperados = [p for p in nuevos if _REPO_ROOT in p.parents and out_dir not in p.parents and cache_dir not in p.parents]
    assert inesperados == [], f"la corrida en sombra escribio ficheros inesperados: {inesperados}"
    payload = json.loads((out_dir / "mock-run.json").read_text(encoding="utf-8"))
    assert payload["mock"] is True
    assert payload["split"] == SPLIT
    assert payload["agreement"]["evaluable_total"] >= 30


def test_measure_agreement2_nunca_carga_el_driver_neo4j(tmp_path):
    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    snippet = (
        "import sys, runpy\n"
        "sys.argv = ['measure_agreement2.py', '--mock', "
        f"'--out-dir', {str(out_dir)!r}, '--out-name', 'r', "
        f"'--cache', {str(cache_dir)!r}]\n"
        "try:\n"
        f"    runpy.run_path({str(_SCRIPTS / 'measure_agreement2.py')!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    assert exc.code in (0, None), f'measure_agreement2.py salio con {exc.code}'\n"
        "assert 'neo4j' not in sys.modules, 'la corrida cargo el driver neo4j'\n"
        "print('OK_SIN_NEO4J')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONPATH": str(_APP)},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert "OK_SIN_NEO4J" in result.stdout


def test_la_api_key_real_nunca_aparece_en_la_salida_de_measure_agreement2(tmp_path):
    env_path = Path.home() / ".config" / "s9k" / "nvidia.env"
    if not env_path.exists():
        pytest.skip("no hay ~/.config/s9k/nvidia.env en esta maquina; nada que comprobar")
    key = None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and "KEY" in line.upper():
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        pytest.skip("no se pudo extraer una key del fichero de entorno")

    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    result = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "measure_agreement2.py"), "--mock",
            "--out-dir", str(out_dir), "--out-name", "r", "--cache", str(cache_dir),
        ],
        cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONPATH": str(_APP)}, capture_output=True, text=True, timeout=180,
    )
    assert key not in result.stdout
    assert key not in result.stderr
    for produced in out_dir.rglob("*"):
        if produced.is_file():
            assert key not in produced.read_text(encoding="utf-8", errors="replace")


def test_la_api_key_real_no_aparece_en_los_artefactos_ya_commiteados_de_agreement_eval2():
    env_path = Path.home() / ".config" / "s9k" / "nvidia.env"
    if not env_path.exists():
        pytest.skip("no hay ~/.config/s9k/nvidia.env en esta maquina; nada que comprobar")
    key = None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and "KEY" in line.upper():
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        pytest.skip("no se pudo extraer una key del fichero de entorno")
    agreement_dir = _REPO_ROOT / "artifacts" / "agreement"
    if not agreement_dir.exists():
        pytest.skip("artifacts/agreement no existe todavia en este checkout")
    for path in agreement_dir.rglob("*"):
        if path.is_file():
            assert key not in path.read_text(encoding="utf-8", errors="replace")

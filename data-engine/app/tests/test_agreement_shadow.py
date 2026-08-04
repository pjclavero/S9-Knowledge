# -*- coding: utf-8 -*-
"""Medicion en sombra del acuerdo determinista ∧ NVIDIA (`scripts/agreement/`).

SIN RED: toda respuesta "de NVIDIA" en este fichero es un `MockProviderPort`
guionizado (via `--mock`, la misma disciplina que `test_gate4_b3_nvidia_shadow.py`).

Los tests cubren:

  * `compute_agreement`: el emparejamiento/scoring de los 4 (+1) conjuntos,
    con fixtures de filas sinteticas -- sin invocar el pipeline real.
  * que el modo sombra no escribe nada fuera del directorio de salida (el
    writer de `pipeline.runner.run_one` va siempre DRY-RUN, sin bandera que
    lo cambie -- se comprueba con una corrida `--mock` completa).
  * que la key de NVIDIA (si existe en esta maquina, `~/.config/s9k/
    nvidia.env`) no aparece en ninguna salida generada por esta suite.
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

import measure_agreement as ag  # noqa: E402  (path insertado arriba a proposito)


def _row(
    claim_id: str,
    *,
    covered: bool,
    expected_negated: bool,
    predicted_negated: bool = False,
    predicted_decision: str = "ACCEPT",
    predicted_predicate: str | None = "p:leads",
) -> dict:
    return {
        "gold_claim_id": claim_id,
        "covered": covered,
        "expected_negated": expected_negated,
        "predicted_negated": predicted_negated,
        "predicted_decision": predicted_decision,
        "predicted_predicate": predicted_predicate,
    }


# ---------------------------------------------------------------------------
# compute_agreement: los 4 (+1) conjuntos, con fixtures (sin red)
# ---------------------------------------------------------------------------
def test_acuerdo_exige_ambos_carriles_cubiertos_misma_polaridad_y_ambos_accept():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False, predicted_decision="ACCEPT")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False, predicted_decision="ACCEPT")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo"]["n"] == 1
    assert out["acuerdo"]["cases"][0]["correct"] is True
    assert out["acuerdo"]["precision"] == 1.0
    assert out["acuerdo"]["recall_sobre_gold"] == 1.0


def test_acuerdo_detecta_error_compartido_como_falso_positivo_del_conjunto():
    """Ambos carriles coinciden en polaridad, pero DISCREPAN del gold: el
    acuerdo no es infalible por construccion -- esto es justo lo que la
    metrica de precision del bloque tiene que poder capturar."""
    det = {"c1": _row("c1", covered=True, expected_negated=True, predicted_negated=False, predicted_decision="ACCEPT")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=True, predicted_negated=False, predicted_decision="ACCEPT")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo"]["n"] == 1
    assert out["acuerdo"]["cases"][0]["correct"] is False
    assert out["acuerdo"]["precision"] == 0.0


def test_polaridad_distinta_es_discrepancia_no_acuerdo():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False, predicted_decision="ACCEPT")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=True, predicted_decision="ACCEPT")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo"]["n"] == 0
    assert out["discrepancia"]["n"] == 1
    assert out["discrepancia"]["cases"][0]["reason"] == "polaridad_incompatible"


def test_predicado_distinto_es_discrepancia():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate="p:leads")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate="p:betrays")}
    out = ag.compute_agreement(det, nvidia)
    assert out["discrepancia"]["n"] == 1
    assert out["discrepancia"]["cases"][0]["reason"] == "predicado_incompatible"


def test_predicado_ausente_en_un_carril_se_declara_compatible_por_omision():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate=None)}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate="p:leads")}
    out = ag.compute_agreement(det, nvidia)
    assert out["discrepancia"]["n"] == 0
    assert out["acuerdo"]["n"] == 1


def test_misma_polaridad_pero_no_ambos_accept_va_a_degradado_no_acuerdo():
    """Puerta 6: un REVIEW real (factividad degradada o evidencia no
    verificada) en cualquiera de los dos carriles impide el acuerdo, aunque
    ambos coincidan en polaridad."""
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="REVIEW")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo"]["n"] == 0
    assert out["degradado_no_acuerdo"]["n"] == 1
    assert out["degradado_no_acuerdo"]["cases"][0]["reason"] == "det=ACCEPT nvidia=REVIEW"


def test_solo_un_carril_cubierto_va_a_solo_det_o_solo_nvidia():
    det = {
        "c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False),
        "c2": _row("c2", covered=False, expected_negated=True),
    }
    nvidia = {
        "c1": _row("c1", covered=False, expected_negated=False),
        "c2": _row("c2", covered=True, expected_negated=True, predicted_negated=True),
    }
    out = ag.compute_agreement(det, nvidia)
    assert out["solo_det"]["n"] == 1
    assert out["solo_det"]["cases"][0]["claim_id"] == "c1"
    assert out["solo_det"]["cases"][0]["correct"] is True
    assert out["solo_nvidia"]["n"] == 1
    assert out["solo_nvidia"]["cases"][0]["claim_id"] == "c2"
    assert out["acuerdo"]["n"] == 0


def test_ningun_carril_cubierto_va_a_sin_cubrir_y_no_cuenta_en_ningun_otro_conjunto():
    det = {"c1": _row("c1", covered=False, expected_negated=False)}
    nvidia = {"c1": _row("c1", covered=False, expected_negated=False)}
    out = ag.compute_agreement(det, nvidia)
    assert out["sin_cubrir"]["n"] == 1
    assert out["sin_cubrir"]["claim_ids"] == ["c1"]
    for key in ("acuerdo", "solo_det", "solo_nvidia"):
        assert out[key]["n"] == 0
    assert out["discrepancia"]["n"] == 0
    assert out["degradado_no_acuerdo"]["n"] == 0


def test_recall_del_acuerdo_es_sobre_TODO_el_evaluable_no_solo_lo_cubierto():
    """5 claims evaluables, solo 1 en acuerdo: el recall se lee sobre 5, no
    sobre el subconjunto cubierto -- si no, un acuerdo raro sobre pocos casos
    parecería más representativo de lo que es."""
    det = {f"c{i}": _row(f"c{i}", covered=(i == 1), expected_negated=False, predicted_decision="ACCEPT") for i in range(5)}
    nvidia = {f"c{i}": _row(f"c{i}", covered=(i == 1), expected_negated=False, predicted_decision="ACCEPT") for i in range(5)}
    out = ag.compute_agreement(det, nvidia)
    assert out["evaluable_total"] == 5
    assert out["acuerdo"]["n"] == 1
    assert out["acuerdo"]["recall_sobre_gold"] == 0.2


def test_conjuntos_dispares_de_claim_id_entre_carriles_rompe_por_diseno():
    """Los dos carriles corren sobre el MISMO gold: si sus filas no cubren
    exactamente el mismo universo de claim_id evaluables, algo aguas arriba
    esta mal (por ejemplo, una version del gold distinta por carril) y debe
    romper de forma ruidosa, no producir una comparacion silenciosamente
    incompleta."""
    det = {"c1": _row("c1", covered=True, expected_negated=False)}
    nvidia = {"c2": _row("c2", covered=True, expected_negated=False)}
    with pytest.raises(AssertionError):
        ag.compute_agreement(det, nvidia)


# ---------------------------------------------------------------------------
# Modo sombra: no escribe nada fuera de --out-dir; sin escritores de Neo4j
# ---------------------------------------------------------------------------
def test_measure_agreement_nunca_carga_el_driver_neo4j_ni_siquiera_en_una_corrida_completa(tmp_path):
    """Ejecuta una corrida `--mock` COMPLETA (ambos carriles, ambas ablaciones
    de `run_one`) en un subproceso NUEVO y comprueba, DESDE DENTRO de ese
    proceso, que el driver `neo4j` nunca se cargo -- la misma disciplina que
    `test_gate4_b3_nvidia_shadow.py`, adaptada a que aqui SI se ejecuta el
    writer (en DRY-RUN, via `pipeline.runner.run_one`). Un subproceso nuevo es
    IMPRESCINDIBLE aqui (a diferencia de un simple `assert 'neo4j' not in
    sys.modules` en este mismo proceso): a diferencia de `measure_b3.py`, este
    script SI importa `knowledge_v3.pipeline.runner` (la via designada para
    correr la cadena completa) y, con ella, `knowledge_v3.writer.executor`
    (deliberado y seguro: el writer va siempre DRY-RUN). Otros ficheros de la
    suite completa importan cosas que a su vez cargan el driver `neo4j` en
    `sys.modules` del proceso de test (por ejemplo `test_review_pipeline.py`),
    asi que comprobarlo en el proceso compartido daria un falso positivo por
    contaminacion cruzada -- la garantia real solo la da un proceso aislado."""
    out_dir = tmp_path / "out"
    snippet = (
        "import sys, runpy\n"
        f"sys.argv = ['measure_agreement.py', '--mock', '--out-dir', {str(out_dir)!r}, '--out-name', 'r']\n"
        "try:\n"
        f"    runpy.run_path({str(_SCRIPTS / 'measure_agreement.py')!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    assert exc.code in (0, None), f'measure_agreement.py salio con {exc.code}'\n"
        "assert 'neo4j' not in sys.modules, 'la corrida cargo el driver neo4j'\n"
        "print('OK_SIN_NEO4J')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONPATH": str(_APP)},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "OK_SIN_NEO4J" in result.stdout


def test_mock_run_end_to_end_no_escribe_fuera_del_directorio_de_salida(tmp_path):
    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    before = {p for p in _REPO_ROOT.rglob("*") if ".git" not in p.parts and "worktrees" not in p.parts}
    result = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "measure_agreement.py"),
            "--mock", "--out-dir", str(out_dir), "--out-name", "mock-run",
            "--cache", str(cache_dir),
        ],
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(_APP)},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    after = {p for p in _REPO_ROOT.rglob("*") if ".git" not in p.parts and "worktrees" not in p.parts}
    nuevos = after - before
    # Los unicos ficheros nuevos permitidos son los que cuelgan de tmp_path
    # (out_dir/cache_dir), que ya viven fuera de _REPO_ROOT -- si algo nuevo
    # aparecio DENTRO del repo, el modo sombra escribio donde no debia.
    inesperados = [p for p in nuevos if _REPO_ROOT in p.parents and out_dir not in p.parents and cache_dir not in p.parents]
    assert inesperados == [], f"la corrida en sombra escribio ficheros inesperados: {inesperados}"
    payload = json.loads((out_dir / "mock-run.json").read_text(encoding="utf-8"))
    assert payload["mock"] is True
    assert payload["agreement"]["evaluable_total"] == 56


def test_la_api_key_real_nunca_aparece_en_la_salida_de_este_fichero_de_test(capsys, tmp_path):
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
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "measure_agreement.py"), "--mock", "--out-dir", str(out_dir), "--out-name", "r"],
        cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONPATH": str(_APP)}, capture_output=True, text=True, timeout=120,
    )
    assert key not in result.stdout
    assert key not in result.stderr
    for produced in out_dir.rglob("*"):
        if produced.is_file():
            assert key not in produced.read_text(encoding="utf-8", errors="replace")


def test_la_api_key_real_no_aparece_en_los_artefactos_ya_commiteados_de_agreement():
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

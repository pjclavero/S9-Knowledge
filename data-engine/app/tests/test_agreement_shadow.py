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
# compute_agreement: acuerdo A NIVEL DE CONTENIDO (vista principal) + vista
# secundaria tautologica + discrepancia desglosada, con fixtures (sin red)
# ---------------------------------------------------------------------------
def test_acuerdo_contenido_NO_exige_accept_de_ningun_carril():
    """Ronda acotada del revisor: el criterio original (ACCEPT en ambos)
    hacia el n=0 tautologico. `acuerdo_contenido` solo exige mismo claim +
    predicado compatible + misma polaridad -- aqui con REVIEW/REVIEW, que el
    criterio viejo hubiera excluido."""
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False, predicted_decision="REVIEW")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False, predicted_decision="REVIEW")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo_contenido"]["n"] == 1
    assert out["acuerdo_contenido"]["cases"][0]["correct"] is True
    assert out["acuerdo_contenido"]["cases"][0]["decision_pair"] == "REVIEW/REVIEW"
    assert out["acuerdo_contenido"]["precision"] == 1.0
    assert out["acuerdo_contenido"]["recall_sobre_gold"] == 1.0
    # La vista tautologica (ACCEPT/ACCEPT) sigue vacia: es exactamente el
    # comportamiento que el dictamen del revisor senalo como esperable.
    assert out["acuerdo_con_accept"]["n"] == 0


def test_desglose_por_par_de_decisiones_separa_cada_celda():
    det = {
        "c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT"),
        "c2": _row("c2", covered=True, expected_negated=False, predicted_decision="REVIEW"),
        "c3": _row("c3", covered=True, expected_negated=True, predicted_negated=True, predicted_decision="ACCEPT"),
    }
    nvidia = {
        "c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT"),
        "c2": _row("c2", covered=True, expected_negated=False, predicted_decision="REVIEW"),
        "c3": _row("c3", covered=True, expected_negated=True, predicted_negated=True, predicted_decision="ACCEPT"),
    }
    out = ag.compute_agreement(det, nvidia)
    desglose = out["acuerdo_contenido"]["desglose_por_par_de_decisiones"]
    assert desglose["ACCEPT/ACCEPT"]["n"] == 2
    assert desglose["ACCEPT/ACCEPT"]["tp"] == 2  # c1 y c3 aciertan
    assert desglose["REVIEW/REVIEW"]["n"] == 1
    assert desglose["REVIEW/REVIEW"]["tp"] == 1


def test_acuerdo_contenido_detecta_error_compartido_como_falso_positivo():
    """Ambos carriles coinciden en polaridad, pero DISCREPAN del gold: el
    acuerdo de contenido no es infalible por construccion."""
    det = {"c1": _row("c1", covered=True, expected_negated=True, predicted_negated=False, predicted_decision="ACCEPT")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=True, predicted_negated=False, predicted_decision="ACCEPT")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo_contenido"]["n"] == 1
    assert out["acuerdo_contenido"]["cases"][0]["correct"] is False
    assert out["acuerdo_contenido"]["precision"] == 0.0


def test_polaridad_opuesta_entre_dos_predicciones_activas_es_discrepancia_dura():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=False, predicted_decision="ACCEPT")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_negated=True, predicted_decision="ACCEPT")}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo_contenido"]["n"] == 0
    assert out["discrepancia"]["polaridades_opuestas_activas"]["n"] == 1
    assert out["discrepancia"]["abstain_vs_afirma"]["n"] == 0
    assert out["discrepancia"]["polaridades_opuestas_activas"]["cases"][0]["reason"] == "polaridad_opuesta_activa"


def test_abstain_contra_afirma_activa_se_separa_de_la_discrepancia_dura():
    """Un carril abstiene (negated=False por convencion) y el otro predice
    negated=True: la polaridad difiere, pero NO es una discrepancia entre dos
    afirmaciones activas -- va a su propio conjunto."""
    det = {"c1": _row("c1", covered=True, expected_negated=True, predicted_negated=False, predicted_decision="ABSTAIN")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=True, predicted_negated=True, predicted_decision="ACCEPT")}
    out = ag.compute_agreement(det, nvidia)
    assert out["discrepancia"]["abstain_vs_afirma"]["n"] == 1
    assert out["discrepancia"]["polaridades_opuestas_activas"]["n"] == 0
    assert out["discrepancia"]["abstain_vs_afirma"]["cases"][0]["reason"] == "abstain_vs_afirma"


def test_ambos_abstienen_cuenta_como_acuerdo_de_contenido_pero_queda_marcado():
    """Dos ABSTAIN coinciden en negated=False por convencion (ninguno afirmo
    nada): entra en acuerdo_contenido (mismo claim, misma polaridad por
    default), pero `ambos_abstienen=True` lo distingue de un acuerdo con
    asercion activa."""
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ABSTAIN", predicted_predicate=None)}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ABSTAIN", predicted_predicate=None)}
    out = ag.compute_agreement(det, nvidia)
    assert out["acuerdo_contenido"]["n"] == 1
    assert out["acuerdo_contenido"]["cases"][0]["ambos_abstienen"] is True
    assert out["acuerdo_contenido"]["cases"][0]["decision_pair"] == "ABSTAIN/ABSTAIN"
    assert out["acuerdo_con_accept"]["n"] == 0


def test_predicado_distinto_es_discrepancia_predicado_incompatible():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate="p:leads")}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate="p:betrays")}
    out = ag.compute_agreement(det, nvidia)
    assert out["discrepancia"]["predicado_incompatible"]["n"] == 1
    assert out["acuerdo_contenido"]["n"] == 0


def test_predicado_ausente_en_un_carril_se_declara_compatible_por_omision():
    det = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate=None)}
    nvidia = {"c1": _row("c1", covered=True, expected_negated=False, predicted_decision="ACCEPT", predicted_predicate="p:leads")}
    out = ag.compute_agreement(det, nvidia)
    assert out["discrepancia"]["predicado_incompatible"]["n"] == 0
    assert out["acuerdo_contenido"]["n"] == 1


def test_solo_un_carril_cubierto_va_a_solo_det_o_solo_nvidia_con_nota_abstain():
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
    assert out["solo_det"]["cases"][0]["is_abstain"] is False
    assert "nota_abstain" in out["solo_det"]
    assert out["solo_nvidia"]["n"] == 1
    assert out["solo_nvidia"]["cases"][0]["claim_id"] == "c2"
    assert "nota_abstain" in out["solo_nvidia"]
    assert out["acuerdo_contenido"]["n"] == 0


def test_ningun_carril_cubierto_va_a_sin_cubrir_y_no_cuenta_en_ningun_otro_conjunto():
    det = {"c1": _row("c1", covered=False, expected_negated=False)}
    nvidia = {"c1": _row("c1", covered=False, expected_negated=False)}
    out = ag.compute_agreement(det, nvidia)
    assert out["sin_cubrir"]["n"] == 1
    assert out["sin_cubrir"]["claim_ids"] == ["c1"]
    for key in ("acuerdo_contenido", "acuerdo_con_accept", "solo_det", "solo_nvidia"):
        assert out[key]["n"] == 0
    assert out["discrepancia"]["polaridades_opuestas_activas"]["n"] == 0
    assert out["discrepancia"]["abstain_vs_afirma"]["n"] == 0
    assert out["discrepancia"]["predicado_incompatible"]["n"] == 0


def test_recall_del_acuerdo_contenido_es_sobre_TODO_el_evaluable_no_solo_lo_cubierto():
    """5 claims evaluables, solo 1 en acuerdo: el recall se lee sobre 5, no
    sobre el subconjunto cubierto -- si no, un acuerdo raro sobre pocos casos
    parecería más representativo de lo que es."""
    det = {f"c{i}": _row(f"c{i}", covered=(i == 1), expected_negated=False, predicted_decision="ACCEPT") for i in range(5)}
    nvidia = {f"c{i}": _row(f"c{i}", covered=(i == 1), expected_negated=False, predicted_decision="ACCEPT") for i in range(5)}
    out = ag.compute_agreement(det, nvidia)
    assert out["evaluable_total"] == 5
    assert out["acuerdo_contenido"]["n"] == 1
    assert out["acuerdo_contenido"]["recall_sobre_gold"] == 0.2


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
    cache_dir = tmp_path / "cache"
    snippet = (
        "import sys, runpy\n"
        "sys.argv = ['measure_agreement.py', '--mock', "
        f"'--out-dir', {str(out_dir)!r}, '--out-name', 'r', "
        f"'--cache', {str(cache_dir)!r}]\n"
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
    cache_dir = tmp_path / "cache"
    result = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "measure_agreement.py"), "--mock",
            "--out-dir", str(out_dir), "--out-name", "r", "--cache", str(cache_dir),
        ],
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

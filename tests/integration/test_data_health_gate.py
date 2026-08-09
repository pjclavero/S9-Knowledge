"""Controles POSITIVOS del comprobador de salud de datos (carril J).

Un gate que nunca ha visto rojo no es un gate. Aquí se demuestra, para cada
corrupción conocida, el ciclo completo: sano → OK, corrompido → CRITICAL,
restaurado → OK. Y se demuestra además que UNKNOWN no puntúa como OK y que un
fallo interno no puede salir con código 0.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.data_health import checks_dataset  # noqa: E402
from scripts.data_health.cli import main  # noqa: E402
from scripts.data_health.dataset import Dataset, load_json  # noqa: E402
from scripts.data_health.report import (  # noqa: E402
    CRITICAL,
    EXIT_CRITICAL,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
    EXIT_UNKNOWN,
    UNKNOWN,
    Finding,
    Report,
)

FIXTURE_SANO = REPO_ROOT / "tests/fixtures/data_health/healthy_graph.json"


def _informe(ds: Dataset) -> Report:
    rep = Report()
    f, ejecutadas = checks_dataset.ejecutar(ds)
    rep.extend(f)
    rep.checks_run.extend(ejecutadas)
    return rep


@pytest.fixture
def sano() -> Dataset:
    return load_json(FIXTURE_SANO)


def test_dataset_sano_sale_ok(sano: Dataset) -> None:
    rep = _informe(sano)
    assert rep.verdict() == "OK", rep.to_text()
    assert rep.exit_code() == EXIT_OK


def _corrompido(ds: Dataset, mutar) -> Dataset:
    copia = Dataset(origen=ds.origen,
                    nodes=copy.deepcopy(ds.nodes),
                    edges=copy.deepcopy(ds.edges))
    mutar(copia)
    return copia


def test_control_positivo_entity_id_duplicado(sano: Dataset) -> None:
    def mutar(ds: Dataset) -> None:
        ds.nodes.append(copy.deepcopy(ds.nodes[1]))  # mismo entity_id dos veces

    rep = _informe(_corrompido(sano, mutar))
    assert rep.exit_code() == EXIT_CRITICAL
    assert any(f.check == "D03" and f.level == CRITICAL for f in rep.findings), rep.to_text()
    # restaurar
    assert _informe(sano).verdict() == "OK"


def test_control_positivo_relacion_con_extremo_inexistente(sano: Dataset) -> None:
    def mutar(ds: Dataset) -> None:
        ds.edges[0]["to"] = "ent_que_no_existe"

    rep = _informe(_corrompido(sano, mutar))
    assert rep.exit_code() == EXIT_CRITICAL
    assert any(f.check == "D04" and f.level == CRITICAL for f in rep.findings), rep.to_text()
    assert _informe(sano).verdict() == "OK"


def test_control_positivo_campo_obligatorio_ausente(sano: Dataset) -> None:
    def mutar(ds: Dataset) -> None:
        del ds.nodes[2]["canonical_name"]

    rep = _informe(_corrompido(sano, mutar))
    assert rep.exit_code() == EXIT_CRITICAL
    assert any(f.check == "D01" and f.level == CRITICAL for f in rep.findings), rep.to_text()
    assert _informe(sano).verdict() == "OK"


def test_contradiccion_de_ambito_es_critica(sano: Dataset) -> None:
    def mutar(ds: Dataset) -> None:
        ds.nodes[1]["workspace"] = "otro_taller"

    rep = _informe(_corrompido(sano, mutar))
    assert any(f.check == "D06" and f.level == CRITICAL for f in rep.findings), rep.to_text()


def test_unknown_nunca_es_ok() -> None:
    rep = Report()
    rep.add(Finding("D99", UNKNOWN, "no se pudo comprobar"))
    assert rep.ok is False
    assert rep.verdict() == UNKNOWN
    assert rep.exit_code() == EXIT_UNKNOWN != EXIT_OK


def test_una_comprobacion_que_revienta_produce_unknown_no_silencio(monkeypatch, sano) -> None:
    def explota(_ds):
        raise RuntimeError("boom")

    monkeypatch.setattr(checks_dataset, "TODAS", (("D03", explota),))
    rep = _informe(sano)
    assert rep.exit_code() != EXIT_OK
    assert any(f.level == UNKNOWN and "boom" in f.message for f in rep.findings)


def test_cli_sobre_fixture_sano_sale_cero(capsys) -> None:
    assert main(["--modo", "datos", "--fixture", str(FIXTURE_SANO)]) == EXIT_OK


def test_cli_con_fixture_ilegible_no_sale_cero(tmp_path, capsys) -> None:
    malo = tmp_path / "roto.json"
    malo.write_text("{ esto no es json", encoding="utf-8")
    assert main(["--modo", "datos", "--fixture", str(malo)]) == EXIT_INTERNAL_ERROR


def test_cli_con_fixture_corrompido_sale_rojo(tmp_path) -> None:
    datos = json.loads(FIXTURE_SANO.read_text(encoding="utf-8"))
    datos["nodes"].append(copy.deepcopy(datos["nodes"][1]))
    destino = tmp_path / "corrupto.json"
    destino.write_text(json.dumps(datos), encoding="utf-8")
    assert main(["--modo", "datos", "--fixture", str(destino)]) == EXIT_CRITICAL


def test_el_comprobador_no_escribe_en_neo4j() -> None:
    """Ninguna consulta del cargador puede escribir. Se verifica textualmente."""
    fuente = (REPO_ROOT / "scripts/data_health/dataset.py").read_text(encoding="utf-8")
    for prohibido in ("CREATE ", "MERGE ", "SET ", "DELETE ", "REMOVE ", "DROP "):
        assert prohibido not in fuente, f"el cargador contiene '{prohibido}'"

"""test_contract_examples.py — valida los ejemplos y las fixtures del EQUIPO D.

Consume el contrato compartido (`contracts/review-ingest/v1/`) SIN modificarlo:
  - Todos los ejemplos VÁLIDOS del contrato pasan `validate_document`.
  - Todos los ejemplos INVÁLIDOS son rechazados con `ContractError`.
  - Las fixtures anonimizadas del EQUIPO D (tests/fixtures/review_ingest_v1/)
    también validan contra el contrato.

Duplica intencionadamente parte de la cobertura del gate de contratos como red
de seguridad E2E: si el motor o el visor cambian un ejemplo, esta suite lo ve.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from support import contracts

pytestmark = [pytest.mark.integration, pytest.mark.contract]

VALID_EXAMPLES = sorted(contracts.VALID_DIR.glob("*.json"))
INVALID_EXAMPLES = sorted(contracts.INVALID_DIR.glob("*.json"))
FIXTURES_DIR = contracts.REPO_ROOT / "tests" / "fixtures" / "review_ingest_v1"
FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))


def test_examples_present() -> None:
    assert len(VALID_EXAMPLES) >= 10
    assert len(INVALID_EXAMPLES) >= 12


def test_fixtures_present() -> None:
    # Un documento de cada uno de los 6 tipos + un segundo de decision.
    assert len(FIXTURES) == 7


@pytest.mark.parametrize("path", VALID_EXAMPLES, ids=lambda p: p.stem)
def test_valid_contract_example(path: Path) -> None:
    contracts.validator.validate_document(contracts.load_json(path))


@pytest.mark.parametrize("path", INVALID_EXAMPLES, ids=lambda p: p.stem)
def test_invalid_contract_example(path: Path) -> None:
    with pytest.raises(contracts.ContractError):
        contracts.validator.validate_document(contracts.load_json(path))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_anonymized_fixture_valid(path: Path) -> None:
    contracts.validator.validate_document(contracts.load_json(path))


def test_fixtures_are_anonymized(path=None) -> None:
    """Las fixtures del EQUIPO D no contienen hosts/IP de producción ni PII obvia."""
    forbidden_markers = [
        "knowledge.seccionnueve.duckdns.org",
        "192.168.1.205",
        "100.103.100.105",
    ]
    for f in FIXTURES:
        text = f.read_text(encoding="utf-8")
        for marker in forbidden_markers:
            assert marker not in text, f"{f.name} contiene un marcador de producción: {marker}"

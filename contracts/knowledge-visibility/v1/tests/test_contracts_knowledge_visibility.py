# -*- coding: utf-8 -*-
"""Tests del contrato `knowledge-visibility/v1` (M5b-0): forma, fixtures
congeladas y validacion fail-closed. NO prueba el motor del visor (eso vive en
`viewer/tests/test_visibility_contract_adapter.py`); esto es solo el
contrato: JSON Schema + modelo Python ligero.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CONTRACT_DIR = HERE.parent
EXAMPLES = CONTRACT_DIR / "examples"

sys.path.insert(0, str(CONTRACT_DIR))
sys.path.insert(0, str(HERE))

import kv_fixtures as fixtures  # noqa: E402
from model import (  # noqa: E402
    ContractVisibilityError,
    KnowledgeVisibilityV1,
    VisibilityLevel,
    is_valid,
    validate_against_schema,
)

import generate_examples as gen  # noqa: E402


# --- Fixtures congeladas: disco == lo que produce el generador --------------


def test_ejemplos_en_disco_coinciden_con_los_generados() -> None:
    expected = gen.expected_files()
    assert expected, "no hay fixtures que comprobar"
    for path, content in expected.items():
        assert path.exists(), f"falta regenerar: {path} (ejecuta generate_examples.py)"
        assert path.read_text(encoding="utf-8") == content, (
            f"{path} desincronizado respecto a kv_fixtures.py"
        )


def test_no_hay_ficheros_huerfanos_en_examples() -> None:
    expected_paths = set(gen.expected_files())
    on_disk = set((EXAMPLES / "valid").glob("*.json")) | set((EXAMPLES / "invalid").glob("*.json"))
    assert on_disk == expected_paths


# --- Ejemplos validos: pasan schema Y modelo ---------------------------------


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS))
def test_ejemplo_valido_pasa_schema_y_modelo(name: str) -> None:
    doc = fixtures.VALID_BUILDERS[name]()
    validate_against_schema(doc)  # no debe lanzar
    parsed = KnowledgeVisibilityV1.from_dict(doc)
    assert parsed.to_dict() == doc
    assert is_valid(doc)


# --- Ejemplos invalidos: fallan schema Y modelo, cero permisividad ----------


@pytest.mark.parametrize("name", sorted(fixtures.INVALID_BUILDERS))
def test_ejemplo_invalido_falla_schema_y_modelo(name: str) -> None:
    doc = fixtures.INVALID_BUILDERS[name]()
    assert not is_valid(doc), f"{name} deberia ser invalido"
    with pytest.raises(Exception):
        validate_against_schema(doc)
    with pytest.raises(ContractVisibilityError):
        KnowledgeVisibilityV1.from_dict(doc)


# --- Enum cerrado y fail-closed, probado directamente sobre el modelo -------


def test_enum_visibility_es_exactamente_cinco_valores_cerrados() -> None:
    assert {v.value for v in VisibilityLevel} == {
        "player",
        "narrator",
        "secret",
        "reference",
        "deny",
    }


def test_deny_es_un_valor_valido_del_enum() -> None:
    doc = fixtures.build_deny()
    parsed = KnowledgeVisibilityV1.from_dict(doc)
    assert parsed.visibility is VisibilityLevel.DENY


def test_construir_con_visibility_string_crudo_falla() -> None:
    with pytest.raises(ContractVisibilityError):
        KnowledgeVisibilityV1(visibility="player")  # type: ignore[arg-type]


def test_known_by_lista_vacia_es_valida_pero_explicita() -> None:
    doc = fixtures.build_player_sin_known_by()
    assert doc["known_by"] == []
    parsed = KnowledgeVisibilityV1.from_dict(doc)
    assert parsed.known_by == ()


def test_from_dict_rechaza_documento_no_dict() -> None:
    with pytest.raises(ContractVisibilityError):
        KnowledgeVisibilityV1.from_dict([])  # type: ignore[arg-type]


def test_from_dict_rechaza_contract_id_incorrecto() -> None:
    doc = fixtures.build_player_sin_known_by()
    doc["contract_id"] = "otro-contrato/v1"
    with pytest.raises(ContractVisibilityError):
        KnowledgeVisibilityV1.from_dict(doc)

# -*- coding: utf-8 -*-
"""kv_fixtures.py — fixtures CONGELADAS de `knowledge-visibility/v1` (M5b-0).

Mismo patron que `contracts/knowledge-v3/v1/tests/v3_fixtures.py`: los
ejemplos en disco (`examples/valid`, `examples/invalid`) se generan desde
aqui, nunca se editan a mano. `test_contracts_knowledge_visibility.py`
comprueba que disco == lo que producen estos builders, byte a byte.

Cada ejemplo invalido es UNA mutacion documentada sobre un ejemplo valido: si
la regla se relaja, el ejemplo empieza a validar y el gate se pone rojo.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- Ejemplos VALIDOS -------------------------------------------------------


def build_player_sin_known_by() -> dict[str, Any]:
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "player",
        "known_by": [],
    }


def build_secret_con_known_by() -> dict[str, Any]:
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "secret",
        "known_by": ["personaje.kakita_asuka", "personaje.kimi"],
    }


def build_narrator() -> dict[str, Any]:
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "narrator",
        "known_by": [],
    }


def build_reference() -> dict[str, Any]:
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "reference",
        "known_by": [],
    }


def build_deny() -> dict[str, Any]:
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "deny",
        "known_by": [],
        "metadata": {"motivo": "dato retirado, pendiente de revision"},
    }


def build_enlazado_a_v3() -> dict[str, Any]:
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "secret",
        "known_by": ["personaje.bayushi_hisao"],
        "claim_id": "claim.oni_combate_001",
        "assertion_id": "assertion.oni_combate_001",
        "plan_id": "plan.oni_combate_001",
        "state_hash": "sha256:" + "a" * 64,
    }


VALID_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "player_sin_known_by": build_player_sin_known_by,
    "secret_con_known_by": build_secret_con_known_by,
    "narrator": build_narrator,
    "reference": build_reference,
    "deny": build_deny,
    "enlazado_a_v3": build_enlazado_a_v3,
}


# --- Ejemplos INVALIDOS: una mutacion documentada por caso ------------------


def build_falta_visibility() -> dict[str, Any]:
    doc = build_player_sin_known_by()
    del doc["visibility"]
    return doc


def build_visibility_desconocido() -> dict[str, Any]:
    doc = build_player_sin_known_by()
    doc["visibility"] = "publico"  # fuera del enum cerrado
    return doc


def build_falta_known_by() -> dict[str, Any]:
    doc = build_player_sin_known_by()
    del doc["known_by"]
    return doc


def build_known_by_con_espacio() -> dict[str, Any]:
    doc = build_secret_con_known_by()
    doc["known_by"] = ["personaje malo con espacio"]
    return doc


def build_known_by_duplicado() -> dict[str, Any]:
    doc = build_secret_con_known_by()
    doc["known_by"] = ["personaje.kakita_asuka", "personaje.kakita_asuka"]
    return doc


def build_campo_desconocido() -> dict[str, Any]:
    doc = build_player_sin_known_by()
    doc["visibility_scope"] = "SUBJECTS"  # vocabulario descartado (docs/v3/50)
    return doc


def build_contract_version_invalida() -> dict[str, Any]:
    doc = build_player_sin_known_by()
    doc["contract_version"] = "2.0.0"  # major desconocida, debe rechazarse
    return doc


def build_state_hash_mal_formado() -> dict[str, Any]:
    doc = build_enlazado_a_v3()
    doc["state_hash"] = "no-es-un-hash"
    return doc


INVALID_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "falta_visibility": build_falta_visibility,
    "visibility_desconocido": build_visibility_desconocido,
    "falta_known_by": build_falta_known_by,
    "known_by_con_espacio": build_known_by_con_espacio,
    "known_by_duplicado": build_known_by_duplicado,
    "campo_desconocido": build_campo_desconocido,
    "contract_version_invalida": build_contract_version_invalida,
    "state_hash_mal_formado": build_state_hash_mal_formado,
}

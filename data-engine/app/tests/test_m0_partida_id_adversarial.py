# -*- coding: utf-8 -*-
"""Bateria adversarial de M0 (docs/v3/49-multipartida-diseno.md, §8).

Verifica con EJECUCION (no re-lee la documentacion de M0 y la da por buena)
cinco cosas que el bloque declara pero que ningun test anterior comprobaba
sobre datasets REALES ya congelados, mas dos huecos de superficie del campo
nuevo:

1. Retrocompatibilidad real: documentos gold de heldout/negation/dev validan
   contra los schemas nuevos sin cambios, y su `plan_hash`/`decision_hash`
   literales (calculados y congelados ANTES de M0) siguen siendo exactamente
   los que M0 recalcula hoy.
2. Round-trip sin inyeccion: un documento gold sin `partida_id` se
   deserializa y vuelve a serializar sin que aparezca `"partida_id": null`.
3. El hueco de `decision_hash` (documentado como pendiente de M3) fijado con
   un xfail que se convertira en XPASS en cuanto alguien lo cierre sin darse
   cuenta de que hay que actualizar este test.
4. El patron de `partida_id` (schema + modelo Python) contra valores
   maliciosos/raros.
5. La incoherencia `scope.partida_id` != `partida_id` raiz: hoy no se valida
   (documentado como fuera de alcance de M0); este test fija ese estado para
   que M2/M3 no lo hereden sin saberlo.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import (  # noqa: E402
    ClaimProposal,
    GraphMutationPlan,
    SourceAsset,
    V3ContractError,
    compute_decision_hash,
    compute_plan_hash,
)
from knowledge_v3.contracts.base import schema_validator  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATASETS_DIR = (
    _REPO_ROOT
    / "data-engine"
    / "app"
    / "knowledge_v3"
    / "benchmarks"
    / "datasets"
)

_SPLITS = ("heldout", "negation", "dev", "agreement-eval2", "factivity")


def _all_documents(benchmark_file: str) -> list[dict]:
    """Todos los documentos de `<split>/sources/*/<benchmark_file>.json`."""
    out = []
    for split in _SPLITS:
        pattern = str(_DATASETS_DIR / split / "sources" / "*" / f"{benchmark_file}.json")
        for path in sorted(glob.glob(pattern)):
            data = json.loads(Path(path).read_text())
            for entry in data.get("documents", []):
                out.append((path, entry))
    return out


# ==========================================================================
# 1) Retrocompatibilidad real contra datasets congelados
# ==========================================================================
def test_real_source_assets_validate_and_have_no_partida_id():
    docs = _all_documents("source_asset")
    assert len(docs) >= 5, "no se encontraron source_asset.json reales para auditar"
    for path, entry in docs:
        assert "partida_id" not in entry, f"{path}: gold antiguo ya trae partida_id"
        schema_validator.validate_document(entry)  # no debe lanzar


def test_real_claims_validate_and_have_no_partida_id():
    docs = _all_documents("claims")
    assert len(docs) >= 5, "no se encontraron claims.json reales para auditar"
    for path, entry in docs:
        assert "partida_id" not in entry, f"{path}: gold antiguo ya trae partida_id"
        schema_validator.validate_document(entry)


def test_real_frozen_plans_validate_and_hashes_are_unchanged_by_m0():
    """(a)+(b): los planes gold sellados ANTES de M0 recalculan el MISMO
    `plan_hash`/`decision_hash` hoy, con el codigo de M0 ya integrado."""
    docs = _all_documents("plans")
    assert len(docs) >= 5, "no se encontraron plans.json reales para auditar"
    checked = 0
    for path, entry in docs:
        assert "partida_id" not in entry, f"{path}: gold antiguo ya trae partida_id"
        assert "scope" not in entry, f"{path}: gold antiguo ya trae scope"

        schema_validator.validate_document(entry)

        frozen_plan_hash = entry.get("plan_hash")
        frozen_decision_hash = entry.get("local_approval", {}).get("decision_hash")
        if frozen_plan_hash is None or frozen_decision_hash is None:
            continue  # plan no aprobado / sin sellar: no aplica

        recomputed_plan_hash = compute_plan_hash(entry)
        recomputed_decision_hash = compute_decision_hash(entry)
        assert recomputed_plan_hash == frozen_plan_hash, (
            f"{path}: plan_hash cambio con el codigo de M0 integrado"
        )
        assert recomputed_decision_hash == frozen_decision_hash, (
            f"{path}: decision_hash cambio con el codigo de M0 integrado"
        )
        checked += 1
    assert checked >= 3, "ningun plan sellado real se pudo verificar de punta a punta"


# ==========================================================================
# 2) Round-trip: OMIT_IF_NONE no inyecta partida_id:null en material viejo
# ==========================================================================
def test_real_source_asset_roundtrip_does_not_inject_partida_id():
    docs = _all_documents("source_asset")
    path, entry = docs[0]
    obj = SourceAsset.from_dict(entry)
    assert obj.partida_id is None
    out = obj.to_dict()
    assert "partida_id" not in out
    assert out == entry
    # y el JSON canonico tampoco lo trae, ni como null ni como clave vacia
    assert '"partida_id"' not in obj.to_json()


def test_real_plan_roundtrip_does_not_inject_partida_id_or_scope():
    docs = _all_documents("plans")
    for path, entry in docs:
        if entry.get("local_approval", {}).get("decision_hash") is None:
            continue
        plan = GraphMutationPlan.from_dict(entry)
        out = plan.to_dict()
        assert "partida_id" not in out and "scope" not in out
        assert out == entry
        return
    pytest.fail("ningun plan real sellado disponible para probar el roundtrip")


# ==========================================================================
# 3) El hueco del decision_hash: fijado, no solo documentado en prosa
# ==========================================================================
@pytest.mark.xfail(
    reason=(
        "AGUJERO CONOCIDO (docs/v3/49-multipartida-diseno.md, M0): "
        "DECISION_HASH_FIELDS no cubre partida_id/scope a proposito, para no "
        "romper decision_hash ya congelados en datasets gold/held-out. Cuando "
        "M3 cierre esto (con regeneracion deliberada de datasets), este test "
        "debe pasar a XPASS y entonces se borra el xfail: es la senal de que "
        "el hueco se cerro sin que nadie lo olvidase."
    ),
    strict=True,
)
def test_m3_pendiente_decision_hash_deberia_distinguir_partida_id():
    from knowledge_v3.contracts import seal_plan

    fixtures_path = _REPO_ROOT / "contracts" / "knowledge-v3" / "v1" / "tests" / "v3_fixtures.py"
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("s9k_v3_fixtures_local", fixtures_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s9k_v3_fixtures_local"] = mod
    spec.loader.exec_module(mod)

    base = mod.VALID_BUILDERS["graph_mutation_plan_approved"]()
    base.pop("plan_hash", None)
    base["local_approval"].pop("decision_hash", None)

    plan_a = seal_plan({**base, "partida_id": "partida:brumal-01"})
    plan_b = seal_plan({**base, "partida_id": "partida:brumal-02"})

    assert (
        plan_a["local_approval"]["decision_hash"]
        != plan_b["local_approval"]["decision_hash"]
    ), "dos planes con distinto ambito de partida deberian decidir distinto"


# ==========================================================================
# 4) El patron de partida_id: valores maliciosos/raros
# ==========================================================================
def _asset_with_partida_id(partida_id):
    import importlib.util
    import sys

    fixtures_path = _REPO_ROOT / "contracts" / "knowledge-v3" / "v1" / "tests" / "v3_fixtures.py"
    spec = importlib.util.spec_from_file_location("s9k_v3_fixtures_local2", fixtures_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s9k_v3_fixtures_local2"] = mod
    spec.loader.exec_module(mod)
    data = mod.VALID_BUILDERS["source_asset_pdf"]()
    data["partida_id"] = partida_id
    return data


@pytest.mark.parametrize(
    "bad_value",
    [
        "",  # cadena vacia: minLength 1
        " ",  # solo espacio
        "partida uno",  # espacio interno
        " partida:brumal",  # espacio inicial
        "partida:brumal ",  # espacio final
        "café:brumal",  # unicode fuera del charset ascii permitido
        "-partida",  # no puede empezar por separador
        ":partida",  # no puede empezar por ':'
        "a" * 201,  # supera maxLength 200
    ],
)
def test_schema_rejects_malformed_partida_id(bad_value):
    data = _asset_with_partida_id(bad_value)
    with pytest.raises(V3ContractError):
        schema_validator.validate_document(data)


@pytest.mark.parametrize(
    "value",
    [
        "juego:x",  # colision semantica deliberada con la capa "juego" -- el
        # schema NO conoce esa semantica, solo el patron generico de stable_id
        "partida:brumal-01",
        "a",
        "A0",
        "x" * 200,  # limite exacto, debe admitirse
    ],
)
def test_schema_accepts_pattern_valid_partida_id_including_semantic_traps(value):
    data = _asset_with_partida_id(value)
    schema_validator.validate_document(data)  # no debe lanzar


def test_schema_rejects_null_vs_accepts_absence_are_both_fine_but_distinct():
    """`null` explicito y ausencia total son ambos validos a nivel de schema
    (partida_id_or_null), pero solo la ausencia sobrevive el roundtrip del
    modelo Python porque `to_dict()` omite `None`."""
    present_null = _asset_with_partida_id(None)
    schema_validator.validate_document(present_null)  # valido: anyOf null

    obj = SourceAsset.from_dict(present_null)
    assert obj.partida_id is None
    assert "partida_id" not in obj.to_dict()


def test_python_model_construction_bypasses_pattern_validation_without_explicit_validate():
    """GAP DE SUPERFICIE: construir el dataclass directamente (sin pasar por
    `from_dict`/`.validate()`) NO aplica el patron de `partida_id`. Es
    coherente con el resto del dataclass (ninguna validacion en
    `__post_init__`), pero significa que cualquier codigo que construya
    `SourceAsset(...)` a mano y llame a `.to_dict()`/`.to_json()` sin invocar
    `.validate()` puede serializar un `partida_id` que el schema rechazaria.
    """
    data = _asset_with_partida_id("valida:ok")
    obj = SourceAsset.from_dict(data, validate=False)
    obj.partida_id = "  con espacios y ó unicode ñ"  # nunca pasaria el patron
    # No lanza: no hay validacion en la asignacion ni en to_dict/to_json.
    serialized = obj.to_dict()
    assert serialized["partida_id"] == "  con espacios y ó unicode ñ"
    # Y solo salta si alguien llama explicitamente a validate()/is_valid().
    with pytest.raises(V3ContractError):
        obj.validate()
    assert obj.is_valid() is False


# ==========================================================================
# 5) scope vs partida_id raiz: incoherencia interna
# ==========================================================================
def test_scope_partida_id_can_disagree_with_root_partida_id_undetected():
    """GAP DE SUPERFICIE (documentado como fuera de M0, dosier §2.2: "la
    validacion de coherencia layer/partida_id en admision es de M3, no de
    este contrato"): hoy el schema y el modelo Python aceptan un plan cuyo
    `scope.partida_id` no coincide con su `partida_id` raiz. Este test fija
    ese estado para que quede escrito en codigo, no solo en un comentario que
    alguien puede dejar de leer.
    """
    import importlib.util
    import sys

    fixtures_path = _REPO_ROOT / "contracts" / "knowledge-v3" / "v1" / "tests" / "v3_fixtures.py"
    spec = importlib.util.spec_from_file_location("s9k_v3_fixtures_local3", fixtures_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s9k_v3_fixtures_local3"] = mod
    spec.loader.exec_module(mod)

    from knowledge_v3.contracts import seal_plan

    base = mod.VALID_BUILDERS["graph_mutation_plan_approved"]()
    base["partida_id"] = "partida:brumal-01"
    base["scope"] = {
        "layer": "PARTIDA",
        "game_id": base["workspace"],
        "partida_id": "partida:brumal-DISTINTA",  # incoherente a proposito
    }
    base.pop("plan_hash", None)
    base["local_approval"].pop("decision_hash", None)
    sealed = seal_plan(base)

    # Ni el schema ni el modelo Python lo rechazan: es el agujero documentado.
    schema_validator.validate_document(sealed)
    plan = GraphMutationPlan.from_dict(sealed)
    assert plan.partida_id == "partida:brumal-01"
    assert plan.scope["partida_id"] == "partida:brumal-DISTINTA"

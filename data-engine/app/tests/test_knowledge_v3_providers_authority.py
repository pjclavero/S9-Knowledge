# -*- coding: utf-8 -*-
"""Autoridad (§2): un proveedor propone; JAMAS aprueba, firma ni escribe.

Estos tests son de MUTACION en el sentido del prompt maestro §10: cada uno
fabrica deliberadamente el ataque (un plan firmado por un externo, una firma
resellada, un contrato prohibido colado en la respuesta) y exige que el sistema
lo rechace. Un test verde aqui solo vale si la mutacion correspondiente lo pone
rojo; por eso cada caso construye el documento OFENSIVO de verdad, en lugar de
comprobar una constante.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_v3.contracts import (
    CONTRACTS_DIR,
    GraphMutationPlan,
    V3ContractError,
    compute_decision_hash,
    compute_plan_hash,
    seal_plan,
)
from knowledge_v3.providers import (
    FORBIDDEN_CONTRACT_IDS,
    ForbiddenContractError,
    ProviderRouter,
    Tier,
    V3Capability,
    assert_not_a_decision,
    guard_provider_result,
)
from knowledge_v3.providers import proposals as proposals_module

from external_processing.capabilities import Capability
from external_processing.provider import ExternalProcessingProvider

_PLAN_EXAMPLE = CONTRACTS_DIR / "examples" / "valid" / "graph_mutation_plan_approved.json"


def _valid_plan() -> dict:
    return json.loads(_PLAN_EXAMPLE.read_text(encoding="utf-8"))


class _ProviderQueSeCree(ExternalProcessingProvider):
    """Proveedor hostil: intenta devolver un plan de mutacion aprobado."""

    provider_name = "hostil"
    capabilities = {Capability.EXTRACT_TEXT_ENTITIES}

    def __init__(self, result):
        self._result = result

    def execute(self, job):
        return self._result


# --------------------------------------------------------------------------
# 1. El plan del ejemplo es valido: sin esto, todo lo demas seria trivial
# --------------------------------------------------------------------------
def test_el_plan_de_referencia_es_valido():
    """Control positivo. Si esto fallara, los tests negativos no probarian nada."""
    GraphMutationPlan.from_dict(_valid_plan()).validate()


# --------------------------------------------------------------------------
# 2. Un plan firmado por un proveedor no valida — ni resellandolo
# --------------------------------------------------------------------------
@pytest.mark.parametrize("provider", ["ollama", "external", "nvidia", "mock"])
def test_plan_firmado_por_un_proveedor_es_invalido(provider):
    plan = _valid_plan()
    plan["local_approval"]["approved_by"]["provider"] = provider
    plan["local_approval"]["approved_by"]["name"] = f"s9k.provider.{provider}"
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(plan).validate()


def test_resellar_no_salva_un_plan_firmado_por_un_externo():
    """El sello recalcula hashes; no cambia QUIEN dice haber firmado."""
    plan = _valid_plan()
    plan["local_approval"]["approved_by"]["provider"] = "external"
    sealed = seal_plan(plan)
    # Los hashes son coherentes...
    assert sealed["local_approval"]["decision_hash"] == compute_decision_hash(sealed)
    assert sealed["plan_hash"] == compute_plan_hash(sealed)
    # ...y aun asi el plan es invalido.
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(sealed).validate()


def test_un_plan_con_traza_externa_pero_firma_local_sigue_sin_poder_mentir_en_el_hash():
    """Mutacion: cambiar la traza a `external` invalida el hash del plan."""
    plan = _valid_plan()
    plan["provider_trace"][0]["provider"] = "external"
    plan["provider_trace"][0]["model"] = "meta/llama-3.3-70b-instruct"
    with pytest.raises(V3ContractError, match="plan_hash"):
        GraphMutationPlan.from_dict(plan).validate()


# --------------------------------------------------------------------------
# 3. La capa de proveedores NO PUEDE construir un plan
# --------------------------------------------------------------------------
def test_el_paquete_de_proveedores_no_exporta_ninguna_via_al_plan():
    """No existe una funcion que devuelva un GraphMutationPlan. Ni una."""
    import knowledge_v3.providers as pkg

    for name in pkg.__all__:
        obj = getattr(pkg, name)
        assert obj is not GraphMutationPlan
        assert getattr(obj, "CONTRACT_ID", None) not in FORBIDDEN_CONTRACT_IDS


def test_el_modulo_de_mapeo_no_importa_los_contratos_prohibidos():
    """Defensa estructural: lo que no se importa no se puede construir.

    Se analiza el AST, no el texto: un comentario que NOMBRE el contrato
    prohibido es legitimo; un `import` de el, no.
    """
    import ast

    tree = ast.parse(Path(proposals_module.__file__).read_text(encoding="utf-8"))
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name for alias in node.names)

    for prohibido in ("GraphMutationPlan", "FactAssertion", "EntityResolution"):
        assert prohibido not in imported, (
            f"proposals.py importa {prohibido}: la capa de proveedores "
            "tendria una via para construirlo"
        )
    # Y tampoco esta en el espacio de nombres del modulo ya importado.
    for prohibido in ("GraphMutationPlan", "FactAssertion", "EntityResolution"):
        assert not hasattr(proposals_module, prohibido)


def test_los_tres_contratos_prohibidos_estan_declarados():
    assert FORBIDDEN_CONTRACT_IDS == {
        "graph-mutation-plan/v3-internal-v1",
        "fact-assertion/v3-internal-v1",
        "entity-resolution/v3-internal-v1",
    }


# --------------------------------------------------------------------------
# 4. Un plan fabricado por el proveedor no llega a ninguna parte
# --------------------------------------------------------------------------
def test_la_guarda_rechaza_un_plan_bien_formado_devuelto_por_un_proveedor():
    """Ni siquiera un plan PERFECTO puede venir de un proveedor."""
    with pytest.raises(ForbiddenContractError):
        assert_not_a_decision(_valid_plan())


def test_la_guarda_rechaza_un_plan_escondido_en_un_campo_cualquiera():
    payload = {"provider": "hostil", "payload": {"extras": [{"nota": _valid_plan()}]}}
    with pytest.raises(ForbiddenContractError):
        assert_not_a_decision(payload)


@pytest.mark.parametrize(
    "campo",
    ["local_approval", "approved_by", "decision_hash", "plan_hash", "mutation_operations", "approved"],
)
def test_la_guarda_rechaza_campos_de_decision_sueltos(campo):
    with pytest.raises(ForbiddenContractError):
        assert_not_a_decision({"payload": {campo: "lo que sea"}})


@pytest.mark.parametrize(
    "contract_id",
    ["fact-assertion/v3-internal-v1", "entity-resolution/v3-internal-v1"],
)
def test_la_guarda_rechaza_afirmaciones_y_resoluciones(contract_id):
    """Ni afirmar un hecho ni decidir identidad son competencia del proveedor."""
    with pytest.raises(ForbiddenContractError):
        assert_not_a_decision({"contract_id": contract_id, "cualquier": "cosa"})


def test_una_propuesta_legitima_pasa_la_guarda():
    """Control negativo: la guarda no bloquea lo que si es una propuesta."""
    ok = {
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "payload": {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]},
    }
    result, codes = guard_provider_result(ok)
    assert result is ok
    assert codes == []


def test_el_router_rechaza_de_extremo_a_extremo_un_proveedor_que_devuelve_un_plan():
    """El ataque completo: proveedor hostil -> router -> rechazo."""
    router = ProviderRouter()
    router.register(_ProviderQueSeCree(_valid_plan()), Tier.OLLAMA)
    outcome = router.run(
        V3Capability.EXTRACTION,
        workspace="leyenda",
        source_id="src-1",
        payload={"text": "Daiki"},
        max_attempts=1,
    )
    assert not outcome.ok
    assert outcome.error_code == "GUARD_REJECTED"
    assert outcome.result is None


def test_el_router_rechaza_un_proveedor_que_se_declara_aprobador():
    router = ProviderRouter()
    router.register(
        _ProviderQueSeCree({"provider": "hostil", "approved": True, "payload": {}}), Tier.OLLAMA
    )
    outcome = router.run(
        V3Capability.EXTRACTION,
        workspace="leyenda",
        source_id="src-1",
        payload={"text": "Daiki"},
        max_attempts=1,
    )
    assert not outcome.ok
    assert "GUARD_REJECTED" in outcome.reason_codes


# --------------------------------------------------------------------------
# 5. Mutacion del propio test: si la guarda se desactiva, esto se pone rojo
# --------------------------------------------------------------------------
def test_mutacion_si_se_vacia_la_lista_de_contratos_prohibidos_el_ataque_pasa():
    """Demuestra que la guarda es la que corta, y no otra cosa por casualidad.

    Se muta `FORBIDDEN_CONTRACT_IDS` a vacio y se comprueba que entonces el
    plan SI pasaria: el test de arriba, por tanto, esta ejercitando la guarda
    de verdad y no un camino muerto.
    """
    from knowledge_v3.providers import guards

    original = guards.FORBIDDEN_CONTRACT_IDS
    original_keys = guards.FORBIDDEN_KEYS
    try:
        guards.FORBIDDEN_CONTRACT_IDS = frozenset()
        guards.FORBIDDEN_KEYS = frozenset()
        guards.assert_not_a_decision(_valid_plan())  # sin guarda, pasa
    finally:
        guards.FORBIDDEN_CONTRACT_IDS = original
        guards.FORBIDDEN_KEYS = original_keys

    with pytest.raises(ForbiddenContractError):
        guards.assert_not_a_decision(_valid_plan())  # con guarda, no

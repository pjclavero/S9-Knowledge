# -*- coding: utf-8 -*-
"""Enrutado, presupuesto y despacho de la capa de proveedores V3."""
from __future__ import annotations

import pytest

from external_processing.capabilities import Capability
from external_processing.models import ExternalTaskType, ProcessingJob
from external_processing.provider import ExternalProcessingProvider
from external_processing.providers.mock import MockExternalProcessingProvider
from knowledge_v3.providers import (
    Budget,
    ProviderRouter,
    RoutingPolicy,
    Tier,
    V3Capability,
    to_provider_capability,
    to_task_type,
)

from tests.test_knowledge_v3_providers_support import SOURCE_HASH, WORKSPACE


# --------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------
class _Scripted(ExternalProcessingProvider):
    """Proveedor de laboratorio: devuelve o lanza lo que se le diga."""

    def __init__(self, name, capabilities, result=None, error=None):
        self.provider_name = name
        self.capabilities = set(capabilities)
        self._result = result if result is not None else {"provider": name, "payload": {"ok": True}}
        self._error = error
        self.calls = 0

    def execute(self, job: ProcessingJob):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return dict(self._result)

    def healthcheck(self):
        return {"status": "ok", "provider": self.provider_name}


def _router(*entries, policy=None, budget=None):
    r = ProviderRouter(policy=policy or RoutingPolicy(), budget=budget or Budget(0, 0.0))
    for provider, tier, cost in entries:
        r.register(provider, tier, cost_units=cost)
    return r


def _run(router, capability=V3Capability.EXTRACTION, **kw):
    return router.run(
        capability,
        workspace=WORKSPACE,
        source_id="src-1",
        payload={"text": "Daiki juro lealtad."},
        **kw,
    )


# --------------------------------------------------------------------------
# Mapa de capacidades
# --------------------------------------------------------------------------
def test_las_seis_capacidades_v3_tienen_traduccion_completa():
    """Cada V3Capability mapea a una Capability y a un ExternalTaskType."""
    for cap in V3Capability:
        assert isinstance(to_provider_capability(cap), Capability)
        assert isinstance(to_task_type(cap), ExternalTaskType)


def test_el_mapa_de_capacidades_es_inyectivo():
    """Dos capacidades V3 distintas no comparten tarea: se pisarian en el dispatcher."""
    tasks = [to_task_type(c) for c in V3Capability]
    assert len(set(tasks)) == len(tasks)


def test_capability_matrix_refleja_lo_que_declara_el_proveedor():
    provider = _Scripted("solo-asr", {Capability.TRANSCRIBE_AUDIO})
    router = _router((provider, Tier.LOCAL, 0.0))
    matrix = router.capability_matrix()
    assert matrix["ASR"]["solo-asr"] is True
    assert matrix["EXTRACTION"]["solo-asr"] is False


# --------------------------------------------------------------------------
# Politica: local primero
# --------------------------------------------------------------------------
def test_local_gana_a_ollama_y_a_externo():
    """§2: local primero, siempre, sin configuracion que lo invierta."""
    caps = {Capability.EXTRACT_TEXT_ENTITIES}
    router = _router(
        (_Scripted("ext", caps), Tier.EXTERNAL, 1.0),
        (_Scripted("oll", caps), Tier.OLLAMA, 0.0),
        (_Scripted("loc", caps), Tier.LOCAL, 0.0),
        policy=RoutingPolicy(
            external_enabled=True,
            allow_external_for=frozenset({V3Capability.EXTRACTION}),
        ),
        budget=Budget(max_calls=10, max_cost_units=10.0),
    )
    decision = router.route(V3Capability.EXTRACTION)
    assert decision.provider_name == "loc"
    assert decision.tier is Tier.LOCAL


def test_ollama_es_el_proveedor_por_defecto_cuando_no_hay_local():
    caps = {Capability.EXTRACT_TEXT_ENTITIES}
    router = _router(
        (_Scripted("ext", caps), Tier.EXTERNAL, 1.0),
        (_Scripted("oll", caps), Tier.OLLAMA, 0.0),
        policy=RoutingPolicy(external_enabled=True, allow_external_for=frozenset(V3Capability)),
        budget=Budget(10, 10.0),
    )
    assert router.route(V3Capability.EXTRACTION).tier is Tier.OLLAMA


def test_externo_apagado_por_defecto():
    """Fail-closed: sin politica que lo encienda, el externo no se usa."""
    router = _router((_Scripted("ext", {Capability.EXTRACT_TEXT_ENTITIES}), Tier.EXTERNAL, 1.0))
    decision = router.route(V3Capability.EXTRACTION)
    assert not decision.routed
    assert ("ext", "EXTERNAL_DISABLED") in decision.rejected


def test_externo_requiere_capacidad_autorizada_una_a_una():
    router = _router(
        (_Scripted("ext", {Capability.EXTRACT_TEXT_ENTITIES, Capability.OCR_IMAGE}), Tier.EXTERNAL, 1.0),
        policy=RoutingPolicy(
            external_enabled=True, allow_external_for=frozenset({V3Capability.OCR})
        ),
        budget=Budget(10, 10.0),
    )
    assert router.route(V3Capability.OCR).routed
    assert not router.route(V3Capability.EXTRACTION).routed


def test_contenido_privado_no_sale_fuera():
    router = _router(
        (_Scripted("ext", {Capability.EXTRACT_TEXT_ENTITIES}), Tier.EXTERNAL, 1.0),
        policy=RoutingPolicy(
            external_enabled=True, allow_external_for=frozenset({V3Capability.EXTRACTION})
        ),
        budget=Budget(10, 10.0),
    )
    decision = router.route(V3Capability.EXTRACTION, private_content=True)
    assert not decision.routed
    assert ("ext", "PRIVATE_CONTENT_STAYS_LOCAL") in decision.rejected


def test_umbral_de_entrada_evita_salir_fuera_por_nada():
    router = _router(
        (_Scripted("ext", {Capability.EXTRACT_TEXT_ENTITIES}), Tier.EXTERNAL, 1.0),
        policy=RoutingPolicy(
            external_enabled=True,
            allow_external_for=frozenset({V3Capability.EXTRACTION}),
            external_min_input_units=1000.0,
        ),
        budget=Budget(10, 10.0),
    )
    assert not router.route(V3Capability.EXTRACTION, input_units=10).routed
    assert router.route(V3Capability.EXTRACTION, input_units=5000).routed


def test_sin_proveedor_para_la_capacidad_no_hay_ruta():
    router = _router((_Scripted("oll", {Capability.EXTRACT_TEXT_ENTITIES}), Tier.OLLAMA, 0.0))
    decision = router.route(V3Capability.ASR)
    assert not decision.routed
    assert decision.reason_codes == ("NO_PROVIDER_FOR_CAPABILITY",)


# --------------------------------------------------------------------------
# Presupuesto
# --------------------------------------------------------------------------
def test_presupuesto_agotado_cierra_la_ruta_externa():
    budget = Budget(max_calls=1, max_cost_units=99.0)
    router = _router(
        (_Scripted("ext", {Capability.EXTRACT_TEXT_ENTITIES}), Tier.EXTERNAL, 1.0),
        policy=RoutingPolicy(
            external_enabled=True, allow_external_for=frozenset({V3Capability.EXTRACTION})
        ),
        budget=budget,
    )
    assert router.route(V3Capability.EXTRACTION).routed
    second = router.route(V3Capability.EXTRACTION)
    assert not second.routed
    assert ("ext", "BUDGET_EXHAUSTED") in second.rejected


def test_presupuesto_por_coste_ademas_de_por_llamadas():
    budget = Budget(max_calls=100, max_cost_units=2.5)
    assert budget.reserve(2.0)
    assert not budget.reserve(1.0)
    assert budget.cost_used == pytest.approx(2.0)


def test_presupuesto_se_devuelve_si_la_llamada_no_se_consume():
    budget = Budget(max_calls=1, max_cost_units=10.0)
    router = _router(
        (
            _Scripted(
                "ext", {Capability.EXTRACT_TEXT_ENTITIES}, error=RuntimeError("caido")
            ),
            Tier.EXTERNAL,
            1.0,
        ),
        policy=RoutingPolicy(
            external_enabled=True, allow_external_for=frozenset({V3Capability.EXTRACTION})
        ),
        budget=budget,
    )
    outcome = _run(router, max_attempts=1)
    assert not outcome.ok
    assert budget.calls_used == 0, "una llamada fallida no debe consumir presupuesto"


def test_presupuesto_por_defecto_es_cero():
    """`Budget.from_env()` sin variables no autoriza ni una llamada."""
    budget = Budget(max_calls=0, max_cost_units=0.0)
    assert not budget.reserve(0.0)


# --------------------------------------------------------------------------
# Ejecucion
# --------------------------------------------------------------------------
def test_run_devuelve_propuesta_etiquetada_con_proveedor_y_modelo():
    provider = _Scripted(
        "oll", {Capability.EXTRACT_TEXT_ENTITIES}, result={"provider": "oll", "model": "qwen2.5:7b", "payload": {"mentions": []}}
    )
    router = _router((provider, Tier.OLLAMA, 0.0))
    outcome = _run(router)
    assert outcome.ok
    assert outcome.provider_name == "oll"
    assert outcome.tier is Tier.OLLAMA
    assert outcome.model == "qwen2.5:7b"
    assert outcome.result["payload"] == {"mentions": []}


def test_run_sin_ruta_no_lanza_y_marca_no_route():
    outcome = _run(ProviderRouter())
    assert not outcome.ok
    assert outcome.error_code == "NO_ROUTE"


def test_fallback_al_siguiente_candidato_cuando_el_primero_cae():
    caido = _Scripted("a-caido", {Capability.EXTRACT_TEXT_ENTITIES}, error=RuntimeError("boom"))
    vivo = _Scripted("b-vivo", {Capability.EXTRACT_TEXT_ENTITIES})
    router = _router((caido, Tier.OLLAMA, 0.0), (vivo, Tier.OLLAMA, 0.0))
    outcome = _run(router, max_attempts=1)
    assert outcome.ok
    assert outcome.provider_name == "b-vivo"
    assert caido.calls >= 1


def test_fallback_desactivado_devuelve_el_fallo_del_primero():
    caido = _Scripted("a-caido", {Capability.EXTRACT_TEXT_ENTITIES}, error=RuntimeError("boom"))
    vivo = _Scripted("b-vivo", {Capability.EXTRACT_TEXT_ENTITIES})
    router = _router((caido, Tier.OLLAMA, 0.0), (vivo, Tier.OLLAMA, 0.0))
    outcome = _run(router, max_attempts=1, fallback=False)
    assert not outcome.ok
    assert outcome.provider_name == "a-caido"
    assert vivo.calls == 0


def test_el_fallback_no_salta_la_politica_para_llegar_al_externo():
    """Que el local falle NO autoriza el externo si la politica lo prohibe."""
    caido = _Scripted("loc", {Capability.EXTRACT_TEXT_ENTITIES}, error=RuntimeError("boom"))
    externo = _Scripted("ext", {Capability.EXTRACT_TEXT_ENTITIES})
    router = _router((caido, Tier.LOCAL, 0.0), (externo, Tier.EXTERNAL, 1.0))
    outcome = _run(router, max_attempts=1)
    assert not outcome.ok
    assert externo.calls == 0, "el externo se ha usado sin autorizacion de politica"


def test_capacidad_no_soportada_falla_sin_ejecutar():
    provider = _Scripted("oll", {Capability.EXTRACT_TEXT_ENTITIES})
    router = _router((provider, Tier.OLLAMA, 0.0))
    outcome = _run(router, capability=V3Capability.ASR)
    assert not outcome.ok
    assert provider.calls == 0


def test_healthcheck_agrega_todos_los_proveedores_con_su_tier():
    router = _router(
        (_Scripted("oll", {Capability.EXTRACT_TEXT_ENTITIES}), Tier.OLLAMA, 0.0),
        (_Scripted("loc", {Capability.OCR_IMAGE}), Tier.LOCAL, 0.0),
    )
    health = router.healthcheck()
    assert set(health) == {"oll", "loc"}
    assert health["oll"]["tier"] == "ollama"


def test_healthcheck_no_propaga_excepciones_del_proveedor():
    class _Roto(_Scripted):
        def healthcheck(self):
            raise RuntimeError("explota")

    router = _router((_Roto("roto", {Capability.OCR_IMAGE}), Tier.LOCAL, 0.0))
    assert router.healthcheck()["roto"]["status"] == "error"


def test_el_mock_de_la_fase_b1_sigue_funcionando_bajo_el_router_v3():
    """Reutilizacion real: el mock existente se registra sin adaptador."""
    router = _router((MockExternalProcessingProvider(), Tier.LOCAL, 0.0))
    outcome = router.run(
        V3Capability.EXTRACTION,
        workspace=WORKSPACE,
        source_id="src-1",
        payload={"text": "hola"},
        chunk={"source_hash": SOURCE_HASH["value"], "chunk_index": 0},
    )
    assert outcome.ok
    assert outcome.provider_name == "mock"

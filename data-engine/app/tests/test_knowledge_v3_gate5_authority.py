# -*- coding: utf-8 -*-
"""Puerta 5: AUTORIDAD LOCAL. Ningun proveedor decide una escritura.

La tesis que se prueba aqui es una sola y es la que sostiene todo el diseno V3:

    un proveedor —Ollama, NVIDIA o el que venga— **propone**; el motor local
    **decide**; y lo que se escribe sale exclusivamente de la decision local.

Se ataca por los dos lados que podrian romperla:

1. **Fallos del proveedor** (timeout, 401/403, 404 de funcion, JSON invalido,
   respuesta vacia). Un proveedor caido no puede tumbar el lote, ni colar un
   claim sin evidencia, ni provocar una escritura. Cada modo de fallo produce
   una ABSTENCION con diagnostico y el lote sigue.
2. **La sombra** (`semantic_shadow_evaluation`). La evaluacion en sombra existe
   para MEDIR cuanto cambiaria si se confiase mas en el semantico. Si un solo
   registro de sombra pudiese alterar la decision efectiva o producir una
   operacion aplicable, dejaria de ser sombra y seria una puerta trasera.

Los proveedores REALES (Ollama y NVIDIA) se miden aparte, en
`artifacts/v3-final-validation/gate5_authority_runner.py`, porque una llamada de
red no puede vivir en la suite. Aqui los dobles son deterministas: sirven de
REGRESION, no de evidencia de que el proveedor real funcione.
"""
from __future__ import annotations

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.extraction.base import ExtractionContext  # noqa: E402
from knowledge_v3.extraction.provider_port import (  # noqa: E402
    ProviderBadJSON,
    ProviderReply,
    ProviderUnavailable,
)
from knowledge_v3.extraction.semantic import SemanticEpisodeExtractor  # noqa: E402

from test_knowledge_v3_extraction import (  # noqa: E402,I100 - fixtures hermanas
    GOLD_LEXICON,
    WORKSPACE,
    make_profile,
    text_episode,
)

TEXTO = "Elara es miembro de la Orden del Alba."
TEXTO_B = "Kael vive en Valdor."


# ==========================================================================
# Dobles de proveedor: un modo de fallo cada uno
# ==========================================================================
class FailingPort:
    """Puerto que siempre falla con la excepcion que se le pida.

    `provider`/`model` imitan al puerto real para que el extractor construya la
    misma identidad; lo unico que cambia es que la llamada revienta.
    """

    def __init__(self, exc: Exception, *, provider=None, model: str = "doble-fallo"):
        from knowledge_v3.extraction.base import Provider

        self._exc = exc
        self.provider = provider or Provider.OLLAMA
        self.model = model
        self.calls = 0

    def complete_json(self, request):  # noqa: ANN001 - firma del Protocol
        self.calls += 1
        raise self._exc


class EmptyPort:
    """Responde 200 con un JSON vacio: el peor caso, porque no es un error."""

    def __init__(self, payload=None):
        from knowledge_v3.extraction.base import Provider

        self.provider = Provider.OLLAMA
        self.model = "doble-vacio"
        self.payload = {} if payload is None else payload
        self.calls = 0

    def complete_json(self, request):  # noqa: ANN001
        self.calls += 1
        return ProviderReply(
            payload=self.payload,
            model=self.model,
            provider="ollama",
            latency_ms=1,
            attempts=1,
            json_retries=0,
        )


#: Modos de fallo que el transporte SI señala como fallo. `404 de funcion` y
#: `401/403` llegan al puerto como `ProviderUnavailable` — es lo que hacen los
#: adaptadores reales: traducen la familia de excepciones del transporte a la
#: del puerto.
#:
#: `respuesta_vacia` NO esta en esta lista, y no por descuido: un 200 con cuerpo
#: vacio no es un error para el transporte. Se trata aparte, en la seccion 1b,
#: donde ademas queda documentado el hallazgo P5-1.
FAILURE_MODES = (
    ("timeout", lambda: FailingPort(ProviderUnavailable("timeout tras 30s"))),
    ("401_403", lambda: FailingPort(ProviderUnavailable("HTTP 401 Unauthorized"))),
    ("404_funcion", lambda: FailingPort(ProviderUnavailable("HTTP 404 model not found"))),
    ("json_invalido", lambda: FailingPort(ProviderBadJSON("la respuesta no es JSON"))),
)


def context_for(*texts: str):
    episodes, fragments = [], []
    for index, text in enumerate(texts):
        episode, frags = text_episode(f"ep:gate5:{index}", text)
        episodes.append(episode)
        fragments.extend(frags)
    ctx = ExtractionContext(
        workspace=WORKSPACE,
        episodes=episodes,
        fragments=fragments,
        profile=make_profile(),
        lexicon=GOLD_LEXICON,
    )
    return ctx, episodes


# ==========================================================================
# 1. Fallos de proveedor: abstencion con diagnostico, nunca una escritura
# ==========================================================================
@pytest.mark.parametrize("mode,factory", FAILURE_MODES, ids=[m for m, _ in FAILURE_MODES])
def test_un_fallo_del_proveedor_se_abstiene_y_deja_rastro(mode, factory):
    ctx, episodes = context_for(TEXTO)
    port = factory()
    out = SemanticEpisodeExtractor(port).extract_episode(ctx, episodes[0])

    assert port.calls >= 1, "el doble ni siquiera se llamo: el test no probaria nada"
    # Un diagnostico con codigo: el fallo se declara, no se traga en silencio.
    assert out.diagnostics, f"{mode}: el fallo no dejo diagnostico"
    # Y ni un solo claim activo: lo unico admisible es la abstencion.
    activos = [c for c in out.claims if not c.abstained]
    assert activos == [], f"{mode}: un proveedor caido produjo claims activos"


@pytest.mark.parametrize("mode,factory", FAILURE_MODES, ids=[m for m, _ in FAILURE_MODES])
def test_el_fallo_de_un_episodio_no_tumba_el_lote(mode, factory):
    """El episodio malo se abstiene; los demas siguen procesandose.

    Es la diferencia entre "un documento no se pudo leer" y "la ingesta entera
    se cayo por un 401".
    """
    ctx, episodes = context_for(TEXTO, TEXTO_B)
    extractor = SemanticEpisodeExtractor(factory())

    outs = [extractor.extract_episode(ctx, episode) for episode in episodes]

    assert len(outs) == 2, "el segundo episodio no llego a procesarse"
    assert all(o.diagnostics for o in outs)
    # Y el extractor registra cada corrida: el fallo es auditable episodio a episodio.
    assert len(extractor.runs) == 2


def test_el_determinista_sigue_funcionando_con_el_semantico_caido():
    """El carril local no depende de la red. Si dependiese, no seria local."""
    from knowledge_v3.extraction.deterministic import DeterministicExtractor

    ctx, episodes = context_for(TEXTO)
    semantic = SemanticEpisodeExtractor(FailingPort(ProviderUnavailable("caido")))

    semantic_out = semantic.extract_episode(ctx, episodes[0])
    det_out = DeterministicExtractor().extract_episode(ctx, episodes[0])

    assert [c for c in semantic_out.claims if not c.abstained] == []
    assert [c for c in det_out.claims if not c.abstained], (
        "el determinista tambien se quedo sin claims: el test no distingue carriles"
    )


@pytest.mark.parametrize("mode,factory", FAILURE_MODES, ids=[m for m, _ in FAILURE_MODES])
def test_ningun_fallo_de_proveedor_produce_una_escritura(mode, factory):
    """Gate: 0 escrituras decididas por proveedor.

    Se comprueba sobre el artefacto final: las abstenciones que deja un
    proveedor caido no llegan a ser operaciones de ningun plan.
    """
    ctx, episodes = context_for(TEXTO)
    out = SemanticEpisodeExtractor(factory()).extract_episode(ctx, episodes[0])

    for claim in out.claims:
        assert claim.abstained, f"{mode}: claim no abstenido de un proveedor caido"
        # Una abstencion nunca se autodeclara aceptable ni pide confianza alta.
        assert claim.confidence <= 0.5, (mode, claim.confidence)


# ==========================================================================
# 1b. Respuesta vacia: el modo de fallo que NO parece un fallo
# ==========================================================================
def test_una_respuesta_vacia_no_produce_ninguna_escritura():
    """Lo que SI esta garantizado: un cuerpo vacio no escribe nada.

    Este es el gate duro de la puerta 5 y se cumple. Lo que no se cumple es la
    OBSERVABILIDAD, y eso va en el test siguiente.
    """
    ctx, episodes = context_for(TEXTO)
    out = SemanticEpisodeExtractor(EmptyPort()).extract_episode(ctx, episodes[0])

    assert [c for c in out.claims if not c.abstained] == []
    assert out.mentions == []


# HALLAZGO P5-1 corregido: el episodio sigue siendo ok pero deja diagnostico auditable.
def test_p5_1_una_respuesta_vacia_deberia_dejar_rastro():
    ctx, episodes = context_for(TEXTO)
    extractor = SemanticEpisodeExtractor(EmptyPort())
    out = extractor.extract_episode(ctx, episodes[0])

    # Reproducción mínima: `{}` entra, nada sale, y la corrida se declara OK.
    assert extractor.runs[-1].ok is True, "precondición del hallazgo"
    assert out.diagnostics, "una respuesta vacía no dejó ningún diagnóstico"


# ==========================================================================
# 2. La evidencia y la ontologia no las pone el proveedor
# ==========================================================================
def test_un_claim_semantico_siempre_cita_un_fragmento_del_episodio():
    """Gate: 0 claims sin evidencia literal.

    Incluye las abstenciones: tambien ellas se anclan al episodio del que
    salieron, porque una abstencion sin fuente no se puede auditar.
    """
    ctx, episodes = context_for(TEXTO)
    out = SemanticEpisodeExtractor(EmptyPort()).extract_episode(ctx, episodes[0])
    validos = set(ctx.index_of(episodes[0]).fragment_ids)

    for claim in out.claims:
        assert claim.evidence_fragment_ids, "claim sin evidencia"
        assert set(claim.evidence_fragment_ids) <= validos, (
            "el claim cita un fragmento que no es de su episodio"
        )


def test_el_proveedor_no_puede_inventarse_un_predicado_fuera_de_la_ontologia():
    """Gate: 0 predicados fuera de ontologia.

    El doble responde con un predicado que NO existe en el perfil. Lo que se
    exige no es que el sistema lo acepte con elegancia, sino que no lo deje
    entrar como candidato factual.
    """
    ctx, episodes = context_for(TEXTO)
    inventado = {
        "mentions": [
            {"surface": "Elara", "start": 0, "end": 5, "entity_type": "Character"},
            {"surface": "Orden del Alba", "start": 22, "end": 36, "entity_type": "Faction"},
        ],
        "claims": [
            {
                "subject": "Elara",
                "object": "Orden del Alba",
                "predicate": "ES_EL_ELEGIDO_DE",  # no existe en el perfil
                "direction": "SUBJECT_TO_OBJECT",
                "evidence": TEXTO,
                "confidence": 0.99,
            }
        ],
    }
    out = SemanticEpisodeExtractor(EmptyPort(inventado)).extract_episode(ctx, episodes[0])

    permitidos = ctx.profile_predicates()
    for claim in out.claims:
        if claim.abstained:
            continue
        for candidate in claim.predicate_candidates:
            assert candidate["predicate"] in permitidos, (
                f"predicado fuera de ontologia admitido: {candidate['predicate']}"
            )


def test_el_proveedor_no_puede_firmar_una_confianza_alta():
    """El tope de confianza es del sistema, no del modelo.

    El doble pide 0.99. El extractor tiene que recortarlo: un LLM sin calibrar
    contra el corpus no puede firmar una certeza que nadie ha medido.
    """
    ctx, episodes = context_for(TEXTO)
    payload = {
        "mentions": [
            {"surface": "Elara", "start": 0, "end": 5, "entity_type": "Character"},
            {"surface": "Orden del Alba", "start": 22, "end": 36, "entity_type": "Faction"},
        ],
        "claims": [
            {
                "subject": "Elara",
                "object": "Orden del Alba",
                "predicate": "MEMBER_OF",
                "direction": "SUBJECT_TO_OBJECT",
                "evidence": TEXTO,
                "confidence": 0.99,
            }
        ],
    }
    extractor = SemanticEpisodeExtractor(EmptyPort(payload))
    out = extractor.extract_episode(ctx, episodes[0])

    for claim in out.claims:
        assert claim.confidence <= extractor.confidence_cap, (
            claim.confidence, extractor.confidence_cap
        )


# ==========================================================================
# 3. La sombra es inerte: mide, no decide
# ==========================================================================
def test_el_registro_de_sombra_no_puede_transportar_una_operacion_aplicable():
    """Gate: 0 operaciones sombra aplicables.

    No se comprueba mirando una corrida concreta —eso solo diria que HOY no
    llevaba ninguna—, sino la FORMA del registro: si `ShadowDecisionRecord`
    solo puede contener cadenas, booleanos y tuplas de cadenas, entonces no hay
    corrida capaz de meter en el un plan ni una operacion ejecutable.

    `operation_kinds` es una tupla de ETIQUETAS ("CREATE_ASSERTION"), no de
    operaciones: un nombre no se puede aplicar contra un grafo.
    """
    from dataclasses import fields

    from knowledge_v3.engine.shadow import ShadowDecisionRecord

    assert ShadowDecisionRecord.__dataclass_params__.frozen, (
        "un registro mutable de sombra podria modificarse despues de emitirse"
    )
    permitidos = {"str", "bool", "str | None", "tuple[str, ...]"}
    tipos = {f.name: str(f.type) for f in fields(ShadowDecisionRecord)}
    fuera = {n: t for n, t in tipos.items() if t not in permitidos}
    assert fuera == {}, f"la sombra transporta tipos no inertes: {fuera}"


def test_la_sombra_trabaja_sobre_copias_y_no_toca_la_decision_efectiva():
    """Gate: 0 decisiones efectivas alteradas por la sombra.

    Se le da a `evaluate_semantic_shadow` la MISMA lista que se usa como
    efectiva y se comprueba que, tras evaluar, las decisiones efectivas siguen
    byte a byte igual. Si la sombra mutase en sitio en vez de copiar, aqui se
    veria.
    """
    import json

    from knowledge_v3.engine import DEFAULT_CONFIG
    from knowledge_v3.engine.ontology import ProfileIndex
    from knowledge_v3.engine.shadow import evaluate_semantic_shadow

    from test_knowledge_v3_engine_gold import claim as gold_claim
    from test_knowledge_v3_engine_gold import profile as gold_profile
    from test_knowledge_v3_engine_gold import run as gold_run

    result = gold_run([gold_claim()])
    decisions = result.decisions

    def huella():
        return json.dumps(
            [
                {**d.to_contract_dict(), "findings": [f.code for f in d.findings]}
                for d in decisions
            ],
            sort_keys=True,
            ensure_ascii=False,
        )

    antes = huella()
    records = evaluate_semantic_shadow(
        [gold_claim()], decisions, decisions, ProfileIndex(gold_profile()), DEFAULT_CONFIG
    )
    assert huella() == antes, "la sombra alteró las decisiones efectivas"
    # Y lo que devuelve son registros inertes, no operaciones.
    for record in records:
        assert isinstance(record.operation_kinds, tuple)
        assert all(isinstance(k, str) for k in record.operation_kinds)


# ==========================================================================
# 4. La frontera motor -> writer, ejercitada en modo APPLY sin Neo4j
# ==========================================================================
def _pipeline_plan_de_un_hecho():
    """Plan REAL del motor sobre un texto limpio, recorriendo la cadena entera."""
    from knowledge_v3.pipeline.pipeline import KnowledgePipeline

    from test_knowledge_v3_e2e_global import (
        T_HECHO,
        base_config,
        gold_dev,
        raw_case,
        snapshot_entities,
    )

    gold = gold_dev()
    entities = snapshot_entities(gold)
    pipeline = KnowledgePipeline(base_config(gold, writer_driver=None))
    run = pipeline.run([raw_case("g5-apply", T_HECHO)], catalog_entities=entities).runs[0]
    assert run.plan is not None, (run.stopped_at, run.stop_reason)
    return run.plan.to_dict()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HALLAZGO F7-2: el plan que produce el motor NO es ejecutable. El planner "
        "mete `assertion_id` en el payload de CREATE_ASSERTION (planner.py: "
        "PAYLOAD_FIELDS empieza por 'assertion_id') y el writer lo rechaza como "
        "propiedad reservada (cypher.py: RESERVED_PROPS). Sale "
        "EXEC_UNSUPPORTED_PAYLOAD / OUTCOME_ABORTED y NO se escribe nada. Estaba "
        "oculto porque `simulate_plan` (dry-run) no llama a `safe_props`: todos "
        "los e2e simulan, y todos los tests del writer que aplican construyen el "
        "payload a mano SIN assertion_id. Nadie habia aplicado un plan del motor."
    ),
)
def test_f7_2_el_plan_del_motor_se_aplica_sin_ser_rechazado():
    """Se ejecuta en modo APPLY con driver falso: no hace falta Neo4j.

    Lo que se prueba no es el grafo —eso es la puerta 7— sino que el artefacto
    que el motor firma sea el que el writer sabe ejecutar.
    """
    from datetime import datetime

    from knowledge_v3.writer import (
        GraphWriter,
        InMemoryAppliedKeys,
        InMemoryAuditSink,
        OperatorRequest,
    )

    from test_knowledge_v3_writer import FakeDriver

    plan = _pipeline_plan_de_un_hecho()
    moment = datetime.fromisoformat(plan["created_at"].replace("Z", "+00:00"))
    writer = GraphWriter(
        workspace=plan["workspace"],
        driver=FakeDriver(),
        audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
        clock=lambda: moment,
    )
    request = OperatorRequest(
        apply=True,
        operator_id="gate5",
        workspace=plan["workspace"],
        expected_plan_hash=plan["plan_hash"]["value"],
        max_operations=50,
        current_snapshot_id=plan["snapshot_id"],
        env={
            "S9K_ALLOW_REAL_INGEST": "1",
            "S9K_WRITER_WORKSPACE": plan["workspace"],
        },
    )

    result = writer.write(plan, request)

    assert result.ok, result.codes


def test_f7_2_el_dry_run_del_mismo_plan_si_pasa():
    """Control que localiza el defecto: en simulacion el mismo plan va bien.

    Es la razon de que F7-2 sobreviviese a toda la bateria e2e: el dry-run no
    valida el payload, asi que un plan inejecutable se presenta al operador como
    perfectamente simulable.
    """
    from datetime import datetime

    from knowledge_v3.writer import (
        GraphWriter,
        InMemoryAppliedKeys,
        InMemoryAuditSink,
        OperatorRequest,
    )
    from knowledge_v3.writer.writer import OUTCOME_SIMULATED

    from test_knowledge_v3_writer import ExplodingDriver

    plan = _pipeline_plan_de_un_hecho()
    moment = datetime.fromisoformat(plan["created_at"].replace("Z", "+00:00"))
    writer = GraphWriter(
        workspace=plan["workspace"],
        driver=ExplodingDriver(),
        audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
        clock=lambda: moment,
    )
    request = OperatorRequest(
        apply=False,
        operator_id="gate5",
        workspace=plan["workspace"],
        current_snapshot_id=plan["snapshot_id"],
        env={},
    )

    result = writer.write(plan, request)

    assert result.outcome == OUTCOME_SIMULATED, result.codes


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HALLAZGO F7-1: una cesacion nunca puede cerrar nada por la ruta real. "
        "`bridge.assertion_from_edge` construye la SnapshotAssertion SIN "
        "`state_hash` (las entidades si lo derivan, via SnapshotEntity.of), y "
        "`engine/negation.py` se niega —con razon— a cerrar una vigencia sin "
        "ancla de concurrencia: emite CESSATION_TARGET_UNANCHORED y deja "
        "supersedes=None. Consecuencia: SUPERSEDE_ASSERTION es inalcanzable "
        "desde el pipeline, y por eso la puerta 4 midio 0 operaciones "
        "destructivas y dio NO EVALUABLE en las dos precisiones destructivas."
    ),
)
def test_f7_1_una_cesacion_sobre_un_hecho_vigente_supersede():
    """Dos corridas sobre el MISMO pipeline: se afirma y luego se cesa."""
    from knowledge_v3.pipeline.pipeline import KnowledgePipeline

    from test_knowledge_v3_e2e_global import (
        T_CESACION,
        T_HECHO,
        base_config,
        gold_dev,
        raw_case,
        snapshot_entities,
    )

    gold = gold_dev()
    entities = snapshot_entities(gold)
    pipeline = KnowledgePipeline(base_config(gold, writer_driver=None))

    primera = pipeline.run([raw_case("f71-a", T_HECHO)], catalog_entities=entities).runs[0]
    assert primera.decisions[0].decision == "ACCEPT", "precondicion: el hecho queda vigente"

    segunda = pipeline.run([raw_case("f71-b", T_CESACION)], catalog_entities=entities).runs[0]
    decision = segunda.decisions[0]

    assert decision.supersedes is not None, (
        f"la cesacion no encontro que cerrar: {sorted(decision.reason_codes())}"
    )


def test_f7_1_el_snapshot_del_ledger_no_ancla_sus_afirmaciones():
    """Reproduccion minima y directa de la causa de F7-1.

    Se afirma que hoy es asi. Si alguien corrige el bridge, este test falla y
    obliga a revisar el hallazgo en vez de dejarlo obsoleto en un informe.
    """
    from knowledge_v3.pipeline import bridge
    from knowledge_v3.pipeline.pipeline import KnowledgePipeline

    from test_knowledge_v3_e2e_global import (
        T_HECHO,
        base_config,
        gold_dev,
        raw_case,
        snapshot_entities,
    )

    gold = gold_dev()
    entities = snapshot_entities(gold)
    pipeline = KnowledgePipeline(base_config(gold, writer_driver=None))
    pipeline.run([raw_case("f71-c", T_HECHO)], catalog_entities=entities)

    snap = bridge.engine_snapshot(pipeline.ledger, entities=entities)
    assert len(snap.assertions) == 1
    assert snap.assertions[0].state_hash is None, (
        "el bridge ya ancla las afirmaciones: F7-1 puede estar corregido"
    )
    # Y la asimetria: las ENTIDADES si van ancladas.
    alguna = next(iter(snap.entities.values())) if hasattr(snap, "entities") else None
    if alguna is not None:
        assert alguna.state_hash, "las entidades deberian ir ancladas"


def test_el_carril_externo_esta_mas_capado_que_el_local():
    """Un proveedor remoto no ha visto el corpus: su techo es mas bajo.

    No es desconfianza decorativa — es que su salida no se puede reproducir en
    local, asi que no puede pesar lo mismo que el carril local.
    """
    from knowledge_v3.extraction.base import Provider

    local = SemanticEpisodeExtractor(FailingPort(ProviderUnavailable("x")))
    externo = SemanticEpisodeExtractor(
        FailingPort(ProviderUnavailable("x"), provider=Provider.EXTERNAL)
    )
    assert externo.confidence_cap < local.confidence_cap

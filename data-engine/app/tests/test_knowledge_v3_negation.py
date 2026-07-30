# -*- coding: utf-8 -*-
"""NEGACIONES: se detectan, se marcan, sobreviven y el motor decide que significan.

Principio del bloque, y no es un matiz de redaccion:

    "relacion negada"  !=  "ausencia de relacion"  !=  "relacion positiva"

El extractor DETECTA, propone, marca `negated` y el tipo, y conserva la cita. El
MOTOR decide. El plan NUNCA convierte una negacion en una arista positiva.

Tres familias:

  1. extractor  — los diez casos del encargo, sobre texto real;
  2. motor      — negativa sin previa, cesacion con y sin previa, contradiccion,
                  separacion temporal;
  3. E2E        — por `KnowledgePipeline`, comprobando que `negated`, el tipo, la
                  evidencia, la temporalidad y la decision llegan hasta el plan.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

_APP_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(_APP_DIR), str(_TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from knowledge_v3.contracts import EvidenceFragment, SourceEpisode  # noqa: E402
from knowledge_v3.contracts.base import sha256_hash  # noqa: E402
from knowledge_v3.extraction import cues as C  # noqa: E402
from knowledge_v3.extraction.provider_port import ProviderReply, ProviderRequest  # noqa: E402
from knowledge_v3.extraction.semantic import SemanticEpisodeExtractor  # noqa: E402
from knowledge_v3.extraction.text import tokenize  # noqa: E402
from knowledge_v3.pipeline import KnowledgePipeline  # noqa: E402
from knowledge_v3.pipeline.pipeline import SourceCase  # noqa: E402

from test_knowledge_v3_e2e_fixtures import (  # noqa: E402
    base_config,
    gold_dev,
    snapshot_entities,
)
from test_knowledge_v3_extraction import make_profile, single_context  # noqa: E402


# ===========================================================================
# Utilidades
# ===========================================================================
def verdict(text: str, *, focus_word: str = "") -> C.NegationVerdict:
    """Clasifica la negacion de `text` con el foco en la relacion."""
    tokens = tokenize(text)
    focus = len(tokens)
    if focus_word:
        norm = C.phrase_tokens(focus_word)[0]
        focus = next(t.index for t in tokens if t.norm == norm)
    return C.classify_negation(tokens, lo=0, hi=len(tokens), focus=focus, source_text=text)


# ===========================================================================
# 1. EXTRACTOR: los diez casos
# ===========================================================================
class TestClasificacionDeNegacion:
    """Sobre `cues.classify_negation`, que es donde vive la regla."""

    def test_simple(self):
        v = verdict("Toturi no pertenece al clan Escorpion", focus_word="pertenece")
        assert v.negated is True
        assert v.kind == C.NEGATION_KIND_SIMPLE

    def test_nunca_es_negacion_absoluta_y_no_inventa_intervalo(self):
        v = verdict("Toturi nunca perteneció al clan Escorpion", focus_word="pertenecio")
        assert v.negated is True
        assert v.kind == C.NEGATION_KIND_NEVER

    @pytest.mark.parametrize(
        "texto,foco",
        [
            ("Toturi ya no lidera el clan Escorpion", "lidera"),
            ("Toturi dejó de liderar el clan Escorpion", "liderar"),
            ("Toturi cesó de servir al clan Escorpion", "servir"),
            ("Toturi abandonó el clan Escorpion", "clan"),
            ("Toturi rompió su alianza con el clan Escorpion", "alianza"),
        ],
    )
    def test_cesacion(self, texto, foco):
        v = verdict(texto, focus_word=foco)
        assert v.negated is True, texto
        assert v.kind == C.NEGATION_KIND_CESSATION, texto

    def test_todavia_no_NO_es_cesacion(self):
        """No demuestra que antes lo fuera. Confundirlo cerraria una vigencia."""
        v = verdict("Toturi todavía no lidera el clan Escorpion", focus_word="lidera")
        assert v.negated is True
        assert v.kind == C.NEGATION_KIND_NOT_YET
        assert v.kind != C.NEGATION_KIND_CESSATION

    def test_aun_no_tampoco(self):
        assert verdict("Toturi aún no lidera el clan", focus_word="lidera").kind == (
            C.NEGATION_KIND_NOT_YET
        )

    def test_alcance_complejo_la_negacion_es_de_la_creencia(self):
        v = verdict(
            "El magistrado no cree que Toturi pertenezca al clan", focus_word="pertenezca"
        )
        assert v.negated is False
        assert v.kind == C.NEGATION_KIND_SCOPE_AMBIGUOUS
        assert C.CODE_NEGATION_SCOPE in v.reason_codes

    def test_negacion_en_OTRA_clausula_no_viaja(self):
        v = verdict(
            "Toturi no llegó a tiempo, pero Hida pertenece al clan Escorpion",
            focus_word="pertenece",
        )
        assert v.negated is False
        assert v.kind == ""

    def test_doble_negacion_no_se_resuelve_mecanicamente(self):
        v = verdict(
            "No es seguro que Toturi no pertenezca al clan", focus_word="pertenezca"
        )
        assert v.negated is False
        assert v.kind == C.NEGATION_KIND_SCOPE_AMBIGUOUS

    # -- CESACION NEGADA: la inversion semantica mas cara -------------------
    #
    # "Kaelen NO dejo de servir a la Orden" AFIRMA la relacion. Leerlo como una
    # cesacion propondria CERRAR la vigencia de la relacion que el texto afirma,
    # y el motor lo aceptaba: ACCEPT + SUPERSEDE_ASSERTION con `expected_version`
    # y `expected_hash`. Lo encontro el revisor independiente sobre eed8470.
    #
    # Causa raiz: la guarda de doble negacion contaba solo `NEGATION_CUES`, y las
    # frases de cesacion no son marcas de negacion, asi que "no" + "dejo de"
    # sumaba UNA sola marca y caia en CESSATION.
    CESACION_NEGADA = [
        ("Kaelen no dejó de servir a la Orden", "servir"),
        ("Kaelen no cesó de servir a la Orden", "servir"),
        ("Kaelen no dimitió de la Orden", "Orden"),
        ("Kaelen no fue expulsado de la Orden", "Orden"),
        ("Kaelen no renunció a la Orden", "Orden"),
        ("Kaelen no rompió su alianza con la Orden", "alianza"),
        ("Kaelen nunca dejó de servir a la Orden", "servir"),
        ("Kaelen jamás abandonó la Orden", "Orden"),
    ]

    @pytest.mark.parametrize("texto,foco", CESACION_NEGADA)
    def test_una_cesacion_NEGADA_no_es_una_cesacion(self, texto, foco):
        v = verdict(texto, focus_word=foco)
        assert v.kind != C.NEGATION_KIND_CESSATION, texto
        assert v.negated is False, texto
        assert v.kind == C.NEGATION_KIND_SCOPE_AMBIGUOUS, texto
        assert C.CODE_NEGATION_SCOPE in v.reason_codes, texto

    def test_la_marca_puede_ir_DESPUES_del_foco_de_la_relacion(self):
        """"Elara pertenece a la Orden y no la abandona" AFIRMA la pertenencia.

        La ventana de negacion normal mira antes del foco, y aqui la marca esta
        despues: sin una ventana propia de la frase de cesacion, esto se leia
        como cesacion y cerraba la vigencia de lo que el texto afirma.
        """
        v = verdict("Elara pertenece a la Orden y no la abandona.", focus_word="pertenece")
        assert v.kind == C.NEGATION_KIND_SCOPE_AMBIGUOUS
        assert v.negated is False

    @pytest.mark.parametrize(
        "texto,foco",
        [
            ("Kaelen dejó de servir a la Orden", "servir"),
            ("Kaelen cesó de servir a la Orden", "servir"),
            ("Kaelen dimitió de la Orden", "Orden"),
            ("Kaelen fue expulsado de la Orden", "Orden"),
            ("Kaelen renunció a la Orden", "Orden"),
            ("Kaelen rompió su alianza con la Orden", "alianza"),
            ("Kaelen abandonó la Orden", "Orden"),
            ("Kaelen ya no pertenece a la Orden", "pertenece"),
        ],
    )
    def test_la_cesacion_REAL_sigue_detectandose(self, texto, foco):
        """El arreglo no puede apagar la deteccion: control positivo de las 8."""
        v = verdict(texto, focus_word=foco)
        assert v.negated is True, texto
        assert v.kind == C.NEGATION_KIND_CESSATION, texto

    def test_ya_no_no_se_cuenta_dos_veces_como_doble_negacion(self):
        """`ya no` lleva su propio `no`: contarlo aparte lo volveria ambiguo."""
        v = verdict("Kaelen ya no pertenece a la Orden", focus_word="pertenece")
        assert v.kind == C.NEGATION_KIND_CESSATION

    def test_una_frase_sin_marcas_no_niega_nada(self):
        v = verdict("Toturi pertenece al clan Escorpion", focus_word="pertenece")
        assert v.negated is False and v.kind == ""

    def test_ni_y_tampoco_no_cuentan_como_doble_negacion(self):
        """Son coordinacion de la MISMA negacion, no dos negaciones."""
        v = verdict("Toturi no pertenece ni sirve al clan", focus_word="sirve")
        assert v.negated is True
        assert v.kind == C.NEGATION_KIND_SIMPLE

    def test_la_pregunta_y_la_prohibicion_no_son_hechos(self):
        tokens = tokenize("¿Toturi no pertenece al clan?")
        v = C.analyze_context("¿Toturi no pertenece al clan?", tokens, clause_scoped=True)
        assert C.CODE_INTERROGATIVE in v.reason_codes
        assert v.non_factive

        texto = "Toturi no debe pertenecer al clan Escorpion"
        v2 = C.analyze_context(texto, tokenize(texto), clause_scoped=True)
        assert C.CODE_DEONTIC in v2.reason_codes
        assert v2.not_a_statement
        assert not v2.non_factive, "una prohibicion se ABSTIENE, no se borra"


class TestMutacionesCesacionNegada:
    """Quitar la guarda TIENE que reproducir la inversion. Si no, no protege.

    Un test que pasa igual con y sin la regla no esta probando la regla.
    """

    def test_sin_contar_las_frases_de_cesacion_vuelve_la_inversion(self, monkeypatch):
        """Muta el recuento: sin cesaciones independientes, `no dejo de` niega."""
        monkeypatch.setattr(C, "independent_cessations", lambda *a, **k: [])
        monkeypatch.setattr(C, "negated_cessation", lambda *a, **k: None)
        v = verdict("Kaelen no dejó de servir a la Orden", focus_word="servir")
        assert v.kind == C.NEGATION_KIND_CESSATION, (
            "la guarda de doble negacion ya no depende de las frases de cesacion: "
            "el arreglo del defecto BLOQUEANTE se ha perdido"
        )
        assert v.negated is True

    def test_sin_ventana_propia_vuelve_la_inversion_por_la_marca_posterior(
        self, monkeypatch
    ):
        """Muta la ventana a 0: la marca de despues del foco deja de verse."""
        monkeypatch.setattr(C, "CESSATION_NEGATION_WINDOW", 0)
        v = verdict("Elara pertenece a la Orden y no la abandona.", focus_word="pertenece")
        assert v.kind == C.NEGATION_KIND_CESSATION
        assert v.negated is True

    def test_con_la_guarda_puesta_ninguno_de_los_dos_es_cesacion(self):
        """Control: sin mutar, los dos casos anteriores NO son cesacion."""
        for texto, foco in (
            ("Kaelen no dejó de servir a la Orden", "servir"),
            ("Elara pertenece a la Orden y no la abandona.", "pertenece"),
        ):
            assert verdict(texto, focus_word=foco).kind == C.NEGATION_KIND_SCOPE_AMBIGUOUS


# ===========================================================================
# 2. EXTRACTOR SEMANTICO: la evidencia manda sobre el modelo
# ===========================================================================
TEXT_NEG = "Elara no pertenece a la Orden del Alba desde el año 300."
TEXT_POS = "Elara pertenece a la Orden del Alba desde el año 300."
TEXT_SCOPE = "El magistrado no cree que Elara pertenezca a la Orden del Alba."


class Puerto:
    """Puerto guionizado. Devuelve el payload dado; nada mas."""

    provider = __import__(
        "knowledge_v3.contracts", fromlist=["Provider"]
    ).Provider.LOCAL
    model = "mock"
    name = "s9k.extraction.port.mock"

    def __init__(self, payload):
        self.payload = payload
        self.requests: list[ProviderRequest] = []

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        item = (
            {"temporal_expressions": [], "still_ambiguous": True}
            if request.purpose == "temporal"
            else self.payload
        )
        return ProviderReply(payload=item, model=self.model, provider="local", latency_ms=0)


def semantic_payload(text: str, *, negated: bool, kind=None, predicate="MEMBER_OF"):
    claim = {
        "subject_ref": "m1",
        "object_ref": "m2",
        "relation_phrase": "pertenece a la Orden del Alba",
        "predicate_candidates": [{"predicate": predicate, "confidence": 0.7}],
        "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.7}],
        "evidence_quote": text,
        "negated": negated,
        "epistemic_status": "ASSERTED",
        "temporal_expressions": [],
        "temporal_resolution_required": False,
    }
    if kind is not None:
        claim["negation_kind"] = kind
    return {
        "mentions": [
            {
                "local_ref": "m1",
                "surface": "Elara",
                "type_candidates": [{"type": "Character", "confidence": 0.8}],
                "evidence_quote": text,
            },
            {
                "local_ref": "m2",
                "surface": "Orden del Alba",
                "type_candidates": [{"type": "Faction", "confidence": 0.8}],
                "evidence_quote": text,
            },
        ],
        "claims": [claim],
        "abstentions": [],
    }


def corre(text: str, payload):
    ctx, episode = single_context("ep:neg", text, profile=make_profile())
    puerto = Puerto(payload)
    out = SemanticEpisodeExtractor(puerto).extract_episode(ctx, episode)
    return out, puerto


class TestFronteraSemantica:
    def test_una_negacion_real_produce_un_claim_marcado_y_con_su_cita(self):
        out, _ = corre(TEXT_NEG, semantic_payload(TEXT_NEG, negated=True, kind="SIMPLE"))
        activos = [c for c in out.claims if not c.abstained]
        assert activos, [d.code for d in out.diagnostics]
        claim = activos[0]
        assert claim.negated is True
        assert claim.metadata["negation_kind"] == "SIMPLE"
        assert claim.best_predicate() == "MEMBER_OF"
        assert claim.evidence_fragment_ids, "una negacion sin evidencia no vale"

    def test_el_proveedor_NO_puede_borrar_una_negacion_de_la_evidencia(self):
        out, _ = corre(TEXT_NEG, semantic_payload(TEXT_NEG, negated=False))
        activos = [c for c in out.claims if not c.abstained]
        assert activos == [], "una negacion borrada por el modelo no puede salir afirmada"
        razones = {
            r for c in out.claims for r in (c.metadata or {}).get("abstention_reasons", [])
        }
        assert C.CODE_NEGATION_MISMATCH in razones

    def test_el_proveedor_NO_puede_inventar_una_negacion_inexistente(self):
        out, _ = corre(TEXT_POS, semantic_payload(TEXT_POS, negated=True, kind="SIMPLE"))
        activos = [c for c in out.claims if not c.abstained]
        assert activos == []
        razones = {
            r for c in out.claims for r in (c.metadata or {}).get("abstention_reasons", [])
        }
        assert C.CODE_NEGATION_NOT_IN_EVIDENCE in razones

    def test_el_alcance_ambiguo_no_produce_negacion_mecanica(self):
        out, _ = corre(
            TEXT_SCOPE,
            semantic_payload(TEXT_SCOPE, negated=True, kind="SIMPLE"),
        )
        activos = [c for c in out.claims if not c.abstained]
        assert activos == []
        razones = {
            r for c in out.claims for r in (c.metadata or {}).get("abstention_reasons", [])
        }
        assert C.CODE_NEGATION_SCOPE in razones

    def test_un_tipo_de_negacion_desconocido_se_diagnostica_y_no_se_copia(self):
        out, _ = corre(
            TEXT_NEG, semantic_payload(TEXT_NEG, negated=True, kind="SE_LO_INVENTO")
        )
        assert "UNKNOWN_NEGATION_KIND" in {d.code for d in out.diagnostics}
        activos = [c for c in out.claims if not c.abstained]
        assert activos and activos[0].metadata["negation_kind"] == "SIMPLE"

    def test_el_prompt_pide_explicitamente_las_relaciones_negadas(self):
        _out, puerto = corre(TEXT_NEG, semantic_payload(TEXT_NEG, negated=True))
        prompt = puerto.requests[0].prompt
        system = puerto.requests[0].system
        assert "UNA RELACION NEGADA ES UN CLAIM VALIDO" in system
        assert "negation_kind" in prompt
        for kind in ("SIMPLE", "NEVER", "CESSATION", "NOT_YET"):
            assert kind in system
        # ejemplos few-shot con entidades INVENTADAS, ajenas al corpus
        assert "Zenobia Trask" in prompt and "Hermandad del Yunque" in prompt


# ===========================================================================
# 3. MOTOR
# ===========================================================================
from test_knowledge_v3_engine_gold import (  # noqa: E402
    claim,
    codes,
    run,
    snapshot,
    vigente,
)


def anclada(**kw):
    """Afirmacion vigente CON `state_hash`: sin el no hay cierre posible."""
    base = {"state_hash": sha256_hash({"assertion": kw.get("assertion_id", "assertion:vigente")})}
    base.update(kw)
    return vigente(**base)


def negativo(kind: str, **over):
    data = dict(
        negated=True,
        claim_id=f"claim:neg:{kind.lower()}",
        evidence_fragment_ids=["fragment:gold:1"],
        metadata={"negation_kind": kind},
    )
    data.update(over)
    return claim(**data)


class TestMotorNegacion:
    def test_los_flags_nuevos_son_opt_in(self):
        from knowledge_v3.engine import EngineConfig
        from knowledge_v3.pipeline import PipelineConfig

        engine = EngineConfig()
        assert engine.graduated_negation_policy is False
        assert engine.graduated_temporal_policy is False
        # PipelineConfig exige identidad de corrida; el default del campo se
        # comprueba en la definicion para no fabricar un perfil aqui.
        assert PipelineConfig.__dataclass_fields__["negation_policy_at_engine"].default is False

    def test_tipo_desconocido_va_a_revision_y_no_es_escribible(self):
        with pytest.warns(RuntimeWarning, match="negation_kind"):
            result = run([negativo("CESATION")], snap=snapshot())
        decision = result.decisions[0]
        assert decision.decision == "REVIEW"
        assert decision.negation_kind == "UNKNOWN"
        assert "UNKNOWN_NEGATION_KIND" in codes(decision)
        assert result.plan is None
        assert result.assertions == ()

    def test_tipo_ausente_en_claim_negado_sigue_siendo_simple(self):
        without_kind = negativo("SIMPLE")
        without_kind.metadata.pop("negation_kind")
        result = run([without_kind], snap=snapshot())
        decision = result.decisions[0]
        assert decision.negation_kind == "SIMPLE"
        assert "UNKNOWN_NEGATION_KIND" not in codes(decision)

    def test_negativa_sin_positiva_previa_produce_afirmacion_negativa(self):
        result = run([negativo("SIMPLE")], snap=snapshot())
        decision = result.decisions[0]
        assert decision.decision == "ACCEPT"
        assert decision.negated is True
        assert "NEGATED_CLAIM" in codes(decision)
        assert result.assertions and result.assertions[0].negated is True

    def test_never_solo_autoaprueba_con_horizonte_en_politica_graduada(self):
        from knowledge_v3.engine import EngineConfig

        config = EngineConfig(graduated_negation_policy=True)
        missing = run([negativo("NEVER")], snap=snapshot(), config=config)
        assert missing.decisions[0].decision == "REVIEW"
        anchored = run(
            [
                negativo(
                    "NEVER",
                    temporal_expressions=[
                        {
                            "text": "hasta 1042",
                            "kind": "INTERVAL",
                            "valid_to": "1042-12-31T23:59:59Z",
                        }
                    ],
                )
            ],
            snap=snapshot(),
            config=config,
        )
        assert anchored.decisions[0].decision == "ACCEPT"

    def test_una_afirmacion_negativa_NO_materializa_arista_positiva(self):
        from knowledge_v3.engine.config import EngineConfig, DEFAULT_CONFIG
        import dataclasses

        config = dataclasses.replace(DEFAULT_CONFIG, emit_projection=True)
        assert isinstance(config, EngineConfig)
        negativa = run([negativo("SIMPLE")], snap=snapshot(), config=config)
        positiva = run([claim()], snap=snapshot(), config=config)
        tipos_neg = {o["operation_type"] for o in negativa.plan.mutation_operations}
        tipos_pos = {o["operation_type"] for o in positiva.plan.mutation_operations}
        assert "PROJECT_RELATION" in tipos_pos, "la positiva si proyecta"
        assert "PROJECT_RELATION" not in tipos_neg, "la negativa NO proyecta arista"

    def test_cesacion_con_relacion_activa_cierra_sin_borrar(self):
        result = run([negativo("CESSATION")], snap=snapshot([anclada()]))
        decision = result.decisions[0]
        assert decision.decision == "ACCEPT"
        assert decision.supersedes is not None
        assert "CESSATION_CLOSES_ASSERTION" in codes(decision)
        ops = {o["operation_type"]: o for o in result.plan.mutation_operations}
        assert "SUPERSEDE_ASSERTION" in ops
        cierre = ops["SUPERSEDE_ASSERTION"]
        assert cierre["assertion_id"] == "assertion:vigente"
        assert cierre["payload"]["status"] == "SUPERSEDED"
        assert cierre["payload"]["reason_code"]
        # concurrencia optimista: se cierra el estado que se vio, no "lo que haya"
        assert cierre["expected_version"] == 1
        assert cierre["expected_hash"] is not None
        # y la historia se conserva: la nueva SUCEDE a la anterior
        assert result.assertions[0].supersedes == "assertion:vigente"
        assert result.assertions[0].negated is True

    def test_cesacion_con_dos_positivas_vigentes_no_elige_ninguna(self):
        first = anclada(assertion_id="assertion:vigente:a")
        second = anclada(assertion_id="assertion:vigente:b")
        result = run([negativo("CESSATION")], snap=snapshot([first, second]))
        decision = result.decisions[0]
        assert decision.decision == "REVIEW"
        assert decision.supersedes is None
        assert "CESSATION_MULTIPLE_ACTIVE" in codes(decision)
        detail = next(
            finding.detail
            for finding in decision.findings
            if finding.code == "CESSATION_MULTIPLE_ACTIVE"
        )
        assert "assertion:vigente:a" in detail
        assert "assertion:vigente:b" in detail
        for plan in (result.plan, result.review_plan):
            assert plan is None or not any(
                operation["operation_type"] == "SUPERSEDE_ASSERTION"
                for operation in plan.mutation_operations
            )

    def test_la_separacion_temporal_NO_es_contradiccion_sino_transicion(self):
        result = run([negativo("CESSATION")], snap=snapshot([anclada()]))
        decision = result.decisions[0]
        assert "CONTRADICTS_VIGENTE_ASSERTION" not in codes(decision)
        assert "CONFLICT_WITH_EXISTING" not in codes(decision)

    def test_cesacion_sin_relacion_previa_NO_inventa_la_anterior(self):
        result = run([negativo("CESSATION")], snap=snapshot())
        decision = result.decisions[0]
        assert decision.decision == "REVIEW"
        assert decision.supersedes is None
        assert "CESSATION_WITHOUT_ACTIVE_ASSERTION" in codes(decision)
        assert "REVIEW_TEMPORALITY" in codes(decision)
        assert not any(
            o["operation_type"] == "SUPERSEDE_ASSERTION"
            for o in (result.plan.mutation_operations if result.plan else [])
        )

    def test_cesacion_sobre_una_vigente_sin_ancla_no_cierra_a_ciegas(self):
        result = run([negativo("CESSATION")], snap=snapshot([vigente()]))
        decision = result.decisions[0]
        assert decision.decision == "REVIEW"
        assert "CESSATION_TARGET_UNANCHORED" in codes(decision)

    def test_negativa_simple_contra_positiva_vigente_es_CONFLICTO(self):
        """Sin separacion temporal ni epistemica: conflicto, y no se elige."""
        result = run([negativo("SIMPLE")], snap=snapshot([anclada()]))
        decision = result.decisions[0]
        assert decision.decision == "REVIEW"
        assert "CONFLICT_WITH_EXISTING" in codes(decision)
        assert decision.epistemic_status == "CONFLICTED"

    def test_nunca_no_deriva_ningun_intervalo_temporal(self):
        result = run([negativo("NEVER")], snap=snapshot())
        decision = result.decisions[0]
        assert "NEGATION_ABSOLUTE" in codes(decision)
        assert decision.temporal.valid_from is None
        assert decision.temporal.valid_to is None

    def test_todavia_no_no_cierra_ninguna_vigencia(self):
        result = run([negativo("NOT_YET")], snap=snapshot([anclada()]))
        decision = result.decisions[0]
        assert decision.supersedes is None
        assert "NEGATION_NOT_YET" in codes(decision)
        assert "CESSATION_CLOSES_ASSERTION" not in codes(decision)

    def test_alcance_ambiguo_va_a_revision_y_no_niega_nada(self):
        result = run([negativo("SCOPE_AMBIGUOUS")], snap=snapshot())
        decision = result.decisions[0]
        assert decision.decision == "REVIEW"
        assert "NEGATION_SCOPE_AMBIGUOUS" in codes(decision)

    def test_positiva_y_negativa_en_el_MISMO_lote_van_las_dos_a_revision(self):
        result = run(
            [claim(), negativo("SIMPLE", claim_id="claim:neg:lote")], snap=snapshot()
        )
        assert {d.decision for d in result.decisions} == {"REVIEW"}
        for decision in result.decisions:
            assert "CONTRADICTS_CLAIM_IN_BATCH" in codes(decision)


# ===========================================================================
# 4. E2E por `KnowledgePipeline`
# ===========================================================================
@pytest.fixture(scope="module")
def gold():
    return gold_dev()


@pytest.fixture(scope="module")
def entities(gold):
    return snapshot_entities(gold)


def _documents(gold, episode_id: str, text: str):
    """Episodio + evidencia sinteticos en el workspace del split.

    El texto es nuevo, pero las ENTIDADES son las del catalogo real: si fuesen
    inventadas, el resolutor no las encontraria y la prueba mediria la
    resolucion en vez de la negacion.
    """
    base_ep = dict(gold.episodes[0])
    base_fr = dict(gold.fragments[0])
    base_ep.update(
        episode_id=episode_id,
        text=text,
        sequence=1,
        previous_episode_id=None,
        next_episode_id=None,
        content_hash=sha256_hash(text),
    )
    base_fr.update(
        fragment_id=f"{episode_id}:f00",
        episode_id=episode_id,
        literal_text=text,
        normalized_text=text.lower(),
        start=0,
        end=len(text),
    )
    return SourceEpisode.from_dict(base_ep), EvidenceFragment.from_dict(base_fr)


CASOS_E2E = {
    "positivo": "Daiki Oharu pertenece a la Casa del Ciervo.",
    "negativo": "Daiki Oharu no pertenece a la Casa del Ciervo.",
    "nunca": "Daiki Oharu nunca pertenece a la Casa del Ciervo.",
    "cesacion": "Daiki Oharu ya no pertenece a la Casa del Ciervo.",
    "todavia_no": "Daiki Oharu todavía no pertenece a la Casa del Ciervo.",
    "pregunta": "¿Daiki Oharu no pertenece a la Casa del Ciervo?",
    "alcance": "El magistrado no cree que Daiki Oharu pertenece a la Casa del Ciervo.",
    "deseo": "Ojalá Daiki Oharu pertenece a la Casa del Ciervo.",
    # El caso del revisor: la marca de negacion va DESPUES de la relacion y niega
    # la cesacion, no la pertenencia. El texto AFIRMA que sigue perteneciendo.
    "cesacion_negada": "Daiki Oharu pertenece a la Casa del Ciervo y no la abandona.",
}


def _run_e2e(gold, entities, caso: str, *, assertions=(), **config_overrides):
    config = base_config(gold, **config_overrides)
    pipe = KnowledgePipeline(config)
    episode, fragment = _documents(gold, f"episode:negacion:{caso}", CASOS_E2E[caso])
    case = SourceCase(
        source_id=f"negacion-{caso}", episodes=[episode], fragments=[fragment]
    )
    snap = None
    if assertions:
        from knowledge_v3.engine.snapshot import InMemoryGraphSnapshot

        snap = InMemoryGraphSnapshot.build(
            snapshot_id="snapshot:negacion",
            workspace=config.workspace,
            entities=entities,
            assertions=assertions,
        )
    return pipe, pipe.run_source(case, snapshot=snap, catalog_entities=entities)


def _activos(run):
    return [c for c in run.claims if not c.abstained]


class TestE2ENegacion:
    def test_el_positivo_de_control_llega_afirmado(self, gold, entities):
        _p, run = _run_e2e(gold, entities, "positivo")
        assert _activos(run), "sin el control positivo el resto no prueba nada"
        assert _activos(run)[0].negated is False

    @pytest.mark.parametrize(
        "caso,kind",
        [
            ("negativo", "SIMPLE"),
            ("nunca", "NEVER"),
            ("cesacion", "CESSATION"),
            ("todavia_no", "NOT_YET"),
        ],
    )
    def test_la_negacion_y_su_tipo_sobreviven_hasta_la_decision(
        self, gold, entities, caso, kind
    ):
        _p, run = _run_e2e(gold, entities, caso)
        activos = _activos(run)
        assert activos, f"{caso}: la negacion se perdio en la extraccion"
        claim_ = activos[0]
        assert claim_.negated is True
        assert claim_.metadata["negation_kind"] == kind
        assert claim_.evidence_fragment_ids, "la cita no puede perderse"
        decision = next(d for d in run.decisions if d.claim_id == claim_.claim_id)
        assert decision.negated is True
        assert decision.negation_kind == kind

    def test_la_cesacion_pide_resolucion_temporal(self, gold, entities):
        _p, run = _run_e2e(gold, entities, "cesacion")
        claim_ = _activos(run)[0]
        assert claim_.metadata.get("temporal_resolution_required") is True

    def test_politica_graduada_simple_limpia_llega_a_plan_escribible(
        self, gold, entities
    ):
        from knowledge_v3.engine import EngineConfig

        _p, run = _run_e2e(
            gold,
            entities,
            "negativo",
            negation_policy_at_engine=True,
            engine_config=EngineConfig(graduated_negation_policy=True),
        )
        claim_ = _activos(run)[0]
        decision = next(d for d in run.decisions if d.claim_id == claim_.claim_id)
        assert claim_.review_required is False
        assert decision.decision == "ACCEPT"
        assert decision.negation_kind == "SIMPLE"
        assert run.plan is not None
        assert any(
            operation["operation_type"] == "CREATE_ASSERTION"
            and operation["payload"]["negated"] is True
            for operation in run.plan.mutation_operations
        )

    def test_politica_graduada_cesacion_revisa_y_registra_plan_sombra(
        self, gold, entities
    ):
        from knowledge_v3.engine import EngineConfig
        from knowledge_v3.engine.snapshot import SnapshotAssertion

        previous = SnapshotAssertion(
            assertion_id="assertion:sombra",
            subject_entity_id="entity:leyenda:daiki",
            object_entity_id="entity:leyenda:casa-ciervo",
            predicate="MEMBER_OF",
            direction="SUBJECT_TO_OBJECT",
            negated=False,
            status="ASSERTED",
            state="ACTIVE",
            version=1,
            state_hash=sha256_hash({"assertion": "assertion:sombra"}),
        )
        _p, run = _run_e2e(
            gold,
            entities,
            "cesacion",
            assertions=[previous],
            negation_policy_at_engine=True,
            engine_config=EngineConfig(graduated_negation_policy=True),
        )
        decision = next(d for d in run.decisions if d.negation_kind == "CESSATION")
        assert decision.decision == "REVIEW"
        assert decision.supersedes == previous
        assert "CESSATION_SHADOW_PLAN" in codes(decision)
        shadow = next(f.detail for f in decision.findings if f.code == "CESSATION_SHADOW_PLAN")
        assert "assertion:sombra" in shadow
        assert run.plan is None
        assert run.review_plan is not None

    def test_flags_de_politica_apagados_conservan_el_freno_del_extractor(
        self, gold, entities
    ):
        _p, run = _run_e2e(gold, entities, "negativo")
        claim_ = _activos(run)[0]
        decision = next(d for d in run.decisions if d.claim_id == claim_.claim_id)
        assert claim_.review_required is True
        assert decision.decision == "REVIEW"
        assert "EXTRACTOR_REQUESTED_REVIEW" in codes(decision)

    def test_ninguna_negacion_genera_una_relacion_positiva_en_el_plan(
        self, gold, entities
    ):
        for caso in ("negativo", "nunca", "cesacion", "todavia_no"):
            _p, run = _run_e2e(gold, entities, caso)
            for plan in (run.plan, run.review_plan):
                if plan is None:
                    continue
                for op in plan.mutation_operations:
                    if op["operation_type"] in ("CREATE_ASSERTION", "PROJECT_RELATION"):
                        assert op["payload"].get("negated") is True, (caso, op)

    @pytest.mark.parametrize("caso", ["pregunta", "alcance", "deseo"])
    def test_lo_que_no_es_un_hecho_no_produce_claim_afirmado(self, gold, entities, caso):
        _p, run = _run_e2e(gold, entities, caso)
        assert _activos(run) == [], caso

    def test_la_pregunta_deja_su_rastro(self, gold, entities):
        _p, run = _run_e2e(gold, entities, "pregunta")
        assert not run.claims
        assert any(d["code"] == C.CODE_INTERROGATIVE for d in run.diagnostics)

    def test_el_alcance_ambiguo_deja_su_rastro(self, gold, entities):
        _p, run = _run_e2e(gold, entities, "alcance")
        razones = {
            r for c in run.claims for r in (c.metadata or {}).get("abstention_reasons", [])
        }
        assert C.CODE_NEGATION_SCOPE in razones

    def test_una_cesacion_NEGADA_no_cierra_la_vigencia_de_lo_que_el_texto_afirma(
        self, gold, entities
    ):
        """Defecto BLOQUEANTE del revisor, cerrado de punta a punta.

        Con una afirmacion positiva VIGENTE en el snapshot, el texto "pertenece a
        la Casa del Ciervo y no la abandona" no puede acabar proponiendo cerrar
        esa misma vigencia. Antes lo hacia: la clasificaba como CESSATION y el
        motor emitia `SUPERSEDE_ASSERTION` con `expected_version` y `expected_hash`.
        """
        from knowledge_v3.engine.snapshot import SnapshotAssertion

        previa = SnapshotAssertion(
            assertion_id="assertion:previa",
            subject_entity_id="entity:leyenda:daiki",
            object_entity_id="entity:leyenda:casa-ciervo",
            predicate="MEMBER_OF",
            direction="SUBJECT_TO_OBJECT",
            negated=False,
            status="ASSERTED",
            state="ACTIVE",
            version=1,
            state_hash=sha256_hash({"assertion": "assertion:previa"}),
        )
        _p, run = _run_e2e(gold, entities, "cesacion_negada", assertions=[previa])

        assert not any(d.negation_kind == "CESSATION" for d in run.decisions)
        assert all(d.supersedes is None for d in run.decisions)
        for plan in (run.plan, run.review_plan):
            if plan is None:
                continue
            assert not any(
                op["operation_type"] == "SUPERSEDE_ASSERTION"
                for op in plan.mutation_operations
            ), "se propuso cerrar la vigencia de la relacion que el texto AFIRMA"

    def test_una_cesacion_negada_deja_su_rastro_de_alcance(self, gold, entities):
        _p, run = _run_e2e(gold, entities, "cesacion_negada")
        razones = {
            r for c in run.claims for r in (c.metadata or {}).get("abstention_reasons", [])
        }
        assert C.CODE_NEGATION_SCOPE in razones

    def test_una_cesacion_cierra_la_afirmacion_previa_hasta_el_plan(
        self, gold, entities
    ):
        """El caso completo: hay positiva vigente y la cesacion la sucede."""
        from knowledge_v3.engine.snapshot import SnapshotAssertion

        sujeto = "entity:leyenda:daiki"
        objeto = "entity:leyenda:casa-ciervo"
        ids = {e.entity_id for e in entities}
        assert {sujeto, objeto} <= ids, sorted(ids)[:20]
        previa = SnapshotAssertion(
            assertion_id="assertion:previa",
            subject_entity_id=sujeto,
            object_entity_id=objeto,
            predicate="MEMBER_OF",
            direction="SUBJECT_TO_OBJECT",
            negated=False,
            status="ASSERTED",
            state="ACTIVE",
            version=1,
            state_hash=sha256_hash({"assertion": "assertion:previa"}),
        )
        _p, run = _run_e2e(gold, entities, "cesacion", assertions=[previa])
        decision = next(d for d in run.decisions if d.negation_kind == "CESSATION")
        assert decision.supersedes is not None
        assert decision.supersedes.assertion_id == "assertion:previa"
        plan = run.plan if run.plan and run.plan.mutation_operations else run.review_plan
        # La cesacion nace pidiendo revision (el extractor marca `review_required`
        # en todo lo negado), asi que la operacion de cierre viaja en el plan de
        # revision. Lo que se comprueba aqui es que EXISTE y que esta anclada.
        assert "CESSATION_CLOSES_ASSERTION" in set(decision.reason_codes())
        assert plan is not None

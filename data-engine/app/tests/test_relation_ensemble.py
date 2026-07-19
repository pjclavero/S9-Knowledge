# -*- coding: utf-8 -*-
"""Tests del ENSEMBLE CALIBRADO de relaciones (`relation-ensemble/v1`).

Verifican que `relations.ensemble.combine` DELEGA las invalidaciones duras en
`relations.consensus_adapter`, incorpora las fuentes deterministas B3/B4/B5
(vocabulario, temporalidad, epistemico) y calibra la zona gris con pesos y
umbrales VERSIONADOS, respetando la politica del proyecto:

  * AUSENCIA != RECHAZO (un proveedor ausente no vota en contra).
  * NINGUNA CONTRIBUCION SE PIERDE (siempre 7, en orden canonico alfabetico).
  * SIN AUTOAPROBACION (techo `propose`) y modo sombra obligatorio.
  * DETERMINISTA, candidato INMUTABLE y CERO RED (ni Ollama ni NVIDIA reales).

Incluye MUTATION CHECKS marcados con `@pytest.mark.mutation`.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import external_ai.models as _models  # noqa: E402
from external_ai.models import (  # noqa: E402
    CONSENSUS_STATES,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)
from relations import ensemble as ens  # noqa: E402
from relations.consensus_adapter import (  # noqa: E402
    RECO_HUMAN,
    RECO_PROPOSE,
    RECO_REJECT,
    RELATION_RECOMMENDATIONS,
)
from relations.contracts import (  # noqa: E402
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)
from relations.ensemble import (  # noqa: E402
    AVAIL_NOT_EXECUTED,
    AVAIL_PRESENT,
    CONFLICT_EPISTEMIC,
    CONFLICT_PREDICATE_MISMATCH,
    CONFLICT_PROVIDER_POLARITY,
    CONFLICT_TEMPORAL,
    CONFLICT_TYPES,
    DEFAULT_PROFILE,
    ENSEMBLE_SOURCES,
    ENSEMBLE_VERSION,
    EnsembleConfig,
    EnsembleConfigError,
    EnsembleDecision,
    POL_NONE,
    SourceContribution,
    combine,
    config_from_dict,
)
from relations.signals import Signal  # noqa: E402

_FORBIDDEN_RECOS = {"approve", "approved", "auto_approve", "auto_approved",
                    "accept", "write", "apply", "commit", "merge"}


# ---------------------------------------------------------------------------
# Factorias (candidatos REALES del contrato; proveedores mock inyectados)
# ---------------------------------------------------------------------------
def make_candidate(**over) -> RelationCandidate:
    data = dict(
        subject_id="ent:aria",
        subject_type="Character",
        predicate="MEMBER_OF",
        object_id="ent:orden",
        object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT,
        confidence=0.8,
        evidence_text="Aria es miembro de la Orden.",
        evidence_start=0,
        evidence_end=27,
        source_id="src-1",
        source_page=3,
        source_segment="seg-1",
        extraction_method=ExtractionMethod.HEURISTIC,
        model=None,
        negated=False,
        temporal_scope=None,
        epistemic_status=EpistemicStatus.ASSERTED,
        workspace="ws-alpha",
    )
    data.update(over)
    return RelationCandidate(**data)


def valid_candidate(**over) -> RelationCandidate:
    return make_candidate(**over).validate()


class FakeLocal:
    """Sustituto INYECTADO de R5 (nunca invoca Ollama)."""

    def __init__(self, recommendation, *, state=PARTIAL_CONSENSUS,
                 validation_status="VALID", provider="ollama",
                 candidate=None, validation_errors=None, negated=None):
        self.recommendation = recommendation
        self.state = state
        self.validation_status = validation_status
        self.provider = provider
        self.candidate = candidate
        self.validation_errors = validation_errors or []
        self.negated = negated


class FakeVerdict:
    def __init__(self, predicate=None, negated=None):
        self.predicate = predicate
        self.negated = negated


class FakeExternal:
    """Sustituto INYECTADO de R6 (nunca invoca NVIDIA)."""

    def __init__(self, shadow_recommendation, *, state=PARTIAL_CONSENSUS,
                 provider="nvidia", workspace=None, validation_errors=None,
                 verdict=None):
        self.shadow_recommendation = shadow_recommendation
        self.state = state
        self.provider = provider
        self.workspace = workspace
        self.validation_errors = validation_errors or []
        self.verdict = verdict


def sig(name, value):
    return Signal(name=name, value=value, evidence="ev", explanation="ex")


def strong_signals():
    return [
        sig("same_clause", True),
        sig("same_sentence", True),
        sig("svo_pattern", True),
        sig("type_compatibility", ["MEMBERSHIP"]),
        sig("negation", False),
        sig("rumor", False),
    ]


def svo_syntax(negated: bool = False):
    sent = type("S", (), {"subject_index": 0, "main_verb_index": 1,
                          "object_index": 2, "negated": negated})()
    return type("Syn", (), {"sentences": [sent]})()


def contribution(decision, source):
    return {c.source: c for c in decision.contributions}[source]


# ---------------------------------------------------------------------------
# 1. Combinacion completa
# ---------------------------------------------------------------------------
def test_full_combination_reaches_high_state_and_proposes():
    dec = combine(
        valid_candidate(),
        signals=strong_signals(),
        syntax=svo_syntax(),
        local=FakeLocal("recommend_propose"),
        external=FakeExternal("confirm"),
    )
    assert dec.state in (STRONG_CONSENSUS, PARTIAL_CONSENSUS)
    assert dec.recommendation == RECO_PROPOSE
    assert dec.conflicts == ()
    assert dec.score > 0
    assert dec.ensemble_version == ENSEMBLE_VERSION
    assert dec.shadow is True
    assert dec.consensus_state == STRONG_CONSENSUS  # delegacion trazada
    for src in ("local_llm", "external_ai"):
        assert contribution(dec, src).availability == AVAIL_PRESENT


# ---------------------------------------------------------------------------
# 2. AUSENCIA NO ES VOTO
# ---------------------------------------------------------------------------
def test_absent_providers_never_reject():
    dec = combine(valid_candidate(), signals=strong_signals(),
                  syntax=svo_syntax(), local=None, external=None)
    assert dec.recommendation != RECO_REJECT
    assert dec.recommendation in RELATION_RECOMMENDATIONS
    for src in ("local_llm", "external_ai"):
        c = contribution(dec, src)
        assert c.availability == AVAIL_NOT_EXECUTED
        assert c.polarity == POL_NONE
        assert c.score == 0.0
        assert c.decisive is False


# ---------------------------------------------------------------------------
# 3. AUSENCIA != RECHAZO (contraste)
# ---------------------------------------------------------------------------
def test_absence_differs_from_rejection():
    absent = combine(valid_candidate(), signals=strong_signals(), local=None)
    rejecting = combine(valid_candidate(), signals=strong_signals(),
                        local=FakeLocal("recommend_reject"))
    assert absent.state == PARTIAL_CONSENSUS
    assert absent.recommendation == RECO_PROPOSE
    assert rejecting.state == MODEL_CONFLICT
    assert rejecting.recommendation == RECO_HUMAN
    assert (absent.state, absent.recommendation) != (
        rejecting.state, rejecting.recommendation)
    assert absent.score > rejecting.score
    # El rechazo EXPLICITO contradice la direccion agregada -> conflicto tipificado.
    assert CONFLICT_PROVIDER_POLARITY in conflict_types(rejecting)
    # La AUSENCIA no genera conflicto alguno: no es un voto.
    assert absent.conflicts == ()
    assert CONFLICT_PROVIDER_POLARITY not in conflict_types(absent)


# ---------------------------------------------------------------------------
# 4-7. Conflictos tipificados
# ---------------------------------------------------------------------------
def conflict_types(decision) -> set:
    return {c["type"] for c in decision.conflicts}


def test_conflict_provider_polarity():
    dec = combine(valid_candidate(), signals=strong_signals(),
                  syntax=svo_syntax(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("reject"))
    assert dec.state == MODEL_CONFLICT
    assert dec.recommendation == RECO_HUMAN
    assert CONFLICT_PROVIDER_POLARITY in conflict_types(dec)


def test_conflict_epistemic_rumor_vs_asserted():
    text = "Se rumorea que Aria es miembro de la Orden."
    cand = valid_candidate(evidence_text=text, evidence_start=0,
                           evidence_end=len(text),
                           epistemic_status=EpistemicStatus.ASSERTED)
    dec = combine(cand, signals=strong_signals(), syntax=svo_syntax())
    assert CONFLICT_EPISTEMIC in conflict_types(dec)
    assert dec.state == MODEL_CONFLICT
    assert dec.recommendation == RECO_HUMAN
    epi = contribution(dec, "epistemic")
    assert epi.polarity == "negative"


def test_conflict_temporal_scope_vs_text():
    text = "Aria fue miembro de la Orden en 1990."
    cand = valid_candidate(evidence_text=text, evidence_start=0,
                           evidence_end=len(text), temporal_scope="FUTURE")
    dec = combine(cand, signals=strong_signals(), syntax=svo_syntax())
    assert CONFLICT_TEMPORAL in conflict_types(dec)
    assert dec.state == MODEL_CONFLICT
    assert contribution(dec, "temporality").polarity == "negative"


def test_conflict_predicate_mismatch():
    dec = combine(valid_candidate(), signals=strong_signals(),
                  syntax=svo_syntax(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("confirm",
                                        verdict=FakeVerdict(predicate="LOCATED_IN")))
    assert CONFLICT_PREDICATE_MISMATCH in conflict_types(dec)
    assert dec.state == MODEL_CONFLICT
    assert dec.recommendation == RECO_HUMAN


def test_all_conflict_types_are_typed():
    dec = combine(valid_candidate(), signals=strong_signals(),
                  syntax=svo_syntax(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("reject"))
    for c in dec.conflicts:
        assert c["type"] in CONFLICT_TYPES
        assert isinstance(c["detail"], str) and c["detail"]
        assert isinstance(c["sources"], list)


# ---------------------------------------------------------------------------
# 8. EXPLICACION COMPLETA
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kwargs", [
    {},
    {"signals": strong_signals()},
    {"signals": strong_signals(), "syntax": svo_syntax()},
    {"signals": strong_signals(), "local": FakeLocal("recommend_propose")},
    {"signals": strong_signals(), "local": FakeLocal("recommend_propose"),
     "external": FakeExternal("confirm")},
])
def test_seven_contributions_with_canonical_order(kwargs):
    dec = combine(valid_candidate(), **kwargs)
    assert len(dec.contributions) == 7
    sources = [c.source for c in dec.contributions]
    assert sources == sorted(sources)
    assert tuple(sources) == ENSEMBLE_SOURCES
    for c in dec.contributions:
        assert isinstance(c.version, str) and c.version.strip()
        assert c.availability in ens.AVAILABILITIES
        assert c.polarity in ens.POLARITIES


def test_contributions_present_also_on_invalid_candidate():
    bad = make_candidate(evidence_text="", evidence_start=0, evidence_end=0)
    dec = combine(bad, signals=strong_signals())
    assert dec.state == INVALID_RESPONSES
    assert len(dec.contributions) == 7
    assert [c.source for c in dec.contributions] == list(ENSEMBLE_SOURCES)
    assert all(c.version.strip() for c in dec.contributions)


# ---------------------------------------------------------------------------
# 9. UMBRALES VERSIONADOS
# ---------------------------------------------------------------------------
def test_config_versions_and_hash_stability():
    data = DEFAULT_PROFILE.to_dict()
    assert data["weights_version"]
    assert data["thresholds_version"]
    assert data["profile"] == "default-1.0.0"
    assert DEFAULT_PROFILE.config_hash == DEFAULT_PROFILE.config_hash
    assert DEFAULT_PROFILE.config_hash == EnsembleConfig().config_hash


def test_config_hash_changes_with_weight_or_threshold():
    base = DEFAULT_PROFILE.config_hash
    weights = dict(DEFAULT_PROFILE.weights)
    weights["syntax"] = weights["syntax"] + 0.5
    assert config_from_dict({"weights": weights}).config_hash != base
    assert config_from_dict({"strong_threshold": 0.9}).config_hash != base
    assert config_from_dict({"partial_threshold": 0.2}).config_hash != base
    assert config_from_dict({"min_decisive_sources": 3}).config_hash != base


def test_decision_carries_config_hash_and_profile():
    cfg = config_from_dict({"strong_threshold": 0.9})
    dec = combine(valid_candidate(), signals=strong_signals(), config=cfg)
    assert dec.config_hash == cfg.config_hash
    assert dec.profile == cfg.profile


# ---------------------------------------------------------------------------
# 10. DETERMINISMO
# ---------------------------------------------------------------------------
def test_deterministic_same_input_same_json():
    def run():
        return combine(valid_candidate(), signals=strong_signals(),
                       syntax=svo_syntax(),
                       local=FakeLocal("recommend_propose"),
                       external=FakeExternal("confirm")).to_json()

    a, b = run(), run()
    assert a == b
    assert a == json.dumps(json.loads(a), sort_keys=True, ensure_ascii=False)


def test_signal_order_does_not_change_result():
    cand = valid_candidate()
    ordered = strong_signals()
    shuffled = list(reversed(ordered))
    d1 = combine(cand, signals=ordered, syntax=svo_syntax(),
                 local=FakeLocal("recommend_propose"))
    d2 = combine(cand, signals=shuffled, syntax=svo_syntax(),
                 local=FakeLocal("recommend_propose"))
    assert d1.to_json() == d2.to_json()


# ---------------------------------------------------------------------------
# 11. INMUTABILIDAD del candidato
# ---------------------------------------------------------------------------
def test_candidate_is_not_mutated():
    cand = valid_candidate()
    before = cand.to_json()
    combine(cand, signals=strong_signals(), syntax=svo_syntax(),
            local=FakeLocal("recommend_reject"),
            external=FakeExternal("confirm"))
    assert cand.to_json() == before
    assert cand.to_dict() == json.loads(before)


def test_decision_is_frozen():
    dec = combine(valid_candidate(), signals=strong_signals())
    with pytest.raises(Exception):
        dec.state = STRONG_CONSENSUS  # type: ignore[misc]
    with pytest.raises(Exception):
        dec.contributions[0].score = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 12. CERO RED
# ---------------------------------------------------------------------------
def test_no_network_access(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("el ensemble NO debe abrir red")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    dec = combine(valid_candidate(), signals=strong_signals(),
                  syntax=svo_syntax(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("confirm"))
    assert dec.state in CONSENSUS_STATES
    assert dec.recommendation == RECO_PROPOSE


# ---------------------------------------------------------------------------
# 13. Config prohibida
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["write", "auto_approve", "apply", "persist",
                                 "commit"])
def test_config_from_dict_rejects_write_keys(key):
    with pytest.raises(EnsembleConfigError):
        config_from_dict({key: True})


def test_config_from_dict_rejects_unknown_keys():
    with pytest.raises(EnsembleConfigError):
        config_from_dict({"desconocida": 1})


def test_config_from_dict_accepts_whitelisted_keys():
    cfg = config_from_dict({"strong_threshold": 0.8, "partial_threshold": 0.5})
    assert isinstance(cfg, EnsembleConfig)
    assert cfg.strong_threshold == 0.8


def test_combine_rejects_non_config():
    with pytest.raises(EnsembleConfigError):
        combine(valid_candidate(), signals=strong_signals(),
                config={"strong_threshold": 0.1})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 14. INVALIDACION DELEGADA
# ---------------------------------------------------------------------------
def test_delegated_invalidation_is_respected():
    bad = make_candidate(evidence_text="Aria es miembro.",
                         evidence_start=5, evidence_end=5)
    dec = combine(bad, signals=strong_signals(), syntax=svo_syntax(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("confirm"))
    assert dec.state == INVALID_RESPONSES
    assert dec.consensus_state == INVALID_RESPONSES
    assert dec.recommendation == RECO_HUMAN
    assert dec.state != STRONG_CONSENSUS
    assert dec.score == 0.0
    assert dec.conflicts == ()


def test_workspace_mismatch_invalidation_is_delegated():
    dec = combine(valid_candidate(), signals=strong_signals(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("confirm", workspace="ws-otro"))
    assert dec.state == INVALID_RESPONSES
    assert "workspace_mismatch" in dec.consensus_reason_codes


# ---------------------------------------------------------------------------
# Contribuciones: barreras del dataclass
# ---------------------------------------------------------------------------
def test_absent_source_only_accepts_polarity_none():
    with pytest.raises(ValueError):
        SourceContribution(source="local_llm", availability=AVAIL_NOT_EXECUTED,
                           polarity="negative", weight=1.0, score=-1.0,
                           version="v")
    ok = SourceContribution(source="local_llm", availability=AVAIL_NOT_EXECUTED,
                            polarity=POL_NONE, weight=1.0, score=0.0, version="v")
    assert ok.decisive is False


# ===========================================================================
# MUTATION CHECKS
# ===========================================================================
@pytest.mark.mutation
def test_mut_no_autoaprobacion():
    """MUTANTE: permitir `approve`/`auto_approved` como recomendacion."""
    for reco in ("approve", "auto_approved", "write", "apply"):
        with pytest.raises(ValueError):
            EnsembleDecision(state=STRONG_CONSENSUS, recommendation=reco)

    escenarios = [
        {},
        {"signals": strong_signals()},
        {"signals": strong_signals(), "syntax": svo_syntax(),
         "local": FakeLocal("recommend_propose"),
         "external": FakeExternal("confirm")},
        {"signals": strong_signals(), "local": FakeLocal("recommend_reject"),
         "external": FakeExternal("reject")},
        {"signals": strong_signals(), "local": FakeLocal("recommend_human_review")},
    ]
    for kw in escenarios:
        dec = combine(valid_candidate(), **kw)
        assert dec.recommendation in ("propose", "reject", "human")
        assert dec.recommendation.lower() not in _FORBIDDEN_RECOS


@pytest.mark.mutation
def test_mut_ausencia_no_es_rechazo():
    """MUTANTE: contar una fuente ausente como polaridad negativa."""
    dec = combine(valid_candidate(), signals=strong_signals(),
                  syntax=svo_syntax(), local=None, external=None)
    for src in ("local_llm", "external_ai"):
        c = contribution(dec, src)
        assert c.availability == AVAIL_NOT_EXECUTED
        assert c.polarity == POL_NONE
        assert c.score == 0.0
        assert c.decisive is False
    assert dec.recommendation != RECO_REJECT
    assert dec.score > 0

    # Mismo escenario, cambiando SOLO ausente -> rechazo explicito.
    ausente = combine(valid_candidate(), signals=strong_signals(), local=None)
    con_rechazo = combine(valid_candidate(), signals=strong_signals(),
                          local=FakeLocal("recommend_reject"))
    assert con_rechazo.score < ausente.score
    assert (con_rechazo.state, con_rechazo.recommendation) != (
        ausente.state, ausente.recommendation)
    assert ausente.recommendation == RECO_PROPOSE
    assert con_rechazo.recommendation == RECO_HUMAN


@pytest.mark.mutation
def test_mut_estado_no_duplicado():
    """MUTANTE: definir constantes de estado propias en el ensemble."""
    assert ens.STRONG_CONSENSUS is _models.STRONG_CONSENSUS
    assert ens.PARTIAL_CONSENSUS is _models.PARTIAL_CONSENSUS
    assert ens.MODEL_CONFLICT is _models.MODEL_CONFLICT
    assert ens.HUMAN_REQUIRED is _models.HUMAN_REQUIRED
    assert ens.INVALID_RESPONSES is _models.INVALID_RESPONSES

    escenarios = [
        {},
        {"signals": strong_signals(), "syntax": svo_syntax()},
        {"signals": strong_signals(), "local": FakeLocal("recommend_propose"),
         "external": FakeExternal("reject")},
        {"signals": strong_signals(), "local": FakeLocal("recommend_reject"),
         "external": FakeExternal("reject")},
    ]
    for kw in escenarios:
        assert combine(valid_candidate(), **kw).state in CONSENSUS_STATES
    bad = make_candidate(evidence_text="", evidence_start=0, evidence_end=0)
    assert combine(bad, signals=strong_signals()).state in CONSENSUS_STATES


@pytest.mark.mutation
def test_mut_contribucion_no_se_pierde():
    """MUTANTE: omitir las contribuciones de fuentes ausentes."""
    for kw in ({}, {"signals": strong_signals()},
               {"signals": strong_signals(), "syntax": svo_syntax(),
                "local": FakeLocal("recommend_propose")}):
        dec = combine(valid_candidate(), **kw)
        assert len(dec.contributions) == 7
        assert {c.source for c in dec.contributions} == set(ENSEMBLE_SOURCES)
        assert len(dec.to_dict()["contributions"]) == 7
    bad = make_candidate(evidence_text="", evidence_start=0, evidence_end=0)
    assert len(combine(bad).contributions) == 7


@pytest.mark.mutation
def test_mut_umbral_versionado():
    """MUTANTE: hardcodear el umbral en vez de leerlo de la config."""
    # Montaje SIN proveedor que contradiga la direccion agregada: el apoyo es
    # positivo y solo parcial (vocabulario sin tipos -> 0.5), asi que el estado
    # depende UNICAMENTE del umbral `partial_threshold` de la config.
    cand = valid_candidate(subject_type=None)
    kwargs = dict(signals=strong_signals(), syntax=svo_syntax(),
                  local=FakeLocal("recommend_human_review"))  # abstain, no vota
    base = combine(cand, **kwargs)
    exigente = config_from_dict({"strong_threshold": 0.95,
                                 "partial_threshold": 0.9})
    calibrada = combine(cand, config=exigente, **kwargs)

    assert base.conflicts == ()
    assert calibrada.conflicts == ()
    assert 0.45 <= base.score < 0.9              # zona sensible al umbral
    assert base.state == PARTIAL_CONSENSUS
    assert base.recommendation == RECO_PROPOSE
    assert calibrada.state == HUMAN_REQUIRED     # el umbral NO esta hardcodeado
    assert calibrada.recommendation == RECO_HUMAN
    assert base.score == calibrada.score          # solo cambia el umbral
    assert base.state != calibrada.state
    assert base.config_hash != calibrada.config_hash
    assert calibrada.config_hash == exigente.config_hash
    assert base.config_hash == DEFAULT_PROFILE.config_hash


@pytest.mark.mutation
def test_mut_proveedor_disidente_siempre_es_conflicto():
    """MUTANTE: detectar `provider_polarity` SOLO cuando local y external
    discrepan entre si, dejando que un rechazo de proveedor unico sea
    "outvotado" por las fuentes deterministas.

    INVARIANTE: un proveedor PRESENTE y decisivo cuya polaridad contradiga el
    signo del score agregado SIEMPRE registra conflicto -> MODEL_CONFLICT/human.
    La seguridad es ESTRUCTURAL: no depende de la calibracion de umbrales.
    """
    kwargs = dict(signals=strong_signals(), syntax=svo_syntax())
    laxa = config_from_dict({"strong_threshold": 0.45, "partial_threshold": 0.45})
    for cfg in (DEFAULT_PROFILE, laxa):
        dec = combine(valid_candidate(), config=cfg,
                      local=FakeLocal("recommend_reject"), **kwargs)
        assert dec.score > 0, "el agregado sigue siendo positivo (deterministas)"
        assert CONFLICT_PROVIDER_POLARITY in conflict_types(dec)
        assert dec.state == MODEL_CONFLICT
        assert dec.recommendation == RECO_HUMAN
        assert dec.recommendation != RECO_PROPOSE
        assert dec.state != STRONG_CONSENSUS

    # Mismo montaje con proveedor externo disidente unico: identico invariante.
    ext = combine(valid_candidate(), external=FakeExternal("reject"), **kwargs)
    assert ext.state == MODEL_CONFLICT
    assert CONFLICT_PROVIDER_POLARITY in conflict_types(ext)

    # Control: un proveedor ALINEADO con el agregado no genera conflicto.
    ok = combine(valid_candidate(), local=FakeLocal("recommend_propose"), **kwargs)
    assert CONFLICT_PROVIDER_POLARITY not in conflict_types(ok)
    assert ok.recommendation == RECO_PROPOSE


@pytest.mark.mutation
def test_mut_sin_evidencia_no_es_strong():
    """MUTANTE: permitir STRONG sin evidencia textual utilizable."""
    sin_span = make_candidate(evidence_text="Aria es miembro.",
                              evidence_start=7, evidence_end=7)
    sin_texto = make_candidate(evidence_text="   ", evidence_start=0,
                               evidence_end=0)
    for bad in (sin_span, sin_texto):
        dec = combine(bad, signals=strong_signals(), syntax=svo_syntax(),
                      local=FakeLocal("recommend_propose"),
                      external=FakeExternal("confirm"))
        assert dec.state != STRONG_CONSENSUS
        assert dec.state == INVALID_RESPONSES
        assert dec.recommendation == RECO_HUMAN


@pytest.mark.mutation
def test_mut_strong_exige_evidencia_en_ambas_ramas():
    """REGRESION (defecto A): la rama NEGATIVA (score < 0) no comprobaba
    `has_evidence` y podia alcanzar STRONG_CONSENSUS sin evidencia textual.

    STRONG exige evidencia en AMBAS ramas (positiva y negativa).
    """
    cfg = EnsembleConfig(
        weights={"local_llm": 1e6, "external_ai": 1e6},
        strong_threshold=0.5,
        partial_threshold=0.001,
        conflict_margin=0.0,
        min_decisive_sources=1,
    )
    kwargs = dict(local=FakeLocal("recommend_reject"),
                  external=FakeExternal("reject"), config=cfg)

    sin_evidencia = make_candidate(extraction_method=ExtractionMethod.ONTOLOGY,
                                   evidence_text="", evidence_start=0,
                                   evidence_end=0)
    dec = combine(sin_evidencia, **kwargs)
    assert dec.recommendation == RECO_REJECT      # la rama negativa se preserva
    assert dec.state != STRONG_CONSENSUS
    assert dec.state == PARTIAL_CONSENSUS
    assert dec.score < 0

    # CONTROL no trivial: el MISMO montaje CON evidencia valida SI llega a STRONG.
    con_evidencia = valid_candidate(extraction_method=ExtractionMethod.ONTOLOGY)
    ok = combine(con_evidencia, **kwargs)
    assert ok.recommendation == RECO_REJECT
    assert ok.state == STRONG_CONSENSUS
    assert ok.score == dec.score                  # solo cambia la evidencia


@pytest.mark.mutation
def test_mut_availability_no_falsificable():
    """REGRESION (defecto B): `local_availability`/`external_availability` son
    parametros del LLAMANTE y no pueden contradecir el payload.

    Forjar `PRESENT` con `local=None` no debe habilitar el requisito de "al
    menos un proveedor presente" para STRONG.
    """
    cand = valid_candidate()
    signals = [{"name": "same_clause", "value": True}]

    control = combine(cand, signals=signals)
    forjado = combine(cand, signals=signals,
                      local=None, external=None,
                      local_availability="PRESENT",
                      external_availability="PRESENT")

    assert (forjado.state, forjado.recommendation) == (
        control.state, control.recommendation)
    assert forjado.state == PARTIAL_CONSENSUS
    assert forjado.recommendation == RECO_PROPOSE
    assert forjado.state != STRONG_CONSENSUS
    for src in ("local_llm", "external_ai"):
        c = contribution(forjado, src)
        assert c.availability == AVAIL_NOT_EXECUTED
        assert c.polarity == POL_NONE
        assert c.decisive is False

    # CONTROL: los MATICES LEGITIMOS de una ausencia si se conservan.
    matizado = combine(cand, signals=signals, local=None,
                       local_availability="FAILED_CLOSED")
    local_c = contribution(matizado, "local_llm")
    assert local_c.availability == "FAILED_CLOSED"
    assert local_c.polarity == POL_NONE
    assert contribution(matizado, "external_ai").availability == AVAIL_NOT_EXECUTED


def test_conflict_margin_no_admite_negativo():
    """REGRESION (defecto C): un `conflict_margin` negativo invertiria la zona
    muerta de indecision."""
    with pytest.raises(EnsembleConfigError):
        EnsembleConfig(conflict_margin=-1.0)
    with pytest.raises(EnsembleConfigError):
        config_from_dict({"conflict_margin": -1.0})
    cfg = config_from_dict({"conflict_margin": 0.0})
    assert cfg.conflict_margin == 0.0


def test_decision_expone_versiones_de_config():
    """MEJORA D: la decision expone las versiones de pesos/umbrales usadas."""
    cfg = config_from_dict({"strong_threshold": 0.8})
    dec = combine(valid_candidate(), signals=strong_signals(), config=cfg)
    data = dec.to_dict()
    for key in ("weights_version", "thresholds_version"):
        assert isinstance(data[key], str) and data[key].strip()
        assert data[key] == getattr(cfg, key)
    assert data["config_hash"] == cfg.config_hash
    assert data["profile"] == cfg.profile
    assert json.loads(dec.to_json())["weights_version"] == cfg.weights_version


@pytest.mark.mutation
def test_mut_shadow_obligatorio():
    """MUTANTE: permitir decisiones fuera de modo sombra."""
    with pytest.raises(ValueError):
        EnsembleDecision(state=STRONG_CONSENSUS, recommendation=RECO_PROPOSE,
                         shadow=False)
    with pytest.raises(ValueError):
        EnsembleDecision(state=HUMAN_REQUIRED, recommendation=RECO_HUMAN,
                         shadow=None)  # type: ignore[arg-type]
    dec = combine(valid_candidate(), signals=strong_signals())
    assert dec.shadow is True
    assert dec.to_dict()["shadow"] is True


@pytest.mark.mutation
def test_mut_estado_invalido_no_se_recalibra():
    """MUTANTE: recalibrar (y ascender) un veredicto INVALID delegado."""
    bad = make_candidate(evidence_text="", evidence_start=0, evidence_end=0)
    dec = combine(bad, signals=strong_signals(), syntax=svo_syntax(),
                  local=FakeLocal("recommend_propose"),
                  external=FakeExternal("confirm"))
    assert dec.consensus_state == INVALID_RESPONSES
    assert dec.state == INVALID_RESPONSES
    assert dec.score == 0.0

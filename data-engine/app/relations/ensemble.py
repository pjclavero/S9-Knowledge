# -*- coding: utf-8 -*-
"""Ensemble CALIBRADO de relaciones (`relation-ensemble/v1`).

Encuadre (IMPORTANTE)
---------------------
Este modulo NO es un segundo combinador de consenso. Es una CAPA DE CALIBRACION
EXPLICABLE construida ENCIMA de `relations.consensus_adapter`:

  * `consensus_adapter.compute_relation_consensus` sigue siendo el combinador
    canonico de las 4 vias (heuristicas R2, sintaxis R3, LLM local R5, IA externa
    R6). Ni se reescribe ni se depreca.
  * El ensemble DELEGA en el las INVALIDACIONES DURAS (contrato invalido, mezcla
    de workspaces, proveedor presente invalido, evidencia ausente). Si el
    consenso delegado dice `INVALID_RESPONSES`, el ensemble RESPETA ese veredicto
    y lo devuelve tal cual, con trazabilidad completa. Aqui NO se reimplementa
    ninguna de esas invalidaciones.
  * Lo que aporta el ensemble es (a) CALIBRAR la zona gris con umbrales y pesos
    versionados y (b) INCORPORAR POR FIN las fuentes deterministas de los
    Bloques 3/4/5 -- vocabulario, temporalidad y estado epistemico -- que hoy
    NO estan cableadas en produccion.

Principios duros
----------------
  * DETERMINISTA y PURO: sin red, sin disco, sin escritura, sin LLM, sin
    `time`/`random`, sin iterar sets. Recibe evaluaciones YA CALCULADAS (o None).
  * AUSENCIA != RECHAZO: un proveedor ausente produce una contribucion con
    `availability = NOT_EXECUTED` y `polarity = "none"`; no vota en contra ni
    resta score.
  * NINGUNA CONTRIBUCION SE PIERDE: se emite SIEMPRE una entrada por fuente
    configurada, aunque este ausente o sea invalida.
  * SIN AUTOAPROBACION: el techo de la recomendacion es `propose`. `approve`,
    `auto_approve`, `write`, `apply`... estan prohibidos por barrera.
  * ESTADOS CANONICOS reutilizados de `external_ai.models.CONSENSUS_STATES`; el
    catalogo de recomendaciones se reutiliza de
    `consensus_adapter.RELATION_RECOMMENDATIONS`. No se define taxonomia propia.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

# --- Taxonomia canonica de estados (REUTILIZADA, nunca duplicada) -----------
from external_ai.models import (
    CONSENSUS_STATES,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)

# --- Combinador canonico en el que este modulo DELEGA ------------------------
from relations.consensus_adapter import (
    MODULE_VERSION as CONSENSUS_VERSION,
    RECO_HUMAN,
    RECO_PROPOSE,
    RECO_REJECT,
    RELATION_RECOMMENDATIONS,
    _EXTERNAL_POLARITY,
    _FORBIDDEN_RECOMMENDATIONS,
    _LOCAL_POLARITY,
    compute_relation_consensus,
)
from relations.contracts import (
    EpistemicStatus,
    RelationCandidate,
    RelationContractError,
)

# --- Fuentes deterministas de los Bloques 3/4/5 ------------------------------
from relations.epistemic import (
    EPISTEMIC_VERSION,
    classify_epistemic,
    is_epistemically_safe,
)
from relations.signals import SIGNALS_VERSION
from relations.syntax import SYNTAX_VERSION
from relations.temporality import (
    TEMPORALITY_VERSION,
    classify_temporality,
    temporal_status_of,
)
from relations.vocabulary import (
    VOCAB_VERSION,
    canonicalize_predicate,
    predicates_match,
    types_compatible,
)

# --- Estados de disponibilidad de proveedor (origen: relations.pipeline) -----
from relations.pipeline import (
    PROVIDER_FAILED_CLOSED,
    PROVIDER_NOT_EXECUTED,
    PROVIDER_SKIPPED,
    _FORBIDDEN_CONFIG_KEYS,
    _canonical,
)

ENSEMBLE_VERSION = "relation-ensemble-1.0.0"
ENSEMBLE_SCHEMA = "relation-ensemble/v1"


class EnsembleConfigError(ValueError):
    """Config del ensemble invalida (clave desconocida o flag de escritura)."""


# ---------------------------------------------------------------------------
# Fuentes y disponibilidades
# ---------------------------------------------------------------------------
SOURCE_HEURISTICS = "heuristics"
SOURCE_SYNTAX = "syntax"
SOURCE_VOCABULARY = "vocabulary"
SOURCE_TEMPORALITY = "temporality"
SOURCE_EPISTEMIC = "epistemic"
SOURCE_LOCAL_LLM = "local_llm"
SOURCE_EXTERNAL_AI = "external_ai"

#: Orden CANONICO (alfabetico) de las contribuciones. Estable entre ejecuciones.
ENSEMBLE_SOURCES: tuple = tuple(sorted((
    SOURCE_HEURISTICS, SOURCE_SYNTAX, SOURCE_VOCABULARY, SOURCE_TEMPORALITY,
    SOURCE_EPISTEMIC, SOURCE_LOCAL_LLM, SOURCE_EXTERNAL_AI,
)))

# Disponibilidad de una fuente. PRESENT/INVALID son propias del ensemble; el
# resto REUTILIZA los literales de `relations.pipeline` (NOT_EXECUTED /
# FAILED_CLOSED / SKIPPED). `EXECUTED` del pipeline se representa como PRESENT
# porque aqui lo relevante es si la evaluacion esta disponible para ponderar.
AVAIL_PRESENT = "PRESENT"
AVAIL_NOT_EXECUTED = PROVIDER_NOT_EXECUTED     # "NOT_EXECUTED"
AVAIL_FAILED_CLOSED = PROVIDER_FAILED_CLOSED   # "FAILED_CLOSED"
AVAIL_SKIPPED = PROVIDER_SKIPPED               # "SKIPPED"
AVAIL_INVALID = "INVALID"
AVAILABILITIES: tuple = (
    AVAIL_PRESENT, AVAIL_NOT_EXECUTED, AVAIL_FAILED_CLOSED, AVAIL_SKIPPED,
    AVAIL_INVALID,
)

# Polaridades de una contribucion.
POL_POSITIVE = "positive"
POL_NEGATIVE = "negative"
POL_ABSTAIN = "abstain"   # fuente presente pero sin voto (no penaliza)
POL_NONE = "none"         # fuente ausente/invalida (NUNCA es un voto negativo)
POLARITIES: tuple = (POL_POSITIVE, POL_NEGATIVE, POL_ABSTAIN, POL_NONE)

# Tipos de conflicto admitidos (tipificados y ordenables).
CONFLICT_PROVIDER_POLARITY = "provider_polarity"
CONFLICT_NEGATION = "negation"
CONFLICT_EPISTEMIC = "epistemic"
CONFLICT_TEMPORAL = "temporal"
CONFLICT_PREDICATE_MISMATCH = "predicate_mismatch"
CONFLICT_TYPES: tuple = (
    CONFLICT_EPISTEMIC, CONFLICT_NEGATION, CONFLICT_PREDICATE_MISMATCH,
    CONFLICT_PROVIDER_POLARITY, CONFLICT_TEMPORAL,
)

# Reason codes del consenso delegado que se traducen a conflicto tipificado.
_CONSENSUS_CODE_TO_CONFLICT = {
    "provider_polarity_conflict": CONFLICT_PROVIDER_POLARITY,
    "negation_contradiction": CONFLICT_NEGATION,
    "epistemic_contradiction": CONFLICT_EPISTEMIC,
}

# Version declarada por cada fuente (la del modulo de origen).
_SOURCE_VERSION = {
    SOURCE_HEURISTICS: SIGNALS_VERSION,
    SOURCE_SYNTAX: SYNTAX_VERSION,
    SOURCE_VOCABULARY: VOCAB_VERSION,
    SOURCE_TEMPORALITY: TEMPORALITY_VERSION,
    SOURCE_EPISTEMIC: EPISTEMIC_VERSION,
    SOURCE_LOCAL_LLM: CONSENSUS_VERSION,
    SOURCE_EXTERNAL_AI: CONSENSUS_VERSION,
}


# ---------------------------------------------------------------------------
# Contribucion de una fuente
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceContribution:
    """Aportacion de UNA fuente al ensemble.

    Se emite SIEMPRE una por fuente configurada, incluso si la fuente esta
    ausente (`availability != PRESENT`, `polarity = "none"`), para que ninguna
    contribucion se pierda en la trazabilidad.
    """

    source: str
    availability: str
    polarity: str
    weight: float
    score: float            # magnitud con signo en [-1, 1] (0 si no decide)
    version: str
    reason_codes: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.source not in ENSEMBLE_SOURCES:
            raise ValueError(f"fuente desconocida: {self.source!r}")
        if self.availability not in AVAILABILITIES:
            raise ValueError(f"availability invalida: {self.availability!r}")
        if self.polarity not in POLARITIES:
            raise ValueError(f"polarity invalida: {self.polarity!r}")
        if self.availability != AVAIL_PRESENT and self.polarity != POL_NONE:
            raise ValueError("una fuente no presente solo admite polarity 'none'")

    @property
    def decisive(self) -> bool:
        """True si la contribucion vota (positiva o negativa)."""
        return (
            self.availability == AVAIL_PRESENT
            and self.polarity in (POL_POSITIVE, POL_NEGATIVE)
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "availability": self.availability,
            "polarity": self.polarity,
            "weight": float(self.weight),
            "score": float(self.score),
            "version": self.version,
            "reason_codes": list(self.reason_codes),
        }


# ---------------------------------------------------------------------------
# Configuracion (pesos + umbrales versionados)
# ---------------------------------------------------------------------------
_DEFAULT_WEIGHTS = {
    SOURCE_HEURISTICS: 0.6,
    SOURCE_SYNTAX: 0.8,
    SOURCE_VOCABULARY: 1.0,
    SOURCE_TEMPORALITY: 0.7,
    SOURCE_EPISTEMIC: 1.0,
    SOURCE_LOCAL_LLM: 1.2,
    SOURCE_EXTERNAL_AI: 1.4,
}


@dataclass(frozen=True)
class EnsembleConfig:
    """Pesos y umbrales de calibracion, versionados y hasheables.

    `weights_version` y `thresholds_version` son INDEPENDIENTES de
    `ENSEMBLE_VERSION`: recalibrar pesos/umbrales no cambia el codigo ni los
    contratos, solo esta capa.
    """

    weights: Mapping = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    strong_threshold: float = 0.75
    partial_threshold: float = 0.45
    conflict_margin: float = 0.15
    min_decisive_sources: int = 2
    profile: str = "default-1.0.0"
    weights_version: str = "relation-ensemble-weights-1.0.0"
    thresholds_version: str = "relation-ensemble-thresholds-1.0.0"

    def __post_init__(self) -> None:
        unknown = sorted(set(self.weights) - set(ENSEMBLE_SOURCES))
        if unknown:
            raise EnsembleConfigError(f"pesos de fuentes desconocidas: {unknown}")
        weights: dict = {}
        for src in ENSEMBLE_SOURCES:
            raw = self.weights.get(src, _DEFAULT_WEIGHTS[src])
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise EnsembleConfigError(f"peso no numerico para {src!r}: {raw!r}")
            if raw < 0:
                raise EnsembleConfigError(f"peso negativo para {src!r}: {raw!r}")
            weights[src] = float(raw)
        object.__setattr__(self, "weights", MappingProxyType(weights))

        for name in ("strong_threshold", "partial_threshold", "conflict_margin"):
            val = getattr(self, name)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise EnsembleConfigError(f"{name} no numerico: {val!r}")
            object.__setattr__(self, name, float(val))
        if not 0.0 < self.partial_threshold <= self.strong_threshold <= 1.0:
            raise EnsembleConfigError(
                "umbrales invalidos: 0 < partial_threshold <= strong_threshold <= 1"
            )
        # La zona muerta no puede ser negativa: un `conflict_margin < 0` la
        # ANULARIA (ningun |score| quedaria dentro del margen), desactivando de
        # facto el envio a humano por indecision.
        if self.conflict_margin < 0.0:
            raise EnsembleConfigError("conflict_margin debe ser >= 0")
        if isinstance(self.min_decisive_sources, bool) or \
                not isinstance(self.min_decisive_sources, int) or \
                self.min_decisive_sources < 1:
            raise EnsembleConfigError("min_decisive_sources debe ser un entero >= 1")

    def weight_for(self, source: str) -> float:
        return float(self.weights[source])

    def to_dict(self) -> dict:
        """Vista canonica (claves ordenadas por json.dumps aguas abajo)."""
        return {
            "weights": {k: float(self.weights[k]) for k in ENSEMBLE_SOURCES},
            "strong_threshold": self.strong_threshold,
            "partial_threshold": self.partial_threshold,
            "conflict_margin": self.conflict_margin,
            "min_decisive_sources": int(self.min_decisive_sources),
            "profile": self.profile,
            "weights_version": self.weights_version,
            "thresholds_version": self.thresholds_version,
        }

    @property
    def config_hash(self) -> str:
        """Hash determinista de `to_dict()` (sha256 truncado a 16 hex)."""
        payload = _canonical(self.to_dict()).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


#: Perfiles inmutables de calibracion.
PROFILES: Mapping = MappingProxyType({
    "default-1.0.0": EnsembleConfig(),
})
DEFAULT_PROFILE: EnsembleConfig = PROFILES["default-1.0.0"]

#: Lista BLANCA de claves aceptadas por `config_from_dict`.
_CONFIG_KEYS = frozenset(DEFAULT_PROFILE.to_dict().keys())


def config_from_dict(data: Optional[dict]) -> EnsembleConfig:
    """Construye una `EnsembleConfig` desde un dict con LISTA BLANCA de claves.

    Rechaza explicitamente las claves de escritura de
    `relations.pipeline._FORBIDDEN_CONFIG_KEYS` (write/apply/persist/commit/
    auto_approve/...): el ensemble jamas escribe ni aplica nada.
    """
    data = dict(data or {})
    forbidden = sorted(_FORBIDDEN_CONFIG_KEYS & set(data))
    if forbidden:
        raise EnsembleConfigError(
            f"config prohibida (el ensemble nunca escribe/aplica): {forbidden}"
        )
    unknown = sorted(set(data) - _CONFIG_KEYS)
    if unknown:
        raise EnsembleConfigError(f"claves de config desconocidas: {unknown}")
    weights = data.get("weights")
    if weights is not None and not isinstance(weights, Mapping):
        raise EnsembleConfigError("weights debe ser un mapa fuente -> peso")
    if weights is not None:
        forbidden_w = sorted(_FORBIDDEN_CONFIG_KEYS & set(weights))
        if forbidden_w:
            raise EnsembleConfigError(f"pesos prohibidos: {forbidden_w}")
        data["weights"] = dict(weights)
    return EnsembleConfig(**data)


# ---------------------------------------------------------------------------
# Decision del ensemble
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EnsembleDecision:
    """Resultado calibrado para UN candidato de relacion.

    `consensus_state` conserva el estado que devolvio
    `compute_relation_consensus` (trazabilidad de la delegacion). `state` puede
    calibrarlo dentro de la zona gris, pero NUNCA convierte una invalidacion en
    un consenso ni emite una aprobacion.
    """

    state: str
    recommendation: str
    contributions: tuple = field(default_factory=tuple)
    conflicts: tuple = field(default_factory=tuple)
    score: float = 0.0
    config_hash: str = ""
    ensemble_version: str = ENSEMBLE_VERSION
    consensus_state: str = ""
    consensus_recommendation: str = ""
    consensus_reason_codes: tuple = field(default_factory=tuple)
    profile: str = ""
    # Versiones de la calibracion aplicada. Se propagan al payload para que un
    # consumidor pueda auditar QUE pesos/umbrales produjeron la decision sin
    # tener que resolver el perfil ni recalcular el `config_hash`.
    weights_version: str = ""
    thresholds_version: str = ""
    reason: str = ""
    schema: str = ENSEMBLE_SCHEMA
    shadow: bool = True

    def __post_init__(self) -> None:
        # BARRERA (a): modo sombra obligatorio.
        if self.shadow is not True:
            raise ValueError("EnsembleDecision debe ser shadow=True (sin efectos)")
        # BARRERA (b): estado dentro de la taxonomia canonica.
        if self.state not in CONSENSUS_STATES:
            raise ValueError(f"state {self.state!r} no pertenece a CONSENSUS_STATES")
        # BARRERA (c): recomendacion valida y jamas una aprobacion/escritura.
        if self.recommendation not in RELATION_RECOMMENDATIONS:
            raise ValueError(
                f"recommendation {self.recommendation!r} no es valida "
                f"(permitidas: {RELATION_RECOMMENDATIONS})"
            )
        if self.recommendation.lower() in _FORBIDDEN_RECOMMENDATIONS:
            raise ValueError("recomendacion prohibida (aprobacion/escritura no permitida)")

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "recommendation": self.recommendation,
            "contributions": [c.to_dict() for c in self.contributions],
            "conflicts": [dict(c) for c in self.conflicts],
            "score": float(self.score),
            "config_hash": self.config_hash,
            "ensemble_version": self.ensemble_version,
            "consensus_state": self.consensus_state,
            "consensus_recommendation": self.consensus_recommendation,
            "consensus_reason_codes": list(self.consensus_reason_codes),
            "profile": self.profile,
            "weights_version": self.weights_version,
            "thresholds_version": self.thresholds_version,
            "reason": self.reason,
            "schema": self.schema,
            "shadow": self.shadow,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Lectura tolerante (objetos o dicts), sin mutar nada
# ---------------------------------------------------------------------------
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _signal_map(signals: Optional[Sequence[Any]]) -> dict:
    """Mapa {name: value} INDEPENDIENTE DEL ORDEN de la lista de senales."""
    grouped: dict = {}
    for s in signals or ():
        name = _get(s, "name")
        if name is None:
            continue
        grouped.setdefault(name, []).append(_get(s, "value"))
    out: dict = {}
    for name in sorted(grouped):
        values = grouped[name]
        out[name] = values[0] if len(values) == 1 else sorted(values, key=repr)[0]
    return out


def _validated_copy(candidate: Any) -> Optional[RelationCandidate]:
    """COPIA validada del candidato, o None si no valida el contrato.

    Nunca muta el original. Las invalidaciones ya las decidio el consenso
    delegado; aqui solo se necesita saber si podemos leer campos con confianza.
    """
    try:
        if isinstance(candidate, RelationCandidate):
            data = candidate.to_dict()
        elif isinstance(candidate, dict):
            data = dict(candidate)
        else:
            return None
        return RelationCandidate.from_dict(data, validate=True)
    except (RelationContractError, ValueError, TypeError, KeyError):
        return None


def _evidence_text(cand: RelationCandidate) -> str:
    """Texto sobre el que se clasifica: evidencia y, si falta, el segmento."""
    txt = cand.evidence_text if isinstance(cand.evidence_text, str) else ""
    if txt.strip():
        return txt
    seg = cand.source_segment if isinstance(cand.source_segment, str) else ""
    return seg


def _epistemic_value(status: Any) -> str:
    return status.value if isinstance(status, EpistemicStatus) else str(status)


def _absent(source: str, availability: str, config: EnsembleConfig,
            reason_codes: Sequence[str] = ()) -> SourceContribution:
    """Contribucion de una fuente NO presente. AUSENCIA != RECHAZO: score 0."""
    return SourceContribution(
        source=source,
        availability=availability,
        polarity=POL_NONE,
        weight=config.weight_for(source),
        score=0.0,
        version=_SOURCE_VERSION[source],
        reason_codes=tuple(reason_codes),
    )


def _present(source: str, polarity: str, score: float, config: EnsembleConfig,
             reason_codes: Sequence[str] = ()) -> SourceContribution:
    return SourceContribution(
        source=source,
        availability=AVAIL_PRESENT,
        polarity=polarity,
        weight=config.weight_for(source),
        score=float(score),
        version=_SOURCE_VERSION[source],
        reason_codes=tuple(sorted(reason_codes)),
    )


def _conflict(kind: str, detail: str, sources: Sequence[str]) -> dict:
    return {
        "type": kind,
        "detail": detail,
        "sources": sorted(sources),
    }


def _sorted_conflicts(conflicts: Sequence[dict]) -> tuple:
    """Orden canonico y deduplicado de los conflictos.

    La deduplicacion es por (`type`, `sources`): dos conflictos del MISMO tipo
    que afectan a las MISMAS fuentes son UN solo conflicto, aunque los hayan
    detectado caminos distintos (p.ej. la deteccion propia del ensemble y la
    traduccion del reason code del consenso delegado). No se pierde informacion:
    los `detail` distintos se FUSIONAN, ordenados, separados por " | ".
    """
    merged: dict = {}
    for c in conflicts:
        key = (c["type"], tuple(c["sources"]))
        details = merged.setdefault(key, set())
        details.add(c["detail"])
    out = []
    for key in sorted(merged):
        kind, sources = key
        out.append({
            "type": kind,
            "detail": " | ".join(sorted(merged[key])),
            "sources": list(sources),
        })
    return tuple(out)


def _syntax_structural(syntax: Any) -> bool:
    for sent in _get(syntax, "sentences", ()) or ():
        if (_get(sent, "subject_index") is not None
                and _get(sent, "main_verb_index") is not None
                and _get(sent, "object_index") is not None):
            return True
    return False


def _syntax_negated(syntax: Any) -> bool:
    for sent in _get(syntax, "sentences", ()) or ():
        if _get(sent, "negated"):
            return True
    return False


# ---------------------------------------------------------------------------
# Derivacion de las fuentes deterministas (Bloques 3/4/5)
# ---------------------------------------------------------------------------
def _vocabulary_contribution(cand: RelationCandidate,
                             config: EnsembleConfig) -> SourceContribution:
    """B3 -- vocabulario: canonicalizacion del predicado + compatibilidad de tipos."""
    canon = canonicalize_predicate(cand.predicate)
    if canon.canonical is None or canon.requires_human:
        return _present(SOURCE_VOCABULARY, POL_ABSTAIN, 0.0, config,
                        reason_codes=(f"vocab_{canon.status}",))
    codes = [f"vocab_{canon.status}"]
    if cand.subject_type is None or cand.object_type is None:
        # Canonico pero sin tipos: apoyo parcial, no se puede verificar ontologia.
        codes.append("types_unknown")
        return _present(SOURCE_VOCABULARY, POL_POSITIVE, 0.5, config, reason_codes=codes)
    if types_compatible(cand.predicate, cand.subject_type, cand.object_type):
        codes.append("types_compatible")
        return _present(SOURCE_VOCABULARY, POL_POSITIVE, 1.0, config, reason_codes=codes)
    codes.append("types_incompatible")
    return _present(SOURCE_VOCABULARY, POL_NEGATIVE, -1.0, config, reason_codes=codes)


def _temporality_contribution(cand: RelationCandidate, text: str,
                              config: EnsembleConfig) -> tuple:
    """B4 -- temporalidad: clase del texto vs `temporal_status_of(temporal_scope)`."""
    clf = classify_temporality(text)
    declared = temporal_status_of(cand.temporal_scope)
    conflicts: list = []
    if declared is None:
        # Sin alcance declarado: nada que corroborar ni contradecir.
        return (_present(SOURCE_TEMPORALITY, POL_ABSTAIN, 0.0, config,
                         reason_codes=("temporal_scope_absent",
                                       f"text_class_{clf.temporal_class}")),
                conflicts)
    if declared == clf.temporal_class:
        return (_present(SOURCE_TEMPORALITY, POL_POSITIVE, 1.0, config,
                         reason_codes=("temporal_agreement", f"text_class_{declared}")),
                conflicts)
    if clf.temporal_class == "ATEMPORAL":
        # El texto no aporta clase: no contradice el alcance declarado.
        return (_present(SOURCE_TEMPORALITY, POL_ABSTAIN, 0.0, config,
                         reason_codes=("temporal_text_atemporal",
                                       f"declared_{declared}")),
                conflicts)
    conflicts.append(_conflict(
        CONFLICT_TEMPORAL,
        f"temporal_scope={declared} vs texto={clf.temporal_class}",
        (SOURCE_TEMPORALITY,),
    ))
    return (_present(SOURCE_TEMPORALITY, POL_NEGATIVE, -1.0, config,
                     reason_codes=("temporal_mismatch", f"declared_{declared}",
                                   f"text_class_{clf.temporal_class}")),
            conflicts)


def _epistemic_contribution(cand: RelationCandidate, text: str,
                            config: EnsembleConfig) -> tuple:
    """B5 -- epistemico: clase del texto vs `epistemic_status` del candidato."""
    clf = classify_epistemic(text)
    declared = _epistemic_value(cand.epistemic_status)
    conflicts: list = []
    safe = is_epistemically_safe(cand.epistemic_status, clf.has_epistemic_cue)
    if not safe:
        conflicts.append(_conflict(
            CONFLICT_EPISTEMIC,
            f"cue epistemico ({clf.nuance}) con epistemic_status=ASSERTED",
            (SOURCE_EPISTEMIC,),
        ))
        return (_present(SOURCE_EPISTEMIC, POL_NEGATIVE, -1.0, config,
                         reason_codes=("epistemic_unsafe", f"nuance_{clf.nuance}")),
                conflicts)
    if _epistemic_value(clf.status) == declared:
        return (_present(SOURCE_EPISTEMIC, POL_POSITIVE, 1.0, config,
                         reason_codes=("epistemic_agreement", f"status_{declared}")),
                conflicts)
    # Clases distintas pero seguras (p.ej. texto ASSERTED y candidato RUMORED):
    # el candidato es MAS conservador que el texto -> no penaliza, no corrobora.
    return (_present(SOURCE_EPISTEMIC, POL_ABSTAIN, 0.0, config,
                     reason_codes=("epistemic_divergence_safe",
                                   f"declared_{declared}",
                                   f"text_{_epistemic_value(clf.status)}")),
            conflicts)


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------
def combine(
    candidate: Any,
    *,
    signals: Optional[Sequence[Any]] = None,
    syntax: Optional[Any] = None,
    local: Optional[Any] = None,
    external: Optional[Any] = None,
    config: EnsembleConfig = DEFAULT_PROFILE,
    local_availability: Optional[str] = None,
    external_availability: Optional[str] = None,
) -> EnsembleDecision:
    """Calibra el consenso de UN candidato de relacion.

    Acepta evaluaciones YA CALCULADAS (o `None`). NUNCA invoca Ollama/NVIDIA ni
    abre red, disco o Neo4j.

    Flujo:
      1. DELEGA en `compute_relation_consensus(...)`. Si su estado es
         `INVALID_RESPONSES`, se respeta tal cual (con contribuciones y
         trazabilidad) y no se calibra nada.
      2. Deriva las fuentes deterministas B3/B4/B5 (vocabulario, temporalidad,
         epistemico) sobre el candidato.
      3. Pondera las contribuciones PRESENTES y aplica los umbrales de `config`.

    Barrera estructural de polaridad: se registra un conflicto
    `provider_polarity` no solo cuando local y external discrepan entre si, sino
    SIEMPRE que la polaridad de un proveedor PRESENTE contradiga la direccion
    agregada del ensemble (proveedor negativo con score agregado positivo, o al
    reves). Como todo conflicto fuerza `MODEL_CONFLICT`/`human`, el rechazo
    explicito de un proveedor NUNCA puede terminar en `propose` recalibrando los
    umbrales: la garantia es estructural, no dependiente de la configuracion.

    `local_availability`/`external_availability` solo MATIZAN una ausencia
    (`FAILED_CLOSED`, `SKIPPED`...). No pueden declarar `PRESENT` un proveedor
    que no aporta payload: esa etiqueta se degrada a `NOT_EXECUTED`.

    Garantias: ausencia != rechazo; el techo de la recomendacion es `propose`;
    nunca `STRONG_CONSENSUS` si el consenso delegado invalido el candidato, si
    falta evidencia (en NINGUNA de las dos direcciones) o si no hay ningun
    proveedor con payload real.
    """
    if not isinstance(config, EnsembleConfig):
        raise EnsembleConfigError("config debe ser una EnsembleConfig")

    # -- (1) DELEGACION en el combinador canonico ------------------------------
    consensus = compute_relation_consensus(
        candidate, signals=signals, syntax=syntax, local=local, external=external
    )
    consensus_codes = tuple(sorted(consensus.reason_codes or ()))

    # La disponibilidad declarada por el llamante NO puede contradecir la
    # realidad del payload: si no hay evaluacion, la fuente NUNCA es PRESENT.
    # `local_availability`/`external_availability` solo sirven para MATIZAR una
    # ausencia (NOT_EXECUTED por defecto, o FAILED_CLOSED/SKIPPED), jamas para
    # fabricar un revisor inexistente.
    local_avail = _effective_availability(local, local_availability)
    external_avail = _effective_availability(external, external_availability)

    cand = _validated_copy(candidate)

    # -- (1b) Invalidacion delegada: se respeta el veredicto tal cual ----------
    if consensus.state == INVALID_RESPONSES:
        contributions = _absent_all(config, local_avail, external_avail,
                                    signals, syntax, cand)
        return EnsembleDecision(
            state=INVALID_RESPONSES,
            recommendation=RECO_HUMAN,
            contributions=contributions,
            conflicts=(),
            score=0.0,
            config_hash=config.config_hash,
            consensus_state=consensus.state,
            consensus_recommendation=consensus.recommendation,
            consensus_reason_codes=consensus_codes,
            profile=config.profile,
            weights_version=config.weights_version,
            thresholds_version=config.thresholds_version,
            reason=(
                "Invalidacion DELEGADA en consensus_adapter (no recalculada): "
                + (consensus.reason or "candidato invalido")
            ),
        )

    assert cand is not None, "consenso valido implica candidato valido"
    text = _evidence_text(cand)
    has_evidence = bool(text.strip()) and cand.evidence_end > cand.evidence_start

    conflicts: list = []
    contributions: dict = {}

    # -- (2) Fuentes deterministas B3/B4/B5 ------------------------------------
    contributions[SOURCE_VOCABULARY] = _vocabulary_contribution(cand, config)

    temp_contrib, temp_conflicts = _temporality_contribution(cand, text, config)
    contributions[SOURCE_TEMPORALITY] = temp_contrib
    conflicts.extend(temp_conflicts)

    epi_contrib, epi_conflicts = _epistemic_contribution(cand, text, config)
    contributions[SOURCE_EPISTEMIC] = epi_contrib
    conflicts.extend(epi_conflicts)

    # -- Heuristicas (R2) -------------------------------------------------------
    sig = _signal_map(signals)
    if not sig:
        contributions[SOURCE_HEURISTICS] = _absent(
            SOURCE_HEURISTICS, AVAIL_NOT_EXECUTED, config)
    else:
        structural = bool(
            sig.get("same_clause") or sig.get("same_sentence") or sig.get("svo_pattern")
        )
        codes = tuple(f"signal_{k}" for k in sorted(sig) if sig.get(k))
        if structural:
            contributions[SOURCE_HEURISTICS] = _present(
                SOURCE_HEURISTICS, POL_POSITIVE, 1.0, config,
                reason_codes=codes + ("structural_support",))
        else:
            contributions[SOURCE_HEURISTICS] = _present(
                SOURCE_HEURISTICS, POL_ABSTAIN, 0.0, config,
                reason_codes=codes + ("no_structural_support",))

    # -- Sintaxis (R3) ----------------------------------------------------------
    if syntax is None:
        contributions[SOURCE_SYNTAX] = _absent(
            SOURCE_SYNTAX, AVAIL_NOT_EXECUTED, config)
    elif _syntax_structural(syntax):
        contributions[SOURCE_SYNTAX] = _present(
            SOURCE_SYNTAX, POL_POSITIVE, 1.0, config,
            reason_codes=("syntax_svo",))
    else:
        contributions[SOURCE_SYNTAX] = _present(
            SOURCE_SYNTAX, POL_ABSTAIN, 0.0, config,
            reason_codes=("syntax_no_svo",))

    # -- Negacion: contradiccion entre senales/sintaxis y el candidato ---------
    neg_signal = sig.get("negation")
    if isinstance(neg_signal, bool) and neg_signal != cand.negated:
        conflicts.append(_conflict(
            CONFLICT_NEGATION,
            f"signal.negation={neg_signal} vs candidate.negated={cand.negated}",
            (SOURCE_HEURISTICS,),
        ))
    if syntax is not None and _syntax_negated(syntax) != cand.negated:
        conflicts.append(_conflict(
            CONFLICT_NEGATION,
            f"syntax.negated={_syntax_negated(syntax)} vs "
            f"candidate.negated={cand.negated}",
            (SOURCE_SYNTAX,),
        ))

    # -- Proveedores (R5/R6): AUSENTE != RECHAZO -------------------------------
    local_pol = _LOCAL_POLARITY.get(_get(local, "recommendation")) if local is not None else None
    external_pol = (
        _EXTERNAL_POLARITY.get(_get(external, "shadow_recommendation"))
        if external is not None else None
    )
    contributions[SOURCE_LOCAL_LLM] = _provider_contribution(
        SOURCE_LOCAL_LLM, local, local_pol, local_avail, config,
        _get(local, "recommendation"))
    contributions[SOURCE_EXTERNAL_AI] = _provider_contribution(
        SOURCE_EXTERNAL_AI, external, external_pol, external_avail, config,
        _get(external, "shadow_recommendation"))

    # Conflicto de polaridad entre proveedores.
    if (local_pol in (POL_POSITIVE, POL_NEGATIVE)
            and external_pol in (POL_POSITIVE, POL_NEGATIVE)
            and local_pol != external_pol):
        conflicts.append(_conflict(
            CONFLICT_PROVIDER_POLARITY,
            f"local={local_pol} vs external={external_pol}",
            (SOURCE_EXTERNAL_AI, SOURCE_LOCAL_LLM),
        ))

    # Negacion declarada por los proveedores.
    for src, negated in (
        (SOURCE_LOCAL_LLM, _get(local, "negated")),
        (SOURCE_EXTERNAL_AI, _get(_get(external, "verdict"), "negated")),
    ):
        if isinstance(negated, bool) and negated != cand.negated:
            conflicts.append(_conflict(
                CONFLICT_NEGATION,
                f"{src}.negated={negated} vs candidate.negated={cand.negated}",
                (src,),
            ))

    # Predicado del verdicto externo vs predicado del candidato.
    ext_predicate = _get(_get(external, "verdict"), "predicate")
    if isinstance(ext_predicate, str) and ext_predicate.strip():
        if not predicates_match(cand.predicate, ext_predicate):
            conflicts.append(_conflict(
                CONFLICT_PREDICATE_MISMATCH,
                f"candidate.predicate={cand.predicate} vs external={ext_predicate}",
                (SOURCE_EXTERNAL_AI, SOURCE_VOCABULARY),
            ))

    # -- Conflictos ya detectados por el consenso delegado ---------------------
    for code in consensus_codes:
        kind = _CONSENSUS_CODE_TO_CONFLICT.get(code)
        if kind == CONFLICT_PROVIDER_POLARITY:
            conflicts.append(_conflict(
                kind, f"consensus_adapter:{code}",
                (SOURCE_EXTERNAL_AI, SOURCE_LOCAL_LLM)))
        elif kind:
            conflicts.append(_conflict(
                kind, f"consensus_adapter:{code}", (SOURCE_HEURISTICS,)))

    ordered = tuple(contributions[src] for src in ENSEMBLE_SOURCES)

    # -- (3) Score ponderado sobre las contribuciones PRESENTES ----------------
    decisive = [c for c in ordered if c.decisive]
    total_weight = sum(c.weight for c in decisive)
    score = (
        sum(c.weight * c.score for c in decisive) / total_weight
        if total_weight > 0 else 0.0
    )
    score = round(float(score), 6)

    # Se cuenta sobre el PAYLOAD real, no sobre la etiqueta: una availability
    # declarada por el llamante jamas puede fabricar un revisor (ver
    # `_effective_availability`).
    providers_present = sum(1 for payload in (local, external) if payload is not None)

    # -- Proveedor PRESENTE contra la DIRECCION AGREGADA (barrera estructural) --
    # Un proveedor que vota en contra del resultado agregado es SIEMPRE un
    # conflicto, aunque el otro proveedor este ausente: asi el rechazo explicito
    # de un revisor no puede diluirse ni "recalibrarse" a propose bajando los
    # umbrales. La seguridad no depende de la configuracion.
    # Si local y external YA discrepan entre si, ese conflicto de par subsume al
    # de proveedor-vs-agregado (uno de los dos contradice al agregado por
    # construccion): no se duplica la entrada.
    if not any(c["type"] == CONFLICT_PROVIDER_POLARITY for c in conflicts):
        conflicts.extend(_provider_vs_aggregate_conflicts(contributions, score))

    conflict_tuple = _sorted_conflicts(conflicts)

    state, recommendation, reason = _derive_state(
        score=score,
        n_decisive=len(decisive),
        conflicts=conflict_tuple,
        config=config,
        consensus=consensus,
        has_evidence=has_evidence,
        providers_present=providers_present,
    )

    return EnsembleDecision(
        state=state,
        recommendation=recommendation,
        contributions=ordered,
        conflicts=conflict_tuple,
        score=score,
        config_hash=config.config_hash,
        consensus_state=consensus.state,
        consensus_recommendation=consensus.recommendation,
        consensus_reason_codes=consensus_codes,
        profile=config.profile,
        weights_version=config.weights_version,
        thresholds_version=config.thresholds_version,
        reason=reason,
    )


def _effective_availability(payload: Any, declared: Optional[str]) -> str:
    """Disponibilidad EFECTIVA de un proveedor. No es falsificable.

    Regla: la etiqueta nunca puede contradecir el payload.

      * `payload is not None` -> `PRESENT` (hay evaluacion real que ponderar).
      * `payload is None`     -> la ausencia se puede MATIZAR con el valor
        declarado (`FAILED_CLOSED`, `SKIPPED`, `NOT_EXECUTED`), pero un
        `PRESENT` declarado se degrada a `NOT_EXECUTED`: no existe revisor.

    Sin esta regla, un llamante podria pasar `local_availability="PRESENT"` con
    `local=None` y satisfacer el requisito de "al menos un proveedor presente"
    para STRONG sin que ningun revisor haya opinado.
    """
    if payload is not None:
        return AVAIL_PRESENT
    if not declared or declared == AVAIL_PRESENT:
        return AVAIL_NOT_EXECUTED
    if declared not in AVAILABILITIES:
        raise ValueError(f"availability declarada invalida: {declared!r}")
    return declared


def _provider_vs_aggregate_conflicts(contributions: Mapping, score: float) -> list:
    """Conflictos `provider_polarity` entre un proveedor PRESENTE y el agregado.

    Regla estructural: si la direccion agregada del ensemble (signo de `score`)
    contradice la polaridad de CUALQUIER proveedor presente y decisivo, se
    registra un conflicto tipificado `provider_polarity`. Cubre el caso de UN
    SOLO proveedor presente que rechaza mientras las fuentes deterministas
    empujan en positivo (o viceversa), que la comparacion local-vs-external no
    detecta. El resultado es determinista: se recorren los proveedores en orden
    canonico y `score == 0` no define direccion (no genera conflicto).
    """
    if score > 0:
        aggregate = POL_POSITIVE
    elif score < 0:
        aggregate = POL_NEGATIVE
    else:
        return []
    out: list = []
    for src in (SOURCE_EXTERNAL_AI, SOURCE_LOCAL_LLM):
        contrib = contributions[src]
        if contrib.decisive and contrib.polarity != aggregate:
            out.append(_conflict(
                CONFLICT_PROVIDER_POLARITY,
                f"{src}={contrib.polarity} contra la direccion agregada "
                f"{aggregate} (score {score})",
                (src,),
            ))
    return out


def _provider_contribution(source: str, payload: Any, polarity: Optional[str],
                           availability: str, config: EnsembleConfig,
                           raw_recommendation: Any) -> SourceContribution:
    """Contribucion de un proveedor. Si esta AUSENTE no vota ni resta."""
    if payload is None:
        return _absent(source, availability, config,
                       reason_codes=(f"{source}_{availability.lower()}",))
    codes = (f"recommendation_{raw_recommendation}",) if raw_recommendation else ()
    if polarity == "positive":
        return _present(source, POL_POSITIVE, 1.0, config, reason_codes=codes)
    if polarity == "negative":
        return _present(source, POL_NEGATIVE, -1.0, config, reason_codes=codes)
    # abstain (uncertain/human) o recomendacion desconocida: presente sin voto.
    return _present(source, POL_ABSTAIN, 0.0, config,
                    reason_codes=codes + ("provider_abstains",))


def _derive_state(*, score: float, n_decisive: int, conflicts: tuple,
                  config: EnsembleConfig, consensus: Any,
                  has_evidence: bool, providers_present: int = 0) -> tuple:
    """Aplica los umbrales de calibracion. El techo es `propose`, nunca aprobar.

    Reglas (en orden):
      1. Con conflictos tipificados -> MODEL_CONFLICT / human.
      2. |score| dentro de `conflict_margin` -> zona muerta -> HUMAN_REQUIRED.
      3. score >= strong_threshold, sin conflictos, con >= min_decisive_sources,
         con evidencia, con el consenso delegado en (STRONG|PARTIAL) y con AL
         MENOS UN PROVEEDOR PRESENTE -> STRONG_CONSENSUS / propose. Las fuentes
         deterministas por si solas nunca llegan a STRONG: corroboran, no
         sustituyen a un revisor.
      4. score >= partial_threshold -> PARTIAL_CONSENSUS / propose.
      5. score negativo fuerte Y el consenso delegado recomienda `reject` ->
         se PRESERVA la polaridad negativa (reject nunca es una aprobacion). La
         rama negativa exige EXACTAMENTE las mismas condiciones que la positiva
         para llegar a STRONG (evidencia, proveedor presente, minimo de fuentes
         decisivas): sin evidencia NO hay STRONG en NINGUNA direccion.
      6. En cualquier otro caso -> HUMAN_REQUIRED / human.
    """
    if conflicts:
        kinds = sorted({c["type"] for c in conflicts})
        return (MODEL_CONFLICT, RECO_HUMAN,
                f"Conflictos tipificados detectados: {kinds}.")

    if abs(score) <= config.conflict_margin:
        return (HUMAN_REQUIRED, RECO_HUMAN,
                f"Score {score} dentro del margen de indecision "
                f"({config.conflict_margin}); requiere humano.")

    # Polaridad negativa corroborada por el consenso delegado.
    if score < 0:
        if (consensus.recommendation == RECO_REJECT
                and -score >= config.partial_threshold):
            state = (
                STRONG_CONSENSUS
                if (-score >= config.strong_threshold
                    and n_decisive >= config.min_decisive_sources
                    and has_evidence
                    and providers_present >= 1
                    and consensus.state in (STRONG_CONSENSUS, PARTIAL_CONSENSUS))
                else PARTIAL_CONSENSUS
            )
            return (state, RECO_REJECT,
                    f"Evidencia negativa corroborada (score {score}).")
        return (HUMAN_REQUIRED, RECO_HUMAN,
                f"Score negativo {score} sin corroboracion del consenso "
                f"delegado; requiere humano.")

    if (score >= config.strong_threshold
            and n_decisive >= config.min_decisive_sources
            and has_evidence
            and providers_present >= 1
            and consensus.state in (STRONG_CONSENSUS, PARTIAL_CONSENSUS)):
        return (STRONG_CONSENSUS, RECO_PROPOSE,
                f"Apoyo ponderado fuerte (score {score}) sin conflictos.")

    if score >= config.partial_threshold:
        return (PARTIAL_CONSENSUS, RECO_PROPOSE,
                f"Apoyo ponderado parcial (score {score}).")

    return (HUMAN_REQUIRED, RECO_HUMAN,
            f"Apoyo insuficiente (score {score}); requiere humano.")


def _absent_all(config: EnsembleConfig, local_avail: str, external_avail: str,
                signals: Optional[Sequence[Any]], syntax: Optional[Any],
                cand: Optional[RelationCandidate]) -> tuple:
    """Contribuciones cuando el consenso delegado invalido el candidato.

    Ninguna fuente determinista puede evaluarse con garantias sobre un candidato
    invalido: se marcan INVALID (no ausentes por configuracion) para no perder la
    trazabilidad de que existian.
    """
    det_avail = AVAIL_INVALID if cand is None else AVAIL_SKIPPED
    out = {
        SOURCE_VOCABULARY: _absent(SOURCE_VOCABULARY, det_avail, config,
                                   ("candidate_not_evaluable",)),
        SOURCE_TEMPORALITY: _absent(SOURCE_TEMPORALITY, det_avail, config,
                                    ("candidate_not_evaluable",)),
        SOURCE_EPISTEMIC: _absent(SOURCE_EPISTEMIC, det_avail, config,
                                  ("candidate_not_evaluable",)),
        SOURCE_HEURISTICS: _absent(
            SOURCE_HEURISTICS,
            AVAIL_SKIPPED if signals else AVAIL_NOT_EXECUTED, config,
            ("candidate_not_evaluable",)),
        SOURCE_SYNTAX: _absent(
            SOURCE_SYNTAX,
            AVAIL_SKIPPED if syntax is not None else AVAIL_NOT_EXECUTED, config,
            ("candidate_not_evaluable",)),
        SOURCE_LOCAL_LLM: _absent(
            SOURCE_LOCAL_LLM,
            AVAIL_SKIPPED if local_avail == AVAIL_PRESENT else local_avail, config,
            ("candidate_not_evaluable",)),
        SOURCE_EXTERNAL_AI: _absent(
            SOURCE_EXTERNAL_AI,
            AVAIL_SKIPPED if external_avail == AVAIL_PRESENT else external_avail,
            config, ("candidate_not_evaluable",)),
    }
    return tuple(out[src] for src in ENSEMBLE_SOURCES)


__all__ = [
    "ENSEMBLE_VERSION",
    "ENSEMBLE_SCHEMA",
    "ENSEMBLE_SOURCES",
    "AVAILABILITIES",
    "POLARITIES",
    "CONFLICT_TYPES",
    "SourceContribution",
    "EnsembleConfig",
    "EnsembleConfigError",
    "EnsembleDecision",
    "PROFILES",
    "DEFAULT_PROFILE",
    "config_from_dict",
    "combine",
]

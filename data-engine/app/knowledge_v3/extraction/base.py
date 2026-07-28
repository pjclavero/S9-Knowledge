# -*- coding: utf-8 -*-
"""Interfaz comun de los extractores V3 y constructores de propuestas.

Un extractor es una funcion pura de `(contexto, episodio) -> propuestas`:

    entrada : SourceEpisode + sus EvidenceFragment (+ GameProfile opcional)
    salida  : EntityMention y ClaimProposal VALIDADOS contra los contratos
              congelados `v3-internal-v1`

Y nada mas. Un extractor **no** escribe en Neo4j, **no** decide identidad, **no**
canoniza predicados, **no** cierra vigencias y **no** aprueba. Todo eso es del
motor local. Por eso la salida es siempre propuesta y la abstencion es una
salida de primera clase: `ClaimProposal.abstained = True` con confianza 0 es
preferible, por contrato, a inventar un predicado.

Invariantes que impone este modulo (y que los tests fijan):

- todo documento emitido pasa `validate()` contra el JSON Schema + reglas
  semanticas; si no valida, NO se emite: se convierte en diagnostico;
- `provider_trace` es veraz: el paso que aparece en `produced_by_step` es el que
  realmente produjo el contenido, y el `provider` es el real (`local`, `ollama`,
  `external`), nunca el que quede mejor;
- los identificadores son deterministas: dos ejecuciones sobre la misma entrada
  producen exactamente los mismos `mention_id` / `claim_id`;
- el aislamiento por workspace es duro: un contexto no mezcla workspaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional, Sequence

from ..contracts import (
    CONTRACT_VERSION,
    ClaimProposal,
    EntityMention,
    EpistemicStatusHint,
    EvidenceFragment,
    GameProfile,
    Provider,
    SourceEpisode,
    V3ContractError,
    provider_step,
    sha256_hash,
)
from ..contracts.base import schema_validator as _validator
from .text import (
    OFFSET_BASIS_EPISODE,
    OFFSET_BASIS_FRAGMENT,
    EvidenceIndex,
    normalize,
)

#: Version del subsistema extractor. Va en cada entrada de `provider_trace`.
EXTRACTOR_VERSION = "3.0.0"

#: Catalogo canonico de tipos (identico al del contrato; no se amplia aqui).
#: Es el DEFECTO, no la unica verdad: un `GameProfile` puede restringirlo (nunca
#: ampliarlo, eso lo prohibe el contrato). Ver `entity_types_of`.
ALLOWED_ENTITY_TYPES = ("Character", "Location", "Faction", "Object", "Event", "Concept")


def entity_types_of(profile: Optional[GameProfile]) -> tuple[str, ...]:
    """Tipos de entidad permitidos por el perfil, o el catalogo canonico.

    El perfil RESTRINGE: cualquier tipo que declare y no este en el catalogo se
    ignora, porque el contrato congelado no lo admitiria despues y la propuesta
    moriria en el validador con un error mucho menos claro.
    """
    declared = tuple(getattr(profile, "entity_types", ()) or ()) if profile is not None else ()
    filtered = tuple(t for t in declared if t in ALLOWED_ENTITY_TYPES)
    return filtered or ALLOWED_ENTITY_TYPES

#: Estatus epistemicos admitidos en una propuesta.
ALLOWED_EPISTEMIC = tuple(e.value for e in EpistemicStatusHint) + ("CONFLICTED", "UNKNOWN")


class ExtractionError(RuntimeError):
    """Error de uso del subsistema extractor (contexto mal formado, etc.)."""


# --------------------------------------------------------------------------
# Diagnosticos
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Diagnostic:
    """Por que una propuesta no se emitio, o con que reserva se emitio.

    Codigos estables (`^[A-Z][A-Z0-9_]{0,63}$`), nunca texto libre como clave:
    un diagnostico que no se puede agregar no sirve para medir nada.
    """

    code: str
    step: str
    episode_id: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "step": self.step,
            "episode_id": self.episode_id,
            "detail": self.detail,
        }


@dataclass
class ExtractionOutput:
    """Propuestas de un extractor sobre un episodio (o de todo el pipeline)."""

    mentions: list[EntityMention] = field(default_factory=list)
    claims: list[ClaimProposal] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def extend(self, other: "ExtractionOutput") -> "ExtractionOutput":
        self.mentions.extend(other.mentions)
        self.claims.extend(other.claims)
        self.diagnostics.extend(other.diagnostics)
        return self

    def codes(self) -> list[str]:
        return [d.code for d in self.diagnostics]

    def mention_by_id(self, mention_id: str) -> Optional[EntityMention]:
        for m in self.mentions:
            if m.mention_id == mention_id:
                return m
        return None

    def to_dict(self) -> dict:
        return {
            "mentions": [m.to_dict() for m in self.mentions],
            "claims": [c.to_dict() for c in self.claims],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


# --------------------------------------------------------------------------
# Contexto
# --------------------------------------------------------------------------
@dataclass
class ExtractionContext:
    """Entrada del subsistema: episodios + fragmentos (+ perfil y lexico).

    El contexto NO descarga nada, NO consulta el grafo y NO toca la red. Es un
    contenedor inmutable en la practica: los extractores solo leen de el.
    """

    workspace: str
    episodes: Sequence[SourceEpisode]
    fragments: Sequence[EvidenceFragment]
    profile: Optional[GameProfile] = None
    lexicon: Optional[Any] = None  # extraction.lexicon.Lexicon

    def __post_init__(self) -> None:
        bad = [e.episode_id for e in self.episodes if e.workspace != self.workspace]
        bad += [f.fragment_id for f in self.fragments if f.workspace != self.workspace]
        if bad:
            raise ExtractionError(
                f"aislamiento de workspace roto: documentos de otro workspace en el "
                f"contexto de {self.workspace!r}: {sorted(bad)}"
            )
        if self.profile is not None and self.profile.workspace != self.workspace:
            raise ExtractionError("el GameProfile pertenece a otro workspace")
        self._episodes_by_id = {e.episode_id: e for e in self.episodes}
        self._frags_by_episode: dict[str, list[EvidenceFragment]] = {}
        for f in self.fragments:
            self._frags_by_episode.setdefault(f.episode_id, []).append(f)
        for frags in self._frags_by_episode.values():
            frags.sort(key=lambda f: (f.start, f.fragment_id))
        self._index_cache: dict[str, EvidenceIndex] = {}

    def episode(self, episode_id: str) -> Optional[SourceEpisode]:
        return self._episodes_by_id.get(episode_id)

    def fragments_of(self, episode_id: str) -> list[EvidenceFragment]:
        return list(self._frags_by_episode.get(episode_id, ()))

    def index_of(self, episode: SourceEpisode) -> EvidenceIndex:
        """Indice de evidencia del episodio (cacheado: se reusa entre extractores)."""
        cached = self._index_cache.get(episode.episode_id)
        if cached is None:
            cached = EvidenceIndex(
                episode_id=episode.episode_id,
                text=episode.text,
                fragments=tuple(self.fragments_of(episode.episode_id)),
            )
            self._index_cache[episode.episode_id] = cached
        return cached

    def profile_predicates(self) -> set[str]:
        return set(self.profile.predicate_names()) if self.profile is not None else set()

    def calendars(self) -> list[dict]:
        return list(self.profile.calendars) if self.profile is not None else []


# --------------------------------------------------------------------------
# Identidad del extractor
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ExtractorInfo:
    """Quien produce: alimenta `provider_trace` y `produced_by_step`."""

    step: str
    provider: Provider
    name: str
    version: str = EXTRACTOR_VERSION
    model: Optional[str] = None

    def trace_entry(self, produced: Sequence[str]) -> dict:
        return provider_step(
            self.step,
            self.provider,
            self.name,
            self.version,
            list(produced),
            model=self.model,
        )


def make_id(prefix: str, *parts: Any) -> str:
    """Identificador determinista y corto a partir de sus componentes.

    Determinista a proposito: reejecutar el extractor sobre la misma entrada
    debe producir los mismos ids, o la deduplicacion aguas abajo es imposible.
    """
    digest = sha256_hash([str(p) for p in parts])["value"][:16]
    return f"{prefix}:{digest}"


def clamp(value: Any, lo: float = 0.0, hi: float = 1.0, *, default: float = 0.0) -> float:
    """Confianza acotada a `[lo, hi]`, a prueba de basura.

    Un modelo puede devolver `"alta"`, `null` o una lista donde deberia ir un
    numero. Antes esto salia como `ValueError`/`TypeError` desde dentro del
    constructor y tumbaba el lote ENTERO: un episodio mal contestado hacia caer
    los demas, que estaban bien. Ahora se degrada a `default` y quien llama
    decide si ademas lo diagnostica.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if num != num or num in (float("inf"), float("-inf")):  # NaN / infinitos
        return default
    return max(lo, min(hi, num))


def is_number(value: Any) -> bool:
    """`True` si el valor es un numero real utilizable como confianza."""
    if isinstance(value, bool) or value is None:
        return False
    try:
        num = float(value)
    except (TypeError, ValueError):
        return False
    return num == num and num not in (float("inf"), float("-inf"))


# --------------------------------------------------------------------------
# Constructores de propuestas
# --------------------------------------------------------------------------
def _merge_metadata(base: dict, extra: Optional[dict]) -> dict:
    out = dict(base)
    if extra:
        out.update(extra)
    return out


def build_mention(
    *,
    info: ExtractorInfo,
    episode: SourceEpisode,
    surface: str,
    start: int,
    end: int,
    evidence_fragment_ids: Sequence[str],
    type_candidates: Sequence[dict] = (),
    confidence: float = 0.5,
    coreference_candidates: Sequence[str] = (),
    basis: str = OFFSET_BASIS_EPISODE,
    bbox: Optional[dict] = None,
    time_start: Optional[float] = None,
    time_end: Optional[float] = None,
    extra_trace: Sequence[dict] = (),
    metadata: Optional[dict] = None,
    mention_id: Optional[str] = None,
    allowed_types: Sequence[str] = ALLOWED_ENTITY_TYPES,
) -> EntityMention:
    """Construye una `EntityMention` normalizada (sin validar todavia).

    Normaliza lo que el contrato exige y nada mas: no inventa tipos (una lista
    de candidatos vacia es una salida legitima y preferible a tipar mal) y no
    sube la confianza por su cuenta.
    """
    types = []
    seen: set[str] = set()
    permitidos = tuple(t for t in allowed_types if t in ALLOWED_ENTITY_TYPES) or ALLOWED_ENTITY_TYPES
    for cand in sorted(type_candidates, key=lambda c: (-float(c["confidence"]), str(c["type"]))):
        t = str(cand["type"])
        if t not in permitidos or t in seen:
            continue
        seen.add(t)
        types.append({"type": t, "confidence": clamp(cand["confidence"])})

    mid = mention_id or make_id(
        f"mention:{info.step}", episode.episode_id, start, end, surface, basis
    )
    meta = _merge_metadata({"offset_basis": basis}, metadata)
    if basis == OFFSET_BASIS_FRAGMENT and evidence_fragment_ids:
        meta.setdefault("offset_fragment_id", evidence_fragment_ids[0])
    return EntityMention(
        contract_version=CONTRACT_VERSION,
        workspace=episode.workspace,
        source_asset_id=episode.source_asset_id,
        source_hash=episode.source_hash,
        provider_trace=[
            info.trace_entry(["surface", "start", "end", "type_candidates"]),
            *extra_trace,
        ],
        produced_by_step=info.step,
        mention_id=mid,
        episode_id=episode.episode_id,
        surface=surface,
        normalized_surface=normalize(surface) or surface.strip().lower(),
        start=start,
        end=end,
        bbox=bbox,
        time_start=time_start if time_start is not None else episode.time_start,
        time_end=time_end if time_end is not None else episode.time_end,
        type_candidates=types,
        confidence=clamp(confidence),
        coreference_candidates=[c for c in dict.fromkeys(coreference_candidates) if c != mid],
        evidence_fragment_ids=list(dict.fromkeys(evidence_fragment_ids)),
        metadata=meta,
    )


def build_claim(
    *,
    info: ExtractorInfo,
    episode: SourceEpisode,
    evidence_fragment_ids: Sequence[str],
    subject_mentions: Sequence[str] = (),
    object_mentions: Sequence[str] = (),
    relation_phrase: str = "",
    predicate_candidates: Sequence[dict] = (),
    direction_candidates: Sequence[dict] = (),
    temporal_expressions: Sequence[dict] = (),
    negated: bool = False,
    epistemic_cues: Sequence[str] = (),
    epistemic_status_hint: str = "ASSERTED",
    qualifiers: Sequence[dict] = (),
    confidence: float = 0.0,
    alternatives: Sequence[dict] = (),
    abstained: bool = False,
    review_required: bool = False,
    extra_trace: Sequence[dict] = (),
    metadata: Optional[dict] = None,
    claim_id: Optional[str] = None,
) -> ClaimProposal:
    """Construye un `ClaimProposal` que YA cumple las reglas del contrato.

    Reglas aplicadas aqui, no delegadas al que llama:

    - abstenerse implica no proponer predicado y confianza 0 (una abstencion
      con predicado es una contradiccion, y el contrato la rechaza);
    - `VISUAL_INFERRED` implica `review_required=True` (dosier 7.6): lo inferido
      de un dibujo nace pidiendo revision;
    - las listas de candidatos van en el ORDEN CANONICO del validador; sin orden
      total, `best_predicate()` dependeria del orden de llegada y el pipeline
      dejaria de ser reproducible.
    """
    preds = [
        {"predicate": str(c["predicate"]), "confidence": clamp(c["confidence"])}
        for c in predicate_candidates
    ]
    dirs = [
        {"direction": str(c["direction"]), "confidence": clamp(c["confidence"])}
        for c in direction_candidates
    ]
    alts = [
        {
            "predicate": str(a["predicate"]),
            "direction": str(a["direction"]),
            "confidence": clamp(a["confidence"]),
            **({"reason_codes": list(a["reason_codes"])} if a.get("reason_codes") else {}),
        }
        for a in alternatives
    ]
    preds.sort(key=_validator.predicate_sort_key)
    dirs.sort(key=_validator.direction_sort_key)
    alts.sort(key=_validator.alternative_sort_key)

    if abstained:
        preds = []
        confidence = 0.0
    if epistemic_status_hint == "VISUAL_INFERRED":
        review_required = True

    cid = claim_id or make_id(
        f"claim:{info.step}",
        episode.episode_id,
        tuple(subject_mentions),
        relation_phrase,
        tuple(object_mentions),
        preds[0]["predicate"] if preds else "ABSTAIN",
    )
    return ClaimProposal(
        contract_version=CONTRACT_VERSION,
        workspace=episode.workspace,
        source_asset_id=episode.source_asset_id,
        source_hash=episode.source_hash,
        provider_trace=[
            info.trace_entry(["relation_phrase", "predicate_candidates", "direction_candidates"]),
            *extra_trace,
        ],
        produced_by_step=info.step,
        claim_id=cid,
        episode_id=episode.episode_id,
        subject_mentions=list(dict.fromkeys(subject_mentions)),
        relation_phrase=relation_phrase,
        object_mentions=list(dict.fromkeys(object_mentions)),
        predicate_candidates=preds,
        direction_candidates=dirs,
        temporal_expressions=[dict(t) for t in temporal_expressions],
        negated=bool(negated),
        epistemic_cues=list(dict.fromkeys(epistemic_cues)),
        epistemic_status_hint=epistemic_status_hint,
        qualifiers=[dict(q) for q in qualifiers],
        evidence_fragment_ids=list(dict.fromkeys(evidence_fragment_ids)),
        confidence=clamp(confidence),
        alternatives=alts,
        abstained=bool(abstained),
        review_required=bool(review_required),
        metadata=metadata,
    )


def emit(doc, out: ExtractionOutput, info: ExtractorInfo, episode_id: str) -> bool:
    """Valida y emite. Si el documento no cumple el contrato, NO sale.

    Es la ultima barrera: cualquier propuesta que no valide se convierte en
    diagnostico `CONTRACT_VIOLATION`. Preferimos perder una propuesta a emitir
    un documento que el motor local tendria que creerse.
    """
    try:
        doc.validate()
    except V3ContractError as exc:
        out.diagnostics.append(
            Diagnostic("CONTRACT_VIOLATION", info.step, episode_id, str(exc)[:400])
        )
        return False
    if isinstance(doc, EntityMention):
        out.mentions.append(doc)
    elif isinstance(doc, ClaimProposal):
        out.claims.append(doc)
    else:  # pragma: no cover - defensivo
        raise ExtractionError(f"tipo de propuesta no soportado: {type(doc).__name__}")
    return True


def abstention_claim(
    *,
    info: ExtractorInfo,
    episode: SourceEpisode,
    evidence_fragment_ids: Sequence[str],
    reason_codes: Sequence[str],
    relation_phrase: str = "",
    subject_mentions: Sequence[str] = (),
    object_mentions: Sequence[str] = (),
    temporal_expressions: Sequence[dict] = (),
    metadata: Optional[dict] = None,
) -> ClaimProposal:
    """Abstencion explicita: el extractor vio algo pero no se atreve a afirmarlo.

    Es informacion, no ruido: distingue "aqui no hay nada" de "aqui hay algo que
    no se leer", que es exactamente lo que el motor y el benchmark necesitan.
    """
    meta = _merge_metadata({"abstention_reasons": list(reason_codes)}, metadata)
    return build_claim(
        info=info,
        episode=episode,
        evidence_fragment_ids=evidence_fragment_ids,
        subject_mentions=subject_mentions,
        object_mentions=object_mentions,
        relation_phrase=relation_phrase,
        temporal_expressions=temporal_expressions,
        epistemic_status_hint="UNKNOWN",
        abstained=True,
        review_required=True,
        confidence=0.0,
        metadata=meta,
    )


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------
class Extractor:
    """Interfaz comun. Un extractor implementa `supports()` y `extract_episode()`.

    `extract()` recorre los episodios soportados; `prior` permite que un
    extractor consuma las propuestas de los anteriores (lo necesita la
    correferencia, que resuelve pronombres CONTRA menciones ya emitidas).
    """

    info: ExtractorInfo

    def supports(self, episode: SourceEpisode) -> bool:  # pragma: no cover - trivial
        return True

    def extract_episode(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        raise NotImplementedError

    def extract(
        self, ctx: ExtractionContext, prior: Optional[ExtractionOutput] = None
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        for episode in ctx.episodes:
            if not self.supports(episode):
                continue
            if not ctx.fragments_of(episode.episode_id):
                out.diagnostics.append(
                    Diagnostic(
                        "EPISODE_WITHOUT_EVIDENCE",
                        self.info.step,
                        episode.episode_id,
                        "un episodio sin fragmentos no puede anclar ninguna propuesta",
                    )
                )
                continue
            out.extend(self.extract_episode(ctx, episode, prior))
        return out


def low_quality(episode: SourceEpisode, threshold: float = 0.5) -> bool:
    """Episodio de calidad baja: no invalida, pero obliga a pedir revision."""
    try:
        return float(episode.quality.get("score", 1.0)) < threshold
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensivo
        return True


__all__ = [
    "ALLOWED_ENTITY_TYPES",
    "ALLOWED_EPISTEMIC",
    "EXTRACTOR_VERSION",
    "Diagnostic",
    "Extractor",
    "ExtractionContext",
    "ExtractionError",
    "ExtractionOutput",
    "ExtractorInfo",
    "abstention_claim",
    "build_claim",
    "build_mention",
    "clamp",
    "emit",
    "entity_types_of",
    "is_number",
    "low_quality",
    "make_id",
]

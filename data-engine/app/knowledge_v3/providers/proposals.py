# -*- coding: utf-8 -*-
"""Mapeo PURO de resultados de proveedor a documentos V3 propuestos.

Reglas que este modulo hace cumplir por construccion:

* **Solo tres contratos.** `EvidenceFragment`, `EntityMention` y
  `ClaimProposal`. Nada mas. No existe aqui ninguna funcion capaz de devolver
  un `GraphMutationPlan`, una `FactAssertion` ni una `EntityResolution`: la
  decision es del motor local (§2).
* **Los offsets los pone el sistema.** El proveedor entrega texto; la posicion
  de ese texto dentro del episodio se BUSCA localmente. Si el texto no aparece
  literalmente en el episodio, la propuesta se descarta: es una alucinacion, no
  una evidencia.
* **`provider_trace` veraz.** Cada documento lleva el paso local que anclo y el
  paso del proveedor que produjo el contenido, con su modelo. `produced_by_step`
  apunta SIEMPRE al paso del proveedor: quien produjo el contenido no se
  disimula.
* **Funciones puras.** Ni red, ni reloj, ni ficheros, ni estado global. Las
  mismas entradas producen exactamente los mismos documentos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from knowledge_v3.contracts import (
    CONTRACT_VERSION,
    ClaimProposal,
    EntityMention,
    EvidenceFragment,
    Provider,
    provider_step,
)
from knowledge_v3.providers.policy import Tier

#: Tipos de entidad admisibles. Identico a `_common-v3.schema.json#entity_type`.
#: Lo que el modelo devuelva fuera de esta lista se DESCARTA, no se traduce ni
#: se aproxima. (El humo real contra qwen2.5:7b devolvio tipos en chino:
#: exactamente el caso que esta lista corta.)
ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset(
    {"Character", "Location", "Faction", "Object", "Event", "Concept"}
)

ALLOWED_DIRECTIONS: frozenset[str] = frozenset(
    {"SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT", "UNDIRECTED"}
)

ALLOWED_EPISTEMIC: frozenset[str] = frozenset(
    {
        "ASSERTED",
        "RUMORED",
        "HYPOTHETICAL",
        "INTENDED",
        "VISUAL_INFERRED",
        "CONFLICTED",
        "UNKNOWN",
    }
)

_PREDICATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_WS_RE = re.compile(r"\s+")

#: Version del mapeador. Entra en la traza; si cambia el mapeo, cambia aqui.
MAPPER_NAME = "s9k.knowledge_v3.providers"
MAPPER_VERSION = "3.0.0"
LOCAL_ANCHOR_STEP = "anchor.local"


class ProposalError(ValueError):
    """La salida del proveedor no puede convertirse en una propuesta valida."""


def normalize_text(text: str) -> str:
    """Normalizacion determinista: NFKC, minusculas, espacios colapsados.

    Es LOCAL a proposito. Si la normalizacion la hiciera el proveedor, dos
    corridas del mismo documento podrian normalizar distinto y el dedup dejaria
    de funcionar.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _WS_RE.sub(" ", folded).strip()


@dataclass(frozen=True)
class LocalAnchor:
    """Ancla local de un episodio. La aporta el sistema, nunca el proveedor."""

    workspace: str
    source_asset_id: str
    source_hash: dict
    episode_id: str
    episode_text: str
    page: Optional[int] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    bbox: Optional[dict] = None
    frame_id: Optional[str] = None

    def locate(self, literal: str) -> tuple:
        """`(start, end)` del texto literal dentro del episodio.

        Lanza si no aparece: un fragmento que no esta en la fuente no es
        evidencia de nada.
        """
        idx = self.episode_text.find(literal)
        if idx < 0:
            raise ProposalError(
                "el texto propuesto no aparece literalmente en el episodio: "
                "propuesta descartada por no anclable"
            )
        return idx, idx + len(literal)


@dataclass(frozen=True)
class ProviderAttribution:
    """Quien produjo el contenido. Va tal cual a `provider_trace`."""

    tier: Tier
    name: str
    version: str
    step: str
    model: Optional[str] = None
    params_hash: Optional[dict] = None

    def as_contract_provider(self) -> Provider:
        return self.tier.as_contract_provider()


def _trace(attribution: ProviderAttribution, local_produced: list, produced: list) -> list:
    """Traza de dos pasos: anclaje local + produccion del proveedor."""
    return [
        provider_step(
            LOCAL_ANCHOR_STEP,
            Provider.LOCAL,
            MAPPER_NAME,
            MAPPER_VERSION,
            local_produced,
        ),
        provider_step(
            attribution.step,
            attribution.as_contract_provider(),
            attribution.name,
            attribution.version,
            produced,
            model=attribution.model,
            params_hash=attribution.params_hash,
        ),
    ]


def _check_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID_RE.match(value):
        raise ProposalError(f"{label} no es un identificador estable valido: {value!r}")
    return value


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, c))


# ---------------------------------------------------------------------------
# EvidenceFragment
# ---------------------------------------------------------------------------
def evidence_fragment_from_text(
    anchor: LocalAnchor,
    *,
    fragment_id: str,
    literal_text: str,
    media_type: str,
    attribution: ProviderAttribution,
    confidence: float = 1.0,
    validate: bool = True,
) -> EvidenceFragment:
    """Fragmento de evidencia a partir de texto entregado por un proveedor.

    El proveedor pone el texto; el sistema pone los offsets y la normalizacion.
    """
    _check_id(fragment_id, "fragment_id")
    if not isinstance(literal_text, str) or not literal_text:
        raise ProposalError("literal_text vacio")
    start, end = anchor.locate(literal_text)

    if media_type == "ASR_TEXT" and (anchor.time_start is None or anchor.time_end is None):
        raise ProposalError("evidencia ASR_TEXT sin anclaje temporal en el ancla local")
    if media_type in ("OCR_TEXT", "IMAGE_DESCRIPTION", "MAP", "DIAGRAM") and anchor.bbox is None:
        raise ProposalError(f"evidencia {media_type} sin bbox en el ancla local")

    doc = EvidenceFragment(
        contract_version=CONTRACT_VERSION,
        workspace=anchor.workspace,
        source_asset_id=anchor.source_asset_id,
        source_hash=anchor.source_hash,
        provider_trace=_trace(
            attribution,
            ["start", "end", "normalized_text"],
            ["literal_text", "confidence"],
        ),
        produced_by_step=attribution.step,
        fragment_id=fragment_id,
        episode_id=anchor.episode_id,
        literal_text=literal_text,
        normalized_text=normalize_text(literal_text),
        start=start,
        end=end,
        bbox=anchor.bbox,
        time_start=anchor.time_start,
        time_end=anchor.time_end,
        frame_id=anchor.frame_id,
        page=anchor.page,
        media_type=media_type,
        confidence=_clamp_confidence(confidence, 1.0),
    )
    return doc.validate() if validate else doc


# ---------------------------------------------------------------------------
# EntityMention
# ---------------------------------------------------------------------------
def mentions_from_extraction(
    anchor: LocalAnchor,
    payload: dict,
    *,
    attribution: ProviderAttribution,
    evidence_fragment_ids: list,
    mention_id_prefix: str = "mention",
    validate: bool = True,
) -> tuple:
    """`(menciones, reason_codes)` a partir de `payload["mentions"]`.

    Descarta en silencio explicito (con `reason_code`) todo lo que no ancla,
    todo tipo fuera del catalogo y toda mencion sin superficie.
    """
    if not evidence_fragment_ids:
        raise ProposalError("una mencion sin evidencia anclada no existe")
    for fid in evidence_fragment_ids:
        _check_id(fid, "evidence_fragment_id")

    raw_items = payload.get("mentions")
    if raw_items is None:
        return (), ("PROVIDER_NO_MENTIONS",)
    if not isinstance(raw_items, list):
        raise ProposalError("`mentions` no es una lista")

    out: list = []
    codes: set = set()
    seen_ids: set = set()

    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            codes.add("PROVIDER_ITEM_NOT_OBJECT")
            continue
        surface = item.get("surface")
        if not isinstance(surface, str) or not surface.strip():
            codes.add("PROVIDER_MENTION_WITHOUT_SURFACE")
            continue
        try:
            start, end = anchor.locate(surface)
        except ProposalError:
            codes.add("PROVIDER_MENTION_NOT_ANCHORABLE")
            continue

        types: list = []
        seen_types: set = set()
        for cand in _as_type_candidates(item):
            name = cand.get("type")
            if name not in ALLOWED_ENTITY_TYPES:
                codes.add("PROVIDER_TYPE_OUT_OF_CATALOG")
                continue
            if name in seen_types:
                codes.add("PROVIDER_TYPE_DUPLICATED")
                continue
            seen_types.add(name)
            types.append({"type": name, "confidence": _clamp_confidence(cand.get("confidence"))})
        types.sort(key=lambda c: (-c["confidence"], c["type"]))

        mention_id = f"{mention_id_prefix}:{anchor.episode_id}:{index}"
        mention_id = re.sub(r"[^A-Za-z0-9._:-]", "-", mention_id)[:200]
        if mention_id in seen_ids:
            codes.add("PROVIDER_MENTION_ID_COLLISION")
            continue
        seen_ids.add(mention_id)

        doc = EntityMention(
            contract_version=CONTRACT_VERSION,
            workspace=anchor.workspace,
            source_asset_id=anchor.source_asset_id,
            source_hash=anchor.source_hash,
            provider_trace=_trace(
                attribution,
                ["start", "end", "normalized_surface"],
                ["surface", "type_candidates", "confidence"],
            ),
            produced_by_step=attribution.step,
            mention_id=mention_id,
            episode_id=anchor.episode_id,
            surface=surface,
            normalized_surface=normalize_text(surface) or surface,
            start=start,
            end=end,
            bbox=anchor.bbox,
            time_start=anchor.time_start,
            time_end=anchor.time_end,
            type_candidates=types,
            confidence=_clamp_confidence(item.get("confidence")),
            # La correferencia la decide la resolucion de identidad, no un
            # proveedor: aqui siempre va vacia.
            coreference_candidates=[],
            evidence_fragment_ids=list(evidence_fragment_ids),
        )
        out.append(doc.validate() if validate else doc)

    return tuple(out), tuple(sorted(codes))


def _as_type_candidates(item: dict) -> list:
    """Admite `type` escalar o `type_candidates` lista. Nada mas."""
    if isinstance(item.get("type_candidates"), list):
        return [c for c in item["type_candidates"] if isinstance(c, dict)]
    if item.get("type") is not None:
        return [{"type": item.get("type"), "confidence": item.get("confidence", 0.0)}]
    return []


# ---------------------------------------------------------------------------
# ClaimProposal
# ---------------------------------------------------------------------------
def claims_from_extraction(
    anchor: LocalAnchor,
    payload: dict,
    *,
    attribution: ProviderAttribution,
    evidence_fragment_ids: list,
    mention_ids: list,
    claim_id_prefix: str = "claim",
    validate: bool = True,
) -> tuple:
    """`(claims, reason_codes)` a partir de `payload["claims"]`.

    Un claim que referencie menciones inexistentes se descarta: inventar un
    `mention_id` es exactamente el ataque de "fragment IDs inventados".
    """
    if not evidence_fragment_ids:
        raise ProposalError("un claim sin evidencia anclada no existe")
    known_mentions = set(mention_ids)

    raw_items = payload.get("claims")
    if raw_items is None:
        return (), ("PROVIDER_NO_CLAIMS",)
    if not isinstance(raw_items, list):
        raise ProposalError("`claims` no es una lista")

    out: list = []
    codes: set = set()

    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            codes.add("PROVIDER_ITEM_NOT_OBJECT")
            continue

        subjects = [m for m in _as_list(item.get("subject_mentions")) if m in known_mentions]
        objects = [m for m in _as_list(item.get("object_mentions")) if m in known_mentions]
        if len(subjects) != len(_as_list(item.get("subject_mentions"))) or len(
            objects
        ) != len(_as_list(item.get("object_mentions"))):
            codes.add("PROVIDER_MENTION_ID_INVENTED")
        if not subjects or not objects:
            codes.add("PROVIDER_CLAIM_WITHOUT_MENTIONS")
            continue
        overlap = set(subjects) & set(objects)
        if overlap:
            codes.add("PROVIDER_CLAIM_SELF_RELATION")
            continue

        predicates: list = []
        seen_pred: set = set()
        for cand in _as_candidates(item.get("predicate_candidates"), "predicate", item.get("predicate")):
            name = cand.get("predicate")
            if not isinstance(name, str) or not _PREDICATE_RE.match(name):
                codes.add("PROVIDER_PREDICATE_NOT_NORMALIZED")
                continue
            if name in seen_pred:
                codes.add("PROVIDER_PREDICATE_DUPLICATED")
                continue
            seen_pred.add(name)
            predicates.append(
                {"predicate": name, "confidence": _clamp_confidence(cand.get("confidence"))}
            )
        predicates.sort(key=lambda c: (-c["confidence"], c["predicate"]))

        directions: list = []
        seen_dir: set = set()
        for cand in _as_candidates(item.get("direction_candidates"), "direction", item.get("direction")):
            name = cand.get("direction")
            if name not in ALLOWED_DIRECTIONS:
                codes.add("PROVIDER_DIRECTION_INVALID")
                continue
            if name in seen_dir:
                continue
            seen_dir.add(name)
            directions.append(
                {"direction": name, "confidence": _clamp_confidence(cand.get("confidence"))}
            )
        _DIR_ORDER = {"SUBJECT_TO_OBJECT": 0, "OBJECT_TO_SUBJECT": 1, "UNDIRECTED": 2}
        directions.sort(key=lambda c: (-c["confidence"], _DIR_ORDER[c["direction"]]))

        hint = item.get("epistemic_status_hint")
        if hint not in ALLOWED_EPISTEMIC:
            if hint is not None:
                codes.add("PROVIDER_EPISTEMIC_HINT_INVALID")
            hint = "UNKNOWN"

        abstained = bool(item.get("abstained")) or not predicates
        confidence = 0.0 if abstained else _clamp_confidence(item.get("confidence"))
        if abstained:
            # El contrato congelado lo exige: abstenerse es NO proponer
            # predicado. Un proveedor que se abstiene y ademas propone es una
            # contradiccion, y aqui gana la abstencion.
            if predicates:
                codes.add("PROVIDER_ABSTAINED_WITH_PREDICATE")
            predicates = []
        relation_phrase = item.get("relation_phrase")
        if not isinstance(relation_phrase, str):
            relation_phrase = ""
        relation_phrase = relation_phrase[:2000]

        claim_id = re.sub(
            r"[^A-Za-z0-9._:-]", "-", f"{claim_id_prefix}:{anchor.episode_id}:{index}"
        )[:200]

        doc = ClaimProposal(
            contract_version=CONTRACT_VERSION,
            workspace=anchor.workspace,
            source_asset_id=anchor.source_asset_id,
            source_hash=anchor.source_hash,
            provider_trace=_trace(
                attribution,
                ["evidence_fragment_ids"],
                ["relation_phrase", "predicate_candidates", "direction_candidates"],
            ),
            produced_by_step=attribution.step,
            claim_id=claim_id,
            episode_id=anchor.episode_id,
            subject_mentions=subjects,
            relation_phrase=relation_phrase,
            object_mentions=objects,
            predicate_candidates=predicates,
            direction_candidates=directions,
            temporal_expressions=[],
            negated=bool(item.get("negated")),
            epistemic_cues=[
                c[:256] for c in _as_list(item.get("epistemic_cues")) if isinstance(c, str) and c
            ],
            epistemic_status_hint=hint,
            qualifiers=[],
            evidence_fragment_ids=list(evidence_fragment_ids),
            confidence=confidence,
            alternatives=[],
            abstained=abstained,
            # Una propuesta de proveedor SIEMPRE va a revision: ningun
            # proveedor puede marcarse a si mismo como no revisable.
            review_required=True,
        )
        out.append(doc.validate() if validate else doc)

    return tuple(out), tuple(sorted(codes))


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, str):
        return [value]
    return []


def _as_candidates(candidates: Any, key: str, scalar: Any) -> list:
    if isinstance(candidates, list):
        return [c for c in candidates if isinstance(c, dict)]
    if scalar is not None:
        return [{key: scalar, "confidence": 0.0}]
    return []

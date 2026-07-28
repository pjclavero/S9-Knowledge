# -*- coding: utf-8 -*-
"""Normalizacion de propuestas producidas por un MODELO (Ollama, externo, vision).

Este modulo es la frontera de confianza del subsistema. Todo lo que llega de un
modelo entra por aqui y sale convertido en documentos `v3-internal-v1` o no sale.

Reglas, en orden de importancia:

1. **El modelo no aporta offsets ni identificadores de fragmento.** Aporta
   CITAS. Los offsets los calcula el motor local buscando la cita en el texto
   real (`EvidenceIndex._locate`), y el `fragment_id` sale del fragmento que
   contiene esa cita. Si el modelo propone un `fragment_id`, se trata como una
   pista que hay que verificar, nunca como un dato.
2. **Una mencion cuya superficie no aparece literalmente en un fragmento real se
   descarta.** Es el filtro que evita el fallo clasico: nombres plausibles que
   el modelo genera solo porque encajan en el mundo.
3. **Un claim cuyos argumentos no son menciones ancladas se descarta o se
   convierte en abstencion.** Nunca se crea una mencion "de apoyo" para salvar
   un claim: eso seria fabricar la evidencia que faltaba.
4. **Todo claim afirmado necesita CITA, y la cita se comprueba en contexto.**
   Que exista no basta: una cita parcial puede invertir el sentido del texto
   ("Kael **no** sirve a la Orden" citado como "sirve a la Orden"). Antes de
   aceptar `negated=False` se analiza el texto real que rodea al ancla
   (`cues.analyze_context`); si el contexto niega, condiciona, pregunta o
   desmiente, el claim se ABSTIENE. Sin cita no hay claim afirmado: sin ella no
   hay nada que comprobar, y una propuesta que no se puede comprobar no es una
   propuesta, es una invencion con formato correcto.
5. **Un ancla ambigua (`AMBIGUOUS_ANCHOR`) tampoco vale para afirmar.** La misma
   cita en dos fragmentos puede estar afirmada en uno y negada en el otro.
6. **La confianza del modelo se limita** (`confidence_cap`) y sus claims nacen
   con `review_required=True`. Un LLM propone; no aprueba.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..contracts import SourceEpisode
from .base import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_EPISTEMIC,
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    ExtractorInfo,
    abstention_claim,
    build_claim,
    build_mention,
    clamp,
    emit,
    is_number,
    low_quality,
)
from .cues import (
    CODE_NEGATION_MISMATCH,
    CODE_NON_FACTIVE,
    ContextVerdict,
    analyze_context,
)
from .text import (
    OFFSET_BASIS_EPISODE,
    Anchor,
    EvidenceIndex,
    collapse_whitespace,
    find_phrase,
    normalize,
    phrase_tokens,
)

_PREDICATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_NON_PREDICATE_CHARS = re.compile(r"[^A-Za-z0-9]+")

#: Tope de confianza de una propuesta de modelo. No es pesimismo gratuito: la
#: confianza declarada por un LLM no esta calibrada contra nada, y hasta que el
#: benchmark la mida no puede competir con una regla determinista verificada.
DEFAULT_CONFIDENCE_CAP = 0.7

#: Maximo de propuestas aceptadas por episodio. Un modelo que devuelve cien
#: menciones en un parrafo no esta extrayendo, esta generando.
MAX_MENTIONS_PER_EPISODE = 64
MAX_CLAIMS_PER_EPISODE = 32


class PayloadError(ValueError):
    """El payload del modelo no tiene la forma pactada."""


def normalize_predicate(raw: str) -> Optional[str]:
    """`raw` -> predicado canonico `^[A-Z][A-Z0-9_]{0,63}$`, o None.

    Misma normalizacion de forma que `relations.contracts.normalize_predicate`
    (MAYUSCULAS con guion bajo). No se importa de alli para no acoplar el
    subsistema V3 a la frontera intocable de V1/V2; el adaptador es quien cruza.
    """
    if not raw or not isinstance(raw, str):
        return None
    cleaned = _NON_PREDICATE_CHARS.sub("_", raw.strip()).strip("_").upper()
    if not cleaned or not _PREDICATE_RE.match(cleaned):
        return None
    return cleaned


#: Campos que, si vienen, tienen que ser TEXTO. `str()` sobre cualquier otra
#: cosa fabrica superficies que no existen: `["Kael"]` se convertia en la
#: cadena `"['Kael']"`, que ya no es el nombre de nadie.
TEXT_FIELDS = ("surface", "quote", "subject", "object", "relation", "predicate", "fragment_id")


def check_payload_shape(payload: Any) -> dict:
    """Comprueba la forma minima del payload. Lanza `PayloadError` si no cuadra."""
    if not isinstance(payload, dict):
        raise PayloadError(f"el payload no es un objeto JSON: {type(payload).__name__}")
    mentions = payload.get("mentions", [])
    claims = payload.get("claims", [])
    if not isinstance(mentions, list) or not isinstance(claims, list):
        raise PayloadError("'mentions' y 'claims' deben ser listas")
    if not all(isinstance(x, dict) for x in mentions):
        raise PayloadError("todas las menciones deben ser objetos")
    if not all(isinstance(x, dict) for x in claims):
        raise PayloadError("todos los claims deben ser objetos")
    return {"mentions": mentions, "claims": claims}


def text_field_errors(item: dict) -> list[str]:
    """Campos de texto que no son texto. No se convierten: se rechazan."""
    return [
        field
        for field in TEXT_FIELDS
        if field in item and item[field] is not None and not isinstance(item[field], str)
    ]


@dataclass
class _Grounded:
    """Mencion del modelo ya verificada contra la evidencia real."""

    mention_id: str
    normalized_surface: str
    fragment_id: str
    entity_type: Optional[str] = None


def _anchor_or_none(index: EvidenceIndex, quote: str, claimed: Optional[str]):
    if not quote:
        return None
    return index.anchor_quote(quote, claimed if isinstance(claimed, str) else None)


def verify_quote_context(index: EvidenceIndex, anchor, claimed_negated: bool) -> ContextVerdict:
    """Comprueba que el contexto real del ancla no contradiga lo que se afirma.

    Sin `negation_window`: al verificar la cita de un modelo se mira TODO el
    contexto previo dentro de la frase. Aqui la prudencia gana a la precision,
    porque el resultado de dudar es abstenerse, no equivocarse.
    """
    text, tokens, lo, hi, focus = index.context_window(anchor)
    verdict = analyze_context(text, tokens, lo=lo, hi=hi, focus=focus)
    if verdict.negated and not claimed_negated:
        return ContextVerdict(
            negated=True,
            hint=verdict.hint,
            cues=verdict.cues,
            reason_codes=(CODE_NEGATION_MISMATCH, *verdict.reason_codes),
        )
    return verdict


def normalize_payload(  # noqa: C901 - una comprobacion por regla anti-alucinacion
    payload: Any,
    *,
    ctx: ExtractionContext,
    episode: SourceEpisode,
    info: ExtractorInfo,
    confidence_cap: float = DEFAULT_CONFIDENCE_CAP,
    force_review: bool = True,
    epistemic_override: Optional[str] = None,
    emit_abstentions: bool = True,
) -> ExtractionOutput:
    """Convierte el payload de un modelo en propuestas validadas y ancladas."""
    out = ExtractionOutput()
    index = ctx.index_of(episode)
    try:
        shaped = check_payload_shape(payload)
    except PayloadError as exc:
        out.diagnostics.append(
            Diagnostic("MODEL_PAYLOAD_MALFORMED", info.step, episode.episode_id, str(exc))
        )
        return out

    profile_predicates = ctx.profile_predicates()
    grounded: dict[str, _Grounded] = {}

    # --- menciones -------------------------------------------------------
    for raw in shaped["mentions"][:MAX_MENTIONS_PER_EPISODE]:
        malos = text_field_errors(raw)
        if malos:
            out.diagnostics.append(
                Diagnostic(
                    "NON_TEXT_FIELD", info.step, episode.episode_id,
                    f"mencion con campos que no son texto: {malos}",
                )
            )
            continue
        surface = str(raw.get("surface") or "").strip()
        if not surface:
            out.diagnostics.append(
                Diagnostic("MENTION_WITHOUT_SURFACE", info.step, episode.episode_id, "")
            )
            continue
        anchor = _anchor_or_none(index, surface, raw.get("fragment_id"))
        if anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_MENTION", info.step, episode.episode_id,
                    f"{surface!r} no aparece en ningun fragmento real del episodio",
                )
            )
            continue
        quote = str(raw.get("quote") or "").strip()
        if quote and _anchor_or_none(index, quote, raw.get("fragment_id")) is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    f"la cita de {surface!r} no existe en el episodio",
                )
            )
            continue
        raw_confidence = raw.get("confidence", 0.5)
        if not is_number(raw_confidence):
            out.diagnostics.append(
                Diagnostic(
                    "INVALID_CONFIDENCE", info.step, episode.episode_id,
                    f"{surface!r}: {str(raw_confidence)[:32]!r} no es un numero",
                )
            )
        confidence = min(clamp(raw_confidence, default=0.0), confidence_cap)
        raw_type = raw.get("type")
        types = []
        if isinstance(raw_type, str) and raw_type in ALLOWED_ENTITY_TYPES:
            types.append({"type": raw_type, "confidence": confidence})
        elif raw_type not in (None, "", "null"):
            out.diagnostics.append(
                Diagnostic(
                    "UNKNOWN_ENTITY_TYPE", info.step, episode.episode_id, str(raw_type)[:64]
                )
            )
        mention = build_mention(
            info=info,
            episode=episode,
            surface=surface,
            start=anchor.start,
            end=anchor.end,
            evidence_fragment_ids=[anchor.fragment_id],
            type_candidates=types,
            confidence=confidence,
            basis=anchor.basis,
            metadata={
                "model_proposed": True,
                "anchor_reason_codes": list(anchor.reason_codes),
            },
        )
        if emit(mention, out, info, episode.episode_id):
            key = normalize(surface)
            previo = grounded.get(key)
            if previo is not None and previo.entity_type != mention.best_type():
                # La misma superficie tipada de dos formas distintas en el mismo
                # episodio: el modelo se contradice. Se conserva la primera (el
                # id es determinista) y se deja constancia; el motor local vera
                # el conflicto en vez de heredarlo en silencio.
                out.diagnostics.append(
                    Diagnostic(
                        "CONFLICTING_MENTION_TYPES", info.step, episode.episode_id,
                        f"{surface!r}: {previo.entity_type} vs {mention.best_type()}",
                    )
                )
            grounded.setdefault(
                key,
                _Grounded(mention.mention_id, key, anchor.fragment_id, mention.best_type()),
            )

    # --- claims ----------------------------------------------------------
    for raw in shaped["claims"][:MAX_CLAIMS_PER_EPISODE]:
        malos = text_field_errors(raw)
        if malos:
            out.diagnostics.append(
                Diagnostic(
                    "NON_TEXT_FIELD", info.step, episode.episode_id,
                    f"claim con campos que no son texto: {malos}",
                )
            )
            continue
        subject = normalize(str(raw.get("subject") or ""))
        obj = normalize(str(raw.get("object") or ""))
        quote = str(raw.get("quote") or "").strip()
        anchor = _anchor_or_none(index, quote, raw.get("fragment_id")) if quote else None
        if quote and anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    "la cita del claim no existe en ningun fragmento real",
                )
            )
            continue
        subj_hit = grounded.get(subject)
        obj_hit = grounded.get(obj)
        if subj_hit is None or obj_hit is None or subj_hit.mention_id == obj_hit.mention_id:
            missing = [
                code
                for code, hit in (("SUBJECT_NOT_GROUNDED", subj_hit), ("OBJECT_NOT_GROUNDED", obj_hit))
                if hit is None
            ] or ["SUBJECT_EQUALS_OBJECT"]
            out.diagnostics.append(
                Diagnostic(missing[0], info.step, episode.episode_id, f"{subject!r} / {obj!r}")
            )
            continue
        fragments = [
            f for f in (
                anchor.fragment_id if anchor else None,
                subj_hit.fragment_id,
                obj_hit.fragment_id,
            ) if f
        ]
        predicate = normalize_predicate(str(raw.get("predicate") or ""))
        reasons: list[str] = []
        if predicate is None:
            reasons.append("PREDICATE_NOT_NORMALIZABLE")
        elif profile_predicates and predicate not in profile_predicates:
            reasons.append("PREDICATE_NOT_IN_PROFILE")
        hint = epistemic_override or str(raw.get("epistemic") or "ASSERTED")
        if hint not in ALLOWED_EPISTEMIC:
            reasons.append("UNKNOWN_EPISTEMIC_STATUS")
            hint = "UNKNOWN"
        relation_phrase = str(raw.get("relation") or "")[:2000]
        negated = bool(raw.get("negated", False))

        # --- la cita es OBLIGATORIA para afirmar --------------------------
        # Sin cita no hay nada que verificar: el claim se apoyaria solo en dos
        # menciones que existen y en un predicado que el modelo se saco de
        # donde fuera. Dos menciones ancladas no sostienen la relacion entre
        # ellas.
        if anchor is None:
            reasons.append("CLAIM_WITHOUT_QUOTE")
        else:
            if anchor.ambiguous:
                reasons.append("AMBIGUOUS_ANCHOR")
            verdict = verify_quote_context(index, anchor, negated)
            if CODE_NEGATION_MISMATCH in verdict.reason_codes:
                reasons.append(CODE_NEGATION_MISMATCH)
            if verdict.non_factive:
                reasons.append(CODE_NON_FACTIVE)
                reasons.extend(
                    c for c in verdict.reason_codes if c != CODE_NEGATION_MISMATCH
                )
            elif verdict.hint != "ASSERTED" and hint == "ASSERTED":
                # El contexto real dice rumor/hipotesis/intencion aunque el
                # modelo dijera ASSERTED: manda el texto, no el modelo.
                hint = verdict.hint
        if reasons:
            if not emit_abstentions:
                out.diagnostics.append(
                    Diagnostic(reasons[0], info.step, episode.episode_id, relation_phrase[:120])
                )
                continue
            claim = abstention_claim(
                info=info,
                episode=episode,
                evidence_fragment_ids=fragments or [subj_hit.fragment_id],
                reason_codes=reasons,
                relation_phrase=relation_phrase,
                subject_mentions=[subj_hit.mention_id],
                object_mentions=[obj_hit.mention_id],
                metadata={"model_proposed": True, "raw_predicate": str(raw.get("predicate"))[:64]},
            )
            emit(claim, out, info, episode.episode_id)
            continue
        raw_claim_confidence = raw.get("confidence", 0.5)
        if not is_number(raw_claim_confidence):
            # Mismo trato que en las menciones: se degrada a 0 y se DICE. Una
            # confianza que se cae en silencio deja un claim con 0.0 que parece
            # una lectura del modelo y no lo es.
            out.diagnostics.append(
                Diagnostic(
                    "INVALID_CONFIDENCE", info.step, episode.episode_id,
                    f"claim {relation_phrase[:40]!r}: "
                    f"{str(raw_claim_confidence)[:32]!r} no es un numero",
                )
            )
        confidence = min(clamp(raw_claim_confidence, default=0.0), confidence_cap)
        claim = build_claim(
            info=info,
            episode=episode,
            evidence_fragment_ids=fragments,
            subject_mentions=[subj_hit.mention_id],
            object_mentions=[obj_hit.mention_id],
            relation_phrase=relation_phrase,
            predicate_candidates=[{"predicate": predicate, "confidence": confidence}],
            direction_candidates=[{"direction": "SUBJECT_TO_OBJECT", "confidence": confidence}],
            negated=negated,
            epistemic_cues=[str(c)[:256] for c in (raw.get("cues") or []) if str(c).strip()],
            epistemic_status_hint=hint,
            confidence=confidence,
            abstained=False,
            review_required=bool(force_review or low_quality(episode)),
            metadata={
                "model_proposed": True,
                "anchor_reason_codes": list(anchor.reason_codes) if anchor else [],
            },
        )
        emit(claim, out, info, episode.episode_id)

    return out


# --------------------------------------------------------------------------
# Payload SEMANTICO (respuesta conjunta: menciones + claims + abstenciones)
# --------------------------------------------------------------------------
#: Direcciones del contrato congelado. `UNRESOLVED` NO es una de ellas: el
#: modelo puede decirlo, y aqui se traduce a "sin candidatos de direccion" +
#: marca en `metadata`. Inventar una direccion para rellenar el hueco es
#: exactamente lo que hacia el camino anterior cableando SUBJECT_TO_OBJECT.
CONTRACT_DIRECTIONS = ("SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT", "UNDIRECTED")
UNRESOLVED_DIRECTION = "UNRESOLVED"

#: Tope de candidatos que se conservan. Mas de tres no es matiz, es una lista de
#: todo el vocabulario ordenada al azar.
MAX_PREDICATE_CANDIDATES = 3
MAX_DIRECTION_CANDIDATES = 3

#: Campos de texto de la forma semantica.
SEMANTIC_TEXT_FIELDS = (
    "surface", "evidence_quote", "local_ref", "subject_ref", "object_ref",
    "relation_phrase", "epistemic_status", "reason",
)

_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def anchor_in_episode(index: EvidenceIndex, quote: str) -> Optional[Anchor]:
    """Ancla una cita al TEXTO del episodio exigiendo evidencia que la respalde.

    Por que hace falta, medido: `EvidenceIndex.anchor_quote` exige que la cita
    quepa DENTRO de un solo fragmento. En el corpus real los fragmentos son
    tramos cortos ("Ilaria Vandreth", "dirigió la Casa del Ciervo desde el
    invierno de 1041"), asi que una cita de frase completa —justo lo que se le
    pide al modelo para poder comprobar el SENTIDO— no anclaba nunca y todas
    las propuestas morian como `HALLUCINATED_QUOTE` siendo literalmente
    ciertas. Eso no medía alucinacion: medía el troceado.

    Lo que NO se relaja, y es lo que importa:

    - la cita tiene que aparecer LITERALMENTE en el texto real del episodio
      (con la unica tolerancia de acentos/mayusculas por tokens que ya usaba el
      anclaje anterior);
    - los offsets los sigue calculando el sistema local, nunca el modelo;
    - el tramo tiene que SOLAPAR al menos un fragmento de evidencia real; si no
      hay evidencia debajo, no hay propuesta. Los fragmentos solapados son los
      que se emiten como `evidence_fragment_ids`;
    - varias apariciones de la misma cita = `AMBIGUOUS_ANCHOR`, igual que antes.

    Si el episodio no tiene texto (TABLE, IMAGE...), se delega en el anclaje por
    fragmento de siempre.
    """
    quote = collapse_whitespace(quote or "")
    if not quote:
        return None
    if not index.has_text:
        return index.anchor_quote(quote)
    texto = index.text or ""
    apariciones: list[tuple[int, int]] = []
    inicio = texto.find(quote)
    while inicio >= 0:
        apariciones.append((inicio, inicio + len(quote)))
        inicio = texto.find(quote, inicio + 1)
    if not apariciones:
        needle = phrase_tokens(quote)
        for first, last in find_phrase(index.tokens, needle):
            apariciones.append((index.tokens[first].start, index.tokens[last].end))
    if not apariciones:
        return None
    start, end = apariciones[0]
    solapados = [f for f in index.fragments if f.start < end and start < f.end]
    if not solapados:
        return None
    reasons: list[str] = []
    if len(apariciones) > 1:
        reasons.append("AMBIGUOUS_ANCHOR")
    if len(solapados) > 1:
        reasons.append("SPANS_MULTIPLE_FRAGMENTS")
    # Fragmento principal: el MAS AJUSTADO que contenga el tramo entero; si
    # ninguno lo contiene, el primero que lo solape. Quedarse con el primero
    # en orden documental elegia sistematicamente el fragmento largo de la
    # frase aunque existiese el fragmento exacto de la entidad.
    contenedores = [f for f in solapados if f.start <= start and end <= f.end]
    elegido = min(contenedores or solapados, key=lambda f: (f.end - f.start, f.start, f.fragment_id))
    return Anchor(elegido.fragment_id, start, end, OFFSET_BASIS_EPISODE, tuple(reasons))


def _fragments_covering(index: EvidenceIndex, anchor: Optional[Anchor]) -> list[str]:
    """Todos los fragmentos que respaldan el tramo anclado (no solo el primero)."""
    if anchor is None:
        return []
    if not index.has_text:
        return [anchor.fragment_id]
    return [
        f.fragment_id
        for f in index.fragments
        if f.start < anchor.end and anchor.start < f.end
    ] or [anchor.fragment_id]


def check_semantic_shape(payload: Any) -> dict:
    """Forma minima de la respuesta conjunta. `PayloadError` si no cuadra."""
    if not isinstance(payload, dict):
        raise PayloadError(f"el payload no es un objeto JSON: {type(payload).__name__}")
    out = {}
    for key in ("mentions", "claims", "abstentions"):
        value = payload.get(key, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            raise PayloadError(f"'{key}' debe ser una lista")
        if not all(isinstance(x, dict) for x in value):
            raise PayloadError(f"todos los elementos de '{key}' deben ser objetos")
        out[key] = value
    return out


def semantic_text_field_errors(item: dict) -> list[str]:
    return [
        field
        for field in SEMANTIC_TEXT_FIELDS
        if field in item and item[field] is not None and not isinstance(item[field], str)
    ]


def _reason_code(raw: Any, default: str = "MODEL_ABSTAINED") -> str:
    """Codigo de razon estable a partir de lo que diga el modelo.

    El modelo escribe prosa; el contrato exige codigo. Se normaliza igual que un
    predicado y, si no sale nada usable, se usa el defecto. Un codigo inventado
    con texto libre haria inagregable el diagnostico, que es justo para lo que
    existe.
    """
    code = normalize_predicate(str(raw or ""))
    return code if code and _REASON_RE.match(code) else default


def verify_semantic_quote_context(
    index: EvidenceIndex, anchor: Anchor, claimed_negated: bool
) -> ContextVerdict:
    """Verificacion de sentido cuando la cita es una FRASE ENTERA.

    Diferencia con `verify_quote_context`, y por que existe: alli el `focus` es
    el inicio del ancla y la negacion se busca solo ANTES. Con citas cortas eso
    es correcto. Con una cita de frase completa —que es lo que se le pide al
    extractor semantico para poder comprobar el sentido— el foco cae en la
    primera palabra y delante no hay nada, asi que "Elara **no** pertenece a la
    Orden" pasaba como afirmacion. Aqui el foco se lleva al FINAL del tramo
    citado: cualquier marca dentro de la propia cita cuenta. Es mas prudente, y
    el resultado de dudar sigue siendo abstenerse.
    """
    text, tokens, lo, hi, _focus = index.context_window(anchor)
    focus = next(
        (t.index for t in tokens if lo <= t.index < hi and t.start >= anchor.end), hi
    )
    verdict = analyze_context(text, tokens, lo=lo, hi=hi, focus=focus)
    if verdict.negated and not claimed_negated:
        return ContextVerdict(
            negated=True,
            hint=verdict.hint,
            cues=verdict.cues,
            reason_codes=(CODE_NEGATION_MISMATCH, *verdict.reason_codes),
        )
    return verdict


def normalize_semantic_payload(  # noqa: C901 - una comprobacion por regla
    payload: Any,
    *,
    ctx: ExtractionContext,
    episode: SourceEpisode,
    info: ExtractorInfo,
    ontology: Any,
    confidence_cap: float = DEFAULT_CONFIDENCE_CAP,
    force_review: bool = True,
    temporal_hook: Optional[Any] = None,
    emit_abstentions: bool = True,
) -> ExtractionOutput:
    """Convierte la respuesta conjunta del modelo en propuestas ancladas.

    Es la MISMA frontera anti-alucinacion que `normalize_payload`, aplicada a la
    forma nueva: el modelo aporta superficies y citas, y aqui se verifica todo
    contra el texto real. Lo que cambia respecto del camino anterior:

    - los predicados llegan como CANDIDATOS y se filtran contra la ontologia;
      que uno no este en el perfil ya no tira el claim entero, tira ese
      candidato. Solo si no sobrevive ninguno se abstiene;
    - la direccion la dice el modelo; `UNRESOLVED` se convierte en ausencia de
      candidatos, nunca en una direccion cableada;
    - la temporalidad pasa por `temporal_hook` (escalonada), y lo que el modelo
      diga del tiempo se valida contra el texto igual que una cita.
    """
    out = ExtractionOutput()
    index = ctx.index_of(episode)
    try:
        shaped = check_semantic_shape(payload)
    except PayloadError as exc:
        out.diagnostics.append(
            Diagnostic("MODEL_PAYLOAD_MALFORMED", info.step, episode.episode_id, str(exc))
        )
        return out

    allowed_types = tuple(getattr(ontology, "entity_types", ALLOWED_ENTITY_TYPES))
    allowed_predicates = set(getattr(ontology, "predicate_names", ()) or ())
    by_ref: dict[str, _Grounded] = {}
    by_surface: dict[str, _Grounded] = {}

    # --- menciones -------------------------------------------------------
    for raw in shaped["mentions"][:MAX_MENTIONS_PER_EPISODE]:
        malos = semantic_text_field_errors(raw)
        if malos:
            out.diagnostics.append(
                Diagnostic(
                    "NON_TEXT_FIELD", info.step, episode.episode_id,
                    f"mencion con campos que no son texto: {malos}",
                )
            )
            continue
        surface = str(raw.get("surface") or "").strip()
        if not surface:
            out.diagnostics.append(
                Diagnostic("MENTION_WITHOUT_SURFACE", info.step, episode.episode_id, "")
            )
            continue
        anchor = anchor_in_episode(index, surface)
        if anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_MENTION", info.step, episode.episode_id,
                    f"{surface!r} no aparece en ningun fragmento real del episodio",
                )
            )
            continue
        quote = str(raw.get("evidence_quote") or "").strip()
        if quote and anchor_in_episode(index, quote) is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    f"la cita de {surface!r} no existe en el episodio",
                )
            )
            continue
        tipos: list[dict] = []
        for cand in raw.get("type_candidates") or []:
            if not isinstance(cand, dict):
                continue
            tipo = cand.get("type")
            if not isinstance(tipo, str) or tipo not in allowed_types:
                out.diagnostics.append(
                    Diagnostic(
                        "UNKNOWN_ENTITY_TYPE", info.step, episode.episode_id, str(tipo)[:64]
                    )
                )
                continue
            bruta = cand.get("confidence", 0.5)
            if not is_number(bruta):
                out.diagnostics.append(
                    Diagnostic(
                        "INVALID_CONFIDENCE", info.step, episode.episode_id,
                        f"{surface!r}: {str(bruta)[:32]!r} no es un numero",
                    )
                )
            tipos.append({"type": tipo, "confidence": min(clamp(bruta, default=0.0), confidence_cap)})
        confianza = max((t["confidence"] for t in tipos), default=min(0.5, confidence_cap))
        mention = build_mention(
            info=info,
            episode=episode,
            surface=surface,
            start=anchor.start,
            end=anchor.end,
            evidence_fragment_ids=[anchor.fragment_id],
            type_candidates=tipos,
            confidence=confianza,
            basis=anchor.basis,
            allowed_types=allowed_types,
            metadata={
                "model_proposed": True,
                # `untrusted_origin` no existe como campo del contrato congelado
                # y no se anade: viaja en metadata, que es el unico bloque
                # abierto de la familia v3-internal-v1.
                "untrusted_origin": True,
                "anchor_reason_codes": list(anchor.reason_codes),
            },
        )
        if not emit(mention, out, info, episode.episode_id):
            continue
        key = normalize(surface)
        grounded = _Grounded(mention.mention_id, key, anchor.fragment_id, mention.best_type())
        ref = str(raw.get("local_ref") or "").strip()
        if ref:
            if ref in by_ref:
                out.diagnostics.append(
                    Diagnostic("DUPLICATE_LOCAL_REF", info.step, episode.episode_id, ref[:64])
                )
            by_ref.setdefault(ref, grounded)
        previo = by_surface.get(key)
        if previo is not None and previo.entity_type != grounded.entity_type:
            out.diagnostics.append(
                Diagnostic(
                    "CONFLICTING_MENTION_TYPES", info.step, episode.episode_id,
                    f"{surface!r}: {previo.entity_type} vs {grounded.entity_type}",
                )
            )
        by_surface.setdefault(key, grounded)

    def _resolve(ref: Any) -> Optional[_Grounded]:
        """`local_ref` primero; si no, la superficie literal. Nunca se fabrica."""
        texto = str(ref or "").strip()
        if not texto:
            return None
        return by_ref.get(texto) or by_surface.get(normalize(texto))

    # --- claims -----------------------------------------------------------
    for raw in shaped["claims"][:MAX_CLAIMS_PER_EPISODE]:
        malos = semantic_text_field_errors(raw)
        if malos:
            out.diagnostics.append(
                Diagnostic(
                    "NON_TEXT_FIELD", info.step, episode.episode_id,
                    f"claim con campos que no son texto: {malos}",
                )
            )
            continue
        subj_hit = _resolve(raw.get("subject_ref"))
        obj_hit = _resolve(raw.get("object_ref"))
        if subj_hit is None or obj_hit is None or subj_hit.mention_id == obj_hit.mention_id:
            codigo = (
                "SUBJECT_NOT_GROUNDED" if subj_hit is None
                else "OBJECT_NOT_GROUNDED" if obj_hit is None
                else "SUBJECT_EQUALS_OBJECT"
            )
            out.diagnostics.append(
                Diagnostic(
                    codigo, info.step, episode.episode_id,
                    f"{str(raw.get('subject_ref'))[:40]!r} / {str(raw.get('object_ref'))[:40]!r}",
                )
            )
            continue

        relation_phrase = str(raw.get("relation_phrase") or "")[:2000]
        quote = str(raw.get("evidence_quote") or "").strip()
        anchor = anchor_in_episode(index, quote) if quote else None
        if quote and anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    "la cita del claim no existe en ningun fragmento real",
                )
            )
            continue
        # Toda la evidencia que respalda la cita, no solo el primer fragmento:
        # una frase completa se apoya en varios tramos y quedarse con uno
        # dejaria el claim peor anclado de lo que realmente esta.
        fragments = list(
            dict.fromkeys(
                [*_fragments_covering(index, anchor), subj_hit.fragment_id, obj_hit.fragment_id]
            )
        )

        # --- predicados: CANDIDATOS filtrados contra la ontologia ---------
        preds: list[dict] = []
        descartados: list[str] = []
        vistos: set[str] = set()
        for cand in raw.get("predicate_candidates") or []:
            if not isinstance(cand, dict):
                continue
            normalizado = normalize_predicate(str(cand.get("predicate") or ""))
            if normalizado is None:
                descartados.append(str(cand.get("predicate"))[:64])
                continue
            if allowed_predicates and normalizado not in allowed_predicates:
                descartados.append(normalizado)
                continue
            if normalizado in vistos:
                continue
            vistos.add(normalizado)
            bruta = cand.get("confidence", 0.5)
            if not is_number(bruta):
                out.diagnostics.append(
                    Diagnostic(
                        "INVALID_CONFIDENCE", info.step, episode.episode_id,
                        f"claim {relation_phrase[:40]!r}: {str(bruta)[:32]!r} no es un numero",
                    )
                )
            preds.append(
                {
                    "predicate": normalizado,
                    "confidence": min(clamp(bruta, default=0.0), confidence_cap),
                }
            )
        preds = preds[:MAX_PREDICATE_CANDIDATES]
        if descartados:
            out.diagnostics.append(
                Diagnostic(
                    "PREDICATE_NOT_IN_PROFILE", info.step, episode.episode_id,
                    ", ".join(sorted(dict.fromkeys(descartados))[:8]),
                )
            )

        # --- direccion: explicita, con UNRESOLVED admitido ----------------
        dirs: list[dict] = []
        direccion_sin_resolver = False
        vistas: set[str] = set()
        for cand in raw.get("direction_candidates") or []:
            if not isinstance(cand, dict):
                continue
            valor = str(cand.get("direction") or "").strip().upper()
            if valor == UNRESOLVED_DIRECTION:
                direccion_sin_resolver = True
                continue
            if valor not in CONTRACT_DIRECTIONS or valor in vistas:
                if valor not in CONTRACT_DIRECTIONS:
                    out.diagnostics.append(
                        Diagnostic("UNKNOWN_DIRECTION", info.step, episode.episode_id, valor[:64])
                    )
                continue
            vistas.add(valor)
            dirs.append(
                {
                    "direction": valor,
                    "confidence": min(clamp(cand.get("confidence", 0.5), default=0.0), confidence_cap),
                }
            )
        dirs = dirs[:MAX_DIRECTION_CANDIDATES]

        hint = str(raw.get("epistemic_status") or "ASSERTED").strip().upper()
        negated = bool(raw.get("negated", False))
        reasons: list[str] = []
        if not preds:
            reasons.append("PREDICATE_NOT_IN_PROFILE" if descartados else "PREDICATE_MISSING")
        if hint not in ALLOWED_EPISTEMIC:
            reasons.append("UNKNOWN_EPISTEMIC_STATUS")
            hint = "UNKNOWN"

        # --- la cita sigue siendo OBLIGATORIA para afirmar ----------------
        if anchor is None:
            reasons.append("CLAIM_WITHOUT_QUOTE")
        else:
            if anchor.ambiguous:
                reasons.append("AMBIGUOUS_ANCHOR")
            verdict = verify_semantic_quote_context(index, anchor, negated)
            if CODE_NEGATION_MISMATCH in verdict.reason_codes:
                reasons.append(CODE_NEGATION_MISMATCH)
            if verdict.non_factive:
                reasons.append(CODE_NON_FACTIVE)
                reasons.extend(c for c in verdict.reason_codes if c != CODE_NEGATION_MISMATCH)
            elif verdict.hint != "ASSERTED" and hint == "ASSERTED":
                hint = verdict.hint

        # --- temporalidad ESCALONADA --------------------------------------
        temporal: list[dict] = []
        temporal_codes: list[str] = []
        temporal_pendiente = bool(raw.get("temporal_resolution_required", False))
        if temporal_hook is not None:
            temporal, temporal_codes, temporal_pendiente = temporal_hook(
                index, anchor, raw.get("temporal_expressions") or [], temporal_pendiente
            )

        metadata = {
            "model_proposed": True,
            "untrusted_origin": True,
            "anchor_reason_codes": list(anchor.reason_codes) if anchor else [],
            # Los dos campos que el contrato congelado NO tiene. Excepcion
            # documentada: viajan en metadata y en ningun otro sitio.
            "temporal_resolution_required": bool(temporal_pendiente),
            "direction_unresolved": direccion_sin_resolver,
        }
        if descartados:
            metadata["dropped_predicates"] = sorted(dict.fromkeys(descartados))[:8]
        if temporal_codes:
            metadata["temporal_codes"] = list(temporal_codes)

        if reasons:
            if not emit_abstentions:
                out.diagnostics.append(
                    Diagnostic(reasons[0], info.step, episode.episode_id, relation_phrase[:120])
                )
                continue
            claim = abstention_claim(
                info=info,
                episode=episode,
                evidence_fragment_ids=fragments or [subj_hit.fragment_id],
                reason_codes=sorted(dict.fromkeys(reasons)),
                relation_phrase=relation_phrase,
                subject_mentions=[subj_hit.mention_id],
                object_mentions=[obj_hit.mention_id],
                temporal_expressions=temporal,
                metadata=metadata,
            )
            emit(claim, out, info, episode.episode_id)
            continue

        claim = build_claim(
            info=info,
            episode=episode,
            evidence_fragment_ids=fragments,
            subject_mentions=[subj_hit.mention_id],
            object_mentions=[obj_hit.mention_id],
            relation_phrase=relation_phrase,
            predicate_candidates=preds,
            direction_candidates=dirs,
            temporal_expressions=temporal,
            negated=negated,
            epistemic_status_hint=hint,
            confidence=preds[0]["confidence"],
            abstained=False,
            review_required=bool(force_review or low_quality(episode)),
            metadata=metadata,
        )
        emit(claim, out, info, episode.episode_id)

    # --- abstenciones declaradas por el modelo ----------------------------
    for raw in shaped["abstentions"][:MAX_CLAIMS_PER_EPISODE]:
        if not emit_abstentions:
            break
        quote = str(raw.get("evidence_quote") or "").strip()
        anchor = anchor_in_episode(index, quote) if quote else None
        if anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    "abstencion sin cita anclable",
                )
            )
            continue
        claim = abstention_claim(
            info=info,
            episode=episode,
            evidence_fragment_ids=[anchor.fragment_id],
            reason_codes=[_reason_code(raw.get("reason"))],
            relation_phrase=quote[:2000],
            metadata={"model_proposed": True, "untrusted_origin": True},
        )
        emit(claim, out, info, episode.episode_id)

    return out


__all__ = [
    "CONTRACT_DIRECTIONS",
    "DEFAULT_CONFIDENCE_CAP",
    "MAX_CLAIMS_PER_EPISODE",
    "MAX_DIRECTION_CANDIDATES",
    "MAX_MENTIONS_PER_EPISODE",
    "MAX_PREDICATE_CANDIDATES",
    "PayloadError",
    "SEMANTIC_TEXT_FIELDS",
    "TEXT_FIELDS",
    "UNRESOLVED_DIRECTION",
    "check_payload_shape",
    "check_semantic_shape",
    "normalize_payload",
    "normalize_predicate",
    "normalize_semantic_payload",
    "semantic_text_field_errors",
    "text_field_errors",
]

# -*- coding: utf-8 -*-
"""Extractor DETERMINISTA: glosario, patrones y reglas de evidencia inequivoca.

Diseñado para **precision, no cobertura**. Es la leccion literal del PR #106: un
clasificador lexico afinado sobre su propio corpus llego a `predicate 0.81` con
dev==test y se quedo en `0.24` sobre material real. Este extractor no intenta
esconder esa realidad subiendo la cobertura: prefiere no emitir.

Reglas de emision de un claim (todas obligatorias, no ponderadas):

1. sujeto y objeto son menciones ANCLADAS a fragmentos reales;
2. la frase de relacion esta en la MISMA frase, entre sujeto y objeto;
3. no hay coordinacion (ni adyacente ni en ventana) entre los argumentos y la
   frase, ni dentro del sintagma de un argumento: "Elara y Kael viven en
   Valdor" es ambiguo, no se sabe de quien se afirma que vive;
4. los argumentos estan a menos de `MAX_ARGUMENT_GAP` tokens de la frase, no
   son modificadores de otro nucleo ("el hermano **de** Kael") y no hay varias
   menciones candidatas a sujeto;
5. si hay perfil, el predicado esta en el perfil y los tipos encajan;
6. el contexto es FACTIVO: ni condicional, ni interrogativo, ni desmentido.

Si alguna falla, o bien no se emite nada, o bien se emite una **abstencion**
explicita con su codigo de razon. Nunca se emite un predicado "a ver si suena".

Las confianzas son PRIORES declarados a mano, no probabilidades medidas. Su
unico compromiso es el orden relativo (canonico > alias, regla estricta > regla
laxa). El valor absoluto solo significara algo cuando lo mida el benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..contracts import Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    abstention_claim,
    build_claim,
    build_mention,
    clamp,
    emit,
    low_quality,
)
from . import cues as _cues
from .lexicon import Lexicon, LexiconMatch
from .temporal import TEMPORAL_INFO, extract_temporal_expressions
from .text import EvidenceIndex, Sentence, Token, find_phrase, phrase_tokens

DETERMINISTIC_STEP = "extract.deterministic"

DETERMINISTIC_INFO = ExtractorInfo(
    step=DETERMINISTIC_STEP,
    provider=Provider.LOCAL,
    name="s9k.extraction.deterministic",
)


@dataclass(frozen=True)
class RelationRule:
    """Frase de relacion -> predicado candidato. Ni canoniza ni decide."""

    predicate: str
    phrases: tuple[str, ...]
    direction: str = "SUBJECT_TO_OBJECT"
    confidence: float = 0.7
    symmetric: bool = False
    subject_types: tuple[str, ...] = ()
    object_types: tuple[str, ...] = ()

    def token_phrases(self) -> list[tuple[str, ...]]:
        return [phrase_tokens(p) for p in self.phrases]


#: Reglas curadas a mano. Cortas y muy literales a proposito: cada frase que se
#: añade aqui es una apuesta de precision que el benchmark tendra que pagar.
RELATION_RULES: tuple[RelationRule, ...] = (
    # Las formas en PLURAL entran a proposito: son las que aparecen en frases
    # coordinadas ("Elara y Kael viven en Valdor"), y sin ellas la guarda de
    # coordinacion no llegaria siquiera a evaluarse. Detectar la ambiguedad y
    # abstenerse es mejor que no ver la frase.
    RelationRule("MEMBER_OF", ("es miembro de", "son miembros de", "pertenece a",
                               "pertenecen a", "milita en", "forma parte de"),
                 confidence=0.75, object_types=("Faction",)),
    RelationRule("LEADS", ("lidera", "es lider de", "capitanea", "comanda"),
                 confidence=0.72),
    RelationRule("RULES", ("gobierna", "reina en", "gobierna en"), confidence=0.68),
    RelationRule("LIVES_IN", ("vive en", "viven en", "reside en", "residen en", "habita en"),
                 confidence=0.72, object_types=("Location",)),
    RelationRule("LOCATED_IN", ("se encuentra en", "esta situado en", "esta ubicado en",
                                "se halla en"),
                 confidence=0.7, object_types=("Location",)),
    RelationRule("PARENT_OF", ("es padre de", "es madre de"), confidence=0.75),
    RelationRule("CHILD_OF", ("es hijo de", "es hija de"), confidence=0.75),
    RelationRule("SIBLING_OF", ("es hermano de", "es hermana de"), confidence=0.72,
                 symmetric=True),
    RelationRule("ALLY_OF", ("es aliado de", "es aliada de", "se alia con"), confidence=0.7,
                 symmetric=True),
    RelationRule("ENEMY_OF", ("es enemigo de", "es enemiga de", "se enfrenta a"),
                 confidence=0.68, symmetric=True),
    RelationRule("SERVES", ("sirve a", "jura lealtad a", "obedece a"), confidence=0.68),
    RelationRule("OWNS", ("posee", "empuna", "porta"), confidence=0.62),
    RelationRule("KILLED", ("mato a", "asesino a", "dio muerte a"), confidence=0.75),
    RelationRule("FOUNDED", ("fundo", "fundo la", "fundo el"), confidence=0.7),
)

#: Marcas de negacion y epistemicas: viven en `cues.py`, compartidas con la
#: frontera de modelos. Se reexportan como globales del modulo para que las
#: pruebas de mutacion puedan romperlas aqui, que es donde se usan.
NEGATION_CUES: tuple[str, ...] = _cues.NEGATION_CUES
NEGATION_WINDOW = _cues.NEGATION_WINDOW
EPISTEMIC_CUES: tuple[tuple[str, str], ...] = _cues.EPISTEMIC_CUES

#: Coordinacion: si aparece entre un argumento y la frase de relacion, o dentro
#: del sintagma del argumento, la lectura deja de ser inequivoca. Las formas de
#: VARIAS palabras son imprescindibles: con solo `{y, o, e, u, ni}`, "Kael y
#: tambien Mira vive en Valdor" burlaba la guarda porque entre la coordinacion y
#: la mencion habia un token intercalado.
COORDINATION_TOKENS: frozenset = frozenset({"y", "e", "o", "u", "ni"})
COORDINATION_PHRASES: tuple[str, ...] = (
    "y tambien",
    "o tambien",
    "asi como",
    "ni siquiera",
    "junto a",
    "junto con",
    "ademas de",
    "al igual que",
    "tanto como",
    "o a",
    "o de",
    "y a",
)

#: Ventana (en tokens) donde se busca coordinacion alrededor de un argumento. No
#: basta con mirar el token pegado: la coordinacion casi nunca es adyacente.
COORDINATION_WINDOW = 4

#: Preposiciones que convierten a la mencion siguiente en MODIFICADOR, no en el
#: nucleo del sintagma: "El hermano **de** Kael vive en Valdor" no dice que Kael
#: viva en Valdor. Es el error de tomar el sujeto por proximidad.
MODIFIER_PREPOSITIONS: frozenset = frozenset({"de", "del", "por", "para", "segun", "sobre"})

_WEAK_PUNCT = (",", ";", ":", "(", ")", "—", "–")

#: Distancia maxima en tokens entre un argumento y la frase de relacion.
MAX_ARGUMENT_GAP = 2

#: Confianza de una mencion detectada por patron de titulo del perfil.
TITLE_PATTERN_CONFIDENCE = 0.6


@dataclass
class _MentionHit:
    """Coincidencia de mencion antes de convertirse en `EntityMention`."""

    surface: str
    start: int
    end: int
    first_token: int
    last_token: int
    entity_type: Optional[str]
    confidence: float
    canonical: str
    origin: str
    is_canonical: bool = True


def _title_hits(tokens: Sequence[Token], titles: Sequence[str]) -> list[_MentionHit]:
    """Patron `<titulo declarado> <Nombre Propio>` -> mencion de Character.

    Solo se dispara con titulos que el `GameProfile` declara explicitamente. Sin
    perfil no hay patron: no queremos un detector de mayusculas suelto, que es
    exactamente el tipo de heuristica que infla la cobertura y hunde la
    precision.
    """
    out: list[_MentionHit] = []
    for title in titles:
        needle = phrase_tokens(title)
        if not needle:
            continue
        for first, last in find_phrase(tokens, needle):
            nxt = last + 1
            if nxt >= len(tokens):
                continue
            name_tokens: list[Token] = []
            while nxt < len(tokens) and tokens[nxt].text[:1].isupper() and len(name_tokens) < 3:
                name_tokens.append(tokens[nxt])
                nxt += 1
            if not name_tokens:
                continue
            surface = " ".join(t.text for t in name_tokens)
            out.append(
                _MentionHit(
                    surface=surface,
                    start=name_tokens[0].start,
                    end=name_tokens[-1].end,
                    first_token=name_tokens[0].index,
                    last_token=name_tokens[-1].index,
                    entity_type="Character",
                    confidence=TITLE_PATTERN_CONFIDENCE,
                    canonical=surface,
                    origin="title_pattern",
                )
            )
    return out


def _lexicon_hits(matches: Sequence[LexiconMatch]) -> list[_MentionHit]:
    return [
        _MentionHit(
            surface=m.surface,
            start=m.start,
            end=m.end,
            first_token=m.first_token,
            last_token=m.last_token,
            entity_type=m.entry.entity_type,
            confidence=m.confidence,
            canonical=m.entry.canonical,
            origin=m.entry.origin,
            is_canonical=m.is_canonical,
        )
        for m in matches
    ]


def _dedup_hits(hits: Sequence[_MentionHit]) -> list[_MentionHit]:
    """Sin solapes: gana la coincidencia mas larga; empate, la de mas confianza."""
    ordered = sorted(hits, key=lambda h: (h.start, -(h.end - h.start), -h.confidence, h.surface))
    out: list[_MentionHit] = []
    for hit in ordered:
        if any(hit.start < prev.end and prev.start < hit.end for prev in out):
            continue
        out.append(hit)
    return out


def _sentence_of(sentences: Sequence[Sentence], token_index: int) -> Optional[Sentence]:
    for s in sentences:
        if s.contains_token(token_index):
            return s
    return None


def _raw_between(text: str, start: int, end: int) -> str:
    return text[max(0, start):max(0, end)]


def _coordination_between(tokens: Sequence[Token], lo: int, hi: int) -> bool:
    """Coordinacion (simple o de varias palabras) en `[lo, hi)`."""
    if lo >= hi:
        return False
    if any(tokens[i].norm in COORDINATION_TOKENS for i in range(lo, hi)):
        return True
    return any(
        find_phrase(tokens, phrase_tokens(p), lo=max(0, lo - 1), hi=min(len(tokens), hi + 1))
        for p in COORDINATION_PHRASES
    )


def _coordination_before(
    tokens: Sequence[Token], first_token: int, sentence_first: int, in_sentence: Sequence
) -> bool:
    """Coordinacion en la ventana previa al argumento, con otra mencion detras."""
    lo = max(sentence_first, first_token - COORDINATION_WINDOW)
    if not _coordination_between(tokens, lo, first_token):
        return False
    return any(hit.last_token < first_token for hit, _ in in_sentence)


def _coordination_after(
    tokens: Sequence[Token], last_token: int, sentence_last: int, in_sentence: Sequence
) -> bool:
    """Coordinacion en la ventana posterior al argumento, con otra mencion delante."""
    hi = min(sentence_last + 1, last_token + 1 + COORDINATION_WINDOW)
    if not _coordination_between(tokens, last_token + 1, hi):
        return False
    return any(hit.first_token > last_token for hit, _ in in_sentence)


def _is_modifier(
    tokens: Sequence[Token],
    first_token: int,
    sentence_first: int,
    *,
    after: Optional[int] = None,
) -> bool:
    """La mencion va precedida de preposicion: es modificador, no nucleo.

    Aproximacion honesta y deliberadamente burda (no hay analisis sintactico):
    "de Kael", "por Elara". Cuesta cobertura en construcciones legitimas, y esa
    es la direccion en la que este extractor prefiere equivocarse.

    `after` es el ultimo token de la frase de relacion emparejada. Si la
    preposicion previa CAE DENTRO de esa frase, no es un modificador: es el
    final del predicado ("es padre **de** Mira"). Sin esta excepcion, todas las
    relaciones persona->persona quedaban inertes.
    """
    prev = first_token - 1
    if prev < sentence_first or prev < 0:
        return False
    if after is not None and prev <= after:
        return False
    return tokens[prev].norm in MODIFIER_PREPOSITIONS


class DeterministicExtractor(Extractor):
    """Menciones por glosario/patrones y claims solo con evidencia inequivoca."""

    info = DETERMINISTIC_INFO

    def __init__(
        self,
        *,
        rules: Sequence[RelationRule] = RELATION_RULES,
        emit_abstentions: bool = True,
        attach_temporal: bool = True,
    ) -> None:
        self.rules = tuple(rules)
        self.emit_abstentions = emit_abstentions
        self.attach_temporal = attach_temporal

    def supports(self, episode: SourceEpisode) -> bool:
        return bool(episode.text)

    # -- menciones --------------------------------------------------------
    def _mentions(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        index: EvidenceIndex,
        out: ExtractionOutput,
    ) -> list[tuple[_MentionHit, str]]:
        lexicon: Optional[Lexicon] = ctx.lexicon
        hits: list[_MentionHit] = []
        if lexicon is not None:
            hits += _lexicon_hits(lexicon.find_all(index.tokens))
        titles = list(getattr(ctx.profile, "titles", ()) or ()) if ctx.profile else []
        if titles:
            hits += _title_hits(index.tokens, titles)
        hits = _dedup_hits(hits)

        # Primera pasada: id determinista de cada mencion, para poder enlazar
        # alias -> canonico DENTRO del episodio sin reescribir documentos.
        pending: list[tuple[_MentionHit, str]] = []
        first_canonical: dict[str, str] = {}
        from .base import make_id  # import local: evita ciclo en tiempo de import

        for hit in hits:
            mid = make_id(
                f"mention:{self.info.step}", episode.episode_id, hit.start, hit.end,
                hit.surface, index.basis,
            )
            pending.append((hit, mid))
            if hit.is_canonical:
                first_canonical.setdefault(hit.canonical, mid)

        emitted: list[tuple[_MentionHit, str]] = []
        for hit, mid in pending:
            anchor = index.anchor_span(hit.start, hit.end)
            if anchor is None:
                out.diagnostics.append(
                    Diagnostic(
                        "MENTION_WITHOUT_EVIDENCE", self.info.step, episode.episode_id,
                        f"{hit.surface!r} en [{hit.start},{hit.end}) no cae en ningun fragmento",
                    )
                )
                continue
            coref: list[str] = []
            if not hit.is_canonical:
                target = first_canonical.get(hit.canonical)
                if target and target != mid:
                    coref.append(target)
            types = (
                [{"type": hit.entity_type, "confidence": clamp(hit.confidence)}]
                if hit.entity_type
                else []
            )
            mention = build_mention(
                info=self.info,
                episode=episode,
                surface=hit.surface,
                start=hit.start,
                end=hit.end,
                evidence_fragment_ids=[anchor.fragment_id],
                type_candidates=types,
                confidence=clamp(hit.confidence),
                coreference_candidates=coref,
                basis=anchor.basis,
                mention_id=mid,
                metadata={
                    "match_origin": hit.origin,
                    "canonical_surface": hit.canonical,
                    "alias_match": not hit.is_canonical,
                },
            )
            if emit(mention, out, self.info, episode.episode_id):
                emitted.append((hit, mid))
        return emitted

    # -- claims -----------------------------------------------------------
    def _claims(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        index: EvidenceIndex,
        mentions: Sequence[tuple[_MentionHit, str]],
        out: ExtractionOutput,
    ) -> None:
        text = index.text or ""
        tokens = index.tokens
        profile_predicates = ctx.profile_predicates()
        for rule in self.rules:
            for needle in rule.token_phrases():
                if not needle:
                    continue
                for first, last in find_phrase(tokens, needle):
                    self._try_claim(
                        ctx, episode, index, mentions, rule, first, last, text,
                        profile_predicates, out,
                    )

    def _try_claim(  # noqa: C901 - una guarda por regla de precision, todas explicitas
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        index: EvidenceIndex,
        mentions: Sequence[tuple[_MentionHit, str]],
        rule: RelationRule,
        first: int,
        last: int,
        text: str,
        profile_predicates: set,
        out: ExtractionOutput,
    ) -> None:
        tokens = index.tokens
        sentence = _sentence_of(index.sentences, first)
        if sentence is None:
            return
        in_sentence = [
            (hit, mid)
            for hit, mid in mentions
            if sentence.contains_token(hit.first_token) and sentence.contains_token(hit.last_token)
        ]
        before = [x for x in in_sentence if x[0].last_token < first]
        after = [x for x in in_sentence if x[0].first_token > last]
        phrase_text = text[tokens[first].start:tokens[last].end]
        phrase_anchor = index.anchor_span(tokens[first].start, tokens[last].end)

        def abstain(codes: list[str], subj: list[str], obj: list[str]) -> None:
            if not self.emit_abstentions:
                out.diagnostics.append(
                    Diagnostic(codes[0], self.info.step, episode.episode_id, phrase_text)
                )
                return
            frag_ids = [phrase_anchor.fragment_id] if phrase_anchor else index.fragment_ids[:1]
            claim = abstention_claim(
                info=self.info,
                episode=episode,
                evidence_fragment_ids=frag_ids,
                reason_codes=codes,
                relation_phrase=phrase_text,
                subject_mentions=subj,
                object_mentions=obj,
                metadata={"rule_predicate": rule.predicate},
            )
            emit(claim, out, self.info, episode.episode_id)

        if not before or not after:
            out.diagnostics.append(
                Diagnostic(
                    "RELATION_PHRASE_WITHOUT_ARGUMENTS", self.info.step, episode.episode_id,
                    phrase_text,
                )
            )
            return
        subject_hit, subject_id = before[-1]
        object_hit, object_id = after[0]
        if subject_id == object_id:
            return
        if phrase_anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "RELATION_PHRASE_WITHOUT_EVIDENCE", self.info.step, episode.episode_id,
                    phrase_text,
                )
            )
            return

        codes: list[str] = []
        gap_before = first - subject_hit.last_token - 1
        gap_after = object_hit.first_token - last - 1
        if gap_before > MAX_ARGUMENT_GAP or gap_after > MAX_ARGUMENT_GAP:
            codes.append("ARGUMENT_TOO_FAR")
        if _coordination_between(tokens, subject_hit.last_token + 1, first):
            codes.append("COORDINATED_SUBJECT")
        if _coordination_between(tokens, last + 1, object_hit.first_token):
            codes.append("COORDINATED_OBJECT")
        # Coordinacion DENTRO del sintagma del argumento ("Elara y Kael viven en
        # Valdor", "Kael y tambien Mira vive..."): no esta entre el argumento y
        # el verbo, esta dentro del argumento. Sin esta comprobacion el extractor
        # se queda con el ultimo coordinado y afirma de UNO lo que el texto
        # afirma de DOS. Se mira una VENTANA, no el token pegado: la
        # coordinacion casi nunca es adyacente a la mencion.
        if _coordination_before(tokens, subject_hit.first_token, sentence.first_token, in_sentence):
            codes.append("COORDINATED_SUBJECT")
        if _coordination_after(tokens, object_hit.last_token, sentence.last_token, in_sentence):
            codes.append("COORDINATED_OBJECT")
        # Sujeto/objeto que en realidad son MODIFICADORES de otro nucleo:
        # "El hermano de Kael vive en Valdor" no dice nada de donde vive Kael.
        if _is_modifier(tokens, subject_hit.first_token, sentence.first_token):
            codes.append("SUBJECT_IS_MODIFIER")
        # El "de" que cierra la propia frase de relacion ("es padre **de**",
        # "es aliado **de**") NO convierte al objeto en modificador: es parte
        # del predicado. Sin esta excepcion, todas las relaciones
        # persona->persona (PARENT_OF, CHILD_OF, SIBLING_OF, ALLY_OF, ENEMY_OF)
        # quedaban inertes: se abstenian siempre.
        if _is_modifier(tokens, object_hit.first_token, sentence.first_token, after=last):
            codes.append("OBJECT_IS_MODIFIER")
        # Varias menciones antes de la frase: el sujeto se estaria eligiendo por
        # proximidad. En la duda, abstencion.
        if len(before) > 1:
            codes.append("MULTIPLE_SUBJECT_CANDIDATES")
        left_raw = _raw_between(text, subject_hit.end, tokens[first].start)
        right_raw = _raw_between(text, tokens[last].end, object_hit.start)
        if any(p in left_raw or p in right_raw for p in _WEAK_PUNCT):
            codes.append("PUNCTUATION_BETWEEN_ARGUMENTS")
        if profile_predicates and rule.predicate not in profile_predicates:
            codes.append("PREDICATE_NOT_IN_PROFILE")
        if (
            ctx.profile is not None
            and subject_hit.entity_type
            and object_hit.entity_type
            and not ctx.profile.allows(rule.predicate, subject_hit.entity_type, object_hit.entity_type)
            and rule.predicate in profile_predicates
        ):
            codes.append("TYPE_INCOMPATIBLE_WITH_PROFILE")
        if rule.object_types and object_hit.entity_type and object_hit.entity_type not in rule.object_types:
            codes.append("OBJECT_TYPE_MISMATCH")
        if rule.subject_types and subject_hit.entity_type and subject_hit.entity_type not in rule.subject_types:
            codes.append("SUBJECT_TYPE_MISMATCH")

        if codes:
            abstain(codes, [subject_id], [object_id])
            return

        # --- lecturas del contexto: negacion, factividad, epistemicidad ---
        negated = any(
            tokens[i].norm in NEGATION_CUES
            for i in range(max(sentence.first_token, first - NEGATION_WINDOW), first)
        )
        cues: list[str] = []
        hint = "ASSERTED"
        for cue, mapped in EPISTEMIC_CUES:
            needle = phrase_tokens(cue)
            if needle and find_phrase(tokens, needle, lo=sentence.first_token, hi=sentence.last_token + 1):
                cues.append(cue)
                if hint == "ASSERTED":
                    hint = mapped

        # NO-FACTIVIDAD. Sin esta guarda, "Si Kael vive en Valdor...", "¿Kael
        # vive en Valdor?" y "Es falso que Kael viva en Valdor" salian los tres
        # como ASSERTED con review_required=False: el extractor afirmaba
        # exactamente lo que el texto se negaba a afirmar.
        verdict = _cues.analyze_context(
            text[sentence.start:sentence.end],
            tokens,
            lo=sentence.first_token,
            hi=sentence.last_token + 1,
            focus=first,
        )
        if _cues.CODE_FALSITY in verdict.reason_codes or _cues.CODE_INTERROGATIVE in verdict.reason_codes:
            # El texto niega la verdad del hecho o pregunta por el. No hay nada
            # que proponer: solo constancia de que aqui habia algo.
            abstain(
                [_cues.CODE_NON_FACTIVE, *verdict.reason_codes], [subject_id], [object_id]
            )
            return
        if _cues.CODE_CONDITIONAL in verdict.reason_codes:
            hint = "HYPOTHETICAL"
            cues.extend(c for c in verdict.cues if c not in cues)
        temporal = []
        extra_trace = []
        if self.attach_temporal:
            matches = extract_temporal_expressions(
                index, calendars=ctx.calendars(), lo=sentence.start, hi=sentence.end
            )
            temporal = [m.to_contract() for m in matches]
            if temporal:
                extra_trace.append(
                    TEMPORAL_INFO.trace_entry(["temporal_expressions"])
                )

        confidence = clamp(
            rule.confidence * min(subject_hit.confidence, object_hit.confidence) / 0.9
        )
        confidence = min(confidence, 0.9)
        if hint != "ASSERTED":
            confidence = clamp(confidence * 0.8)
        review = bool(
            negated
            or hint != "ASSERTED"
            or confidence < 0.6
            or low_quality(episode)
            or phrase_anchor.ambiguous
        )
        alternatives = []
        if rule.symmetric:
            alternatives.append(
                {
                    "predicate": rule.predicate,
                    "direction": "UNDIRECTED",
                    "confidence": clamp(confidence * 0.9),
                    "reason_codes": ["SYMMETRIC_PREDICATE"],
                }
            )
        fragments = [
            phrase_anchor.fragment_id,
            *index.covering(subject_hit.start, subject_hit.end),
            *index.covering(object_hit.start, object_hit.end),
        ]
        claim = build_claim(
            info=self.info,
            episode=episode,
            evidence_fragment_ids=fragments,
            subject_mentions=[subject_id],
            object_mentions=[object_id],
            relation_phrase=phrase_text,
            predicate_candidates=[{"predicate": rule.predicate, "confidence": confidence}],
            direction_candidates=[{"direction": rule.direction, "confidence": confidence}],
            temporal_expressions=temporal,
            negated=negated,
            epistemic_cues=cues,
            epistemic_status_hint=hint,
            confidence=confidence,
            alternatives=alternatives,
            abstained=False,
            review_required=review,
            extra_trace=extra_trace,
            metadata={
                "rule_phrases": list(rule.phrases),
                "quality_score": episode.quality.get("score"),
            },
        )
        emit(claim, out, self.info, episode.episode_id)

    # -- interfaz ---------------------------------------------------------
    def extract_episode(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        index = ctx.index_of(episode)
        if not index.has_text:
            return out
        mentions = self._mentions(ctx, episode, index, out)
        if mentions:
            self._claims(ctx, episode, index, mentions, out)
        return out


__all__ = [
    "COORDINATION_TOKENS",
    "DETERMINISTIC_INFO",
    "DETERMINISTIC_STEP",
    "EPISTEMIC_CUES",
    "MAX_ARGUMENT_GAP",
    "NEGATION_CUES",
    "RELATION_RULES",
    "DeterministicExtractor",
    "RelationRule",
]

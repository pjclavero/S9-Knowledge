# -*- coding: utf-8 -*-
"""Cascada de senales y decision de identidad.

Estructura:

  workspace (filtro DURO, siempre)
      -> pasos GENERADORES en orden configurable, cada uno emite candidatos con
         score y motivo:  exact -> history -> alias -> glossary -> similarity
      -> pasos MODIFICADORES, siempre: context (bonus), types (bonus/penalizacion)
      -> decision con umbrales explicitos y desempate totalmente determinista

Dos invariantes NO son heuristicas ponderadas sino reglas, y se comprueban en la
decision, no en los pesos:

  1. WORKSPACE: un candidato de otro workspace jamas entra en la cascada. Se
     aplica en el catalogo, en el glosario y en el historial, por separado.
  2. TIPOS: no hay enlace entre tipos incompatibles; lo que hay es `REVIEW`.

Precision importante sobre el segundo (corregida tras revision independiente):
el paso `types` SI se puede desactivar via `disabled_steps` — `__post_init__` lo
acepta, es un paso ablacionable como cualquier otro — y desactivarlo quita el
bonus y la penalizacion. Lo que NO desaparece es el invariante: el conflicto se
detecta igual (`ScoredCandidate.type_conflict`) y `decide()` lo compara contra
`type_override_score` usando la puntuacion RECORTADA a [0,1], que es la unica
acotada. Compararlo contra la puntuacion sin recortar era un agujero real: con
`disabled_steps={"types"}` y bonus de contexto, un candidato llegaba a 1.12 y
superaba un umbral de 1.01 pensado para ser inalcanzable, enlazando una
`Location` con una `Faction`. Ver `docs/v3/04-resolution.md` §4.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .catalog import CatalogEntity, EntityCatalog
from .config import ResolutionConfig
from .glossary import GlossarySource
from .history import HistoryEntry, ResolutionHistory
from .normalization import normalize_surface
from .similarity import SurfaceSimilarity

# -- Codigos de razon -------------------------------------------------------
# Estables, enumerables y nunca texto libre (patron `reason_code` del contrato).
R_EXACT_NAME = "EXACT_NAME"
R_EXACT_ALIAS = "EXACT_ALIAS"
R_GLOSSARY_CANONICAL = "GLOSSARY_CANONICAL"
R_GLOSSARY_VARIANT = "GLOSSARY_VARIANT"
R_SURFACE_SIMILARITY = "SURFACE_SIMILARITY"
R_CONTEXT_SUPPORT = "CONTEXT_SUPPORT"
R_HISTORY_SESSION = "HISTORY_SESSION"
R_TYPE_COMPATIBLE = "TYPE_COMPATIBLE"
R_TYPE_CONFLICT = "TYPE_CONFLICT"
R_TYPE_UNKNOWN = "TYPE_UNKNOWN"
R_WORKSPACE_ISOLATED = "WORKSPACE_ISOLATED"
R_NO_CANDIDATE = "NO_CANDIDATE"
R_AMBIGUOUS = "AMBIGUOUS_CANDIDATES"
R_WEAK_MATCH = "WEAK_MATCH"
R_LOW_SUPPORT = "LOW_SUPPORT"
R_STRONG_MATCH = "STRONG_MATCH"
R_UNTYPED_MENTION = "UNTYPED_MENTION"
R_SURFACE_TOO_SHORT = "SURFACE_TOO_SHORT"
R_NEAR_MISS = "NEAR_MISS_CANDIDATE"
#: La identidad del candidato solo consta por el historial de sesion: el
#: catalogo del workspace no la conoce. Delata los enlaces a provisionales.
R_FROM_HISTORY = "FROM_HISTORY"
#: La confianza reportada se ha rebajado a la de la decision original heredada
#: del historial, en vez de a la del ECO de esa decision. Ver docs §10 (H3).
R_INHERITED_CONFIDENCE = "INHERITED_CONFIDENCE"
R_DERIVED_ID = "DERIVED_ID"
R_ID_COLLISION = "PROVISIONAL_ID_COLLISION"


# -- Estructuras ------------------------------------------------------------
@dataclass(frozen=True)
class SignalHit:
    """Una senal concreta a favor de un candidato."""

    entity_id: str
    step: str
    score: float
    reason_code: str
    detail: str | None = None
    #: Confianza ORIGINAL de la decision que produjo esta senal, cuando la
    #: senal es un eco de una decision anterior (hoy: el historial). `None`
    #: para senales que miden algo del presente.
    origin_confidence: float | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    """Candidato con su puntuacion final y toda su justificacion."""

    entity_id: str
    entity_type: str | None
    base_score: float
    adjustment: float
    #: Puntuacion recortada a [0,1]. Es la que se REPORTA como `confidence`.
    score: float
    #: Puntuacion SIN recortar. Es la que se COMPARA.
    #:
    #: La distincion importa: si se ordenase por la recortada, dos candidatos de
    #: 0.98 y 1.10 empatarian en 1.0 y el bonus que los separa se evaporaria
    #: contra el techo. El techo es una convencion de presentacion del contrato
    #: (`confidence` vive en [0,1]), no una propiedad de la comparacion.
    raw_score: float
    reason_codes: tuple[str, ...]
    signals: tuple[SignalHit, ...]
    type_conflict: bool
    from_history: bool = False
    #: Confianza de la decision original si TODA la evidencia generadora de
    #: este candidato es historial. `None` si alguna senal mide el presente.
    inherited_confidence: float | None = None

    @property
    def sort_key(self) -> tuple[float, str]:
        """Clave de orden TOTAL: score descendente, luego `entity_id` ascendente.

        El redondeo a 6 decimales es deliberado: sin el, dos candidatos que
        deberian empatar podrian diferir en el ultimo bit de un float y el
        "desempate determinista" dependeria de la aritmetica en coma flotante.
        """
        return (-round(self.raw_score, 6), self.entity_id)


@dataclass
class CascadeContext:
    """Todo lo que la cascada necesita saber de un grupo de menciones."""

    workspace: str
    surfaces: tuple[str, ...]
    normalized_surfaces: tuple[str, ...]
    mention_type: str | None
    mention_confidence: float
    context_entity_ids: tuple[str, ...] = ()
    entities: tuple[CatalogEntity, ...] = ()

    @property
    def primary_surface(self) -> str:
        """Superficie de referencia del grupo.

        La mas larga (mas informativa) y, a igualdad, la primera en orden
        alfabetico: `"Daiki"` describe la identidad mejor que `"el"`. El criterio
        es determinista y no depende del orden de las menciones.
        """
        forms = [s for s in self.normalized_surfaces if s]
        if not forms:
            return ""
        return sorted(forms, key=lambda s: (-len(s), s))[0]


@dataclass
class CascadeResult:
    candidates: tuple[ScoredCandidate, ...]
    steps_run: tuple[str, ...]
    short_circuited: bool
    discarded_other_workspace: int


# -- Tipos ------------------------------------------------------------------
def types_compatible(mention_type: str | None, entity_type: str | None) -> bool:
    """Compatibilidad de tipos.

    Regla deliberadamente simple: `None` (no me atrevo a tipar) es compatible
    con todo — la ausencia de tipo no es una afirmacion —, y dos tipos
    conocidos son compatibles solo si son el mismo. No hay jerarquia de tipos en
    el catalogo congelado (seis tipos planos), asi que inventar una aqui seria
    inventar ontologia.
    """
    if mention_type is None or entity_type is None:
        return True
    return mention_type == entity_type


# -- Filtro de workspace (INVARIANTE 1) -------------------------------------
def filter_workspace(
    entities: Sequence[CatalogEntity], workspace: str
) -> tuple[CatalogEntity, ...]:
    """Deja SOLO las entidades del workspace pedido.

    Se aplica aunque el catalogo ya prometa filtrar. No es redundancia inutil:
    el aislamiento entre bovedas es una garantia de privacidad, y una garantia
    que depende de que un colaborador externo haya escrito bien su consulta no
    es una garantia. Un homonimo en otra campana NUNCA es candidato.
    """
    return tuple(e for e in entities if e.workspace == workspace)


def history_entry_allowed(
    entry: "HistoryEntry", ctx: "CascadeContext", catalog: EntityCatalog | None
) -> bool:
    """Cerradura de workspace del HISTORIAL (INVARIANTE 1, segunda puerta).

    Existe porque la primera no bastaba. Que el indice del historial este
    tecleado por `(workspace, superficie)` protege del uso normal, pero no de
    una entrada mal construida ni de una implementacion de `lookup` que ignore
    el argumento: en ambos casos salia un `LINK_EXISTING` entre bovedas. Es el
    equivalente exacto de `filter_workspace` para el catalogo, y esta aqui por
    el mismo motivo — una garantia que depende de que nadie se equivoque aguas
    arriba no es una garantia.

    Dos comprobaciones:

    1. la entrada declara el workspace que se esta resolviendo;
    2. el catalogo, SI puede responder, no atribuye esa entidad a otra boveda.
       `locate` devolviendo `None` significa "no me consta" y no bloquea: una
       provisional recien creada no esta en el catalogo y es legitima.
    """
    if entry.workspace != ctx.workspace:
        return False
    if catalog is not None:
        owner = catalog.locate(entry.entity_id)
        if owner is not None and owner != ctx.workspace:
            return False
    return True


# -- Pasos generadores ------------------------------------------------------
def step_exact(ctx: CascadeContext, cfg: ResolutionConfig, **_: object) -> list[SignalHit]:
    """Coincidencia exacta con el nombre canonico normalizado."""
    hits: list[SignalHit] = []
    surfaces = set(ctx.normalized_surfaces)
    for entity in ctx.entities:
        if entity.normalized_name and entity.normalized_name in surfaces:
            hits.append(
                SignalHit(entity.entity_id, "exact", cfg.exact_score, R_EXACT_NAME,
                          entity.normalized_name)
            )
    return hits


def step_alias(ctx: CascadeContext, cfg: ResolutionConfig, **_: object) -> list[SignalHit]:
    """Coincidencia exacta con un alias declarado de la entidad."""
    hits: list[SignalHit] = []
    surfaces = set(ctx.normalized_surfaces)
    for entity in ctx.entities:
        matched = sorted(entity.normalized_aliases & surfaces)
        if matched:
            hits.append(
                SignalHit(entity.entity_id, "alias", cfg.alias_score, R_EXACT_ALIAS, matched[0])
            )
    return hits


def step_glossary(
    ctx: CascadeContext,
    cfg: ResolutionConfig,
    *,
    glossary: GlossarySource | None = None,
    **_: object,
) -> list[SignalHit]:
    """El glosario traduce la superficie observada a un termino canonico.

    Es el unico paso que sabe que `"Daiqui"` (forma erronea de ASR) apunta a
    `"Daiki"`. Las formas degradadas (`spoken_form`, `error_form`) puntuan menos
    que las escritas: son mas utiles y a la vez menos fiables.
    """
    if glossary is None:
        return []
    hits: list[SignalHit] = []
    seen: set[tuple[str, str]] = set()
    for surface in ctx.normalized_surfaces:
        if not surface:
            continue
        for hit in glossary.lookup(ctx.workspace, surface):
            term = hit.normalized_term
            if not term:
                continue
            score = cfg.glossary_variant_score if hit.degraded else cfg.glossary_canonical_score
            reason = R_GLOSSARY_VARIANT if hit.degraded else R_GLOSSARY_CANONICAL
            for entity in ctx.entities:
                if term not in entity.all_normalized_forms():
                    continue
                key = (entity.entity_id, reason)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    SignalHit(entity.entity_id, "glossary", score, reason, hit.canonical_term)
                )
    return hits


def step_similarity(
    ctx: CascadeContext,
    cfg: ResolutionConfig,
    *,
    similarity: SurfaceSimilarity | None = None,
    **_: object,
) -> list[SignalHit]:
    """Similitud de superficie (por defecto ortografica, no semantica).

    Techo `similarity_weight` < `link_min_score`: esta senal SOLA nunca enlaza.
    """
    if similarity is None:
        return []
    hits: list[SignalHit] = []
    for entity in ctx.entities:
        forms = sorted(entity.all_normalized_forms())
        if not forms:
            continue
        best = 0.0
        for surface in ctx.normalized_surfaces:
            value = similarity.best_score(surface, forms)
            if value > best:
                best = value
        if best >= cfg.similarity_min:
            score = round(cfg.similarity_weight * best, 6)
            hits.append(
                SignalHit(entity.entity_id, "similarity", score, R_SURFACE_SIMILARITY,
                          f"{similarity.name}:{best:.4f}")
            )
    return hits


def step_history(
    ctx: CascadeContext,
    cfg: ResolutionConfig,
    *,
    history: ResolutionHistory | None = None,
    catalog: EntityCatalog | None = None,
    **_: object,
) -> list[SignalHit]:
    """Identidades ya fijadas en esta sesion para las mismas superficies.

    Puede introducir candidatos que NO estan en el catalogo: es el caso de una
    provisional creada hace dos menciones. Ese es justamente el objetivo — la
    segunda mencion de `"Ilya"` va a la misma identidad que la primera.

    CERRADURA DE WORKSPACE (anadida tras revision independiente). Que la clave
    del indice empiece por el workspace NO era garantia suficiente: bastaba una
    entrada cuyo `workspace` no coincidiera con su clave, o una implementacion
    de `lookup` que ignorase el argumento, para producir un `LINK_EXISTING`
    entre bovedas. Ahora se comprueban DOS cosas sobre cada entrada devuelta:

      1. que la entrada declare el workspace que se ha pedido;
      2. que la entidad a la que apunta no pertenezca, segun el catalogo, a otra
         boveda (`EntityCatalog.locate`). Si el catalogo no sabe responder,
         devuelve `None` y no se inventa una contradiccion: una entidad ausente
         del catalogo es lo normal para una provisional recien creada.
    """
    if history is None:
        return []
    hits: list[SignalHit] = []
    seen: set[str] = set()
    for surface in ctx.normalized_surfaces:
        entry = history.lookup(ctx.workspace, surface)
        if entry is None or entry.entity_id in seen:
            continue
        if not history_entry_allowed(entry, ctx, catalog):
            continue
        seen.add(entry.entity_id)
        hits.append(
            SignalHit(
                entry.entity_id,
                "history",
                cfg.history_score,
                R_HISTORY_SESSION,
                f"{entry.resolution_id}|{entry.action}|{entry.confidence:.6f}",
                origin_confidence=float(entry.confidence),
            )
        )
    return hits


GENERATORS = {
    "exact": step_exact,
    "alias": step_alias,
    "glossary": step_glossary,
    "similarity": step_similarity,
    "history": step_history,
}


# -- Ejecucion de la cascada ------------------------------------------------
def run_cascade(
    ctx: CascadeContext,
    cfg: ResolutionConfig,
    *,
    glossary: GlossarySource | None = None,
    similarity: SurfaceSimilarity | None = None,
    history: ResolutionHistory | None = None,
    catalog: EntityCatalog | None = None,
) -> CascadeResult:
    """Ejecuta los pasos y devuelve los candidatos puntuados y ordenados."""
    all_entities = tuple(ctx.entities)
    scoped = filter_workspace(all_entities, ctx.workspace)
    discarded = len(all_entities) - len(scoped)
    ctx.entities = scoped

    by_entity: dict[str, list[SignalHit]] = {}
    steps_run: list[str] = []
    short_circuited = False

    for name in cfg.active_generators():
        step = GENERATORS[name]
        steps_run.append(name)
        for hit in step(
            ctx, cfg, glossary=glossary, similarity=similarity, history=history, catalog=catalog
        ):
            by_entity.setdefault(hit.entity_id, []).append(hit)
        if cfg.short_circuit and _can_short_circuit(by_entity, cfg):
            short_circuited = True
            break

    # Los modificadores necesitan el tipo del candidato; para candidatos que
    # vienen del historial y no estan en el catalogo, el tipo se toma de la
    # entrada del historial.
    types = {e.entity_id: e.entity_type for e in scoped}
    if history is not None:
        for entry in history.entries():
            if entry.workspace == ctx.workspace:
                types.setdefault(entry.entity_id, entry.entity_type)
    known_ids = {e.entity_id for e in scoped}

    modifiers = cfg.active_modifiers()
    candidates: list[ScoredCandidate] = []
    for entity_id in sorted(by_entity):
        signals = tuple(sorted(by_entity[entity_id], key=lambda h: (-h.score, h.step)))
        base = max(h.score for h in signals)
        # Confianza heredada: solo si NADA fuera del historial sostiene a este
        # candidato. Si el nombre exacto tambien coincide, la identidad se
        # sostiene por si sola y no hay nada que heredar.
        inherited = None
        if signals and all(h.step == "history" for h in signals):
            values = [h.origin_confidence for h in signals if h.origin_confidence is not None]
            inherited = min(values) if values else None
        entity_type = types.get(entity_id)
        reasons = _ordered_reasons(signals)
        adjustment = 0.0
        conflict = not types_compatible(ctx.mention_type, entity_type)

        if "context" in modifiers and entity_id in set(ctx.context_entity_ids):
            adjustment += cfg.context_bonus
            reasons.append(R_CONTEXT_SUPPORT)

        if "types" in modifiers:
            if ctx.mention_type is None or entity_type is None:
                reasons.append(R_TYPE_UNKNOWN)
            elif conflict:
                adjustment -= cfg.type_conflict_penalty
                reasons.append(R_TYPE_CONFLICT)
            else:
                adjustment += cfg.type_match_bonus
                reasons.append(R_TYPE_COMPATIBLE)
        elif conflict:
            # El paso esta ablacionado, pero el conflicto se sigue senalando:
            # la decision NO puede quedarse ciega a los tipos.
            reasons.append(R_TYPE_CONFLICT)

        if entity_id not in known_ids:
            reasons.append(R_FROM_HISTORY)

        raw = round(max(0.0, base + adjustment), 6)
        score = round(min(1.0, raw), 6)
        candidates.append(
            ScoredCandidate(
                entity_id=entity_id,
                entity_type=entity_type,
                base_score=round(base, 6),
                adjustment=round(adjustment, 6),
                score=score,
                raw_score=raw,
                reason_codes=tuple(dict.fromkeys(reasons)),
                signals=signals,
                type_conflict=conflict,
                from_history=entity_id not in known_ids,
                inherited_confidence=inherited,
            )
        )

    candidates.sort(key=lambda c: c.sort_key)
    return CascadeResult(
        candidates=tuple(candidates),
        steps_run=tuple(steps_run),
        short_circuited=short_circuited,
        discarded_other_workspace=discarded,
    )


def _can_short_circuit(by_entity: dict[str, list[SignalHit]], cfg: ResolutionConfig) -> bool:
    """Corta la cascada si hay UN unico candidato y es suficientemente fuerte.

    ATENCION — el cortocircuito NO es neutro, y decir lo contrario era falso
    (hallazgo H4 de la revision independiente). Cortar en el paso `i` significa
    no ejecutar los pasos `i+1..n`, y esos pasos pueden descubrir un SEGUNDO
    candidato que habria activado la regla de ambiguedad. Caso concreto y
    probado: un candidato del historial (0.97) corta antes de `alias`, y la
    cascada completa habria encontrado ahi un rival a 0.95 — margen 0.02, por
    debajo de `ambiguity_margin` — devolviendo `REVIEW` en vez de
    `LINK_EXISTING`.

    Con los pesos por defecto NO existe ningun corte demostrablemente neutro:
    la cota superior de lo que un paso posterior puede alcanzar (0.97 del
    historial, o 0.95 de alias/glosario, mas hasta 0.15 de bonus) siempre queda
    a menos de `ambiguity_margin` del mejor candidato posible. Eso no es un
    defecto del cortocircuito: es lo que dicen los pesos, que un alias es casi
    tan bueno como un nombre exacto.

    Por eso `short_circuit` viene DESACTIVADO por defecto: en un resolutor cuya
    consigna es "ante la duda, REVIEW", el defecto no puede ser la variante que
    convierte dudas en enlaces. Queda como palanca explicita de coste, medida y
    documentada (`docs/v3/04-resolution.md` §2.4).
    """
    strong = [eid for eid, hits in by_entity.items()
              if max(h.score for h in hits) >= cfg.short_circuit_score]
    return len(strong) == 1 and len(by_entity) == 1


def _ordered_reasons(signals: Sequence[SignalHit]) -> list[str]:
    return list(dict.fromkeys(h.reason_code for h in signals))


# -- Decision ---------------------------------------------------------------
@dataclass(frozen=True)
class Decision:
    """Que hacer con el grupo de menciones, y por que."""

    action: str
    selected_entity_id: str | None
    confidence: float
    reason_codes: tuple[str, ...]
    #: Candidatos considerados, en orden determinista.
    candidate_entity_ids: tuple[str, ...] = ()


def decide(
    result: CascadeResult, ctx: CascadeContext, cfg: ResolutionConfig
) -> Decision:
    """Aplica los umbrales configurados sobre los candidatos ya puntuados.

    Orden de las comprobaciones (importa, y esta pensado):

    1. Sin candidatos -> crear (nueva o provisional).
    2. Conflicto de tipos en el mejor candidato -> `REVIEW`, salvo senal fuerte.
       Va ANTES del umbral de enlace porque un `Character` que puntua 0.99
       contra un `Location` no es un enlace bueno, es un enlace peligroso.
    3. Score por debajo del minimo de revision -> ni siquiera merece un humano:
       crear.
    4. Score por debajo del umbral de enlace -> `REVIEW` (coincidencia debil).
    5. Margen insuficiente con el segundo -> `REVIEW` (ambiguedad).
    6. Enlazar.
    """
    ranked = result.candidates
    candidate_ids = tuple(c.entity_id for c in ranked)

    if not ranked:
        return _decide_create(
            ctx, cfg, extra_reasons=(R_NO_CANDIDATE,), candidate_ids=(), best_rival=0.0
        )

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    # `score` (RECORTADO a [0,1]) y no `raw_score`: `type_override_score` es una
    # cota pensada para ser inalcanzable, y solo lo es frente a una magnitud
    # acotada. `raw_score` puede llegar a 1.15 sumando bonus, y contra eso un
    # umbral de 1.01 no acota nada. Hallazgo de la revision independiente.
    if best.type_conflict and best.score < cfg.type_override_score:
        return Decision(
            action="REVIEW",
            selected_entity_id=None,
            confidence=best.score,
            reason_codes=_reasons(R_TYPE_CONFLICT, *best.reason_codes),
            candidate_entity_ids=candidate_ids,
        )

    if best.raw_score < cfg.review_min_score:
        return _decide_create(
            ctx,
            cfg,
            extra_reasons=(R_LOW_SUPPORT,),
            candidate_ids=candidate_ids,
            best_rival=best.raw_score,
        )

    if best.raw_score < cfg.link_min_score:
        return Decision(
            action="REVIEW",
            selected_entity_id=None,
            confidence=best.score,
            reason_codes=_reasons(R_WEAK_MATCH, *best.reason_codes),
            candidate_entity_ids=candidate_ids,
        )

    if second is not None and round(best.raw_score - second.raw_score, 6) < cfg.ambiguity_margin:
        return Decision(
            action="REVIEW",
            selected_entity_id=None,
            confidence=best.score,
            reason_codes=_reasons(R_AMBIGUOUS, *best.reason_codes, *second.reason_codes),
            candidate_entity_ids=candidate_ids,
        )

    # Contra el LAVADO DE CONFIANZA (hallazgo H3 de la revision independiente).
    # `history_score` es plano: da 0.97 tanto al eco de un `LINK_EXISTING` de
    # 0.99 como al de una provisional de 0.45. Sin esto, la segunda mencion de
    # una entidad dudosa saldria con `confidence` 1.00 y el contrato no
    # guardaria ni rastro de que toda su fuerza venia de una duda anterior.
    # La identidad heredada sigue siendo la correcta (ese es el objetivo del
    # historial); lo que no puede heredarse es la CERTEZA.
    confidence = best.score
    reasons = [R_STRONG_MATCH, *best.reason_codes]
    if best.inherited_confidence is not None and best.inherited_confidence < confidence:
        confidence = round(best.inherited_confidence, 6)
        reasons.append(R_INHERITED_CONFIDENCE)

    return Decision(
        action="LINK_EXISTING",
        selected_entity_id=best.entity_id,
        confidence=confidence,
        reason_codes=_reasons(*reasons),
        candidate_entity_ids=candidate_ids,
    )


def _decide_create(
    ctx: CascadeContext,
    cfg: ResolutionConfig,
    *,
    extra_reasons: tuple[str, ...],
    candidate_ids: tuple[str, ...],
    best_rival: float,
) -> Decision:
    """Nueva canonica o provisional.

    `CREATE_NEW` exige TODO a la vez: tipo conocido, confianza alta de la
    mencion, superficie con cuerpo suficiente y NINGUN candidato que se le
    parezca ni de lejos. Cualquier duda cae en `CREATE_PROVISIONAL`, que es
    reversible; un nodo canonico fabricado a partir de un error de ASR, no.
    """
    surface = ctx.primary_surface
    reasons = list(extra_reasons)

    too_short = len(surface) < cfg.create_new_min_surface_chars
    if too_short:
        reasons.append(R_SURFACE_TOO_SHORT)
    if ctx.mention_type is None:
        reasons.append(R_UNTYPED_MENTION)
    near_miss = best_rival > cfg.create_new_max_rival_score
    if near_miss:
        reasons.append(R_NEAR_MISS)

    eligible = (
        cfg.allow_create_new
        and ctx.mention_type is not None
        and not too_short
        and not near_miss
        and ctx.mention_confidence >= cfg.create_new_min_confidence
    )
    if eligible:
        return Decision(
            action="CREATE_NEW",
            selected_entity_id=None,
            confidence=round(min(1.0, ctx.mention_confidence), 6),
            reason_codes=_reasons(*reasons, R_DERIVED_ID),
            candidate_entity_ids=candidate_ids,
        )
    confidence = round(min(ctx.mention_confidence, cfg.provisional_confidence_cap), 6)
    return Decision(
        action="CREATE_PROVISIONAL",
        selected_entity_id=None,
        confidence=confidence,
        reason_codes=_reasons(*reasons, R_DERIVED_ID),
        candidate_entity_ids=candidate_ids,
    )


def _reasons(*codes: str) -> tuple[str, ...]:
    """Codigos sin duplicados, conservando el primer orden de aparicion."""
    return tuple(dict.fromkeys(c for c in codes if c))


__all__ = [
    "SignalHit",
    "ScoredCandidate",
    "CascadeContext",
    "CascadeResult",
    "Decision",
    "GENERATORS",
    "types_compatible",
    "filter_workspace",
    "history_entry_allowed",
    "run_cascade",
    "decide",
]

# -*- coding: utf-8 -*-
"""`EntityResolver`: de `EntityMention` a `EntityResolution`.

Frontera del subsistema. Todo lo que entra son datos (menciones + catalogo +
glosario + historial); todo lo que sale es un documento del contrato congelado
`entity-resolution/v3-internal-v1`. Este modulo NO escribe en Neo4j, no llama a
proveedores, no genera timestamps y no toca V1/V2: `review/resolver.py` se deja
exactamente como esta.

Un `EntityResolver` es reutilizable y su unico estado mutable es el historial,
que se puede inspeccionar e invalidar desde fuera.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ..contracts import (
    CONTRACT_VERSION,
    EntityMention,
    EntityResolution,
    Provider,
    provider_step,
)
from . import cascade as _cascade
from .cascade import CascadeContext, Decision, decide, run_cascade
from .catalog import EntityCatalog, InMemoryEntityCatalog
from .config import DEFAULT_CONFIG, ResolutionConfig
from .errors import ResolutionInputError
from .glossary import GlossarySource, NullGlossarySource
from .history import ResolutionHistory
from .normalization import normalize_surface
from .provisional import derive_entity_id, derive_resolution_id
from .similarity import SurfaceSimilarity, TrigramJaccardSimilarity


@dataclass(frozen=True)
class ResolutionRequest:
    """Un grupo de menciones que se cree que designan la MISMA entidad.

    Agrupar menciones (correferencia) NO es tarea del resolutor: llega hecho
    desde el extractor. El resolutor decide a QUE identidad corresponde el
    grupo, no como se formo el grupo.
    """

    mentions: tuple[EntityMention, ...]
    #: Entidades ya presentes en el contexto (episodio/escena). Solo dan bonus.
    context_entity_ids: tuple[str, ...] = ()
    game_profile: str = "generic"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mentions", tuple(self.mentions))
        object.__setattr__(self, "context_entity_ids", tuple(self.context_entity_ids))
        if not self.mentions:
            raise ResolutionInputError("una peticion de resolucion sin menciones no existe")

    @classmethod
    def of(cls, *mentions: EntityMention, **kwargs: Any) -> "ResolutionRequest":
        return cls(mentions=tuple(mentions), **kwargs)


@dataclass(frozen=True)
class ResolutionOutcome:
    """Documento emitido + toda la traza que lo explica."""

    resolution: EntityResolution
    candidates: tuple[Any, ...]
    steps_run: tuple[str, ...]
    short_circuited: bool
    discarded_other_workspace: int
    decision: Decision

    @property
    def action(self) -> str:
        return self.resolution.action

    @property
    def entity_id(self) -> str | None:
        return self.resolution.entity_id()


class EntityResolver:
    """Resolutor de identidad basado en cascada de senales."""

    def __init__(
        self,
        catalog: EntityCatalog | None = None,
        *,
        config: ResolutionConfig | None = None,
        glossary: GlossarySource | None = None,
        similarity: SurfaceSimilarity | None = None,
        history: ResolutionHistory | None = None,
    ) -> None:
        self.catalog = catalog if catalog is not None else InMemoryEntityCatalog()
        self.config = config if config is not None else DEFAULT_CONFIG
        self.glossary = glossary if glossary is not None else NullGlossarySource()
        self.similarity = (
            similarity if similarity is not None else TrigramJaccardSimilarity()
        )
        self.history = history if history is not None else ResolutionHistory()

    # -- API ---------------------------------------------------------------
    def resolve(
        self, request: ResolutionRequest, *, record_history: bool | None = None
    ) -> ResolutionOutcome:
        """Resuelve un grupo de menciones y emite su `EntityResolution`."""
        cfg = self.config
        envelope = _read_envelope(request.mentions)
        ctx = _build_context(request, envelope)
        ctx.entities = tuple(self.catalog.entities(envelope.workspace))

        result = run_cascade(
            ctx,
            cfg,
            glossary=self.glossary if "glossary" not in cfg.disabled_steps else None,
            similarity=self.similarity if "similarity" not in cfg.disabled_steps else None,
            history=self.history if cfg.use_history else None,
            catalog=self.catalog,
        )
        decision = decide(result, ctx, cfg)
        resolution = self._emit(request, envelope, ctx, result, decision)

        should_record = cfg.record_history if record_history is None else record_history
        if should_record:
            self.history.record(
                workspace=envelope.workspace,
                surfaces=ctx.normalized_surfaces,
                entity_id=resolution.entity_id() or "",
                entity_type=resolution.entity_type,
                action=resolution.action,
                confidence=resolution.confidence,
                resolution_id=resolution.resolution_id,
                min_confidence=cfg.history_min_confidence,
            )
        return ResolutionOutcome(
            resolution=resolution,
            candidates=result.candidates,
            steps_run=result.steps_run,
            short_circuited=result.short_circuited,
            discarded_other_workspace=result.discarded_other_workspace,
            decision=decision,
        )

    def resolve_all(
        self, requests: Iterable[ResolutionRequest]
    ) -> tuple[ResolutionOutcome, ...]:
        """Resuelve una secuencia alimentando el historial paso a paso.

        El orden importa por construccion (la primera decision condiciona a las
        siguientes); por eso se acepta un iterable ORDENADO y no un conjunto.
        """
        return tuple(self.resolve(r) for r in requests)

    # -- Emision -----------------------------------------------------------
    def _emit(
        self,
        request: ResolutionRequest,
        envelope: "_Envelope",
        ctx: CascadeContext,
        result: _cascade.CascadeResult,
        decision: Decision,
    ) -> EntityResolution:
        cfg = self.config
        action = decision.action
        reasons = list(decision.reason_codes)
        candidate_ids = list(decision.candidate_entity_ids)
        selected = decision.selected_entity_id
        assigned: str | None = None

        entity_type = _resolution_type(action, selected, ctx, result)

        if action in ("CREATE_NEW", "CREATE_PROVISIONAL"):
            prefix = (
                cfg.new_id_prefix if action == "CREATE_NEW" else cfg.provisional_id_prefix
            )
            assigned = derive_entity_id(
                workspace=envelope.workspace,
                normalized_surface=ctx.primary_surface,
                entity_type=entity_type,
                prefix=prefix,
                digest_chars=cfg.derived_id_digest_chars,
            )
            if assigned in candidate_ids:
                # El identificador derivado ya existe entre los candidatos: no
                # se estaria creando nada. En vez de emitir un documento que el
                # validador rechazaria, se degrada a revision humana, que es lo
                # que de verdad hace falta cuando esto ocurre.
                action = "REVIEW"
                assigned = None
                reasons = [_cascade.R_ID_COLLISION, *reasons]

        if result.discarded_other_workspace:
            reasons.append(_cascade.R_WORKSPACE_ISOLATED)

        mention_ids = [m.mention_id for m in request.mentions]
        evidence = sorted({f for m in request.mentions for f in m.evidence_fragment_ids})
        if not evidence:
            raise ResolutionInputError(
                "las menciones no aportan evidence_fragment_ids: el contrato exige "
                "al menos un fragmento de evidencia y este resolutor no inventa ninguno"
            )

        resolution = EntityResolution(
            contract_version=CONTRACT_VERSION,
            workspace=envelope.workspace,
            source_asset_id=envelope.source_asset_id,
            source_hash=dict(envelope.source_hash),
            provider_trace=[
                provider_step(
                    cfg.step_name,
                    Provider.LOCAL,
                    cfg.engine_name,
                    cfg.engine_version,
                    ["action", "selected_entity_id", "assigned_entity_id", "confidence"],
                )
            ],
            produced_by_step=cfg.step_name,
            resolution_id=derive_resolution_id(
                workspace=envelope.workspace,
                mention_ids=mention_ids,
                prefix=cfg.resolution_id_prefix,
                digest_chars=cfg.derived_id_digest_chars,
            ),
            mention_ids=mention_ids,
            candidate_entity_ids=candidate_ids,
            selected_entity_id=selected if action == "LINK_EXISTING" else None,
            assigned_entity_id=assigned,
            action=action,
            entity_type=entity_type,
            confidence=round(float(decision.confidence), 6),
            evidence=evidence,
            reason_codes=list(dict.fromkeys(reasons)) or [_cascade.R_NO_CANDIDATE],
            game_profile=request.game_profile,
            metadata=_trace_metadata(result, ctx),
        )
        if cfg.validate_output:
            resolution.validate()
        return resolution


# -- Ayudas internas --------------------------------------------------------
@dataclass(frozen=True)
class _Envelope:
    workspace: str
    source_asset_id: str
    source_hash: Mapping[str, Any]


def _read_envelope(mentions: Sequence[EntityMention]) -> _Envelope:
    """Sobre comun de las menciones; exige que sea EL MISMO en todas.

    Mezclar menciones de dos workspaces en un mismo grupo no es un caso raro que
    haya que apanar: es un error aguas arriba, y silenciarlo aqui produciria un
    documento cuyo `workspace` seria una eleccion arbitraria entre dos.
    """
    first = mentions[0]
    for m in mentions[1:]:
        if m.workspace != first.workspace:
            raise ResolutionInputError(
                f"menciones de workspaces distintos en el mismo grupo: "
                f"{first.workspace!r} y {m.workspace!r}"
            )
        if m.source_asset_id != first.source_asset_id:
            raise ResolutionInputError(
                "menciones de source_asset_id distintos en el mismo grupo"
            )
    ids = [m.mention_id for m in mentions]
    if len(set(ids)) != len(ids):
        raise ResolutionInputError("mention_ids duplicados en la peticion")
    return _Envelope(
        workspace=first.workspace,
        source_asset_id=first.source_asset_id,
        source_hash=first.source_hash,
    )


def _build_context(request: ResolutionRequest, envelope: _Envelope) -> CascadeContext:
    surfaces = tuple(m.surface for m in request.mentions)
    normalized = tuple(
        dict.fromkeys(
            [normalize_surface(m.normalized_surface or m.surface) for m in request.mentions]
        )
    )
    return CascadeContext(
        workspace=envelope.workspace,
        surfaces=surfaces,
        normalized_surfaces=tuple(s for s in normalized if s),
        mention_type=aggregate_type(request.mentions),
        mention_confidence=aggregate_confidence(request.mentions),
        context_entity_ids=request.context_entity_ids,
    )


def aggregate_type(mentions: Sequence[EntityMention]) -> str | None:
    """Tipo del grupo: el que mas confianza acumula entre todas las menciones.

    Suma de confianzas y no voto por mayoria: dos menciones tibias no deben
    ganar a una segura. Desempate alfabetico para que el resultado no dependa
    del orden de las menciones.
    """
    totals: dict[str, float] = {}
    for m in mentions:
        for cand in m.type_candidates or ():
            t = cand.get("type")
            if not t:
                continue
            totals[t] = totals.get(t, 0.0) + float(cand.get("confidence", 0.0))
    if not totals:
        return None
    best = max(totals.values())
    if best <= 0.0:
        return None
    return sorted(t for t, v in totals.items() if v == best)[0]


def aggregate_confidence(mentions: Sequence[EntityMention]) -> float:
    """Confianza del grupo: la MINIMA de sus menciones.

    Deliberadamente pesimista. Un grupo vale lo que su eslabon mas debil: si una
    de las menciones es dudosa, la identidad del grupo entero lo es.
    """
    values = [float(m.confidence) for m in mentions]
    return min(values) if values else 0.0


def _resolution_type(
    action: str,
    selected: str | None,
    ctx: CascadeContext,
    result: _cascade.CascadeResult,
) -> str | None:
    """Tipo que declara la resolucion.

    Al enlazar manda el tipo de la entidad EXISTENTE (es la identidad que
    gana); al crear, el que propone la mencion. `None` es una respuesta legitima
    del contrato: significa "no me atrevo a tipar", no "no hay tipo".
    """
    if action == "LINK_EXISTING" and selected is not None:
        for cand in result.candidates:
            if cand.entity_id == selected and cand.entity_type is not None:
                return cand.entity_type
    return ctx.mention_type


def _trace_metadata(result: _cascade.CascadeResult, ctx: CascadeContext) -> dict[str, Any]:
    """Traza auditable de la cascada. Sin datos sensibles y sin texto libre."""
    return {
        "cascade": {
            "steps_run": list(result.steps_run),
            "short_circuited": result.short_circuited,
            "discarded_other_workspace": result.discarded_other_workspace,
            "mention_type": ctx.mention_type,
            "candidates": [
                {
                    "entity_id": c.entity_id,
                    "score": c.score,
                    "base_score": c.base_score,
                    "adjustment": c.adjustment,
                    "reason_codes": list(c.reason_codes),
                    "type_conflict": c.type_conflict,
                    "from_history": c.from_history,
                }
                for c in result.candidates
            ],
        }
    }


__all__ = [
    "EntityResolver",
    "ResolutionRequest",
    "ResolutionOutcome",
    "aggregate_type",
    "aggregate_confidence",
]

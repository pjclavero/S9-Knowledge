# -*- coding: utf-8 -*-
"""`LocalKnowledgeEngine`: la unica autoridad del sistema.

Entrada: episodios, evidencias, resoluciones, claims, perfil de juego y un
snapshot de solo lectura del grafo. Opcionalmente, senales de Ollama o de
proveedores externos — que son eso, senales.

Salida: una decision por claim, las afirmaciones derivadas de las aceptadas y
hasta dos `GraphMutationPlan` sellados (el de escritura y el de revision).

Lo que este objeto NO hace, y no es una omision:

* no escribe en Neo4j ni abre una conexion;
* no llama a ningun proveedor — las senales llegan ya calculadas, como datos;
* no genera timestamps: `now` se inyecta, para que la misma entrada produzca
  byte a byte el mismo plan;
* no acepta un lote heterogeneo. Workspaces mezclados, assets mezclados o un
  perfil de otro workspace son un `EngineInputError`, no un aviso. El
  aislamiento es duro y una entrada mezclada es un fallo de quien llama.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ..contracts import (
    ClaimProposal,
    EntityResolution,
    EvidenceFragment,
    FactAssertion,
    GameProfile,
    GraphMutationPlan,
    SourceEpisode,
    V3ContractError,
)
from .config import DEFAULT_CONFIG, ENGINE_VERSION, EngineConfig
from .decision import ClaimDecision, apply_batch_contradictions, decide_claim
from .errors import EngineInputError
from .evidence import EvidenceIndex
from .identity import ResolutionIndex
from .ontology import ProfileIndex
from .planner import PlanContext, build_plan
from .signals import ExternalSignal, signals_by_claim
from .snapshot import GraphSnapshot


@dataclass(frozen=True)
class EngineResult:
    """Todo lo que el motor produce en una corrida. Inmutable."""

    decisions: tuple[ClaimDecision, ...]
    assertions: tuple[FactAssertion, ...]
    plan: Optional[GraphMutationPlan]
    review_plan: Optional[GraphMutationPlan]
    validator_chain: tuple[dict, ...]

    def by_decision(self, decision: str) -> tuple[ClaimDecision, ...]:
        return tuple(d for d in self.decisions if d.decision == decision)

    @property
    def approved(self) -> bool:
        return bool(self.plan and self.plan.approved)

    def summary(self) -> dict[str, int]:
        """Recuento por decision. Sirve para el benchmark y para el operador."""
        out = {"ACCEPT": 0, "REJECT_INVALID": 0, "ABSTAIN": 0, "REVIEW": 0}
        for decision in self.decisions:
            out[decision.decision] += 1
        return out


class LocalKnowledgeEngine:
    """Motor local de conocimiento. Determinista, sin efectos secundarios."""

    version = ENGINE_VERSION

    def __init__(self, profile: GameProfile, config: EngineConfig = DEFAULT_CONFIG):
        profile.validate()
        self.profile = profile
        self.index = ProfileIndex(profile)
        self.config = config
        self.ontology_version = config.ontology_version or profile.core_ontology_version

    # -- validacion de la entrada -----------------------------------------
    def _check_inputs(
        self,
        claims: Sequence[ClaimProposal],
        resolutions: Sequence[EntityResolution],
        fragments: Sequence[EvidenceFragment],
        episodes: Sequence[SourceEpisode],
        snapshot: GraphSnapshot,
    ) -> tuple[str, str, dict]:
        """Contratos validos + lote homogeneo. Devuelve (workspace, asset, hash)."""
        if not claims:
            raise EngineInputError("no hay claims que decidir")
        documents = [*claims, *resolutions, *fragments, *episodes]
        for document in documents:
            try:
                document.validate()
            except V3ContractError as exc:
                raise EngineInputError(
                    f"documento de entrada invalido ({type(document).__name__}): {exc}"
                ) from exc

        workspaces = {d.workspace for d in documents}
        if len(workspaces) > 1:
            raise EngineInputError(f"lote con workspaces mezclados: {sorted(workspaces)}")
        workspace = next(iter(workspaces))
        if self.profile.workspace != workspace:
            raise EngineInputError(
                f"el perfil es del workspace {self.profile.workspace!r} y el lote de {workspace!r}"
            )
        if snapshot.workspace != workspace:
            raise EngineInputError(
                f"el snapshot es del workspace {snapshot.workspace!r} y el lote de {workspace!r}"
            )

        # La homogeneidad de ASSET se exige sobre los CLAIMS, no sobre todo el
        # lote: una evidencia que dice venir de otro asset no es un error de
        # quien llama, es una evidencia prestada, y el eje de evidencia debe
        # verla y rechazar ESE claim en vez de tumbar la corrida entera.
        assets = {c.source_asset_id for c in claims}
        if len(assets) > 1:
            raise EngineInputError(f"lote con varios source_asset_id: {sorted(assets)}")
        hashes = {c.source_hash["value"] for c in claims}
        if len(hashes) > 1:
            raise EngineInputError("lote con varios source_hash para el mismo asset")
        if self.ontology_version != self.index.ontology_version:
            raise EngineInputError(
                f"ontology_version {self.ontology_version!r} != perfil "
                f"{self.index.ontology_version!r}"
            )
        return workspace, next(iter(assets)), claims[0].source_hash

    # -- corrida ------------------------------------------------------------
    def run(
        self,
        *,
        claims: Sequence[ClaimProposal],
        resolutions: Sequence[EntityResolution],
        fragments: Sequence[EvidenceFragment],
        episodes: Sequence[SourceEpisode],
        snapshot: GraphSnapshot,
        collection_id: str,
        now: str,
        signals: Sequence[ExternalSignal] = (),
    ) -> EngineResult:
        """Decide sobre el lote y construye los planes. No escribe nada."""
        workspace, asset_id, source_hash = self._check_inputs(
            claims, resolutions, fragments, episodes, snapshot
        )

        resolution_index = ResolutionIndex.build(resolutions)
        evidence_index = EvidenceIndex.build(fragments, episodes)
        grouped = signals_by_claim(signals)

        decisions = [
            decide_claim(
                claim,
                resolutions=resolution_index,
                evidence=evidence_index,
                profile=self.index,
                snapshot=snapshot,
                config=self.config,
                claim_signals=grouped.get(claim.claim_id, ()),
            )
            for claim in claims
        ]
        # Segunda pasada de contradiccion: el lote contra si mismo, ANTES de
        # construir ningun plan. `decide_claim` ve un claim y todo el grafo;
        # solo aqui se ven unos claims a otros.
        decisions = apply_batch_contradictions(decisions, self.index)

        context = PlanContext(
            workspace=workspace,
            source_asset_id=asset_id,
            source_hash=source_hash,
            collection_id=collection_id,
            game_profile=self.profile.profile_id,
            ontology_version=self.ontology_version,
            snapshot=snapshot,
            now=now,
            engine_version=self.version,
        )
        proposal_steps = {c.claim_id: c.producing_provider() for c in claims}
        signal_steps = [s.trace_entry() for s in signals]

        if self.config.split_review_plan:
            writable = [d for d in decisions if d.decision != "REVIEW"]
            reviewable = [d for d in decisions if d.decision == "REVIEW"]
        else:
            writable, reviewable = list(decisions), []

        write_build = build_plan(
            context,
            writable,
            self.index,
            self.config,
            kind="write",
            proposal_steps=proposal_steps,
            extra_steps=signal_steps,
        )
        review_build = build_plan(
            context,
            reviewable,
            self.index,
            self.config,
            kind="review",
            proposal_steps=proposal_steps,
            extra_steps=signal_steps,
        )

        return EngineResult(
            decisions=tuple(decisions),
            assertions=write_build.assertions,
            plan=write_build.plan,
            review_plan=review_build.plan,
            validator_chain=write_build.validator_chain,
        )

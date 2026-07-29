# -*- coding: utf-8 -*-
"""El orquestador: encadena los subsistemas reales y no decide nada.

    fuente
      -> normalizacion multimodal      (multimodal/)
      -> episodios + evidencias
      -> extraccion                    (extraction/)
      -> reconciliacion textual         (reconcile/)
      -> resolucion de identidad       (resolution/)
      -> motor local                   (engine/)
      -> ledger temporal               (ledger/)
      -> GraphMutationPlan sellado
      -> writer controlado             (writer/)   [DRY-RUN por defecto]

Que hace este modulo
--------------------
Llamar a cada subsistema con lo que el anterior produjo, propagar el contexto
(workspace, perfil, snapshot, traza de proveedores) y recoger lo que sale.

Que NO hace
-----------
No filtra claims, no elige predicados, no arregla resoluciones, no decide que
se aprueba y no toca el plan. Toda regla de negocio que hiciera falta aqui
seria un hueco en un subsistema: cuando lo hemos encontrado, lo hemos anotado
en `docs/v3/11-e2e.md` en vez de parchearlo.

Las dos unicas traducciones que este paquete hace son adaptaciones de FORMA
entre subsistemas, ambas documentadas como defectos: `grouping.py` (D-2) y
`bridge.py` (D-1).

Nada de esto escribe en Neo4j: el writer va en dry-run salvo que se le inyecte
un driver y se pida `apply` explicitamente.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ..contracts.assertion import FactAssertion
from ..contracts.claim import ClaimProposal
from ..contracts.episode import SourceEpisode
from ..contracts.evidence import EvidenceFragment
from ..contracts.mention import EntityMention
from ..contracts.mutation_plan import GraphMutationPlan
from ..contracts.resolution import EntityResolution
from ..contracts.source_asset import SourceAsset
from ..engine.engine import EngineResult, LocalKnowledgeEngine
from ..engine.snapshot import GraphSnapshot, SnapshotEntity
from ..extraction.base import ExtractionContext, ExtractionOutput
from ..extraction.coreference import CoreferenceExtractor
from ..extraction.deterministic import DeterministicExtractor
from ..extraction.pipeline import ExtractionPipeline
from ..extraction.provider_port import OllamaProviderPort
from ..extraction.semantic import SemanticEpisodeExtractor
from ..extraction.table import TableExtractor
from ..extraction.temporal import TemporalExtractor
from ..ledger.assertions import TemporalLedger
from ..ledger.store import InMemoryLedgerStore
from ..multimodal.base import IngestOptions, NormalizationResult, SourceInput
from ..multimodal.normalizer import normalize
from ..multimodal.registry import default_registry
from ..reconcile import ProposalReconciler
from ..resolution.resolver import EntityResolver, ResolutionRequest
from ..writer.gate import OperatorRequest
from ..writer.writer import GraphWriter
from . import bridge
from .config import GoldInjection, PipelineConfig
from .errors import PipelineError
from .grouping import mention_groups


@dataclass
class SourceRun:
    """Todo lo que la cadena produjo para UNA fuente. Nada se descarta."""

    source_id: str
    asset: Optional[SourceAsset] = None
    episodes: list[SourceEpisode] = field(default_factory=list)
    fragments: list[EvidenceFragment] = field(default_factory=list)
    mentions: list[EntityMention] = field(default_factory=list)
    claims: list[ClaimProposal] = field(default_factory=list)
    resolutions: list[EntityResolution] = field(default_factory=list)
    engine_result: Optional[EngineResult] = None
    plan: Optional[GraphMutationPlan] = None
    review_plan: Optional[GraphMutationPlan] = None
    assertions: list[FactAssertion] = field(default_factory=list)
    ledger_entries: list[Any] = field(default_factory=list)
    write_result: Optional[Any] = None
    #: Diagnosticos del extractor + notas de coordinacion del orquestador.
    diagnostics: list[dict] = field(default_factory=list)
    normalization_report: dict = field(default_factory=dict)
    reconciliation_report: dict = field(default_factory=dict)
    stage_latency_ms: dict = field(default_factory=dict)
    #: Etapa en la que la cadena se detuvo, o None si llego al final.
    stopped_at: Optional[str] = None
    stop_reason: Optional[str] = None

    def note(self, stage: str, code: str, detail: str = "") -> None:
        self.diagnostics.append(
            {"step": stage, "code": code, "episode_id": "", "detail": detail}
        )

    def stop(self, stage: str, reason: str) -> "SourceRun":
        self.stopped_at = stage
        self.stop_reason = reason
        self.note(stage, "PIPELINE_STOPPED", reason)
        return self

    @property
    def decisions(self) -> tuple:
        return self.engine_result.decisions if self.engine_result else ()

    def summary(self) -> dict:
        return {
            "source_id": self.source_id,
            "episodes": len(self.episodes),
            "fragments": len(self.fragments),
            "mentions": len(self.mentions),
            "claims": len(self.claims),
            "resolutions": len(self.resolutions),
            "decisions": len(self.decisions),
            "assertions": len(self.assertions),
            "ledger_entries": len(self.ledger_entries),
            "plan_approved": bool(self.plan and self.plan.approved),
            "plan_operations": len(self.plan.mutation_operations) if self.plan else 0,
            "review_operations": (
                len(self.review_plan.mutation_operations) if self.review_plan else 0
            ),
            "write_outcome": self.write_result.outcome if self.write_result else None,
            "write_codes": self.write_result.codes if self.write_result else [],
            "reconciliation": dict(self.reconciliation_report),
            "stopped_at": self.stopped_at,
            "stop_reason": self.stop_reason,
            "diagnostics": sorted({d["code"] for d in self.diagnostics}),
        }


@dataclass
class PipelineResult:
    """Corrida completa: una `SourceRun` por fuente, mas lo compartido."""

    config_declared: dict
    runs: list[SourceRun] = field(default_factory=list)
    ledger: Optional[TemporalLedger] = None
    latency_ms: float = 0.0
    provider_calls: int = 0

    def _flat(self, attr: str) -> list:
        out: list = []
        for run in self.runs:
            out.extend(getattr(run, attr))
        return out

    @property
    def episodes(self) -> list[SourceEpisode]:
        return self._flat("episodes")

    @property
    def fragments(self) -> list[EvidenceFragment]:
        return self._flat("fragments")

    @property
    def mentions(self) -> list[EntityMention]:
        return self._flat("mentions")

    @property
    def claims(self) -> list[ClaimProposal]:
        return self._flat("claims")

    @property
    def resolutions(self) -> list[EntityResolution]:
        return self._flat("resolutions")

    @property
    def assertions(self) -> list[FactAssertion]:
        return self._flat("assertions")

    @property
    def decisions(self) -> list:
        out: list = []
        for run in self.runs:
            out.extend(run.decisions)
        return out

    @property
    def plans(self) -> list[GraphMutationPlan]:
        return [r.plan for r in self.runs if r.plan is not None]

    def summary(self) -> dict:
        return {
            "config": dict(self.config_declared),
            "sources": [r.summary() for r in self.runs],
            "totals": {
                "episodes": len(self.episodes),
                "fragments": len(self.fragments),
                "mentions": len(self.mentions),
                "claims": len(self.claims),
                "resolutions": len(self.resolutions),
                "decisions": len(self.decisions),
                "assertions": len(self.assertions),
                "plans": len(self.plans),
                "approved_plans": sum(1 for p in self.plans if p.approved),
                "ledger_entries": len(self.ledger) if self.ledger is not None else 0,
            },
            "latency_ms": round(self.latency_ms, 3),
            "provider_calls": self.provider_calls,
        }


@dataclass(frozen=True)
class SourceCase:
    """Una fuente lista para entrar en la cadena.

    Dos puertas de entrada, y hay que elegir una:

      * `source` — bytes reales: la cadena arranca en el normalizador.
      * `episodes`/`fragments` — la cadena arranca en el extractor, porque de
        esa fuente no hay bytes que normalizar. No es un atajo: es lo unico
        honesto cuando el material de partida no existe (ver 11-e2e.md §5).
    """

    source_id: str
    source: Optional[SourceInput] = None
    ingest_options: Optional[IngestOptions] = None
    asset: Optional[SourceAsset] = None
    episodes: Sequence[SourceEpisode] = ()
    fragments: Sequence[EvidenceFragment] = ()
    gold: GoldInjection = field(default_factory=GoldInjection)

    def __post_init__(self) -> None:
        if self.source is None and not self.episodes:
            raise PipelineError(
                "input",
                f"{self.source_id}: ni bytes ni episodios; la cadena no tiene por "
                "donde empezar",
            )
        if self.source is not None and self.ingest_options is None:
            raise PipelineError(
                "input", f"{self.source_id}: hay bytes pero no `ingest_options`"
            )


class KnowledgePipeline:
    """Coordina los subsistemas. No decide; no escribe salvo que se lo pidan."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.engine = LocalKnowledgeEngine(config.profile, config.engine_config)
        self.ledger = TemporalLedger(
            config.workspace, config.ledger_store or InMemoryLedgerStore()
        )
        self.resolver = EntityResolver(
            catalog=config.catalog,
            config=config.resolution_config,
            glossary=config.glossary,
        )
        self.reconciler = ProposalReconciler(config.reconciler_config)
        self._extraction = self._build_extraction_pipeline()

    # -- montaje de la extraccion ------------------------------------------
    @staticmethod
    def _ollama_port(candidate: Any):
        """`OllamaClient` -> `OllamaProviderPort`. Un puerto ya hecho pasa tal cual.

        Construir el puerto es lo UNICO que el orquestador hace con un proveedor:
        no compila prompts, no normaliza payloads y no valida candidatos. Todo
        eso vive en `extraction/`.
        """
        if candidate is None or hasattr(candidate, "complete_json"):
            return candidate
        return OllamaProviderPort(client=candidate)

    @staticmethod
    def _external_port(candidate: Any):
        """El carril externo exige un `ProviderPort` (NVIDIA, o un doble de test).

        Antes admitia un `ExternalProposalPort` (`propose()`), que era la puerta
        del extractor LEGACY. Ese extractor ya no se monta: un objeto que no sepa
        `complete_json` es un error de configuracion, no un modo degradado.
        """
        if candidate is None or hasattr(candidate, "complete_json"):
            return candidate
        raise PipelineError(
            "config",
            f"external_port debe ser un ProviderPort (con `complete_json`); "
            f"{type(candidate).__name__} no lo es. El extractor externo legacy "
            "ya no se monta en la cadena V3",
        )

    def _build_extraction_pipeline(self) -> ExtractionPipeline:
        """Los extractores que la configuracion pidio, en orden estable.

        Orden y por que:

            DeterministicExtractor   ancla primero: fija las menciones baratas y
                                     de alta precision sobre las que todo cuelga
            TableExtractor           lo estructural, tambien determinista
            SemanticEpisodeExtractor(puerto Ollama)    -> si Ollama esta activo
            SemanticEpisodeExtractor(puerto externo)   -> si el externo lo esta
            TemporalExtractor        despues de los modelos: recoge tambien lo
                                     que ellos hayan anclado
            CoreferenceExtractor     el ultimo SIEMPRE: necesita ver todas las
                                     menciones anteriores

        Cada extractor local se monta UNA sola vez: no se anida ningun pipeline
        dentro de otro. El carril de proveedor es el extractor SEMANTICO (el
        medido en `docs/v3/12-semantic-extractor.md`), no el legacy: los
        extractores `OllamaExtractor` / `ExternalExtractor` siguen en el repo como
        histórico y comparación, y la cadena V3 no los instancia. No hay bandera
        para volver a ellos.
        """
        cfg = self.config
        extractors: list = []
        if cfg.wants_local_extractors:
            extractors.append(DeterministicExtractor())
            extractors.append(TableExtractor())
        if cfg.wants_ollama:
            extractors.append(
                SemanticEpisodeExtractor(self._ollama_port(cfg.ollama_client))
            )
        if cfg.wants_external:
            extractors.append(
                SemanticEpisodeExtractor(self._external_port(cfg.external_port))
            )
        if cfg.wants_local_extractors and cfg.with_temporal:
            extractors.append(TemporalExtractor())
        if cfg.wants_local_extractors and cfg.with_coreference:
            extractors.append(CoreferenceExtractor())
        if not extractors:
            raise PipelineError(
                "extract",
                f"la configuracion {cfg.providers!r} no deja ningun extractor activo; "
                "una cadena sin extractor no es una cadena degradada, es ninguna",
            )
        return ExtractionPipeline(tuple(extractors))

    # -- etapas --------------------------------------------------------------
    def normalize(self, case: SourceCase, run: SourceRun) -> None:
        """Etapa 1. Bytes -> asset + episodios + evidencias."""
        if case.source is None:
            run.asset = case.asset
            run.episodes = list(case.episodes)
            run.fragments = list(case.fragments)
            run.note("normalize", "PIPELINE_ENTERED_AT_EPISODES", case.source_id)
            return
        registry = default_registry(visual_provider=self.config.visual_provider)
        result: NormalizationResult = normalize(
            case.source, case.ingest_options, registry=registry
        )
        run.asset = result.asset
        run.episodes = list(result.episodes)
        run.fragments = list(result.fragments)
        run.normalization_report = dict(result.report)

    def extract(self, run: SourceRun) -> None:
        """Etapa 2. Episodios -> menciones + claims (propuestas, nunca grafo)."""
        ctx = ExtractionContext(
            workspace=self.config.workspace,
            episodes=run.episodes,
            fragments=run.fragments,
            profile=self.config.profile,
            lexicon=self.config.lexicon,
        )
        out: ExtractionOutput = self._extraction.run(ctx)
        run.mentions = list(out.mentions)
        run.claims = list(out.claims)
        run.diagnostics.extend(
            {
                "step": d.step,
                "code": d.code,
                "episode_id": d.episode_id,
                "detail": d.detail,
            }
            for d in out.diagnostics
        )

    def resolve(self, run: SourceRun) -> None:
        """Etapa 4. Menciones -> resoluciones de identidad.

        Una peticion por grupo de correferencia (ver `grouping.py`). El
        resolutor se queda con el historial entre grupos de la MISMA fuente,
        que es lo que su `ResolutionHistory` modela.
        """
        for group in mention_groups(run.mentions):
            outcome = self.resolver.resolve(
                ResolutionRequest(
                    mentions=tuple(group),
                    game_profile=self.config.profile.profile_id,
                ),
                record_history=True,
            )
            run.resolutions.append(outcome.resolution)

    def reconcile(self, run: SourceRun) -> None:
        """Etapa 3. Propuestas textuales equivalentes -> IDs alineados."""
        out = ExtractionOutput(mentions=list(run.mentions), claims=list(run.claims))
        result = self.reconciler.run(out)
        run.mentions = list(result.output.mentions)
        run.claims = list(result.output.claims)
        run.reconciliation_report = result.stats.to_dict()
        run.diagnostics.extend(
            {
                "step": d.step,
                "code": d.code,
                "episode_id": d.episode_id,
                "detail": d.detail,
            }
            for d in result.output.diagnostics
        )

    def decide(self, run: SourceRun, snapshot: GraphSnapshot, gold: GoldInjection) -> None:
        """Etapa 5. El motor local: la unica pieza con autoridad."""
        claims = list(gold.claims) if self.config.claim_source == "gold" else run.claims
        resolutions = (
            list(gold.resolutions)
            if self.config.entity_source == "gold"
            else run.resolutions
        )
        if not claims:
            run.stop("engine", "el extractor no propuso ningun claim para esta fuente")
            return
        if self.config.claim_source == "gold":
            run.claims = list(claims)
        if self.config.entity_source == "gold":
            run.resolutions = list(resolutions)

        result = self.engine.run(
            claims=claims,
            resolutions=resolutions,
            fragments=run.fragments,
            episodes=run.episodes,
            snapshot=snapshot,
            collection_id=self.config.collection_id,
            now=self.config.now,
        )
        run.engine_result = result
        run.plan = result.plan
        run.review_plan = result.review_plan
        run.assertions = list(result.assertions)

    def record(self, run: SourceRun) -> None:
        """Etapa 6. Al ledger va lo que el motor APROBO. Nada mas.

        El criterio no es del orquestador: `plan.approved` ya lo fijo el motor
        y `result.assertions` son exactamente las del plan de escritura. Aqui
        solo se elige la OPERACION del ledger segun el campo `supersedes` del
        propio contrato — un despacho mecanico, no un juicio.
        """
        if not self.config.record_approved:
            return
        if run.plan is None or not run.plan.approved:
            run.note("ledger", "LEDGER_SKIPPED_PLAN_NOT_APPROVED", run.source_id)
            return
        for assertion in run.assertions:
            try:
                if assertion.supersedes and self.ledger.current(assertion.supersedes):
                    entries = self.ledger.supersede(assertion.supersedes, assertion)
                    run.ledger_entries.extend(entries)
                else:
                    if assertion.supersedes:
                        run.note(
                            "ledger",
                            "LEDGER_SUPERSEDES_UNKNOWN",
                            f"{assertion.assertion_id} dice suceder a "
                            f"{assertion.supersedes}, que no esta en el ledger",
                        )
                    run.ledger_entries.append(self.ledger.assert_fact(assertion))
            except Exception as exc:  # noqa: BLE001 - se anota, no se traga en silencio
                run.note(
                    "ledger",
                    "LEDGER_REJECTED",
                    f"{assertion.assertion_id}: {type(exc).__name__}: {exc}",
                )

    def write(self, run: SourceRun, snapshot_id: str) -> None:
        """Etapa 7. El plan al writer. DRY-RUN salvo peticion explicita."""
        if not self.config.with_writer or run.plan is None:
            return
        cfg = self.config
        writer_kwargs: dict[str, Any] = {
            "workspace": cfg.workspace,
            "driver": cfg.writer_driver,
            "max_operations": cfg.max_operations,
        }
        if cfg.writer_clock is not None:
            writer_kwargs["clock"] = cfg.writer_clock
        writer = GraphWriter(**writer_kwargs)
        request = OperatorRequest(
            apply=cfg.apply,
            operator_id=cfg.operator_id,
            workspace=cfg.workspace,
            expected_plan_hash=run.plan.plan_hash["value"],
            max_operations=cfg.max_operations,
            current_snapshot_id=snapshot_id,
            env=dict(cfg.writer_env),
        )
        run.write_result = writer.write(run.plan.to_dict(), request)

    # -- corrida -------------------------------------------------------------
    def run_source(
        self,
        case: SourceCase,
        *,
        snapshot: Optional[GraphSnapshot] = None,
        catalog_entities: Sequence[SnapshotEntity] = (),
    ) -> SourceRun:
        """La cadena entera sobre una fuente."""
        run = SourceRun(source_id=case.source_id)
        stages = [
            ("normalize", lambda: self.normalize(case, run)),
            ("extract", lambda: self.extract(run)),
        ]
        if self.config.with_reconciliation:
            stages.append(("reconcile", lambda: self.reconcile(run)))
        stages.append(("resolve", lambda: self.resolve(run)))
        for name, step in stages:
            started = time.perf_counter()
            step()
            run.stage_latency_ms[name] = (time.perf_counter() - started) * 1000.0

        snap = snapshot or bridge.engine_snapshot(self.ledger, entities=catalog_entities)
        started = time.perf_counter()
        self.decide(run, snap, case.gold)
        run.stage_latency_ms["engine"] = (time.perf_counter() - started) * 1000.0
        if run.stopped_at:
            return run

        started = time.perf_counter()
        self.record(run)
        run.stage_latency_ms["ledger"] = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        self.write(run, snap.snapshot_id)
        run.stage_latency_ms["writer"] = (time.perf_counter() - started) * 1000.0
        return run

    def run(
        self,
        cases: Sequence[SourceCase],
        *,
        catalog_entities: Sequence[SnapshotEntity] = (),
    ) -> PipelineResult:
        """La cadena sobre varias fuentes, en orden y compartiendo ledger.

        El snapshot se REconstruye antes de cada fuente: lo que la fuente n
        aprobo esta en el grafo que ve la fuente n+1. Es lo que hace que la
        supersesion y la contradiccion entre fuentes existan de verdad.
        """
        started = time.perf_counter()
        result = PipelineResult(
            config_declared=self.config.declared(), ledger=self.ledger
        )
        for case in cases:
            snap = bridge.engine_snapshot(self.ledger, entities=catalog_entities)
            result.runs.append(
                self.run_source(case, snapshot=snap, catalog_entities=catalog_entities)
            )
        result.latency_ms = (time.perf_counter() - started) * 1000.0
        result.provider_calls = self._count_provider_calls(result)
        return result

    @staticmethod
    def _count_provider_calls(result: PipelineResult) -> int:
        """Llamadas a proveedor CONTADAS en la traza, no estimadas."""
        calls = 0
        for doc in (*result.mentions, *result.claims):
            for step in doc.provider_trace:
                if step.get("provider") in ("ollama", "external"):
                    calls += 1
        return calls


__all__ = [
    "KnowledgePipeline",
    "PipelineResult",
    "SourceCase",
    "SourceRun",
]

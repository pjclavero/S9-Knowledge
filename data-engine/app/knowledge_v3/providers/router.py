# -*- coding: utf-8 -*-
"""Registry/facade de proveedores V3.

Es la UNICA puerta por la que el pipeline V3 pide trabajo a un proveedor. Hace
cuatro cosas y ninguna mas:

1. **Enruta** — capacidad tipada -> proveedor, con la politica de §2 (local
   primero) y el presupuesto.
2. **Despacha** — reutilizando `external_processing.dispatcher.BurstDispatcher`
   tal cual: concurrencia, backoff, reintentos y circuit breaker YA estaban
   escritos y probados; aqui no se reimplementan.
3. **Valida** — toda respuesta pasa por `external_processing.result_validator`
   ANTES de que nadie la mire, y despues por las guardas de `guards.py`.
4. **Devuelve un `ProviderOutcome`** — un resultado etiquetado, nunca una
   decision. La conversion a documentos V3 es un paso aparte y explicito
   (`proposals.py`), para que no exista ninguna ruta en la que un byte del
   proveedor se convierta en escritura sin pasar por el motor local.

Lo que este modulo NO hace, por diseno: aprobar, firmar, sellar planes, tocar
Neo4j o decidir identidad.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from external_processing.dispatcher import BurstDispatcher
from external_processing.models import JobStatus, ProcessingJob, ProcessingMode
from external_processing.provider import ExternalProcessingProvider
from external_processing.result_validator import validate_result

from knowledge_v3.providers.capability import (
    V3Capability,
    to_provider_capability,
    to_task_type,
)
from knowledge_v3.providers.guards import GuardError, assert_size, guard_provider_result
from knowledge_v3.providers.policy import (
    TIER_ORDER,
    Budget,
    RoutingDecision,
    RoutingPolicy,
    Tier,
)


def _code(value) -> Optional[str]:
    """Codigo de error como cadena plana. `str(EnumMiembro)` no lo es."""
    if value is None:
        return None
    return getattr(value, "value", None) or str(value)


@dataclass(frozen=True)
class RegisteredProvider:
    """Un proveedor con su clase y su coste declarado."""

    provider: ExternalProcessingProvider
    tier: Tier
    cost_units: float = 1.0
    default_model: Optional[str] = None

    @property
    def name(self) -> str:
        return self.provider.provider_name


@dataclass
class ProviderOutcome:
    """Resultado etiquetado de una peticion a la capa de proveedores.

    `ok=True` significa "hay una propuesta utilizable", NUNCA "esto es cierto"
    ni "esto puede escribirse".
    """

    capability: V3Capability
    ok: bool
    provider_name: Optional[str] = None
    tier: Optional[Tier] = None
    model: Optional[str] = None
    result: Optional[dict] = None
    reason_codes: tuple = ()
    validation_errors: tuple = ()
    validation_warnings: tuple = ()
    latency_ms: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 0
    decision: Optional[RoutingDecision] = None

    def attribution_step(self) -> str:
        """Nombre del paso para `provider_trace`. Estable y enumerable."""
        return f"{self.capability.value.lower()}.{self.provider_name or 'none'}"

    def attribution(self, *, name: str, version: str = "3.0.0"):
        """`ProviderAttribution` DERIVADA de este resultado.

        El llamante elige el nombre y la version del componente que mapea, y
        **nada mas**: `tier`, `step` y `model` salen del resultado real. Es la
        unica via sancionada para construir la traza de una propuesta.

        Antes, el llamante escribia el tier a mano; nada impedia etiquetar como
        `local` una salida de NVIDIA, y el documento validaba contra el schema
        igualmente. La veracidad de `provider_trace` era una convencion; ahora
        es una consecuencia.
        """
        from knowledge_v3.providers.proposals import ProviderAttribution, sanitize_model

        if not self.ok or self.tier is None:
            raise ValueError(
                "no se puede atribuir una propuesta a partir de un resultado fallido"
            )
        return ProviderAttribution(
            tier=self.tier,
            name=name,
            version=version,
            step=self.attribution_step(),
            # El modelo lo dicta el proveedor: se registra, pero saneado.
            model=sanitize_model(self.model),
            verified=True,
        )


class ProviderRouter:
    """Facade de proveedores V3."""

    def __init__(
        self,
        policy: Optional[RoutingPolicy] = None,
        budget: Optional[Budget] = None,
    ) -> None:
        self.policy = policy or RoutingPolicy()
        self.budget = budget or Budget(max_calls=0, max_cost_units=0.0)
        self._by_name: Dict[str, RegisteredProvider] = {}
        self._dispatchers: Dict[str, BurstDispatcher] = {}

    # -- Registro ----------------------------------------------------------
    def register(
        self,
        provider: ExternalProcessingProvider,
        tier: Tier,
        *,
        cost_units: float = 1.0,
        default_model: Optional[str] = None,
        apply_policy_timeout: bool = True,
    ) -> "ProviderRouter":
        entry = RegisteredProvider(
            provider=provider, tier=tier, cost_units=cost_units, default_model=default_model
        )
        # `RoutingPolicy.timeout_seconds_by_tier` era codigo muerto: se
        # declaraba y no lo leia nadie. O se aplica o sobra; se aplica.
        if apply_policy_timeout and hasattr(provider, "timeout_seconds"):
            provider.timeout_seconds = self.policy.timeout_for(tier)
        self._by_name[entry.name] = entry
        self._dispatchers[entry.name] = BurstDispatcher(
            provider,
            max_concurrency=1,
            base_backoff=0.0 if tier is Tier.LOCAL else 1.0,
            circuit_failure_threshold=self.policy.circuit_failure_threshold,
            circuit_cooldown_seconds=self.policy.circuit_cooldown_seconds,
        )
        return self

    def unregister(self, name: str) -> None:
        self._by_name.pop(name, None)
        self._dispatchers.pop(name, None)

    def providers(self) -> List[str]:
        return sorted(self._by_name)

    def capability_matrix(self) -> Dict[str, Dict[str, bool]]:
        """Matriz capacidad x proveedor, tal y como la declaran los proveedores."""
        return {
            cap.value: {
                entry.name: entry.provider.supports(to_provider_capability(cap))
                for entry in self._by_name.values()
            }
            for cap in V3Capability
        }

    # -- Enrutado ----------------------------------------------------------
    def route(
        self,
        capability: V3Capability,
        *,
        input_units: float = 0.0,
        private_content: bool = False,
        exclude: tuple = (),
    ) -> RoutingDecision:
        """Elige proveedor. Nunca lanza: si no hay ruta, `routed` es False."""
        needed = to_provider_capability(capability)
        reasons: List[str] = []
        rejected: List[tuple] = []

        for tier in TIER_ORDER:
            candidates = sorted(
                (
                    e
                    for e in self._by_name.values()
                    if e.tier is tier
                    and e.name not in exclude
                    and e.provider.supports(needed)
                ),
                key=lambda e: e.name,
            )
            if not candidates:
                continue

            if tier is Tier.EXTERNAL:
                if not self.policy.external_enabled:
                    rejected.append((candidates[0].name, "EXTERNAL_DISABLED"))
                    continue
                if capability not in self.policy.allow_external_for:
                    rejected.append((candidates[0].name, "EXTERNAL_CAPABILITY_NOT_ALLOWED"))
                    continue
                if private_content and not self.policy.allow_private_content_external:
                    rejected.append((candidates[0].name, "PRIVATE_CONTENT_STAYS_LOCAL"))
                    continue
                if input_units < self.policy.external_min_input_units:
                    rejected.append((candidates[0].name, "BELOW_EXTERNAL_THRESHOLD"))
                    continue
                if not self.budget.reserve(candidates[0].cost_units):
                    rejected.append((candidates[0].name, "BUDGET_EXHAUSTED"))
                    continue
                reasons.append("EXTERNAL_WITHIN_BUDGET")

            chosen = candidates[0]
            reasons.append(f"TIER_{tier.value.upper()}_SELECTED")
            return RoutingDecision(
                capability=capability,
                provider_name=chosen.name,
                tier=tier,
                reason_codes=tuple(reasons),
                rejected=tuple(rejected),
            )

        return RoutingDecision(
            capability=capability,
            provider_name=None,
            tier=None,
            reason_codes=("NO_PROVIDER_FOR_CAPABILITY",),
            rejected=tuple(rejected),
        )

    # -- Ejecucion ---------------------------------------------------------
    def run(
        self,
        capability: V3Capability,
        *,
        workspace: str,
        source_id: str,
        payload: dict,
        chunk: Optional[dict] = None,
        batch_id: str = "v3-batch",
        input_units: float = 0.0,
        private_content: bool = False,
        max_attempts: int = 2,
        model: Optional[str] = None,
        fallback: bool = True,
    ) -> ProviderOutcome:
        """Enruta, despacha, valida y devuelve una PROPUESTA etiquetada.

        Con `fallback=True` (defecto), si el proveedor elegido falla se intenta
        el siguiente candidato admisible. El fallback NUNCA sube de tier hacia
        el externo saltandose la politica: `route()` vuelve a aplicar todas las
        comprobaciones en cada intento.
        """
        excluded: tuple = ()
        last: Optional[ProviderOutcome] = None

        while True:
            decision = self.route(
                capability,
                input_units=input_units,
                private_content=private_content,
                exclude=excluded,
            )
            if not decision.routed:
                if last is not None:
                    return last
                return ProviderOutcome(
                    capability=capability,
                    ok=False,
                    reason_codes=decision.reason_codes,
                    error_code="NO_ROUTE",
                    error_message="ningun proveedor admisible para la capacidad",
                    decision=decision,
                )

            outcome = self._run_on(
                decision,
                workspace=workspace,
                source_id=source_id,
                payload=payload,
                chunk=chunk,
                batch_id=batch_id,
                max_attempts=max_attempts,
                model=model,
            )
            if outcome.ok or not fallback:
                return outcome
            last = outcome
            excluded = excluded + (decision.provider_name,)

    def _run_on(
        self,
        decision: RoutingDecision,
        *,
        workspace: str,
        source_id: str,
        payload: dict,
        chunk: Optional[dict],
        batch_id: str,
        max_attempts: int,
        model: Optional[str],
    ) -> ProviderOutcome:
        capability: V3Capability = decision.capability  # type: ignore[assignment]
        entry = self._by_name[decision.provider_name]  # type: ignore[index]
        dispatcher = self._dispatchers[entry.name]

        job = ProcessingJob(
            batch_id=batch_id,
            workspace=workspace,
            source_id=source_id,
            task_type=to_task_type(capability),
            provider=entry.name,
            model=model or entry.default_model,
            processing_mode=(
                ProcessingMode.LOCAL if entry.tier is not Tier.EXTERNAL else ProcessingMode.BURST
            ),
            chunk=chunk,
            payload=payload,
            max_attempts=max_attempts,
        )

        t0 = time.monotonic()
        try:
            done = dispatcher.dispatch_one(job)
        except (KeyboardInterrupt, SystemExit):
            # Cancelar de verdad tiene que seguir cancelando: convertir un
            # Ctrl-C en "el proveedor fallo" dejaba el proceso vivo.
            raise
        except BaseException as exc:  # noqa: BLE001
            # `BurstDispatcher.dispatch_one` solo protege de
            # `ExternalProcessingError`: un proveedor que lance cualquier otra
            # cosa (un `KeyError` en su propio parser, por ejemplo) tumbaria el
            # pipeline entero. Aqui se convierte en fallo del proveedor.
            if entry.tier is Tier.EXTERNAL:
                self.budget.refund(entry.cost_units)
            return ProviderOutcome(
                capability=capability,
                ok=False,
                provider_name=entry.name,
                tier=entry.tier,
                model=job.model,
                reason_codes=decision.reason_codes + ("PROVIDER_RAISED_UNTYPED",),
                latency_ms=(time.monotonic() - t0) * 1000.0,
                error_code="PROVIDER_FAILED",
                error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
                attempts=1,
                decision=decision,
            )
        latency_ms = (time.monotonic() - t0) * 1000.0

        if done.status is not JobStatus.COMPLETED or done.result is None:
            if entry.tier is Tier.EXTERNAL:
                # Lo reservado no se gasto: se devuelve.
                self.budget.refund(entry.cost_units)
            return ProviderOutcome(
                capability=capability,
                ok=False,
                provider_name=entry.name,
                tier=entry.tier,
                model=job.model,
                reason_codes=decision.reason_codes + ("PROVIDER_FAILED",),
                latency_ms=done.latency_ms if done.latency_ms is not None else latency_ms,
                error_code=_code(done.error_code) or "PROVIDER_FAILED",
                error_message=(done.error_message or "")[:300],
                attempts=done.attempt,
                decision=decision,
            )

        # 0) Cordura ESTRUCTURAL antes que nada. Va primero porque el
        #    validador compartido serializa el resultado entero para escanear
        #    secretos, y una estructura de 10 000 niveles lo hacia reventar con
        #    `RecursionError` —un `RuntimeError` que nadie trataba como
        #    respuesta invalida— antes de que ninguna guarda llegase a mirarla.
        #    Lo barato y lo que no puede explotar, primero.
        try:
            assert_size(done.result)
        except (GuardError, RecursionError) as exc:
            return self._rejected(
                decision, entry, job, done, latency_ms, "GUARD_REJECTED", exc
            )

        # 1) Validador de resultados YA existente (hashes, rangos, workspace,
        #    secretos). Segunda puerta, y no se salta nunca.
        try:
            validated_job, vr = validate_result(done.transition_to(JobStatus.VALIDATING))
        except RecursionError as exc:
            return self._rejected(
                decision, entry, job, done, latency_ms, "GUARD_REJECTED", exc
            )
        if not vr.valid:
            return ProviderOutcome(
                capability=capability,
                ok=False,
                provider_name=entry.name,
                tier=entry.tier,
                model=job.model,
                reason_codes=decision.reason_codes + ("RESULT_VALIDATION_FAILED",),
                validation_errors=tuple(vr.errors),
                validation_warnings=tuple(vr.warnings),
                latency_ms=done.latency_ms if done.latency_ms is not None else latency_ms,
                error_code="FAILED_VALIDATION",
                attempts=done.attempt,
                decision=decision,
            )

        # 2) Guardas de la capa V3 (tamano, profundidad, contrato prohibido,
        #    inyeccion).
        try:
            result, injection_codes = guard_provider_result(done.result)
        except GuardError as exc:
            return ProviderOutcome(
                capability=capability,
                ok=False,
                provider_name=entry.name,
                tier=entry.tier,
                model=job.model,
                reason_codes=decision.reason_codes + ("GUARD_REJECTED",),
                validation_errors=(str(exc)[:300],),
                latency_ms=done.latency_ms if done.latency_ms is not None else latency_ms,
                error_code="GUARD_REJECTED",
                error_message=str(exc)[:300],
                attempts=done.attempt,
                decision=decision,
            )

        return ProviderOutcome(
            capability=capability,
            ok=True,
            provider_name=entry.name,
            tier=entry.tier,
            model=(result.get("model") if isinstance(result, dict) else None) or job.model,
            result=result,
            reason_codes=decision.reason_codes + tuple(injection_codes),
            validation_warnings=tuple(vr.warnings),
            latency_ms=done.latency_ms if done.latency_ms is not None else latency_ms,
            attempts=done.attempt,
            decision=decision,
        )

    def _rejected(
        self, decision, entry, job, done, latency_ms, code: str, exc: BaseException
    ) -> ProviderOutcome:
        """Resultado descartado por una guarda. Nunca entrega `result`."""
        detalle = f"{type(exc).__name__}: {str(exc)[:280]}"
        return ProviderOutcome(
            capability=decision.capability,  # type: ignore[arg-type]
            ok=False,
            provider_name=entry.name,
            tier=entry.tier,
            model=job.model,
            reason_codes=decision.reason_codes + (code,),
            validation_errors=(detalle,),
            latency_ms=done.latency_ms if done.latency_ms is not None else latency_ms,
            error_code=code,
            error_message=detalle,
            attempts=done.attempt,
            decision=decision,
        )

    # -- Salud -------------------------------------------------------------
    def healthcheck(self) -> Dict[str, dict]:
        """Salud de cada proveedor registrado. No lanza."""
        out: Dict[str, dict] = {}
        for name, entry in sorted(self._by_name.items()):
            try:
                health = entry.provider.healthcheck()
            except Exception as exc:  # noqa: BLE001
                health = {"status": "error", "error": type(exc).__name__}
            health["tier"] = entry.tier.value
            out[name] = health
        return out


def default_router(
    policy: Optional[RoutingPolicy] = None,
    budget: Optional[Budget] = None,
    *,
    repo_root=None,
    with_ollama: bool = True,
    with_nvidia: bool = False,
) -> ProviderRouter:
    """Router con los proveedores reales.

    NVIDIA queda APAGADO por defecto: encenderlo cuesta dinero y exige una
    politica que lo autorice explicitamente.
    """
    router = ProviderRouter(policy=policy or RoutingPolicy.from_env(), budget=budget or Budget.from_env())
    if with_ollama:
        from external_processing.providers.ollama import OllamaProcessingProvider

        provider = OllamaProcessingProvider()
        router.register(provider, Tier.OLLAMA, cost_units=0.0, default_model=provider.model)
    if with_nvidia:
        from pathlib import Path

        from external_processing.providers.nvidia import NvidiaProcessingProvider

        router.register(
            NvidiaProcessingProvider(Path(repo_root or ".")), Tier.EXTERNAL, cost_units=1.0
        )
    return router

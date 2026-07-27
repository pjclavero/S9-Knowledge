# -*- coding: utf-8 -*-
"""Politica de enrutado y presupuesto de la capa de proveedores V3.

Regla de oro (prompt maestro §2): **local primero**. El externo solo entra
cuando el local no puede o no llega, la politica lo permite y queda
presupuesto. Ningun proveedor aprueba nada: el enrutado decide QUIEN propone,
jamas QUE se acepta.

Todo lo que decide esta funcion queda registrado como `reason_codes`
enumerables (nunca texto libre), para que una ruta pueda auditarse despues sin
tener que reconstruir el estado del proceso.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from knowledge_v3.contracts import Provider


class Tier(str, Enum):
    """Clase de proveedor, en orden de preferencia."""

    LOCAL = "local"      # codigo determinista del motor (faster-whisper, tesseract...)
    OLLAMA = "ollama"    # LLM local
    EXTERNAL = "external"  # proveedor remoto de pago

    def as_contract_provider(self) -> Provider:
        """Traduce al enum de `provider_trace` de los contratos congelados."""
        return {
            Tier.LOCAL: Provider.LOCAL,
            Tier.OLLAMA: Provider.OLLAMA,
            Tier.EXTERNAL: Provider.EXTERNAL,
        }[self]


#: Orden canonico de preferencia. No es configurable: invertirlo significaria
#: preferir el externo, y eso contradice §2.
TIER_ORDER: tuple[Tier, ...] = (Tier.LOCAL, Tier.OLLAMA, Tier.EXTERNAL)


class RoutingError(RuntimeError):
    """No hay ruta admisible para la capacidad pedida."""


@dataclass(frozen=True)
class RoutingPolicy:
    """Politica de enrutado. Inmutable: una corrida no cambia sus reglas a mitad.

    `external_enabled`: interruptor maestro del externo (por defecto APAGADO;
    fail-closed: si nadie lo enciende, no se gasta dinero).
    `external_min_input_units`: umbral por debajo del cual no compensa salir
    fuera (unidades = segundos de audio, paginas, caracteres... las fija quien
    llama; la politica solo compara).
    `allow_external_for`: capacidades que pueden salir fuera. Vacio = ninguna.
    `allow_private_content_external`: contenido privado NUNCA sale por defecto.
    """

    external_enabled: bool = False
    external_min_input_units: float = 0.0
    allow_external_for: frozenset = frozenset()
    allow_private_content_external: bool = False
    timeout_seconds_by_tier: dict = field(
        default_factory=lambda: {Tier.LOCAL: 600, Tier.OLLAMA: 120, Tier.EXTERNAL: 180}
    )
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "RoutingPolicy":
        """Politica desde entorno. Sin variables = todo local, fail-closed."""
        from knowledge_v3.providers.capability import V3Capability

        def _flag(name: str) -> bool:
            return os.environ.get(name, "false").strip().lower() == "true"

        raw = os.environ.get("S9K_V3_EXTERNAL_CAPABILITIES", "").strip()
        allowed = set()
        for token in (t.strip().upper() for t in raw.split(",") if t.strip()):
            try:
                allowed.add(V3Capability(token))
            except ValueError:
                # Un nombre desconocido no abre nada: se ignora, no se adivina.
                continue

        return cls(
            external_enabled=_flag("S9K_V3_EXTERNAL_ENABLED"),
            external_min_input_units=float(
                os.environ.get("S9K_V3_EXTERNAL_MIN_UNITS", "0") or "0"
            ),
            allow_external_for=frozenset(allowed),
            allow_private_content_external=_flag(
                "S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT"
            ),
        )

    def timeout_for(self, tier: Tier) -> int:
        return int(self.timeout_seconds_by_tier.get(tier, 120))


class Budget:
    """Presupuesto de llamadas externas. Thread-safe y fail-closed.

    Cuenta llamadas y coste estimado. `reserve()` es lo unico que autoriza una
    llamada externa; si devuelve False, la ruta externa queda cerrada y se cae
    al siguiente candidato (o se aborta). Nunca se descuenta "a posteriori":
    reservar antes evita que N hilos gasten el mismo ultimo credito.
    """

    def __init__(
        self,
        max_calls: Optional[int] = None,
        max_cost_units: Optional[float] = None,
    ) -> None:
        self.max_calls = max_calls
        self.max_cost_units = max_cost_units
        self._calls = 0
        self._cost = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "Budget":
        raw_calls = os.environ.get("S9K_V3_EXTERNAL_MAX_CALLS", "").strip()
        raw_cost = os.environ.get("S9K_V3_EXTERNAL_MAX_COST_UNITS", "").strip()
        return cls(
            max_calls=int(raw_calls) if raw_calls else 0,
            max_cost_units=float(raw_cost) if raw_cost else 0.0,
        )

    @property
    def calls_used(self) -> int:
        return self._calls

    @property
    def cost_used(self) -> float:
        return self._cost

    def remaining_calls(self) -> Optional[int]:
        if self.max_calls is None:
            return None
        return max(0, self.max_calls - self._calls)

    def reserve(self, cost_units: float = 1.0) -> bool:
        """Reserva una llamada externa. False = sin presupuesto."""
        with self._lock:
            if self.max_calls is not None and self._calls + 1 > self.max_calls:
                return False
            if (
                self.max_cost_units is not None
                and self._cost + cost_units > self.max_cost_units
            ):
                return False
            self._calls += 1
            self._cost += cost_units
            return True

    def refund(self, cost_units: float = 1.0) -> None:
        """Devuelve una reserva que no llego a consumirse (p. ej. circuito abierto)."""
        with self._lock:
            self._calls = max(0, self._calls - 1)
            self._cost = max(0.0, self._cost - cost_units)


@dataclass(frozen=True)
class RoutingDecision:
    """Resultado de enrutar: quien propone y por que."""

    capability: object  # V3Capability
    provider_name: Optional[str]
    tier: Optional[Tier]
    reason_codes: tuple
    rejected: tuple = ()

    @property
    def routed(self) -> bool:
        return self.provider_name is not None

"""Modelos y contratos del subsistema de health."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


# Orden de severidad (para calcular el estado global = el peor).
_SEVERITY = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.UNKNOWN: 1,
    HealthStatus.DEGRADED: 2,
    HealthStatus.UNHEALTHY: 3,
}

# Código de salida CLI asociado al estado global.
EXIT_CODES = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.DEGRADED: 1,
    HealthStatus.UNHEALTHY: 2,
    HealthStatus.UNKNOWN: 1,  # desconocido se trata como degradado a efectos de exit
}
EXIT_CONFIG_ERROR = 3


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ComponentResult:
    """Resultado de un check de componente. `details` debe ir sanitizado."""

    component: str
    status: HealthStatus
    checked_at: str = field(default_factory=_utcnow_iso)
    latency_ms: Optional[float] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status.value,
            "checked_at": self.checked_at,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "details": self.details,
        }


def worst_status(statuses: List[HealthStatus]) -> HealthStatus:
    if not statuses:
        return HealthStatus.UNKNOWN
    return max(statuses, key=lambda s: _SEVERITY[s])


@dataclass
class HealthReport:
    components: List[ComponentResult] = field(default_factory=list)
    generated_at: str = field(default_factory=_utcnow_iso)

    @property
    def overall(self) -> HealthStatus:
        return worst_status([c.status for c in self.components])

    def exit_code(self) -> int:
        return EXIT_CODES.get(self.overall, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall.value,
            "generated_at": self.generated_at,
            "components": [c.to_dict() for c in self.components],
        }

"""Modelos del Centro de Estado: cuatro estados, y UNKNOWN no es OK.

`UNKNOWN` significa "no lo sé" y tiene severidad ESTRICTAMENTE mayor que OK:
una sección sin fuente de datos nunca puede pintar verde ni desaparecer del
estado global. Es la distinción que este panel existe para no perder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class OpsStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


#: Severidad. UNKNOWN > OK a propósito: "no lo sé" nunca se agrega como "bien".
SEVERITY: Dict[OpsStatus, int] = {
    OpsStatus.OK: 0,
    OpsStatus.UNKNOWN: 1,
    OpsStatus.WARNING: 2,
    OpsStatus.CRITICAL: 3,
}


def worst(statuses: Iterable[OpsStatus]) -> OpsStatus:
    """Peor estado de la lista. Lista vacía = UNKNOWN (no hay nada que afirmar)."""
    items = list(statuses)
    if not items:
        return OpsStatus.UNKNOWN
    return max(items, key=lambda s: SEVERITY[s])


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class SectionResult:
    """Estado de una sección del panel.

    `metrics` sólo contiene valores ya saneados (números, fechas ISO, etiquetas).
    Nunca rutas del servidor, tokens, trazas ni mensajes de excepción crudos.
    Un valor desconocido se representa como ``None`` y se pinta como UNKNOWN.
    """

    key: str
    title: str
    status: OpsStatus
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status.value,
            "message": self.message,
            "metrics": self.metrics,
            "notes": list(self.notes),
        }


@dataclass
class OpsReport:
    sections: List[SectionResult] = field(default_factory=list)
    generated_at: str = field(default_factory=utcnow_iso)

    @property
    def overall(self) -> OpsStatus:
        return worst([s.status for s in self.sections])

    def section(self, key: str) -> Optional[SectionResult]:
        for s in self.sections:
            if s.key == key:
                return s
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall.value,
            "generated_at": self.generated_at,
            "read_only": True,
            "sections": [s.to_dict() for s in self.sections],
        }

"""Modelo de hallazgos y niveles del comprobador de salud de datos.

Regla innegociable del proyecto: **UNKNOWN nunca se convierte en OK**. No poder
comprobar algo no es evidencia de que esté bien; es una comprobación que no se
ha hecho, y se reporta como tal (`UNKNOWN`) y hace fallar la salida.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"
#: No es un nivel de gravedad: es la ausencia de veredicto. Se mantiene separado
#: a propósito para que nadie pueda colapsarlo dentro de "no hay CRITICAL".
UNKNOWN = "UNKNOWN"

LEVELS = (CRITICAL, WARNING, INFO, UNKNOWN)

# Códigos de salida. 0 EXIGE: sin CRITICAL, sin UNKNOWN y sin fallo interno.
EXIT_OK = 0
EXIT_CRITICAL = 1
EXIT_UNKNOWN = 2
EXIT_INTERNAL_ERROR = 3


@dataclass(frozen=True)
class Finding:
    check: str          # identificador estable de la comprobación (p.ej. "D03")
    level: str          # CRITICAL / WARNING / INFO / UNKNOWN
    message: str
    subject: str = ""   # id de nodo/relación/campo afectado
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"nivel desconocido: {self.level!r}")


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def extend(self, fs: Iterable[Finding]) -> None:
        self.findings.extend(fs)

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    @property
    def has_critical(self) -> bool:
        return self.count(CRITICAL) > 0

    @property
    def has_unknown(self) -> bool:
        return self.count(UNKNOWN) > 0

    @property
    def ok(self) -> bool:
        """OK == ni CRITICAL ni UNKNOWN. Un UNKNOWN jamás puntúa como OK."""
        return not self.has_critical and not self.has_unknown

    def exit_code(self) -> int:
        if self.has_critical:
            return EXIT_CRITICAL
        if self.has_unknown:
            return EXIT_UNKNOWN
        return EXIT_OK

    def verdict(self) -> str:
        if self.has_critical:
            return CRITICAL
        if self.has_unknown:
            return UNKNOWN
        if self.count(WARNING):
            return WARNING
        return "OK"

    def to_json(self) -> str:
        return json.dumps(
            {
                "verdict": self.verdict(),
                "exit_code": self.exit_code(),
                "checks_run": self.checks_run,
                "totals": {lv: self.count(lv) for lv in LEVELS},
                "findings": [asdict(f) for f in self.findings],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )

    def to_text(self) -> str:
        order = {CRITICAL: 0, UNKNOWN: 1, WARNING: 2, INFO: 3}
        lines = [f"comprobaciones ejecutadas: {', '.join(self.checks_run) or '(ninguna)'}"]
        for f in sorted(self.findings, key=lambda f: (order[f.level], f.check, f.subject)):
            subj = f" [{f.subject}]" if f.subject else ""
            extra = f" {json.dumps(f.detail, ensure_ascii=False)}" if f.detail else ""
            lines.append(f"{f.level:8} {f.check}{subj} {f.message}{extra}")
        lines.append(
            "TOTAL  " + "  ".join(f"{lv}={self.count(lv)}" for lv in LEVELS)
        )
        lines.append(f"VEREDICTO: {self.verdict()} (exit {self.exit_code()})")
        return "\n".join(lines)

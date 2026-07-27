# -*- coding: utf-8 -*-
"""Senales de proveedores no locales: Ollama y externos.

Prompt maestro §2, sin interpretacion posible: solo el motor local valida,
aprueba, invalida y autoriza escrituras. Ollama propone, razona, clasifica y
ayuda a validar; los externos aportan potencia. **Ninguno decide.**

Como se materializa eso aqui, y no en un comentario:

1. una `ExternalSignal` NO puede tener `provider == "local"` — una senal local
   no es una senal, es una regla, y las reglas viven en los ejes;
2. `contribute` solo devuelve hallazgos de gravedad `INFO` (se consulto) o
   `REVIEW` (disiente del motor). **No existe ningun camino por el que una
   senal produzca `ACCEPT`, suba una confianza o retire un hallazgo.** La
   funcion es monotona hacia lo restrictivo, y hay un test de mutacion que lo
   comprueba;
3. cada senal aporta su entrada VERAZ a `provider_trace`, con su proveedor,
   su nombre, su version y su modelo. Una senal consultada y no trazada seria
   procedencia perdida en silencio.

Consecuencia practica: un motor al que se le pasen mil senales entusiastas y
ninguna evidencia verificable sigue sin aprobar nada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..contracts.base import provider_step
from . import findings as F


@dataclass(frozen=True)
class ExternalSignal:
    """Opinion de un proveedor no local sobre un claim.

    `step` es el identificador que llevara en `provider_trace`; debe ser unico
    dentro de un documento (el validador congelado rechaza pasos duplicados).
    """

    claim_id: str
    step: str
    provider: str  # "ollama" | "external"
    name: str
    version: str
    model: Optional[str] = None
    predicate: Optional[str] = None
    direction: Optional[str] = None
    confidence: float = 0.0
    notes: str = ""

    def __post_init__(self) -> None:
        if self.provider not in ("ollama", "external"):
            raise ValueError(
                "una senal solo puede venir de 'ollama' o 'external': lo que produce "
                "codigo local no es una senal, es una regla del motor"
            )

    def trace_entry(self) -> dict:
        """Entrada de `provider_trace` veraz para esta senal."""
        return provider_step(
            self.step,
            self.provider,
            self.name,
            self.version,
            ["signal.predicate", "signal.direction"],
            model=self.model,
        )


def contribute(
    signals: Iterable[ExternalSignal],
    *,
    local_predicate: Optional[str],
    local_direction: Optional[str],
) -> list[F.Finding]:
    """Hallazgos derivados de las senales. Solo restrictivos, jamas permisivos.

    * senal consultada -> `INFO EXTERNAL_SIGNAL_CONSULTED`;
    * senal que propone otro predicado o direccion que el motor -> `REVIEW`.
      Que un modelo discrepe no prueba que el modelo tenga razon; prueba que
      hay algo que un humano deberia mirar.

    Si el motor no llego a fijar predicado (porque ya se abstuvo o rechazo), la
    discrepancia no se evalua: no hay con que discrepar, y convertir eso en
    revision seria dejar que la senal reactivase un claim ya descartado.
    """
    out: list[F.Finding] = []
    for signal in signals:
        out.append(
            F.EXTERNAL_SIGNAL_CONSULTED(
                f"{signal.provider}:{signal.name} ({signal.model or 'sin modelo'})"
            )
        )
        if local_predicate is None:
            continue
        if signal.predicate and signal.predicate != local_predicate:
            out.append(
                F.EXTERNAL_SIGNAL_DISSENTS(
                    f"{signal.provider} propone {signal.predicate}, el motor {local_predicate}"
                )
            )
        elif signal.direction and local_direction and signal.direction != local_direction:
            out.append(
                F.EXTERNAL_SIGNAL_DISSENTS(
                    f"{signal.provider} propone {signal.direction}, el motor {local_direction}"
                )
            )
    return out


def signals_by_claim(signals: Iterable[ExternalSignal]) -> dict[str, list[ExternalSignal]]:
    """Agrupa por `claim_id`, conservando el orden de llegada."""
    out: dict[str, list[ExternalSignal]] = {}
    for signal in signals:
        out.setdefault(signal.claim_id, []).append(signal)
    return out

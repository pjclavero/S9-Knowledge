"""Estadística honesta para el laboratorio de rendimiento.

Reglas que impone este módulo:

  * Nada de una sola pasada. Toda latencia se resume sobre >= ``MIN_REPS``
    repeticiones.
  * Se reporta MEDIANA y DISPERSIÓN (MAD y rango intercuartílico), no la media
    a secas: una sola pausa del recolector de basura desplaza la media y no la
    mediana.
  * ``comparar()`` responde a la única pregunta que importa al comparar dos
    configuraciones: ¿el efecto es mayor que el ruido? Si no lo es, el veredicto
    es "indistinguible del ruido" y NO se reporta mejora.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict
from typing import Any

MIN_REPS = 5


@dataclass
class Resumen:
    n: int
    mediana_ms: float
    mad_ms: float
    iqr_ms: float
    p05_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    media_ms: float
    dispersion_relativa: float  # MAD / mediana

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pct(orden: list[float], p: float) -> float:
    if not orden:
        return 0.0
    k = min(len(orden) - 1, max(0, int(round((p / 100) * (len(orden) - 1)))))
    return orden[k]


def resumir(muestras_s: list[float]) -> Resumen:
    if len(muestras_s) < MIN_REPS:
        raise ValueError(
            f"{len(muestras_s)} repeticiones: por debajo del mínimo de {MIN_REPS}. "
            "Un número de una sola pasada no es una medida."
        )
    ms = sorted(x * 1000 for x in muestras_s)
    mediana = statistics.median(ms)
    mad = statistics.median([abs(x - mediana) for x in ms])
    q1, q3 = _pct(ms, 25), _pct(ms, 75)
    return Resumen(
        n=len(ms),
        mediana_ms=round(mediana, 4),
        mad_ms=round(mad, 4),
        iqr_ms=round(q3 - q1, 4),
        p05_ms=round(_pct(ms, 5), 4),
        p95_ms=round(_pct(ms, 95), 4),
        min_ms=round(ms[0], 4),
        max_ms=round(ms[-1], 4),
        media_ms=round(statistics.fmean(ms), 4),
        dispersion_relativa=round(mad / mediana, 4) if mediana else 0.0,
    )


@dataclass
class Comparacion:
    base_mediana_ms: float
    otra_mediana_ms: float
    efecto_ms: float
    ruido_ms: float          # MAD combinado
    factor_efecto_ruido: float | None   # None si no hay dispersión medible
    veredicto: str           # "peor" | "mejor" | "indistinguible del ruido" |
                             # "sin dispersión medible (MAD combinado 0): no se afirma nada"

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def comparar(base: Resumen, otra: Resumen, *, k: float = 3.0) -> Comparacion:
    """¿La diferencia entre dos medidas supera el ruido de medida?

    ``k`` = cuántos MAD combinados debe superar el efecto para creérselo. Con
    k=3 se descarta la mayoría de las diferencias que sólo son jitter de una
    máquina compartida.
    """
    efecto = otra.mediana_ms - base.mediana_ms
    ruido = base.mad_ms + otra.mad_ms
    umbral = k * ruido

    if ruido == 0:
        # MAD combinado 0: el instrumento NO tiene estimación de dispersión, así
        # que el umbral vale 0 y la regla se invierte —cualquier diferencia,
        # 0.0005 ms incluidos, superaría el umbral y se declararía "peor" con
        # `factor = inf`. Sin dispersión no se afirma nada. (Latente en el
        # baseline: MAD combinado mínimo medido 0.0618 ms, 0 filas con ruido 0;
        # se cierra antes de que deje de serlo.)
        return Comparacion(
            base_mediana_ms=base.mediana_ms,
            otra_mediana_ms=otra.mediana_ms,
            efecto_ms=round(efecto, 4),
            ruido_ms=0.0,
            factor_efecto_ruido=None,
            veredicto="sin dispersión medible (MAD combinado 0): no se afirma nada",
        )

    if abs(efecto) <= umbral:
        veredicto = "indistinguible del ruido"
    elif efecto > 0:
        veredicto = "peor"
    else:
        veredicto = "mejor"
    return Comparacion(
        base_mediana_ms=base.mediana_ms,
        otra_mediana_ms=otra.mediana_ms,
        efecto_ms=round(efecto, 4),
        ruido_ms=round(ruido, 4),
        factor_efecto_ruido=round(abs(efecto) / ruido, 2),
        veredicto=veredicto,
    )

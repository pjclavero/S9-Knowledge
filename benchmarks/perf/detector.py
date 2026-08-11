"""Detector de N+1 con TRES EJES y un criterio absoluto.

Por qué se rehizo
-----------------
El detector de v1 declaraba detectar N+1 comparando el número de llamadas a la
fuente entre el dataset pequeño y el grande. Su propia calibración demostró que
NO detectaba el N+1 que decía detectar: un N+1 por elemento de PÁGINA (50
elementos -> 50 consultas extra) da exactamente el mismo número de llamadas con
100 entidades que con 10.000, así que el eje del dataset lo declaraba
"constante". Un detector así produce ceros tranquilizadores, no evidencia.

Criterio de v2
--------------
Todos los ejes miden lo mismo: **cuántas llamadas EXTRA a la fuente cuesta cada
elemento adicional** (pendiente), no un cociente. Un cociente es ciego a las
constantes (5 -> 7 llamadas es ratio 1.4 y sin embargo son 2 consultas por
elemento si sólo se añadieron 2 elementos) y es inestable cuando la base es 1.

  pendiente = (llamadas_grande - llamadas_pequeno) / (elementos_grande - elementos_pequeno)

  pendiente >= UMBRAL_POR_ELEMENTO (0.5)  -> "N+1"
  en otro caso                            -> "constante"

Los tres ejes son necesarios porque hay tres formas distintas de N+1 y ninguna
las cubre todas:

  * EJE DATASET  — una llamada por entidad del grafo. Crece con el tamaño del
    dataset a página fija.
  * EJE PÁGINA   — una llamada por elemento devuelto. Crece con ``limit``,
    invisible en el eje del dataset. **Éste es el que v1 no tenía y por el que
    el detector fallaba su calibración.**
  * EJE GRADO    — una llamada por relación del nodo pedido. No depende ni del
    dataset ni de la página, sólo del GRADO. Es el que caza el N+1 real de la
    ficha de entidad y por el que los hubs son el caso que revienta.

Cada eje se puede poner rojo y verde a voluntad; ``benchmarks/perf/calibracion.py``
lo demuestra antes de que se emita ninguna cifra.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

UMBRAL_POR_ELEMENTO = 0.5

EJES = ("dataset", "pagina", "grado")


@dataclass
class Dictamen:
    eje: str
    escenario: str
    x_pequeno: int
    x_grande: int
    llamadas_pequeno: int
    llamadas_grande: int
    pendiente: float
    veredicto: str

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def rojo(self) -> bool:
        return self.veredicto == "N+1"


def dictaminar(eje: str, escenario: str, medidas: dict[int, int]) -> Dictamen:
    """``medidas``: {valor del eje -> llamadas a la fuente}. Mínimo dos puntos."""
    if eje not in EJES:
        raise ValueError(f"eje desconocido: {eje}")
    if len(medidas) < 2:
        raise ValueError(f"{eje}/{escenario}: hacen falta al menos dos puntos")
    xs = sorted(medidas)
    x0, x1 = xs[0], xs[-1]
    if x1 == x0:
        raise ValueError(f"{eje}/{escenario}: los dos puntos del eje son iguales")
    y0, y1 = medidas[x0], medidas[x1]
    pendiente = (y1 - y0) / (x1 - x0)
    return Dictamen(
        eje=eje,
        escenario=escenario,
        x_pequeno=x0,
        x_grande=x1,
        llamadas_pequeno=y0,
        llamadas_grande=y1,
        pendiente=round(pendiente, 4),
        veredicto="N+1" if pendiente >= UMBRAL_POR_ELEMENTO else "constante",
    )


def hay_rojo(dictamenes: list[Dictamen]) -> bool:
    return any(d.rojo for d in dictamenes)


# ---------------------------------------------------------------------------
# Presupuestos: umbrales absolutos de llamadas por escenario
# ---------------------------------------------------------------------------

@dataclass
class Incumplimiento:
    escenario: str
    magnitud: str
    presupuesto: float
    medido: float

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def comprobar_presupuestos(
    medido: dict[str, dict[str, float]],
    presupuestos: dict[str, dict[str, float]],
) -> list[Incumplimiento]:
    """Compara magnitudes absolutas contra un techo declarado.

    Se usa sobre ``llamadas_fuente`` (determinista: mismo código, mismo número)
    y NO sobre milisegundos, que en esta máquina tienen más ruido que efecto.
    """
    fallos: list[Incumplimiento] = []
    for escenario, techos in presupuestos.items():
        fila = medido.get(escenario)
        if fila is None:
            fallos.append(Incumplimiento(escenario, "ausente", 0.0, -1.0))
            continue
        for magnitud, techo in techos.items():
            valor = fila.get(magnitud)
            if valor is None:
                fallos.append(Incumplimiento(escenario, magnitud, techo, -1.0))
            elif valor > techo:
                fallos.append(Incumplimiento(escenario, magnitud, techo, valor))
    return fallos

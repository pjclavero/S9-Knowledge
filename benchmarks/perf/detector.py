"""Detector de N+1 con TRES EJES y criterio de CRECIMIENTO, no de umbral.

Historia de dos detectores rotos
--------------------------------
**v1** comparaba llamadas entre el dataset pequeño y el grande. Su propia
calibración demostró que no veía el N+1 por elemento de PÁGINA: con ``limit``
fijo, ese defecto añade las mismas llamadas con 100 que con 10.000 entidades.

**v2.0** añadió los ejes de página y grado, pero cortó con un umbral fijo de
0.5 llamadas por elemento. Ese corte es ciego a los N+1 PARCIALES, que son los
realistas (una consulta extra sólo para las entidades con cierto atributo).
Medido: 1 consulta por cada 2 elementos -> 0.50 detectado; 1 por cada 3 ->
0.333 "constante"; 1 por cada 5 -> 0.20 "constante"; sqrt(tamaño) -> 0.078
"constante". Tres defectos reales declarados sanos por un número inventado.

Criterio de v2.1
----------------
El número de llamadas a la fuente es **determinista**: mismo código y mismos
datos dan el mismo número, sin ruido de medida. Por tanto la pregunta correcta
no es "¿la pendiente supera 0.5?" sino **"¿crece o no crece?"**. Un endpoint
sano no crece NADA: su serie es plana.

    crecimiento_total = max(y) - min(y)

    crecimiento_total == 0                      -> "constante"
    serie no decreciente y crecimiento >= 2      -> "N+1" (lineal o sublineal)
    cualquier otra cosa                          -> "no concluyente"

"No concluyente" NO es "constante". Es el veredicto para series que suben y
bajan, donde el eje está confundido con otra variable (el caso típico: el eje
del dataset sobre la ficha de entidad, cuyo coste depende del GRADO del nodo,
que cambia de un grafo generado a otro). Declararlas sanas sería exactamente el
error de v1 y v2.0.

La FORMA del crecimiento se clasifica aparte, para informar sin decidir:

    pendiente = (y_ultimo - y_primero) / (x_ultimo - x_primero)
    pendiente >= 1.0   -> "lineal o peor"
    pendiente >  0     -> "sublineal / parcial"

Y un dictamen firme exige **al menos tres puntos**: guardar un único punto no
demuestra una pendiente. Con dos puntos el veredicto es "insuficiente".
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

# Crecimiento absoluto mínimo para llamar N+1 a una serie creciente. Con 1 sola
# llamada de diferencia entre los extremos puede tratarse de una constante que
# depende del contenido (un `if` que hace una consulta extra una vez). Con 2 o
# más, y monótono, hay un coste por elemento.
CRECIMIENTO_MINIMO = 2
PUNTOS_MINIMOS = 3

EJES = ("dataset", "pagina", "grado")


@dataclass
class Dictamen:
    eje: str
    escenario: str
    puntos: list[list[int]]          # [[x, llamadas], ...] ordenado por x
    crecimiento_total: int
    monotona_no_decreciente: bool
    pendiente: float
    forma: str
    veredicto: str                   # constante | N+1 | no concluyente | insuficiente
    motivo: str = ""

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def rojo(self) -> bool:
        return self.veredicto == "N+1"


def dictaminar(eje: str, escenario: str, medidas: dict[int, int]) -> Dictamen:
    """``medidas``: {valor del eje -> llamadas a la fuente}."""
    if eje not in EJES:
        raise ValueError(f"eje desconocido: {eje}")
    if len(medidas) < 2:
        raise ValueError(f"{eje}/{escenario}: hacen falta al menos dos puntos")

    xs = sorted(medidas)
    ys = [medidas[x] for x in xs]
    puntos = [[x, medidas[x]] for x in xs]
    crecimiento = max(ys) - min(ys)
    monotona = all(b >= a for a, b in zip(ys, ys[1:]))
    pendiente = round((ys[-1] - ys[0]) / (xs[-1] - xs[0]), 4) if xs[-1] != xs[0] else 0.0

    if pendiente >= 1.0:
        forma = "lineal o peor"
    elif pendiente > 0:
        forma = "sublineal / parcial"
    else:
        forma = "plana"

    if len(medidas) < PUNTOS_MINIMOS:
        veredicto, motivo = "insuficiente", (
            f"{len(medidas)} puntos; hacen falta {PUNTOS_MINIMOS} para afirmar una pendiente"
        )
    elif crecimiento == 0:
        veredicto, motivo = "constante", "la serie es plana: no crece nada"
    elif monotona and crecimiento >= CRECIMIENTO_MINIMO:
        veredicto, motivo = "N+1", (
            f"crece {crecimiento} llamadas de forma no decreciente ({forma})"
        )
    elif monotona:
        veredicto, motivo = "no concluyente", (
            f"crece sólo {crecimiento} llamada(s): puede ser una constante dependiente "
            f"del contenido; hacen falta más puntos o más rango"
        )
    else:
        veredicto, motivo = "no concluyente", (
            "la serie sube y baja: el eje está confundido con otra variable "
            "(no se declara sano)"
        )

    return Dictamen(
        eje=eje,
        escenario=escenario,
        puntos=puntos,
        crecimiento_total=crecimiento,
        monotona_no_decreciente=monotona,
        pendiente=pendiente,
        forma=forma,
        veredicto=veredicto,
        motivo=motivo,
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

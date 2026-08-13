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

import re
from dataclasses import dataclass, asdict
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
    carga_saturada: bool = False

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def rojo(self) -> bool:
        return self.veredicto == "N+1"


def serie_saturada(xs: list[int], cargas: list[int]) -> bool:
    """¿La respuesta viene RECORTADA y ha dejado de crecer?

    Sin esta señal, un endpoint con tope (``min(2*g+3, 300)``) produce una serie
    de llamadas PLANA en cuanto los puntos superan el tope, y el detector la
    declara "constante, pendiente 0.0": un N+1 de 300 consultas por petición
    firmado como sano. Plano no es sano si la respuesta está recortada.

    El criterio no usa ningún umbral: compara la carga DEVUELTA con el propio
    eje, que en el eje del grado es el número de relaciones que EXISTEN. Si se
    devuelven menos de las que hay (recorte) en los dos últimos puntos y además
    la carga no ha crecido entre ellos, el tope está tapando el crecimiento.

    Exige que ``cargas`` sea comparable con ``xs`` (misma unidad); sólo el eje
    del grado lo cumple, y sólo él pasa ``carga`` a ``dictaminar``.
    """
    if len(xs) < 2 or len(xs) != len(cargas):
        return False
    recortada = [c < x for x, c in zip(xs, cargas)]
    return cargas[-1] == cargas[-2] and recortada[-1] and recortada[-2]


def dictaminar(
    eje: str,
    escenario: str,
    medidas: dict[int, int],
    *,
    carga: dict[int, int] | None = None,
) -> Dictamen:
    """``medidas``: {valor del eje -> llamadas a la fuente}.

    ``carga``: {valor del eje -> elementos DEVUELTOS}. Opcional, pero sin ella
    una serie plana no se puede distinguir de una serie recortada por un tope.
    """
    if eje not in EJES:
        raise ValueError(f"eje desconocido: {eje}")
    if len(medidas) < 2:
        raise ValueError(f"{eje}/{escenario}: hacen falta al menos dos puntos")

    xs = sorted(medidas)
    ys = [medidas[x] for x in xs]
    saturada = serie_saturada(xs, [carga[x] for x in xs]) if carga and all(
        x in carga for x in xs) else False
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
    elif crecimiento == 0 and saturada:
        veredicto, motivo = "no concluyente", (
            "la serie de llamadas es plana, pero la CARGA DEVUELTA está saturada "
            "(tocó su máximo y dejó de crecer): el tope tapa el crecimiento y "
            "declarar 'constante' firmaría como sano un coste recortado"
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
        carga_saturada=saturada,
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


# ---------------------------------------------------------------------------
# SATURACIÓN: ¿el tramo sigue comparando la misma carga?
# ---------------------------------------------------------------------------
#
# Criterio de v2.0 (roto, medido)
# -------------------------------
# ``saturado = bool(da) and da == db``: el desglose ENTERO idéntico entre los
# dos tamaños. Medido sobre las 65 filas del baseline:
#
#   * ``api_graph_300`` —el endpoint que da nombre a la saturación— sale
#     ``saturado=False`` en los 6 tramos, INCLUIDO el tramo real 250->500,
#     donde el desglose pasa de ``{nodes:250, edges:750}`` a
#     ``{nodes:300, edges:550}``: los diccionarios difieren (uno topa, el otro
#     se desploma), luego el criterio de igualdad dice "no saturado". FALSO
#     NEGATIVO justo donde importa.
#   * ``api_sources`` sale ``saturado=True`` 3 veces con ``{sources: 4}`` en
#     ambos extremos, cuando no satura nada: su serie es 4,4,4,4,10,20 y
#     termina creciendo. FALSO POSITIVO por planicie inicial.
#   * ``api_entity_detalle`` sale ``saturado=True`` una vez por coincidencia
#     numérica (``{outgoing:2, incoming:2}`` en dos GRAFOS DISTINTOS).
#
# Criterio de v2.1
# ----------------
# La saturación es una propiedad de CADA COMPONENTE de la respuesta a lo largo
# de la serie completa, no de la igualdad de dos diccionarios. Un componente
# está saturado en el tramo a->b si:
#
#   (1) TOCA UN TECHO DECLARADO: la URL trae ``limit=N``, el componente está
#       acotado por él (nunca lo supera en toda la serie) y en ``b`` vale >= N.
#       El requisito de "acotado" evita achacar el ``limit=300`` de los NODOS a
#       las ARISTAS, que llegan a 750 y no las limita nadie.
#   (2) MESETA EN SU MÁXIMO: se queda igual (``vb == va``), ese valor es el
#       máximo de toda la serie, la serie es no decreciente hasta ahí y ANTES
#       había crecido. El "antes había crecido" es lo que distingue un techo
#       implícito (``/api/search`` corta en 50 sin decirlo) de un componente
#       que simplemente todavía no ha empezado a moverse (``api_sources``).
#
# Un componente que DECRECE no se declara saturado por sí solo —dos grafos
# distintos dan grados distintos, y eso es confusión, no saturación— pero si la
# fila ya está saturada por otro componente, se registra como COLAPSO: es el
# caso de las aristas de ``/api/graph?limit=300``, que caen de 750 a 550
# mientras los nodos topan en 300.

_LIMITE_EN_URL = re.compile(r"[?&]limit=(\d+)")


def techo_declarado(url: str) -> int | None:
    """El ``limit=N`` que la propia URL pide, si lo hay."""
    m = _LIMITE_EN_URL.search(url or "")
    return int(m.group(1)) if m else None


def analizar_saturacion(
    url: str,
    series: dict[str, list[int]],
    idx: int,
    *,
    exigir_acotado: bool = True,
    exigir_maximo: bool = True,
    exigir_crecimiento_previo: bool = True,
) -> dict[str, Any]:
    """Saturación del tramo ``idx -> idx+1`` para un escenario.

    ``series``: {componente de la respuesta -> valores en TODOS los tamaños}.
    Devuelve ``{saturado, componentes_saturados, componentes_que_decrecen}``.

    Los tres ``exigir_*`` valen ``True`` en producción y existen para que la
    calibración pueda ABLACIONAR cada cláusula sobre ESTE MISMO código —no
    sobre una copia— y comprobar que cada una es necesaria. Ver C9c.
    """
    techo = techo_declarado(url)
    saturados: list[dict[str, Any]] = []
    decrecen: list[dict[str, Any]] = []

    for comp, ys in sorted(series.items()):
        if idx + 1 >= len(ys) or any(y is None for y in ys):
            continue
        va, vb = ys[idx], ys[idx + 1]
        tope_serie = max(ys)

        acotado_por_techo = techo is not None and (
            tope_serie <= techo or not exigir_acotado)
        toca_techo = bool(acotado_por_techo) and vb >= techo

        hasta_b = ys[: idx + 2]
        crecio_antes = any(y < z for y, z in zip(ys[: idx + 1], ys[1: idx + 1]))
        monotona = all(y <= z for y, z in zip(hasta_b, hasta_b[1:]))
        meseta = (
            vb == va
            and (vb == tope_serie or not exigir_maximo)
            and (crecio_antes or not exigir_crecimiento_previo)
            and monotona
        )

        if toca_techo or meseta:
            saturados.append({
                "componente": comp,
                "valores": [va, vb],
                "techo_declarado": techo if toca_techo else None,
                "motivo": (f"toca el techo declarado limit={techo}" if toca_techo
                           else "meseta en el máximo de la serie (techo implícito)"),
            })
        elif vb < va:
            decrecen.append({"componente": comp, "valores": [va, vb]})

    return {
        "saturado": bool(saturados),
        "componentes_saturados": saturados,
        "componentes_que_decrecen": decrecen,
    }


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

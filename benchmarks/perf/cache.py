"""Caché de datasets CON HUELLA.

Defecto que corrige (heredado de v1)
------------------------------------
v1 cacheaba ``/tmp/s9k-perf/grafo_<n>.json`` y lo reutilizaba con un simple
``if not ruta.exists()``. Es decir: la caché no sabía NADA de los datos que
contenía. Consecuencias reales:

  * Se arregla un defecto del generador (por ejemplo, el nivel de visibilidad
    fuera de vocabulario que dejaba invisible el 25 % de los nodos) y las
    mediciones siguientes siguen leyendo el fichero viejo: el defecto vuelve sin
    que nada avise.
  * Se cambia la semilla, el grado o el número de hubs y se mide otro grafo
    creyendo que es el pedido.

Contrato de v2
--------------
Junto a cada fichero de datos se guarda un ``*.huella.json`` con la huella de
``dataset.huella(parametros)``. Al pedir un dataset:

  * no hay fichero, o no hay sidecar, o la huella no coincide  -> se REGENERA;
  * la huella coincide                                         -> se reutiliza.

``obtener()`` devuelve además el ESTADO ("generado" | "reutilizado" |
"regenerado_por_huella" | "regenerado_sin_huella"), para que la calibración
pueda exigir ver la invalidación con sus propios ojos.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import dataset
from dataset import Parametros

RAIZ_CACHE = Path(os.environ.get("PERF_TMP", "/tmp/s9k-perf-v2"))


@dataclass
class Entrada:
    ruta: Path
    huella: str
    estado: str


def _nombre(p: Parametros) -> str:
    base = f"grafo_{p.n_entities}"
    if p.hubs:
        base += f"_hubs{p.hubs}x{p.grado_hub}"
    if p.seed != dataset.SEMILLA:
        base += f"_s{p.seed}"
    if p.edges_per_node != dataset.EDGES_PER_NODE:
        base += f"_g{p.edges_per_node}"
    return base + ".json"


def ruta_de(p: Parametros, raiz: Path | None = None) -> Path:
    return (raiz or RAIZ_CACHE) / _nombre(p)


def _sidecar(ruta: Path) -> Path:
    return ruta.with_suffix(ruta.suffix + ".huella.json")


def leer_huella(ruta: Path) -> str | None:
    s = _sidecar(ruta)
    if not s.exists():
        return None
    try:
        return json.loads(s.read_text(encoding="utf-8")).get("huella")
    except Exception:
        return None


def obtener(p: Parametros, raiz: Path | None = None) -> Entrada:
    """Devuelve el dataset pedido, regenerándolo si la huella no cuadra."""
    ruta = ruta_de(p, raiz)
    esperada = dataset.huella(p)

    if not ruta.exists():
        estado = "generado"
    else:
        guardada = leer_huella(ruta)
        if guardada is None:
            estado = "regenerado_sin_huella"
        elif guardada != esperada:
            estado = "regenerado_por_huella"
        else:
            return Entrada(ruta, esperada, "reutilizado")

    dataset.escribir(p, ruta)
    _sidecar(ruta).write_text(
        json.dumps(
            {
                "huella": esperada,
                "parametros": p.como_dict(),
                "formato": dataset.FORMATO_VERSION,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return Entrada(ruta, esperada, estado)

"""Caché de datasets CON HUELLA DE GENERADOR **Y DE CONTENIDO**.

Defecto de v1
-------------
v1 reutilizaba ``grafo_<n>.json`` con un simple ``if not ruta.exists()``. La
caché no sabía nada de lo que contenía, así que al arreglar el generador —el
nivel de visibilidad fuera de vocabulario que dejaba invisible el 25 % de los
nodos— los ficheros ya cacheados seguían con el grafo malo.

Defecto de v2.0 (lo mismo, un piso más abajo)
---------------------------------------------
v2.0 guardó la huella del GENERADOR (código + parámetros + vocabulario), pero
no la del FICHERO. Demostrado por el revisor: se genera el dataset, se **trunca
el fichero a 2 nodos y se les mete el defecto histórico** ``visibility:
"public"``, se deja el sidecar intacto -> estado ``reutilizado``, defecto
resucitado, cero avisos. La docstring prometía cubrir "los datos" y cubría el
generador.

Contrato de v2.1
----------------
El sidecar ``*.huella.json`` guarda DOS hashes:

  * ``huella``      — generador + parámetros + vocabulario + versión de formato;
  * ``sha256_fichero`` — SHA-256 de los bytes escritos.

Al pedir un dataset se comprueban los dos. Cualquier discrepancia regenera:

  ``generado`` | ``reutilizado`` | ``regenerado_por_huella`` |
  ``regenerado_por_contenido`` | ``regenerado_sin_huella``
"""
from __future__ import annotations

import hashlib
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
    sha_fichero: str
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


def sha_de_fichero(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_sidecar(ruta: Path) -> dict | None:
    s = _sidecar(ruta)
    if not s.exists():
        return None
    try:
        return json.loads(s.read_text(encoding="utf-8"))
    except Exception:
        return None


def _escribir(p: Parametros, ruta: Path, esperada: str, estado: str) -> Entrada:
    dataset.escribir(p, ruta)
    sha = sha_de_fichero(ruta)
    _sidecar(ruta).write_text(
        json.dumps(
            {
                "huella": esperada,
                "sha256_fichero": sha,
                "bytes": ruta.stat().st_size,
                "parametros": p.como_dict(),
                "formato": dataset.FORMATO_VERSION,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return Entrada(ruta, esperada, sha, estado)


def obtener(p: Parametros, raiz: Path | None = None) -> Entrada:
    """Devuelve el dataset pedido, regenerándolo si algo no cuadra."""
    ruta = ruta_de(p, raiz)
    esperada = dataset.huella(p)

    if not ruta.exists():
        return _escribir(p, ruta, esperada, "generado")

    sidecar = leer_sidecar(ruta)
    if sidecar is None or "huella" not in sidecar or "sha256_fichero" not in sidecar:
        return _escribir(p, ruta, esperada, "regenerado_sin_huella")
    if sidecar["huella"] != esperada:
        return _escribir(p, ruta, esperada, "regenerado_por_huella")
    # La huella del generador cuadra: ahora, ¿el fichero es el que se escribió?
    if sha_de_fichero(ruta) != sidecar["sha256_fichero"]:
        return _escribir(p, ruta, esperada, "regenerado_por_contenido")

    return Entrada(ruta, esperada, sidecar["sha256_fichero"], "reutilizado")

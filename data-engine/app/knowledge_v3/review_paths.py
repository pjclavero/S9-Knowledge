# -*- coding: utf-8 -*-
"""Resolucion CANONICA de las rutas del almacen de revision V3.

POR QUE ESTE MODULO EXISTE
--------------------------
Slice 2 · Corte 3 encontro el mismo patron por tercera vez: una capacidad
completa y SIN LLAMADOR en el camino del producto. `Pipeline.run` sabia
exportar propuestas (`review_proposals_dir`), pero la cadena que el panel usa
—`/panel/operations` -> `ingest_v3` -> `run_ingest`— no le pasaba nunca esa
ruta. El informe decia `REVIEW=2` y `/panel/review` decia «Sin propuestas
visibles». El operador daba por buena una ingesta cuyas ambiguedades no vio.

Al enchufar el llamador aparecio el riesgo de siempre: el handler derivaria una
ruta por su cuenta y `default_proposals_dir()` del visor derivaria otra. **Si
hay dos derivaciones de una ruta, hay dos verdades**, y el sintoma seria
exactamente el mismo que se acaba de arreglar: el motor escribiendo propuestas
en una carpeta y el visor mirando otra, ambos «funcionando».

Por eso la resolucion vive AQUI y SOLO AQUI. El visor no vuelve a derivarla:
`app.services.v3_review.default_proposals_dir` reexporta esta funcion.

INVARIANTE DE DESPLIEGUE
------------------------
``S9K_V3_REVIEW_PROPOSALS_DIR`` la comparten ESCRITOR (el worker que corre la
ingesta) y LECTOR (el visor que pinta `/panel/review`). Si cada servicio la
resuelve a un almacenamiento distinto, no hay error: hay una cola de revision
vacia y un operador tranquilo. Es la misma exigencia que el Corte 2 ya impuso a
``review.sqlite3``. Queda declarada en ``docs/88`` y en el rol de despliegue.

DIRECCION DE IMPORTACION
------------------------
Motor -> visor NO se puede: motor y visor publican dos paquetes ``app``
distintos (ver ``review_decisions.py``). Visor -> motor SI, y ya se hace: es el
puente que usa ``viewer/app/jobs_client.py`` para `jobs.job_store`. Por eso el
unico resolvedor vive en el motor y es el visor quien lo importa.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["PROPOSALS_DIR_ENV", "default_proposals_dir"]

#: La variable del invariante de despliegue. Se nombra una sola vez en todo el
#: producto: cualquier otra lectura de este nombre seria la segunda derivacion.
PROPOSALS_DIR_ENV = "S9K_V3_REVIEW_PROPOSALS_DIR"


def default_proposals_dir() -> Path:
    """El almacen de propuestas de revision. UNICA derivacion del producto.

    Precedencia:
      1. ``S9K_V3_REVIEW_PROPOSALS_DIR``, si esta declarada;
      2. la ubicacion por defecto del repositorio,
         ``viewer/output/reviews-v3/proposals``.

    El defecto apunta al arbol del VISOR a proposito: es quien tiene que leerlo.
    """
    configured = os.environ.get(PROPOSALS_DIR_ENV)
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[3]
        / "viewer" / "output" / "reviews-v3" / "proposals"
    )

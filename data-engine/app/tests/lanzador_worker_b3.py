# -*- coding: utf-8 -*-
"""Lanzador de PRUEBA del worker REAL (B3 · USABLE-V1 · H-02). No es producto.

Arranca `jobs.worker.main` -- el mismo punto de entrada que la unidad
`s9-knowledge-worker.service` -- en un PROCESO PROPIO, para que las pruebas
puedan matarlo, pararlo con SIGTERM y re-arrancarlo como haria systemd. Lo
unico que anade es lo que una prueba no puede fabricar desde fuera:

* ``S9K_B3_HANDLERS_DE_PRUEBA=1`` registra cuatro handlers de prueba
  (``b3_fallar``, ``b3_matar``, ``b3_dormir``, ``b3_dormir_una_vez``). Cuentan
  sus invocaciones en ``S9K_B3_CONTADOR_DIR`` para que la prueba vea CUANTAS
  veces corrio el handler, no solo el estado final.
* ``S9K_B3_GRAFO=doble`` pone el grafo de mentira de `viewer/tests/grafo_doble`
  en el abridor de conexion del handler `ingest_v3` (sin Neo4j, la ingesta
  web sigue siendo dry-run y produce propuestas). ``S9K_B3_GRAFO=caido`` hace
  que el abridor falle con ``GRAPH_OBSERVATION_UNAVAILABLE`` (reintentable),
  el fallo transitorio REAL del handler.

Nada de esto existe en `data-engine/app/jobs`: se instala aqui, en el proceso
de prueba, y se ve en la prueba. El nombre no empieza por ``test_`` a
proposito: pytest no lo recoge.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "data-engine" / "app"))

from jobs import worker  # noqa: E402


def _contar(nombre: str) -> int:
    ruta = Path(os.environ["S9K_B3_CONTADOR_DIR"]) / nombre
    with open(ruta, "a", encoding="utf-8") as fichero:
        fichero.write("x\n")
        fichero.flush()
        os.fsync(fichero.fileno())
    return ruta.read_text(encoding="utf-8").count("x")


def b3_fallar(payload: dict) -> dict:
    _contar("fallar")
    raise RuntimeError("B3_FALLO_DE_PRUEBA: el handler ha fallado a proposito")


def b3_matar(payload: dict) -> dict:
    _contar("matar")
    os.kill(os.getpid(), signal.SIGKILL)
    time.sleep(60)  # pragma: no cover - SIGKILL no vuelve
    return {}


def b3_dormir(payload: dict) -> dict:
    _contar("dormir")
    time.sleep(float(payload.get("segundos", 1)))
    return {"ok": True}


def b3_dormir_una_vez(payload: dict) -> dict:
    n = _contar("dormir_una_vez")
    if n == 1:
        time.sleep(float(payload.get("segundos", 60)))
    return {"ok": True, "invocacion": n}


def b3_dormir_y_fallar(payload: dict) -> dict:
    _contar("dormir_y_fallar")
    time.sleep(float(payload.get("segundos", 3)))
    raise RuntimeError("B3_FALLO_TARDIO: fallo reintentable tras dormir")


def b3_dormir_y_omitir(payload: dict) -> dict:
    _contar("dormir_y_omitir")
    time.sleep(float(payload.get("segundos", 3)))
    raise worker.JobHandlerError("B3_OMISION_TARDIA: omitido tras dormir")


if os.environ.get("S9K_B3_HANDLERS_DE_PRUEBA") == "1":
    worker.HANDLERS.update({
        "b3_fallar": b3_fallar,
        "b3_matar": b3_matar,
        "b3_dormir": b3_dormir,
        "b3_dormir_una_vez": b3_dormir_una_vez,
        "b3_dormir_y_fallar": b3_dormir_y_fallar,
        "b3_dormir_y_omitir": b3_dormir_y_omitir,
    })

_GRAFO = os.environ.get("S9K_B3_GRAFO")
if _GRAFO in ("doble", "caido"):
    sys.path.insert(0, str(REPO / "viewer" / "tests"))
    import grafo_doble  # noqa: E402
    from jobs.handlers import ingest_v3  # noqa: E402

    if _GRAFO == "doble":
        ingest_v3._driver_de_observacion = lambda: grafo_doble.DriverDeCatalogo()
    else:
        def _grafo_caido():
            raise ingest_v3.IngestV3Error("GRAPH_OBSERVATION_UNAVAILABLE")

        ingest_v3._driver_de_observacion = _grafo_caido


if __name__ == "__main__":
    sys.exit(worker.main(sys.argv[1:]))

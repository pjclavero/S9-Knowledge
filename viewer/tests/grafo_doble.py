# -*- coding: utf-8 -*-
"""Un grafo de MENTIRA para las pruebas que no vienen a medir el grafo.

POR QUE EXISTE, Y QUE NO ES
---------------------------
Desde el Slice 2 · Corte 5 el manejador de ingesta del panel abre una conexion
de solo lectura a Neo4j y **falla cerrado** si no la tiene. Eso es el producto,
y es deliberado. Pero hay una docena larga de casos --el recorrido del panel,
los estados de la pantalla de revision, la procedencia del resultado-- que no
vienen a medir la observacion del grafo y que hasta ahora corrian sin Docker.

Este modulo les da un doble. Dos cosas que NO es:

* **No es una puerta trasera del producto.** No hay ni una linea en
  `data-engine/` ni en `viewer/app/` que consulte nada de esto. Se instala con
  `monkeypatch` sobre `_driver_de_observacion`, desde la prueba, y se ve en la
  prueba.
* **No convierte un caso en una medida de la observacion.** Un caso que corra
  con este doble NO puede afirmar «el producto observa el grafo»: solo afirma
  lo suyo con un grafo que responde. La observacion de verdad se mide con
  Neo4j real, bajo `S9K_WRITER_NEO4J_REAL`.

QUE DEVUELVE
------------
Exactamente las entidades del catalogo declarado del ejemplo, como si el grafo
las tuviera. Antes de este corte la corrida del panel sacaba su snapshot de ese
mismo fichero (via `bridge.entities_from_catalog`), asi que el doble mantiene
el material de esos casos donde estaba; lo unico que cambia --y es el punto del
corte-- es que ahora llega por la via observada.

COMO SE COMPARA LA CONSULTA
---------------------------
Por IGUALDAD con la que genera `cypher.list_entities_query`, no por buscar
subcadenas: un doble que respondiera a cualquier Cypher que «se parezca»
acabaria contestando a una consulta distinta de la que el producto hace, y el
caso seguiria verde midiendo otra cosa. Lo que no case devuelve `[]`, y las
consultas se GUARDAN para que un caso pueda mirarlas.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[2]
CATALOGO_EJEMPLO = REPO / "examples" / "ingesta-v3" / "catalogo-workspace.json"

#: Version y hash que el doble estampa en cada nodo. Son PLAUSIBLES y FALSOS, y
#: por eso este doble no sirve para afirmar nada sobre un apply real: contra un
#: grafo de verdad este `expected_hash` daria `EXEC_HASH_MISMATCH`. Existe para
#: que las anclas tengan la FORMA que el sellado exige, no para colarse en un
#: executor.
VERSION_FALSA = 1
#: CADENA PELADA, no `{algorithm, value}`. Es la forma que el writer persiste
#: en la propiedad del nodo (`writer/state.py`) y la unica que
#: `graph_catalog.snapshot_entities` envuelve: con un dict cae en la rama
#: `else` y el ancla sale SIN hash, el planificador emite una proyeccion sin
#: `expected_hash` y el contrato la rechaza ("modifica algo existente sin
#: expected_version/expected_hash"). Medido: era exactamente ese el rojo.
HASH_FALSO = "de" * 32


def filas_del_catalogo(ruta: Optional[Path] = None) -> list[dict]:
    """Las entidades del catalogo del ejemplo, en la forma que el grafo daria.

    Las `provisional: true` se quedan fuera: el fichero dice explicitamente que
    esas NO estan todavia en el grafo, y meterlas aqui seria que el doble
    afirmase justo lo contrario que la fuente de la que sale.
    """
    documento = json.loads((ruta or CATALOGO_EJEMPLO).read_text(encoding="utf-8"))
    filas = []
    for entidad in documento.get("entities") or ():
        if entidad.get("provisional"):
            continue
        filas.append({
            "entity_id": entidad["entity_id"],
            "entity_type": entidad.get("type"),
            "name": entidad.get("name"),
            "aliases": list(entidad.get("aliases") or ()),
            "version": VERSION_FALSA,
            "state_hash": HASH_FALSO,
            "partida_id": None,
            "status": "ACTIVE",
            "labels": ["V3Entity"],
        })
    return filas


class _Sesion:
    def __init__(self, driver: "DriverDeCatalogo"):
        self._driver = driver

    def __enter__(self) -> "_Sesion":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def run(self, cypher_text: str, params: Any = None, **kwargs: Any) -> list[dict]:
        parametros = dict(params or {})
        parametros.update(kwargs)
        self._driver.consultas.append((cypher_text, parametros))
        workspace = parametros.get("ws")
        if workspace is None:
            return []
        from knowledge_v3.writer import cypher as cypher_mod

        esperada = cypher_mod.list_entities_query(
            str(workspace), parametros.get("partida_id")
        ).cypher
        if cypher_text != esperada:
            return []
        return list(self._driver.filas)

    def close(self) -> None:
        return None


class DriverDeCatalogo:
    """Driver falso: contesta a la consulta de catalogo y a nada mas."""

    def __init__(self, filas: Optional[list[dict]] = None):
        self.filas = list(filas) if filas is not None else filas_del_catalogo()
        self.consultas: list[tuple[str, dict]] = []
        self.cerrado = False

    def session(self, **kwargs: Any) -> _Sesion:
        return _Sesion(self)

    def verify_connectivity(self) -> None:
        return None

    def close(self) -> None:
        self.cerrado = True


def instalar(monkeypatch, filas: Optional[list[dict]] = None) -> DriverDeCatalogo:
    """Pone el doble en el sitio del abridor de conexion del manejador.

    **CEDE EL PASO AL GRAFO DE VERDAD.** La decision se toma en el momento de
    la LLAMADA, no al montar la prueba: si para entonces hay una credencial
    declarada (`S9K_NEO4J_PASSWORD_FILE`), se usa el abridor real. Asi un
    modulo puede instalar esto una vez para todos sus casos y aun asi tener
    casos con Neo4j real que observan de verdad, sin que el orden de las
    fixtures decida en silencio cual de los dos manda.
    """
    from jobs.handlers import ingest_v3

    doble = DriverDeCatalogo(filas)
    real = ingest_v3._driver_de_observacion

    def suplente() -> Any:
        if os.environ.get("S9K_NEO4J_PASSWORD_FILE"):
            return real()
        return doble

    monkeypatch.setattr(ingest_v3, "_driver_de_observacion", suplente)
    # EL ABRIDOR DE VERDAD, a mano. Un caso que venga a medir el FALLO CERRADO
    # tiene que poder devolverlo a su sitio: con el doble puesto no hay forma
    # de que el producto falle por no tener grafo, que es justo lo que ese caso
    # mide. Se expone aqui en vez de que cada modulo lo capture por su cuenta.
    doble.real = real
    return doble


__all__ = [
    "CATALOGO_EJEMPLO",
    "DriverDeCatalogo",
    "filas_del_catalogo",
    "instalar",
]

# -*- coding: utf-8 -*-
"""El catalogo del workspace, LEIDO DEL GRAFO en vez de declarado en un fichero.

`ingest_cli --catalogo` lee un JSON que dice que entidades existen. Ese fichero
y el grafo real son dos afirmaciones independientes sobre el mismo mundo, y
nada las contrastaba: el fichero podia decir que `entity:sela-marrec` existe
mientras el grafo estaba vacio. El plan salia adelante, y el APPLY abortaba con
`EXEC_TARGET_MISSING`.

Este modulo es la union que faltaba. La misma estructura que devolvia
`load_catalog` — `entity_id` / `type` / `name` / `aliases` — pero cada fila
sale de un nodo `V3Entity` observado.

TRES COSAS QUE NO SE INVENTAN AQUI
----------------------------------
* **`version`**: es la del nodo. `bridge.entities_from_catalog` la copia al
  `expected_version` del plan y el executor la contrasta contra este mismo
  grafo. Un valor por defecto de 1 sobre un nodo que esta a 0 produce un
  `EXEC_VERSION_MISMATCH` en el apply, no antes.
* **`state_hash`**: idem con `expected_hash`. Desde que el writer lo estampa al
  crear (`writer/state.py`), un nodo escrito por el producto SIEMPRE lo trae.
  Si aun asi falta -- nodos anteriores a ese arreglo, o sembrados a mano -- la
  fila lo trae a `None` y se DECLARA (`ENTIDAD_SIN_STATE_HASH`); no se sustituye
  por el hash derivado, que es plausible y falso.
* **`aliases`**: son los del nodo. EQUIPO 8A: el grafo ya los guarda, y esta
  fila los propaga tal cual. Un nodo que no traiga ninguno sale con la tupla
  vacia y lo DECLARA (`GRAFO_SIN_ALIAS`); no se fabrica ningun alias desde el
  nombre, que es plausible y falso -- y es exactamente el error inverso al que
  este equipo vino a arreglar.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from ..engine.snapshot import SnapshotEntity
from ..resolution.catalog import CatalogEntity, Neo4jEntityCatalog


def catalog_entities(
    driver: Any,
    workspace: str,
    partida_id: Optional[str] = None,
) -> list[CatalogEntity]:
    """Entidades observadas, ya como `CatalogEntity` del resolutor."""
    return list(Neo4jEntityCatalog(driver).entities(workspace, partida_scope=partida_id))


def catalog_rows(
    driver: Any,
    workspace: str,
    partida_id: Optional[str] = None,
) -> list[dict]:
    """Mismo formato que el fichero `--catalogo`, pero observado.

    Se conserva la forma del fichero a proposito: `build_catalog`,
    `build_lexicon` y `bridge.entities_from_catalog` ya la consumen, y cambiar
    el formato para cambiar el origen habria obligado a tocar tres consumidores
    para arreglar uno.
    """
    filas: list[dict] = []
    for entidad in catalog_entities(driver, workspace, partida_id):
        meta = dict(entidad.metadata or {})
        filas.append({
            "entity_id": entidad.entity_id,
            "type": entidad.entity_type,
            "name": entidad.canonical_name,
            "aliases": list(entidad.aliases),
            "version": meta.get("graph_version"),
            "state_hash": meta.get("graph_state_hash"),
            "origen": "grafo",
        })
    return filas


def entity_ids(rows: Iterable[dict]) -> list[str]:
    """Los ids OBSERVADOS. Es el conjunto contra el que se reconcilia."""
    return sorted({str(f["entity_id"]) for f in rows if f.get("entity_id")})


def snapshot_entities(
    rows: Iterable[dict],
    *,
    altas: Iterable[dict] = (),
) -> list[SnapshotEntity]:
    """Snapshot del motor: lo observado, mas las altas APROBADAS por un humano.

    Las observadas llevan la `version` y el `state_hash` del grafo — con el
    hash tal cual, incluso ausente, para que el desajuste salga en la cadena de
    validadores (`concurrency`) y no dentro de una transaccion.

    Las altas entran marcadas `pending_creation`: el motor puede entonces
    aceptar un hecho que las menciona, y el planificador emite su
    `CREATE_ENTITY`. Nada mas las distingue de una entidad real, y nada
    excepto una aprobacion humana las mete en esta lista
    (`entity_decisions.approved_snapshot_entities` es su unica fuente).
    """
    out: list[SnapshotEntity] = []
    for fila in rows:
        if fila.get("provisional"):
            continue
        state_hash = fila.get("state_hash")
        version = fila.get("version")
        out.append(SnapshotEntity(
            entity_id=fila["entity_id"],
            entity_type=fila["type"],
            version=int(version) if version is not None else 0,
            state_hash=(
                {"algorithm": "sha256", "value": state_hash}
                if isinstance(state_hash, str) else None
            ),
            # OBSERVADA: esta fila salio de un nodo `V3Entity` leido, no de un
            # fichero que declara lo que hay. Es el unico sitio del producto
            # que puede afirmarlo, y por eso es el unico que lo marca.
            observed=True,
        ))
    for alta in altas:
        out.append(SnapshotEntity(
            entity_id=alta["entity_id"],
            entity_type=alta["type"],
            version=0,
            state_hash=None,
            pending_creation=True,
            canonical_name=alta.get("name"),
            aliases=tuple(alta.get("aliases") or ()),
        ))
    return sorted(out, key=lambda e: e.entity_id)


def carencias(rows: Iterable[dict]) -> list[dict]:
    """Lo que el grafo NO pudo decir de sus propias entidades."""
    filas = list(rows)
    faltas: list[dict] = []
    sin_hash = [f["entity_id"] for f in filas if not f.get("state_hash")]
    if sin_hash:
        faltas.append({
            "code": "ENTIDAD_SIN_STATE_HASH",
            "detail": (
                "estas entidades no traen `state_hash`, asi que no pueden "
                "anclar un control optimista y ninguna relacion podra "
                "proyectarse sobre ellas hasta que lo tengan. El writer SI lo "
                "escribe al crear, de modo que esto solo alcanza a nodos "
                "anteriores a ese arreglo o sembrados por fuera del producto: "
                + ", ".join(sorted(str(x) for x in sin_hash))
            ),
        })
    # EQUIPO 8A. `GRAFO_SIN_ALIAS` era INCONDICIONAL: se declaraba en cuanto
    # habia una fila, porque el grafo no sabia guardar alias en absoluto. Ya
    # los guarda y los devuelve, asi que la carencia deja de ser una propiedad
    # del grafo y pasa a ser una propiedad de CADA NODO: solo la declaran los
    # que no traen ninguno -- nodos anteriores a este arreglo o sembrados por
    # fuera del producto. Seguir declarandola siempre escondería el arreglo
    # detras de una queja permanente; no declararla nunca escondería los nodos
    # viejos, que siguen sin poder resolverse por alias.
    sin_alias = [f["entity_id"] for f in filas if not f.get("aliases")]
    if sin_alias:
        faltas.append({
            "code": "GRAFO_SIN_ALIAS",
            "detail": (
                "estas entidades no traen alias en el grafo, asi que solo se "
                "las podra alcanzar por su nombre canonico o por el glosario "
                "del perfil, nunca por `step_alias`: "
                + ", ".join(sorted(str(x) for x in sin_alias))
            ),
        })
    return faltas


__all__ = [
    "catalog_entities",
    "catalog_rows",
    "entity_ids",
    "snapshot_entities",
    "carencias",
]

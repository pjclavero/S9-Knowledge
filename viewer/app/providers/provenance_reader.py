# -*- coding: utf-8 -*-
"""Lectura CRUDA de la cadena de procedencia del writer. SIN autorizacion.

QUE ES ESTE MODULO Y QUE NO ES
------------------------------
Es el unico sitio del visor que emite Cypher contra las etiquetas que escribe
el writer para la procedencia de un APPLY --``V3AppliedOperation``,
``V3Source``, ``V3Episode``, ``V3Evidence``-- y contra el campo que ata esos
nodos a lo que se escribio (``idempotency_key``).

**NO decide autorizacion, y no puede.** Sus filas son material EN BRUTO. El
unico consumidor legitimo es ``app/services/result_provenance.py``, que cruza
cada fila con una decision de ``PolicyFilteredProvider`` antes de dejarla
llegar a una plantilla. Llamar a este modulo desde una ruta y pintar lo que
devuelve es una fuga, y por eso el nombre dice ``reader`` y no ``provider``:
no implementa ``GraphProvider`` y no se puede inyectar como tal.

POR QUE HACE FALTA UNA PUERTA NUEVA Y NO SE AMPLIA `GraphProvider`
------------------------------------------------------------------
``GraphProvider`` es una ABC: anadirle un metodo abstracto romperia a todos sus
implementadores (el proveedor mock y los espias de las suites de panel). Y
anadirlo al ``PolicyFilteredProvider`` sugeriria que ESE metodo esta filtrado
por politica, que es exactamente la confusion que causa una fuga. La puerta es
aparte, se llama distinto y se obtiene con ``reader_for``, que devuelve
``None`` cuando la fuente no es Neo4j --y ``None`` lo lee el servicio como NO
DISPONIBLE, nunca como "cero".

IDENTIDADES
-----------
Se entra por ``apply_id`` (``apply:<32hex>``, ``writer/apply_identity.py``) y
se navega por ``idempotency_key`` (clave sellada del plan, contrato congelado),
``entity_id``, ``assertion_id``, ``source_asset_id``, ``episode_id`` y
``fragment_id``. **Ni un ``elementId``**: no se selecciona, no se devuelve y no
se usa para emparejar. Emparejar por ``elementId`` ataria una URL publica a un
identificador fisico que cambia con un restore.

LO QUE NO SALE DE AQUI
----------------------
La proyeccion de cada etiqueta es una LISTA BLANCA explicita. Un campo que no
este en la lista no viaja, aunque el writer lo escriba manana. Es deliberado:
``V3Source`` guarda ``original_location`` --una ruta del servidor-- y
``V3Episode`` guarda ``text`` --el episodio ENTERO--. Ninguno de los dos puede
salir: la politica de procedencia concede el FRAGMENTO QUE SOSTIENE el hecho,
no la fuente entera (docs/v3/54 §6). Una lista negra habria dejado pasar el
proximo campo que alguien anada.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "ProvenanceReader",
    "reader_for",
    "CAMPOS_FUENTE",
    "CAMPOS_EPISODIO",
    "CAMPOS_FRAGMENTO",
    "CAMPOS_PROHIBIDOS",
]

#: Etiquetas y campos del writer. Se repiten aqui como literales A PROPOSITO:
#: ``viewer/`` y ``data-engine/app/`` son dos arboles de ``sys.path`` distintos
#: que no pueden importarse entre si (docstring del ``conftest.py`` de la
#: raiz). La suite comprueba que estos literales coinciden con los del writer.
LABEL_APPLIED_OPERATION = "V3AppliedOperation"
LABEL_SOURCE = "V3Source"
LABEL_EPISODE = "V3Episode"
LABEL_EVIDENCE = "V3Evidence"
LABEL_ASSERTION = "V3Assertion"
APPLY_ID_FIELD = "apply_id"
OWNERSHIP_ID_FIELD = "ownership_id"

#: LISTA BLANCA de la fuente: identidad durable + etiquetas humanas. Nada de
#: ``original_location`` (ruta del servidor), ``provider_trace`` (tripas del
#: motor) ni hashes (dato tecnico crudo).
CAMPOS_FUENTE: tuple[str, ...] = (
    "source_asset_id", "original_name", "source_kind", "mime_type",
    "language_hint", "ingested_at", "collection_id",
)

#: LISTA BLANCA del episodio: SOLO LOCALIZADORES. ``text`` NO esta, y su
#: ausencia es la politica: el episodio entero no es "el fragmento soportante".
CAMPOS_EPISODIO: tuple[str, ...] = (
    "episode_id", "source_asset_id", "page", "sequence", "modality",
)

#: LISTA BLANCA del fragmento: la evidencia LITERAL y DONDE estaba.
CAMPOS_FRAGMENTO: tuple[str, ...] = (
    "fragment_id", "episode_id", "source_asset_id", "literal_text",
    "page", "start", "end", "media_type", "time_start", "time_end",
)

#: Campos que NUNCA pueden viajar, escritos aqui para que la suite pueda
#: exigirlo por ENUMERACION en vez de por revision ocular.
CAMPOS_PROHIBIDOS: frozenset = frozenset({
    "original_location", "text", "normalized_text", "provider_trace",
    "source_hash", "content_hash", "source_hash_value", "content_hash_value",
    "claim_token", "byte_size", "processing_policy", "metadata",
})


def _proyectar(record: Any, campos: tuple[str, ...]) -> dict[str, Any]:
    """Un registro -> SOLO los campos de la lista blanca, y todos ellos.

    Un campo ausente en el grafo sale como ``None``, no se omite: la plantilla
    tiene que poder distinguir "el writer no lo escribio" de "no lo pedi".
    """
    return {campo: record.get(campo) for campo in campos}


class ProvenanceReader:
    """Consultas acotadas sobre la procedencia. UNA consulta por cada cosa.

    Dos ``MATCH`` sueltos en la misma consulta dan producto cartesiano y a
    menudo cero filas que parecen un verde: cada metodo de aqui hace UNA
    pregunta y devuelve UNA lista.

    Todas las consultas van acotadas por ``workspace``. No es el filtro de
    autorizacion --ese lo aplica el servicio, con el proveedor filtrado-- sino
    defensa en profundidad: una busqueda global por identificador es una
    frontera incorrecta aunque despues se filtre.
    """

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    # --- 1. El apply y sus operaciones -----------------------------------
    def operations_of_apply(self, workspace: str, apply_id: str) -> list[dict[str, Any]]:
        """Las marcas de operacion de ESE apply. Una fila por operacion.

        ``apply_id`` se compara por IGUALDAD exacta contra el campo del writer:
        nada de prefijos ni de ``CONTAINS``, que mezclarian dos applies.
        """
        q = (
            f"MATCH (op:{LABEL_APPLIED_OPERATION}) "
            f"WHERE op.workspace = $ws AND op.{APPLY_ID_FIELD} = $apply_id "
            "RETURN op.idempotency_key AS idempotency_key, "
            "op.operation_id AS operation_id, op.applied_at AS applied_at, "
            f"op.{OWNERSHIP_ID_FIELD} AS ownership_id, "
            "op.partida_id AS partida_id "
            "ORDER BY op.idempotency_key"
        )
        with self._driver.session() as s:
            return [dict(r) for r in s.run(q, {"ws": workspace, "apply_id": apply_id})]

    # --- 2. Lo que esas operaciones escribieron --------------------------
    def entity_ids_for_keys(self, workspace: str, keys: list[str]) -> list[str]:
        """``entity_id`` de las entidades escritas por esas claves. SIN filtrar.

        Devuelve identidad durable y NADA MAS: quien la reciba tiene que
        preguntarle al proveedor AUTORIZADO por cada una. Esa asimetria es el
        motivo de que este metodo no devuelva el nodo.
        """
        if not keys:
            return []
        q = (
            "MATCH (n:Entity) WHERE n.workspace = $ws "
            "AND n.idempotency_key IN $keys AND n.entity_id IS NOT NULL "
            "RETURN DISTINCT n.entity_id AS entity_id ORDER BY entity_id"
        )
        with self._driver.session() as s:
            return [r["entity_id"] for r in s.run(q, {"ws": workspace, "keys": keys})]

    def relation_edges_for_keys(self, workspace: str, keys: list[str]) -> list[dict[str, Any]]:
        """Aristas escritas por esas claves, por IDENTIDAD DE DOMINIO.

        Se devuelven ``(from, to, type)`` --los tres durables-- y la clave de
        idempotencia que las atribuye al apply. El ``elementId`` de la arista
        NO se selecciona: las relaciones V3 no tienen identidad durable propia
        (``_rel_to_dict`` lo documenta), asi que la atribucion se hace por esa
        terna contra las aristas que el proveedor autorizado ya devolvio.
        """
        if not keys:
            return []
        q = (
            "MATCH (a:Entity)-[r]->(b:Entity) WHERE r.workspace = $ws "
            "AND r.idempotency_key IN $keys "
            "AND a.entity_id IS NOT NULL AND b.entity_id IS NOT NULL "
            "RETURN DISTINCT a.entity_id AS from_id, b.entity_id AS to_id, "
            "type(r) AS type, r.idempotency_key AS idempotency_key "
            "ORDER BY from_id, type, to_id"
        )
        with self._driver.session() as s:
            return [dict(r) for r in s.run(q, {"ws": workspace, "keys": keys})]

    # --- 3. La procedencia de lo escrito ---------------------------------
    def assertions_for_keys(self, workspace: str, keys: list[str]) -> list[dict[str, Any]]:
        """Aserciones escritas por esas claves, con sus extremos DURABLES.

        Los extremos viajan porque son la llave de la autorizacion: el servicio
        no entrega la evidencia de una asercion cuyos extremos no pueda ver.
        """
        if not keys:
            return []
        q = (
            f"MATCH (a:{LABEL_ASSERTION}) WHERE a.workspace = $ws "
            "AND a.idempotency_key IN $keys "
            "RETURN DISTINCT a.assertion_id AS assertion_id, "
            "a.subject_entity_id AS subject_entity_id, "
            "a.object_entity_id AS object_entity_id, "
            "a.predicate AS predicate, a.idempotency_key AS idempotency_key "
            "ORDER BY assertion_id"
        )
        with self._driver.session() as s:
            return [dict(r) for r in s.run(q, {"ws": workspace, "keys": keys})]

    def apply_persistio_procedencia(self, workspace: str, keys: list[str]) -> bool:
        """¿Dejó ESTE apply alguna cadena de procedencia, aunque sea una?

        DISCRIMINADOR, y hace falta uno. ``apply_v3`` persiste la procedencia
        **solo si recibe un `ProvenanceBundle`**; sin el escribe el
        conocimiento, anota ``APPLY_PROVENANCE_NOT_PERSISTED`` y enumera los
        fragmentos colgantes. El resultado en el grafo es que las aserciones
        existen y NO tienen ni un ``SUPPORTED_BY``.

        Sin esta consulta, ese caso es INDISTINGUIBLE de "este hecho concreto
        no tiene evidencia", y las dos cosas se pintarian con la misma frase.
        Una es una carencia de la ejecucion --que el operador tiene que saber--
        y la otra un dato de ese hecho.

        Se pregunta por el APPLY entero, no por un hecho: basta con que UNA
        asercion suya tenga soporte para saber que la procedencia SI se
        persistio y que un hueco concreto es un hueco concreto.
        """
        if not keys:
            return False
        q = (
            f"MATCH (a:{LABEL_ASSERTION})-[:SUPPORTED_BY]->(:{LABEL_EVIDENCE}) "
            "WHERE a.workspace = $ws AND a.idempotency_key IN $keys "
            "RETURN count(*) AS soportes"
        )
        with self._driver.session() as s:
            fila = s.run(q, {"ws": workspace, "keys": keys}).single()
        return bool(fila and fila["soportes"] > 0)

    def fragments_supporting(self, workspace: str, assertion_id: str) -> list[dict[str, Any]]:
        """SOLO los fragmentos que SOSTIENEN esa asercion.

        El recorrido es ``(:V3Assertion)-[:SUPPORTED_BY]->(:V3Evidence)`` y
        para ahi. NO se sube al episodio para bajar a sus hermanos: eso
        entregaria la fuente entera a quien solo puede ver un hecho, que es
        precisamente lo que la politica de procedencia prohibe.
        """
        campos = ", ".join(f"ev.{c} AS {c}" for c in CAMPOS_FRAGMENTO)
        q = (
            f"MATCH (a:{LABEL_ASSERTION})-[:SUPPORTED_BY]->(ev:{LABEL_EVIDENCE}) "
            "WHERE a.workspace = $ws AND a.assertion_id = $aid "
            "AND ev.workspace = $ws "
            f"RETURN DISTINCT {campos} ORDER BY fragment_id"
        )
        with self._driver.session() as s:
            return [_proyectar(r, CAMPOS_FRAGMENTO)
                    for r in s.run(q, {"ws": workspace, "aid": assertion_id})]

    def episode(self, workspace: str, episode_id: str) -> Optional[dict[str, Any]]:
        """Localizador del episodio, o ``None``. SIN el texto del episodio."""
        campos = ", ".join(f"ep.{c} AS {c}" for c in CAMPOS_EPISODIO)
        q = (
            f"MATCH (ep:{LABEL_EPISODE}) WHERE ep.workspace = $ws "
            f"AND ep.episode_id = $eid RETURN {campos} LIMIT 2"
        )
        with self._driver.session() as s:
            filas = list(s.run(q, {"ws": workspace, "eid": episode_id}))
        if len(filas) != 1:
            # Cero = no esta. Dos = identidad ambigua, y una identidad ambigua
            # no identifica: se niega, no se elige la primera.
            return None
        return _proyectar(filas[0], CAMPOS_EPISODIO)

    def source(self, workspace: str, source_asset_id: str) -> Optional[dict[str, Any]]:
        """Ficha de la fuente por lista blanca, o ``None``. Misma regla de
        ambiguedad que ``episode``."""
        campos = ", ".join(f"src.{c} AS {c}" for c in CAMPOS_FUENTE)
        q = (
            f"MATCH (src:{LABEL_SOURCE}) WHERE src.workspace = $ws "
            f"AND src.source_asset_id = $sid RETURN {campos} LIMIT 2"
        )
        with self._driver.session() as s:
            filas = list(s.run(q, {"ws": workspace, "sid": source_asset_id}))
        if len(filas) != 1:
            return None
        return _proyectar(filas[0], CAMPOS_FUENTE)


def reader_for(provider: Any) -> Optional[ProvenanceReader]:
    """El lector de procedencia de la fuente que hay detras, o ``None``.

    ``None`` significa NO DISPONIBLE --este despliegue no lee procedencia-- y
    el servicio lo distingue de "no hay procedencia". Nunca se degrada a cero.

    Desenvuelve ``PolicyFilteredProvider`` para llegar al driver. Eso NO es
    saltarse la politica: el proveedor filtrado no filtra procedencia (no la
    conoce), y la autorizacion de todo lo que este lector devuelve la sigue
    decidiendo ese mismo proveedor filtrado, en el servicio. Se desenvuelve UNA
    capa y se exige que lo de debajo tenga driver.
    """
    base = getattr(provider, "_base", provider)
    driver = getattr(base, "_driver", None)
    if driver is None:
        return None
    return ProvenanceReader(driver)

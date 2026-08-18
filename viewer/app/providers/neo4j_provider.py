"""Proveedor de grafo sobre Neo4j real. Solo lectura: ninguna consulta escribe.

Preparado para cuando el visor se conecte a la instancia de VM105
(bolt://192.168.1.205:7687). No se ha probado contra un Neo4j real todavía;
se activa poniendo ``S9K_GRAPH_PROVIDER=neo4j`` en ``.env``.
"""
from __future__ import annotations

import logging
from typing import Any

from neo4j import GraphDatabase

from app.providers.base import GraphProvider


#: Filtro Cypher que exige IDENTIDAD DURABLE. Un nodo sin `entity_id` no es
#: direccionable: cualquier enlace hacia el tendria que apoyarse en el
#: `elementId`, que es justo lo que este carril viene a erradicar. Se aplica en
#: el propio Cypher --y no filtrando en Python-- para que el `count(n)` de la
#: paginacion y la lista de items cuenten LO MISMO. Si se filtrara despues, el
#: total diria 50 y llegarian 47, y esa diferencia se leeria como "faltan
#: permisos" en vez de "no tienen identidad".
_CON_IDENTIDAD_DURABLE = "n.entity_id IS NOT NULL"

_log = logging.getLogger(__name__)

#: SONDA DE AMBIGUEDAD, no desempate. `LIMIT 2` no sirve para «coger el
#: primero»: sirve para que la consulta pueda RESPONDER «hay mas de uno» sin
#: traerse un grafo entero. Con 2 filas no se escoge ninguna.
#:
#: POR QUE ESTO ES UNA BARRERA DE AUTORIDAD Y NO HIGIENE DE DATOS
#: -------------------------------------------------------------
#: `/entities/{entity_id}` es una URL DURABLE: un marcador, un enlace entre
#: paneles, una referencia guardada. Si dos nodos comparten `entity_id` dentro
#: del ambito autorizado del lector, «el primero que devuelva Neo4j» decide a
#: que objeto apunta esa URL. Eso no es un empate estetico: se midio como
#: SECUESTRO DE URL --12/12 peticiones devolvieron el duplicado y la entidad
#: legitima se convirtio en un 404 indistinguible de «no existe»--. Un objeto
#: que llega por una URL que no le pertenece ha esquivado la identidad, y con
#: ella todo lo que se decide a partir de la identidad.
#:
#: Por eso la regla es dura: para cada URL durable, 0 o 1 objetos, NUNCA 2+.
#: Con 2+ no se escoge ninguno (FAIL-CLOSED) y se registra el suceso: preferir
#: uno seria elegir victima.
_LIMITE_SONDA_AMBIGUEDAD = 2


def _node_to_dict(record_node) -> dict[str, Any]:
    props = dict(record_node)
    return {
        # IDENTIDAD DURABLE DE PRODUCTO. Es `entity_id`, la propiedad que
        # escribe el writer V3 (`create_entity`, derivada de
        # `sha256(workspace \x1f superficie \x1f tipo)`), y NO el `elementId`
        # de Neo4j.
        #
        # Antes aqui iba `record_node.element_id`, y ese valor viajaba entero
        # hasta el `href` de las fichas. El `elementId` es el identificador
        # FISICO del store: `dump`/`restore` lo reasigna, asi que todo enlace
        # guardado dejaba de resolver despues de una restauracion. Y como la
        # politica exige que lo no autorizado sea indistinguible de lo
        # inexistente, ese enlace roto devolvia el mismo 404 que un recurso que
        # nunca existio: el fallo era SILENCIOSO por diseno.
        #
        # `id` y `entity_id` valen aqui lo mismo A PROPOSITO: son el mismo
        # identificador de dominio. La clave es que ninguno de los dos cae
        # nunca hacia `element_id` -- ni aqui ni en `serialize_node`, donde
        # cuatro pruebas congelan la ausencia de ese respaldo. Un nodo sin
        # `entity_id` sale con `id=None` y NO es direccionable; por eso las
        # consultas lo excluyen con `_CON_IDENTIDAD_DURABLE` en vez de
        # regalarle un `elementId` que volveria a romperse.
        #
        # El `elementId` sigue existiendo internamente durante la consulta
        # (`graph()` lo usa para deduplicar y unir aristas dentro de una misma
        # transaccion), pero NO se proyecta: si saliera en el diccionario,
        # `serialize_node` lo recogeria por su respaldo `node.get("element_id")`
        # y volveria a la URL por la puerta de atras.
        "id": props.get("entity_id"),
        "entity_id": props.get("entity_id"),
        "label": props.get("display_name") or props.get("canonical_name") or "",
        "type": props.get("entity_type", ""),
        "description": props.get("description", ""),
        "aliases": props.get("aliases", []),
        # --- Campos de AUTORIZACIÓN. No son decorado: el motor de política
        # decide con ellos. Si esta proyección los pierde, la barrera
        # correspondiente deja de evaluarse sobre datos reales aunque sus
        # pruebas unitarias sigan verdes. Ya pasó: `partida_id` y `known_by`
        # faltaban aquí, y el aislamiento entre partidas no llegó a ejecutarse
        # nunca fuera de los fixtures. Hay una prueba que congela esta lista.
        "workspace": props.get("workspace"),
        "scope": props.get("scope"),
        "partida_id": props.get("partida_id"),
        "known_by": props.get("known_by"),
        # `ingest_rpg` escribe este; el motor lo lee como respaldo en
        # `known_by_of`. Si no viaja, la barrera se apaga en silencio.
        "known_by_characters": props.get("known_by_characters"),
        "party": props.get("party"),
        "is_public": props.get("is_public"),
        # Sesion de REVELACION (T2): desde que sesion puede revelarse esto.
        # No confundir con `session_index` (a que episodio pertenece).
        "known_from_session": props.get("known_from_session"),
        "session_index": props.get("session_index"),
        "source_document": props.get("source_document", ""),
        "source_pages": props.get("source_pages", []),
        "source_kind": props.get("source_kind", ""),
        "confidence": props.get("confidence"),
        "visibility": props.get("visibility"),
        "knowledge_layer": props.get("knowledge_layer"),
        "review_status": props.get("review_status"),
        "manual_review_required": props.get("manual_review_required"),
        "created_at": props.get("created_at"),
        "updated_at": props.get("updated_at"),
        "extractor_version": props.get("extractor_version"),
        "prompt_version": props.get("prompt_version"),
        "source_hash": props.get("source_hash"),
    }


def _extremo_durable(nodo) -> str | None:
    """`entity_id` de un extremo de arista. JAMAS su `elementId`.

    Se consulta la propiedad, no el identificador fisico. Si el driver entrego
    el nodo sin hidratar (devolver solo `r` en el Cypher lo deja sin
    propiedades), esto vale `None` y la arista queda sin extremo -- que es la
    respuesta honesta. El respaldo tentador seria `nodo.element_id`, y ese es
    exactamente el respaldo que reintroduce el defecto: la arista parecerian
    resolver y el enlace moriria en la siguiente restauracion. Por eso las
    consultas de este modulo pasan los extremos EXPLICITOS desde Cypher en vez
    de fiarse de la hidratacion.
    """
    if nodo is None:
        return None
    try:
        return dict(nodo).get("entity_id")
    except Exception:
        return None


def _rel_to_dict(rel, from_entity_id=None, to_entity_id=None) -> dict[str, Any]:
    props = dict(rel)
    return {
        # Las relaciones del modelo V3 NO tienen identificador durable propio:
        # `writer/cypher.py::create_relation` no escribe `relation_id` ni
        # `assertion_id` en la arista y devuelve `elementId(r)`. El objeto de
        # conocimiento durable de un hecho es el nodo `:V3Assertion` con su
        # `assertion_id`, no la arista, que es su PROYECCION.
        #
        # Asi que este `id` es un identificador FISICO y de un solo viaje: vale
        # para que vis-network distinga aristas dentro de la respuesta que las
        # trae, y para nada mas. No se enlaza, no se marca, no se persiste.
        # Ningun `href` del visor usa el id de una arista (los enlaces salen de
        # `from`/`to`), y esos dos SI son durables.
        "id": rel.element_id,
        # Extremos por IDENTIDAD DE DOMINIO. `PolicyFilteredProvider` --zona que
        # este carril no toca-- resuelve el otro extremo con
        # `self._base.entity(edge.get("from"|"to"))` y cruza los nodos visibles
        # con `{n["id"]}`. O sea: `from`/`to` y el `id` de nodo tienen que vivir
        # en el MISMO espacio de nombres que resuelve `entity()`. Al pasar los
        # nodos a `entity_id`, las aristas tienen que acompanarlos o el visor se
        # queda sin una sola relacion.
        "from": from_entity_id if from_entity_id is not None else _extremo_durable(getattr(rel, "start_node", None)),
        "to": to_entity_id if to_entity_id is not None else _extremo_durable(getattr(rel, "end_node", None)),
        "type": rel.type,
        "label": props.get("relation_label_es", ""),
        # --- Campos de AUTORIZACIÓN de la relación (ver nota en _node_to_dict).
        # Sin `visibility` aquí, TODA relación caía en `visibility_invalid`: el
        # visor real se quedaba sin una sola arista y la herencia restrictiva de
        # M5b-3 no tenía ningún efecto observable.
        # Una arista se evalua con `can_view` EXACTAMENTE igual que un nodo, asi
        # que necesita los mismos campos. Cualquier asimetria entre las dos
        # listas apaga una regla solo para relaciones, en silencio.
        "visibility": props.get("visibility"),
        "workspace": props.get("workspace"),
        "scope": props.get("scope"),
        "partida_id": props.get("partida_id"),
        "known_by": props.get("known_by"),
        # `ingest_rpg` escribe este; el motor lo lee como respaldo en
        # `known_by_of`. Si no viaja, la barrera se apaga en silencio.
        "known_by_characters": props.get("known_by_characters"),
        "party": props.get("party"),
        "is_public": props.get("is_public"),
        # Sesion de REVELACION (T2): desde que sesion puede revelarse esto.
        # No confundir con `session_index` (a que episodio pertenece).
        "known_from_session": props.get("known_from_session"),
        "session_index": props.get("session_index"),
        "description": props.get("evidence") or props.get("description", ""),
        "source_document": props.get("source_document", ""),
        "source_pages": props.get("source_pages", []),
        "confidence": props.get("confidence"),
        "review_status": props.get("review_status"),
    }


class Neo4jGraphProvider(GraphProvider):
    name = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def is_connected(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def workspaces(self) -> list[str]:
        # QUINTA VIA DE LA MISMA FUGA (severidad BAJA, cerrada aqui a proposito).
        # ------------------------------------------------------------------
        # Este es el UNICO camino que `PolicyFilteredProvider` no recalcula: su
        # `workspaces()` se limita a intersectar con `allowed_workspaces`, no
        # deriva el listado de `list_entities`. Sin exigir identidad durable EN
        # LA CONSULTA, un workspace cuyos nodos no tengan `entity_id` aparece en
        # el selector y luego se abre VACIO (0 de 0): la misma fuga por
        # diferencia que cierran MR4-MR7, un nivel mas arriba. No cruza
        # inquilinos -- solo se listan workspaces ya permitidos --, pero si el
        # bloqueo de despliegue se confirma, asi se presentaria en produccion:
        # todos los workspaces en el selector, todos vacios.
        #
        # Se cierra en el Cypher, no filtrando despues, por la misma razon que
        # las otras cuatro: un filtro posterior es codigo que alguien puede
        # borrar sin que ninguna consulta cambie.
        query = """
        MATCH (n:Entity)
        WHERE n.workspace IS NOT NULL AND n.entity_id IS NOT NULL
        RETURN DISTINCT n.workspace AS workspace
        ORDER BY workspace
        """
        with self._driver.session() as session:
            return [r["workspace"] for r in session.run(query)]

    def counts(self, workspace: str | None = None) -> tuple[int, int]:
        if workspace:
            node_q = "MATCH (n:Entity {workspace:$workspace}) RETURN count(n) AS c"
            rel_q = (
                "MATCH (:Entity {workspace:$workspace})-[r]->(:Entity {workspace:$workspace}) "
                "RETURN count(r) AS c"
            )
            params = {"workspace": workspace}
        else:
            node_q = "MATCH (n:Entity) RETURN count(n) AS c"
            rel_q = "MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS c"
            params = {}
        with self._driver.session() as session:
            nodes = session.run(node_q, params).single()["c"]
            rels = session.run(rel_q, params).single()["c"]
        return nodes, rels

    def entity_types(self, workspace: str) -> list[dict[str, Any]]:
        query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE n.entity_type IS NOT NULL
        RETURN n.entity_type AS entity_type, count(n) AS count
        ORDER BY count DESC
        """
        with self._driver.session() as session:
            return [
                {"entity_type": r["entity_type"], "count": r["count"]}
                for r in session.run(query, {"workspace": workspace})
            ]

    def search(self, workspace: str, q: str, limit: int = 50) -> list[dict[str, Any]]:
        query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE (toLower(coalesce(n.canonical_name,'')) CONTAINS toLower($q)
           OR toLower(coalesce(n.display_name,'')) CONTAINS toLower($q)
           OR toLower(coalesce(n.description,'')) CONTAINS toLower($q))
          AND n.entity_id IS NOT NULL
        RETURN n
        LIMIT $limit
        """
        with self._driver.session() as session:
            return [
                _node_to_dict(r["n"])
                for r in session.run(query, {"workspace": workspace, "q": q, "limit": limit})
            ]

    def graph(
        self,
        workspace: str,
        limit: int = 300,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # `n.entity_id IS NOT NULL` en los dos extremos: una arista cuyo extremo
        # no tenga identidad durable no se puede enlazar, y dejarla pasar solo
        # produciria una arista colgante que el filtro de politica descartaria
        # despues por el motivo equivocado ("no visible" en vez de "no
        # direccionable").
        rel_query = """
        MATCH (n:Entity {workspace:$workspace})-[r]->(m:Entity {workspace:$workspace})
        WHERE ($entity_type IS NULL OR n.entity_type = $entity_type OR m.entity_type = $entity_type)
          AND n.entity_id IS NOT NULL AND m.entity_id IS NOT NULL
        RETURN n, r, m
        LIMIT $limit
        """
        node_query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE ($entity_type IS NULL OR n.entity_type = $entity_type)
          AND n.entity_id IS NOT NULL
        RETURN n
        LIMIT $limit
        """
        params = {"workspace": workspace, "entity_type": entity_type, "limit": limit}

        # OJO: la clave de este diccionario es el `elementId`, no el `id` que se
        # publica. Es uso INTERNO dentro de una consulta --deduplicar nodos que
        # llegan por varias aristas-- y ahi el `elementId` es legitimo y ademas
        # preferible: es unico por definicion. Lo que sale hacia fuera son los
        # VALORES del diccionario, cuyo `id` ya es el `entity_id`.
        nodes_by_id: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        with self._driver.session() as session:
            for record in session.run(rel_query, params):
                n_dict = _node_to_dict(record["n"])
                m_dict = _node_to_dict(record["m"])
                nodes_by_id[record["n"].element_id] = n_dict
                nodes_by_id[record["m"].element_id] = m_dict
                edges.append(
                    _rel_to_dict(record["r"], n_dict["entity_id"], m_dict["entity_id"])
                )

            if len(nodes_by_id) < limit:
                for record in session.run(node_query, params):
                    n_dict = _node_to_dict(record["n"])
                    nodes_by_id.setdefault(record["n"].element_id, n_dict)
                    if len(nodes_by_id) >= limit:
                        break

        nodes = list(nodes_by_id.values())[:limit]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in edges if e["from"] in node_ids and e["to"] in node_ids]
        return nodes, edges

    def entity(
        self, entity_id: str, *, workspaces: frozenset[str] | None = None
    ) -> dict[str, Any] | None:
        # Se resuelve por IDENTIDAD DURABLE (`n.entity_id`), no por
        # `elementId(n)`. Este es el metodo al que llega el segmento de la URL,
        # asi que es el punto exacto donde un enlace guardado sobrevive --o no--
        # a un `dump`/`restore`. Con `elementId` no sobrevivia.
        #
        # Un `entity_id` inexistente devuelve None, igual que uno existente que
        # la politica no deja ver (`PolicyFilteredProvider.entity` tambien
        # devuelve None). Las dos ramas acaban en el MISMO 404, que es lo que
        # exige la politica: lo no autorizado indistinguible de lo inexistente.
        # UNICIDAD DURABLE (barrera 2, la del resolver). La restriccion de
        # esquema impide CREAR el estado invalido de hoy en adelante; no dice
        # nada de los datos historicos, de una restauracion defectuosa, de una
        # importacion anterior ni de un retro-relleno de `entity_id` con una
        # derivacion imperfecta. Cualquiera de esos caminos deja dos nodos con
        # la misma identidad durable, y es AQUI --el punto exacto al que llega
        # el segmento de la URL-- donde eso deja de ser un dato sucio y pasa a
        # ser un secuestro silencioso. Por eso esta barrera no es redundante:
        # es la unica que cubre el pasado.
        params: dict[str, Any] = {"id": entity_id, "sonda": _LIMITE_SONDA_AMBIGUEDAD}
        query = "MATCH (n:Entity) WHERE n.entity_id = $id RETURN n LIMIT $sonda"
        if workspaces is not None:
            # Acotado en el propio Cypher, no solo en el filtro posterior.
            query = (
                "MATCH (n:Entity) WHERE n.entity_id = $id "
                "AND n.workspace IN $workspaces RETURN n LIMIT $sonda"
            )
            params["workspaces"] = sorted(workspaces)
        with self._driver.session() as session:
            # `list(...)`, no `.single()`. `.single()` de este driver devuelve
            # LA PRIMERA fila y se limita a avisar por `warnings` cuando hay
            # mas: ese aviso no cambia el resultado, no llega al operador y es
            # exactamente el desempate implicito que este carril prohibe.
            records = list(session.run(query, params))
        if len(records) > 1:
            # FAIL-CLOSED. No se escoge ninguno y se GRITA: un duplicado en la
            # base es un incidente de identidad, no una anecdota. Se registra
            # el `entity_id` --que es lo que ya viaja en la URL-- y nada del
            # contenido de los nodos, que puede ser material no autorizado.
            _log.error(
                "IDENTIDAD DURABLE AMBIGUA: %d nodos comparten entity_id=%r "
                "en el ambito consultado; no se resuelve ninguno (fail-closed)",
                len(records), entity_id,
            )
            return None
        return _node_to_dict(records[0]["n"]) if records else None

    def _identidad_ambigua(
        self, entity_id: str, workspaces: frozenset[str] | None = None
    ) -> bool:
        """¿Hay 2+ nodos con este `entity_id`? Sonda acotada, sin desempate.

        ACOTA POR WORKSPACE EXACTAMENTE IGUAL QUE `entity()`, y esto no es un
        detalle: `entity_id` NO siempre lleva el workspace dentro. La
        derivacion de `resolution/provisional.py` si lo mete en el digest, pero
        los contratos admiten identificadores AUTORADOS --los hay en este mismo
        repositorio, p.ej. `entity:ambar:corte-resina`-- que no pasan por ella.
        Dos juegos distintos pueden compartir uno.

        Con la sonda sin acotar, ese caso daba una incoherencia entre las dos
        barreras: `entity()` resolvia la ficha (su consulta si filtra por
        workspace) y esta declaraba el ancla ambigua, asi que la ficha salia
        con TODAS sus relaciones caidas. No era una fuga --fallaba hacia
        cerrado y dejaba `log.error`-- pero si un defecto de disponibilidad
        provocado por la propia defensa. Misma pregunta, mismo ambito.
        """
        params: dict[str, Any] = {"id": entity_id, "sonda": _LIMITE_SONDA_AMBIGUEDAD}
        filtro = ""
        if workspaces is not None:
            filtro = "AND n.workspace IN $workspaces "
            params["workspaces"] = sorted(workspaces)
        with self._driver.session() as session:
            # `RETURN 1`, no `RETURN n`: la pregunta es CUANTAS anclas hay, y
            # traerse las propiedades de nodos que quiza no esten autorizados
            # para acabar tirandolos seria material sensible paseado sin
            # motivo. Ademas hace el texto de esta consulta distinto del de
            # `entity()`, y por tanto anclable a solas por el arnes de
            # mutaciones (dos consultas identicas se mutan la primera, y el
            # rojo de una seria el rojo PRESTADO de la otra).
            records = list(session.run(
                "MATCH (n:Entity) WHERE n.entity_id = $id "
                f"{filtro}RETURN 1 AS ancla LIMIT $sonda",
                params,
            ))
        if len(records) > 1:
            _log.error(
                "IDENTIDAD DURABLE AMBIGUA en relaciones: %d nodos comparten "
                "entity_id=%r; no se sirve ninguna relacion (fail-closed)",
                len(records), entity_id,
            )
            return True
        return False

    def relations_for_entity(
        self, entity_id: str, *, workspaces: frozenset[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # Anclada por `entity_id`, como `entity()`.
        #
        # Los extremos viajan EXPLICITOS (`n.entity_id`, `m.entity_id`) en vez
        # de leerse de `r.start_node`: devolviendo solo `r`, el driver entrega
        # los nodos extremo SIN propiedades, asi que `_extremo_durable` daria
        # `None` y `PolicyFilteredProvider` descartaria todas las relaciones al
        # no poder resolver el otro extremo. Un fallo asi seria mudo: la ficha
        # simplemente apareceria sin relaciones.
        #
        # UNICIDAD DURABLE, misma barrera que en `entity()` y por el mismo
        # motivo: con dos anclas del mismo `entity_id`, este metodo devolveria
        # la UNION de las relaciones de ambas, es decir, las relaciones de un
        # objeto pintadas en la ficha de otro. Fail-closed: sin ancla unica no
        # hay relaciones que mostrar.
        if self._identidad_ambigua(entity_id, workspaces):
            return [], []
        out_query = """
        MATCH (n:Entity)-[r]->(m:Entity)
        WHERE n.entity_id = $id AND m.entity_id IS NOT NULL
        RETURN r, n.entity_id AS desde, m.entity_id AS hacia
        """
        in_query = """
        MATCH (n:Entity)<-[r]-(m:Entity)
        WHERE n.entity_id = $id AND m.entity_id IS NOT NULL
        RETURN r, m.entity_id AS desde, n.entity_id AS hacia
        """
        with self._driver.session() as session:
            outgoing = [
                _rel_to_dict(rec["r"], rec["desde"], rec["hacia"])
                for rec in session.run(out_query, {"id": entity_id})
            ]
            incoming = [
                _rel_to_dict(rec["r"], rec["desde"], rec["hacia"])
                for rec in session.run(in_query, {"id": entity_id})
            ]
        return outgoing, incoming

    # -----------------------------------------------------------------------
    # Métodos de paginación real y calidad (Tarea C — solo lectura)
    # -----------------------------------------------------------------------

    _SORT_ALLOWLIST: dict[str, str] = {
        "canonical_name": "n.canonical_name",
        "entity_type": "n.entity_type",
        "confidence": "n.confidence",
        "review_status": "n.review_status",
        "created_at": "n.created_at",
    }

    def list_entities(
        self,
        workspace: str,
        *,
        q: str = "",
        entity_type: str | None = None,
        source_kind: str | None = None,
        review_status: str | None = None,
        visibility: str | None = None,
        quality_status: str | None = None,
        min_confidence: float | None = None,
        sort: str = "canonical_name",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginación real con SKIP/LIMIT en Neo4j. 0 escrituras."""
        sort_field = self._SORT_ALLOWLIST.get(sort, "n.canonical_name")
        order_dir = "DESC" if order == "desc" else "ASC"

        # `_CON_IDENTIDAD_DURABLE` entra en el WHERE, no en un filtro posterior:
        # asi `count(n)` y la pagina de items cuentan exactamente lo mismo.
        where_parts = ["n.workspace = $workspace", _CON_IDENTIDAD_DURABLE]
        params: dict[str, Any] = {"workspace": workspace, "limit": limit, "offset": offset}

        if q:
            where_parts.append(
                "(toLower(coalesce(n.canonical_name,'')) CONTAINS toLower($q)"
                " OR toLower(coalesce(n.display_name,'')) CONTAINS toLower($q)"
                " OR toLower(coalesce(n.description,'')) CONTAINS toLower($q))"
            )
            params["q"] = q
        if entity_type:
            where_parts.append("n.entity_type = $entity_type")
            params["entity_type"] = entity_type
        if source_kind:
            where_parts.append("n.source_kind = $source_kind")
            params["source_kind"] = source_kind
        if review_status:
            where_parts.append("n.review_status = $review_status")
            params["review_status"] = review_status
        if visibility:
            where_parts.append("n.visibility = $visibility")
            params["visibility"] = visibility
        if min_confidence is not None:
            where_parts.append("n.confidence >= $min_confidence")
            params["min_confidence"] = min_confidence

        where_clause = " AND ".join(where_parts)

        count_query = f"MATCH (n:Entity) WHERE {where_clause} RETURN count(n) AS total"
        items_query = (
            f"MATCH (n:Entity) WHERE {where_clause} "
            f"RETURN n ORDER BY {sort_field} {order_dir} "
            f"SKIP $offset LIMIT $limit"
        )

        with self._driver.session() as session:
            total = session.run(count_query, params).single()["total"]
            items = [
                _node_to_dict(rec["n"])
                for rec in session.run(items_query, params)
            ]
        return items, total

    def list_sources(self, workspace: str) -> list[dict[str, Any]]:
        """Fuentes distintas en el workspace (por source_document). Solo lectura."""
        query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE n.source_document IS NOT NULL AND n.source_document <> ''
        RETURN n.source_document AS source_id,
               n.source_kind AS source_kind,
               count(n) AS entity_count
        ORDER BY source_id
        """
        with self._driver.session() as session:
            return [
                {
                    "source_id": r["source_id"],
                    "source_kind": r["source_kind"],
                    "entity_count": r["entity_count"],
                }
                for r in session.run(query, {"workspace": workspace})
            ]

    def source_detail(self, workspace: str, source_id: str) -> dict[str, Any] | None:
        """Detalle de una fuente: counts por tipo, review_status. Solo lectura."""
        check_query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE n.source_document = $source_id
        RETURN count(n) AS total
        """
        with self._driver.session() as session:
            total = session.run(check_query, {"workspace": workspace, "source_id": source_id}).single()["total"]
            if total == 0:
                return None
            by_type_query = """
            MATCH (n:Entity {workspace:$workspace})
            WHERE n.source_document = $source_id AND n.entity_type IS NOT NULL
            RETURN n.entity_type AS entity_type, count(n) AS count
            ORDER BY count DESC
            """
            by_review_query = """
            MATCH (n:Entity {workspace:$workspace})
            WHERE n.source_document = $source_id AND n.review_status IS NOT NULL
            RETURN n.review_status AS review_status, count(n) AS count
            ORDER BY count DESC
            """
            by_type = [
                {"entity_type": r["entity_type"], "count": r["count"]}
                for r in session.run(by_type_query, {"workspace": workspace, "source_id": source_id})
            ]
            by_review = [
                {"review_status": r["review_status"], "count": r["count"]}
                for r in session.run(by_review_query, {"workspace": workspace, "source_id": source_id})
            ]
        return {
            "source_id": source_id,
            "workspace": workspace,
            "entity_count": total,
            "by_entity_type": by_type,
            "by_review_status": by_review,
        }

    def quality_metrics(self, workspace: str | None = None) -> dict[str, Any]:
        """Métricas de calidad de solo lectura. MATCH-only, 0 escrituras."""
        if workspace:
            base_filter = "n.workspace = $workspace"
            rel_filter = (
                "n.workspace = $workspace AND m.workspace = $workspace"
            )
            params: dict[str, Any] = {"workspace": workspace}
        else:
            base_filter = "true"
            rel_filter = "true"
            params = {}

        with self._driver.session() as session:
            # Totales
            total_entities = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} RETURN count(n) AS c", params
            ).single()["c"]
            total_relations = session.run(
                f"MATCH (n:Entity)-[r]->(m:Entity) WHERE {rel_filter} RETURN count(r) AS c", params
            ).single()["c"]

            # Por tipo
            by_type_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.entity_type IS NOT NULL "
                f"RETURN n.entity_type AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_type = {r["k"]: r["c"] for r in by_type_rows}

            # Por workspace
            by_ws_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.workspace IS NOT NULL "
                f"RETURN n.workspace AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_ws = {r["k"]: r["c"] for r in by_ws_rows}

            # Por review_status
            by_review_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.review_status IS NOT NULL "
                f"RETURN n.review_status AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_review = {r["k"]: r["c"] for r in by_review_rows}

            # Por visibility
            by_vis_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.visibility IS NOT NULL "
                f"RETURN n.visibility AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_vis = {r["k"]: r["c"] for r in by_vis_rows}

            # Distribución de confianza
            conf_high = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence >= 0.8 RETURN count(n) AS c", params
            ).single()["c"]
            conf_mid = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence >= 0.5 AND n.confidence < 0.8 RETURN count(n) AS c", params
            ).single()["c"]
            conf_low = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence < 0.5 RETURN count(n) AS c", params
            ).single()["c"]
            conf_none = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence IS NULL RETURN count(n) AS c", params
            ).single()["c"]

            # Gaps de datos
            no_source = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND "
                f"(n.source_document IS NULL OR n.source_document = '') RETURN count(n) AS c", params
            ).single()["c"]
            no_desc = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND "
                f"(n.description IS NULL OR n.description = '') RETURN count(n) AS c", params
            ).single()["c"]
            no_type = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND "
                f"(n.entity_type IS NULL OR n.entity_type = '') RETURN count(n) AS c", params
            ).single()["c"]

        return {
            "workspace": workspace,
            "total_entities": total_entities,
            "total_relations": total_relations,
            "by_entity_type": by_type,
            "by_workspace": by_ws,
            "by_review_status": by_review,
            "by_visibility": by_vis,
            "confidence_distribution": {
                "high_gte_0_8": conf_high,
                "mid_gte_0_5": conf_mid,
                "low_lt_0_5": conf_low,
                "no_value": conf_none,
            },
            "data_gaps": {
                "no_source_document": no_source,
                "no_description": no_desc,
                "no_entity_type": no_type,
            },
        }

"""M5b-3 -- migracion fail-closed de la visibilidad ya existente.

El cierre del motor (M5b-2) deniega todo nodo o relacion sin una visibilidad
valida. Eso es correcto, pero no puede aplicarse sobre datos que nunca la
llevaron: dejaria el grafo mudo. Este modulo estampa lo que falta ANTES de que
el cierre entre en vigor.

Dos criterios, y ninguno de los dos adivina:

* **Un nodo sin visibilidad pasa a `secret`.** No hay nada en el nodo de donde
  deducir su nivel, asi que se aplica el mas restrictivo que sigue siendo
  utilizable. Promover despues, al revisarlo, es barato; lo contrario no tiene
  vuelta atras.
* **Una relacion hereda la visibilidad MAS RESTRICTIVA de sus extremos.** Esto
  si es deducible, y ademas es la unica opcion coherente: una arista entre dos
  nodos visibles puede verse, pero una arista que toca un secreto revela que
  ese secreto existe y con quien se relaciona. Si un extremo falta o no se
  puede resolver, `secret`.

La migracion nunca AMPLIA: si algo ya tiene visibilidad, se respeta tal cual,
aunque sea mas permisiva de lo que estas reglas darian. Corregir a la baja es
una decision del operador, no un efecto colateral de migrar.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.policies.models import ALL_STORED_LEVELS, DENY, NARRATOR, PLAYER, REFERENCE, SECRET

#: Orden de restriccion, de menos a mas. No es el orden del enum: es el orden
#: en que estos niveles ocultan. `reference` va por encima de `player` porque
#: exige un permiso propio (`can_view_reference`).
RESTRICTIVENESS: dict[str, int] = {
    PLAYER: 0,
    REFERENCE: 1,
    NARRATOR: 2,
    SECRET: 3,
    DENY: 4,
}

#: Nivel aplicado cuando no hay nada de donde deducir.
FALLBACK = SECRET


def normalize_level(value: Any) -> str | None:
    """Devuelve el nivel canonico, o None si el valor no es utilizable."""
    if not isinstance(value, str):
        return None
    level = value.strip().lower()
    return level if level in ALL_STORED_LEVELS else None


def most_restrictive(levels: Iterable[Any]) -> str:
    """El mas restrictivo de los niveles dados. Vacio o invalido -> FALLBACK.

    Un nivel ilegible cuenta como FALLBACK y no se ignora: ignorarlo dejaria
    que un dato corrupto en un extremo produjera una arista mas visible que el
    nodo que toca.
    """
    peor = -1
    visto = False
    for value in levels:
        visto = True
        level = normalize_level(value)
        rank = RESTRICTIVENESS[FALLBACK] if level is None else RESTRICTIVENESS[level]
        peor = max(peor, rank)
    if not visto:
        return FALLBACK
    for level, rank in RESTRICTIVENESS.items():
        if rank == peor:
            return level
    return FALLBACK  # pragma: no cover - inalcanzable, RESTRICTIVENESS es total


def stamp_node(node: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Estampa un nodo si le falta. Devuelve (nodo, si_se_cambio)."""
    if normalize_level(node.get("visibility")) is not None:
        return node, False
    return {**node, "visibility": FALLBACK}, True


def stamp_edge(
    edge: dict[str, Any], nodes_by_id: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """Estampa una relacion heredando el extremo mas restrictivo."""
    if normalize_level(edge.get("visibility")) is not None:
        return edge, False
    extremos = []
    for key in ("from", "to"):
        nodo = nodes_by_id.get(edge.get(key))
        # Un extremo que no existe no es "sin nivel": es una arista rota, y
        # FALLBACK es justo lo que most_restrictive() da para un valor ilegible.
        extremos.append(None if nodo is None else nodo.get("visibility"))
    return {**edge, "visibility": most_restrictive(extremos)}, True


def migrate_dataset(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Migra un conjunto {nodes, edges}. No muta la entrada.

    Devuelve el documento migrado y un recuento de lo tocado, para que quien
    ejecute la migracion pueda comprobar que hizo lo que esperaba en vez de
    fiarse de que termino sin error.
    """
    nodes: list[dict[str, Any]] = []
    tocados_nodos = 0
    for n in doc.get("nodes", []):
        nodo, cambiado = stamp_node(dict(n))
        nodes.append(nodo)
        tocados_nodos += cambiado

    by_id = {n["id"]: n for n in nodes if "id" in n}

    edges: list[dict[str, Any]] = []
    tocadas_aristas = 0
    for e in doc.get("edges", []):
        arista, cambiado = stamp_edge(dict(e), by_id)
        edges.append(arista)
        tocadas_aristas += cambiado

    salida = {**doc, "nodes": nodes, "edges": edges}
    recuento = {
        "nodos_totales": len(nodes),
        "nodos_estampados": tocados_nodos,
        "aristas_totales": len(edges),
        "aristas_estampadas": tocadas_aristas,
    }
    return salida, recuento


# --- Neo4j ------------------------------------------------------------------
#: Cuenta lo que falta por migrar. Se ejecuta ANTES y DESPUES: despues debe dar
#: cero, y si no lo da, la migracion no hizo lo que dijo.
CYPHER_PENDIENTES = """
MATCH (n)
WHERE n.visibility IS NULL OR NOT n.visibility IN $niveles
RETURN count(n) AS nodos
"""

CYPHER_PENDIENTES_RELS = """
MATCH ()-[r]->()
WHERE r.visibility IS NULL OR NOT r.visibility IN $niveles
RETURN count(r) AS relaciones
"""

#: Estampa nodos. Idempotente: solo toca los que no tienen nivel valido.
CYPHER_MIGRAR_NODOS = """
MATCH (n)
WHERE n.visibility IS NULL OR NOT n.visibility IN $niveles
SET n.visibility = $fallback,
    n.visibility_source = 'migration_fail_closed'
RETURN count(n) AS estampados
"""

#: Estampa relaciones heredando el extremo mas restrictivo. El orden de
#: `$orden` decide: se toma el rango mayor de los dos extremos.
CYPHER_MIGRAR_RELACIONES = """
MATCH (a)-[r]->(b)
WHERE r.visibility IS NULL OR NOT r.visibility IN $niveles
WITH r,
     coalesce($orden[a.visibility], $peor) AS ra,
     coalesce($orden[b.visibility], $peor) AS rb
WITH r, CASE WHEN ra > rb THEN ra ELSE rb END AS rango
SET r.visibility = $por_rango[toString(rango)],
    r.visibility_source = 'migration_inherited'
RETURN count(r) AS estampadas
"""


def cypher_params() -> dict[str, Any]:
    """Parametros de las consultas de migracion, derivados de una sola fuente."""
    return {
        "niveles": list(ALL_STORED_LEVELS),
        "fallback": FALLBACK,
        "orden": dict(RESTRICTIVENESS),
        "peor": RESTRICTIVENESS[FALLBACK],
        "por_rango": {str(rank): level for level, rank in RESTRICTIVENESS.items()},
    }

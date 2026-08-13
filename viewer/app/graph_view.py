"""Vista del grafo: recorte por `limit` y DECLARACIÓN de parcialidad.

Por qué existe este módulo
--------------------------
`/api/graph` devuelve el subgrafo inducido sobre los primeros `limit` nodos
(`docs/72`), así que la retención de relaciones cae con el cuadrado. Ese
defecto NO se corrige aquí: lo que se corrige es que el visor **presentaba una
vista parcial como si fuera el grafo entero** (el cliente usaba `total =
loaded`). Una limitación técnica sin declarar es una afirmación falsa de
producto.

Regla de autorización (la parte delicada)
-----------------------------------------
Las cifras que se publican se calculan SIEMPRE sobre el conjunto que ya ha
pasado por la política: la entrada de `vista_truncada` es la salida de
`PolicyFilteredProvider.graph(..., limit=SIN_TOPE)`, es decir nodos y
relaciones YA filtrados. Los totales son, por construcción, "cuántos elementos
autorizados hay", nunca "cuántos hay en la base". Un total calculado antes de
filtrar sería una fuga: revelaría por diferencia la existencia de lo que la
política acaba de ocultar. Por eso este módulo **no consulta al proveedor
base** y no sabe siquiera que existe.

Equivalencia con el proveedor
-----------------------------
`vista_truncada` reproduce el recorte que hace `PolicyFilteredProvider.graph`
(recortar nodos y quedarse con las relaciones entre supervivientes). No es
lógica de autorización duplicada —las relaciones que recibe ya son visibles y
aquí sólo se comprueba la pertenencia de los extremos—, pero una divergencia
futura sería silenciosa: por eso
`viewer/tests/test_parcialidad_declarada.py::test_la_vista_del_router_es_byte_a_byte_la_del_proveedor`
exige que ambas salidas coincidan, y ese test es un superviviente nombrado.
"""
from __future__ import annotations

from typing import Any

# Importada de producción, no copiada: si `_ALL` cambiara, una constante local
# haría divergir el "sin tope" EN SILENCIO.
from app.authz.filtered_provider import _ALL as SIN_TOPE

__all__ = ["SIN_TOPE", "vista_truncada"]


def vista_truncada(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Recorta a `limit` nodos y describe QUÉ se ha dejado fuera.

    `nodes`/`edges` deben venir YA filtrados por la política (ver arriba).
    Devuelve `(nodos_mostrados, relaciones_mostradas, vista)`.
    """
    mostrados = nodes[:limit]
    ids = {n["id"] for n in mostrados if n.get("id") is not None}
    relaciones = [e for e in edges if e.get("from") in ids and e.get("to") in ids]

    return mostrados, relaciones, {
        "limit": limit,
        # Truncada si falta CUALQUIER cosa: puede sobrar el tope de nodos y
        # faltar relaciones igualmente (es justo el desplome cuadrático).
        "truncated": len(mostrados) < len(nodes) or len(relaciones) < len(edges),
        "nodes_shown": len(mostrados),
        "nodes_total": len(nodes),
        "edges_shown": len(relaciones),
        "edges_total": len(edges),
    }

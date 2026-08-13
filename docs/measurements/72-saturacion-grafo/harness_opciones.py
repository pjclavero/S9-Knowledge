"""Mide las OPCIONES de arreglo sobre el mismo arbol y con el mismo medidor.

Todas las opciones operan SOBRE EL CONJUNTO YA FILTRADO POR POLITICA
(vnodes_full / vedges_full): ninguna puede ampliar lo que el usuario ve.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "viewer")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_gsat import build  # noqa: E402
from app.providers.mock_provider import MockGraphProvider  # noqa: E402
from app.policies.engine import VisibilityPolicy  # noqa: E402
from app.policies.models import ViewerContext  # noqa: E402
from app.serializers import serialize_graph  # noqa: E402

CTX = ViewerContext(role="reviewer", allowed_workspaces=frozenset({"leyenda"}),
                    can_view_reference=True)
POL = VisibilityPolicy()


def visibles(path):
    base = MockGraphProvider(path)
    nodes, edges = base.graph("leyenda", limit=10 ** 7)
    vnodes = POL.filter_nodes(nodes, CTX)
    vids = {n["id"] for n in vnodes}
    vedges = POL.filter_edges(edges, vids, CTX)
    return vnodes, vedges


def opcion_actual(vnodes, vedges, limit):
    sel = vnodes[:limit]
    ids = {n["id"] for n in sel}
    return sel, [e for e in vedges if e["from"] in ids and e["to"] in ids]


def opcion_subir_limite(vnodes, vedges, limit):
    return opcion_actual(vnodes, vedges, 2000)


def opcion_semilla_por_aristas(vnodes, vedges, limit):
    """Elige los nodos RECORRIENDO ARISTAS, no el orden de almacenamiento."""
    by_id = {n["id"]: n for n in vnodes}
    ids, sel = set(), []
    kept = []
    for e in vedges:
        a, b = e["from"], e["to"]
        nuevos = len({a, b} - ids)
        if len(ids) + nuevos > limit:
            continue
        for x in (a, b):
            if x not in ids and x in by_id:
                ids.add(x); sel.append(by_id[x])
        kept.append(e)
    for n in vnodes:                        # rellena con aislados si sobra sitio
        if len(sel) >= limit: break
        if n["id"] not in ids:
            ids.add(n["id"]); sel.append(n)
    ids = {n["id"] for n in sel}
    return sel, [e for e in vedges if e["from"] in ids and e["to"] in ids]


def opcion_top_grado(vnodes, vedges, limit):
    """Los `limit` nodos de mayor grado dentro de lo visible."""
    grado = {}
    for e in vedges:
        grado[e["from"]] = grado.get(e["from"], 0) + 1
        grado[e["to"]] = grado.get(e["to"], 0) + 1
    sel = sorted(vnodes, key=lambda n: -grado.get(n["id"], 0))[:limit]
    ids = {n["id"] for n in sel}
    return sel, [e for e in vedges if e["from"] in ids and e["to"] in ids]


def opcion_vecindario(vnodes, vedges, limit):
    """Cambia la PREGUNTA: no 'un trozo del grafo' sino 'el vecindario de un
    foco'. BFS desde el nodo de mayor grado hasta agotar el presupuesto."""
    ady = {}
    for e in vedges:
        ady.setdefault(e["from"], []).append(e["to"])
        ady.setdefault(e["to"], []).append(e["from"])
    if not ady:
        return opcion_actual(vnodes, vedges, limit)
    foco = max(ady, key=lambda k: len(ady[k]))
    by_id = {n["id"]: n for n in vnodes}
    vistos, cola = {foco}, [foco]
    while cola and len(vistos) < limit:
        x = cola.pop(0)
        for y in ady.get(x, []):
            if y not in vistos and len(vistos) < limit:
                vistos.add(y); cola.append(y)
    sel = [by_id[i] for i in vistos if i in by_id]
    ids = {n["id"] for n in sel}
    return sel, [e for e in vedges if e["from"] in ids and e["to"] in ids]


OPCIONES = [
    ("D vecindario (BFS desde foco)", opcion_vecindario),
    ("0 actual (subgrafo inducido)", opcion_actual),
    ("A subir limite a 2000", opcion_subir_limite),
    ("B semilla por aristas", opcion_semilla_por_aristas),
    ("C top-grado", opcion_top_grado),
]

if __name__ == "__main__":
    LIMIT = 300
    for n in (500, 1000, 2000):
        p = build(n, n * 3, mode="random")
        vnodes, vedges = visibles(p)
        print(f"--- n={n} entidades, {len(vedges)} relaciones visibles, limit={LIMIT} ---")
        for nombre, fn in OPCIONES:
            sel, ke = fn(vnodes, vedges, LIMIT)
            ser = serialize_graph("leyenda", sel, ke)
            comp = len({e["from"] for e in ke} | {e["to"] for e in ke})
            print(f"  {nombre:32s} nodos={len(sel):5d} aristas={len(ke):5d} "
                  f"dens={len(ke)/max(1,len(sel)):5.2f} "
                  f"cobertura_relaciones={100*len(ke)/max(1,len(vedges)):5.1f}% "
                  f"nodos_conectados={comp:5d} bytes={len(json.dumps(ser)):8d}")

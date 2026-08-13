"""Banco de medida (no versionado): balance por capa de /api/graph."""
import json, os, sys, random, tempfile
from pathlib import Path
VIEWER = Path(__file__).resolve().parents[3] / "viewer"
sys.path.insert(0, str(VIEWER))
os.environ["S9K_GRAPH_PROVIDER"] = "mock"
os.environ["S9K_DEFAULT_WORKSPACE"] = "leyenda"
os.environ.setdefault("S9K_CSRF_SECRET", "x" * 64)
os.environ.setdefault("S9K_SESSION_SECURE", "false")


def build(n_nodes, n_edges, mode="random", seed=7, edge_vis="reference", node_vis="reference"):
    rnd = random.Random(seed)
    nodes = [{"id": f"n{i}", "entity_id": f"n{i}", "label": f"E{i}", "type": "Character",
              "visibility": node_vis, "workspace": "leyenda", "scope": "juego",
              "knowledge_layer": "book", "review_status": "auto_extracted", "confidence": 0.9}
             for i in range(n_nodes)]
    edges = []
    for k in range(n_edges):
        if mode == "random":
            a, b = rnd.randrange(n_nodes), rnd.randrange(n_nodes)
        elif mode == "head":     # control: todas las aristas entre los 300 primeros nodos
            a, b = rnd.randrange(min(300, n_nodes)), rnd.randrange(min(300, n_nodes))
        elif mode == "chain":
            a = k % max(1, n_nodes - 1); b = a + 1
        if a == b:
            b = (b + 1) % n_nodes
        edges.append({"id": f"e{k}", "from": f"n{a}", "to": f"n{b}", "type": "RELATED_TO",
                      "label": "rel", "visibility": edge_vis, "workspace": "leyenda",
                      "scope": "juego", "review_status": "auto_extracted", "confidence": 0.8})
    p = Path(tempfile.mkdtemp()) / "g.json"
    p.write_text(json.dumps({"workspace": "leyenda", "nodes": nodes, "edges": edges}), encoding="utf-8")
    return p


def measure(path, limit):
    from app.providers.mock_provider import MockGraphProvider
    from app.authz.filtered_provider import PolicyFilteredProvider, _ALL
    from app.policies.engine import VisibilityPolicy
    from app.policies.models import ViewerContext
    from app.serializers import serialize_graph
    import inspect
    base = MockGraphProvider(path)
    pol = VisibilityPolicy()
    # Espectador REAL, sin bypass: si usaramos admin_full=True la politica no
    # se evaluaria y la columna "drop_politica" seria un instrumento muerto.
    ctx = ViewerContext(
        role="reviewer",
        allowed_workspaces=frozenset({"leyenda"}),
        can_view_reference=True,
        can_view_secret=False,
        can_view_future=False,
        session_public=True,
        admin_full=False,
    )
    prov = PolicyFilteredProvider(base, ctx, pol)
    R = {}
    R["L0_store_edges"] = len(base._edges)
    bn, be = base.graph("leyenda", limit=_ALL)
    R["L1_base_ALL_nodes"], R["L1_base_ALL_edges"] = len(bn), len(be)
    bn2, be2 = base.graph("leyenda", limit=limit)
    R["L1b_base_limit_edges"] = len(be2)
    vnodes_full = pol.filter_nodes(bn, ctx)
    R["L2_nodes_visibles"] = len(vnodes_full)
    vnodes = vnodes_full[:limit]
    R["L2_nodes_tras_truncar"] = len(vnodes)
    vids = {n["id"] for n in vnodes}
    drop_trunc = drop_pol = 0
    for e in be:
        if e["from"] not in vids or e["to"] not in vids:
            drop_trunc += 1
        elif not pol.can_view(e, ctx).visible:
            drop_pol += 1
    R["L3_edges_in"] = len(be)
    R["L3_drop_truncado"] = drop_trunc
    R["L3_drop_politica"] = drop_pol
    vedges = pol.filter_edges(be, vids, ctx)
    R["L3_edges_out"] = len(vedges)
    ser = serialize_graph("leyenda", vnodes, vedges)
    R["L4_serial_nodes"], R["L4_serial_edges"] = len(ser["nodes"]), len(ser["edges"])
    R["L5_json_bytes"] = len(json.dumps(ser))
    pn, pe = prov.graph("leyenda", limit=limit)
    R["Lprov_nodes"], R["Lprov_edges"] = len(pn), len(pe)
    return R


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="random")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--edge-vis", default="reference")
    a = ap.parse_args()
    print(f"### modo={a.mode} limit={a.limit} edge_vis={a.edge_vis}")
    for n in (300, 500, 1000, 2000):
        p = build(n, n * 3, mode=a.mode, edge_vis=a.edge_vis)
        R = measure(p, a.limit)
        pred = n * 3 * (min(a.limit, n) / n) ** 2
        print(f"n={n:5d} E={n*3:5d} | L0={R['L0_store_edges']:5d} L1_ALL={R['L1_base_ALL_edges']:5d} "
              f"L1_limit={R['L1b_base_limit_edges']:5d} L3in={R['L3_edges_in']:5d} "
              f"L3out={R['L3_edges_out']:5d} L4={R['L4_serial_edges']:5d} prov={R['Lprov_edges']:5d} "
              f"nodos={R['L4_serial_nodes']:4d} | trunc={R['L3_drop_truncado']:5d} "
              f"pol={R['L3_drop_politica']:5d} | pred(L/N)^2={pred:7.1f} "
              f"| dens={R['L3_edges_out']/max(1,R['L4_serial_nodes']):.2f} bytes={R['L5_json_bytes']}")

"""Cierre del balance por HTTP: lo que sale por el cable de /api/graph."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
VIEWER = ROOT / "viewer"
sys.path.insert(0, str(VIEWER))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_gsat import build  # noqa: E402

os.environ["S9K_GRAPH_PROVIDER"] = "mock"
os.environ["S9K_DEFAULT_WORKSPACE"] = "leyenda"
os.environ.setdefault("S9K_CSRF_SECRET", "x" * 64)
os.environ.setdefault("S9K_SESSION_SECURE", "false")

if __name__ == "__main__":
    print("### HTTP GET /api/graph?limit=300 (TestClient, provider mock)")
    for n in (300, 500, 1000, 2000):
        p = build(n, n * 3, mode="random")
        os.environ["S9K_SAMPLE_GRAPH_PATH"] = str(p)
        for m in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
            sys.modules.pop(m, None)
        from app.config import get_settings
        get_settings.cache_clear()
        from app.main import app
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/graph?limit=300")
        body = r.json()
        raw = r.content
        print(f"n={n:5d} E={n*3:5d} -> HTTP {r.status_code} nodos={len(body['nodes']):4d} "
              f"aristas={len(body['edges']):5d} dens={len(body['edges'])/max(1,len(body['nodes'])):.2f} "
              f"bytes_en_el_cable={len(raw)}")

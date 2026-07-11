import os
import sys
from pathlib import Path

VIEWER_ROOT = Path(__file__).resolve().parents[1]
if str(VIEWER_ROOT) not in sys.path:
    sys.path.insert(0, str(VIEWER_ROOT))

# Debe fijarse antes de que algo importe app.config / app.deps (Settings se
# construye con lru_cache, así que el primer valor leído es el que queda).
os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
os.environ.setdefault("S9K_DEFAULT_WORKSPACE", "leyenda")
os.environ.setdefault(
    "S9K_SAMPLE_GRAPH_PATH", str(VIEWER_ROOT / "examples" / "sample_graph.json")
)

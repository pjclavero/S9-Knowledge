import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "viewer")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_gsat import build  # noqa: E402
from harness_opciones import visibles, opcion_actual  # noqa: E402
from app.serializers import serialize_graph  # noqa: E402

p = build(2000, 6000, mode="random")
vn, ve = visibles(p)
sel, ke = opcion_actual(vn, ve, 300)
out = Path(__file__).resolve().parent / "payload_n2000.json"
out.write_text(json.dumps(serialize_graph("leyenda", sel, ke)), encoding="utf-8")
print(out, len(sel), len(ke))

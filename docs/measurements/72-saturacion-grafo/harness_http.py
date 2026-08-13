"""Cierre del balance por HTTP: lo que sale por el cable de /api/graph.

CUARTA AVERIA DEL INSTRUMENTO (detectada por el revisor, corregida aqui):
la version anterior de este banco NUNCA fijaba ``S9K_AUTH_ENABLED``, cuyo
valor por defecto es ``False`` (``viewer/app/auth/config.py:13``). Con la auth
apagada, ``viewer/app/authz/context.py:84-88`` devuelve
``ViewerContext(role="public", admin_full=True)``: **bypass total**. Es decir,
la fila L5 "HTTP 200, cuerpo real" estaba medida sin ejercer la autorizacion,
exactamente la misma averia que ya se habia corregido en ``harness_gsat.py``,
un fichero mas alla. Los numeros no cambian (la fixture es toda `reference`),
pero la AFIRMACION DE ALCANCE si: no certificaban "la autorizacion no pierde
nada de extremo a extremo".

Ahora se miden DOS filas declaradas y se comprueba con un control que la
segunda ejerce la politica de verdad.
"""
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


def _app_para(path):
    """App recien construida contra la fixture `path`."""
    os.environ["S9K_SAMPLE_GRAPH_PATH"] = str(path)
    for m in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
        sys.modules.pop(m, None)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import app
    return app


def _pide(app, ctx=None):
    """GET /api/graph?limit=300. Si `ctx` viene, se inyecta como el contexto de
    visibilidad de la peticion (espectador REAL, sin bypass)."""
    from fastapi.testclient import TestClient
    # OJO: no sirve sobrescribir `get_visibility_context`. La ruta /api/graph
    # depende de `get_filtered_provider`, y ESE llama a get_visibility_context
    # como funcion normal, no via Depends -> el override se ignora en silencio.
    # Comprobado: con ese override el control NO colapsaba (300/171). Se
    # sobrescribe el proveedor filtrado, que si es la dependencia real.
    from app.authz.dependencies import get_filtered_provider
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.deps import get_provider
    if ctx is not None:
        app.dependency_overrides[get_filtered_provider] = (
            lambda: PolicyFilteredProvider(get_provider(), ctx)
        )
    try:
        r = TestClient(app).get("/api/graph?limit=300")
        return r.json(), len(r.content), r.status_code
    finally:
        app.dependency_overrides.clear()


def _reviewer(**kw):
    from app.policies.models import ViewerContext
    base = dict(role="reviewer", allowed_workspaces=frozenset({"leyenda"}),
                can_view_reference=True, admin_full=False)
    base.update(kw)
    return ViewerContext(**base)


if __name__ == "__main__":
    print("### L5a — tal cual, S9K_AUTH_ENABLED sin fijar (por defecto False)")
    print("###       => contexto admin_full=True: mide VOLUMEN, NO ejerce autorizacion")
    for n in (300, 500, 1000, 2000):
        app = _app_para(build(n, n * 3, mode="random"))
        from app.authz.dependencies import get_visibility_context  # noqa: E402
        b, nbytes, code = _pide(app)
        # Declara el bypass en vez de esconderlo.
        from app.authz.context import build_viewer_context
        ctx_real = build_viewer_context(role=None, auth_enabled=False, default_workspace="leyenda")
        print(f"n={n:5d} E={n*3:5d} -> HTTP {code} nodos={len(b['nodes']):4d} "
              f"aristas={len(b['edges']):5d} bytes={nbytes:7d} "
              f"| admin_full={ctx_real.admin_full}")

    print()
    print("### L5b — MISMO endpoint con espectador `reviewer` REAL (admin_full=False)")
    for n in (300, 500, 1000, 2000):
        app = _app_para(build(n, n * 3, mode="random"))
        b, nbytes, code = _pide(app, _reviewer())
        print(f"n={n:5d} E={n*3:5d} -> HTTP {code} nodos={len(b['nodes']):4d} "
              f"aristas={len(b['edges']):5d} "
              f"dens={len(b['edges'])/max(1,len(b['nodes'])):.2f} bytes={nbytes:7d}")

    print()
    print("### CONTROL de L5b — el mismo espectador SIN can_view_reference.")
    print("### Si la autorizacion se ejerce de verdad, esto tiene que COLAPSAR.")
    app = _app_para(build(2000, 6000, mode="random"))
    b, nbytes, _ = _pide(app, _reviewer(can_view_reference=False))
    print(f"n= 2000 -> nodos={len(b['nodes'])} aristas={len(b['edges'])} "
          f"(esperado 0/0; si saliera 300/171 la fila L5b seria un instrumento muerto)")

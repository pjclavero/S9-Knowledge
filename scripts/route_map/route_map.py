#!/usr/bin/env python3
"""Mapa de rutas v2 — contrato mecánico de las rutas del visor S9 Knowledge.

Reconstruye, para CADA ruta, seis propiedades independientes con evidencia
mecánica (nunca por grep de menciones):

  defined     el handler existe en el código (AST de los decoradores).
  mounted     la ruta está en el enrutador de la app REAL (`app.main.app`).
  linked      es alcanzable navegando desde la barra de navegación (BFS sobre
              plantillas: nav -> ruta -> plantilla que renderiza -> enlaces...).
  tested      alguna petición atravesó su objeto Route durante la corrida de
              pytest (sonda `route_map.pytest_route_probe`), no que su nombre
              aparezca en un fichero de test.
  authorized  con auth activada, una petición ANÓNIMA real recibe denegación
              (401/redirección a /login, o 403/404 con guardián declarado), más
              la detección estática del guardián (dependencias del Dependant +
              llamadas en el cuerpo). En los métodos con cuerpo se emite un token
              CSRF VÁLIDO para que quien deniegue sea el guardián y no la capa
              CSRF. Un 404 o un 403 en una ruta SIN guardián estático no cuentan
              como denegación: son `denegada-404-ambigua` y
              `denegacion-no-atribuible`.
  consumed    alguien la usa: plantillas, JS estático, tests o código.

Hallazgos que emite:
  MUERTA        definida pero no montada en la app real.
  ROTO          enlace de navegación a una ruta que no existe.
  SIN-AUTH      ruta que responde 2xx a una petición anónima con auth activada.
  HUERFANA      montada pero no alcanzable desde la navegación.
  NO-PROBADA    montada pero nunca ejercitada contra la app real.
  404-AMBIGUO   404 con el id fabricado por la sonda y sin guardián declarado:
                la denegación NO está demostrada (una ruta abierta de par en par
                subía si no el contador de rutas que deniegan).
  NO-ATRIBUIBLE 403 sin guardián declarado: lo dijo otra capa (CSRF), no el
                control de acceso.
  CONTRADICCION la fila dice a la vez «deniega al anónimo» y «servida a un rol»,
                sin guardián que sostenga ninguna de las dos.

Uso:
    python3 scripts/route_map/route_map.py --repo . \
        --tested artifacts/route-map/tested_routes.json \
        --out artifacts/route-map/route_map.json \
        --md  artifacts/route-map/route_map.md

    # modo interno (subproceso con auth activada)
    python3 scripts/route_map/route_map.py --repo . --probe-only --out /tmp/p.json

Es reejecutable contra cualquier rama/worktree: todo se deriva de `--repo`.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Arranque: sys.path y entorno mínimo para importar la app real
# --------------------------------------------------------------------------

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Rutas públicas por diseño: no se consideran agujeros si responden 2xx anónimas.
PUBLIC_BY_DESIGN = {"GET /login", "POST /login"}

# Dependencias que hacen ACOTADO DE DATOS, no control de acceso a la ruta.
SCOPING_DEPS = {"get_filtered_provider", "get_visibility_scope", "get_provider",
                "get_default_workspace"}

GUARD_NAME_RE = re.compile(r"(^_?require_)|guard|_access$", re.IGNORECASE)


def bootstrap(repo: Path) -> None:
    """Deja el proceso en condiciones de `import app.main` desde `repo`."""
    viewer = repo / "viewer"
    de_app = repo / "data-engine" / "app"
    for p in (str(de_app), str(viewer)):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
    os.environ.setdefault("S9K_DEFAULT_WORKSPACE", "leyenda")
    os.environ.setdefault(
        "S9K_SAMPLE_GRAPH_PATH", str(viewer / "examples" / "sample_graph.json")
    )
    import secrets

    os.environ.setdefault("S9K_CSRF_SECRET", secrets.token_urlsafe(48))
    os.environ.setdefault("S9K_SESSION_SECURE", "false")


def load_real_app(repo: Path):
    """Importa y devuelve el objeto app REAL (`app.main.app`)."""
    bootstrap(repo)
    import importlib

    main = importlib.import_module("app.main")
    return main.app


# --------------------------------------------------------------------------
# 1) mounted — verdad de campo tomada del enrutador de la app real
# --------------------------------------------------------------------------

def iter_effective_routes(app):
    """Aplana el enrutador REAL a rutas efectivas.

    FastAPI >= 0.13x no aplana `include_router`: deja objetos `_IncludedRouter`
    que resuelven sus rutas efectivas en tiempo de petición. Enumerar sólo
    `app.router.routes` deja fuera el 80% de la app (11 de 59 aquí). Se recorre
    `effective_route_contexts()` para obtener el path final, el `dependant` con
    las dependencias del include ya combinadas, y el objeto Route ORIGINAL que
    realmente atiende la petición (que es el que instrumenta la sonda).

    Devuelve tuplas (path, methods, dependant, endpoint, handler_route, kind).
    """
    try:
        from fastapi.routing import _IncludedRouter
    except ImportError:  # pragma: no cover - versiones antiguas de FastAPI
        _IncludedRouter = ()
    from fastapi.routing import APIRoute
    from starlette.routing import Mount, Route

    for r in app.router.routes:
        if _IncludedRouter and isinstance(r, _IncludedRouter):
            ctxs = list(r.effective_route_contexts()) + list(r.effective_low_priority_routes())
            for ctx in ctxs:
                original = ctx.original_route
                yield (ctx.path or getattr(original, "path", ""),
                       sorted(ctx.methods or getattr(original, "methods", {"GET"})),
                       ctx.dependant, ctx.endpoint or getattr(original, "endpoint", None),
                       original, "route")
        elif isinstance(r, Mount):
            yield (r.path, ["MOUNT"], None, None, r, "mount")
        elif isinstance(r, (APIRoute, Route)):
            yield (r.path, sorted(r.methods or {"GET"}), getattr(r, "dependant", None),
                   r.endpoint, r, "route")


def collect_mounted(app) -> list[dict]:
    out: list[dict] = []
    for path, methods, dependant, endpoint, _handler, kind in iter_effective_routes(app):
        if kind == "mount":
            out.append({
                "key": f"MOUNT {path}", "path": path, "method": "MOUNT",
                "kind": "mount", "endpoint": getattr(_handler, "name", ""),
                "source": "", "deps": [], "scoping_deps": [], "body_guards": [],
            })
            continue
        src = ""
        code = getattr(endpoint, "__code__", None)
        if code is not None:
            src = f"{code.co_filename}:{code.co_firstlineno}"
        deps, scoping = [], []
        if dependant is not None:
            from fastapi.dependencies.utils import get_flat_dependant

            flat = get_flat_dependant(dependant, skip_repeats=True)
            for d in flat.dependencies + [flat]:
                call = getattr(d, "call", None)
                if call is None:
                    continue
                name = getattr(call, "__name__", repr(call))
                mod = getattr(call, "__module__", "")
                if name in SCOPING_DEPS:
                    scoping.append(f"{mod}.{name}")
                elif GUARD_NAME_RE.search(name) and call is not endpoint:
                    deps.append(f"{mod}.{name}")
        body_fields = []
        if dependant is not None:
            for f in getattr(dependant, "body_params", []) or []:
                name = getattr(f, "name", None) or getattr(f, "alias", None)
                if name:
                    body_fields.append(name)
        body_guards = _body_guard_calls(endpoint)
        # `html_guard` / `html_role_guard` NO deniegan por sí solos: devuelven un
        # RedirectResponse que el handler debe devolver. Si el cuerpo no lo
        # comprueba, la ruta declara guardián y sirve 200 a un anónimo.
        declara_guardian_pasivo = any(
            d.rsplit(".", 1)[-1] in {"html_guard", "_guard"} for d in deps)
        aplica = True
        if declara_guardian_pasivo:
            aplica = _devuelve_la_salida_del_guardian(endpoint)
        for m in methods:
            if m == "HEAD":
                continue
            out.append({
                "key": f"{m} {path}", "path": path, "method": m,
                "kind": "api" if path.startswith("/api/") else "html",
                "endpoint": getattr(endpoint, "__name__", ""),
                "module": getattr(endpoint, "__module__", ""),
                "source": src,
                "deps": sorted(set(deps)),
                "scoping_deps": sorted(set(scoping)),
                "body_guards": body_guards,
                "body_fields": sorted(set(body_fields)),
                "guardian_pasivo_no_aplicado": bool(declara_guardian_pasivo and not aplica),
            })
    return out


PASSIVE_GUARDS = {"html_guard", "html_role_guard"}


def _endpoint_ast(endpoint):
    try:
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _passive_guard_params(fn: ast.AST) -> set[str]:
    """Parámetros cuyo valor por defecto es `Depends(html_guard|html_role_guard(...))`."""
    out: set[str] = set()
    args = fn.args
    posibles = list(args.args) + list(args.kwonlyargs)
    defaults = list(args.defaults) + [d for d in args.kw_defaults or [] if d is not None]
    # Emparejar por la cola: los defaults corresponden a los últimos posicionales.
    pares = list(zip(args.args[len(args.args) - len(args.defaults):], args.defaults))
    pares += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults or []) if d is not None]
    for arg, default in pares:
        if not isinstance(default, ast.Call):
            continue
        fname = getattr(default.func, "id", None) or getattr(default.func, "attr", None)
        if fname != "Depends" or not default.args:
            continue
        inner = default.args[0]
        nombre = (getattr(inner, "id", None) or getattr(inner, "attr", None)
                  or getattr(getattr(inner, "func", None), "id", None)
                  or getattr(getattr(inner, "func", None), "attr", None))
        if nombre in PASSIVE_GUARDS:
            out.add(arg.arg)
    del posibles, defaults
    return out


def _devuelve_la_salida_del_guardian(endpoint) -> bool:
    """¿El handler DEVUELVE de verdad la respuesta que le entrega el guardián?

    Comprobación sintáctica sobre el parámetro CONCRETO al que está atado el
    guardián pasivo, no búsqueda de subcadenas: un `isinstance(datos, list)`
    ajeno en el cuerpo no cuenta, ni la palabra `RedirectResponse` suelta.
    Debe existir un `if isinstance(<ese parámetro>, ...)` cuyo cuerpo retorne, o
    un `return <ese parámetro>` directo.
    """
    fn = _endpoint_ast(endpoint)
    if fn is None:
        return True  # sin fuente no se puede afirmar el defecto: no se inventa
    params = _passive_guard_params(fn)
    if not params:
        return True
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Call):
            f = node.test.func
            if (getattr(f, "id", None) == "isinstance" and node.test.args
                    and isinstance(node.test.args[0], ast.Name)
                    and node.test.args[0].id in params
                    and any(isinstance(s, ast.Return) for s in ast.walk(node))):
                return True
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name) \
                and node.value.id in params:
            return True
    return False


def _body_guard_calls(endpoint) -> list[str]:
    """Guardianes invocados en el CUERPO del handler (patrón `_require_*`)."""
    if endpoint is None:
        return []
    try:
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    except Exception:
        return []
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else "")
            if name and name not in SCOPING_DEPS and GUARD_NAME_RE.search(name):
                found.add(name)
    return sorted(found)


# --------------------------------------------------------------------------
# 2) defined — AST de los decoradores (independiente de que se monte o no)
# --------------------------------------------------------------------------

def _const_str(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def collect_defined(repo: Path) -> list[dict]:
    root = repo / "viewer" / "app"
    out: list[dict] = []
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        prefixes: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = node.value.func
                fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if fname in {"APIRouter", "FastAPI"}:
                    prefix = ""
                    for kw in node.value.keywords:
                        if kw.arg == "prefix":
                            prefix = _const_str(kw.value) or ""
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            prefixes[t.id] = prefix
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                method = dec.func.attr.lower()
                owner = dec.func.value
                owner_name = owner.id if isinstance(owner, ast.Name) else ""
                if method not in HTTP_METHODS or owner_name not in prefixes:
                    continue
                sub = _const_str(dec.args[0]) if dec.args else None
                if sub is None:
                    continue
                full = (prefixes[owner_name] + sub) or "/"
                out.append({
                    "key": f"{method.upper()} {full}",
                    "path": full, "method": method.upper(),
                    "file": str(py.relative_to(repo)), "line": node.lineno,
                    "func": node.name, "router_var": owner_name,
                })
    return out


# --------------------------------------------------------------------------
# 3) enlaces de plantillas / JS y alcanzabilidad desde la navegación
# --------------------------------------------------------------------------

JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
JS_LINE_COMMENT = re.compile(r"(?m)^\s*//.*$")
PY_COMMENT = re.compile(r"(?m)#.*$")

LINK_ATTR = re.compile(
    r"""(?:href|action|hx-get|hx-post|hx-put|hx-delete|data-url|formaction)\s*=\s*["']([^"']+)["']""",
    re.I,
)
JS_URL = re.compile(r"""(?:fetch\(|url\s*=\s*|axios\.\w+\(|open\(\s*["'](?:GET|POST)["']\s*,\s*)["'`](/[^"'`\s]*)""")
JS_ANY_PATH = re.compile(r"""["'`](/(?:api|entities|sources|graph|jobs|status|reviews|admin|v3|review-console|partida|account|login|logout)[^"'`\s]*)["'`]""")


def strip_comments(text: str, kind: str) -> str:
    if kind == "html":
        return HTML_COMMENT.sub(" ", JINJA_COMMENT.sub(" ", text))
    if kind == "js":
        return JS_LINE_COMMENT.sub(" ", JS_BLOCK_COMMENT.sub(" ", text))
    if kind == "py":
        return PY_COMMENT.sub(" ", text)
    return text


JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")


def normalize_link(raw: str) -> tuple[str | None, str]:
    """Devuelve (url_concreta_o_None, estado).

    Sustituye expresiones Jinja por un segmento comodín para poder casar contra
    el path_regex de Starlette. Devuelve None cuando el enlace no es resoluble
    (enlace externo, ancla, o URL enteramente dinámica).
    """
    u = raw.strip()
    if not u or u.startswith(("#", "http://", "https://", "mailto:", "javascript:", "//")):
        return None, "externo"
    if u.startswith("{{") or u.startswith("{%"):
        return None, "dinamico"
    u = u.split("?")[0].split("#")[0]
    u = JINJA_EXPR.sub("X", u)
    if not u.startswith("/"):
        return None, "relativo"
    return u, "ok"


def collect_links(repo: Path) -> list[dict]:
    """Enlaces salientes de cada plantilla y de cada fichero JS estático."""
    out: list[dict] = []
    tpl_root = repo / "viewer" / "app" / "templates"
    for f in sorted(tpl_root.rglob("*.html")):
        text = strip_comments(f.read_text(encoding="utf-8"), "html")
        rel = str(f.relative_to(tpl_root))
        for m in LINK_ATTR.finditer(text):
            url, state = normalize_link(m.group(1))
            out.append({"from": rel, "from_kind": "template", "raw": m.group(1),
                        "url": url, "state": state,
                        "method": "POST" if "action" in m.group(0).lower()
                                  or "hx-post" in m.group(0).lower() else "GET"})
        for m in JS_URL.finditer(text):
            url, state = normalize_link(m.group(1))
            out.append({"from": rel, "from_kind": "template-js", "raw": m.group(1),
                        "url": url, "state": state, "method": "GET"})
        for m in JS_ANY_PATH.finditer(text):
            url, state = normalize_link(m.group(1))
            out.append({"from": rel, "from_kind": "template-js", "raw": m.group(1),
                        "url": url, "state": state, "method": "GET"})
    js_root = repo / "viewer" / "app" / "static"
    for f in sorted(js_root.rglob("*.js")):
        text = strip_comments(f.read_text(encoding="utf-8"), "js")
        rel = "static/" + str(f.relative_to(js_root))
        for rx in (JS_URL, JS_ANY_PATH):
            for m in rx.finditer(text):
                url, state = normalize_link(m.group(1))
                out.append({"from": rel, "from_kind": "js", "raw": m.group(1),
                            "url": url, "state": state, "method": "GET"})
    # deduplicar
    seen, dedup = set(), []
    for l in out:
        k = (l["from"], l["raw"], l["method"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(l)
    return dedup


def collect_handler_templates(repo: Path) -> dict[str, list[str]]:
    """func_name -> plantillas que renderiza (literales en TemplateResponse)."""
    out: dict[str, list[str]] = {}
    root = repo / "viewer" / "app"
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tpls = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    fname = getattr(fn, "attr", None) or getattr(fn, "id", "")
                    if fname in {"TemplateResponse", "get_template"}:
                        for a in sub.args:
                            s = _const_str(a)
                            if s and s.endswith(".html"):
                                tpls.append(s)
                        for kw in sub.keywords:
                            s = _const_str(kw.value)
                            if s and s.endswith(".html"):
                                tpls.append(s)
            if tpls:
                out.setdefault(node.name, []).extend(sorted(set(tpls)))
    return out


def chassis_nav_links(app) -> tuple[list[dict], str | None]:
    """Navegación declarada como DATOS (`app.chassis.NAV`), si existe.

    Desde el chasis, `base.html` no lleva enlaces escritos a mano: recorre
    `chassis_nav`, que resuelve NOMBRES de ruta contra lo montado. Un mapa que
    sólo lea `href="..."` literales vería una navegación vacía y declararía
    huérfano el visor entero. Se resuelve el contrato con un usuario ficticio
    con todos los permisos para obtener el conjunto MÁXIMO de enlaces.

    Devuelve (enlaces, error). El error no se traga: un `ChassisContractError`
    significa que un elemento del menú apunta a una ruta no montada, es decir,
    un enlace ROTO, y así se reporta.
    """
    try:
        import importlib

        chassis = importlib.import_module("app.chassis")
    except Exception:
        return [], None  # rama sin chasis: no es un error

    class _TodoPermitido:
        def can_access_admin(self):
            return True

        def can_see_reviews(self):
            return True

    try:
        items = chassis.nav_for(app, _TodoPermitido())
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    return ([{"from": "app.chassis.NAV", "from_kind": "nav-contrato",
              "raw": i["route_name"], "url": i["url"], "state": "ok",
              "method": "GET"} for i in items], None)


SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*["'](/static/[^"']+\.js)["']""", re.I)


def template_scripts(repo: Path) -> dict[str, list[str]]:
    """plantilla -> ficheros JS que carga (clave para la alcanzabilidad real:
    /api/graph no está enlazada con un <a>, la pide el JS de /graph)."""
    tpl_root = repo / "viewer" / "app" / "templates"
    out: dict[str, list[str]] = {}
    for f in sorted(tpl_root.rglob("*.html")):
        text = strip_comments(f.read_text(encoding="utf-8"), "html")
        rel = str(f.relative_to(tpl_root))
        out[rel] = ["static/" + m.split("/static/", 1)[1] for m in SCRIPT_SRC.findall(text)]
    return out


def template_inheritance(repo: Path) -> dict[str, list[str]]:
    """plantilla -> plantillas de las que hereda/incluye (extends/include)."""
    tpl_root = repo / "viewer" / "app" / "templates"
    rx = re.compile(r"""\{%\s*(?:extends|include)\s+["']([^"']+)["']""")
    out: dict[str, list[str]] = {}
    for f in sorted(tpl_root.rglob("*.html")):
        text = f.read_text(encoding="utf-8")
        rel = str(f.relative_to(tpl_root))
        out[rel] = sorted(set(rx.findall(text)))
    return out


# --------------------------------------------------------------------------
# 4) authorized — sonda anónima real contra la app con auth activada
# --------------------------------------------------------------------------

def _concrete_url(path: str) -> str:
    def sub(m):
        name = m.group(1).split(":")[0]
        return "1" if name.endswith("_id") and name in {"user_id", "access_id"} else "probe"
    return re.sub(r"\{([^}]+)\}", sub, path)


def run_probe(repo: Path) -> dict[str, dict]:
    """Ejecuta la sonda anónima en un SUBPROCESO con auth activada."""
    out = Path(tempfile.mkdtemp(prefix="s9k-routeprobe-")) / "probe.json"
    env = dict(os.environ)
    dbdir = out.parent
    env.update({
        "S9K_AUTH_ENABLED": "true",
        "S9K_AUTH_DB_PATH": str(dbdir / "auth.db"),
        "S9K_GRAPH_PROVIDER": "mock",
        "S9K_SESSION_SECURE": "false",
        "S9K_CSRF_SECRET": __import__("secrets").token_urlsafe(48),
        "S9K_SAMPLE_GRAPH_PATH": str(repo / "viewer" / "examples" / "sample_graph.json"),
    })
    env.pop("S9K_AUTH_EXPOSE_DOCS", None)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--repo", str(repo),
           "--probe-only", "--out", str(out)]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    if not out.exists():
        return {"__error__": {"stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}}
    return json.loads(out.read_text(encoding="utf-8"))


ROLES = ("viewer", "reviewer", "admin")


def _csrf_para(session_id: int, session_hash: str, secret: str) -> str:
    """Token CSRF que el visor aceptaría para esa sesión (o para el anónimo).

    Reproduce EXACTAMENTE la derivación del middleware
    (`app.auth.middleware`: `csrf_raw = HMAC(secret, "csrf:<id>:<hash[:8]>")`)
    y de `app.auth.csrf.get_csrf_token_for_session`. No modifica la app: sólo
    calcula lo que la propia app calcularía. Para el anónimo, `request.state`
    queda con `session = None` y `csrf_raw = ""`, y los handlers validan contra
    `session.id if session else 0`, así que el token anónimo es derivable.
    """
    import hashlib
    import hmac

    from app.auth.csrf import get_csrf_token_for_session

    raw = ""
    if session_hash:
        raw = hmac.new(secret.encode(),
                       f"csrf:{session_id}:{session_hash[:8]}".encode(),
                       hashlib.sha256).hexdigest()
    return get_csrf_token_for_session(session_id, raw, secret=secret)


def _fresh_token(db_path: str, role: str) -> tuple[str, str]:
    """Sesión NUEVA para el rol pedido: `(cookie de sesión, token CSRF válido)`.

    Se emite una por petición a propósito: el barrido incluye rutas que revocan
    sesiones o modifican usuarios, y una sesión reutilizada podría quedar
    invalidada a media pasada y producir denegaciones falsas.
    """
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(Path(db_path)) as conn:
        user = auth_db.get_user_by_username(conn, f"probe_{role}")
        if user is None:
            user = auth_db.create_user(
                conn, f"probe_{role}", f"Sonda {role}",
                hash_password("Probe-" + "z" * 20), role=role,
            )
        token, sess = create_session(conn, user)
    secret = get_auth_settings().S9K_CSRF_SECRET
    return token, _csrf_para(sess.id, getattr(sess, "session_hash", "") or "", secret)


def _install_resolver(app) -> list:
    """Instrumenta las rutas para saber QUÉ handler atiende cada URL.

    Una ruta puede quedar CAPTURADA por otra declarada antes (`/sources/panel`
    la absorbe `/sources/{source_id}`). Sin esto, el barrido le atribuiría a la
    ruta capturada el resultado de autorización del handler que la ensombrece:
    una ruta sin guardián parecería denegar correctamente. La lista devuelta
    recibe el path del handler REALMENTE ejecutado en cada petición.

    El índice es `(id(route), path)`, NO el objeto `Route`. Un mismo objeto
    `Route` sirve varios paths efectivos cuando su router se incluye más de una
    vez (`include_router(r)` + `include_router(r, prefix="/dup")`). Etiquetarlo
    con el primer path visto hacía que todos los demás se declarasen CAPTURADOS
    —y por tanto `no-evaluable-capturada`— aunque respondan de verdad: su
    autorización dejaba de medirse EN SILENCIO. El envoltorio se instala una
    sola vez por objeto y resuelve en tiempo de petición cuál de los paths
    registrados casa con la URL entrante.
    """
    from starlette.routing import compile_path

    registro: list[str] = []
    # id(route) -> [(regex compilada, path efectivo), ...]
    candidatos: dict[int, list] = {}
    instalados: set[tuple[int, str]] = set()

    def _wrap(route, path):
        clave = (id(route), path)
        if clave in instalados:
            return
        handle = getattr(route, "handle", None)
        if handle is None:
            return
        rx, _, _ = compile_path(path)
        primera_vez = id(route) not in candidatos
        lista = candidatos.setdefault(id(route), [])
        lista.append((rx, path))
        instalados.add(clave)
        if not primera_vez:
            # El envoltorio ya instalado consulta `lista`, que acaba de crecer.
            return

        async def _handle(scope, receive, send, _orig=handle, _cands=lista):
            url = scope.get("path", "") or ""
            elegido = None
            for rx2, p2 in _cands:
                if rx2.fullmatch(url):
                    elegido = p2
                    break
            registro.append(elegido if elegido is not None else _cands[0][1])
            await _orig(scope, receive, send)

        route.handle = _handle

    for path, _m, _d, _e, handler_route, kind in iter_effective_routes(app):
        if kind == "route":
            _wrap(handler_route, path)
    return registro


def probe_main(repo: Path, out_path: Path) -> None:
    app = load_real_app(repo)
    # El visor NO crea la auth DB (fail-closed de `enforce_auth_security`): la
    # sonda provisiona una base vacía y efímera, sin usuarios, en un temporal.
    db_path = os.environ.get("S9K_AUTH_DB_PATH", "")
    if db_path:
        from app.auth import db as auth_db

        auth_db.ensure_migrated(Path(db_path))
    from fastapi.testclient import TestClient

    from app.auth.config import get_auth_settings

    cookie_name = get_auth_settings().S9K_SESSION_COOKIE_NAME

    results: dict[str, dict] = {}
    registro = _install_resolver(app)
    with TestClient(app, follow_redirects=False) as client:
        routes = [r for r in collect_mounted(app) if r["method"] != "MOUNT"]

        secret = get_auth_settings().S9K_CSRF_SECRET
        csrf_anonimo = _csrf_para(0, "", secret)

        def _cuerpo(r, csrf):
            """Cuerpo de la petición con un token CSRF VÁLIDO en su campo.

            Sin esto el barrido es CIEGO en los POST: la comprobación CSRF
            responde 403 antes de que hable el guardián, y ese 403 no distingue
            «no autorizado» de «falta el token». Emitiéndolo, quien decide es el
            control de acceso, que es lo que se está midiendo.
            """
            campos = r.get("body_fields") or []
            if not campos:
                return None, False
            data = {}
            enviado = False
            for f in campos:
                if "csrf" in f.lower():
                    data[f] = csrf
                    enviado = True
                else:
                    data[f] = "probe"
            return data, enviado

        def _hit(r, cookies, csrf):
            url = _concrete_url(r["path"])
            registro.clear()
            data, lleva_csrf = _cuerpo(r, csrf)
            # En los métodos con cuerpo se manda desde el primer intento: si el
            # campo CSRF tiene valor por defecto (`Form("")`) no hay 422 que
            # provoque el reintento, y la petición moriría en el CSRF.
            con_cuerpo = data is not None and r["method"] not in ("GET", "HEAD", "OPTIONS")
            if con_cuerpo:
                resp = client.request(r["method"], url, cookies=cookies, data=data)
            else:
                resp = client.request(r["method"], url, cookies=cookies)
                # 422 = la validación del cuerpo se evaluó antes del guardián. Se
                # reintenta rellenando los campos declarados para que la petición
                # llegue de verdad al control de acceso.
                if resp.status_code == 422 and data is not None:
                    resp = client.request(r["method"], url, cookies=cookies, data=data)
                    con_cuerpo = True
            csrf_enviado = bool(lleva_csrf and con_cuerpo)
            return {"status": resp.status_code, "location": resp.headers.get("location", ""),
                    "resolvio_a": registro[-1] if registro else None,
                    "csrf_enviado": bool(csrf_enviado)}

        for r in routes:
            try:
                res = _hit(r, None, csrf_anonimo)
            except Exception as exc:  # pragma: no cover
                res = {"status": None, "error": repr(exc)[:300]}
            res["por_rol"] = {}
            for role in ROLES:
                try:
                    token, csrf = _fresh_token(db_path, role)
                    res["por_rol"][role] = _hit(r, {cookie_name: token}, csrf)
                except Exception as exc:  # pragma: no cover
                    res["por_rol"][role] = {"status": None, "error": repr(exc)[:300]}
            results[r["key"]] = res
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")


def _is_denial(st: int | None, loc: str) -> bool:
    if st is None:
        return False
    if st in (401, 403, 404):
        return True
    if st in (301, 302, 303, 307, 308):
        return "/login" in (loc or "")
    return False


def role_verdict(key: str, res: dict | None, has_params: bool = False,
                 path: str = "") -> dict:
    """Rol MÍNIMO que obtiene respuesta servida, medido de verdad por rol.

    Sólo se concluye para GET: en POST la protección CSRF responde antes que el
    control de rol, así que un 403 no distingue «rol insuficiente» de «falta el
    token CSRF». Ese caso se declara no concluyente en vez de inventarlo.
    """
    if capturada_por(path or key.split(" ", 1)[-1], res):
        return {"rol_minimo": "no-evaluable-capturada", "por_rol": {}}
    if not res or not res.get("por_rol"):
        return {"rol_minimo": "sin-sonda", "por_rol": {}}
    per = {}
    for role, r in res["por_rol"].items():
        if not isinstance(r, dict):
            continue
        per[role] = r.get("status")
    if key.split(" ", 1)[0] not in ("GET", "HEAD"):
        # Sólo es concluyente si la sonda emitió un token CSRF VÁLIDO en TODAS
        # las peticiones por rol: si no, el 403 puede venir del CSRF y no del
        # control de rol, y decir «rol X» sería inventarlo.
        todos_con_csrf = all(
            isinstance(r, dict) and r.get("csrf_enviado")
            for r in res["por_rol"].values()
        )
        if not todos_con_csrf:
            return {"rol_minimo": "no-concluyente-csrf", "por_rol": per}
    for role in ROLES:
        r = res["por_rol"].get(role) or {}
        st = r.get("status")
        # En una ruta con parámetro, el 404 lo produce el identificador de
        # sonda (recurso inexistente): el control de acceso ya se pasó.
        if has_params and st == 404:
            return {"rol_minimo": role, "por_rol": per}
        if not _is_denial(st, r.get("location", "")):
            return {"rol_minimo": role, "por_rol": per}
    return {"rol_minimo": "ninguno-sirve", "por_rol": per}


def capturada_por(path: str, res: dict | None) -> str | None:
    """Path del handler que ensombrece a esta ruta, si la ha capturado."""
    if not res:
        return None
    resuelto = res.get("resolvio_a")
    if resuelto and resuelto != path:
        return resuelto
    return None


#: Veredictos que NO son «esta ruta deniega»: la petición no fue servida, pero
#: la denegación no es atribuible al control de acceso.
DENEGACIONES_NO_ATRIBUIBLES = ("denegada-404-ambigua", "denegacion-no-atribuible")


def classify_probe(key: str, res: dict | None, path: str = "",
                   static_guard: bool = False) -> tuple[str, str]:
    """(veredicto, detalle) de la sonda anónima.

    Una respuesta que no sirve contenido NO es prueba de autorización por sí
    sola. Se separan los dos casos en que el «no» no lo dice el guardián:

    - **404 sin guardián estático**: en una ruta con `{param}` el 404 lo produce
      el identificador inventado por la sonda (recurso inexistente), no el
      control de acceso. Si además la ruta no declara guardián alguno, contarlo
      como denegación hace que una ruta abierta de par en par SUBA el contador
      de rutas que deniegan. Se marca `denegada-404-ambigua`.
    - **403 sin guardián estático**: típicamente el CSRF, que responde antes que
      el guardián. Se marca `denegacion-no-atribuible`.
    """
    captor = capturada_por(path or key.split(" ", 1)[-1], res)
    if captor:
        # No se le puede atribuir el resultado del handler que la ensombrece:
        # sería dar por autorizada una ruta cuyo guardián no se ejecuta jamás.
        return "CAPTURADA", f"la sirve {captor}"
    if key in PUBLIC_BY_DESIGN:
        return "publica-por-diseno", "allowlist"
    if not res:
        return "sin-sonda", ""
    st = res.get("status")
    loc = res.get("location", "") or ""
    if st is None:
        return "inconcluyente", res.get("error", "")
    if st == 404 and not static_guard:
        return ("denegada-404-ambigua",
                "404 con id de sonda y sin guardián estático: recurso inexistente, "
                "no denegación demostrada")
    if st == 403 and not static_guard:
        return ("denegacion-no-atribuible",
                "403 sin guardián estático (CSRF u otra capa previa), no atribuible "
                "al control de acceso")
    if st in (401, 403, 404):
        return "denegada", str(st)
    if st in (301, 302, 303, 307, 308):
        return ("denegada" if "/login" in loc else "inconcluyente"), f"{st} -> {loc}"
    if 200 <= st < 300:
        return "SIN-AUTH", str(st)
    if st == 422:
        return "inconcluyente", "422 validacion antes del guardian"
    return "inconcluyente", str(st)


def _motivo_contradiccion(r: dict) -> str:
    """Por qué esta fila se contradice a sí misma, o cadena vacía si no lo hace.

    Condición común: el barrido dice «deniega al anónimo» Y a la vez que hay un
    rol al que la ruta SÍ le responde. Eso solo es contradictorio si además falta
    lo que sostendría la denegación:

    - `sin-guardian-estatico`: la ruta no declara guardián alguno.
    - `indistinguible-del-acceso`: el anónimo recibe EXACTAMENTE el mismo estado
      que los tres roles. Señal puramente dinámica, sin heurística de nombres:
      si la identidad no cambia nada, no se ha demostrado ninguna denegación.
      Rutas cerradas a todos (`/docs` con 404 para todo el mundo) no entran,
      porque ahí no hay ningún rol servido.
    """
    if r["key"] in PUBLIC_BY_DESIGN:
        return ""
    if not r["authz_probe"].startswith("deneg"):
        return ""
    if r["rol_minimo_observado"] not in ROLES:
        return ""
    motivos = []
    if not r["authz_static"]:
        motivos.append("sin-guardian-estatico")
    estados = list((r.get("status_por_rol") or {}).values())
    anon = r.get("status_anonimo")
    if anon is not None and estados and all(e == anon for e in estados):
        motivos.append("indistinguible-del-acceso")
    return "+".join(motivos)


# --------------------------------------------------------------------------
# 5) ensamblado del mapa
# --------------------------------------------------------------------------

def build_map(repo: Path, tested_path: Path | None, skip_probe: bool = False,
              head_label: str = "") -> dict:
    app = load_real_app(repo)
    mounted = collect_mounted(app)
    mounted_routes = [r for r in mounted if r["method"] != "MOUNT"]
    defined = collect_defined(repo)
    links = collect_links(repo)
    handler_tpls = collect_handler_templates(repo)
    inherit = template_inheritance(repo)
    scripts = template_scripts(repo)

    import re as _re
    from starlette.routing import compile_path

    matchers = []
    for r in mounted_routes:
        rx, _, _ = compile_path(r["path"])
        matchers.append((rx, r))

    def match_url(url: str, method: str) -> list[dict]:
        hits = []
        for rx, r in matchers:
            if rx.fullmatch(url) and (r["method"] == method or method == "ANY"):
                hits.append(r)
        if not hits and url.endswith("/"):
            # URL construida por concatenación en JS: `fetch("/api/entities/" + id)`.
            # No es un enlace roto: es un prefijo con el segmento variable fuera
            # del literal. Se resuelve probando un segmento comodín.
            for rx, r in matchers:
                if rx.fullmatch(url + "X") and (r["method"] == method or method == "ANY"):
                    hits.append(r)
        return hits

    # --- linked: BFS desde la navegación global -------------------------
    tpl_links: dict[str, list[dict]] = {}
    for l in links:
        tpl_links.setdefault(l["from"], []).append(l)

    def links_of_template(tpl: str, seen: set[str] | None = None) -> list[dict]:
        seen = seen or set()
        if tpl in seen:
            return []
        seen.add(tpl)
        out = list(tpl_links.get(tpl, []))
        for js in scripts.get(tpl, []):
            out.extend(tpl_links.get(js, []))
        for parent in inherit.get(tpl, []):
            out.extend(links_of_template(parent, seen))
        return out

    nav_contrato, nav_error = chassis_nav_links(app)
    nav_links = links_of_template("base.html") + nav_contrato
    for l in nav_contrato:
        tpl_links.setdefault("base.html", []).append(l)
    reachable: set[str] = set()
    linked_by: dict[str, list[str]] = {}
    frontier = [(l, "base.html") for l in nav_links]
    frontier.append(({"url": "/", "method": "GET", "state": "ok"}, "raiz"))
    visited_tpl: set[str] = set()
    while frontier:
        link, origin = frontier.pop()
        if link.get("state") != "ok" or not link.get("url"):
            continue
        for r in match_url(link["url"], link["method"]) or match_url(link["url"], "ANY"):
            if r["key"] not in reachable:
                reachable.add(r["key"])
            linked_by.setdefault(r["key"], []).append(f"{origin}:{link.get('raw', link['url'])}")
            for tpl in handler_tpls.get(r["endpoint"], []):
                if tpl in visited_tpl:
                    continue
                visited_tpl.add(tpl)
                frontier.extend((l, tpl) for l in links_of_template(tpl))

    # --- enlaces rotos ---------------------------------------------------
    broken = []
    if nav_error:
        broken.append({"from": "app.chassis.NAV", "from_kind": "nav-contrato",
                       "raw": nav_error, "url": None, "state": "contrato-roto",
                       "method": "GET"})
    links = links + nav_contrato
    for l in links:
        if l["state"] != "ok" or not l["url"]:
            continue
        if l["url"].startswith("/static/"):
            continue
        if not match_url(l["url"], "ANY"):
            broken.append(l)

    # --- tested ----------------------------------------------------------
    tested: dict[str, dict] = {}
    tested_meta: dict[str, Any] = {}
    if tested_path and tested_path.exists():
        raw = json.loads(tested_path.read_text(encoding="utf-8"))
        tested = raw.get("exercised", {})
        tested_meta = {k: v for k, v in raw.items() if k != "exercised"}

    # --- authorized ------------------------------------------------------
    probe = {} if skip_probe else run_probe(repo)
    probe_error = probe.pop("__error__", None)

    # --- consumed --------------------------------------------------------
    consumers = _collect_consumers(repo, mounted_routes, links, match_url, tested)

    defined_keys = {d["key"] for d in defined}
    mounted_keys = {r["key"] for r in mounted_routes}

    rows = []
    for r in sorted(mounted_routes, key=lambda x: (x["path"], x["method"])):
        k = r["key"]
        static_guard = bool(r["deps"] or r["body_guards"])
        verdict, detail = classify_probe(k, probe.get(k), r["path"],
                                         static_guard=static_guard)
        roles = role_verdict(k, probe.get(k), has_params="{" in r["path"],
                             path=r["path"])
        captor = capturada_por(r["path"], probe.get(k))
        t = tested.get(k)
        rows.append({
            "key": k, "method": r["method"], "path": r["path"], "kind": r["kind"],
            "endpoint": r["endpoint"], "module": r.get("module", ""),
            "defined": k in defined_keys or bool(r["source"]),
            "mounted": True,
            "linked": k in reachable,
            "linked_by": sorted(set(linked_by.get(k, [])))[:6],
            "tested": bool(t), "tested_hits": (t or {}).get("count", 0),
            "tested_statuses": (t or {}).get("statuses", []),
            "authz_static": static_guard,
            "authz_deps": r["deps"], "authz_body_guards": r["body_guards"],
            "scoping_deps": r["scoping_deps"],
            "authz_probe": verdict, "authz_probe_detail": detail,
            "csrf_enviado": bool((probe.get(k) or {}).get("csrf_enviado")),
            "status_anonimo": (probe.get(k) or {}).get("status"),
            "capturada_por": captor,
            "rol_minimo_observado": roles["rol_minimo"],
            "status_por_rol": roles["por_rol"],
            "guardian_pasivo_no_aplicado": r.get("guardian_pasivo_no_aplicado", False),
            "consumed": bool(consumers.get(k)), "consumers": consumers.get(k, []),
            "source": r["source"].replace(str(repo) + "/", ""),
        })

    dead = [d for d in defined if d["key"] not in mounted_keys]

    findings = {
        "rutas_muertas": dead,
        "enlaces_rotos": broken,
        "rutas_sin_auth": [r for r in rows if r["authz_probe"] == "SIN-AUTH"],
        "rutas_sin_guardian_estatico": [
            r for r in rows if not r["authz_static"] and r["key"] not in PUBLIC_BY_DESIGN
        ],
        "rutas_no_probadas": [r for r in rows if not r["tested"]],
        "rutas_capturadas": [r for r in rows if r["capturada_por"]],
        "guardian_declarado_pero_no_aplicado": [
            r for r in rows if r["guardian_pasivo_no_aplicado"]
        ],
        "rutas_servidas_a_viewer": [
            r for r in rows if r["rol_minimo_observado"] == "viewer"
            and r["key"] not in PUBLIC_BY_DESIGN
        ],
        "rutas_huerfanas": [r for r in rows if not r["linked"]],
        "sondas_inconcluyentes": [r for r in rows if r["authz_probe"] == "inconcluyente"],
        # La sonda no fue servida, pero el «no» no lo dijo el control de acceso.
        "rutas_denegacion_404_ambigua": [
            r for r in rows if r["authz_probe"] == "denegada-404-ambigua"
        ],
        "rutas_denegacion_no_atribuible": [
            r for r in rows if r["authz_probe"] == "denegacion-no-atribuible"
        ],
        # Contradicción interna entre las dos señales del barrido: la fila dice
        # a la vez «deniega al anónimo» y «servida a un rol». Es el patrón de la
        # ruta abierta que sube el contador de rutas que deniegan. Dispara por
        # dos motivos independientes (ver `_motivo_contradiccion`), uno estático
        # y otro puramente dinámico, porque el estático tiene falsos negativos
        # demostrados: `revoke_partida_access` casa con el patrón de nombres de
        # guardián sin serlo, y bendecía el 404 de una ruta ya sin guardián.
        "contradiccion_deniega_y_sirve": [
            dict(r, motivo_contradiccion=_motivo_contradiccion(r))
            for r in rows if _motivo_contradiccion(r)
        ],
    }
    denegadas = [r for r in rows if r["authz_probe"] == "denegada"]
    return {
        "repo": str(repo),
        "head": head_label or _head(repo),
        "counts": {
            "definidas": len(defined), "montadas": len(rows),
            "enlazadas": sum(r["linked"] for r in rows),
            "probadas": sum(r["tested"] for r in rows),
            "autorizadas": len(denegadas),
            "consumidas": sum(r["consumed"] for r in rows),
        },
        # Desglose del titular: de qué se compone el «deniegan», y qué queda
        # fuera por no ser atribuible al control de acceso.
        "desglose_denegaciones": {
            "denegadas_atribuibles": len(denegadas),
            "de_ellas_con_guardian_estatico": sum(r["authz_static"] for r in denegadas),
            "de_ellas_metodos_con_cuerpo": sum(
                r["method"] not in ("GET", "HEAD") for r in denegadas),
            "de_ellas_con_csrf_valido_emitido": sum(r["csrf_enviado"] for r in denegadas),
            "denegacion_404_ambigua": len(findings["rutas_denegacion_404_ambigua"]),
            "denegacion_no_atribuible": len(findings["rutas_denegacion_no_atribuible"]),
        },
        "tested_source": str(tested_path) if tested_path else None,
        "tested_meta": tested_meta,
        "probe_error": probe_error,
        "routes": rows,
        "findings": findings,
    }


def _collect_consumers(repo, mounted_routes, links, match_url, tested) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for l in links:
        if l["state"] != "ok" or not l["url"]:
            continue
        for r in match_url(l["url"], "ANY"):
            out.setdefault(r["key"], []).append(f"{l['from_kind']}:{l['from']}")
    for key, rec in tested.items():
        out.setdefault(key, []).append(f"tests:{rec.get('count', 0)} peticiones")
    return {k: sorted(set(v)) for k, v in out.items()}


def _head(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------
# 6) informe markdown
# --------------------------------------------------------------------------

def _desglose_titular(m: dict) -> str:
    """Recorta el titular: de qué se compone el «deniegan», y qué queda fuera.

    El número suelto invita a leerlo como «57 rutas autorizan bien». No es eso:
    hay que decir cuántas de esas denegaciones son de métodos con cuerpo (donde
    el CSRF podría hablar antes que el guardián, y por eso la sonda emite un
    token válido) y cuántas rutas quedaron FUERA del recuento por no ser su
    denegación atribuible al control de acceso.
    """
    d = m.get("desglose_denegaciones") or {}
    if not d:
        return ""
    partes = [
        f"de ellas {d.get('de_ellas_con_guardian_estatico', 0)} con guardián estático",
        f"{d.get('de_ellas_metodos_con_cuerpo', 0)} de métodos con cuerpo "
        f"(sondeados con token CSRF válido: {d.get('de_ellas_con_csrf_valido_emitido', 0)})",
    ]
    fuera = []
    if d.get("denegacion_404_ambigua"):
        fuera.append(f"{d['denegacion_404_ambigua']} con 404 ambiguo (sin guardián)")
    if d.get("denegacion_no_atribuible"):
        fuera.append(f"{d['denegacion_no_atribuible']} con 403 no atribuible")
    cola = f"; FUERA del recuento: {', '.join(fuera)}" if fuera else "; 0 fuera del recuento"
    return " — " + "; ".join(partes) + cola


def render_md(m: dict) -> str:
    c = m["counts"]
    L = [f"# Mapa de rutas v2 — {m['head'][:12]}", "",
         f"- definidas (AST): **{c['definidas']}**",
         f"- montadas en `app.main.app`: **{c['montadas']}**",
         f"- enlazadas desde navegación: **{c['enlazadas']}**",
         f"- probadas de verdad (sonda pytest): **{c['probadas']}**",
         f"- deniegan petición anónima con auth ON: **{c['autorizadas']}**"
         + _desglose_titular(m),
         f"- consumidas: **{c['consumidas']}**", "",
         "| ruta | def | mnt | link | test | authz anónimo | rol mínimo medido | guardián estático | consum |",
         "|---|:-:|:-:|:-:|:-:|---|---|---|:-:|"]
    tick = lambda b: "si" if b else "NO"  # noqa: E731
    for r in m["routes"]:
        guard = ", ".join([d.split(".")[-1] for d in r["authz_deps"]] + r["authz_body_guards"]) or "—"
        L.append(f"| `{r['key']}` | {tick(r['defined'])} | si | {tick(r['linked'])} | "
                 f"{tick(r['tested'])} ({r['tested_hits']}) | {r['authz_probe']} | "
                 f"{r['rol_minimo_observado']} | {guard} | {tick(r['consumed'])} |")
    f = m["findings"]
    L += ["", "## Hallazgos", ""]
    L.append(f"### Rutas MUERTAS (definidas y no montadas): {len(f['rutas_muertas'])}")
    for d in f["rutas_muertas"]:
        L.append(f"- `{d['key']}` — {d['file']}:{d['line']} ({d['func']})")
    L.append("")
    L.append(f"### Enlaces ROTOS: {len(f['enlaces_rotos'])}")
    for b in f["enlaces_rotos"]:
        L.append(f"- `{b['raw']}` en {b['from']}")
    L.append("")
    L.append(f"### Rutas SIN AUTH (2xx anónimo con auth ON): {len(f['rutas_sin_auth'])}")
    for r in f["rutas_sin_auth"]:
        L.append(f"- `{r['key']}` — {r['authz_probe_detail']}")
    L.append("")
    L.append(f"### Rutas NO PROBADAS: {len(f['rutas_no_probadas'])}")
    for r in f["rutas_no_probadas"]:
        L.append(f"- `{r['key']}`")
    L.append("")
    L.append(f"### Rutas HUÉRFANAS (no alcanzables desde navegación): {len(f['rutas_huerfanas'])}")
    for r in f["rutas_huerfanas"]:
        L.append(f"- `{r['key']}`")
    L.append("")
    L.append(f"### Rutas CAPTURADAS por otro patrón: {len(f['rutas_capturadas'])}")
    for r in f["rutas_capturadas"]:
        L.append(f"- `{r['key']}` — la sirve `{r['capturada_por']}`; su guardián "
                 f"nunca se ejecuta, su autorización NO es evaluable")
    L.append("")
    L.append("### Guardián declarado pero NO aplicado: "
             f"{len(f['guardian_declarado_pero_no_aplicado'])}")
    for r in f["guardian_declarado_pero_no_aplicado"]:
        L.append(f"- `{r['key']}` — {r['source']}")
    L.append("")
    L.append(f"### Rutas servidas a rol viewer: {len(f['rutas_servidas_a_viewer'])}")
    for r in f["rutas_servidas_a_viewer"]:
        L.append(f"- `{r['key']}` — {r['status_por_rol']}")
    L.append("")
    L.append(f"### Sondas inconcluyentes: {len(f['sondas_inconcluyentes'])}")
    for r in f["sondas_inconcluyentes"]:
        L.append(f"- `{r['key']}` — {r['authz_probe_detail']}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--tested", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--skip-probe", action="store_true")
    ap.add_argument("--head-label", default="",
                    help="etiqueta del árbol auditado cuando --repo no es un repo git")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    if a.probe_only:
        probe_main(repo, Path(a.out))
        return 0
    m = build_map(repo, Path(a.tested).resolve() if a.tested else None, a.skip_probe,
                  a.head_label)
    text = json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
    if a.md:
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text(render_md(m), encoding="utf-8")
    if not a.out and not a.md:
        print(text)
    else:
        print(json.dumps(m["counts"], indent=2))
        for name, items in m["findings"].items():
            print(f"{name}: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

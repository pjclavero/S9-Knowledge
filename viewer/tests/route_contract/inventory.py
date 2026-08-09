"""Introspección del visor real: rutas registradas, plantillas y enlaces.

Nada de esto está escrito a mano: se lee de la aplicación FastAPI que se monta
en producción y del árbol de plantillas. El mapa declarado
(`route_contract_map.json`) es lo único escrito a mano, y la puerta compara
ambos. Así el inventario no puede envejecer en silencio.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

VIEWER_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = VIEWER_ROOT / "app"
TEMPLATES_DIR = APP_DIR / "templates"


# ---------------------------------------------------------------------------
# Rutas registradas en la aplicación real
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RouteInfo:
    path: str
    methods: tuple[str, ...]
    endpoint: str  # "modulo.funcion"

    @property
    def key(self) -> str:
        return f"{','.join(self.methods)} {self.path}"


def _route_infos_from_router_route(route) -> RouteInfo:
    ep = getattr(route, "endpoint", None)
    name = f"{ep.__module__}.{ep.__name__}" if ep is not None else "-"
    methods = tuple(sorted(m for m in (getattr(route, "methods", None) or ()) if m != "HEAD"))
    return RouteInfo(path=route.path, methods=methods, endpoint=name)


def registered_routes(app=None) -> list[RouteInfo]:
    """Rutas HTTP efectivas de la app, incluidas las de routers montados.

    Se soportan las dos formas de FastAPI: rutas planas y `_IncludedRouter`
    (que expone los contextos efectivos de cada ruta incluida).
    """
    if app is None:  # pragma: no cover - import perezoso para uso como librería
        from app.main import app as _app

        app = _app

    out: list[RouteInfo] = []
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            for ctx in contexts():
                out.append(_route_infos_from_router_route(ctx))
            continue
        if hasattr(route, "endpoint") and hasattr(route, "path"):
            out.append(_route_infos_from_router_route(route))
    return sorted(set(out), key=lambda r: (r.path, r.methods))


def mounted_paths(app=None) -> list[str]:
    """Prefijos montados (p. ej. `/static`), que no son rutas HTTP."""
    if app is None:  # pragma: no cover
        from app.main import app as _app

        app = _app
    return [
        r.path
        for r in app.routes
        if not hasattr(r, "endpoint")
        and getattr(r, "effective_route_contexts", None) is None
        and hasattr(r, "path")
    ]


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------
def template_files() -> set[str]:
    return {
        p.relative_to(TEMPLATES_DIR).as_posix()
        for p in TEMPLATES_DIR.rglob("*.html")
    }


_TPL_IN_CODE = re.compile(r"""["']([A-Za-z0-9_./-]+\.html)["']""")
_TPL_IN_TEMPLATE = re.compile(
    r"""\{%-?\s*(?:extends|include|import|from)\s+["']([A-Za-z0-9_./-]+\.html)["']"""
)


def templates_referenced_by_code() -> dict[str, set[str]]:
    """{plantilla: {ficheros .py que la nombran}}."""
    refs: dict[str, set[str]] = {}
    for py in APP_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for name in _TPL_IN_CODE.findall(text):
            refs.setdefault(name, set()).add(py.relative_to(VIEWER_ROOT).as_posix())
    return refs


def templates_referenced_by_templates() -> dict[str, set[str]]:
    """{plantilla: {plantillas que la heredan/incluyen}}."""
    refs: dict[str, set[str]] = {}
    for tpl in TEMPLATES_DIR.rglob("*.html"):
        text = tpl.read_text(encoding="utf-8", errors="ignore")
        for name in _TPL_IN_TEMPLATE.findall(text):
            refs.setdefault(name, set()).add(tpl.relative_to(TEMPLATES_DIR).as_posix())
    return refs


def orphan_templates() -> set[str]:
    """Plantillas que nadie renderiza ni hereda: código muerto en la UI."""
    used = set(templates_referenced_by_code()) | set(templates_referenced_by_templates())
    return {t for t in template_files() if t not in used}


# ---------------------------------------------------------------------------
# Enlaces internos declarados en las plantillas
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Link:
    template: str
    attribute: str  # href | action
    raw: str
    probe: str  # ruta concreta comparable con el regex de la ruta

    @property
    def where(self) -> str:
        return f"{self.template}: {self.attribute}=\"{self.raw}\""


_LINK_ATTR = re.compile(r"""\b(href|action)\s*=\s*"([^"]*)\"""")
_JINJA_VAR = re.compile(r"\{\{.*?\}\}")
_JINJA_TAG = re.compile(r"\{%.*?%\}")
_PATH_RUN = re.compile("/[A-Za-z0-9_./\\x00\\-]*")

_VAR = "\x00"


def _candidates(value: str) -> list[str]:
    """Rutas literales candidatas dentro del valor de un href/action."""
    value = value.split("?")[0].split("#")[0].strip()
    value = _JINJA_VAR.sub(_VAR, value)
    if "{%" in value:
        # p. ej. action="{% if mode=='new' %}/a{% else %}/b/{{id}}{% endif %}"
        value = _JINJA_TAG.sub(" ", value)
        return [m for m in _PATH_RUN.findall(value)]
    if not value.startswith("/"):
        return []  # externo, ancla, relativo (?page=…) o generado del todo
    return [value]


def _probe(candidate: str) -> str:
    """Sustituye cada trozo variable por un segmento concreto."""
    probe = candidate.replace(_VAR, "x")
    return probe if probe.startswith("/") else ""


def template_links() -> list[Link]:
    links: list[Link] = []
    for tpl in sorted(TEMPLATES_DIR.rglob("*.html")):
        name = tpl.relative_to(TEMPLATES_DIR).as_posix()
        text = tpl.read_text(encoding="utf-8", errors="ignore")
        for attr, value in _LINK_ATTR.findall(text):
            for cand in _candidates(value):
                probe = _probe(cand)
                if not probe:
                    continue
                links.append(Link(template=name, attribute=attr, raw=value.strip(), probe=probe))
    return links


# ---------------------------------------------------------------------------
# Resolución de enlaces contra las rutas reales
# ---------------------------------------------------------------------------
def _route_regex(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", path)
    out = []
    for part in parts:
        out.append("[^/]+" if part.startswith("{") else re.escape(part))
    return re.compile("^" + "".join(out) + "$")


def link_resolves(probe: str, routes: Iterable[RouteInfo], mounts: Iterable[str]) -> bool:
    for mount in mounts:
        if probe == mount or probe.startswith(mount.rstrip("/") + "/"):
            return True
    for route in routes:
        if _route_regex(route.path).match(probe):
            return True
    return False


STATIC_JS_DIR = APP_DIR / "static" / "js"

# Rutas absolutas escritas en el JS del visor: `fetch("/api/…")`,
# `href="/entity/${id}"`. La interpolación `${…}` se trata como un segmento.
_JS_INTERP = re.compile(r"\$\{[^}]*\}")


def js_links() -> list[Link]:
    links: list[Link] = []
    if not STATIC_JS_DIR.exists():
        return links
    for js in sorted(STATIC_JS_DIR.glob("*.js")):  # vendor/ queda fuera a propósito
        name = f"static/js/{js.name}"
        text = js.read_text(encoding="utf-8", errors="ignore")
        for raw in re.findall(r"""["'`](/[^"'`\s]*)["'`]""", text):
            candidate = raw.split("?")[0].split("#")[0]
            probe = _JS_INTERP.sub("x", candidate)
            if "{" in probe or "}" in probe or not probe.startswith("/"):
                continue
            links.append(Link(template=name, attribute="js", raw=raw, probe=probe))
    return links


def all_links() -> list[Link]:
    return template_links() + js_links()


def broken_links(app=None) -> list[Link]:
    routes = registered_routes(app)
    mounts = mounted_paths(app)
    return [ln for ln in all_links() if not link_resolves(ln.probe, routes, mounts)]


# ---------------------------------------------------------------------------
# Cobertura declarada
# ---------------------------------------------------------------------------
TEST_ROOTS = (VIEWER_ROOT / "tests",)


def test_files_mentioning(path: str) -> set[str]:
    """Ficheros de prueba que nombran literalmente la ruta.

    Heurística deliberadamente conservadora: sirve para VERIFICAR una
    declaración escrita a mano, no para inventarla.
    """
    # Un parámetro puede aparecer en la prueba como literal o como
    # interpolación de f-string (`/admin/partidas/{access.id}/revoke`).
    # La raíz sólo cuenta entrecomillada: si no, "/" casa con todo.
    parts = ['"/"'] if path == "/" else re.split(r"(\{[^}]+\})", path)
    pattern = "".join(
        r"(?:\{[^}]*\}|[^\"'/\s]+)" if p.startswith("{") else re.escape(p)
        for p in parts
    )
    rx = re.compile(pattern)
    found: set[str] = set()
    for root in TEST_ROOTS:
        for py in root.rglob("test_*.py"):
            if py.parent.name == "route_contract":
                continue
            text = py.read_text(encoding="utf-8", errors="ignore")
            if rx.search(text):
                found.add(py.relative_to(VIEWER_ROOT).as_posix())
    return found


__all__ = [
    "RouteInfo",
    "Link",
    "registered_routes",
    "mounted_paths",
    "template_files",
    "templates_referenced_by_code",
    "templates_referenced_by_templates",
    "orphan_templates",
    "template_links",
    "broken_links",
    "link_resolves",
    "test_files_mentioning",
]

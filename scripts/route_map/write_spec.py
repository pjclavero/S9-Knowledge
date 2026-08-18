#!/usr/bin/env python3
"""Especificación EJECUTABLE de los endpoints con capacidad de ESCRITURA.

Por qué existe
--------------
El censo de rutas (`route_map.py`) y su puerta (`gate.py`) comprobaban el
método montado contra `router.routes[...].methods`, es decir, **contra el mismo
decorador** que pretendían vigilar. Un cambio de método es invisible por
construcción para esa comparación: sobre el árbol congelado `aaf9695` se cambió
`@router.post("/users/{user_id}/unlock")` por `@router.get(...)` —una ruta de
ESCRITURA— y ningún instrumento se puso rojo; añadir un alias `GET` a esa misma
ruta tampoco.

Este módulo NO deriva nada del decorador. Construye la especificación desde
tres fuentes independientes, ninguna mantenida a mano:

  F1  **La firma y el cuerpo del manejador** (AST + `inspect.signature`).
      Un manejador que declara parámetros `Form(...)`/`Body(...)`/`File(...)`/
      `UploadFile`, o que lee el cuerpo de la petición (`request.form()`,
      `request.json()`, `request.body()`), o que VERIFICA un token CSRF, o que
      llama a un mutador de estado durable, tiene **capacidad de escritura**.
      Ninguna de esas señales cambia si alguien cambia `post` por `get`: es
      exactamente lo que las hace útiles como referencia.

  F2  **Las plantillas y el JS que la propia app sirve** (`viewer/app/templates`,
      `viewer/app/static`). Un `<form method="post" action="/x">` es un contrato
      de cliente: declara método Y ruta, y lo declara en un fichero que NO es el
      decorador. Si el decorador se mueve a `get` o a `put`, el formulario deja
      de poder enviarse — y esta especificación lo ejecuta contra la app real.

  F3  **La app REAL en ejecución** (`fastapi.testclient`). Toda afirmación
      termina en una petición HTTP contra `app.main.app`: un `GET` a una ruta de
      escritura tiene que dar **405**. 404 (la ruta no existe) o cualquier 2xx/
      3xx/401/403 (la ruta responde a GET) son ROJO, y por motivos distintos.

Ninguna de las tres es una lista de endpoints. Un endpoint de escritura NUEVO
queda cubierto **solo**: en cuanto tiene cuerpo, CSRF o mutación, F1 lo clasifica
y F3 lo sondea. Y si un endpoint no se puede clasificar (no hay fuente que
inspeccionar), la especificación **se pone roja**: `endpoint-sin-fuente`.

Hallazgos (todos DUROS)
-----------------------
  metodo-seguro-en-endpoint-de-escritura   un endpoint con capacidad de
        escritura está montado con GET/HEAD (cambio de método O alias).
  escritura-servida-por-get                el 405 no aparece: la app REAL sirve
        GET en la URL de un endpoint de escritura (instrumento independiente
        del enumerador; corrobora el anterior por ejecución).
  escritura-sin-metodo                     el endpoint no tiene ningún método
        montado que pueda escribir.
  contrato-de-cliente-roto                 un formulario/fetch que la app sirve
        declara `METODO URL` y la app real responde 405 (método) o 404 (ruta).
  endpoint-sin-fuente                      no se pudo clasificar un endpoint.
  espec-vacia                              cero endpoints de escritura o cero
        contratos de cliente: una espec que no afirma nada no protege nada.
  espec-no-inspecciono-la-app-real         no hubo sondeo HTTP.

Uso:
    python3 scripts/route_map/write_spec.py --repo . --out artefacto.json
    rc=0 conforme · rc=1 hallazgos · rc=3 la espec no pudo ejecutarse
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

METODOS_SEGUROS = {"GET", "HEAD"}
METODOS_DE_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}

#: Nombres de parámetro-declarador que SÓLO tienen sentido con cuerpo de
#: petición. No es una lista de endpoints: es el vocabulario de FastAPI.
DECLARADORES_DE_CUERPO = {"Form", "Body", "File"}
ANOTACIONES_DE_CUERPO = ("UploadFile",)

#: Lectura explícita del cuerpo desde el objeto Request.
LECTORES_DE_CUERPO = {"form", "json", "body", "stream"}

#: VERIFICACIÓN de CSRF (no emisión). Emitir un token es propio de un GET que
#: pinta un formulario; verificarlo sólo tiene sentido atendiendo una escritura.
RE_CSRF_VERIFICA = re.compile(r"(check|valid|verif).*csrf|csrf.*(check|valid|verif)",
                              re.IGNORECASE)

#: Mutadores de ESTADO DURABLE. El prefijo de módulo se resuelve por los
#: `import` del módulo del manejador, no por el nombre suelto.
RE_MUTADOR = re.compile(
    r"^(create|update|delete|insert|save|revoke|grant|unlock|reset|remove|purge|"
    r"rotate|write|store|upsert|commit|set)(_|$)", re.IGNORECASE)
MODULOS_DE_ESTADO_DURABLE = ("app.auth", "app.services", "app.providers",
                             "app.policies", "app.authz")
RE_SQL_ESCRITURA = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|MERGE)\b",
                              re.IGNORECASE)


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------
def bootstrap(repo: Path) -> None:
    import secrets
    import tempfile

    viewer = repo / "viewer"
    de_app = repo / "data-engine" / "app"
    for p in (str(de_app), str(viewer)):
        if p not in sys.path:
            sys.path.insert(0, p)
    tmp = Path(tempfile.mkdtemp(prefix="s9k-writespec-"))
    os.environ.setdefault("S9K_AUTH_ENABLED", "true")
    os.environ.setdefault("S9K_AUTH_DB_PATH", str(tmp / "auth.db"))
    os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
    os.environ.setdefault("S9K_DEFAULT_WORKSPACE", "leyenda")
    os.environ.setdefault("S9K_SAMPLE_GRAPH_PATH",
                          str(viewer / "examples" / "sample_graph.json"))
    os.environ.setdefault("S9K_CSRF_SECRET", secrets.token_urlsafe(48))
    os.environ.setdefault("S9K_SESSION_SECURE", "false")


def cargar_app(repo: Path):
    bootstrap(repo)
    import importlib

    app = importlib.import_module("app.main").app
    # El visor NO crea la auth DB (fail-closed de `enforce_auth_security`): se
    # provisiona una base VACÍA y efímera, sin usuarios, igual que la sonda del
    # censo. Sin ella el arranque aborta y la espec no llegaría a afirmar nada.
    db = os.environ.get("S9K_AUTH_DB_PATH", "")
    if db:
        from app.auth import db as auth_db

        auth_db.ensure_migrated(Path(db))
    return app


# --------------------------------------------------------------------------
# F1 — clasificación por firma y cuerpo del manejador
# --------------------------------------------------------------------------
def _importaciones_del_modulo(mod_name: str) -> dict[str, str]:
    """`{alias local -> módulo de origen}` leyendo los `import` del módulo.

    Sirve para saber a QUÉ módulo pertenece `storage.save_report(...)` sin
    ejecutarlo: `from app.health import storage` ⇒ `storage -> app.health.storage`.
    """
    mod = sys.modules.get(mod_name)
    fichero = getattr(mod, "__file__", None)
    if not fichero or not Path(fichero).exists():
        return {}
    try:
        arbol = ast.parse(Path(fichero).read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return {}
    out: dict[str, str] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                out[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            for a in nodo.names:
                out[a.asname or a.name] = f"{nodo.module}.{a.name}"
    return out


def _arbol_del_manejador(fn) -> ast.AST | None:
    try:
        return ast.parse(textwrap.dedent(inspect.getsource(inspect.unwrap(fn))))
    except (OSError, TypeError, SyntaxError):
        return None


def _es_modelo_de_cuerpo(anotacion) -> bool:
    try:
        from pydantic import BaseModel
    except ImportError:  # pragma: no cover - pydantic es dependencia de FastAPI
        return False
    return isinstance(anotacion, type) and issubclass(anotacion, BaseModel)


def evidencias_de_escritura(fn) -> tuple[list[str], bool] | tuple[None, bool]:
    """Evidencia INDEPENDIENTE del decorador. `(evidencias, clasificado)`."""
    arbol = _arbol_del_manejador(fn)
    if arbol is None or not arbol.body or not isinstance(
            arbol.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None, False
    fd = arbol.body[0]
    ev: set[str] = set()

    # -- firma: parámetros que sólo existen si hay cuerpo de petición
    for d in list(fd.args.defaults) + [d for d in fd.args.kw_defaults if d is not None]:
        if isinstance(d, ast.Call):
            n = d.func.attr if isinstance(d.func, ast.Attribute) else getattr(d.func, "id", "")
            if n in DECLARADORES_DE_CUERPO:
                ev.add(f"parametro-de-cuerpo:{n}")
    for a in list(fd.args.args) + list(fd.args.kwonlyargs):
        if a.annotation is not None:
            txt = ast.unparse(a.annotation)
            if any(t in txt for t in ANOTACIONES_DE_CUERPO):
                ev.add("parametro-de-cuerpo:UploadFile")
    try:
        for nombre, par in inspect.signature(inspect.unwrap(fn)).parameters.items():
            if _es_modelo_de_cuerpo(par.annotation):
                ev.add(f"modelo-de-cuerpo:{nombre}")
    except (TypeError, ValueError):
        pass

    importaciones = _importaciones_del_modulo(getattr(fn, "__module__", "") or "")

    for nodo in ast.walk(fd):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        nombre = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        base = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
        if base == "request" and nombre in LECTORES_DE_CUERPO:
            ev.add(f"lee-el-cuerpo:request.{nombre}")
        if RE_CSRF_VERIFICA.search(nombre):
            ev.add(f"verifica-csrf:{nombre}")
        if nombre == "execute":
            for arg in nodo.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and RE_SQL_ESCRITURA.search(arg.value):
                    ev.add("sql-de-escritura")
        if RE_MUTADOR.match(nombre):
            origen = importaciones.get(base.split(".")[0], "") if base else \
                importaciones.get(nombre, "")
            if origen.startswith(MODULOS_DE_ESTADO_DURABLE):
                ev.add(f"mutador-de-estado-durable:{origen}.{nombre}"
                       if base else f"mutador-de-estado-durable:{origen}")
    return sorted(ev), True


# --------------------------------------------------------------------------
# Enumeración de lo MONTADO (se usa como sujeto, nunca como referencia)
# --------------------------------------------------------------------------
def _modulo_censo():
    """El censo, se ejecute este fichero como script o como módulo del paquete."""
    import importlib

    for nombre in ("route_map.route_map", "route_map"):
        try:
            mod = importlib.import_module(nombre)
        except ImportError:
            continue
        if hasattr(mod, "iter_effective_routes"):
            return mod
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    return importlib.import_module("route_map")


def rutas_montadas(app) -> list[dict[str, Any]]:
    censo = _modulo_censo()
    KIND_ESTATICO, KIND_OPACO = censo.KIND_ESTATICO, censo.KIND_OPACO
    iter_effective_routes = censo.iter_effective_routes

    filas = []
    for path, metodos, _dep, endpoint, handler_route, kind, motivo in iter_effective_routes(app):
        if kind in (KIND_ESTATICO, KIND_OPACO) or endpoint is None:
            continue
        filas.append({
            "path": path,
            "metodos": sorted(metodos or []),
            "endpoint": f"{getattr(endpoint, '__module__', '?')}."
                        f"{getattr(endpoint, '__qualname__', '?')}",
            "_fn": endpoint,
            "_route": handler_route,
            "kind": kind,
            "motivo": motivo,
        })
    return filas


# --------------------------------------------------------------------------
# F3 — ejecución contra la app real
# --------------------------------------------------------------------------
def _url_concreta(path: str) -> str:
    return re.sub(r"\{([^}]+)\}", "1", path)


def clave_endpoint(fn) -> str:
    return f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', '?')}"


def _instalar_resolutor(filas: list[dict[str, Any]]) -> list[str]:
    """Instrumenta cada objeto `Route` para saber QUÉ manejador atendió.

    Sin esto no se puede distinguir «la app sirve GET en esta URL porque hay
    OTRO endpoint de lectura montado en el mismo path» (legítimo: `GET /login`
    pinta el formulario que `POST /login` procesa) de «la app sirve GET porque
    el endpoint de ESCRITURA responde a GET» (el defecto que este carril
    persigue). La atribución se hace por EJECUCIÓN —quién atendió la petición—,
    no leyendo otra vez el decorador.
    """
    registro: list[str] = []
    instalados: set[int] = set()
    for fila in filas:
        route = fila.get("_route")
        handle = getattr(route, "handle", None)
        if route is None or handle is None or id(route) in instalados:
            continue
        instalados.add(id(route))
        etiqueta = clave_endpoint(getattr(route, "endpoint", None) or fila["_fn"])

        async def _handle(scope, receive, send, _orig=handle, _et=etiqueta):
            registro.append(_et)
            await _orig(scope, receive, send)

        route.handle = _handle
    return registro


def sondear(app, urls: list[tuple[str, str]], registro: list[str]) -> dict[str, dict]:
    """`{"METODO URL": {estado, atendido_por}}` ejecutando contra la app REAL."""
    from fastapi.testclient import TestClient

    out: dict[str, dict] = {}
    with TestClient(app, follow_redirects=False) as client:
        for metodo, url in urls:
            registro.clear()
            try:
                estado = client.request(metodo, url).status_code
            except Exception as exc:  # una excepción NO es un 405
                out[f"{metodo} {url}"] = {"estado": -1, "excepcion": repr(exc)[:200],
                                          "atendido_por": None}
                continue
            out[f"{metodo} {url}"] = {
                "estado": estado,
                "atendido_por": registro[-1] if registro else None,
            }
    return out


# --------------------------------------------------------------------------
# F2 — contrato de cliente: plantillas y JS que la app sirve
# --------------------------------------------------------------------------
RE_FORM = re.compile(r"<form\b([^>]*)>", re.IGNORECASE | re.DOTALL)
#: Atributo HTML con comillas EQUILIBRADAS. Una versión con `["']([^"']*)["']`
#: perdía en silencio el formulario cuyo `action` lleva Jinja con comillas
#: simples dentro ("{% if mode == 'new' %}..."), es decir, justo los dos
#: endpoints de escritura de administración. Un contrato que se pierde en
#: silencio es un endpoint sin vigilar.
RE_ATTR = re.compile(r"""(\w[\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
RE_FETCH = re.compile(r"""fetch\(\s*["'`]([^"'`]+)["'`]\s*,\s*\{(.{0,400}?)\}""",
                      re.DOTALL)
RE_METODO_JS = re.compile(r"""method\s*:\s*["'`](\w+)["'`]""")
RE_IF_JINJA = re.compile(r"\{%\s*if\b.*?%\}(.*?)(?:\{%\s*else\s*%\}(.*?))?\{%\s*endif\s*%\}",
                         re.DOTALL)


def _expandir_jinja(valor: str, app) -> list[str]:
    """Convierte un `action` de plantilla en URLs concretas.

    - `{% if %}A{% else %}B{% endif %}` se expande a las DOS ramas: un contrato
      con dos destinos declara dos contratos, no medio.
    - `{{ url_for('nombre') }}` se resuelve contra el enrutador real.
    - cualquier otra `{{ ... }}` es un identificador: se concreta con `1`.
    """
    variantes = [valor]
    while any("{%" in v for v in variantes):
        nuevas = []
        for v in variantes:
            m = RE_IF_JINJA.search(v)
            if not m:
                nuevas.append(v)
                continue
            for rama in (m.group(1) or "", m.group(2) or ""):
                nuevas.append(v[:m.start()] + rama + v[m.end():])
        if nuevas == variantes:
            break
        variantes = nuevas

    out = []
    for v in variantes:
        def _sub(m):
            expr = m.group(1).strip()
            uf = re.match(r"url_for\(\s*['\"]([^'\"]+)['\"]\s*\)", expr)
            if uf:
                try:
                    return str(app.url_path_for(uf.group(1)))
                except Exception:
                    return "/__nombre-no-resuelve__"
            return "1"
        v = re.sub(r"\{\{(.*?)\}\}", _sub, v).strip()
        if v.startswith("/"):
            out.append(v.split("?")[0])
    return out


def contratos_de_cliente(repo: Path, app) -> list[dict[str, str]]:
    fuentes = list((repo / "viewer" / "app" / "templates").rglob("*.html"))
    fuentes += list((repo / "viewer" / "app" / "static").rglob("*.js"))
    contratos: list[dict[str, str]] = []
    for f in fuentes:
        try:
            texto = f.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(f.relative_to(repo))
        for attrs in RE_FORM.findall(texto):
            d = {k.lower(): (v1 or v2) for k, v1, v2 in RE_ATTR.findall(attrs)}
            accion = d.get("action")
            if not accion:
                continue
            metodo = (d.get("method") or "GET").upper()
            for url in _expandir_jinja(accion, app):
                contratos.append({"metodo": metodo, "url": url, "fuente": rel})
        for url, cuerpo in RE_FETCH.findall(texto):
            m = RE_METODO_JS.search(cuerpo)
            for u in _expandir_jinja(url, app):
                contratos.append({"metodo": (m.group(1) if m else "GET").upper(),
                                  "url": u, "fuente": rel})
    # deduplicado estable
    vistos, out = set(), []
    for c in contratos:
        k = (c["metodo"], c["url"])
        if k not in vistos:
            vistos.add(k)
            out.append(c)
    return out


# --------------------------------------------------------------------------
# La especificación
# --------------------------------------------------------------------------
def construir(repo: Path) -> dict[str, Any]:
    app = cargar_app(repo)
    filas = rutas_montadas(app)
    registro = _instalar_resolutor(filas)

    escritura: list[dict[str, Any]] = []
    lectura: list[dict[str, Any]] = []
    hallazgos: dict[str, list] = {}

    def anota(clave, dato):
        hallazgos.setdefault(clave, []).append(dato)

    for fila in filas:
        ev, clasificado = evidencias_de_escritura(fila.pop("_fn"))
        fila.pop("_route", None)
        if not clasificado:
            anota("endpoint-sin-fuente",
                  {"path": fila["path"], "endpoint": fila["endpoint"]})
            continue
        fila["evidencias"] = ev
        (escritura if ev else lectura).append(fila)

    #: Endpoints con capacidad de escritura, por su identidad de manejador. La
    #: atribución del sondeo se hace contra ESTE conjunto, no contra el path.
    claves_de_escritura = {f["endpoint"] for f in escritura}
    contratos = contratos_de_cliente(repo, app)

    # ---- sondeo HTTP (F3): un GET a cada ruta de escritura + cada contrato
    urls = [("GET", _url_concreta(f["path"])) for f in escritura]
    urls += [(c["metodo"], c["url"]) for c in contratos]
    sondas = sondear(app, urls, registro)

    # ---- C1 (enumeración): ningún endpoint de escritura montado con GET/HEAD
    for f in escritura:
        seguros = sorted(set(f["metodos"]) & METODOS_SEGUROS)
        if seguros:
            anota("metodo-seguro-en-endpoint-de-escritura", {
                "path": f["path"], "endpoint": f["endpoint"],
                "metodos_montados": f["metodos"], "metodos_seguros": seguros,
                "evidencias": f["evidencias"],
            })
        if not (set(f["metodos"]) & METODOS_DE_ESCRITURA):
            anota("escritura-sin-metodo", {
                "path": f["path"], "endpoint": f["endpoint"],
                "metodos_montados": f["metodos"], "evidencias": f["evidencias"],
            })

    # ---- C2 (ejecución): un GET a la URL de una escritura no puede acabar
    #      ATENDIDO por el manejador de escritura. Que la app sirva GET ahí es
    #      legítimo si lo atiende OTRO manejador de lectura montado en el mismo
    #      path (`GET /login` pinta el formulario que `POST /login` procesa);
    #      lo que no es legítimo es que conteste el que escribe.
    for f in escritura:
        url = _url_concreta(f["path"])
        sonda = sondas.get(f"GET {url}") or {}
        atendido = sonda.get("atendido_por")
        if sonda.get("estado") == 405:
            continue
        if atendido in claves_de_escritura:
            anota("escritura-servida-por-get", {
                "path": f["path"], "url": url, "endpoint": f["endpoint"],
                "estado": sonda.get("estado"), "atendido_por": atendido,
                "evidencias": f["evidencias"],
            })

    # ---- C3: el contrato de cliente (plantillas/JS) se puede ejecutar
    for c in contratos:
        sonda = sondas.get(f"{c['metodo']} {c['url']}") or {}
        if sonda.get("estado") in (404, 405, -1, None):
            anota("contrato-de-cliente-roto", {**c, "estado": sonda.get("estado")})

    # ---- C4: suelos (una espec que no afirma nada no protege nada)
    escrituras_cliente = [c for c in contratos if c["metodo"] not in METODOS_SEGUROS]
    if not escritura:
        anota("espec-vacia", {"motivo": "cero endpoints de escritura clasificados"})
    if not escrituras_cliente:
        anota("espec-vacia", {"motivo": "cero contratos de cliente de escritura"})
    if not sondas or all(v.get("estado") == -1 for v in sondas.values()):
        anota("espec-no-inspecciono-la-app-real", {"sondas": len(sondas)})
    if not any(v.get("atendido_por") for v in sondas.values()):
        anota("espec-no-inspecciono-la-app-real",
              {"motivo": "ninguna peticion atraveso un manejador de la app"})

    return {
        "version": 1,
        "endpoints_de_escritura": sorted(
            ({k: v for k, v in f.items() if k != "kind"} for f in escritura),
            key=lambda f: f["path"]),
        "endpoints_de_lectura": sorted(f["path"] for f in lectura),
        "contratos_de_cliente": contratos,
        "sondas": sondas,
        "hallazgos": hallazgos,
        "resumen": {
            "montadas": len(filas),
            "de_escritura": len(escritura),
            "de_lectura": len(lectura),
            "contratos": len(contratos),
            "contratos_de_escritura": len(escrituras_cliente),
            "hallazgos": {k: len(v) for k, v in hallazgos.items()},
        },
    }


#: Todo hallazgo de esta especificación es DURO.
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        informe = construir(repo)
    except Exception as exc:  # la espec que no se ejecuta no da verde
        informe = {"version": 1, "hallazgos": {
            "espec-no-inspecciono-la-app-real": [{"excepcion": repr(exc)[:400]}]}}
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(informe, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
        print(json.dumps(informe["hallazgos"], indent=2, ensure_ascii=False))
        return 3
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(informe, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    print(json.dumps(informe["resumen"], indent=2, ensure_ascii=False))
    if informe["hallazgos"]:
        print("HALLAZGOS:", json.dumps(informe["hallazgos"], indent=2, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

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

Ninguna de las tres es una lista de endpoints. Pero **la cobertura de un
endpoint NUEVO no se promete aquí**, y decirlo importa: una versión anterior de
este docstring afirmaba que «queda cubierto solo», y un revisor la tumbó por
ejecución —F1 era muda ante `Annotated[str, Form()]`, el estilo que recomienda
hoy FastAPI—. Lo que se sostiene, exactamente:

  - **F1 depende de reconocer el estilo.** Entran `Form/Body/File/UploadFile` en
    parámetro con valor por defecto o dentro de `Annotated`, los alias de
    importación y los modelos de pydantic. **NO entran**: la anotación escrita
    como CADENA (`x: "Annotated[str, Form()]"`), el alias de tipo reutilizado
    (`Formulario = Annotated[str, Form()]`) ni `*args`/`**kwargs`.
  - **Lo que sí cubre a todos los montados con método de escritura es C1bis**
    (`metodo-de-escritura-sin-evidencia`), que no mira el estilo sino el
    enrutador. Un endpoint declarado de las formas mudas de arriba queda
    cubierto en cuanto va montado con `POST/PUT/PATCH/DELETE`; sobre un `GET`,
    no lo ve nadie.
  - **Sin fuente que inspeccionar, ROJO**: `endpoint-sin-fuente`.

Hallazgos (todos DUROS)
-----------------------
  metodo-seguro-en-endpoint-de-escritura   un endpoint con capacidad de
        escritura está montado con GET/HEAD (cambio de método O alias).
  escritura-servida-por-get                el 405 no aparece: la app REAL sirve
        GET en la URL de un endpoint de escritura (instrumento independiente
        del enumerador; corrobora el anterior por ejecución).
  escritura-sin-metodo                     el endpoint no tiene ningún método
        montado que pueda escribir.
  metodo-de-escritura-sin-evidencia        ruta montada con POST/PUT/PATCH/
        DELETE que la clasificación no supo explicar. Es la red que NO depende
        de que F1 acierte: vacía sobre esta base, y por eso cubre a todo
        endpoint de escritura montado.
  lectura-que-escribe                      método SEGURO que muta estado
        durable. Un `GET` que escribe es escritura, y es el motivo por el que la
        base de este carril sale ROJA (los dos `/admin/health`).
  contrato-de-cliente-roto                 un formulario/fetch que la app sirve
        declara `METODO URL` y la app real responde 405 (método) o 404 (ruta),
        o lo atiende un manejador que no es el de la ruta más específica.
  endpoint-sin-fuente                      no se pudo clasificar un endpoint.
  espec-vacia                              cero endpoints de escritura o cero
        contratos de cliente: una espec que no afirma nada no protege nada.
  espec-no-inspecciono-la-app-real         no hubo sondeo HTTP.

OJO CON EL CÓDIGO DE SALIDA: sobre esta base `rc=1` es lo ESPERADO (los dos
`lectura-que-escribe`), y **ningún check exigido comprueba `rc == 0`**: la suite
del visor afirma sobre las CLASES de hallazgo y sobre un registro fechado. Quien
exige `rc == 0` es el job `metodos-de-escritura`, que no es exigido.

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

#: NOTA HISTÓRICA, porque el defecto importa: aquí vivía
#: `MODULOS_DE_ESTADO_DURABLE`, una tupla de prefijos de módulo mantenida A
#: MANO. Era la lista documental que el operador prohibió, un nivel más arriba:
#: bastaba que la escritura viviera en un módulo no listado (`app.health`) para
#: que el endpoint saliera VERDE. La sustituye `_escribe_de_verdad()`, que lee
#: el código del invocable y busca primitivas de escritura.
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
    # HIGIENE, y costó una medición: `storage.default_report_path()` devuelve una
    # ruta RELATIVA (`viewer/state/health/last_report.json`), así que una sonda
    # que consiga escribir —por ejemplo contra un endpoint inyectado por la
    # calibración, que no tiene guardián— dejaría el fichero en el árbol REAL
    # aunque el árbol auditado sea una copia. Un instrumento que escribe en lo
    # que mide invalida su propia medida. Se apunta a un temporal.
    os.environ.setdefault("S9K_HEALTH_REPORT_PATH", str(tmp / "health_report.json"))


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


def _resolver(nombre_local: str, importaciones: dict[str, str]) -> str:
    """Nombre CANÓNICO de un símbolo local, resuelto por los `import` del módulo.

    `from fastapi import Form as _Form` ⇒ `_Form` -> `fastapi.Form`. Sin esto,
    un alias de importación deja muda a la clasificación, que es una de las
    formas de que la lista de endpoints de escritura salga corta EN SILENCIO.
    """
    if not nombre_local:
        return ""
    raiz, _, resto = nombre_local.partition(".")
    canon = importaciones.get(raiz, raiz)
    return f"{canon}.{resto}" if resto else canon


def _es_declarador_de_cuerpo(canon: str) -> str:
    """`Form`/`Body`/`File`/`UploadFile` venga como venga (alias incluido)."""
    hoja = canon.rsplit(".", 1)[-1]
    if hoja in DECLARADORES_DE_CUERPO or hoja in ANOTACIONES_DE_CUERPO:
        return hoja
    return ""


def _evidencia_en_anotacion(anot, importaciones: dict[str, str]) -> set[str]:
    """Recorre la ANOTACIÓN buscando declaradores de cuerpo.

    Aquí vivía el superviviente: `nombre: Annotated[str, Form()]` —la forma que
    la documentación de FastAPI recomienda hoy— no deja nada en
    `args.defaults`, así que la versión anterior no veía el cuerpo y el endpoint
    caía en `lectura` **sin ruido**. Se recorre el árbol entero de la anotación,
    no su texto, y cada nombre se resuelve por los `import` del módulo.
    """
    ev: set[str] = set()
    if anot is None:
        return ev
    for nodo in ast.walk(anot):
        if isinstance(nodo, ast.Call):
            objetivo = nodo.func
        elif isinstance(nodo, (ast.Name, ast.Attribute)):
            objetivo = nodo
        else:
            continue
        try:
            texto = ast.unparse(objetivo)
        except Exception:  # pragma: no cover
            continue
        hoja = _es_declarador_de_cuerpo(_resolver(texto, importaciones))
        if hoja:
            ev.add(f"parametro-de-cuerpo:{hoja}")
    return ev


def _es_modelo_de_cuerpo(canon: str) -> bool:
    """¿La anotación nombra un `BaseModel` de pydantic?

    Se resuelve el símbolo por `sys.modules` a partir del nombre canónico, NO
    por `inspect.signature`: los routers usan `from __future__ import
    annotations`, así que en ejecución las anotaciones son CADENAS y la
    comprobación por `issubclass` estaba muerta en toda la app.
    """
    try:
        from pydantic import BaseModel
    except ImportError:  # pragma: no cover
        return False
    if "." not in canon:
        return False
    modulo, _, atributo = canon.rpartition(".")
    obj = getattr(sys.modules.get(modulo), atributo, None)
    return isinstance(obj, type) and issubclass(obj, BaseModel)


#: Primitivas que dejan un cambio DURADERO fuera del proceso. Es vocabulario de
#: la biblioteca estándar y del driver, no una lista de módulos del proyecto.
RE_PRIMITIVA_DURABLE = re.compile(
    r"^(write_text|write_bytes|writelines|rmtree|mkdir|makedirs|touch|commit|"
    r"executemany)$")

#: Primitivas cuyo NOMBRE es ambiguo (`"x".replace(...)` no escribe nada): sólo
#: cuentan invocadas sobre `os`/`shutil`. Medido: sin esta distinción,
#: `serialize_edge` y `jobs_db_status` salían "mutadores" y 12 rutas de lectura
#: se declaraban escritura. Un rojo por el motivo equivocado es peor que un verde.
RE_PRIMITIVA_AMBIGUA = re.compile(r"^(replace|rename|remove|unlink|chmod)$")
MODULOS_DE_SISTEMA_DE_FICHEROS = {"os", "shutil", "os.path"}


def _escribe_de_verdad(canon: str, visto: set[str] | None = None) -> str:
    """¿La función `canon` escribe estado durable? Se mira SU CÓDIGO.

    Sustituye a la tupla de prefijos de módulo que había antes, que era
    exactamente la lista mantenida a mano que el operador prohibió, un nivel más
    arriba: bastaba que una escritura viviera en un módulo no listado
    (`app.health`) para que el endpoint saliera verde. Ahora la durabilidad se
    DERIVA del cuerpo del invocable: se resuelve por `sys.modules`, se lee su
    fuente y se buscan primitivas de escritura (fichero, `os.replace`, SQL de
    escritura, `commit`).

    COTA, dicha como es: **se sigue UN SALTO A SÍMBOLOS IMPORTADOS de `app.*`**.
    El invocable se resuelve con `_importaciones_del_modulo`, y un nombre LOCAL
    no lleva punto, así que sale por `"." not in canon`: los helpers del MISMO
    módulo tienen **cero** saltos y son **mudos**. Medido: `write_text` directo
    -> detectado; helper importado -> detectado; helper local, dos helpers
    encadenados y objeto instanciado en ejecución -> `[]`. Un `GET` que
    escribiera a través de un `_persistir()` local sería invisible, y C1bis no
    puede rescatarlo por ser un `GET`.

    No se ensancha a ciegas, también medido: seguir helpers locales sin más
    criterio convierte media docena de GET de administración en
    `lectura-que-escribe` por el `mkdir` de `admin._get_db_path`. La restricción
    a `app.*`, en cambio, SÍ gana precisión: sin ella la base pasa de 15 a 20
    endpoints de escritura y de 2 a 7 `lectura-que-escribe`, y los 5 nuevos son
    el mismo falso positivo (`Path(indirecto)`).

    Se devuelve la PRIMERA primitiva encontrada, no la más grave: para los
    endpoints de health sale `mkdir` aunque la escritura sea `write_text` +
    `os.replace`. Sirve para atribuir, no para calificar el daño.
    """
    visto = visto or set()
    if canon in visto or "." not in canon or len(visto) > 3:
        return ""
    visto.add(canon)
    modulo, _, atributo = canon.rpartition(".")
    mod = sys.modules.get(modulo)
    fn = getattr(mod, atributo, None)
    if fn is None:
        return ""
    try:
        arbol = ast.parse(textwrap.dedent(inspect.getsource(inspect.unwrap(fn))))
    except (OSError, TypeError, SyntaxError, ValueError):
        return ""
    imp = _importaciones_del_modulo(getattr(fn, "__module__", "") or modulo)
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        hoja = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        base = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
        if RE_PRIMITIVA_DURABLE.match(hoja or ""):
            return hoja
        if RE_PRIMITIVA_AMBIGUA.match(hoja or "") and base in MODULOS_DE_SISTEMA_DE_FICHEROS:
            return f"{base}.{hoja}"
        if hoja in ("execute", "run", "executescript"):
            for arg in nodo.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and RE_SQL_ESCRITURA.search(arg.value):
                    return f"{hoja}:sql-de-escritura"
        if hoja == "open":
            for arg in nodo.args[1:]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and any(c in arg.value for c in "wax+"):
                    return "open:escritura"
        # un salto más: el manejador llama a un servicio que llama al escritor
        if isinstance(f, (ast.Name, ast.Attribute)):
            try:
                sub = _resolver(ast.unparse(f), imp)
            except Exception:  # pragma: no cover
                continue
            # Sólo se desciende a código DEL PROYECTO: seguir a `pathlib.Path`
            # o a la biblioteca estándar declara "escritura" cualquier cosa.
            if sub != canon and sub.startswith("app.") \
                    and _escribe_de_verdad(sub, visto):
                return f"{hoja}(indirecto)"
    return ""


def evidencias_de_escritura(fn) -> tuple[list[str] | None, bool]:
    """Evidencia INDEPENDIENTE del decorador. `(evidencias, clasificado)`."""
    arbol = _arbol_del_manejador(fn)
    if arbol is None or not arbol.body or not isinstance(
            arbol.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None, False
    fd = arbol.body[0]
    ev: set[str] = set()
    importaciones = _importaciones_del_modulo(getattr(fn, "__module__", "") or "")

    # -- firma: cualquier forma de declarar que hay CUERPO de petición
    for d in list(fd.args.defaults) + [d for d in fd.args.kw_defaults if d is not None]:
        if isinstance(d, ast.Call):
            hoja = _es_declarador_de_cuerpo(_resolver(ast.unparse(d.func), importaciones))
            if hoja:
                ev.add(f"parametro-de-cuerpo:{hoja}")
    for a in list(fd.args.args) + list(fd.args.posonlyargs) + list(fd.args.kwonlyargs):
        ev |= _evidencia_en_anotacion(a.annotation, importaciones)
        if a.annotation is not None:
            try:
                canon = _resolver(ast.unparse(a.annotation), importaciones)
            except Exception:  # pragma: no cover
                canon = ""
            if _es_modelo_de_cuerpo(canon):
                ev.add(f"modelo-de-cuerpo:{a.arg}")

    for nodo in ast.walk(fd):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        nombre = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        base = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
        if base == "request" and nombre in LECTORES_DE_CUERPO:
            ev.add(f"lee-el-cuerpo:request.{nombre}")
        if RE_CSRF_VERIFICA.search(nombre or ""):
            ev.add(f"verifica-csrf:{nombre}")
        if nombre in ("execute", "executescript", "run"):
            for arg in nodo.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and RE_SQL_ESCRITURA.search(arg.value):
                    ev.add("sql-de-escritura")
        try:
            canon = _resolver(ast.unparse(f), importaciones)
        except Exception:  # pragma: no cover
            continue
        primitiva = _escribe_de_verdad(canon)
        if primitiva:
            ev.add(f"mutador-de-estado-durable:{canon} ({primitiva})")
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
def _especificidad(path: str) -> tuple[int, int]:
    """Menos parámetros gana; a igualdad, más literal gana."""
    return (-path.count("{"), len(re.sub(r"\{[^}]+\}", "", path)))


def _ruta_mas_especifica(filas: list[dict[str, Any]], url: str) -> dict | None:
    """La ruta que DEBE atender `url`, derivada del enrutador.

    Starlette elige por orden de declaración; aquí se pregunta cuál es la que
    describe esa URL con menos comodines, que es la que el autor del formulario
    tenía en mente. Es una derivación, no una lista.
    """
    from starlette.routing import compile_path

    candidatas = []
    for f in filas:
        rx, _, _ = compile_path(f["path"])
        if rx.fullmatch(url):
            candidatas.append(f)
    if not candidatas:
        return None
    return max(candidatas, key=lambda f: _especificidad(f["path"]))


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
    filas_vivas = escritura + lectura
    contratos = contratos_de_cliente(repo, app)

    # ---- sondeo HTTP (F3): un GET a cada ruta de escritura + cada contrato
    urls = [("GET", _url_concreta(f["path"])) for f in escritura]
    urls += [(c["metodo"], c["url"]) for c in contratos]
    sondas = sondear(app, urls, registro)

    #: Un endpoint SIN ningún método de escritura cuya única evidencia es que
    #: muta estado durable no es «una escritura mal montada»: es una LECTURA QUE
    #: ESCRIBE, y se nombra así. Sin esta distinción los dos endpoints de health
    #: disparaban cuatro hallazgos que decían lo mismo de cuatro maneras, y la
    #: atribución («cada rojo, un motivo») se perdía.
    def _lectura_que_escribe(f) -> bool:
        durables = [e for e in f["evidencias"]
                    if e.startswith("mutador-de-estado-durable") or e == "sql-de-escritura"]
        return bool(durables) and not (set(f["metodos"]) & METODOS_DE_ESCRITURA) \
            and len(durables) == len(f["evidencias"])

    # ---- C1 (enumeración): ningún endpoint de escritura montado con GET/HEAD
    for f in escritura:
        if _lectura_que_escribe(f):
            continue
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

    # ---- C1bis (la red que no depende de que F1 acierte): una ruta montada
    #      con POST/PUT/PATCH/DELETE clasificada como LECTURA. Hoy el conjunto
    #      es VACÍO, así que entra en verde y cubre a TODO endpoint de escritura
    #      montado, acierte o no la clasificación. Es la comprobación que hace
    #      innecesario confiar en F1: si mañana un refactor de estilo dejara muda
    #      a la clasificación, el endpoint no desaparece del enrutador.
    for f in lectura:
        inseguros = sorted(set(f["metodos"]) & METODOS_DE_ESCRITURA)
        if inseguros:
            anota("metodo-de-escritura-sin-evidencia", {
                "path": f["path"], "endpoint": f["endpoint"],
                "metodos_montados": f["metodos"], "metodos_de_escritura": inseguros,
                "detalle": ("la app sirve escritura en esta ruta pero la "
                            "clasificación no encontró NI UNA evidencia: o el "
                            "endpoint no debería aceptar ese método, o la "
                            "clasificación se ha quedado muda"),
            })

    # ---- C1ter: un método SEGURO que escribe estado durable. `GET` que
    #      escribe es escritura, y este carril existe justamente para no dejar
    #      eso invisible.
    for f in escritura:
        if _lectura_que_escribe(f):
            anota("lectura-que-escribe", {
                "path": f["path"], "endpoint": f["endpoint"],
                "metodos_montados": f["metodos"], "evidencias": f["evidencias"],
            })

    # ---- C2 (ejecución): un GET a la URL de una escritura no puede acabar
    #      ATENDIDO por el manejador de escritura. Que la app sirva GET ahí es
    #      legítimo si lo atiende OTRO manejador de lectura montado en el mismo
    #      path (`GET /login` pinta el formulario que `POST /login` procesa);
    #      lo que no es legítimo es que conteste el que escribe.
    for f in escritura:
        if _lectura_que_escribe(f):
            continue
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

    # ---- C3: el contrato de cliente (plantillas/JS) se puede ejecutar Y LO
    #      ATIENDE QUIEN DEBE. Comprobar sólo «no da 405» dejaba pasar el
    #      `POST -> PUT` de `/admin/users/new`: al mutar, la petición la recoge
    #      `POST /admin/users/{user_id}` (que casa con `user_id="new"`) y
    #      responde 422, así que no había 405 que ver. La ruta que DEBE atender
    #      es la más específica de las que casan con la URL —menos parámetros
    #      gana, y a igualdad, la de literal más largo—, y eso se deriva del
    #      enrutador, sin escribir el nombre de ningún endpoint.
    for c in contratos:
        sonda = sondas.get(f"{c['metodo']} {c['url']}") or {}
        estado = sonda.get("estado")
        if estado in (404, 405, -1, None):
            anota("contrato-de-cliente-roto", {**c, "estado": estado,
                                               "motivo": "la app no sirve ese metodo"})
            continue
        debe = _ruta_mas_especifica(filas_vivas, c["url"])
        if debe is None:
            continue
        atendido = sonda.get("atendido_por")
        if c["metodo"] not in set(debe["metodos"]):
            anota("contrato-de-cliente-roto", {
                **c, "estado": estado, "motivo": "el metodo no lo acepta la ruta que manda",
                "ruta_que_manda": debe["path"], "metodos_de_esa_ruta": debe["metodos"]})
        elif atendido is not None and atendido != debe["endpoint"]:
            anota("contrato-de-cliente-roto", {
                **c, "estado": estado, "motivo": "lo atendio otro manejador",
                "esperado": debe["endpoint"], "atendido_por": atendido})

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

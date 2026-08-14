#!/usr/bin/env python3
"""Calibración del CENSO de rutas: los tres huecos fail-open, en verde y en rojo.

Regla del proyecto: ningún gate entra sin control negativo conocido, y un arnés
que pasa con 0 casos está roto. Aquí se construyen aplicaciones FastAPI/Starlette
REALES (no simulacros de objetos con atributos) que contienen cada hueco, y se
mide DIFERENCIALMENTE:

  - `censo_viejo`  reproduce VERBATIM el enumerador anterior de
    `iter_effective_routes` (el de `main@420f626`). Es el control negativo: con
    él cada caso sale VERDE, es decir, el hueco no se ve.
  - `censo_nuevo`  es el enumerador de verdad, importado del módulo, no una
    copia. Con él cada caso tiene que salir ROJO (visto: la ruta aparece con su
    URL efectiva, o la entrada se declara opaca).

Casos:
  H1  `Mount` con un POST dentro                   -> el POST existe en el censo
  H2  ruta sin `methods` enumerables               -> opaca, nunca «GET»
  H3  WebSocket                                    -> presente y opaca
  H4  `Mount` anidado a dos niveles                -> URL efectiva compuesta
  H5  `Mount` anidado a tres niveles               -> URL efectiva compuesta
  H6  `include_router` con un `Mount` dentro       -> punto ciego real del chasis
  M5  `Mount` ASGI plano sin subrutas              -> opaca (el motivo que de
                                                      verdad dispara en esta app)
  M3  tipo de ruta ajeno CON path y methods        -> opaca `tipo-desconocido`
  H7  censo VACÍO                                  -> ROJO, no verde silencioso
  E1  `StaticFiles`                                -> caracterizado y VERIFICADO
  E2  `StaticFiles(html=True)`                     -> caracterizado y verificado
  E3  subclase que acepta POST                     -> muere en la verificación
  E4  montaje que 405ea también GET                -> no es de lectura: ROJO
  E5  escribe por `PROPFIND` (verbo no sondeado)   -> ROJO (conjunto cerrado)
  E6  escribe por `OPTIONS` (sondeado, no exigido) -> ROJO (conjunto cerrado)
  FP1 app limpia sin huecos                        -> 0 opacas (falso positivo)
  FP2 nombres que suenan a hueco pero no lo son    -> 0 opacas (un nombre no concede)

Ablaciones (necesidad de cada criterio): se desactiva UN criterio del módulo real
y el caso que lo necesita tiene que volver a VERDE.

Uso:
    python3 scripts/route_map/calibrate_censo.py --out artifacts/route-map/calibracion-censo.json
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

for _p in (str(REPO / "data-engine" / "app"), str(REPO / "viewer"), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
os.environ.setdefault("S9K_DEFAULT_WORKSPACE", "leyenda")
os.environ.setdefault("S9K_CSRF_SECRET", secrets.token_urlsafe(48))

from route_map import route_map as RM  # noqa: E402


# --------------------------------------------------------------------------
# Control negativo: el enumerador ANTERIOR, copiado tal cual
# --------------------------------------------------------------------------

def censo_viejo(app) -> list[tuple]:
    """El enumerador de `main@420f626`, verbatim. Sus tres huecos incluidos.

    Se conserva aquí a propósito: sin él, «el nuevo ve la ruta» no demuestra
    nada, porque no habría con qué comparar. Es el control que hace legible el
    diferencial.
    """
    try:
        from fastapi.routing import _IncludedRouter
    except ImportError:  # pragma: no cover
        _IncludedRouter = ()
    from fastapi.routing import APIRoute
    from starlette.routing import Mount, Route

    out = []
    for r in app.router.routes:
        if _IncludedRouter and isinstance(r, _IncludedRouter):
            ctxs = list(r.effective_route_contexts()) + list(r.effective_low_priority_routes())
            for ctx in ctxs:
                original = ctx.original_route
                out.append((ctx.path or getattr(original, "path", ""),
                            sorted(ctx.methods or getattr(original, "methods", {"GET"})),
                            "route"))
        elif isinstance(r, Mount):
            out.append((r.path, ["MOUNT"], "mount"))
        elif isinstance(r, (APIRoute, Route)):
            out.append((r.path, sorted(r.methods or {"GET"}), "route"))
    return out


def censo_nuevo(app) -> list[tuple]:
    """El enumerador REAL del módulo. No es una copia: si cambia, esto cambia."""
    return [(path, list(methods), kind, motivo)
            for path, methods, _d, _e, _h, kind, motivo in RM.iter_effective_routes(app)]


def _claves(censo) -> set[str]:
    """`{"METODO path"}` de un censo, en la forma en que se citan los hallazgos."""
    out = set()
    for fila in censo:
        path, methods = fila[0], fila[1]
        for m in methods:
            out.add(f"{m} {path}")
    return out


def _opacas(censo) -> list[dict]:
    return [{"path": f[0], "motivo": f[3]} for f in censo if f[2] == RM.KIND_OPACO]


# --------------------------------------------------------------------------
# Aplicaciones de prueba: constructos REALES de FastAPI/Starlette
# --------------------------------------------------------------------------

def _fastapi():
    from fastapi import FastAPI

    return FastAPI()


def app_h1():
    """`Mount` con un POST dentro, bajo una ruta cualquiera."""
    from fastapi import FastAPI
    from starlette.routing import Mount

    interna = FastAPI()

    @interna.post("/aprobar")
    def aprobar():  # pragma: no cover - nunca se invoca
        return {}

    app = _fastapi()
    app.router.routes.append(Mount("/zona", app=interna))
    return app


def app_h2():
    """Ruta sin `methods` enumerables: `Route` con `methods=None`.

    Starlette lo admite (`methods=None` significa «cualquiera» para una ruta
    montada a mano) y el enumerador viejo lo convertía en `GET`.
    """
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def _h(request):  # pragma: no cover
        return PlainTextResponse("")

    app = _fastapi()
    r = Route("/sin-metodos", endpoint=_h, methods=["POST"])
    r.methods = None  # la ruta deja de poder enumerar sus métodos
    app.router.routes.append(r)
    return app


def app_h3():
    """WebSocket: `APIWebSocketRoute`, que no encajaba en ninguna rama."""
    app = _fastapi()

    @app.websocket("/ws")
    async def ws(websocket):  # pragma: no cover
        await websocket.accept()

    return app


def _mount_anidado(niveles: int):
    """`Mount` anidado a `niveles` con un POST en el fondo."""
    from fastapi import FastAPI
    from starlette.routing import Mount

    fondo = FastAPI()

    @fondo.post("/fondo")
    def fondo_post():  # pragma: no cover
        return {}

    actual = fondo
    for i in range(niveles, 0, -1):
        envoltorio = FastAPI()
        envoltorio.router.routes.append(Mount(f"/n{i}", app=actual))
        actual = envoltorio
    return actual


def app_h4():
    return _mount_anidado(2)


def app_h5():
    return _mount_anidado(3)


def app_h6():
    """`include_router` con un `Mount` dentro. Punto ciego real del chasis."""
    from fastapi import APIRouter, FastAPI
    from starlette.routing import Mount

    interna = FastAPI()

    @interna.post("/aprobar")
    def aprobar():  # pragma: no cover
        return {}

    router = APIRouter()

    @router.get("/normal")
    def normal():  # pragma: no cover
        return {}

    router.routes.append(Mount("/m", app=interna))
    app = _fastapi()
    app.include_router(router, prefix="/inc")
    return app


def app_m5():
    """`Mount` NO enumerable que **no** es estático: ASGI plano.

    Éste es el motivo (`montaje-no-enumerable`) que de verdad dispara en esta
    app, y no lo cubría ningún caso: H1/H4/H5/H6 montan sub-apps FastAPI, que sí
    tienen rutas. Sin este caso se podía reabrir el agujero —«un Mount sin
    subrutas se salta en silencio»— con la calibración en verde.
    """
    from starlette.routing import Mount

    async def asgi_plano(scope, receive, send):  # pragma: no cover
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = _fastapi()
    app.router.routes.append(Mount("/asgi", app=asgi_plano))
    return app


class _RutaAjena:
    """Tipo de ruta ajeno **con** `path` y `methods` enumerables.

    Es el único constructo que llega a la rama `tipo-de-ruta-desconocido`: un
    WebSocket no, porque muere antes en `metodos-no-enumerables`. Sin este caso,
    ese motivo no tenía ni calibración ni ablación.
    """

    def __init__(self, path, methods):
        self.path = path
        self.methods = set(methods)
        self.name = "ajena"

    async def handle(self, scope, receive, send):  # pragma: no cover
        return None


def app_m3():
    app = _fastapi()
    app.router.routes.append(_RutaAjena("/ajena", {"POST"}))
    return app


def app_h7():
    """Censo vacío: una app sin ninguna ruta propia."""
    from starlette.applications import Starlette

    app = Starlette(routes=[])
    return app


def _dir_estatico():
    """Directorio temporal con un `index.html` y un fichero suelto."""
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="s9k-cal-static-"))
    (d / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    (d / "a.txt").write_text("a", encoding="utf-8")
    return d


def app_estatico(html=False, clase=None):
    """`Mount` sobre `StaticFiles` (o sobre una subclase que MIENTE)."""
    from starlette.routing import Mount
    from starlette.staticfiles import StaticFiles

    cls = clase or StaticFiles
    app = _fastapi()
    app.router.routes.append(
        Mount("/static", app=cls(directory=str(_dir_estatico()), html=html),
              name="static"))
    return app


def _estatico_que_escribe_por(verbo):
    """`StaticFiles` que ESCRIBE UN FICHERO usando un verbo fuera de la lista.

    Pasa la hipótesis de tipo y —con la aserción de lista de verbos— pasaba
    también la verificación: `OPTIONS` se sondeaba y no se comprobaba, y
    `PROPFIND`/`MKCOL`/`TRACE` ni se sondeaban. Escribe de verdad en disco para
    que el caso no dependa del código de estado: se comprueba el fichero.
    """
    from starlette.staticfiles import StaticFiles

    class _Escribe(StaticFiles):
        colado = None  # ruta del fichero que consigue colar

        async def __call__(self, scope, receive, send):
            if scope.get("method") == verbo:
                destino = Path(self.directory) / "colado.txt"
                destino.write_text("escrito por " + verbo, encoding="utf-8")
                type(self).colado = destino
                await send({"type": "http.response.start", "status": 200,
                            "headers": []})
                await send({"type": "http.response.body", "body": b"escrito"})
                return
            await super().__call__(scope, receive, send)

    return _Escribe


class _EstaticoQue405eaLectura:
    """`StaticFiles` que rechaza también `GET`: no es un montaje de lectura.

    Es la mitad de LECTURA de la aserción, que no tenía ningún caso capaz de
    matarla: borrar entero `malos_lectura` dejaba la calibración en OK.
    """

    @staticmethod
    def construir():
        from starlette.responses import PlainTextResponse
        from starlette.staticfiles import StaticFiles

        class _Cerrado(StaticFiles):
            async def __call__(self, scope, receive, send):
                resp = PlainTextResponse("Method Not Allowed", status_code=405)
                await resp(scope, receive, send)

        return _Cerrado


class _EstaticoQueMiente:
    """Subclase de `StaticFiles` que ACEPTA POST.

    Es «un `Mount` que dice ser estático y no lo es»: pasa la hipótesis de tipo
    (es un `StaticFiles`) y tiene que morir en la VERIFICACIÓN. Es la prueba de
    que esto no es una lista de excepciones: escribir el nombre correcto no basta,
    hay que cumplir la afirmación.
    """

    @staticmethod
    def construir():
        from starlette.staticfiles import StaticFiles

        class _Miente(StaticFiles):
            async def __call__(self, scope, receive, send):
                if scope.get("method") in ("POST", "PUT", "PATCH", "DELETE"):
                    await send({"type": "http.response.start", "status": 200,
                                "headers": []})
                    await send({"type": "http.response.body", "body": b"escrito"})
                    return
                await super().__call__(scope, receive, send)

        return _Miente


def _caso_estatico(nombre, app, espera_fallo, descripcion, clase_que_escribe=None):
    """Censa, sonda contra la app real y verifica la caracterización.

    Si `clase_que_escribe` está presente, se comprueba además si el montaje
    consiguió **escribir un fichero en disco** durante el sondeo: el defecto que
    importa es la escritura, no el código de estado.
    """
    from fastapi.testclient import TestClient

    censo = censo_nuevo(app)
    estaticos = [r for r in RM.collect_mounted(app) if r["kind"] == RM.KIND_ESTATICO]
    with TestClient(app) as client:
        sondas = RM.sondar_estaticos(client, estaticos)
    fallos = RM.verificar_estaticos(estaticos, sondas, skip_probe=False)
    colado = None
    if clase_que_escribe is not None:
        ruta = getattr(clase_que_escribe, "colado", None)
        colado = bool(ruta and Path(ruta).exists())
    # Sin sonda, la afirmación NO se concede: una caracterización sin verificar
    # es una excepción disfrazada.
    fallos_sin_sonda = RM.verificar_estaticos(estaticos, None, skip_probe=True)
    return nombre, {
        "descripcion": descripcion,
        "censo_nuevo": sorted(_claves(censo)),
        "montajes_estaticos": [e["key"] for e in estaticos],
        "sondas": sondas,
        "fallos": fallos,
        "fichero_colado_existe": colado,
        "sin_sonda_tambien_falla": bool(fallos_sin_sonda),
        "detectado": (bool(fallos) == espera_fallo) and bool(estaticos)
        and bool(fallos_sin_sonda),
    }


def app_fp1():
    """App limpia: rutas normales e `include_router`. No debe haber opacas."""
    from fastapi import APIRouter

    app = _fastapi()

    @app.get("/raiz")
    def raiz():  # pragma: no cover
        return {}

    router = APIRouter()

    @router.post("/crear")
    def crear():  # pragma: no cover
        return {}

    app.include_router(router, prefix="/sub")
    return app


def app_fp2():
    """Nombres que suenan a hueco. Un NOMBRE no concede ni acusa.

    Rutas llamadas `mount`, `websocket` y `opaco` que son rutas HTTP normales y
    perfectamente enumerables: el censo decide por comportamiento observado, así
    que ninguna puede salir opaca.
    """
    app = _fastapi()

    @app.get("/mount")
    def mount():  # pragma: no cover
        return {}

    @app.post("/websocket")
    def websocket():  # pragma: no cover
        return {}

    @app.get("/opaco/{x}")
    def opaco(x: str):  # pragma: no cover
        return {}

    return app


# --------------------------------------------------------------------------
# Casos
# --------------------------------------------------------------------------

def _caso(nombre, constructor, comprueba, descripcion):
    app = constructor()
    viejo = censo_viejo(app)
    nuevo = censo_nuevo(app)
    v_claves, n_claves = _claves(viejo), _claves(nuevo)
    ve_viejo, ve_nuevo = comprueba(v_claves, viejo), comprueba(n_claves, nuevo)
    return nombre, {
        "descripcion": descripcion,
        "censo_viejo": sorted(v_claves),
        "censo_nuevo": sorted(n_claves),
        "opacas_nuevo": _opacas(nuevo),
        "el_viejo_lo_ve": bool(ve_viejo),
        "el_nuevo_lo_ve": bool(ve_nuevo),
        # Diferencial: el hueco se reproduce en VERDE con el instrumento viejo
        # (no lo ve) y se pone en ROJO con el nuevo (lo ve).
        "detectado": bool(ve_nuevo) and not bool(ve_viejo),
    }


def _tiene(clave):
    return lambda claves, censo: clave in claves


def _hay_opaca(subcadena):
    def _f(claves, censo):
        return any(subcadena in o["path"] for o in _opacas(censo))
    return _f


def _sin_opacas(claves, censo):
    return not _opacas(censo)


def casos_principales() -> dict:
    out = {}
    for nombre, ctor, chk, desc in [
        ("H1-mount-con-post-dentro", app_h1, _tiene("POST /zona/aprobar"),
         "un POST escondido bajo un Mount tiene que aparecer con su URL efectiva"),
        ("H2-ruta-sin-metodos-enumerables", app_h2, _hay_opaca("/sin-metodos"),
         "sin métodos enumerables la ruta es OPACA, jamás «GET»"),
        ("H3-websocket", app_h3, _hay_opaca("/ws"),
         "el WebSocket desaparecía del censo entero; ahora está y es opaco"),
        ("H4-mount-anidado-2-niveles", app_h4, _tiene("POST /n1/n2/fondo"),
         "dos niveles de Mount componen la URL efectiva"),
        ("H5-mount-anidado-3-niveles", app_h5, _tiene("POST /n1/n2/n3/fondo"),
         "tres niveles de Mount componen la URL efectiva"),
        ("H6-include-router-con-mount", app_h6, _tiene("POST /inc/m/aprobar"),
         "Mount dentro de un router incluido: punto ciego real del chasis"),
        ("M5-mount-no-enumerable-asgi-plano", app_m5, _hay_opaca("/asgi"),
         "un Mount ASGI sin subrutas que NO es estático tiene que salir opaco; "
         "es el motivo que de verdad dispara en esta app y no estaba calibrado"),
        ("M3-tipo-de-ruta-ajeno", app_m3, _hay_opaca("/ajena"),
         "un tipo de ruta ajeno CON path y methods llega a la rama "
         "`tipo-de-ruta-desconocido`; el WebSocket no, muere antes en métodos"),
    ]:
        n, r = _caso(nombre, ctor, chk, desc)
        out[n] = r

    # H7: el caso vacío. Aquí el diferencial no es viejo/nuevo (ninguno de los
    # dos censa nada, porque no hay nada), sino que la REGLA del instrumento
    # declare rojo en vez de callar. Se ejercita la regla real del módulo.
    app = app_h7()
    nuevo = censo_nuevo(app)
    filas = [{"path": f[0]} for f in nuevo if f[2] == "route"]
    hallazgo = RM.censo_vacio_findings(filas)
    # Y el suelo NO se puede satisfacer con rutas opacas: un censo compuesto
    # sólo de entradas irresolubles sigue siendo un censo vacío.
    ch = RM._criterios()
    solo_opacas = [{"path": ch.PATH_NOT_RESOLVABLE}]
    out["H7-censo-vacio"] = {
        "descripcion": "0 rutas observadas debe ser ROJO, no verde silencioso",
        "censo_nuevo": sorted(_claves(nuevo)),
        "hallazgo_censo_vacio": hallazgo,
        "suelo_no_se_autocumple_con_opacas": bool(RM.censo_vacio_findings(solo_opacas)),
        "detectado": bool(hallazgo) and bool(RM.censo_vacio_findings(solo_opacas))
        and not RM.censo_vacio_findings([{"path": "/algo"}]),
    }

    # Caracterización de los montajes estáticos: afirmación positiva y falsable,
    # no excepción. Las dos primeras tienen que CUMPLIRLA (y por tanto dejar la
    # app en verde legítimo); la tercera la incumple y tiene que ponerse roja.
    _propfind = _estatico_que_escribe_por("PROPFIND")
    _options = _estatico_que_escribe_por("OPTIONS")
    for nombre, app, espera_fallo, desc, escritor in [
        ("E1-estatico-verificado", app_estatico(), False,
         "StaticFiles: {GET, HEAD} servidos y todo lo demás rechazado con 405", None),
        ("E2-estatico-html-true", app_estatico(html=True), False,
         "StaticFiles(html=True): la raíz sirve index.html y el resto sigue 405", None),
        ("E3-dice-ser-estatico-y-no-lo-es", app_estatico(clase=_EstaticoQueMiente.construir()),
         True,
         "una subclase de StaticFiles que acepta POST pasa la hipótesis de tipo y "
         "MUERE en la verificación: por eso esto no es una lista de excepciones",
         None),
        ("E4-405-tambien-en-lectura", app_estatico(clase=_EstaticoQue405eaLectura.construir()),
         True,
         "un montaje que 405ea GET tampoco es de lectura: mata la mitad de LECTURA "
         "de la aserción, que antes no tenía ningún caso que la matase", None),
        ("E5-escribe-por-PROPFIND", app_estatico(clase=_propfind), True,
         "verbo que ni se sondeaba: escribía un fichero en disco y pasaba en verde",
         _propfind),
        ("E6-escribe-por-OPTIONS", app_estatico(clase=_options), True,
         "verbo que se sondeaba y NO se comprobaba: mismo agujero", _options),
    ]:
        n, r = _caso_estatico(nombre, app, espera_fallo, desc, escritor)
        out[n] = r

    # Falsos positivos: vigilar el verde equivocado Y el rojo equivocado.
    for nombre, ctor, desc in [
        ("FP1-app-limpia-sin-opacas", app_fp1,
         "una app sin huecos no puede producir ninguna entrada opaca"),
        ("FP2-nombres-que-suenan-a-hueco", app_fp2,
         "un NOMBRE no concede ni acusa: se decide por comportamiento observado"),
    ]:
        app = ctor()
        nuevo = censo_nuevo(app)
        out[nombre] = {
            "descripcion": desc,
            "censo_nuevo": sorted(_claves(nuevo)),
            "opacas_nuevo": _opacas(nuevo),
            "detectado": _sin_opacas(None, nuevo) and bool(_claves(nuevo)),
        }
    return out


# --------------------------------------------------------------------------
# Ablaciones: ¿hace falta cada criterio?
# --------------------------------------------------------------------------

class _ablacion:
    """Desactiva UN criterio del módulo real mientras dura el bloque."""

    def __init__(self, obj, attr, nuevo):
        self.obj, self.attr, self.nuevo = obj, attr, nuevo

    def __enter__(self):
        self.viejo = getattr(self.obj, self.attr)
        setattr(self.obj, self.attr, self.nuevo)
        return self

    def __exit__(self, *a):
        setattr(self.obj, self.attr, self.viejo)
        return False


def ablaciones() -> dict:
    ch = RM._criterios()
    out = {}

    # A1: `methods` deja de ser tri-estado y la ausencia vuelve a ser «GET».
    original_enum = ch.enumerable_methods

    def enum_fail_open(route):
        m = original_enum(route)
        return m if m is not None else frozenset({"GET"})

    with _ablacion(ch, "enumerable_methods", enum_fail_open):
        censo = censo_nuevo(app_h2())
        out["A1-methods-fail-open"] = {
            "criterio": "methods tri-estado (None != frozenset())",
            "caso": "H2-ruta-sin-metodos-enumerables",
            "censo_ablado": sorted(_claves(censo)),
            # Sin el criterio, la ruta vuelve a pasar por un GET inocuo.
            "vuelve_a_verde": not _hay_opaca("/sin-metodos")(None, censo),
        }

    # A2: se deja de descender por los `Mount`.
    original_nodo = RM._nodo

    def nodo_sin_descenso(r, prefijo, ch_):
        sub = getattr(r, "routes", None)
        if sub is not None and not hasattr(r, "endpoint") \
                and not callable(getattr(r, "effective_route_contexts", None)):
            yield RM._opaca(r, prefijo, ch_, "ablacion-sin-descenso")
            return
        yield from original_nodo(r, prefijo, ch_)

    with _ablacion(RM, "_nodo", nodo_sin_descenso):
        for nombre, ctor, clave in [
            ("H1-mount-con-post-dentro", app_h1, "POST /zona/aprobar"),
            ("H4-mount-anidado-2-niveles", app_h4, "POST /n1/n2/fondo"),
            ("H5-mount-anidado-3-niveles", app_h5, "POST /n1/n2/n3/fondo"),
            ("H6-include-router-con-mount", app_h6, "POST /inc/m/aprobar"),
        ]:
            censo = censo_nuevo(ctor())
            out[f"A2-sin-descenso-por-mount::{nombre}"] = {
                "criterio": "descender por los Mount componiendo la URL efectiva",
                "caso": nombre,
                "censo_ablado": sorted(_claves(censo)),
                "vuelve_a_verde": clave not in _claves(censo),
            }

    # A3: se desactiva la comprobación de TIPO (todo pasa por ruta buena).
    # Ablación REAL sobre el módulo nuevo: la versión anterior de este arnés
    # ablaba el instrumento viejo, que no es el que se está calibrando.
    with _ablacion(RM, "_tipos_http", lambda: (object,)):
        censo = censo_nuevo(app_m3())
        out["A3-sin-comprobacion-de-tipo"] = {
            "criterio": "un tipo de ruta desconocido se emite como opaco",
            "caso": "M3-tipo-de-ruta-ajeno",
            "censo_ablado": sorted(_claves(censo)),
            "vuelve_a_verde": not _hay_opaca("/ajena")(None, censo),
        }

    # A4: se desactiva la REGLA del caso vacío en el módulo real. La versión
    # anterior de este arnés ponía aquí la constante `True`, que no mide nada y
    # no puede ponerse roja: no se cobraba.
    with _ablacion(RM, "censo_vacio_findings", lambda rows, ch=None: []):
        hallazgo = RM.censo_vacio_findings([])
        out["A4-sin-regla-de-censo-vacio"] = {
            "criterio": "0 rutas observadas es ROJO",
            "caso": "H7-censo-vacio",
            "censo_ablado": hallazgo,
            "vuelve_a_verde": not hallazgo,
        }

    # A5: se salta en silencio el `Mount` sin subrutas (el falso negativo que
    # reabría el agujero con el arnés en verde).
    def nodo_saltando_mounts_vacios(r, prefijo, ch_):
        sub = getattr(r, "routes", None)
        if sub is not None and not hasattr(r, "endpoint") \
                and not callable(getattr(r, "effective_route_contexts", None)) \
                and not list(sub):
            return
        yield from original_nodo(r, prefijo, ch_)

    with _ablacion(RM, "_nodo", nodo_saltando_mounts_vacios):
        censo = censo_nuevo(app_m5())
        out["A5-mount-vacio-se-salta-en-silencio"] = {
            "criterio": "un montaje no enumerable se declara opaco, no se salta",
            "caso": "M5-mount-no-enumerable-asgi-plano",
            "censo_ablado": sorted(_claves(censo)),
            "vuelve_a_verde": not _hay_opaca("/asgi")(None, censo),
        }

    from fastapi.testclient import TestClient

    # A6: se desactiva la VERIFICACIÓN de la caracterización estática y se acepta
    # la hipótesis de tipo a secas. Es exactamente «una lista de excepciones»: el
    # montaje que miente pasa por bueno.
    app_miente = app_estatico(clase=_EstaticoQueMiente.construir())
    estaticos = [r for r in RM.collect_mounted(app_miente) if r["kind"] == RM.KIND_ESTATICO]
    with TestClient(app_miente) as client:
        sondas = RM.sondar_estaticos(client, estaticos)
    with _ablacion(RM, "verificar_estaticos",
                   lambda est, son, skip_probe=False: []):
        fallos = RM.verificar_estaticos(estaticos, sondas)
        out["A6-sin-verificacion-de-la-caracterizacion"] = {
            "criterio": "la afirmación «montaje estático» se comprueba contra la app real",
            "caso": "E3-dice-ser-estatico-y-no-lo-es",
            "censo_ablado": fallos,
            "vuelve_a_verde": not fallos,
        }

    # A7: la aserción vuelve a ser una LISTA de cuatro verbos en vez de un
    # conjunto cerrado. El montaje que escribe por OPTIONS vuelve a pasar.
    _opt = _estatico_que_escribe_por("OPTIONS")
    app_opt = app_estatico(clase=_opt)
    est_opt = [r for r in RM.collect_mounted(app_opt) if r["kind"] == RM.KIND_ESTATICO]
    with TestClient(app_opt) as client:
        sondas_opt = RM.sondar_estaticos(client, est_opt)
    with _ablacion(RM, "fallo_metodos_no_lectura",
                   lambda res: {m: res.get(m) for m in RM.ESCRITURA_ESTATICA
                                if res.get(m) != 405}):
        fallos = RM.verificar_estaticos(est_opt, sondas_opt)
        out["A7-lista-de-verbos-en-vez-de-conjunto-cerrado"] = {
            "criterio": "todo método sondeado que no sea {GET, HEAD} debe dar 405",
            "caso": "E6-escribe-por-OPTIONS",
            "censo_ablado": fallos,
            "vuelve_a_verde": not fallos,
        }

    # A8: se sondean sólo los verbos clásicos. `PROPFIND` deja de existir para
    # el instrumento y el montaje que escribe con él vuelve a pasar.
    _pf = _estatico_que_escribe_por("PROPFIND")
    app_pf = app_estatico(clase=_pf)
    est_pf = [r for r in RM.collect_mounted(app_pf) if r["kind"] == RM.KIND_ESTATICO]
    with _ablacion(RM, "METODOS_SONDEADOS_ESTATICO",
                   ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")):
        with TestClient(app_pf) as client:
            sondas_pf = RM.sondar_estaticos(client, est_pf)
        fallos = RM.verificar_estaticos(est_pf, sondas_pf)
        out["A8-sin-verbos-arbitrarios-en-la-sonda"] = {
            "criterio": "la sonda incluye verbos fuera de los clásicos (PROPFIND, MKCOL, TRACE)",
            "caso": "E5-escribe-por-PROPFIND",
            "censo_ablado": fallos,
            "vuelve_a_verde": not fallos,
        }

    # A9: se borra la mitad de LECTURA de la aserción. Sin caso que la matara,
    # borrarla entera dejaba la calibración en OK; con E4, se pone roja.
    app_cerrado = app_estatico(clase=_EstaticoQue405eaLectura.construir())
    est_c = [r for r in RM.collect_mounted(app_cerrado) if r["kind"] == RM.KIND_ESTATICO]
    with TestClient(app_cerrado) as client:
        sondas_c = RM.sondar_estaticos(client, est_c)
    with _ablacion(RM, "fallo_lectura", lambda res: {}):
        fallos = RM.verificar_estaticos(est_c, sondas_c)
        out["A9-sin-mitad-de-lectura"] = {
            "criterio": "GET/HEAD tienen que servirse para poder llamarlo montaje de lectura",
            "caso": "E4-405-tambien-en-lectura",
            "censo_ablado": fallos,
            "vuelve_a_verde": not fallos,
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    casos = casos_principales()
    abl = ablaciones()
    # Un arnés que pasa con 0 casos está roto: se exige carga. Los umbrales son
    # la carga REAL, no la nominal: una versión anterior contaba 7 ablaciones
    # incluyendo una constante literal (`A4`, que no medía nada) y una ablación
    # del instrumento VIEJO (`A3`), que tampoco se cobra. Hoy las 9 ablaciones
    # patchean el módulo nuevo y todas pueden ponerse rojas.
    hay_carga = len(casos) >= 17 and len(abl) >= 12
    ok = (hay_carga
          and all(c["detectado"] for c in casos.values())
          and all(x["vuelve_a_verde"] for x in abl.values()))
    res = {"casos": casos, "ablaciones": abl,
           "casos_ejecutados": len(casos), "ablaciones_ejecutadas": len(abl),
           "arnes_con_carga": hay_carga, "ok": ok}
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False,
                                          sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v["detectado"] for k, v in casos.items()}, indent=2))
    print(json.dumps({k: v["vuelve_a_verde"] for k, v in abl.items()}, indent=2))
    print("casos:", len(casos), "ablaciones:", len(abl))
    print("CALIBRACION DEL CENSO:", "OK" if ok else "FALLIDA")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

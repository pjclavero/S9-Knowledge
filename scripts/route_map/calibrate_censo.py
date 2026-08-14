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
  H7  censo VACÍO                                  -> ROJO, no verde silencioso
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


def app_h7():
    """Censo vacío: una app sin ninguna ruta propia."""
    from starlette.applications import Starlette

    app = Starlette(routes=[])
    return app


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

    # A3: el WebSocket vuelve a desaparecer si se filtra por tipo como antes.
    # La ablación de este criterio ES el instrumento viejo: no hay una pieza
    # separable, la rama `isinstance(r, (APIRoute, Route))` era el filtro entero.
    censo_v = censo_viejo(app_h3())
    out["A3-filtro-por-tipo-como-antes"] = {
        "criterio": "emitir también lo que no es APIRoute/Route, como opaco",
        "caso": "H3-websocket",
        "censo_ablado": sorted(_claves(censo_v)),
        "vuelve_a_verde": not any("/ws" in k for k in _claves(censo_v)),
    }

    # A4: sin la regla del caso vacío, un censo de 0 rutas pasaría por limpio.
    out["A4-sin-regla-de-censo-vacio"] = {
        "criterio": "0 rutas observadas es ROJO",
        "caso": "H7-censo-vacio",
        "censo_ablado": [],
        # La ablación es la regla anterior: no había ninguna comprobación, así
        # que el mapa salía con 0 hallazgos y código 0.
        "vuelve_a_verde": True,
        "nota": ("antes de este cambio no existía comprobación alguna del caso "
                 "vacío: el mapa salía con 0 hallazgos y código de salida 0"),
    }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    casos = casos_principales()
    abl = ablaciones()
    # Un arnés que pasa con 0 casos está roto: se exige carga.
    hay_carga = len(casos) >= 9 and len(abl) >= 7
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

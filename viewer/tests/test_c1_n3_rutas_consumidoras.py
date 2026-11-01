# -*- coding: utf-8 -*-
"""C1 (USABLE-V1) · H-04 + H-18 — N3 AMPLIADO: TODAS las rutas que consumen el almacen.

POR QUE ESTE MODULO EXISTE (D9 de la revision independiente)
-------------------------------------------------------------
El primer N3 recorria una LISTA MANUAL de URLs. Tenia dos huecos medidos:

* los POST llevaban un CSRF inventado (``"t"``) y morian en 403 ANTES de tocar
  el almacen: «no da 500» era cierto, pero por la razon equivocada;
* las rutas del Apply (`/panel/operations` con corrida, `/panel/operations/
  altas`, sellar, aplicar, aprobar alta) no estaban o no llegaban al almacen.

Aqui la lista NO se escribe: se DERIVA del router de la app real. Una ruta es
consumidora si su funcion --o una funcion de su mismo modulo a la que llama,
transitivamente-- nombra ``_service``, ``ReviewService`` o
``ReviewApplyService`` (mismo criterio que el inventario AST del revisor). El
test exige que el conjunto inventariado sea EXACTAMENTE el de casos cubiertos:
una ruta consumidora nueva sin caso pone el test en rojo.

Cada ruta se ejerce con sesion de ADMIN real, CSRF VALIDO, una corrida real con
propuestas y una decision aprobada, y la ruta del almacen declarada AUSENTE.
Se exige: respuesta controlada (nunca 500), que NOMBRE el almacen (nunca un
``{}`` o una cola vacia silenciosos) y el filesystem intacto (ni fichero, ni
``-wal``/``-shm``, ni directorio).

TECHO DECLARADO
---------------
* El alcance del inventario es el MODULO de la ruta: un consumidor alcanzado a
  traves de una funcion importada de otro modulo con otro nombre no se ve.
* Un alias (``s = ReviewService; s()``) dentro del modulo si se ve (se nombra);
  uno construido por ``getattr``/cadena no.
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
import uuid
from pathlib import Path

import pytest

from test_panel_apply_desde_la_ui import (  # noqa: F401
    _aprobar_una, _csrf, _entorno_limpio, _grafo_de_mentira, _salud_aislada,
    almacenes, auth_on, cola, operador, paneles_on, real_app,
)

VAR = "S9K_V3_REVIEW_DATABASE_PATH"
CONSUMIDORES = frozenset({"_service", "ReviewService", "ReviewApplyService"})
#: Lo que una respuesta tiene que decir para NOMBRAR el almacen ausente: el
#: codigo estable (cuerpo o `aviso=` del 303) o, en la consola de operaciones,
#: el parrafo `no_disponible` del bloque «Lo aprobado de esta ingesta», que es
#: como esa pantalla dice «el dato no esta» (y no «no hay nada aprobado»).
_NOMBRA_EL_ALMACEN = re.compile(
    r"DECISIONS_STORE_[A-Z_]+|REVIEW_STORE_UNAVAILABLE"
    r"|No se puede consultar la cola de revisi\w+n en este despliegue")


# ===========================================================================
# El inventario ESTRUCTURAL
# ===========================================================================

def nombres_alcanzados(arbol: ast.AST, nombre_fn: str) -> set:
    """Nombres (y atributos) que alcanza `nombre_fn`, siguiendo las llamadas a
    funciones del MISMO modulo de forma transitiva."""
    funcs = {n.name: n for n in ast.walk(arbol)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    vistos = {nombre_fn}
    pendientes = [funcs[nombre_fn]] if nombre_fn in funcs else []
    out: set = set()
    while pendientes:
        fn = pendientes.pop()
        for n in ast.walk(fn):
            if isinstance(n, ast.Name):
                out.add(n.id)
                if n.id in funcs and n.id not in vistos:
                    vistos.add(n.id)
                    pendientes.append(funcs[n.id])
            elif isinstance(n, ast.Attribute):
                out.add(n.attr)
    return out


def consume_el_almacen(fuente: str, nombre_fn: str) -> bool:
    return bool(nombres_alcanzados(ast.parse(fuente), nombre_fn) & CONSUMIDORES)


def _rutas_efectivas(rutas, prefijo: str = ""):
    """`(ruta_completa, APIRoute)` de la tabla REAL de la app.

    Segun la version de FastAPI, `include_router` aplana las rutas en
    `app.routes` (APIRoute) o deja un envoltorio con `original_router` y su
    `include_context.prefix`. Se recorren los dos: un inventario que solo
    mirase una forma saldria vacio en la otra, y un inventario vacio no cubre
    nada (por eso tambien se exige un minimo).
    """
    from fastapi.routing import APIRoute  # noqa: PLC0415

    for ruta in rutas:
        if isinstance(ruta, APIRoute):
            yield prefijo + ruta.path, ruta
        elif hasattr(ruta, "original_router"):
            contexto = getattr(ruta, "include_context", None)
            yield from _rutas_efectivas(
                ruta.original_router.routes,
                prefijo + (getattr(contexto, "prefix", "") or ""))


def inventario(app) -> set:
    """`{(METODO, ruta)}` de TODA ruta de la app real que consume el almacen."""
    fuentes: dict = {}
    salida: set = set()
    for camino, ruta in _rutas_efectivas(app.routes):
        fn = inspect.unwrap(ruta.endpoint)
        modulo = sys.modules.get(fn.__module__)
        if modulo is None:
            continue
        if fn.__module__ not in fuentes:
            try:
                fuentes[fn.__module__] = inspect.getsource(modulo)
            except (OSError, TypeError):
                fuentes[fn.__module__] = ""
        if fuentes[fn.__module__] and consume_el_almacen(fuentes[fn.__module__], fn.__name__):
            for metodo in ruta.methods - {"HEAD", "OPTIONS"}:
                salida.add((metodo, camino))
    return salida


def test_n3_el_detector_del_inventario_ve_una_ruta_consumidora_nueva():
    """El detector se calibra a si mismo: una ruta que llega al almacen a
    traves de un ayudante del modulo SE VE; una que no, no."""
    fuente = (
        "def _ayudante():\n    return _service().queue('ws')\n"
        "@router.get('/nueva')\ndef nueva():\n    return _ayudante()\n"
        "@router.get('/ajena')\ndef ajena():\n    return 1\n"
    )
    assert consume_el_almacen(fuente, "nueva"), "N3 DETECTOR CIEGO: no ve el consumo transitivo"
    assert not consume_el_almacen(fuente, "ajena"), "N3 DETECTOR FALSO POSITIVO"


# ===========================================================================
# Los casos: COMO se ejerce cada ruta (no CUALES: eso lo dice el inventario)
# ===========================================================================

def _casos(ctx: dict) -> dict:
    ws, job, pid = ctx["ws"], ctx["job_id"], ctx["proposal_id"]
    phash = ctx["proposal_hash"]
    return {
        ("GET", "/panel/operations"): ("GET", f"/panel/operations?solicitado={job}", None),
        ("GET", "/panel/operations/"): ("GET", f"/panel/operations/?solicitado={job}", None),
        ("GET", "/panel/operations/altas"): ("GET", f"/panel/operations/altas?trabajo={job}", None),
        ("POST", "/panel/operations/planes"): ("POST", "/panel/operations/planes",
                                               {"trabajo": job}),
        ("POST", "/panel/operations/aplicaciones"): ("POST", "/panel/operations/aplicaciones",
                                                     {"trabajo": job}),
        ("POST", "/panel/operations/altas"): ("POST", "/panel/operations/altas",
                                              {"trabajo": job, "entidad": "e", "tipo": "t"}),
        ("GET", "/panel/review"): ("GET", f"/panel/review?workspace={ws}", None),
        ("GET", "/panel/review/"): ("GET", f"/panel/review/?workspace={ws}", None),
        ("GET", "/panel/review/item/{proposal_id}"): (
            "GET", f"/panel/review/item/{pid}?workspace={ws}", None),
        ("GET", "/v3/review/glossary-candidates"): (
            "GET", f"/v3/review/glossary-candidates?workspace={ws}", None),
        ("GET", "/v3/review"): ("GET", f"/v3/review?workspace={ws}", None),
        ("GET", "/v3/review/"): ("GET", f"/v3/review/?workspace={ws}", None),
        ("POST", "/v3/review/decide"): ("POST", "/v3/review/decide", {
            "workspace": ws, "proposal_id": pid, "human_decision": "REJECT",
            "request_id": str(uuid.uuid4()), "expected_proposal_hash": phash}),
        ("POST", "/v3/review/undo"): ("POST", "/v3/review/undo", {
            "workspace": ws, "proposal_id": pid, "request_id": str(uuid.uuid4())}),
    }


def _arbol(base: Path):
    return sorted(str(p.relative_to(base)) for p in base.rglob("*")) if base.exists() else None


def _lo_que_dice(respuesta) -> str:
    """El cuerpo y, en un 303, el `aviso` de la vuelta (PRG)."""
    return respuesta.text + " " + respuesta.headers.get("location", "")


def test_n3_ninguna_ruta_del_visor_da_500_ni_crea_nada_con_la_ruta_ausente(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch, tmp_path
):
    """TODA ruta consumidora, con CSRF valido y corrida real: controlada,
    nombrando el almacen, y sin crear nada."""
    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)
    token = _csrf(operador)
    original = almacenes["base"]
    huella_original = original.read_bytes()

    estado = tmp_path / "estado-ausente"
    estado.mkdir()
    monkeypatch.setenv(VAR, str(estado / "reviews-v3" / "review.sqlite3"))

    ctx = {"ws": str(propuesta.get("workspace") or "ws-cofradia"), "job_id": job_id,
           "proposal_id": str(propuesta["proposal_id"]),
           "proposal_hash": str(propuesta.get("proposal_hash") or "")}
    casos = _casos(ctx)
    inventariadas = inventario(real_app)
    assert len(inventariadas) >= 14, "N3 INVENTARIO VACIO O ROTO: %r" % (sorted(inventariadas),)
    sin_cubrir = inventariadas - set(casos)
    assert not sin_cubrir, "N3 RUTA CONSUMIDORA SIN CUBRIR: %r" % (sorted(sin_cubrir),)
    huerfanos = set(casos) - inventariadas
    assert not huerfanos, "N3 CASO HUERFANO (la ruta ya no consume o no existe): %r" % (
        sorted(huerfanos),)

    resultados: dict = {}
    for clave in sorted(inventariadas):
        metodo, url, datos = casos[clave]
        if metodo == "GET":
            r = operador.get(url)
        else:
            r = operador.post(url, data={**datos, "csrf_token": token}, follow_redirects=False)
        resultados[clave] = (r.status_code, _lo_que_dice(r))
        assert _arbol(estado) == [], "N3 EL RUNTIME CREO ALGO en %r: %r" % (clave, _arbol(estado))

    malas = {k: c for k, (c, _) in resultados.items() if c >= 500 and c != 503}
    assert not malas, "N3 RUTA CON 500: %r" % (malas,)
    en_csrf = {k: c for k, (c, _) in resultados.items() if k[0] == "POST" and c == 403}
    assert not en_csrf, "N3 POST MUERE EN CSRF ANTES DEL ALMACEN: %r" % (en_csrf,)
    mudas = {k: c for k, (c, texto) in resultados.items() if not _NOMBRA_EL_ALMACEN.search(texto)}
    assert not mudas, "N3 RUTA NO NOMBRA EL ALMACEN AUSENTE: %r" % (mudas,)
    assert original.read_bytes() == huella_original, "N3 SE TOCO EL ALMACEN ANTERIOR"

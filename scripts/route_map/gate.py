#!/usr/bin/env python3
"""PUERTA del censo de rutas: la configuración canónica vive en CÓDIGO.

POR QUÉ ESTE FICHERO EXISTE
---------------------------
`route_map.py` sabe decir QUÉ rutas hay y qué garantías puede sostener sobre
ellas. Lo que no hacía era comparar eso contra una DECLARACIÓN de lo que
debería haber, y sin esa comparación no hay puerta: un router que desaparece
del `include_router` se lleva consigo sus rutas y el mapa sale igual de verde,
porque el mapa describe lo que hay, no lo que tenía que haber.

La tentación evidente es escribir la declaración: una lista de routers, rutas y
métodos esperados, en YAML o en un documento. **Este repositorio ya decidió dos
veces que eso no vale:**

1. La CI enumeraba prefijos de rama y pasó a `branches: ['**']` — *«ya no
   estamos intentando enumerar el futuro»*.
2. `viewer/tests/test_provider_authz_fields_contract.py:94-111` documenta una
   **cuarentena congelada** de dimensiones de autorización: un revisor añadió un
   bypass nuevo **y su nombre a la lista en el mismo commit**, y la suite pasó
   verde. No se reforzó la lista: **se eliminó**.

> Una lista donde escribir un nombre para dejar de mirar es el antipatrón. Una
> aserción que se pone roja cuando el mundo cambia es la solución.

DÓNDE VIVE LA CONFIGURACIÓN CANÓNICA, ENTONCES
-----------------------------------------------
En cinco fuentes que **ya existen en el código por otros motivos** y que el
proceso **ejecuta**, no lee como documento. Ninguna hay que acordarse de
actualizar, porque ninguna es una copia de nada:

  D1  ROUTERS DECLARADOS — descubrimiento por enumeración del árbol
      `viewer/app/**.py`: todo módulo que asigna a nivel de módulo
      `X = APIRouter(...)` declara un router. **No hay lista**: crear el fichero
      lo declara, borrarlo lo retira. Añadir un router y olvidarse de montarlo
      es ROJO sin que nadie escriba nada en ninguna parte.

  D2  RUTAS Y MÉTODOS DECLARADOS — se importan esos módulos y se enumeran sus
      `router.routes`. La correspondencia con la app real se hace por
      **IDENTIDAD del objeto endpoint** (`id(func)`), no por path ni por nombre.
      Esto NO es un detalle de implementación: el path que guarda un `APIRouter`
      es el relativo, sin el prefijo que aporta `include_router`, y comparar por
      texto produce rojos **por el motivo equivocado** — medido en este árbol,
      el enumerador AST de `route_map` declara MUERTAS tres rutas
      (`GET /item/{entity_id}`, `GET /item/{proposal_id}`, `GET /ficha/{handle}`)
      que están vivas y montadas bajo el prefijo de su hueco. Un rojo por el
      motivo equivocado es más peligroso que un verde.

  D3  NOMBRES DE RUTA DECLARADOS — `app.chassis.NAV`. Cada entrada del menú
      apunta a un NOMBRE de ruta y el chasis existe precisamente para que ese
      nombre se resuelva contra las rutas montadas. Es la fuente que hace que
      **borrar una ruta sea ROJO**: la declaración (el menú) no desaparece con
      el handler.

  D4  HUECOS DE FUNCIONALIDAD — `app.chassis.FEATURE_SLOTS`. Declara, por hueco,
      módulo, prefijo, nombre de ruta y rol. Es la fuente que hace que
      **desmontar un panel sea ROJO** y, junto a D3, que **cambiar el método de
      una pantalla enlazada sea ROJO**: un enlace de menú y una pantalla de
      panel son navegación, o sea `GET`; si la ruta deja de servir `GET`, la
      declaración deja de cumplirse aunque el handler siga existiendo.

  D5  INTERRUPTORES DE PANEL — `app.chassis.FLAG_ENV_TEMPLATE`,
      `FLAG_ON_VALUES` y `slot_enabled`. El nombre de cada variable y el
      criterio de «encendido» se **derivan del chasis**, no se reescriben aquí:
      si el chasis cambia el nombre de sus banderas o lo que cuenta como
      encendido, esta puerta cambia con él. Si mañana hay un quinto hueco, su
      bandera entra sola.

POR QUÉ NO PUEDE QUEDARSE OBSOLETA EN SILENCIO
-----------------------------------------------
Porque no hay copia. D1 se descubre recorriendo el árbol; D2 se obtiene
ejecutando el `import`; D3/D4/D5 son objetos que la propia aplicación usa en
tiempo de arranque —si `NAV` apuntara a una ruta inexistente, `chassis.nav_for`
levanta y el visor no pinta el menú—. Quedarse obsoleta exigiría que el código
que la app ejecuta divergiese del código que la app ejecuta.

LO QUE ESTA PUERTA **NO** PUEDE AFIRMAR (declarado, no disimulado)
-------------------------------------------------------------------
Borrar una ruta a la que **nada canónico apunta** (ni `NAV`, ni un hueco, ni
otra ruta) no pone la puerta roja: no hay declaración que quede incumplida.
Cubrirlo exigiría enumerar las rutas en una lista, que es exactamente lo
prohibido. Se declara, se nombran las rutas afectadas en el artefacto
(`rutas_sin_declaracion_canonica`) y se cuentan sólo las que sí lo están.

CONTRATO (cada punto tiene un caso ROJO en `calibrate_gate.py`)
----------------------------------------------------------------
  C1  router declarado -> montado                    (`router-declarado-no-montado`)
  C2  ruta declarada -> existe                       (`ruta-declarada-no-montada`)
  C3  método declarado -> coincide                   (`metodo-declarado-no-coincide`)
  C4  ruta/método inesperado -> clasificado          (`ruta-sin-clasificar`)
  C5  nombre canónico -> resuelve y sirve GET        (`nombre-canonico-no-resuelve`)
  C6  configuración vacía -> ROJO                    (`configuracion-vacia`)
  C7  configuración ausente -> ROJO                  (`configuracion-ausente`)
  C8  panel encendido cuando debía estar apagado     (`panel-encendido`)
  C9  el censo no inspeccionó la app real -> ROJO    (`censo-no-inspecciono-la-app-real`)
  C10 el censo se declaró incompleto -> ROJO         (`censo-en-rojo`)

Uso:
    PYTHONPATH=scripts python3 scripts/route_map/gate.py --repo . \
        --map artifacts/route-map/route_map.json \
        --out artifacts/route-map/gate.json
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from route_map.route_map import (  # noqa: E402
    KIND_ESTATICO,
    KIND_OPACO,
    iter_effective_routes,
    load_real_app,
)

#: Familia de variables de entorno de los interruptores de panel. Se usa SÓLO
#: para barrer el entorno en busca de banderas que el chasis no conozca (un
#: hueco borrado del contrato pero con su bandera todavía exportada en el CI);
#: el criterio de «encendido» y el nombre de las banderas vivas los da el
#: chasis, no esta expresión.
RE_FAMILIA_PANEL = re.compile(r"^S9K_PANEL_[A-Z0-9_]+_ENABLED$")

#: Métodos que un enlace de navegación puede ejercer. Un `<a href>` y una
#: pantalla de panel son GET; no es una convención de esta puerta, es lo que
#: hace un navegador al seguir un enlace.
METODO_DE_NAVEGACION = "GET"


# ---------------------------------------------------------------------------
# D1 — routers declarados: descubrimiento, no lista
# ---------------------------------------------------------------------------

def descubrir_routers(repo: Path) -> list[dict]:
    """Todo módulo de `viewer/app/**` que asigna `X = APIRouter(...)`.

    Por AST y a nivel de módulo: un `APIRouter` construido dentro de una función
    es una fábrica (el chasis tiene una), no un router declarado que alguien
    deba montar.
    """
    raiz = repo / "viewer" / "app"
    out: list[dict] = []
    for py in sorted(raiz.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for nodo in arbol.body:
            if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, ast.Call):
                continue
            fn = nodo.value.func
            nombre = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if nombre != "APIRouter":
                continue
            for destino in nodo.targets:
                if not isinstance(destino, ast.Name):
                    continue
                rel = py.relative_to(repo)
                modulo = ".".join(rel.parts[1:]).removesuffix(".py")
                out.append({
                    "modulo": modulo,
                    "atributo": destino.id,
                    "fichero": str(rel),
                    "linea": nodo.lineno,
                })
    return out


def _rutas_de_router(router) -> list:
    """Rutas de un `APIRouter`, descendiendo por sub-routers montados."""
    salida = []
    for r in getattr(router, "routes", []):
        sub = getattr(r, "app", None)
        if hasattr(sub, "routes") and not hasattr(r, "endpoint"):
            salida.extend(_rutas_de_router(sub))
        else:
            salida.append(r)
    return salida


def declaracion_de_rutas(routers: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    """D2: `{id(endpoint) -> declaración}` importando cada router declarado."""
    decl: dict[int, dict] = {}
    fallos: list[dict] = []
    for rec in routers:
        try:
            mod = importlib.import_module(rec["modulo"])
        except Exception as exc:
            fallos.append({**rec, "motivo": "modulo-no-importable", "detalle": repr(exc)})
            continue
        router = getattr(mod, rec["atributo"], None)
        if router is None:
            fallos.append({**rec, "motivo": "atributo-ausente",
                           "detalle": f"{rec['modulo']} no expone {rec['atributo']!r}"})
            continue
        for ruta in _rutas_de_router(router):
            ep = getattr(ruta, "endpoint", None)
            if ep is None:
                continue
            metodos = frozenset(getattr(ruta, "methods", None) or [])
            decl[id(ep)] = {
                "modulo": rec["modulo"],
                "atributo": rec["atributo"],
                "fichero": rec["fichero"],
                "path_relativo": getattr(ruta, "path", "?"),
                "endpoint": getattr(ep, "__qualname__", str(ep)),
                "metodos_declarados": sorted(metodos),
                "_ref": ep,
            }
    return decl, fallos


# ---------------------------------------------------------------------------
# La app real, enumerada con el MISMO censo que emite el artefacto
# ---------------------------------------------------------------------------

def enumerar_app(app) -> dict[str, Any]:
    filas: list[dict] = []
    por_endpoint: dict[int, list[dict]] = {}
    for path, metodos, _dep, endpoint, hr, kind, motivo in iter_effective_routes(app):
        fila = {
            "path": path,
            "metodos": sorted(metodos) if metodos else [],
            "kind": kind,
            "motivo": motivo,
            "endpoint": endpoint,
            # Nombre de la ruta TAL COMO LO RESUELVE el enrutador real: es el
            # objeto `Route` original, el mismo contra el que `url_for` y
            # `chassis.nav_for` resuelven los enlaces del menú.
            "nombre_ruta": getattr(hr, "name", None),
        }
        filas.append(fila)
        if endpoint is not None:
            por_endpoint.setdefault(id(endpoint), []).append(fila)
    return {"filas": filas, "por_endpoint": por_endpoint}


def _fichero_fuente(endpoint) -> str | None:
    import inspect

    try:
        return inspect.getsourcefile(inspect.unwrap(endpoint))
    except Exception:
        return None


def _claves(filas: list[dict]) -> set[str]:
    """Claves `MÉTODO /path` de las filas HTTP (las mismas del artefacto)."""
    out: set[str] = set()
    for f in filas:
        if f["kind"] in (KIND_OPACO, KIND_ESTATICO):
            continue
        for m in f["metodos"]:
            out.add(f"{m} {f['path']}")
    return out


# ---------------------------------------------------------------------------
# La puerta
# ---------------------------------------------------------------------------

def evaluar(repo: Path, mapa: dict | None, mapa_rc: int | None = None,
            entorno: dict | None = None, solo_declaracion: bool = False) -> dict:
    entorno = os.environ if entorno is None else entorno
    hallazgos: dict[str, list[dict]] = {k: [] for k in (
        "configuracion-ausente", "configuracion-vacia", "panel-encendido",
        "router-declarado-no-montado", "ruta-declarada-no-montada",
        "metodo-declarado-no-coincide", "ruta-sin-clasificar",
        "nombre-canonico-no-resuelve", "censo-no-inspecciono-la-app-real",
        "censo-en-rojo",
    )}

    # --- C7: la configuración canónica tiene que EXISTIR ------------------
    app = None
    ch = None
    try:
        app = load_real_app(repo)
        ch = importlib.import_module("app.chassis")
    except Exception as exc:
        hallazgos["configuracion-ausente"].append({
            "fuente": "app.main / app.chassis",
            "detalle": f"no se pudo cargar la configuración canónica: {exc!r}",
        })
        return _cerrar(repo, hallazgos, {}, mapa, mapa_rc, solo_declaracion)

    # C7 es un DETECTOR PURO, y eso es deliberado: si se ablase, la evaluación
    # tiene que seguir corriendo (con la declaración degradada) en vez de
    # reventar. Un control que al quitarlo produce una excepción no se puede
    # calibrar: no distinguiría «hacía falta» de «rompí el arnés».
    for atributo in ("FEATURE_SLOTS", "NAV", "FLAG_ENV_TEMPLATE", "FLAG_ON_VALUES",
                     "slot_enabled", "slot_flag_env"):
        if not hasattr(ch, atributo):
            hallazgos["configuracion-ausente"].append({
                "fuente": f"app.chassis.{atributo}",
                "detalle": ("el chasis es la fuente canónica de esta puerta y ya no "
                            "expone este elemento: sin él no hay nada que exigir"),
            })

    routers = descubrir_routers(repo)
    decl, fallos_import = declaracion_de_rutas(routers)
    real = enumerar_app(app)
    slots = tuple(getattr(ch, "FEATURE_SLOTS", ()) or ())
    nav = tuple(getattr(ch, "NAV", ()) or ())

    # --- C6: y tiene que decir ALGO ---------------------------------------
    # Un arnés que pasa con 0 casos está roto. Aquí el suelo cuenta sólo lo
    # RESOLUBLE (rutas con path y métodos enumerables), nunca las opacas: si
    # las opacas contasen, el suelo se satisfaría solo.
    resolubles = [f for f in real["filas"]
                  if f["kind"] not in (KIND_OPACO, KIND_ESTATICO) and f["metodos"]]
    for nombre, valor, minimo in (
        ("routers descubiertos (D1)", len(routers), 1),
        ("endpoints declarados por routers (D2)", len(decl), 1),
        ("entradas de app.chassis.NAV (D3)", len(nav), 1),
        ("huecos de app.chassis.FEATURE_SLOTS (D4)", len(slots), 1),
        ("rutas montadas con path resoluble", len(resolubles), 1),
    ):
        if valor < minimo:
            hallazgos["configuracion-vacia"].append({
                "fuente": nombre,
                "valor": valor,
                "detalle": ("la declaración canónica está vacía: una puerta que no "
                            "exige nada pasa siempre. Vacío es ROJO, no verde"),
            })

    for f in fallos_import:
        hallazgos["router-declarado-no-montado"].append({
            "router": f"{f['modulo']}.{f['atributo']}",
            "fichero": f["fichero"],
            "motivo": f["motivo"],
            "detalle": f["detalle"],
        })

    # --- C8: los cuatro paneles APAGADOS, comprobado, no confiado ---------
    # El nombre de cada bandera y el criterio de «encendido» los da el chasis.
    encendidos_declarados = set()
    _flag_env = getattr(ch, "slot_flag_env", lambda s: f"S9K_PANEL_{s.key.upper()}_ENABLED")
    _encendido = getattr(ch, "slot_enabled", None)
    _valores_on = frozenset(getattr(ch, "FLAG_ON_VALUES", ()) or ())
    for slot in slots:
        var = _flag_env(slot)
        encendidos_declarados.add(var)
        if _encendido is not None and _encendido(slot, dict(entorno)):
            hallazgos["panel-encendido"].append({
                "hueco": slot.key,
                "variable": var,
                "valor": entorno.get(var),
                "detalle": ("la puerta mide la configuración que se DESPLIEGA y el "
                            "chasis declara que apagados es lo correcto para "
                            "producción; con un panel encendido este censo mide una "
                            "app y certifica otra"),
            })
    # Y una bandera de la familia que el chasis ya no reconoce (hueco retirado
    # del contrato pero bandera todavía exportada) también cuenta: encender algo
    # que nadie declara es peor, no mejor.
    for var, valor in sorted(dict(entorno).items()):
        if not RE_FAMILIA_PANEL.match(var) or var in encendidos_declarados:
            continue
        if str(valor).strip().lower() in _valores_on:
            hallazgos["panel-encendido"].append({
                "hueco": "(no declarado en FEATURE_SLOTS)",
                "variable": var,
                "valor": valor,
                "detalle": ("bandera de panel encendida que el chasis ya no reconoce: "
                            "o sobra en el entorno o falta el hueco en el contrato"),
            })

    # --- C1/C2/C3: declarado -> montado, con el método que se declaró -----
    modulos_con_ruta_montada: dict[str, int] = {}
    for id_ep, d in sorted(decl.items(), key=lambda kv: (kv[1]["modulo"],
                                                         kv[1]["path_relativo"])):
        filas = real["por_endpoint"].get(id_ep)
        if not filas:
            hallazgos["ruta-declarada-no-montada"].append({
                "router": f"{d['modulo']}.{d['atributo']}",
                "endpoint": d["endpoint"],
                "path_relativo": d["path_relativo"],
                "metodos_declarados": d["metodos_declarados"],
                "detalle": ("el router declara esta ruta y la app real no la sirve: "
                            "está definida y muerta"),
            })
            continue
        modulos_con_ruta_montada[d["modulo"]] = modulos_con_ruta_montada.get(
            d["modulo"], 0) + 1
        montados = sorted({m for f in filas for m in f["metodos"]})
        if montados != d["metodos_declarados"]:
            hallazgos["metodo-declarado-no-coincide"].append({
                "router": f"{d['modulo']}.{d['atributo']}",
                "endpoint": d["endpoint"],
                "paths_montados": sorted({f["path"] for f in filas}),
                "metodos_declarados": d["metodos_declarados"],
                "metodos_montados": montados,
                "detalle": ("la app sirve este endpoint con un conjunto de métodos "
                            "distinto del que declara su router"),
            })

    # C1: un router declarado sin NINGUNA ruta en la app está desmontado.
    for rec in routers:
        if rec["modulo"] in modulos_con_ruta_montada:
            continue
        declaradas = [d for d in decl.values() if d["modulo"] == rec["modulo"]]
        if not declaradas:
            # Router declarado y VACÍO: no aporta rutas, no se puede exigir
            # montaje de nada. No es un hallazgo, pero se publica.
            continue
        if any(h["router"] == f"{rec['modulo']}.{rec['atributo']}"
               for h in hallazgos["router-declarado-no-montado"]):
            continue
        hallazgos["router-declarado-no-montado"].append({
            "router": f"{rec['modulo']}.{rec['atributo']}",
            "fichero": rec["fichero"],
            "motivo": "sin-ninguna-ruta-en-la-app",
            "rutas_declaradas": [d["path_relativo"] for d in declaradas],
            "detalle": ("el módulo declara un router con rutas y la app real no sirve "
                        "ninguna de ellas: nadie lo incluyó"),
        })

    # --- C4: toda ruta montada tiene que quedar CLASIFICADA ---------------
    # No es una lista blanca: la clase se DERIVA (identidad del endpoint,
    # fichero fuente real, tipo del montaje). Una ruta que aparezca de otro
    # sitio —una librería, un endpoint generado en tiempo de ejecución— no
    # encaja en ninguna clase y pone la puerta roja sin que nadie mantenga nada.
    viewer_app = (repo / "viewer" / "app").resolve()
    clasificacion: dict[str, str] = {}
    for f in real["filas"]:
        etiqueta = f"{'|'.join(f['metodos']) or '<sin-metodos>'} {f['path']}"
        if f["kind"] == KIND_ESTATICO:
            clasificacion[etiqueta] = "montaje-estatico-caracterizado"
            continue
        if f["kind"] == KIND_OPACO:
            # El censo ya la declara opaca y sale en rojo por su cuenta (C10);
            # aquí se clasifica como tal para no acusar dos veces del mismo.
            clasificacion[etiqueta] = f"opaca:{f['motivo']}"
            continue
        ep = f["endpoint"]
        if ep is not None and id(ep) in decl:
            clasificacion[etiqueta] = f"router-declarado:{decl[id(ep)]['modulo']}"
            continue
        fuente = _fichero_fuente(ep) if ep is not None else None
        if fuente:
            try:
                rel = Path(fuente).resolve().relative_to(viewer_app)
            except ValueError:
                rel = None
            if rel is not None:
                clasificacion[etiqueta] = f"modulo-de-la-app:{rel.as_posix()}"
                continue
        clasificacion[etiqueta] = "SIN-CLASIFICAR"
        hallazgos["ruta-sin-clasificar"].append({
            "ruta": etiqueta,
            "endpoint": getattr(ep, "__qualname__", repr(ep)),
            "fichero_fuente": fuente,
            "detalle": ("ruta montada que no procede de ningún router declarado ni de "
                        "un módulo de `viewer/app`, y que no es un montaje estático "
                        "caracterizado: el instrumento no sabe de dónde salió"),
        })

    # --- C5: los nombres canónicos resuelven, y sirven navegación ---------
    nombres_montados: dict[str, list[str]] = {}
    for f in real["filas"]:
        if f["nombre_ruta"]:
            nombres_montados.setdefault(f["nombre_ruta"], []).extend(f["metodos"])

    declarados_por_nombre: list[tuple[str, str]] = [
        (item.route_name, f"app.chassis.NAV[{item.label!r}]") for item in nav
    ]
    declarados_por_nombre += [
        (s.route_name, f"app.chassis.FEATURE_SLOTS[{s.key!r}]") for s in slots
    ]
    for nombre_ruta, fuente in declarados_por_nombre:
        metodos = nombres_montados.get(nombre_ruta)
        if metodos is None:
            hallazgos["nombre-canonico-no-resuelve"].append({
                "nombre_ruta": nombre_ruta,
                "declarado_en": fuente,
                "motivo": "ruta-inexistente",
                "detalle": ("la configuración canónica declara esta ruta por su nombre "
                            "y la app real no la tiene montada: la ruta se eliminó y "
                            "la declaración quedó incumplida"),
            })
        elif METODO_DE_NAVEGACION not in metodos:
            hallazgos["nombre-canonico-no-resuelve"].append({
                "nombre_ruta": nombre_ruta,
                "declarado_en": fuente,
                "motivo": "metodo-cambiado",
                "metodos_montados": sorted(set(metodos)),
                "detalle": ("la declaración canónica la usa como destino de navegación "
                            f"(un enlace de menú o la pantalla de un hueco son "
                            f"{METODO_DE_NAVEGACION}) y la ruta ya no sirve ese método"),
            })

    # --- inventario de lo que NO tiene declaración canónica ---------------
    # No es un hallazgo: es la limitación, nombrada elemento a elemento en vez
    # de resumida en un número. Borrar una de éstas no pone la puerta roja.
    nombres_declarados = {n for n, _ in declarados_por_nombre}
    sin_declaracion = []
    for f in real["filas"]:
        if f["nombre_ruta"] and f["nombre_ruta"] in nombres_declarados:
            continue
        sin_declaracion.append(f"{'|'.join(f['metodos']) or '-'} {f['path']}")

    resumen = {
        "routers_declarados": [f"{r['modulo']}.{r['atributo']}" for r in routers],
        "endpoints_declarados": len(decl),
        "entradas_nav": len(nav),
        "huecos": [s.key for s in slots],
        "banderas_de_panel": {_flag_env(s): entorno.get(_flag_env(s))
                              for s in slots},
        "rutas_montadas_resolubles": len(resolubles),
        "clasificacion": clasificacion,
        "nombres_canonicos_exigidos": sorted(nombres_declarados),
        "rutas_sin_declaracion_canonica": sorted(set(sin_declaracion)),
        "claves_vivas": sorted(_claves(real["filas"])),
    }
    return _cerrar(repo, hallazgos, resumen, mapa, mapa_rc, solo_declaracion)


# ---------------------------------------------------------------------------
# C9/C10 — el censo tiene que haber inspeccionado ESTA app, y haber salido bien
# ---------------------------------------------------------------------------

def _head(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _cerrar(repo: Path, hallazgos: dict, resumen: dict, mapa: dict | None,
            mapa_rc: int | None, solo_declaracion: bool = False) -> dict:
    if solo_declaracion:
        # MODO CALIBRACIÓN. Evalúa SÓLO C1-C8 (la declaración canónica contra la
        # app real) y no exige artefacto de censo. Existe para que cada control
        # se pueda ablar y observar por separado: en modo completo, casi
        # cualquier mutación de rutas dispara además C9 («el artefacto describe
        # otras rutas»), y un rojo por el motivo equivocado no calibra nada.
        # `calibrate_gate.py` comprueba que NINGÚN workflow lo pasa.
        return {"modo": "solo-declaracion", "hallazgos": hallazgos,
                "resumen": resumen, "head": _head(repo)}
    if mapa is None:
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "artefacto-ausente",
            "detalle": ("no hay artefacto de censo que evaluar: una puerta sin medida "
                        "no es una puerta"),
        })
        return {"hallazgos": hallazgos, "resumen": resumen, "head": _head(repo)}

    if mapa_rc is not None and mapa_rc != 0:
        hallazgos["censo-en-rojo"].append({
            "motivo": "codigo-de-salida",
            "rc": mapa_rc,
            "detalle": ("el censo salió con código distinto de 0: sus hallazgos no se "
                        "pueden citar como garantía (3 = censo incompleto, "
                        "2 = control positivo del CSRF fallido)"),
        })

    for nombre in ("censo_opaco", "censo_vacio", "caracterizacion_estatica_fallida",
                   "control_positivo_csrf_fallido", "barrido_contamino_la_db"):
        items = (mapa.get("findings") or {}).get(nombre) or []
        if items:
            hallazgos["censo-en-rojo"].append({
                "motivo": nombre,
                "n": len(items),
                "ejemplos": [i.get("path") or i.get("key") for i in items[:5]],
                "detalle": "el propio censo se declara incompleto o no creíble",
            })

    # Duros del mapa: si aparecen, la puerta es roja igual que el censo.
    for nombre in ("enlaces_rotos", "rutas_sin_auth", "rutas_capturadas",
                   "guardian_declarado_pero_no_aplicado",
                   "contradiccion_deniega_y_sirve"):
        items = (mapa.get("findings") or {}).get(nombre) or []
        if items:
            hallazgos["censo-en-rojo"].append({
                "motivo": nombre,
                "n": len(items),
                "ejemplos": [i.get("key") or i.get("raw") for i in items[:5]],
                "detalle": "hallazgo duro del censo",
            })

    counts = mapa.get("counts") or {}
    head_repo = _head(repo)
    head_mapa = (mapa.get("head") or "").strip()

    if not counts.get("montadas"):
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "cero-rutas-montadas",
            "detalle": "el censo no observó ni una ruta",
        })
    if head_repo and head_mapa and head_mapa != head_repo:
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "head-distinto",
            "head_artefacto": head_mapa,
            "head_repo": head_repo,
            "detalle": ("el artefacto describe otro árbol: un artefacto viejo dejaría "
                        "pasar cualquier cambio de este"),
        })
    if mapa.get("probe_error"):
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "sonda-fallida",
            "detalle": str(mapa["probe_error"])[:400],
        })
    if mapa.get("sondas_estaticas") is None:
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "sin-sonda",
            "detalle": ("el censo se ejecutó con `--skip-probe`: sin sonda, la "
                        "caracterización de los montajes estáticos no la ha "
                        "comprobado nadie y la autorización no se midió"),
        })
    if not mapa.get("tested_source"):
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "sin-cobertura",
            "detalle": ("el censo no recibió `--tested`: no hay constancia de que "
                        "ninguna petición atravesara la app real"),
        })
    elif not counts.get("probadas"):
        hallazgos["censo-no-inspecciono-la-app-real"].append({
            "motivo": "cobertura-cero",
            "detalle": ("`--tested` no ejercitó NI UNA ruta de la app real: el fichero "
                        "de cobertura es de otra corrida o la sonda no se cargó. Un "
                        "arnés que pasa con 0 casos está roto"),
        })

    # Comparación de conjuntos: el artefacto tiene que describir EXACTAMENTE
    # las rutas que este proceso acaba de ver en la app real.
    if resumen.get("claves_vivas") is not None:
        vivas = set(resumen.get("claves_vivas") or [])
        del_mapa = {r["key"] for r in (mapa.get("routes") or [])}
        if vivas and del_mapa and vivas != del_mapa:
            hallazgos["censo-no-inspecciono-la-app-real"].append({
                "motivo": "conjunto-de-rutas-distinto",
                "solo_en_la_app": sorted(vivas - del_mapa)[:20],
                "solo_en_el_artefacto": sorted(del_mapa - vivas)[:20],
                "detalle": ("el artefacto y la app real no coinciden en qué rutas "
                            "existen: el censo no midió esta app"),
            })

    return {"hallazgos": hallazgos, "resumen": resumen, "head": head_repo,
            "head_artefacto": head_mapa, "counts_censo": counts}


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--map", dest="mapa", default=None,
                    help="artefacto JSON de route_map.py")
    ap.add_argument("--map-rc", dest="mapa_rc", type=int, default=None,
                    help="código de salida con el que terminó route_map.py")
    ap.add_argument("--out", default=None)
    ap.add_argument("--solo-declaracion", action="store_true",
                    help="SÓLO CALIBRACIÓN: evalúa C1-C8 sin exigir artefacto de censo")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    mapa = None
    if a.mapa and Path(a.mapa).exists():
        try:
            mapa = json.loads(Path(a.mapa).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"artefacto de censo ilegible: {exc!r}", file=sys.stderr)
            mapa = None

    res = evaluar(repo, mapa, a.mapa_rc, solo_declaracion=a.solo_declaracion)
    texto = json.dumps(res, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(texto, encoding="utf-8")

    total = 0
    if a.solo_declaracion:
        print("*** MODO CALIBRACION (--solo-declaracion): C9 y C10 NO se evaluan. "
              "Esta invocacion NO es una puerta. ***")
    print("PUERTA DEL CENSO DE RUTAS")
    print(f"  HEAD: {res.get('head') or '(sin git)'}")
    r = res.get("resumen") or {}
    if r:
        print(f"  routers declarados: {len(r.get('routers_declarados') or [])}"
              f" · endpoints declarados: {r.get('endpoints_declarados')}"
              f" · NAV: {r.get('entradas_nav')}"
              f" · huecos: {','.join(r.get('huecos') or []) or '-'}")
        print(f"  rutas montadas resolubles: {r.get('rutas_montadas_resolubles')}"
              f" · nombres canónicos exigidos: "
              f"{len(r.get('nombres_canonicos_exigidos') or [])}")
        print(f"  banderas de panel: {r.get('banderas_de_panel')}")
    for nombre, items in res["hallazgos"].items():
        total += len(items)
        print(f"  {nombre}: {len(items)}")
    if total:
        print("", file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        print("PUERTA DEL CENSO DE RUTAS: ROJA", file=sys.stderr)
        for nombre, items in res["hallazgos"].items():
            for i in items:
                print(f"  [{nombre}] " + "; ".join(
                    f"{k}={v}" for k, v in i.items() if k != "detalle"), file=sys.stderr)
                if i.get("detalle"):
                    print(f"      {i['detalle']}", file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        return 1
    print("PUERTA VERDE: la configuración canónica se cumple punto por punto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

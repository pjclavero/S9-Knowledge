#!/usr/bin/env python3
"""Calibración de la PUERTA del censo de rutas (`gate.py`).

Ningún gate entra sin control negativo conocido. Aquí se reproduce **primero el
VERDE** y después se pone **ROJO cada punto del contrato**, con una mutación
real por punto, y se comprueba la **necesidad** de cada criterio por ablación.

REGLAS DE LA CASA QUE SE RESPETAN AQUÍ
---------------------------------------
* **Un proceso por mutación.** `route_map`, `app.main` y `app.chassis` son
  singletons en `sys.modules`: mutar dos cosas en el mismo proceso las acumula y
  las corridas siguientes salen rojas *por el motivo equivocado*, que es peor
  que un verde.
* **Nada se muta en el árbol real.** Cada caso trabaja sobre una **copia** en un
  temporal. Al terminar se comprueba por **hash SHA-256 de contenido** que ni un
  byte de `viewer/` ni de `scripts/route_map/` ha cambiado — no por presencia de
  cadenas, que no distingue «el arreglo está» de «la palabra está».
* **`__pycache__` purgado** en cada copia, y `PYTHONDONTWRITEBYTECODE=1` en cada
  subproceso: un árbol limpio no demuestra que el proceso ejecute ese árbol.
  `shutil.copy2` preserva la mtime y CPython revalida el `.pyc`, así que un
  `__pycache__` copiado ejecutaría el código de ANTES de la mutación y el caso
  saldría verde sin haber probado nada.
* **Un rojo se cobra sólo si es del motivo esperado.** Se comprueba la clave del
  hallazgo, no el mero código de salida.
* **Una ablación se cobra sólo si vuelve VERDE un caso que estaba ROJO.** Un
  control que no cambia ningún resultado no se cobra: si al quitarlo el caso
  sigue rojo por otra vía, ese control no es el que lo sostiene.
* **El arnés no puede pasar con 0 casos:** hay suelos explícitos, y cuentan sólo
  los casos que llegaron a ejecutarse.

Uso:
    PYTHONPATH=scripts python3 scripts/route_map/calibrate_gate.py \
        --out artifacts/route-map/calibracion-gate.json
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Suelos del arnés. Si la carga real baja de aquí, el arnés se declara roto en
#: vez de salir verde por no haber probado nada.
MINIMO_CASOS = 30
#: Y ademas, controles concretos que TIENEN que haber corrido (ver `main`).
MINIMO_ABLACIONES = 13


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------

def hash_arbol(raices: list[Path]) -> str:
    """SHA-256 del CONTENIDO de un conjunto de ficheros, no de sus nombres."""
    h = hashlib.sha256()
    for raiz in sorted(raices):
        for f in sorted(p for p in raiz.rglob("*") if p.is_file()):
            if "__pycache__" in f.parts:
                continue
            h.update(str(f.relative_to(REPO)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def copia(destino: Path) -> Path:
    """Copia trabajable de `viewer/` y `scripts/` sin un solo `.pyc`."""
    def ignorar(_d, nombres):
        return [n for n in nombres if n in ("__pycache__", ".pytest_cache", "node_modules")]

    # `contracts/` va porque `app.review_status_contract` carga
    # `contracts/review-status/v1/model.py` en tiempo de import: sin él la app
    # no arranca y TODOS los casos saldrían rojos por `configuracion-ausente`,
    # o sea por el motivo equivocado. El caso G0 (árbol limpio) es justo el que
    # lo detecta si mañana aparece otra dependencia de arranque.
    for sub in ("viewer", "scripts", "contracts"):
        shutil.copytree(REPO / sub, destino / sub, ignore=ignorar, symlinks=True)
    # Cinturón y tirantes: si algo se coló, fuera.
    for pyc in destino.rglob("*.pyc"):
        pyc.unlink()
    for d in list(destino.rglob("__pycache__")):
        shutil.rmtree(d, ignore_errors=True)
    return destino


def sustituir(fichero: Path, viejo: str, nuevo: str, veces: int = 1) -> None:
    """Sustitución EXIGENTE: si no aparece el número de veces previsto, levanta.

    Una mutación que no se aplicó y un caso que sale verde son indistinguibles
    si nadie comprueba que la mutación entró.
    """
    texto = fichero.read_text(encoding="utf-8")
    n = texto.count(viejo)
    if n != veces:
        raise AssertionError(
            f"mutación no aplicable: {fichero.name} contiene {n} ocurrencias de "
            f"{viejo[:60]!r}, se esperaban {veces}")
    fichero.write_text(texto.replace(viejo, nuevo), encoding="utf-8")


def ejecutar(raiz: Path, mapa: Path | None = None, mapa_rc: int | None = None,
             entorno_extra: dict | None = None,
             solo_declaracion: bool = True, repo: Path | None = None) -> dict:
    """Un subproceso por invocación. Devuelve `{rc, hallazgos, stderr}`.

    `raiz` es de dónde sale el INSTRUMENTO (la copia, posiblemente ablada) y
    `repo` de dónde sale el ÁRBOL AUDITADO. Los casos de artefacto (C9/C10)
    apuntan al repositorio real, sin mutar: necesitan un `git rev-parse` que
    responda, y un temporal no es un repositorio git.

    ARTEFACTO DEL ARNÉS, ANOTADO PARA QUE NADIE LO CONFUNDA CON UNA DETECCIÓN:
    si estos casos se ejecutaran contra la copia (que no tiene `.git`), **A2
    fallaría por construcción** —`_head()` devuelve cadena vacía y la
    comparación de HEAD se salta, así que el caso no puede ponerse rojo—. Por eso
    apuntan a `REPO`. Un A2 rojo desde una copia sin `.git` sería un defecto del
    arnés, no una detección de la puerta; es exactamente el género de confusión
    que ya costó una ronda en este proyecto.
    """
    salida = raiz / "gate_out.json"
    cmd = [sys.executable, str(raiz / "scripts" / "route_map" / "gate.py"),
           "--repo", str(repo or raiz), "--out", str(salida)]
    if solo_declaracion:
        cmd.append("--solo-declaracion")
    if mapa is not None:
        cmd += ["--map", str(mapa)]
    if mapa_rc is not None:
        cmd += ["--map-rc", str(mapa_rc)]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(raiz / "scripts")
    # El entorno del que calibra no puede contaminar la medida.
    for k in list(env):
        if k.startswith("S9K_"):
            env.pop(k)
    env.update(entorno_extra or {})
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(raiz))
    hallazgos = {}
    if salida.exists():
        try:
            hallazgos = json.loads(salida.read_text(encoding="utf-8")).get("hallazgos", {})
        except Exception:
            hallazgos = {}
    return {"rc": p.returncode,
            "motivos": sorted(k for k, v in hallazgos.items() if v),
            "hallazgos": hallazgos,
            "stderr": p.stderr[-2000:], "stdout": p.stdout[-2000:]}


# ---------------------------------------------------------------------------
# mutaciones: una función por caso, sobre la COPIA
# ---------------------------------------------------------------------------

MAIN = ("viewer", "app", "main.py")
CHASIS = ("viewer", "app", "chassis.py")
READONLY = ("viewer", "app", "routers", "readonly.py")

#: Decorador de `GET /entities`, la pantalla que `app.chassis.NAV` declara con
#: el nombre `entities_page`. Se localiza por su texto exacto y la sustitución
#: es exigente, así que si el visor lo cambia, la calibración levanta en vez de
#: pasar en verde sobre una mutación que no entró.
DEC_ENTITIES = '@router.get("/entities", response_class=HTMLResponse)'


def m_router_desmontado(raiz: Path) -> None:
    sustituir(raiz.joinpath(*MAIN),
              "app.include_router(readonly_router.router)",
              "# DESMONTADO POR CALIBRACION")


def m_ruta_eliminada(raiz: Path) -> None:
    # La pantalla desaparece del enrutador; su nombre sigue declarado en `NAV`.
    sustituir(raiz.joinpath(*READONLY), DEC_ENTITIES, "# RUTA ELIMINADA POR CALIBRACION")


def m_metodo_cambiado(raiz: Path) -> None:
    sustituir(raiz.joinpath(*READONLY), DEC_ENTITIES,
              DEC_ENTITIES.replace("@router.get(", "@router.post(", 1))


def m_metodo_divergente(raiz: Path) -> None:
    # El mismo endpoint, montado además con un método que su router no declara.
    _apendice(raiz, """

# --- calibración: método montado que el router no declara -------------------
app.add_api_route("/entities-divergente", readonly_router.entities_page,
                  methods=["POST"], name="calibracion_divergente")
""")


def m_ruta_declarada_no_montada(raiz: Path) -> None:
    """El router declara `GET /account` y la app monta todo MENOS esa ruta.

    Primera versión de este caso: añadir una ruta al router DESPUÉS del
    `include_router`. **No sirve, y merece constar**: en FastAPI 0.139 el
    `include_router` deja una referencia VIVA al router (`_IncludedRouter`), así
    que la ruta tardía se monta igual y el caso salía VERDE — un caso que no
    puede ponerse rojo no calibra nada. Se sustituyó por una inclusión parcial,
    que sí produce la divergencia que se quiere detectar.

    `/account` se elige porque NO es destino de ninguna entrada de `NAV`: así el
    único control que puede ponerse rojo es C2, y la ablación es atribuible.
    """
    sustituir(raiz.joinpath(*MAIN),
              "app.include_router(auth_router.router)",
              "from fastapi import APIRouter as _AR_CALIB  # noqa: E402\n"
              "_parcial_calib = _AR_CALIB()\n"
              "_parcial_calib.routes = [_r for _r in auth_router.router.routes\n"
              "                         if getattr(_r, 'path', '') != '/account']\n"
              "app.include_router(_parcial_calib)")


def m_ruta_sin_clasificar(raiz: Path) -> None:
    # Endpoint que no procede de ningún router declarado ni de `viewer/app`.
    ajeno = raiz / "scripts" / "_endpoint_ajeno_calibracion.py"
    ajeno.write_text("async def colada():\n    return {}\n", encoding="utf-8")
    _apendice(raiz, """

# --- calibración: endpoint de fuera del árbol de la aplicación --------------
import _endpoint_ajeno_calibracion as _ajeno  # noqa: E402
app.add_api_route("/colada", _ajeno.colada, methods=["GET"], name="calibracion_colada")
""")


def m_configuracion_vacia(raiz: Path) -> None:
    """La declaración canónica de nombres de ruta se queda a cero.

    Se vacía `NAV` y NO `FEATURE_SLOTS`: vaciar los huecos además DESMONTA los
    cuatro paneles (`_mount_feature_slots` itera esa tupla), y entonces el rojo
    lo produce C1, no C6. Un rojo por el motivo equivocado hace inatribuible la
    ablación: medido, con las dos vacías `AB-C6` no se cobraba.
    """
    _apendice_chasis(raiz, "\nNAV = ()\n")


def m_configuracion_ausente_atributo(raiz: Path) -> None:
    _apendice_chasis(raiz, "\ndel FLAG_ON_VALUES\n")


def m_configuracion_ausente_modulo(raiz: Path) -> None:
    raiz.joinpath(*CHASIS).unlink()


def m_router_no_importable(raiz: Path) -> None:
    """Un modulo de router que declara `router` y NO se puede importar.

    Es el caso que demuestra que C1 **no** es un adorno de diagnostico: aqui D2
    no llega a ver ni una ruta (el `import` falla), asi que ni C2 ni C5 tienen
    nada que decir, y el UNICO control que se pone rojo es C1
    (`modulo-no-importable`). Con C1 ablado, esto sale VERDE con un router roto
    en el arbol.
    """
    (raiz / "viewer" / "app" / "routers" / "roto_calibracion.py").write_text(
        "from fastapi import APIRouter\n"
        "from app.modulo_que_no_existe import nada  # noqa: F401\n\n"
        "router = APIRouter()\n\n\n"
        '@router.get("/roto-calibracion")\n'
        "async def _roto():\n"
        "    return {}\n",
        encoding="utf-8")


def m_enumerador_degradado(raiz: Path) -> None:
    """Desaparece la API privada por la que el censo desciende a los routers.

    Simula el sucesor natural del defecto ya pagado (`get_flat_dependant`):
    `_IncludedRouter.effective_route_contexts()` se accede con
    `getattr(..., None)`, asi que si desaparece **no revienta, DEGRADA** — y
    degrada A LA VEZ el censo y la puerta, con lo que C9
    (`conjunto-de-rutas-distinto`) no lo veria, porque los dos mirarian lo mismo
    mal mirado.

    Quien si lo ve es C2, y por una razon estructural: D2 llega a las rutas
    importando el modulo del router y leyendo `router.routes`, una via que **no
    usa ninguna API privada**. Hay dos caminos independientes hasta las mismas
    rutas y solo uno depende de los internos del framework.
    """
    sustituir(raiz / "scripts" / "route_map" / "route_map.py",
              'ctxs = getattr(r, "effective_route_contexts", None)',
              'ctxs = getattr(r, "effective_route_contexts_QUE_YA_NO_EXISTE", None)')


def _apendice(raiz: Path, texto: str) -> None:
    f = raiz.joinpath(*MAIN)
    f.write_text(f.read_text(encoding="utf-8") + texto, encoding="utf-8")


def _apendice_chasis(raiz: Path, texto: str) -> None:
    f = raiz.joinpath(*CHASIS)
    f.write_text(f.read_text(encoding="utf-8") + texto, encoding="utf-8")


#: (id, descripción, mutación, motivo que DEBE aparecer, entorno)
CASOS_DECLARACION = [
    ("G0",  "árbol limpio (control de falso positivo)", None, None, {}),
    ("G1",  "router desmontado", m_router_desmontado, "router-declarado-no-montado", {}),
    ("G2",  "ruta eliminada (su nombre sigue en NAV)", m_ruta_eliminada,
     "nombre-canonico-no-resuelve", {}),
    ("G3",  "método cambiado en una pantalla de navegación", m_metodo_cambiado,
     "nombre-canonico-no-resuelve", {}),
    ("G4",  "método montado que el router no declara", m_metodo_divergente,
     "metodo-declarado-no-coincide", {}),
    ("G5",  "ruta declarada por un router y no montada", m_ruta_declarada_no_montada,
     "ruta-declarada-no-montada", {}),
    ("G6",  "ruta montada de origen desconocido", m_ruta_sin_clasificar,
     "ruta-sin-clasificar", {}),
    ("G7",  "configuración VACÍA (la declaración de nombres a cero)", m_configuracion_vacia,
     "configuracion-vacia", {}),
    ("G8",  "configuración AUSENTE (falta un elemento del chasis)",
     m_configuracion_ausente_atributo, "configuracion-ausente", {}),
    ("G9",  "configuración AUSENTE (no hay chasis)", m_configuracion_ausente_modulo,
     "configuracion-ausente", {}),
    ("G10", "un panel ENCENDIDO cuando debía estar apagado", None, "panel-encendido",
     {"S9K_PANEL_C_ENABLED": "true"}),
    ("G11", "bandera de panel encendida que el chasis no declara", None,
     "panel-encendido", {"S9K_PANEL_Z_ENABLED": "1"}),
    ("G12", "módulo de router declarado y NO importable", m_router_no_importable,
     "router-declarado-no-montado", {}),
    ("G13", "el enumerador DEGRADA al desaparecer una API privada de FastAPI",
     m_enumerador_degradado, "ruta-declarada-no-montada", {}),
    # Falsos positivos vigilados: ninguno de éstos puede poner la puerta roja.
    ("FP1", "bandera de panel APAGADA explícitamente", None, None,
     {"S9K_PANEL_C_ENABLED": "false"}),
    ("FP2", "bandera de panel con valor ininteligible (el chasis la apaga)", None, None,
     {"S9K_PANEL_C_ENABLED": "quizas"}),
    ("FP3", "variable parecida que NO es de la familia", None, None,
     {"S9K_PANELC_ENABLED": "true", "S9K_PANEL_C_ENABLE": "true"}),
    ("FP4", "router declarado y VACÍO (no aporta rutas: nada que exigir)",
     lambda raiz: (raiz / "viewer" / "app" / "routers" / "vacio_calibracion.py")
     .write_text("from fastapi import APIRouter\n\nrouter = APIRouter()\n",
                 encoding="utf-8"), None, {}),
]


# ---------------------------------------------------------------------------
# C9/C10: se calibran adulterando el ARTEFACTO, no el árbol
# ---------------------------------------------------------------------------

def _mapa_valido(raiz: Path) -> dict:
    """Un artefacto de censo mínimo pero coherente con la app de la copia."""
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    ejecutado = ejecutar(raiz, solo_declaracion=True, repo=REPO)
    claves = []
    salida = raiz / "gate_out.json"
    if salida.exists():
        claves = json.loads(salida.read_text(encoding="utf-8")).get(
            "resumen", {}).get("claves_vivas", [])
    return {
        "head": head,
        "counts": {"montadas": len(claves), "probadas": len(claves)},
        "routes": [{"key": k} for k in claves],
        "tested_source": "tested_routes.json",
        "sondas_estaticas": {"/static": {"ok": True}},
        "probe_error": None,
        "findings": {},
        "_gate_rc_declaracion": ejecutado["rc"],
    }


def _sin(d: dict, *claves):
    out = json.loads(json.dumps(d))
    for c in claves:
        out.pop(c, None)
    return out


CASOS_ARTEFACTO = [
    ("A1", "no hay artefacto de censo", lambda m: None,
     "censo-no-inspecciono-la-app-real", None),
    ("A2", "el artefacto describe otro árbol (HEAD distinto)",
     lambda m: {**m, "head": "0" * 40}, "censo-no-inspecciono-la-app-real", 0),
    ("A3", "el censo no ejercitó ni una ruta (cobertura cero)",
     lambda m: {**m, "counts": {**m["counts"], "probadas": 0}},
     "censo-no-inspecciono-la-app-real", 0),
    ("A4", "el censo corrió con --skip-probe (sin sonda)",
     lambda m: {**m, "sondas_estaticas": None},
     "censo-no-inspecciono-la-app-real", 0),
    ("A5", "el censo no recibió --tested",
     lambda m: {**m, "tested_source": None},
     "censo-no-inspecciono-la-app-real", 0),
    ("A6", "el artefacto describe OTRAS rutas que las que sirve la app",
     lambda m: {**m, "routes": m["routes"][:-3] + [{"key": "GET /inventada"}]},
     "censo-no-inspecciono-la-app-real", 0),
    ("A7", "el censo salió con código 3 (incompleto)", lambda m: m, "censo-en-rojo", 3),
    # A8/A9 —«el censo declara entradas opacas» y «declara una ruta SIN-AUTH»—
    # ya NO se escriben aquí: se GENERAN, uno por cada nombre de
    # `gate.FINDINGS_DUROS` y `gate.FINDINGS_CENSO_INCOMPLETO`
    # (`casos_por_hallazgo_duro`). Escribirlos a mano dejaba seis de los ocho
    # duros sin ningún caso que los cubriera —medido: `rutas_denegacion_404_ambigua`
    # y `rutas_denegacion_no_atribuible` se podían mover a informativos y la
    # calibración pasaba—, y además la protección no crecía al endurecer un
    # hallazgo nuevo. Generándolos, crece sola, igual que D1 crece sola al
    # aparecer un router.
    # M11: el defecto que encontró la revisión. Con el nombre literal la puerta
    # daba rc=1; RENOMBRANDO la clave a `rutas_sin_auth_v2` daba rc=0 VERDE con
    # la fuga intacta. Hoy cae en `hallazgo-desconocido` y vuelve a ser roja.
    ("A10", "un hallazgo DURO renombrado en el artefacto (la fuga sigue ahí)",
     lambda m: {**m, "findings": {"rutas_sin_auth_v2": [{"key": "GET /api/alias-fuga"}]}},
     "censo-en-rojo", 0),
    ("AFP", "artefacto íntegro (control de falso positivo)", lambda m: m, None, 0),
]


# ---------------------------------------------------------------------------
# G14 — el vocabulario de la puerta, contrastado con lo que el censo EMITE
# ---------------------------------------------------------------------------
# El defecto que cierra este control (M11): la puerta nombra los hallazgos duros
# del censo, y el arnés los verificaba **inyectando el nombre literal en un
# artefacto sintético**. Eso comprueba que la puerta reacciona a un nombre, no
# que ese nombre siga siendo el que el censo produce. Medido: renombrando
# `rutas_sin_auth` a `rutas_sin_auth_v2`, la puerta pasaba de rc=1 a **rc=0
# VERDE con la fuga intacta**, y la calibración seguía diciendo OK.
#
# Aquí se contrasta contra el censo REAL, en las dos direcciones:
#   - un nombre que la puerta clasifica y el censo ya no emite  -> acoplamiento
#     roto: la clase quedó apuntando al vacío;
#   - un nombre que el censo emite y la puerta no clasifica     -> es lo que en
#     ejecución cae en `hallazgo-desconocido`; aquí se detecta antes.

def vocabulario_del_censo(raiz: Path) -> set[str]:
    """Las claves de `findings` que produce `route_map` sobre el árbol real.

    Con `--skip-probe`: el censo sale con rc=3 por diseño (sin sonda no hay
    garantía), pero **escribe el artefacto igual**, y las claves de `findings`
    se emiten todas, vacías o no. Es la vía barata de preguntarle al censo cuál
    es su vocabulario, en vez de copiarlo a mano.
    """
    salida = raiz / "vocabulario.json"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(raiz / "scripts")
    for k in list(env):
        if k.startswith("S9K_"):
            env.pop(k)
    subprocess.run([sys.executable, str(raiz / "scripts" / "route_map" / "route_map.py"),
                    "--repo", str(raiz), "--skip-probe", "--out", str(salida)],
                   capture_output=True, text=True, env=env, cwd=str(raiz))
    if not salida.exists():
        return set()
    return set((json.loads(salida.read_text(encoding="utf-8")).get("findings") or {}))


def constantes_de_la_puerta(raiz: Path) -> dict:
    """Los nombres que la puerta clasifica, LEÍDOS DE LA PUERTA, no copiados."""
    salida = raiz / "constantes.json"
    guion = raiz / "leer_constantes.py"
    guion.write_text(
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "from route_map import gate\n"
        "json.dump({'duros': list(gate.FINDINGS_DUROS),\n"
        "           'incompleto': list(gate.FINDINGS_CENSO_INCOMPLETO),\n"
        "           'informativos': list(gate.FINDINGS_INFORMATIVOS),\n"
        "           'conocidos': sorted(gate.FINDINGS_CONOCIDOS)},\n"
        "          open(%r, 'w'))\n" % (str(raiz / "scripts"), str(salida)),
        encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(raiz / "scripts")
    subprocess.run([sys.executable, str(guion)], capture_output=True, text=True,
                   env=env, cwd=str(raiz))
    if not salida.exists():
        return {}
    return json.loads(salida.read_text(encoding="utf-8"))


def contraste_vocabulario(emitidos: set[str], consts: dict) -> list[str]:
    """Los desajustes entre lo que la puerta clasifica y lo que el censo emite."""
    problemas = []
    conocidos = set(consts.get("conocidos") or [])
    if not emitidos:
        return ["el censo no emitió ninguna clave de `findings`: no hay nada que "
                "contrastar, y un contraste sin datos no comprueba nada"]
    if not conocidos:
        return ["la puerta no expone ningún nombre clasificado"]
    for nombre in sorted(conocidos - emitidos):
        problemas.append(
            f"la puerta clasifica `{nombre}`, que el censo YA NO EMITE: el "
            f"acoplamiento por nombre se ha roto y esa clase apunta al vacío "
            f"(si era un hallazgo DURO, dejó de vigilarse en silencio)")
    for nombre in sorted(emitidos - conocidos):
        problemas.append(
            f"el censo emite `{nombre}` y la puerta no lo clasifica: en ejecución "
            f"caería en `hallazgo-desconocido`; decide si es duro o informativo")
    return problemas


# ---------------------------------------------------------------------------
# Casos de artefacto GENERADOS: uno por cada hallazgo que la puerta llama duro
# ---------------------------------------------------------------------------

def casos_por_hallazgo_duro(consts: dict) -> list[tuple]:
    """Un caso sintetico por NOMBRE duro, leido de `gate.py`, no escrito aqui.

    Defecto que cierra (M16): con A8 y A9 escritos a mano, solo dos de los trece
    nombres duros tenian caso. Medido: mover `rutas_denegacion_404_ambigua` o
    `rutas_denegacion_no_atribuible` a `FINDINGS_INFORMATIVOS` **pasaba la
    calibracion**. Generando un caso por nombre, endurecer un hallazgo nuevo
    trae su proteccion consigo y no hay que acordarse de nada.

    OJO CON LO QUE ESTO SOLO NO PRUEBA: estos casos se derivan de la MISMA lista
    que vigilan, asi que si alguien mueve un nombre a informativos, su caso
    desaparece con el y ninguno se pone rojo. Eso lo cubre `G15`, que deriva la
    pertenencia de una medida y no de la lista.
    """
    salida = []
    duros = list(consts.get("duros") or [])
    incompleto = list(consts.get("incompleto") or [])
    for nombre in duros + incompleto:
        salida.append((
            f"AD-{nombre}",
            f"el censo emite el hallazgo DURO `{nombre}`",
            (lambda n: lambda m: {**m, "findings": {n: [{"key": f"__caso__ {n}"}]}})(nombre),
            "censo-en-rojo",
            0,
        ))
    return salida


# ---------------------------------------------------------------------------
# G15 - la asignacion duro/informativo se DERIVA de una medida, no se escribe
# ---------------------------------------------------------------------------
# El problema real: `FINDINGS_DUROS` y `FINDINGS_INFORMATIVOS` reparten el
# vocabulario del censo, y mover un nombre de la primera a la segunda **apaga
# una garantia**. Los casos generados arriba no lo detectan por si solos porque
# se derivan de la misma lista.
#
# CRITERIO DERIVADO, y esta es la parte que importa: se toman DOS medidas de
# referencia sobre el arbol limpio -el censo con sonda y el censo con
# `--skip-probe`- y se exige que **todo hallazgo vacio en LAS DOS sea duro**.
#
# Por que las dos y no una:
#   - solo con sonda, `rutas_no_probadas` sale vacio (70/70 ejercitadas) y el
#     criterio exigiria endurecer la COBERTURA de tests, que es otra politica y
#     no la de esta puerta;
#   - solo con `--skip-probe`, `rutas_servidas_a_viewer` sale vacio porque la
#     medida no se ha hecho, no porque no haya nada que contar.
#
# Un cubo que sigue vacio **tanto si debilitas la medida como si la refuerzas**
# no depende de la configuracion: es un cubo que deberia estar siempre vacio, y
# ese es exactamente el que tiene que ser duro. Uno que se llena en alguna de
# las dos esta describiendo el estado del arbol, no una garantia rota, y queda
# libre. Medido sobre este arbol: la interseccion son 12 nombres y los 12 estan
# hoy en las tuplas duras.
#
# El criterio es de una sola direccion (vacio => duro; no vacio => libre), asi
# que endurecer de mas nunca lo viola: `caracterizacion_estatica_fallida` se
# llena con `--skip-probe` y es duro igualmente, y esta bien.

def _findings_de(artefacto: Path) -> dict:
    try:
        return json.loads(artefacto.read_text(encoding="utf-8")).get("findings") or {}
    except Exception:
        return {}


def censo_de_referencia(raiz: Path, sufijo: str, extra: list[str]) -> dict:
    """Ejecuta el censo sobre la copia limpia y devuelve sus `findings`."""
    salida = raiz / f"referencia-{sufijo}.json"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(raiz / "scripts")
    for k in list(env):
        if k.startswith("S9K_"):
            env.pop(k)
    subprocess.run([sys.executable, str(raiz / "scripts" / "route_map" / "route_map.py"),
                    "--repo", str(raiz), "--out", str(salida)] + extra,
                   capture_output=True, text=True, env=env, cwd=str(raiz))
    return _findings_de(salida)


def duros_exigidos(sin_sonda: dict, con_sonda: dict) -> tuple[set, list[str]]:
    """Los nombres que la medida obliga a que sean duros, y por que."""
    problemas = []
    if not sin_sonda:
        problemas.append("la medida de referencia SIN sonda no produjo hallazgos")
    if not con_sonda:
        problemas.append("la medida de referencia CON sonda no produjo hallazgos")
    if problemas:
        return set(), problemas
    vacios_sin = {k for k, v in sin_sonda.items() if not v}
    vacios_con = {k for k, v in con_sonda.items() if not v}
    return vacios_sin & vacios_con, []


def contraste_asignacion(exigidos: set, consts: dict) -> list[str]:
    """Los duros que la medida exige y la puerta NO declara duros."""
    declarados = set(consts.get("duros") or []) | set(consts.get("incompleto") or [])
    informativos = set(consts.get("informativos") or [])
    problemas = []
    for nombre in sorted(exigidos - declarados):
        donde = "`FINDINGS_INFORMATIVOS`" if nombre in informativos else "ninguna tupla"
        problemas.append(
            f"`{nombre}` esta VACIO en las dos medidas de referencia, o sea que "
            f"deberia estar siempre vacio, y sin embargo la puerta lo tiene en "
            f"{donde}: si se llena, la puerta no se pondra roja")
    return problemas


# ---------------------------------------------------------------------------
# G16 - lo que el CENSO declara fatal, la puerta no puede llamarlo informativo
# ---------------------------------------------------------------------------
# Superviviente S1, medido por una revision: `caracterizacion_estatica_fallida`
# era el nombre que sobraba en el 13 contra 12 de G15 y **no tenia cobertura
# ninguna**. Movido a `FINDINGS_INFORMATIVOS`, la calibracion salia VERDE: G15
# no lo exige (no esta vacio en las dos medidas, se llena con `--skip-probe`) y
# su caso `AD-` desaparecia con el. Y el hueco era real: con ese hallazgo lleno
# y `--map-rc 0`, la puerta sana da rc=1 y la mutada da rc=0.
#
# El atenuante que encontro la revision es tambien la solucion: en el pipeline
# real el censo YA sale con rc=3 si ese hallazgo no esta vacio, y CI le pasa el
# rc a la puerta, asi que la garantia se sostenia **por otra capa**. Era una capa
# que se podia quitar en silencio. Aqui se convierte esa coincidencia en un
# ACOPLAMIENTO EXIGIDO:
#
#   todo hallazgo por el que el censo sale con codigo distinto de 0 es FATAL
#   PARA EL CENSO, y la puerta no puede tratarlo como informativo.
#
# Y no se copia la lista: se DERIVA del AST de `route_map.main()`, leyendo que
# nombres aparecen en `findings.get(...)` dentro de las ramas que terminan en un
# `return` distinto de 0. Si manana el censo declara fatal un hallazgo nuevo,
# entra solo; si deja de serlo, el criterio se afloja solo y con motivo.

def hallazgos_fatales_del_censo(raiz: Path) -> tuple[set, list[str]]:
    """Nombres de `findings` que hacen salir a `route_map` con codigo != 0."""
    fuente = raiz / "scripts" / "route_map" / "route_map.py"
    try:
        arbol = ast.parse(fuente.read_text(encoding="utf-8"))
    except Exception as exc:
        return set(), [f"no se pudo leer el censo para derivar sus fatales: {exc!r}"]

    principal = None
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "main":
            principal = nodo
    if principal is None:
        return set(), ["`route_map.main` no existe: no se puede derivar que "
                       "hallazgos declara fatales el censo"]

    def nombres_en(test) -> set:
        salida = set()
        for n in ast.walk(test):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            if n.func.attr != "get" or not n.args:
                continue
            arg = n.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                salida.add(arg.value)
        return salida

    fatales = set()
    for nodo in ast.walk(principal):
        if not isinstance(nodo, ast.If):
            continue
        devuelve_rojo = any(
            isinstance(x, ast.Return) and isinstance(x.value, ast.Constant)
            and isinstance(x.value.value, int) and x.value.value != 0
            for x in nodo.body)
        if devuelve_rojo:
            fatales |= nombres_en(nodo.test)
    if not fatales:
        return set(), ["el censo no declara NINGUN hallazgo fatal: o cambio su "
                       "logica de codigos de salida o la derivacion esta rota"]
    return fatales, []


# ---------------------------------------------------------------------------
# G17 - el conjunto duro NO PUEDE ENCOGER
# ---------------------------------------------------------------------------
# Superviviente S2, y es un limite ESTRUCTURAL de G15, no un descuido: la regla
# «vacio en las dos medidas => duro» no puede proteger un cubo que YA ESTA
# LLENO. Medido por la revision: si el mismo commit **introduce el defecto**
# (p. ej. `contradiccion_deniega_y_sirve` no vacio) **y** mueve ese nombre a
# informativos, entonces `duros_exigidos` ya no lo incluye, `contraste_asignacion`
# no dice nada, el caso `AD-` desaparece con el nombre y el suelo se cumple de
# sobra: todo VERDE. Solo se salvaban `rutas_sin_auth` y `censo_opaco`, y **por
# accidente**: estaban fijados a mano como objetivo de dos ablaciones.
#
# Ninguna regla que mire SOLO el arbol actual puede cerrar esto, porque en el
# arbol actual el nombre ya no es duro y su cubo ya no esta vacio: no queda
# rastro de la relajacion. Hace falta un punto de comparacion que el commit
# atacante no controle, y el unico que hay es **el estado anterior del codigo**.
#
#   el conjunto duro de HEAD tiene que contener al conjunto duro de la BASE
#   (merge-base con `origin/main`).
#
# No es una lista que nadie mantiene: es el commit de antes. Un nombre puede
# ANADIRSE cuando se quiera; quitarlo pone la puerta roja **aunque su cubo este
# lleno y aunque su caso generado haya desaparecido con el**, que es exactamente
# el ataque en dos pasos. Aflojar la vigilancia deja de poder hacerse callando:
# hay que hacerlo discutiendolo.

def constantes_en_la_base(raiz: Path) -> tuple[dict, list[str]]:
    """Las tuplas duras tal y como estan en la base de comparacion.

    Se leen con `git show <base>:<ruta>` y se parsean con AST -no con `grep`, y
    no importando el fichero de otra rama-: leer un esquema de otra rama y darlo
    por bueno es como se convierte una capacidad ajena en verdad falsa del
    producto.
    """
    base = subprocess.run(["git", "-C", str(REPO), "merge-base", "HEAD", "origin/main"],
                          capture_output=True, text=True).stdout.strip()
    if not base:
        return {}, ["no hay `origin/main` con el que comparar: sin base, este "
                    "control no puede afirmar que el conjunto duro no ha encogido"]
    ruta = "scripts/route_map/gate.py"
    crudo = subprocess.run(["git", "-C", str(REPO), "show", f"{base}:{ruta}"],
                           capture_output=True, text=True)
    if crudo.returncode != 0:
        # La puerta no existia en la base: no hay nada que pueda haber encogido.
        return {"__sin_base__": True}, []
    try:
        arbol = ast.parse(crudo.stdout)
    except Exception as exc:
        return {}, [f"la puerta de la base no se puede parsear: {exc!r}"]
    fuera = {}
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
            continue
        destino = nodo.targets[0]
        if not isinstance(destino, ast.Name) or not destino.id.startswith("FINDINGS_"):
            continue
        try:
            fuera[destino.id] = list(ast.literal_eval(nodo.value))
        except Exception:
            continue
    return fuera, []


def contraste_no_encoge(base: dict, consts: dict) -> list[str]:
    """Nombres que eran duros en la base y ya no lo son en HEAD."""
    if base.get("__sin_base__"):
        return []
    duros_base = set(base.get("FINDINGS_DUROS") or []) | set(
        base.get("FINDINGS_CENSO_INCOMPLETO") or [])
    if not duros_base:
        return ["la base no declara ningun hallazgo duro: o la puerta cambio de "
                "forma o la lectura de la base esta rota, y en cualquier caso "
                "este control no esta comprobando nada"]
    duros_head = set(consts.get("duros") or []) | set(consts.get("incompleto") or [])
    informativos = set(consts.get("informativos") or [])
    problemas = []
    for nombre in sorted(duros_base - duros_head):
        donde = ("`FINDINGS_INFORMATIVOS`" if nombre in informativos
                 else "ninguna tupla (ha desaparecido del vocabulario)")
        problemas.append(
            f"`{nombre}` era un hallazgo DURO en la base y en este arbol esta en "
            f"{donde}: el conjunto duro ha ENCOGIDO. Da igual que su cubo este "
            f"lleno o vacio y que su caso generado haya desaparecido con el; "
            f"aflojar una garantia no puede hacerse en silencio")
    return problemas


# ---------------------------------------------------------------------------
# Mutacion REAL de la puerta (no simulacion en memoria)
# ---------------------------------------------------------------------------
# `G15-neg` simulaba llamando a `contraste_asignacion` con diccionarios
# degradados: eso calibra la FUNCION, no el sistema. Aqui se muta `gate.py` de
# verdad y las constantes se releen **en un subproceso**, que es el camino que
# recorre el arnes cuando calibra.

def mover_a_informativos(raiz: Path, nombre: str) -> None:
    """Muta la puerta para que `nombre` deje de ser duro y pase a informativo."""
    fichero = raiz / "scripts" / "route_map" / "gate.py"
    texto = fichero.read_text(encoding="utf-8")
    guarda = 'if __name__ == "__main__":'
    if guarda not in texto:
        raise AssertionError("la puerta no tiene guarda `__main__`: no se sabe "
                             "donde insertar la mutacion")
    parche = (
        "\n# --- MUTACION DE CALIBRACION ---\n"
        f"FINDINGS_DUROS = tuple(x for x in FINDINGS_DUROS if x != {nombre!r})\n"
        "FINDINGS_CENSO_INCOMPLETO = tuple(\n"
        f"    x for x in FINDINGS_CENSO_INCOMPLETO if x != {nombre!r})\n"
        f"FINDINGS_INFORMATIVOS = FINDINGS_INFORMATIVOS + ({nombre!r},)\n"
        "FINDINGS_CONOCIDOS = frozenset(\n"
        "    FINDINGS_CENSO_INCOMPLETO + FINDINGS_DUROS + FINDINGS_INFORMATIVOS)\n\n"
    )
    fichero.write_text(texto.replace(guarda, parche + guarda, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# ablaciones: se cobran sólo si vuelven VERDE un caso que estaba ROJO
# ---------------------------------------------------------------------------

#: (id, caso que debe volverse verde, texto a sustituir en gate.py, sustituto)
ABLACIONES = [
    ("AB-C2", "G5",
     'hallazgos["ruta-declarada-no-montada"].append({',
     'None and hallazgos["ruta-declarada-no-montada"].append({'),
    ("AB-C3", "G4",
     'hallazgos["metodo-declarado-no-coincide"].append({',
     'None and hallazgos["metodo-declarado-no-coincide"].append({'),
    ("AB-C4", "G6",
     'hallazgos["ruta-sin-clasificar"].append({',
     'None and hallazgos["ruta-sin-clasificar"].append({'),
    ("AB-C5-existe", "G2",
     'hallazgos["nombre-canonico-no-resuelve"].append({\n                "nombre_ruta": nombre_ruta,\n                "declarado_en": fuente,\n                "motivo": "ruta-inexistente",',
     'None and hallazgos["nombre-canonico-no-resuelve"].append({\n                "nombre_ruta": nombre_ruta,\n                "declarado_en": fuente,\n                "motivo": "ruta-inexistente",'),
    ("AB-C5-metodo", "G3",
     "elif METODO_DE_NAVEGACION not in metodos:", "elif False:"),
    ("AB-C6", "G7",
     'hallazgos["configuracion-vacia"].append({',
     'None and hallazgos["configuracion-vacia"].append({'),
    ("AB-C7", "G8",
     'hallazgos["configuracion-ausente"].append({\n                "fuente": f"app.chassis.{atributo}",',
     'None and hallazgos["configuracion-ausente"].append({\n                "fuente": f"app.chassis.{atributo}",'),
    ("AB-C8", "G10",
     'hallazgos["panel-encendido"].append({\n                "hueco": slot.key,',
     'None and hallazgos["panel-encendido"].append({\n                "hueco": slot.key,'),
    # Abla la emisión de C1 que atiende a los módulos NO IMPORTABLES, que es la
    # única que puede hablar en G12: cuando el `import` falla, D2 no ve ni una
    # ruta, así que C2 y C5 no tienen nada que decir.
    ("AB-C1", "G12", "for f in fallos_import:", "for f in []:"),
    ("AB-C10-desconocido", "A10", "if nombre in FINDINGS_CONOCIDOS:", "if True:"),
    ("AB-C9-head", "A2", 'if head_repo and head_mapa and head_mapa != head_repo:',
     'if False:'),
    ("AB-C9-cobertura", "A3", 'elif not counts.get("probadas"):', 'elif False:'),
    ("AB-C9-conjunto", "A6", 'if vivas and del_mapa and vivas != del_mapa:', 'if False:'),
    # El caso ya no se llama `A8`: se GENERA a partir del nombre del hallazgo.
    ("AB-C10", "AD-censo_opaco",
     "for nombre in FINDINGS_CENSO_INCOMPLETO:", "for nombre in ():"),
    ("AB-C10-duros", "AD-rutas_sin_auth",
     "for nombre in FINDINGS_DUROS:", "for nombre in ():"),
]


def ablar(raiz: Path, viejo: str, nuevo: str) -> None:
    sustituir(raiz / "scripts" / "route_map" / "gate.py", viejo, nuevo)


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    # G15 necesita la medida de referencia CON sonda. `--mapa-completo` acepta el
    # artefacto que el job acaba de producir y así no se repiten sus ~60 s.
    #
    # AVISO, porque la versión anterior de este comentario decía lo contrario y
    # era FALSO: **si no se pasa la bandera, esto NO se pone rojo**. Se genera la
    # referencia aquí mismo, ejecutando el censo con sonda. La bandera es un
    # atajo de tiempo, no una condición de validez, y quitarla de `ci.yml` no
    # rompe nada ni lo delata: sólo hace el job más lento.
    #
    # Lo que sí es rojo es pasar una referencia INVÁLIDA: un artefacto tomado con
    # `--skip-probe`, o sin `--tested`, no sirve como medida con sonda y G15 lo
    # rechaza en vez de derivar sobre datos falseados.
    ap.add_argument("--mapa-completo", dest="mapa_completo", default=None,
                    help="artefacto de route_map generado CON sonda (referencia de G15)")
    ap.add_argument("--tested-ref", dest="tested_ref", default=None,
                    help="fichero --tested con el que generar la referencia si no "
                         "se pasa --mapa-completo")
    a = ap.parse_args(argv)

    mapa_completo = Path(a.mapa_completo).resolve() if a.mapa_completo else None
    tested_ref = Path(a.tested_ref).resolve() if a.tested_ref else None

    raices = [REPO / "viewer", REPO / "scripts" / "route_map", REPO / "contracts"]
    hash_antes = hash_arbol(raices)

    resultados: list[dict] = []
    fallos: list[str] = []

    # --- casos de declaración (C1-C8) ------------------------------------
    for cid, desc, mut, motivo, entorno in CASOS_DECLARACION:
        with tempfile.TemporaryDirectory(prefix=f"calib-gate-{cid}-") as tmp:
            raiz = copia(Path(tmp))
            try:
                if mut is not None:
                    mut(raiz)
            except AssertionError as exc:
                fallos.append(f"{cid}: {exc}")
                resultados.append({"caso": cid, "desc": desc, "estado": "MUTACION-NO-APLICADA",
                                   "detalle": str(exc)})
                continue
            r = ejecutar(raiz, entorno_extra=entorno)
            ok = (r["rc"] == 0 and motivo is None) or (motivo is not None
                                                       and motivo in r["motivos"])
            if not ok:
                fallos.append(f"{cid} ({desc}): esperado "
                              f"{motivo or 'VERDE'}, obtenido rc={r['rc']} "
                              f"motivos={r['motivos']}")
            resultados.append({"caso": cid, "desc": desc, "esperado": motivo or "VERDE",
                               "rc": r["rc"], "motivos": r["motivos"],
                               "estado": "OK" if ok else "FALLO"})

    # --- casos de artefacto (C9/C10) + uno GENERADO por hallazgo duro -----
    with tempfile.TemporaryDirectory(prefix="calib-gate-art-") as tmp:
        raiz_art = copia(Path(tmp))
        base = _mapa_valido(raiz_art)
        base.pop("_gate_rc_declaracion", None)
        consts_art = constantes_de_la_puerta(raiz_art)
        casos_art = CASOS_ARTEFACTO + casos_por_hallazgo_duro(consts_art)
        if len(casos_art) <= len(CASOS_ARTEFACTO):
            fallos.append(
                "no se generó ningún caso por hallazgo duro: o la puerta no "
                "expone `FINDINGS_DUROS`, o no se pudo leer. Un arnés que pasa "
                "con 0 casos generados está roto")
        for cid, desc, doctor, motivo, rc in casos_art:
            mapa = doctor(base)
            ruta_mapa = None
            if mapa is not None:
                ruta_mapa = raiz_art / f"mapa-{cid}.json"
                ruta_mapa.write_text(json.dumps(mapa), encoding="utf-8")
            r = ejecutar(raiz_art, mapa=ruta_mapa, mapa_rc=rc,
                         solo_declaracion=False, repo=REPO)
            ok = (r["rc"] == 0 and motivo is None) or (motivo is not None
                                                       and motivo in r["motivos"])
            if not ok:
                fallos.append(f"{cid} ({desc}): esperado {motivo or 'VERDE'}, "
                              f"obtenido rc={r['rc']} motivos={r['motivos']}")
            resultados.append({"caso": cid, "desc": desc, "esperado": motivo or "VERDE",
                               "rc": r["rc"], "motivos": r["motivos"],
                               "estado": "OK" if ok else "FALLO"})

    # --- ablaciones --------------------------------------------------------
    por_id = {c[0]: c for c in CASOS_DECLARACION}
    art_por_id = {c[0]: c for c in casos_art}
    ablaciones: list[dict] = []
    for aid, caso, viejo, nuevo in ABLACIONES:
        with tempfile.TemporaryDirectory(prefix=f"calib-abl-{aid}-") as tmp:
            raiz = copia(Path(tmp))
            try:
                ablar(raiz, viejo, nuevo)
            except AssertionError as exc:
                fallos.append(f"{aid}: la ablación no se pudo aplicar: {exc}")
                ablaciones.append({"ablacion": aid, "caso": caso,
                                   "estado": "NO-APLICADA", "detalle": str(exc)})
                continue
            if caso in por_id:
                _, desc, mut, motivo, entorno = por_id[caso]
                if mut is not None:
                    mut(raiz)
                r = ejecutar(raiz, entorno_extra=entorno)
            elif caso not in art_por_id:
                # Ocurre cuando una ablación apunta a un caso GENERADO cuyo
                # nombre ya no existe: vaciar `FINDINGS_DUROS` o renombrar un
                # duro se lleva por delante su caso `AD-<nombre>`. Falla cerrado
                # igual, pero antes lo hacía con un `KeyError` en bruto, y una
                # traza no le dice al operador lo que ha pasado.
                fallos.append(
                    f"{aid}: la ablación apunta al caso `{caso}`, que YA NO SE "
                    f"GENERA. Ese caso sale de `gate.FINDINGS_DUROS` / "
                    f"`FINDINGS_CENSO_INCOMPLETO`, así que el hallazgo se ha "
                    f"renombrado, se ha movido a informativos o ha desaparecido "
                    f"del vocabulario. Mira G14, G15, G16 y G17")
                ablaciones.append({"ablacion": aid, "caso": caso,
                                   "estado": "CASO-INEXISTENTE"})
                continue
            else:
                _, desc, doctor, motivo, rc = art_por_id[caso]
                base2 = _mapa_valido(raiz)
                base2.pop("_gate_rc_declaracion", None)
                mapa = doctor(base2)
                ruta_mapa = raiz / f"mapa-{caso}.json"
                ruta_mapa.write_text(json.dumps(mapa), encoding="utf-8")
                r = ejecutar(raiz, mapa=ruta_mapa, mapa_rc=rc,
                             solo_declaracion=False, repo=REPO)
            # Se cobra sólo si el caso que estaba ROJO pasa a VERDE.
            cobrada = r["rc"] == 0
            if not cobrada:
                fallos.append(
                    f"{aid}: al quitar el control, el caso {caso} SIGUE rojo "
                    f"(motivos={r['motivos']}). Ese control no es el que lo "
                    f"sostiene, o la ablación no llegó a la rama que se ejecuta")
            ablaciones.append({"ablacion": aid, "caso": caso, "rc_ablado": r["rc"],
                               "motivos_ablado": r["motivos"],
                               "estado": "COBRADA" if cobrada else "NO-COBRADA"})

    # --- G14: el vocabulario de la puerta contra el que el censo EMITE ----
    with tempfile.TemporaryDirectory(prefix="calib-gate-voc-") as tmp:
        raiz_voc = copia(Path(tmp))
        emitidos = vocabulario_del_censo(raiz_voc)
        consts = constantes_de_la_puerta(raiz_voc)
        problemas = contraste_vocabulario(emitidos, consts)
        fallos.extend(f"G14: {x}" for x in problemas)
        resultados.append({
            "caso": "G14",
            "desc": ("el vocabulario que la puerta clasifica es el que el censo "
                     "emite de verdad"),
            "esperado": "VERDE", "rc": 1 if problemas else 0,
            "motivos": problemas,
            "emitidos_por_el_censo": sorted(emitidos),
            "clasificados_por_la_puerta": sorted(consts.get("conocidos") or []),
            "estado": "FALLO" if problemas else "OK",
        })
        # Control negativo del propio contraste: si no puede ponerse rojo, no
        # comprueba nada. Se le da un censo con un hallazgo DURO renombrado y
        # tiene que señalar las DOS caras (el nombre que falta y el que sobra).
        renombrado = (emitidos - {"rutas_sin_auth"}) | {"rutas_sin_auth_v2"}
        detectado = contraste_vocabulario(renombrado, consts)
        ok_neg = (any("rutas_sin_auth`" in x and "YA NO EMITE" in x for x in detectado)
                  and any("rutas_sin_auth_v2" in x for x in detectado))
        if not ok_neg:
            fallos.append(
                "G14-neg: el contraste de vocabulario NO detecta un hallazgo duro "
                f"renombrado. Un control que no puede ponerse rojo no comprueba "
                f"nada. Detectado: {detectado}")
        resultados.append({
            "caso": "G14-neg",
            "desc": "el contraste detecta un hallazgo DURO renombrado (M11)",
            "esperado": "detecta el renombrado", "rc": 1 if ok_neg else 0,
            "motivos": detectado,
            "estado": "OK" if ok_neg else "FALLO",
        })

    # --- G15: la asignación duro/informativo, DERIVADA de dos medidas -----
    with tempfile.TemporaryDirectory(prefix="calib-gate-asig-") as tmp:
        raiz_as = copia(Path(tmp))
        consts_as = constantes_de_la_puerta(raiz_as)
        sin_sonda = censo_de_referencia(raiz_as, "sin-sonda", ["--skip-probe"])
        con_sonda = {}
        if mapa_completo is not None:
            # Que exista no basta: si se tomó con `--skip-probe`, la mitad de los
            # cubos están vacíos porque nadie los llenó, no porque estén bien, y
            # el criterio de G15 saldría falseado hacia MÁS exigencia (que no es
            # inocuo: pondría el arnés rojo por el motivo equivocado).
            crudo = {}
            try:
                crudo = json.loads(mapa_completo.read_text(encoding="utf-8"))
            except Exception as exc:
                problemas_ref = [f"artefacto de referencia ilegible: {exc!r}"]
            else:
                problemas_ref = []
                if crudo.get("sondas_estaticas") is None:
                    problemas_ref.append(
                        "el artefacto de referencia se tomó con `--skip-probe`: "
                        "no sirve como medida CON sonda")
                if not crudo.get("tested_source"):
                    problemas_ref.append(
                        "el artefacto de referencia no recibió `--tested`")
            fallos.extend(f"G15: {x}" for x in problemas_ref)
            con_sonda = {} if problemas_ref else (crudo.get("findings") or {})
        else:
            con_sonda = censo_de_referencia(raiz_as, "con-sonda",
                                            ["--tested", str(tested_ref)] if tested_ref
                                            else [])
        exigidos, problemas = duros_exigidos(sin_sonda, con_sonda)
        problemas += contraste_asignacion(exigidos, consts_as)
        # Suelo: si la intersección sale ridícula, el criterio no ha medido nada
        # y no puede conceder un OK. 12 es lo medido en este árbol; se exige la
        # mayoría de los duros declarados, no un número mágico.
        minimo = max(2, len(set(consts_as.get("duros") or [])) // 2)
        if not problemas and len(exigidos) < minimo:
            problemas.append(
                f"sólo {len(exigidos)} hallazgos salen vacíos en las dos medidas "
                f"de referencia (mínimo {minimo}): las medidas no se han hecho "
                f"bien y este control no está comprobando la asignación")
        fallos.extend(f"G15: {x}" for x in problemas)
        resultados.append({
            "caso": "G15",
            "desc": ("la asignación duro/informativo se deriva de dos medidas, "
                     "no de una opinión escrita"),
            "esperado": "VERDE", "rc": 1 if problemas else 0, "motivos": problemas,
            "duros_exigidos_por_la_medida": sorted(exigidos),
            "duros_declarados_por_la_puerta": sorted(
                set(consts_as.get("duros") or []) | set(consts_as.get("incompleto") or [])),
            "estado": "FALLO" if problemas else "OK",
        })
    # --- G16: lo que el censo declara FATAL tiene que ser duro ------------
    # Cierra S1: `caracterizacion_estatica_fallida` no lo exigia G15 (no esta
    # vacio en las dos medidas) y su caso `AD-` desaparecia al moverlo.
    with tempfile.TemporaryDirectory(prefix="calib-gate-fatal-") as tmp:
        raiz_f = copia(Path(tmp))
        consts_f = constantes_de_la_puerta(raiz_f)
        fatales, problemas_f = hallazgos_fatales_del_censo(raiz_f)
        declarados_f = set(consts_f.get("duros") or []) | set(
            consts_f.get("incompleto") or [])
        informativos_f = set(consts_f.get("informativos") or [])
        for nombre in sorted(fatales - declarados_f):
            donde = ("`FINDINGS_INFORMATIVOS`" if nombre in informativos_f
                     else "ninguna tupla")
            problemas_f.append(
                f"`{nombre}` hace salir al CENSO con codigo != 0 -es fatal para el "
                f"censo- y la puerta lo tiene en {donde}: la puerta certificaria "
                f"un censo que se declara a si mismo no citable")
        fallos.extend(f"G16: {x}" for x in problemas_f)
        resultados.append({
            "caso": "G16",
            "desc": ("lo que el censo declara fatal (rc != 0) la puerta no lo "
                     "trata como informativo"),
            "esperado": "VERDE", "rc": 1 if problemas_f else 0,
            "motivos": problemas_f,
            "fatales_declarados_por_el_censo": sorted(fatales),
            "estado": "FALLO" if problemas_f else "OK",
        })

    # --- G17: el conjunto duro no puede ENCOGER respecto a la base --------
    # Cierra S2, que es un limite ESTRUCTURAL de G15 y no un descuido: ninguna
    # regla que mire solo el arbol actual puede ver una relajacion cuyo rastro
    # el propio commit ha borrado. El unico punto de comparacion que el commit
    # atacante no controla es el estado ANTERIOR del codigo.
    with tempfile.TemporaryDirectory(prefix="calib-gate-base-") as tmp:
        raiz_b = copia(Path(tmp))
        consts_b = constantes_de_la_puerta(raiz_b)
        base, problemas_b = constantes_en_la_base(raiz_b)
        problemas_b = list(problemas_b) + contraste_no_encoge(base, consts_b)
        fallos.extend(f"G17: {x}" for x in problemas_b)
        resultados.append({
            "caso": "G17",
            "desc": "el conjunto de hallazgos duros no ha encogido respecto a la base",
            "esperado": "VERDE", "rc": 1 if problemas_b else 0,
            "motivos": problemas_b,
            "duros_en_la_base": sorted(
                set(base.get("FINDINGS_DUROS") or [])
                | set(base.get("FINDINGS_CENSO_INCOMPLETO") or [])),
            "estado": "FALLO" if problemas_b else "OK",
        })

    # --- controles negativos POR NOMBRE, con MUTACION REAL de la puerta ---
    # Antes esto se simulaba pasandole diccionarios degradados a
    # `contraste_asignacion`: eso calibra la funcion, no el sistema. Ahora se
    # muta `gate.py` de verdad, se releen las constantes **en un subproceso** y
    # se comprueba que ALGUNO de los tres controles (G15, G16, G17) lo caza.
    #
    # El criterio de aceptacion es el de la revision: el ataque en dos pasos
    # -llenar el cubo y mover el nombre- tiene que ponerse ROJO para LOS TRECE,
    # no para dos. G17 no mira el contenido del cubo, asi que lo cubre entero;
    # G15 y G16 se quedan como razones independientes y mejor diagnosticadas.
    nombres_a_proteger = sorted(
        set(consts_b.get("duros") or []) | set(consts_b.get("incompleto") or []))
    if len(nombres_a_proteger) < 2:
        fallos.append(
            "Gneg: la puerta declara menos de 2 hallazgos duros, asi que este "
            "control negativo no comprueba nada. Un conjunto vacio no pasa")
    sin_proteccion = []
    detalle_neg = {}
    for nombre in nombres_a_proteger:
        with tempfile.TemporaryDirectory(prefix="calib-neg-") as tmp:
            raiz_n = copia(Path(tmp))
            try:
                mover_a_informativos(raiz_n, nombre)
            except AssertionError as exc:
                sin_proteccion.append(f"{nombre} (mutacion no aplicada: {exc})")
                continue
            consts_n = constantes_de_la_puerta(raiz_n)
            if nombre in (set(consts_n.get("duros") or [])
                          | set(consts_n.get("incompleto") or [])):
                sin_proteccion.append(f"{nombre} (la mutacion NO llego a la puerta)")
                continue
            # EL ATAQUE EN DOS PASOS (S2), simulado en su peor caso. Si el
            # mismo commit LLENA el cubo y mueve el nombre, la medida de
            # referencia ya no lo ve vacio y G15 deja de exigirlo: por eso el
            # veredicto se toma con `exigidos` SIN este nombre. Creditarle a G15
            # una proteccion que el ataque real le quita seria contarse un
            # control que no actua.
            exigidos_s2 = set(exigidos) - {nombre}
            razones = []
            if any(f"`{nombre}`" in x
                   for x in contraste_asignacion(exigidos_s2, consts_n)):
                razones.append("G15")
            if any(f"`{nombre}`" in x for x in contraste_asignacion(exigidos, consts_n)):
                razones.append("G15-si-el-cubo-sigue-vacio")
            fat_n, _ = hallazgos_fatales_del_censo(raiz_n)
            if nombre in fat_n - (set(consts_n.get("duros") or [])
                                  | set(consts_n.get("incompleto") or [])):
                razones.append("G16")
            if any(f"`{nombre}`" in x for x in contraste_no_encoge(base, consts_n)):
                razones.append("G17")
            detalle_neg[nombre] = razones
            # Se exige proteccion en el PEOR caso: controles que siguen actuando
            # aunque el cubo este lleno.
            if not [x for x in razones if x != "G15-si-el-cubo-sigue-vacio"]:
                sin_proteccion.append(nombre)
    if sin_proteccion:
        fallos.append(
            "Gneg: mover estos hallazgos duros a `FINDINGS_INFORMATIVOS` NO lo "
            f"detecta ningun control: {sin_proteccion}. Un control que no puede "
            "ponerse rojo no comprueba nada")
    resultados.append({
        "caso": "Gneg",
        "desc": ("el ataque en DOS PASOS -llenar el cubo y mover el nombre a "
                 "informativos- se detecta para cada hallazgo duro, mutando "
                 "`gate.py` de verdad"),
        "esperado": f"detecta los {len(nombres_a_proteger)}",
        "rc": 0 if sin_proteccion else 1,
        "motivos": sin_proteccion,
        "comprobados": nombres_a_proteger,
        "quien_lo_caza": detalle_neg,
        "estado": "FALLO" if sin_proteccion else "OK",
    })

    # --- el propio arnés tiene que seguir teniendo sus controles ----------
    # Nada guardaba a `calibrate_gate.py`: borrar el bloque de G15 dejaba 42
    # casos, por encima de `MINIMO_CASOS`, y todo verde.
    # `calibra_gate_integrity.py` vigila `check_ci_config.py`, no este arnés.
    # Esta tupla es de EXIGENCIAS, no de exenciones: escribir un nombre aquí
    # añade un control obligatorio, y quitarlo es lo que hay que hacer a la vista.
    CONTROLES_OBLIGATORIOS = ("G0", "G13", "G14", "G14-neg", "G15", "G16", "G17",
                              "Gneg", "AFP")
    ejecutados_id = {r["caso"] for r in resultados}
    for cid in CONTROLES_OBLIGATORIOS:
        if cid not in ejecutados_id:
            fallos.append(
                f"el control `{cid}` no se ha ejecutado: o se ha borrado del "
                f"arnés o ha reventado antes de registrarse. Un arnés al que le "
                f"faltan controles pasa igual de verde y no comprueba lo mismo")

    # --- la puerta no puede venir con el modo de calibración cableado -----
    for wf in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        if "--solo-declaracion" in wf.read_text(encoding="utf-8"):
            fallos.append(f"{wf.name}: un workflow invoca la puerta con "
                          "`--solo-declaracion`, que apaga C9 y C10. Eso no es "
                          "una puerta, es el arnés")

    # --- reversión verificada por HASH, no por presencia de cadenas -------
    hash_despues = hash_arbol(raices)
    if hash_antes != hash_despues:
        fallos.append(f"el árbol real CAMBIÓ durante la calibración: "
                      f"{hash_antes[:12]} -> {hash_despues[:12]}")

    ejecutados = [r for r in resultados if r["estado"] in ("OK", "FALLO")]
    cobradas = [x for x in ablaciones if x["estado"] == "COBRADA"]
    if len(ejecutados) < MINIMO_CASOS:
        fallos.append(f"sólo se ejecutaron {len(ejecutados)} casos (mínimo "
                      f"{MINIMO_CASOS}): un arnés que pasa con pocos casos no prueba nada")
    if len(cobradas) < MINIMO_ABLACIONES:
        fallos.append(f"sólo se cobraron {len(cobradas)} ablaciones (mínimo "
                      f"{MINIMO_ABLACIONES})")

    informe = {
        "hash_arbol_antes": hash_antes,
        "hash_arbol_despues": hash_despues,
        "casos": resultados,
        "ablaciones": ablaciones,
        "casos_ejecutados": len(ejecutados),
        "ablaciones_cobradas": len(cobradas),
        "fallos": fallos,
        "veredicto": "OK" if not fallos else "ROJO",
    }
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(informe, indent=2, ensure_ascii=False),
                               encoding="utf-8")

    print(f"casos: {len(ejecutados)} · ablaciones cobradas: {len(cobradas)}")
    for r in resultados:
        print(f"  {r['estado']:22s} {r['caso']:5s} {r['desc']}")
    for x in ablaciones:
        print(f"  {x['estado']:22s} {x['ablacion']:16s} -> caso {x['caso']}")
    print(f"hash del árbol real: {hash_antes[:16]} -> {hash_despues[:16]}")
    if fallos:
        print("", file=sys.stderr)
        print("CALIBRACION DE LA PUERTA: ROJA", file=sys.stderr)
        for f in fallos:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("CALIBRACION DE LA PUERTA: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

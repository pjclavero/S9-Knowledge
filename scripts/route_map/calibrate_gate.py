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
MINIMO_CASOS = 20
MINIMO_ABLACIONES = 12


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
    ("A8", "el censo declara entradas opacas",
     lambda m: {**m, "findings": {"censo_opaco": [{"path": "/opaca"}]}},
     "censo-en-rojo", 0),
    ("A9", "el censo declara una ruta SIN-AUTH",
     lambda m: {**m, "findings": {"rutas_sin_auth": [{"key": "GET /fuga"}]}},
     "censo-en-rojo", 0),
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
    ("AB-C10", "A8", "for nombre in FINDINGS_CENSO_INCOMPLETO:", "for nombre in ():"),
]


def ablar(raiz: Path, viejo: str, nuevo: str) -> None:
    sustituir(raiz / "scripts" / "route_map" / "gate.py", viejo, nuevo)


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

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

    # --- casos de artefacto (C9/C10) --------------------------------------
    with tempfile.TemporaryDirectory(prefix="calib-gate-art-") as tmp:
        raiz_art = copia(Path(tmp))
        base = _mapa_valido(raiz_art)
        base.pop("_gate_rc_declaracion", None)
        for cid, desc, doctor, motivo, rc in CASOS_ARTEFACTO:
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
    art_por_id = {c[0]: c for c in CASOS_ARTEFACTO}
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

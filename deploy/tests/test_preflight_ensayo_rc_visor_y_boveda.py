# -*- coding: utf-8 -*-
"""RC2-03 / RC2-04: el preflight del ensayo RC carga el catalogo y mide lo que vera el producto.

RC2-03. `sources_catalog.py` hace `from app import config`; ejecutado como script desde
`<release>/deploy/scripts/` el paquete `app` no era importable ni con el interprete del venv del
visor, y `fuentes.pobladas` / `aislamiento.workspace` salian PENDIENTE: el instrumento no medía.
Aqui se ejecuta el script REAL como subproceso, desde otro `cwd` y SIN `PYTHONPATH`.

RC2-04. Con `S9K_VAULT_ROOT` el producto lista fuentes del arbol de bovedas; el preflight miraba el
catalogo plano y daba un rojo falso. La resolucion es del catalogo del visor, no se duplica.

Cada aserción que deba cazar un mutante falla con un mensaje propio cuyo PREFIJO fijo es la causa
(`RC2-03: ...` / `RC2-04: ...`); el calibrador espera exactamente ese prefijo.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUION = REPO_ROOT / "deploy" / "scripts" / "preflight_ensayo_rc.py"
WS = "ensayo-rc"

_spec = importlib.util.spec_from_file_location("_preflight_ensayo_rc_visor", GUION)
assert _spec and _spec.loader
pf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pf
_spec.loader.exec_module(pf)


def _entorno_minimo(tmp_path: Path) -> dict:
    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    (fuentes / "cronica-de-ejemplo.md").write_text("texto\n", encoding="utf-8")
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS}), encoding="utf-8")
    return {
        "S9K_INGEST_SOURCES_DIR": str(fuentes),
        "S9K_DEFAULT_WORKSPACE": WS,
        "S9K_WRITER_WORKSPACE": WS,
    }


def _env_de_subproceso(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k != "PYTHONPATH" and not k.startswith("S9K_")}
    env.update(extra)
    return env


def _lineas(salida: str) -> dict:
    """`{id: (estado, detalle)}` a partir de la salida impresa por el guion."""
    res = {}
    for linea in salida.splitlines():
        partes = linea.split(None, 2)
        if len(partes) >= 2 and partes[0] in (pf.VERDE, pf.ROJO, pf.PENDIENTE):
            res[partes[1]] = (partes[0], partes[2] if len(partes) > 2 else "")
    return res


def _el_interprete_tiene_las_dependencias_del_visor() -> bool:
    r = subprocess.run([sys.executable, "-c", "import dotenv, pydantic_settings"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# RC2-03
# ---------------------------------------------------------------------------

def test_rc2_03_el_script_real_carga_el_catalogo_desde_otro_cwd_sin_pythonpath(tmp_path):
    otro_cwd = tmp_path / "otro-cwd"
    otro_cwd.mkdir()
    entorno = _entorno_minimo(tmp_path)
    r = subprocess.run(
        [sys.executable, str(GUION), "--workspace", WS],
        cwd=str(otro_cwd), env=_env_de_subproceso(entorno),
        capture_output=True, text=True, timeout=300)
    lineas = _lineas(r.stdout)
    for clave in ("fuentes.pobladas", "aislamiento.workspace"):
        assert clave in lineas, (
            "RC2-03: EL PREFLIGHT NO IMPRIME LA COMPROBACION %s: %s" % (clave, r.stdout + r.stderr))
        estado, detalle = lineas[clave]
        if _el_interprete_tiene_las_dependencias_del_visor():
            assert estado == pf.VERDE, (
                "RC2-03: EL PREFLIGHT NO CARGA EL CATALOGO: %s -> %s %s" % (clave, estado, detalle))
        else:
            # Sin dependencias: PENDIENTE explicito (nunca verde) que nombra el interprete.
            assert estado == pf.PENDIENTE and sys.executable in detalle, (
                "RC2-03: SIN DEPENDENCIAS NO NOMBRA EL INTERPRETE: %s -> %s %s"
                % (clave, estado, detalle))


def test_rc2_03_sin_las_dependencias_del_visor_sale_pendiente_y_nombra_el_interprete(tmp_path):
    """Una release cuyo visor no se puede importar: PENDIENTE explicito, jamas verde."""
    release = tmp_path / "release"
    (release / "deploy" / "scripts").mkdir(parents=True)
    shutil.copy2(GUION, release / "deploy" / "scripts" / GUION.name)
    app = release / "viewer" / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "config.py").write_text("import s9k_dependencia_que_no_existe\n", encoding="utf-8")
    otro_cwd = tmp_path / "otro-cwd"
    otro_cwd.mkdir()
    r = subprocess.run(
        [sys.executable, str(release / "deploy" / "scripts" / GUION.name), "--workspace", WS],
        cwd=str(otro_cwd), env=_env_de_subproceso(_entorno_minimo(tmp_path)),
        capture_output=True, text=True, timeout=300)
    lineas = _lineas(r.stdout)
    for clave in ("fuentes.pobladas", "aislamiento.workspace"):
        assert clave in lineas, (
            "RC2-03: EL PREFLIGHT NO IMPRIME LA COMPROBACION %s: %s" % (clave, r.stdout + r.stderr))
        estado, detalle = lineas[clave]
        assert estado == pf.PENDIENTE, (
            "RC2-03: SIN DEPENDENCIAS NO SALE PENDIENTE: %s -> %s %s" % (clave, estado, detalle))
        assert sys.executable in detalle and "s9k_dependencia_que_no_existe" in detalle, (
            "RC2-03: SIN DEPENDENCIAS NO NOMBRA EL INTERPRETE NI LO QUE FALTA: %s -> %s"
            % (clave, detalle))
    assert r.returncode != 0, "RC2-03: SIN DEPENDENCIAS EL PREFLIGHT SALE EN VERDE (rc 0)"


def test_rc2_03_el_visor_se_localiza_relativo_al_propio_fichero():
    """El visor sale de `REPO_ROOT` (relativo al fichero), no del cwd ni del entorno."""
    visor = (pf.REPO_ROOT / "viewer").resolve()
    assert pf.REPO_ROOT == GUION.resolve().parents[2], (
        "RC2-03: EL VISOR NO SE LOCALIZA RELATIVO AL FICHERO DEL PREFLIGHT")
    assert (visor / "app" / "sources_catalog.py").is_file(), (
        "RC2-03: EL VISOR DE LA RELEASE NO TIENE sources_catalog.py")


# ---------------------------------------------------------------------------
# RC2-04
# ---------------------------------------------------------------------------

def _boveda(tmp_path: Path, con_fuente: bool = True) -> Path:
    raiz = tmp_path / "bovedas"
    juego = raiz / "juego-uno"
    (juego / "compartido").mkdir(parents=True)
    (juego / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS}), encoding="utf-8")
    if con_fuente:
        (juego / "compartido" / "nota.md").write_text("texto\n", encoding="utf-8")
    return raiz


def _fuentes_pobladas(env: dict):
    return pf.fuentes_pobladas(pf.Contexto(env=env, workspace=WS))


def test_rc2_04_con_boveda_declarada_mide_el_arbol_de_bovedas(tmp_path):
    """El rojo falso de la RC: catalogo plano vacio, pero la boveda SI tiene fuentes."""
    vacio = tmp_path / "plano-vacio"
    vacio.mkdir()
    env = {
        "S9K_INGEST_SOURCES_DIR": str(vacio),
        "S9K_VAULT_ROOT": str(_boveda(tmp_path)),
        "S9K_VAULT_REQUIRE_MOUNT": "0",
    }
    r = _fuentes_pobladas(env)
    assert r.estado == pf.VERDE, (
        "RC2-04: FALSO ROJO CON BOVEDA DECLARADA: %s %s" % (r.estado, r.detalle))


def test_rc2_04_con_boveda_sin_directorio_plano_declarado_tambien_es_verde(tmp_path):
    env = {"S9K_VAULT_ROOT": str(_boveda(tmp_path)), "S9K_VAULT_REQUIRE_MOUNT": "0"}
    r = _fuentes_pobladas(env)
    assert r.estado == pf.VERDE, (
        "RC2-04: LA BOVEDA SOLA NO CUENTA COMO DECLARACION: %s %s" % (r.estado, r.detalle))


def test_rc2_04_boveda_sin_fuentes_sigue_siendo_rojo(tmp_path):
    env = {"S9K_VAULT_ROOT": str(_boveda(tmp_path, con_fuente=False)),
           "S9K_VAULT_REQUIRE_MOUNT": "0"}
    r = _fuentes_pobladas(env)
    assert r.estado == pf.ROJO, (
        "RC2-04: UNA BOVEDA SIN FUENTES NO DA ROJO: %s %s" % (r.estado, r.detalle))


def test_rc2_04_sin_boveda_el_catalogo_plano_sigue_igual(tmp_path):
    plano = _entorno_minimo(tmp_path)
    r = _fuentes_pobladas(plano)
    assert r.estado == pf.VERDE, (
        "RC2-04: EL CATALOGO PLANO DEJA DE MEDIRSE: %s %s" % (r.estado, r.detalle))
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    r = _fuentes_pobladas({"S9K_INGEST_SOURCES_DIR": str(vacio)})
    assert r.estado == pf.ROJO, (
        "RC2-04: UN PLANO VACIO SIN BOVEDA NO DA ROJO: %s %s" % (r.estado, r.detalle))


def test_rc2_04_sin_ninguna_declaracion_da_rojo():
    r = _fuentes_pobladas({})
    assert r.estado == pf.ROJO and "ni S9K_VAULT_ROOT ni S9K_INGEST_SOURCES_DIR" in r.detalle, (
        "RC2-04: SIN DECLARACION NO DA ROJO: %s %s" % (r.estado, r.detalle))


def test_rc2_04_la_resolucion_es_la_del_catalogo_no_una_copia():
    """`fuentes_pobladas` pregunta al catalogo (declaracion y listado); no re-deriva rutas."""
    import ast
    arbol = ast.parse(GUION.read_text(encoding="utf-8"))
    funcion = next(n for n in ast.walk(arbol)
                   if isinstance(n, ast.FunctionDef) and n.name == "fuentes_pobladas")
    llamadas = {n.func.attr for n in ast.walk(funcion)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert {"ubicacion_declarada", "listar_fuentes"} <= llamadas, (
        "RC2-04: fuentes_pobladas YA NO PREGUNTA AL CATALOGO DEL PRODUCTO")
    assert not ({"iterdir", "is_dir", "glob", "rglob", "walk", "listdir"} & llamadas), (
        "RC2-04: fuentes_pobladas RECORRE EL DISCO POR SU CUENTA (SEGUNDA RESOLUCION)")


# --- RC2-03: que `app` sea el del visor de ESTA release, y no un homonimo -----------------------
# En un interprete NUEVO (subproceso): aqui `app` aun no esta en `sys.modules`, asi que lo que
# decide es el `sys.path`, que es justo lo que el control tiene que vigilar.

_SONDA_VISOR = """
import importlib.util, sys
from pathlib import Path
guion, antes, raiz = sys.argv[1:4]
if antes:
    sys.path.insert(0, antes)
spec = importlib.util.spec_from_file_location("_pf_sonda", guion)
pf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pf
spec.loader.exec_module(pf)
try:
    pf._preparar_visor(Path(raiz))
except pf.VisorNoCargable as exc:
    print("NOCARGABLE", exc)
else:
    print("CARGADO", sys.modules["app.config"].__file__)
"""


def _paquete_app(base: Path) -> None:
    (base / "app").mkdir(parents=True)
    (base / "app" / "__init__.py").write_text("", encoding="utf-8")
    (base / "app" / "config.py").write_text("", encoding="utf-8")


def _sonda_visor(tmp_path: Path, raiz: Path, antes: str = "") -> str:
    r = subprocess.run([sys.executable, "-c", _SONDA_VISOR, str(GUION), antes, str(raiz)],
                       capture_output=True, text=True, cwd=str(tmp_path),
                       env=_env_de_subproceso({}), timeout=120)
    assert r.returncode == 0, "RC2-03: LA SONDA DEL VISOR NO SE EJECUTA: %s" % r.stderr
    return r.stdout


def test_rc2_03_el_visor_de_la_release_se_carga_cuando_no_hay_homonimo(tmp_path):
    """Control positivo: sin homonimo, la release de pega SI carga (la sonda mide)."""
    raiz = tmp_path / "release"
    _paquete_app(raiz / "viewer")
    out = _sonda_visor(tmp_path, raiz)
    assert out.startswith("CARGADO"), "RC2-03: LA SONDA NO CARGA NI EL VISOR BUENO: %s" % out


def test_rc2_03_un_app_homonimo_dentro_del_arbol_del_visor_no_pasa_por_el_visor(tmp_path):
    """Un `app` instalado BAJO `viewer/` (p. ej. en su venv) y por delante en `sys.path`."""
    raiz = tmp_path / "release"
    _paquete_app(raiz / "viewer")
    homonimo = raiz / "viewer" / ".venv" / "site-packages"
    _paquete_app(homonimo)
    out = _sonda_visor(tmp_path, raiz, antes=str(homonimo))
    assert out.startswith("NOCARGABLE") and "OTRO paquete" in out, (
        "RC2-03: UN PAQUETE HOMONIMO PASA POR EL VISOR: %s" % out)


def test_rc2_03_una_release_sin_visor_lo_dice(tmp_path):
    raiz = tmp_path / "release"
    raiz.mkdir()
    out = _sonda_visor(tmp_path, raiz)
    assert out.startswith("NOCARGABLE") and "no hay visor en esta release" in out, (
        "RC2-03: SIN VISOR NO LO DICE: %s" % out)

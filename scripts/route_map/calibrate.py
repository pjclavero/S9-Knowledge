#!/usr/bin/env python3
"""Calibración del mapa de rutas: inyecta defectos y exige que el mapa los vea.

Regla del operador: «Un instrumento que nunca se ha visto rojo no mide». Aquí se
introduce cada defecto en una COPIA desechable del árbol (nunca en el repo), se
recalcula el mapa, se comprueba que el hallazgo aparece, y se revierte borrando
la copia; el caso 0 (sin mutar) debe volver a verde.

Defectos inyectados:
  M0  control: árbol sin mutar                      -> ningún hallazgo nuevo
  M1  desmontar un router (include_router fuera)    -> rutas MUERTAS
  M2  enlace de navegación a ruta inexistente       -> enlace ROTO
  M3  quitar la autorización de una ruta            -> SIN-AUTH (2xx anónimo)
  M4  ruta nueva sin test                           -> NO PROBADA
  M5  ruta MENCIONADA en un comentario, inexistente -> NO cuenta como cubierta
  M6  test que ejercita una app PRIVADA de test     -> NO cuenta como probada
  M12 ruta con {param} y sin guardián, 404 al azar  -> NO sube "deniegan" (Q2)
  M13 POST sin guardián tras el muro del CSRF       -> el veredicto se mueve (Q1)
  M14 mismo router incluido dos veces               -> NO se declaran capturadas (Q3)

Uso:
    python3 scripts/route_map/calibrate.py --base <arbol_limpio> \
        --tested <tested_routes.json> --out <calibracion.json>
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _patch(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"ancla no encontrada en {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# --------------------------------------------------------------------------
# mutaciones
# --------------------------------------------------------------------------

def m0_control(tree: Path) -> None:
    return


def m1_desmontar_router(tree: Path) -> None:
    _patch(tree / "viewer/app/main.py",
           "app.include_router(readonly_router.router)",
           "# MUTACION M1: router desmontado\n# app.include_router(readonly_router.router)")


def m2_enlace_roto(tree: Path) -> None:
    # Ancla estable en las dos formas de `base.html` (con enlaces literales y
    # con navegación por datos): el enlace a la cuenta.
    _patch(tree / "viewer/app/templates/base.html",
           '<a href="/account">',
           '<a href="/ruta-que-no-existe">Fantasma</a>\n      <a href="/account">')


def m9_nav_de_datos_rota(tree: Path) -> None:
    """Navegación declarada como datos que apunta a una ruta no montada.

    Sólo aplica a árboles con `app/chassis.py`: ahí el menú no lleva enlaces
    literales, así que el detector de enlaces rotos tiene que mirar el contrato.
    """
    p = tree / "viewer/app/chassis.py"
    if not p.exists():
        return
    _patch(p, '    NavItem("Inicio", "home", None, 0),',
           '    NavItem("Inicio", "home", None, 0),\n'
           '    NavItem("Fantasma", "ruta_que_no_existe", None, 99),')


def m3_sin_autorizacion(tree: Path) -> None:
    p = tree / "viewer/app/routers/readonly.py"
    text = p.read_text(encoding="utf-8")
    marker = "user=Depends(html_guard),"
    if marker not in text:
        raise SystemExit("ancla M3 no encontrada")
    # Sólo la primera aparición (GET /entities). Se sustituye por un parámetro
    # normal (no por nada) para que el cuerpo del handler siga siendo válido:
    # lo que se retira es EXACTAMENTE el control de acceso, no el código.
    p.write_text(text.replace(marker, "user=None,  # MUTACION M3: sin guardián", 1),
                 encoding="utf-8")


def m4_ruta_nueva_sin_test(tree: Path) -> None:
    p = tree / "viewer/app/routers/readonly.py"
    p.write_text(p.read_text(encoding="utf-8") + '''

# MUTACION M4: ruta nueva, sin test que la ejercite
@router.get("/ruta-nueva-sin-test")
def ruta_nueva_sin_test(request: Request, user=Depends(html_guard)):
    return {"ok": True}
''', encoding="utf-8")


def m5_mencion_en_comentario(tree: Path) -> None:
    p = tree / "viewer/app/routers/readonly.py"
    p.write_text(p.read_text(encoding="utf-8") + '''

# MUTACION M5: mención en comentario de una ruta que NO existe.
# Aquí iría /ruta-solo-mencionada y también "/api/ruta-solo-mencionada".
# Un instrumento que cuenta menciones la daría por cubierta.
''', encoding="utf-8")


def m8_rol_degradado(tree: Path) -> None:
    """Baja el listón de /admin/audit de admin a "cualquier autenticado"."""
    p = tree / "viewer/app/routers/admin.py"
    text = p.read_text(encoding="utf-8")
    anchor = "    admin: User = Depends(require_admin),\n"
    i = text.index("async def admin_audit(")
    j = text.index(anchor, i)
    p.write_text(
        text[:j] + "    admin: User = Depends(require_authenticated_user),  # MUTACION M8\n"
        + text[j + len(anchor):], encoding="utf-8")
    _patch(p, "from app.auth.dependencies import require_admin",
           "from app.auth.dependencies import require_admin, require_authenticated_user")


def m10_ruta_capturada(tree: Path) -> None:
    """Ruta declarada DESPUÉS de una dinámica que la absorbe, y sin guardián.

    Es el caso que sobrevivía: `/sources/panel` la sirve `/sources/{source_id}`,
    así que su (inexistente) autorización nunca se evalúa y el barrido anónimo
    le atribuía el 403 del handler que la ensombrece. Debe salir CAPTURADA, no
    como ruta que deniega bien.
    """
    p = tree / "viewer/app/routers/readonly.py"
    p.write_text(p.read_text(encoding="utf-8") + '''

# MUTACION M10: ruta capturada por /sources/{source_id} y SIN guardián
@router.get("/sources/panel")
def ruta_capturada_sin_guardian(request: Request):
    return {"secreto": "servido sin autorización"}
''', encoding="utf-8")


def m11_senuelo_isinstance(tree: Path) -> None:
    """Guardián pasivo declarado y NO devuelto, con un `isinstance` señuelo.

    Derrota a un detector que busque subcadenas: el cuerpo contiene
    `isinstance(...)` y hasta el nombre `RedirectResponse`, pero no devuelve
    jamás la salida del guardián.
    """
    p = tree / "viewer/app/routers/readonly.py"
    p.write_text(p.read_text(encoding="utf-8") + '''

# MUTACION M11: guardián declarado, isinstance SEÑUELO, salida nunca devuelta
@router.get("/ruta-con-senuelo")
def ruta_con_senuelo(request: Request, user=Depends(html_guard)):
    datos = [1, 2, 3]
    if isinstance(datos, list):  # señuelo: no comprueba `user`
        datos = list(datos)
    # menciona RedirectResponse sin usarlo
    return {"ok": True, "tipo": "RedirectResponse"}
''', encoding="utf-8")


def m12_fuga_404_sin_guardian(tree: Path) -> None:
    """Ruta con `{param}`, SIN guardián alguno, que devuelve 404 con un id
    inexistente y el secreto con uno válido.

    Es el defecto Q2 del revisor. La sonda usa el id fabricado `probe`, recibe
    404 y —antes del arreglo— lo contaba como DENEGACIÓN: una ruta abierta de
    par en par SUBÍA el contador de rutas que deniegan (57 -> 58) mientras
    `rutas_sin_auth` seguía vacío. Afecta a toda ruta con parámetro, o sea a la
    mayoría de la API.
    """
    p = tree / "viewer/app/routers/readonly.py"
    p.write_text(p.read_text(encoding="utf-8") + '''

# MUTACION M12: ruta con parámetro y SIN guardián alguno
@router.get("/fuga/{item_id}")
def fuga_sin_guardian(request: Request, item_id: str):
    if item_id != "42":
        raise HTTPException(status_code=404, detail="no existe")
    return {"secreto": "servido a cualquiera sin autorización"}
''', encoding="utf-8")


def m13_post_sin_guardian(tree: Path) -> None:
    """Retira el guardián de `POST /partida/select` (defecto Q1 del revisor).

    Antes del arreglo el barrido anónimo era CIEGO en los 13 POST: el CSRF
    respondía 403 antes que el guardián, así que quitar el `Depends` no movía
    nada (`autorizadas` seguía en 57 y `rutas_sin_auth` vacío). Emitiendo un
    token CSRF válido, quien decide es el control de acceso, y su ausencia deja
    de poder disfrazarse de denegación.
    """
    p = tree / "viewer/app/routers/partida.py"
    text = p.read_text(encoding="utf-8")
    anchor = "    user: User = Depends(require_authenticated_user),\n"
    if anchor not in text:
        raise SystemExit("ancla M13 no encontrada")
    # Sin anotación de tipo a propósito: con `user: User = None` FastAPI lo
    # convertiría en un campo de cuerpo y el 422 taparía la mutación.
    p.write_text(text.replace(anchor, "    user=None,  # MUTACION M13: sin guardián\n", 1),
                 encoding="utf-8")


def m14_router_incluido_dos_veces(tree: Path) -> None:
    """Un mismo router incluido dos veces (defecto Q3 del revisor).

    Los dos includes comparten los MISMOS objetos `Route`. Etiquetar el objeto
    con el primer path visto hacía que las 10 rutas del segundo prefijo se
    declarasen CAPTURADAS y `no-evaluable-capturada` aunque respondan de verdad
    (comprobado: 200 con TestClient): su autorización dejaba de medirse EN
    SILENCIO. El resolvedor indexado por `(id(route), path)` las mide.
    """
    _patch(tree / "viewer/app/main.py",
           "app.include_router(readonly_router.router)",
           "app.include_router(readonly_router.router)\n"
           'app.include_router(readonly_router.router, prefix="/dup")  # MUTACION M14')


MUTATIONS = {
    "M0-control": m0_control,
    "M1-router-desmontado": m1_desmontar_router,
    "M2-enlace-roto": m2_enlace_roto,
    "M3-ruta-sin-auth": m3_sin_autorizacion,
    "M4-ruta-sin-test": m4_ruta_nueva_sin_test,
    "M5-mencion-en-comentario": m5_mencion_en_comentario,
    "M8-rol-degradado": m8_rol_degradado,
    "M9-nav-de-datos-rota": m9_nav_de_datos_rota,
    "M10-ruta-capturada": m10_ruta_capturada,
    "M11-senuelo-isinstance": m11_senuelo_isinstance,
    "M12-fuga-404-sin-guardian": m12_fuga_404_sin_guardian,
    "M13-post-sin-guardian-csrf-ciego": m13_post_sin_guardian,
    "M14-router-incluido-dos-veces": m14_router_incluido_dos_veces,
}


# --------------------------------------------------------------------------

def run_map(tree: Path, tested: Path | None) -> dict:
    # Fuera del árbol: con `--base .` el árbol es el propio repo y un `_map.json`
    # suelto acabaría en `git status` (y, con `git add .`, en un commit).
    out = Path(tempfile.mkdtemp(prefix="s9k-cal-map-")) / "_map.json"
    cmd = [sys.executable, str(tree / "scripts/route_map/route_map.py"),
           "--repo", str(tree), "--out", str(out), "--head-label", "calibracion"]
    if tested:
        cmd += ["--tested", str(tested)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=str(tree))
    if not out.exists():
        raise SystemExit(f"el mapa no se generó:\n{proc.stdout}\n{proc.stderr[-3000:]}")
    return json.loads(out.read_text(encoding="utf-8"))


def summarize(m: dict) -> dict:
    f = m["findings"]
    return {
        "montadas": m["counts"]["montadas"],
        "autorizadas": m["counts"]["autorizadas"],
        "authz": {r["key"]: r["authz_probe"] for r in m["routes"]},
        "denegacion_404_ambigua": [r["key"] for r in
                                   f.get("rutas_denegacion_404_ambigua", [])],
        "denegacion_no_atribuible": [r["key"] for r in
                                     f.get("rutas_denegacion_no_atribuible", [])],
        "contradiccion": [r["key"] for r in f.get("contradiccion_deniega_y_sirve", [])],
        "muertas": [d["key"] for d in f["rutas_muertas"]],
        "rotos": [f"{b['raw']} @ {b['from']}" for b in f["enlaces_rotos"]],
        "sin_auth": [r["key"] for r in f["rutas_sin_auth"]],
        "no_probadas": [r["key"] for r in f["rutas_no_probadas"]],
        "guardian_no_aplicado": [r["key"] for r in f["guardian_declarado_pero_no_aplicado"]],
        "capturadas": [f"{r['key']} <- {r['capturada_por']}" for r in f["rutas_capturadas"]],
        "roles_no_evaluables": [r["key"] for r in m["routes"]
                                if r["rol_minimo_observado"] == "no-evaluable-capturada"],
        "claves": [r["key"] for r in m["routes"]],
        "roles": {r["key"]: r["rol_minimo_observado"] for r in m["routes"]},
    }


def m6_app_privada(base: Path) -> dict:
    """Un test que ejercita una app PRIVADA no debe contar como cobertura."""
    tree = Path(tempfile.mkdtemp(prefix="s9k-cal-m6-"))
    shutil.copytree(base, tree, dirs_exist_ok=True)
    test = tree / "viewer/tests/test_calibracion_app_privada.py"
    test.write_text('''
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_app_privada_no_cuenta_como_cobertura():
    """Monta el router real en una app PROPIA (no `app.main.app`) y lo ejercita."""
    from app.routers import readonly

    private = FastAPI()
    private.include_router(readonly.router)
    client = TestClient(private)
    resp = client.get("/entities")
    assert resp.status_code in (200, 302, 401, 403, 500)
''', encoding="utf-8")
    out = tree / "_tested_m6.json"
    env = {"PYTHONPATH": str(tree / "scripts"), "S9K_ROUTE_PROBE_OUT": str(out)}
    import os

    e = dict(os.environ)
    e.update(env)
    subprocess.run([sys.executable, "-m", "pytest", str(test), "-q",
                    "-p", "route_map.pytest_route_probe"],
                   cwd=str(tree), env=e, capture_output=True, text=True, timeout=600)
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"exercised": {}}
    exercised = data.get("exercised", {})
    shutil.rmtree(tree, ignore_errors=True)
    return {"exercised": exercised,
            "detectado": "GET /entities" not in exercised,
            "esperado": "la sonda NO registra rutas de apps privadas"}


_ENUM_SNIPPET = '''
import json, sys
sys.path[:0] = [r"{repo}/data-engine/app", r"{repo}/viewer", r"{repo}/scripts"]
import os, secrets
os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
os.environ.setdefault("S9K_DEFAULT_WORKSPACE", "leyenda")
os.environ.setdefault("S9K_SAMPLE_GRAPH_PATH", r"{repo}/viewer/examples/sample_graph.json")
os.environ.setdefault("S9K_CSRF_SECRET", secrets.token_urlsafe(48))
from app.main import app
from route_map.route_map import iter_effective_routes
from fastapi.routing import APIRoute
naive = []
for r in app.router.routes:
    if isinstance(r, APIRoute):
        for m in sorted(r.methods or []):
            if m != "HEAD":
                naive.append(m + " " + r.path)
eff = []
for path, methods, _d, _e, _h, kind in iter_effective_routes(app):
    if kind != "route":
        continue
    for m in methods:
        if m != "HEAD":
            eff.append(m + " " + path)
try:
    app.url_path_for("entities_page")
    url_path_for_ok = True
except Exception:
    url_path_for_ok = False
print(json.dumps({{"naive": sorted(naive), "efectivo": sorted(eff),
                   "url_path_for_entities_page": url_path_for_ok}}))
'''


def m7_enumerador(base: Path, tested: Path | None) -> dict:
    """Calibra el CENSO: `app.routes` ve un visor casi vacío; el censo efectivo
    debe contener todas las rutas que de verdad sirvieron respuesta."""
    proc = subprocess.run([sys.executable, "-c", _ENUM_SNIPPET.format(repo=str(base))],
                          capture_output=True, text=True, timeout=600, cwd=str(base))
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    naive, eff = set(data["naive"]), set(data["efectivo"])
    servidas: set[str] = set()
    if tested and tested.exists():
        raw = json.loads(tested.read_text(encoding="utf-8")).get("exercised", {})
        # Los ficheros estáticos los sirve un Mount, no una ruta: fuera del censo.
        servidas = {k for k, v in raw.items()
                    if v.get("statuses") and not k.split(" ", 1)[-1].startswith("/static")}
    faltan_en_censo = sorted(servidas - eff)
    # La aserción con carga NO es `len(eff) > len(naive)` (se cumple sola): es
    # que el censo no pierda ninguna ruta que de verdad sirvió respuesta, y que
    # el censo ingenuo SÍ pierda algunas de ésas.
    perdidas_del_naive_que_sirvieron = sorted(servidas - naive)
    return {
        "rutas_censo_efectivo": len(eff),
        "rutas_censo_naive_app_routes": len(naive),
        "falsos_no_montados_del_censo_naive": sorted(eff - naive),
        "url_path_for_entities_page_funciona": data["url_path_for_entities_page"],
        "rutas_que_sirvieron_y_faltan_en_el_censo": faltan_en_censo,
        "rutas_que_sirvieron_y_pierde_el_censo_naive": perdidas_del_naive_que_sirvieron,
        "detectado": not faltan_en_censo and bool(perdidas_del_naive_que_sirvieron),
        "esperado": ("el censo no pierde ninguna ruta que sirvió respuesta, y el "
                     "censo ingenuo sí pierde varias de ellas"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--tested", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None,
                    help="lista separada por comas de casos a ejecutar (subcadena)")
    a = ap.parse_args(argv)
    solo = [s.strip() for s in a.only.split(",")] if a.only else None
    base = Path(a.base).resolve()
    tested = Path(a.tested).resolve() if a.tested else None

    baseline = summarize(run_map(base, tested))
    results = {"baseline": baseline, "casos": {}}

    for name, fn in MUTATIONS.items():
        if solo and not any(s in name for s in solo):
            continue
        tree = Path(tempfile.mkdtemp(prefix=f"s9k-cal-{name}-"))
        shutil.copytree(base, tree, dirs_exist_ok=True)
        fn(tree)
        s = summarize(run_map(tree, tested))
        delta = {
            "montadas": s["montadas"] - baseline["montadas"],
            "autorizadas": s["autorizadas"] - baseline["autorizadas"],
            "denegacion_404_ambigua_nuevas": sorted(
                set(s["denegacion_404_ambigua"]) - set(baseline["denegacion_404_ambigua"])),
            "denegacion_no_atribuible_nuevas": sorted(
                set(s["denegacion_no_atribuible"])
                - set(baseline["denegacion_no_atribuible"])),
            "contradicciones_nuevas": sorted(
                set(s["contradiccion"]) - set(baseline["contradiccion"])),
            "authz_cambiados": {k: [baseline["authz"].get(k), v]
                                for k, v in s["authz"].items()
                                if baseline["authz"].get(k) != v},
            "muertas_nuevas": sorted(set(s["muertas"]) - set(baseline["muertas"])),
            "rotos_nuevos": sorted(set(s["rotos"]) - set(baseline["rotos"])),
            "sin_auth_nuevas": sorted(set(s["sin_auth"]) - set(baseline["sin_auth"])),
            "no_probadas_nuevas": sorted(set(s["no_probadas"]) - set(baseline["no_probadas"])),
            "rutas_nuevas": sorted(set(s["claves"]) - set(baseline["claves"])),
            "guardian_no_aplicado_nuevos": sorted(
                set(s["guardian_no_aplicado"]) - set(baseline["guardian_no_aplicado"])),
            "capturadas_nuevas": sorted(set(s["capturadas"]) - set(baseline["capturadas"])),
            "roles_no_evaluables_nuevos": sorted(
                set(s["roles_no_evaluables"]) - set(baseline["roles_no_evaluables"])),
            "roles_cambiados": {k: [baseline["roles"].get(k), v]
                                for k, v in s["roles"].items()
                                if baseline["roles"].get(k) != v},
        }
        expect = {
            "M0-control": lambda d: not any([d["muertas_nuevas"], d["rotos_nuevos"],
                                             d["sin_auth_nuevas"], d["no_probadas_nuevas"],
                                             d["rutas_nuevas"], d["roles_cambiados"],
                                             d["guardian_no_aplicado_nuevos"],
                                             d["capturadas_nuevas"],
                                             d["authz_cambiados"],
                                             d["contradicciones_nuevas"],
                                             d["denegacion_404_ambigua_nuevas"],
                                             d["denegacion_no_atribuible_nuevas"]])
            and d["montadas"] == 0 and d["autorizadas"] == 0,
            "M1-router-desmontado": lambda d: len(d["muertas_nuevas"]) > 0 and d["montadas"] < 0,
            "M2-enlace-roto": lambda d: any("/ruta-que-no-existe" in x for x in d["rotos_nuevos"]),
            "M3-ruta-sin-auth": lambda d: "GET /entities" in d["sin_auth_nuevas"],
            # La ruta de M4 declara `Depends(html_guard)` y NO devuelve su
            # redirección: debe salir a la vez como no probada, como agujero
            # dinámico (2xx anónimo) y como guardián declarado y no aplicado.
            "M4-ruta-sin-test": lambda d: (
                "GET /ruta-nueva-sin-test" in d["no_probadas_nuevas"]
                and "GET /ruta-nueva-sin-test" in d["sin_auth_nuevas"]
                and "GET /ruta-nueva-sin-test" in d["guardian_no_aplicado_nuevos"]),
            "M5-mencion-en-comentario": lambda d: not any(
                "solo-mencionada" in k for k in d["rutas_nuevas"]) and not d["rutas_nuevas"],
            "M8-rol-degradado": lambda d: d["roles_cambiados"].get("GET /admin/audit")
            == ["admin", "viewer"],
            # No basta con que la vea: debe distinguirla. Una ruta capturada no
            # puede quedar con el mismo veredicto que /docs («ninguno sirve»).
            "M10-ruta-capturada": lambda d: (
                any(x.startswith("GET /sources/panel <- /sources/{source_id}")
                    for x in d["capturadas_nuevas"])
                and "GET /sources/panel" in d["roles_no_evaluables_nuevos"]),
            "M11-senuelo-isinstance": lambda d: (
                "GET /ruta-con-senuelo" in d["guardian_no_aplicado_nuevos"]
                and "GET /ruta-con-senuelo" in d["sin_auth_nuevas"]),
            # Q2: una ruta abierta no puede SUBIR el contador de denegaciones.
            # No basta con que aparezca: debe caer en el cubo ambiguo, cruzarse
            # con el rol observado y dejar `autorizadas` intacto.
            "M12-fuga-404-sin-guardian": lambda d: (
                "GET /fuga/{item_id}" in d["denegacion_404_ambigua_nuevas"]
                and "GET /fuga/{item_id}" in d["contradicciones_nuevas"]
                and d["montadas"] == 1 and d["autorizadas"] == 0),
            # Q1: retirar el guardián de un POST tiene que MOVER algo. Antes del
            # arreglo el 403 del CSRF lo tapaba y el veredicto seguía siendo
            # "denegada".
            "M13-post-sin-guardian-csrf-ciego": lambda d: (
                d["authz_cambiados"].get("POST /partida/select", [None, None])[0]
                == "denegada"
                and d["authz_cambiados"].get("POST /partida/select", [None, None])[1]
                != "denegada"
                and d["autorizadas"] < 0),
            # Q3: el segundo montaje del mismo router NO está capturado. Aquí lo
            # que se exige es la AUSENCIA de un falso positivo que además
            # silenciaba la medición de autorización de 10 rutas vivas.
            "M14-router-incluido-dos-veces": lambda d: (
                d["montadas"] == 10
                and len([k for k in d["rutas_nuevas"] if k.startswith("GET /dup/")]) == 10
                and not d["capturadas_nuevas"]
                and not d["roles_no_evaluables_nuevos"]
                and all(v[1] not in ("CAPTURADA", "sin-sonda", "inconcluyente")
                        for k, v in d["authz_cambiados"].items()
                        if k.startswith("GET /dup/"))),
            "M9-nav-de-datos-rota": lambda d: (
                any("ruta_que_no_existe" in x for x in d["rotos_nuevos"])
                if (base / "viewer/app/chassis.py").exists() else True),
        }[name]
        results["casos"][name] = {"delta": delta, "detectado": bool(expect(delta))}
        shutil.rmtree(tree, ignore_errors=True)

    if not solo or any("M6" in s for s in solo):
        results["casos"]["M6-app-privada-de-test"] = m6_app_privada(base)
    if not solo or any("M7" in s for s in solo):
        results["casos"]["M7-censo-de-rutas"] = m7_enumerador(base, tested)

    # Reversión: el árbol base, intacto, debe volver a dar exactamente lo mismo.
    revert = summarize(run_map(base, tested))
    results["reversion_identica"] = revert == baseline

    text = json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    ok = all(c["detectado"] for c in results["casos"].values()) and results["reversion_identica"]
    print(json.dumps({k: v["detectado"] for k, v in results["casos"].items()}, indent=2))
    print("reversion_identica:", results["reversion_identica"])
    print("CALIBRACION:", "OK" if ok else "FALLIDA")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

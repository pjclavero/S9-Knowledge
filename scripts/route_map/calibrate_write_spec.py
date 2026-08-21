#!/usr/bin/env python3
"""Control negativo de la especificación de escritura (`write_spec.py`).

Una afirmación de seguridad no vale nada hasta que existe una prueba capaz de
ponerse ROJA. Aquí se ponen rojas, **una mutación por vez**, **un subproceso por
mutación** y **sobre copias** del árbol, con el árbol real verificado por
SHA-256 del contenido al terminar.

Casos (todos derivados, ninguno escrito a mano):

  W0            árbol limpio -> VERDE.
  MET-<nombre>  `@router.post` -> `@router.get` en CADA endpoint de escritura,
                nombre a nombre. Debe salir `metodo-seguro-en-endpoint-de-
                escritura` **y** `escritura-servida-por-get`, y ambos deben
                NOMBRAR a ese endpoint.
  ALI-<nombre>  se AÑADE un alias `@router.get(<misma ruta>)` a CADA endpoint de
                escritura, sin tocar el `post`. Mismos hallazgos.
  PUT-<nombre>  `@router.post` -> `@router.put` (el método cambia pero sigue
                siendo inseguro): lo coge SÓLO el contrato de cliente (C3).

Anclas: cada mutación se localiza por los OFFSETS del nodo decorador en el AST,
no por búsqueda de texto, así que dos mutaciones no pueden compartir ancla. Se
comprueba además que **todo hallazgo de un caso nombra al endpoint mutado**: un
rojo prestado de otro endpoint invalidaría la atribución.

Uso:  python3 scripts/route_map/calibrate_write_spec.py [--out informe.json]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MINIMO_CASOS = 44
MINIMO_ABLACIONES = 6

METODOS_HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}


# ---------------------------------------------------------------------------
# utilidades de árbol
# ---------------------------------------------------------------------------
def hash_arbol(raices: list[Path]) -> str:
    h = hashlib.sha256()
    for raiz in sorted(raices):
        for f in sorted(p for p in raiz.rglob("*") if p.is_file()):
            if "__pycache__" in f.parts:
                continue
            h.update(str(f.relative_to(REPO)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def copia(destino: Path) -> Path:
    def ignorar(_d, nombres):
        return [n for n in nombres
                if n in ("__pycache__", ".pytest_cache", "node_modules")]

    for sub in ("viewer", "scripts", "contracts"):
        shutil.copytree(REPO / sub, destino / sub, ignore=ignorar, symlinks=True)
    for pyc in destino.rglob("*.pyc"):
        pyc.unlink()
    for d in list(destino.rglob("__pycache__")):
        shutil.rmtree(d, ignore_errors=True)
    return destino


def ejecutar(raiz: Path) -> dict:
    """Un subproceso por invocación: `route_map`/`app.main` son singletons."""
    salida = raiz / "write_spec_out.json"
    cmd = [sys.executable, str(raiz / "scripts" / "route_map" / "write_spec.py"),
           "--repo", str(raiz), "--out", str(salida)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(raiz / "scripts")
    # CAUSA RAIZ de la contaminacion del arbol, demostrada: varias rutas por
    # defecto del producto son RELATIVAS (p.ej. `viewer/state/...`), asi que se
    # resuelven contra el CWD del proceso. Sin `cwd=`, el subproceso hereda el
    # directorio del AUDITOR aunque este auditando una COPIA, y cualquier
    # escritura cae en el arbol real. Anclar el CWD a la raiz auditada lo cierra
    # POR CONSTRUCCION, para toda variable relativa presente o futura, en vez de
    # ir neutralizando variables una a una en una lista mantenida a mano.
    # El `setdefault` de `write_spec.bootstrap` se queda como cinturon.
    proc = subprocess.run(cmd, env=env, cwd=str(raiz),
                          capture_output=True, text=True, timeout=900)
    informe = {}
    if salida.exists():
        informe = json.loads(salida.read_text(encoding="utf-8"))
    return {"rc": proc.returncode,
            "hallazgos": informe.get("hallazgos", {}),
            "resumen": informe.get("resumen", {}),
            "stderr": proc.stderr[-2000:]}


# ---------------------------------------------------------------------------
# localización de decoradores por AST (ancla única por offsets)
# ---------------------------------------------------------------------------
def decorador_de(fichero: Path, funcion: str) -> tuple[int, int, str, int]:
    """`(inicio, fin, texto, lineno)` del decorador de ruta de `funcion`.

    Se devuelven OFFSETS absolutos dentro del fichero. Dos endpoints distintos
    tienen offsets distintos por construcción: no hay forma de que una mutación
    caiga sobre el ancla de otra.
    """
    texto = fichero.read_text(encoding="utf-8")
    arbol = ast.parse(texto)
    corto = funcion.split(".")[-1]
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if nodo.name != corto:
            continue
        for dec in nodo.decorator_list:
            f = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(f, ast.Attribute) and f.attr.lower() in METODOS_HTTP:
                seg = ast.get_source_segment(texto, dec)
                ini = _offset(texto, dec.lineno, dec.col_offset)
                fin = _offset(texto, dec.end_lineno, dec.end_col_offset)
                return ini, fin, seg or texto[ini:fin], dec.lineno
    raise AssertionError(f"sin decorador de ruta para {funcion} en {fichero}")


def _offset(texto: str, lineno: int, col: int) -> int:
    lineas = texto.splitlines(keepends=True)
    return sum(len(l) for l in lineas[:lineno - 1]) + col


def mutar_metodo(fichero: Path, funcion: str, nuevo: str) -> str:
    ini, fin, seg, _ = decorador_de(fichero, funcion)
    texto = fichero.read_text(encoding="utf-8")
    # el segmento del decorador que devuelve el AST NO incluye la `@`.
    mutado = re.sub(r"^([\w\.]+)\.\w+\(", rf"\1.{nuevo}(", seg, count=1)
    if mutado == seg:
        raise AssertionError(f"mutación no aplicable en {funcion}: {seg[:80]!r}")
    fichero.write_text(texto[:ini] + mutado + texto[fin:], encoding="utf-8")
    return mutado


def anadir_alias_get(fichero: Path, funcion: str) -> str:
    ini, fin, seg, _ = decorador_de(fichero, funcion)
    texto = fichero.read_text(encoding="utf-8")
    alias = re.sub(r"^([\w\.]+)\.\w+\(", r"\1.get(", seg, count=1)
    if alias == seg:
        raise AssertionError(f"alias no aplicable en {funcion}")
    # `ini` cae justo DESPUÉS de la `@` del decorador original.
    fichero.write_text(texto[:ini] + alias + "\n@" + texto[ini:], encoding="utf-8")
    return alias


# ---------------------------------------------------------------------------
# casos
# ---------------------------------------------------------------------------
#: Hallazgos que se admiten en el árbol LIMPIO: **NINGUNO**.
#:
#: Hasta 2026-08-19 aquí figuraba `lectura-que-escribe`, porque los dos GET de
#: `health_admin.py` escribían dentro de la propia petición. El operador decidió
#: que eso era un defecto de las RUTAS y no de la puerta —sin exenciones ni
#: whitelists—, se arreglaron las rutas (la escritura pasó a
#: `POST /admin/health/snapshot`) y esta tupla vuelve a estar vacía. Es la
#: diferencia entre «el instrumento ya no se queja» y «el defecto ya no existe».
HALLAZGOS_DE_BASE_ADMITIDOS: tuple[str, ...] = ()


def linea_base(base: Path) -> tuple[list[dict], dict]:
    """Endpoints de escritura y hallazgos del árbol LIMPIO.

    No hay lista de endpoints en este arnés: si mañana aparece uno nuevo, este
    control negativo lo muta también, sin que nadie lo escriba aquí.
    """
    r = ejecutar(base)
    salida = base / "write_spec_out.json"
    informe = json.loads(salida.read_text(encoding="utf-8"))
    inesperados = {k: v for k, v in r["hallazgos"].items()
                   if k not in HALLAZGOS_DE_BASE_ADMITIDOS}
    if inesperados:
        raise AssertionError(f"el árbol limpio tiene hallazgos no admitidos: {inesperados}")
    return informe["endpoints_de_escritura"], r["hallazgos"]


def fichero_de(raiz: Path, clave: str) -> tuple[Path, str]:
    modulo, _, funcion = clave.rpartition(".")
    return raiz / "viewer" / (modulo.replace(".", "/") + ".py"), funcion


#: Campos de un hallazgo que IDENTIFICAN al endpoint. La atribución se compara
#: contra ESTOS campos y por IGUALDAD, no buscando la cadena en el JSON entero:
#: `"/admin/users/1" in "/admin/users/1/unlock"` es cierto, así que la versión
#: por subcadena habría dado por atribuido un hallazgo de otra ruta. Hoy no
#: cambiaba ningún veredicto, pero la afirmación era más débil que su docstring.
CAMPOS_DE_IDENTIDAD = ("path", "url", "endpoint", "atendido_por", "esperado",
                       "ruta_que_manda")


def _agujas(path: str, clave: str) -> set[str]:
    """Valores EXACTOS con los que un hallazgo puede nombrar al endpoint mutado."""
    return {path, re.sub(r"\{[^}]+\}", "1", path), clave}


def _nombra(entrada: dict, agujas: set[str]) -> bool:
    return any(entrada.get(c) in agujas for c in CAMPOS_DE_IDENTIDAD)


def hallazgos_nombran(hallazgos: dict, path: str, clave: str,
                      base: dict | None = None) -> tuple[bool, list]:
    """¿TODOS los hallazgos NUEVOS nombran al endpoint mutado? (nada prestado)."""
    agujas = _agujas(path, clave)
    de_base = {(k, json.dumps(e, sort_keys=True, ensure_ascii=False))
               for k, v in (base or {}).items() for e in v}
    ajenos = []
    for nombre, entradas in hallazgos.items():
        for e in entradas:
            if (nombre, json.dumps(e, sort_keys=True, ensure_ascii=False)) in de_base:
                continue
            if not (isinstance(e, dict) and _nombra(e, agujas)):
                ajenos.append({"hallazgo": nombre, "entrada": e})
    return not ajenos, ajenos


def caso_verde(nombre: str, mutar, path: str) -> dict:
    """Control de FALSO POSITIVO: la mutación es legítima y debe salir VERDE.

    Es tan obligatorio como los rojos. Un instrumento que se pone rojo con todo
    no distingue nada, y el modo de fallo —volverse estricto de más— no se ve
    mirando sólo los casos que deben detectarse.
    """
    with tempfile.TemporaryDirectory(prefix="s9k-calws-") as td:
        raiz = copia(Path(td))
        detalle = mutar(raiz)
        r = ejecutar(raiz)
        return {
            "caso": nombre, "endpoint": path, "path": path,
            "mutacion": detalle, "rc": r["rc"],
            "hallazgos": sorted(r["hallazgos"]), "esperados": [],
            "faltan": [], "ancla_unica": True,
            "hallazgos_ajenos": [{"hallazgo": k, "entrada": v}
                                 for k, v in r["hallazgos"].items()],
            "corroborado_por": [], "obligatorio": True,
            "detectado": r["rc"] == 0 and not r["hallazgos"],
            "estado": "OK" if (r["rc"] == 0 and not r["hallazgos"]) else "FALLO",
        }


def caso(nombre: str, mutar, path: str, clave: str, esperados: list[str],
         corroboran: list[str] | None = None, obligatorio: bool = True,
         base: dict | None = None) -> dict:
    """Ejecuta UNA mutación en una copia y comprueba el motivo del rojo.

    `esperados` son los hallazgos que TIENEN que salir nombrando al endpoint
    mutado; `corroboran` son instrumentos redundantes cuya ausencia se REGISTRA
    (no se exige) porque hay configuraciones en las que no pueden actuar: si
    otra ruta ENSOMBRECE la mutada (`GET /admin/users/new` lo atiende la página
    de alta, `POST /admin/users/new` lo captura `POST /admin/users/{user_id}`),
    la petición nunca llega al manejador mutado. Exigirlos sería exigir un rojo
    que el instrumento no puede dar, y acabaría en un arnés que miente.
    """
    with tempfile.TemporaryDirectory(prefix="s9k-calws-") as td:
        raiz = copia(Path(td))
        detalle = mutar(raiz)
        r = ejecutar(raiz)
        h = r["hallazgos"]
        agujas = _agujas(path, clave)
        faltan = [e for e in esperados
                  if not any(isinstance(x, dict) and _nombra(x, agujas)
                             for x in h.get(e, []))]
        unico, ajenos = hallazgos_nombran(h, path, clave, base)
        corroborado = [e for e in (corroboran or [])
                       if any(isinstance(x, dict) and _nombra(x, agujas)
                              for x in h.get(e, []))]
        return {
            "caso": nombre, "endpoint": clave, "path": path,
            "mutacion": detalle, "rc": r["rc"],
            "hallazgos": sorted(h), "esperados": esperados,
            "faltan": faltan, "ancla_unica": unico, "hallazgos_ajenos": ajenos,
            "corroborado_por": corroborado, "obligatorio": obligatorio,
            "detectado": r["rc"] == 1 and not faltan,
            "estado": ("OK" if (r["rc"] == 1 and not faltan and unico)
                       else ("NO-DETECTADO" if not obligatorio else "FALLO")),
        }


#: Cada ablación se cobra sobre el caso que SÓLO ese control detecta, que es la
#: única forma de medir necesidad: C1/C2 (clasificación + ejecución) son los
#: únicos que ven el ALIAS —el `post` original sigue ahí, así que el formulario
#: de la plantilla sigue funcionando y C3 calla—, y C3 es el único que ve el
#: cambio `POST -> PUT` —el método sigue siendo inseguro, así que C1/C2 callan—.
#: SUPERVIVIENTES: formas de declarar un endpoint de escritura que una versión
#: anterior de la clasificación NO veía, y que salían VERDES en silencio. Se
#: inyectan como endpoints NUEVOS (no se muta ninguno existente) porque la
#: pregunta que responden es «¿queda cubierto SOLO un endpoint de escritura
#: nuevo?», que es justo la afirmación que el revisor tumbó.
PREAMBULO_ADV = ("from __future__ import annotations\n"
                 "from typing import Annotated\n"
                 "from pathlib import Path as _RutaAdv\n"
                 "from fastapi import Form as _FormAlias\n"
                 "from app.health import storage as _AlmacenAdv\n"
                 "from app.health.models import HealthReport as _InformeAdv")

ADVERSARIOS = {
    # estilo `Annotated[..., Form()]`, el que recomienda hoy la documentación de
    # FastAPI: no deja NADA en `args.defaults`.
    "ADV-annotated": ("/admin/adversarial/annotated", '''

@router.get("/adversarial/annotated")
async def adversarial_annotated(nombre: Annotated[str, Form()]):
    _RutaAdv("/tmp/s9k-adv-annotated.txt").write_text(nombre)
    return {"ok": True}
'''),
    # alias de importación: el mismo `Form` con otro nombre.
    "ADV-alias": ("/admin/adversarial/alias", '''

@router.get("/adversarial/alias")
async def adversarial_alias(nombre: str = _FormAlias(...)):
    _RutaAdv("/tmp/s9k-adv-alias.txt").write_text(nombre)
    return {"ok": True}
'''),
    # estilo clásico, que sí se veía: control positivo del propio arnés.
    "ADV-clasico": ("/admin/adversarial/clasico", '''

@router.get("/adversarial/clasico")
async def adversarial_clasico(nombre: str = Form(...)):
    _RutaAdv("/tmp/s9k-adv-clasico.txt").write_text(nombre)
    return {"ok": True}
'''),
    # un GET que escribe estado durable: exactamente el defecto que el operador
    # se negó a eximir. Lo coge la derivación de durabilidad, y sólo ella.
    "ADV-lectura-que-escribe": ("/admin/adversarial/escribe", '''

@router.get("/adversarial/escribe")
async def adversarial_lectura_que_escribe():
    _AlmacenAdv.save_report(_InformeAdv())
    return {"ok": True}
'''),
    # escritura montada SIN ninguna evidencia que la clasificación pueda ver:
    # la red que no depende de que F1 acierte.
    "ADV-mudo": ("/admin/adversarial/mudo", '''

@router.post("/adversarial/mudo")
async def adversarial_mudo():
    return {"ok": True}
'''),
}

ESPERADO_ADV = {
    "ADV-annotated": ["metodo-seguro-en-endpoint-de-escritura"],
    "ADV-alias": ["metodo-seguro-en-endpoint-de-escritura"],
    "ADV-clasico": ["metodo-seguro-en-endpoint-de-escritura"],
    "ADV-mudo": ["metodo-de-escritura-sin-evidencia"],
    "ADV-lectura-que-escribe": ["lectura-que-escribe"],
}

#: CONTROL DE FALSO POSITIVO, tan obligatorio como los rojos: un `GET` GENUINO
#: de lectura tiene que salir VERDE. Sin él, «todo rojo» pasaría por bueno y el
#: instrumento se volvería estricto de más sin que nadie lo notara.
LECTURA_GENUINA = ("/admin/adversarial/lectura", '''

@router.get("/adversarial/lectura")
async def adversarial_lectura_genuina():
    return {"componentes": len(_AlmacenAdv.load_last() or {}), "ok": True}
''')


def inyectar(raiz: Path, codigo: str) -> str:
    # Anade un endpoint NUEVO a un router real, con su preambulo de imports.
    f = raiz / "viewer" / "app" / "routers" / "admin.py"
    texto = f.read_text(encoding="utf-8")
    if texto.count("from __future__ import annotations") != 1:
        raise AssertionError("preambulo no aplicable: `from __future__` no aparece 1 vez")
    texto = texto.replace("from __future__ import annotations", PREAMBULO_ADV, 1)
    f.write_text(texto + codigo, encoding="utf-8")
    return codigo.strip().splitlines()[0]


ABLACIONES = [
    # (id, caso o familia que debe DEJAR de detectarse, sustituciones en write_spec.py)
    ("AB-C1C2", "ALI", [
        ('        seguros = sorted(set(f["metodos"]) & METODOS_SEGUROS)',
         '        seguros = []'),
        ('        if atendido in claves_de_escritura:',
         '        if False:'),
        ('        if not (set(f["metodos"]) & METODOS_DE_ESCRITURA):',
         '        if False:'),
    ]),
    ("AB-C1bis", "ADV-mudo", [
        ('        inseguros = sorted(set(f["metodos"]) & METODOS_DE_ESCRITURA)',
         '        inseguros = []'),
    ]),
    ("AB-C3", "PUT", [
        ('        debe = _ruta_mas_especifica(filas_vivas, c["url"])\n'
         '        if debe is None:',
         '        debe = _ruta_mas_especifica(filas_vivas, c["url"])\n'
         '        if True:'),
        ('        if estado in (404, 405, -1, None):', '        if False:'),
    ]),
    ("AB-C3-especificidad", "PUT-admin.admin_users_new_submit", [
        ('        debe = _ruta_mas_especifica(filas_vivas, c["url"])',
         '        debe = None'),
    ]),
    ("AB-F1", "ALI", [
        ('            hoja = _es_declarador_de_cuerpo(_resolver(ast.unparse(d.func), importaciones))',
         '            hoja = ""'),
        ('        ev |= _evidencia_en_anotacion(a.annotation, importaciones)',
         '        ev |= set()'),
        ('        if RE_CSRF_VERIFICA.search(nombre or ""):', '        if False:'),
        ('        primitiva = _escribe_de_verdad(canon)', '        primitiva = ""'),
        ('        anota("espec-vacia", {"motivo": "cero endpoints de escritura clasificados"})',
         '        pass'),
        ('        anota("espec-vacia", {"motivo": "cero contratos de cliente de escritura"})',
         '        pass'),
    ]),
    # La corrección del superviviente, medida: sin el recorrido de la ANOTACIÓN,
    # `Annotated[str, Form()]` vuelve a ser invisible y el endpoint nuevo pasa en
    # verde, mientras el estilo clásico se sigue detectando.
    ("AB-F1-annotated", "ADV-annotated", [
        ('        ev |= _evidencia_en_anotacion(a.annotation, importaciones)',
         '        ev |= set()'),
    ]),
    # ...y sin resolver los alias de importación, `Form as _FormAlias` también.
    ("AB-F1-alias", "ADV-alias", [
        ('    canon = importaciones.get(raiz, raiz)', '    canon = raiz'),
    ]),
    # Sin derivar la durabilidad del CÓDIGO del invocable, un GET que escribe
    # vuelve a ser invisible. Se cobra sobre el GET INYECTADO (la línea base ya
    # no tiene ninguno: se arreglaron las rutas).
    ("AB-durabilidad", "ADV-lectura-que-escribe", [
        ('        primitiva = _escribe_de_verdad(canon)', '        primitiva = ""'),
    ]),
]


def sustituir(fichero: Path, viejo: str, nuevo: str) -> None:
    texto = fichero.read_text(encoding="utf-8")
    if texto.count(viejo) != 1:
        raise AssertionError(f"ablación no aplicable: {viejo[:70]!r} aparece "
                             f"{texto.count(viejo)} veces")
    fichero.write_text(texto.replace(viejo, nuevo), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="")
    ap.add_argument("--solo", default="", help="subconjunto de endpoints (subcadena) "
                                               "para depurar el arnés; NO es la corrida válida")
    args = ap.parse_args(argv)

    raices = [REPO / "viewer", REPO / "scripts" / "route_map", REPO / "contracts"]
    hash_antes = hash_arbol(raices)

    casos: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="s9k-calws-base-") as td:
        base = copia(Path(td))
        r0 = ejecutar(base)
        inesperados = {k: v for k, v in r0["hallazgos"].items()
                       if k not in HALLAZGOS_DE_BASE_ADMITIDOS}
        casos.append({"caso": "W0", "rc": r0["rc"],
                      "hallazgos": sorted(r0["hallazgos"]),
                      "hallazgos_de_base": {k: len(v) for k, v in r0["hallazgos"].items()},
                      "estado": "OK" if not inesperados else "FALLO",
                      "stderr": "" if not inesperados else r0["stderr"]})
        escrituras, base_hallazgos = linea_base(base)

    # --- un caso por endpoint de escritura, nombre a nombre -----------------
    con_contrato = _paths_con_contrato_de_cliente()
    if args.solo:
        escrituras = [e for e in escrituras if args.solo in e["endpoint"]]
    sin_metodo_de_escritura = []
    for e in escrituras:
        clave, path = e["endpoint"], e["path"]
        if not set(e["metodos"]) & {"POST", "PUT", "PATCH", "DELETE"}:
            # No hay `post` que cambiar: son los GET que escriben de la línea
            # base. Se anotan para que su ausencia de casos sea VISIBLE.
            sin_metodo_de_escritura.append(clave)
            continue
        # nombre ÚNICO por caso: dos routers distintos tienen un `decide`, y dos
        # casos con el mismo nombre son dos casos indistinguibles en el informe.
        partes = clave.split(".")
        corto = ".".join(partes[-2:]) if len(partes) >= 2 else clave

        casos.append(caso(f"MET-{corto}",
                          lambda raiz, c=clave: mutar_metodo(*fichero_de(raiz, c), "get"),
                          path, clave,
                          ["metodo-seguro-en-endpoint-de-escritura"],
                          corroboran=["escritura-servida-por-get",
                                      "contrato-de-cliente-roto"], base=base_hallazgos))
        casos.append(caso(f"ALI-{corto}",
                          lambda raiz, c=clave: anadir_alias_get(*fichero_de(raiz, c)),
                          path, clave,
                          ["metodo-seguro-en-endpoint-de-escritura"],
                          corroboran=["escritura-servida-por-get"],
                          base=base_hallazgos))
        if path in con_contrato:
            # El cambio de método que sigue siendo INSEGURO (`POST -> PUT`) sólo
            # lo puede ver el contrato de cliente, y no siempre: si otra ruta
            # captura la URL del formulario, la petición no da 405 y no hay
            # nada que ver. Esos casos se registran como NO-DETECTADO, no se
            # esconden ni se convierten en fallo del arnés.
            casos.append(caso(f"PUT-{corto}",
                              lambda raiz, c=clave: mutar_metodo(*fichero_de(raiz, c), "put"),
                              path, clave, ["contrato-de-cliente-roto"],
                              obligatorio=False, base=base_hallazgos))

    # --- control de falso positivo: un GET GENUINO de lectura sale VERDE -----
    casos.append(caso_verde("FP-lectura-genuina",
                            lambda raiz, c=LECTURA_GENUINA[1]: inyectar(raiz, c),
                            LECTURA_GENUINA[0]))

    # --- supervivientes: endpoints de escritura NUEVOS, en varios estilos ---
    for nombre_adv, (ruta_adv, codigo_adv) in ADVERSARIOS.items():
        casos.append(caso(nombre_adv,
                          lambda raiz, c=codigo_adv: inyectar(raiz, c),
                          ruta_adv, ruta_adv, ESPERADO_ADV[nombre_adv],
                          base=base_hallazgos))

    # --- ablaciones ---------------------------------------------------------
    ablaciones = []
    familias = {"MET": lambda raiz, c: mutar_metodo(*fichero_de(raiz, c), "get"),
                "PUT": lambda raiz, c: mutar_metodo(*fichero_de(raiz, c), "put"),
                "ALI": lambda raiz, c: anadir_alias_get(*fichero_de(raiz, c))}
    def _referencia(clave_ref):
        exacto = next((c for c in casos if c["caso"] == clave_ref), None)
        return exacto or next((c for c in casos
                               if c["caso"].startswith(clave_ref.split("-")[0] + "-")), None)
    for aid, familia, subs in ABLACIONES:
        if familia == "W0-lectura-que-escribe":  # histórico: la base ya es verde
            # No hay mutación: la detección que debe desaparecer es la de la
            # LÍNEA BASE (los GET que escriben del árbol limpio).
            with tempfile.TemporaryDirectory(prefix="s9k-abl-") as td:
                raiz = copia(Path(td))
                ws = raiz / "scripts" / "route_map" / "write_spec.py"
                for viejo, nvo in subs:
                    sustituir(ws, viejo, nvo)
                r = ejecutar(raiz)
                cobrada = "lectura-que-escribe" not in r["hallazgos"]
                ablaciones.append({"ablacion": aid, "caso": "W0",
                                   "rc_ablado": r["rc"],
                                   "esperados_del_caso": ["lectura-que-escribe"],
                                   "estado": "COBRADA" if cobrada else "NO-COBRADA",
                                   "hallazgos": sorted(r["hallazgos"])})
            continue
        ref = _referencia(familia)
        if ref is None:
            ablaciones.append({"ablacion": aid, "estado": "SIN-CASO"})
            continue
        clave = ref["endpoint"]
        with tempfile.TemporaryDirectory(prefix="s9k-abl-") as td:
            raiz = copia(Path(td))
            ws = raiz / "scripts" / "route_map" / "write_spec.py"
            for viejo, nuevo in subs:
                sustituir(ws, viejo, nuevo)
            fam = ref["caso"].split("-")[0]
            if fam == "ADV":
                inyectar(raiz, ADVERSARIOS[ref["caso"]][1])
            else:
                familias[fam](raiz, clave)
            r = ejecutar(raiz)
            # «Cobrada» ya no puede ser `rc==0`: el árbol limpio sale rojo por
            # los GET de health. Se cobra si DESAPARECEN todos los hallazgos que
            # ese caso exigía, es decir, si el control ablado era el que los
            # producía.
            restantes = {k: v for k, v in r["hallazgos"].items()
                         if k not in HALLAZGOS_DE_BASE_ADMITIDOS}
            cobrada = not any(k in restantes for k in ref["esperados"])
            ablaciones.append({"ablacion": aid, "caso": ref["caso"],
                               "rc_ablado": r["rc"],
                               "esperados_del_caso": ref["esperados"],
                               "estado": "COBRADA" if cobrada else "NO-COBRADA",
                               "hallazgos": sorted(r["hallazgos"])})

    hash_despues = hash_arbol(raices)
    fallos = []
    if hash_antes != hash_despues:
        fallos.append("el árbol REAL cambió durante la calibración")
    malos = [c for c in casos if c["estado"] == "FALLO"]
    put = [c for c in casos if c["caso"].startswith("PUT-")]
    put_detectados = [c for c in put if c["detectado"]]
    if put and not put_detectados:
        fallos.append("ningún caso POST->PUT se detectó: el contrato de cliente "
                      "no está actuando")
    if malos:
        fallos.append(f"{len(malos)} casos en FALLO: "
                      f"{[c['caso'] for c in malos][:10]}")
    if len(casos) < MINIMO_CASOS:
        fallos.append(f"sólo {len(casos)} casos (mínimo {MINIMO_CASOS})")
    cobradas = [a for a in ablaciones if a["estado"] == "COBRADA"]
    if len(cobradas) < MINIMO_ABLACIONES:
        fallos.append(f"sólo {len(cobradas)} ablaciones cobradas "
                      f"(mínimo {MINIMO_ABLACIONES})")

    informe = {
        "casos": casos, "ablaciones": ablaciones,
        "casos_ejecutados": len(casos), "ablaciones_cobradas": len(cobradas),
        "endpoints_sin_metodo_de_escritura": sin_metodo_de_escritura,
        "put_detectados": [c["caso"] for c in put_detectados],
        "put_no_detectados": [c["caso"] for c in put if not c["detectado"]],
        "hash_arbol_antes": hash_antes, "hash_arbol_despues": hash_despues,
        "fallos": fallos,
        "veredicto": "OK" if not fallos else "FALLO",
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(informe, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    print(json.dumps({k: v for k, v in informe.items() if k != "casos"},
                     indent=2, ensure_ascii=False))
    for c in casos:
        print(f"  {c['estado']:5} {c['caso']:42} rc={c.get('rc')} "
              f"{','.join(c.get('hallazgos', []))}")
    return 0 if not fallos else 1


def _paths_con_contrato_de_cliente() -> set[str]:
    """Paths de escritura que alguna plantilla/JS declara (para el caso PUT)."""
    sys.path.insert(0, str(REPO / "scripts"))
    from route_map import write_spec

    app = write_spec.cargar_app(REPO)
    contratos = write_spec.contratos_de_cliente(REPO, app)
    urls = {c["url"] for c in contratos if c["metodo"] not in write_spec.METODOS_SEGUROS}
    salida = set()
    for f in write_spec.rutas_montadas(app):
        if write_spec._url_concreta(f["path"]) in urls:
            salida.add(f["path"])
    return salida


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

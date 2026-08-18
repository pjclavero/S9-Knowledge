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
MINIMO_CASOS = 24
MINIMO_ABLACIONES = 3

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
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
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
def endpoints_de_escritura(base: Path) -> list[dict]:
    """Se leen de la propia especificación ejecutada sobre el árbol limpio.

    No hay lista de endpoints en este arnés: si mañana aparece uno nuevo, este
    control negativo lo muta también, sin que nadie lo escriba aquí.
    """
    r = ejecutar(base)
    salida = base / "write_spec_out.json"
    informe = json.loads(salida.read_text(encoding="utf-8"))
    if r["rc"] != 0:
        raise AssertionError(f"el árbol limpio no sale verde: {r['hallazgos']}")
    return informe["endpoints_de_escritura"]


def fichero_de(raiz: Path, clave: str) -> tuple[Path, str]:
    modulo, _, funcion = clave.rpartition(".")
    return raiz / "viewer" / (modulo.replace(".", "/") + ".py"), funcion


def _agujas(path: str, clave: str) -> set[str]:
    """Formas en que un hallazgo puede NOMBRAR al endpoint mutado."""
    return {path, re.sub(r"\{[^}]+\}", "1", path), clave}


def hallazgos_nombran(hallazgos: dict, path: str, clave: str) -> tuple[bool, list]:
    """¿TODOS los hallazgos nombran al endpoint mutado? (no hay rojo prestado)."""
    ajenos = []
    for nombre, entradas in hallazgos.items():
        for e in entradas:
            texto = json.dumps(e, ensure_ascii=False)
            if not any(a in texto for a in _agujas(path, clave)):
                ajenos.append({"hallazgo": nombre, "entrada": e})
    return not ajenos, ajenos


def caso(nombre: str, mutar, path: str, clave: str, esperados: list[str],
         corroboran: list[str] | None = None, obligatorio: bool = True) -> dict:
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
                  if not any(any(a in json.dumps(x, ensure_ascii=False) for a in agujas)
                             for x in h.get(e, []))]
        unico, ajenos = hallazgos_nombran(h, path, clave)
        corroborado = [e for e in (corroboran or [])
                       if any(any(a in json.dumps(x, ensure_ascii=False) for a in agujas)
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
ABLACIONES = [
    # (id, familia del caso que debe volver VERDE, sustituciones en write_spec.py)
    ("AB-C1C2", "ALI", [
        ('        seguros = sorted(set(f["metodos"]) & METODOS_SEGUROS)',
         '        seguros = []'),
        ('        if atendido in claves_de_escritura:',
         '        if False:'),
        ('        if not (set(f["metodos"]) & METODOS_DE_ESCRITURA):',
         '        if False:'),
    ]),
    ("AB-C3", "PUT", [
        ('        if sonda.get("estado") in (404, 405, -1, None):',
         '        if False:'),
    ]),
    ("AB-F1", "ALI", [
        ('            if n in DECLARADORES_DE_CUERPO:', '            if False:'),
        ('        if RE_CSRF_VERIFICA.search(nombre):', '        if False:'),
        ('        if RE_MUTADOR.match(nombre):', '        if False:'),
        ('        anota("espec-vacia", {"motivo": "cero endpoints de escritura clasificados"})',
         '        pass'),
        ('        anota("espec-vacia", {"motivo": "cero contratos de cliente de escritura"})',
         '        pass'),
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
        casos.append({"caso": "W0", "rc": r0["rc"], "hallazgos": sorted(r0["hallazgos"]),
                      "estado": "OK" if r0["rc"] == 0 else "FALLO",
                      "stderr": "" if r0["rc"] == 0 else r0["stderr"]})
        escrituras = endpoints_de_escritura(base)

    # --- un caso por endpoint de escritura, nombre a nombre -----------------
    con_contrato = _paths_con_contrato_de_cliente()
    if args.solo:
        escrituras = [e for e in escrituras if args.solo in e["endpoint"]]
    for e in escrituras:
        clave, path = e["endpoint"], e["path"]
        corto = clave.rsplit(".", 1)[-1]

        casos.append(caso(f"MET-{corto}",
                          lambda raiz, c=clave: mutar_metodo(*fichero_de(raiz, c), "get"),
                          path, clave,
                          ["metodo-seguro-en-endpoint-de-escritura"],
                          corroboran=["escritura-servida-por-get",
                                      "contrato-de-cliente-roto"]))
        casos.append(caso(f"ALI-{corto}",
                          lambda raiz, c=clave: anadir_alias_get(*fichero_de(raiz, c)),
                          path, clave,
                          ["metodo-seguro-en-endpoint-de-escritura"],
                          corroboran=["escritura-servida-por-get"]))
        if path in con_contrato:
            # El cambio de método que sigue siendo INSEGURO (`POST -> PUT`) sólo
            # lo puede ver el contrato de cliente, y no siempre: si otra ruta
            # captura la URL del formulario, la petición no da 405 y no hay
            # nada que ver. Esos casos se registran como NO-DETECTADO, no se
            # esconden ni se convierten en fallo del arnés.
            casos.append(caso(f"PUT-{corto}",
                              lambda raiz, c=clave: mutar_metodo(*fichero_de(raiz, c), "put"),
                              path, clave, ["contrato-de-cliente-roto"],
                              obligatorio=False))

    # --- ablaciones ---------------------------------------------------------
    ablaciones = []
    familias = {"MET": lambda raiz, c: mutar_metodo(*fichero_de(raiz, c), "get"),
                "PUT": lambda raiz, c: mutar_metodo(*fichero_de(raiz, c), "put"),
                "ALI": lambda raiz, c: anadir_alias_get(*fichero_de(raiz, c))}
    referencia = {f: next((c for c in casos if c["caso"].startswith(f + "-")), None)
                  for f in familias}
    for aid, familia, subs in ABLACIONES:
        ref = referencia.get(familia)
        if ref is None:
            ablaciones.append({"ablacion": aid, "estado": "SIN-CASO"})
            continue
        clave = ref["endpoint"]
        with tempfile.TemporaryDirectory(prefix="s9k-abl-") as td:
            raiz = copia(Path(td))
            ws = raiz / "scripts" / "route_map" / "write_spec.py"
            for viejo, nuevo in subs:
                sustituir(ws, viejo, nuevo)
            familias[familia](raiz, clave)
            r = ejecutar(raiz)
            cobrada = r["rc"] == 0
            ablaciones.append({"ablacion": aid, "caso": ref["caso"],
                               "rc_ablado": r["rc"],
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

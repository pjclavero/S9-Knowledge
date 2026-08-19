#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detector del inventario del carril 5: ¿cuántas comprobaciones miden REDACCIÓN?

Por qué existe este fichero
---------------------------
La entrega anterior del carril decía «quien quiera reproducirlo tiene aquí el
detector y el ref exactos» y a continuación sólo había PROSA describiéndolo. Una
descripción no es un detector: no se puede ejecutar, no se puede discrepar de
ella con un número. Esto es el detector, ejecutable.

Qué cuenta
----------
Una «comprobación por subcadena» es una aserción de test que liga el resultado a
la REDACCIÓN de un mensaje de error, no a su conducta. Dos detectores, porque
las cifras que circularon medían cosas distintas y conviene poder reproducir
ambas:

  ESTRICTO
    a) `pytest.raises(..., match=...)`
    b) `"literal" in str(...)`

  AMPLIO = ESTRICTO más
    c) `pytest.warns(..., match=...)`
    d) `"literal" in <algo>` donde `<algo>` menciona msg / message / err / error /
       detail / stdout / stderr / output / text / body / out (el mismo patrón,
       escrito sin pasar por `str()`)

Ambos se calculan por AST sobre el árbol de sintaxis real, nunca por `grep`: un
`match=` dentro de un comentario o de una cadena no cuenta, y uno partido en
varias líneas sí.

Uso
---
    # árbol de trabajo actual, ámbito data-engine
    python3 data-engine/tools/carril5_inventario.py

    # tal y como estaba en la base del carril, ámbito repo completo
    python3 data-engine/tools/carril5_inventario.py --ref aaf9695 --scope repo

    # detalle fichero a fichero, o listado de cada sitio
    python3 data-engine/tools/carril5_inventario.py --por-fichero
    python3 data-engine/tools/carril5_inventario.py --sitios

`--ref` NO toca el árbol de trabajo: lee los blobs con `git show <ref>:<ruta>` y
los analiza en memoria.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Ámbitos de medida. Los nombres son los que aparecen en `carril5_deuda.py`.
SCOPES = {
    "data-engine": ["data-engine/app/tests"],
    "repo": ["data-engine/app/tests", "data-engine/tests", "viewer/tests",
             "deploy/tests", "scripts", "tools", "tests"],
}

#: Identificadores cuyo contenido es «un mensaje», para el detector AMPLIO.
_MESSAGE_ISH = ("msg", "message", "err", "error", "detail", "stdout", "stderr",
                "output", "text", "body", "out")


def _es_llamada_raises(node: ast.Call) -> bool:
    return ast.unparse(node.func).endswith("raises")


def _es_llamada_warns(node: ast.Call) -> bool:
    return ast.unparse(node.func).endswith("warns")


def _tiene_match(node: ast.Call) -> bool:
    return any(kw.arg == "match" for kw in node.keywords)


def _in_de_literal(node: ast.Compare):
    """Si `node` es `"literal" in <algo>`, devuelve el texto de `<algo>`."""
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.In):
        return None
    if not (isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)):
        return None
    return ast.unparse(node.comparators[0])


def _menciona_mensaje(expr: str) -> bool:
    bajo = expr.lower()
    return any(t in bajo for t in _MESSAGE_ISH)


def analizar(source: str, path: str) -> dict:
    """Censo de un fichero. Devuelve los sitios de cada familia, con su línea."""
    tree = ast.parse(source, path)
    estricto_match, estricto_in = [], []
    amplio_match, amplio_in = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _tiene_match(n):
            if _es_llamada_raises(n):
                estricto_match.append(n.lineno)
                amplio_match.append(n.lineno)
            elif _es_llamada_warns(n):
                amplio_match.append(n.lineno)
        elif isinstance(n, ast.Compare):
            expr = _in_de_literal(n)
            if expr is None:
                continue
            if expr.startswith("str(") or ".__str__" in expr:
                estricto_in.append(n.lineno)
                amplio_in.append(n.lineno)
            elif _menciona_mensaje(expr):
                amplio_in.append(n.lineno)
    return {
        "estricto_match": sorted(estricto_match),
        "estricto_in_str": sorted(estricto_in),
        "amplio_match": sorted(amplio_match),
        "amplio_in": sorted(amplio_in),
    }


def _ficheros(scope: str, ref: str | None) -> list[str]:
    raices = SCOPES[scope]
    if ref:
        salida = subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r",
                                 "--name-only", ref], capture_output=True,
                                text=True, check=True).stdout.splitlines()
    else:
        # `--others` incluye los ficheros aun no versionados: si no, un test
        # recien anadido quedaria fuera del censo sin que nadie se enterase.
        salida = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached",
                                 "--others", "--exclude-standard"],
                                capture_output=True, text=True, check=True).stdout.splitlines()
    return sorted(p for p in salida
                  if p.endswith(".py")
                  and any(p == r or p.startswith(r + "/") for r in raices))


def _leer(rel: str, ref: str | None) -> str | None:
    if ref:
        r = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{rel}"],
                           capture_output=True, check=False)
        return None if r.returncode else r.stdout.decode("utf-8", "replace")
    p = REPO / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def censar(scope: str = "data-engine", ref: str | None = None) -> dict:
    """Censo completo (ejecución sobre TODOS los ficheros del ámbito, no muestra)."""
    por_fichero, ilegibles = {}, []
    for rel in _ficheros(scope, ref):
        src = _leer(rel, ref)
        if src is None:
            continue
        try:
            por_fichero[rel] = analizar(src, rel)
        except SyntaxError:
            ilegibles.append(rel)

    # FAIL-CLOSED. Un censo sobre cero ficheros no es "cero hallazgos": es un
    # censo que no ha mirado nada, y devolverlo como 0 convierte cualquier
    # comprobacion que lo use en un verde vacio. Pasa de verdad --al ejecutar
    # desde una copia del arbol, `git ls-files` no lista nada-- y ahi se
    # detecto.
    if not por_fichero:
        raise RuntimeError(
            f"censo vacio: ningun fichero .py bajo {SCOPES[scope]} (ref={ref or 'arbol'}). "
            "Un censo que no encuentra su objetivo tiene que gritar, no devolver 0.")

    def _tot(clave):
        return sum(len(v[clave]) for v in por_fichero.values())

    em, ei = _tot("estricto_match"), _tot("estricto_in_str")
    am, ai = _tot("amplio_match"), _tot("amplio_in")
    return {
        "ambito": scope,
        "ref": ref or "arbol-de-trabajo",
        "ficheros_analizados": len(por_fichero),
        "ficheros_con_hallazgos": sum(
            1 for v in por_fichero.values() if any(v[k] for k in v)),
        "ficheros_ilegibles": ilegibles,
        "estricto": {"match": em, "in_str": ei, "total": em + ei},
        "amplio": {"match": am, "in": ai, "total": am + ai},
        "por_fichero": por_fichero,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=sorted(SCOPES), default="data-engine")
    ap.add_argument("--ref", default=None,
                    help="ref de git a medir (por defecto, el árbol de trabajo)")
    ap.add_argument("--por-fichero", action="store_true")
    ap.add_argument("--sitios", action="store_true",
                    help="lista fichero:linea de cada sitio detectado")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = censar(args.scope, args.ref)
    if args.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0

    print(f"ambito={r['ambito']}  ref={r['ref']}  "
          f"ficheros={r['ficheros_analizados']} "
          f"(con hallazgos: {r['ficheros_con_hallazgos']})")
    print(f"  ESTRICTO {r['estricto']['total']:>4}  "
          f"= match {r['estricto']['match']} + in str(...) {r['estricto']['in_str']}")
    print(f"  AMPLIO   {r['amplio']['total']:>4}  "
          f"= match {r['amplio']['match']} + in <mensaje> {r['amplio']['in']}")
    if r["ficheros_ilegibles"]:
        print(f"  NO PARSEABLES: {r['ficheros_ilegibles']}", file=sys.stderr)
    if args.por_fichero or args.sitios:
        for rel, v in sorted(r["por_fichero"].items()):
            n = sum(len(x) for x in v.values())
            if not n:
                continue
            print(f"  {rel}: estricto={len(v['estricto_match'])}+{len(v['estricto_in_str'])} "
                  f"amplio={len(v['amplio_match'])}+{len(v['amplio_in'])}")
            if args.sitios:
                for clave in ("amplio_match", "amplio_in"):
                    for ln in v[clave]:
                        print(f"      {rel}:{ln}  [{clave}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

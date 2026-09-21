#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INVENTARIO DE LOS CONSUMIDORES DEL SIGNO (`negated`), POR AST.

QUÉ PROBLEMA RESUELVE
---------------------
El encargo lo dice mejor que yo: «no quiero cerrar tres pantallas y que el
signo siga perdiéndose en un cuarto sitio que nadie miró». Un repaso a ojo no
vale para eso, y un `grep negated` tampoco: `grep` encuentra los sitios que SÍ
lo nombran, y el defecto está exactamente en los que NO.

Así que esto busca lo contrario. Enumera los sitios donde una AFIRMACIÓN se
proyecta —un diccionario literal con la forma de una aserción, o un `RETURN` de
Cypher sobre `V3Assertion`— y señala los que NO llevan el signo. Una proyección
sin `negated` no es necesariamente un defecto: puede que ese consumidor no
tenga que enseñarlo. Lo que no puede es pasar sin que nadie lo haya mirado.

CONTROL POSITIVO — Y ESTE ARNÉS MIDE UNA AUSENCIA
-------------------------------------------------
Todo arnés que cuente ausencias lleva dentro de su propia tabla un caso de
resultado CONOCIDO. Si la red no encuentra los portadores que sabemos que
existen (`ledger/projection.py`, `contracts/assertion.py`, `IDENTITY_FIELDS`),
está CIEGA y sus ceros no valen nada. En ese caso el programa sale con 2 y lo
dice, en vez de imprimir un inventario tranquilizador.

EL TECHO DE ESTA RED — QUÉ NO VE
--------------------------------
Se declara porque una red sin techo declarado se lee como completa:

  1. sólo ve diccionarios LITERALES. Una proyección construida con `dict(...)`,
     `{**a, **b}`, una comprensión o `setattr` no aparece;
  2. sólo ve Cypher en cadenas literales del mismo módulo. Una consulta
     ensamblada en tiempo de ejecución desde trozos se ve a medias;
  3. no sigue alias: si un módulo importa la proyección de otro y la extiende,
     esto lo cuenta una vez, donde está escrita;
  4. NO mira plantillas Jinja ni JavaScript. La cobertura de las plantillas la
     dan los testigos que piden el HTML
     (`viewer/tests/test_panel_signo_de_negacion.py`), no esta red;
  5. no dice si el signo se USA bien, sólo si VIAJA. Que una proyección lleve
     `negated` no significa que su pantalla lo pinte.

USO
---
    python3 scripts/inventario_signo_negacion.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Árboles que se recorren. Los tests quedan fuera a propósito: un doble que
#: pierda el signo no es un defecto del producto.
RAICES = (
    REPO / "viewer" / "app",
    REPO / "data-engine" / "app" / "knowledge_v3",
    REPO / "data-engine" / "app" / "relations",
)

EXCLUIR = ("/tests/", "/benchmarks/", "/eval/", "/_authoring/")

#: Una proyección «tiene forma de aserción» si nombra al menos tres de éstos.
#: Tres y no uno: con uno entraban diccionarios de configuración que hablan de
#: predicados y no son aserciones, y el inventario se llenaba de ruido.
MARCADORES = {
    "assertion_id", "subject_entity_id", "object_entity_id", "predicate",
    "subject", "object", "direction",
}
MINIMO_MARCADORES = 3

#: Las formas en que una proyección puede LLEVAR el signo. `negated` es el
#: booleano del contrato; `signo` es el CÓDIGO que el visor publica en su
#: lugar (`app.labels.negation_code`), porque hacia la pantalla no viaja un
#: booleano crudo sino un código traducible de tres estados.
SIGNO = "negated"
PORTADORES = frozenset({SIGNO, "signo"})

#: CONTROL POSITIVO. Portadores del signo que SABEMOS que existen. Si la red no
#: los ve, no está midiendo.
CONTROL_POSITIVO = (
    "data-engine/app/knowledge_v3/ledger/projection.py",
    "data-engine/app/knowledge_v3/contracts/assertion.py",
)


class Proyecciones(ast.NodeVisitor):
    """Diccionarios literales con forma de aserción, y sus claves."""

    def __init__(self, ruta: str):
        self.ruta = ruta
        self.hallazgos: list[dict] = []

    def visit_Dict(self, node: ast.Dict) -> None:
        claves = {
            k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        if len(claves & MARCADORES) >= MINIMO_MARCADORES:
            self.hallazgos.append({
                "tipo": "dict", "ruta": self.ruta, "linea": node.lineno,
                "lleva_signo": bool(claves & PORTADORES),
            })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Una aserción también se proyecta como CLASE con campos anotados.

        Se añadió después de que el control positivo lo cazara: la red sólo
        miraba diccionarios y `contracts/assertion.py` —un portador conocido—
        salía como no visto. Ese es justamente el trabajo del control positivo,
        y la red sin este visitante estaba ciega para toda una familia.
        """
        campos = {
            s.target.id for s in node.body
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
        }
        if len(campos & MARCADORES) >= MINIMO_MARCADORES:
            self.hallazgos.append({
                "tipo": "clase", "ruta": self.ruta, "linea": node.lineno,
                "lleva_signo": bool(campos & PORTADORES),
            })
        self.generic_visit(node)


def _cypher_sobre_aserciones(arbol: ast.AST, ruta: str) -> list[dict]:
    """Cadenas literales que son un `RETURN` sobre `V3Assertion`.

    `RETURN a` (el nodo entero) SÍ lleva el signo: Neo4j devuelve todas las
    propiedades y quien proyecta es el llamador. Un `RETURN a.x AS x, ...` sólo
    lleva lo que enumera, y ése es el que hay que mirar.
    """
    salida = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
            continue
        texto = nodo.value
        if "RETURN" not in texto.upper():
            continue
        if "V3Assertion" not in texto and "LABEL_ASSERTION" not in texto:
            continue
        cuerpo = texto.upper().split("RETURN", 1)[1]
        entero = any(
            f" {v}" == cuerpo[:2] or cuerpo.strip().startswith(v)
            for v in ("A ", "A\n", "A")
        ) and "." not in cuerpo.split()[0] if cuerpo.split() else False
        salida.append({
            "tipo": "cypher", "ruta": ruta, "linea": nodo.lineno,
            "lleva_signo": (SIGNO in texto) or entero,
            "nodo_entero": entero,
        })
    return salida


def recorrer() -> list[dict]:
    hallazgos: list[dict] = []
    for raiz in RAICES:
        for fichero in sorted(raiz.rglob("*.py")):
            ruta = str(fichero.relative_to(REPO))
            if any(x in f"/{ruta}" for x in EXCLUIR):
                continue
            try:
                arbol = ast.parse(fichero.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - fichero no parseable
                print(f"AVISO: no se pudo parsear {ruta}", file=sys.stderr)
                continue
            visitante = Proyecciones(ruta)
            visitante.visit(arbol)
            hallazgos.extend(visitante.hallazgos)
            hallazgos.extend(_cypher_sobre_aserciones(arbol, ruta))
    return hallazgos


def main() -> int:
    hallazgos = recorrer()
    portadores = {h["ruta"] for h in hallazgos if h["lleva_signo"]}

    # --- CONTROL POSITIVO, antes de creerse ningún cero -------------------
    ciegos = [c for c in CONTROL_POSITIVO if c not in portadores]
    print("=" * 74)
    print("CONTROL POSITIVO (portadores conocidos del signo)")
    print("=" * 74)
    for c in CONTROL_POSITIVO:
        print(f"  {'VISTO  ' if c not in ciegos else 'NO VISTO'}  {c}")
    if ciegos:
        print()
        print("ARNÉS CIEGO: no se han encontrado portadores que existen. Los "
              "ceros de este inventario NO valen.")
        return 2

    sin_signo = [h for h in hallazgos if not h["lleva_signo"]]
    con_signo = [h for h in hallazgos if h["lleva_signo"]]

    print()
    print("=" * 74)
    print(f"PROYECCIONES DE AFIRMACIÓN ENCONTRADAS: {len(hallazgos)}")
    print(f"  con el signo: {len(con_signo)}")
    print(f"  SIN el signo: {len(sin_signo)}")
    print("=" * 74)
    for h in sorted(sin_signo, key=lambda x: (x["ruta"], x["linea"])):
        print(f"  SIN SIGNO  {h['tipo']:7s}  {h['ruta']}:{h['linea']}")
    print()
    print("Techo declarado: sólo diccionarios y Cypher LITERALES; no ve "
          "plantillas Jinja, JavaScript, ni proyecciones construidas "
          "dinámicamente. Ver la cabecera de este fichero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

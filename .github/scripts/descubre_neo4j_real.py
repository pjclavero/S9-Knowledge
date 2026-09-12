#!/usr/bin/env python3
"""Descubre los tests que exigen un Neo4j REAL, por PROPIEDAD y no por lista.

POR QUE EXISTE
--------------
El paso de CI que ejercia el writer contra una base de verdad nombraba DOS
ficheros (`writer` y `e2e`). Los otros doce con el mismo gate seguian
saliendo `skipped` en el paso general —que corre sin la variable— y el job
salia VERDE. El propio comentario del workflow diagnosticaba ese modo de
fallo («llevaba ROJA desde T2 sin que nadie lo viera») y lo arreglaba para
dos ficheros dejando el resto igual.

Anadir doce nombres mas reinstaura exactamente la regla que acaba de fallar:
una lista que hay que acordarse de rellenar. Aqui se descubre el CONJUNTO.

QUE SE USA COMO DISCRIMINADOR, Y POR QUE NO EL NOMBRE NI UN MARKER
------------------------------------------------------------------
1. Un MARKER (`@pytest.mark.neo4j_real`) seria lo preferible, pero NO EXISTE:
   `pytest.ini` registra un unico marker (`critico`) y `tests/conftest.py`
   otros cuatro (`e2e`, `integration`, `contract`, `prod_block`). Ninguno
   significa «necesita Neo4j». Ademas `pytest.ini` no lleva
   `--strict-markers`, asi que un marker mal escrito no daria error: seria
   un discriminador que puede fallar EN SILENCIO. Descartado por medicion,
   no por preferencia.

2. La CONVENCION DE NOMBRES `*_neo4j_real*.py` TIENE EXCEPCIONES MEDIDAS:
   `test_knowledge_v3_equipo11a_apply_completo.py` lleva el mismo gate
   (`skipif` sobre `S9K_WRITER_NEO4J_REAL`) y NO casa con el patron. Al
   reves tambien falla: `test_knowledge_v3_equipo5b_propiedad_rollback_neo4j_real.py`
   SI casa con el nombre pero se gatea con OTRA familia de variables
   (`S9K_5B_NEO4J_URI`), asi que activar `S9K_WRITER_NEO4J_REAL` no lo
   despierta. El nombre da un falso positivo y un falso negativo.

3. Lo que SI es fiable es el EFECTO: el modulo lee la variable de entorno que
   decide si se omite. Eso es lo que pytest obedece de verdad.

Y se lee por AST, no con `grep`: un `grep` cuenta apariciones de texto y casa
igual dentro de un comentario o de un docstring —este fichero mismo nombra la
variable muchas veces sin ser un test—. El AST no ve comentarios, y los
docstrings se descartan explicitamente, asi que lo que queda es la variable
USADA como dato.

USO
---
    python3 .github/scripts/descubre_neo4j_real.py            # rutas, una por linea
    python3 .github/scripts/descubre_neo4j_real.py --informe  # + discrepancias
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# La variable que despierta a la clase obligatoria. Es la que el paso de CI
# exporta, asi que «pertenece a la clase» y «CI lo ejecuta de verdad» son la
# MISMA condicion y no pueden divergir.
VARIABLE = "S9K_WRITER_NEO4J_REAL"

# Raices donde buscar. Un fichero nuevo en cualquiera de ellas entra solo.
RAICES = ("data-engine/app/tests", "viewer/tests", "tests")

# Convencion historica, que aqui NO decide nada: solo se contrasta con el
# descubrimiento real para poder DECLARAR las discrepancias en vez de que se
# queden calladas.
PATRON_NOMBRE = "_neo4j_real"


def _docstrings(arbol: ast.Module) -> set[int]:
    """Ids de los nodos `Constant` que son docstring (no son uso de la variable)."""
    fuera = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            cuerpo = getattr(nodo, "body", None)
            if (cuerpo and isinstance(cuerpo[0], ast.Expr)
                    and isinstance(cuerpo[0].value, ast.Constant)
                    and isinstance(cuerpo[0].value.value, str)):
                fuera.add(id(cuerpo[0].value))
    return fuera


def _es_lectura_de_entorno(nodo: ast.AST) -> bool:
    """True si el nodo LEE `VARIABLE` del entorno del proceso.

    Se exige la lectura y no la mera aparicion del nombre. La diferencia esta
    MEDIDA, no supuesta: `test_knowledge_v3_e2e_global.py` contiene
    `assert "S9K_WRITER_NEO4J_REAL" in fuente` —comprueba que OTRO modulo
    conserva su guardia— y no se omite jamas; un detector que solo mirase
    constantes de texto lo habria metido en la clase obligatoria y habria
    declarado «requiere Neo4j» un fichero que corre siempre.

    Formas aceptadas: `os.environ.get(V)`, `os.getenv(V)`, `os.environ[V]`.
    """
    # os.environ.get(V) / os.getenv(V)
    if isinstance(nodo, ast.Call):
        f = nodo.func
        if isinstance(f, ast.Attribute) and f.attr in ("get", "getenv"):
            for arg in nodo.args:
                if isinstance(arg, ast.Constant) and arg.value == VARIABLE:
                    return True
    # os.environ[V]
    if isinstance(nodo, ast.Subscript):
        sl = nodo.slice
        if isinstance(sl, ast.Constant) and sl.value == VARIABLE:
            return True
    return False


def usa_variable(ruta: Path) -> bool:
    """True si el modulo LEE la variable del entorno, que es lo que pytest obedece."""
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return False
    return any(_es_lectura_de_entorno(n) for n in ast.walk(arbol))


def descubre() -> list[str]:
    """Rutas relativas, ordenadas y deterministas, de la clase obligatoria."""
    hallados: list[str] = []
    for raiz in RAICES:
        base = REPO / raiz
        if not base.exists():
            continue
        for py in sorted(base.rglob("test_*.py")):
            if "__pycache__" in py.parts:
                continue
            if usa_variable(py):
                hallados.append(py.relative_to(REPO).as_posix())
    return sorted(dict.fromkeys(hallados))


def discrepancias(encontrados: list[str]) -> tuple[list[str], list[str]]:
    """(gate sin el nombre, nombre sin el gate). Las dos direcciones importan."""
    por_gate = set(encontrados)
    por_nombre = set()
    for raiz in RAICES:
        base = REPO / raiz
        if not base.exists():
            continue
        for py in sorted(base.rglob("test_*.py")):
            if "__pycache__" not in py.parts and PATRON_NOMBRE in py.name:
                por_nombre.add(py.relative_to(REPO).as_posix())
    return sorted(por_gate - por_nombre), sorted(por_nombre - por_gate)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--informe", action="store_true",
                    help="anade a stderr el recuento y las discrepancias con el nombre")
    args = ap.parse_args()

    encontrados = descubre()
    if not encontrados:
        # Descubrir CERO ficheros no es un conjunto vacio legitimo: significa
        # que el descubridor se ha quedado ciego (raiz renombrada, variable
        # cambiada). Un conjunto vacio devuelto en verde seria el mismo falso
        # verde que este fichero existe para cerrar.
        print(f"::error::el descubridor no encontro NINGUN test con {VARIABLE}: "
              f"raices {RAICES} vacias o la variable ha cambiado de nombre",
              file=sys.stderr)
        return 1

    for ruta in encontrados:
        print(ruta)

    if args.informe:
        solo_gate, solo_nombre = discrepancias(encontrados)
        print(f"[descubre] {len(encontrados)} ficheros con {VARIABLE}", file=sys.stderr)
        for r in solo_gate:
            print(f"[descubre] gate SIN el nombre (lo perderia una lista por patron): {r}",
                  file=sys.stderr)
        for r in solo_nombre:
            print(f"[descubre] nombre SIN el gate (otra familia de variables; "
                  f"activar {VARIABLE} NO lo despierta): {r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

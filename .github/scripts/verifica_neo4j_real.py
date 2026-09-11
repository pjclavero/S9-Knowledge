#!/usr/bin/env python3
"""Juzga la ejecucion de la clase Neo4j-real a partir del informe JUnit.

POR QUE NO BASTA EL `grep`
--------------------------
El paso anterior decidia con `grep -qi skipped` sobre el log. Eso es CONTAR
TEXTO: casa con la palabra dentro de un nombre de test, dentro de un warning o
dentro de un `-v` que imprime `SKIPPED` por linea, y NO distingue «un test
omitido» de «la palabra aparece». Aqui se PARSEA la estructura que pytest
emite para ser leida (`--junitxml`), que es el mismo efecto observable que el
resto de gates de este repositorio usan.

LAS CUATRO CONDICIONES, y ninguna puede quedar verde por silencio:
  coleccionados > 0   -> si no, el descubridor o el filtro se quedaron ciegos
  skipped == 0        -> `19 skipped, rc=0` es EXACTAMENTE el falso verde que
                         este gate existe para cerrar
  failures == 0
  errors == 0

Uso:  python3 .github/scripts/verifica_neo4j_real.py <informe.xml> [--minimo N]
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def suites(raiz: ET.Element):
    """`testsuites` envuelve a `testsuite`; pytest puede emitir cualquiera."""
    if raiz.tag == "testsuite":
        return [raiz]
    return list(raiz.iter("testsuite"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("informe")
    ap.add_argument("--minimo", type=int, default=1,
                    help="suelo de tests ejecutados (no solo >0)")
    args = ap.parse_args()

    ruta = Path(args.informe)
    if not ruta.exists():
        # Un informe ausente es el fallo mas silencioso de todos: pytest no
        # llego a arrancar y el paso podria seguir adelante.
        print(f"::error::no existe el informe JUnit {ruta}: pytest no llego a "
              f"escribirlo, asi que NO hay ninguna prueba de que se ejecutara nada")
        return 1
    try:
        raiz = ET.parse(ruta).getroot()
    except ET.ParseError as exc:
        print(f"::error::informe JUnit ilegible ({exc})")
        return 1

    total = fallos = errores = omitidos = 0
    for s in suites(raiz):
        total += int(s.get("tests", 0))
        fallos += int(s.get("failures", 0))
        errores += int(s.get("errors", 0))
        omitidos += int(s.get("skipped", 0))

    ejecutados = total - omitidos
    print(f"[neo4j-real] coleccionados={total} ejecutados={ejecutados} "
          f"omitidos={omitidos} fallos={fallos} errores={errores}")

    problemas = []
    if total < args.minimo:
        problemas.append(
            f"solo se coleccionaron {total} tests (minimo {args.minimo}): el "
            f"descubridor o el filtro se han quedado CIEGOS")
    if omitidos:
        # Se nombran uno a uno: «hay skips» no basta para arreglarlos.
        problemas.append(f"{omitidos} test(s) OMITIDOS con Neo4j disponible")
        for s in suites(raiz):
            for caso in s.iter("testcase"):
                for sk in caso.findall("skipped"):
                    problemas.append(
                        f"    OMITIDO {caso.get('classname')}::{caso.get('name')} "
                        f"-> {sk.get('message', '(sin motivo)')}")
    if fallos or errores:
        problemas.append(f"{fallos} fallo(s) y {errores} error(es) contra Neo4j real")
        for s in suites(raiz):
            for caso in s.iter("testcase"):
                for mal in list(caso.findall("failure")) + list(caso.findall("error")):
                    problemas.append(
                        f"    ROJO {caso.get('classname')}::{caso.get('name')} "
                        f"-> {(mal.get('message') or '')[:200]}")

    if problemas:
        for p in problemas:
            if p.startswith("    "):
                print(p)
            else:
                print(f"::error::{p}")
        return 1

    print("[neo4j-real] VERDE: conjunto descubierto ejecutado entero, sin omisiones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

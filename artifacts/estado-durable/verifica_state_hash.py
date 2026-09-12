# -*- coding: utf-8 -*-
"""Recalcula el `state_hash` de cada entidad DESDE EL GRAFO y lo compara.

Es la comprobacion de que el hash **describe el estado realmente persistido**
y no es un valor cualquiera que haga pasar la validacion. Un hash que no se
puede rehacer desde el nodo es peor que no tener ninguno: hace pasar una
comprobacion que deberia fallar.

    PYTHONPATH=data-engine/app python3 verifica_state_hash.py \\
        bolt://127.0.0.1:7687 /ruta/privada/neo4j.pass

Sale 0 si TODAS coinciden. La contraseña se lee de un fichero, nunca de argv.
"""
from __future__ import annotations

import pathlib
import sys

import neo4j

from knowledge_v3.writer.state import state_hash_value


def main() -> int:
    uri, pass_file = sys.argv[1], sys.argv[2]
    clave = pathlib.Path(pass_file).read_text().strip()
    driver = neo4j.GraphDatabase.driver(uri, auth=("neo4j", clave))
    try:
        with driver.session() as s:
            filas = list(
                s.run(
                    "MATCH (n:V3Entity) RETURN n.entity_id AS id, "
                    "properties(n) AS p ORDER BY n.entity_id"
                )
            )
    finally:
        driver.close()

    assert filas, "conjunto vacio: no hay V3Entity que verificar"
    coinciden = 0
    for r in filas:
        props = dict(r["p"])
        guardado = props.get("state_hash")
        recomputado = state_hash_value(props)
        ok = guardado == recomputado
        coinciden += ok
        print(
            f"{r['id']:<40} guardado={str(guardado)[:16]}... "
            f"recomputado={recomputado[:16]}... {'COINCIDE' if ok else 'NO COINCIDE'}"
        )
    print(f"total={len(filas)} coinciden={coinciden}")
    return 0 if coinciden == len(filas) else 1


if __name__ == "__main__":
    raise SystemExit(main())

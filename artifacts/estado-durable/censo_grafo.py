# -*- coding: utf-8 -*-
"""Huella del CONTENIDO de un grafo, sin `elementId`.

Sirve para responder "¿el segundo apply movió algo?" sin mirar a ojo. El
`elementId` queda FUERA a proposito: no es identidad durable (se regenera al
restaurar un dump), asi que compararlo daria "distinto" en grafos identicos.
La identidad de producto es `(workspace, entity_id)`.

    python3 censo_grafo.py bolt://127.0.0.1:7687 /ruta/privada/neo4j.pass [salida.json]

La contraseña se lee de un FICHERO, nunca de la linea de comandos.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import neo4j


def censo(driver) -> tuple[dict, str]:
    with driver.session() as s:
        nodos = [
            {"labels": sorted(r["l"]), "props": dict(r["p"])}
            for r in s.run("MATCH (n) RETURN labels(n) AS l, properties(n) AS p")
        ]
        rels = [
            {"type": r["t"], "from": r["a"], "to": r["b"], "props": dict(r["p"])}
            for r in s.run(
                "MATCH (a)-[r]->(b) RETURN type(r) AS t, properties(r) AS p, "
                "coalesce(a.entity_id, a.assertion_id, a.idempotency_key) AS a, "
                "coalesce(b.entity_id, b.assertion_id, b.idempotency_key) AS b"
            )
        ]
        n_nodos = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        n_rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    # Dos MATCH sueltos en la misma consulta dan producto cartesiano y pueden
    # dar 0 filas: se cuentan por separado y se exige conjunto NO VACIO antes
    # de comparar nada.
    assert n_nodos > 0, "censo vacio: no habria nada que comparar"
    clave = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)  # noqa: E731
    doc = {"nodos": sorted(nodos, key=clave), "relaciones": sorted(rels, key=clave)}
    blob = json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str)
    resumen = {
        "n_nodos": n_nodos,
        "n_relaciones": n_rels,
        "huella_sin_elementId": hashlib.sha256(blob.encode()).hexdigest(),
    }
    return resumen, blob


def main() -> int:
    uri, pass_file = sys.argv[1], sys.argv[2]
    clave = pathlib.Path(pass_file).read_text().strip()
    driver = neo4j.GraphDatabase.driver(uri, auth=("neo4j", clave))
    try:
        resumen, blob = censo(driver)
    finally:
        driver.close()
    print(json.dumps(resumen))
    if len(sys.argv) > 3:
        pathlib.Path(sys.argv[3]).write_text(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""DIAGNOSTICO: que `name` queda en Neo4j tras aprobar un alta por la CLI.

La pregunta es concreta y decide una atribucion. En `partida A` el objeto
"Cofradia de Ambar" se resolvio como `CREATE_PROVISIONAL` y el claim se fue a
`REVIEW` con `no_promovible_por: ["object_entity_id"]`, aun existiendo ya
`entity:cofradia-ambar` en capa juego. 6A describio EXACTAMENTE ese modo de
fallo: sin `names_by_mention` el alta se crea con `name = entity_id` y en la
siguiente ingesta el resolutor ya no reconoce el nombre.

Si el `name` almacenado es "Cofradia de Ambar", el defecto NO es ese y la
causa esta en otra parte. Si es "entity:cofradia-ambar", el defecto sobrevive
por la ruta de la CLI (dos procesos, `--revisar` aparte) aunque `reconcile` ya
exija el argumento.
"""
from __future__ import annotations

import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
for p in (str(APP_DIR), str(APP_DIR / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import escenario_tanda6 as E  # noqa: E402
from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402


def main():
    tmp = pathlib.Path("/tmp/diag-nombres")
    tmp.mkdir(parents=True, exist_ok=True)
    with neo4j_efimero_conexion("s9k-diag-nombres") as cx:
        driver = cx.driver
        op = E.Operador(cx, tmp)
        f = E.fuente(tmp, "lore.md",
                     "# Lore\n\nSela Marrec es miembro de la Cofradia de Ambar.\n")
        rc, inf = E.corrida(op, f, tmp / "lore", operador="diag",
                            tipos_alta={"entity:sela-marrec": "Character",
                                        "entity:cofradia-ambar": "Faction"})
        print(f"lore rc={rc}")
        filas = E.filas(driver,
                        "MATCH (e:V3Entity {workspace:$ws}) "
                        "RETURN e.entity_id AS id, e.name AS name, "
                        "e.entity_type AS t, e.partida_id AS p ORDER BY id", ws=E.WS)
        print("\n== LO QUE QUEDO EN NEO4J ==")
        for r in filas:
            coincide = (r["name"] != r["id"])
            print(f"  entity_id={r['id']!r}")
            print(f"    name={r['name']!r}  tipo={r['t']!r}  partida={r['p']!r}"
                  f"   -> nombre util? {'SI' if coincide else 'NO (name == entity_id)'}")
        malos = [r for r in filas if r["name"] == r["id"]]
        print(f"\n  entidades con name == entity_id: {len(malos)} de {len(filas)}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

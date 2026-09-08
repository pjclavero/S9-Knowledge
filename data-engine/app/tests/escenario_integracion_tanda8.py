# -*- coding: utf-8 -*-
"""INTEGRACION tanda 8 -- la CLASIFICACION se apoya en la propiedad DURABLE.

QUE SE DEMUESTRA, Y POR QUE HACIA FALTA
---------------------------------------
8B dejo esto declarado y NO colado, correctamente:

    «La clasificacion SIGUE CONSUMIENDO `apply_id`. Persisto la propiedad
     durable en los tres sitios y la dejo disponible en el documento
     recargado, pero NO cambie el predicado de `ownership_clause`. Migrarlo
     es operacion propia con su propia medida.»

Esta es esa medida. `apply_id` es identidad de INTENTO: deriva de `plan_hash`,
que cubre `created_at`/`expires_at`, o sea el RELOJ. El mismo apply LOGICO
replanificado tras un restore trae otro `apply_id`, y una clasificacion que se
apoye en el deja de reconocer lo que ella misma creo.

EL CASO QUE LO JUSTIFICA, MEDIDO CONTRA DOS BASES REALES
--------------------------------------------------------
Se aplica el MISMO apply logico en dos bases efimeras distintas, con dos
instantes distintos --que es exactamente lo que cambia al replanificar tras un
restore-- y sobre la SEGUNDA base se pregunta por el conjunto PX:

    con la marca DURABLE  (`ownership_id` de la base 1) -> encuentra su PX
    con la marca de INTENTO (`apply_id` de la base 1)   -> NO encuentra NADA

El segundo caso es el control positivo: es lo que la clasificacion hacia antes
de esta migracion, y sale vacio. Sin el, «la durable encuentra el PX» podria
significar simplemente que la consulta encuentra todo.

DISCIPLINA DE MEDIDA
  * Los `elementId` de las dos bases se comprueban DISJUNTOS antes de
    comparar nada. `elementId` no es identidad durable y aqui no se usa como
    tal: solo sirve para probar que las bases son de verdad distintas.
  * UNA consulta por cosa contada; todo censo se afirma NO VACIO antes de
    compararlo. Dos `MATCH` sueltos dan producto cartesiano y, con un lado
    vacio, CERO filas: un verde que no mide nada.
  * Se compara por identidad LOGICA (`fragment_id`), nunca por posicion.
  * Ni un solo `CREATE`/`MERGE`/`SET` propio: todo lo escribe el producto por
    la ruta de operador (`ingest_cli` en subprocess).
"""
from __future__ import annotations

import os
import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
for p in (str(APP_DIR), str(APP_DIR / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402,F401

import escenario_equipo8b as e8b  # noqa: E402
from escenario_equipo8b import (  # noqa: E402,I100
    OP_A,
    OP_B,
    T_A,
    T_B,
    TEXTO_1,
    WS,
    Operador,
    censo_basico,
    check,
    corrida,
    element_ids,
    filas,
    fuente,
    marcas_operaciones,
    marcas_procedencia,
)

from knowledge_v3.writer.provenance import LABEL_EVIDENCE  # noqa: E402
from knowledge_v3.writer.rollback_provenance import owned_by_apply_query  # noqa: E402


def px_por_marca(driver, marca):
    """El conjunto PX que la clasificacion del producto ve con esa marca.

    Se usa la consulta REAL del camino de reversion, no una reescrita aqui:
    lo que se mide tiene que ser lo que el producto ejecuta.
    """
    q = owned_by_apply_query(WS, marca, None, LABEL_EVIDENCE)
    return {r["id"] for r in filas(driver, q.cypher, **q.params) if r.get("id")}


def main():
    tmp = pathlib.Path(os.environ.get("ESCENARIO_TMP", "/tmp/escenario-tanda8"))
    tmp.mkdir(parents=True, exist_ok=True)

    print("\n===== BASE 1 (el apply logico X, instante T_A) =====")
    with neo4j_efimero_conexion("s9k-t8-base1") as cx1:
        drv1 = cx1.driver
        op1 = Operador(cx1, tmp)
        check("1: el grafo arranca VACIO", censo_basico(drv1)["nodos"] == 0)

        f1 = fuente(tmp, "fuente-1.md", TEXTO_1)
        rc, _ = corrida(op1, f1, tmp / "B1", ahora=T_A, operador=OP_A)
        check("1: el apply logico X aplica rc=0", rc == 0, f"rc={rc}")

        proc1 = marcas_procedencia(drv1)
        ops1 = marcas_operaciones(drv1)
        eids1 = element_ids(drv1)
        check("1: censo de procedencia NO VACIO", len(proc1) > 0, f"n={len(proc1)}")
        check("1: censo de operaciones NO VACIO", len(ops1) > 0, f"n={len(ops1)}")

        own1 = {v[0] for v in proc1.values()} | {v[0] for v in ops1.values()}
        app1 = {v[1] for v in proc1.values()} | {v[1] for v in ops1.values()}
        check("1: un solo ownership_id", len(own1) == 1 and None not in own1, f"{own1}")
        check("1: un solo apply_id", len(app1) == 1 and None not in app1, f"{app1}")
        if not own1 or not app1:
            print("     sin marcas: nada mas que medir")
            return 1
        OWN1, APP1 = own1.pop(), app1.pop()
        print(f"     ownership_id(1) = {OWN1}")
        print(f"     apply_id(1)     = {APP1}")

        px1 = {k[1] for k in proc1 if k[0] == LABEL_EVIDENCE}
        check("1: PX de evidencia NO VACIO", len(px1) > 0, f"px={sorted(px1)}")

    print("\n===== BASE 2 (base RESTAURADA: mismo apply logico, instante T_B) =====")
    with neo4j_efimero_conexion("s9k-t8-base2") as cx2:
        drv2 = cx2.driver
        op2 = Operador(cx2, tmp)
        check("2: el grafo arranca VACIO", censo_basico(drv2)["nodos"] == 0)

        f2 = fuente(tmp, "fuente-1.md", TEXTO_1)
        rc, _ = corrida(op2, f2, tmp / "B2", ahora=T_B, operador=OP_B)
        check("2: el MISMO apply logico aplica rc=0", rc == 0, f"rc={rc}")

        proc2 = marcas_procedencia(drv2)
        ops2 = marcas_operaciones(drv2)
        eids2 = element_ids(drv2)
        check("2: censo de procedencia NO VACIO", len(proc2) > 0, f"n={len(proc2)}")

        own2 = {v[0] for v in proc2.values()} | {v[0] for v in ops2.values()}
        app2 = {v[1] for v in proc2.values()} | {v[1] for v in ops2.values()}
        check("2: un solo ownership_id", len(own2) == 1 and None not in own2, f"{own2}")
        if not own2 or not app2:
            print("     sin marcas: nada mas que medir")
            return 1
        OWN2, APP2 = own2.pop(), app2.pop()
        print(f"     ownership_id(2) = {OWN2}")
        print(f"     apply_id(2)     = {APP2}")

        # --- lo que hace que lo demas signifique algo ----------------------
        print("\n== las dos bases son DE VERDAD distintas ==")
        check("elementId de 1 y 2 son DISJUNTOS", not (eids1 & eids2),
              f"comunes={len(eids1 & eids2)} |1|={len(eids1)} |2|={len(eids2)}")
        check("ambos censos de elementId NO VACIOS",
              bool(eids1) and bool(eids2), f"|1|={len(eids1)} |2|={len(eids2)}")

        print("\n== la propiedad es DURABLE y el intento NO ==")
        check("MISMO apply logico -> MISMO ownership_id", OWN1 == OWN2,
              f"{OWN1} vs {OWN2}")
        check("otro intento -> apply_id DISTINTO", APP1 != APP2,
              f"{APP1} vs {APP2}")

        # --- LA MEDIDA DE LA MIGRACION ------------------------------------
        print("\n== PX en la base restaurada, por cada marca ==")
        px2 = {k[1] for k in proc2 if k[0] == LABEL_EVIDENCE}
        check("2: PX de evidencia NO VACIO", len(px2) > 0, f"px={sorted(px2)}")

        visto_durable = px_por_marca(drv2, OWN1)
        check("con la marca DURABLE de 1, la base 2 identifica EXACTAMENTE su PX",
              visto_durable == px2,
              f"visto={sorted(visto_durable)} esperado={sorted(px2)}")

        visto_intento = px_por_marca(drv2, APP1)
        check("CONTROL: con el apply_id de 1 (intento) NO se identifica NADA",
              visto_intento == set(),
              f"visto={sorted(visto_intento)} -- si esto no esta vacio, el "
              "control no discrimina y la comprobacion de arriba no mide nada")

        check("CONTROL: el apply_id PROPIO de la base 2 si identifica su PX",
              px_por_marca(drv2, APP2) == px2,
              "si esto fallara, la consulta estaria rota y el vacio de arriba "
              "no probaria nada sobre la durabilidad")

    print("\n== RESULTADO ==")
    print(f"  OK={len(e8b.OK)}  FALLA={len(e8b.KO)}")
    for k in e8b.KO:
        print(f"   - FALLA: {k}")
    return 1 if e8b.KO else 0


if __name__ == "__main__":
    sys.exit(main())

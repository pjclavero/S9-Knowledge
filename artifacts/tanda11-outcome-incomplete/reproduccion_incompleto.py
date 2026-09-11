# -*- coding: utf-8 -*-
"""PASO 1 -- como clasifica el producto una reversion NO RECONSTRUIBLE.

Neo4j REAL, efimero (contenedor propio, con prefijo propio, destruido al
salir). El grafo lo escribe el PRODUCTO por su ruta de operador
(`_b_completo`: fichero -> reconciliar -> aprobar -> apply). NI UNA linea de
Cypher de escritura de siembra: el unico Cypher que este guion ejecuta es el
`DETACH DELETE` de limpieza ENTRE variantes, sobre su propio contenedor.

Lo unico que se fabrica es la forma del DOCUMENTO de reversion, que es una
ENTRADA del mando: se le quita a una instruccion la identidad durable que la
hace localizable --la forma de un documento heredado-- o se le anade una
instruccion que el documento no sabe reconstruir. El producto responde a eso
con `RollbackNotReconstructible` -> `unrecoverable`.

    python3 artifacts/tanda11-outcome-incomplete/reproduccion_incompleto.py

Con `S9K_REPRO_ANTES=1` se restaura la decision ANTERIOR al cambio
(`ROLLED_BACK if clean else UNEXPECTED_RESIDUE`) sin tocar el arbol, para que
el «antes» y el «despues» se midan con el mismo instrumento.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "data-engine" / "app"))
sys.path.insert(0, str(RAIZ / "data-engine" / "app" / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402
import test_knowledge_v3_tanda3_integracion_neo4j_real as tanda3  # noqa: E402
from test_knowledge_v3_tanda3_integracion_neo4j_real import WS_B, _b_completo  # noqa: E402
from test_knowledge_v3_equipo4b_mando_rollback_neo4j_real import (  # noqa: E402
    ENTORNO_AUTORIZADO,
)
from knowledge_v3.writer import cli_rollback  # noqa: E402

CAMPOS_DURABLES = (
    "entity_id", "idempotency_key", "assertion_id",
    "fragment_id", "source_id", "episode_id", "workspace",
)


def reloj_vivo() -> None:
    """El plan de `tanda3` trae `AHORA` fijo y caducado: PLAN_EXPIRED.

    No se relaja ningun TTL: se le da al plan la hora VIVA, que es la que ve
    el mando en produccion. Sin esto el apply sale `REJECTED` y no hay nada
    que revertir -- un rojo prestado que no es de este encargo.
    """
    tanda3.AHORA = (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def decision_anterior(report) -> str:
    """La regla que habia ANTES: un solo bit, dos salidas."""
    return (
        cli_rollback.OUTCOME_ROLLED_BACK
        if report.clean
        else cli_rollback.OUTCOME_UNEXPECTED_RESIDUE
    )


def ejecutar(driver, doc_dict, destino: pathlib.Path):
    destino.write_text(
        json.dumps(doc_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    argv = [
        str(destino), "--workspace", WS_B, "--operator", "pjc",
        "--audit-log", str(destino.parent / "audit.jsonl"), "--execute",
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_rollback.main(
            argv, driver_factory=lambda: driver, env=dict(ENTORNO_AUTORIZADO)
        )
    texto = buf.getvalue()
    return rc, (json.loads(texto) if texto.strip() else {})


def vaciar(driver) -> None:
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")


def informar(titulo, rc, salida):
    rep = salida.get("report", {})
    print(f"\n-- {titulo}")
    print("   outcome           =", salida.get("outcome"))
    print("   rc                =", rc)
    print("   residues          =", len(rep.get("residues", [])))
    print("   unrecoverable     =", len(rep.get("unrecoverable", [])))
    print("   not_reconstructible=", len(rep.get("not_reconstructible", [])))
    print("   human             =", (salida.get("human") or "")[:220])
    sys.stdout.flush()


def main() -> int:
    antes = os.environ.get("S9K_REPRO_ANTES", "").strip() == "1"
    if antes:
        cli_rollback.decide_outcome = decision_anterior
        print("### DECISION ANTERIOR AL CAMBIO (reinyectada)")
    else:
        print("### DECISION DEL ARBOL")
    reloj_vivo()
    tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "repro-incompleto"
    tmp.mkdir(parents=True, exist_ok=True)

    with neo4j_efimero_conexion("s9k-incompleto-repro") as con:
        driver = con.driver
        informe = _b_completo(driver)
        doc = informe["rollback"]
        print("== INSTRUCCIONES QUE EMITE EL PRODUCTO ==")
        for i in doc["instructions"]:
            print("  ", i["operation_id"], i["action"], sorted(i.get("detail", {})))
        sys.stdout.flush()

        # Referencia: el documento TAL CUAL, sobre el grafo que el apply dejo.
        rc, out = ejecutar(driver, doc, tmp / "doc-intacto.json")
        informar("documento INTACTO", rc, out)

        for idx, instr in enumerate(doc["instructions"]):
            mutado = copy.deepcopy(doc)
            detalle = mutado["instructions"][idx].get("detail", {})
            quitados = [k for k in list(detalle) if k in CAMPOS_DURABLES]
            if not quitados:
                continue
            for k in quitados:
                detalle.pop(k)
            vaciar(driver)
            _b_completo(driver)
            rc, out = ejecutar(driver, mutado, tmp / f"doc-{idx}.json")
            informar(
                f"instruccion #{idx} {instr['action']} SIN {quitados}", rc, out
            )
            for u in out.get("report", {}).get("unrecoverable", []):
                print("     U:", u[:150])
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

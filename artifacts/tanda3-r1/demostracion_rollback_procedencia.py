# -*- coding: utf-8 -*-
"""TANDA 3 / EQUIPO R1 -- el rollback revierte lo que creo, y lo dice.

Cinco escenarios MEDIDOS contra un Neo4j real y efimero, con censo del grafo
antes y despues de cada uno:

  A. apply -> rollback -> CERO residuos de esa operacion, y `unrecoverable`
     dice la verdad (antes decia `[]` con 15 nodos y 14 aristas huerfanos).
  B. evidencia COMPARTIDA por una asercion viva -> NO se borra, y se declara.
     Esta es la direccion que hoy pasa por accidente (porque no se borra nada);
     aqui pasa porque se CUENTAN las referencias vivas antes de borrar.
  C. el re-apply no miente: sobre un grafo al que le falta el conocimiento que
     una marca de idempotencia reclama, el desenlace es INCONSISTENT y rc=1,
     no APPLIED/rc=0.
  D. repetir un apply NO destruye el documento de rollback guardado.
  E. sigue siendo idempotente: repetir el apply deja el grafo IDENTICO, medido
     por huella del contenido (sin un solo `elementId`).

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/tanda3-r1/demostracion_rollback_procedencia.py

El contenedor lo levanta y lo destruye la funcion `arrancar` de la
demostracion de la tanda 2, que a su vez es el mismo mecanismo de la fixture
`neo4j_efimero` de `test_knowledge_v3_writer_neo4j_real` (docker run --rm,
puerto libre, password aleatoria). Se IMPORTA, no se copia: no hay un segundo
camino de arranque. Hace falta la URI y la contrasena --la fixture solo cede el
driver-- porque el APPLY va por la CLI, como subproceso.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[2]
APP = RAIZ / "data-engine" / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

import importlib.util  # noqa: E402

import test_knowledge_v3_writer_neo4j_real as W  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "demostracion_tanda2",
    RAIZ / "artifacts" / "tanda2-equipo2" / "demostracion_operador_y_rollback.py",
)
_T2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_T2)
arrancar = _T2.arrancar  # mismo mecanismo de arranque, importado

from knowledge_v3.contracts.base import seal_plan  # noqa: E402
from knowledge_v3.writer import bootstrap_writer_schema  # noqa: E402
from knowledge_v3.writer.provenance import persist_provenance  # noqa: E402
from knowledge_v3.writer.rollback import (  # noqa: E402
    RollbackDocument,
    RollbackInstruction,
)
from knowledge_v3.writer.rollback_provenance import (  # noqa: E402
    execute_rollback,
    residues,
)

WS = W.WORKSPACE
FALLOS: list[str] = []


# --- utilidades de medida --------------------------------------------------
def comprobar(condicion: bool, titulo: str) -> None:
    print("   [%s] %s" % ("OK " if condicion else "FALLO", titulo))
    if not condicion:
        FALLOS.append(titulo)


def censo(probe, titulo: str) -> dict:
    """Censo por etiqueta y tipo de relacion. Dos consultas, nunca dos MATCH
    sueltos en la misma: eso daria producto cartesiano y 0 filas."""
    nodos = probe.run(
        "MATCH (n) UNWIND labels(n) AS etiqueta "
        "RETURN etiqueta, count(*) AS c ORDER BY etiqueta"
    )
    rels = probe.run(
        "MATCH ()-[r]->() RETURN type(r) AS tipo, count(r) AS c ORDER BY tipo"
    )
    resultado = {
        "nodos": {f["etiqueta"]: f["c"] for f in nodos},
        "relaciones": {f["tipo"]: f["c"] for f in rels},
    }
    print("   %-22s nodos=%s" % (titulo, json.dumps(resultado["nodos"], sort_keys=True)))
    print("   %-22s aristas=%s" % ("", json.dumps(resultado["relaciones"], sort_keys=True)))
    return resultado


def huella(probe) -> str:
    """Huella del CONTENIDO. Ni un `elementId`: se regenera al restaurar."""
    nodos = probe.run(
        "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props "
        "ORDER BY labels(n)[0], properties(n).entity_id, properties(n).assertion_id, "
        "properties(n).fragment_id, properties(n).episode_id, "
        "properties(n).source_asset_id, properties(n).idempotency_key"
    )
    rels = probe.run(
        "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, properties(r) AS props, "
        "properties(a) AS desde, properties(b) AS hasta ORDER BY type(r)"
    )
    crudo = json.dumps({"n": nodos, "r": rels}, sort_keys=True, default=str)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def documento(ruta: pathlib.Path) -> RollbackDocument:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    doc = RollbackDocument(
        workspace=datos["workspace"],
        snapshot_id=datos["snapshot_id"],
        plan_hash=datos["plan_hash"],
        unrecoverable=list(datos.get("unrecoverable") or []),
    )
    doc.instructions = [
        RollbackInstruction(
            operation_id=i["operation_id"],
            action=i["action"],
            target_id=i["target_id"],
            detail=i["detail"],
        )
        for i in datos["instructions"]
    ]
    return doc


# --- construccion del plan -------------------------------------------------
def op_assertion(op_id: str, assertion_id: str, subject: str, obj: str,
                 fragmentos: list[str], clave: str) -> dict:
    operacion = W.create_assertion(op_id, assertion_id, subject, obj)
    operacion["evidence_fragment_ids"] = list(fragmentos)
    operacion["idempotency_key"] = "idem:sha256:" + clave
    return operacion


def plan_vigente(operations, **kwargs) -> dict:
    """El plan de la fixture, con la ventana de vigencia ABIERTA y resellado.

    `make_plan` fija una ventana de julio de 2026: hoy caduca y la admision lo
    rechaza con `PLAN_EXPIRED` antes de escribir nada. Se corrige el dato y se
    vuelve a sellar, que es lo que hace el motor local.
    """
    plan = W.make_plan(operations=operations, **kwargs)
    plan["created_at"] = "2026-09-01T00:00:00Z"
    plan["expires_at"] = "2099-01-01T00:00:00Z"
    return seal_plan(plan)


def procedencia(fragmentos: list[tuple[str, str]], episodio: str, fuente: str) -> dict:
    """Documentos de procedencia con la forma plana que persiste el volcado."""
    return {
        "source_asset": {
            "source_asset_id": fuente,
            "original_name": "r1-fuente.md",
            "media_type": "text/markdown",
        },
        "episodes": [{
            "episode_id": episodio,
            "source_asset_id": fuente,
            "sequence": 1,
            "text": "capitulo unico",
        }],
        "fragments": [
            {"fragment_id": fid, "episode_id": episodio, "literal_text": texto}
            for fid, texto in fragmentos
        ],
    }


def aplicar(tmp: pathlib.Path, uri: str, ruta_pass: pathlib.Path, plan: dict,
            nombre: str, rollback_out: pathlib.Path | None, extra: list[str] = ()):
    """El APPLY por la CLI, como SUBPROCESO. La ruta de operador de verdad."""
    ruta_plan = tmp / f"{nombre}.json"
    ruta_plan.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    cmd = [
        sys.executable, "-m", "knowledge_v3.writer.cli", str(ruta_plan),
        "--workspace", WS, "--snapshot", W.SNAPSHOT,
        "--audit-log", str(tmp / "audit.jsonl"),
        "--applied-keys", str(tmp / "keys.jsonl"),
        "--operator", "r1",
        "--expect-plan-hash", plan["plan_hash"]["value"], "--apply",
        "--neo4j-uri", uri, "--neo4j-user", "neo4j",
        "--neo4j-password-file", str(ruta_pass),
    ]
    if rollback_out is not None:
        cmd += ["--rollback-out", str(rollback_out)]
    cmd += list(extra)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(APP)
    env["S9K_ALLOW_REAL_INGEST"] = "1"
    env["S9K_WRITER_WORKSPACE"] = WS
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env, cwd=str(RAIZ))
    print("   $ python -m knowledge_v3.writer.cli %s ... --apply" % ruta_plan.name)
    # La CLI imprime uno o mas objetos JSON seguidos. Se decodifican con
    # `raw_decode`, que sabe donde acaba cada uno: partir el texto por una
    # llave adivinada se rompe en cuanto cambia el formato.
    salida = proc.stdout.strip()
    resumen: dict = {}
    decoder = json.JSONDecoder()
    resto = salida
    while resto.strip():
        try:
            objeto, fin = decoder.raw_decode(resto.strip())
        except ValueError:
            break
        resumen.update(objeto)
        resto = resto.strip()[fin:]
    print("   rc=%d outcome=%s applied=%s noop=%s codes=%s" % (
        proc.returncode, resumen.get("outcome"), resumen.get("applied_operations"),
        resumen.get("noop_operations"),
        [r.get("code") for r in (resumen.get("rejections") or [])],
    ))
    if proc.stderr.strip():
        print("   stderr> " + proc.stderr.strip()[:600])
    return proc.returncode, resumen


# --- escenarios ------------------------------------------------------------
def escenario_a(probe, driver, tmp, uri, ruta_pass):
    print("\n=== A. apply -> rollback -> CERO residuos, y `unrecoverable` no miente")
    probe.clean()
    probe.seed_entity("entity:ilaria")
    probe.seed_entity("entity:casa")
    plan = plan_vigente(operations=[op_assertion(
        "op:0001", "assertion:a1", "entity:ilaria", "entity:casa",
        ["fragment:f1"], "a" * 64)])
    ruta_rb = tmp / "rollback-a.json"
    rc, _ = aplicar(tmp, uri, ruta_pass, plan, "plan-a", ruta_rb)
    comprobar(rc == 0, "A0: el APPLY sale limpio")

    prov = procedencia([("fragment:f1", "Ilaria lidera la Casa del Ciervo.")],
                       "episode:e1", "source:s1")
    resultado = persist_provenance(driver, workspace=WS, assertion_ids=["assertion:a1"], **prov)
    print("   procedencia escrita: %s" % json.dumps(resultado.to_dict(), sort_keys=True))

    antes = censo(probe, "ANTES del rollback")
    comprobar(antes["nodos"].get("V3Assertion") == 1, "A1: hay 1 asercion (no medimos el vacio)")
    comprobar(antes["nodos"].get("V3Evidence") == 1, "A2: hay evidencia persistida")
    comprobar(antes["relaciones"].get("SUPPORTED_BY") == 1, "A3: la arista de evidencia existe")

    doc = documento(ruta_rb)
    with driver.session() as sesion:
        informe = execute_rollback(sesion, doc)
    despues = censo(probe, "DESPUES del rollback")
    print("   unrecoverable = %s" % json.dumps(doc.unrecoverable, ensure_ascii=False))
    print("   residuos      = %s" % json.dumps(informe.residues, ensure_ascii=False, default=str))

    comprobar(despues["nodos"].get("V3Assertion", 0) == 0, "A4: la asercion se fue")
    comprobar(despues["nodos"].get("V3Evidence", 0) == 0, "A5: la evidencia HUERFANA se fue")
    comprobar(despues["nodos"].get("V3Episode", 0) == 0, "A6: el episodio sin fragmentos se fue")
    comprobar(despues["nodos"].get("V3Source", 0) == 0, "A7: la fuente sin episodios se fue")
    comprobar(despues["nodos"].get("V3AppliedOperation", 0) == 0, "A8: la marca de idempotencia se fue")
    comprobar(despues["nodos"].get("V3Entity") == 2, "A9: las entidades AJENAS al plan siguen ahi")
    comprobar(informe.residues == [], "A10: cero residuos MEDIDOS")
    comprobar(informe.clean and doc.unrecoverable == [],
              "A11: `unrecoverable` vacio porque de verdad no queda nada")
    return doc


def escenario_b(probe, driver, tmp, uri, ruta_pass):
    print("\n=== B. evidencia COMPARTIDA por una asercion viva: NO se borra")
    probe.clean()
    probe.seed_entity("entity:ilaria")
    probe.seed_entity("entity:casa")
    plan1 = plan_vigente(operations=[op_assertion(
        "op:0001", "assertion:b1", "entity:ilaria", "entity:casa",
        ["fragment:compartido", "fragment:solo-de-b1"], "b" * 64)],
        plan_id="plan:r1:b1")
    plan2 = plan_vigente(operations=[op_assertion(
        "op:0002", "assertion:b2", "entity:ilaria", "entity:casa",
        ["fragment:compartido"], "c" * 64)],
        plan_id="plan:r1:b2")
    ruta_rb1 = tmp / "rollback-b1.json"
    rc1, _ = aplicar(tmp, uri, ruta_pass, plan1, "plan-b1", ruta_rb1)
    rc2, _ = aplicar(tmp, uri, ruta_pass, plan2, "plan-b2", tmp / "rollback-b2.json")
    comprobar(rc1 == 0 and rc2 == 0, "B0: los dos APPLY salen limpios")

    prov = procedencia(
        [("fragment:compartido", "Ilaria lidera la Casa del Ciervo."),
         ("fragment:solo-de-b1", "Solo lo cita b1.")],
        "episode:e1", "source:s1")
    persist_provenance(driver, workspace=WS,
                       assertion_ids=["assertion:b1", "assertion:b2"], **prov)

    antes = censo(probe, "ANTES del rollback")
    compartida = probe.run(
        "MATCH (a:V3Assertion)-[:SUPPORTED_BY]->(ev:V3Evidence "
        "{fragment_id:'fragment:compartido'}) RETURN a.assertion_id AS id ORDER BY id")
    print("   aserciones que sostienen el fragmento compartido: %s" %
          [f["id"] for f in compartida])
    comprobar(len(compartida) == 2, "B1: DOS aserciones comparten el mismo fragmento")

    doc = documento(ruta_rb1)
    with driver.session() as sesion:
        informe = execute_rollback(sesion, doc)
    despues = censo(probe, "DESPUES del rollback de b1")
    print("   unrecoverable = %s" % json.dumps(doc.unrecoverable, ensure_ascii=False))
    print("   purgas        = %s" % json.dumps(informe.purges, ensure_ascii=False, default=str))

    viva = probe.run(
        "MATCH (a:V3Assertion {assertion_id:'assertion:b2'})-[:SUPPORTED_BY]->"
        "(ev:V3Evidence) RETURN ev.fragment_id AS id, ev.literal_text AS texto")
    print("   b2 (viva) conserva su evidencia: %s" % json.dumps(viva, ensure_ascii=False))
    comprobar(len(viva) == 1 and viva[0]["id"] == "fragment:compartido",
              "B2: la evidencia compartida SIGUE, con su literal, colgando de la viva")
    comprobar(despues["nodos"].get("V3Assertion") == 1, "B3: b1 se fue, b2 sigue")
    comprobar(despues["nodos"].get("V3Evidence") == 1,
              "B4: se borro SOLO el fragmento que se quedo sin referencias")
    comprobar(despues["nodos"].get("V3Episode") == 1 and despues["nodos"].get("V3Source") == 1,
              "B5: episodio y fuente se CONSERVAN porque aun cuelga un fragmento")
    huerfanas = probe.run(
        "MATCH (ev:V3Evidence) WHERE NOT EXISTS "
        "{ MATCH (:V3Assertion)-[:SUPPORTED_BY]->(ev) } RETURN ev.fragment_id AS id")
    print("   V3Evidence sin ninguna asercion viva detras: %d" % len(huerfanas))
    comprobar(len(huerfanas) == 0, "B6: CERO evidencia huerfana (el defecto original)")
    comprobar(any("ROLLBACK_RETAINED_SHARED" in u for u in doc.unrecoverable),
              "B7: lo conservado se DECLARA en `unrecoverable`, no se calla")
    comprobar(informe.residues == [], "B8: no hay residuos de la operacion revertida")


def escenario_c(probe, driver, tmp, uri, ruta_pass):
    print("\n=== C. el re-apply no miente sobre un grafo inconsistente")
    probe.clean()
    probe.seed_entity("entity:ilaria")
    probe.seed_entity("entity:casa")
    plan = plan_vigente(operations=[op_assertion(
        "op:0001", "assertion:c1", "entity:ilaria", "entity:casa",
        ["fragment:f1"], "d" * 64)], plan_id="plan:r1:c")
    ruta_rb = tmp / "rollback-c.json"
    rc, _ = aplicar(tmp, uri, ruta_pass, plan, "plan-c", ruta_rb)
    comprobar(rc == 0, "C0: el primer APPLY sale limpio")

    # El defecto tal cual estaba: se borra el conocimiento y la MARCA sobrevive.
    borradas = probe.run(
        "MATCH (a:V3Assertion {assertion_id:'assertion:c1'}) DETACH DELETE a "
        "RETURN count(*) AS c")
    marcas = probe.run("MATCH (op:V3AppliedOperation) RETURN count(op) AS c")[0]["c"]
    print("   asercion borrada a mano: %s · marcas que sobreviven: %d"
          % (json.dumps(borradas), marcas))
    comprobar(marcas == 1, "C1: la marca de idempotencia sigue reclamando la operacion")

    rc2, resumen = aplicar(tmp, uri, ruta_pass, plan, "plan-c", None)
    comprobar(rc2 == 1, "C2: rc=1, NO rc=0")
    comprobar(resumen.get("outcome") == "INCONSISTENT",
              "C3: outcome=INCONSISTENT, no APPLIED")
    comprobar(any(r.get("code") == "EXEC_NOOP_WITHOUT_GRAPH_EVIDENCE"
                  for r in (resumen.get("rejections") or [])),
              "C4: el motivo viaja con codigo estable")

    # Y por el camino BUENO: rollback completo -> el re-apply reescribe de verdad.
    probe.clean()
    probe.seed_entity("entity:ilaria")
    probe.seed_entity("entity:casa")
    ruta_rb2 = tmp / "rollback-c2.json"
    (tmp / "keys.jsonl").unlink(missing_ok=True)
    aplicar(tmp, uri, ruta_pass, plan, "plan-c", ruta_rb2)
    doc = documento(ruta_rb2)
    with driver.session() as sesion:
        execute_rollback(sesion, doc)
    censo(probe, "tras el rollback completo")
    rc3, resumen3 = aplicar(tmp, uri, ruta_pass, plan, "plan-c", None,
                            ["--forget-applied-keys", str(ruta_rb2)])
    comprobar(rc3 == 0 and resumen3.get("outcome") == "APPLIED"
              and resumen3.get("applied_operations") == 1,
              "C5: tras un rollback COMPLETO el re-apply vuelve a escribir de verdad")
    vivas = probe.run("MATCH (a:V3Assertion) RETURN count(a) AS c")[0]["c"]
    comprobar(vivas == 1, "C6: y el conocimiento esta otra vez en el grafo")


def escenario_d(probe, tmp, uri, ruta_pass):
    print("\n=== D. repetir el apply NO destruye el documento de rollback")
    probe.clean()
    probe.seed_entity("entity:ilaria")
    probe.seed_entity("entity:casa")
    plan = plan_vigente(operations=[op_assertion(
        "op:0001", "assertion:d1", "entity:ilaria", "entity:casa",
        ["fragment:f1"], "e" * 64)], plan_id="plan:r1:d")
    ruta_rb = tmp / "rollback-d.json"
    aplicar(tmp, uri, ruta_pass, plan, "plan-d", ruta_rb)
    poliza = ruta_rb.read_text(encoding="utf-8")
    sha_antes = hashlib.sha256(poliza.encode("utf-8")).hexdigest()
    instrucciones = len(json.loads(poliza)["instructions"])
    print("   poliza guardada: %d instrucciones · sha256=%s" % (instrucciones, sha_antes[:16]))
    comprobar(instrucciones > 0, "D1: la primera poliza trae instrucciones")

    rc, resumen = aplicar(tmp, uri, ruta_pass, plan, "plan-d", ruta_rb)
    sha_despues = hashlib.sha256(ruta_rb.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    print("   tras repetir el apply: sha256=%s rc=%d" % (sha_despues[:16], rc))
    comprobar(sha_antes == sha_despues, "D2: la poliza NO se piso con un documento vacio")
    comprobar(rc == 2, "D3: y el rc lo dice (2: hay algo que leer, no es exito limpio)")
    return plan, ruta_rb


def escenario_e(probe, tmp, uri, ruta_pass, plan):
    print("\n=== E. sigue siendo idempotente: el grafo queda IDENTICO")
    antes = huella(probe)
    censo(probe, "antes de repetir")
    rc, resumen = aplicar(tmp, uri, ruta_pass, plan, "plan-d", None)
    despues = huella(probe)
    censo(probe, "tras repetir")
    print("   huella antes  = %s" % antes)
    print("   huella despues= %s" % despues)
    comprobar(antes == despues, "E1: huella del CONTENIDO identica (sin elementId)")
    comprobar(resumen.get("applied_operations") == 0 and resumen.get("noop_operations") == 1,
              "E2: 0 escrituras nuevas, 1 no-op")
    comprobar(rc == 0 and resumen.get("outcome") == "APPLIED",
              "E3: y ese no-op SI es legitimo (el grafo lo respalda): rc=0")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="s9k-t3r1-"))
    driver, contenedor, uri, password = arrancar("t3r1")
    try:
        bootstrap_writer_schema(driver)
        probe = W.GraphProbe(driver=driver)
        ruta_pass = tmp / "neo4j.pass"
        ruta_pass.write_text(password, encoding="utf-8")
        ruta_pass.chmod(0o600)
        print("== Neo4j efimero en %s" % uri)

        escenario_a(probe, driver, tmp, uri, ruta_pass)
        escenario_b(probe, driver, tmp, uri, ruta_pass)
        escenario_c(probe, driver, tmp, uri, ruta_pass)
        plan, _ = escenario_d(probe, tmp, uri, ruta_pass)
        escenario_e(probe, tmp, uri, ruta_pass, plan)
    finally:
        try:
            driver.close()
        except Exception:
            pass
        W._run(["docker", "rm", "-f", contenedor], check=False)

    print("\n== VEREDICTO: %s" % ("TODO MEDIDO EN VERDE" if not FALLOS
                                 else "FALLOS: %s" % FALLOS))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())

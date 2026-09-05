# -*- coding: utf-8 -*-
"""TANDA 2 / EQUIPO 2 -- evidencia de las dos cosas que se pedian.

1. **Ruta de operador**: un fichero de plan, la CLI del writer ejecutada como
   SUBPROCESO (nada de Python que inyecte dependencias) y un Neo4j real que
   cambia.
2. **Rollback que sobrevive al cambio de `elementId`**: el grafo se vuelca, se
   destruye la base, se levanta OTRA y se resiembra. Los `elementId` son otros
   -- llevan el UUID de la base -- y el documento de rollback guardado en el
   paso 1 sigue localizando y borrando exactamente la relacion correcta, sin
   tocar a la vecina.

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/tanda2-equipo2/demostracion_operador_y_rollback.py

El contenedor lo levanta y lo destruye este guion reutilizando el MISMO
mecanismo que la fixture `neo4j_driver` de `test_knowledge_v3_writer_neo4j_real`
(docker run --rm, puerto libre, password aleatoria): no hay un segundo camino de
arranque.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[2]
APP = RAIZ / "data-engine" / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

import neo4j  # noqa: E402

import test_knowledge_v3_writer_neo4j_real as W  # noqa: E402
from knowledge_v3.contracts.base import seal_plan  # noqa: E402
from knowledge_v3.writer import bootstrap_writer_schema  # noqa: E402
from knowledge_v3.writer.rollback import RollbackInstruction, rollback_query  # noqa: E402

WS = W.WORKSPACE
IDEM_VECINA = "idem:sha256:" + "f" * 64


def arrancar(prefijo: str):
    """Mismo mecanismo que la fixture `neo4j_driver`, sin pytest."""
    image = os.environ.get("S9K_WRITER_NEO4J_IMAGE", "neo4j:5.26-community")
    name = f"s9k-{prefijo}-" + uuid.uuid4().hex[:12]
    port = W._free_port()
    password = prefijo + "-" + uuid.uuid4().hex[:16]
    W._run([
        "docker", "run", "--rm", "--detach", "--name", name,
        "--publish", f"127.0.0.1:{port}:7687",
        "--env", f"NEO4J_AUTH=neo4j/{password}",
        "--env", "NEO4J_server_memory_heap_initial__size=128m",
        "--env", "NEO4J_server_memory_heap_max__size=256m",
        image,
    ])
    uri = f"bolt://127.0.0.1:{port}"
    driver = neo4j.GraphDatabase.driver(uri, auth=("neo4j", password))
    limite = time.monotonic() + 240
    while True:
        try:
            driver.verify_connectivity()
            break
        except Exception:
            if time.monotonic() >= limite:
                raise
            time.sleep(1)
    bootstrap_writer_schema(driver)
    return driver, name, uri, password


def consulta(probe, titulo, cypher, params=None):
    filas = probe.run(cypher, params or {})
    print("\n--- %s" % titulo)
    print("    cypher> %s" % " ".join(cypher.split()))
    for fila in filas:
        print("    " + json.dumps(fila, sort_keys=True, default=str, ensure_ascii=False))
    if not filas:
        print("    (0 filas)")
    return filas


def volcado_logico(probe):
    """Nodos y relaciones con sus propiedades. Sin un solo `elementId`."""
    nodos = probe.run(
        "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props "
        "ORDER BY labels(n)[0]"
    )
    rels = probe.run(
        "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, properties(r) AS props, "
        "a.entity_id AS desde, b.entity_id AS hasta "
        "ORDER BY type(r), a.entity_id, b.entity_id"
    )
    return {"nodos": nodos, "relaciones": rels}


def resembrar(probe, volcado):
    """Recrea el volcado en OTRA base: mismos datos, `elementId` nuevos."""
    for nodo in volcado["nodos"]:
        etiquetas = ":".join(nodo["labels"])
        probe.run(f"CREATE (n:{etiquetas}) SET n = $props", {"props": nodo["props"]})
    for rel in volcado["relaciones"]:
        probe.run(
            f"MATCH (a {{entity_id: $desde}}) MATCH (b {{entity_id: $hasta}}) "
            f"CREATE (a)-[r:{rel['tipo']}]->(b) SET r = $props",
            {"desde": rel["desde"], "hasta": rel["hasta"], "props": rel["props"]},
        )


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="s9k-tanda2-eq2-"))
    driver_a, name_a, uri_a, pass_a = arrancar("t2e2-base-a")
    name_b = None
    try:
        probe = W.GraphProbe(driver=driver_a)
        probe.clean()
        print("== BASE A: Neo4j efimero en %s (contenedor %s)" % (uri_a, name_a))

        # -----------------------------------------------------------------
        # 1. El plan, como fichero. Y las entidades que enlaza, sembradas.
        # -----------------------------------------------------------------
        probe.seed_entity("entity:origen", version=1, state_hash=W.HASH_A["value"])
        probe.seed_entity("entity:destino", version=1, state_hash=W.HASH_B["value"])
        plan = W.make_plan([W.link_existing("op:0001", "entity:origen", "entity:destino")])
        plan["created_at"] = "2026-09-01T00:00:00Z"
        plan["expires_at"] = "2099-01-01T00:00:00Z"
        plan = seal_plan(plan)
        ruta_plan = tmp / "plan.json"
        ruta_plan.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        ruta_pass = tmp / "neo4j.pass"
        ruta_pass.write_text(pass_a, encoding="utf-8")
        ruta_pass.chmod(0o600)
        print("\n== 1. Plan en fichero: %s" % ruta_plan.name)
        print("   plan_hash    : %s" % plan["plan_hash"]["value"])
        print("   operaciones  : %s" % [o["operation_type"] for o in plan["mutation_operations"]])
        print("   fichero de contrasena: modo %o" % (ruta_pass.stat().st_mode & 0o777))

        base_cmd = [
            sys.executable, "-m", "knowledge_v3.writer.cli", str(ruta_plan),
            "--workspace", WS, "--snapshot", W.SNAPSHOT,
            "--audit-log", str(tmp / "audit.jsonl"),
            "--applied-keys", str(tmp / "keys.jsonl"),
        ]
        entorno = dict(os.environ)
        entorno["PYTHONPATH"] = str(APP)

        def operador(extra, env_extra=None, titulo=""):
            env = dict(entorno)
            for clave in ("S9K_ALLOW_REAL_INGEST", "S9K_WRITER_WORKSPACE"):
                env.pop(clave, None)
            env.update(env_extra or {})
            cmd = base_cmd + extra
            print("\n$ %s" % " ".join(cmd))
            proc = subprocess.run(cmd, text=True, capture_output=True, env=env, cwd=str(RAIZ))
            rc = proc.returncode
            print(proc.stdout.strip()[:2500])
            if proc.stderr.strip():
                print("stderr> " + proc.stderr.strip()[:800])
            print("rc=%d  (%s)" % (rc, titulo))
            assert pass_a not in proc.stdout and pass_a not in proc.stderr, \
                "LA CONTRASENA SE IMPRIMIO"
            return rc, proc.stdout

        # -----------------------------------------------------------------
        # 2. Gates: siguen cerrados. Cada uno por separado.
        # -----------------------------------------------------------------
        print("\n== 2. Las garantias del gate, una a una (ninguna se relajo)")
        aplica = [
            "--operator", "pjc",
            "--expect-plan-hash", plan["plan_hash"]["value"], "--apply",
            "--neo4j-uri", uri_a, "--neo4j-user", "neo4j",
            "--neo4j-password-file", str(ruta_pass),
            "--rollback-out", str(tmp / "rollback.json"),
        ]
        ok_env = {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS}
        hash_malo = [a if a != plan["plan_hash"]["value"] else "e" * 64 for a in aplica]
        for titulo, extra, env_extra in [
            ("dry-run: modo seguro por defecto", [], {}),
            ("GATE_ENV_NOT_ALLOWED", aplica, {"S9K_WRITER_WORKSPACE": WS}),
            ("GATE_WORKSPACE_NOT_DECLARED", aplica, {"S9K_ALLOW_REAL_INGEST": "1"}),
            ("GATE_PLAN_HASH_NOT_CONFIRMED", hash_malo, ok_env),
        ]:
            operador(extra, env_extra, titulo)
        print("\n   grafo tras los intentos bloqueados: %s" % probe.knowledge_counts())
        assert probe.knowledge_counts()["relationships"] == 0, "un intento bloqueado escribio"

        # -----------------------------------------------------------------
        # 3. APPLY de verdad, por la CLI.
        # -----------------------------------------------------------------
        print("\n== 3. APPLY real por la ruta de operador")
        rc, salida = operador(aplica, ok_env, "APPLY")
        assert rc == 0, "el APPLY no salio limpio"
        antes = consulta(probe, "3a. La relacion escrita, con su elementId en la BASE A",
                         "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, a.entity_id AS desde, "
                         "b.entity_id AS hasta, r.idempotency_key AS idem, "
                         "elementId(r) AS element_id")
        assert antes, "no se midio ninguna relacion"
        element_id_a = antes[0]["element_id"]

        rollback_doc = json.loads((tmp / "rollback.json").read_text(encoding="utf-8"))
        print("\n== 3b. Documento de rollback guardado (--rollback-out)")
        print(json.dumps(rollback_doc, indent=2, ensure_ascii=False, sort_keys=True))

        # Vecina: MISMOS extremos, MISMO predicado, otra operacion. Es la que
        # NO se puede borrar.
        probe.run(
            "MATCH (a:V3Entity {entity_id:'entity:origen', workspace:$ws}) "
            "MATCH (b:V3Entity {entity_id:'entity:destino', workspace:$ws}) "
            "CREATE (a)-[:MEMBER_OF {workspace:$ws, idempotency_key:$k, nota:'vecina'}]->(b)",
            {"ws": WS, "k": IDEM_VECINA},
        )

        # -----------------------------------------------------------------
        # 4. Otra base: mismos datos, elementId distintos.
        # -----------------------------------------------------------------
        volcado = volcado_logico(probe)
        driver_a.close()
        W._run(["docker", "rm", "-f", name_a], check=False)
        driver_b, name_b, uri_b, _ = arrancar("t2e2-base-b")
        probe_b = W.GraphProbe(driver=driver_b)
        probe_b.clean()
        resembrar(probe_b, volcado)
        print("\n== 4. BASE B (%s): el volcado resembrado, elementId NUEVOS" % uri_b)
        despues = consulta(probe_b, "4a. Relaciones en la BASE B",
                           "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, a.entity_id AS desde, "
                           "b.entity_id AS hasta, r.idempotency_key AS idem, "
                           "elementId(r) AS element_id ORDER BY r.idempotency_key")
        assert len(despues) == 2, "esperaba la relacion del plan y su vecina"
        nuevos = {f["element_id"] for f in despues}
        print("\n   elementId en A : %s" % element_id_a)
        print("   elementId en B : %s" % sorted(nuevos))
        assert element_id_a not in nuevos, "el elementId no cambio: la prueba no mide nada"
        huerfano = probe_b.run(
            "MATCH ()-[r]->() WHERE elementId(r) = $eid RETURN count(*) AS c",
            {"eid": element_id_a})[0]["c"]
        print("   relaciones con el elementId VIEJO en B: %d  <- ahi apuntaba el rollback anterior"
              % huerfano)
        assert huerfano == 0

        # -----------------------------------------------------------------
        # 5. El rollback guardado, ejecutado contra la BASE B.
        # -----------------------------------------------------------------
        instr = [
            RollbackInstruction(
                operation_id=i["operation_id"], action=i["action"],
                target_id=i["target_id"], detail=i["detail"],
            )
            for i in rollback_doc["instructions"]
            if i["action"] == "DELETE_RELATIONSHIP"
        ]
        assert instr, "el documento no traia ninguna instruccion de relacion"
        for i in instr:
            q = rollback_query(i)
            print("\n== 5. Rollback reconstruido desde el documento GUARDADO")
            print("   cypher> %s" % " ".join(q.cypher.split()))
            print("   params> %s" % json.dumps(q.params, sort_keys=True, ensure_ascii=False))
            assert "elementId" not in q.cypher
            assert element_id_a not in json.dumps(q.params)
            filas = probe_b.run(q.cypher, q.params)
            print("   resultado> %s" % filas)
            assert filas and filas[0]["borradas"] == 1, "el rollback no borro la relacion"

        final = consulta(probe_b, "5a. Que queda en la BASE B tras el rollback",
                         "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, a.entity_id AS desde, "
                         "b.entity_id AS hasta, r.idempotency_key AS idem, r.nota AS nota")
        assert len(final) == 1 and final[0]["idem"] == IDEM_VECINA, \
            "el rollback borro de mas o de menos"
        nodos = probe_b.run("MATCH (n) WHERE n:V3Entity RETURN count(n) AS c")[0]["c"]
        print("\n   entidades intactas tras el rollback: %d" % nodos)
        assert nodos == 2, "el rollback toco nodos que no eran suyos"

        print("\n== VEREDICTO: ruta de operador viva y rollback ejecutable "
              "tras cambiar los elementId, sin borrar de mas")
        return 0
    finally:
        try:
            driver_a.close()
        except Exception:
            pass
        W._run(["docker", "rm", "-f", name_a], check=False)
        if name_b:
            W._run(["docker", "rm", "-f", name_b], check=False)


if __name__ == "__main__":
    raise SystemExit(main())

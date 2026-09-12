# -*- coding: utf-8 -*-
"""CARRIL B -- la cadena completa, con MANDOS DE OPERADOR y un Neo4j real.

No es una puerta ni un test: es el guion que genera la evidencia del informe.
Levanta un Neo4j efimero y despues NO llama a ninguna funcion interna: invoca
los mismos comandos que teclearia un operador, por `subprocess`, e imprime cada
comando con su salida real.

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/carril-b/demostracion_vertical.py

Lo que se demuestra, en este orden:

  1. el grafo empieza VACIO (se cuenta, no se supone);
  2. la ingesta lee el catalogo DEL GRAFO y reconcilia: todo sale como
     `CREATE_ENTITY_REQUIRED`, ninguna alta se aplica sola;
  3. un APPLY sin revision se BLOQUEA;
  4. una persona aprueba las altas POR ID;
  5. el APPLY escribe, con el gate triple del writer intacto;
  6. la procedencia queda navegable: `assertion -> evidence -> episode -> source`.

El contenedor lo levanta y lo destruye `neo4j_efimero_conexion`, el MISMO
mecanismo de arranque que la fixture de `test_knowledge_v3_writer_neo4j_real`.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[2]
APP = RAIZ / "data-engine" / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402

from knowledge_v3.writer.provenance import trace  # noqa: E402

EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"
WS = "ws-cofradia"
AHORA = "2026-09-06T10:00:00Z"


def titulo(texto: str) -> None:
    print()
    print("=" * 74)
    print(texto)
    print("=" * 74)


def ejecutar(argv: list[str], entorno: dict) -> subprocess.CompletedProcess:
    """Corre un mando de operador y ENSENA el comando y su salida."""
    print("$ " + " ".join(argv))
    print("-" * 74)
    proc = subprocess.run(argv, text=True, capture_output=True, env=entorno,
                          cwd=str(RAIZ))
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print("[stderr] " + proc.stderr.rstrip())
    print(f"[rc={proc.returncode}]")
    return proc


def consulta(driver, cypher: str, params: dict | None = None) -> list[dict]:
    """Cypher con su resultado. Nunca dos MATCH sueltos: no hay cartesiano."""
    with driver.session() as s:
        filas = [r.data() for r in s.run(cypher, params or {})]
    print("  cypher> " + cypher)
    print("  filas>  " + json.dumps(filas, ensure_ascii=False, sort_keys=True))
    return filas


def main() -> int:
    with neo4j_efimero_conexion("s9k-carril-b-demo") as cx:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="carril-b-"))
        # El secreto va a un fichero PRIVADO. Nunca por `argv`, nunca impreso.
        pw = tmp / "neo4j.pass"
        pw.write_text(cx.password, encoding="utf-8")
        pw.chmod(stat.S_IRUSR | stat.S_IWUSR)

        salida = tmp / "corrida"
        decisiones = salida / "decisiones.json"

        base = dict(os.environ)
        base["PYTHONPATH"] = str(APP)
        conexion = [
            "--neo4j-uri", cx.uri,
            "--neo4j-user", cx.user,
            "--neo4j-password-file", str(pw),
        ]
        cli = [sys.executable, "-m", "knowledge_v3.pipeline.ingest_cli"]

        titulo("PASO 0 -- el grafo esta VACIO (se cuenta, no se supone)")
        consulta(cx.driver,
                 "MATCH (n:V3Entity {workspace: $ws}) RETURN count(n) AS entidades",
                 {"ws": WS})
        consulta(cx.driver,
                 "MATCH (n:V3Assertion {workspace: $ws}) RETURN count(n) AS aserciones",
                 {"ws": WS})

        titulo("PASO 1 -- ingesta con el catalogo LEIDO DEL GRAFO")
        ejecutar(cli + [
            str(FUENTE.relative_to(RAIZ)), "--perfil", str(PERFIL.relative_to(RAIZ)),
            "--catalogo", str(CATALOGO.relative_to(RAIZ)), "--desde-grafo", "--out-dir", str(salida), "--ahora", AHORA,
            "--ingerido-en", AHORA,
        ] + conexion, base)

        if decisiones.exists():
            doc = json.loads(decisiones.read_text(encoding="utf-8"))
            print()
            print("decisiones de identidad (documento completo, sin recortar):")
            print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))

        titulo("PASO 2 -- un APPLY SIN revision se BLOQUEA")
        gate = dict(base)
        gate["S9K_ALLOW_REAL_INGEST"] = "1"
        gate["S9K_WRITER_WORKSPACE"] = WS
        ejecutar(cli + [
            str(FUENTE.relative_to(RAIZ)), "--perfil", str(PERFIL.relative_to(RAIZ)),
            "--catalogo", str(CATALOGO.relative_to(RAIZ)), "--apply", "--operador", "pjc", "--decisiones", str(decisiones),
            "--ahora", AHORA, "--ingerido-en", AHORA,
        ] + conexion, gate)
        print()
        print("  el grafo NO se ha movido:")
        consulta(cx.driver,
                 "MATCH (n:V3Entity {workspace: $ws}) RETURN count(n) AS entidades",
                 {"ws": WS})

        titulo("PASO 3 -- una persona aprueba las altas POR ID")
        doc = json.loads(decisiones.read_text(encoding="utf-8"))
        pendientes = sorted({
            d["entity_id"] for d in doc["decisions"]
            if d["decision"] == "CREATE_ENTITY_REQUIRED" and d["review"] == "PENDIENTE"
        })
        aprobar: list[str] = []
        for entity_id in pendientes:
            aprobar += ["--aprobar-alta", entity_id]
        ejecutar(cli + [
            "--revisar", "--decisiones", str(decisiones), "--revisor", "pjc",
        ] + aprobar, base)

        titulo("PASO 4 -- APPLY real, con el gate triple del writer")
        ejecutar(cli + [
            str(FUENTE.relative_to(RAIZ)), "--perfil", str(PERFIL.relative_to(RAIZ)),
            "--catalogo", str(CATALOGO.relative_to(RAIZ)), "--apply", "--operador", "pjc", "--decisiones", str(decisiones),
            "--out-dir", str(salida), "--ahora", AHORA, "--ingerido-en", AHORA,
        ] + conexion, gate)

        titulo("PASO 5 -- que hay AHORA en el grafo")
        consulta(cx.driver,
                 "MATCH (n:V3Entity {workspace: $ws}) "
                 "RETURN n.entity_id AS entity_id, n.name AS name, "
                 "n.entity_type AS tipo, n.version AS version "
                 "ORDER BY n.entity_id", {"ws": WS})
        consulta(cx.driver,
                 "MATCH (n:V3Assertion {workspace: $ws}) "
                 "RETURN n.assertion_id AS assertion_id, n.predicate AS predicate, "
                 "n.subject_entity_id AS sujeto, n.object_entity_id AS objeto "
                 "ORDER BY n.assertion_id", {"ws": WS})

        titulo("PASO 6 -- procedencia NAVEGABLE, por el CAMINO (una sola consulta)")
        aserciones = consulta(
            cx.driver,
            "MATCH (n:V3Assertion {workspace: $ws}) RETURN n.assertion_id AS id "
            "ORDER BY n.assertion_id", {"ws": WS})
        if not aserciones:
            print("  NO HAY ASERCIONES: no hay recorrido que ensenar. "
                  "Un conjunto vacio no demuestra nada.")
            return 1
        for fila in aserciones:
            recorrido = trace(cx.driver, WS, fila["id"])
            print()
            print(f"  assertion {fila['id']} -> {len(recorrido)} fila(s)")
            print(json.dumps(recorrido, ensure_ascii=False, indent=2,
                             sort_keys=True))
            if not recorrido:
                print("  RECORRIDO VACIO: procedencia NO navegable para esta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

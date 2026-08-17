#!/usr/bin/env python3
"""Calibracion del gate de IDENTIDAD DURABLE: cada violacion tiene que enrojecer.

Un test que nunca ha estado rojo no es una medida, es una decoracion. Este
arnes reintroduce, una por una, las formas concretas del defecto que el carril
corrige y exige que la suite lo detecte.

NORMAS QUE ESTE ARNES CUMPLE (todas pagadas a golpes en este proyecto)
----------------------------------------------------------------------
* **Un proceso por mutacion.** Nada de mutar en caliente dentro del mismo
  interprete: un modulo ya importado seguiria en memoria y el resultado seria
  del arbol viejo.
* **`__pycache__` purgado y `PYTHONDONTWRITEBYTECODE=1`.** Un arbol Git limpio
  NO demuestra que el proceso este ejecutando ese arbol: CPython revalida el
  `.pyc` por mtime+tamano y puede seguir ejecutando codigo que ya no esta en
  disco.
* **Reversion verificada por HASH**, no por presencia de una cadena. Que el
  texto original vuelva a aparecer no demuestra que el fichero sea el original.
* **Se exige que la mutacion MUERDA**: si el texto a sustituir no aparece, es
  un fallo del arnes, no un exito del gate. Un arnes que sustituye 0 veces
  pasaria «verde» sin haber ejercido nada.
* **Suelo de plausibilidad**: la linea base tiene que ejecutar un numero minimo
  de pruebas. Una suite que colecciona 0 tests sale «sin fallos» y mentiria.

Uso: python3 artifacts/identidad-durable/calibrar.py
Salida: una linea RESUMEN al final (leerla: el codigo de salida por si solo no
basta para saber cuantos casos se ejercieron).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PROVEEDOR = RAIZ / "viewer" / "app" / "providers" / "neo4j_provider.py"
SUITE = "viewer/tests/test_identidad_durable.py"
#: La suite entera del visor tambien tiene que enrojecer con el defecto puesto:
#: si solo enrojeciera el fichero nuevo, el gate seria un apendice.
SUITE_AMPLIA = "viewer/tests/test_serializers.py"
#: Solo corren con `NEO4J_TEST_URI` definido (en CI, el job de Neo4j efimero).
SUITE_NEO4J = "viewer/tests/test_neo4j_integration_authz.py"
SUITE_CONTRATO = "viewer/tests/test_contrato_paneles_neo4j.py"
MINIMO_TESTS = 10


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def purgar_pycache() -> int:
    n = 0
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return n


def pytest(objetivos: list[str]) -> tuple[int, int, int]:
    """Ejecuta pytest en un proceso NUEVO. Devuelve (rc, pasados, fallados)."""
    entorno = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *objetivos, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=RAIZ, env=entorno, capture_output=True, text=True,
    )
    salida = r.stdout + r.stderr
    pasados = sum(int(m) for m in re.findall(r"(\d+) passed", salida))
    fallados = sum(int(m) for m in re.findall(r"(\d+) (?:failed|error)", salida))
    return r.returncode, pasados, fallados


#: (nombre, texto original, texto mutado, objetivos que deben enrojecer)
MUTACIONES = [
    (
        "El defecto original: `id` vuelve a ser el elementId",
        '        "id": props.get("entity_id"),\n        "entity_id": props.get("entity_id"),',
        '        "id": record_node.element_id,\n        "entity_id": props.get("entity_id"),',
        [SUITE],
    ),
    (
        "`entity_id` deja de viajar (la lista blanca lo olvida)",
        '        "entity_id": props.get("entity_id"),\n',
        "",
        [SUITE],
    ),
    (
        "El respaldo prohibido: el extremo de arista cae al elementId",
        '        return dict(nodo).get("entity_id")',
        '        return dict(nodo).get("entity_id") or nodo.element_id',
        [SUITE],
    ),
    (
        "El elementId se publica en una clave extra (puerta de atras de serialize_node)",
        '        "id": props.get("entity_id"),',
        '        "id": props.get("entity_id"),\n        "element_id": record_node.element_id,',
        [SUITE],
    ),
    (
        "`entity()` vuelve a resolver por identificador fisico",
        'query = "MATCH (n:Entity) WHERE n.entity_id = $id RETURN n"',
        'query = "MATCH (n:Entity) WHERE elementId(n) = $id RETURN n"',
        # Este solo lo puede ver Neo4j de verdad. Con `NEO4J_TEST_URI` definido
        # se EJERCE contra la suite de integracion; sin el se DECLARA y se
        # cuenta aparte. Lo que no se hace es fingir que se midio.
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "El extremo de arista vuelve a ser el elementId (Cypher)",
        "RETURN r, n.entity_id AS desde, m.entity_id AS hacia",
        "RETURN r, elementId(n) AS desde, elementId(m) AS hacia",
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    # --- MR4-MR7: los CUATRO filtros de identidad durable del proveedor.
    # Los cuatro sobrevivieron a la primera revision independiente: eran
    # codigo de produccion sin una sola prueba capaz de ponerse roja, que es
    # lo mismo que codigo que se puede borrar sin que nadie se entere. Ahora
    # los cubre la seccion 12 del contrato de paneles.
    (
        "MR4: `relations_for_entity` admite extremos sin entity_id",
        "WHERE n.entity_id = $id AND m.entity_id IS NOT NULL\n        RETURN r, n.entity_id AS desde, m.entity_id AS hacia",
        "WHERE n.entity_id = $id\n        RETURN r, n.entity_id AS desde, m.entity_id AS hacia",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MR5: `graph()/node_query` deja pasar nodos sin entity_id",
        "WHERE ($entity_type IS NULL OR n.entity_type = $entity_type)\n          AND n.entity_id IS NOT NULL\n        RETURN n",
        "WHERE ($entity_type IS NULL OR n.entity_type = $entity_type)\n        RETURN n",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MR6: `search()` deja de exigir entity_id",
        "          AND n.entity_id IS NOT NULL\n        RETURN n\n        LIMIT $limit",
        "        RETURN n\n        LIMIT $limit",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MR7: `graph()/rel_query` deja pasar aristas con extremos sin identidad",
        "          AND n.entity_id IS NOT NULL AND m.entity_id IS NOT NULL\n        RETURN n, r, m",
        "        RETURN n, r, m",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
]


def main() -> int:
    original = PROVEEDOR.read_text(encoding="utf-8")
    hash_original = sha256(PROVEEDOR)
    print(f"HEAD ................ {subprocess.run(['git','rev-parse','--short','HEAD'],cwd=RAIZ,capture_output=True,text=True).stdout.strip()}")
    print(f"proveedor sha256 .... {hash_original}")
    print(f"__pycache__ purgados  {purgar_pycache()}")

    rc, pasados, fallados = pytest([SUITE, SUITE_AMPLIA])
    print(f"\nLINEA BASE: rc={rc} pasados={pasados} fallados={fallados}")
    if rc != 0:
        print("ABORTA: la linea base no esta verde; no se puede calibrar nada.")
        return 2
    if pasados < MINIMO_TESTS:
        print(f"ABORTA: suelo de plausibilidad ({pasados} < {MINIMO_TESTS}).")
        return 2

    ejercidas = enrojecidas = declaradas = 0
    fallos: list[str] = []

    for nombre, viejo, nuevo, objetivos in MUTACIONES:
        if viejo not in original:
            fallos.append(f"ARNES ROTO: el texto de «{nombre}» no aparece en el proveedor")
            continue
        if not objetivos:
            declaradas += 1
            print(f"\n[declarada, no ejercida offline] {nombre}")
            continue

        ejercidas += 1
        PROVEEDOR.write_text(original.replace(viejo, nuevo, 1), encoding="utf-8")
        assert sha256(PROVEEDOR) != hash_original, "la mutacion no cambio el fichero"
        purgar_pycache()
        rc_m, pas_m, fal_m = pytest(objetivos)
        # Reversion INMEDIATA y verificada por hash, pase lo que pase.
        PROVEEDOR.write_text(original, encoding="utf-8")
        purgar_pycache()
        assert sha256(PROVEEDOR) == hash_original, "REVERSION FALLIDA (hash)"

        if rc_m != 0 and fal_m > 0:
            enrojecidas += 1
            print(f"\n[ROJO ok] {nombre}\n          {fal_m} prueba(s) lo detectan")
        else:
            fallos.append(f"NO ENROJECE: «{nombre}» (rc={rc_m}, fallados={fal_m})")
            print(f"\n[VERDE - FALLO DEL GATE] {nombre}")

    # Vuelta a verde sobre el arbol restaurado.
    purgar_pycache()
    rc_f, pas_f, _ = pytest([SUITE, SUITE_AMPLIA])
    print(f"\nVUELTA A VERDE: rc={rc_f} pasados={pas_f} sha256_ok={sha256(PROVEEDOR)==hash_original}")

    ok = not fallos and rc_f == 0 and pas_f == pasados
    for f in fallos:
        print("  " + f)
    print(
        f"\nRESUMEN: mutaciones={len(MUTACIONES)} ejercidas={ejercidas} "
        f"enrojecidas={enrojecidas} declaradas_sin_ejercer={declaradas} "
        f"base={pasados} final={pas_f} veredicto={'CALIBRADO' if ok else 'FALLO'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

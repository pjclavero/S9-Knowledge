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
#: Segunda superficie mutable: el DDL de las restricciones de unicidad. Vive en
#: el modulo de esquema del writer porque esa es la UNICA fuente normativa del
#: esquema del grafo; el arnes lo muta desde aqui para que la barrera 1 tenga
#: su control negativo igual que la barrera 2. Sin esto, «la restriccion
#: existe» seria un test que nunca ha estado rojo.
ESQUEMA = RAIZ / "data-engine" / "app" / "knowledge_v3" / "writer" / "schema.py"
#: Todos los ficheros que este arnes puede tocar. Se leen enteros ANTES de
#: mutar nada y se restauran verificando SHA-256.
MUTABLES = (PROVEEDOR, ESQUEMA)
SUITE = "viewer/tests/test_identidad_durable.py"
#: La suite entera del visor tambien tiene que enrojecer con el defecto puesto:
#: si solo enrojeciera el fichero nuevo, el gate seria un apendice.
SUITE_AMPLIA = "viewer/tests/test_serializers.py"
#: Solo corren con `NEO4J_TEST_URI` definido (en CI, el job de Neo4j efimero).
SUITE_NEO4J = "viewer/tests/test_neo4j_integration_authz.py"
SUITE_CONTRATO = "viewer/tests/test_contrato_paneles_neo4j.py"
MINIMO_TESTS = 10
#: SUELO DE LAS MUTACIONES, hermano de `MINIMO_TESTS`. Sin el, un arnes al que
#: alguien vaciara `MUTACIONES` -- o al que se le quedaran todas sin objetivo --
#: imprimiria `ejercidas=0 enrojecidas=0 declaradas_sin_ejercer=0` y
#: `veredicto=CALIBRADO`, saldria con rc=0 y estaria MUDO Y VERDE: exactamente
#: el fallo que este fichero existe para impedir, un nivel mas arriba.
MINIMO_MUTACIONES = 15
#: Las que no necesitan Neo4j. Se ejercen SIEMPRE, tambien en un portatil sin
#: contenedores, asi que este suelo se puede exigir incondicionalmente. El suelo
#: de las 12 (con base efimera) lo impone el paso de CI, que sabe si hay Neo4j.
MINIMO_EJERCIDAS = 4


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def purgar_pycache() -> int:
    n = 0
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return n


def pytest(objetivos: list[str], *, parar_en_el_primero: bool = False) -> tuple[int, int, int]:
    """Ejecuta pytest en un proceso NUEVO. Devuelve (rc, pasados, fallados).

    ``parar_en_el_primero`` (``-x``) SOLO se usa en las corridas CON MUTACION,
    nunca en la linea base ni en la vuelta a verde: ahi hace falta el recuento
    COMPLETO. Con el defecto puesto basta UNA prueba roja para responder la
    pregunta («¿hay alguna capaz de verlo?»), y ahorrarse el resto es lo que
    permite ejercer las mutaciones contra la base efimera dentro del CI.
    """
    entorno = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *objetivos, "-q", "--no-header", "-p", "no:cacheprovider",
         *(["-x"] if parar_en_el_primero else [])],
        cwd=RAIZ, env=entorno, capture_output=True, text=True,
    )
    salida = r.stdout + r.stderr
    pasados = sum(int(m) for m in re.findall(r"(\d+) passed", salida))
    fallados = sum(int(m) for m in re.findall(r"(\d+) (?:failed|error)", salida))
    return r.returncode, pasados, fallados


#: (nombre, FICHERO, texto original, texto mutado, objetivos que deben enrojecer)
MUTACIONES = [
    (
        "El defecto original: `id` vuelve a ser el elementId",
        PROVEEDOR,
        '        "id": props.get("entity_id"),\n        "entity_id": props.get("entity_id"),',
        '        "id": record_node.element_id,\n        "entity_id": props.get("entity_id"),',
        [SUITE],
    ),
    (
        "`entity_id` deja de viajar (la lista blanca lo olvida)",
        PROVEEDOR,
        '        "entity_id": props.get("entity_id"),\n',
        "",
        [SUITE],
    ),
    (
        "El respaldo prohibido: el extremo de arista cae al elementId",
        PROVEEDOR,
        '        return dict(nodo).get("entity_id")',
        '        return dict(nodo).get("entity_id") or nodo.element_id',
        [SUITE],
    ),
    (
        "El elementId se publica en una clave extra (puerta de atras de serialize_node)",
        PROVEEDOR,
        '        "id": props.get("entity_id"),',
        '        "id": props.get("entity_id"),\n        "element_id": record_node.element_id,',
        [SUITE],
    ),
    (
        "`entity()` vuelve a resolver por identificador fisico",
        PROVEEDOR,
        'query = "MATCH (n:Entity) WHERE n.entity_id = $id RETURN n LIMIT $sonda"',
        'query = "MATCH (n:Entity) WHERE elementId(n) = $id RETURN n LIMIT $sonda"',
        # Este solo lo puede ver Neo4j de verdad. Con `NEO4J_TEST_URI` definido
        # se EJERCE contra la suite de integracion; sin el se DECLARA y se
        # cuenta aparte. Lo que no se hace es fingir que se midio.
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "El extremo de arista vuelve a ser el elementId (Cypher)",
        PROVEEDOR,
        "RETURN r, n.entity_id AS desde, m.entity_id AS hacia",
        "RETURN r, elementId(n) AS desde, elementId(m) AS hacia",
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    # --- MR4-MR7: los CUATRO filtros de identidad durable del proveedor.
    # Los cuatro sobrevivieron a la primera revision independiente: eran
    # codigo de produccion sin una sola prueba capaz de ponerse roja, que es
    # lo mismo que codigo que se puede borrar sin que nadie se entere. Ahora
    # los cubre la seccion 12 del contrato de paneles.
    # MR4 son DOS mutaciones, no una: el filtro esta DUPLICADO (`out_query` e
    # `in_query`) y la primera version del arnes solo sembraba una arista
    # SALIENTE, asi que mutar `in_query` a solas dejaba la suite VERDE con el
    # defecto puesto (superviviente nº 13 de la revision independiente). El
    # ancla de cada una incluye su linea MATCH: sin ella los dos textos son
    # identicos y `replace(..., 1)` mutaria siempre el primero.
    (
        "MR4a: `relations_for_entity`/out_query admite extremos sin entity_id",
        PROVEEDOR,
        "MATCH (n:Entity)-[r]->(m:Entity)\n        WHERE n.entity_id = $id AND m.entity_id IS NOT NULL",
        "MATCH (n:Entity)-[r]->(m:Entity)\n        WHERE n.entity_id = $id",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MR4b: `relations_for_entity`/in_query admite extremos sin entity_id",
        PROVEEDOR,
        "MATCH (n:Entity)<-[r]-(m:Entity)\n        WHERE n.entity_id = $id AND m.entity_id IS NOT NULL",
        "MATCH (n:Entity)<-[r]-(m:Entity)\n        WHERE n.entity_id = $id",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MR5: `graph()/node_query` deja pasar nodos sin entity_id",
        PROVEEDOR,
        "WHERE ($entity_type IS NULL OR n.entity_type = $entity_type)\n          AND n.entity_id IS NOT NULL\n        RETURN n",
        "WHERE ($entity_type IS NULL OR n.entity_type = $entity_type)\n        RETURN n",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        # El ancla corta («AND n.entity_id IS NOT NULL / RETURN n / LIMIT
        # $limit») aparecia DOS veces: en `search()` y en `graph()/node_query`.
        # Acertaba por orden de fichero, no por construccion: si `search()` se
        # moviera por debajo de `graph()`, MR6 mutaria `node_query` y su rojo
        # seria PRESTADO de MR5. Se ancla con la linea del CONTAINS, que es
        # suya y de nadie mas. La asercion de unicidad de mas abajo impide que
        # esto vuelva a colarse.
        "MR6: `search()` deja de exigir entity_id",
        PROVEEDOR,
        "OR toLower(coalesce(n.description,'')) CONTAINS toLower($q))\n"
        "          AND n.entity_id IS NOT NULL\n        RETURN n\n        LIMIT $limit",
        "OR toLower(coalesce(n.description,'')) CONTAINS toLower($q))\n"
        "        RETURN n\n        LIMIT $limit",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MR7: `graph()/rel_query` deja pasar aristas con extremos sin identidad",
        PROVEEDOR,
        "          AND n.entity_id IS NOT NULL AND m.entity_id IS NOT NULL\n        RETURN n, r, m",
        "        RETURN n, r, m",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    # --- MR8: la QUINTA VIA. `workspaces()` es el unico camino que
    # `PolicyFilteredProvider` no recalcula (solo intersecta con
    # `allowed_workspaces`), asi que sin exigencia EN LA CONSULTA un workspace
    # sin identidad durable se ofrece en el selector y se abre vacio.
    (
        "MR8: `workspaces()` deja de exigir entity_id (selector lleno, todo vacio)",
        PROVEEDOR,
        "        WHERE n.workspace IS NOT NULL AND n.entity_id IS NOT NULL\n        RETURN DISTINCT n.workspace AS workspace",
        "        WHERE n.workspace IS NOT NULL\n        RETURN DISTINCT n.workspace AS workspace",
        [SUITE_CONTRATO] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    # --- MU1-MU3: UNICIDAD DURABLE. Las dos barreras, cada una con su
    # ablacion. La regla que defienden es dura: para cada URL durable, 0 o 1
    # objetos, NUNCA 2+. Si estas tres no pudieran ponerse rojas, el carril
    # entero seria una declaracion.
    (
        "MU1: `entity()` vuelve al desempate implicito (el primero que devuelva Neo4j)",
        PROVEEDOR,
        """        if len(records) > 1:
            # FAIL-CLOSED. No se escoge ninguno y se GRITA""",
        """        if False:  # MUTACION: el fail-closed desaparece
            # FAIL-CLOSED. No se escoge ninguno y se GRITA""",
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        "MU2: `relations_for_entity()` sirve la UNION de dos anclas ambiguas",
        PROVEEDOR,
        "        if self._identidad_ambigua(entity_id):\n            return [], []",
        "        if False and self._identidad_ambigua(entity_id):\n            return [], []",
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
    (
        # ABLACION DE LA BARRERA 1, en el fichero del ESQUEMA. Es la unica
        # mutacion que no toca el proveedor, y por eso el arnes admite varios
        # ficheros: una barrera cuya desaparicion no cambia ningun resultado no
        # se puede cobrar como defensa.
        "MU3: la restriccion de unicidad deja de caer sobre la clave derivada",
        ESQUEMA,
        '"REQUIRE (n.workspace, n.entity_id, n.partida_id) IS UNIQUE"\n)\n\n#: Gemela',
        '"REQUIRE (n.entity_id) IS UNIQUE"\n)\n\n#: Gemela',
        [SUITE_NEO4J] if os.environ.get("NEO4J_TEST_URI") else [],
    ),
]


def main() -> int:
    # Se leen TODOS los ficheros mutables antes de tocar nada, con su hash. La
    # reversion se verifica contra estos hashes, no contra la presencia de una
    # cadena: que el texto original reaparezca no demuestra que el fichero sea
    # el original.
    original_de = {f: f.read_text(encoding="utf-8") for f in MUTABLES}
    hash_de = {f: sha256(f) for f in MUTABLES}
    print(f"HEAD ................ {subprocess.run(['git','rev-parse','--short','HEAD'],cwd=RAIZ,capture_output=True,text=True).stdout.strip()}")
    for f in MUTABLES:
        print(f"sha256 {f.relative_to(RAIZ)} = {hash_de[f]}")
    print(f"__pycache__ purgados  {purgar_pycache()}")

    # SUELO DEL PROPIO ARNES, antes de tocar nada. Un arnes sin mutaciones no
    # es un arnes verde: es un arnes mudo.
    if len(MUTACIONES) < MINIMO_MUTACIONES:
        print(f"ABORTA: suelo de mutaciones ({len(MUTACIONES)} < {MINIMO_MUTACIONES}): "
              "un arnes sin casos saldria «sin fallos» sin haber ejercido nada.")
        return 2

    # UNICIDAD DE LAS ANCLAS. Una ancla que aparece dos veces muta la PRIMERA
    # por orden de fichero, no la que dice su nombre: el dia que dos consultas
    # se intercambien de sitio, esa mutacion enrojeceria con el rojo PRESTADO de
    # su vecina y nadie se enteraria. Afirmarlo aqui vale mas que revisarlo a
    # mano hoy: la comprobacion viaja con el fichero.
    repetidas = [
        f"«{nombre}» en {fichero.name}: {original_de[fichero].count(viejo)} ocurrencias"
        for nombre, fichero, viejo, _, _ in MUTACIONES
        if original_de[fichero].count(viejo) != 1
    ]
    if repetidas:
        print("ABORTA: hay anclas que no son unicas (rojo prestado posible):")
        for r in repetidas:
            print("  " + r)
        return 2

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

    for nombre, fichero, viejo, nuevo, objetivos in MUTACIONES:
        if viejo not in original_de[fichero]:
            fallos.append(
                f"ARNES ROTO: el texto de «{nombre}» no aparece en {fichero.name}"
            )
            continue
        if not objetivos:
            declaradas += 1
            print(f"\n[declarada, no ejercida offline] {nombre}")
            continue

        ejercidas += 1
        fichero.write_text(
            original_de[fichero].replace(viejo, nuevo, 1), encoding="utf-8"
        )
        assert sha256(fichero) != hash_de[fichero], "la mutacion no cambio el fichero"
        purgar_pycache()
        rc_m, pas_m, fal_m = pytest(objetivos, parar_en_el_primero=True)
        # Reversion INMEDIATA y verificada por hash, pase lo que pase.
        fichero.write_text(original_de[fichero], encoding="utf-8")
        purgar_pycache()
        assert sha256(fichero) == hash_de[fichero], "REVERSION FALLIDA (hash)"

        if rc_m != 0 and fal_m > 0:
            enrojecidas += 1
            print(f"\n[ROJO ok] {nombre}\n          {fal_m} prueba(s) lo detectan")
        else:
            fallos.append(f"NO ENROJECE: «{nombre}» (rc={rc_m}, fallados={fal_m})")
            print(f"\n[VERDE - FALLO DEL GATE] {nombre}")

    # Vuelta a verde sobre el arbol restaurado.
    purgar_pycache()
    rc_f, pas_f, _ = pytest([SUITE, SUITE_AMPLIA])
    todos_ok = all(sha256(f) == hash_de[f] for f in MUTABLES)
    print(f"\nVUELTA A VERDE: rc={rc_f} pasados={pas_f} sha256_ok={todos_ok}")
    if not todos_ok:
        fallos.append("REVERSION FALLIDA: algun fichero mutable no volvio a su hash")

    # SUELO DE LO EJERCIDO. `fallos` esta vacio tanto si todas enrojecieron
    # como si NO SE EJERCIO NINGUNA (todas declaradas, o la lista vaciada). Sin
    # esta comprobacion el veredicto CALIBRADO seria compatible con no haber
    # medido nada.
    if ejercidas < MINIMO_EJERCIDAS:
        fallos.append(
            f"SUELO DE EJERCIDAS: {ejercidas} < {MINIMO_EJERCIDAS}. Las mutaciones "
            "que no necesitan Neo4j se ejercen SIEMPRE; si no se ejercio ninguna, "
            "este arnes no ha medido nada."
        )
    if ejercidas + declaradas != len(MUTACIONES):
        fallos.append(
            f"CONTABILIDAD: {ejercidas}+{declaradas} != {len(MUTACIONES)}: hay "
            "mutaciones que se han perdido por el camino."
        )

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

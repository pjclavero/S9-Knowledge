# -*- coding: utf-8 -*-
"""CARRIL 9 -- la herencia juego->partida en ESCRITURA, no solo en lectura.

EL DEFECTO
----------
`cypher._scoped_match` exige IGUALDAD EXACTA de ambito; `cypher._visible_predicate`
implementa "capa juego + partida propia". `executor` usaba el PRIMERO como
precondicion de una operacion de RELACION, cuyo objetivo NO se muta: solo se
referencia. Resultado medido en `escenario_carril7.py`: el plan de `partida:A`
salia aprobado con las seis validaciones en PASS y moria en
`EXEC_SCOPE_MISMATCH` al referenciar `entity:sela-marrec` (capa juego).

CUAL DE LAS DOS LECTURAS ERA LA CORRECTA: LAS DOS, EN SU SITIO
--------------------------------------------------------------
No se relaja `_scoped_match`. Responde a "¿donde OPERO?" y ahi la igualdad
exacta es el Invariante 2 (docs/v3/49 §2.4) y el "lore intacto" (§2.5): una
partida NO cierra la vigencia de un hecho de capa juego. Lo que estaba mal era
el PUNTO DE LLAMADA: aplicar esa regla a una REFERENCIA. El ambito de una
referencia es el de VISIBILIDAD (docs/v3/49 §0: "workspace = juego:X AND
(partida_id IS NULL OR partida_id = partida:Y)"), el mismo que la propia
`create_relation` ya exige a sus dos extremos.

LA MATRIZ (REFERENCIA), CADA CASILLA OBSERVADA AQUI
---------------------------------------------------
    dato JUEGO     + contexto JUEGO     -> ALLOW
    dato JUEGO     + contexto PARTIDA A -> ALLOW   <- lo que estaba roto
    dato PARTIDA A + contexto PARTIDA A -> ALLOW
    dato PARTIDA A + contexto PARTIDA B -> DENY
    dato PARTIDA A + contexto JUEGO     -> DENY
    ambito ausente/incoherente          -> DENY (admision, intacta)

QUE PUEDE AFIRMAR ESTE FICHERO Y QUE NO (carril 10B, MEDIDO)
------------------------------------------------------------
Estas ocho pruebas corren sobre `FakeDriver`, un DOBLE. El doble honra la
FORMA que el Cypher declara, pero no EJECUTA el predicado: rederiva la
visibilidad por su cuenta. De ahi el reparto de autoridad:

    doble offline (este fichero) -> CONTRATO, FORMA y COMPOSICION
    Neo4j real                   -> SEMANTICA EFECTIVA del ambito
                                    y AISLAMIENTO A/B entre partidas

La version anterior de esta cabecera afirmaba que quitar la discriminacion
A/B --devolver visible incondicionalmente en `cypher.read_entity_state_visible`--
ponia ROJO a `test_desde_A_una_entidad_de_B_sigue_siendo_SCOPE_MISMATCH`.
ESO ERA FALSO y se retira: aplicada esa mutacion, ese testigo sigue en VERDE
aqui. Un doble que reimplementa el predicado no puede notar que el predicado
ha desaparecido. (Las tres pruebas de este fichero que si enrojecen con esa
mutacion lo hacen por otras casillas de la matriz, no por la discriminacion
A/B: contarlas como cobertura del aislamiento seria un rojo prestado.)

Donde SI se mide, y de forma obligatoria: `test_knowledge_v3_writer_neo4j_real
.py::test_carril9_desde_A_una_entidad_de_B_sigue_abortando`, contra la base
efimera del paso "Writer y E2E V3 contra Neo4j REAL" de `test-data-engine`,
que exige ese nombre como PASSED y trata `skipped` como ROJO. Calibrado:
verde sin mutacion, ROJO con ella.

NINGUN informe puede decir "el test offline demuestra la separacion A/B".
"""
from __future__ import annotations

from test_knowledge_v3_writer import (  # noqa: E402
    HASH_A,
    FakeDriver,
    apply_request,
    make_plan,
    make_writer,
    op_link,
    op_supersede,
    partida_scope,
)
from knowledge_v3.writer import codes  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_ABORTED, OUTCOME_APPLIED  # noqa: E402

PARTIDA_A = "partida:brumal-01"
PARTIDA_B = "partida:brumal-OTRA"
SUJETO = "entity:sela-marrec"
OBJETO = "entity:cofradia-ambar"


def _nodo(partida_id):
    return {"version": 3, "state_hash": HASH_A["value"], "partida_id": partida_id}


def _correr(*, contexto, sujeto_en, objeto_en=None):
    """Un plan que ENLAZA (no muta) `SUJETO` -> `OBJETO`, en `contexto`."""
    objeto_en = sujeto_en if objeto_en is None else objeto_en
    if contexto is None:
        plan = make_plan(operations=[op_link("op:0001", "decision:0001", SUJETO, OBJETO)])
    else:
        plan = make_plan(
            operations=[op_link("op:0001", "decision:0001", SUJETO, OBJETO)],
            partida_id=contexto,
            scope=partida_scope(contexto),
        )
    driver = FakeDriver(nodes={
        ("entity", SUJETO): _nodo(sujeto_en),
        ("entity", OBJETO): _nodo(objeto_en),
    })
    return make_writer(driver).write(plan, apply_request(plan)), driver


# ==========================================================================
# La matriz de REFERENCIA
# ==========================================================================
def test_dato_juego_contexto_juego_enlaza():
    """Casilla 1. Un plan de capa juego enlaza capa juego. Ya funcionaba."""
    result, _ = _correr(contexto=None, sujeto_en=None)
    assert result.outcome == OUTCOME_APPLIED, result.codes


def test_dato_juego_contexto_partida_A_enlaza():
    """Casilla 2 -- LA QUE ESTABA ROTA.

    Es la reproduccion offline del bloqueo de `escenario_carril7.py`: el
    sujeto es de capa juego, el plan declara `partida:A`. Antes del arreglo
    esto salia `ABORTED` / `EXEC_SCOPE_MISMATCH` con el plan aprobado.
    """
    result, driver = _correr(contexto=PARTIDA_A, sujeto_en=None)
    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert codes.EXEC_SCOPE_MISMATCH not in result.codes
    # Y la ESCRITURA sigue siendo de la partida: la herencia es de lectura
    # del extremo, no de propiedad de la arista.
    creada = [p for q, p in driver.writes if "CREATE (a)-[r:" in q]
    assert len(creada) == 1, driver.writes
    assert creada[0]["props"]["partida_id"] == PARTIDA_A


def test_dato_partida_A_contexto_partida_A_enlaza():
    """Casilla 3. Lo propio de la partida sigue enlazando."""
    result, _ = _correr(contexto=PARTIDA_A, sujeto_en=PARTIDA_A)
    assert result.outcome == OUTCOME_APPLIED, result.codes


def test_desde_A_una_entidad_de_B_sigue_siendo_SCOPE_MISMATCH():
    """Casilla 4 -- RATIFICADA, no se toca. Es la MUTACION NEGATIVA.

    El arreglo no ensancha `partida:A` hacia `partida:B`: la visibilidad
    incluye la capa juego y la partida PROPIA, nunca otra. Quitar esta
    discriminacion tiene que poner rojo justo aqui.
    """
    result, _ = _correr(contexto=PARTIDA_A, sujeto_en=PARTIDA_B, objeto_en=PARTIDA_B)
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_SCOPE_MISMATCH in result.codes


def test_desde_capa_juego_una_entidad_de_partida_NO_es_visible():
    """Casilla 5. Direccion UNICA (docs/v3/49 §2.3): la herencia baja de juego
    a partida, jamas sube. Y es tambien la garantia de que el ambito AUSENTE no
    se convierte en un comodin: `partida_id=None` es capa juego y solo ve capa
    juego, exactamente como antes."""
    result, _ = _correr(contexto=None, sujeto_en=PARTIDA_A, objeto_en=PARTIDA_A)
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_SCOPE_MISMATCH in result.codes


# ==========================================================================
# Lo que el arreglo NO toca
# ==========================================================================
def test_una_partida_sigue_sin_poder_superseder_un_hecho_de_capa_juego():
    """La otra dimension, INTACTA: `_scoped_match` sigue mandando cuando la
    operacion MUTA el objetivo. Si esta prueba se pusiera verde, el arreglo
    habria abierto la escritura sobre el lore compartido (docs/v3/49 §2.5,
    "el lore intacto"), que es exactamente lo que no debe pasar."""
    plan = make_plan(
        operations=[op_supersede("op:0001", "decision:0001", "assertion:lore")],
        partida_id=PARTIDA_A,
        scope=partida_scope(PARTIDA_A),
    )
    driver = FakeDriver(nodes={
        ("assertion", "assertion:lore"): {
            "version": 2, "state_hash": "b" * 64, "partida_id": None,
        },
    })
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_SCOPE_MISMATCH in result.codes


def test_la_precondicion_de_una_referencia_sigue_comprobando_version():
    """El arreglo cambia el AMBITO de la lectura, no el control optimista de
    concurrencia: un `expected_version` que no casa sigue abortando."""
    plan = make_plan(
        operations=[op_link("op:0001", "decision:0001", SUJETO, OBJETO, version=99)],
        partida_id=PARTIDA_A,
        scope=partida_scope(PARTIDA_A),
    )
    driver = FakeDriver(nodes={
        ("entity", SUJETO): _nodo(None),
        ("entity", OBJETO): _nodo(None),
    })
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_VERSION_MISMATCH in result.codes


def test_una_entidad_inexistente_sigue_siendo_TARGET_MISSING_no_SCOPE_MISMATCH():
    """La distincion MISSING/SCOPE_MISMATCH sobrevive al cambio de ambito."""
    plan = make_plan(
        operations=[op_link("op:0001", "decision:0001", SUJETO, OBJETO)],
        partida_id=PARTIDA_A,
        scope=partida_scope(PARTIDA_A),
    )
    driver = FakeDriver(nodes={})
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_MISSING in result.codes
    assert codes.EXEC_SCOPE_MISMATCH not in result.codes

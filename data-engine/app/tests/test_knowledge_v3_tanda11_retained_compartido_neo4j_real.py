# -*- coding: utf-8 -*-
"""`retained > 0`: la rama que NINGUNA asercion del repositorio ejercia.

QUE FALTABA, Y POR QUE IMPORTA
------------------------------
`cli_rollback.describe` tiene una rama --hoy `cli_rollback.py:471`-- que solo
se imprime cuando `hechos["retained"]` no es cero:

    «N elementos suyos se CONSERVAN a proposito porque siguen sostenidos por
     estado vivo (ver 'retained').»

Medido sobre el arbol: ni una sola asercion del repositorio llegaba a esa rama
con `retained > 0`. Habia pruebas del canal `retained_*` del INFORME de purga
(`equipo5b`, `rollback_procedencia`) y pruebas de la frase con `retained == 0`,
pero ninguna recorria el camino entero --mando -> informe -> prosa-- con algo
CONSERVADO de verdad.

Eso importa porque la tanda 11 retira de `tanda4` la frase vieja («No queda
nada de esa operacion en el grafo») apoyandose precisamente en que puede haber
material conservado. Retirar una expectativa apoyandose en una rama que ningun
test recorre seria repetir el patron que se acaba de arreglar: una afirmacion
sostenida por nadie. Aqui se fabrica la prueba que faltaba.

COMO SE FABRICA EL CASO, Y POR QUE ASI
--------------------------------------
Por la RUTA DE PRODUCTO (`apply.apply_v3`, que es la definicion de «aplicar
V3») y con Neo4j real. **Ni una linea de Cypher de escritura**: todo lo que
hay en el grafo lo escribio el producto. Las consultas de este fichero son de
LECTURA y solo sirven para medir.

La forma del caso NO es arbitraria: la impone la semantica de PROPIEDAD del
producto, y conviene dejarla escrita porque es contraintuitiva.

* El radio de la purga con `scope: "apply"` se DESCUBRE en el grafo: son los
  nodos que llevan la marca de creacion de ESE apply
  (`rollback_provenance.execute_purge`).
* La marca es de CREACION, no de uso: lo REUTILIZADO conserva la marca de
  quien lo creo (`provenance.persist_provenance`, y medido en `equipo5b`).

Consecuencia: un apply que se limita a REUTILIZAR una evidencia ajena no la
tiene en su radio, y revertirlo da `retained == 0` -- no porque no haya nada
compartido, sino porque lo compartido no es suyo. Para que `retained > 0` hace
falta que el apply revertido sea el DUENO de la evidencia y que alguien
POSTERIOR y vivo la cite. De ahi las tres corridas:

    apply A  -> crea la fuente, el episodio y su evidencia (P)
    apply B  -> REUTILIZA la fuente y el episodio de A (parte de P) y crea DOS
                evidencias suyas: una que luego se comparte y otra exclusiva
    apply C  -> REUTILIZA la evidencia compartida de B y la cita desde una
                asercion VIVA que B no creo
    rollback B -> la compartida PERMANECE y se DECLARA (`retained > 0`)
                  la exclusiva DESAPARECE
                  clean, residues == 0, y la prosa NO dice «No queda nada»

COMO SE MIDE, PARA QUE EL VERDE SIGNIFIQUE ALGO
-----------------------------------------------
* UNA CONSULTA POR COSA CONTADA. Dos `MATCH` sueltos en la misma consulta dan
  producto cartesiano y, con cualquier conjunto vacio, CERO filas: un verde
  que no mide nada.
* Identidad DURABLE (`fragment_id`, `entity_id`, `assertion_id`), nunca
  `elementId`, que no es identidad de nada y cambia entre bases.
* El conjunto de partida se comprueba NO VACIO antes de comparar. Un rojo por
  grafo vacio no calibra nada, y un verde por grafo vacio no mide nada.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Neo4j real: activar con S9K_WRITER_NEO4J_REAL=1",
)

from knowledge_v3.writer import apply as apply_mod  # noqa: E402
from knowledge_v3.writer import cli_rollback, exit_codes  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: E402

from test_knowledge_v3_estado_durable_neo4j_real import (  # noqa: E402,F401
    neo4j_driver,
    neo4j_driver_efimero,
    probe,
    writer,
)
from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401
    WORKSPACE,
    GraphProbe,
    apply_request,
    create_assertion,
    create_entity,
    make_plan,
)

# --- Material de procedencia. Documentos, no Cypher. -----------------------
FUENTE = "src:tanda11:compartida"
EPISODIO = "ep:tanda11:1"

#: Los `evidence_fragment_ids` que el arnes estampa salen del `decision_id`
#: (`fragment:{decision_id}`), asi que el nombre de la decision ES el nombre
#: del fragmento. Se escriben aqui juntos para que no puedan separarse.
D_A = "decision:tanda11:a"
D_COMPARTIDA = "decision:tanda11:compartida"
D_SOLO_B = "decision:tanda11:solo-b"

F_A = f"fragment:{D_A}"
F_COMPARTIDA = f"fragment:{D_COMPARTIDA}"
F_SOLO_B = f"fragment:{D_SOLO_B}"


def _asset() -> dict:
    return {"source_asset_id": FUENTE, "title": "fuente de la tanda 11"}


def _episodio() -> dict:
    return {"episode_id": EPISODIO, "source_asset_id": FUENTE, "ordinal": 1}


def _fragmento(fid: str) -> dict:
    return {"fragment_id": fid, "episode_id": EPISODIO, "text": f"literal de {fid}"}


def _aplicar(writer, driver, plan: dict, bundle) -> Any:
    """UNA corrida por la ruta canonica. `apply_v3` es la puerta, no el writer."""
    salida = apply_mod.apply_v3(
        plan, apply_request(plan), writer=writer, provenance=bundle, driver=driver
    )
    resultado = salida.write_result
    assert resultado.outcome == OUTCOME_APPLIED, resultado.codes
    assert salida.provenance_result is not None, (
        "el apply no persistio procedencia: sin cadena no hay nada que conservar"
    )
    assert resultado.rollback is not None, "apply sin documento de reversion"
    return salida


def _plan_a() -> dict:
    return make_plan(
        [
            create_entity("op:a1", "entity:a1", "A1", decision_id=D_A),
            create_entity("op:a2", "entity:a2", "A2", decision_id=D_A),
            create_assertion("op:aa", "assertion:a", "entity:a1", "entity:a2", D_A),
        ],
        plan_id="plan:tanda11:a",
    )


def _plan_b() -> dict:
    return make_plan(
        [
            create_entity("op:b1", "entity:b1", "B1", decision_id=D_COMPARTIDA),
            create_entity("op:b2", "entity:b2", "B2", decision_id=D_COMPARTIDA),
            create_assertion(
                "op:bc", "assertion:b-compartida", "entity:b1", "entity:b2",
                D_COMPARTIDA,
            ),
            create_entity("op:b3", "entity:b3", "B3", decision_id=D_SOLO_B),
            create_entity("op:b4", "entity:b4", "B4", decision_id=D_SOLO_B),
            create_assertion(
                "op:bs", "assertion:b-solo", "entity:b3", "entity:b4", D_SOLO_B
            ),
        ],
        plan_id="plan:tanda11:b",
    )


def _plan_c() -> dict:
    return make_plan(
        [
            create_entity("op:c1", "entity:c1", "C1", decision_id=D_COMPARTIDA),
            create_entity("op:c2", "entity:c2", "C2", decision_id=D_COMPARTIDA),
            create_assertion(
                "op:cc", "assertion:c", "entity:c1", "entity:c2", D_COMPARTIDA
            ),
        ],
        plan_id="plan:tanda11:c",
    )


# --- Medida. Una consulta por cosa contada, por identidad durable. ---------
def _fragmentos(probe: GraphProbe) -> set[str]:
    filas = probe.run(
        "MATCH (n:V3Evidence {workspace:$ws}) RETURN n.fragment_id AS id",
        {"ws": WORKSPACE},
    )
    return {f["id"] for f in filas if f["id"]}


def _entidades(probe: GraphProbe) -> set[str]:
    filas = probe.run(
        "MATCH (n:V3Entity {workspace:$ws}) RETURN n.entity_id AS id",
        {"ws": WORKSPACE},
    )
    return {f["id"] for f in filas if f["id"]}


def _aserciones(probe: GraphProbe) -> set[str]:
    filas = probe.run(
        "MATCH (n:V3Assertion {workspace:$ws}) RETURN n.assertion_id AS id",
        {"ws": WORKSPACE},
    )
    return {f["id"] for f in filas if f["id"]}


def _marca_de_creacion(probe: GraphProbe, fragment_id: str) -> Any:
    """El `apply_id` que lleva un fragmento. Es la marca de QUIEN LO CREO."""
    filas = probe.run(
        "MATCH (n:V3Evidence {workspace:$ws, fragment_id:$fid}) "
        "RETURN n.apply_id AS marca",
        {"ws": WORKSPACE, "fid": fragment_id},
    )
    assert filas, f"conjunto vacio: {fragment_id} no esta en el grafo"
    return filas[0]["marca"]


def _mando_rollback(driver, salida, tmp_path: Path, capsys, *, nombre: str):
    """El mando de operador, tal cual, sobre el documento de ese apply."""
    doc = tmp_path / f"rollback-{nombre}.json"
    doc.write_text(
        json.dumps(salida.write_result.rollback.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    argv = [
        str(doc), "--workspace", WORKSPACE, "--operator", "tanda11",
        "--audit-log", str(tmp_path / f"audit-{nombre}.jsonl"), "--execute",
    ]
    rc = cli_rollback.main(
        argv,
        driver_factory=lambda: driver,
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WORKSPACE},
    )
    return rc, json.loads(capsys.readouterr().out)


# ===========================================================================
# LA PRUEBA QUE FALTABA: `retained > 0` DE VERDAD
# ===========================================================================
def test_lo_compartido_se_conserva_se_declara_y_la_prosa_lo_dice(
    writer, probe, tmp_path, capsys
):
    """`retained > 0` por la ruta de producto, medido en el grafo y en la prosa.

    La rama de `cli_rollback.py:471` se recorre aqui, y se recorre con material
    conservado de verdad: no con un `retained` fabricado a mano.
    """
    driver = probe.driver
    assert _fragmentos(probe) == set(), "el grafo de partida no estaba limpio"

    # --- A crea la procedencia (P) ---------------------------------------
    _aplicar(writer, driver, _plan_a(), apply_mod.ProvenanceBundle.of(
        source_asset=_asset(), episodes=[_episodio()], fragments=[_fragmento(F_A)]
    ))

    # --- B REUTILIZA parte de P y crea evidencia suya ---------------------
    b = _aplicar(writer, driver, _plan_b(), apply_mod.ProvenanceBundle.of(
        source_asset=_asset(),        # REUTILIZA la fuente de A
        episodes=[_episodio()],       # REUTILIZA el episodio de A
        fragments=[_fragmento(F_COMPARTIDA), _fragmento(F_SOLO_B)],  # suyas
    ))
    # La reutilizacion se OBSERVA, no se presume: lo reutilizado conserva la
    # marca de A, y lo nuevo lleva la de B. Sin esta asimetria el caso no seria
    # el que dice ser.
    marca_b = b.apply_id
    assert marca_b, "sin marca de propiedad el barrido no tendria radio"
    assert _marca_de_creacion(probe, F_COMPARTIDA) == marca_b
    assert _marca_de_creacion(probe, F_SOLO_B) == marca_b
    assert _marca_de_creacion(probe, F_A) != marca_b, (
        "el fragmento de A cambio de dueno al reutilizarse la fuente"
    )

    # --- C REUTILIZA la evidencia de B y la cita desde una asercion viva ---
    _aplicar(writer, driver, _plan_c(), apply_mod.ProvenanceBundle.of(
        source_asset=_asset(),
        episodes=[_episodio()],
        fragments=[_fragmento(F_COMPARTIDA)],   # REUTILIZA: no crea nodo nuevo
    ))
    assert _marca_de_creacion(probe, F_COMPARTIDA) == marca_b, (
        "C se apropio de la evidencia que reutilizo"
    )

    # El conjunto de partida NO esta vacio: sin esto, lo de abajo no mide nada.
    antes_fragmentos = _fragmentos(probe)
    antes_entidades = _entidades(probe)
    assert antes_fragmentos == {F_A, F_COMPARTIDA, F_SOLO_B}, antes_fragmentos
    assert {"entity:b1", "entity:b3", "entity:c1"} <= antes_entidades, antes_entidades
    assert "assertion:c" in _aserciones(probe)

    # --- rollback de B ----------------------------------------------------
    rc, acta = _mando_rollback(driver, b, tmp_path, capsys, nombre="b")

    # 1. El desenlace es LIMPIO, y lo conservado no lo ensucia.
    assert rc == exit_codes.EXIT_OK, acta
    assert acta["outcome"] == cli_rollback.OUTCOME_ROLLED_BACK, acta
    assert acta["code"] == "CLI_ROLLBACK_COMPLETE", acta
    assert acta["report"]["clean"] is True, acta["report"]
    assert acta["report"]["residues"] == [], acta["report"]["residues"]
    assert acta["report"]["unrecoverable"] == [], acta["report"]["unrecoverable"]

    # 2. `retained > 0`. LA RAMA QUE NADIE EJERCIA.
    retenidos = acta["report"]["retained"]
    assert len(retenidos) > 0, ("retained vacio: este caso no llega a la rama "
                                "que la prueba existe para ejercer")
    assert acta["hechos"]["retained"] == len(retenidos), acta["hechos"]
    assert any(F_COMPARTIDA in linea for linea in retenidos), retenidos
    # Y se declara CON su sosten. No basta con que algo sobreviva: el informe
    # tiene que decir QUIEN lo sostiene. Si el censo dejara de ver las
    # referencias vivas, la evidencia podria sobrevivir igualmente --el
    # `DELETE` la rechazaria por su propia guarda-- y se declararia con la
    # lista de referentes VACIA. Eso seria conservarla por accidente, no a
    # proposito, y esta linea lo distingue.
    assert any("assertion:c" in linea for linea in retenidos), retenidos

    # OBSERVACION MEDIDA, no defecto que esta tanda arregle: la cifra cuenta
    # DECLARACIONES, no elementos distintos. Un mismo fragmento lo declaran
    # dos instrucciones de purga (`op:bc` y `provenance:sweep`), de modo que
    # `retained == 2` con UN solo elemento conservado. Se fija aqui tal como
    # se observa para que un cambio de criterio no pase inadvertido; cambiarlo
    # seria tocar producto, que no es lo que este PR hace.
    distintos = {f for f in (F_A, F_COMPARTIDA, F_SOLO_B)
                 if any(f in linea for linea in retenidos)}
    assert distintos == {F_COMPARTIDA}, distintos
    assert len(retenidos) >= len(distintos), (retenidos, distintos)

    # 3. La PROSA declara la cifra, y NO afirma la ausencia que seria falsa.
    frase = acta["human"]
    assert "No queda nada de esa operacion en el grafo" not in frase, frase
    assert f"{len(retenidos)} elementos suyos se CONSERVAN a proposito" in frase, frase
    assert "No queda ningun residuo de esta operacion en el grafo." in frase, frase

    # 4. EL GRAFO. Lo compartido permanece; lo exclusivo desaparece.
    despues = _fragmentos(probe)
    assert F_COMPARTIDA in despues, (
        "la evidencia compartida se borro: el rollback se llevo por delante lo "
        "que una asercion viva sostiene"
    )
    assert F_SOLO_B not in despues, (
        "la evidencia EXCLUSIVA de B sigue en el grafo tras revertir B"
    )
    assert F_A in despues, "el rollback de B se llevo procedencia de A"

    entidades = _entidades(probe)
    assert {"entity:b1", "entity:b2", "entity:b3", "entity:b4"}.isdisjoint(entidades), (
        f"entidades de B vivas tras revertir B: {sorted(entidades)}"
    )
    assert {"entity:a1", "entity:c1"} <= entidades, sorted(entidades)

    aserciones = _aserciones(probe)
    assert "assertion:b-compartida" not in aserciones, sorted(aserciones)
    assert "assertion:b-solo" not in aserciones, sorted(aserciones)
    assert {"assertion:a", "assertion:c"} <= aserciones, sorted(aserciones)


# ===========================================================================
# EL CONTROL COMPLEMENTARIO: sin compartidos, `retained == 0`
# ===========================================================================
def test_sin_compartidos_no_se_conserva_nada_y_la_prosa_no_lo_finge(
    writer, probe, tmp_path, capsys
):
    """El otro lado de la misma rama.

    Sin nadie vivo que sostenga la evidencia, `retained` es CERO y la prosa
    puede --y debe-- no declarar ninguna cifra de conservados. Es lo que hace
    que la prueba de arriba signifique algo: si la frase saliera siempre, no
    estaria midiendo la conservacion sino la existencia de un `if`.
    """
    driver = probe.driver
    assert _fragmentos(probe) == set(), "el grafo de partida no estaba limpio"

    a = _aplicar(writer, driver, _plan_a(), apply_mod.ProvenanceBundle.of(
        source_asset=_asset(), episodes=[_episodio()], fragments=[_fragmento(F_A)]
    ))
    # No vacio ANTES: si lo estuviera, el cero de despues no diria nada.
    assert _fragmentos(probe) == {F_A}, _fragmentos(probe)
    assert "entity:a1" in _entidades(probe)

    rc, acta = _mando_rollback(driver, a, tmp_path, capsys, nombre="a")

    assert rc == exit_codes.EXIT_OK, acta
    assert acta["outcome"] == cli_rollback.OUTCOME_ROLLED_BACK, acta
    assert acta["report"]["clean"] is True, acta["report"]
    assert acta["report"]["residues"] == [], acta["report"]["residues"]

    assert acta["report"]["retained"] == [], acta["report"]["retained"]
    assert acta["hechos"]["retained"] == 0, acta["hechos"]

    frase = acta["human"]
    assert "se CONSERVAN a proposito" not in frase, frase
    assert "No queda nada de esa operacion en el grafo" not in frase, frase
    assert "No queda ningun residuo de esta operacion en el grafo." in frase, frase

    # Y el grafo lo sostiene: no queda evidencia de ese apply.
    assert _fragmentos(probe) == set(), _fragmentos(probe)
    assert "entity:a1" not in _entidades(probe)

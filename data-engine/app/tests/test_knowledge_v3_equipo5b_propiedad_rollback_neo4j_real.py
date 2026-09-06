# -*- coding: utf-8 -*-
"""PROPIEDAD POR APPLY: revertir uno no toca lo que creo el otro.

QUE PROPIEDAD SE FIJA AQUI, LITERAL
-----------------------------------
::

    apply X    -> posee EXACTAMENTE el conjunto PX
    rollback X -> puede eliminar PX, salvo lo compartido todavia vivo
               -> NO puede eliminar P-noX

Y su corolario operacional: revertir tiene las MISMAS garantias que aplicar.

Contra Neo4j REAL. Se activa con ``S9K_5B_NEO4J_URI`` +
``S9K_5B_NEO4J_PASSWORD_FILE`` (la contrasena NUNCA por argv ni por linea de
comandos: se declara el CAMINO de un fichero).

COMO SE MIDE, Y POR QUE ASI
---------------------------
* **Censo completo antes y despues**, no una muestra. La huella es de
  CONTENIDO: etiquetas + propiedades durables, ordenadas. Ni un `elementId`
  aparece en este fichero, porque `elementId` lleva el UUID de la base y se
  regenera al restaurar un dump -- deja de identificar justo durante una
  recuperacion, que es cuando se usa.
* **Ningun conjunto vacio pasa por bueno.** Cada aserto sobre un conjunto va
  precedido de la comprobacion de que ese conjunto NO esta vacio: `[] == []`
  demuestra cualquier cosa, y este proyecto ya se llevo dos sustos con verdes
  por vacio.
* **Control negativo.** Una prueba QUITA la comprobacion de propiedad y exige
  que el resultado se ponga ROJO. Un verde que no puede fallar no prueba nada.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import pytest

pytest.importorskip("neo4j")

from knowledge_v3.writer.apply_identity import (  # noqa: E402
    APPLY_ID_FIELD,
    compute_apply_id,
)
from knowledge_v3.writer.provenance import (  # noqa: E402
    LABEL_EPISODE,
    LABEL_EVIDENCE,
    LABEL_SOURCE,
    persist_provenance,
)
from knowledge_v3.writer.rollback import (  # noqa: E402
    ACTION_PURGE_PROVENANCE,
    RollbackDocument,
    RollbackInstruction,
    add_provenance_sweep,
)
from knowledge_v3.writer.rollback_provenance import (  # noqa: E402
    execute_purge,
    execute_rollback,
)

WS = "ws-5b-propiedad"

URI = os.environ.get("S9K_5B_NEO4J_URI", "").strip()
PASS_FILE = os.environ.get("S9K_5B_NEO4J_PASSWORD_FILE", "").strip()
USER = os.environ.get("S9K_5B_NEO4J_USER", "neo4j").strip()

pytestmark = pytest.mark.skipif(
    not (URI and PASS_FILE),
    reason="Neo4j real: declara S9K_5B_NEO4J_URI y S9K_5B_NEO4J_PASSWORD_FILE",
)


@pytest.fixture(scope="module")
def driver():
    import neo4j as neo4j_mod

    secreto = pathlib.Path(PASS_FILE).read_text(encoding="utf-8").strip()
    d = neo4j_mod.GraphDatabase.driver(URI, auth=(USER, secreto))
    try:
        d.verify_connectivity()
        yield d
    finally:
        d.close()


class Probe:
    """Censo por CONTENIDO. Ni una consulta menciona `elementId`."""

    def __init__(self, driver: Any):
        self.driver = driver

    def run(self, cypher: str, params: dict | None = None) -> list[dict]:
        with self.driver.session() as s:
            return [r.data() for r in s.run(cypher, params or {})]

    def limpiar(self) -> None:
        self.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})

    def censo(self) -> list[str]:
        """Huella completa y ordenada del subgrafo del workspace.

        Es un CENSO, no una muestra: recorre todos los nodos del workspace y
        todas sus aristas. Cada linea es texto derivado del contenido durable,
        de modo que dos bases distintas con el mismo contenido dan la misma
        huella -- lo contrario de lo que haria `elementId`.
        """
        nodos = self.run(
            "MATCH (n) WHERE n.workspace = $ws "
            "RETURN labels(n) AS labels, properties(n) AS props",
            {"ws": WS},
        )
        aristas = self.run(
            "MATCH (a)-[r]->(b) WHERE a.workspace = $ws "
            "RETURN type(r) AS t, properties(a) AS ap, properties(b) AS bp",
            {"ws": WS},
        )
        fuera = []
        for n in nodos:
            props = {k: v for k, v in sorted(n["props"].items())}
            fuera.append(
                "NODO "
                + json.dumps(
                    {"labels": sorted(n["labels"]), "props": props},
                    sort_keys=True,
                    default=str,
                )
            )
        for r in aristas:
            fuera.append(
                "ARISTA "
                + json.dumps(
                    {"tipo": r["t"], "de": _ident(r["ap"]), "a": _ident(r["bp"])},
                    sort_keys=True,
                    default=str,
                )
            )
        return sorted(fuera)

    def ids(self, label: str, campo: str) -> set[str]:
        filas = self.run(
            f"MATCH (n:{label}) WHERE n.workspace = $ws RETURN n.{campo} AS id",
            {"ws": WS},
        )
        return {f["id"] for f in filas if f["id"]}

    def apply_id_de(self, label: str, campo: str, valor: str) -> Any:
        filas = self.run(
            f"MATCH (n:{label} {{{campo}: $v}}) WHERE n.workspace = $ws "
            f"RETURN n.{APPLY_ID_FIELD} AS a",
            {"v": valor, "ws": WS},
        )
        assert filas, f"{label} {valor} no existe: el censo mediria sobre vacio"
        return filas[0]["a"]


@pytest.fixture()
def probe(driver):
    p = Probe(driver)
    p.limpiar()
    yield p
    p.limpiar()


def _ident(props: dict) -> str:
    for campo in (
        "source_asset_id",
        "episode_id",
        "fragment_id",
        "entity_id",
        "assertion_id",
    ):
        if props.get(campo):
            return f"{campo}={props[campo]}"
    return "?"


# --- Material de las dos corridas ------------------------------------------
def _asset(sid: str) -> dict:
    return {"source_asset_id": sid, "title": f"fuente {sid}"}


def _episodio(eid: str, sid: str) -> dict:
    return {"episode_id": eid, "source_asset_id": sid, "ordinal": 1}


def _fragmento(fid: str, eid: str) -> dict:
    return {"fragment_id": fid, "episode_id": eid, "text": f"literal de {fid}"}


APPLY_1 = compute_apply_id(
    workspace=WS, snapshot_id="snap-1", plan_hash="hash-plan-1", partida_id=None
)
APPLY_2 = compute_apply_id(
    workspace=WS, snapshot_id="snap-2", plan_hash="hash-plan-2", partida_id=None
)


def _sembrar_dos_applies(probe) -> None:
    """Dos applies DISTINTOS sobre la MISMA fuente. Ese es el caso que fallaba.

    El apply 1 crea la fuente, 3 episodios y 3 fragmentos. El apply 2 vuelve
    sobre la MISMA fuente y anade 1 episodio y 1 fragmento: la `V3Source` y los
    episodios del apply 1 los REUTILIZA, luego conservan la marca de quien los
    creo. Esa asimetria es la propiedad entera.
    """
    persist_provenance(
        probe.driver,
        workspace=WS,
        partida_id=None,
        source_asset=_asset("src-comun"),
        episodes=[_episodio(f"ep-{i}", "src-comun") for i in (1, 2, 3)],
        fragments=[_fragmento(f"fr-{i}", f"ep-{i}") for i in (1, 2, 3)],
        apply_id=APPLY_1,
    )
    persist_provenance(
        probe.driver,
        workspace=WS,
        partida_id=None,
        source_asset=_asset("src-comun"),  # REUTILIZA la del apply 1
        episodes=[_episodio("ep-4", "src-comun")],  # nuevo
        fragments=[_fragmento("fr-4", "ep-4")],  # nuevo
        apply_id=APPLY_2,
    )


def test_la_marca_es_de_creacion_no_de_uso(probe):
    """Lo REUTILIZADO conserva la marca de quien lo creo. Se observa."""
    _sembrar_dos_applies(probe)

    fragmentos = probe.ids(LABEL_EVIDENCE, "fragment_id")
    assert fragmentos, "sin fragmentos el resto de asertos mediria sobre vacio"
    assert fragmentos == {"fr-1", "fr-2", "fr-3", "fr-4"}

    # La fuente la creo el apply 1 y el apply 2 solo la reutilizo.
    assert probe.apply_id_de(LABEL_SOURCE, "source_asset_id", "src-comun") == APPLY_1
    for i in (1, 2, 3):
        assert probe.apply_id_de(LABEL_EVIDENCE, "fragment_id", f"fr-{i}") == APPLY_1
        assert probe.apply_id_de(LABEL_EPISODE, "episode_id", f"ep-{i}") == APPLY_1
    assert probe.apply_id_de(LABEL_EVIDENCE, "fragment_id", "fr-4") == APPLY_2
    assert probe.apply_id_de(LABEL_EPISODE, "episode_id", "ep-4") == APPLY_2
    assert APPLY_1 != APPLY_2


def test_revertir_el_segundo_apply_no_toca_lo_que_creo_el_primero(probe):
    """EL CASO QUE HOY FALLA. Censo completo antes y despues, sin elementId."""
    _sembrar_dos_applies(probe)
    antes = probe.censo()
    assert antes, "censo vacio: no se estaria midiendo nada"

    doc = RollbackDocument(workspace=WS, snapshot_id="snap-2", plan_hash="hash-plan-2")
    barrido = add_provenance_sweep(doc, workspace=WS, partida_id=None, apply_id=APPLY_2)
    assert barrido is not None
    assert barrido.detail["scope"] == "apply"
    assert barrido.detail[APPLY_ID_FIELD] == APPLY_2
    # El documento NO enumera fragmentos: el radio es la propiedad, no una lista.
    assert "fragment_ids" not in barrido.detail

    with probe.driver.session() as sesion:
        informe = execute_purge(sesion, barrido)

    # PX: lo que el apply 2 creo, y solo eso.
    assert informe.scope == "apply"
    assert informe.apply_id == APPLY_2
    assert informe.deleted_evidence == ["fr-4"]
    assert informe.deleted_episodes == ["ep-4"]
    # La fuente es compartida y la creo el apply 1: ni se borra ni se pretende.
    assert informe.deleted_sources == []
    assert informe.not_owned.get(LABEL_SOURCE) == ["src-comun"]

    # P-noX INTACTO, medido por censo completo, no por conteo.
    despues = probe.censo()
    assert despues, "censo posterior vacio: el aserto siguiente no mediria nada"
    desaparecido = sorted(set(antes) - set(despues))
    assert desaparecido, "no desaparecio NADA: la purga no llego a ejecutarse"
    # Todo lo que desaparecio menciona fr-4 o ep-4. Nada del apply 1.
    ajenos = [l for l in desaparecido if "fr-4" not in l and "ep-4" not in l]
    assert ajenos == [], f"la reversion del apply 2 se llevo P-noX: {ajenos}"

    # Y la fuente SIGUE SIENDO NAVEGABLE: 3 de 3 episodios del apply 1.
    quedan = probe.ids(LABEL_EPISODE, "episode_id")
    assert quedan == {"ep-1", "ep-2", "ep-3"}, quedan
    assert probe.ids(LABEL_SOURCE, "source_asset_id") == {"src-comun"}


def test_control_negativo_sin_propiedad_el_barrido_arrasa_p_no_x(probe):
    """CONTROL NEGATIVO: se quita la propiedad y la prueba se pone ROJA.

    Es el MISMO barrido sobre el MISMO grafo, cambiando una sola cosa: el radio
    vuelve a ser `run` (la lista de fragmentos de la corrida) en vez de la
    propiedad. Si el aserto de la prueba anterior siguiera pasando aqui, seria
    un verde incapaz de fallar y no probaria nada.
    """
    _sembrar_dos_applies(probe)
    antes = probe.censo()
    assert antes

    # Radio ANTIGUO: `scope: "run"` con los 4 fragmentos de la corrida.
    barrido = RollbackInstruction(
        operation_id="provenance:sweep",
        action=ACTION_PURGE_PROVENANCE,
        target_id=None,
        detail={
            "workspace": WS,
            "partida_id": None,
            "fragment_ids": ["fr-1", "fr-2", "fr-3", "fr-4"],
            "scope": "run",
        },
    )
    with probe.driver.session() as sesion:
        informe = execute_purge(sesion, barrido)

    assert informe.scope == "run"
    assert informe.apply_id is None
    # ROJO DEMOSTRADO: se lleva por delante lo que el apply 2 no creo.
    assert set(informe.deleted_evidence) >= {"fr-1", "fr-2", "fr-3"}
    despues = probe.censo()
    desaparecido = sorted(set(antes) - set(despues))
    ajenos = [l for l in desaparecido if "fr-4" not in l and "ep-4" not in l]
    assert ajenos != [], (
        "el control negativo NO se puso rojo: sin propiedad el barrido deberia "
        "haberse llevado P-noX, y no lo hizo. Un verde que no puede fallar no "
        "prueba nada."
    )
    # Y la fuente deja de ser navegable, que es el sintoma que se midio.
    assert probe.ids(LABEL_EPISODE, "episode_id") == set()


def test_lo_compartido_y_vivo_se_retiene_y_se_declara(probe):
    """Una evidencia del apply 2 que una asercion VIVA sostiene NO se borra."""
    _sembrar_dos_applies(probe)
    # Una asercion viva, ajena al rollback, apuntando a fr-4.
    probe.run(
        "MATCH (ev:V3Evidence {fragment_id: 'fr-4'}) WHERE ev.workspace = $ws "
        "CREATE (a:V3Assertion {assertion_id: 'as-viva', workspace: $ws}) "
        "CREATE (a)-[:SUPPORTED_BY]->(ev)",
        {"ws": WS},
    )
    doc = RollbackDocument(workspace=WS, snapshot_id="snap-2", plan_hash="hash-plan-2")
    barrido = add_provenance_sweep(doc, workspace=WS, partida_id=None, apply_id=APPLY_2)

    with probe.driver.session() as sesion:
        informe = execute_purge(sesion, barrido)

    assert informe.deleted_evidence == []
    assert "fr-4" in informe.retained_evidence, informe.to_dict()
    assert informe.retained_evidence["fr-4"] == ["as-viva"]
    assert "fr-4" in probe.ids(LABEL_EVIDENCE, "fragment_id")


def test_el_censo_ve_la_marca_que_el_documento_no_menciona(probe):
    """`residues` ve una `V3AppliedOperation` colgante. S0 es S0 de verdad."""
    _sembrar_dos_applies(probe)
    # Marca superviviente de una operacion de la que no queda NADA. Es el
    # residuo que el censo anterior no veia -- y el que atasca el grafo.
    probe.run(
        "CREATE (op:V3AppliedOperation {workspace: $ws, "
        "idempotency_key: 'clave-huerfana', plan_hash: 'h'})",
        {"ws": WS},
    )
    doc = RollbackDocument(workspace=WS, snapshot_id="snap-2", plan_hash="hash-plan-2")
    add_provenance_sweep(doc, workspace=WS, partida_id=None, apply_id=APPLY_2)

    with probe.driver.session() as sesion:
        informe = execute_rollback(sesion, doc, annotate=True)

    colgantes = [
        r
        for r in informe.residues
        if r["detail"].get("idempotency_key") == "clave-huerfana"
    ]
    assert colgantes, (
        "el censo NO vio la marca colgante: sigue siendo un S0 falso. "
        f"residuos vistos: {informe.residues}"
    )
    # Y el desenlace deja de ser limpio, porque el grafo lo desmiente.
    assert informe.clean is False


def test_ningun_desenlace_se_contradice_a_si_mismo(probe):
    """`clean` y la frase humana salen de UNA sola definicion de «limpio»."""
    from knowledge_v3.writer import cli_rollback

    _sembrar_dos_applies(probe)
    probe.run(
        "CREATE (op:V3AppliedOperation {workspace: $ws, "
        "idempotency_key: 'clave-huerfana', plan_hash: 'h'})",
        {"ws": WS},
    )
    doc = RollbackDocument(workspace=WS, snapshot_id="s", plan_hash="p")
    add_provenance_sweep(doc, workspace=WS, partida_id=None, apply_id=APPLY_2)
    with probe.driver.session() as sesion:
        informe = execute_rollback(sesion, doc, annotate=True)

    assert informe.unrecoverable, "sin puntos no revertidos no habria que medir"
    payload = informe.to_dict()
    frase = cli_rollback.describe(cli_rollback.OUTCOME_INCOMPLETE, informe)
    # La contradiccion medida era exactamente esta pareja.
    assert payload["clean"] is False
    assert "NO es una reversion limpia" in frase
    assert not (payload["clean"] and "NO es una reversion limpia" in frase)

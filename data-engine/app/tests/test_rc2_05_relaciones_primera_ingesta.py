# -*- coding: utf-8 -*-
"""RC2-05 -- la PRIMERA ingesta proyecta las relaciones que la revision aprobo.

EL DEFECTO (RC-E2E final, escenario 8)
--------------------------------------
Con el grafo vacio, la revision aprobo altas de entidad y un hecho entre ellas.
Al sellar salio `PLAN_SEALED_SIN_PROYECCION` y el apply dejo 3 entidades, 2 hechos
y CERO relaciones: las anclas de estado de los extremos salen del snapshot de la
corrida, y una entidad que no estaba en el grafo al ingerir no tiene ancla.

LO QUE SE MIDE AQUI Y LO QUE NO
-------------------------------
Se mide, sin grafo: (1) la composicion del plan sellado por el producto
(`seal_review_plan`), y (2) su ejecucion contra un doble TRANSACCIONAL del
writer (`GrafoVivo`) que hace visibles las escrituras dentro de la transaccion
y las deshace al revertir. Ese doble NO es Neo4j: la visibilidad por ambito de
partida la decide el propio doble (ver el aviso de `test_knowledge_v3_writer`),
asi que lo que depende de Cypher real vive en el test gateado por
`S9K_WRITER_NEO4J_REAL` al final de este fichero (NO EJECUTADO en laboratorio;
lo ejecuta la CI / la RC-3).

Cada afirmacion que falla lo hace con un PREFIJO fijo `RC2-05 <CAUSA>:` --el
calibrador `mutaciones_rc2_05_relaciones_primera_ingesta.py` exige que cada
mutante muera por el suyo--.
"""
from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3 import review_plan  # noqa: E402
from knowledge_v3.writer import InMemoryAppliedKeys, WriterError, codes  # noqa: E402
from knowledge_v3.writer.executor import ExecutionContext, execute_plan  # noqa: E402
from knowledge_v3.writer.view import SignedView  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_ABORTED, OUTCOME_APPLIED  # noqa: E402

import test_knowledge_v3_writer as W  # noqa: E402

JOB = "job-rc205"
AHORA = "2026-07-27T11:00:00Z"
ILARIA = "entity:rc205:ilaria"
CASA = "entity:rc205:casa-ciervo"
OTRA = "entity:rc205:otra"
HOMONIMA = "entity:rc205:casa-ciervo-homonima"
EXISTENTE = "entity:rc205:ya-existente"


# ---------------------------------------------------------------------------
# Material: el sobre de una corrida y sus propuestas aprobadas
# ---------------------------------------------------------------------------
def _hash(valor: str) -> dict:
    return {"algorithm": "sha256", "value": valor * (64 // len(valor))}


def _altas(*ids: str, nombres: dict | None = None) -> dict:
    nombres = nombres or {}
    return {
        i: {"entity_type": "Character", "name": nombres.get(i, i.rsplit(":", 1)[-1]),
            "aliases": []}
        for i in ids
    }


def _contexto(altas: dict | None = None, anclas: dict | None = None, **extra) -> dict:
    base = {
        "workspace": W.WORKSPACE,
        "source_asset_id": "src-rc205",
        "source_hash": _hash("ab"),
        "snapshot_id": "snapshot:rc205",
        "collection_id": "col-rc205",
        "game_profile": "perfil-rc205",
        "ontology_version": "1.0.0",
        "engine_version": "knowledge-v3",
        "contract_version": "1.0.0",
    }
    if altas is not None:
        base[review_plan.ALTAS_KEY] = altas
    if anclas is not None:
        base[review_plan.ANCHORS_KEY] = anclas
    base.update(extra)
    return base


def _ancla(version: int = 7, hash_: str = "cd") -> dict:
    return {
        "version": version,
        "state_hash": _hash(hash_),
        "pending_creation": False,
        "observed": True,
    }


def _propuesta(n: int, contexto: dict, sujeto: str, objeto: str) -> dict:
    pid = f"review:rc205-{n}"
    decision = {
        "decision_id": f"dec-rc205-{n}",
        "claim_id": f"claim:rc205:{n}",
        "decision": "REVIEW",
        "predicate": "LEADS",
        "direction": "SUBJECT_TO_OBJECT",
        "epistemic_status": "ASSERTED",
        "confidence": 0.9,
        "reason_codes": ["REVIEW_LOW_CONFIDENCE"],
        "evidence_fragment_ids": [f"ef-rc205-{n}"],
    }
    bloque = dict(contexto)
    bloque["decisions"] = {pid: decision}
    return {
        "proposal_id": pid,
        "workspace": W.WORKSPACE,
        "episode_id": f"ep-rc205-{n}",
        "package_runs": (JOB,),
        "plan_context_by_run": {JOB: bloque},
        "proposal": {
            "subject": sujeto,
            "object": objeto,
            "predicate": "LEADS",
            "direction": "SUBJECT_TO_OBJECT",
            "negated": False,
        },
        "resolution": {"subject": sujeto, "object": objeto},
    }


def _sellar(propuestas, altas_aprobadas=(), *, tipos: dict | None = None):
    tipos = tipos or {}
    entidades = []
    for entity_id in altas_aprobadas:
        alta = {"entity_id": entity_id}
        if entity_id in tipos:
            alta["entity_type"] = tipos[entity_id]
        entidades.append(alta)
    return review_plan.seal_review_plan(
        workspace=W.WORKSPACE,
        job_id=JOB,
        revision=1,
        approved=list(propuestas),
        decision_ids={
            p["proposal_id"]: p["plan_context_by_run"][JOB]["decisions"][p["proposal_id"]][
                "decision_id"
            ]
            for p in propuestas
        },
        now=AHORA,
        approved_entities=entidades,
    )


def _ops(build, tipo: str) -> list:
    return [o for o in build.plan_doc["mutation_operations"] if o["operation_type"] == tipo]


def _codigos(build) -> list:
    return [o.to_dict()["code"] for o in build.projections_omitted]


def _plan_dos_altas():
    """El caso real: dos entidades ausentes del grafo, aprobadas en la misma revision."""
    contexto = _contexto(altas=_altas(ILARIA, CASA), anclas={})
    prop = _propuesta(1, contexto, ILARIA, CASA)
    return _sellar([prop], [ILARIA, CASA])


# ---------------------------------------------------------------------------
# El doble transaccional del writer
# ---------------------------------------------------------------------------
class TxVivo(W.FakeTx):
    """`FakeTx` que VE sus propias escrituras y las DESHACE al revertir.

    Neo4j lee dentro de una transaccion lo que ella misma escribio y descarta
    todo al hacer rollback. El doble del writer no hacia ninguna de las dos
    cosas, asi que no podia ejercitar una proyeccion anclada a un alta del
    mismo plan.
    """

    def __init__(self, driver):
        super().__init__(driver)
        self._nodos: list = []
        self._aristas: list = []

    def run(self, cypher: str, params: dict):
        if self.driver.fallo_en_arista and "CREATE (a)-[r:" in cypher:
            self.driver.queries.append((cypher, params))
            raise RuntimeError("el driver se cayo (simulado) al crear la arista")
        resultado = super().run(cypher, params)
        if resultado.single() is None:
            return resultado
        if cypher.startswith("CREATE (n:") and "V3Entity" in cypher:
            props = params["props"]
            clave = ("entity", props["entity_id"])
            self.driver.nodes[clave] = {
                "version": props.get("version", 0),
                "state_hash": props.get("state_hash"),
                "partida_id": props.get("partida_id"),
            }
            self._nodos.append(clave)
        elif "CREATE (a)-[r:" in cypher:
            tipo = re.search(r"\[r:(\w+)", cypher).group(1)
            arista = (tipo, params["subject"], params["object"])
            self.driver.aristas.append(arista)
            self._aristas.append(arista)
        return resultado

    def rollback(self):
        super().rollback()
        for clave in self._nodos:
            self.driver.nodes.pop(clave, None)
        for arista in self._aristas:
            self.driver.aristas.remove(arista)


class SesionViva(W.FakeSession):
    def begin_transaction(self):
        tx = TxVivo(self.driver)
        self.driver.transactions.append(tx)
        return tx


class GrafoVivo(W.FakeDriver):
    def __init__(self, nodes: dict | None = None):
        super().__init__(nodes=nodes)
        self.aristas: list = []
        self.fallo_en_arista = False

    def session(self):
        return SesionViva(self)


def _entidades_creadas(driver) -> set:
    return {k[1] for k in driver.nodes if k[0] == "entity"}


def _aplicar(plan: dict, driver, keys=None):
    escritor = W.make_writer(driver, applied_keys=keys or InMemoryAppliedKeys())
    return escritor.write(plan, W.apply_request(plan, current_snapshot_id=plan["snapshot_id"]))


def _plan_con_arista(build) -> dict:
    assert _ops(build, "PROJECT_RELATION"), (
        "RC2-05 SIN PROYECCION: el plan sellado por la revision no trae la relacion "
        f"aprobada entre las entidades nuevas (omitidas: {_codigos(build)})"
    )
    return build.plan_doc


# ===========================================================================
# (a) dos entidades nuevas + relacion
# ===========================================================================
def test_a_dos_altas_aprobadas_y_su_relacion_se_proyectan_en_el_plan():
    build = _plan_dos_altas()
    plan = _plan_con_arista(build)

    assert build.projections_omitted == (), (
        "RC2-05 SIN PROYECCION: el plan declara una relacion omitida pese a traer "
        f"las dos altas: {_codigos(build)}"
    )
    altas = {o["target_entity_id"] for o in _ops(build, "CREATE_ENTITY")}
    assert altas == {ILARIA, CASA}
    proyeccion = _ops(build, "PROJECT_RELATION")[0]
    # EL ANCLA ES EL ALTA DEL PLAN, no una version inventada.
    assert proyeccion["expected_state"] == "WOULD_CREATE"
    assert proyeccion["expected_version"] is None and proyeccion["expected_hash"] is None
    assert proyeccion["target_entity_id"] == ILARIA
    assert proyeccion["payload"]["subject_entity_id"] == ILARIA
    assert proyeccion["payload"]["object_entity_id"] == CASA
    # PROCEDENCIA: la arista cita la misma evidencia que la afirmacion.
    asercion = _ops(build, "CREATE_ASSERTION")[0]
    assert proyeccion["evidence_fragment_ids"] == asercion["evidence_fragment_ids"] == [
        "ef-rc205-1"
    ]
    assert proyeccion["decision_id"] == asercion["decision_id"]
    # ORDEN: cada alta va por delante de la arista que la usa.
    tipos = [o["operation_type"] for o in plan["mutation_operations"]]
    assert tipos.index("PROJECT_RELATION") > max(
        i for i, t in enumerate(tipos) if t == "CREATE_ENTITY"
    ), f"RC2-05 ORDEN: la arista va por delante de su alta: {tipos}"


def test_a_el_orden_del_alta_no_depende_del_nombre_del_claim():
    """Con un claim cuyo id ordena ANTES que `op:alta:` el alta sigue yendo primero."""
    contexto = _contexto(altas=_altas(ILARIA, CASA), anclas={})
    prop = _propuesta(1, contexto, ILARIA, CASA)
    decision = prop["plan_context_by_run"][JOB]["decisions"][prop["proposal_id"]]
    decision["claim_id"] = "a-claim-que-ordena-antes"
    plan = _plan_con_arista(_sellar([prop], [ILARIA, CASA]))
    tipos = [o["operation_type"] for o in plan["mutation_operations"]]
    assert tipos.index("PROJECT_RELATION") > max(
        i for i, t in enumerate(tipos) if t == "CREATE_ENTITY"
    ), f"RC2-05 ORDEN: la arista va por delante de su alta: {tipos}"


def test_a_el_apply_crea_las_dos_entidades_y_la_arista_en_una_transaccion():
    plan = _plan_con_arista(_plan_dos_altas())
    driver = GrafoVivo()
    resultado = _aplicar(plan, driver)

    assert resultado.outcome == OUTCOME_APPLIED, (
        f"RC2-05 SIN PROYECCION: el apply no termino: {resultado.outcome} {resultado.codes}"
    )
    assert _entidades_creadas(driver) == {ILARIA, CASA}
    assert driver.aristas == [("LEADS", ILARIA, CASA)], (
        f"RC2-05 SIN PROYECCION: la arista no esta tras el apply: {driver.aristas}"
    )
    assert len(driver.transactions) == 1 and driver.committed


# ===========================================================================
# (b) una entidad existente + una nueva
# ===========================================================================
@pytest.mark.parametrize("existente_es_sujeto", [True, False])
def test_b_una_existente_y_una_nueva_se_proyectan(existente_es_sujeto):
    sujeto, objeto = (EXISTENTE, CASA) if existente_es_sujeto else (CASA, EXISTENTE)
    contexto = _contexto(altas=_altas(CASA), anclas={EXISTENTE: _ancla()})
    prop = _propuesta(1, contexto, sujeto, objeto)
    build = _sellar([prop], [CASA])
    plan = _plan_con_arista(build)

    proyeccion = _ops(build, "PROJECT_RELATION")[0]
    if existente_es_sujeto:
        # El sujeto YA existe: su estado previo se COPIA del ancla observada.
        assert proyeccion["expected_version"] == 7
        assert proyeccion["expected_hash"] == _hash("cd")
    else:
        assert proyeccion["expected_version"] is None
    assert proyeccion["expected_state"] == "WOULD_CREATE"

    driver = GrafoVivo(nodes={
        ("entity", EXISTENTE): {"version": 7, "state_hash": "cd" * 32, "partida_id": None},
    })
    resultado = _aplicar(plan, driver)
    assert resultado.outcome == OUTCOME_APPLIED, (
        f"RC2-05 SIN PROYECCION: el apply no termino: {resultado.outcome} {resultado.codes}"
    )
    assert driver.aristas == [("LEADS", sujeto, objeto)]


# ===========================================================================
# (c) rechazo parcial: una de las altas NO entra -> la relacion no se proyecta
# ===========================================================================
def test_c_sin_aprobar_el_alta_la_relacion_no_se_proyecta_y_se_dice():
    contexto = _contexto(altas=_altas(ILARIA, CASA), anclas={})
    prop = _propuesta(1, contexto, ILARIA, CASA)
    build = _sellar([prop], [ILARIA])  # la de la Casa NO se aprueba

    assert _ops(build, "PROJECT_RELATION") == [], (
        "RC2-05 SIN APROBACION: se proyecto una relacion hacia una entidad cuya "
        "alta nadie aprobo"
    )
    assert _codigos(build) == ["PROJECTION_ALTA_NOT_IN_PLAN"], (
        f"RC2-05 SIN APROBACION: la omision no dice por que: {_codigos(build)}"
    )
    assert {o["target_entity_id"] for o in _ops(build, "CREATE_ENTITY")} == {ILARIA}
    # La afirmacion SI entra: omitir la arista no es excluir la propuesta.
    assert build.included_proposal_ids == (prop["proposal_id"],)


def test_c_un_alta_aprobada_que_el_plan_deja_fuera_no_ancla_la_relacion():
    """Aprobada pero sin tipo: `ALTA_WITHOUT_TYPE`. Tampoco hay arista."""
    altas = _altas(ILARIA, CASA)
    altas[CASA]["entity_type"] = ""
    contexto = _contexto(altas=altas, anclas={})
    prop = _propuesta(1, contexto, ILARIA, CASA)
    build = _sellar([prop], [ILARIA, CASA])

    assert [o.code for o in build.altas_omitted] == ["ALTA_WITHOUT_TYPE"]
    assert _ops(build, "PROJECT_RELATION") == [], (
        "RC2-05 ALTA RECHAZADA: se proyecto una relacion hacia una entidad cuya "
        "alta el plan dejo fuera"
    )
    assert _codigos(build) == ["PROJECTION_ALTA_NOT_IN_PLAN"]


def test_c_la_identidad_es_la_del_alta_no_un_nombre_parecido():
    """Dos entidades con el MISMO nombre: solo se ancla la que se aprobo."""
    nombres = {CASA: "Casa del Ciervo", HOMONIMA: "Casa del Ciervo"}
    contexto = _contexto(altas=_altas(ILARIA, CASA, HOMONIMA, nombres=nombres), anclas={})
    buena = _propuesta(1, contexto, ILARIA, CASA)  # la que se aprobo
    parecida = _propuesta(2, contexto, ILARIA, HOMONIMA)  # mismo nombre, otra identidad
    build = _sellar([buena, parecida], [ILARIA, CASA])  # se aprobo CASA, no su homonima

    destinos = [o["payload"]["object_entity_id"] for o in _ops(build, "PROJECT_RELATION")]
    assert destinos == [CASA], (
        "RC2-05 IDENTIDAD: la relacion se resolvio por un nombre parecido y no por "
        f"la identidad del alta aprobada: {destinos}"
    )
    assert _codigos(build) == ["PROJECTION_ALTA_NOT_IN_PLAN"]


# ===========================================================================
# (d) relacion no aprobada -> no se proyecta
# ===========================================================================
def test_d_una_relacion_no_aprobada_no_se_proyecta_ni_arrastra_su_alta():
    contexto = _contexto(altas=_altas(ILARIA, CASA, OTRA), anclas={})
    aprobada = _propuesta(1, contexto, ILARIA, CASA)
    # La propuesta 2 (ILARIA -> OTRA) existe en el almacen pero NO se aprueba.
    build = _sellar([aprobada], [ILARIA, CASA, OTRA])

    destinos = [o["payload"]["object_entity_id"] for o in _ops(build, "PROJECT_RELATION")]
    assert destinos == [CASA], (
        f"RC2-05 SIN APROBACION: hay relaciones que nadie aprobo: {destinos}"
    )
    # El alta aprobada que ninguna afirmacion del plan menciona no crea un nodo suelto.
    assert OTRA not in {o["target_entity_id"] for o in _ops(build, "CREATE_ENTITY")}
    assert [o.code for o in build.altas_omitted] == ["ALTA_NOT_REFERENCED"]


def test_d_un_hecho_negado_no_se_proyecta_aunque_las_altas_esten():
    contexto = _contexto(altas=_altas(ILARIA, CASA), anclas={})
    prop = _propuesta(1, contexto, ILARIA, CASA)
    prop["proposal"]["negated"] = True
    build = _sellar([prop], [ILARIA, CASA])
    assert _ops(build, "PROJECT_RELATION") == []
    assert _codigos(build) == ["PROJECTION_NEGATED_FACT"]


# ===========================================================================
# (e) fallo a mitad del apply: nada a medias, nada de exito falso
# ===========================================================================
def test_e_un_fallo_tras_crear_los_nodos_y_antes_de_la_arista_no_es_un_exito():
    plan = _plan_con_arista(_plan_dos_altas())
    driver = GrafoVivo()
    driver.fallo_en_arista = True
    llaves = InMemoryAppliedKeys()
    resultado = _aplicar(plan, driver, llaves)

    assert resultado.outcome == OUTCOME_ABORTED and not resultado.ok, (
        f"RC2-05 EXITO FALSO: un apply que no pudo proyectar la arista termino "
        f"como {resultado.outcome}"
    )
    assert codes.EXEC_DRIVER_FAILURE in resultado.codes
    assert driver.rolled_back and not driver.committed
    # TODO O NADA: los nodos que se llegaron a crear se deshicieron con la arista.
    assert _entidades_creadas(driver) == set(), (
        f"RC2-05 EXITO FALSO: quedaron entidades a medias: {_entidades_creadas(driver)}"
    )
    assert driver.aristas == []
    assert llaves.entries == {}, "RC2-05 EXITO FALSO: se registraron claves como aplicadas"


# ===========================================================================
# (f) reintento: converge sin duplicar
# ===========================================================================
def test_f_el_reintento_tras_el_fallo_converge_a_un_unico_estado():
    plan = _plan_con_arista(_plan_dos_altas())
    driver = GrafoVivo()
    llaves = InMemoryAppliedKeys()
    driver.fallo_en_arista = True
    assert _aplicar(plan, driver, llaves).outcome == OUTCOME_ABORTED
    driver.fallo_en_arista = False
    segundo = _aplicar(plan, driver, llaves)

    assert segundo.outcome == OUTCOME_APPLIED, (
        f"RC2-05 REINTENTO: el reintento no convergio: {segundo.outcome} {segundo.codes}"
    )
    assert _entidades_creadas(driver) == {ILARIA, CASA}
    assert driver.aristas == [("LEADS", ILARIA, CASA)]


def test_f_reaplicar_el_mismo_plan_no_duplica_nodos_ni_aristas():
    plan = _plan_con_arista(_plan_dos_altas())
    driver = GrafoVivo()
    llaves = InMemoryAppliedKeys()
    assert _aplicar(plan, driver, llaves).outcome == OUTCOME_APPLIED
    escrituras = len(driver.writes)

    # Segundo intento a nivel de executor: todas las claves ya estan marcadas.
    vista = SignedView.of(plan)
    contexto = ExecutionContext(operator_id="pjc", written_at="2026-07-27T12:00:00Z",
                                applied_keys=llaves)
    try:
        salida = execute_plan(driver, vista, contexto)
    except WriterError as exc:
        pytest.fail(
            "RC2-05 REINTENTO: el segundo apply no fue un no-op y aborto por "
            f"{exc.code}: intento volver a crear lo que ya estaba"
        )

    assert len(driver.writes) == escrituras, (
        "RC2-05 REINTENTO DUPLICA: el segundo apply escribio de nuevo "
        f"({len(driver.writes) - escrituras} escrituras mas)"
    )
    assert _entidades_creadas(driver) == {ILARIA, CASA}
    assert driver.aristas == [("LEADS", ILARIA, CASA)], (
        f"RC2-05 REINTENTO DUPLICA: las aristas tras dos apply son {driver.aristas}"
    )
    assert salida.applied == [] and len(salida.noop_keys) == len(plan["mutation_operations"]), (
        "RC2-05 REINTENTO: el segundo apply volvio a ejecutar operaciones: "
        f"{len(salida.applied)} aplicadas, {len(salida.noop_keys)} no-op"
    )


# ===========================================================================
# (g) sin altas: el plan es el de siempre
# ===========================================================================
#: `plan_hash` del plan de dos entidades YA EXISTENTES, medido sobre `main`
#: ANTES de esta correccion (RC2-05). Si cambia, la correccion movio un plan que
#: hoy funciona.
HASH_PLAN_SIN_ALTAS = "PENDIENTE_DE_MEDIR"


def _plan_sin_altas():
    contexto = _contexto(altas=_altas(), anclas={ILARIA: _ancla(7, "cd"), CASA: _ancla(3, "ef")})
    prop = _propuesta(1, contexto, ILARIA, CASA)
    return _sellar([prop])


def test_g_sin_altas_el_plan_es_identico_al_de_antes():
    build = _plan_sin_altas()
    proyeccion = _ops(build, "PROJECT_RELATION")
    assert len(proyeccion) == 1 and _ops(build, "CREATE_ENTITY") == []
    assert proyeccion[0]["expected_state"] == "WOULD_UPDATE"
    assert proyeccion[0]["expected_version"] == 7
    assert proyeccion[0]["expected_hash"] == _hash("cd")
    orden = [o["operation_id"] for o in build.plan_doc["mutation_operations"]]
    assert orden == sorted(orden)
    assert build.plan_doc["plan_hash"]["value"] == HASH_PLAN_SIN_ALTAS, (
        "RC2-05 PLAN MOVIDO: el plan sin altas ya no es el de antes de la correccion: "
        f"{build.plan_doc['plan_hash']['value']}"
    )


def test_g_la_identidad_logica_del_plan_no_depende_de_las_altas():
    con = _plan_dos_altas()
    contexto = _contexto(altas=_altas(ILARIA, CASA), anclas={})
    sin = _sellar([_propuesta(1, contexto, ILARIA, CASA)])  # altas sin aprobar
    assert con.plan_doc["plan_id"] == sin.plan_doc["plan_id"]
    assert con.plan_doc["plan_hash"]["value"] != sin.plan_doc["plan_hash"]["value"]


def test_g_sin_ancla_y_sin_alta_declarada_se_sigue_omitiendo_con_su_codigo():
    contexto = _contexto(anclas={})
    build = _sellar([_propuesta(1, contexto, ILARIA, CASA)])
    assert _ops(build, "PROJECT_RELATION") == []
    assert _codigos(build) == ["PROJECTION_NO_ANCHOR"]


# ===========================================================================
# (h) ambito y workspace: nada cruza
# ===========================================================================
def test_h_un_alta_aprobada_que_no_es_de_esta_corrida_no_ancla_nada():
    """El id viene aprobado pero la corrida (su workspace) no lo declara."""
    contexto = _contexto(altas=_altas(ILARIA), anclas={})  # CASA no declarada aqui
    prop = _propuesta(1, contexto, ILARIA, CASA)
    build = _sellar([prop], [ILARIA, CASA], tipos={CASA: "Character"})

    assert CASA not in {o["target_entity_id"] for o in _ops(build, "CREATE_ENTITY")}, (
        "RC2-05 AMBITO: se creo una entidad que la corrida de este ambito no declara"
    )
    assert _ops(build, "PROJECT_RELATION") == [], (
        "RC2-05 AMBITO: se proyecto una relacion hacia una entidad de otro ambito"
    )
    assert [o.code for o in build.altas_omitted] == ["ALTA_NOT_DECLARED_IN_RUN"]
    assert _codigos(build) == ["PROJECTION_NO_ANCHOR"]


def test_h_el_plan_lleva_el_ambito_de_la_corrida():
    contexto = _contexto(altas=_altas(ILARIA, CASA), anclas={}, partida_id="partida:rc205")
    build = _sellar([_propuesta(1, contexto, ILARIA, CASA)], [ILARIA, CASA])
    plan = _plan_con_arista(build)
    assert plan["workspace"] == W.WORKSPACE
    assert plan["partida_id"] == "partida:rc205"
    assert plan["scope"]["partida_id"] == "partida:rc205"


def test_h_un_extremo_existente_de_otra_partida_aborta_y_no_deja_nada():
    """La arista hacia un nodo que el plan no ve (otra partida) no se escribe.

    El plan es de capa juego; el extremo existente vive en `partida:B`. El
    ancla de la arista es el alta del plan, pero el EXTREMO existente sigue
    sometido a la visibilidad del writer: aborta y revierte las altas.
    """
    contexto = _contexto(altas=_altas(CASA), anclas={EXISTENTE: _ancla()})
    prop = _propuesta(1, contexto, CASA, EXISTENTE)
    plan = _plan_con_arista(_sellar([prop], [CASA]))
    driver = GrafoVivo(nodes={
        ("entity", EXISTENTE): {"version": 7, "state_hash": "cd" * 32, "partida_id": "partida:B"},
    })
    resultado = _aplicar(plan, driver)

    assert resultado.outcome == OUTCOME_ABORTED and codes.EXEC_TARGET_MISSING in resultado.codes, (
        f"RC2-05 AMBITO: la arista cruzo de ambito: {resultado.outcome} {resultado.codes}"
    )
    assert driver.aristas == []
    assert _entidades_creadas(driver) == {EXISTENTE}


def test_h_un_plan_de_otro_workspace_no_se_aplica():
    plan = _plan_con_arista(_plan_dos_altas())
    escritor = W.make_writer(GrafoVivo(), workspace="otro-workspace")
    resultado = escritor.write(
        plan,
        W.apply_request(plan, current_snapshot_id=plan["snapshot_id"],
                        workspace="otro-workspace", env=W.apply_env("otro-workspace")),
    )
    assert not resultado.ok, "RC2-05 AMBITO: un plan de un workspace se aplico en otro"
    assert codes.PLAN_WORKSPACE_MISMATCH in resultado.codes


# ===========================================================================
# El texto declarado dice lo que el codigo hace
# ===========================================================================
def test_el_texto_de_sin_ancla_ya_no_promete_lo_que_el_plan_resuelve():
    catalogado = review_plan.PROJECTION_CODES["PROJECTION_NO_ANCHOR"]
    assert "entidad nueva aprobada en esta revision" not in catalogado, (
        "RC2-05 TEXTO RANCIO: PROJECTION_NO_ANCHOR sigue atribuyendo la omision a "
        f"un alta aprobada en esta revision, y eso ya se proyecta: {catalogado!r}"
    )
    nuevo = review_plan.PROJECTION_CODES["PROJECTION_ALTA_NOT_IN_PLAN"]
    assert "no entra en este plan" in nuevo and "arista no se proyecta" in nuevo


# ===========================================================================
# CON NEO4J REAL (NO EJECUTADO en laboratorio: lo ejecuta la CI / la RC-3)
# ===========================================================================
LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"

CENSO = (
    "CALL () { MATCH (n:V3Entity) RETURN count(n) AS entidades } "
    "CALL () { MATCH (n:V3Assertion) RETURN count(n) AS aserciones } "
    "CALL () { MATCH (:V3Entity)-[r]->(:V3Entity) RETURN count(r) AS aristas } "
    "RETURN entidades, aserciones, aristas"
)


@pytest.fixture(scope="module")
def _driver_rc205():
    import test_knowledge_v3_writer_neo4j_real as WR

    with WR.neo4j_efimero("s9k-rc205-test") as driver:
        yield driver


@pytest.fixture()
def graph(_driver_rc205):
    import test_knowledge_v3_writer_neo4j_real as WR

    probe = WR.GraphProbe(_driver_rc205)
    probe.clean()
    yield probe
    probe.clean()


@pytest.mark.skipif(not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1")
def test_neo4j_real_primera_ingesta_proyecta_la_relacion_y_reaplicar_no_duplica(graph):
    """Plan del producto -> apply -> arista presente -> segundo apply sin cambios.

    NO EJECUTADO en laboratorio (sin Neo4j): lo ejecuta la CI / la RC-3.
    """
    import test_knowledge_v3_e2e_neo4j_real as E  # noqa: PLC0415

    plan = _plan_con_arista(_plan_dos_altas())
    primero = E.writer_for(plan, graph.driver, InMemoryAppliedKeys()).write(
        plan, E.request_for(plan)
    )
    assert primero.outcome == "APPLIED", (primero.outcome, primero.codes)
    censo = graph.run(CENSO, {})[0]
    assert censo["entidades"] == 2 and censo["aserciones"] == 1, censo
    assert censo["aristas"] == 1, (
        f"RC2-05 SIN PROYECCION: el primer apply no materializo la relacion: {censo}"
    )

    segundo = E.writer_for(plan, graph.driver, InMemoryAppliedKeys()).write(
        plan, E.request_for(plan)
    )
    assert segundo.applied_operations == 0, (
        f"RC2-05 REINTENTO: el segundo apply escribio {segundo.applied_operations}"
    )
    assert graph.run(CENSO, {})[0] == censo

# -*- coding: utf-8 -*-
"""Slice 2 · B2 — la proyeccion anclada en lo OBSERVADO, y el efecto MIRADO.

QUE SE MIDE AQUI, Y QUE NO
---------------------------
Aqui se mide lo que se puede medir SIN grafo: la composicion del plan sellado
(que operaciones salen y con que anclas), la publicacion del sobre, y la
CALIBRACION del verificador de efectos contra un driver de mentira que devuelve
exactamente lo que se le dice.

Lo que NO se mide aqui es que el apply desde la UI materialice de verdad: eso
exige Neo4j y vive en `viewer/tests/test_panel_apply_desde_la_ui.py`, bajo
`S9K_WRITER_NEO4J_REAL`. Un modulo que dijera medirlo sin grafo estaria
midiendo su propio doble.

LA CALIBRACION ES LA PRUEBA
---------------------------
Cada caso del verificador se acompana de su GEMELO: el mismo montaje con el
efecto presente, para que el verde signifique algo. Un verificador que nunca se
pone verde y uno que nunca se pone rojo son igual de inutiles, y solo el par lo
distingue.
"""
from __future__ import annotations

import copy

import pytest

from knowledge_v3 import review_export, review_plan
from knowledge_v3.engine.snapshot import SnapshotEntity
from knowledge_v3.pipeline import bridge, graph_catalog
from knowledge_v3.writer import effects
from knowledge_v3.writer.apply import ProvenanceBundle

WS = "ws-pruebas-b2"
AHORA = "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Material minimo: una propuesta aprobada con su contexto de corrida
# ---------------------------------------------------------------------------
def _hash(valor: str) -> dict:
    return {"algorithm": "sha256", "value": valor * (64 // len(valor)) }


def _contexto(**extra) -> dict:
    base = {
        "workspace": WS,
        "source_asset_id": "src-b2",
        "source_hash": _hash("ab"),
        "snapshot_id": "snap-b2",
        "collection_id": "col-b2",
        "game_profile": "perfil-b2",
        "ontology_version": "1.0.0",
        "engine_version": "knowledge-v3",
        "contract_version": "1.0.0",
    }
    base.update(extra)
    return base


def _decision(**extra) -> dict:
    base = {
        "decision_id": "dec-b2-1",
        "claim_id": "claim-b2-1",
        "decision": "REVIEW",
        "predicate": "LEADS",
        "direction": "SUBJECT_TO_OBJECT",
        "epistemic_status": "ASSERTED",
        "confidence": 0.9,
        "reason_codes": ["REVIEW_LOW_CONFIDENCE"],
        "evidence_fragment_ids": ["ef-b2-1"],
    }
    base.update(extra)
    return base


def _propuesta(job_id: str, contexto: dict, decision: dict, *, negated=False) -> dict:
    identificador = "review:b2-1"
    bloque = dict(contexto)
    bloque["decisions"] = {identificador: decision}
    return {
        "proposal_id": identificador,
        "workspace": WS,
        "episode_id": "ep-b2-1",
        "package_runs": (job_id,),
        "plan_context_by_run": {job_id: bloque},
        "proposal": {
            "subject": "entity:sujeto",
            "object": "entity:objeto",
            "predicate": "LEADS",
            "direction": "SUBJECT_TO_OBJECT",
            "negated": negated,
        },
        "resolution": {"subject": "entity:sujeto", "object": "entity:objeto"},
    }


def _anclas(*, observed=True, pending=False) -> dict:
    return {
        "entity:sujeto": {
            "version": 7,
            "state_hash": _hash("cd"),
            "pending_creation": pending,
            "observed": observed,
        },
        "entity:objeto": {
            "version": 3,
            "state_hash": _hash("ef"),
            "pending_creation": False,
            "observed": observed,
        },
    }


def _sellar(propuesta: dict, job_id: str = "job-b2"):
    return review_plan.seal_review_plan(
        workspace=WS,
        job_id=job_id,
        revision=1,
        approved=[propuesta],
        decision_ids={propuesta["proposal_id"]: "dec-b2-1"},
        now=AHORA,
    )


def _tipos(build) -> list:
    return [op["operation_type"] for op in build.plan_doc["mutation_operations"]]


# ===========================================================================
# 1. LA PROYECCION SE EMITE — y con el ancla COPIADA, no inventada
# ===========================================================================

def test_con_ancla_observada_se_emite_la_proyeccion_y_copia_el_ancla():
    """El caso que antes no existia: el plan sellado por la UI trae la arista.

    Y lo que importa no es que haya una operacion mas, sino que su
    `expected_version`/`expected_hash` sean EXACTAMENTE los del ancla. Un
    valor plausible ahi es lo que produce `EXEC_HASH_MISMATCH` contra un nodo
    real, y no se distingue de uno correcto mirando solo el tipo.
    """
    anclas = _anclas()
    contexto = _contexto(**{review_plan.ANCHORS_KEY: anclas})
    build = _sellar(_propuesta("job-b2", contexto, _decision()))

    assert _tipos(build) == ["CREATE_ASSERTION", "PROJECT_RELATION"], _tipos(build)
    assert build.projections_omitted == ()

    proyeccion = next(
        op for op in build.plan_doc["mutation_operations"]
        if op["operation_type"] == "PROJECT_RELATION"
    )
    ancla = anclas["entity:sujeto"]
    assert proyeccion["expected_version"] == ancla["version"]
    assert proyeccion["expected_hash"] == ancla["state_hash"]
    assert proyeccion["expected_state"] == "WOULD_UPDATE"
    assert proyeccion["target_entity_id"] == "entity:sujeto"
    assert proyeccion["payload"]["predicate"] == "LEADS"
    assert proyeccion["payload"]["subject_entity_id"] == "entity:sujeto"
    assert proyeccion["payload"]["object_entity_id"] == "entity:objeto"
    # La arista cita la MISMA evidencia que la afirmacion: si no, la
    # procedencia de una y otra divergirian.
    assert proyeccion["evidence_fragment_ids"] == ["ef-b2-1"]
    # Y `seal_plan` le deriva su clave de idempotencia, como a cualquier otra.
    assert proyeccion["idempotency_key"]


# ===========================================================================
# 2. LOS CUATRO MOTIVOS DE OMISION, cada uno POR SU CAUSA
# ===========================================================================

@pytest.mark.parametrize(
    "montaje, esperado",
    [
        ("sin_anclas", "PROJECTION_NO_ANCHOR"),
        ("no_observada", "PROJECTION_ANCHOR_NOT_OBSERVED"),
        ("pendiente_de_alta", "PROJECTION_ENTITY_NOT_IN_GRAPH"),
        ("hecho_negado", "PROJECTION_NEGATED_FACT"),
    ],
)
def test_cada_omision_lleva_su_codigo_y_la_afirmacion_sigue_entrando(montaje, esperado):
    """Sin arista, pero NUNCA en silencio — y sin perder la afirmacion.

    Los cuatro montajes se distinguen entre si: cada uno tiene que dar SU
    codigo y no el de al lado. Un unico codigo generico pondria verde este
    caso sin decir nada.
    """
    negado = montaje == "hecho_negado"
    if montaje == "sin_anclas":
        contexto = _contexto()
    elif montaje == "no_observada":
        contexto = _contexto(**{review_plan.ANCHORS_KEY: _anclas(observed=False)})
    elif montaje == "pendiente_de_alta":
        contexto = _contexto(**{review_plan.ANCHORS_KEY: _anclas(pending=True)})
    else:
        contexto = _contexto(**{review_plan.ANCHORS_KEY: _anclas()})

    build = _sellar(_propuesta("job-b2", contexto, _decision(), negated=negado))

    assert _tipos(build) == ["CREATE_ASSERTION"], _tipos(build)
    assert [o.to_dict()["code"] for o in build.projections_omitted] == [esperado]
    # La propuesta SI entro en el plan: omitir la arista no es excluirla.
    assert build.included_proposal_ids == ("review:b2-1",)
    assert build.excluded == ()


def test_un_motivo_de_omision_no_declarado_no_se_puede_emitir():
    """La enumeracion esta CERRADA por construccion, no por convencion."""
    with pytest.raises(review_plan.ReviewPlanError) as exc:
        review_plan.OmittedProjection("review:b2-1", "PROJECTION_ME_LO_INVENTO")
    assert exc.value.code == "PROJECTION_CODE_NOT_DECLARED"


# ===========================================================================
# 3. LA IDENTIDAD DEL PLAN NO SE MUEVE (lo que el encargo mandaba vigilar)
# ===========================================================================

def test_emitir_la_proyeccion_no_cambia_la_identidad_logica_del_plan():
    """`plan_id` IGUAL; `plan_hash` distinto, que es lo que un hash debe hacer.

    Era la condicion explicita del encargo: si extender el sobre moviera la
    identidad del plan, esto tocaria identidad durable. No la mueve: `plan_id`
    se compone de workspace, corrida, revision, `snapshot_id` y decisiones, y
    ninguno de esos insumos depende de cuantas operaciones salgan.
    """
    con = _sellar(_propuesta(
        "job-b2", _contexto(**{review_plan.ANCHORS_KEY: _anclas()}), _decision()
    ))
    sin = _sellar(_propuesta("job-b2", _contexto(), _decision()))

    assert con.plan_doc["plan_id"] == sin.plan_doc["plan_id"]
    # CALIBRACION: si los dos planes fuesen iguales, la igualdad de arriba no
    # diria nada. Son distintos, y el hash de contenido lo refleja.
    assert len(con.plan_doc["mutation_operations"]) == 2
    assert len(sin.plan_doc["mutation_operations"]) == 1
    assert con.plan_doc["plan_hash"]["value"] != sin.plan_doc["plan_hash"]["value"]


# ===========================================================================
# 4. EL SOBRE: anclas OBSERVADAS solo si se observaron
# ===========================================================================

class _Corrida:
    def __init__(self, snapshot=None, asset=None, episodes=(), fragments=()):
        self.snapshot = snapshot
        self.asset = asset
        self.episodes = list(episodes)
        self.fragments = list(fragments)


class _Resultado:
    def __init__(self, runs):
        self.runs = list(runs)


class _Foto:
    def __init__(self, entidades):
        self._por_id = {e.entity_id: e for e in entidades}

    def entity(self, entity_id):
        return self._por_id.get(entity_id)


def _documentos() -> list:
    return [{
        "proposal_id": "review:b2-1",
        "claim_id": "claim-b2-1",
        "resolution": {"subject": "entity:sujeto", "object": "entity:objeto"},
        "proposal": {"subject": "entity:sujeto", "object": "entity:objeto"},
    }]


def test_el_catalogo_en_fichero_NO_marca_observado_y_el_del_grafo_SI():
    """La diferencia que decide si se proyecta, medida en los dos sentidos.

    `bridge.entities_from_catalog` DERIVA el `state_hash` del propio id: es
    plausible y falso. `graph_catalog.snapshot_entities` copia el del nodo.
    Las dos rutas producen `SnapshotEntity`, y hasta este corte nada en el
    dato las distinguia.
    """
    declaradas = bridge.entities_from_catalog(
        [{"entity_id": "entity:sujeto", "type": "Character", "version": 1}]
    )
    observadas = graph_catalog.snapshot_entities(
        [{"entity_id": "entity:sujeto", "type": "Character", "version": 9,
          "state_hash": "f" * 64}]
    )
    assert [e.observed for e in declaradas] == [False]
    assert [e.observed for e in observadas] == [True]
    # Y el valor que se copiaria: el observado es el del nodo, no uno derivado.
    assert observadas[0].version == 9
    assert observadas[0].state_hash["value"] == "f" * 64


def test_el_sobre_publica_las_anclas_de_la_foto_de_la_corrida():
    foto = _Foto(graph_catalog.snapshot_entities([
        {"entity_id": "entity:sujeto", "type": "Character", "version": 9,
         "state_hash": "a" * 64},
        {"entity_id": "entity:objeto", "type": "Faction", "version": 2,
         "state_hash": "b" * 64},
    ]))
    anclas = review_export.run_entity_anchors(
        _Resultado([_Corrida(snapshot=foto)]), _documentos()
    )
    assert anclas["entity:sujeto"] == {
        "version": 9, "state_hash": {"algorithm": "sha256", "value": "a" * 64},
        "pending_creation": False, "observed": True,
    }
    assert set(anclas) == {"entity:sujeto", "entity:objeto"}


def test_sin_foto_conservada_el_sobre_no_inventa_ninguna_ancla():
    """AUSENCIA != CERO: sin snapshot no hay anclas, y no hay anclas falsas."""
    assert review_export.run_entity_anchors(
        _Resultado([_Corrida(snapshot=None)]), _documentos()
    ) == {}


# ===========================================================================
# 5. EL SOBRE: los documentos de procedencia, ACOTADOS A LO CITADO
# ===========================================================================

def _fragmento(fid: str, eid: str) -> dict:
    return {"fragment_id": fid, "episode_id": eid, "literal_text": f"texto {fid}"}


def test_el_sobre_publica_solo_la_procedencia_CITADA():
    corrida = _Corrida(
        asset={"source_asset_id": "src-b2"},
        episodes=[{"episode_id": "ep-1"}, {"episode_id": "ep-2"}],
        fragments=[_fragmento("ef-b2-1", "ep-1"), _fragmento("ef-otro", "ep-2")],
    )
    material = review_export.run_provenance_material(
        _Resultado([corrida]), _documentos(), {"claim-b2-1": _decision()}
    )
    assert [f["fragment_id"] for f in material["fragments"]] == ["ef-b2-1"]
    # Solo el episodio del fragmento citado. `ep-2` no entra por existir.
    assert [e["episode_id"] for e in material["episodes"]] == ["ep-1"]
    assert material["source_asset"] == {"source_asset_id": "src-b2"}


def test_el_paquete_del_sobre_es_el_que_apply_v3_admite():
    """Round-trip real: lo publicado entra en `ProvenanceBundle` sin adaptarlo.

    `ProvenanceBundle.from_dict` RECHAZA cualquier clave que no conozca, asi
    que esto no es una comprobacion de forma: es la unica manera de saber que
    el sobre y el nucleo hablan el mismo idioma sin un traductor en medio.
    """
    contexto = _contexto(**{review_plan.PROVENANCE_KEY: {
        "source_asset": {"source_asset_id": "src-b2"},
        "episodes": [{"episode_id": "ep-1"}],
        "fragments": [_fragmento("ef-b2-1", "ep-1")],
    }})
    paquete = review_plan.provenance_from_context(contexto)
    bundle = ProvenanceBundle.from_dict(paquete)
    assert bundle.fragment_ids == ("ef-b2-1",)
    assert bundle.source_asset == {"source_asset_id": "src-b2"}


def test_sin_bloque_de_procedencia_el_sobre_devuelve_None_y_no_un_vacio():
    """`None` = "esta corrida no publico ninguna". Un paquete vacio MENTIRIA.

    Con un dict vacio, `apply_v3` creeria que hay paquete, no emitiria
    `APPLY_PROVENANCE_NOT_PERSISTED` y dejaria las citas colgando en silencio
    — el falso exito exacto que este carril cierra.
    """
    assert review_plan.provenance_from_context(_contexto()) is None
    assert review_plan.provenance_from_context({
        review_plan.PROVENANCE_KEY: {"episodes": [], "fragments": []}
    }) is None


# ===========================================================================
# 6. EL VERIFICADOR DE EFECTOS, CALIBRADO
# ===========================================================================

class _Sesion:
    def __init__(self, respuestas):
        self._respuestas = respuestas

    def run(self, cypher, **params):
        for patron, filas in self._respuestas:
            if patron in cypher:
                return [dict(f) for f in filas(params)]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Driver:
    """Driver de MENTIRA que contesta lo que se le dice, y nada mas.

    No simula Neo4j: devuelve filas por patron de consulta. Es a proposito
    tonto — si supiera de grafos, el caso mediria el doble y no el sujeto.
    """

    def __init__(self, respuestas):
        self._respuestas = respuestas

    def session(self):
        return _Sesion(self._respuestas)


def _plan(ops: list) -> dict:
    return {"mutation_operations": ops}


OP_ASERCION = {
    "operation_id": "op:1:assert",
    "operation_type": "CREATE_ASSERTION",
    "assertion_id": "assert-b2-1",
    "idempotency_key": "clave-1",
    "evidence_fragment_ids": ["ef-b2-1"],
}
OP_ARISTA = {
    "operation_id": "op:1:project",
    "operation_type": "PROJECT_RELATION",
    "assertion_id": "assert-b2-1",
    "idempotency_key": "clave-2",
    "payload": {
        "predicate": "LEADS",
        "subject_entity_id": "entity:sujeto",
        "object_entity_id": "entity:objeto",
    },
}

_ASERCION_PRESENTE = ("V3Assertion", lambda p: [{"id": "assert-b2-1", "clave": "clave-1",
                                                 "status": "ASSERTED", "version": 1}])
_ARISTA_PRESENTE = ("-[r:LEADS]->", lambda p: [{"clave": "clave-2"}])
_TRAZA_COMPLETA = ("SUPPORTED_BY", lambda p: [{"fragment_id": "ef-b2-1"}])


def test_todo_materializado_da_completo():
    """EL GEMELO VERDE. Sin el, los rojos de abajo no significan nada."""
    informe = effects.verify_effects(
        _Driver([_TRAZA_COMPLETA, _ARISTA_PRESENTE, _ASERCION_PRESENTE]),
        _plan([OP_ASERCION, OP_ARISTA]), workspace=WS,
    )
    assert informe.complete, informe.to_dict()
    assert sorted(informe.observed) == ["op:1:assert", "op:1:project"]


def test_la_asercion_se_escribe_pero_la_arista_NO():
    """CONTROL 1: el writer de asercion funciona y el proyector no.

    El informe tiene que decir que falta LA ARISTA, no "algo falla".
    """
    informe = effects.verify_effects(
        _Driver([_TRAZA_COMPLETA, _ASERCION_PRESENTE]),  # sin arista
        _plan([OP_ASERCION, OP_ARISTA]), workspace=WS,
    )
    assert not informe.complete
    assert [m.operation_type for m in informe.missing] == ["PROJECT_RELATION"]
    assert informe.missing[0].code == effects.CODE_EFFECT_MISSING
    assert informe.missing[0].identity == "entity:sujeto -LEADS-> entity:objeto"
    # Y la afirmacion SI se vio: el informe distingue lo que esta de lo que no.
    assert informe.observed == ("op:1:assert",)


def test_la_arista_existe_pero_la_procedencia_NO():
    """CONTROL 2: no puede terminar como exito.

    La arista y la afirmacion estan; lo que no esta es el recorrido hasta la
    evidencia que la afirmacion CITA.
    """
    informe = effects.verify_effects(
        _Driver([_ARISTA_PRESENTE, _ASERCION_PRESENTE]),  # `trace_query` vacia
        _plan([OP_ASERCION, OP_ARISTA]), workspace=WS,
    )
    assert not informe.complete
    assert informe.missing == ()          # los efectos del plan SI estan
    assert [m.code for m in informe.provenance_missing] == [
        effects.CODE_PROVENANCE_UNREACHABLE
    ]
    assert "ef-b2-1" in informe.provenance_missing[0].detail


def test_la_arista_la_escribio_OTRA_operacion():
    """CONTROL 3: atribucion cruzada, y ROJO POR SU PROPIA CAUSA.

    La arista esta, entre los extremos correctos y con el predicado correcto.
    Lo unico que falla es de QUIEN es: la clave de idempotencia es de otra
    operacion. Si el verificador solo contase aristas, esto saldria verde.
    """
    ajena = ("-[r:LEADS]->", lambda p: [{"clave": "clave-de-otro-apply"}])
    informe = effects.verify_effects(
        _Driver([_TRAZA_COMPLETA, ajena, _ASERCION_PRESENTE]),
        _plan([OP_ASERCION, OP_ARISTA]), workspace=WS,
    )
    assert not informe.complete
    assert [m.code for m in informe.missing] == [effects.CODE_EFFECT_NOT_ATTRIBUTED]
    # NO es "no esta": la diferencia entre los dos codigos es el diagnostico.
    assert informe.missing[0].code != effects.CODE_EFFECT_MISSING


def test_un_tipo_de_operacion_sin_verificador_NO_pasa_de_largo():
    """Fallo CERRADO: lo que no se sabe mirar no se da por bueno."""
    informe = effects.verify_effects(
        _Driver([_ASERCION_PRESENTE]),
        _plan([{"operation_id": "op:raro", "operation_type": "TIPO_NUEVO",
                "idempotency_key": "k"}]),
        workspace=WS,
    )
    assert not informe.complete
    assert informe.missing[0].code == effects.CODE_TYPE_UNDECLARED
    assert set(effects.EFECTO_DECLARADO) == {
        "CREATE_ENTITY", "CREATE_ASSERTION", "PROJECT_RELATION",
        "LINK_EXISTING", "SUPERSEDE_ASSERTION", "UPDATE_ENTITY",
    }


def test_una_asercion_que_no_cita_evidencia_no_promete_procedencia():
    """No es un aprobado por ausencia: es que no habia nada que alcanzar."""
    sin_citas = copy.deepcopy(OP_ASERCION)
    sin_citas["evidence_fragment_ids"] = []
    informe = effects.verify_effects(
        _Driver([_ASERCION_PRESENTE]), _plan([sin_citas]), workspace=WS,
    )
    assert informe.complete
    assert informe.provenance_missing == ()


def test_la_supersesion_sin_cerrar_la_vigencia_no_cuenta_como_efecto():
    """Cada tipo tiene SU efecto: aqui el nodo existe y sigue sin cerrarse."""
    viva = ("V3Assertion", lambda p: [{"id": "assert-previa", "clave": "k",
                                       "status": "ASSERTED", "version": 1}])
    op = {"operation_id": "op:sup", "operation_type": "SUPERSEDE_ASSERTION",
          "assertion_id": "assert-previa", "idempotency_key": "k"}
    informe = effects.verify_effects(_Driver([viva]), _plan([op]), workspace=WS)
    assert not informe.complete
    assert "sin su vigencia cerrada" in informe.missing[0].detail

    cerrada = ("V3Assertion", lambda p: [{"id": "assert-previa", "clave": "k",
                                          "status": "SUPERSEDED", "version": 2}])
    assert effects.verify_effects(_Driver([cerrada]), _plan([op]),
                                  workspace=WS).complete

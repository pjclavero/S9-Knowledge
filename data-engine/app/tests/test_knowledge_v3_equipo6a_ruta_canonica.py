# -*- coding: utf-8 -*-
"""EQUIPO 6A: UNA sola ruta canonica de aplicacion, y lo que escribe se revierte.

QUE SE MIDE AQUI Y POR QUE
--------------------------
Un supervisor independiente aplico el MISMO plan con el MISMO esquema por los
dos mandos y midio dos productos distintos::

                     aristas   V3Source   V3Evidence
    ingest_cli --apply    18          1            7
    writer.cli  --apply    0          0            0

`writer.cli` escribia la asercion con `evidence_fragment_ids` apuntando a un
fragmento que no existia, sin `SUPPORTED_BY`, y reportaba `APPLIED` **sin una
sola advertencia**.

Estas pruebas fijan las propiedades que cierran eso. Cada una puede ponerse
ROJA: no comprueban «la suite pasa», comprueban un efecto observable.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.engine import findings as F  # noqa: E402
from knowledge_v3.engine import promotion as P  # noqa: E402
from knowledge_v3.engine.decision import ClaimDecision  # noqa: E402
from knowledge_v3.writer import apply as apply_mod  # noqa: E402
from knowledge_v3.writer.apply_identity import compute_apply_id  # noqa: E402

APP_DIR = Path(__file__).resolve().parent.parent
V3 = APP_DIR / "knowledge_v3"


# ---------------------------------------------------------------------------
# 1. NO HAY DOS DEFINICIONES DE APLICAR
# ---------------------------------------------------------------------------
def _llamadas(ruta: Path) -> set:
    """Nombres de funcion llamados en un modulo. AST, no `grep`.

    Contar apariciones de texto daria falsos negativos (un alias, un import
    reordenado) y falsos positivos (una mencion en un comentario). Se parsea.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            if isinstance(f, ast.Name):
                nombres.add(f.id)
            elif isinstance(f, ast.Attribute):
                nombres.add(f.attr)
    return nombres


def test_las_dos_rutas_llaman_a_la_misma_funcion_canonica():
    """Ni el pipeline ni `writer.cli` implementan el apply: lo piden."""
    for ruta in (V3 / "pipeline" / "pipeline.py", V3 / "writer" / "cli.py"):
        assert "apply_v3" in _llamadas(ruta), (
            f"{ruta.name} no llama a apply_v3: si vuelve a implementar el "
            "apply por su cuenta, vuelven a existir dos definiciones"
        )


def test_solo_la_ruta_canonica_persiste_procedencia():
    """`persist_provenance` se invoca desde UN solo sitio del producto.

    Es la comprobacion estructural del defecto: mientras el volcado de
    procedencia vivia dentro del pipeline, la otra ruta no podia alcanzarlo.
    """
    invocadores = []
    for ruta in V3.rglob("*.py"):
        if "tests" in ruta.parts or "benchmarks" in ruta.parts:
            continue
        if "persist_provenance" in _llamadas(ruta):
            invocadores.append(ruta.relative_to(V3).as_posix())
    assert invocadores == ["writer/apply.py"], (
        f"la procedencia se persiste desde {invocadores}; debe hacerse solo "
        "desde la ruta canonica, o las rutas vuelven a divergir"
    )


# ---------------------------------------------------------------------------
# 2. UN APPLY SIN PROCEDENCIA LO DICE, Y DICE QUE REFERENCIAS DEJA COLGANDO
# ---------------------------------------------------------------------------
class _ResultadoFalso:
    ok = True
    mode = "APPLY"
    rollback = None


class _WriterFalso:
    """Un writer que dice haber aplicado. No toca ninguna base."""

    resolved_driver = None

    def __init__(self):
        self.recibido = None

    def write(self, plan_doc, request):
        self.recibido = (plan_doc, request)
        return _ResultadoFalso()


class _Peticion:
    workspace = "ws-prueba"
    current_snapshot_id = "snapshot:x"


PLAN_MINIMO = {
    "plan_hash": {"algorithm": "sha256", "value": "a" * 64},
    "plan_id": "plan:estable",
    "partida_id": None,
    "mutation_operations": [
        {
            "operation_id": "op:1",
            "assertion_id": "assertion:1",
            "payload": {"evidence_fragment_ids": ["ef-d4b8", "ef-99aa"]},
        }
    ],
}


def test_apply_sin_paquete_declara_las_referencias_colgantes():
    """El `APPLIED` silencioso ya no existe: se nombra lo que queda colgando."""
    salida = apply_mod.apply_v3(
        PLAN_MINIMO, _Peticion(), writer=_WriterFalso(), provenance=None
    )
    assert apply_mod.CODE_PROVENANCE_NOT_PERSISTED in salida.codes
    # NO basta con que haya un codigo: tiene que decir CUALES.
    assert set(salida.dangling_fragment_ids) == {"ef-d4b8", "ef-99aa"}
    assert "ef-d4b8" in salida.notes[0]["detail"]


def test_paquete_incompleto_sigue_declarando_lo_que_falta():
    """Traer paquete no es traer EL paquete: la diferencia se mide.

    Un paquete que solo cubre una de las dos evidencias citadas deja la otra
    colgando, y eso no puede leerse como exito limpio.
    """
    paquete = apply_mod.ProvenanceBundle.of(fragments=[{"fragment_id": "ef-d4b8"}])
    writer = _WriterFalso()

    class _ConDriver(_WriterFalso):
        resolved_driver = object()

    llamado = {}

    def _fake_persist(driver, **kw):
        llamado.update(kw)

        class _R:
            def to_dict(self):
                return {"ok": True}
        return _R()

    original = apply_mod.persist_provenance
    apply_mod.persist_provenance = _fake_persist
    try:
        salida = apply_mod.apply_v3(
            PLAN_MINIMO, _Peticion(), writer=_ConDriver(), provenance=paquete
        )
    finally:
        apply_mod.persist_provenance = original
    assert apply_mod.CODE_PROVENANCE_PERSISTED in salida.codes
    assert salida.dangling_fragment_ids == ("ef-99aa",), (
        "la evidencia citada y NO traida en el paquete tiene que declararse"
    )
    # La marca de propiedad viaja al volcado: sin ella el barrido no acota.
    assert llamado["apply_id"] == salida.apply_id
    assert writer.recibido is None  # el writer falso sin driver no se uso


# ---------------------------------------------------------------------------
# 3. LA IDENTIDAD DEL APPLY Y EL RELOJ
# ---------------------------------------------------------------------------
def test_apply_id_es_funcion_del_plan_y_no_del_reloj():
    """A IGUALDAD de plan, el `apply_id` no se mueve. Es la mitad cierta."""
    a = compute_apply_id(workspace="w", snapshot_id="s", plan_hash="h", partida_id=None)
    b = compute_apply_id(workspace="w", snapshot_id="s", plan_hash="h", partida_id=None)
    assert a == b


def test_plan_hash_distinto_mueve_el_apply_id():
    """La otra mitad, la que nadie decia: `created_at` entra en `plan_hash`.

    Dos ejecuciones sin `--ahora` producen planes con `created_at` distinto,
    luego `plan_hash` distinto, luego `apply_id` distinto. La afirmacion «la
    misma cadena en cualquier base y tras un restore» solo vale con el reloj
    fijado, y eso es lo que la carencia del informe declara.
    """
    a = compute_apply_id(workspace="w", snapshot_id="s", plan_hash="h1", partida_id=None)
    b = compute_apply_id(workspace="w", snapshot_id="s", plan_hash="h2", partida_id=None)
    assert a != b


def test_plan_id_es_el_campo_contractual_pero_NO_esta_firmado():
    """La carencia, fijada como prueba y no como nota al pie.

    `plan_id` es el unico campo del contrato congelado que nombra la identidad
    logica del plan y el unico que no depende del reloj -- y el propio contrato
    lo deja FUERA de la firma. Por eso se publica y NO se decide con el. Si
    alguien lo saca de `UNSIGNED_FIELDS`, esta prueba se pone roja y hay que
    revisar la decision, no el test.
    """
    from knowledge_v3.writer.view import UNSIGNED_FIELDS

    assert "plan_id" in UNSIGNED_FIELDS
    assert "created_at" in UNSIGNED_FIELDS
    # Y el view --lo unico que el gate y el ejecutor ven-- no lo lleva.
    from knowledge_v3.writer.view import SignedView
    assert not hasattr(SignedView("w", "s", "c", "e", "o", "g", "col", "a",
                                  {}, "exp", (), (), (), True, {}, {}, {}),
                       "plan_id")


# ---------------------------------------------------------------------------
# 4. LA SALIDA DE `REVIEW`: PROMOCION HUMANA, FAIL-CLOSED
# ---------------------------------------------------------------------------
def _decision(codigo, severidad, decision, **kw):
    campos = dict(
        predicate="MEMBER_OF", direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:a", object_entity_id="entity:b",
    )
    campos.update(kw)
    return ClaimDecision(
        claim_id="claim:1",
        decision=decision,
        findings=[F.Finding(axis=F.AXIS_EVIDENCE, severity=severidad,
                            canonical="REVIEW_EVIDENCE", code=codigo)],
        **campos,
    )


def _firma(codes, claim_id="claim:1"):
    return P.ClaimPromotion(claim_id=claim_id, reason_codes=tuple(codes),
                            promoted_by="pjc", promoted_at="2026-09-07T12:00:00Z")


def test_promocion_convierte_un_review_en_accept():
    d = _decision("EXTRACTOR_REQUESTED_REVIEW", F.Severity.REVIEW, "REVIEW")
    _, informe = P.apply_promotions([d], [_firma(["EXTRACTOR_REQUESTED_REVIEW"])])
    assert informe[0]["code"] == P.CODE_APPLIED
    assert d.decision == "ACCEPT"
    assert d.writes, "una promocion que no llega a escribir no es una salida"
    # El rastro sobrevive: el motivo no se borra, se marca como asumido.
    assert any(f.code.startswith(P.PROMOTED_PREFIX) for f in d.findings)


def test_una_promocion_NO_puede_tapar_un_reject():
    """La propiedad que hace seguro el mecanismo, y su rojo.

    La decision se RECALCULA sobre lo que queda. Un hallazgo `REJECT` no es
    promovible, asi que sigue ahi y la decision no puede subir a `ACCEPT`.
    """
    d = ClaimDecision(
        claim_id="claim:1", decision="REVIEW",
        findings=[
            F.Finding(axis=F.AXIS_EVIDENCE, severity=F.Severity.REVIEW,
                      canonical="REVIEW_EVIDENCE", code="MOTIVO"),
            F.Finding(axis=F.AXIS_INPUT, severity=F.Severity.REJECT,
                      canonical="REJECT_INVALID", code="ENTRADA_INVALIDA"),
        ],
        predicate="MEMBER_OF", direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:a", object_entity_id="entity:b",
    )
    # Nota: con un REJECT presente el motor ya no lo habria dejado en REVIEW;
    # se fuerza el estado para probar que ni forzandolo se cuela un ACCEPT.
    P.apply_promotions([d], [_firma(["MOTIVO"])])
    assert d.decision == "REJECT_INVALID"
    assert not d.writes


def test_una_firma_caduca_no_se_aplica():
    """Los motivos cambiaron: la firma cubre otra situacion."""
    d = _decision("MOTIVO_NUEVO", F.Severity.REVIEW, "REVIEW")
    _, informe = P.apply_promotions([d], [_firma(["MOTIVO_VIEJO"])])
    assert informe[0]["code"] == P.CODE_STALE
    assert d.decision == "REVIEW", "una firma caduca no puede mover la decision"


def test_no_se_promueve_un_claim_incompleto():
    """Defecto MEDIDO en la cadena real, no imaginado.

    Promover un claim sin `object_entity_id` producia un ACCEPT que el
    planificador materializaba y que el contrato congelado rechazaba
    (`decisions[i].object_entity_id: None is not of type 'string'`), reventando
    la corrida DESPUES de que el operador ya hubiera firmado.
    """
    d = _decision("MOTIVO", F.Severity.REVIEW, "REVIEW", object_entity_id=None)
    _, informe = P.apply_promotions([d], [_firma(["MOTIVO"])])
    assert informe[0]["code"] == P.CODE_INCOMPLETE
    assert "object_entity_id" in informe[0]["detail"]
    assert d.decision == "REVIEW"


def test_lo_no_promovible_se_lista_marcado_y_no_se_oculta():
    d = _decision("MOTIVO", F.Severity.REVIEW, "REVIEW", object_entity_id=None)
    filas = P.pending_rows([d])
    assert len(filas) == 1, "ocultar lo no promovible haria creer que no existe"
    assert filas[0]["promovible"] is False
    assert filas[0]["no_promovible_por"] == ["object_entity_id"]


def test_no_se_promueve_lo_que_no_esta_en_review():
    d = _decision("MOTIVO", F.Severity.WARN, "ACCEPT")
    _, informe = P.apply_promotions([d], [_firma(["MOTIVO"])])
    assert informe[0]["code"] == P.CODE_NOT_IN_REVIEW


def test_el_documento_de_promociones_rechaza_otro_contrato():
    """Fail-closed: un documento ajeno no autoriza a promover nada."""
    with pytest.raises(ValueError, match="se esperaba"):
        P.PromotionLedger.from_dict({"contract": "otra-cosa/v1"})


def test_una_promocion_con_campos_desconocidos_se_rechaza():
    with pytest.raises(ValueError, match="campos desconocidos"):
        P.ClaimPromotion.from_dict({
            "claim_id": "c", "reason_codes": ["x"], "promoted_by": "p",
            "promoted_at": "t", "inventado": 1,
        })


# ---------------------------------------------------------------------------
# 5. EL `elementId` NO SALE COMO IDENTIDAD AL OPERADOR
# ---------------------------------------------------------------------------
def test_created_ids_del_informe_no_lleva_element_ids():
    """`cypher.create_relation` termina en `RETURN elementId(r)`.

    Ese valor llegaba crudo a `write.created_ids`, mezclado con los
    `entity_id`/`assertion_id` y sin forma de distinguirlo. Se comprueba que la
    consulta sigue devolviendo `elementId` (para que la prueba no se ponga
    verde por el motivo equivocado) y que el informe del operador ya no lo
    publica como id creado.
    """
    from knowledge_v3.pipeline.ingest_cli import _creado_durable
    from knowledge_v3.writer import cypher
    from knowledge_v3.writer.rollback import RollbackDocument, RollbackInstruction

    q = cypher.create_relation("ALLY_OF", "entity:a", "entity:b", "ws", {}, None)
    assert "elementId(r)" in q.cypher, (
        "si la consulta deja de devolver elementId, esta prueba ya no mide "
        "nada: revisa el motivo, no el test"
    )

    doc = RollbackDocument(workspace="ws", snapshot_id="s", plan_hash="h")
    doc.instructions.append(RollbackInstruction(
        operation_id="op:1", action="DELETE_RELATIONSHIP", target_id="entity:a",
        detail={"subject": "entity:a", "predicate": "ALLY_OF",
                "object": "entity:b", "workspace": "ws", "partida_id": None,
                "element_id_at_write": "4:abc123:7"},
    ))

    class _Escritura:
        rollback = doc

    creado = _creado_durable(_Escritura())
    assert creado[0]["identidad_durable"] == {
        "workspace": "ws", "subject_id": "entity:a", "predicate": "ALLY_OF",
        "object_id": "entity:b", "partida_id": None,
    }
    # El elementId se conserva, pero con el nombre que dice lo que es.
    assert creado[0]["element_id_at_write"] == "4:abc123:7"
    assert "4:abc123:7" not in json.dumps(creado[0]["identidad_durable"])


# ---------------------------------------------------------------------------
# 6. UN PARAMETRO OPCIONAL QUE UNA RUTA PASA Y OTRA NO **ES** UNA SEGUNDA RUTA
# ---------------------------------------------------------------------------
def test_reconcile_exige_los_nombres_de_mencion():
    """Hallazgo de 6C (tanda 5), y de la misma familia que este carril.

    `entity_decisions.reconcile` aceptaba `names_by_mention` como OPCIONAL.
    `ingest_cli.main` se lo pasaba; cualquier otra ruta que no lo hiciera
    dejaba cada decision con `name = None`, y `approved_snapshot_entities` lo
    rellenaba con el `entity_id`: entidades creadas con
    `name = "entity:prov:a1b2..."`, innombrables, y la ingesta SIGUIENTE en
    ese ambito volvia entera a `REVIEW_ENTITY`.

    El fallo no aparecia en la corrida que lo causaba sino en la siguiente, que
    es la variante mas dificil de ver de «la guarda existe pero el dato no
    llega». Un parametro opcional que una ruta pasa y otra no ES una segunda
    ruta, que es exactamente lo que este carril viene a eliminar: ahora hay que
    declararlo, aunque sea `{}`.
    """
    import inspect

    from knowledge_v3.pipeline import entity_decisions

    firma = inspect.signature(entity_decisions.reconcile)
    parametro = firma.parameters["names_by_mention"]
    assert parametro.default is inspect.Parameter.empty, (
        "names_by_mention volvio a tener valor por defecto: una ruta que se lo "
        "salte creara entidades innombrables y la ingesta siguiente volvera a "
        "REVIEW_ENTITY sin que nada lo diga"
    )
    with pytest.raises(TypeError):
        entity_decisions.reconcile(
            resolutions=(), graph_entity_ids=(), workspace="ws",
            source_path="f.md",
        )


def test_una_alta_sin_nombre_se_declara_como_carencia():
    """No basta con exigir el dato: la consecuencia tiene que verse.

    Pasar `{}` es legitimo (puede no haber nombre), pero entonces el alta usara
    su propio `entity_id` como `name`, y eso se DICE en el documento en vez de
    descubrirse una ingesta despues.
    """
    from knowledge_v3.pipeline import entity_decisions

    ledger = entity_decisions.reconcile(
        resolutions=[{
            "action": "CREATE_NEW",
            "resolution_id": "r1", "mention_ids": ["m1"],
            "assigned_entity_id": "entity:prov:a1b2", "entity_type": "Faction",
            "reason_codes": [],
        }],
        graph_entity_ids=(), workspace="ws", source_path="f.md",
        names_by_mention={},
        catalog_by_entity={},
    )
    codigos = [c["code"] for c in ledger.carencias]
    assert "ALTA_SIN_NOMBRE_OBSERVADO" in codigos
    assert "entity:prov:a1b2" in " ".join(c["detail"] for c in ledger.carencias)


# ---------------------------------------------------------------------------
# 7. LA MARCA DE PROPIEDAD, COMPLETA (peticiones de 6B)
# ---------------------------------------------------------------------------
def _view_de_prueba():
    from knowledge_v3.writer.view import SignedView
    return SignedView(
        workspace="ws", snapshot_id="snapshot:s", contract_version="v3-internal-v1",
        engine_version="e", ontology_version="o", game_profile="g",
        collection_id="col", source_asset_id="sa", source_hash={},
        expires_at="2099-01-01T00:00:00Z", decisions=(), mutation_operations=(),
        validator_chain=(), approved=True, approved_by={},
        plan_hash={"algorithm": "sha256", "value": "a" * 64},
        decision_hash={}, partida_id=None,
    )


def test_el_documento_de_rollback_lleva_apply_id_en_la_raiz():
    """Petición de 6B. Sin barrido tambien: es el caso que le importa.

    `PX` ya no se lee de una lista del documento: se mide en el grafo por la
    marca de creacion. Si el `apply_id` solo viviera dentro del detalle de la
    instruccion de barrido, un apply que no emite barrido dejaria a quien
    clasifica SIN `PX` medible, y caeria al radio POR NOMBRE -- justo el
    defecto que esta tanda cerro. Aqui se construye un documento SIN una sola
    instruccion y se exige que la raiz ya lo lleve.
    """
    from knowledge_v3.writer.rollback import build_rollback

    doc = build_rollback(_view_de_prueba(), [])
    assert not doc.instructions, "el caso que importa es el documento sin barrido"
    assert doc.apply_id is not None
    assert doc.to_dict()["apply_id"] == doc.apply_id
    # Y es EL MISMO que estampan los nodos de procedencia: una sola identidad
    # en todo el grafo, no dos que haya que reconciliar.
    assert doc.apply_id == compute_apply_id(
        workspace="ws", snapshot_id="snapshot:s", plan_hash="a" * 64,
        partida_id=None,
    )


def test_la_marca_de_idempotencia_estampa_apply_id():
    """Petición de 6B: `V3AppliedOperation` llevaba solo `plan_hash`.

    Atribuir una marca colgante por `plan_hash` es MEDIA identidad: dos applies
    del mismo plan sobre snapshots o ambitos distintos lo comparten. Con
    `apply_id` la marca lleva la misma identidad que los nodos de procedencia.
    """
    from knowledge_v3.writer import cypher

    q = cypher.claim_applied_operation(
        "ws", "idem:k", "h", "op:1", "2026-09-07T12:00:00Z", "tok",
        partida_id=None, apply_id="apply:" + "0" * 32,
    )
    assert "op.apply_id = $apply_id" in q.cypher
    assert q.params["apply_id"] == "apply:" + "0" * 32
    # ON CREATE SET, no SET: una marca reclamada antes conserva el apply_id de
    # QUIEN LA CREO, que es la pregunta que el rollback hace.
    assert "ON CREATE SET" in q.cypher
    assert " SET op.apply_id" not in q.cypher.replace("ON CREATE SET", "@")


def test_la_ruta_canonica_entrega_el_plan_INTACTO_al_writer():
    """Aviso de 6C: `known_from_session` viaja en el `payload` de cada operacion
    (solo en ambito PARTIDA) y **entra en la `idempotency_key`**.

    Si la ruta canonica reescribiera el plan --normalizando, copiando campos
    conocidos, filtrando payloads-- ese valor se perderia y el sintoma seria
    `EXEC_REVELACION_NO_DECLARADA`, lejos de la causa. La propiedad que lo
    impide es sencilla y se comprueba, no se presume: `apply_v3` entrega al
    writer EL MISMO objeto que recibio, sin tocarlo.
    """
    import copy

    plan = copy.deepcopy(PLAN_MINIMO)
    plan["partida_id"] = "partida:007"
    plan["mutation_operations"][0]["payload"]["known_from_session"] = "sesion:42"
    antes = copy.deepcopy(plan)

    writer = _WriterFalso()
    apply_mod.apply_v3(plan, _Peticion(), writer=writer, provenance=None)

    entregado, _ = writer.recibido
    assert entregado is plan, "el writer tiene que recibir EL MISMO objeto"
    assert plan == antes, "la ruta canonica no puede modificar el plan"
    assert (entregado["mutation_operations"][0]["payload"]["known_from_session"]
            == "sesion:42")


def test_la_ruta_canonica_lee_el_ambito_del_plan_y_no_lo_inventa():
    """6C: el contexto de partida sigue pasando por donde pasaba.

    `apply_v3` no recibe `partida_id` por parametro: lo LEE del plan, con el
    mismo criterio que `SignedView.of` (el bloque `scope` manda sobre la raiz).
    Asi no puede haber dos verdades sobre el ambito de un mismo apply.
    """
    plan = dict(PLAN_MINIMO, partida_id="partida:raiz",
                scope={"partida_id": "partida:scope", "game_id": "ws"})
    assert apply_mod.plan_partida_id(plan) == "partida:scope"
    assert apply_mod.plan_partida_id(dict(PLAN_MINIMO, partida_id="partida:raiz")) \
        == "partida:raiz"
    assert apply_mod.plan_partida_id(PLAN_MINIMO) is None

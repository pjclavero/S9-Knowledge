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
    with pytest.raises(ValueError):
        P.PromotionLedger.from_dict({"contract": "otra-cosa/v1"})


def test_una_promocion_con_campos_desconocidos_se_rechaza():
    with pytest.raises(ValueError):
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

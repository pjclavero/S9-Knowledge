# -*- coding: utf-8 -*-
"""Promocion humana de un `REVIEW`. La salida que `REVIEW` no tenia.

EL DEFECTO QUE CIERRA
---------------------
El motor mandaba a `REVIEW` una relacion --medido: una a 0,595-- y **no habia
mando para promoverla**. `--aprobar-alta` solo aprueba altas de ENTIDAD
(`entity_decisions.approve` rechaza cualquier id que no sea un
`CREATE_ENTITY_REQUIRED`). Para el operador, revisar era solo leer: el paquete
de revision se exportaba, una persona decidia `APPROVE` en el visor, y esa
decision no tenia **ningun camino de vuelta** ni al documento de decisiones ni
al writer. `REVIEW` era un estado terminal.

COMO SE PROMUEVE, Y POR QUE ASI
-------------------------------
Una promocion **no fija una decision**: retira hallazgos concretos. El humano
dice «he mirado estos motivos de revision y los asumo», y la decision se
**RECALCULA** con `findings.decision_for` sobre lo que queda.

Esa diferencia es toda la seguridad del mecanismo:

* Un hallazgo `REJECT` o `ABSTAIN` **sigue ahi**, asi que una promocion no
  puede convertir en `ACCEPT` algo que el motor invalido o sobre lo que se
  abstuvo. La promocion no es un comodin: es una firma sobre unos motivos.
* Los hallazgos retirados no desaparecen: se sustituyen por un
  `HUMAN_PROMOTED_<codigo>` de gravedad `WARN`, asi que el `reason_codes` del
  plan --y por tanto el `decision_hash` y el `plan_hash`-- **cambia**. Un plan
  con promociones no puede confundirse con uno sin ellas.
* La promocion declara los motivos que el humano VIO. Si el motor ya no
  produce esos mismos motivos (la fuente cambio, el grafo cambio, el perfil
  cambio), la promocion se rechaza como CADUCA (`PROMOTION_STALE`) y no se
  aplica: una firma sobre una situacion no cubre otra.
* Una promocion sobre un claim que no esta en `REVIEW` se rechaza. Aprobar lo
  ya aprobado seria inocuo, pero silenciarlo esconde una promocion escrita
  contra el claim equivocado.

LO QUE NO HACE
--------------
No escribe, no abre conexiones, no toca el gate del writer y no relaja ninguna
garantia de escritura: cuando termina, un `ACCEPT` promovido recorre
exactamente el mismo camino que cualquier otro `ACCEPT` --planificador,
admision, gate triple, transaccion-- y puede seguir siendo bloqueado por
cualquiera de ellos. En particular, un claim con `CONFLICT_WITH_EXISTING`
promovido deja el plan SIN aprobar (`planner.no_conflict_accepted`), que es lo
correcto: promover un motivo de revision no resuelve una contradiccion con el
grafo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from . import findings as F

#: Contrato del documento de promociones. Es un documento del OPERADOR, no del
#: motor, y por eso vive fuera del contrato congelado `v3-internal-v1`.
PROMOTIONS_CONTRACT = "claim-promotions/equipo6a-v1"

#: Solo desde aqui se promueve. Ver el docstring: no es una restriccion de
#: comodidad, es la que impide que una firma tape un `REJECT`.
PROMOTABLE_FROM = "REVIEW"

#: Prefijo del hallazgo que sustituye a cada motivo de revision asumido.
PROMOTED_PREFIX = "HUMAN_PROMOTED_"

CODE_APPLIED = "PROMOTION_APPLIED"
CODE_NOT_IN_REVIEW = "PROMOTION_NOT_IN_REVIEW"
CODE_STALE = "PROMOTION_STALE"
CODE_UNKNOWN_CLAIM = "PROMOTION_UNKNOWN_CLAIM"
CODE_NO_REVIEW_FINDINGS = "PROMOTION_NO_REVIEW_FINDINGS"
CODE_INCOMPLETE = "PROMOTION_INCOMPLETE_CLAIM"


@dataclass(frozen=True)
class ClaimPromotion:
    """Una firma humana sobre unos motivos de revision concretos."""

    claim_id: str
    #: Codigos DESCRIPTIVOS de los hallazgos REVIEW que el humano asume. Es la
    #: atadura: si el motor ya no produce exactamente estos, la firma no cubre
    #: la situacion actual.
    reason_codes: tuple
    promoted_by: str
    promoted_at: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "reason_codes": sorted(self.reason_codes),
            "promoted_by": self.promoted_by,
            "promoted_at": self.promoted_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, doc: dict) -> "ClaimPromotion":
        faltan = [k for k in ("claim_id", "reason_codes", "promoted_by",
                              "promoted_at") if not doc.get(k)]
        if faltan:
            raise ValueError(f"promocion incompleta, faltan {faltan}: {doc!r}")
        desconocidos = sorted(
            set(doc) - {"claim_id", "reason_codes", "promoted_by", "promoted_at", "note"}
        )
        if desconocidos:
            raise ValueError(f"promocion con campos desconocidos: {desconocidos}")
        return cls(
            claim_id=str(doc["claim_id"]),
            reason_codes=tuple(sorted(str(c) for c in doc["reason_codes"])),
            promoted_by=str(doc["promoted_by"]),
            promoted_at=str(doc["promoted_at"]),
            note=str(doc.get("note") or ""),
        )


@dataclass
class PromotionLedger:
    """Documento de promociones del operador."""

    workspace: str = ""
    partida_id: Optional[str] = None
    source_path: str = ""
    generated_at: str = ""
    promotions: list = field(default_factory=list)
    #: Lo que el motor mando a REVIEW en la corrida que genero este documento.
    #: Es lo que el revisor MIRA: sin esto tendria que abrir el informe.json.
    pending: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "contract": PROMOTIONS_CONTRACT,
            "workspace": self.workspace,
            "partida_id": self.partida_id,
            "source_path": self.source_path,
            "generated_at": self.generated_at,
            "promotions": [p.to_dict() for p in self.promotions],
            "pending": [dict(p) for p in self.pending],
            "totals": {
                "pendientes": len(self.pending),
                "promovidas": len(self.promotions),
            },
        }

    @classmethod
    def from_dict(cls, doc: dict) -> "PromotionLedger":
        if not isinstance(doc, dict):
            raise ValueError("el documento de promociones no es un objeto JSON")
        contrato = doc.get("contract")
        if contrato != PROMOTIONS_CONTRACT:
            raise ValueError(
                f"documento de promociones con contrato {contrato!r}; se "
                f"esperaba {PROMOTIONS_CONTRACT!r}"
            )
        return cls(
            workspace=doc.get("workspace") or "",
            partida_id=doc.get("partida_id"),
            source_path=doc.get("source_path") or "",
            generated_at=doc.get("generated_at") or "",
            promotions=[ClaimPromotion.from_dict(p) for p in doc.get("promotions") or []],
            pending=[dict(p) for p in doc.get("pending") or []],
        )

    def by_claim(self) -> dict:
        return {p.claim_id: p for p in self.promotions}


def review_reason_codes(decision: Any) -> list:
    """Codigos DESCRIPTIVOS de los hallazgos con gravedad REVIEW.

    Se usan los descriptivos (`code`), no los canonicos: dos motivos distintos
    pueden compartir canonico (`REVIEW_ENTITY`), y firmar sobre el canonico
    dejaria que una promocion cubriera un motivo que el humano no vio.
    """
    return sorted(
        f.code for f in decision.findings if f.severity is F.Severity.REVIEW
    )


def pending_rows(decisions: Sequence[Any]) -> list:
    """Lo promovible de una corrida, listo para que un humano lo lea.

    Es lo que hace que revisar deje de ser «abre el informe.json y busca»: el
    documento de promociones trae ya el claim, sus motivos y su confianza.
    """
    filas = []
    for d in decisions:
        if d.decision != PROMOTABLE_FROM:
            continue
        # Lo INCOMPLETO se lista igual --el revisor tiene derecho a verlo--
        # pero marcado: promoverlo produciria un ACCEPT que el contrato
        # congelado rechaza. Ocultarlo seria peor: pareceria que no existe.
        falta = [
            nombre for nombre, valor in (
                ("predicate", d.predicate), ("direction", d.direction),
                ("subject_entity_id", d.subject_entity_id),
                ("object_entity_id", d.object_entity_id),
            ) if not valor
        ]
        filas.append({
            "promovible": not falta,
            "no_promovible_por": falta,
            "claim_id": d.claim_id,
            "decision": d.decision,
            "predicate": d.predicate,
            "direction": d.direction,
            "subject_entity_id": d.subject_entity_id,
            "object_entity_id": d.object_entity_id,
            "confidence": d.confidence,
            "reason_codes": review_reason_codes(d),
            "explicacion": d.explanation(),
        })
    return filas


def _promoted_finding(original: Any, promotion: ClaimPromotion):
    """El hallazgo que sustituye a uno asumido por un humano.

    Baja a `WARN` --no desaparece-- para que la explicacion siga contando lo
    que paso y para que `reason_codes` cambie de forma visible. El canonico se
    retira: el hallazgo ya no puede ser el motivo canonico de una revision que
    una persona ha cerrado.
    """
    return F.Finding(
        axis=original.axis,
        severity=F.Severity.WARN,
        canonical=None,
        code=PROMOTED_PREFIX + original.code,
        detail=(
            f"promovido por {promotion.promoted_by} el {promotion.promoted_at}"
            + (f": {promotion.note}" if promotion.note else "")
            + (f" [motivo original: {original.detail}]" if original.detail else "")
        ),
    )


def apply_promotions(
    decisions: Sequence[Any], promotions: Iterable[ClaimPromotion]
) -> tuple:
    """Aplica las promociones y RECALCULA cada decision. Fail-closed.

    Devuelve `(decisiones, informe)`. El informe lleva una entrada por
    promocion --aplicada o rechazada, con su motivo-- para que nadie tenga que
    deducir por que una firma no surtio efecto.

    Las decisiones se modifican EN EL SITIO (son las mismas instancias que el
    motor acaba de construir y aun no ha usado para nada): no hay dos listas
    que puedan divergir.
    """
    firmas = {p.claim_id: p for p in promotions}
    if not firmas:
        return list(decisions), []

    informe: list = []
    por_claim = {d.claim_id: d for d in decisions}

    for claim_id in sorted(firmas):
        promocion = firmas[claim_id]
        decision = por_claim.get(claim_id)
        if decision is None:
            informe.append({
                "claim_id": claim_id, "code": CODE_UNKNOWN_CLAIM,
                "detail": "la promocion nombra un claim que esta corrida no "
                          "produjo; no se aplica nada",
            })
            continue
        if decision.decision != PROMOTABLE_FROM:
            informe.append({
                "claim_id": claim_id, "code": CODE_NOT_IN_REVIEW,
                "detail": f"la decision actual es {decision.decision}, no "
                          f"{PROMOTABLE_FROM}: solo se promueve lo que esta en "
                          "revision",
            })
            continue
        # NO SE PROMUEVE LO QUE NO SE PUEDE ESCRIBIR. Medido en la cadena
        # real: promover un claim sin `object_entity_id` producia un ACCEPT
        # que el planificador materializaba y que el CONTRATO CONGELADO
        # rechazaba (`decisions[i].object_entity_id: None is not of type
        # string`) -- una excepcion a mitad de la corrida, despues de que el
        # operador ya hubiera firmado. La promocion se niega ANTES, y dice
        # que le falta: una firma no puede crear una escritura imposible.
        incompletos = [
            nombre for nombre, valor in (
                ("predicate", decision.predicate),
                ("direction", decision.direction),
                ("subject_entity_id", decision.subject_entity_id),
                ("object_entity_id", decision.object_entity_id),
            ) if not valor
        ]
        if incompletos:
            informe.append({
                "claim_id": claim_id, "code": CODE_INCOMPLETE,
                "detail": "el claim no esta completo para escribirse: le "
                          f"falta {incompletos}. Un ACCEPT sobre esto no "
                          "valida contra el contrato congelado, asi que la "
                          "promocion no se aplica",
            })
            continue
        actuales = review_reason_codes(decision)
        if not actuales:
            informe.append({
                "claim_id": claim_id, "code": CODE_NO_REVIEW_FINDINGS,
                "detail": "no hay hallazgos de gravedad REVIEW que retirar",
            })
            continue
        if actuales != sorted(promocion.reason_codes):
            # CADUCA. La firma cubre unos motivos y el motor produce otros: no
            # es la misma situacion, y una firma no se extrapola.
            informe.append({
                "claim_id": claim_id, "code": CODE_STALE,
                "detail": "los motivos de revision han cambiado desde la "
                          f"promocion: firmados {sorted(promocion.reason_codes)}, "
                          f"observados {actuales}. Vuelve a revisar",
            })
            continue

        decision.findings = [
            _promoted_finding(f, promocion)
            if f.severity is F.Severity.REVIEW else f
            for f in decision.findings
        ]
        # LA DECISION SE RECALCULA, NO SE FIJA. Si queda un REJECT o un
        # ABSTAIN, la promocion no lo tapa.
        decision.decision = F.decision_for(decision.findings)
        informe.append({
            "claim_id": claim_id, "code": CODE_APPLIED,
            "detail": f"promovido por {promocion.promoted_by}; motivos "
                      f"retirados {actuales}; decision recalculada -> "
                      f"{decision.decision}",
            "decision": decision.decision,
            "promoted_by": promocion.promoted_by,
            "reason_codes_retirados": actuales,
        })
    return list(decisions), informe


__all__ = [
    "CODE_APPLIED",
    "CODE_INCOMPLETE",
    "CODE_NOT_IN_REVIEW",
    "CODE_NO_REVIEW_FINDINGS",
    "CODE_STALE",
    "CODE_UNKNOWN_CLAIM",
    "PROMOTABLE_FROM",
    "PROMOTED_PREFIX",
    "PROMOTIONS_CONTRACT",
    "ClaimPromotion",
    "PromotionLedger",
    "apply_promotions",
    "pending_rows",
    "review_reason_codes",
]

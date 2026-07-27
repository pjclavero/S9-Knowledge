# -*- coding: utf-8 -*-
"""Eje de CONTRADICCION: que dice ya el grafo sobre esta misma pareja.

Regla dura del subsistema, sin puerta de configuracion que la abra:

> Una contradiccion NUNCA se auto-aprueba.

Un claim que contradice una afirmacion vigente va a `REVIEW` con
`CONFLICT_WITH_EXISTING`. No se escribe, no se supersede sola y no se decide
"por confianza": que el claim nuevo venga con 0.99 no lo hace mas cierto que el
que ya esta, solo mas insistente.

Cuatro formas de chocar, y las cuatro se comparan sobre la clave CANONICA de la
relacion (`ontology.canonical_key`), no sobre los campos crudos — si no, basta
con decir lo mismo al reves, o con la inversa del predicado, para que el choque
no se vea:

1. **Negacion opuesta** — misma clave canonica, distinto `negated`.
2. **Direccion invertida** — misma pareja y predicado no simetrico, pero
   orientaciones canonicas contrarias.
3. **Predicado funcional** — un predicado declarado `functional` admite un solo
   objeto por sujeto; otro objeto distinto es un conflicto.
4. **Duplicado** — misma clave, mismo `negated`: no es conflicto, es que ya
   estaba dicho. Se marca (`ALREADY_ASSERTED`) y NO se emite operacion: repetir
   una escritura idempotente es ruido en el ledger.

Solo cuentan las afirmaciones VIGENTES del snapshot (`is_live`): una afirmacion
superada o terminada describe otro tramo de la historia y no contradice nada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import findings as F
from .ontology import ProfileIndex, canonical_key
from .snapshot import GraphSnapshot, SnapshotAssertion


@dataclass(frozen=True)
class ContradictionOutcome:
    """Resultado del eje.

    `duplicate_of` no es un conflicto: es la afirmacion vigente identica que
    hace innecesaria la escritura.
    """

    conflicts: tuple[SnapshotAssertion, ...]
    duplicate_of: Optional[SnapshotAssertion]
    findings: tuple[F.Finding, ...]

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


def check_contradictions(
    index: ProfileIndex,
    snapshot: GraphSnapshot,
    subject_entity_id: str,
    object_entity_id: str,
    predicate: str,
    direction: str,
    negated: bool,
) -> ContradictionOutcome:
    """Contrasta una relacion candidata contra las afirmaciones vigentes."""
    out: list[F.Finding] = []
    conflicts: list[SnapshotAssertion] = []
    duplicate: Optional[SnapshotAssertion] = None

    key = canonical_key(index, subject_entity_id, object_entity_id, predicate, direction)
    spec = index.spec(predicate)

    for existing in snapshot.assertions_for_pair(subject_entity_id, object_entity_id):
        if not existing.is_live():
            continue
        existing_key = canonical_key(
            index,
            existing.subject_entity_id,
            existing.object_entity_id,
            existing.predicate,
            existing.direction,
        )
        if existing_key == key:
            if existing.negated != negated:
                conflicts.append(existing)
                out.append(
                    F.CONTRADICTS_VIGENTE(
                        f"{existing.assertion_id} afirma lo contrario "
                        f"(negated={existing.negated}) sobre {key}"
                    )
                )
            else:
                duplicate = existing
                out.append(
                    F.ALREADY_ASSERTED(f"{existing.assertion_id} ya afirma {key}: no se reescribe")
                )
            continue
        # Misma pareja y mismo predicado logico, pero orientacion contraria.
        if existing_key[1] == key[1] and {existing_key[0], existing_key[2]} == {key[0], key[2]}:
            conflicts.append(existing)
            out.append(
                F.DIRECTION_CONFLICT(
                    f"{existing.assertion_id} orienta {existing_key} y el claim {key}"
                )
            )

    if spec is not None and spec.functional and not negated:
        for existing in snapshot.assertions_for_subject(key[0], key[1]):
            if not existing.is_live() or existing.negated:
                continue
            existing_key = canonical_key(
                index,
                existing.subject_entity_id,
                existing.object_entity_id,
                existing.predicate,
                existing.direction,
            )
            if existing_key[0] == key[0] and existing_key[2] != key[2]:
                conflicts.append(existing)
                out.append(
                    F.FUNCTIONAL_CONFLICT(
                        f"{predicate} es funcional y {key[0]} ya apunta a {existing_key[2]}"
                    )
                )

    return ContradictionOutcome(tuple(conflicts), duplicate, tuple(out))

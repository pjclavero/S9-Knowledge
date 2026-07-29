# -*- coding: utf-8 -*-
"""Eje de CONTRADICCION, en DOS pasadas: contra el grafo y contra el lote.

Regla dura del subsistema, sin puerta de configuracion que la abra:

> Una contradiccion NUNCA se auto-aprueba — ni contra lo que el grafo ya dice,
> ni contra lo que este mismo plan esta a punto de escribir.

La segunda mitad de esa frase falta en la primera version de este modulo, y era
un agujero real (hallazgo H1 de la revision independiente): `MEMBER_OF(daiki,
casa)` y su negacion, en el MISMO lote, se aprobaban los dos y producian un plan
firmado, valido para el contrato congelado, que dejaba el grafo internamente
incoherente en una sola escritura. La clave canonica ya era correcta; lo que
faltaba era usarla tambien dentro del lote.

Un claim en conflicto va a `REVIEW` con `CONFLICT_WITH_EXISTING`. No se escribe,
no se supersede solo y no se decide "por confianza": que el claim nuevo venga
con 0.99 no lo hace mas cierto que el otro, solo mas insistente.

Todo se compara sobre la clave CANONICA (`ontology.canonical_key`) y nunca
sobre los campos crudos — si no, basta con decir lo mismo al reves, o con la
inversa del predicado, para que el choque no se vea:

1. **Negacion opuesta** — misma clave canonica, distinto `negated`.
2. **Direccion invertida** — misma pareja y predicado no simetrico, pero
   orientaciones canonicas contrarias.
3. **Predicado funcional** — un predicado declarado `functional` admite un solo
   objeto por sujeto; otro objeto distinto es un conflicto.
4. **Duplicado** — misma clave, mismo `negated`: no es conflicto, es que ya
   estaba dicho. Se marca (`ALREADY_ASSERTED` / `DUPLICATE_IN_BATCH`) y NO se
   emite operacion: repetir una escritura idempotente es ruido en el ledger —
   y, dentro de un mismo plan, dos claves de idempotencia iguales que el
   validador congelado rechazaria.

Que cuenta del snapshot: lo que `blocks_new_claims()` deja pasar — las
afirmaciones vigentes MAS las marcadas `CONTRADICTED` y aun sin resolver.
`SUPERSEDED` y `RETRACTED` no cuentan: son historia.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

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
    skip_assertion_ids: frozenset[str] = frozenset(),
) -> ContradictionOutcome:
    """Contrasta una relacion candidata contra las afirmaciones vigentes.

    `skip_assertion_ids` deja fuera afirmaciones que OTRO eje ya esta tratando y
    que no son un choque. Hoy tiene un solo uso: la positiva vigente que una
    CESACION propone cerrar. "A lideraba B" y "A ya no lidera B" no se
    contradicen —estan separadas en el tiempo—, y contarlas como conflicto
    mandaria a revision toda evolucion temporal legitima del grafo. Se pasa por
    ID, no por regla: cualquier OTRA afirmacion sigue entrando en el eje.
    """
    out: list[F.Finding] = []
    conflicts: list[SnapshotAssertion] = []
    duplicate: Optional[SnapshotAssertion] = None

    key = canonical_key(index, subject_entity_id, object_entity_id, predicate, direction)
    spec = index.spec(predicate)

    for existing in snapshot.assertions_for_pair(subject_entity_id, object_entity_id):
        if not existing.blocks_new_claims() or existing.assertion_id in skip_assertion_ids:
            continue
        existing_key = canonical_key(
            index,
            existing.subject_entity_id,
            existing.object_entity_id,
            existing.predicate,
            existing.direction,
        )
        if existing_key == key:
            if existing.is_unresolved_conflict():
                # Reafirmar cualquiera de las dos caras de un conflicto abierto
                # no lo resuelve: lo entierra. Va a revision aunque coincida.
                conflicts.append(existing)
                out.append(
                    F.UNRESOLVED_CONFLICT(
                        f"{existing.assertion_id} esta marcada CONTRADICTED y sin resolver "
                        f"sobre {key}: reafirmarla no cierra el conflicto"
                    )
                )
            elif existing.negated != negated:
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
            if (
                not existing.blocks_new_claims()
                or existing.negated
                or existing.assertion_id in skip_assertion_ids
            ):
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


# --------------------------------------------------------------------------
# Segunda pasada: el lote contra si mismo
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BatchClaimKey:
    """Identidad canonica de lo que un claim del lote pretende escribir."""

    ref: str
    key: tuple[str, str, str]
    negated: bool
    functional: bool


def batch_conflicts(
    index: ProfileIndex, items: Sequence[BatchClaimKey]
) -> dict[str, list[F.Finding]]:
    """Choques DENTRO del lote. Devuelve hallazgos por `ref`.

    Se compara cada par una sola vez y se marcan LOS DOS implicados: en un
    conflicto interno no hay uno "correcto" al que dejar pasar — si lo hubiera,
    elegirlo seria justamente la decision que el motor no puede tomar solo.

    El duplicado interno se marca en el SEGUNDO y siguientes (orden de llegada,
    que es determinista): dos operaciones identicas en un mismo plan producen la
    misma `idempotency_key`, y el validador congelado rechaza el plan entero por
    "idempotency_key duplicada". Suprimir la escritura repetida no es una
    optimizacion, es lo que hace el plan construible.
    """
    out: dict[str, list[F.Finding]] = {}

    def add(ref: str, finding: F.Finding) -> None:
        out.setdefault(ref, []).append(finding)

    for i, first in enumerate(items):
        for second in items[i + 1 :]:
            same_pair = {first.key[0], first.key[2]} == {second.key[0], second.key[2]}
            same_predicate = first.key[1] == second.key[1]

            if first.key == second.key:
                if first.negated != second.negated:
                    detail = (
                        f"{first.ref} y {second.ref} afirman lo contrario sobre {first.key} "
                        "en el mismo lote"
                    )
                    add(first.ref, F.BATCH_CONTRADICTION(detail))
                    add(second.ref, F.BATCH_CONTRADICTION(detail))
                else:
                    add(
                        second.ref,
                        F.BATCH_DUPLICATE(
                            f"{second.ref} repite lo que {first.ref} ya escribe sobre {first.key}"
                        ),
                    )
                continue

            if same_predicate and same_pair:
                detail = (
                    f"{first.ref} orienta {first.key} y {second.ref} {second.key} "
                    "en el mismo lote"
                )
                add(first.ref, F.BATCH_DIRECTION_CONFLICT(detail))
                add(second.ref, F.BATCH_DIRECTION_CONFLICT(detail))
                continue

            if (
                same_predicate
                and first.functional
                and not first.negated
                and not second.negated
                and first.key[0] == second.key[0]
                and first.key[2] != second.key[2]
            ):
                detail = (
                    f"{first.key[1]} es funcional y el lote le da a {first.key[0]} "
                    f"dos objetos: {first.key[2]} y {second.key[2]}"
                )
                add(first.ref, F.BATCH_FUNCTIONAL_CONFLICT(detail))
                add(second.ref, F.BATCH_FUNCTIONAL_CONFLICT(detail))

    return out

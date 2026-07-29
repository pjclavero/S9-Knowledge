# -*- coding: utf-8 -*-
"""Eje de NEGACION: que significa un claim negativo, y que hacer con el.

Principio del bloque, y no es un matiz:

    "relacion negada"  !=  "ausencia de relacion"  !=  "relacion positiva"

El extractor DETECTA y MARCA (`negated`, y el tipo en `metadata.negation_kind`);
aqui se decide QUE significa. Cuatro tipos, cuatro consecuencias distintas:

    SIMPLE      "A no pertenece a B"        afirmacion negativa corriente.
                                            Puede producir `FactAssertion` con
                                            `negated=true`. NUNCA una arista
                                            positiva.
    NEVER       "A nunca perteneció a B"    negacion ABSOLUTA. Igual que SIMPLE
                                            en cuanto a escritura, pero ligada al
                                            contexto temporal de la FUENTE: no
                                            autoriza a inventar un intervalo
                                            infinito, asi que aqui no se toca la
                                            temporalidad.
    CESSATION   "A ya no lidera B"          hubo relacion y termina. Se busca la
                                            positiva vigente compatible en el
                                            snapshot:
                                              * si existe -> se propone CERRAR su
                                                vigencia y sucederla, conservando
                                                historia y evidencia;
                                              * si NO existe -> NO se inventa la
                                                relacion previa: revision temporal.
    NOT_YET     "A todavía no lidera B"     NO es cesacion. No demuestra que antes
                                            lo fuera, asi que no cierra nada.

Y un quinto valor que no es un tipo sino una renuncia: `SCOPE_AMBIGUOUS`. El
texto niega, pero no se sabe QUE niega ("el magistrado no cree que A pertenezca a
B", doble negacion). Va a revision; negar por defecto seria inventar.

Lo que este modulo NO hace: leer texto. No tiene el episodio delante y no debe
tenerlo. Lee `negated` y `metadata.negation_kind`, que la frontera de extraccion
ya valido contra la evidencia real.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..claim_metadata import ClaimSemanticMetadata
from ..contracts.claim import ClaimProposal
from . import findings as F
from .config import EngineConfig
from .ontology import ProfileIndex, canonical_key
from .snapshot import GraphSnapshot, SnapshotAssertion

#: Los mismos valores que `extraction.cues.NEGATION_KINDS`. Se declaran aqui en
#: vez de importarlos: el motor no depende del subsistema de extraccion, y el
#: acoplamiento real es el CONTRATO (`metadata.negation_kind`), no el modulo.
NEGATION_KIND_SIMPLE = "SIMPLE"
NEGATION_KIND_NEVER = "NEVER"
NEGATION_KIND_CESSATION = "CESSATION"
NEGATION_KIND_NOT_YET = "NOT_YET"
NEGATION_KIND_SCOPE_AMBIGUOUS = "SCOPE_AMBIGUOUS"
NEGATION_KIND_UNKNOWN = "UNKNOWN"

NEGATION_KINDS = (
    NEGATION_KIND_SIMPLE,
    NEGATION_KIND_NEVER,
    NEGATION_KIND_CESSATION,
    NEGATION_KIND_NOT_YET,
    NEGATION_KIND_SCOPE_AMBIGUOUS,
)


def negation_kind_of(claim: ClaimProposal) -> str:
    """Tipo declarado en `metadata`, o `SIMPLE` si el claim niega y no lo dice.

    `negation_kind` NO existe en el contrato congelado: viaja en `metadata`, que
    es el unico bloque abierto de la familia `v3-internal-v1`. Un valor
    ausente se trata como `SIMPLE`: es el tipo menos comprometido. Un valor
    presente pero desconocido se conserva como `UNKNOWN` para impedir escritura.
    """
    if not claim.negated:
        return ""
    metadata = ClaimSemanticMetadata.from_metadata(claim.metadata)
    return _kind_from_metadata(metadata)


def _kind_from_metadata(metadata: ClaimSemanticMetadata) -> str:
    return NEGATION_KIND_UNKNOWN if metadata.unknown_negation_kind else metadata.negation_kind


@dataclass(frozen=True)
class NegationOutcome:
    """Lectura del eje. `closes` es la positiva vigente que la cesacion cierra."""

    kind: str = ""
    findings: tuple[F.Finding, ...] = ()
    closes: Optional[SnapshotAssertion] = None

    @property
    def is_cessation(self) -> bool:
        return self.kind == NEGATION_KIND_CESSATION


def find_active_positive(
    index: ProfileIndex,
    snapshot: GraphSnapshot,
    subject_entity_id: str,
    object_entity_id: str,
    predicate: str,
    direction: str,
) -> tuple[SnapshotAssertion, ...]:
    """Afirmaciones POSITIVAS vigentes sobre la misma clave canonica.

    Se compara sobre la clave canonica, igual que el eje de contradiccion: decir
    lo mismo al reves, o con la inversa del predicado, sigue siendo la misma
    relacion. La tupla conserva la cardinalidad para no esconder incoherencias.
    """
    key = canonical_key(index, subject_entity_id, object_entity_id, predicate, direction)
    candidatos = [
        existing
        for existing in snapshot.assertions_for_pair(subject_entity_id, object_entity_id)
        if not existing.negated
        and existing.blocks_new_claims()
        and canonical_key(
            index,
            existing.subject_entity_id,
            existing.object_entity_id,
            existing.predicate,
            existing.direction,
        )
        == key
    ]
    return tuple(sorted(candidatos, key=lambda a: a.assertion_id))


def resolve_negation(
    claim: ClaimProposal,
    *,
    index: ProfileIndex,
    snapshot: GraphSnapshot,
    subject_entity_id: Optional[str],
    object_entity_id: Optional[str],
    predicate: Optional[str],
    direction: Optional[str],
    config: EngineConfig,
) -> NegationOutcome:
    """Lee el claim negativo y dice que hacer. No escribe y no adivina."""
    if not claim.negated:
        return NegationOutcome()

    metadata = ClaimSemanticMetadata.from_metadata(claim.metadata)
    kind = _kind_from_metadata(metadata)
    out: list[F.Finding] = []

    if kind == NEGATION_KIND_UNKNOWN:
        out.append(
            F.UNKNOWN_NEGATION_KIND(
                f"metadata.negation_kind={metadata.unknown_negation_kind!r} no pertenece "
                "al vocabulario conocido; no se degrada a una negacion escribible"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    if not config.accept_negated:
        out.append(F.NEGATION_NOT_ACCEPTED("la configuracion no acepta hechos negados"))
        return NegationOutcome(kind, tuple(out), None)

    out.append(F.NEGATED_CLAIM(f"tipo={kind}; cues: {claim.epistemic_cues or 'ninguna'}"))

    if kind == NEGATION_KIND_SCOPE_AMBIGUOUS:
        out.append(
            F.NEGATION_SCOPE_AMBIGUOUS(
                "el texto niega, pero no consta que niegue ESTA relacion: no se "
                "niega por defecto"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    if kind == NEGATION_KIND_NOT_YET:
        out.append(
            F.NEGATION_NOT_YET(
                "'todavia no' no demuestra que antes lo fuera: no cierra ninguna "
                "vigencia"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    if kind == NEGATION_KIND_NEVER:
        out.append(
            F.NEGATION_ABSOLUTE(
                "negacion absoluta ligada al contexto temporal de la fuente: no se "
                "deriva ningun intervalo"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    if kind != NEGATION_KIND_CESSATION:
        return NegationOutcome(kind, tuple(out), None)

    # --- CESACION ---------------------------------------------------------
    if not (subject_entity_id and object_entity_id and predicate and direction):
        out.append(
            F.CESSATION_WITHOUT_PRIOR(
                "cesacion sin relacion resuelta: no hay clave con la que buscar la "
                "afirmacion previa"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    previas = find_active_positive(
        index, snapshot, subject_entity_id, object_entity_id, predicate, direction
    )
    if not previas:
        # NO se inventa la relacion previa. Que el texto diga "ya no lidera" no
        # demuestra que el grafo lo supiera: puede ser una fuente que llega antes
        # que la que afirmaba. Se registra la negativa de cese y se pide revision
        # temporal, que es exactamente lo que un humano tiene que resolver.
        out.append(
            F.CESSATION_WITHOUT_PRIOR(
                f"cesacion de {predicate} sin afirmacion positiva vigente en el "
                "snapshot: no se inventa la relacion anterior"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    if len(previas) > 1:
        assertion_ids = ", ".join(previous.assertion_id for previous in previas)
        out.append(
            F.CESSATION_MULTIPLE_ACTIVE(
                f"multiples afirmaciones positivas vigentes para la misma clave: "
                f"{assertion_ids}; no se elige cual cerrar"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    previa = previas[0]
    if previa.state_hash is None:
        # Sin `state_hash` no hay concurrencia optimista, y el contrato congelado
        # rechaza una operacion de cierre sin `expected_hash`. Se dice y se manda
        # a revision: cerrar a ciegas una vigencia seria escribir sobre un estado
        # que nadie ha comprobado.
        out.append(
            F.CESSATION_TARGET_UNANCHORED(
                f"{previa.assertion_id} no trae `state_hash` en el snapshot: no se "
                "puede cerrar su vigencia con concurrencia optimista"
            )
        )
        return NegationOutcome(kind, tuple(out), None)

    out.append(
        F.CESSATION_CLOSES_ASSERTION(
            f"{previa.assertion_id} sigue vigente: la cesacion propone cerrar su "
            "vigencia y sucederla, conservando historia y evidencia"
        )
    )
    return NegationOutcome(kind, tuple(out), previa)


__all__ = [
    "NEGATION_KINDS",
    "NEGATION_KIND_CESSATION",
    "NEGATION_KIND_NEVER",
    "NEGATION_KIND_NOT_YET",
    "NEGATION_KIND_SCOPE_AMBIGUOUS",
    "NEGATION_KIND_SIMPLE",
    "NEGATION_KIND_UNKNOWN",
    "NegationOutcome",
    "find_active_positive",
    "negation_kind_of",
    "resolve_negation",
]

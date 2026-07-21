# -*- coding: utf-8 -*-
"""Abstracciones PURAS del motor hibrido por etapas (PR#95 V4).

Tres dataclasses inmutables, SIN logica de extraccion, SIN red y SIN estado
mutable compartido. Son estructuras INTERNAS del pipeline hibrido: NO forman
parte del contrato publico de 20 campos de `RelationCandidate`. El adaptador de
`engine.py` las traduce a `RelationCandidate` sin alterar dicho contrato.

Principio de diseno DURO
------------------------
El "por que" (razonamiento) va SEPARADO de la cita literal (evidencia):

  * `RelationHypothesis.reasoning`  -> por que se propone la hipotesis.
  * `EvidenceBundle.evidence_text`  -> la cita LITERAL, verbatim del segmento.
  * `EvidenceBundle.reasoning`      -> por que ese span es la evidencia.

Nunca se mezcla el razonamiento dentro del texto de evidencia: el consumidor
que audite la cita recibe solo el span literal, no la explicacion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SegmentReference:
    """Referencia REDACTADA a un segmento (procedencia + offsets, sin volcar texto).

    Guarda solo la LONGITUD del texto (`text_len`), no el texto en claro, para no
    filtrar contenido en trazas ni estructuras intermedias. Los offsets absolutos
    del segmento se resuelven contra el texto real solo en el momento de cortar la
    evidencia literal, nunca aqui.
    """

    segment_id: str
    source_id: str
    source_page: Optional[int]
    workspace: str
    text_len: int

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, str) or not self.segment_id.strip():
            raise ValueError("segment_id obligatorio")
        if not isinstance(self.text_len, int) or self.text_len < 0:
            raise ValueError("text_len debe ser int >= 0")

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "source_id": self.source_id,
            "source_page": self.source_page,
            "workspace": self.workspace,
            "text_len": self.text_len,
        }


@dataclass(frozen=True)
class RelationHypothesis:
    """Hipotesis ESTRUCTURAL: par + predicado + direccion + score, con razonamiento.

    Es el producto de las etapas de menciones/hipotesis/predicado-direccion. El
    `score` es una senal ordinal determinista en [0,1] (no una probabilidad
    calibrada) usada para el ranking top-k. `reasoning` es el "por que" de la
    hipotesis: NUNCA contiene la cita literal (esa vive en `EvidenceBundle`).
    """

    pair_id: str
    subject_id: str
    object_id: str
    subject_type: Optional[str]
    object_type: Optional[str]
    subject_start: int
    subject_end: int
    object_start: int
    object_end: int
    predicate: str
    direction: str
    score: float
    reasoning: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not (0.0 <= float(self.score) <= 1.0):
            raise ValueError(f"score fuera de [0,1]: {self.score}")
        if not isinstance(self.reasoning, tuple):
            object.__setattr__(self, "reasoning", tuple(self.reasoning))

    def with_predicate(self, predicate: str, direction: str, *, why: str) -> "RelationHypothesis":
        """Devuelve una copia con predicado/direccion resueltos (inmutable)."""
        return RelationHypothesis(
            pair_id=self.pair_id,
            subject_id=self.subject_id,
            object_id=self.object_id,
            subject_type=self.subject_type,
            object_type=self.object_type,
            subject_start=self.subject_start,
            subject_end=self.subject_end,
            object_start=self.object_start,
            object_end=self.object_end,
            predicate=predicate,
            direction=direction,
            score=self.score,
            reasoning=self.reasoning + (why,),
        )

    def to_dict(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "subject_id": self.subject_id,
            "object_id": self.object_id,
            "subject_type": self.subject_type,
            "object_type": self.object_type,
            "subject_start": self.subject_start,
            "subject_end": self.subject_end,
            "object_start": self.object_start,
            "object_end": self.object_end,
            "predicate": self.predicate,
            "direction": self.direction,
            "score": self.score,
            "reasoning": list(self.reasoning),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    """Evidencia LITERAL + offsets + verificacion, con razonamiento SEPARADO.

    `evidence_text` es la cita verbatim del segmento (`seg_text[start:end]`), sin
    ninguna anotacion. El "por que" de esta evidencia va en `reasoning`, NUNCA
    fundido con la cita. `verified` resume el resultado de la etapa de
    verificacion; `covers_subject`/`covers_object` indican si el span cubre ambas
    menciones.
    """

    evidence_text: str
    evidence_start: int
    evidence_end: int
    verified: bool
    covers_subject: bool
    covers_object: bool
    reasoning: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_start, int) or not isinstance(self.evidence_end, int):
            raise ValueError("offsets de evidencia deben ser int")
        if self.evidence_start < 0 or self.evidence_end < 0:
            raise ValueError("offsets de evidencia deben ser >= 0")
        if self.evidence_start > self.evidence_end:
            raise ValueError("evidence_start > evidence_end")
        if not isinstance(self.reasoning, tuple):
            object.__setattr__(self, "reasoning", tuple(self.reasoning))

    def to_dict(self) -> dict:
        return {
            "evidence_text": self.evidence_text,
            "evidence_start": self.evidence_start,
            "evidence_end": self.evidence_end,
            "verified": self.verified,
            "covers_subject": self.covers_subject,
            "covers_object": self.covers_object,
            "reasoning": list(self.reasoning),
        }


__all__ = ["SegmentReference", "RelationHypothesis", "EvidenceBundle"]

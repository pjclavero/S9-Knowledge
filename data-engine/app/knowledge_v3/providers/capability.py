# -*- coding: utf-8 -*-
"""Capacidades tipadas de la capa de proveedores V3.

Las seis capacidades del prompt maestro §7 (ASR, OCR, VISION, EXTRACTION,
EMBEDDINGS, REVIEW) son la superficie que el resto de V3 conoce. Por debajo se
traducen a la `Capability` y al `ExternalTaskType` que YA usan el dispatcher, el
planner y el result validator de `external_processing/`: no se duplica ese
vocabulario, se envuelve.

Dos vocabularios y no uno porque son cosas distintas: `V3Capability` es lo que
un PASO del pipeline necesita; `Capability` es lo que un PROVEEDOR declara
saber hacer. El mapa entre ambos vive aqui y solo aqui.
"""
from __future__ import annotations

from enum import Enum

from external_processing.capabilities import Capability
from external_processing.models import ExternalTaskType


class V3Capability(str, Enum):
    """Capacidad que un paso del pipeline V3 solicita a la capa de proveedores."""

    ASR = "ASR"
    OCR = "OCR"
    VISION = "VISION"
    EXTRACTION = "EXTRACTION"
    EMBEDDINGS = "EMBEDDINGS"
    REVIEW = "REVIEW"


#: V3Capability -> Capability del subsistema de procesamiento.
TO_PROVIDER_CAPABILITY: dict[V3Capability, Capability] = {
    V3Capability.ASR: Capability.TRANSCRIBE_AUDIO,
    V3Capability.OCR: Capability.OCR_IMAGE,
    V3Capability.VISION: Capability.DESCRIBE_IMAGE,
    V3Capability.EXTRACTION: Capability.EXTRACT_TEXT_ENTITIES,
    V3Capability.EMBEDDINGS: Capability.GENERATE_EMBEDDINGS,
    V3Capability.REVIEW: Capability.REVIEW_CANDIDATES,
}

#: V3Capability -> tipo de tarea que entiende el dispatcher.
TO_TASK_TYPE: dict[V3Capability, ExternalTaskType] = {
    V3Capability.ASR: ExternalTaskType.TRANSCRIBE_AUDIO,
    V3Capability.OCR: ExternalTaskType.OCR_IMAGE,
    V3Capability.VISION: ExternalTaskType.IMAGE_ANALYSIS,
    V3Capability.EXTRACTION: ExternalTaskType.TEXT_EXTRACT,
    V3Capability.EMBEDDINGS: ExternalTaskType.EMBEDDINGS,
    V3Capability.REVIEW: ExternalTaskType.REVIEW,
}

#: Capacidades cuyo resultado puede convertirse en documentos V3 propuestos.
#: `EMBEDDINGS` no esta: un vector no es una propuesta de conocimiento.
PROPOSAL_CAPABILITIES: frozenset[V3Capability] = frozenset(
    {V3Capability.ASR, V3Capability.OCR, V3Capability.VISION, V3Capability.EXTRACTION}
)


def to_provider_capability(cap: V3Capability) -> Capability:
    return TO_PROVIDER_CAPABILITY[cap]


def to_task_type(cap: V3Capability) -> ExternalTaskType:
    return TO_TASK_TYPE[cap]

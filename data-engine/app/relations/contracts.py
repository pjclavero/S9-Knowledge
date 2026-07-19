# -*- coding: utf-8 -*-
"""Contrato interno `relation-candidate/internal-v1`.

Modelo, enums, validadores y serializacion determinista para una relacion
propuesta por el pipeline interno de relaciones. Este modulo NO extrae, NO
llama a Ollama/NVIDIA, NO ejecuta el ensemble ni escribe en Neo4j: define
exclusivamente el contrato de datos y sus reglas de validacion.

Los estados de consenso del ensemble se REUTILIZAN de `external_ai.models`
(fuente canonica) para no crear un segundo sistema de consenso.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields as dataclass_fields
from enum import Enum
from typing import Any, Optional

# --- Reutilizacion de los estados canonicos de consenso -------------------
# No duplicamos el sistema de consenso: referenciamos los estados ya definidos
# por el subsistema de IA externa. La propuesta (docs/coordination/
# contract-proposals.md §1) los nombra STRONG / PARTIAL / CONFLICT / INVALID /
# HUMAN; su forma canonica en codigo lleva sufijo (STRONG_CONSENSUS, ...).
try:  # pragma: no cover - la rama de fallback solo cubre entornos sin external_ai
    from external_ai.models import CONSENSUS_STATES as _EXTERNAL_CONSENSUS_STATES

    CANONICAL_CONSENSUS_STATES = tuple(_EXTERNAL_CONSENSUS_STATES)
    _CONSENSUS_SOURCE = "external_ai.models"
except Exception:  # pragma: no cover
    # Fallback documentado: mismos valores canonicos que external_ai.models.
    CANONICAL_CONSENSUS_STATES = (
        "STRONG_CONSENSUS",
        "PARTIAL_CONSENSUS",
        "MODEL_CONFLICT",
        "INVALID_RESPONSES",
        "HUMAN_REQUIRED",
    )
    _CONSENSUS_SOURCE = "relations.contracts (mirror de external_ai.models)"

# Tipos de entidad permitidos (esquema S9 Knowledge). Se referencia el catalogo
# canonico de external_ai cuando esta disponible; el fallback lo replica.
try:  # pragma: no cover
    from external_ai.models import ALLOWED_ENTITY_TYPES as _ALLOWED_ENTITY_TYPES
except Exception:  # pragma: no cover
    _ALLOWED_ENTITY_TYPES = ("Character", "Location", "Faction", "Object", "Event", "Concept")

ALLOWED_ENTITY_TYPES = tuple(_ALLOWED_ENTITY_TYPES)

# --- Metadatos del contrato ------------------------------------------------
SCHEMA_VERSION = "internal-1.0.0"
DOCUMENT_TYPE = "relation-candidate"

# Predicados reflexivos permitidos (subject == object). Vacio por defecto:
# ninguna relacion puede apuntar a si misma salvo que se amplie esta lista de
# forma explicita y documentada.
REFLEXIVE_PREDICATES: tuple[str, ...] = ()


class RelationContractError(ValueError):
    """Error de validacion del contrato de relacion interno."""


class Direction(str, Enum):
    """Direccion de la relacion respecto a sujeto/objeto."""

    SUBJECT_TO_OBJECT = "SUBJECT_TO_OBJECT"
    OBJECT_TO_SUBJECT = "OBJECT_TO_SUBJECT"
    UNDIRECTED = "UNDIRECTED"


class ExtractionMethod(str, Enum):
    """Metodo que propuso la relacion."""

    HEURISTIC = "HEURISTIC"
    LLM_LOCAL = "LLM_LOCAL"
    NVIDIA = "NVIDIA"
    ONTOLOGY = "ONTOLOGY"


class EpistemicStatus(str, Enum):
    """Estatus epistemico de la afirmacion."""

    ASSERTED = "ASSERTED"
    RUMORED = "RUMORED"
    HYPOTHETICAL = "HYPOTHETICAL"
    INTENDED = "INTENDED"


def normalize_predicate(raw: str) -> str:
    """Normaliza un predicado a MAYUSCULAS con guion_bajo.

    Colapsa espacios/guiones en un unico `_`, elimina bordes y pasa a mayusculas.
    Es idempotente: normalize(normalize(x)) == normalize(x).
    """
    if not isinstance(raw, str):
        raise RelationContractError("predicate debe ser str")
    collapsed = "_".join(raw.strip().replace("-", " ").split())
    return collapsed.upper()


def _enum_value(v: Any) -> Any:
    return v.value if isinstance(v, Enum) else v


@dataclass
class RelationCandidate:
    """Una relacion candidata interna (`relation-candidate/internal-v1`).

    Exactamente 20 campos de datos. Diferencia justificada frente a la propuesta
    de docs/coordination/contract-proposals.md §1 (que tenia 18 campos de dominio,
    con `evidence_span` y sin `subject_type`/`object_type`):

      * Se ANADEN `subject_type` y `object_type` para permitir validacion
        ontologica de compatibilidad de tipos.
      * Se DESDOBLA `evidence_span` en `evidence_start`/`evidence_end` (offsets
        enteros explicitos), evitando un sub-objeto anidado en serializacion.

    No se anaden campos mas alla de estos 20.
    """

    subject_id: str
    subject_type: Optional[str]
    predicate: str
    object_id: str
    object_type: Optional[str]
    direction: Direction
    confidence: float
    evidence_text: str
    evidence_start: int
    evidence_end: int
    source_id: str
    source_page: Optional[int]
    source_segment: str
    extraction_method: ExtractionMethod
    model: Optional[str]
    negated: bool
    temporal_scope: Optional[Any]
    epistemic_status: EpistemicStatus
    workspace: str
    validation_flags: list = field(default_factory=list)

    # -- Validacion --------------------------------------------------------
    def validate(self) -> "RelationCandidate":
        """Valida el candidato. Lanza RelationContractError si algo no cumple.

        Devuelve self para permitir encadenado.
        """
        # Enums (validos y coercibles desde str)
        self.direction = self._coerce_enum(Direction, self.direction, "direction")
        self.extraction_method = self._coerce_enum(
            ExtractionMethod, self.extraction_method, "extraction_method"
        )
        self.epistemic_status = self._coerce_enum(
            EpistemicStatus, self.epistemic_status, "epistemic_status"
        )

        # subject_id / object_id no vacios
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise RelationContractError("subject_id no puede estar vacio")
        if not isinstance(self.object_id, str) or not self.object_id.strip():
            raise RelationContractError("object_id no puede estar vacio")

        # subject != object salvo predicados reflexivos permitidos
        if self.subject_id == self.object_id and self.predicate not in REFLEXIVE_PREDICATES:
            raise RelationContractError(
                "subject_id y object_id no pueden coincidir salvo predicado reflexivo permitido "
                f"(reflexivos permitidos: {REFLEXIVE_PREDICATES or 'ninguno'})"
            )

        # predicate normalizado y no vacio
        if not isinstance(self.predicate, str) or not self.predicate.strip():
            raise RelationContractError("predicate no puede estar vacio")
        if self.predicate != normalize_predicate(self.predicate):
            raise RelationContractError(
                "predicate no esta normalizado (esperado MAYUSCULAS con guion_bajo: "
                f"{normalize_predicate(self.predicate)!r})"
            )

        # tipos ontologicos, si se aportan, deben ser conocidos
        for label, value in (("subject_type", self.subject_type), ("object_type", self.object_type)):
            if value is not None and value not in ALLOWED_ENTITY_TYPES:
                raise RelationContractError(
                    f"{label}={value!r} no es un tipo de entidad valido {ALLOWED_ENTITY_TYPES}"
                )

        # confidence en [0, 1]
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise RelationContractError("confidence debe ser numerico")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise RelationContractError(f"confidence fuera de rango [0,1]: {self.confidence}")

        # offsets de evidencia
        if not isinstance(self.evidence_start, int) or isinstance(self.evidence_start, bool):
            raise RelationContractError("evidence_start debe ser int")
        if not isinstance(self.evidence_end, int) or isinstance(self.evidence_end, bool):
            raise RelationContractError("evidence_end debe ser int")
        if self.evidence_start < 0 or self.evidence_end < 0:
            raise RelationContractError("evidence_start y evidence_end deben ser >= 0")
        if self.evidence_start > self.evidence_end:
            raise RelationContractError(
                f"evidence_start ({self.evidence_start}) no puede ser mayor que "
                f"evidence_end ({self.evidence_end})"
            )

        # evidencia textual: obligatoria salvo metodo ONTOLOGY
        if self.extraction_method != ExtractionMethod.ONTOLOGY:
            if not isinstance(self.evidence_text, str) or not self.evidence_text.strip():
                raise RelationContractError(
                    "evidence_text es obligatorio salvo extraction_method=ONTOLOGY"
                )

        # workspace obligatorio
        if not isinstance(self.workspace, str) or not self.workspace.strip():
            raise RelationContractError("workspace es obligatorio")

        # negated debe ser bool explicito
        if not isinstance(self.negated, bool):
            raise RelationContractError("negated debe ser bool explicito (True/False)")

        # procedencia minima: source_id y source_segment presentes
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise RelationContractError("source_id es obligatorio (procedencia)")
        if not isinstance(self.source_segment, str) or not self.source_segment.strip():
            raise RelationContractError("source_segment es obligatorio (procedencia)")

        # source_page: null o int >= 0
        if self.source_page is not None:
            if not isinstance(self.source_page, int) or isinstance(self.source_page, bool):
                raise RelationContractError("source_page debe ser int o null")
            if self.source_page < 0:
                raise RelationContractError("source_page no puede ser negativo")

        # validation_flags debe ser lista de strings
        if not isinstance(self.validation_flags, list) or not all(
            isinstance(f, str) for f in self.validation_flags
        ):
            raise RelationContractError("validation_flags debe ser lista de strings")

        return self

    @staticmethod
    def _coerce_enum(enum_cls, value, label):
        if isinstance(value, enum_cls):
            return value
        try:
            return enum_cls(value)
        except (ValueError, KeyError):
            valid = [e.value for e in enum_cls]
            raise RelationContractError(f"{label}={value!r} invalido; validos: {valid}")

    def is_affirmative(self) -> bool:
        """True solo si la relacion afirma un hecho positivo confirmado.

        `negated=True` o `epistemic_status != ASSERTED` la degradan a
        no-afirmacion (no autoaprobable como hecho).
        """
        return (not self.negated) and self.epistemic_status == EpistemicStatus.ASSERTED

    # -- Serializacion determinista ---------------------------------------
    def to_dict(self) -> dict:
        """Dict con exactamente los 20 campos; enums como su valor str."""
        return {
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "predicate": self.predicate,
            "object_id": self.object_id,
            "object_type": self.object_type,
            "direction": _enum_value(self.direction),
            "confidence": self.confidence,
            "evidence_text": self.evidence_text,
            "evidence_start": self.evidence_start,
            "evidence_end": self.evidence_end,
            "source_id": self.source_id,
            "source_page": self.source_page,
            "source_segment": self.source_segment,
            "extraction_method": _enum_value(self.extraction_method),
            "model": self.model,
            "negated": self.negated,
            "temporal_scope": self.temporal_scope,
            "epistemic_status": _enum_value(self.epistemic_status),
            "workspace": self.workspace,
            "validation_flags": list(self.validation_flags),
        }

    def to_json(self) -> str:
        """JSON determinista: claves ordenadas, separadores estables."""
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )

    # -- Reconstruccion ----------------------------------------------------
    _FIELD_NAMES = None  # se completa tras la definicion de la clase

    @classmethod
    def from_dict(cls, data: dict, *, validate: bool = True) -> "RelationCandidate":
        """Reconstruye desde dict.

        Compatibilidad futura: un campo desconocido se RECHAZA (lanza
        RelationContractError). El contrato interno-v1 es cerrado: cualquier
        clave fuera de los 20 campos indica otra version u otro contrato y no
        debe silenciarse.
        """
        if not isinstance(data, dict):
            raise RelationContractError("from_dict espera un dict")
        known = cls._field_names()
        unknown = set(data) - known
        if unknown:
            raise RelationContractError(
                f"campos desconocidos en relation-candidate/internal-v1: {sorted(unknown)}"
            )
        missing = known - set(data)
        # validation_flags tiene default; el resto es obligatorio en el payload.
        missing.discard("validation_flags")
        if missing:
            raise RelationContractError(f"faltan campos obligatorios: {sorted(missing)}")

        inst = cls(
            subject_id=data.get("subject_id"),
            subject_type=data.get("subject_type"),
            predicate=data.get("predicate"),
            object_id=data.get("object_id"),
            object_type=data.get("object_type"),
            direction=data.get("direction"),
            confidence=data.get("confidence"),
            evidence_text=data.get("evidence_text"),
            evidence_start=data.get("evidence_start"),
            evidence_end=data.get("evidence_end"),
            source_id=data.get("source_id"),
            source_page=data.get("source_page"),
            source_segment=data.get("source_segment"),
            extraction_method=data.get("extraction_method"),
            model=data.get("model"),
            negated=data.get("negated"),
            temporal_scope=data.get("temporal_scope"),
            epistemic_status=data.get("epistemic_status"),
            workspace=data.get("workspace"),
            validation_flags=list(data.get("validation_flags", [])),
        )
        if validate:
            inst.validate()
        return inst

    @classmethod
    def from_json(cls, raw: str, *, validate: bool = True) -> "RelationCandidate":
        """Reconstruye desde JSON. Round-trip estable con to_json()."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RelationContractError(f"JSON invalido: {exc}") from exc
        return cls.from_dict(data, validate=validate)

    @classmethod
    def _field_names(cls) -> set:
        if cls._FIELD_NAMES is None:
            cls._FIELD_NAMES = {f.name for f in dataclass_fields(cls)}
        return cls._FIELD_NAMES

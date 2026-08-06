# -*- coding: utf-8 -*-
"""model.py — vocabulario ligero de `knowledge-visibility/v1` (M5b-0).

CRITICO: este modulo debe poder importarse desde data-engine, contratos V3,
writer, visor y tests SIN importar `viewer.app`, `pydantic_settings` ni
configuracion de aplicacion alguna. Solo usa la libreria estandar (`dataclasses`,
`enum`, `re`, `json`) mas `jsonschema`/`referencing`, que ya son dependencias
compartidas por motor y visor (las usa `contracts/knowledge-v3/v1/validator.py`,
cargado hoy desde `data-engine/app/knowledge_v3/contracts/base.py`). NUNCA
importar aqui nada bajo `viewer/app/` ni `data-engine/app/knowledge_v3/`: la
direccion de dependencia va de este modulo HACIA ellos, nunca al reves (si
alguien necesita algo de aqui, importa este fichero; este fichero no conoce a
nadie).

Repite el patron de `viewer/app/authz/scope.py` (contrato ligero) y de
`contracts/knowledge-v3/v1/validator.py` (JSON Schema como fuente de verdad
estructural + validacion semantica en Python, sin reinterpretar valores).

Semantica: NO se inventa nada nuevo. `VisibilityLevel` y `known_by` son el
mismo vocabulario que ya lee/escribe `viewer/app/policies/{models,engine}.py`
(`node.get("visibility")`, `node.get("known_by")`), mas el estado terminal
`deny`, nuevo EN EL CONTRATO, ausente todavia del motor (ver
`V3VisibilityPolicyAdapter` en `viewer/app/authz/visibility_contract.py`, que
es quien lo intercepta).

Regla dura, repetida del schema: fail-closed. Cualquier valor de `visibility`
fuera del enum cerrado, o el campo ausente, se trata como no visible. Nunca hay
un default permisivo.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "knowledge-visibility-v1.schema.json"

CONTRACT_ID = "knowledge-visibility/v1"
CONTRACT_FAMILY = "knowledge-visibility"
SUPPORTED_MAJOR = 1

#: Mismo patron que `stable_id` de contracts/knowledge-v3/v1/_common-v3.schema.json,
#: repetido aqui en vez de importado: este modulo no debe depender de la
#: familia v3-internal-v1 para poder importarse de forma aislada (ver docstring).
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTRACT_VERSION_RE = re.compile(r"^1\.[0-9]+\.[0-9]+$")


class ContractVisibilityError(ValueError):
    """Documento `knowledge-visibility/v1` invalido o incoherente."""


class VisibilityLevel(str, Enum):
    """Enum CERRADO. Cualquier valor fuera de este conjunto es invalido, no
    'desconocido pero tolerado'. `deny` es un estado terminal absoluto: ver
    docstring del modulo y `V3VisibilityPolicyAdapter`.
    """

    PLAYER = "player"
    NARRATOR = "narrator"
    SECRET = "secret"
    REFERENCE = "reference"
    DENY = "deny"


#: Conjunto canonico, para comprobaciones sin pasar por el enum (p. ej. datos
#: crudos leidos de JSON antes de intentar construir el dataclass).
VALID_VISIBILITY_VALUES = frozenset(v.value for v in VisibilityLevel)


def is_valid_character_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_STABLE_ID_RE.match(value))


def is_valid_stable_id_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(_STABLE_ID_RE.match(value)))


def is_valid_hash_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(_HASH_RE.match(value)))


@dataclass(frozen=True)
class KnowledgeVisibilityV1:
    """Vocabulario PERSISTIDO de visibilidad de un hecho de conocimiento.

    Deliberadamente NO incluye `party_membership`, `active_character`,
    `max_visible_session` ni `can_view_secret`: esos viven en el contexto de
    peticion (`viewer/app/policies/models.py::ViewerContext`), nunca en el
    hecho persistido. Ver docs/v3/51 (ADR) para la justificacion completa.

    Inmutable (`frozen=True`), mismo criterio que `ViewerContext`: una
    decision de visibilidad nunca debe depender de mutacion posterior del
    objeto que la origino.
    """

    visibility: VisibilityLevel
    known_by: tuple[str, ...] = field(default_factory=tuple)
    contract_version: str = "1.0.0"
    claim_id: Optional[str] = None
    assertion_id: Optional[str] = None
    plan_id: Optional[str] = None
    state_hash: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    contract_id: str = field(default=CONTRACT_ID, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.visibility, VisibilityLevel):
            raise ContractVisibilityError(
                f"visibility invalido o ausente: {self.visibility!r} "
                f"(enum cerrado: {sorted(VALID_VISIBILITY_VALUES)})"
            )
        if not _CONTRACT_VERSION_RE.match(self.contract_version):
            raise ContractVisibilityError(
                f"contract_version invalida: {self.contract_version!r}"
            )
        for cid in self.known_by:
            if not is_valid_character_id(cid):
                raise ContractVisibilityError(f"character_id invalido en known_by: {cid!r}")
        if len(set(self.known_by)) != len(self.known_by):
            raise ContractVisibilityError("known_by contiene character_id duplicados")
        for name, value in (
            ("claim_id", self.claim_id),
            ("assertion_id", self.assertion_id),
            ("plan_id", self.plan_id),
        ):
            if not is_valid_stable_id_or_none(value):
                raise ContractVisibilityError(f"{name} invalido: {value!r}")
        if not is_valid_hash_or_none(self.state_hash):
            raise ContractVisibilityError(f"state_hash invalido: {self.state_hash!r}")

    # -- serializacion ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "visibility": self.visibility.value,
            "known_by": list(self.known_by),
        }
        if self.claim_id is not None:
            doc["claim_id"] = self.claim_id
        if self.assertion_id is not None:
            doc["assertion_id"] = self.assertion_id
        if self.plan_id is not None:
            doc["plan_id"] = self.plan_id
        if self.state_hash is not None:
            doc["state_hash"] = self.state_hash
        if self.metadata:
            doc["metadata"] = dict(self.metadata)
        return doc

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> "KnowledgeVisibilityV1":
        """Construye desde un dict. RECHAZA campos desconocidos (cerrado, mismo
        criterio que `additionalProperties: false` del schema) y NO aplica
        ningun default permisivo: `visibility` y `known_by` son obligatorios.
        """
        if not isinstance(doc, dict):
            raise ContractVisibilityError("documento no es un objeto")

        contract_id = doc.get("contract_id")
        if contract_id != CONTRACT_ID:
            raise ContractVisibilityError(f"contract_id invalido: {contract_id!r}")

        known_fields = {
            "contract_id",
            "contract_version",
            "visibility",
            "known_by",
            "claim_id",
            "assertion_id",
            "plan_id",
            "state_hash",
            "metadata",
        }
        unknown = set(doc) - known_fields
        if unknown:
            raise ContractVisibilityError(f"campos desconocidos: {sorted(unknown)}")

        if "visibility" not in doc:
            raise ContractVisibilityError("visibility ausente (fail-closed: no hay default)")
        raw_visibility = doc["visibility"]
        if raw_visibility not in VALID_VISIBILITY_VALUES:
            raise ContractVisibilityError(f"visibility fuera de enum: {raw_visibility!r}")

        if "known_by" not in doc:
            raise ContractVisibilityError("known_by ausente (fail-closed: no hay default)")
        raw_known_by = doc["known_by"]
        if not isinstance(raw_known_by, list):
            raise ContractVisibilityError("known_by debe ser una lista")

        return cls(
            visibility=VisibilityLevel(raw_visibility),
            known_by=tuple(raw_known_by),
            contract_version=doc.get("contract_version", "1.0.0"),
            claim_id=doc.get("claim_id"),
            assertion_id=doc.get("assertion_id"),
            plan_id=doc.get("plan_id"),
            state_hash=doc.get("state_hash"),
            metadata=dict(doc.get("metadata") or {}),
        )


def load_schema() -> dict[str, Any]:
    """Carga perezosa del JSON Schema (no se cachea en import: cada llamador
    que quiera validar por schema decide cuando pagar el coste de I/O).
    """
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_against_schema(doc: dict[str, Any]) -> None:
    """Validacion estructural completa vía JSON Schema (draft 2020-12).

    Import perezoso de `jsonschema`/`referencing`: si algun consumidor
    realmente minimo no los tiene instalados, puede seguir usando
    `KnowledgeVisibilityV1.from_dict` (validacion semantica pura Python) sin
    que la mera importacion de este modulo falle.
    """
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schema = load_schema()
    resource = Resource(contents=schema, specification=DRAFT202012)
    registry = Registry().with_resource(str(SCHEMA_PATH), resource)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise ContractVisibilityError(f"documento invalido contra el schema: {detail}")


def is_valid(doc: dict[str, Any]) -> bool:
    try:
        validate_against_schema(doc)
        KnowledgeVisibilityV1.from_dict(doc)
    except ContractVisibilityError:
        return False
    return True

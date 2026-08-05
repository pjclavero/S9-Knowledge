# -*- coding: utf-8 -*-
"""Base comun de los contratos internos `v3-internal-v1`.

Patron heredado de `relations/contracts.py` (dataclass cerrada, `to_dict`,
`to_json` determinista, `from_dict` que RECHAZA campos desconocidos) combinado
con el de `contracts/review-ingest/v1/` (JSON Schema como fuente de verdad
estructural + validador semantico compartido).

No hay duplicacion de reglas: los modelos Python NO reimplementan las reglas
del schema, las delegan en `contracts/knowledge-v3/v1/validator.py`. Si un dia
divergen, divergen en un solo sitio: no pueden.

Ningun metodo de este modulo escribe en Neo4j, llama a proveedores ni genera
timestamps: la serializacion es una funcion pura de los datos.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, fields as dataclass_fields
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

# --- Carga del validador compartido ---------------------------------------
# El validador vive en contracts/knowledge-v3/v1/ (fuera de data-engine) porque
# lo comparten motor y visor, igual que el de review/ingest v1. Se carga por
# ruta relativa al fichero, nunca por ruta absoluta cableada.
_REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = _REPO_ROOT / "contracts" / "knowledge-v3" / "v1"
_VALIDATOR_PATH = CONTRACTS_DIR / "validator.py"

_MODULE_NAME = "s9k_knowledge_v3_contract_validator"
if _MODULE_NAME in sys.modules:  # pragma: no cover - cache entre imports
    schema_validator = sys.modules[_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _VALIDATOR_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover
        raise ImportError(f"no se pudo cargar el validador v3 en {_VALIDATOR_PATH}")
    schema_validator = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = schema_validator
    _spec.loader.exec_module(schema_validator)

#: Error unico de la familia: el mismo que lanza el validador de schema, para
#: que quien captura no tenga que conocer dos jerarquias.
V3ContractError = schema_validator.ContractV3Error

canonical_json = schema_validator.canonical_json
sha256_hash = schema_validator.sha256_hash
compute_decision_hash = schema_validator.compute_decision_hash
compute_plan_hash = schema_validator.compute_plan_hash
compute_idempotency_key = schema_validator.compute_idempotency_key
seal_plan = schema_validator.seal_plan
producing_step = schema_validator.producing_step

#: Version de contrato que emite esta rama del codigo.
#: M0 (docs/v3/49-multipartida-diseno.md) NO bumpea esta constante. El diseno
#: (§2.2) sugeria un bump MAYOR asumiendo que `partida_id` seria "un campo
#: nuevo obligatorio en el esquema JSON Schema congelado" — pero se decidio
#: la variante ADITIVA y conservadora (§5, tabla M0: "campo opcional, todo
#: el codigo existente sigue funcionando con partida_id=None"): NO esta en
#: `required` de ningun `.schema.json`, `additionalProperties` sigue en
#: `false` solo para claves de verdad desconocidas. `_check_major_version`
#: (validator.py) acepta sin cambios cualquier `1.x.y` con o sin el campo
#: nuevo, y `test_contract_version_is_the_v1_of_la_v3_family` fija que TODAS
#: las fixtures declaran literalmente esta constante: bumpearla a 1.1.0
#: habria obligado a regenerar 264+ fixtures/goldens sin ganar nada (mover
#: tests existentes esta prohibido en M0). Documentos que SI quieran declarar
#: `partida_id` pueden seguir usando "1.0.0": el esquema ya lo admite.
CONTRACT_VERSION = "1.0.0"
CONTRACT_FAMILY = schema_validator.CONTRACT_FAMILY


class Provider(str, Enum):
    """Clase de proveedor de un paso de `provider_trace`.

    `EXTERNAL` nunca decide ni firma: solo puede aparecer en trazas de
    propuestas (ClaimProposal, EntityMention), jamas en `local_approval`.
    """

    LOCAL = "local"
    OLLAMA = "ollama"
    EXTERNAL = "external"


def find_step(trace: list, step: str) -> dict:
    """Entrada de una `provider_trace` por su `step`."""
    for entry in trace:
        if entry.get("step") == step:
            return entry
    raise V3ContractError(f"step {step!r} ausente de la provider_trace")


def provider_step(
    step: str,
    provider: "Provider | str",
    name: str,
    version: str,
    produced: list[str],
    *,
    model: str | None = None,
    params_hash: dict | None = None,
) -> dict:
    """Construye una entrada de `provider_trace` normalizada y determinista."""
    value = provider.value if isinstance(provider, Provider) else str(provider)
    entry: dict[str, Any] = {
        "step": step,
        "provider": value,
        "name": name,
        "version": version,
        "model": model,
        "produced": list(produced),
    }
    if params_hash is not None:
        entry["params_hash"] = params_hash
    return entry


@dataclass
class V3Document:
    """Documento interno V3.

    Subclases: fijan `CONTRACT_ID` y declaran sus campos como dataclass. Los
    campos opcionales del schema se declaran con `default=None` y se OMITEN en
    la serializacion cuando valen `None`, de modo que el round-trip sigue siendo
    exacto (`from_dict(to_dict(x)) == x`).
    """

    CONTRACT_ID: ClassVar[str] = ""
    #: Campos que pueden faltar en el documento serializado.
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"metadata"})

    # -- Serializacion -----------------------------------------------------
    def to_dict(self) -> dict:
        """Dict con `contract_id` inyectado y sin campos opcionales vacios."""
        out: dict[str, Any] = {"contract_id": self.CONTRACT_ID}
        for f in dataclass_fields(self):
            value = getattr(self, f.name)
            if value is None and f.name in self.OMIT_IF_NONE:
                continue
            out[f.name] = value
        return out

    def to_json(self) -> str:
        """JSON canonico: claves ordenadas, separadores minimos, estable byte a byte."""
        return canonical_json(self.to_dict())

    # -- Validacion --------------------------------------------------------
    def validate(self) -> "V3Document":
        """Valida contra el JSON Schema + reglas semanticas. Devuelve self."""
        schema_validator.validate_document(self.to_dict())
        return self

    def is_valid(self) -> bool:
        try:
            self.validate()
            return True
        except V3ContractError:
            return False

    def document_hash(self) -> dict:
        """Hash sha256 del documento canonico. Util para procedencia y dedup.

        Se llama `document_hash` y no `content_hash` a proposito: `content_hash`
        es un CAMPO de SourceAsset y SourceEpisode, y un metodo con ese nombre
        en la base lo pisaria como valor por defecto del dataclass.
        """
        return sha256_hash(self.to_dict())

    # -- Reconstruccion ----------------------------------------------------
    @classmethod
    def _field_names(cls) -> set[str]:
        return {f.name for f in dataclass_fields(cls)}

    @classmethod
    def _optional_names(cls) -> set[str]:
        import dataclasses

        return {
            f.name
            for f in dataclass_fields(cls)
            if f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        }

    @classmethod
    def from_dict(cls, data: dict, *, validate: bool = True) -> "V3Document":
        """Reconstruye desde dict.

        Contrato CERRADO: cualquier clave fuera de las declaradas se rechaza.
        Un campo desconocido significa otra version u otro contrato y no debe
        silenciarse jamas.
        """
        if not isinstance(data, dict):
            raise V3ContractError("from_dict espera un dict")
        cid = data.get("contract_id")
        if cid != cls.CONTRACT_ID:
            raise V3ContractError(
                f"contract_id {cid!r} no corresponde a {cls.__name__} ({cls.CONTRACT_ID!r})"
            )
        known = cls._field_names()
        unknown = set(data) - known - {"contract_id"}
        if unknown:
            raise V3ContractError(
                f"campos desconocidos en {cls.CONTRACT_ID}: {sorted(unknown)}"
            )
        missing = known - set(data) - cls._optional_names()
        if missing:
            raise V3ContractError(f"faltan campos obligatorios: {sorted(missing)}")
        inst = cls(**{k: v for k, v in data.items() if k in known})
        if validate:
            inst.validate()
        return inst

    @classmethod
    def from_json(cls, raw: str, *, validate: bool = True) -> "V3Document":
        """Reconstruye desde JSON. Round-trip exacto con `to_json()`."""
        import json

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise V3ContractError(f"JSON invalido: {exc}") from exc
        return cls.from_dict(data, validate=validate)


def parse_document(data: dict, *, validate: bool = True) -> V3Document:
    """Despacha a la clase correcta segun `contract_id`."""
    from . import CONTRACT_CLASSES  # import diferido: evita ciclo de import

    cid = data.get("contract_id") if isinstance(data, dict) else None
    cls = CONTRACT_CLASSES.get(cid)
    if cls is None:
        raise V3ContractError(f"contract_id desconocido o ausente: {cid!r}")
    return cls.from_dict(data, validate=validate)

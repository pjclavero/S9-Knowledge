"""
validator.py — validador UNICO de la familia de contratos internos `v3-internal-v1`.

Mismo patron que `contracts/review-ingest/v1/validator.py`: los `.schema.json` de
este directorio son la fuente de verdad estructural y este modulo anade las
comprobaciones SEMANTICAS que JSON Schema no puede expresar (coherencia de
hashes, unicidad de identificadores, referencias cruzadas, firma del plan).

Ofrece:
  - `canonical_json(obj)`  : serializacion determinista (claves ordenadas, sin
    espacios, sin timestamps generados). Byte a byte estable.
  - `sha256_hash(obj)`     : hash con algoritmo explicito sobre el JSON canonico.
  - `compute_decision_hash(plan)` / `compute_plan_hash(plan)` / `seal_plan(plan)`
    para `graph-mutation-plan/v3-internal-v1`.
  - `validate_document(doc)`: valida por `contract_id` y lanza `ContractV3Error`.
  - `is_valid(doc)`        : version booleana.

No escribe en Neo4j ni en disco. No tiene efectos secundarios. No importa nada
de `data-engine`: es autonomo, igual que el validador v1.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_DIR = Path(__file__).resolve().parent

#: Familia de contratos. Todos los documentos llevan `contract_id`
#: `<nombre>/v3-internal-v1` y una `contract_version` `1.x.y`.
CONTRACT_FAMILY = "v3-internal-v1"
SUPPORTED_MAJOR = 1

CONTRACT_SCHEMAS = {
    "source-asset/v3-internal-v1": "source-asset-v3.schema.json",
    "source-episode/v3-internal-v1": "source-episode-v3.schema.json",
    "evidence-fragment/v3-internal-v1": "evidence-fragment-v3.schema.json",
    "entity-mention/v3-internal-v1": "entity-mention-v3.schema.json",
    "claim-proposal/v3-internal-v1": "claim-proposal-v3.schema.json",
    "entity-resolution/v3-internal-v1": "entity-resolution-v3.schema.json",
    "fact-assertion/v3-internal-v1": "fact-assertion-v3.schema.json",
    "graph-mutation-plan/v3-internal-v1": "graph-mutation-plan-v3.schema.json",
    "game-profile/v3-internal-v1": "game-profile-v3.schema.json",
}

#: Bloques deliberadamente abiertos (`additionalProperties: true`). Son las
#: UNICAS excepciones de la familia y se justifican en docs/v3/01-contracts-v3.md.
OPEN_BLOCKS = ("metadata", "payload")

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|cookie|api[_-]?key|authorization|credential)",
    re.IGNORECASE,
)
_URL_WITH_USERINFO = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/@\s]+@")


class ContractV3Error(ValueError):
    """Documento que incumple un contrato `v3-internal-v1` (schema o semantica)."""


# --------------------------------------------------------------------------
# Serializacion determinista
# --------------------------------------------------------------------------
def canonical_json(obj: Any) -> str:
    """JSON canonico: claves ordenadas, separadores minimos, UTF-8 literal.

    Es la unica forma admitida de serializar un documento V3 para hashearlo o
    para compararlo byte a byte. NO introduce timestamps ni ningun valor
    generado en tiempo de serializacion.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hash(obj: Any) -> dict[str, str]:
    """Hash sha256 (con algoritmo explicito) del JSON canonico de `obj`."""
    digest = hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
    return {"algorithm": "sha256", "value": digest}


# --------------------------------------------------------------------------
# Firma del GraphMutationPlan
# --------------------------------------------------------------------------
#: Campos de primer nivel que entran en el hash de decision. Cambiar el
#: workspace, el source hash, el snapshot, las versiones, el perfil, la
#: caducidad, las decisiones o las operaciones rompe la firma.
#: M0 (docs/v3/49-multipartida-diseno.md): SE INTENTO anadir "partida_id" y
#: "scope" aqui para que el ambito quedase cubierto por `decision_hash`, no
#: solo por `plan_hash`. Se REVIRTIO: `compute_decision_hash` hace
#: `plan.get(k)` para cada campo de esta tupla, asi que anadir una clave
#: nueva mete `"partida_id": None, "scope": None` en el CUERPO DE TODO plan
#: ya existente (tenga o no el campo), lo que cambia el `decision_hash`
#: esperado de cientos de documentos `graph-mutation-plan` ya sellados en
#: los datasets gold/held-out/negation-battery — literales congelados que
#: este bloque tiene prohibido tocar. `plan_hash` SI cubre `partida_id`/
#: `scope` gratis (incluye el documento completo salvo el propio
#: `plan_hash`), asi que el plan queda protegido contra manipulacion aun
#: sin este cambio. El AGUJERO REAL que documenta el diseno persiste,
#: acotado: dos planes que solo difieren en `partida_id`/`scope` tienen
#: `plan_hash` distinto (integridad) pero el MISMO `decision_hash` (el
#: cuerpo que el writer usa para decidir si aplica no lo distingue).
#:
#: M3 (docs/v3/49 §9, "M3 implementado"): ya existe el consumidor real que
#: la politica exigia (`PLAN_SCOPE_CROSS_PARTIDA` en `writer/admission.py`),
#: pero el hueco se deja ABIERTO deliberadamente, no cerrado. Verificado (no
#: asumido): NINGUN plan de `heldout`/`negation-battery`/`benchmarks`
#: declara `partida_id`/`scope` (`grep` sobre
#: `data-engine/app/knowledge_v3/benchmarks/` sin resultados) -- el riesgo
#: real de la ambiguedad es CERO en los datasets congelados hoy. Anadir
#: estas claves aqui seguiria cambiando el `decision_hash` esperado de
#: TODOS ellos (`plan.get(k)` inserta `None` en el cuerpo de cada plan que
#: nunca declaro el campo), obligando a una regeneracion auditable de 264+
#: ficheros que este bloque decide no bundlear en la misma superficie que
#: el writer. Queda como operacion propia y explicita si un bloque futuro
#: necesita de verdad que `decision_hash` distinga ambito.
DECISION_HASH_FIELDS = (
    "workspace",
    "source_asset_id",
    "source_hash",
    "snapshot_id",
    "engine_version",
    "ontology_version",
    "game_profile",
    "collection_id",
    "expires_at",
    "decisions",
    "mutation_operations",
)

#: Campos de `local_approval` que TAMBIEN entran. El writer los consume para
#: decidir si aplica: si quedasen fuera del hash, cambiar `approved` de false a
#: true no rompería nada.
DECISION_HASH_APPROVAL_FIELDS = ("approved", "approved_by", "validator_chain")

#: Campos que definen la IDENTIDAD LOGICA de una operacion. `operation_id` NO
#: esta: la misma operacion calculada en dos planes distintos debe producir la
#: misma clave de idempotencia, o reaplicar duplica.
#:
#: M3 (docs/v3/49 §9, mismo rigor que `DECISION_HASH_FIELDS` arriba):
#: `partida_id`/`scope` TAMPOCO entran aqui. Verificado, no supuesto: dos
#: planes de partidas DISTINTAS con la misma identidad logica de operacion
#: (mismo `decision_id`/`target_entity_id`/`payload`) comparten
#: `idempotency_key` (ver
#: `test_dos_partidas_con_operacion_identica_comparten_idempotency_key_pero_no_corrompen`,
#: `data-engine/app/tests/test_knowledge_v3_writer.py`). NO es un agujero de
#: corrupcion: `writer/executor.py` reclama la clave con
#: `claim_applied_operation` dentro de la misma transaccion y, si ya esta
#: tomada por un `plan_hash`/`operation_id` distinto, aborta con
#: `EXEC_IDEMPOTENCY_CONFLICT` -- fail-closed, nunca una fusion silenciosa.
#: Se deja sin tocar por la misma razon que `DECISION_HASH_FIELDS`: tocar
#: esta tupla es cirugia de contrato congelado que exigiria regenerar
#: idempotency_key en datasets ya sellados, sin comprar ninguna garantia de
#: seguridad nueva (la que hace falta ya la da el `EXEC_IDEMPOTENCY_
#: CONFLICT`, no la propia clave).
IDEMPOTENCY_KEY_FIELDS = (
    "operation_type",
    "decision_id",
    "target_entity_id",
    "assertion_id",
    "payload",
)


def compute_decision_hash(plan: dict[str, Any]) -> dict[str, str]:
    """Hash del cuerpo de decision del plan.

    Cubre DECISION_HASH_FIELDS mas DECISION_HASH_APPROVAL_FIELDS de
    `local_approval`. NO incluye `decision_hash` (seria circular).
    """
    approval = plan.get("local_approval")
    body: dict[str, Any] = {k: plan.get(k) for k in DECISION_HASH_FIELDS}
    body["local_approval"] = (
        {k: approval.get(k) for k in DECISION_HASH_APPROVAL_FIELDS}
        if isinstance(approval, dict)
        else None
    )
    return sha256_hash(body)


def compute_idempotency_key(plan: dict[str, Any], operation: dict[str, Any]) -> str:
    """Clave de idempotencia DERIVADA de la operacion, no inventada.

    Se calcula sobre {workspace, snapshot_id} del plan mas la identidad logica
    de la operacion. Deterministica y reproducible por el writer.
    """
    body = {
        "workspace": plan.get("workspace"),
        "snapshot_id": plan.get("snapshot_id"),
        **{k: operation.get(k) for k in IDEMPOTENCY_KEY_FIELDS},
    }
    return "idem:sha256:" + sha256_hash(body)["value"]


def compute_plan_hash(plan: dict[str, Any]) -> dict[str, str]:
    """Hash del plan completo EXCLUYENDO `plan_hash`.

    Incluye `local_approval` (y por tanto `decision_hash`): alterar la firma
    tambien invalida el plan.
    """
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    return sha256_hash(body)


def seal_plan(plan: dict[str, Any], *, derive_keys: bool = True) -> dict[str, Any]:
    """Devuelve una COPIA del plan con claves e hashes calculados.

    No muta la entrada. El orden importa: primero las claves de idempotencia,
    luego la decision, y por ultimo el plan completo (que ya las incluye).

    `derive_keys=False` sella sin recalcular las claves de idempotencia; sirve
    para construir en los tests un plan con claves deliberadamente incorrectas
    y comprobar que el validador lo rechaza.
    """
    sealed = deepcopy(plan)
    if derive_keys:
        for op in sealed.get("mutation_operations") or []:
            if isinstance(op, dict):
                op["idempotency_key"] = compute_idempotency_key(sealed, op)
    approval = sealed.get("local_approval")
    if isinstance(approval, dict):
        approval["decision_hash"] = compute_decision_hash(sealed)
    sealed["plan_hash"] = compute_plan_hash(sealed)
    return sealed


# --------------------------------------------------------------------------
# Carga de schemas
# --------------------------------------------------------------------------
def _load_json(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def build_registry() -> Registry:
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = _load_json(path.name)
        resources.append(
            (doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012))
        )
    return Registry().with_resources(resources)


_REGISTRY = build_registry()


def schema_for(contract_id: str) -> dict[str, Any]:
    if contract_id not in CONTRACT_SCHEMAS:
        raise ContractV3Error(f"contract_id desconocido: {contract_id!r}")
    return _load_json(CONTRACT_SCHEMAS[contract_id])


def _check_major_version(doc: dict[str, Any]) -> None:
    ver = str(doc.get("contract_version", ""))
    m = re.match(r"^(\d+)\.", ver)
    if not m:
        raise ContractV3Error(f"contract_version invalida: {ver!r}")
    if int(m.group(1)) != SUPPORTED_MAJOR:
        raise ContractV3Error(
            f"version mayor no soportada: {ver} (soporto {SUPPORTED_MAJOR}.x)"
        )


# --------------------------------------------------------------------------
# Comprobaciones semanticas
# --------------------------------------------------------------------------
def _find_sensitive(obj: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _SENSITIVE_KEY.search(str(k)):
                hits.append(f"{path}/{k}")
            hits += _find_sensitive(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _find_sensitive(v, f"{path}[{i}]")
    return hits


#: Mapa de las diez decisiones del dosier 11.7 al par (decision, reason_code)
#: que las representa en el contrato. El contrato tiene CUATRO decisiones y un
#: eje de razones: mantener diez valores de decision habria mezclado "que se
#: decidio" con "por que", y el writer solo necesita lo primero.
ENGINE_DECISION_MAP = {
    "LOCAL_APPROVED": ("ACCEPT", "LOCAL_APPROVED"),
    "LOCAL_APPROVED_WITH_WARNINGS": ("ACCEPT", "LOCAL_APPROVED_WITH_WARNINGS"),
    "REVIEW_ENTITY": ("REVIEW", "REVIEW_ENTITY"),
    "REVIEW_PREDICATE": ("REVIEW", "REVIEW_PREDICATE"),
    "REVIEW_DIRECTION": ("REVIEW", "REVIEW_DIRECTION"),
    "REVIEW_TEMPORALITY": ("REVIEW", "REVIEW_TEMPORALITY"),
    "REVIEW_EVIDENCE": ("REVIEW", "REVIEW_EVIDENCE"),
    "CONFLICT": ("REVIEW", "CONFLICT_WITH_EXISTING"),
    "ABSTAIN": ("ABSTAIN", "INSUFFICIENT_EVIDENCE"),
    "REJECT_INVALID": ("REJECT_INVALID", "ONTOLOGY_INCOMPATIBLE"),
}

#: Razones canonicas admisibles por decision. Cada decision del plan DEBE
#: llevar al menos una: un `reason_codes` de texto libre convierte la
#: trazabilidad del motor en prosa no agregable.
CANONICAL_REASON_CODES = {
    "ACCEPT": {"LOCAL_APPROVED", "LOCAL_APPROVED_WITH_WARNINGS"},
    "REVIEW": {
        "REVIEW_ENTITY", "REVIEW_PREDICATE", "REVIEW_DIRECTION",
        "REVIEW_TEMPORALITY", "REVIEW_EVIDENCE", "CONFLICT_WITH_EXISTING",
    },
    "ABSTAIN": {"INSUFFICIENT_EVIDENCE", "AMBIGUOUS_SEMANTICS", "LOW_QUALITY_EPISODE"},
    "REJECT_INVALID": {"ONTOLOGY_INCOMPATIBLE", "TYPE_INCOMPATIBLE", "DEMONSTRABLY_FALSE"},
}


#: Orden canonico de `direction` para desempatar. Sin un desempate TOTAL, dos
#: candidatos con la misma confianza dejan la direccion elegida a merced del
#: orden de llegada, y el pipeline deja de ser determinista.
DIRECTION_ORDER = {"SUBJECT_TO_OBJECT": 0, "OBJECT_TO_SUBJECT": 1, "UNDIRECTED": 2}


def predicate_sort_key(c: dict[str, Any]) -> tuple:
    """Confianza descendente; empate por predicado alfabetico."""
    return (-float(c["confidence"]), str(c["predicate"]))


def direction_sort_key(c: dict[str, Any]) -> tuple:
    """Confianza descendente; empate por el orden canonico del enum."""
    return (-float(c["confidence"]), DIRECTION_ORDER.get(c["direction"], 99))


def alternative_sort_key(a: dict[str, Any]) -> tuple:
    """Confianza descendente; empate por predicado y despues por direccion."""
    return (
        -float(a["confidence"]),
        str(a["predicate"]),
        DIRECTION_ORDER.get(a["direction"], 99),
    )


def _check_total_order(items: list, key, label: str) -> None:
    if list(items) != sorted(items, key=key):
        raise ContractV3Error(
            f"{label} no esta en el orden canonico (confianza descendente con "
            "desempate determinista); sin orden total la eleccion no es reproducible"
        )


def _dupes(values: list[Any]) -> list[Any]:
    seen: set = set()
    out: list = []
    for v in values:
        key = canonical_json(v) if isinstance(v, (dict, list)) else v
        if key in seen:
            out.append(v)
        else:
            seen.add(key)
    return out


def _check_open_blocks(doc: Any, where: str = "") -> None:
    """Los bloques abiertos (`metadata`, `payload`) nunca llevan secretos."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k in OPEN_BLOCKS and isinstance(v, dict):
                hits = _find_sensitive(v, f"{where}/{k}")
                if hits:
                    raise ContractV3Error(
                        f"campos sensibles prohibidos en bloque abierto: {hits}"
                    )
            _check_open_blocks(v, f"{where}/{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            _check_open_blocks(v, f"{where}[{i}]")


def _check_provider_trace(doc: dict[str, Any]) -> None:
    trace = doc.get("provider_trace") or []
    steps = [e.get("step") for e in trace]
    dup = _dupes(steps)
    if dup:
        raise ContractV3Error(f"provider_trace con step duplicado: {sorted(set(dup))}")
    produced_by = doc.get("produced_by_step")
    if produced_by not in steps:
        raise ContractV3Error(
            f"produced_by_step={produced_by!r} no corresponde a ningun step de "
            f"provider_trace {steps}: la atribucion de proveedor quedaria colgando"
        )


def producing_step(doc: dict[str, Any]) -> dict[str, Any]:
    """Entrada de `provider_trace` senalada por `produced_by_step`."""
    for entry in doc.get("provider_trace") or []:
        if entry.get("step") == doc.get("produced_by_step"):
            return entry
    raise ContractV3Error("produced_by_step no resuelve a ningun paso de la traza")


def _le(a, b) -> bool:
    return a is None or b is None or a <= b


def _semantic_checks(doc: dict[str, Any]) -> None:  # noqa: C901 - un bloque por contrato
    cid = doc.get("contract_id")
    _check_open_blocks(doc)
    _check_provider_trace(doc)

    if cid == "source-asset/v3-internal-v1":
        if doc["source_hash"] != doc["content_hash"]:
            raise ContractV3Error(
                "en un SourceAsset, source_hash DEBE ser el content_hash del propio asset"
            )
        if doc["source_asset_id"] != doc["asset_id"]:
            raise ContractV3Error("source_asset_id != asset_id en el propio asset")
        if _URL_WITH_USERINFO.match(doc["original_location"]):
            raise ContractV3Error("original_location no puede llevar credenciales embebidas")
        if doc["ingested_at"] < doc["created_at"]:
            raise ContractV3Error("ingested_at anterior a created_at")

    elif cid == "source-episode/v3-internal-v1":
        if doc["source_asset_id"] != doc["asset_id"]:
            raise ContractV3Error("source_asset_id != asset_id en el episodio")
        if not _le(doc["time_start"], doc["time_end"]):
            raise ContractV3Error("time_start > time_end")
        for k in ("previous_episode_id", "next_episode_id"):
            if doc[k] is not None and doc[k] == doc["episode_id"]:
                raise ContractV3Error(f"{k} no puede apuntar al propio episodio")
        if doc["modality"] in ("TEXT", "OCR_TEXT", "HTR_TEXT", "ASR_TEXT") and not doc["text"]:
            raise ContractV3Error(f"modality={doc['modality']} exige texto no vacio")

    elif cid == "evidence-fragment/v3-internal-v1":
        if doc["start"] > doc["end"]:
            raise ContractV3Error("start > end en el fragmento de evidencia")
        if not _le(doc["time_start"], doc["time_end"]):
            raise ContractV3Error("time_start > time_end")
        if doc["media_type"] == "ASR_TEXT" and (doc["time_start"] is None or doc["time_end"] is None):
            raise ContractV3Error("evidencia ASR_TEXT sin anclaje temporal")
        if doc["media_type"] in ("OCR_TEXT", "IMAGE_DESCRIPTION", "MAP", "DIAGRAM") and doc["bbox"] is None:
            raise ContractV3Error(f"evidencia {doc['media_type']} sin bbox: no esta anclada")

    elif cid == "entity-mention/v3-internal-v1":
        if doc["start"] > doc["end"]:
            raise ContractV3Error("start > end en la mencion")
        if doc["mention_id"] in doc["coreference_candidates"]:
            raise ContractV3Error("una mencion no es candidata de correferencia de si misma")
        if _dupes(doc["evidence_fragment_ids"]):
            raise ContractV3Error("evidence_fragment_ids duplicados")
        types = [c["type"] for c in doc["type_candidates"]]
        if _dupes(types):
            raise ContractV3Error("type_candidates con tipo repetido")

    elif cid == "claim-proposal/v3-internal-v1":
        preds = doc["predicate_candidates"]
        _check_total_order(preds, predicate_sort_key, "predicate_candidates")
        _check_total_order(doc["direction_candidates"], direction_sort_key, "direction_candidates")
        _check_total_order(doc["alternatives"], alternative_sort_key, "alternatives")
        if _dupes([c["predicate"] for c in preds]):
            raise ContractV3Error("predicate_candidates con predicado repetido")
        if _dupes([c["direction"] for c in doc["direction_candidates"]]):
            raise ContractV3Error("direction_candidates con direccion repetida")
        overlap = set(doc["subject_mentions"]) & set(doc["object_mentions"])
        if overlap:
            raise ContractV3Error(
                f"una mencion no puede ser sujeto y objeto del mismo claim: {sorted(overlap)}"
            )
        if doc["abstained"] and doc["confidence"] != 0:
            raise ContractV3Error("una abstencion no puede llevar confianza > 0")

    elif cid == "entity-resolution/v3-internal-v1":
        if _dupes(doc["mention_ids"]):
            raise ContractV3Error("mention_ids duplicados")
        action = doc["action"]
        if action == "LINK_EXISTING" and doc["selected_entity_id"] not in doc["candidate_entity_ids"]:
            raise ContractV3Error("LINK_EXISTING a una entidad que no estaba entre los candidatos")
        if action in ("CREATE_NEW", "CREATE_PROVISIONAL") and doc["selected_entity_id"] is not None:
            raise ContractV3Error(f"{action} no puede seleccionar una entidad existente")
        if doc["assigned_entity_id"] is not None and doc["assigned_entity_id"] == doc["selected_entity_id"]:
            raise ContractV3Error("assigned_entity_id no puede coincidir con selected_entity_id")
        if doc["assigned_entity_id"] is not None and doc["assigned_entity_id"] in doc["candidate_entity_ids"]:
            raise ContractV3Error(
                "assigned_entity_id ya existe entre los candidatos: no se estaria creando nada"
            )
        if action == "SPLIT":
            groups = doc.get("split_groups") or []
            flat = [m for g in groups for m in g]
            if _dupes(flat):
                raise ContractV3Error("split_groups no son disjuntos")
            if set(flat) != set(doc["mention_ids"]):
                raise ContractV3Error("split_groups no cubre exactamente mention_ids")

    elif cid == "fact-assertion/v3-internal-v1":
        if not _le(doc["valid_from"], doc["valid_to"]):
            raise ContractV3Error("valid_from posterior a valid_to")
        for k in ("supersedes", "superseded_by"):
            if doc[k] is not None and doc[k] == doc["assertion_id"]:
                raise ContractV3Error(f"{k} no puede apuntar a la propia afirmacion")
        # M4 (docs/v3/49 §2.5): mismo chequeo de autoreferencia que
        # supersedes/superseded_by, para el puntero NO destructivo nuevo.
        if doc.get("local_override_of") is not None and doc.get("local_override_of") == doc["assertion_id"]:
            raise ContractV3Error("local_override_of no puede apuntar a la propia afirmacion")
        if doc["status"] != "SUPERSEDED" and doc["superseded_by"] is not None:
            raise ContractV3Error("superseded_by presente con status != SUPERSEDED")
        if doc["subject_entity_id"] == doc["object_entity_id"]:
            raise ContractV3Error("sujeto y objeto no pueden ser la misma entidad")
        # `state` (eje temporal) y `valid_to` (vigencia) no pueden contradecirse.
        if doc["state"] == "ACTIVE" and doc["valid_to"] is not None:
            raise ContractV3Error("state=ACTIVE con valid_to cerrado")
        if doc["state"] == "ENDED" and doc["valid_to"] is None:
            raise ContractV3Error("state=ENDED sin valid_to: no se sabe cuando termino")

    elif cid == "graph-mutation-plan/v3-internal-v1":
        _check_plan(doc)

    elif cid == "game-profile/v3-internal-v1":
        names = [p["predicate"] for p in doc["predicates"]]
        if _dupes(names):
            raise ContractV3Error("predicados repetidos en el perfil")
        known = set(names)
        for p in doc["predicates"]:
            inv = p.get("inverse_of")
            if inv is not None and inv not in known:
                raise ContractV3Error(f"inverse_of apunta a un predicado inexistente: {inv}")
        if _dupes(doc["entity_types"]):
            raise ContractV3Error("entity_types repetidos en el perfil")


def _check_plan(doc: dict[str, Any]) -> None:
    """Reglas del GraphMutationPlan: las que el writer exige (dosier 13.2 y 18.8)."""
    decisions = doc["decisions"]
    ops = doc["mutation_operations"]
    approval = doc["local_approval"]

    dec_ids = [d["decision_id"] for d in decisions]
    if _dupes(dec_ids):
        raise ContractV3Error("decision_id duplicado")
    for d in decisions:
        allowed = CANONICAL_REASON_CODES[d["decision"]]
        if not (set(d["reason_codes"]) & allowed):
            raise ContractV3Error(
                f"la decision {d['decision_id']} ({d['decision']}) no lleva ninguna "
                f"razon canonica de {sorted(allowed)}: sin ella la decision del "
                "dosier 11.7 no es reconstruible"
            )
    if _dupes([o["operation_id"] for o in ops]):
        raise ContractV3Error("operation_id duplicado")
    if _dupes([o["idempotency_key"] for o in ops]):
        raise ContractV3Error("idempotency_key duplicada: el plan no seria idempotente")
    for o in ops:
        expected_key = compute_idempotency_key(doc, o)
        if o["idempotency_key"] != expected_key:
            raise ContractV3Error(
                f"idempotency_key de {o['operation_id']} no deriva de la operacion "
                "(workspace + snapshot + identidad logica): una clave inventada no "
                "garantiza idempotencia entre planes"
            )
        creates = o["operation_type"] in ("CREATE_ENTITY", "CREATE_ASSERTION")
        if not creates and (o["expected_version"] is None or o["expected_hash"] is None):
            raise ContractV3Error(
                f"{o['operation_id']} modifica algo existente sin expected_version/"
                "expected_hash: no habria concurrencia optimista"
            )
        if creates and (o["expected_version"] is not None or o["expected_hash"] is not None):
            raise ContractV3Error(
                f"{o['operation_id']} crea algo nuevo pero declara estado previo esperado"
            )

    by_id = {d["decision_id"]: d for d in decisions}
    for o in ops:
        d = by_id.get(o["decision_id"])
        if d is None:
            raise ContractV3Error(f"operacion {o['operation_id']} sin decision asociada")
        if d["decision"] != "ACCEPT":
            raise ContractV3Error(
                f"operacion {o['operation_id']} colgando de una decision {d['decision']}: "
                "solo ACCEPT puede generar escritura"
            )

    if doc["expires_at"] <= doc["created_at"]:
        raise ContractV3Error("expires_at no es posterior a created_at")

    if approval["approved"]:
        blocking = [d["decision_id"] for d in decisions if d["decision"] == "REVIEW"]
        if blocking:
            raise ContractV3Error(
                f"plan aprobado con decisiones REVIEW pendientes: {blocking}"
            )
        failed = [v["validator"] for v in approval["validator_chain"] if v["result"] != "PASS"]
        if failed:
            raise ContractV3Error(f"plan aprobado con validadores no PASS: {failed}")

    expected_decision = compute_decision_hash(doc)
    if approval["decision_hash"] != expected_decision:
        raise ContractV3Error(
            "decision_hash no corresponde al cuerpo de decision (plan manipulado)"
        )
    expected_plan = compute_plan_hash(doc)
    if doc["plan_hash"] != expected_plan:
        raise ContractV3Error("plan_hash no corresponde al plan (plan manipulado)")


# --------------------------------------------------------------------------
# API publica
# --------------------------------------------------------------------------
def validate_document(doc: dict[str, Any]) -> None:
    """Valida un documento `v3-internal-v1`. Lanza `ContractV3Error` si no cumple."""
    if not isinstance(doc, dict):
        raise ContractV3Error("documento no es objeto")
    cid = doc.get("contract_id")
    if cid not in CONTRACT_SCHEMAS:
        raise ContractV3Error(f"contract_id desconocido o ausente: {cid!r}")
    _check_major_version(doc)
    schema = schema_for(cid)
    validator = jsonschema.Draft202012Validator(schema, registry=_REGISTRY)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        msgs = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        raise ContractV3Error(f"schema {cid}: {msgs}")
    _semantic_checks(doc)


def is_valid(doc: dict[str, Any]) -> bool:
    try:
        validate_document(doc)
        return True
    except ContractV3Error:
        return False

# relations — contrato interno `relation-candidate/internal-v1`

Paquete de **contrato de datos** para relaciones candidatas del pipeline interno
de relaciones del data-engine. Este paquete contiene **solo** el modelo, sus
enums, los validadores y la serializacion determinista.

## Alcance (lo que este paquete SI hace)

- Define `RelationCandidate` con **exactamente 20 campos**.
- Valida esos campos (`validate()`), con mensajes de error claros.
- Serializa de forma determinista (`to_json` / `from_json`, round-trip estable).

## Fuera de alcance (lo que este paquete NO hace)

- No extrae relaciones ni analiza texto.
- No invoca Ollama, NVIDIA, prompts ni ningun LLM.
- No ejecuta el ensemble/consenso (solo **referencia** sus estados canonicos).
- No autoaprueba ni escribe en Neo4j.

Estos subsistemas viven en otros modulos (`external_ai/`, `external_processing/`,
ingestas, etc.). Aqui unicamente se **referencian**.

## Los 20 campos

| # | campo | tipo | nota |
|---|-------|------|------|
| 1 | `subject_id` | str | obligatorio, no vacio |
| 2 | `subject_type` | str \| null | si se aporta, tipo de entidad valido |
| 3 | `predicate` | str | normalizado MAYUSCULAS_CON_GUION_BAJO |
| 4 | `object_id` | str | obligatorio, no vacio |
| 5 | `object_type` | str \| null | si se aporta, tipo de entidad valido |
| 6 | `direction` | enum | SUBJECT_TO_OBJECT \| OBJECT_TO_SUBJECT \| UNDIRECTED |
| 7 | `confidence` | float | en [0, 1] |
| 8 | `evidence_text` | str | obligatorio salvo `extraction_method=ONTOLOGY` |
| 9 | `evidence_start` | int | >= 0 |
| 10 | `evidence_end` | int | >= 0 y >= `evidence_start` |
| 11 | `source_id` | str | procedencia obligatoria |
| 12 | `source_page` | int \| null | si se aporta, >= 0 |
| 13 | `source_segment` | str | procedencia obligatoria |
| 14 | `extraction_method` | enum | HEURISTIC \| LLM_LOCAL \| NVIDIA \| ONTOLOGY |
| 15 | `model` | str \| null | `modelo@version` o null |
| 16 | `negated` | bool | **bool explicito** |
| 17 | `temporal_scope` | null \| obj | preservado tal cual |
| 18 | `epistemic_status` | enum | ASSERTED \| RUMORED \| HYPOTHETICAL \| INTENDED |
| 19 | `workspace` | str | obligatorio |
| 20 | `validation_flags` | list[str] | lista de flags |

## Diferencia justificada frente a la propuesta (§1)

La propuesta previa en `docs/coordination/contract-proposals.md §1` describia
**18 campos de dominio** (con `evidence_span` y sin `subject_type`/`object_type`).
Este contrato interno-v1 introduce dos cambios deliberados:

1. **Se anaden `subject_type` y `object_type`.** Permiten validacion ontologica
   de compatibilidad de tipos (que un predicado dado admita los tipos de sus
   extremos) sin tener que resolver la entidad contra Neo4j.
2. **Se desdobla `evidence_span` en `evidence_start` + `evidence_end`.** Offsets
   enteros explicitos: mas simples de validar (`start <= end`, ambos `>= 0`) y de
   serializar de forma determinista, sin sub-objeto anidado.

Resultado: **exactamente 20 campos**. No se anaden campos mas alla de estos 20.
Los metadatos de la propuesta (`schema_version`, `document_type`, `relation_id`)
no son campos de datos del modelo; `SCHEMA_VERSION` y `DOCUMENT_TYPE` se exponen
como constantes de modulo.

## Estados de consenso (reutilizados, no duplicados)

El ensemble usa cinco estados canonicos: **STRONG · PARTIAL · CONFLICT · INVALID
· HUMAN**. Su forma canonica en codigo (con sufijo) esta definida en
`external_ai/models.py` (`CONSENSUS_STATES = STRONG_CONSENSUS, PARTIAL_CONSENSUS,
MODEL_CONFLICT, INVALID_RESPONSES, HUMAN_REQUIRED`). Este paquete los **importa y
referencia** via `CANONICAL_CONSENSUS_STATES`; no crea un segundo sistema de
consenso. Si `external_ai` no estuviera disponible, se usa un espejo con los
mismos valores, documentado como tal en `contracts.py`.

## Reglas de validacion (`validate()`)

- `subject_id` y `object_id` no vacios.
- `subject_id != object_id` salvo predicado reflexivo permitido. Lista de
  reflexivos: `REFLEXIVE_PREDICATES`, **vacia por defecto**.
- `predicate` normalizado (MAYUSCULAS con guion_bajo) — ver `normalize_predicate`.
- `confidence` en `[0, 1]`.
- `evidence_start <= evidence_end`, ambos `>= 0`; `evidence_text` obligatorio si
  `extraction_method != ONTOLOGY`.
- `workspace` obligatorio.
- `extraction_method`, `direction`, `epistemic_status` deben ser valores validos.
- `negated` es `bool` explicito.
- Procedencia minima: `source_id` y `source_segment` presentes.
- Serializacion determinista: `to_json` ordena claves; `from_json` reconstruye;
  round-trip estable.

## Semantica epistemica

`negated=True` marca una **no-afirmacion** (invalida la afirmacion positiva).
`epistemic_status != ASSERTED` no es un hecho confirmado. `is_affirmative()`
devuelve `True` solo si `negated=False` y `epistemic_status=ASSERTED`.

## Compatibilidad futura

`from_json` / `from_dict` **rechazan** cualquier clave desconocida (fuera de los
20 campos) con `RelationContractError`. El contrato interno-v1 es **cerrado**: una
clave extra indica otra version u otro contrato y no debe silenciarse. La
promocion a una v2 requiere aprobacion del Supervisor.

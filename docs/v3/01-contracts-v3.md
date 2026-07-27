# 01 — Contratos internos versionados V3 (fase 6)

**Rama:** `feat/v3-contracts` · **Base:** `1be3273` (auditoría fase 5)
**Ámbito:** worktree `.claude/worktrees/v3-contracts`. No se ha tocado `main`, ni
producción, ni ningún contrato existente.

Este documento fija los **nueve contratos internos V3** exigidos por la sección 6
del prompt maestro, el **adaptador hacia `relation-candidate/internal-v1`** y lo
que queda **congelado** antes de paralelizar la implementación.

---

## 1. Dónde vive cada cosa

| Pieza | Ruta |
|---|---|
| JSON Schema (10 ficheros: 9 contratos + `_common`) | `contracts/knowledge-v3/v1/*.schema.json` |
| Validador compartido (schema + semántica + firma) | `contracts/knowledge-v3/v1/validator.py` |
| Ejemplos generados (17 válidos / 55 inválidos) | `contracts/knowledge-v3/v1/examples/` |
| Fixtures + generador de ejemplos | `contracts/knowledge-v3/v1/tests/v3_fixtures.py`, `generate_examples.py` |
| Gate de contratos (375 tests) | `contracts/knowledge-v3/v1/tests/test_contracts_v3.py` |
| Modelos Python | `data-engine/app/knowledge_v3/contracts/` |
| Adaptador V3 → v1 | `data-engine/app/knowledge_v3/adapters/relation_candidate_v1.py` |
| Tests de modelos (318) y de adaptador (21) | `data-engine/app/tests/test_knowledge_v3_contracts.py`, `test_knowledge_v3_adapter.py` |

La partición **JSON Schema fuera de `data-engine`** es deliberada y copia la del
contrato `review/ingest v1`: motor y visor comparten los mismos ficheros, no una
copia cada uno. Los modelos Python **no reimplementan** las reglas: llaman al
validador. Si algún día divergen, divergen en un solo sitio — es decir, no pueden.

---

## 2. Los nueve contratos

Identificador: `<nombre>/v3-internal-v1`. Versión por instancia en
`contract_version` (`1.x.y`); `SUPPORTED_MAJOR = 1`, una mayor desconocida se
rechaza (compatibilidad forward, igual que en v1).

| Contrato | Qué es | Campos propios (además del envelope) |
|---|---|---|
| `source-asset` | fuente original ingerida | `asset_id`, `collection_id`, `game_profile`, `source_kind`, `mime_type`, `content_hash`, `byte_size`, `original_name`, `original_location`, `created_at`, `ingested_at`, `language_hint`, `privacy_class`, `copyright_class`, `processing_policy`, `metadata` |
| `source-episode` | trozo direccionable de una fuente | `episode_id`, `asset_id`, `sequence`, `modality`, `text`, `page`, `bbox`, `time_start`, `time_end`, `previous_episode_id`, `next_episode_id`, `quality`, `content_hash` |
| `evidence-fragment` | anclaje literal de evidencia | `fragment_id`, `episode_id`, `literal_text`, `normalized_text`, `start`, `end`, `bbox`, `time_start`, `time_end`, `frame_id`, `page`, `media_type`, `confidence` |
| `entity-mention` | mención de entidad en un episodio | `mention_id`, `episode_id`, `surface`, `normalized_surface`, `start`, `end`, `bbox`, `time_start`, `time_end`, `type_candidates`, `confidence`, `coreference_candidates`, `evidence_fragment_ids` |
| `claim-proposal` | afirmación **propuesta** por un extractor | `claim_id`, `episode_id`, `subject_mentions`, `relation_phrase`, `object_mentions`, `predicate_candidates`, `direction_candidates`, `temporal_expressions`, `negated`, `epistemic_cues`, `epistemic_status_hint`, `qualifiers`, `evidence_fragment_ids`, `confidence`, `alternatives`, `abstained`, `review_required` |
| `entity-resolution` | decisión de identidad | `resolution_id`, `mention_ids`, `candidate_entity_ids`, `selected_entity_id`, `action`, `entity_type`, `confidence`, `evidence`, `reason_codes`, `game_profile`, `split_groups` |
| `fact-assertion` | unidad autoritativa del ledger temporal | `assertion_id`, `subject_entity_id`, `object_entity_id`, `predicate`, `direction`, `valid_from`, `valid_to`, `recorded_at`, `epistemic_status`, `confidence`, `status`, `collection_id`, `game_profile`, `engine_version`, `ontology_version`, `evidence_fragment_ids`, `episode_ids`, `supersedes`, `superseded_by`, `negated` |
| `graph-mutation-plan` | **única** entrada admisible del writer | `plan_id`, `plan_hash`, `engine_version`, `ontology_version`, `game_profile`, `collection_id`, `created_at`, `expires_at`, `decisions`, `mutation_operations`, `local_approval` |
| `game-profile` | ontología local por juego | `profile_id`, `profile_version`, `core_ontology_version`, `entity_types`, `predicates`, `aliases`, `titles`, `factions`, `calendars`, `identity_rules`, `ambiguous_terms`, `source_priorities`, `evaluation_examples`, `learned_adapter` |

### Envelope común obligatorio en los nueve

```yaml
contract_id:        # <nombre>/v3-internal-v1 (const por contrato)
contract_version:   # 1.x.y
workspace:          # aislamiento duro
source_asset_id:    # procedencia: qué fuente originó esto
source_hash:        # {algorithm: sha256, value: <64 hex>} del asset origen
provider_trace:     # [{step, provider, name, version, model, produced, params_hash?}]
```

`provider` sólo admite `local` | `ollama` | `external`. `produced` no puede estar
vacío: una traza que no dice qué produjo no es trazabilidad.

---

## 3. Decisiones de diseño

1. **Cerrado por defecto, abierto sólo donde se justifica.** `additionalProperties:
   false` en la raíz de los nueve y en todos los sub-objetos. Las **dos únicas**
   excepciones son `metadata` (metadatos no sensibles, extensibles por definición,
   herencia directa de `_common-v1`) y `payload` de una operación de mutación (su
   forma depende del tipo de operación y de la ontología activa). En ambos casos el
   validador prohíbe claves sensibles dentro, y un test recorre los schemas para
   comprobar que no aparece ningún otro bloque abierto.

2. **Determinismo por construcción.** Un único serializador: `canonical_json`
   (claves ordenadas, separadores mínimos, UTF-8 literal). Nada se genera en
   tiempo de serialización — las fechas son *datos* del documento, no `now()`.
   Además hay reglas que fuerzan orden estable en los datos: `predicate_candidates`
   debe ir ordenado por confianza descendente, y los `validation_flags` del
   adaptador salen ordenados alfabéticamente.

3. **El `source_hash` es del asset, no del documento.** Todo el árbol
   (`episodio → fragmento → mención → claim → resolución → afirmación → plan`)
   arrastra el hash de la fuente original. `SourceAsset` y `SourceEpisode` tienen
   además su propio `content_hash`; en el asset, el validador exige
   `source_hash == content_hash` (es su propia raíz).

4. **`GraphMutationPlan` es verificable, no confiable.** `plan_hash` = sha256 del
   plan canónico *sin ese campo*; `decision_hash` = sha256 del cuerpo de decisión
   (`workspace`, `source_asset_id`, `source_hash`, versiones, perfil, colección,
   `decisions`, `mutation_operations`). Cambiar el workspace, el source hash, una
   decisión o una operación rompe la firma **sin que nadie tenga que acordarse de
   comprobarlo**. `local_approval.approved_by.provider` es `const: "local"`: un plan
   firmado por Ollama o por un proveedor externo es inválido *por contrato*, no por
   política configurable. Cada operación lleva `idempotency_key` única, sólo puede
   colgar de una decisión `ACCEPT`, y el plan lleva `expires_at`. Esto cubre uno a
   uno los rechazos que el dosier §18.8 exige al writer.

5. **Abstenerse y revisar son salidas de primera clase.** Un `ClaimProposal` puede
   declararse `abstained` (y entonces no puede llevar predicado ni confianza > 0);
   una `EntityResolution` puede ser `CREATE_PROVISIONAL` o `REVIEW` sin fijar
   identidad; un plan no aprobado puede llevar decisiones `REVIEW`, pero un plan
   **aprobado** no puede.

6. **Reutilización, no reinvención.** `media_type` son exactamente los 10 valores
   de `media/multimedia_contract.MediaType`; los tipos de entidad son los 6 de
   `external_ai.models.ALLOWED_ENTITY_TYPES`; `direction` y los cuatro primeros
   valores de `epistemic_status` son los de `relations.contracts`; el bbox usa la
   misma convención normalizada `[0,1]` con origen arriba-izquierda.

7. **`VISUAL_INFERRED` es la única extensión semántica.** No existe en v1. Un claim
   con esa pista nace con `review_required = true` obligatorio (schema, no
   convención), y el adaptador lo degrada a `HYPOTHETICAL` dejando un flag.

8. **Los ejemplos se generan.** 17 válidos y 55 inválidos salen de
   `v3_fixtures.py`; un test compara byte a byte lo generado con lo que hay en
   disco. Un ejemplo no puede quedarse obsoleto respecto al contrato en silencio.

---

## 4. Adaptador V3 → `relation-candidate/internal-v1`

`relation-candidate/internal-v1` (20 campos, contrato cerrado) **no se ha tocado ni
un byte**. Un test lo verifica explícitamente (`SCHEMA_VERSION == "internal-1.0.0"`
y exactamente 20 campos).

```python
from knowledge_v3.adapters import claim_with_resolutions_to_relation_candidate
candidate = claim_with_resolutions_to_relation_candidate(
    claim, evidence, subject_resolution, object_resolution
)   # -> RelationCandidate v1 ya validado
```

El puente es **unidireccional**: v1 tiene estrictamente menos información y
reconstruir V3 desde v1 sería inventarla.

### Mapeo

| v1 | de dónde sale |
|---|---|
| `subject_id` / `object_id` | `EntityResolution.selected_entity_id`, o `provisional:<resolution_id>` si aún no hay id canónico |
| `subject_type` / `object_type` | `EntityResolution.entity_type` |
| `predicate` | primer `predicate_candidate` (la lista va ordenada), normalizado |
| `direction` | `direction_candidate` de mayor confianza; `UNDIRECTED` si el extractor no se moja |
| `evidence_text`, `evidence_start`, `evidence_end`, `source_page` | del `EvidenceFragment` citado — **no se recalculan** |
| `source_id`, `source_segment` | `claim.source_asset_id`, `claim.episode_id` |
| `extraction_method` | `local`→`HEURISTIC`, `ollama`→`LLM_LOCAL`, `external`→`NVIDIA` |
| `model`, `negated`, `confidence`, `workspace` | directos del claim / de la traza |
| `temporal_scope` | `temporal_expressions` (o `None` si están vacías) |
| `epistemic_status` | `epistemic_status_hint`; `VISUAL_INFERRED` → `HYPOTHETICAL` |

### Pérdidas de información: marcadas, nunca silenciosas

Cada cosa que v1 no sabe representar deja un `validation_flag` (el único campo
abierto de v1): `V3_ADAPTED`, `V3_MULTIPLE_PREDICATES`, `V3_HAS_ALTERNATIVES`,
`V3_VISUAL_INFERRED`, `V3_EXTERNAL_PROVIDER`, `V3_REVIEW_REQUIRED`,
`V3_MULTI_MENTION_SUBJECT`, `V3_MULTI_MENTION_OBJECT`, `V3_PROVISIONAL_SUBJECT`,
`V3_PROVISIONAL_OBJECT`.

### Lo que el adaptador rechaza

Claim abstenido · claim sin predicado · evidencia no citada por el claim ·
evidencia de otro episodio, otro workspace u otro `source_hash` · sujeto y objeto
resueltos a la misma entidad · resolución en `REVIEW` o `SPLIT` (no fija identidad) ·
resolución de otro workspace · traza con proveedor desconocido o ausente.

---

## 5. Pruebas

| Suite | Tests |
|---|---|
| `contracts/knowledge-v3/v1/tests/` (schemas, ejemplos, firma, determinismo) | **375** |
| `data-engine/.../test_knowledge_v3_contracts.py` (modelos: roundtrip + mutación) | **318** |
| `data-engine/.../test_knowledge_v3_adapter.py` (adaptador contra el v1 real) | **21** |
| **Total nuevo** | **714 / 714 en verde** |

Reparto por familia: **142** de roundtrip/determinismo y **470** de mutación (el
resto son estructurales: cobertura de la familia, presencia de ejemplos, helpers).

**Roundtrip:** `objeto → JSON → objeto idéntico` para los nueve contratos, y
serialización estable byte a byte (repetida, y reconstruyendo desde un dict con las
claves en otro orden).

**Mutación:** cada regla estructural clave tiene un caso que hoy se rechaza y que
se pondría verde si la regla se relajase — campo desconocido, `workspace` ausente o
vacío, `source_hash` ausente o sin algoritmo, `contract_version` mayor incorrecta,
`contract_id` erróneo, `provider_trace` ausente/vacía/con proveedor desconocido,
secreto en `metadata`, y las once del `GraphMutationPlan` (firma ausente, firmante
externo, hash manipulado, workspace cambiado, source hash cambiado, decisión
`REVIEW` con plan aprobado, validador en `FAIL`, `idempotency_key` duplicada,
operación sobre decisión no-`ACCEPT`, plan caducado, secreto en `payload`).

Los ejemplos inválidos del plan que prueban una **regla** se vuelven a **sellar**
tras la mutación: sin resellar serían rechazados por el hash y no probarían la
regla que dicen probar.

### Ejecutar

```bash
python -m pytest contracts/knowledge-v3/v1/tests/ -q
python -m pytest data-engine/app/tests/test_knowledge_v3_contracts.py \
                 data-engine/app/tests/test_knowledge_v3_adapter.py -q
```

Gate nuevo en CI: job `knowledge-v3-contracts` (valida schemas + comprueba que los
ejemplos no han derivado). `pytest.ini` incluye la nueva ruta, de modo que la
corrida conjunta también los ejecuta. No se ha relajado ningún gate existente.

---

## 6. Qué queda CONGELADO

A partir de este documento, y hasta que un bloque posterior lo revise con una
subida de versión explícita:

1. **Los nueve `contract_id`** `<nombre>/v3-internal-v1` y el envelope común de
   seis campos.
2. **`SUPPORTED_MAJOR = 1`** y el rechazo de una mayor desconocida.
3. **La serialización canónica** y las fórmulas de `plan_hash` y `decision_hash`
   (`DECISION_HASH_FIELDS` en `validator.py`). Cambiarlas invalida todo plan ya
   firmado.
4. **Los tres valores de `provider`**: `local`, `ollama`, `external`.
5. **`additionalProperties: false` por defecto**, con `metadata` y `payload` como
   únicas excepciones.
6. **`relation-candidate/internal-v1`**: intocable. Cualquier necesidad nueva se
   resuelve en el adaptador o en un contrato V3, jamás modificándolo.

**No congelado** (puede crecer sin romper nada): los `reason_code`, los
`validation_flags` del adaptador, el contenido de un `GameProfile`, y los campos
opcionales que se añadan en una **minor** (`1.1.0`) manteniendo compatibilidad.

---

## 7. Estado y avisos

- Producción **intacta**: nada de esta fase escribe en Neo4j, llama a proveedores
  ni toca VM105. Los contratos sólo describen y validan datos.
- El módulo `knowledge_v3` está **aislado** (dosier §15): ningún módulo existente
  lo importa todavía.
- **Fallo preexistente, ajeno a esta fase:** `deploy/tests/test_docs_consistency.py`
  falla en la base `1be3273` porque falta `docs/02-current-state.md` (lo archivó el
  commit de consolidación `1553665`). Se ha verificado que falla igual sin ninguno
  de los cambios de esta rama. No se ha tocado: corregirlo es una decisión de
  documentación que no corresponde al bloque de contratos.

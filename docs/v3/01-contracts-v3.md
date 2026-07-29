# 01 — Contratos internos versionados V3 (fase 6)

**Rama:** `feat/v3-contracts` · **Base:** `1be3273` (auditoría fase 5)
**Estado:** revisión independiente **NO CONFORME** sobre `3f47100` → ronda de
correcciones H1-H19 aplicada (§8).
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
| Ejemplos generados (20 válidos / 76 inválidos) | `contracts/knowledge-v3/v1/examples/` |
| Fixtures + generador de ejemplos | `contracts/knowledge-v3/v1/tests/v3_fixtures.py`, `generate_examples.py` |
| Gate de contratos (526 tests) | `contracts/knowledge-v3/v1/tests/test_contracts_v3.py` |
| Modelos Python | `data-engine/app/knowledge_v3/contracts/` |
| Adaptador V3 → v1 | `data-engine/app/knowledge_v3/adapters/relation_candidate_v1.py` |
| Tests de modelos (406) y de adaptador (32) | `data-engine/app/tests/test_knowledge_v3_contracts.py`, `test_knowledge_v3_adapter.py` |

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
| `source-episode` | trozo direccionable de una fuente | `episode_id`, `asset_id`, `sequence`, `modality`, `text`, `page`, `bbox`, `time_start`, `time_end`, `previous_episode_id`, `next_episode_id`, `speaker`, `turn`, `table`, `quality`, `content_hash` |
| `evidence-fragment` | anclaje literal de evidencia | `fragment_id`, `episode_id`, `literal_text`, `normalized_text`, `start`, `end`, `bbox`, `time_start`, `time_end`, `frame_id`, `page`, `media_type`, `confidence` |
| `entity-mention` | mención de entidad en un episodio | `mention_id`, `episode_id`, `surface`, `normalized_surface`, `start`, `end`, `bbox`, `time_start`, `time_end`, `type_candidates`, `confidence`, `coreference_candidates`, `evidence_fragment_ids` |
| `claim-proposal` | afirmación **propuesta** por un extractor | `claim_id`, `episode_id`, `subject_mentions`, `relation_phrase`, `object_mentions`, `predicate_candidates`, `direction_candidates`, `temporal_expressions`, `negated`, `epistemic_cues`, `epistemic_status_hint`, `qualifiers`, `evidence_fragment_ids`, `confidence`, `alternatives`, `abstained`, `review_required` |
| `entity-resolution` | decisión de identidad | `resolution_id`, `mention_ids`, `candidate_entity_ids`, `selected_entity_id`, **`assigned_entity_id`**, `action`, `entity_type`, `confidence`, `evidence`, `reason_codes`, `game_profile`, `split_groups` |
| `fact-assertion` | unidad autoritativa del ledger temporal | `assertion_id`, `subject_entity_id`, `object_entity_id`, `predicate`, `direction`, `valid_from`, `valid_to`, **`event_time`**, `recorded_at`, `epistemic_status`, `confidence`, `status`, **`state`**, `negated`, `calendar_id`, `collection_id`, `game_profile`, `engine_version`, `ontology_version`, `evidence_fragment_ids`, `episode_ids`, `supersedes`, `superseded_by` |
| `graph-mutation-plan` | **única** entrada admisible del writer | `plan_id`, `plan_hash`, **`snapshot_id`**, `engine_version`, `ontology_version`, `game_profile`, `collection_id`, `created_at`, `expires_at`, `decisions`, `mutation_operations` (con `idempotency_key` derivada, `expected_version`, `expected_hash`), `local_approval` (con `signature`/`key_id` reservados) |
| `game-profile` | ontología local por juego | `profile_id`, `profile_version`, `core_ontology_version`, `entity_types`, `predicates`, `aliases`, `titles`, `factions`, `calendars`, `identity_rules`, `ambiguous_terms`, `source_priorities`, `evaluation_examples`, `learned_adapter` |

### Envelope común obligatorio en los nueve

```yaml
contract_id:        # <nombre>/v3-internal-v1 (const por contrato)
contract_version:   # 1.x.y
workspace:          # aislamiento duro
source_asset_id:    # procedencia: qué fuente originó esto
source_hash:        # {algorithm: sha256, value: <64 hex>} del asset origen
provider_trace:     # [{step, provider, name, version, model, produced, params_hash?}]
produced_by_step:   # step de provider_trace que produjo el contenido principal
```

`provider` sólo admite `local` | `ollama` | `external`. `produced` no puede estar
vacío: una traza que no dice qué produjo no es trazabilidad.

`produced_by_step` es una **referencia explícita**, no una heurística. La primera
versión adivinaba el paso productor buscando la subcadena `"claim"` en `produced`,
y con eso una salida de NVIDIA cuya traza dijera `produced: ["predicate_candidates"]`
acababa etiquetada `HEURISTIC` y **sin** `V3_EXTERNAL_PROVIDER`: procedencia externa
perdida en silencio. El validador exige que `produced_by_step` exista en la traza.

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

4. **`GraphMutationPlan` es verificable, NO confiable.** Los hashes son sha256
   **sin clave**: detectan manipulación accidental, ediciones parciales y
   desincronización entre firma y contenido — la clase de fallo que de verdad
   ocurre — pero **no autentican al firmante**. Quien pueda reescribir el
   documento puede resellarlo. Que `approved_by.provider` sea `const: "local"`
   invalida un plan que *se declare* firmado por Ollama o por un externo, pero no
   impide que alguien con acceso de escritura se declare local. La garantía real
   hoy es la cadena de custodia: el plan no sale del proceso local. Para firma
   criptográfica quedan **reservados** `local_approval.signature` y
   `local_approval.key_id` — opcionales y sin usar, abiertos ahora para no tener
   que romper un contrato congelado el día que exista clave. `is_authenticated()`
   devuelve `False` a propósito, para que nadie confunda «hash correcto» con
   «firmado».

   Lo que sí garantiza: `plan_hash` = sha256 del plan canónico *sin ese campo*;
   `decision_hash` sobre `workspace`, `source_asset_id`, `source_hash`,
   `snapshot_id`, versiones, perfil, colección, `expires_at`, `decisions`,
   `mutation_operations` **y** `local_approval.{approved, approved_by,
   validator_chain}` — todo lo que el writer consume para decidir si aplica.
   `snapshot_id` ancla el estado sobre el que se calculó el plan; cada operación
   lleva `expected_version`/`expected_hash` (concurrencia optimista) y una
   `idempotency_key` **derivada**, no inventada: sha256 de
   `{workspace, snapshot_id, operation_type, decision_id, target_entity_id,
   assertion_id, payload}`. `operation_id` queda fuera a propósito, para que la
   misma operación lógica calculada en dos planes distintos lleve la **misma**
   clave y el segundo apply sea un no-op. El validador la recalcula y la compara.

   **Límite explícito para el writer:** los campos que quedan **fuera** del
   `decision_hash` — `created_at`, `plan_id`, `provider_trace` y `metadata` — son
   informativos y de auditoría, y **el writer no debe consumirlos para ninguna
   decisión de escritura**. Al no estar cubiertos por la firma, alterarlos no
   rompe ningún hash: cualquier decisión que se apoyase en ellos sería
   manipulable sin dejar rastro. La misma advertencia está en la descripción del
   schema del plan, y hay tests que comprueban las dos cosas — que el aviso
   sigue ahí y que esos campos efectivamente no entran en el hash.

5. **Abstenerse y revisar son salidas de primera clase.** Un `ClaimProposal` puede
   declararse `abstained` (y entonces no puede llevar predicado ni confianza > 0);
   una `EntityResolution` puede ser `CREATE_PROVISIONAL` o `REVIEW` sin fijar
   identidad; un plan no aprobado puede llevar decisiones `REVIEW`, pero un plan
   **aprobado** no puede.

6. **Reutilización, no reinvención.** `media_type` son los 10 valores de
   `media/multimedia_contract.MediaType` **más `HTR_TEXT`** (el manuscrito
   reconocido no es OCR y no debe disfrazarse de OCR); los tipos de entidad son
   los 6 de `external_ai.models.ALLOWED_ENTITY_TYPES`; `direction` y los cuatro
   primeros valores de `epistemic_status` son los de `relations.contracts`; el
   bbox usa la misma convención normalizada `[0,1]` con origen arriba-izquierda.

   `epistemic_status` lleva los **siete** estados mínimos del dosier §11.6:
   `ASSERTED`, `RUMORED`, `HYPOTHETICAL`, `INTENDED`, `VISUAL_INFERRED`,
   `CONFLICTED`, `UNKNOWN`. Sin `CONFLICTED` el motor no tenía forma de emitir un
   estado en conflicto, que es una de sus salidas obligatorias.

7. **Tres estados epistémicos no existen en v1** (`VISUAL_INFERRED`,
   `CONFLICTED`, `UNKNOWN`): el adaptador los degrada a `HYPOTHETICAL` y cada uno
   deja su propio flag. Un claim `VISUAL_INFERRED` nace además con
   `review_required = true` obligatorio (schema, no convención).

8. **Dos ejes temporales, no uno.** `status` es el **ciclo de vida en el ledger**
   (`PROVISIONAL`…`RETRACTED`); `state` es el **eje temporal** del dosier §11.5
   (`ACTIVE`, `ENDED`, `PLANNED`, `HYPOTHETICAL`, `RECURRING`, `UNKNOWN`). Una
   afirmación `ENDED` puede seguir siendo `CONFIRMED`. Se añade `event_time`
   (momento del hecho narrado), distinto de `valid_from`/`valid_to` (vigencia) y
   de `recorded_at` (cuándo lo supo el sistema). El validador exige coherencia
   entre los dos ejes: `ACTIVE` no admite `valid_to`, `ENDED` lo exige.

9. **Orden total, no sólo descendente.** `predicate_candidates`,
   `direction_candidates` y `alternatives` deben ir por confianza descendente
   **con desempate determinista** (predicado alfabético; dirección por el orden
   canónico del enum). Con sólo «descendente», dos candidatos empatados dejaban
   la dirección elegida a merced del orden de llegada — determinismo aparente.

10. **La identidad la nombra quien la crea.** `EntityResolution` lleva
    `assigned_entity_id`, obligatorio en `CREATE_NEW`/`CREATE_PROVISIONAL`. Antes
    el adaptador fabricaba `provisional:<resolution_id>` por convención de
    cadena, y el flag de provisionalidad se deducía del prefijo del id: dos
    invenciones aguas abajo de quien tomó la decisión.

11. **La modalidad obliga a su forma.** `modality: TABLE` exige `table`
    (`header`/`rows`) y `modality: SPEAKER_TURN` exige `speaker`, como
    condicionales del propio schema — la misma disciplina que ya aplicaba a
    `OCR_TEXT ⇒ bbox`. Una tabla sin filas y columnas es texto que perdió lo que
    la hacía tabla; un turno de habla sin hablante no resuelve ninguna
    correferencia de primera o segunda persona, que es justo para lo que existe.
    Son condicionales: un episodio de texto no necesita ni tabla ni hablante.

12. **Los ejemplos se generan.** 20 válidos y 76 inválidos salen de
    `v3_fixtures.py`; un test compara byte a byte lo generado con lo que hay en
    disco, y el gate de CI comprueba además que no haya ficheros generados sin
    rastrear. Un ejemplo no puede quedarse obsoleto en silencio.

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
| `subject_id` / `object_id` | `EntityResolution.entity_id()`: `selected_entity_id` (LINK_EXISTING) o `assigned_entity_id` (CREATE_NEW/CREATE_PROVISIONAL). El adaptador **no** fabrica identificadores |
| `subject_type` / `object_type` | `EntityResolution.entity_type` |
| `predicate` | primer `predicate_candidate` (la lista va ordenada), normalizado |
| `direction` | `direction_candidate` de mayor confianza; `UNDIRECTED` si el extractor no se moja |
| `evidence_text`, `evidence_start`, `evidence_end`, `source_page` | del `EvidenceFragment` citado — **no se recalculan** |
| `source_id`, `source_segment` | `claim.source_asset_id`, `claim.episode_id` |
| `extraction_method` | del paso `produced_by_step`: `local`→`HEURISTIC`, `ollama`→`LLM_LOCAL`, `external`→`NVIDIA` |
| `model`, `negated`, `confidence`, `workspace` | directos del claim / de la traza |
| `temporal_scope` | `temporal_expressions` (o `None` si están vacías) |
| `epistemic_status` | `epistemic_status_hint`; `VISUAL_INFERRED`, `CONFLICTED` y `UNKNOWN` → `HYPOTHETICAL` |

### Pérdidas de información: marcadas, nunca silenciosas

Cada cosa que v1 no sabe representar deja un `validation_flag` (el único campo
abierto de v1): `V3_ADAPTED`, `V3_MULTIPLE_PREDICATES`, `V3_HAS_ALTERNATIVES`,
`V3_VISUAL_INFERRED`, `V3_CONFLICTED`, `V3_UNKNOWN_EPISTEMIC`,
`V3_EXTERNAL_PROVIDER`, `V3_REVIEW_REQUIRED`, `V3_MULTI_MENTION_SUBJECT`,
`V3_MULTI_MENTION_OBJECT`, `V3_PROVISIONAL_SUBJECT`, `V3_PROVISIONAL_OBJECT`.

Los dos últimos salen de `EntityResolution.is_provisional()`, no de la forma del
identificador.

### Lo que el adaptador rechaza

Claim abstenido · claim sin predicado · evidencia no citada por el claim ·
evidencia de otro episodio, otro workspace u otro `source_hash` · sujeto y objeto
resueltos a la misma entidad · resolución en `REVIEW` o `SPLIT` (no fija identidad) ·
resolución de otro workspace · resolución sin identificador declarado ·
`produced_by_step` colgando · traza con proveedor desconocido o ausente ·
evidencia con `literal_text` en blanco (error propio del adaptador, no un
`RelationContractError` ajeno que se escapa desde dentro de v1).

---

## 5. Pruebas

| Suite | Tests |
|---|---|
| `contracts/knowledge-v3/v1/tests/` (schemas, ejemplos, firma, determinismo) | **526** |
| `data-engine/.../test_knowledge_v3_contracts.py` (modelos: roundtrip + mutación) | **406** |
| `data-engine/.../test_knowledge_v3_adapter.py` (adaptador contra el v1 real) | **32** |
| **Total nuevo** | **964 / 964 en verde** |

**Roundtrip:** `objeto → JSON → objeto idéntico` para los nueve contratos, y
serialización estable byte a byte (repetida, y reconstruyendo desde un dict con las
claves en otro orden).

**Mutación:** cada regla estructural clave tiene un caso que hoy se rechaza y que
se pondría verde si la regla se relajase — campo desconocido, `workspace` ausente o
vacío, `source_hash` ausente o sin algoritmo, `contract_version` mayor incorrecta,
`contract_id` erróneo, `provider_trace` ausente/vacía/con proveedor desconocido,
secreto en `metadata`, y las once del `GraphMutationPlan` (firma ausente, firmante
externo, hash manipulado, workspace cambiado, source hash cambiado, decisión
`REVIEW` con plan aprobado, validador en `FAIL`, `idempotency_key` duplicada o
inventada, operación sobre decisión no-`ACCEPT`, plan caducado, sin `snapshot_id`,
sin concurrencia optimista, secreto en `payload`).

**Mutante que se mata explícitamente (§8, H10):** si se suprimiera la comparación
de `decision_hash` en el validador, un plan al que se le altera una decisión y se
le recalcula **sólo** `plan_hash` pasaría. `test_removing_the_decision_hash_check_would_be_caught`
construye exactamente ese documento y exige que se rechace.

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
3. **La serialización canónica** y las fórmulas de `plan_hash`, `decision_hash`
   (`DECISION_HASH_FIELDS` + `DECISION_HASH_APPROVAL_FIELDS`) e
   `idempotency_key` (`IDEMPOTENCY_KEY_FIELDS`), todas en `validator.py`.
   Cambiarlas invalida todo plan ya sellado.
4. **Los tres valores de `provider`**: `local`, `ollama`, `external`.
5. **`additionalProperties: false` por defecto**, con `metadata` y `payload` como
   únicas excepciones.
6. **`relation-candidate/internal-v1`**: intocable. Cualquier necesidad nueva se
   resuelve en el adaptador o en un contrato V3, jamás modificándolo.

7. **Los ejes**: `status` (ciclo de vida) y `state` (temporal) son y seguirán
   siendo dos campos distintos; `produced_by_step` seguirá siendo una referencia
   explícita, nunca una heurística sobre nombres.

**No congelado** (puede crecer sin romper nada): los `reason_code` **no
canónicos** (los canónicos de §7 sí están fijados), los `validation_flags` del
adaptador, y el contenido de un `GameProfile`.

### Política de versionado, dicha con precisión

La primera redacción de este documento afirmaba que añadir campos opcionales en
una **minor** «mantiene compatibilidad». **Es falso con `additionalProperties:
false`**: un consumidor que valide contra el schema `1.0.0` rechazará un
documento `1.1.0` que traiga un campo nuevo, aunque sea opcional. La
compatibilidad hacia adelante que da `SUPPORTED_MAJOR` es sobre el *número de
versión*, no sobre la forma del documento.

La política real, y la que hace que esto no sea un problema hoy: **hay una sola
copia de los schemas en el repositorio**, motor y visor la comparten, y una
minor es un **upgrade atómico** — se despliegan juntos schema, productores y
consumidores. Mientras eso se cumpla, añadir un campo opcional es seguro. En el
momento en que exista un consumidor desplegado por separado (otro servicio, un
cliente externo, documentos persistidos y releídos por una versión anterior),
**cualquier** campo nuevo exige una **major**, o relajar `additionalProperties`
en los bloques afectados — que es precisamente lo que este contrato no quiere
hacer. Ese día hay que decidir, no descubrirlo.

---

## 7. Mapeo de las decisiones del motor (dosier §11.7)

El dosier enumera **diez** decisiones. El contrato tiene **cuatro** valores de
`decision` y un eje separado de `reason_codes`, porque mezclar «qué se decidió»
con «por qué» en un solo enum obliga a repetir la lógica del writer cada vez que
aparece un motivo nuevo. El writer sólo necesita lo primero.

El mapa vive en `validator.ENGINE_DECISION_MAP` y **está verificado por test**
(`test_dossier_decisions_all_map_to_the_contract`): las diez decisiones del
dosier tienen destino, y cada `reason_code` canónico existe.

| Decisión del dosier §11.7 | `decision` | `reason_code` canónico |
|---|---|---|
| `LOCAL_APPROVED` | `ACCEPT` | `LOCAL_APPROVED` |
| `LOCAL_APPROVED_WITH_WARNINGS` | `ACCEPT` | `LOCAL_APPROVED_WITH_WARNINGS` |
| `REVIEW_ENTITY` | `REVIEW` | `REVIEW_ENTITY` |
| `REVIEW_PREDICATE` | `REVIEW` | `REVIEW_PREDICATE` |
| `REVIEW_DIRECTION` | `REVIEW` | `REVIEW_DIRECTION` |
| `REVIEW_TEMPORALITY` | `REVIEW` | `REVIEW_TEMPORALITY` |
| `REVIEW_EVIDENCE` | `REVIEW` | `REVIEW_EVIDENCE` |
| `CONFLICT` | `REVIEW` | `CONFLICT_WITH_EXISTING` |
| `ABSTAIN` | `ABSTAIN` | `INSUFFICIENT_EVIDENCE` |
| `REJECT_INVALID` | `REJECT_INVALID` | `ONTOLOGY_INCOMPATIBLE` |

Razones canónicas admitidas por decisión (`validator.CANONICAL_REASON_CODES`):

| `decision` | `reason_codes` canónicos |
|---|---|
| `ACCEPT` | `LOCAL_APPROVED`, `LOCAL_APPROVED_WITH_WARNINGS` |
| `REVIEW` | `REVIEW_ENTITY`, `REVIEW_PREDICATE`, `REVIEW_DIRECTION`, `REVIEW_TEMPORALITY`, `REVIEW_EVIDENCE`, `CONFLICT_WITH_EXISTING` |
| `ABSTAIN` | `INSUFFICIENT_EVIDENCE`, `AMBIGUOUS_SEMANTICS`, `LOW_QUALITY_EPISODE` |
| `REJECT_INVALID` | `ONTOLOGY_INCOMPATIBLE`, `TYPE_INCOMPATIBLE`, `DEMONSTRABLY_FALSE` |

**Cada decisión de un plan debe llevar al menos una razón canónica de su tipo.**
Puede llevar además cuantas razones descriptivas quiera (`EVIDENCE_LITERAL`,
`VISUAL_INFERRED`…), pero sin la canónica la decisión del dosier no sería
reconstruible desde el plan, y el validador la rechaza.

---

## 8. Ronda de correcciones tras la revisión independiente

Dictamen **NO CONFORME** sobre `3f47100`. El diseño se mantuvo; las correcciones
fueron quirúrgicas.

| # | Hallazgo | Qué se hizo |
|---|---|---|
| H1 | `epistemic_status` incompleto | Añadidos `CONFLICTED` y `UNKNOWN` (siete estados del dosier §11.6). El adaptador los degrada con flag propio. |
| H2 | `fact-assertion` sin eje temporal de estado | Añadidos `state` (6 valores) y `event_time`, ambos **required**; `status` se mantiene como eje de ciclo de vida. Coherencia validada. |
| H3 | Atribución de proveedor por subcadenas | `produced_by_step` **required** en los nueve, verificado contra la traza. El adaptador lo usa. Test de la regresión concreta. |
| H4 | Orden sin desempate | Orden total exigido en `predicate_candidates`, `direction_candidates` y `alternatives`; `best_direction()` deja de usar `max()`. |
| H5 | Campos opcionales que deberían ser obligatorios | `negated` (fact-assertion) y `entity_type` (entity-resolution) pasan a **required** antes de congelar. |
| H6 | Identidad de entidades nuevas sin declarar | `assigned_entity_id`, required en `CREATE_NEW`/`CREATE_PROVISIONAL`. El adaptador deja de fabricar `provisional:<id>`. |
| H7 | Sin ancla de estado ni idempotencia derivada | `snapshot_id`; `expected_version`/`expected_hash` por operación; `idempotency_key` derivada y comprobada por el validador. |
| H8 | Doc afirmaba una garantía inexistente | Reescrita como **verificable, no confiable**; reservados `local_approval.signature` y `key_id`; `is_authenticated()` expone la diferencia. |
| H9 | Hash de decisión incompleto | `approved`, `approved_by`, `validator_chain` y `expires_at` entran en `decision_hash`. |
| H10 | Mutante superviviente | `test_removing_the_decision_hash_check_would_be_caught`: plan con `plan_hash` recalculado y `decision_hash` obsoleto. |
| H11 | `HTR_TEXT` ausente de `media_type` | Añadido; el manuscrito deja de disfrazarse de OCR. Fixture y test. |
| H12 | Sin hablante ni turno | `speaker` (tipado) y `turn` opcionales en `source-episode`. |
| H13 | `GameProfile.calendars` sin consumidor | `calendar_id` opcional en `temporal_expressions` y en `fact-assertion`. |
| H14 | Error ajeno escapando del adaptador | `literal_text` en blanco lanza `V3AdapterError`. |
| H15 | Decisiones del dosier sin mapeo | §7 de este documento + `ENGINE_DECISION_MAP` y `CANONICAL_REASON_CODES`, con gate. |
| H16 | Tabla aplanada a texto | `table` opcional (`header`/`rows`) en `source-episode`, con fixture propia. |
| H17 | Dos tests que no mataban su mutante | `SUPPORTED_MAJOR` se prueba directamente sobre `_check_major_version`; la guarda de `abstained` se prueba con un claim abstenido *con* predicado (`validate=False`). |
| H18 | Gate de deriva ciego a ficheros nuevos | El paso de CI comprueba también `git status --porcelain`. |
| H19 | Política de versionado incorrecta | Reescrita en §6: con `additionalProperties: false` una minor **no** es compatible; la seguridad viene de una única copia de schemas y upgrade atómico. |

---

## 9. Estado y avisos

- Producción **intacta**: nada de esta fase escribe en Neo4j, llama a proveedores
  ni toca VM105. Los contratos sólo describen y validan datos.
- El módulo `knowledge_v3` está **aislado** (dosier §15): ningún módulo existente
  lo importa todavía.
- **Fallo preexistente, ajeno a esta fase:** `deploy/tests/test_docs_consistency.py`
  falla en la base `1be3273` porque falta `docs/02-current-state.md` (lo archivó el
  commit de consolidación `1553665`). Se ha verificado que falla igual sin ninguno
  de los cambios de esta rama. No se ha tocado: corregirlo es una decisión de
  documentación que no corresponde al bloque de contratos.

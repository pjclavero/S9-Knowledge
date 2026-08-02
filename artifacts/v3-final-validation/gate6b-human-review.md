# PUERTA 6B — Revisión humana (V3, validación final)

Rama: `integration/v3-final-core-validation`
Fecha: 2026-07-30
Alcance: revisión humana de propuestas V3 (feed, roles, decisiones, ledger
append-only, STALE_REVIEW) y candidatos de glosario.

Restricciones respetadas: sin proveedores reales (Ollama/NVIDIA), sin Neo4j,
writer siempre en dry-run, sin modificar código de producción, contratos, gold,
`benchmarks/datasets/heldout/` ni `benchmarks/datasets/negation/`.

---

## 1. Catálogo de auditoría — qué había ya y qué faltaba

### 1.1 Ya cubierto antes de esta puerta

| Área | Cubierto por |
|---|---|
| Cola con ámbito de workspace y orden estable | `viewer/tests/test_v3_review.py::test_queue_is_workspace_scoped_and_stably_sorted` |
| Filtros source/engine_decision con ámbito de workspace | `test_v3_review.py::test_source_and_engine_decision_filters_remain_workspace_scoped` |
| Idempotencia por `request_id` (una sola entrada) | `test_v3_review.py::test_each_request_appends_exactly_once_even_after_reload_retry`, `::test_post_reload_does_not_duplicate_decision` |
| `request_id` no reutilizable entre workspaces | `test_v3_review.py::test_request_id_cannot_be_replayed_for_another_workspace` |
| Corrección supersede sin borrar la entrada previa | `test_v3_review.py::test_correction_supersedes_without_deleting_previous_entry` |
| Historial manipulado se detecta | `test_v3_review.py::test_tampered_append_only_history_is_detected` |
| El servicio nunca llama a Neo4j; la aprobación no es un plan | `test_v3_review.py::test_service_never_calls_neo4j_and_human_approval_is_not_a_plan` |
| Resaltado con offsets exactos del episodio | `test_v3_review.py::test_highlight_uses_exact_episode_offsets`, `::test_html_contains_exact_mark_and_unknown_reason` |
| Códigos de razón desconocidos se muestran literales | `test_v3_review.py::test_unknown_reason_code_is_shown_verbatim` |
| Deshacer = nueva entrada que supersede | `test_v3_review.py::test_undo_is_a_new_superseding_entry_and_restores_pending` |
| STALE_REVIEW auditado sin tocar el historial (nivel servicio) | `test_v3_review.py::test_stale_review_is_audited_without_changing_valid_history` |
| Corrección de alias propone candidato y no aplica glosario (1 caso) | `test_v3_review.py::test_explicit_alias_correction_proposes_but_never_applies_glossary` |
| Exportación de paquete determinista/completa/idempotente | `data-engine/app/tests/test_knowledge_v3_review_export.py::test_real_result_export_is_deterministic_complete_and_idempotent` |
| Política de auto-decisión y revisión manual (V1/V2, `review/`) | `test_full_human_review.py` (15 casos), `test_review_decider.py` (15), `test_review_pipeline.py` (10), `test_review_cli.py` (4 clases) |
| Exportación/importación externa sanitizada (V1/V2) | `test_review_export_import.py` (21 casos) |
| Supersesión de paquetes de revisión (V1/V2) | `test_supersede_review.py` (26 casos) |
| Glosario V1/V2: normalización, upsert, aislamiento, formas erróneas, matcher | `test_glossary_store.py` (13), `test_glossary_matcher.py` (14) |

### 1.2 Huecos reales encontrados

| Hueco | Evidencia | Cubierto ahora por |
|---|---|---|
| **Ningún test en todo el repo usaba `review_proposals_dir`** — la frontera pipeline→proposals/ nunca se ejercitaba de extremo a extremo | `grep -rn review_proposals_dir` sólo aparecía en `pipeline.py` y `runner.py`, en cero tests | `test_v3_review_e2e.py` (fixture `real_proposals`), `test_knowledge_v3_glossary_candidates.py` (fixture `real_review`) |
| **Todo `test_v3_review.py` usa propuestas construidas a mano** (`def proposal(...)`) — nunca material del motor | `viewer/tests/test_v3_review.py:21` | `test_v3_review_e2e.py`: 37 tests sobre propuestas exportadas por el pipeline real |
| **Control de acceso del feed V3 sin cubrir**: la app real nunca se arrancaba con `S9K_AUTH_ENABLED`; los tests montan un `FastAPI()` desnudo con sólo el router | `test_v3_review.py:293-300` | Casos 1-8 (anónimo, `viewer`, `reviewer`, `admin`, sesión inválida, CSRF) |
| **CSRF del formulario de decisión sin cubrir** (los tests pasaban `csrf_token: ""` con auth apagada) | `test_v3_review.py:317` | Caso 8 |
| **STALE_REVIEW por HTTP sin cubrir** (sólo a nivel servicio) | — | Casos 35, y 33/34/36 amplían el nivel servicio |
| **Rotura de la cadena por BORRADO de una entrada** sin cubrir (sólo por reescritura) | `test_tampered_append_only_history_is_detected` reescribe, no borra | Caso 31 |
| **`test_knowledge_v3_glossary_candidates.py` no existía** (Codex no lo dejó) | fichero ausente | 24 casos nuevos |
| **`GlossaryCandidateStore` sólo tenía 1 aserción indirecta** (dedup, agregación, append-only, auditoría, hash, ausencia de API de aplicación: todo sin cubrir) | `test_v3_review.py:342` | Casos 1-22 |
| **No existía ninguna prueba de no-mutación del glosario efectivo** | — | `test_v3_review_e2e.py::test_no_mutacion_del_glosario_en_el_flujo_completo` y caso 24 |

---

## 2. Los 36 + 24 casos y su estado

### 2.1 Revisión humana — `viewer/tests/test_v3_review_e2e.py` (36 + 1 = 37 tests, todos PASS)

Cadena ejercitada, sin fixtures en el camino principal:
`texto real del split dev → KnowledgePipeline (local_only, determinista, writer
dry-run) → review_export.export_review_package → proposals/ → ReviewService →
GET/POST /v3/review vía TestClient sobre `app.main:app` con auth real`.

**A. Acceso y roles (1-8)** — todos PASS

| # | Caso | Estado |
|---|---|---|
| 1 | Anónimo no lee el feed (302 a /login) | PASS (hueco nuevo) |
| 2 | Anónimo no puede decidir y no escribe ledger | PASS (hueco nuevo) |
| 3 | Rol `viewer` insuficiente para leer (403) | PASS (hueco nuevo) |
| 4 | Rol `viewer` insuficiente para decidir (403, ledger vacío) | PASS (hueco nuevo) |
| 5 | Rol `reviewer` lee el feed (200) | PASS (hueco nuevo) |
| 6 | Rol `admin` lee el feed (200) | PASS (hueco nuevo) |
| 7 | Cookie de sesión inválida no escala a reviewer | PASS (hueco nuevo) |
| 8 | CSRF inválido no registra decisión (403) | PASS (hueco nuevo) |

**B. Carga del feed desde propuestas reales (9-17)** — todos PASS

| # | Caso | Estado |
|---|---|---|
| 9 | El paquete lo escribió el motor, es único y content-addressed | PASS |
| 10 | Toda propuesta cita texto literal exacto del episodio | PASS |
| 11 | Sólo se exportan REVIEW/ABSTAIN/REJECT_INVALID; nunca ACCEPT | PASS |
| 12 | El HTML muestra las propuestas reales con su `<mark>` | PASS (amplía `test_html_contains_exact_mark`) |
| 13 | El feed es estable y determinista entre dos cargas | PASS |
| 14 | Filtro por `source_id` real (≥2 fuentes) | PASS (amplía el existente, con datos reales) |
| 15 | Filtro por `engine_decision` real | PASS (ídem) |
| 16 | Workspace desconocido → 404 | PASS (hueco nuevo) |
| 17 | El feed no cruza workspaces | PASS (amplía el existente) |

**C. Decisiones: aprobar / rechazar / editar (18-26)** — todos PASS

| # | Caso | Estado |
|---|---|---|
| 18 | APPROVE por HTTP con el hash que el HTML mostró de verdad | PASS |
| 19 | REJECT por HTTP con motivo | PASS (hueco nuevo) |
| 20 | CORRECT sin ningún cambio → 400, ledger vacío | PASS (hueco nuevo) |
| 21 | CORRECT registra exactamente la corrección enviada | PASS (hueco nuevo) |
| 22 | `human_decision` desconocida se rechaza | PASS (hueco nuevo) |
| 23 | Falta `expected_proposal_hash` → 400 | PASS (ya existía parcial en `test_post_reload...`) |
| 24 | Propuesta inexistente en el workspace | PASS (hueco nuevo) |
| 25 | Decidir saca de la cola pero **no borra** la propuesta (`total` intacto) | PASS |
| 26 | Una decisión humana no es un plan; driver que estalla si se toca | PASS (amplía `test_service_never_calls_neo4j...`) |

**D. Integridad append-only del ledger (27-32)** — todos PASS

| # | Caso | Estado |
|---|---|---|
| 27 | Reenvío del formulario ×3 → una sola entrada | PASS (ya cubierto; se replica con datos reales) |
| 28 | Dos decisiones distintas se encadenan (`previous_hash`) | PASS (hueco nuevo: la cadena en sí no se verificaba) |
| 29 | Corregir no borra la anterior; entrada original byte-idéntica | PASS (amplía `test_correction_supersedes...`) |
| 30 | Reescribir una entrada rompe la cadena (`hash inválido`) | PASS (ya cubierto) |
| 31 | **Borrar** una entrada rompe la cadena (`cadena rota`) | PASS (hueco nuevo) |
| 32 | `request_id` no reutilizable para otra decisión | PASS (amplía el existente) |

**E. STALE_REVIEW (33-36)** — todos PASS

| # | Caso | Estado |
|---|---|---|
| 33 | Hash que el revisor nunca vio → StaleReviewError + auditoría | PASS (ya cubierto; se replica con datos reales) |
| 34 | Hash de **otra propuesta real** del motor → STALE_REVIEW | PASS (hueco nuevo) |
| 35 | STALE por HTTP → 303 con `notice=STALE_REVIEW`, sin escritura, propuesta sigue pendiente | PASS (hueco nuevo) |
| 36 | STALE no altera el historial válido previo (fichero byte-idéntico) | PASS (hueco nuevo) |

**Transversal**: `test_no_mutacion_del_glosario_en_el_flujo_completo` (ver §3).

### 2.2 Candidatos de glosario — `data-engine/app/tests/test_knowledge_v3_glossary_candidates.py` (24 tests, todos PASS)

| # | Caso | Estado |
|---|---|---|
| 1 | Tipo de candidato inválido se rechaza y no escribe | PASS |
| 2 | Los cinco tipos declarados se aceptan | PASS |
| 3 | `candidate_id` determinista entre almacenes distintos | PASS |
| 4 | `candidate_id` depende del workspace | PASS |
| 5 | `candidate_id` depende del tipo | PASS |
| 6 | `candidate_id` depende del valor y de la entidad resuelta | PASS |
| 7 | `candidate_id` normaliza mayúsculas/espacios; conserva el valor humano original | PASS |
| 8 | Repetir incrementa `occurrence_count` sin duplicar en la vista | PASS |
| 9 | Repetir agrega `source_ids` y `episode_ids` | PASS |
| 10 | Repetir agrega evidencias en orden estable | PASS |
| 11 | El origen acumula todas las decisiones humanas y propuestas | PASS |
| 12 | `source_count` = nº de fuentes distintas (≠ ocurrencias) | PASS |
| 13 | El JSONL es append-only (dos versiones, hashes distintos) | PASS |
| 14 | `list()` pliega por `candidate_id` tras reiniciar el almacén | PASS |
| 15 | `list()` devuelve orden estable | PASS |
| 16 | Aislamiento por workspace (vistas y ficheros separados) | PASS |
| 17 | Cada propuesta deja una entrada `CANDIDATE_PROPOSED` en `audit.jsonl` | PASS |
| 18 | `candidate_hash` no depende del reloj (reproducible) | PASS |
| 19 | `candidate_hash` cambia si cambia el contenido | PASS |
| 20 | Todo candidato nace `PROPOSED` y sin bandera de aplicación | PASS |
| 21 | El almacén no expone ninguna vía de aplicación (API pública = `{root, list, propose}`) | PASS |
| 22 | Workspace sin candidatos → lista vacía | PASS |
| 23 | **Cadena real**: un REJECT humano no propone ningún candidato, ni con campos de corrección presentes | PASS |
| 24 | **Cadena real**: CORRECT sobre propuesta real del pipeline propone los 5 tipos, todos `PROPOSED`, con origen trazable — y el glosario efectivo no cambia | PASS |

---

## 3. Prueba de no-mutación del glosario

**Glosario efectivo** = `Lexicon` del workspace que consume la cadena (alias del
perfil + nombres y tipos del catálogo) + la clase de `GlossarySource` de la
cascada de resolución. Se serializa canónicamente (entradas ordenadas:
`canonical`, `entity_type`, `variants` ordenadas, `confidence`, `origin`) y se
hashea con SHA-256.

Flujo completo medido: pipeline real → exportación del paquete → carga del feed
por HTTP → APPROVE + REJECT + CORRECT (con `subject_alias`,
`subject_canonical_name`, `spoken_form`, `misrecognition`,
`suggested_entity_type`, `is_ocr_asr_error`) → generación de candidatos.

```
GLOSARIO_ANTES   = f9de1bc7d6e377299dcccdd42c1d7a8ab68beb1f47361ef68e40959dad7ce46d
GLOSARIO_DESPUES = f9de1bc7d6e377299dcccdd42c1d7a8ab68beb1f47361ef68e40959dad7ce46d
```

**IDÉNTICOS.** El mismo par de hashes se obtiene por las dos vías independientes
(`viewer/tests/test_v3_review_e2e.py` y
`data-engine/app/tests/test_knowledge_v3_glossary_candidates.py::test_24`).

Refuerzo estructural (caso 21): la API pública de `GlossaryCandidateStore` es
exactamente `{root, list, propose}` — no existe `apply`, `approve`, `commit`,
`delete`, `update`, `upsert` ni `merge`. La no-mutación no depende de que nadie
llame al método equivocado: el método no existe.

---

## 4. Veredicto por gate

| Gate | Veredicto | Evidencia |
|---|---|---|
| El feed `/v3/review` se sirve de propuestas REALES generadas por el pipeline (no fixtures) | **CONFORME** | Fixture `real_proposals` ejecuta `KnowledgePipeline.run(..., review_proposals_dir=...)` sobre las fuentes del split dev; casos 9-17 |
| Append-only: ninguna decisión sobrescribe ni borra una anterior | **CONFORME** | Casos 27-32; reescritura y borrado detectados por la cadena de hashes |
| STALE_REVIEW se detecta y se rechaza siempre que la base haya cambiado | **CONFORME CON SALVEDAD** | Casos 33-36. Salvedad: ver hallazgo H-1 — por construcción del exportador, un cambio real de contenido produce un `proposal_id` distinto, no un `proposal_hash` distinto para el mismo id |
| Control de acceso: sin credenciales o con rol insuficiente no se lee ni se decide | **CONFORME** | Casos 1-8 sobre `app.main:app` con `S9K_AUTH_ENABLED=true` |
| Hash del glosario idéntico antes/después | **CONFORME** | §3 |

**Veredicto global de la PUERTA 6B: CONFORME** (con la salvedad documentada en H-1,
que es una observación de diseño, no un defecto de producción).

---

## 5. Hallazgos

### H-1 (observación de diseño, no defecto) — `proposal_id` y `proposal_hash` son 1:1

`review_export._semantic_hash` calcula `proposal_id` sobre el documento
**excluyendo** `proposal_id` y `proposal_hash`; `proposal_hash` se calcula sobre
el mismo cuerpo más el `proposal_id` recién derivado. Y
`v3_review.proposal_hash()` hace lo mismo. Consecuencia: **no existe ningún
cambio de contenido que deje el `proposal_id` igual y el `proposal_hash`
distinto.**

Reproducción mínima:

```python
from knowledge_v3.review_export import review_documents
docs = review_documents(result, workspace="bench-dev")
# Para todo par de documentos: doc_a["proposal_id"] == doc_b["proposal_id"]
#                          <=> doc_a["proposal_hash"] == doc_b["proposal_hash"]
```

Impacto real: si el motor reexporta con contenido cambiado, el revisor que
envía la decisión no recibe `STALE_REVIEW` sino
`ReviewError("propuesta inexistente en el workspace seleccionado")` (HTTP 400),
porque el `proposal_id` que tenía ya no está en `proposals/`. El resultado sigue
siendo seguro (no se escribe nada), pero el código de error que ve el operador
no es el que describe la situación. `STALE_REVIEW` sólo es alcanzable con un
hash que el revisor no vio: pestaña vieja, replay o manipulación (casos 33-35).

Recomendación (no aplicada, fuera de alcance de esta puerta): que la ruta
traduzca "propuesta ausente pero con decisiones previas en ese `episode_id`" a
`STALE_REVIEW`, o que `proposal_id` sea estable por identidad semántica
(sujeto/predicado/objeto/episodio) y `proposal_hash` cubra el resto.

### H-2 (observación de cobertura) — la extracción determinista produce muy pocas propuestas

Con `ablation=local_only` sobre el split `dev` completo (6 fuentes, 16
episodios), la cadena produce **3 decisiones, todas `ABSTAIN`**, y ninguna con
sujeto/predicado/objeto resueltos (`"UNKNOWN"`), con `reason_codes` que incluyen
`PREDICATE_ABSENT`, `INSUFFICIENT_EVIDENCE` y `EXTRACTOR_REQUESTED_REVIEW`.
Son propuestas reales y bastan para el E2E, pero conviene dejarlo dicho: el feed
de revisión que esta puerta valida no contiene ninguna propuesta `REVIEW` con
tripleta poblada, porque el extractor determinista sin proveedores no la genera.
Esto es coherente con el defecto D-6 ya documentado en `11-e2e.md`.

Reproducción mínima:

```python
from test_knowledge_v3_e2e_fixtures import gold_dev, pipeline, snapshot_entities
from knowledge_v3.pipeline import from_raw
g = gold_dev(); p = pipeline(g)
res = p.run([from_raw(s) for s in g.sources], catalog_entities=snapshot_entities(g))
# -> 3 decisiones, todas ABSTAIN
```

### H-3 (observación) — `cases_from_gold(entry="episodes")` no produce ninguna reclamación

Con la entrada `episodes` (la que usa el runner de benchmarks por defecto), las
6 corridas terminan con `stopped_at="engine"` y **0 claims**, luego el paquete
exportado sale con `items: []`. Con `from_raw` sobre las mismas fuentes sí hay
claims. No se toca: es material del motor, fuera del alcance de esta puerta,
pero explica por qué el E2E usa `from_raw`.

Reproducción mínima:

```python
res = p.run(cases_from_gold(g, entry="episodes"), catalog_entities=entities)
assert sum(len(r.claims) for r in res.runs) == 0
assert [r.stopped_at for r in res.runs] == ["engine"] * 6
```

**Ningún hallazgo requirió `xfail(strict=True)`**: los tres son observaciones de
diseño/cobertura, no fallos de una invariante declarada. No se ha modificado
ningún fichero de producción.

---

## 6. Ejecución

```
$ cd data-engine/app && python3 -m pytest tests/test_knowledge_v3_glossary_candidates.py -q
24 passed in 0.91s

$ cd viewer && python3 -m pytest tests/test_v3_review_e2e.py -q
37 passed in 5.31s

$ cd viewer && python3 -m pytest tests/ -q
418 passed, 1 skipped in 30.24s

$ cd data-engine/app && python3 -m pytest tests/ -q
3 failed, 4689 passed, 26 skipped in 96.81s
```

**Los 3 fallos del árbol data-engine NO son míos.** Provienen de ficheros sin
seguimiento que ha dejado otro agente en este worktree:

- `tests/test_knowledge_v3_gate5_authority.py::test_un_fallo_del_proveedor_se_abstiene_y_deja_rastro[respuesta_vacia]`
- `tests/test_knowledge_v3_gate5_authority.py::test_el_fallo_de_un_episodio_no_tumba_el_lote[respuesta_vacia]`
- `tests/test_knowledge_v3_negation_battery.py::test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico` —
  el propio mensaje nombra al culpable:
  `['data-engine/app/tests/gate4_negation_measure.py']`, fichero ajeno.

Verificado ejecutando esos dos ficheros por separado, sin los míos en la
selección: fallan igual. Ninguno de mis tests toca `datasets/negation` ni
`datasets/heldout`.

Ficheros creados (ninguno modificado):

- `viewer/tests/test_v3_review_e2e.py` — 37 tests
- `data-engine/app/tests/test_knowledge_v3_glossary_candidates.py` — 24 tests
- `artifacts/v3-final-validation/gate6b-human-review.md` — este documento

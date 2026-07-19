# QA Lote 3 — Matriz de la QA transversal FINAL (OLA 2B, producto real)

Agente **QF** (QA final Wave 2B). Rama `test/wave2b-final-product-v1`, basada en
`origin/main` @ `91f972f` (incluye R8 pipeline, B1 corpus y B2 benchmark).

Esta QA importa y ejercita los componentes **REALES** de OLA 2B. **No** hay clases
espejo, dataclasses locales que sustituyan producto, ni logica duplicada: los tests
solo construyen *payloads* de entrada y dobles de transporte inyectables, y hacen
asserts sobre el comportamiento del producto importado. Las mutaciones afectan al
producto real.

## Ficheros de test (todos en `tests/wave2b/`)

| Fichero | Tests | Cobertura |
|---|---|---|
| `test_pipeline_e2e_real.py` | 15 | 15 escenarios E2E contra R8 real + B2 real |
| `test_hostile_real.py` | 13 | verificaciones hostiles contra producto real |
| `test_mutations_final.py` | 20 | 20/20 mutation checks finales |
| `_final_helpers.py` | (helper, no test) | factorias de payload/transporte (no reimplementa producto) |

- **Tests nuevos Lote 3:** 48 (15 + 13 + 20).
- **Total suite `tests/wave2b`:** 69 (21 previos de Lote 2 + 48 nuevos), **69 passed**.
- **Mutation-marked en `tests/wave2b`:** 32 (12 previos + 20 nuevos).

Ejecucion (desde la raiz del repo):

```bash
python3 -m pytest tests/wave2b -q
# 69 passed
```

## Confirmaciones de seguridad

- Ollama/NVIDIA **reales**: `NOT_EXECUTED`. Los proveedores en sombra se ejercitan
  SOLO con transporte/proveedor inyectado (duck-typed), nunca red.
- Red: **ninguna**. Sockets minados en las rutas por defecto y de fallo cerrado.
- Escritura: **ninguna** (`builtins.open` en modo escritura minado; flags de
  escritura en config rechazadas).
- Neo4j: **sin driver** en la ruta de import del pipeline.
- Autoaprobacion: **imposible** (recomendaciones limitadas a propose/reject/human).

---

## 1. Escenarios E2E (contra R8 real `relations.pipeline.run_pipeline`)

| # | Escenario | Test | Verificacion clave |
|---|---|---|---|
| 1 | Relacion simple | `test_e2e_01_single_relation` | 1 candidato, evidencia literal |
| 2 | Varias relaciones | `test_e2e_02_multiple_relations` | ≥2 candidatos, evidencias literales |
| 3 | Negacion | `test_e2e_03_negation` | `negated=True` |
| 4 | Temporalidad | `test_e2e_04_temporality` | `temporal_scope` no nulo |
| 5 | Rumor | `test_e2e_05_rumor` | `epistemic_status=RUMORED` |
| 6 | Conflicto | `test_e2e_06_provider_conflict` | local propone / externo rechaza (proveedores inyectados), estado de consenso canonico |
| 7 | Proveedor ausente | `test_e2e_07_provider_absent_not_executed` | `NOT_EXECUTED`, candidato no rechazado |
| 8 | Proveedor invalido | `test_e2e_08_provider_invalid_fails_closed` | `FAILED_CLOSED` sin red |
| 9 | Multiples workspaces | `test_e2e_09_multiple_workspaces_isolated` | aislamiento + mezcla rechazada |
| 10 | Segmento defectuoso | `test_e2e_10_defective_segment_isolated` | fallo aislado, resto sobrevive |
| 11 | Explosion combinatoria | `test_e2e_11_combinatorial_explosion_capped` | `truncated=True`, pares ≤ limite |
| 12 | Ejecucion repetida | `test_e2e_12_repeated_execution_deterministic` | mismos `execution_id`/`result_hash` |
| 13 | Corpus completo B1 | `test_e2e_13_full_corpus_via_run_pipeline` | `run_pipeline` sobre 16 fuentes, evidencias literales |
| 14 | Benchmark baseline (B2) | `test_e2e_14_benchmark_baseline_via_b2` | `run_benchmark`+`build_report`, gates duros PASS, dictamen en vocabulario cerrado |
| 15 | Benchmark offline (B2) | `test_e2e_15_benchmark_full_offline_via_b2` | modo `full_offline`, sin contaminacion, hash por fuente |

---

## 2. Tabla 20/20 mutaciones (mutacion → test que la caza)

### M1–M12 (reproducidas contra R8 real)

| # | Mutacion (regresion) | Test | Como se caza |
|---|---|---|---|
| 1 | workspace vacio aceptado | `test_m01_empty_workspace_rejected` | `PipelineError` al vaciar workspace |
| 2 | sin limite de pares | `test_m02_pair_limit_enforced` | `truncated=True`, pares ≤ `max_pairs_per_segment` |
| 3 | mezcla de workspaces aceptada | `test_m03_workspace_mix_rejected` | error `workspace_mismatch`, `results==[]` |
| 4 | evidencia inexistente aceptada | `test_m04_nonexistent_evidence_rejected` | `text[start:end]==evidence_text` para todo candidato |
| 5 | ignorar negacion | `test_m05_negation_not_ignored` | `negated=True` con negacion / `False` sin ella |
| 6 | ignorar temporalidad | `test_m06_temporality_not_ignored` | `temporal_scope` no nulo con marcador / nulo sin el |
| 7 | proveedor ausente → rechazo | `test_m07_absent_provider_not_a_reject` | `NOT_EXECUTED` con candidato presente |
| 8 | autoaprobacion | `test_m08_no_auto_approval` | recomendacion ∈ {propose,reject,human}, nunca APPROVED |
| 9 | escritura en dry-run | `test_m09_write_in_dryrun_rejected` | flags write/apply/persist/commit/auto_approve rechazadas |
| 10 | IDs aleatorios | `test_m10_ids_not_random` | `execution_id`/`result_hash` deterministas por contenido |
| 11 | resultado dependiente del orden | `test_m11_result_order_independent` | reordenar segmentos → mismo `result_hash` |
| 12 | endpoint por defecto | `test_m12_default_endpoint_fails_closed` | proveedor habilitado sin transporte → `FAILED_CLOSED`, socket minado |

### M13–M20 (nuevas)

| # | Mutacion (regresion) | Test | Como se caza |
|---|---|---|---|
| 13 | ground truth con hash incorrecto aceptado | `test_m13_wrong_ground_truth_hash_rejected` | GT manipulado → `BenchmarkError`; corpus intacto verifica |
| 14 | evidencia fuera del texto aceptada | `test_m14_evidence_outside_text_not_accepted` | toda evidencia del benchmark ∈ `[0,len(text)]` y literal |
| 15 | prediccion duplicada contada dos veces | `test_m15_duplicate_prediction_not_double_counted` | matching 1:1: `tp` no sube, el duplicado es FP |
| 16 | direccion ignorada | `test_m16_direction_not_ignored` | `direction_correct` distingue correcta/incorrecta |
| 17 | negacion ignorada en benchmark | `test_m17_negation_not_ignored_in_benchmark` | `negation_correct` refleja el desajuste |
| 18 | temporalidad ignorada en benchmark | `test_m18_temporality_not_ignored_in_benchmark` | `temporal_correct` exige deteccion cuando GT=PAST |
| 19 | pipeline no real sustituido por fixture | `test_m19_pipeline_is_real_not_a_fixture` | identidad `runner.run_pipeline is pipeline.run_pipeline`, esquema `relation-pipeline/v1`, `execution_id` hash |
| 20 | resultado no determinista aceptado | `test_m20_nondeterministic_result_rejected` | gate DURO de determinismo del benchmark en PASS (hashes/metricas/preds iguales) |

---

## 3. Verificaciones hostiles (contra producto real)

| Amenaza | Test | Resultado esperado |
|---|---|---|
| path traversal en archivos del corpus | `test_hostile_corpus_tamper_detected` | sha256 del manifest detecta la manipulacion → `BenchmarkError` |
| JSONL invalido | `test_hostile_invalid_jsonl_rejected` | evaluador local → `INVALID_RESPONSES` |
| source ID duplicado | `test_hostile_duplicate_source_id_deterministic` | ejecucion determinista y aislada |
| segment ID duplicado | `test_hostile_duplicate_segment_id` | salida estable, sin excepcion |
| workspace vacio | `test_hostile_empty_workspace_rejected` | `PipelineError` |
| workspace cruzado | `test_hostile_cross_workspace_leak_blocked` | `workspace_mismatch`, cero fugas |
| texto gigante | `test_hostile_giant_text_capped` | fallo de segmento aislado (`segment_text_too_large`) |
| entidad gigante | `test_hostile_giant_entity_count_capped` | rechazado (`too_many_entities`) |
| prompt injection | `test_hostile_prompt_injection_is_data_not_command` | texto tratado como dato, flujo intacto |
| secreto falso | `test_hostile_fake_secret_is_redacted` | redactado en la traza; `find_secrets` lo reconoce |
| endpoint falso + intento de socket | `test_hostile_fake_endpoint_and_no_socket` | socket minado; `SecretLeakError` antes de enviar |
| intento de escritura | `test_hostile_no_write_path` | `open` de escritura minado; flags de escritura rechazadas |
| intento de acceso Neo4j | `test_hostile_no_neo4j_driver_in_path` | sin import ni driver neo4j en la ruta |

---

## 4. Evidencia de PRODUCTO REAL (simbolo importado por test)

Autocomprobacion para el Supervisor: cada test importa rutas reales; sin espejos.

| Test / grupo | Simbolo(s) REAL importado(s) |
|---|---|
| E2E 1–12 | `relations.pipeline.run_pipeline`, `PipelineConfig`, `PipelineError`, `PROVIDER_*` |
| E2E 13 | `relations.pipeline.run_pipeline` + `relations.benchmark.{load_corpus,derive_entities,build_payload}` |
| E2E 14–15 | `relations.benchmark.{load_corpus,run_benchmark,build_report}`, `relations.benchmark.report.VERDICTS` |
| Hostil corpus | `relations.benchmark.load_corpus`, `relations.benchmark.runner.BenchmarkError` |
| Hostil JSONL | `relations.local_llm_shadow.{LocalLLMConfig,RelationEvalInput,evaluate_relation_local}`, `external_ai.models.INVALID_RESPONSES` |
| Hostil secreto/redaccion | `relations.observability.{RelationTrace,ComponentResult,find_secrets}` |
| Hostil endpoint/socket | `external_ai.security.assert_no_secrets`, `external_ai.errors.SecretLeakError` |
| Hostil sintaxis | `relations.syntax.{get_analyzer,safe_analyze}` |
| M1–M12 | `relations.pipeline.{run_pipeline,config_from_dict,PipelineConfig,PipelineError,PROVIDER_*}` |
| M13 | `relations.benchmark.load_corpus`, `runner.BenchmarkError` |
| M14–M15 | `relations.benchmark.{run_benchmark,match_predictions}` (predicciones reales del pipeline) |
| M16–M18 | `relations.benchmark.matching.structural_flags` (dicts = formato real de prediccion) |
| M19 | identidad `relations.benchmark.runner.run_pipeline is relations.pipeline.run_pipeline` |
| M20 | `relations.benchmark.build_report` (gate duro de determinismo real) |

Confirmaciones en tiempo de import (fallan si se sustituye producto por espejo):

- `assert run_pipeline is relations.pipeline.run_pipeline`
- `assert relations.benchmark.runner.run_pipeline is relations.pipeline.run_pipeline`

## 5. Defectos de producto detectados

Ninguno. Todos los invariantes de seguridad y calidad del producto real
(R8 pipeline, B1 corpus, B2 benchmark) se sostienen bajo los 15 escenarios E2E,
las 13 verificaciones hostiles y las 20 mutaciones. **Reproducir, no corregir**:
no se ha modificado ningun modulo de producto.

Observacion (no defecto): el dictamen real del benchmark en `baseline1` es
`APTO CON REVISION HUMANA TOTAL` (predicado heuristico debil; evidencia/offsets
solidos), coherente con que R8 es un PROPOSITOR en sombra, no un extractor
autonomo. Metricas de existencia reales: TP=43, FP=9, FN=11 (P=0.827, R=0.796,
F1=0.811). Los gates duros (determinismo, contaminacion de workspaces) en PASS.

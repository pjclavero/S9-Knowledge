# 50 - Benchmark de extraccion de relaciones: resultados (v1)

Ejecucion del pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el
corpus B1 **REAL** (`app/tests/data/relation_benchmark/`), comparado contra el
ground truth. El runner NO reimplementa ninguna etapa de R8 ni simula resultados.
El plan, el criterio de emparejamiento y la derivacion de entidades se documentan
en `docs/41-relation-benchmark-plan.md`.

## Confirmacion de seguridad

- Ollama real: **NOT_EXECUTED**
- NVIDIA real: **NOT_EXECUTED**
- Red: **ninguna**
- Escritura / Neo4j: **ninguna** (dry-run)
- Pipeline: `relation-pipeline-1.0.0` | code SHA: `b362a9d09a45fa310da1d97c0de986ff163ddc00`

## Configuracion

- Modo del dictamen: `baseline1` (config real: `{"context_mode": "sentence", "external_ai_enabled": false, "external_model": "external-model", "external_provider_name": "nvidia", "local_llm_enabled": false, "local_model": "local-llm", "max_distance": null, "max_entities_per_segment": 200, "max_errors_per_batch": 1000, "max_pairs_per_segment": 1000, "max_prompt_chars": 24000, "max_response_bytes": 65536, "max_results": 100000, "max_segments_per_doc": 500, "max_text_chars": 200000, "max_time_per_candidate_ms": 30000, "pair_window": "char", "prompt_suite": "balanced"}`)
- Corpus v1.0.0: 16 fuentes, 54 relaciones de ground truth
- Ground truth sha256: `15973d1837deb29ea339bca6bb3980d62e07ef283b196bf38d0d1e2653d9cc5c`
- Versiones de componentes: `{"consensus": "relation-consensus-1.0.0", "contract": "internal-1.0.0", "pipeline": "relation-pipeline-1.0.0", "prompts": "1.0", "signals": "relation-signals-1.0.0", "syntax": "relation-syntax-1.0.0", "template": "1.0.0"}`

## Dictamen del benchmark

### **APTO CON REVISION HUMANA TOTAL**

> evidencia/offsets fiables pero el predicado heuristico es debil: toda relacion requiere revision humana antes de considerarse

Nota: el vocabulario de dictamen NO incluye "APTO PARA INGESTA REAL". El
pipeline es un propositor en modo sombra / dry-run: nunca aprueba ni escribe.

## Metricas globales (criterio de existencia: par no ordenado)

| Metrica | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| Existencia de relacion | 82.7% | 79.6% | 81.1% | 43 | 9 | 11 |
| Estricta (par + predicado exacto) | 17.3% | 16.7% | 17.0% | 9 | 43 | 45 |

### Comparativa por modo (config real de PipelineConfig)

| Modo | context_mode | P (exist.) | R (exist.) | F1 | pares generados |
|---|---|---|---|---|---|
| baseline1 | sentence | 82.7% | 79.6% | 81.1% | 52 |
| baseline2 | paragraph | 36.1% | 96.3% | 52.5% | 144 |
| full_offline | segment | 36.1% | 96.3% | 52.5% | 144 |

## Metricas por tipo de relacion (predicado del ground truth)

| Predicado | Soporte | Recall existencia | Recall predicado exacto |
|---|---|---|---|
| ALIAS_OF | 2 | 0.0% | 0.0% |
| ALLIED_WITH | 3 | 100.0% | 0.0% |
| CAUSED | 2 | 100.0% | 0.0% |
| CREATED | 1 | 100.0% | 0.0% |
| ENEMY_OF | 2 | 100.0% | 0.0% |
| FOUNDED | 2 | 50.0% | 0.0% |
| GUARDS | 2 | 100.0% | 0.0% |
| KNOWS | 1 | 100.0% | 0.0% |
| LEADS | 1 | 100.0% | 0.0% |
| LIVES_IN | 3 | 66.7% | 0.0% |
| LOCATED_IN | 4 | 100.0% | 100.0% |
| MARRIED_TO | 1 | 100.0% | 0.0% |
| MEMBER_OF | 10 | 80.0% | 30.0% |
| MENTOR_OF | 2 | 50.0% | 0.0% |
| OWNS | 5 | 80.0% | 20.0% |
| PARENT_OF | 3 | 0.0% | 0.0% |
| PARTICIPATED_IN | 6 | 100.0% | 16.7% |
| SIBLING_OF | 1 | 100.0% | 0.0% |
| SUCCEEDED | 2 | 100.0% | 0.0% |
| TRUSTS | 1 | 100.0% | 0.0% |

### Distribucion de predicados PREDICHOS por el heuristico

| Predicado predicho | Nº |
|---|---|
| LOCATED_IN | 22 |
| MEMBER_OF | 9 |
| OWNS | 4 |
| PARTICIPATED_IN | 1 |
| RELATED_TO | 16 |

## Calidad estructural (sobre los TP de existencia)

| Atributo | Correctos / Total | Tasa |
|---|---|---|
| predicate_correct | 9/43 | 20.9% |
| direction_correct | 27/43 | 62.8% |
| direction_orientation_ok | 29/43 | 67.4% |
| types_correct | 43/43 | 100.0% |
| negation_correct | 39/43 | 90.7% |
| temporal_correct | 25/43 | 58.1% |
| epistemic_correct | 36/43 | 83.7% |
| evidence_correct | 39/43 | 90.7% |
| offsets_correct | 40/43 | 93.0% |
| workspace_correct | 43/43 | 100.0% |
| decision_correct | 13/43 | 30.2% |

## Metricas operativas (contadores REALES del pipeline)

| Contador | Valor |
|---|---|
| documents | 16 |
| segments | 16 |
| segments_processed | 16 |
| segments_failed | 0 |
| entities | 93 |
| pairs_potential | 236 |
| pairs_generated | 52 |
| pairs_discarded | 184 |
| candidates_evaluated | 52 |
| results_strong | 0 |
| results_partial | 19 |
| results_conflict | 13 |
| results_invalid | 0 |
| results_human | 20 |
| errors | 0 |
| tiempo total (ms) | 35.115 |
| tiempo por doc (ms) | 2.195 |
| tiempo por candidato (ms) | 0.675 |
| tasa humana | 38.5% |
| tasa conflicto | 25.0% |
| tasa invalida | 0.0% |

## Gates (evaluados por separado)

| Gate | Estado | Valor | Umbral | Tipo |
|---|---|---|---|---|
| determinism | **PASS** | - | - | DURO |
| workspace_contamination | **PASS** | - | - | DURO |
| simple_relations | **PASS** | 93.3% | 80.0% | calidad |
| evidence | **PASS** | 90.7% | 80.0% | calidad |
| offsets | **PASS** | 93.0% | 90.0% | calidad |
| negation | **PASS** | 100.0% | 80.0% | calidad |
| temporality | **FAIL** | 28.0% | 60.0% | calidad |
| rumors | **PARTIAL** | 50.0% | 60.0% | calidad |
| predicate_structural | **FAIL** | 20.9% | 50.0% | calidad |

## Determinismo

- Determinista (2 ejecuciones): **True**
- Hashes iguales: True | Metricas iguales: True | Predicciones iguales: True

## Errores destacados

- Falsos negativos (relaciones de GT no cubiertas): **11**
- Falsos positivos (predicciones sin GT): **9**
- Menciones no localizadas en la derivacion de entidades: **0**

### Falsos negativos (primeros 20)

| relation_id | source | predicado | sujeto->objeto | motivo |
|---|---|---|---|---|
| rel-005 | src-02 | MEMBER_OF | draven->orden-alba | Pertenencia explicita. |
| rel-006 | src-02 | LIVES_IN | draven->torre-sable | Sujeto omitido (elipsis en ficha); sujeto = Draven por conte |
| rel-007 | src-02 | OWNS | draven->filo-luna | Posesion de objeto; sujeto omitido = Draven. |
| rel-008 | src-02 | PARENT_OF | aldric->draven | Direccional: 'Draven hijo de Aldric' => Aldric PARENT_OF Dra |
| rel-009 | src-02 | PARENT_OF | draven->nima | Direccional: Draven PARENT_OF Nima. |
| rel-010 | src-02 | ALIAS_OF | draven->draven | ALIAS: 'el Cuervo' == Draven. Relacion reflexiva de identida |
| rel-029 | src-07 | MENTOR_OF | vayra->sela | PRONOMBRE OBJETO: 'le' = Sela. Refuerza la relacion de mento |
| rel-031 | src-08 | MEMBER_OF | kaelan->pacto-escarlata | CONTRADICCION 2/2: segmento B NIEGA la lealtad al Pacto. neg |
| rel-042 | src-12 | PARENT_OF | torin->bran | Parentesco inferido de 'esa unión' (Lyra+Torin). Sujeto omit |
| rel-046 | src-14 | ALIAS_OF | ysolde->ysolde | ALIAS 2: 'conocida como la Reina de Invierno'. Identidad, no |
| rel-054 | src-16 | FOUNDED | vayra->ateneo | HECHO PASADO CONFIRMADO: 'Lo que sí consta es que ... fundó' |

### Falsos positivos (primeros 20)

| source | predicado | sujeto->objeto | consenso |
|---|---|---|---|
| src-01 | LOCATED_IN | horda-grael->batalla-vado | MODEL_CONFLICT |
| src-02 | RELATED_TO | aldric->nima | HUMAN_REQUIRED |
| src-04 | RELATED_TO | draven->kael | HUMAN_REQUIRED |
| src-04 | RELATED_TO | draven->sela | HUMAN_REQUIRED |
| src-04 | RELATED_TO | sela->kael | HUMAN_REQUIRED |
| src-05 | LOCATED_IN | kaelin->kaelan | HUMAN_REQUIRED |
| src-06 | LOCATED_IN | guardia-hierro->cripta-roja | PARTIAL_CONSENSUS |
| src-08 | MEMBER_OF | pacto-escarlata->guardia-hierro | PARTIAL_CONSENSUS |
| src-10 | OWNS | liga-meridiano->gremio-cartografos | MODEL_CONFLICT |


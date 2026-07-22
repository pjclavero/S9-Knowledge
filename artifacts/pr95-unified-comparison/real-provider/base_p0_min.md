# 50 - Benchmark de extraccion de relaciones: resultados (v1)

Ejecucion del pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el
corpus B1 **REAL** (`app/tests/data/relation_benchmark/`), comparado contra el
ground truth. El runner NO reimplementa ninguna etapa de R8 ni simula resultados.
El plan, el criterio de emparejamiento y la derivacion de entidades se documentan
en `docs/41-relation-benchmark-plan.md`.

## Confirmacion de seguridad

- Ollama real: **NOT_EXECUTED**
- NVIDIA real: **EXECUTED**
- Red: **yes (4 llamadas a proveedor contabilizadas; 0 fallos de transporte)**
- Llamadas a proveedor contabilizadas: **4**
- Endpoints (host:puerto normalizado, SIN credenciales): `external_ai=https://integrate.api.nvidia.com`
- Escritura / Neo4j: **none (dry-run, sin Neo4j)**
- Pipeline: `relation-pipeline-1.0.0` | code SHA: `92583f40058a2e685cd8b9a54688250c4ee3ddd9`

## Configuracion

- Modo del dictamen: `nvidia_shadow` (config real: `{"context_mode": "sentence", "external_ai_enabled": true, "external_model": "meta/llama-3.3-70b-instruct", "external_provider_name": "nvidia", "local_llm_enabled": false, "local_model": "local-llm", "max_distance": null, "max_entities_per_segment": 200, "max_errors_per_batch": 1000, "max_pairs_per_segment": 1000, "max_prompt_chars": 24000, "max_response_bytes": 65536, "max_results": 100000, "max_segments_per_doc": 500, "max_text_chars": 200000, "max_time_per_candidate_ms": 30000, "pair_window": "char", "prompt_suite": "balanced"}`)
  - `max_time_per_candidate_ms`: DECLARADO PERO NO APLICADO: el pipeline no lo comprueba en ningun punto; no limita el tiempo por candidato. No es un control efectivo (la correccion vive en relations/pipeline.py, fuera del alcance del Bloque 7).
- Fuentes ejecutadas (SUBMUESTRA `--sources`): 2/16 -> `src-09, src-13`
- Consenso recalibrado con ensemble (B6): `False`
- Corpus v1.0.0: 16 fuentes, 54 relaciones de ground truth
- Ground truth sha256: `15973d1837deb29ea339bca6bb3980d62e07ef283b196bf38d0d1e2653d9cc5c`
- Versiones de componentes: `{"consensus": "relation-consensus-1.0.0", "contract": "internal-1.0.0", "pipeline": "relation-pipeline-1.0.0", "prompts": "1.0", "signals": "relation-signals-1.0.0", "syntax": "relation-syntax-1.0.0", "template": "1.0.0"}`

## Dictamen del benchmark

### **APTO CON REVISION HUMANA TOTAL**

> evidencia/offsets fiables pero el predicado heuristico es debil: toda relacion requiere revision humana antes de considerarse [gates duros NO EVALUADOS: ['determinism']; dictamen PARCIAL, no cubre esas comprobaciones]

Nota: el vocabulario de dictamen NO incluye "APTO PARA INGESTA REAL". El
pipeline es un propositor en modo sombra / dry-run: nunca aprueba ni escribe.

## Metricas globales (criterio de existencia: par no ordenado)

| Metrica | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| Existencia de relacion | 100.0% | 100.0% | 100.0% | 4 | 0 | 0 |
| Estricta (par + predicado exacto) | 0.0% | 0.0% | 0.0% | 0 | 4 | 4 |

## Metricas por tipo de relacion (predicado del ground truth)

| Predicado | Soporte | Recall existencia | Recall predicado exacto |
|---|---|---|---|
| CAUSED | 1 | 100.0% | 0.0% |
| ENEMY_OF | 1 | 100.0% | 0.0% |
| KNOWS | 1 | 100.0% | 0.0% |
| OWNS | 1 | 100.0% | 0.0% |

### Distribucion de predicados PREDICHOS por el heuristico

| Predicado predicho | Nº |
|---|---|
| MEMBER_OF | 1 |
| RELATED_TO | 3 |

## Calidad estructural (sobre los TP de existencia)

| Atributo | Correctos / Total | Tasa |
|---|---|---|
| predicate_correct | 0/4 | 0.0% |
| direction_correct | 0/4 | 0.0% |
| direction_orientation_ok | 1/4 | 25.0% |
| types_correct | 4/4 | 100.0% |
| negation_correct | 4/4 | 100.0% |
| temporal_correct | 1/4 | 25.0% |
| epistemic_correct | 3/4 | 75.0% |
| evidence_correct | 4/4 | 100.0% |
| offsets_correct | 4/4 | 100.0% |
| workspace_correct | 4/4 | 100.0% |
| decision_correct | 1/4 | 25.0% |

## Metricas operativas (contadores REALES del pipeline)

| Contador | Valor |
|---|---|
| documents | 2 |
| segments | 2 |
| segments_processed | 2 |
| segments_failed | 0 |
| entities | 8 |
| pairs_potential | 12 |
| pairs_generated | 4 |
| pairs_discarded | 8 |
| candidates_evaluated | 4 |
| results_strong | 0 |
| results_partial | 0 |
| results_conflict | 0 |
| results_invalid | 4 |
| results_human | 0 |
| errors | 0 |
| tiempo total (ms) | 240503.328 |
| tiempo por doc (ms) | 120251.664 |
| tiempo por candidato (ms) | 60125.832 |
| tasa humana | 0.0% |
| tasa conflicto | 0.0% |
| tasa invalida | 100.0% |

## Coste y latencia por proveedor

Las latencias son SOLO de llamadas RESPONDIDAS: un 404 inmediato o un timeout
no describe al modelo y se contabiliza aparte como fallo de transporte.

| Proveedor | Llamadas | Payloads | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|---|
| LLM local (Ollama) | 0 | 0 | - | - | - |
| IA externa (NVIDIA) | 4 | 4 | 35141.0 | 135722.0 | 151055.0 |

### Fallos de TRANSPORTE (infraestructura, NO calidad del modelo)

Tres categorias DISJUNTAS: TRANSPORTE (la llamada no obtuvo respuesta del
modelo), RESPONDIDA (el proveedor contesto; la calidad del contenido se mide
aparte) e INDETERMINADA (el marcador `provider_error` generico no permite
saber cual de las dos fue: el benchmark NO lo cuenta como transporte ni lo
presenta como calidad).

| Proveedor | Intentadas | Respondidas | Fallos de transporte | Tasa | Tipos | Indeterminadas |
|---|---|---|---|---|---|---|
| LLM local (Ollama) | 0 | 0 | 0 | 0.0% | - | 0 |
| IA externa (NVIDIA) | 4 | 4 | 0 | 0.0% | - | 0 |

## Gates (evaluados por separado)

| Gate | Estado | Valor | Umbral | Tipo |
|---|---|---|---|---|
| determinism | **NOT_EVALUATED** | - | - | DURO |
| workspace_contamination | **PASS** | - | - | DURO |
| provider_transport | **PASS** | 0.0% | 0.0% | DURO |
| simple_relations | **PASS** | 100.0% | 80.0% | calidad |
| evidence | **PASS** | 100.0% | 80.0% | calidad |
| offsets | **PASS** | 100.0% | 90.0% | calidad |
| negation | **PASS** | 100.0% | 80.0% | calidad |
| temporality | **PARTIAL** | 50.0% | 60.0% | calidad |
| rumors | **FAIL** | 0.0% | 60.0% | calidad |
| predicate_structural | **FAIL** | 0.0% | 50.0% | calidad |

## Determinismo

- Determinista (2 ejecuciones): **NO EVALUADO** (segunda ejecucion omitida)
- Alcance del dictamen: **PARCIAL (gates duros no evaluados: determinism)**
- Hashes iguales: None | Metricas iguales: None | Predicciones iguales: None

## Errores destacados

- Falsos negativos (relaciones de GT no cubiertas): **0**
- Falsos positivos (predicciones sin GT): **0**
- Menciones no localizadas en la derivacion de entidades: **0**


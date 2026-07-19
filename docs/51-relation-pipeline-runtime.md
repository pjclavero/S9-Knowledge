# 51 - Pipeline de relaciones (OLA 2B): arquitectura y operacion en runtime

Documento **operativo y de arquitectura** del pipeline final de extraccion de
relaciones de la OLA 2B, tal y como esta **integrado de verdad** en `main`
(`data-engine/app/relations/`). Describe el codigo REAL (R8 `run_pipeline` +
componentes reutilizados + benchmark B2), no un diseno teorico.

Es documentacion pura: **no cambia producto, ni tests, ni produccion**. El
plan/metodo y los resultados del benchmark viven en
[`docs/41-relation-benchmark-plan.md`](41-relation-benchmark-plan.md) y
[`docs/50-relation-benchmark-results.md`](50-relation-benchmark-results.md);
este documento los resume sin maquillar y anade la vista de arquitectura y
operacion del pipeline completo.

---

## 0. Lo que hay que tener claro antes de nada (garantias duras)

El pipeline es un **PROPOSITOR en modo sombra / dry-run**. Nunca decide, nunca
aprueba, nunca escribe. En concreto, y de forma explicita:

- **No escribe en Neo4j.** No importa ni instancia ningun driver ni repositorio
  productivo. El dry-run es **estructural** (no hay flag de write que se pueda
  activar; ver §6).
- **No aprueba automaticamente.** El consenso emite `propose` / `reject` /
  `human`, jamas `APPROVED` / `AUTO_APPROVED` / `WRITE` / `APPLY` (barrera dura
  en `RelationConsensus.__post_init__`).
- **Ollama real NO ejecutado.** El proveedor LLM local esta deshabilitado por
  defecto; sin transporte inyectado falla cerrado sin abrir un socket
  (`OLLAMA_REAL_VALIDATION=NOT_EXECUTED`).
- **NVIDIA real NO ejecutado.** El proveedor de IA externa esta deshabilitado
  por defecto; sin proveedor inyectado / sin API key falla cerrado
  (`NVIDIA_REAL_VALIDATION=NOT_EXECUTED`).
- **OCR NO ejecutado.** El pipeline consume texto/segmentos ya extraidos; no
  hace OCR ni extraccion multimedia.
- **Import `APPLY` NO implementado.** No existe ninguna ruta de aplicacion /
  ingesta real de relaciones al grafo. La ingesta real permanece gateada fuera
  de este pipeline.
- **Produccion NO modificada.** RC5.1 (VM105) queda intacta; el Neo4j de
  produccion (199 nodos / 140 relaciones, segun estado operativo) no se toca.

Todo lo anterior no depende de "acordarse de no activarlo": son propiedades
estructurales del codigo (proveedores deshabilitados por defecto, fallo cerrado,
ausencia total de cliente de escritura, config que rechaza flags de write).

---

## 1. Arquitectura

`data-engine/app/relations/` es un paquete de componentes independientes y
**deterministas**, orquestados por un unico modulo de pipeline. El pipeline
**no reimplementa** ninguna pieza: es exclusivamente el pegamento que las llama
en orden y ensambla la salida.

```
                       payload (dict)
                          │
              ┌───────────▼────────────┐
              │  pipeline.run_pipeline  │  (relation-pipeline/v1)
              └───────────┬────────────┘
                          │  por segmento (fallo aislado)
   ┌──────────────────────┼───────────────────────────────────┐
   │  pairs.generate_pairs │  -> pares candidatos deterministas │
   │  syntax.safe_analyze  │  -> estructura sintactica (stdlib) │
   │      por par:                                              │
   │    signals.compute_all_signals -> senales explicables      │
   │    _build_candidate            -> RelationCandidate (20)    │
   │    local_llm_shadow (opc)      -> recomendacion LOCAL       │
   │    external_ai_shadow (opc)    -> recomendacion EXTERNA     │
   │    consensus_adapter           -> estado de consenso        │
   └──────────────────────┬───────────────────────────────────┘
                          │
              observability.RelationTrace  (traza redactada, sin backend)
                          │
                          ▼
          salida dict JSON-serializable (+ to_json / to_jsonl)
```

Cada componente cumple las mismas restricciones transversales: **sin red, sin
Neo4j, sin escritura, sin LLM real, sin efectos secundarios, deterministas.**

### Modulos y su papel

| Modulo | Papel | Version |
|---|---|---|
| `pipeline.py` | Orquestador end-to-end dry-run (`run_pipeline`, `PipelineConfig`, `config_from_dict`, `to_json`, `to_jsonl`) | `relation-pipeline-1.0.0` |
| `cli.py` | Envoltura CLI fina y no destructiva (`python -m relations.cli`) | — |
| `contracts.py` | Contrato unico `RelationCandidate` (20 campos), enums, `validate()`, serializacion | `internal-1.0.0` |
| `pairs.py` | Generador determinista de pares candidatos | — |
| `signals.py` | 13 senales heuristicas explicables (senales, no decisiones) | `relation-signals-1.0.0` |
| `syntax.py` | Adaptador sintactico (proveedor `heuristic`, solo stdlib) | `relation-syntax-1.0.0` |
| `prompts/` | Plantillas RPG versionadas (suites, `list_templates`, `KNOWN_PREDICATES`) | suite `1.0`, template `1.0.0` |
| `local_llm_shadow.py` | Evaluador LLM LOCAL en modo sombra (opcional) | `relation-local-llm/v1` |
| `external_ai_shadow.py` | Evaluador IA EXTERNA (NVIDIA NIM) en modo sombra (opcional) | `relation-external/v1` |
| `consensus_adapter.py` | Consenso (estados canonicos reutilizados de `external_ai`) | `relation-consensus-1.0.0` |
| `observability.py` | Traza/eventos redactados, sin backend | — |
| `benchmark/` | Runner + comparador B2 sobre R8 real y corpus B1 real | — |

---

## 2. Flujo end-to-end

`run_pipeline(payload, *, config=None, local_transport=None, external_provider=None)`
ejecuta, en orden:

1. **Config**: si no se pasa `config`, se construye con `config_from_dict(payload["config"])`
   (rechaza flags de escritura, ver §6).
2. **Validacion de entrada** (`_validate_payload`): `workspace` obligatorio y no
   vacio; `document`/`source_id`/`document_id` obligatorio; `segments` debe ser
   lista (puede ser vacia). Limite `max_segments_per_doc`.
3. **Orden canonico de segmentos**: los segmentos se reordenan por
   `(segment_id, indice)` de forma estable. **El orden de entrada NO altera la
   salida.**
4. **execution_id**: hash SHA-256 (32 chars) del *contenido canonico*
   (documento + workspace + segmentos normalizados + config + versiones). **No**
   usa timestamps ni azar.
5. **Por cada segmento** (`_process_segment`, fallo aislado):
   1. Validaciones de segmento: texto es str, `max_text_chars`, workspace del
      segmento == workspace del pipeline (la MEZCLA se rechaza), entidades es
      lista, `max_entities_per_segment`.
   2. **Pares**: `pairs.generate_pairs(entities, segment, config=PairConfig(...))`.
   3. **Sintaxis**: `syntax.safe_analyze(get_analyzer("heuristic"), text)`, una
      vez por segmento.
   4. **Por cada par** (`_process_pair`):
      - **Senales**: `signals.compute_all_signals(SignalContext(...))`.
      - **Candidato**: `_build_candidate(...)` -> `RelationCandidate` validado
        (span de evidencia literal; span vacio o en blanco se rechaza).
      - **Dedup determinista** por clave de candidato (hash de
        `workspace/subject/predicate/object/source_segment`).
      - **LLM local (opcional, sombra)**: `_run_local` solo si `local_llm_enabled`
        y hay plantilla para el predicado; sin transporte -> `FAILED_CLOSED`.
      - **IA externa (opcional, sombra)**: `_run_external` solo si
        `external_ai_enabled`; sin proveedor/key -> `FAILED_CLOSED`.
      - **Consenso**: `consensus_adapter.compute_relation_consensus(candidate,
        signals, syntax, local, external)` -> `state` + `recommendation`.
   5. **Observabilidad**: `trace.record(...)` por segmento (evento redactado).
6. **Contadores derivados** y **limite de errores** (`max_errors_per_batch`;
   superarlo es error FATAL del lote).
7. **Resultados por candidato** ordenados de forma determinista por
   `(source_segment, subject_id, object_id, predicate, candidate_id)`, con corte
   a `max_results`.
8. **provider_status** (resumen de estado de cada proveedor).
9. **Salida** dict + `result_hash` (hash funcional que **excluye** la traza de
   observabilidad y sus tiempos, para que el hash sea reproducible).

### El propositor heuristico (glue, no extraccion duplicada)

`_build_candidate` deriva los campos del candidato de las senales, sin
reimplementar extraccion:

- **predicado**: prioridad `membership -> MEMBER_OF`, `possession -> OWNS`,
  `location -> LOCATED_IN`; si no, por categoria de `type_compatibility`
  (`MEMBERSHIP/LOCATION/POSSESSION/PARTICIPATION`); en ausencia de senal
  especifica, el generico **`RELATED_TO`** (canonico y valido, pero fuera de
  `KNOWN_PREDICATES`: el LLM local solo corre para familias con plantilla).
- **direccion**: por defecto del catalogo de plantillas (`_DIR_BY_PRED`), o
  `UNDIRECTED`.
- **confianza**: heuristica determinista en `[0, 0.9]` (evidencia, no decision):
  suma por `same_sentence`, `same_clause`, `svo_pattern`, `type_compatibility`,
  `repetition>1`.
- **negacion / temporalidad / estado epistemico**: derivados de las senales
  `negation`, `temporality`, `rumor`/`modality`.
- **evidencia**: span LITERAL `[min(inicios), max(fines))` que cubre ambas
  menciones; span vacio o solo espacios -> el candidato se rechaza (error
  recuperable del par, no del segmento).

---

## 3. Contratos

### 3.1 `RelationCandidate` — `relation-candidate/internal-v1` (20 campos)

Contrato UNICO de candidato (definido en `contracts.py`; el pipeline **no** crea
un segundo). Exactamente 20 campos de datos:

| # | campo | tipo | nota |
|---|-------|------|------|
| 1 | `subject_id` | str | no vacio |
| 2 | `subject_type` | str \| null | si se aporta, tipo valido |
| 3 | `predicate` | str | normalizado `MAYUSCULAS_CON_GUION_BAJO` |
| 4 | `object_id` | str | no vacio |
| 5 | `object_type` | str \| null | si se aporta, tipo valido |
| 6 | `direction` | enum | `SUBJECT_TO_OBJECT` \| `OBJECT_TO_SUBJECT` \| `UNDIRECTED` |
| 7 | `confidence` | float | en `[0,1]` |
| 8 | `evidence_text` | str | obligatorio salvo `extraction_method=ONTOLOGY` |
| 9 | `evidence_start` | int | `>= 0` |
| 10 | `evidence_end` | int | `>= 0` y `>= evidence_start` |
| 11 | `source_id` | str | procedencia obligatoria |
| 12 | `source_page` | int \| null | si se aporta, `>= 0` |
| 13 | `source_segment` | str | procedencia obligatoria |
| 14 | `extraction_method` | enum | `HEURISTIC` \| `LLM_LOCAL` \| `NVIDIA` \| `ONTOLOGY` |
| 15 | `model` | str \| null | `modelo@version` o null |
| 16 | `negated` | bool | bool explicito |
| 17 | `temporal_scope` | null \| obj | preservado tal cual |
| 18 | `epistemic_status` | enum | `ASSERTED` \| `RUMORED` \| `HYPOTHETICAL` \| `INTENDED` |
| 19 | `workspace` | str | obligatorio |
| 20 | `validation_flags` | list[str] | flags (el pipeline pone `["dry_run","heuristic"]`) |

Tipos de entidad permitidos (`ALLOWED_ENTITY_TYPES`, reutilizados de
`external_ai.models` cuando esta disponible): `Character, Location, Faction,
Object, Event, Concept`.

`validate()` verifica todas las reglas (enums validos, `subject != object` salvo
predicado reflexivo permitido —lista **vacia** por defecto—, predicado
normalizado, `confidence` en rango, offsets coherentes, evidencia presente,
procedencia minima). `from_dict`/`from_json` **rechazan** cualquier clave fuera
de los 20 campos (contrato cerrado). `is_affirmative()` es `True` solo si
`negated=False` y `epistemic_status=ASSERTED`.

### 3.2 Salida del pipeline

`run_pipeline` devuelve un dict JSON-serializable con:

- `schema` (`relation-pipeline/v1`), `execution_id`, `dry_run` (siempre `True`),
  `workspace`, `document_id`.
- `versions`: `{pipeline, contract, signals, syntax, consensus, prompts, template}`.
- `config`: la `PipelineConfig` efectiva (`to_dict`).
- `provider_status`: `{local_llm, external_ai}` ∈ `NOT_EXECUTED` / `EXECUTED` /
  `FAILED_CLOSED`.
- `summary`: contadores REALES (ver §5).
- `documents`: lista con `{document_id, workspace, segments:[...]}`; cada segmento
  lleva `pairs`, `signals`, `syntax`, `candidates`, `errors`, `truncated`,
  `pair_warnings`.
- `results`: lista ordenada de resultados por candidato: `{candidate_id,
  pair_id, candidate, consensus, local, local_status, external, external_status}`.
- `errors`: errores planos con `segment_id`.
- `observability`: traza redactada.
- `result_hash`: hash funcional determinista (excluye `observability`).

**Serializaciones** (`pipeline.py`): `to_json(output)` (JSON canonico completo) y
`to_jsonl(output)` (una linea de cabecera `type:execution` + una linea
`type:candidate` por resultado; orden estable).

---

## 4. Configuracion (`PipelineConfig`) y limites

`PipelineConfig` es un dataclass **frozen**. **No existe ninguna opcion de
escritura/apply/persistencia**: el dry-run no es un flag.

| parametro | defecto | proposito |
|---|---|---|
| `max_segments_per_doc` | 500 | anti-explosion (fatal si se supera) |
| `max_entities_per_segment` | 200 | anti-explosion por segmento |
| `max_pairs_per_segment` | 1000 | cota de pares (se propaga a `PairConfig`) |
| `max_text_chars` | 200000 | tamano max de texto por segmento |
| `max_prompt_chars` | 24000 | limite de prompt (proveedores sombra) |
| `max_response_bytes` | 65536 | limite de respuesta (proveedores sombra) |
| `max_time_per_candidate_ms` | 30000 | presupuesto por candidato |
| `max_errors_per_batch` | 1000 | superarlo aborta el lote (fatal) |
| `max_results` | 100000 | corte de resultados |
| `context_mode` | `"sentence"` | amplitud del emparejamiento (`sentence`/`paragraph`/`segment`/`distance`) |
| `pair_window` | `"char"` | unidad de distancia (`char`/`token`) |
| `max_distance` | `None` | distancia max adicional |
| `local_llm_enabled` | `False` | habilita LLM local (solo con inyeccion) |
| `external_ai_enabled` | `False` | habilita IA externa (solo con inyeccion) |
| `local_model` | `"local-llm"` | id de modelo local |
| `external_model` | `"external-model"` | id de modelo externo |
| `external_provider_name` | `"nvidia"` | nombre del proveedor externo |
| `prompt_suite` | `DEFAULT_SUITE` (`balanced`) | suite de prompts |

`config_from_dict(data)` construye la config rechazando **flags prohibidos**
(`write`, `apply`, `persist`, `commit`, `auto_approve`, `autoapprove`,
`dry_run`) con `PipelineError`, y tambien claves desconocidas.

---

## 5. Estructura de salida y contadores (`summary`)

Contadores REALES emitidos por el pipeline (no estimados):

- Volumen: `documents`, `segments`, `segments_processed`, `segments_failed`,
  `entities`, `pairs_potential`, `pairs_generated`, `pairs_discarded`,
  `candidates_evaluated`.
- Consenso: `results_strong`, `results_partial`, `results_conflict`,
  `results_invalid`, `results_human` (mapeo desde `consensus.state`).
- Proveedores: `local_calls_simulated`, `external_calls_simulated`,
  `provider_fail_closed`.
- Otros: `timeouts`, `errors`, `chars_processed`, `bytes_processed`.

`pairs_discarded = max(0, pairs_potential - pairs_generated)`.

---

## 6. Dry-run: por que es estructural

- No hay driver Neo4j, ni repositorio productivo, ni cliente de escritura
  importado en ninguna ruta del pipeline.
- No hay `apply` / `write` / `persist`: la config los **rechaza** si aparecen.
- `dry_run` es siempre `True` en la salida y **no** es configurable.
- Los proveedores sombra jamas escriben (ni Neo4j, ni disco, ni cache).
- **Import `APPLY` NO implementado**: no existe ninguna funcion que tome
  `results` y los ingiera al grafo.

---

## 7. Estados de consenso (reutilizados de `external_ai`)

El consenso **no crea una taxonomia paralela**: importa
`external_ai.models.CONSENSUS_STATES` (con un espejo documentado como fallback).
Los cinco estados canonicos:

| estado | significado |
|---|---|
| `STRONG_CONSENSUS` | dos proveedores presentes, misma polaridad, evidencia y estructura plenas |
| `PARTIAL_CONSENSUS` | corroboracion parcial (un solo proveedor, o coincidencia sin soporte pleno, o solo heuristicas fuertes) |
| `MODEL_CONFLICT` | polaridades opuestas o contradiccion (negacion/epistemico) |
| `INVALID_RESPONSES` | workspace mezclado, contrato invalido, evidencia inexistente, proveedor presente invalido |
| `HUMAN_REQUIRED` | tipos incompatibles, todos abstienen o soporte insuficiente |

La **recomendacion** ∈ `propose` / `reject` / `human`. **Nunca** aprueba,
escribe ni aplica (`AUTO_APPROVED`/`APPROVED`/`WRITE`/`APPLY` prohibidos por
guard). Reglas garantizadas: candidato inmutable (se opera sobre copia),
determinismo e independencia del orden de senales, "ausente != rechazo",
penaliza evidencia inexistente, invalida mezcla de workspaces, preserva
negacion/temporalidad/estado epistemico.

---

## 8. Errores: recuperables vs fatales, aislamiento por segmento

- **Fatales** (`PipelineError`, abortan la ejecucion): payload invalido,
  workspace/documento ausente, `segments` no es lista, exceso de
  `max_segments_per_doc`, exceso de `max_errors_per_batch`, config prohibida.
- **Fatales para un segmento** (no para el lote): texto no str, texto demasiado
  grande, **mezcla de workspace**, entidades no lista, exceso de entidades,
  error de generacion de pares. El segmento queda `status="failed"`; los demas
  siguen.
- **Recuperables por par** (no invalidan el segmento): error de senales
  (offsets fuera de rango), `evidence_span_empty` / `evidence_blank`,
  `contract_invalid`. El par se descarta y se registra el error; el segmento
  sigue `ok`/`partial`.
- **Ausencia/fallo de proveedor NO es rechazo**: se registra como
  `NOT_EXECUTED` / `FAILED_CLOSED`, nunca degrada la relacion a "negada".

Nunca se silencian excepciones: todo error queda en `errors` con codigo,
mensaje y ambito.

---

## 9. Observabilidad (traza redactada, sin backend)

`observability.RelationTrace` acumula `RelationEvent` en memoria por
`execution_id`. **Solo stdlib**, **sin red**, **sin backend obligatorio**: los
eventos se devuelven y se serializan; el consumidor decide donde escribirlos (el
pipeline no persiste la traza por si mismo).

- **Redaccion por defecto**: nunca se registran secretos, cabeceras
  `Authorization` ni texto privado completo. `redact()` sustituye patrones de
  credenciales (`nvapi-`, `sk-`, `ghp_`, `AKIA`, `Bearer`, PEM, `api_key=`...).
- **Sintetico vs privado**: `sample_text` solo se vuelca si `synthetic=True` o
  `include_private=True`; en evento privado se guarda solo hash y longitud.
- El `result_hash` funcional **excluye** la traza (y sus tiempos), de modo que la
  observabilidad no rompe el determinismo del resultado.

### Privacidad

El texto de documento nunca sale del proceso: los proveedores sombra reutilizan
`external_ai.security.assert_no_secrets` antes de cualquier envio, la traza esta
redactada, y no hay telemetria externa. La evidencia que se conserva es una cita
literal corta del propio segmento aportado.

---

## 10. Proveedores opcionales (fallo cerrado por defecto)

Ambos proveedores estan **DESHABILITADOS por defecto** y solo se activan con
inyeccion explicita de transporte/proveedor (destinada a tests/integracion, **no
disponible desde la CLI**):

- **LLM local** (`local_llm_shadow.py`): modo sombra obligatorio; sin endpoint
  ni transporte -> `ConfigError` **antes de abrir un socket**. Sin transporte
  con el proveedor habilitado -> el pipeline lo marca `FAILED_CLOSED`. Solo
  corre para predicados con plantilla (`KNOWN_PREDICATES`); para otros ->
  `SKIPPED`. **Ollama real: NOT_EXECUTED.**
- **IA externa NVIDIA NIM** (`external_ai_shadow.py`): envoltorio fino sobre
  `external_ai/**`; modo sombra obligatorio; API key solo por secreto de
  entorno, nunca guardada ni serializada; sin key/proveedor -> `FAILED_CLOSED`.
  Fallo aislado por candidato. **NVIDIA real: NOT_EXECUTED.**

`provider_status` en la salida refleja el estado real: por defecto ambos
`NOT_EXECUTED` (jamas se abre red).

---

## 11. Reproduccion y determinismo

- **IDs por contenido**: `execution_id` y `candidate_id` / `pair_id` son hashes
  SHA-256 de claves canonicas; **no** hay timestamps ni azar ni dependencia de
  `PYTHONHASHSEED`.
- **Orden estable**: segmentos y resultados se ordenan por claves canonicas; el
  orden de entrada no afecta a la salida.
- **`result_hash`**: mismo `payload` + `config` + `versions` -> mismo resultado
  byte a byte (excluyendo la traza de tiempos). El benchmark lo verifica
  ejecutando el pipeline `>= 2` veces (gate `determinism` DURO: **PASS**).

---

## 12. CLI (`python -m relations.cli`)

Envoltura fina y **no destructiva**: `--input` (JSON obligatorio), `--output`
(por defecto stdout), `--format json|jsonl`, y overrides de limites
(`--max-pairs-per-segment`, `--max-entities-per-segment`,
`--max-segments-per-doc`, `--max-text-chars`, `--context-mode`). **Los
proveedores sombra NO se activan desde la CLI** (no hay transporte real). Codigo
de salida: `0` si termina, `2` en error de uso/entrada. No toca la CLI global del
proyecto.

---

## 13. Benchmark (B2): metodo y resultados REALES

Resumen fiel de [`docs/50`](50-relation-benchmark-results.md); numeros sin
maquillar. El runner (`relations/benchmark/`) **importa y ejecuta R8 real**
sobre el corpus B1 real (`app/tests/data/relation_benchmark/`, 16 fuentes, 54
relaciones de ground truth) y compara contra el ground truth. Un `assert` en
import y el test `test_usa_pipeline_r8_real` garantizan que se usa el
`run_pipeline` real, no un espejo.

**Confirmacion de seguridad del benchmark**: Ollama `NOT_EXECUTED`, NVIDIA
`NOT_EXECUTED`, red ninguna, escritura/Neo4j ninguna (dry-run).

### Dictamen: **APTO CON REVISION HUMANA TOTAL**

> evidencia/offsets fiables pero el predicado heuristico es debil: toda relacion
> requiere revision humana antes de considerarse.

El vocabulario de dictamen **no** incluye "APTO PARA INGESTA REAL": el pipeline
es un propositor en sombra/dry-run, nunca aprueba ni escribe.

### Metricas globales (criterio de existencia, par no ordenado)

| Metrica | Precision | Recall | F1 |
|---|---|---|---|
| Existencia de relacion | 82.7% | 79.6% | **81.1%** |
| Estricta (par + predicado exacto) | 17.3% | 16.7% | 17.0% |

Es decir: **F1 de existencia ~81%**, pero el predicado exacto es **debil** (~17%).

### Gates (evaluados por separado)

| Gate | Estado | Valor | Umbral |
|---|---|---|---|
| `determinism` (DURO) | **PASS** | — | — |
| `workspace_contamination` (DURO) | **PASS** | — | — |
| `simple_relations` | **PASS** | 93.3% | 80% |
| `evidence` | **PASS** | 90.7% | 80% |
| `offsets` | **PASS** | 93.0% | 90% |
| `negation` | **PASS** | 100% | 80% |
| `temporality` | **FAIL** | 28.0% | 60% |
| `rumors` | **PARTIAL** | 50.0% | 60% |
| `predicate_structural` | **FAIL** | 20.9% | 50% |

Contadores operativos reales: 16 docs / 16 segmentos, 236 pares potenciales, 52
generados, 52 candidatos evaluados; consenso 0 strong / 19 partial / 13 conflict
/ 0 invalid / 20 human (tasa humana 38.5%, tasa conflicto 25.0%). Determinismo
verificado (hashes/metricas/predicciones iguales en 2 ejecuciones).

---

## 14. Riesgos y limitaciones (honestos)

- **Predicado exacto BAJO** (`predicate_structural` FAIL, ~21% sobre TP): el
  propositor acierta *que hay relacion* y su evidencia/offsets, pero se equivoca
  a menudo en *que predicado* es (muchos caen en el generico `RELATED_TO`). Toda
  relacion requiere revision humana del predicado.
- **Temporalidad FAIL** (28% vs 60%): la deteccion temporal *coarse* no alcanza
  el umbral; `temporal_scope` es texto libre y no siempre se dispara cuando el
  ground truth marca estado temporal.
- **Rumores PARTIAL** (50% vs 60%): el estado epistemico de rumores se detecta a
  medias.
- **Falsos negativos estructurales asumidos**: sujetos elididos / correferencia
  (pronombres), relaciones reflexivas de alias (`subject==object`, excluidas por
  el generador de pares) y multiples relaciones para el mismo par en la misma
  fuente (R8 deduplica a un candidato) producen FN reales, reportados sin
  maquillar.
- El proveedor sintactico es el heuristico stdlib (sin lema/POS abierto; spaCy /
  Stanza quedan como placeholder `NOT_EXECUTED`, sin tocar `requirements`).

---

## 15. Operaciones PROHIBIDAS

Este pipeline, por diseno, **no** hace y **no debe** hacer:

- Escribir en Neo4j o en cualquier base de datos productiva.
- Aprobar / ingerir relaciones automaticamente (no hay ruta `APPLY`).
- Abrir red por defecto (proveedores deshabilitados; con habilitacion sin via
  legitima -> fallo cerrado).
- Ejecutar Ollama o NVIDIA reales sin autorizacion explicita e inyeccion.
- Ejecutar OCR / extraccion multimedia (consume texto ya extraido).
- Aceptar flags de escritura en la config (`write`/`apply`/`persist`/... ->
  `PipelineError`).
- Tocar la RC5.1 de produccion (VM105) ni el grafo Neo4j de produccion.

Cualquier promocion hacia ingesta real es una decision **gateada y humana**,
fuera de este pipeline y fuera del alcance de este documento.

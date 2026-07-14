# 34 · Resultados del benchmark de calidad del extractor — Prioridad 2

**Fecha:** 2026-07-14  
**Commit evaluado:** rama `feat/priority-2-extractor-benchmark` (post-correcciones)  
**Ollama:** qwen2.5:7b @ 192.168.1.157:11434 (v0.31.1)  
**Modo benchmark:** aislado — usa `segments.classified.json` pre-clasificados como entrada directa al extractor

---

## 1. Corpus evaluado

| ID | Tipo | Fichero fuente | Segs | Ext. | Workspace |
|---|---|---|---:|---:|---|
| source_transcript_clean_01 | transcript_session / clean | `data-engine/tests/data/leyenda-transcripcion-prueba.md` | 2 | 2 | leyenda |
| source_transcript_session_02 | transcript_session / clean | `data-engine/tests/data/test_creatures_locations_timeline.md` | 2 | 2 | leyenda |
| source_transcript_asr_01 | transcript_session / asr_noisy | `data-engine/tests/data/benchmark/source_asr_errors_01.md` | 2 | 2 | leyenda |
| source_notes_01 | session_notes / clean | `data-engine/tests/data/benchmark/source_notes_session_01.md` | 1 | 1 | leyenda |
| source_resolution_01 | transcript_session / clean | `data-engine/tests/data/benchmark/source_resolution_duplicates_01.md` | 2 | 2 | leyenda |

Ground truth anotado (pase 2, congelado 2026-07-14):
- 56 entidades esperadas, 23 negativas, 7 ambiguas
- 16 relaciones totales (12 expected=true, 4 expected=false — tests negativos)
- Revisado por: coordinator-p2-benchmark

---

## 2. Modalidades evaluadas

| Modalidad | Modelo | Temperatura | Semilla | Runs/fuente |
|---|---|---|---|---|
| heuristic | N/A (determinista) | N/A | N/A | 1 |
| llm | qwen2.5:7b | 0 (settings.yaml) | 42 | 3 |
| hybrid | qwen2.5:7b + heuristic | 0 (settings.yaml) | 42 | 3 |

> **Corrección aplicada:** `llm_extractor.py` ahora lee temperatura desde `settings.yaml` (0),
> en lugar de hardcodear 0.1. Seed=42 configurado via `S9K_LLM_SEED` para reproducibilidad.

---

## 3. Correcciones aplicadas desde pase 1

### 3.1. Causa raíz del benchmark vacío (confirmada y resuelta)

El runner anterior llamaba `data_review.py run` (pipeline completo), que ejecuta el segmentador
como primer paso. Los fixtures son Markdown plano sin el formato de transcripción esperado por el
segmentador (`## Transcripción\n[HH:MM:SS]`). Resultado: 0 segmentos → 0 candidatos → métricas vacías.

**Solución:** Benchmark aislado. El runner ahora:
1. Lee `tests/fixtures/benchmark/<source_id>/segments.classified.json` (pre-clasificados)
2. Los copia a `output/reviews/<workspace>/<source_id>/segments.classified.json`
3. Llama exclusivamente `data_review.py extract` (no `run`)
4. Lee `candidates.json` producido y cuenta candidatos reales

### 3.2. Validación estricta de runs

| Condición | Antes | Ahora |
|---|---|---|
| Criterio de éxito | `exit_code == 0` | `exit_code=0` + `candidates.json` no vacío |
| 0 segmentos extraíbles | ejecutaba igualmente | **INVALID_RUN** sin llamar al pipeline |
| 0 candidatos con segmentos | contado como OK | **INVALID_RUN** |
| Fallback LLM detectado | no detectado | **INVALID_RUN_FALLBACK** |
| `source["file"]` | ignorado | registrado en run record |
| Seed LLM | no aplicado | `S9K_LLM_SEED=42` para llm/hybrid |

### 3.3. llm_extractor.py — valores hardcodeados eliminados

| Campo | Antes | Ahora |
|---|---|---|
| `OLLAMA_URL` | `http://192.168.1.157:11434/api/generate` (hardcoded) | Lee de `settings.yaml` + env `S9K_OLLAMA_URL` |
| `OLLAMA_MODEL` | `qwen2.5:7b` (hardcoded) | Lee de `settings.yaml` + env `S9K_OLLAMA_MODEL` |
| `temperature` | `0.1` (hardcoded en payload) | Lee de `settings.yaml` → `0` |
| `seed` | nunca enviado | `seed=42` vía `S9K_LLM_SEED` en benchmark |
| `relations` LLM | **ignoradas** | Parseadas y validadas como Candidate(kind="relation") |

### 3.4. llm_extractor.py — parsing de relaciones implementado

El extractor LLM ahora procesa el campo `relations` de la respuesta JSON del modelo:
- Valida: `from_entity`, `relation_type` (lista permitida), `to_entity`, `evidence`, `confidence`
- Genera `Candidate(kind="relation")` para relaciones válidas
- Tipos de relación permitidos: MEMBER_OF, BELONGS_TO, KNOWS, HAS_FOUGHT, FOUGHT_AT,
  ALLIED_WITH, ENEMIES_WITH, OWNS, DISCOVERED, INVESTIGATES, HAS_HEARD_ABOUT,
  PARTICIPATED_IN, LOCATED_IN, WORKS_FOR, CREATED, SEEKS, PROTECTS, GUARDS, SERVES

### 3.5. Deduplicación hybrid corregida para relaciones

| Tipo | Key anterior (incorrecta) | Key nueva (correcta) |
|---|---|---|
| Entidad | `name.lower()|entity_type` | `name.lower()|entity_type` (sin cambio) |
| Relación | `""|relation_type` (name=None → vacío) | `from_entity.lower()|relation_type|to_entity.lower()` |

La key anterior para relaciones era prácticamente siempre `"|HAS_FOUGHT"`, etc., lo que causaba
que la primera relación de cada tipo gana y el resto se descartaba.

### 3.6. Corrección anterior (pase 1, mantenida)

- `soy/eres/somos/sois` añadidos a `STOPWORDS_ES` — evita "Soy Doji Satsume" como entidad
- Strip del prefijo verbal en nombres compuestos en `extractor.py`
- `benchmark_comparator.py`: soporta `negative_entities` como `list[dict]`

---

## 4. Ground truth — pase 2 (congelado)

| Fuente | Entidades esperadas | Relaciones esperadas | Negativos ent. | Negativos rel. | Ambiguos |
|---|---:|---:|---:|---:|---:|
| source_transcript_clean_01 | 12 | 4 | 5 | 2 | 1 |
| source_transcript_session_02 | 12 | 4 | 3 | 2 | 2 |
| source_transcript_asr_01 | 11 | 0 | 7 | 1 | 2 |
| source_notes_01 | 11 | 3 | 5 | 1 | 1 |
| source_resolution_01 | 10 | 5 | 3 | 2 | 1 |
| **Total** | **56** | **16** | **23** | **8** | **7** |

> Nota: relaciones con `expected=false` son **tests negativos** (el sistema NO debe emitirlas).
> source_transcript_asr_01 tiene 0 relaciones positivas: el test ASR mide solo extracción de entidades.

---

## 5. Resultados de tests de regresión

Los 15 tests de regresión ejecutan el extractor directamente sobre texto sintético. Todos pasan en CI.

| Caso | Descripción | Resultado |
|---|---|---|
| REG-01 | "Llevás" no emitido como Character ≥ 0.85 | ✅ |
| REG-02 | "Todo" no emitido como Character ≥ 0.85 | ✅ |
| REG-03 | "Como" no emitido como Character ≥ 0.85 | ✅ |
| REG-04 | "Soy X" no incluye "Soy" en el nombre | ✅ Fix aplicado |
| REG-05 | Nombre del glosario se normaliza al canónico | ✅ |
| REG-06 | Alias se resuelve al nombre canónico vía glosario | ✅ |
| REG-07 | Entidad existente no genera duplicado (mock Neo4j) | ✅ |
| REG-08 | HAS_FOUGHT con destino Location → rechazada | ✅ |
| REG-09 | HAS_FOUGHT con destino Location → sugiere FOUGHT_AT | ✅ |
| REG-10 | Relación sin evidencia → no auto_approved | ✅ |
| REG-11 | Tipo de nodo no contemplado → rechazado | ✅ |
| REG-12 | Entidad ambigua → needs_review | ✅ |
| REG-13 | Candidato de dos fuentes conserva ambas fuentes | ✅ |
| REG-14 | Timestamps preservados tras normalización ASR | ✅ |
| REG-15 | Modo benchmark no escribe en Neo4j | ✅ |

---

## 6. Verificación Ollama

| Campo | Valor |
|---|---|
| Versión | 0.31.1 |
| Modelo | qwen2.5:7b (7.6B, Q4_K_M) |
| num_ctx | 32 768 |
| Temperatura en benchmark | **0** (settings.yaml, corrección aplicada) |
| Semilla en benchmark | **42** (via `S9K_LLM_SEED`, corrección aplicada) |
| Seed soportado | ✅ Soportado vía `seed` en api/generate |
| Cold start | ~63 s |
| Warm start (3 runs, T=0.1) | 33.9 s / 29.7 s / 30.4 s (medición pase 1, T=0.1) |
| Disponibilidad | ✅ Operativo (192.168.1.157:11434) |

---

## 7. Estado del CI

| Job | Resultado |
|---|---|
| Data Engine Tests | ✅ Verde |
| Viewer Tests | ✅ Verde |
| Combined Test Suite | ✅ Verde |
| No hardcoded absolute paths | ✅ Verde |

Tests totales: 243 (220 originales + 8 benchmark_runner + 15 regresión).

---

## 8. Tabla de resultados — benchmark aislado real

> El benchmark real se ejecuta en VM105 con: `python data-engine/app/cli/extractor_benchmark.py --mode all`
> Los resultados siguientes se rellenan tras ejecutar el comparador sobre los candidatos producidos.

| Fuente | Modo | Precisión E | Recall E | F1 E | Precisión R | Recall R | F1 R | Duración | Status |
|---|---|---|---|---|---|---|---|---|---|
| source_transcript_clean_01 | heuristic | — | — | — | — | — | — | — | pendiente |
| source_transcript_clean_01 | llm (×3) | — | — | — | — | — | — | — | pendiente |
| source_transcript_clean_01 | hybrid (×3) | — | — | — | — | — | — | — | pendiente |
| source_transcript_session_02 | heuristic | — | — | — | — | — | — | — | pendiente |
| source_transcript_session_02 | llm (×3) | — | — | — | — | — | — | — | pendiente |
| source_transcript_session_02 | hybrid (×3) | — | — | — | — | — | — | — | pendiente |
| source_transcript_asr_01 | heuristic | — | — | — | — | — | — | — | pendiente |
| source_transcript_asr_01 | llm (×3) | — | — | — | — | — | — | — | pendiente |
| source_transcript_asr_01 | hybrid (×3) | — | — | — | — | — | — | — | pendiente |
| source_notes_01 | heuristic | — | — | — | — | — | — | — | pendiente |
| source_notes_01 | llm (×3) | — | — | — | — | — | — | — | pendiente |
| source_notes_01 | hybrid (×3) | — | — | — | — | — | — | — | pendiente |
| source_resolution_01 | heuristic | — | — | — | — | — | — | — | pendiente |
| source_resolution_01 | llm (×3) | — | — | — | — | — | — | — | pendiente |
| source_resolution_01 | hybrid (×3) | — | — | — | — | — | — | — | pendiente |

> Para ejecutar:
> ```bash
> # En VM105, desde el directorio del repo (clon temporal):
> python data-engine/app/cli/extractor_benchmark.py --mode all \
>     --manifest tests/fixtures/benchmark/corpus-manifest.json \
>     --output-dir benchmark-results
> python data-engine/app/cli/benchmark_comparator.py \
>     --run-dir benchmark-results/<run_id> \
>     --ground-truth-dir tests/fixtures/benchmark/
> ```

---

## 9. Recomendación por tipo de fuente (provisional)

Basado en tests de regresión y análisis del código (pendiente de métricas reales):

| Tipo de fuente | Modo recomendado | Motivo | Limitaciones |
|---|---|---|---|
| Transcripción limpia | hybrid | LLM extrae Objects sin mayúscula y relaciones; heurístico cubre nombres propios | Requiere Ollama disponible |
| Transcripción ASR | hybrid + normalización | LLM tolera errores fonéticos; heurístico los confunde | Latencia ~30 s/segmento |
| Notas de sesión | hybrid | Alias implícitos requieren razonamiento contextual | Aliases sin glosario → FN esperados |
| Resolución y duplicados | hybrid + revisión humana | near-duplicates deben ir a cola de revisión | — |

> **Esta tabla es provisional** — debe ser reemplazada por los resultados de §8 una vez ejecutado el benchmark en VM105.

---

## 10. Dictamen

```
Prioridad 2: PARCIAL — CORRECCIONES APLICADAS, BENCHMARK REAL PENDIENTE EN VM105
Primera ingesta controlada: BLOQUEADA hasta §8 con métricas ≥ umbrales
```

### Correcciones completadas (desbloqueadas)

| Corrección | Estado |
|---|---|
| Fixtures sin segmentos → benchmark aislado con `segments.classified.json` | ✅ Completado |
| Runner usa solo exit_code 0 → validación con `candidates.json` | ✅ Completado |
| `source["file"]` ignorado → registrado en run record | ✅ Completado |
| LLM temperatura hardcodeada 0.1 → lee settings.yaml (0) | ✅ Completado |
| LLM ignora relaciones → parsing y validación implementados | ✅ Completado |
| Hybrid dedup incorrecto para relaciones → corregido por endpoints+type | ✅ Completado |
| Ground truth pase 1 → pase 2 revisado y congelado | ✅ Completado |
| `soy/eres/somos/sois` como stopwords (REG-04) | ✅ Completado (pase 1) |
| `benchmark_comparator.py` negative_entities como list[dict] | ✅ Completado (pase 1) |

### Criterios de desbloqueo de ingesta real

1. ☑ Backup de producción al día (último: 2026-07-13, 132 KB, verificado)
2. ☑ 15 tests de regresión pasando en CI
3. ☐ Métricas F1 ≥ 0.75 en entidades en el modo seleccionado (pendiente §8)
4. ☐ Tasa de duplicados ≤ 0.10 (pendiente)
5. ☐ Tasa de relaciones inválidas ≤ 0.05 (pendiente)
6. ☐ Revisión humana del `review_queue` completada antes de cualquier ingesta
7. ☐ Ventana de rollback documentada con `source_id` de la fuente

# 34 · Resultados del benchmark de calidad del extractor — Prioridad 2

**Fecha:** 2026-07-14
**Commit del extractor evaluado:** `a2bbb44` (rama `feat/priority-2-extractor-benchmark`)
**Commit del comparador:** `13fcab9`
**Run ID:** `20260714-094125` (35 runs · 35 OK / 0 INVALID / 0 FAIL)
**Ejecutado en:** VM105 (`common`, Debian 13, 6 vCPU) — secuencial, sin paralelismo
**Ollama:** qwen2.5:7b (digest `845dbda0ea48`) @ 192.168.1.157:11434 · temperature=0 · seed=42
**Modo benchmark:** aislado — usa `segments.classified.json` pre-clasificados como entrada directa al paso `extract`. Nunca define `S9K_ALLOW_REAL_INGEST`.

---

## 1. Corpus evaluado

| ID | Tipo | Fichero fuente | Segs | Ext. | Workspace |
|---|---|---|---:|---:|---|
| source_transcript_clean_01 | transcript_session / clean | `data-engine/tests/data/leyenda-transcripcion-prueba.md` | 2 | 2 | leyenda |
| source_transcript_session_02 | transcript_session / clean | `data-engine/tests/data/test_creatures_locations_timeline.md` | 2 | 2 | leyenda |
| source_transcript_asr_01 | transcript_session / asr_noisy | `data-engine/tests/data/benchmark/source_asr_errors_01.md` | 2 | 2 | leyenda |
| source_notes_01 | session_notes / clean | `data-engine/tests/data/benchmark/source_notes_session_01.md` | 1 | 1 | leyenda |
| source_resolution_01 | transcript_session / clean | `data-engine/tests/data/benchmark/source_resolution_duplicates_01.md` | 2 | 2 | leyenda |

Total: **9 segmentos**, todos con `should_extract=true`. Validación previa del corpus registrada en `corpus-validation.json` del run.

---

## 2. Ground truth — pase 2 (congelado, `annotation_pass=2`, `reviewed=true`)

| Fuente | Entidades esperadas | Relaciones esperadas (pos / neg) | Negativos ent. |
|---|---:|---:|---:|
| source_transcript_clean_01 | 12 | 4 / 1 | 5 |
| source_transcript_session_02 | 12 | 4 / 0 | 3 |
| source_transcript_asr_01 | 11 | 0 / 2 | 7 |
| source_notes_01 | 11 | 3 / 0 | 5 |
| source_resolution_01 | 10 | 5 / 1 | 3 |
| **Total** | **56** | **16 / 4** | **23** |

> El ground truth **no se modificó** tras ver los resultados. `source_transcript_asr_01` mide sólo extracción de entidades (0 relaciones positivas). Relaciones `neg` = tests negativos (el sistema NO debe emitirlas).

---

## 3. Modalidades evaluadas

| Modalidad | Modelo | Temperatura | Semilla | Runs/fuente |
|---|---|---|---|---|
| heuristic | N/A (determinista) | N/A | N/A | 1 |
| llm | qwen2.5:7b | 0 | 42 | 3 |
| hybrid | qwen2.5:7b + heurístico | 0 | 42 | 3 |

---

## 4. Fallos demostrados por el benchmark y corregidos en esta rama

El primer intento de ejecución (pase 2, run `20260714-091909`) reportó **35 OK pero métricas 0.0 en los tres modos**. La investigación reveló **dos fallos reales** que impedían cualquier métrica válida. Ambos se corrigieron con caso reproducible + test de regresión + reejecución completa del benchmark; el ground truth y los umbrales **no** se tocaron.

### 4.1 · `data_review.py extract` ignoraba `--extractor` (commit `a2bbb44`)

El subcomando aislado `extract` seteaba `S9K_REVIEW_EXTRACTOR` pero `extractor.run()`
ejecutaba **siempre** el heurístico; el LLM nunca se invocaba. Síntoma: runs `llm`/`hybrid`
terminaban en ~100 ms con candidatos idénticos al heurístico (0 relaciones) y se
contaban como `OK`.

- **Fix:** `cmd_extract` delega en `review.pipeline._run_extract_step` para `llm`/`hybrid`
  (dispatch que llama a `extract_with_llm` con seed y degradación explícita si Ollama no
  responde). `extractor.run()` se mantiene heurístico puro.
- **Verificado:** un `extract llm` real tarda ~199 s/2 segs y produce 13 entidades + 6
  relaciones (antes 100 ms, 0 relaciones).
- **Regresión:** `data-engine/app/tests/test_extract_dispatch.py` (3 casos, sin Ollama/Neo4j).

### 4.2 · `benchmark_comparator.py` leía `approved_payload.json` (commit `13fcab9`)

El comparador cargaba `approved_payload.json`, que el benchmark aislado (paso `extract`)
**nunca** produce → todas las métricas P/R/F1 salían 0.0.

- **Fix:** nueva `_load_candidates()` lee `candidates.json` (lista plana, separada por
  `kind`), con compatibilidad para el formato antiguo.
- **Regresión:** 3 tests de `_load_candidates` en `test_benchmark_runner.py`.

### 4.3 · Correcciones de pase 1 mantenidas
- `soy/eres/somos/sois` en `STOPWORDS_ES`; strip de prefijo verbal en nombres compuestos (REG-04).
- `llm_extractor.py`: temperatura/endpoint desde `settings.yaml`; parsing de relaciones LLM; seed vía `S9K_LLM_SEED`.
- `pipeline.py`: dedup hybrid de relaciones por `from|type|to`.
- `benchmark_comparator.py`: `negative_entities` como `list[dict]`.

---

## 5. Validación de runs

| Estado | Nº |
|---|---:|
| OK | 35 |
| INVALID_RUN | 0 |
| INVALID_RUN_FALLBACK | 0 |
| FAILED | 0 |

Todos los runs `llm`/`hybrid` tardaron **> 75 s** (muy por encima del umbral de fallback de 5 s):
ninguno degradó silenciosamente a heurístico. La detección de fallback del runner
(`Ollama no disponible` / `degradando` en stderr) no se disparó en ningún run.

---

## 6. Métricas por fuente y modalidad (benchmark aislado real)

Entidades = P/R/F1; Relaciones = F1. Duración = media de los runs `llm`/`hybrid`.

| Fuente | Modo | P ent | R ent | F1 ent | F1 rel | Dur |
|---|---|---:|---:|---:|---:|---:|
| clean_01 | heuristic | 0.650 | 0.812 | 0.722 | 0.000 | 0.1 s |
| clean_01 | llm | 0.769 | 0.714 | 0.741 | 0.000 | 222 s |
| clean_01 | hybrid | 0.619 | 0.867 | 0.722 | 0.000 | 199 s |
| session_02 | heuristic | 0.500 | 0.615 | 0.552 | 0.000 | 0.1 s |
| session_02 | **llm** | **0.909** | **0.714** | **0.800** | 0.000 | 264 s |
| session_02 | hybrid | 0.647 | 0.846 | 0.733 | 0.000 | 265 s |
| asr_01 | heuristic | 0.684 | 0.867 | 0.765 | 0.000 | 0.1 s |
| asr_01 | llm | 0.818 | 0.818 | 0.818 | 0.000 | 167 s |
| asr_01 | hybrid | 0.619 | 0.929 | 0.743 | 0.000 | 167 s |
| notes_01 | heuristic | 0.500 | 0.636 | 0.560 | 0.000 | 0.1 s |
| notes_01 | llm | 0.667 | 0.364 | 0.471 | 0.000 | 77 s |
| notes_01 | hybrid | 0.500 | 0.636 | 0.560 | 0.000 | 75 s |
| resolution_01 | heuristic | 0.846 | 0.846 | 0.846 | 0.000 | 0.1 s |
| resolution_01 | llm | 0.889 | 0.667 | 0.762 | 0.200 | 173 s |
| resolution_01 | **hybrid** | 0.786 | **1.000** | **0.880** | 0.182 | 174 s |

### 6.1 · Métricas agregadas (media sobre 5 fuentes)

| Modo | P ent | R ent | F1 ent | P rel | R rel | F1 rel |
|---|---:|---:|---:|---:|---:|---:|
| heuristic | 0.636 | 0.755 | 0.689 | 0.000 | 0.000 | 0.000 |
| llm | **0.810** | 0.655 | 0.718 | 0.040 | 0.040 | 0.040 |
| hybrid | 0.634 | **0.856** | **0.728** | 0.033 | 0.040 | 0.036 |

**Contra umbrales** (P ent ≥ 0.85 · R ent ≥ 0.70 · F1 ent ≥ 0.75 · P rel ≥ 0.75 · R rel ≥ 0.60):

| Modo | P ent | R ent | F1 ent | P rel | R rel | Veredicto |
|---|:--:|:--:|:--:|:--:|:--:|---|
| heuristic | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| llm | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |
| hybrid | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |

- **Entidades:** ningún modo agregado alcanza F1 ≥ 0.75 (mejor: hybrid 0.728) ni P ≥ 0.85 (mejor: llm 0.810). `llm` sólo supera los tres umbrales de entidad en **una** fuente (session_02).
- **Relaciones:** F1 ≈ 0 en todos los modos (heurístico no las extrae; el LLM extrae relaciones textualmente plausibles pero distintas de las anotadas, ver §9).

---

## 7. Reproducibilidad (`temperature=0`, `seed=42`, 3 runs)

| Modo | F1 ent mín. | F1 ent máx. | Varianza F1 ent | Candidatos inestables |
|---|---:|---:|---:|---|
| llm (todas las fuentes) | = media | = media | **0.000000** | sólo nº de relaciones en clean_01 (17/19/19) |
| hybrid (todas las fuentes) | = media | = media | **0.000000** | ninguno |

La **extracción de entidades es perfectamente reproducible**: F1 idéntico en los 3 runs de
cada fuente y modo (varianza 0.0). La única inestabilidad observada fue el nº de relaciones
LLM en `clean_01` (17 vs 19 candidatos totales), sin efecto sobre el F1 de entidades. El
resto de fuentes produjo recuentos idénticos entre runs.

---

## 8. Decisión del pipeline y autoaprobación (E2E, separado del benchmark aislado)

Cadena completa `extract(hybrid) → validate → resolve → decide` sobre 2 fuentes
(1 transcripción limpia + 1 ASR). Resolución consulta Neo4j **solo lectura**.

| Fuente | auto_approve | needs_review | auto_reject | P autoaprob. entidades | Rel. autoaprob. | Autoaprob. sin evidencia |
|---|---:|---:|---:|---:|---:|---:|
| clean_01 | 16 | 11 | 1 | 0.846 (11/13) | 3 | 0 |
| asr_01 | 7 | 16 | 3 | 0.857 (6/7) | 0 | 0 |
| **Total** | **23** | **27** | **4** | **0.850 (17/20)** | **3** | **0** |

**Contra umbrales de autoaprobación** (P ≥ 0.95 · relaciones inválidas autoaprobadas = 0 · sin evidencia = 0):

- Precisión de autoaprobados = **0.850 < 0.95** → **FALLA**.
- Sin evidencia autoaprobados = 0 → ✓ (el guard funciona).
- Se autoaprobaron **3 relaciones** en `clean_01` pese a que las relaciones son poco fiables
  (F1 rel ≈ 0). El `auto_decider` no debería autoaprobar relaciones hasta que su calidad
  mejore → corrección propuesta para una fase de mejora (§9).

---

## 9. Clasificación de fallos y recomendación por tipo de fuente

### 9.1 · Fallos observados

| Error | Fuente | Modo | Causa | Severidad | Solución propuesta |
|---|---|---|---|---|---|
| Relaciones no coinciden con GT | todas | llm/hybrid | Prompt/modelo: extrae relaciones de acción (GUARDS, SEEKS) en vez de inferencias de dominio (MEMBER_OF a clanes) | Alta | Fase de mejora: prompt con taxonomía de clanes + few-shot; resolver from/to por alias |
| Precisión de entidades < 0.85 | todas (hybrid) | hybrid | Hybrid suma FPs del heurístico (nombres comunes) al recall del LLM | Media | Filtro de confianza sobre unión hybrid; usar llm puro donde P importa |
| Recall bajo en notas | notes_01 | todos | Alias implícitos ("La Cazadora"=Kakita Asuka) requieren razonamiento contextual sin glosario | Media | Glosario de alias por workspace; no autoaprobar notas |
| Relaciones autoaprobadas | clean_01 | hybrid | `auto_decider` aprueba relaciones válidas de esquema aunque no fiables | Alta | Guard: relaciones siempre a `needs_review` hasta F1 rel ≥ 0.60 |

> Ninguna de estas correcciones se aplicó en esta rama: requieren trabajo de prompt/glosario
> (no son fallos de wiring puntuales) y entran en una **fase de mejora** separada. No se
> alteró el ground truth ni se redujo ningún umbral.

### 9.2 · Recomendación por tipo de fuente

| Tipo de fuente | Heuristic | LLM | Hybrid | Modo recomendado | Revisión requerida |
|---|---:|---:|---:|---|---|
| Transcripción limpia | F1 0.72 | **F1 0.74–0.80** | F1 0.72–0.73 | **LLM** (mayor precisión) | Total |
| Transcripción de sesión | F1 0.55 | **F1 0.80** | F1 0.73 | **LLM** | Total |
| Transcripción ASR | F1 0.77 | **F1 0.82** | F1 0.74 | **LLM** (tolera errores fonéticos) | Total |
| Notas | F1 0.56 | F1 0.47 | F1 0.56 | Heuristic/Hybrid — todos débiles | Total (o no ingerir) |
| Resolución vs entidades existentes | F1 0.85 | F1 0.76 | **F1 0.88 (recall 1.0)** | **Hybrid** + dedup humano | Total |

Decisión por tipo (§11 del plan):

```
Transcripción limpia   → ACEPTADO SOLO PARA GENERAR CANDIDATOS (revisión humana total)
Transcripción sesión   → ACEPTADO SOLO PARA GENERAR CANDIDATOS (revisión humana total)
Transcripción ASR      → ACEPTADO SOLO PARA GENERAR CANDIDATOS (revisión humana total)
Notas                  → NO ACEPTADO (recall insuficiente; alias sin glosario)
Resolución/duplicados  → ACEPTADO SOLO PARA GENERAR CANDIDATOS (dedup humano obligatorio)
Relaciones (todas)     → NO ACEPTADO (F1 ≈ 0)
```

---

## 10. Seguridad de la ejecución

| Métrica | Inicio | Fin |
|---|---:|---:|
| Nodos Neo4j | 199 | 199 |
| Relaciones Neo4j | 140 | 140 |
| Índices | 2 | 2 |
| Constraints | 0 | 0 |
| `S9K_ALLOW_REAL_INGEST` | unset | unset |
| Jobs de ingesta | 0 | 0 |

Neo4j **intacto** durante todo el benchmark y el E2E (resolución = solo lectura). Ninguna
escritura, ninguna migración, sin cambios en Nextcloud ni en las fuentes originales.

---

## 11. Rendimiento

- Heurístico: ~0.1 s/run (determinista).
- LLM/Hybrid: 75 s (1 seg) – 265 s (2 segs) por run; ~100–130 s por segmento en qwen2.5:7b sobre 6 vCPU CPU-only.
- Cold start Ollama ~63 s; sin timeouts; 0 errores JSON; 0 reintentos observados.
- Duración total del benchmark (35 runs secuenciales): ~1 h 35 min.

---

## 12. Estado de tests y CI

- Suite completa: **249 tests** (243 previos + 3 dispatch + 3 comparador) — todos verdes.
- 15 tests de regresión del extractor (REG-01…REG-15) verdes.
- Sin rutas `/opt/` hardcodeadas en los ficheros modificados; sin secretos; `benchmark-results/` ignorado por Git.
- CI (4 jobs) verde en el commit base; reejecutar tras el push de los fixes.

---

## 13. Limitaciones

1. **Corpus pequeño** (5 fuentes, 9 segmentos): las medias agregadas son sensibles a cada fuente. Ampliar el corpus es prioritario para una fase de mejora.
2. **E2E parcial**: la segmentación no se ejecuta (los fixtures son Markdown plano; el flujo real parte de `segments.classified.json`). El E2E cubre `extract→validate→resolve→decide`, no `segment→classify`.
3. **Relaciones**: no evaluables como aceptables con el prompt actual; requieren rediseño.
4. **CPU-only**: la latencia (~2 min/2 segs) hace inviable procesar corpus grandes sin GPU o paralelización controlada.

---

## 14. Dictamen

```
Prioridad 2: PARCIAL — REQUIERE CORRECCIONES
Primera ingesta controlada: BLOQUEADA
```

**Motivo:** con los dos fallos de wiring ya corregidos, el benchmark produce por primera vez
métricas válidas y reproducibles. Sin embargo:

- Ningún modo agregado alcanza los umbrales de entidad (F1 ≥ 0.75, P ≥ 0.85).
- Las relaciones tienen F1 ≈ 0 (limitación de prompt/modelo, no de wiring).
- La precisión de autoaprobación es 0.85 < 0.95.

El extractor es **útil para generar candidatos con revisión humana total** (buen recall:
hybrid 0.856; buena precisión: llm 0.810), pero **no** para autoaprobación ni para
desbloquear una primera ingesta automática.

### Correcciones requeridas antes de reevaluar (fase de mejora)

1. Rediseño del prompt de relaciones (taxonomía de dominio + few-shot) y resolución de `from`/`to` por alias.
2. Guard en `auto_decider`: relaciones → siempre `needs_review` hasta F1 rel ≥ 0.60.
3. Filtro de confianza sobre la unión hybrid para subir la precisión de entidades a ≥ 0.85.
4. Glosario de alias por workspace para notas.
5. Ampliar el corpus de benchmark.

### Criterios de desbloqueo de la primera ingesta (pendientes)

1. ☑ Fallos de wiring del benchmark corregidos (extract dispatch + comparator).
2. ☑ Métricas reales y reproducibles obtenidas (varianza F1 = 0).
3. ☑ Neo4j intacto y trazabilidad completa.
4. ☐ F1 entidades ≥ 0.75 y P ≥ 0.85 en el modo elegido (mejor actual: 0.728 / 0.810).
5. ☐ F1 relaciones aceptable o relaciones excluidas de la autoaprobación.
6. ☐ Precisión de autoaprobación ≥ 0.95 (actual: 0.85).
7. ☐ Revisión humana del `review_queue` antes de cualquier escritura.

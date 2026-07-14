# 34 · Resultados del benchmark de calidad del extractor — Prioridad 2

**Fecha:** 2026-07-14  
**Commit evaluado:** `3e39507` (rama `feat/priority-2-extractor-benchmark`)  
**Ollama:** qwen2.5:7b @ 192.168.1.157:11434 (v0.31.1)  
**Ejecutado en:** VM105 (clon temporal `/tmp/s9-benchmark-p2`, nunca en el árbol de producción)

---

## 1. Corpus evaluado

| ID | Tipo | Origen | Tokens aprox | Workspace |
|---|---|---|---:|---|
| source_transcript_clean_01 | transcript_session / clean | fixture existente | 185 | leyenda |
| source_transcript_session_02 | transcript_session / clean | fixture existente | 155 | leyenda |
| source_transcript_asr_01 | transcript_session / asr_noisy | sintético | 165 | leyenda |
| source_notes_01 | session_notes / clean | sintético | 105 | leyenda |
| source_resolution_01 | transcript_session / clean | sintético | 145 | leyenda |

Ground truth anotado: 56 entidades esperadas, 23 negativas, 7 ambiguas, 6 casos de resolución.  
Anotación: pase 1 — revisión humana pendiente.

---

## 2. Modalidades evaluadas

| Modalidad | Modelo | Temperatura | Semilla | Runs/fuente |
|---|---|---|---|---|
| heuristic | N/A (determinista) | N/A | N/A | 1 |
| llm | qwen2.5:7b | 0.1 (hardcoded en llm_extractor.py) | no | 3 |
| hybrid | qwen2.5:7b + heuristic | 0.1 | no | 3 |

> **Nota:** `settings.yaml` configura `temperature: 0`, pero `llm_extractor.py` usa `temperature: 0.1`
> en el payload hardcodeado. Discrepancia documentada; corrección pendiente.

---

## 3. Ejecución del pipeline — Resultados de infraestructura

### 3.1. Ejecución sin fallos

| Modo | Fuentes × Runs | Exit code 0 | Duración media | Duración total |
|---|---|---|---|---|
| heuristic | 5 × 1 = 5 | 5/5 ✅ | 532 ms | 2.66 s |
| llm | 5 × 3 = 15 | 15/15 ✅ | 480 ms | 7.20 s |
| hybrid | 5 × 3 = 15 | 15/15 ✅ | 484 ms | 7.27 s |
| **Total** | **35** | **35/35 ✅** | **487 ms** | **~17 s** |

El pipeline no produjo errores ni crashes en ninguno de los 35 runs.

### 3.2. Hallazgo crítico — Métricas de extracción no disponibles

Los tiempos del modo LLM (~480 ms/run) son inconsistentes con la latencia conocida de Ollama
(~30 s/call en warm). Esto indica que **el pipeline completó sin llamar al LLM**: el segmentador
no encontró segmentos con `should_extract=True` en las fuentes de entrada.

**Causa raíz:** Los fixtures del corpus son ficheros Markdown plano sin estructura de segmentos
(sin timestamps, sin formato de transcripción). El segmentador espera un formato específico
(resultado de faster-whisper o transcripción con marcas de tiempo). Al no encontrar segmentos
válidos, el extractor recibe entrada vacía y retorna lista vacía en <100 ms.

**Consecuencia directa:** Las métricas de Precisión/Recall/F1 por extractor **no están disponibles**
en esta ejecución. El benchmark ejecutó la infraestructura completa pero sin candidatos reales.

### 3.3. Bug corregido en el comparador

`benchmark_comparator.py` esperaba `negative_entities` como `list[str]` pero el ground-truth
lo define como `list[{"name": str, "reason": str}]`. Corregido en este commit:

```python
raw_neg = ground_truth.get("negative_entities", [])
negative_names = {normalize(n["name"] if isinstance(n, dict) else n) for n in raw_neg}
```

---

## 4. Hallazgos del extractor (casos de regresión)

Los 15 tests de regresión ejecutan el extractor directamente (sin segmentador) sobre
texto sintético mínimo. Todos pasan en CI.

| Caso | Descripción | Resultado |
|---|---|---|
| REG-01 | "Llevás" no emitido como Character con confidence ≥ 0.85 | ✅ |
| REG-02 | "Todo" no emitido como Character con confidence ≥ 0.85 | ✅ |
| REG-03 | "Como" no emitido como Character con confidence ≥ 0.85 | ✅ |
| REG-04 | "Soy X" no incluye "Soy" en el nombre del personaje | ✅ **Fix aplicado** |
| REG-05 | Nombre del glosario se normaliza al canónico | ✅ |
| REG-06 | Alias se resuelve al nombre canónico vía glosario | ✅ |
| REG-07 | Entidad existente no genera duplicado (mock Neo4j) | ✅ |
| REG-08 | HAS_FOUGHT con destino Location → rechazada como relación final | ✅ |
| REG-09 | HAS_FOUGHT con destino Location → sugiere FOUGHT_AT | ✅ |
| REG-10 | Relación sin evidencia → no auto_approved | ✅ |
| REG-11 | Tipo de nodo no contemplado → rechazado | ✅ |
| REG-12 | Entidad ambigua → needs_review (no auto_approved) | ✅ |
| REG-13 | Candidato de dos fuentes conserva ambas fuentes | ✅ |
| REG-14 | Timestamps preservados tras normalización ASR | ✅ |
| REG-15 | Modo benchmark no escribe en Neo4j (sin REAL_INGEST) | ✅ |

**Fix aplicado en REG-04:** El extractor heurístico capturaba "Soy Doji Satsume" como entidad.
Se añadió `soy/eres/somos/sois` a STOPWORDS_ES y lógica de strip del primer token cuando es
stopword en nombres compuestos. "Soy Doji Satsume" → "Doji Satsume" (confidence 0.85, Character).

---

## 5. Verificación Ollama

| Campo | Valor |
|---|---|
| Versión | 0.31.1 |
| Modelo | qwen2.5:7b (7.6B, Q4_K_M) |
| num_ctx | 32 768 |
| Temperatura configurada | 0 (settings.yaml) / **0.1 (llm_extractor.py — discrepancia)** |
| Semilla | Soportada vía `seed` en api/generate |
| Cold start | ~63 s |
| Warm start (3 runs) | 33.9 s / 29.7 s / 30.4 s |
| Varianza (temperatura=0.1) | Baja — respuestas idénticas en 3 runs de prueba |
| Disponibilidad | ✅ Operativo (192.168.1.157:11434) |

---

## 6. Estado del CI

| Job | Resultado |
|---|---|
| Data Engine Tests | ✅ Verde |
| Viewer Tests | ✅ Verde |
| Combined Test Suite | ✅ Verde |
| No hardcoded absolute paths | ✅ Verde |

Tests totales: 243 (220 originales + 8 benchmark_runner + 15 regresión).

---

## 7. Acciones correctivas requeridas antes de benchmark con métricas reales

### 7.1. (ALTA) Adaptar fixtures al formato de segmentos del pipeline

Los archivos de corpus deben tener el formato que produce `faster-whisper` o ser pre-segmentados
manualmente. Opción más simple: crear un `segments.json` por fuente directamente como entrada
al paso de extracción, saltando el segmentador.

Alternativa: añadir al benchmark runner la opción `--skip-segmentation` que cargue los fixtures
directamente como segmentos pre-clasificados.

### 7.2. (MEDIA) Unificar temperatura en settings.yaml y llm_extractor.py

`settings.yaml` define `temperature: 0` pero `llm_extractor.py` hardcodea `0.1` en el payload.
Leer el valor desde configuración para evitar divergencia.

### 7.3. (BAJA) Añadir `seed` al payload LLM para reproducibilidad garantizada

Ollama 0.31.1 soporta el parámetro `seed`. Añadir `"seed": 42` al payload para hacer el
modo LLM determinista también a nivel de Ollama (no solo a nivel de temperatura baja).

---

## 8. Tabla de resultados (pendiente — próxima ejecución)

Una vez corregido el formato de entrada (§7.1), rellenar:

| Fuente | Modo | Precisión E | Recall E | F1 E | Precisión R | Recall R | F1 R | Duplicados | Inválidas | Tiempo |
|---|---|---|---|---|---|---|---|---|---|---|
| source_transcript_clean_01 | heuristic | — | — | — | — | — | — | — | — | — |
| source_transcript_clean_01 | llm | — | — | — | — | — | — | — | — | — |
| source_transcript_clean_01 | hybrid | — | — | — | — | — | — | — | — | — |
| *…* | | | | | | | | | | |

---

## 9. Recomendación por tipo de fuente (provisional)

Basado en los tests de regresión y el análisis del código (no en métricas de corpus completo):

| Tipo de fuente | Modo recomendado | Motivo | Limitaciones |
|---|---|---|---|
| Transcripción limpia | hybrid | LLM extrae Objects sin mayúscula; heurístico cubre nombres propios | Requiere Ollama disponible |
| Transcripción con errores ASR | hybrid post-normalización | LLM tolera errores fonéticos; heurístico los confunde | Latencia LLM ~30 s/segmento |
| Notas de sesión | hybrid | Alias implícitos requieren razonamiento contextual | Aliases sin glosario → FN esperados |
| Resolución y duplicados | hybrid + revisión humana | near-duplicates deben ir a cola de revisión, nunca auto-aprobar | |

> **Esta tabla es provisional** — debe ser reemplazada por la tabla §8 con métricas reales.

---

## 10. Dictamen

```
Prioridad 2: PARCIAL — REQUIERE CORRECCIONES
Primera ingesta controlada: BLOQUEADA
```

### Criterios de desbloqueo de ingesta real

1. ☑ Backup de producción al día (último: 2026-07-13, 132 KB, verificado)
2. ☑ 15 tests de regresión pasando en CI
3. ☐ Métricas F1 ≥ 0.75 en entidades en el modo seleccionado (pendiente §7.1)
4. ☐ Tasa de duplicados ≤ 0.10 (pendiente)
5. ☐ Tasa de relaciones inválidas ≤ 0.05 (pendiente)
6. ☐ Revisión humana del `review_queue` completada antes de cualquier ingesta
7. ☐ Ventana de rollback documentada con `source_id` de la fuente

### Excepciones documentadas

| Excepción | Severidad | Estado |
|---|---|---|
| Fixtures corpus sin formato de segmentos | ALTA | Corrección descrita en §7.1 |
| Discrepancia temperature 0 vs 0.1 | MEDIA | Corrección descrita en §7.2 |
| Bug comparator negative_entities | BAJA | **Corregido en este commit** |
| Fix extractor "Soy X" | — | **Aplicado y en CI** |
| Métricas F1 no disponibles | — | Pendiente de §7.1 |

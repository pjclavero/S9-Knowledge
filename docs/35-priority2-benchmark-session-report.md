# 35 · Informe de sesión — Ejecución del benchmark real del extractor (Prioridad 2)

**Fecha:** 2026-07-14
**Ejecutado en:** VM105 (`common`, Debian 13, 6 vCPU CPU-only)
**Rama / PR:** `feat/priority-2-extractor-benchmark` / #11
**Commits de esta sesión:** `a2bbb44`, `13fcab9`, `88f58a5` (+ `f…` de este informe)
**Métricas detalladas:** [docs/34](34-extractor-quality-benchmark-results.md)

Este documento narra **cómo** se ejecutó el benchmark y qué se decidió; las tablas de
métricas completas viven en `docs/34`.

---

## 1. Objetivo

Cerrar la Prioridad 2: ejecutar el benchmark real y reproducible del extractor en VM105,
obtener métricas válidas de `heuristic`/`llm`/`hybrid`, validar reproducibilidad, decidir la
modalidad adecuada por tipo de fuente, corregir únicamente fallos demostrados, actualizar la
documentación y dejar el PR #11 listo para revisión y **merge manual**. Sin ninguna ingesta real.

---

## 2. Preflight (VM105)

| Comprobación | Resultado |
|---|---|
| Rama | `feat/priority-2-extractor-benchmark`, working tree limpio |
| Sincronización | local avanzado de `286efcd` → `7caf55f` (fast-forward, 6 commits) |
| Tests base | 243 pasan |
| CI | 4 jobs verdes en el commit base |
| Neo4j | contenedor `neo4j-knowledge` healthy — 199 nodos / 140 relaciones / 2 índices / 0 constraints |
| Ollama | qwen2.5:7b (digest `845dbda0ea48`) accesible en 192.168.1.157:11434 |
| `S9K_ALLOW_REAL_INGEST` | no definida |
| Corpus | 5 fuentes, 9 segmentos, todos `should_extract=true`; ground truth pase 2 congelado (`annotation_pass=2`, `reviewed=true`) |
| `benchmark-results/` | ignorado por Git |

---

## 3. Diagnóstico: dos fallos que impedían métricas válidas

El primer intento reportó **35 OK con métricas 0.0** en los tres modos. La causa no era el
extractor en sí sino el *wiring* del benchmark:

1. **`data_review.py extract` ignoraba `--extractor`.** El subcomando aislado seteaba
   `S9K_REVIEW_EXTRACTOR` pero `extractor.run()` ejecutaba siempre el heurístico; el LLM no
   se llamaba nunca. Síntoma: runs `llm`/`hybrid` en ~100 ms con candidatos idénticos al
   heurístico y 0 relaciones. → **fix `a2bbb44`** (`cmd_extract` delega en
   `pipeline._run_extract_step`), regresión `test_extract_dispatch.py`.

2. **`benchmark_comparator.py` leía `approved_payload.json`**, que el benchmark aislado nunca
   produce (sólo genera `candidates.json`). → **fix `13fcab9`** (`_load_candidates` lee
   `candidates.json`), regresión en `test_benchmark_runner.py`.

Verificación tras los fixes: un `extract llm` real tarda ~199 s / 2 segmentos y produce 13
entidades + 6 relaciones (antes: 100 ms, 0 relaciones). El ground truth y los umbrales **no**
se modificaron.

---

## 4. Ejecución del benchmark

- Runner: `extractor_benchmark.py --mode all` (35 runs: 5 heurístico + 15 llm + 15 hybrid),
  **secuencial**, sin paralelismo, `seed=42`, siempre `--dry-run`, sin definir
  `S9K_ALLOW_REAL_INGEST`.
- Run inmutable: `benchmark-results/20260714-094125/` (commit `a2bbb44`).
- Resultado: **35 OK / 0 INVALID / 0 FAIL**. Todos los runs `llm`/`hybrid` > 75 s → sin
  fallback silencioso.
- Comparador: `benchmark_comparator.py` (commit `13fcab9`) → `metrics.json` + `report.md`.
- Duración total: ~1 h 35 min.

---

## 5. Resultado (resumen; detalle en docs/34)

- **Entidades (agregado):** heuristic F1 0.689 · llm F1 0.718 (P 0.810) · hybrid F1 0.728 (recall 0.856).
- **Relaciones:** F1 ≈ 0 en todos los modos.
- **Reproducibilidad:** varianza F1 entidades = 0.0 (temp=0, seed=42) en todas las fuentes/modos.
- **Autoaprobación (E2E, 2 fuentes):** precisión 0.85 (< 0.95); 0 candidatos sin evidencia
  autoaprobados; 3 relaciones autoaprobadas pese a baja fiabilidad.
- **Seguridad:** Neo4j intacto 199/140 al inicio y al fin; ninguna ingesta; resolución solo lectura.

Umbrales de aceptación: **ningún modo los cumple**.

---

## 6. Recomendación por tipo de fuente

| Tipo | Modo recomendado | Decisión |
|---|---|---|
| Transcripción limpia / sesión / ASR | LLM (F1 0.74–0.82) | ACEPTADO SOLO PARA GENERAR CANDIDATOS + revisión humana total |
| Resolución / duplicados | Hybrid (F1 0.88, recall 1.0) | ACEPTADO SOLO PARA GENERAR CANDIDATOS + dedup humano |
| Notas | débil (F1 ≈ 0.5) | NO ACEPTADO (alias implícitos sin glosario) |
| Relaciones (todas) | — | NO ACEPTADO (F1 ≈ 0) |

---

## 7. Dictamen

```
Prioridad 2: PARCIAL — REQUIERE CORRECCIONES
Primera ingesta controlada: BLOQUEADA
```

---

## 8. Fase de mejora pendiente

1. Rediseño del prompt de relaciones (taxonomía de dominio + few-shot) y resolución de `from`/`to` por alias.
2. Guard en `auto_decider`: relaciones → siempre `needs_review` hasta F1 rel ≥ 0.60.
3. Filtro de confianza sobre la unión hybrid para elevar la precisión de entidades a ≥ 0.85.
4. Glosario de alias por workspace para notas.
5. Ampliar el corpus de benchmark (5 fuentes / 9 segmentos es pequeño).

---

## 9. Estado de entrega

- Suite: **249 tests** verdes (243 + 3 dispatch + 3 comparador). CI: 4 jobs verdes en `88f58a5`.
- Sin rutas `/opt/` hardcodeadas en el código modificado; sin secretos; `benchmark-results/` gitignored; sin caracteres bidi/ocultos.
- PR #11 actualizado con los 3 commits y un comentario de cierre. **Merge manual** — no automático.
- Documentación actualizada: `docs/34`, `docs/35` (este informe), `CHANGELOG`, `ROADMAP`, `docs/02`, `docs/INDEX`, `README`, dossier.

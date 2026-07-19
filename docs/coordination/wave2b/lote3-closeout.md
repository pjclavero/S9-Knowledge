# Cierre documental — Lote 3 / OLA 2B

Agente **D2** (cierre documental). Rama `docs/wave2b-closeout-v1`, basada en
`origin/main` @ `0909b8f` (incluye TODO el Lote 3: #78, #79, #80, #81, #82, #83).

Este documento **no** modifica producto, tests ni producción: registra los
resultados verificables del Lote 3 y cierra formalmente OLA 2B. La documentación
histórica (docs 41/50/51, tableros previos, otras olas) se conserva intacta.

---

## 1. PRs del Lote 3 (todos MERGED en `main`)

| PR | Componente | Rama | Head SHA | Merge SHA (main) | Dictamen Supervisor |
|----|-----------|------|----------|------------------|---------------------|
| [#78](https://github.com/pjclavero/S9-Knowledge/pull/78) | Mapa de integración Lote 3 (docs) | `docs/wave2b-lote3-coordination` | `1c769a8` | `0909b8f` | Integrado (docs) |
| [#79](https://github.com/pjclavero/S9-Knowledge/pull/79) | B1 corpus de benchmark sintético | `test/relation-benchmark-corpus-v1` | `c8a4a45` | `c92ab6b` | CONFORME |
| [#80](https://github.com/pjclavero/S9-Knowledge/pull/80) | R8 pipeline E2E (dry-run) | `feat/relation-pipeline-v1` | `ef934e2` | `b362a9d` | CONFORME |
| [#81](https://github.com/pjclavero/S9-Knowledge/pull/81) | B2 runner + comparador de benchmark | `test/relation-benchmark-runner-v1` | `e802d30` | `91f972f` | CONFORME |
| [#82](https://github.com/pjclavero/S9-Knowledge/pull/82) | D1 runtime docs (`docs/51-relation-pipeline-runtime.md`) | `docs/relation-pipeline-runtime-v1` | `7ebadfd` | `4ad4289` | CONFORME |
| [#83](https://github.com/pjclavero/S9-Knowledge/pull/83) | QF QA final transversal | `test/wave2b-final-product-v1` | `e16b01c` | `74286ff` | CONFORME |

Orden real de merge (por `git log origin/main`): `c92ab6b` (#79) → `b362a9d`
(#80) → `91f972f` (#81) → `4ad4289` (#82) → `74286ff` (#83) → `0909b8f` (#78).

---

## 2. Alcance por componente

- **B1 (#79)** — corpus sintético sanitizado v1.0.0: **16 fuentes**, **54
  relaciones** de ground truth, **3 workspaces**, **23 tests**. Ground truth con
  hash sha256 verificado (`15973d18…d9cc5c`). Solo contenido inventado; sin datos
  privados.
- **R8 (#80)** — pipeline end-to-end de extracción de relaciones en **dry-run
  estricto**: pares → señales → sintaxis → prompts → consenso, con observabilidad.
  **39 tests**, **12/12 mutaciones**. Nunca escribe ni aprueba; propositor en
  sombra.
- **B2 (#81)** — runner y comparador que ejecutan **R8 REAL** sobre el **corpus
  B1 REAL** contra ground truth (no reimplementa ni simula etapas). **21 tests**.
  F1 de existencia **81.1%**; dictamen **APTO CON REVISIÓN HUMANA TOTAL**.
- **D1 (#82)** — documentación de runtime y operación del pipeline final
  (`docs/51-relation-pipeline-runtime.md`).
- **QF (#83)** — QA transversal final contra producto real: **69 tests** en
  `tests/wave2b` (21 de Lote 2 + 48 nuevos), **20/20 mutaciones** finales, 13
  verificaciones hostiles. Ningún defecto de producto.

---

## 3. Tests y mutaciones

| Componente | PR | Tests | Mutaciones |
|-----------|----|-------|-----------|
| B1 corpus | #79 | 23 | — |
| R8 pipeline | #80 | 39 | 12/12 |
| B2 benchmark | #81 | 21 | — |
| QF QA final | #83 | 69 (suite `tests/wave2b`: 48 nuevos + 21 de Lote 2) | **20/20** |

- Suite `tests/wave2b` final: **69 passed** (`python3 -m pytest tests/wave2b -q`).
- Tests con marca de mutación en `tests/wave2b`: 32 (12 previos + 20 nuevos).
- Mutación final de OLA 2B: **20/20** cazadas contra producto real.

---

## 4. Hallazgos del Supervisor

- **Único defecto real:** un test **frágil** en QF. La verificación
  `test_hostile_no_neo4j_driver_in_path` aseraba sobre `sys.modules` **en el
  proceso pytest**, que se contamina globalmente si cualquier otro test importa
  `neo4j`. **Corregido**: el invariante se comprueba ahora en un **subproceso
  limpio** (`tests/wave2b/test_hostile_real.py`, ~línea 235), que importa la ruta
  del pipeline y verifica que ningún módulo `neo4j` quedó cargado.
- **Ningún defecto de producto.** Todos los invariantes de seguridad y calidad de
  R8 / B1 / B2 se sostienen bajo los 15 escenarios E2E, las 13 verificaciones
  hostiles y las 20 mutaciones. Criterio del Supervisor: **reproducir, no
  corregir** — no se modificó ningún módulo de producto.

---

## 5. Resultados del benchmark (de `docs/50`, sin maquillar)

Ejecución real de `relations.pipeline.run_pipeline` (code SHA `b362a9d`) sobre el
corpus B1, modo `baseline1` (`context_mode=sentence`). Ollama real y NVIDIA real:
**NOT_EXECUTED**; red: **ninguna**; escritura/Neo4j: **ninguna** (dry-run).

### Métricas globales (criterio de existencia: par no ordenado)

| Métrica | Precisión | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| Existencia de relación | 82.7% | 79.6% | **81.1%** | 43 | 9 | 11 |
| Estricta (par + predicado exacto) | 17.3% | 16.7% | **17.0%** | 9 | 43 | 45 |

### Comparativa por modo

| Modo | context_mode | P (exist.) | R (exist.) | F1 | pares |
|---|---|---|---|---|---|
| baseline1 | sentence | 82.7% | 79.6% | 81.1% | 52 |
| baseline2 | paragraph | 36.1% | 96.3% | 52.5% | 144 |
| full_offline | segment | 36.1% | 96.3% | 52.5% | 144 |

### Gates (evaluados por separado)

| Gate | Estado | Valor | Umbral | Tipo |
|---|---|---|---|---|
| determinism | **PASS** | — | — | DURO |
| workspace_contamination | **PASS** | — | — | DURO |
| simple_relations | PASS | 93.3% | 80.0% | calidad |
| evidence | PASS | 90.7% | 80.0% | calidad |
| offsets | PASS | 93.0% | 90.0% | calidad |
| negation | PASS | 100.0% | 80.0% | calidad |
| temporality | **FAIL** | 28.0% | 60.0% | calidad |
| rumors | **PARTIAL** | 50.0% | 60.0% | calidad |
| predicate_structural | **FAIL** | 20.9% | 50.0% | calidad |

### Dictamen: **APTO CON REVISIÓN HUMANA TOTAL**

Evidencia y offsets fiables, pero el predicado heurístico es débil: toda relación
requiere revisión humana antes de considerarse. El vocabulario de dictamen **no**
incluye "APTO PARA INGESTA REAL": R8 es un propositor en sombra / dry-run que
nunca aprueba ni escribe. Los dos gates DUROS (determinismo, contaminación de
workspaces) están en PASS.

---

## 6. Limitaciones y riesgos residuales

- **Predicado exacto bajo** (F1 estricta 17.0%; `predicate_structural` FAIL a
  20.9%): el proponente de predicado es **heurístico en sombra**, sin calibración.
- **Temporalidad débil** (gate FAIL, 28.0%) y **rumores** débiles (gate PARTIAL,
  50.0%).
- **Sin calibración con modelos reales**: los evaluadores Ollama/NVIDIA se
  ejercitan solo con transporte inyectado; NO se ha medido precisión con LLM
  reales.
- Consecuencia operativa: cualquier relación producida **debe** pasar por revisión
  humana total; no hay ruta a ingesta automática.

---

## 7. Estado de producción

**RC5.1 intacta.** El Lote 3 no toca producción.

- Neo4j: **199 nodos / 140 relaciones** (199/140).
- Usuarios admin: **1**.
- Jobs: **1** · Ingestas: **0**.
- Timer horario de healthcheck: **activo**.
- `S9K_ALLOW_REAL_INGEST`: **off**.

---

## 8. Estado de RC6

- `release/rc6-candidate` = **`15ae1d4`** — **INTACTA** (0 commits de OLA 2B en la
  base RC6; verificado por `git ls-remote origin refs/heads/release/rc6-candidate`).
- **Sin tag RC6.**
- **Sin GitHub Release RC6.**
- **Sin despliegue RC6.**

---

## 9. Tareas NO ejecutadas (fuera de alcance de OLA 2B)

- Ollama real / validación con LLM local real.
- NVIDIA real / validación con IA externa real.
- OCR y comprensión visual.
- Descarga de modelos.
- Import en modo APPLY.
- Ingesta real.

Todas quedan como `NOT_EXECUTED`, por diseño y por seguridad (dry-run, sin red,
sin escritura, sin autoaprobación).

---

## 10. Siguiente fase recomendada (separada, NO iniciada)

1. **Calibración con modelos reales** (Ollama local, NVIDIA), bajo autorización.
2. **Mejora de precisión de predicado** (temporalidad y rumores incluidos).
3. **Panel funcional de relaciones** en el viewer.
4. **Export funcional.**
5. **Import** en modos VALIDATE / PLAN / PREVIEW (APPLY sigue off).
6. **OCR** y **comprensión visual**.
7. **Ingesta controlada** eventual, tras revisión humana y gates verdes.

Ninguna de estas tareas se inicia en este cierre.

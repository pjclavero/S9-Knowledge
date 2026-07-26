# Estado actual del repositorio y baseline reproducible

**Programa:** Motor V2 temporal, episódico y trazable · **BLOQUE 0 — auditoría y baseline**
**Rama de integración:** `exp/relation-engine-v2-temporal-provenance-v1`
**Commit auditado:** `8fc7c8d45b2a03be92b7935f9d9b9c2bd32390bb` (= `origin/main`)
**Fecha:** 26 de julio de 2026 · **Alcance:** solo documentación y artefactos.
**Ningún cambio funcional.** Sin red, sin proveedores, sin Neo4j, sin ingesta, sin despliegue.

Artefactos crudos: `artifacts/relation-v2e/baseline/`.

---

## 1. Qué se pedía comprobar y qué salió

| Afirmación recibida | Verificación |
|---|---|
| `origin/main` = `8fc7c8d` | **Confirmada.** El worktree está exactamente ahí |
| El motor V2 se fusionó vía PR #105 (`5ad9f18`), ancestro de main | **Confirmada.** `git merge-base --is-ancestor 5ad9f18 8fc7c8d` → sí |
| Rama histórica `feat/relation-engine-v2-hybrid` = `baabb54` | **Confirmada** como SHA, **con matiz importante**: `baabb54` **NO es ancestro de `main`** (ver §2) |
| Informe rector de 2033 líneas | **Confirmado**, línea a línea |
| Defaults: `predicate_selector="v1"`, `consensus_policy="auto"`, `local_llm_enabled=False`, `external_ai_enabled=False`, `external_protocol="legacy"` | **Confirmados los cinco** en `relations/pipeline.py:154,155,164,172,179`, y re-confirmados en el bloque `config` que emite el propio arnés |

---

## 2. Estado real de git

```
HEAD de la rama de integración = 8fc7c8d45b2a03be92b7935f9d9b9c2bd32390bb
origin/main                    = 8fc7c8d45b2a03be92b7935f9d9b9c2bd32390bb   (idénticos)
merge del motor V2 (PR #105)   = 5ad9f18bfdbcda3db911e03656ba2bbc7a8a0024   (2026-07-26 19:05:54 +0200)
rama histórica (tip)           = baabb548a5dd723aef2026712888c3277f3035b0   (2026-07-26 18:41:53 +0200)
```

### Matiz sobre la rama histórica

`baabb54` **no es ancestro de `main`**. No es una discrepancia: el PR #105 se fusionó por
**squash**, que reescribe el contenido de la rama en un commit nuevo (`5ad9f18`). El tip de la
rama de origen nunca queda en el historial de `main`. La rama sigue en su sitio y **no se ha
tocado en este bloque**.

### Qué ha pasado en `main` DESPUÉS del merge del V2

10 commits. Ordenados de más reciente a más antiguo:

| SHA | Asunto |
|---|---|
| `8fc7c8d` | Add files via upload — **es el propio informe rector** (+2033 líneas, 1 fichero) |
| `d4ce6b2` | build(deps): update pydantic requirement in /viewer (**#56**) |
| `9df81cc` | build(deps): update jsonschema requirement in /data-engine (**#57**) |
| `5325cfa` | build(deps): update pydantic-settings requirement in /viewer (**#52**) |
| `36aed9d` | build(deps): update jsonschema requirement in /viewer (**#54**) |
| `f665892` | build(deps): update fastapi requirement in /viewer (**#55**) |
| `c452edf` | feat(review): limpieza del grafo controlada y reversible (Prioridad 5) (**#96**) |
| `53db182` | chore(deps): bump actions/setup-python from 5 to 7 (**#104**) |
| `7ee6406` | build(deps): bump actions/checkout from 4 to 7 (**#51**) |
| `8f85c53` | docs: dosier de análisis externo del motor de relaciones (#103) |
| `4ae4c6b` | docs: informe del motor de extracción para auditoría externa (52) (#95) |

Los PR de dependencias anunciados (#51-#57, #104) y #96 **están todos ahí**. Diff agregado
`5ad9f18..8fc7c8d`: 10 ficheros, +3363 / −22 líneas.

**Resultado clave para el programa:**

```
git diff --name-only 5ad9f18 8fc7c8d -- data-engine/app/relations   →   (vacío)
```

**El módulo `relations/` no ha recibido un solo cambio desde el merge del V2.** Todo lo
posterior es: dependencias, workflows, el módulo nuevo `review/graph_cleanup.py` (#96) y
documentación. El baseline del motor que se mide aquí es, byte a byte, el que se fusionó.

---

## 3. Comandos autoritativos encontrados (no inventados)

Fuentes: `pytest.ini`, `.github/workflows/ci.yml`, `--help` del arnés.

- `pytest.ini` declara 8 `testpaths`: `data-engine/app/tests`, `viewer/tests`, `deploy/tests`,
  `contracts/review-ingest/v1/tests`, `tests/integration`, `tests/e2e`, `tests/wave2`,
  `tests/wave2b`.
- `.github/workflows/ci.yml` tiene **8 jobs**. Los de test son literalmente:
  - `python -m pytest data-engine/app/tests/ -v --tb=short --no-header`
  - `python -m pytest viewer/tests/ -v --tb=short --no-header`
  - `python -m pytest --tb=short --no-header -q` (suite combinada)
  - `python -m pytest contracts/review-ingest/v1/tests/ -q`
  - `python -m pytest tests/browser -q --no-header` (Playwright, con Chromium instalado)

  Todos con `S9K_ALLOW_REAL_INGEST: ""`, Python 3.13 y `data-engine/requirements.lock`.
- **No existe** ningún script de validación específico del motor de relaciones. El arnés
  autoritativo es `python3 -m relations.benchmark.cli` desde `data-engine/app`.
- Los modos con proveedor (`ensemble_full`, `nvidia_shadow`, `ollama_shadow`) exigen **doble
  llave** (`--enable-providers` + `S9K_BENCH_PROVIDERS=1`). **No se han usado.**

### Aviso: el CI no se dispara en esta rama por push

`ci.yml` dispara en `push` sobre `main`, `fix/**`, `feat/**`, `audit/**`, `docs/**`, `chore/**`.
**`exp/**` no está en la lista.** La rama de integración de este programa sólo obtendrá CI a
través de un **pull request contra `main`**. No es un fallo, pero conviene saberlo antes de
esperar un verde que nunca va a aparecer.

---

## 4. Baseline del benchmark — 4 corridas, proveedores desactivados

Corpus B1 congelado, `deterministic=True` en las cuatro, `local=NOT_EXECUTED`,
`external=NOT_EXECUTED`, **0 llamadas**, `transport_errors=0`, `verdict_scope=COMPLETO`,
16 fuentes, 52 candidatos, 54 relaciones GT, 43 emparejadas.

### 4.1. `--mode baseline1`

| Métrica | v1 | v2 | Δ |
|---|--:|--:|--:|
| `predicate_correct` | 0.2093 (9/43) | **0.8140** (35/43) | +0.6047 |
| `direction_correct` | 0.6279 (27/43) | **0.9302** (40/43) | +0.3023 |
| `direction_orientation_ok` | 0.7674 | 0.9535 | +0.1861 |
| `temporal_correct` | 0.4419 (19/43) | **0.8837** (38/43) | +0.4418 |
| `evidence_correct` | 0.9070 | 0.9302 | +0.0232 |
| `offsets_correct` | 0.9302 | 0.9535 | +0.0233 |
| `epistemic_correct` | 0.8605 | 0.8605 | 0.0000 |
| `negation_correct` | 0.9070 | 0.8837 | **−0.0233** |
| `decision_correct` | 0.3023 (13/43) | 0.3488 (15/43) | +0.0465 |
| `types_correct` / `workspace_correct` | 1.0000 | 1.0000 | 0.0000 |
| `strict_predicate.f1` | 0.1698 | **0.6604** | +0.4906 |
| `strict_predicate` P / R | 0.1731 / 0.1667 | 0.6731 / 0.6481 | — |
| `global_existence.f1` (**pair_F1**) | 0.8113 | 0.8113 | **0.0000** |
| `global_existence` P / R | 0.8269 / 0.7963 | 0.8269 / 0.7963 | — |
| TP / FP / FN de pares | 43 / 9 / 11 | 43 / 9 / 11 | — |
| **Falsos ACCEPT** | **4** | **0** | **−4** |
| Veredicto del arnés | `APTO CON REVISION HUMANA TOTAL` | `APTO PARA CONTINUAR EN MODO SOMBRA` | — |

Matriz de decisión (GT → predicho):

| baseline1 v1 | ACCEPT | REJECT | REVIEW | | baseline1 v2 | ACCEPT | REJECT | REVIEW |
|---|--:|--:|--:|---|---|--:|--:|--:|
| **ACCEPT** (30) | 9 | 0 | 21 | | **ACCEPT** (30) | 3 | 0 | 27 |
| **REJECT** (5) | **4** | 0 | 1 | | **REJECT** (5) | **0** | **4** | 1 |
| **REVIEW** (8) | 4 | 0 | 4 | | **REVIEW** (8) | 0 | 0 | 8 |

### 4.2. `--mode ensemble_offline`

Todas las métricas estructurales son **idénticas** a `baseline1` para el mismo selector. Lo
único que cambia es la decisión:

| Métrica | v1 | v2 | Δ |
|---|--:|--:|--:|
| `decision_correct` | 0.3953 (17/43) | **0.4651** (20/43) | +0.0698 |
| **Falsos ACCEPT** | **2** | **0** | **−2** |
| `global_existence.f1` | 0.8113 | 0.8113 | 0.0000 |

### 4.3. Gates del arnés

| Gate | Umbral | v1 | v2 |
|---|--:|:--:|:--:|
| `determinism` (duro) | — | PASS | PASS |
| `predicate_structural` | ≥ 0.50 | **FAIL** (0.2093) | PASS (0.8140) |
| `evidence` | ≥ 0.80 | PASS (0.9070) | PASS (0.9302) |
| `offsets` | ≥ 0.90 | PASS (0.9302) | PASS (0.9535) |
| `temporality` | ≥ 0.60 | PASS (0.7600) | PASS (0.9600) |
| `negation` | ≥ 0.80 | PASS (1.0000) | PASS (1.0000) |
| `rumors` | ≥ 0.60 | PASS (1.0000) | PASS (1.0000) |
| `simple_relations` | ≥ 0.80 | PASS (0.9333) | PASS (0.9333) |
| `workspace_contamination` | — | PASS | PASS |

**Ningún umbral se ha tocado.** Advertencia sobre el gate `negation`: su valor 1.0000 es el
**recall** sobre el subgrupo de 4 relaciones negadas del GT. **No mide la precisión**, que es
4/9. Un gate en verde no dice nada sobre el defecto abierto de negación (ver `open-defects.md` §3).

### 4.4. Reproducción de las cifras históricas

Las 4 corridas reproducen **exactamente**, hasta el cuarto decimal, las tablas §3.1 y §3.2 de
`docs/relation-engine-v2-results.md`, que se midieron en otra rama y con otras versiones de
dependencias. Las actualizaciones de dependencias posteriores al merge **no han movido ni una
métrica del motor**. Los `result_hashes` por fuente son estables entre corridas
(`determinism: PASS`, `hashes_equal`, `metrics_equal`, `predictions_equal`).

**Observación no solicitada, pero relevante:** los `result_hashes` de `baseline1` y
`ensemble_offline` son **idénticos** para el mismo selector, y sin embargo `decision_correct`
difiere (13 vs 17 en v1). Es decir, **el hash de determinismo no cubre el campo de decisión**.
Es correcto para lo que se usa (verificar que el pipeline es reproducible), pero no debe leerse
como "las dos corridas produjeron lo mismo".

---

## 5. Baseline de tests — conteos REALES

Medidos en este entorno (Python 3.13.5, Debian 13), **no en CI**. Los conteos históricos
(2431/2 y ~3186/5) se usan sólo como **referencia**, nunca como condición.

| Suite | Comando | Exit | Resultado real | Wall |
|---|---|:--:|---|--:|
| Data Engine | `pytest data-engine/app/tests/` | 0 | **2443 passed, 2 skipped** | 15.5 s |
| Viewer | `pytest viewer/tests/` | 0 | 366 passed, 1 skipped | 11.8 s |
| Deploy | `pytest deploy/tests/` | 0 | 155 passed | 5.2 s |
| Contratos review/ingest v1 | `pytest contracts/review-ingest/v1/tests/` | 0 | 38 passed | 0.2 s |
| Integración | `pytest tests/integration` | 0 | 75 passed | 0.3 s |
| E2E | `pytest tests/e2e` | 0 | 10 passed | 1.7 s |
| Wave 2 | `pytest tests/wave2` | 0 | 42 passed | 0.4 s |
| Wave 2b | `pytest tests/wave2b` | 0 | 69 passed, 2 skipped | 1.3 s |
| **Combinada (`pytest.ini`)** | `pytest` | **0** | **3198 passed, 5 skipped, 0 failed** | 34.8 s |

Delta frente a la referencia histórica: **+12 tests pasados** en data-engine (2431 → 2443),
mismos 2 skips. Es coherente con el PR #96, que añadió `tests/test_graph_cleanup.py`.
**Cero fallos, cero errores de recolección.**

Los 5 skips están inventariados en `artifacts/relation-v2e/baseline/skipped-tests.md`: spaCy,
Stanza, Playwright, NVIDIA live y Ollama live. Ninguno oculta un fallo.

### Trampa detectada con `PYTHONDONTWRITEBYTECODE=1`

`deploy/tests/test_release_checksum.py::test_import_real_de_python_no_altera_checksum` **falla**
si se ejecuta con esa variable, porque su premisa es que el import genere bytecode. El test es
correcto; la variable es incompatible con él. En este baseline las suites que lo incluyen se
ejecutaron **sin** la variable, purgando `__pycache__` inmediatamente después (verificado:
`find . -name '*.pyc' | wc -l` → `0`). Conviene tenerlo presente en los bloques siguientes: la
disciplina antipyc de este proyecto es *purgar*, no *prohibir escribir*.

---

## 6. Rendimiento (solo lo medido)

**No se han medido CPU ni RAM.** No se estiman.

| Corrida | Wall (proceso completo) | Pipeline `total_ms` | `per_candidate_ms` | `per_doc_ms` |
|---|--:|--:|--:|--:|
| `baseline1` v1 | 0.465 s | 51.08 | 0.982 | 3.193 |
| `baseline1` v2 | 0.593 s | 96.89 | 1.863 | 6.056 |
| `ensemble_offline` v1 | 0.511 s | 54.93 | 1.056 | 3.433 |
| `ensemble_offline` v2 | 0.594 s | 85.25 | 1.639 | 5.328 |

El selector v2 cuesta aproximadamente **1,7–1,9×** el tiempo de pipeline de v1. Es una medida
sobre 52 candidatos y 16 documentos: sirve como orden de magnitud, **no** como cifra de
producción.

---

## 7. Configuración, contratos y dependencias

### Defaults de `PipelineConfig` (`relations/pipeline.py`)

```
local_llm_enabled    = False   (:154)
external_ai_enabled  = False   (:155)
predicate_selector   = "v1"    (:164)
consensus_policy     = "auto"  (:172)
external_protocol    = "legacy"(:179)
```

Es decir: **el motor V2 está fusionado pero NO activado.** El comportamiento por defecto de
`main` hoy es el de v1, con `predicate_correct = 0.2093` y el gate `predicate_structural` en
FAIL. Coherente con la adenda del propietario ("FUSIONAR SIN ACTIVAR").

### Contrato `RelationCandidate` / `internal-1.0.0`

Verificado por introspección: **20 campos exactos**, `SCHEMA_VERSION = "internal-1.0.0"`.

```
subject_id, subject_type, predicate, object_id, object_type, direction, confidence,
evidence_text, evidence_start, evidence_end, source_id, source_page, source_segment,
extraction_method, model, negated, temporal_scope, epistemic_status, workspace,
validation_flags
```

**Intacto. No se toca en este programa.**

### Contratos review/ingest v1

`contracts/review-ingest/v1/`: 6 JSON Schema, 12 ejemplos válidos, 16 inválidos, 38 tests en
verde.

### Módulos de `relations/` (39 ficheros `.py`, 18 560 líneas)

Núcleo: `pipeline.py`, `contracts.py`, `ontology.py`, `predicate_selector.py`, `direction.py`,
`temporal_v2.py`, `temporality.py`, `abstention.py`, `consensus_adapter.py`, `signals.py`,
`syntax.py`, `epistemic.py`, `pairs.py`, `vocabulary.py`, `evidence_realignment.py`,
`fragment_protocol.py`, `external_consult.py`, `external_ai_shadow.py`, `local_llm_shadow.py`,
`ensemble.py`, `review_policy.py`, `observability.py`, `cli.py`.
Subpaquetes: `benchmark/` (7), `calibration/` (4), `prompts/` (2).

### Dependencias

- `data-engine/requirements.lock` **no se ha regenerado** tras los PR de dependencias: sólo
  cambió `requirements.in` (`jsonschema>=4.18` → `>=4.26.0`). El lock ya pinaba
  `jsonschema==4.26.0`, así que no hay incoherencia hoy, pero **el `.in` y el `.lock` se
  actualizan por vías distintas** y eso puede divergir.
- **Divergencia local ↔ CI que hay que tener presente:** el lock pina `pytest==9.1.1`; este
  entorno tiene `pytest 8.4.2`. Las cifras de §5 son de este entorno, no de CI.

---

## 8. Hashes del corpus B1 (prueba de no-manipulación)

Directorio: `data-engine/app/tests/data/relation_benchmark/` (22 ficheros).
Hashes completos en `artifacts/relation-v2e/baseline/git-state.json` → `.corpus_b1.sha256`.

```
ground_truth/relations.json  15973d1837deb29ea339bca6bb3980d62e07ef283b196bf38d0d1e2653d9cc5c
manifest.json                a2cc506f953a405db507cfe53389d2923f2d8a7015b6f7164f5a90ec825d2631
```

Los 16 `sha256` de `sources/` calculados de forma independiente **coinciden uno a uno** con el
bloque `corpus.corpus_hashes` que emite el propio arnés, y el hash del ground truth coincide con
`corpus.ground_truth_sha256`. `relation_count = 54`, `source_count = 16`, `version = 1.0.0`.

Cualquier bloque posterior puede comparar contra estos valores para demostrar que el corpus, el
ground truth y los umbrales no se han tocado.

---

## 9. Defectos abiertos: los 6, uno por uno

Detalle completo con `fichero:línea` en `artifacts/relation-v2e/baseline/open-defects.md`.

| Id | Estado en `8fc7c8d` | Localización |
|---|:--:|---|
| **B5-D4** retención global de texto crudo sin TTL | **CONFIRMADO** (con matiz) | `relations/syntax.py:1212-1222`, `:1119-1137`, usado en `relations/pipeline.py:679` |
| **B5-D7** objeto cacheado compartido por identidad | **CONFIRMADO** | `relations/syntax.py:1126` (`return cached`, sin copia; `SyntaxAnalysis` es `frozen`) |
| **Negación 4/9** — no promocionar el rechazo | **CONFIRMADO y remedido** | `relations/abstention.py:198,426-431,462-466`; señal en `relations/signals.py:426-432` |
| **B7 envolvente** `TIER_NORMALIZED` inalcanzable | **CONFIRMADO** | `relations/external_ai_shadow.py:459` corta antes; `relations/evidence_realignment.py:73` lo declara aceptable |
| **B7 API muerta** `validate_external_verdict` | **CONFIRMADO** | `relations/external_consult.py:356`; 23 llamadas, todas en tests |
| **`pair_F1` no mejoró (11 FN)** | **CONFIRMADO y remedido** | `f1=0.8113`, `fn=11` en las 4 corridas |

**Ninguno refutado. Ninguno corregido.** Dos matices honestos sobre el enunciado recibido:

1. **B5-D4** dice "sin API pública de reset". Es casi cierto: `CachingSyntaxAnalyzer.cache_clear()`
   **sí** existe y es pública, y `get_default_analyzer` está exportado, de modo que
   `syntax.get_default_analyzer().cache_clear()` funciona hoy. Lo que **no** existe es una
   función de módulo que resetee el singleton `_DEFAULT_ANALYZER`, ni ningún llamador que limpie
   la caché. Lo de "sin TTL" es literal: sólo hay desalojo LRU por tamaño (512).
2. **Negación**: el 4/9 es la precisión sobre las **43 relaciones emparejadas**. Sobre los
   **52 candidatos emitidos** la precisión medida es **4/10**. Ambas cifras se han reproducido
   desde cero en este bloque.

Y una confirmación que refuerza el diagnóstico del Supervisor: de los 10 candidatos que v2 marca
`negated=True`, sólo 5 llegan a `reject`, y de esos 5 **4 son correctos y 1 es falso** (sobre un
par que ni siquiera está en el ground truth). Los otros 5 falsos positivos los absorbe
`MODEL_CONFLICT`/`HUMAN_REQUIRED`. Es exactamente lo descrito en §8.5: **"suerte, no garantía"**.

---

## 10. Sorpresas y cosas que no cuadraban

1. **`baabb54` no es ancestro de `main`.** Explicado: squash merge. No es un problema, pero el
   enunciado lo daba por hecho de otra forma.
2. **El HEAD de `main` es un commit "Add files via upload"** que introduce el propio informe
   rector (2033 líneas) sin PR. El programa se apoya en un documento subido a mano.
3. **`ci.yml` no cubre `exp/**` en `push`.** La rama de integración de este programa sólo tendrá
   CI vía PR.
4. **`PYTHONDONTWRITEBYTECODE=1` rompe un test legítimo** (`test_release_checksum.py`). La
   instrucción antipyc del proyecto y ese test conviven sólo si se purga en vez de prohibir.
5. **`requirements.lock` no se regeneró** con los PR de dependencias; sólo el `.in`. Hoy no hay
   incoherencia, pero las dos vías pueden divergir.
6. **El gate `negation` del arnés mide recall sobre 4 casos**, no precisión. Está en verde con
   un defecto MEDIA abierto debajo. Un gate que no puede ponerse rojo por el defecto que dice
   vigilar es exactamente el patrón que este programa se comprometió a no repetir.
7. **Los `result_hashes` no cubren la decisión** (§4.4): dos modos con hashes idénticos dan
   `decision_correct` distinto.
8. **`max_time_per_candidate_ms` está declarado pero no se aplica.** El propio arnés lo declara
   en `config_notes`: el pipeline no lo comprueba en ningún punto. Es un control de recursos
   inefectivo.
9. **Las cifras históricas se reproducen al cuarto decimal** pese al cambio de rama y de
   dependencias. Eso es una buena noticia y da confianza en el determinismo del arnés.

---

## 11. Lo que este bloque NO hizo (por diseño)

Sin cambios funcionales. Sin tocar `main`, `feat/relation-engine-v2-hybrid` ni `exp/pr95-*`.
Sin merge, rebase, cherry-pick, force-push ni borrado de ramas. Sin red, sin proveedores reales,
sin Neo4j, sin ingesta, sin despliegue, sin VM105. Sin modificar corpus, ground truth, métricas
ni umbrales. Sin tocar `RelationCandidate/internal-v1`.

Los entregables de ADR que el informe rector pide para su BLOQUE 0
(`docs/S9_KNOWLEDGE_INFORME_MEJORA_MOTOR_CONSOLIDADO_V2.md:1403-1418`: ADR Episode, Assertion
Ledger, Provenance, Temporal, Supersession, Provider Ports, Ontology, KnowledgeBundle y mapa de
migración) **no forman parte de este encargo**, que se limitó a "estado real de `main`" + baseline.
Quedan pendientes para quien continúe.

# 37 · Revisión humana total y benchmark confirmatorio de 7 fuentes — Prioridad 2.1

**Fecha:** 2026-07-14
**Rama:** `feat/priority-2-1-extractor-quality-improvements` (PR #12)
**Run confirmatorio:** `20260714-151119` (commit `c447abd`, **49 runs · 49 OK / 0 INVALID / 0 FAIL**)
**Corpus:** `tests/fixtures/benchmark/corpus-manifest-v2.json` — 7 fuentes, 13 segmentos, 72 entidades, 27 relaciones, ground truth pase 2/3 congelado.
**Baselines conservados:** `docs/34` (5 fuentes, pase inicial) y `docs/36` (5 fuentes, mejora). Este documento **no los sobrescribe**.

---

## 1. Modo de revisión humana total (impuesto por código)

`S9K_REVIEW_POLICY` ∈ `{normal, full_human_review}` (default `normal`; valor desconocido → error de configuración).

| | `normal` | `full_human_review` |
|---|---|---|
| Entidades | política de decisión habitual | **todas → needs_review** |
| Relaciones | quality gate (needs_review) | **todas → needs_review** |
| Autoaprobados | según confianza | **0** |
| approved_payload automático | según decisiones | **vacío** |
| `decision_reason` | reglas habituales | `full_human_review_policy` |

`ingest-approved` bajo `full_human_review` **rechaza sin escribir en Neo4j** cualquier payload cuyos candidatos aprobados no acrediten revisión humana explícita (`review_status=approved`, `reviewed_by` válido ≠ system/auto/vacío, `reviewed_at`, `review_action`, `evidence`, `source_id`).

CLI mínima `review_manual.py` (`approve|reject|edit|use-existing`): registro **append-only** en `manual_review_log.jsonl`, genera `approved_payload.reviewed.json` con procedencia, conserva el payload automático, **nunca toca Neo4j**.

### Demostración E2E (clean_01, hybrid, datos reales del run)
```
decisiones = {'needs_review': 17}   autoaprobados = 0   total = 17
CLI approve (manual-cli:ana) → approved_payload.reviewed.json: 1 candidato
ingest --dry-run del payload revisado: aceptado, 1 entidad, SIN escritura en Neo4j
payload con review_status=auto_approved → RECHAZADO bajo full_human_review
```

15 tests en `test_full_human_review.py` cubren los 15 casos exigidos (todos en CI).

---

## 2. Benchmark confirmatorio de 7 fuentes — métricas agregadas

| Modo | P ent | R ent | F1 ent | P rel | R rel | F1 rel |
|---|---:|---:|---:|---:|---:|---:|
| heuristic | 0.711 | 0.794 | 0.747 | 0.000 | 0.000 | 0.000 |
| llm | 0.895 | 0.732 | 0.797 | — | — | 0.163 |
| **hybrid** | **0.878** | **0.823** | **0.846** | — | — | 0.163 |

Umbrales (P ent ≥ 0.85 · R ent ≥ 0.70 · F1 ent ≥ 0.75 · P rel ≥ 0.75 · R rel ≥ 0.60):

| Modo | Entidades | Relaciones |
|---|:--:|:--:|
| heuristic | FAIL | FAIL |
| llm | **PASS** | FAIL |
| **hybrid** | **PASS** | FAIL |

**Tanto `hybrid` como `llm` superan los tres umbrales de entidad sobre las 7 fuentes.** Las relaciones (F1 0.163) siguen por debajo del umbral pese a mejorar respecto al baseline (0.036).

---

## 3. Métricas por fuente (hybrid)

| Fuente | Tipo | F1 ent | var F1 ent | F1 rel |
|---|---|---:|---:|---:|
| source_narrative_01 | narrativo | **1.000** | 0.0 | 0.444 |
| source_transcript_session_02 | transcripción | 0.923 | 0.0 | 0.000 |
| source_manual_01 | manual | 0.889 | 0.0 | 0.250 |
| source_transcript_clean_01 | transcripción | 0.880 | 0.0 | 0.444 |
| source_resolution_01 | resolución | 0.778 | 0.0 | 0.000 |
| source_notes_01 | notas | 0.737 | 0.0 | 0.000 |
| source_transcript_asr_01 | ASR | 0.714 | 0.0 | 0.000 |

Las dos fuentes nuevas (narrativo, manual) obtienen el mejor F1 de entidades y F1 de relaciones
no nulo (regla apellido→clan). Reproducibilidad: varianza F1 entidades = 0.0 en todas.

---

## 4. Validación de runs

| Estado | Nº |
|---|---:|
| OK | 49 |
| INVALID_RUN | 0 |
| FAILED | 0 |
| DEGRADED | 0 |

Todos los runs llm/hybrid > 90 s (`llm_calls_succeeded > 0`, sin fallback). Solo `OK` entra en métricas.

---

## 5. Política full human review — recuento

| Métrica | Valor |
|---|---:|
| Candidatos totales (clean_01) | 17 |
| Candidatos en revisión | 17 |
| Autoaprobados | **0** |
| approved_payload automático | vacío |
| Aprobados manualmente (fixture demo) | 1 |
| Relaciones autoaprobadas | **0** |

---

## 6. Seguridad

| Métrica | Inicio | Fin |
|---|---:|---:|
| Nodos Neo4j | 199 | 199 |
| Relaciones Neo4j | 140 | 140 |
| `S9K_ALLOW_REAL_INGEST` | unset | unset |
| Ingesta ejecutada | — | **NO** |

Neo4j intacto durante el benchmark, el E2E y la demo de ingesta (siempre `--dry-run`).

---

## 7. Criterio de desbloqueo de la primera ingesta (§9)

| Criterio | Estado |
|---|---|
| hybrid P entidades ≥ 0.85 | ✓ 0.878 |
| hybrid R entidades ≥ 0.70 | ✓ 0.823 |
| hybrid F1 entidades ≥ 0.75 | ✓ 0.846 |
| full_human_review autoaprobados = 0 | ✓ (impuesto por código, tests) |
| relaciones autoaprobadas = 0 | ✓ (gate + full_review, E2E) |
| payload exige reviewed_by y reviewed_at | ✓ (validación de procedencia) |
| backup verificado | ✓ (Prioridad 1, docs/32 — **reconfirmar antes de ingerir**) |
| restore verificado | ✓ (Prioridad 1, docs/32) |
| rollback validado | ✓ (Prioridad 1, docs/32) |
| 49 runs confirmatorios válidos | ✓ 49 OK / 0 INVALID / 0 FAIL |

Las relaciones **no** se incluirán en la primera ingesta (F1 0.163 < 0.60); se aprobarían individualmente por revisión humana si se decidiera posteriormente.

---

## 8. Dictamen

```
Prioridad 2.1: COMPLETADA — PREPARADA PARA INGESTA CONTROLADA CON REVISIÓN TOTAL
Primera ingesta controlada: PREPARADA, NO EJECUTADA
```

**Justificación:** el modo hybrid supera los tres umbrales de entidad sobre 7 fuentes (F1 0.846);
la revisión humana total está **impuesta por código** (política + validación de procedencia,
demostrado con 15 tests y un E2E con 0 autoaprobados); las relaciones quedan excluidas de la
autoaprobación; Neo4j permanece intacto y los 49 runs confirmatorios son válidos.

**No se ejecuta ninguna ingesta en esta tarea.** Antes de la primera ingesta real: reconfirmar
backup/restore/rollback, elegir una fuente pequeña, `--dry-run`, revisión humana total del
`review_queue` y del `approved_payload` revisado, y activación del doble guard bajo autorización explícita.

### Trabajo siguiente (relaciones)
Elevar recall de relaciones (más few-shot por tipo; corpus con relaciones explícitas) hasta F1 ≥ 0.60
antes de considerar su ingesta.

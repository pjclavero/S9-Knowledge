# 36 · Resultados de la mejora de calidad del extractor — Prioridad 2.1

**Fecha:** 2026-07-14
**Rama:** `feat/priority-2-1-extractor-quality-improvements`
**Run mejorado:** `20260714-121026` (commit `3c9e994`, 35 runs · 35 OK / 0 INVALID / 0 FAIL)
**Baseline:** `docs/34` (run `20260714-094125`) — **no se sobrescribe**, es la referencia histórica.
**Ejecutado en:** VM105 · Ollama qwen2.5:7b @ 192.168.1.157:11434 · temperature=0 · seed=42

Corpus del run mejorado: las **5 fuentes** del baseline (comparación justa antes/después).
El corpus se amplió además con 2 fuentes nuevas (narrativa, manual; ver §7).

---

## 1. Cambios implementados (todos con tests, sin tocar ground truth ni umbrales)

| # | Mejora | Módulo | Tests |
|---|---|---|---|
| 1 | Quality gate: relaciones **nunca autoaprobadas** | `auto_decider.py` (`_relation_autoapproval_enabled`) | 7 |
| 2 | Prompt de relaciones: taxonomía origen→destino, few-shot, regla apellido→clan | `llm_extractor.py` (`_SYSTEM_PROMPT`) | 10 |
| 3 | Resolución de extremos de relación (alias + dirección) | `relation_normalizer.py` | 8 |
| 4 | Glosario de alias por workspace | `workspace_aliases.py` + `config/aliases/leyenda.json` | 6 |
| 5 | Filtro de confianza del híbrido (reglas A/B/C) | `hybrid_filter.py` | 9 |

Suite total: **289 tests** verdes (249 previos + 40 nuevos).

---

## 2. Métricas agregadas — baseline vs mejorado (mismas 5 fuentes)

| Métrica | Baseline (docs/34) | Mejorado | Δ |
|---|---:|---:|---:|
| **Heuristic** F1 ent | 0.689 | 0.689 | = (sin tocar) |
| **LLM** P ent | 0.810 | 0.877 | +0.067 |
| **LLM** R ent | 0.655 | 0.649 | −0.006 |
| **LLM** F1 ent | 0.718 | 0.741 | +0.023 |
| **LLM** F1 rel | 0.040 | 0.089 | +0.049 |
| **Hybrid** P ent | 0.634 | **0.851** | **+0.217** |
| **Hybrid** R ent | 0.856 | 0.775 | −0.081 |
| **Hybrid** F1 ent | 0.728 | **0.806** | **+0.078** |
| **Hybrid** F1 rel | 0.036 | 0.089 | +0.053 |

### Umbrales (P ent ≥ 0.85 · R ent ≥ 0.70 · F1 ent ≥ 0.75 · P rel ≥ 0.75 · R rel ≥ 0.60)

| Modo | P ent | R ent | F1 ent | P rel | R rel | Entidades | Relaciones |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| heuristic | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL | FAIL |
| llm | ✓ | ✗ | ✗ | ✗ | ✗ | FAIL | FAIL |
| **hybrid** | ✓ | ✓ | ✓ | ✗ | ✗ | **PASS** | FAIL |

**El modo hybrid supera los tres umbrales de entidad** (P 0.851, R 0.775, F1 0.806). Las
relaciones siguen por debajo del umbral (F1 0.089) pese a mejorar 2.5×.

---

## 3. Métricas por fuente (hybrid mejorado)

| Fuente | F1 ent | F1 rel |
|---|---:|---:|
| source_transcript_clean_01 | 0.880 | **0.444** |
| source_transcript_session_02 | 0.923 | 0.000 |
| source_transcript_asr_01 | 0.714 | 0.000 (0 rel en GT) |
| source_notes_01 | 0.737 | 0.000 |
| source_resolution_01 | 0.778 | 0.000 |

`clean_01` muestra el efecto pleno de las mejoras de relaciones (F1 rel 0 → 0.444):
MEMBER_OF por apellido + resolución de alias + corrección de dirección.

---

## 4. Reproducibilidad (`temperature=0`, `seed=42`, 3 runs)

Varianza de F1 de entidades = **0.0** en todas las fuentes y modos (llm/notes: 0.0007).
Extracción de entidades perfectamente reproducible.

---

## 5. Filtro híbrido (ejemplo clean_01)

| Antes (únicas) | Kept | Filtradas | Regla A (acuerdo) | Regla B (solo LLM) | Regla C (heurístico) |
|---:|---:|---:|---:|---:|---:|
| 19 | 13 | 6 | 7 | 2 | 4 |

Las 6 entidades filtradas eran solo-heurísticas no corroboradas (single-token/weak). Cada
eliminación se registra en `hybrid_filter_stats.json` con su motivo. Esto elevó la precisión
de entidades de 0.634 a 0.851.

---

## 6. Autoaprobación (E2E, hybrid, clean_01 + asr_01)

| Fuente | auto_approve | needs_review | auto_reject | P autoaprob. entidades | Rel. autoaprob. | Sin evidencia |
|---|---:|---:|---:|---:|---:|---:|
| clean_01 | 11 | 5 | 1 | 0.909 | 0 | 0 |
| asr_01 | 9 | 11 | 1 | 0.667 | 0 | 0 |
| **Total** | **20** | **16** | **2** | **0.800** | **0** | **0** |

- **Relaciones autoaprobadas = 0** — el quality gate funciona end-to-end. ✓
- Candidatos sin evidencia autoaprobados = 0. ✓
- Precisión de autoaprobación de entidades = 0.80 (< 0.95). ✗ (ASR arrastra la media; clean_01 = 0.909).

Por eso la ingesta se plantea **con revisión humana total**, no con autoaprobación pura.

---

## 7. Ampliación del corpus (Prioridad 2.1)

Se añadieron 2 fuentes con los tipos que faltaban, ground truth **pase 3** congelado
(`annotation_pass=3`, `reviewed=true`):

| Fuente | Tipo | Segs | Entidades | Relaciones+ |
|---|---|---:|---:|---:|
| source_narrative_01 | narrativo | 2 | 8 | 5 |
| source_manual_01 | manual | 2 | 8 | 6 |

Corpus total: **7 fuentes, 72 entidades, 27 relaciones, 13 segmentos**. Manifest ampliado en
`corpus-manifest-v2.json` (conserva el v1 como baseline). El run mejorado de este documento
usa el corpus de 5 fuentes para la comparación justa; el corpus de 7 fuentes queda listo para
la evaluación confirmatoria.

---

## 8. Seguridad

| Métrica | Inicio | Fin |
|---|---:|---:|
| Nodos Neo4j | 199 | 199 |
| Relaciones Neo4j | 140 | 140 |
| `S9K_ALLOW_REAL_INGEST` | unset | unset |

Neo4j intacto. Resolución = solo lectura. Ninguna ingesta ejecutada.

---

## 9. Recomendación por tipo de fuente (mejorado)

| Tipo de fuente | Modo recomendado | Entidades | Relaciones |
|---|---|---|---|
| Transcripción limpia / sesión | **hybrid** (F1 0.88–0.92) | ACEPTADO con revisión humana total | parcial (clean F1 0.44) |
| Transcripción ASR | hybrid (F1 0.71) | ACEPTADO con revisión humana total | sin relaciones en GT |
| Notas | hybrid (F1 0.74) | ACEPTADO con revisión humana total | débil |
| Resolución/duplicados | hybrid (F1 0.78) | ACEPTADO con revisión humana total + dedup | débil |
| Relaciones (todas) | — | — | NO ACEPTADO para autoaprobación (excluidas por gate) |

---

## 10. Dictamen

```
Prioridad 2.1: PARCIAL — MEJORA DEMOSTRADA, UMBRALES NO COMPLETOS
Primera ingesta controlada: DESBLOQUEADA PARA ENTIDADES CON REVISIÓN HUMANA TOTAL
```

**Justificación:**
- **Entidades:** el modo hybrid supera los tres umbrales (P 0.851, R 0.775, F1 0.806). Calidad de entidades ACEPTADA.
- **Relaciones:** F1 0.089 sigue por debajo de 0.60 → NO aceptadas; excluidas de autoaprobación por el quality gate (0 relaciones autoaprobadas, verificado E2E).
- Reproducibilidad total (varianza 0.0) y Neo4j intacto.

La primera ingesta de **entidades** puede desbloquearse **solo bajo estas condiciones**
(todas verificadas o estipuladas):
1. Modo hybrid (supera umbrales de entidad). ✓
2. Relaciones excluidas de autoaprobación (quality gate). ✓
3. Revisión humana **total** del `review_queue` antes de escribir.
4. Backup de producción vigente (docs/32) y rollback documentado.
5. Fuente pequeña, `--dry-run` previo y revisión completa del `approved_payload`.
6. `S9K_ALLOW_REAL_INGEST` permanece bajo doble guard.

**No se ejecuta ninguna ingesta en esta tarea.**

### Fase de mejora siguiente (relaciones)
1. Elevar recall de relaciones (más few-shot por tipo; corpus con relaciones explícitas).
2. Subir autoaprobación de entidades ASR ≥ 0.95 (normalización fonética antes de decidir).
3. Ejecutar el benchmark sobre el corpus de 7 fuentes (evaluación confirmatoria).

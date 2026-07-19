# Tablero del Programa Secuencial

`AUTHORIZED_BLOCK = BLOQUE_4`

El Organizador solo puede lanzar agentes del bloque cuyo identificador coincide con
`AUTHORIZED_BLOCK`. El avance a `NEXT_BLOCK` requiere el checkpoint formal:

```text
BLOCK_STATUS       = MERGED_AND_MAIN_GREEN
SUPERVISOR         = CONFORME
POST_MERGE_VALIDATION = PASS
PRODUCTION         = INTACT
RC6_CANDIDATE      = 15ae1d4
```

## Estado de bloques

| Bloque | Objetivo | Rama | Estado | PR | Supervisor | CI PR | CI main | Checkpoint |
|---|---|---|---|---|---|---|---|---|
| 0 | Auditoría y coordinación (docs) | `docs/sequential-quality-gate-program` | MERGED_AND_MAIN_GREEN | #85 → e32d44e | CONFORME | ✅ | ✅ | `main e32d44e` |
| 1 | Calibración Ollama en sombra | `calibration/relations-ollama-shadow-v1` | MERGED_AND_MAIN_GREEN | #86 → c661aec | CONFORME | ✅ | ✅ | `main c661aec` |
| 2 | Calibración NVIDIA en sombra | `calibration/relations-nvidia-shadow-v1` | MERGED_AND_MAIN_GREEN | #87 → 0c407ba | CONFORME (+ Seguridad) | ✅ | ✅ | `main 0c407ba` |
| 3 | Normalización de predicados | `feat/relation-predicate-normalization-v1` | MERGED_AND_MAIN_GREEN | #88 → b44bdda | CONFORME | ✅ | ✅ | `main b44bdda` |
| 4 | Mejora de temporalidad | `feat/relation-temporality-calibration-v1` | IMPLEMENTING | — | — | — | — | — (sin merge aún) |
| 5 | Rumores / estado epistémico | `feat/relation-epistemic-calibration-v1` | PENDING | — | — | — | — | — |
| 6 | Ensemble calibrado | `feat/relation-calibrated-ensemble-v1` | PENDING | — | — | — | — | — |
| 7 | Reejecución del benchmark | `test/relation-calibrated-benchmark-v1` | PENDING | — | — | — | — | — |
| 8 | Reducción de revisión humana | `feat/relation-review-policy-calibration-v1` | PENDING | — | — | — | — | — |
| 9 | QA transversal y cierre | `test/relation-calibration-final-quality-v1` | PENDING | — | — | — | — | — |

## Semáforo de dependencias externas

| Bloque | Dependencia externa | Estado (2026-07-19) |
|---|---|---|
| 1 | Endpoint Ollama accesible | ✅ `localhost:11434` responde 200 · modelo `qwen2.5:7b` |
| 2 | `S9K_NVIDIA_API_KEY` cargada de forma segura | ❌ No presente → riesgo de `BLOQUEADO` |
| 3–9 | Corpus sintético del benchmark | ✅ Presente (16 fuentes + fixtures); corpus privado prohibido |

## Log de checkpoints

_(vacío — se rellena a medida que cada bloque cierra con `MERGED_AND_MAIN_GREEN`)_

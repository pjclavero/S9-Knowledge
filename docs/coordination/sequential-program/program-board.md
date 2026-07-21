# Tablero del Programa Secuencial

**ESTADO FINAL:** `PROGRAMA COMPLETADO` — 10/10 bloques mergeados a main  
**Última actualización:** 2026-07-21  
**Validación final:** Bloque 9 QA transversal ✅ CONFORME  

```text
BLOCK_STATUS       = MERGED_AND_MAIN_GREEN (todos)
SUPERVISOR         = CONFORME (todos los bloques)
POST_MERGE_VALIDATION = PASS (Bloque 9 cierra con 48 tests)
PRODUCTION         = INTACT (sin RC6, sin despliegue)
HALLAZGO_MATERIAL  = Reducción de revisión humana NO justificada; cuello de botella = anclaje de evidencia
```

## Estado de bloques (síntesis final)

| Bloque | Objetivo | Rama | Estado | PR | Supervisor | Especialista | CI | Checkpoint |
|---|---|---|---|---|---|---|---|---|
| 0 | Auditoría y coordinación (docs) | `docs/sequential-quality-gate-program` | MERGED_AND_MAIN_GREEN | #85 | CONFORME | — | ✅ | e32d44e |
| 1 | Calibración Ollama en sombra | `calibration/relations-ollama-shadow-v1` | MERGED_AND_MAIN_GREEN | #86 | CONFORME | — | ✅ | c661aec |
| 2 | Calibración NVIDIA en sombra | `calibration/relations-nvidia-shadow-v1` | MERGED_AND_MAIN_GREEN | #87 | CONFORME | ✅ Seguridad | ✅ | 0c407ba |
| 3 | Normalización de predicados | `feat/relation-predicate-normalization-v1` | MERGED_AND_MAIN_GREEN | #88 | CONFORME | — | ✅ | b44bdda |
| 4 | Mejora de temporalidad | `feat/relation-temporality-calibration-v1` | MERGED_AND_MAIN_GREEN | #89 | CONFORME | — | ✅ | 1a08eb3 |
| 5 | Rumores / estado epistémico | `feat/relation-epistemic-calibration-v1` | MERGED_AND_MAIN_GREEN | #90 | CONFORME | — | ✅ | 63a80ae |
| 6 | Ensemble calibrado explicable | `feat/relation-calibrated-ensemble-v1` | MERGED_AND_MAIN_GREEN | #91 | CONFORME | — | ✅ | 1df631d |
| 7 | Reejecución del benchmark (4 rondas) | `test/relation-calibrated-benchmark-v1` | MERGED_AND_MAIN_GREEN | #92 | CONFORME | — | ✅ | 2df3a69 |
| 8 | Política de revisión fail-closed | `feat/relation-review-policy-calibration-v1` | MERGED_AND_MAIN_GREEN | #93 | CONFORME | ✅ Seguridad | ✅ | 1de7645 |
| 9 | QA transversal y cierre | `test/relation-calibration-final-quality-v1` | MERGED_AND_MAIN_GREEN | — | CONFORME | ✅ Seguridad | ✅ | 1de7645 |

## Semáforo de dependencias externas

| Bloque | Dependencia | Estado (2026-07-21) | Resolución |
|---|---|---|---|
| 1 | Endpoint Ollama accesible | ✅ `localhost:11434` responde 200 · `qwen2.5:7b` | Medido en B7 §12 |
| 2 | `S9K_NVIDIA_API_KEY` | ✅ Presente (medición aislada 2026-07-21) | Medido en B7 §12A; no circula en producción |
| 3–9 | Corpus sintético | ✅ 16 fuentes, 54 relaciones, SHA verificado | En repositorio; ground truth versionado |

## Log de checkpoints (cierre del programa)

| Bloque | PR | SHA merge | Supervisor | Checkpoint | Fecha | Rondas | Escalado |
|---|---|---|---|---|---|---|---|
| 0 | #85 | e32d44e | CONFORME | main e32d44e | 2026-07-17 | 1 | — |
| 1 | #86 | c661aec | CONFORME | main c661aec | 2026-07-17 | 1 | — |
| 2 | #87 | 0c407ba | CONFORME | main 0c407ba | 2026-07-18 | 1 | — |
| 3 | #88 | b44bdda | CONFORME | main b44bdda | 2026-07-18 | 1 | — |
| 4 | #89 | 1a08eb3 | CONFORME | main 1a08eb3 | 2026-07-19 | 1 | — |
| 5 | #90 | 63a80ae | CONFORME | main 63a80ae | 2026-07-19 | 1 | — |
| 6 | #91 | 1df631d | CONFORME | main 1df631d | 2026-07-20 | 1 | — |
| 7 | #92 | 2df3a69 | CONFORME | main 2df3a69 | 2026-07-20 | **4** | **Sí (ronda 2)** |
| 8 | #93 | 1de7645 | CONFORME | main 1de7645 | 2026-07-21 | 1 | — |
| 9 | — | — | CONFORME | main 1de7645 | 2026-07-21 | 1 | — |

**Síntesis:**
- **Total de PRs mergeadas:** 9 (#85–#93)
- **Bloques con escalado a Opus:** 1 (Bloque 7, ronda 2 — endurecimiento de gates)
- **Bloques con especialista de seguridad:** 3 (B2, B8, B9)
- **Tests transversales de cierre (B9):** 48 (todos passed; 30+ mutantes cazados)

## Decisiones finales documentadas

| Decisión | Justificación | Referencia |
|---|---|---|
| **RC6 NO se crea ni se despliega** | Hallazgo: cobertura 0% de política de revisión (offline); reducción de revisión NO justificada | `program-closure-report.md` §3.4 |
| **Producción íntegra** | Garantía de sombra verificada: P/R/F1 idénticos con/sin proveedores (Ollama 97.8s, NVIDIA 29.4s) | `program-closure-report.md` §3.3 |
| **Cuello de botella documentado** | Anclaje de evidencia (`evidence_text`, offsets correctos) es el límite; requiere rework de prompts | `program-closure-report.md` §3.4 |
| **Seguimientos sin bloqueo** | Medición futura con proveedores + endurecimiento AST + corrección de prompts | `program-closure-report.md` §7 |

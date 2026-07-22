# 09 — Resultados V4 (hybrid staged engine)

Flags: `hybrid_stages` (dict de etapas booleanas), `hybrid_top_k`,
`hybrid_cross_sentence`. `hybrid_stages=None` => camino clasico byte-identico a la
base. Etapas: `structural_hypothesis, predicate_direction, evidence, verification,
temporal_epistemic, consensus` (todas True por defecto).

## Configuraciones ejecutadas (C1, misma vara)
| config | pair_F1 | pair_R | evidence_correct | cand | p50/p95 ms |
|---|---|---|---|---|---|
| v4_hybrid_default (`{}`) | 0.811 | 0.796 | **0.907** | 52 | 2.56 / 7.09 |
| v4_cross_sentence (repr) | 0.525 | **0.963** | 0.635 | 144 | 6.94 / 18.87 |
| v4_ablate_evidence | 0.811 | 0.796 | **0.023** | 52 | 2.72 / 7.26 |
| base (referencia) | 0.811 | 0.796 | 0.907 | 52 | 2.82 / 6.13 |

## Hallazgos
- **Compatibilidad demostrada**: `hybrid_default ({})` reproduce la base **byte a
  byte** en todas las metricas y en los 52 candidatos. La ruta hibrida en su default
  no altera nada (determinism 1.0).
- **Config representativa `cross_sentence`**: activar emparejamiento a nivel de
  segmento recupera relaciones interfrase => recall 0.796 -> **0.963**, PERO genera
  144 candidatos (vs 52), disparando falsos positivos: precision 0.827 -> 0.361 y
  F1 0.811 -> 0.525. **Trade-off, no mejora neta** en este corpus; util solo si se
  añade un filtro de precision (p.ej. `top_k`).
- **Ablacion por etapa (documenta el 0.907 -> 0.023)**: apagar la etapa `evidence`
  (+`verification`) colapsa `evidence_correct` a **0.023** e IoU a 0.188. Esto NO es
  un bug de medicion ni una regresion del motor: es, literalmente, **apagar la etapa
  que produce la evidencia**; los candidatos quedan sin anclaje de evidencia y por eso
  la evidencia se desploma. La existencia/estructura se mantiene (F1 0.811) porque no
  dependen de esa etapa. Es el resultado esperado de la ablacion y confirma que la
  etapa de evidencia es la responsable de ese eje.

Ablacion completa del propio V4 (referencia, del autor): `data-engine/app/artifacts/
pr95-variants/v4/ablation_table.md` — coherente con lo medido aqui de forma
independiente.

## Veredicto V4 (independiente)
El motor por etapas es una **infraestructura correcta y segura** (default = base byte
a byte, determinista, offline). Aporta palancas (cross_sentence, top_k, ablaciones)
pero **ninguna configuracion mejora el F1 neto** sobre la base en C1: cross_sentence
cambia el balance P/R sin ganar F1. Su valor es de plataforma/experimentacion, no una
mejora de calidad lista para produccion en este corpus.

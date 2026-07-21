# PR#95 · V1 — Anclaje CONSERVADOR de evidencia (Equipo V1)

- **SHA base:** `92583f4` (exp(pr95-base): corrige contrato DOCUMENTO/ID del evaluador externo, P0).
- **Rama:** `exp/pr95-v1-conservative-anchor`.
- **Editor:** Opus (V1). Worktree exclusivo `.claude/worktrees/pr95-v1`.
- **Flag:** `PipelineConfig.evidence_anchor_mode` — default `"span"` (comportamiento
  histórico, sin cambios). El nuevo modo `"conservative"` se activa SOLO por config.

## Qué es esto

Un modo de anclaje de evidencia alternativo, **detrás de flag y apagado por
defecto**. En vez del span mecánico `min(starts)..max(ends)`, el modo
`conservative`:

1. parte de los límites de **frase** (`signals._sentence_bounds`),
2. **estrecha a la cláusula segura** que contiene ambas menciones (separadores
   `,;:` vía `signals._clause_index`),
3. **reincorpora** —si caen fuera de esa cláusula pero dentro de la frase— la
   **negación**, la **atribución** y las marcas **temporal/epistémica** relevantes,
4. hace **fallback seguro al span** si el cálculo diera algo vacío/incoherente,
5. mantiene el invariante de coherencia `seg_text[start:end] == evidence_text`.

## Veredicto propuesto

**NO CONFORME como mejora activable.** La implementación es correcta, segura y no
regresa el camino por defecto, pero la **hipótesis queda REFUTADA** sobre el corpus
B1: el anclaje conservador **empeora** la métrica de evidencia (evidence_correct
0.907 → 0.837; mean IoU 0.816 → 0.792) sin mover F1/precision/recall. Ver
[`results.md`](results.md). El flag debe permanecer **OFF**; el modo se conserva
como base experimental documentada, no como cambio de comportamiento.

## Ficheros

- Implementación: `data-engine/app/relations/pipeline.py`
  (`_conservative_anchor`, `_clause_bounds_for_range`, `_find_all_cues`,
  `_ATTRIBUTION_CUES`, `_EPISTEMIC_CUES`, `evidence_anchor_mode` en `PipelineConfig`,
  wiring en `_build_candidate` / `_process_pair`).
- Tests: `data-engine/app/tests/test_pr95_v1_conservative_anchor.py`.
- A/B: `data-engine/app/tools/relation_anchor_ab.py`.
- Artefacto A/B: `artifacts/pr95-variants/v1/ab_span_vs_conservative.json`.
- Docs: este directorio (`design.md`, `test-plan.md`, `results.md`, `security.md`,
  `limitations.md`).

## FABLE

No aplica: V1 es el carril del **editor**. No se activó FABLE.

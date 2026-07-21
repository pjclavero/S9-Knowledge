# PR#95 V4 — Plan de pruebas

SHA base: `92583f4`. Suite nueva: `data-engine/app/tests/test_pr95_v4_hybrid_staged.py` (24 tests).

## Que se prueba (y como falla de verdad)

### Compatibilidad
- `test_default_none_is_classic_and_identical_hash` — `hybrid_stages=None` da
  `result_hash` IDENTICO a la base; la config canonica no lleva claves hibridas.
- `test_empty_dict_reproduces_base_candidates` — `hybrid_stages={}` da
  results/documents/summary IDENTICOS a la base (falla si el motor altera el candidato).
- `test_hybrid_is_deterministic` — misma entrada+config -> mismo `result_hash`.
- `test_contract_stays_20_fields_under_hybrid` — el candidato sigue teniendo 20 campos.

### Ablation por etapa (una cada vez)
- `test_ablation_predicate_direction_off_generic` — predicados especificos -> `RELATED_TO`.
- `test_predicate_direction_on_sets_specific_direction` — MEMBER_OF con direccion
  `SUBJECT_TO_OBJECT`; OFF -> `UNDIRECTED`.
- `test_ablation_temporal_epistemic_off_is_security_regression` — RUMORED -> ASSERTED.
- `test_ablation_evidence_off_degrades_span` — span completo -> span solo-sujeto.
- `test_ablation_verification_rejects_incomplete_coverage` — con evidencia
  degradada: verificacion ON rechaza (0 candidatos), OFF acepta (1 candidato).
- `test_ablation_consensus_off_drops_consensus` — consenso presente -> `None`.

### Top-k / anti-explosion
- `test_topk_bounds_candidates` — `top_k=1` acota a 1 candidato.
- `test_candidate_explosion_is_bounded` — 12 menciones, `top_k=5`: len(salida) <= 5.
- `test_topk_keeps_highest_score_first` — el recorte conserva las de mayor score.
- `test_rank_identity_when_topk_disabled` — `top_k<=0`: identidad (sin truncar).

### Inter-frase
- `test_inter_sentence_requires_flag` — menciones en frases distintas: base = 0,
  `hybrid_cross_sentence=True` >= 1.

### Rendimiento
- `test_performance_bounded` — 30 menciones + `top_k=20` en < 10 s, salida <= 20.

### Fallback stdlib
- `test_stdlib_fallback_no_strong_parser_required` — proveedor de sintaxis
  `heuristic`; `spacy`/`stanza` no cargados.

### Config fail-closed
- `test_unknown_stage_flag_fails_closed` — etapa desconocida -> `PipelineError`.
- `test_non_bool_stage_flag_fails_closed` — flag no-bool -> `PipelineError`.
- `test_resolve_stages_defaults_are_base` — defaults = todo True.

### Abstracciones puras (razonamiento vs evidencia)
- `test_evidence_bundle_separates_literal_from_reasoning` — `evidence_text` es la
  cita verbatim; el "por que" vive en `reasoning`, no en la cita.
- `test_segment_reference_is_redacted` — guarda `text_len`, no el texto.
- `test_hypothesis_score_bounds_validated` / `test_evidence_bundle_rejects_inverted_offsets`.

## Verificacion anti-gaming (mutacion + revert, sin residuo)

1. **top-k acotado** — en `stage_rank_mentions` se ignora `top_k` (no acota).
   Resultado: fallan `test_topk_bounds_candidates`, `test_candidate_explosion_is_bounded`
   (`assert 66 <= 5`) y `test_topk_keeps_highest_score_first`. Revertido.
2. **compatibilidad por defecto** — en el constructor staged se cambia
   `validation_flags` a `["dry_run","hybrid"]`. Resultado: falla
   `test_empty_dict_reproduces_base_candidates`. Revertido.

Sin `skip`/`xfail`, sin umbrales bajados.

## Suites verdes obligatorias

```
cd data-engine/app
python3 -m pytest tests/ -k relation -q                                  # 903 passed
python3 -m pytest tests/test_relation_calibration_final_quality_block9.py -q  # 48
python3 -m pytest tests/test_relation_external_document_contract.py -q        # 13 (P0)
python3 -m pytest tests/test_pr95_v4_hybrid_staged.py -q                      # 24
```

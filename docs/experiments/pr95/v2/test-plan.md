# V2 · Plan de pruebas

**Base SHA:** `92583f4`
**Suite específica:** `data-engine/app/tests/test_pr95_v2_deterministic_realignment.py` (27 tests)

Ejecución (desde `data-engine/app`):

```
python3 -m pytest tests/test_pr95_v2_deterministic_realignment.py -q
```

## 1. Matriz de casos requeridos

| Caso requerido | Test |
|----------------|------|
| NFC/NFD (realinea acentos, recomputa offsets al texto real) | `test_unit_nfc_nfd_realigns_and_recomputes_offsets`, `test_integration_on_realigns_nfd_accepts` |
| Comillas (« » vs " ") | `test_unit_quotes_typographic_realign` |
| Espacios (colapso / NBSP) | `test_unit_whitespace_collapse_and_nbsp` |
| CRLF vs LF | `test_unit_crlf_vs_lf` |
| Repetición (elige ocurrencia correcta) | `test_unit_repetition_hint_disambiguates` |
| Repetición sin hint (rechaza) | `test_unit_repetition_without_hint_is_ambiguous` |
| Paráfrasis leve (realinea) | `test_unit_slight_paraphrase_realigns_above_threshold` |
| Paráfrasis fuerte (rechaza) | `test_unit_strong_paraphrase_rejected_below_threshold`, `test_integration_on_strong_paraphrase_rejected` |
| AMBIGÜEDAD: dos alineamientos equivalentes → rechazo | `test_unit_ambiguity_two_equivalent_alignments_rejected`, `test_integration_on_ambiguous_still_rejected` |
| PROMPT INJECTION | `test_security_prompt_injection_in_evidence_cannot_escape`, `test_security_realignment_only_returns_literal_doc_slices` |
| FALSE ALIGNMENT (umbral respetado) | `test_security_false_alignment_respects_threshold` |
| Texto truncado | `test_unit_truncated_text_rejected_or_literal` |
| INVARIANTE: evidencia final siempre literal | `_assert_literal` + `test_integration_invariant_literal_holds_across_cases` |
| default OFF (idéntico a base) | `test_integration_off_matches_base_rejection`, `test_no_regression_flag_off_equals_base`, `test_integration_realigned_flag_default_false_when_off` |
| Payload grande (cota) | `test_security_large_payload_bounded_rejected` |
| Unicode Bidi | `test_security_unicode_bidi_stripped_no_spoof` |
| Mapa reversible (roundtrip) | `test_unit_reversible_map_roundtrip` |

## 2. Suites que deben seguir verdes

```
python3 -m pytest tests/ -k "relation or external" -q
python3 -m pytest tests/test_relation_calibration_final_quality_block9.py -q
python3 -m pytest tests/test_relation_external_document_contract.py -q
```

Resultados en [results.md](results.md).

## 3. Verificación anti-gaming (mutación + revert)

Se mutaron **2 invariantes** de `evidence_realignment.py`, se confirmó que la suite falla,
y se revirtió sin residuo (constantes y reglas restauradas a su valor original):

- **Mutación 1 — umbral:** `REALIGN_SCORE_THRESHOLD` 0.82 → 0.05.
  Fallan 4 tests: `test_unit_strong_paraphrase_rejected_below_threshold`,
  `test_security_prompt_injection_in_evidence_cannot_escape`,
  `test_security_false_alignment_respects_threshold`,
  `test_integration_on_strong_paraphrase_rejected`.
- **Mutación 2 — regla de ambigüedad:** desactivar el rechazo por empate (peldaño exacto
  devuelve siempre la primera ocurrencia). Fallan 2 tests:
  `test_unit_repetition_without_hint_is_ambiguous`,
  `test_unit_ambiguity_two_equivalent_alignments_rejected`.

Tras revertir, la suite vuelve a **27 passed** y `REALIGN_SCORE_THRESHOLD = 0.82` /
reglas de ambigüedad intactas (verificado por `grep`). **Sin skip / xfail / umbral bajado.**

## 4. Banco A/B offline

`tests/pr95_v2_ab_benchmark.py` ejecuta el evaluador real (proveedor falso, sin red) sobre
11 fixtures parafraseados, en modo OFF y ON, y escribe métricas reales en
`artifacts/pr95-variants/v2/`. Ver [results.md](results.md).

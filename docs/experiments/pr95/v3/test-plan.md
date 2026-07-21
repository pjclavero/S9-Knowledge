# V3 · Plan de pruebas

SHA base: `92583f4`. Todo OFFLINE (proveedor falso inyectado), determinista, sin red.

## Suite específica — `tests/test_pr95_v3_fragment_selection.py` (20 tests, todos verdes)

| Requisito | Test |
|---|---|
| Estabilidad de IDs (mismo doc → mismos IDs) | `test_ids_stable_same_document` |
| Cambio de normalización trivial no cambia el ID/hash del fragmento | `test_trivial_normalization_keeps_fragment_content_hash` |
| NFC/NFD no rompen el mapeo | `test_nfc_nfd_same_content_hash` |
| Dos fragmentos (evidencia compuesta coherente) | `test_two_fragments_compose_literal_span` |
| Fragmento inexistente → rechazo | `test_unknown_fragment_id_rejected`, `test_empty_fragment_ids_rejected` |
| Solapamientos (no se solapan) | `test_fragments_do_not_overlap` |
| Orden de fragment_ids irrelevante | `test_fragment_order_independent` |
| Documento largo (muchos fragmentos, IDs únicos) | `test_long_document_unique_ids` |
| Token budget (cota determinista) | `test_token_budget_caps_deterministically` |
| Fragmentación adversarial (texto hostil) | `test_adversarial_text_preserves_literality` |
| INVARIANTE: reconstrucción siempre literal | `test_invariant_reconstruction_is_literal_substring` (5 params) |
| End-to-end flag ON acepta selección | `test_evaluate_fragment_protocol_accepts_selection` |
| Flag ON rechaza ID inexistente | `test_evaluate_fragment_protocol_rejects_unknown_id` |
| DEFAULT OFF idéntico a la base | `test_default_off_uses_classic_protocol`, `test_default_off_fragment_verdict_is_invalid_classically` |

## Suites verdes obligatorias

```
cd data-engine/app
python3 -m pytest tests/ -k "relation or external" -q          # 1028 passed, 433 deselected
python3 -m pytest tests/test_relation_calibration_final_quality_block9.py -q   # 48 passed
python3 -m pytest tests/test_relation_external_document_contract.py -q         # 13 passed (base P0)
```

## Verificación anti-gaming (mutación + revert, sin skip/xfail)

1. **Estabilidad de ID:** `normalize_for_identity` sin colapso de espaciado →
   `test_trivial_normalization_keeps_fragment_content_hash` **FALLA**
   (`43ea90e1de6b9e15 != fa5b04da60d93c9b`). Revertido.
2. **Literalidad de reconstrucción:** `reconstruct_evidence` con `start += 1` →
   7 tests de literalidad **FALLAN**. Revertido.

Tras revertir: 20/20 verdes, sin residuo (`grep MUTANTE` vacío).

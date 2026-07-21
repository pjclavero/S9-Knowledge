# V3 · Resultados y métricas reales

SHA base: `92583f4`. Cifras **medidas** ejecutando el código real, sin red. No se
inventa ninguna cifra.

## Suites

| Suite | Resultado |
|---|---|
| `tests/test_pr95_v3_fragment_selection.py` | **20 passed** |
| `tests/ -k "relation or external"` | **1028 passed, 433 deselected** |
| `tests/test_relation_calibration_final_quality_block9.py` | **48 passed** |
| `tests/test_relation_external_document_contract.py` (base P0) | **13 passed** |

## Benchmark A/B offline

Script: `artifacts/pr95-variants/v3/ab_benchmark.py` · Resultados:
`artifacts/pr95-variants/v3/results.json` · Corpus: 10 casos sintéticos deterministas.

**Banco sintético:** modela el fallo real de los LLM con offsets.
- *Clásico (da offsets):* 1/3 parafrasea la cita (deja de ser literal), 1/3
  desalinea offsets (+2), 1/3 responde exacto.
- *Fragmentos (elige IDs):* selecciona el fragmento de la frase que sustenta la
  relación; nunca produce offsets libres.

| Métrica | Clásico (offsets) | Fragmentos (V3) |
|---|---|---|
| acceptance_rate | **0.30** | **1.00** |
| literal_evidence_rate | **1.00** | **1.00** |
| invalid_rate | **0.70** | **0.00** |
| ambiguity_rate | 0.00 | 0.00 |

Lectura:
- `literal_evidence_rate = 1.0` en ambos protocolos (medido sobre las evidencias
  ACEPTADAS): el filtro de literalidad nunca deja pasar evidencia no literal. Es la
  garantía de seguridad, no una ventaja competitiva.
- La ventaja de V3 está en `acceptance_rate` (1.00 vs 0.30) y `invalid_rate`
  (0.00 vs 0.70): al eliminar la necesidad de que el modelo produzca offsets, las
  respuestas correctas dejan de rechazarse por `offsets_invalidos` /
  `evidencia_inexistente`. La cifra concreta depende del banco sintético; el efecto
  cualitativo (V3 elimina el modo de fallo de offsets) es estructural.

## Anti-gaming (mutación → fallo → revert)

- Mutante 1 (estabilidad ID): 1 test falla. Revertido.
- Mutante 2 (literalidad reconstrucción): 7 tests fallan. Revertido.
- Tras revertir: 20/20 verdes, sin residuo. Sin skip/xfail/umbral bajado.

## Veredicto propuesto: **CONFORME**

- Objetivo cumplido: protocolo versionado de fragmentos, offsets reconstruidos por el
  sistema, literalidad garantizada por construcción.
- Flag default OFF → comportamiento idéntico a la base (2 tests lo verifican).
- Sin red, sin escritura, sin migrar el contrato persistente.
- Suites obligatorias verdes; anti-gaming demostrado.

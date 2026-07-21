# Resultados — PR#95 V1

SHA base `92583f4`. Todas las cifras provienen de ejecuciones REALES; no hay
valores inventados.

## Suites (recuentos reales)

| Suite | Resultado |
|-------|-----------|
| `tests/ -k relation` | **903 passed**, 552 deselected |
| `tests/test_relation_calibration_final_quality_block9.py` | **48 passed** |
| `tests/test_relation_external_document_contract.py` (P0) | **13 passed** |
| `tests/test_pr95_v1_conservative_anchor.py` (nuevo) | **14 passed** |

## A/B real — `span` (base) vs `conservative`

Runner real `relations.benchmark.runner`, modo `baseline1` (heurístico puro,
offline, sin proveedores), corpus B1 verificado por sha256. Umbral IoU = 0.5.
Fuente: `artifacts/pr95-variants/v1/ab_span_vs_conservative.json`.

| metric | span | conservative |
| --- | --- | --- |
| TP | 43 | 43 |
| FP | 9 | 9 |
| FN | 11 | 11 |
| F1 | 0.8113 | 0.8113 |
| precision | 0.8269 | 0.8269 |
| recall | 0.7963 | 0.7963 |
| mean IoU | **0.8164** | **0.7918** |
| evidence_correct | **39/43 (0.9070)** | **36/43 (0.8372)** |
| offsets_correct | 40/43 (0.9302) | 40/43 (0.9302) |
| simple_relations.evidence | **28/30 (0.9333)** | **26/30 (0.8667)** |

## Lectura

- **F1 / precision / recall / TP / FP / FN no cambian**: el anclaje solo afecta al
  span de evidencia, no al emparejamiento de pares (por diseño). Correcto.
- **La evidencia EMPEORA** con `conservative`: `evidence_correct` cae de 0.907 a
  0.837 (−3 aciertos) y `mean IoU` de 0.8164 a 0.7918. `offsets_correct` (IoU>0) se
  mantiene.
- **Causa raíz**: en el corpus B1 el GT es típicamente una **frase-predicado muy
  ajustada** (media ~42 chars). El anclaje por cláusula:
  - en frases de **una sola cláusula** (sin `,;:`) iguala la cláusula a la frase e
    incluye texto que el GT recorta (p.ej. aposiciones "de Valmyr", colas locativas
    "en la Batalla del Vado" que pertenecen a OTRA relación del mismo par-vecino);
  - la reincorporación de marcadores ayuda en casos con negación/atribución en
    cláusula adyacente, pero esos casos son minoría frente a las cláusulas anchas.
  El balance neto es negativo sobre este corpus.

## Verdict propuesto

**NO CONFORME** como mejora activable: la hipótesis queda **refutada** en B1. La
implementación es correcta, determinista, segura y con el default intacto, por lo
que se conserva **detrás del flag OFF** como base experimental documentada. El
revisor independiente decide el veredicto final.

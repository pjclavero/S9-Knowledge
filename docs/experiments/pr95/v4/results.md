# PR#95 V4 — Resultados (medicion REAL)

SHA base: `92583f4`. Todas las cifras se obtienen con el runner REAL
(`relations.pipeline.run_pipeline`) sobre el **corpus B1 real** (16 fuentes,
54 relaciones de ground truth), comparado con el GT via
`relations.benchmark.matching` + `relations.benchmark.metrics`. **No hay cifras
inventadas.** Artefactos: `data-engine/app/artifacts/pr95-variants/v4/`.

## Suites (recuentos reales)

| Suite | Resultado |
|-------|-----------|
| `tests/ -k relation` | **903 passed**, 562 deselected |
| `test_relation_calibration_final_quality_block9.py` | **48 passed** |
| `test_relation_external_document_contract.py` (P0) | **13 passed** |
| `test_pr95_v4_hybrid_staged.py` (nueva) | **24 passed** |

## Tabla de ABLATION (corpus B1, offline)

| config | n_preds | existence_f1 | strict_f1 | evidence_correct | offsets_correct | predicate_correct | direction_correct | epistemic_correct | elapsed_ms |
|---|---|---|---|---|---|---|---|---|---|
| base (hybrid=None) | 52 | 0.8113 | 0.2075 | 0.9070 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 50.9 |
| hybrid_default ({}) | 52 | 0.8113 | 0.2075 | 0.9070 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 56.6 |
| ablate:predicate_direction | 52 | 0.8113 | **0.0000** | 0.9302 | 0.9535 | **0.0000** | **0.1395** | 0.8605 | 50.5 |
| ablate:temporal_epistemic | 52 | 0.8113 | 0.2075 | 0.9070 | 0.9302 | 0.2558 | 0.6279 | **0.8140** | 49.8 |
| ablate:evidence(+ver_off) | 52 | 0.8113 | 0.2075 | **0.0233** | **0.8140** | 0.2558 | 0.6279 | 0.8605 | 52.4 |
| ablate:verification | 52 | 0.8113 | 0.2075 | 0.9070 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 51.6 |
| ablate:consensus | 52 | 0.8113 | 0.2075 | 0.9070 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 43.7 |
| stage:top_k=1 | **16** | 0.4286 | 0.1714 | 0.9333 | 0.9333 | 0.4000 | 0.7333 | 0.8667 | 44.0 |
| stage:cross_sentence | **144** | 0.5253 | 0.1212 | 0.6346 | 0.9615 | 0.2308 | 0.6923 | 0.7885 | 141.8 |

## Lectura (efecto de encender/apagar cada etapa)

- **Compatibilidad**: `base` y `hybrid_default` son **identicos en TODAS las
  metricas** -> el motor por etapas, con todo en default, reproduce la base sobre
  el corpus real (no solo en un test sintetico).
- **Etapa 3 (predicado/direccion)**: apagarla hunde `strict_f1` 0.2075 -> 0.000 y
  `predicate_correct` 0.2558 -> 0.000, y `direction_correct` 0.6279 -> 0.1395. Es
  la etapa que aporta los predicados especificos y su orientacion.
- **Etapa 4 (evidencia)**: apagarla (con verificacion tambien off para observar el
  candidato degradado) colapsa `evidence_correct` 0.9070 -> 0.0233 y baja
  `offsets_correct` 0.9302 -> 0.8140. Es la etapa critica de la cita literal.
- **Etapa 6 (temporal/epistemica)**: apagarla baja `epistemic_correct`
  0.8605 -> 0.8140 (rumores marcados como ASSERTED). Efecto pequeño en agregado
  pero **relevante para seguridad** (ver `security.md`).
- **Etapa 5 (verificacion)** y **Etapa 7 (consenso)**: **sin efecto medible en
  ESTAS metricas del corpus B1**. Honesto: la verificacion solo rechaza cuando la
  evidencia esta degradada (etapa 4 off), y el consenso afecta a la decision, no a
  la calidad estructural aqui medida. Sus efectos se demuestran a nivel de test
  unitario (verificacion rechaza cobertura incompleta; consenso -> `None`).
- **Top-k = 1**: reduce n_preds 52 -> 16 (uno por fuente). Baja recall/existence_f1
  (0.81 -> 0.43): es el precio del acotado. La calidad estructural por candidato
  sube ligeramente (se conservan los de mayor score).
- **Cross-sentence**: dispara n_preds 52 -> 144 (pares inter-frase). Sube
  `offsets_correct` (0.96) pero baja precision/existence_f1 (0.53): mas cobertura,
  mas ruido. Trade-off explicito.

## Notas metodologicas

- 52 predicciones vs 54 relaciones GT: hay pares de GT cuyas menciones no producen
  candidato con la config offline base (mismo comportamiento que la base; no lo
  altera V4).
- El determinismo se comprueba con `result_hash`; `elapsed_ms` es orientativo (no
  entra en ningun hash ni gate).

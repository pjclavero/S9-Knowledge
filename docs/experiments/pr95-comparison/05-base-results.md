# 05 — Resultados BASE

Base P0 (head `92583f4`): `external_ai_shadow.py` + `pipeline.py`. Sirve de referencia
en ambas pistas.

## PISTA PIPELINE (C1, 52 candidatos, 54 GT)
- pair: P 0.827 / R 0.796 / F1 0.811; strict_f1 0.208.
- evidencia: **evidence_correct (IoU>=.5) = 0.907**, evidence_iou 0.816,
  evidence_exact 0.395, offsets_overlap 0.930, boundary_mae 7.29.
- semantica: predicate_exact 0.256, direction_exact 0.628, negation 0.907,
  temporal 0.442, epistemic 0.860, decision 0.302.
- operacion: p50 2.82 ms / p95 6.13 ms; determinism_rate 1.0.

Nota: el bajo `predicate_exact` (0.256) y `strict_f1` (0.208) son propiedad del
extractor heuristico base sobre este corpus (el predicado suele quedar en
`RELATED_TO`), no de la comparativa. Se reporta igual para todas las versiones con la
misma vara.

## PISTA PROTOCOLO (banco sintetico)
El protocolo clasico de la base exige **evidencia literal + offsets exactos**:
- C1_common valid_response_rate **0.185** (solo acepta el tier `exact`, 10/11;
  rechaza offset_shift, para_light, para_strong, injection).
- C3_adversarial valid 0.500; C2_independent valid 1.000.
- literal_evidence_rate de lo aceptado = **1.0** en los tres grupos.
- prompt_injection_success = 0; network_attempts = 0.

Interpretacion: la base es maximamente estricta (0 falsos aceptados, literalidad
perfecta) a costa de rechazar toda evidencia no-literal del modelo. V2 y V3 atacan
precisamente esa perdida de recall del protocolo sin relajar la literalidad.

Detalle: `normalized-results/pipeline-base.json`, `protocol-base-*.json`;
`metrics.json`, `security.json`.

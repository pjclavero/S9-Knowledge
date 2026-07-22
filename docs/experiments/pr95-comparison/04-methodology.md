# 04 — Metodologia (Comparativa unificada PR#95)

## Principio: dos pistas, una sola vara
Las versiones atacan capas distintas, asi que se separan **dos pistas** y cada
version se ejecuta con **su mecanismo activado** (flag ON), midiendo con la MISMA
vara (los modulos `relations.benchmark.matching` + `metrics` de la BASE).

- **PISTA PIPELINE** (evidencia heuristica): base, V1, V4. Se ejecuta el pipeline
  REAL sobre C1 (`load_corpus -> derive_entities -> build_payload -> run_pipeline ->
  extract_predictions`), y el orquestador hace `match_predictions` + metricas con la
  vara de la base.
- **PISTA PROTOCOLO PROVEEDOR** (evidencia del modelo externo): base, V2, V3. Offline
  => banco sintetico comun y congelado; `evaluate_relation_external` con un proveedor
  MOCK que devuelve la respuesta pre-generada del banco. Cero red.

## Aislamiento entre versiones
Cada version se ejecuta en **subproceso** dentro de SU worktree
(`cwd = <wt>/data-engine/app`, su `relations` en `sys.path`). Asi no hay colision del
paquete `relations` entre versiones y el orden de importacion queda aislado. Los
workers (`harness/worker_pipeline.py`, `harness/worker_protocol.py`) NO calculan
metricas: solo ejecutan el pipeline/evaluador de la version y devuelven salida cruda.

## Adaptador uniforme
La salida de cada version se normaliza (LECTURA, sin copiar implementaciones) al
esquema comun `{candidate_id, subject, predicate, object, direction, evidence_spans,
negated, temporality, epistemic, confidence, provider_status, validation_status,
latency_ms}` en `normalized-results/`. Campo no soportado => `"unsupported"` (no se
inventa). `raw-redacted-results/` guarda solo spans/longitud/estado (sin texto crudo
del documento, sin secretos).

## Activacion de cada mecanismo (flag ON)
| version | pista | flag |
|---|---|---|
| V1 | pipeline | `PipelineConfig.evidence_anchor_mode = "conservative"` |
| V4 | pipeline | `hybrid_stages={}` (default) / `+hybrid_cross_sentence` (repr) / ablaciones |
| V2 | protocolo | `RelationExternalConfig.realignment_enabled = True` |
| V3 | protocolo | `RelationExternalConfig.fragment_protocol_enabled = True` |

## Ejecucion homogenea
Mismo Python (3.13.5), mismo corpus congelado, misma vara, red cerrada, **3
repeticiones** offline por configuracion para determinismo/latencia. Orden base,V1,V4
(pipeline) y base,V2,V3 (protocolo); cada worker es un proceso fresco (randomiza el
orden de importacion respecto a un proceso unico). `determinism_rate = 1` si el hash
de la salida es identico en las 3 reps.

## Metricas
- **Pares/estructura**: pair_precision/recall/f1, strict_f1, predicate_exact,
  direction_exact, direction_orientation_ok.
- **Evidencia**: evidence_correct (IoU>=0.5), evidence_iou, evidence_exact_match,
  evidence_char_f1, evidence_token_f1, offset_exact_match, offsets_overlap,
  start/end_absolute_error, boundary_mae, literal_evidence_rate,
  evidence_overextension, evidence_underextension.
- **Protocolo**: valid_response_rate, invalid_response_rate, missing_evidence_rate,
  realignment_success_rate, false_realignment_rate, ambiguous_realignment_rate,
  invalid_fragment_rate, fragment_reconstruction_rate.
- **Semantica**: negation_accuracy, temporality_accuracy, epistemic_accuracy,
  decision_accuracy.
- **Operacion**: latency_p50/p95, candidate_count, determinism_rate.
- **Seguridad**: network_attempts (0), write_attempts (0), secret_exposure (0),
  prompt_injection_success (0), unsafe_output_acceptance (0).

## Regla dura
`literal_evidence_rate` de lo ACEPTADO debe ser 1.0 en toda version aceptable;
ningun alineamiento ambiguo aceptado; 0 intentos de red/escritura. Verificado (ver
05-10 y `security.json`).

## Reproducibilidad
`python3 artifacts/pr95-unified-comparison/harness/build_bank.py` (congela corpus +
banco) y `python3 .../harness/run_comparison.py` (ejecuta ambas pistas y escribe
metrics/performance/security/normalized/raw).

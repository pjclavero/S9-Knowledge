# Tabla homogenea PR#95 — dos pistas, misma vara

Corpus congelado; matching + metricas con los modulos de la BASE; 3 reps offline.
`literal_evidence_rate` de lo ACEPTADO = 1.0 en toda la tabla (regla dura).

## PISTA PIPELINE (evidencia heuristica) — corpus C1 real (54 relaciones)

| config | pair_P | pair_R | pair_F1 | strict_F1 | **evidence_correct** (IoU>=.5) | evidence_iou | evidence_exact | offsets_overlap | boundary_mae | predicate_exact | direction_exact | negation | temporal | epistemic | decision | cand | det |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 0.827 | 0.796 | 0.811 | 0.208 | **0.907** | 0.816 | 0.395 | 0.930 | 7.29 | 0.256 | 0.628 | 0.907 | 0.442 | 0.860 | 0.302 | 52 | 1.0 |
| v1_conservative | 0.827 | 0.796 | 0.811 | 0.208 | **0.837** | 0.792 | 0.000 | 0.930 | 9.50 | 0.256 | 0.628 | 0.907 | 0.442 | 0.860 | 0.302 | 52 | 1.0 |
| v4_hybrid_default | 0.827 | 0.796 | 0.811 | 0.208 | **0.907** | 0.816 | 0.395 | 0.930 | 7.29 | 0.256 | 0.628 | 0.907 | 0.442 | 0.860 | 0.302 | 52 | 1.0 |
| v4_cross_sentence | 0.361 | **0.963** | 0.525 | 0.121 | 0.635 | 0.624 | 0.289 | 0.962 | 18.6 | 0.231 | 0.692 | 0.904 | 0.404 | 0.789 | 0.365 | 144 | 1.0 |
| v4_ablate_evidence | 0.827 | 0.796 | 0.811 | 0.208 | **0.023** | 0.188 | 0.000 | 0.814 | 23.4 | 0.256 | 0.628 | 0.907 | 0.442 | 0.860 | 0.302 | 52 | 1.0 |

Latencias (p50/p95 ms por fuente): base 2.82/6.13 · v1 2.80/6.23 · v4_default 2.56/7.09 · v4_cross 6.94/18.87 · v4_ablate 2.72/7.26.

Lecturas clave:
- **v4_hybrid_default == base byte a byte** en TODAS las metricas: la ruta hibrida en su default reproduce la base (compatibilidad demostrada).
- **v1_conservative**: existencia y todo lo estructural IDENTICO a base; SOLO cambia la evidencia, y **empeora** (0.907 -> 0.837, -7 pp; 0 mejoras). Ver 06-v1-results.md.
- **v4_cross_sentence** (representativa): recall 0.796 -> **0.963** (recupera relaciones interfrase) pero precision 0.827 -> 0.361 (144 candidatos, muchos FP) => F1 baja a 0.525. Trade-off, no mejora neta en este corpus.
- **v4_ablate_evidence**: apagar la etapa de evidencia colapsa evidence_correct a 0.023 (documenta que 0.907->0.023 = "evidencia apagada", no un bug de medicion).

## PISTA PROTOCOLO PROVEEDOR (evidencia del modelo externo) — banco sintetico

Banco de "competencia fija" (SINTETICO; el juez real es la corrida NVIDIA, no ejecutada).
`valid` = aceptado (no INVALID_RESPONSES). `literal` = literalidad de lo aceptado.

### C1_common (54 casos, mezcla exact/offset/para_light/para_strong/injection)

| config | valid_response_rate | literal (aceptado) | realign_success | false_realign | ambiguous | frag_reconstruction | invalid_fragment | injection_success | net_attempts | det |
|---|---|---|---|---|---|---|---|---|---|---|
| base | 0.185 | 1.0 | — | — | — | — | — | 0 | 0 | 1.0 |
| v2_realignment | **0.796** | 1.0 | 0.767 | **0.182** | 0.0 | — | — | 0 | 0 | 1.0 |
| v3_fragments | **0.963** | 1.0 | — | — | — | 0.963 | 0.037 | 0 | 0 | 1.0 |

Aceptacion por tier (C1): base solo acepta `exact` (10/11); rechaza offset/para/injection.
V2 acepta offset 11/11, para_light 11/11, para_strong 11/11, injection 0/10.
V3 acepta offset/para 11/11 cada uno, injection 9/10 (la evidencia inyectada es
irrelevante: reconstruye por fragmentos), literalidad intacta.

### C3_adversarial (6 casos) / C2_independent (4 casos)

| config | C3 valid | C3 literal | C3 injection_succ | C2 valid | C2 literal |
|---|---|---|---|---|---|
| base | 0.500 | 1.0 | 0 | 1.000 | 1.0 |
| v2_realignment | 0.667 | 1.0 | 0 | 1.000 | 1.0 |
| v3_fragments | 0.667 | 1.0 | 0 | 1.000 | 1.0 |

Hallazgos adversariales: los 3 protocolos rechazan la inyeccion, el JSON hostil
(verdict fuera de catalogo + confidence>1) y los offsets fuera de rango. V3 rechaza
correctamente los fragment_ids inexistentes; V2 realinea offsets fuera de rango por
texto literal. **prompt_injection_success = 0** en todos.

## Regla dura — verificacion
- literal_evidence_rate de lo aceptado = **1.0** en todas las filas de ambas pistas.
- ningun alineamiento ambiguo aceptado (V2 ambiguous_realignment tratado como no-aceptado).
- network_attempts = 0, write_attempts = 0, determinism_rate = 1.0 en todo.

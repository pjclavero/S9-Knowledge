# 10 — Head to head (todas las versiones, dos pistas)

Tabla homogenea completa en `artifacts/pr95-unified-comparison/comparison-table.md`.
Aqui, la sintesis y el veredicto independiente.

## Advertencia metodologica
Las versiones **no compiten en la misma metrica**: V1/V4 tocan la PISTA PIPELINE
(evidencia heuristica sobre C1 real); V2/V3 tocan la PISTA PROTOCOLO (evidencia del
modelo externo, banco sintetico). Compararlas en un unico ranking seria deshonesto.
Se comparan DENTRO de su pista, contra la MISMA base.

## PISTA PIPELINE (C1 real)
| config | pair_F1 | pair_R | evidence_correct | veredicto |
|---|---|---|---|---|
| base | 0.811 | 0.796 | 0.907 | referencia |
| v1_conservative | 0.811 | 0.796 | **0.837** | negativo neto en evidencia (-7 pp, 0 mejoras) |
| v4_hybrid_default | 0.811 | 0.796 | 0.907 | == base byte a byte (compatibilidad) |
| v4_cross_sentence | **0.525** | **0.963** | 0.635 | +recall, -precision => F1 baja; trade-off |

Ninguna variante de pipeline mejora el F1 ni el evidence_correct sobre la base en C1.
V1 empeora la evidencia; V4 iguala (default) o desplaza el balance P/R sin ganar F1.

## PISTA PROTOCOLO (banco sintetico; C1_common)
| config | valid_response_rate | literal (aceptado) | injection_success | riesgo | veredicto |
|---|---|---|---|---|---|
| base | 0.185 | 1.0 | 0 | — | estricto: 0 recall no-literal |
| v2_realignment | 0.796 | 1.0 | 0 | false_realign **0.182** | +recall, con 18% realineado a span erroneo |
| v3_fragments | **0.963** | 1.0 | 0 | evidencia gruesa (frase) | +recall e inmune a inyeccion; evidencia menos fina |

En el protocolo, tanto V2 como V3 **mejoran mucho el recall** sin romper literalidad
ni aceptar inyecciones. **V3 domina a V2** en tasa valida (0.963 vs 0.796) y en
robustez a inyeccion (ignora la cita del modelo), a cambio de evidencia a nivel de
frase. V2 conserva granularidad fina pero arrastra un 18% de realineamientos a lugar
equivocado.

## Sintesis para PR#95 (independiente, no vinculante)
- **Pipeline**: mantener la BASE. V4 aporta plataforma (compatibilidad byte a byte)
  pero sin mejora de calidad; V1 no conviene en este corpus.
- **Protocolo**: hay valor real. **V3 (fragmentos)** es la via mas robusta y de mayor
  recall con literalidad garantizada; **V2 (realineamiento)** es util donde importe la
  granularidad, pero requiere reducir el `false_realignment_rate`. La decision final
  debe apoyarse en la **corrida real NVIDIA** (no ejecutada aqui): el banco sintetico
  demuestra que los MECANISMOS son correctos, deterministas y seguros, no que el
  modelo real elija bien.

## Seguridad (todas las versiones, ambas pistas)
network_attempts 0 · write_attempts 0 · secret_exposure 0 · prompt_injection_success 0
· unsafe_output_acceptance 0 · literal_evidence_rate (aceptado) 1.0 ·
determinism_rate 1.0. Detalle en `security.json`.

## Pendiente (honesto, 2a oleada)
- C2 completo (ausencia de relacion, rumor, intencion, multi-mencion, mas interfrase).
- Combinaciones V2+V3 (realineamiento sobre evidencia derivada de fragmentos).
- Stats bootstrap / intervalos de confianza sobre las tasas.
- V4 con `top_k` como filtro de precision para el modo cross_sentence.
- La comparativa real contra el modelo externo (NVIDIA), unico juez valido del
  protocolo.

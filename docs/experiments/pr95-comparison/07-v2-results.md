# 07 — Resultados V2 (evidence realignment)

Flag: `RelationExternalConfig.realignment_enabled = True`. Cuando la evidencia del
modelo NO casa literalmente, V2 la sustituye por una **rodaja literal** del documento
(escalera exact/normalized/fuzzy con umbral `REALIGN_SCORE_THRESHOLD=0.82`). NUNCA
relaja la validacion: la literalidad final la sigue imponiendo el validador estricto.

## Banco sintetico — C1_common (54 casos)
| metrica | base | V2 |
|---|---|---|
| valid_response_rate | 0.185 | **0.796** |
| literal_evidence_rate (aceptado) | 1.0 | **1.0** |
| realignment_success_rate | — | 0.767 |
| false_realignment_rate | — | **0.182** |
| ambiguous_realignment_rate | — | 0.0 |
| prompt_injection_success | 0 | **0** |

Aceptacion por tier: `offset_shift` 0->11/11, `para_light` 0->11/11, `para_strong`
0->11/11, `injection` 0/10 (sigue rechazada), `exact` 10/11.

## Hallazgos
- **Positivo**: V2 cuadruplica la tasa de respuesta valida del protocolo (0.185 ->
  0.796) recuperando offsets desplazados y parafrasis (normalizacion NFD/NBSP y
  reescritura leve), manteniendo **literalidad 1.0** y **0 inyecciones aceptadas**.
- **Negativo real (importante)**: `false_realignment_rate = 0.182`. ~1 de cada 5
  realineamientos ancla en un span que **no solapa** el GT (IoU=0). Es decir, V2 a
  veces "encuentra" una rodaja literal valida pero en el lugar equivocado del
  documento. La literalidad se preserva, pero la **evidencia deja de ser la
  correcta**. Esto es un riesgo de calidad que la corrida real (NVIDIA) debe vigilar:
  aceptar mas no es gratis.
- C3_adversarial: valid 0.667; realinea correctamente los offsets fuera de rango por
  texto literal; rechaza injection y JSON hostil; ambiguo (evidencia repetida) NO se
  fuerza (no hay realineamiento ambiguo aceptado).
- Determinismo 1.0; network_attempts 0; write_attempts 0.

## Veredicto V2 (independiente)
Mejora sustancial de recall del protocolo con literalidad intacta, pero con un
**18% de realineamientos a span equivocado** que hay que medir contra el modelo real
antes de darlo por bueno. Prometedor, no cerrado.

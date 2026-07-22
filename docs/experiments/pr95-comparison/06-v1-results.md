# 06 — Resultados V1 (conservative anchor)

Flag: `PipelineConfig.evidence_anchor_mode = "conservative"`. Cambia SOLO el anclaje
de la evidencia heuristica (envolvente de clausula + marcadores), con fallback seguro
al span. No toca generacion de pares ni consenso.

## Resultado global (C1)
Todo lo estructural es **identico a la base** (P/R/F1 0.827/0.796/0.811, strict_f1
0.208, predicate/direction/negation/temporal/epistemic/decision iguales, mismos 52
candidatos, determinism 1.0). Lo unico que cambia es la evidencia:

| metrica | base | V1 | delta |
|---|---|---|---|
| evidence_correct (IoU>=.5) | 0.907 | **0.837** | -0.070 |
| evidence_iou (media) | 0.816 | 0.792 | -0.024 |
| evidence_exact_match | 0.395 | 0.000 | -0.395 |
| boundary_mae | 7.29 | 9.50 | +2.21 |
| offsets_overlap | 0.930 | 0.930 | 0 |

## Analisis por categorias del 0.907 -> 0.837
`v1-evidence-category-analysis.json`. Sobre 43 pares emparejados: **0 mejoras, 3
regresiones**, 36 sin cambio (correctos), 4 sin cambio (ya <0.5). Las 3 regresiones:

| relation | predicado | neg | temporal | epistemic | base_iou | v1_iou | categoria |
|---|---|---|---|---|---|---|---|
| rel-001 | ALLIED_WITH | no | PAST | ASSERTED | 0.629 | 0.470 | reencuadre / GT mas amplio |
| rel-002 | ENEMY_OF | no | PAST | ASSERTED | 0.667 | 0.417 | reencuadre / GT mas amplio |
| rel-047 | OWNS | **si** | ENDED | ASSERTED | 0.569 | 0.439 | recorte de clausula (pierde marca negacion/temporal) |

Categorias del encargo, aplicadas:
- **frase amplia / clausula corta**: las 3 regresiones son casos en que el GT anota
  una evidencia MAS AMPLIA que la clausula segura; el anclaje conservador estrecha el
  span y baja el IoU justo por debajo de 0.5 (todas partian de 0.57-0.67, al borde).
- **perdida de negacion/temporal/epistemica**: rel-047 (negada, ENDED) es el caso
  claro: recortar a la clausula deja fuera marcadores que el GT incluye.
- **GT alternativo**: rel-001/rel-002 son "reencuadre" donde el span movido sigue
  siendo defendible pero no supera el umbral IoU del GT concreto.
- **error de algoritmo / de matching**: NO se observan; el matching y el resto de
  atributos son identicos a la base.
- **mejora en algun subconjunto**: **ninguna** (0 casos mejoran). `evidence_exact`
  cae a 0 porque el anclaje deja de coincidir exactamente con el span mecanico.

## Veredicto V1 (independiente)
En ESTE corpus el anclaje conservador es un **negativo neto para la evidencia**
(-7 pp evidence_correct, 0 ganancias) porque el GT del corpus tiende a evidencias mas
amplias que la clausula segura. Es seguro (literalidad 1.0, sin regresiones
estructurales, fallback correcto) y determinista, pero no aporta valor de evidencia
aqui. Podria ayudar en corpus con evidencias-GT ajustadas a clausula; no es el caso.

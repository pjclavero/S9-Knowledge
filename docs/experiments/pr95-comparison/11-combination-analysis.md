# 11 — Analisis de combinaciones (ablacion por componente)

Simulacion OFFLINE sobre el **mismo banco sintetico congelado** (`synthetic-bank.json`).
Se ejercita el protocolo REAL de cada version (worktrees V2/V3) via `worker_protocol.py`
(mock puro, cero red). Driver: `harness/run_combinations.py`. Salida:
`artifacts/pr95-unified-comparison/combination-analysis.json` +
`normalized-results/combo-v2v3-*.json`.

> Recordatorio: el banco sintetico NO es el juez real. Los numeros de abajo son
> firmes como *ablacion del mecanismo*, pero PROVISIONALES como prediccion de
> calidad (el juez real es la corrida NVIDIA, doc 15, no ejecutada).

## Regla del ejercicio
Ningun componente entra "por defecto". Cada uno debe justificar su coste con una
ablacion que muestre beneficio marginal **unico** (que no aporte otro componente
mas barato o mas seguro).

## V2+V3 — combinacion principal (orden del spec)

Politica por caso (fail-closed):
1. **Seleccion por fragmento (V3)**: se intenta reconstruir la evidencia por id de
   fragmento (literal por construccion).
2. Si V3 **acepta** -> resultado literal, sin realinear.
3. Si V3 **no** acepta -> **fallback a realineamiento determinista (V2)**.
4. Si V2 tampoco acepta -> **rechazo**.

Un caso solo puede producir `false_realign` si el realineamiento de V2 llega a
**activarse** (paso 3). V3 nunca realinea: reconstruye literal.

### Resultados (numeros reales del banco)

| grupo | metrica | V2 sola | V3 sola | **V2+V3** |
|---|---|---|---|---|
| C1 (n=54) | valid_response_rate | 0.796 | 0.963 | **0.963** |
| C1 | literal (aceptado) | 1.0 | 1.0 | **1.0** |
| C1 | injection_success | 0 | 0 | **0** |
| C1 | realineamientos activados | 33 | — | **0** |
| C1 | **false_realign_rate** | **0.1818 (6/33)** | n/a | **0.0** |
| C3 (n=6) | valid_response_rate | 0.667 | 0.667 | **0.833 (5/6)** |
| C3 | injection_success | 0 | 0 | **0** |
| C2 (n=4) | valid_response_rate | 1.0 | 1.0 | **1.0** |

### Lectura honesta del resultado

- **El false_realign de V2 (0.182) baja a 0.0 en la combinacion** — pero **no**
  porque el realineamiento realinee mejor, sino porque **nunca se activa**
  (`realign_fired = 0` en C1/C2/C3). V3 cubre por fragmento literal exactamente
  los casos que V2 realineaba (los 6 fallos de V2 en C1 son **todos** `para_strong`,
  con span reubicado a IoU=0 respecto al GT; V3 los reconstruye literalmente).
- Consecuencia de ablacion: **sobre este banco, V2 no aporta beneficio marginal
  unico sobre V3**. Su unica contribucion es como *fallback de aceptacion literal*
  en el caso adversarial `invalid_fragment` de C3 (V3 lo rechaza, V2 lo acepta
  sin realinear), que sube C3 de 4/6 a **5/6**. Eso NO ejercita el realineamiento;
  lo cubriria igual una mejora de cobertura de fragmentos en V3.
- Es decir: **el componente de riesgo de V2 (realineamiento difuso) falla su
  justificacion por ablacion.** Aporta 0.182 de riesgo cuando dispara y 0 beneficio
  unico cuando V3 esta presente.

## Otras combinaciones (esbozo con datos)

- **V1+V2 / V1+V3**: **ortogonales, no combinables como sinergia.** V1 actua en la
  PISTA PIPELINE (anclaje de evidencia heuristica, C1 real); V2/V3 en la PISTA
  PROTOCOLO (evidencia del modelo externo). No comparten superficie. V1, ademas, es
  **negativo neto** en su propia pista (evidence_correct 0.907->0.837, 0 mejoras,
  3 regresiones; doc 13). Combinar V1 solo arrastra su regresion; sin sinergia.
- **V2 + componentes de V4**: V4 aporta plataforma en pipeline (hybrid_default ==
  base byte a byte; cross_sentence sube recall a 0.963 pero hunde F1 a 0.525 por
  precision 0.361). El realineamiento de V2 no interactua con el cross_sentence de
  V4: uno mueve spans de evidencia del modelo externo, el otro genera pares
  candidatos. Combinacion posible pero **sin sinergia medible**; hereda el trade-off
  P/R de V4 y el riesgo de realineo de V2.
- **V3 + componentes de V4**: la unica con potencial real. `v4_hybrid_default` es
  compatible byte a byte con base, asi que **V3 sobre plataforma V4-hybrid** conserva
  las metricas de V3 sin coste (misma salida). No se justifica activar
  `cross_sentence` (mata F1). Recomendable solo si se quiere la plataforma V4 por
  otras razones; V3 no la necesita.

## Coste por componente (justificacion de ablacion)

| componente | beneficio unico en el banco | coste | veredicto ablacion |
|---|---|---|---|
| V3 fragmentos | +recall (0.185->0.963), inmune a inyeccion, literal 1.0 | evidencia a nivel frase (menos fina); coste de prompt/granularidad (doc 14) | **justificado** (provisional a NVIDIA) |
| V2 realineamiento | ninguno cuando V3 esta presente; +recall solo si V3 ausente | false_realign 0.182 al activarse | **no justificado junto a V3** |
| V2 (fallback literal) | +1 caso adversarial `invalid_fragment` (C3 4/6->5/6) | menor; sustituible por cobertura de fragmentos | marginal |
| V1 anclaje | ninguno (0 mejoras, 3 regresiones) | -7 pp evidence_correct | **no justificado** |
| V4 hybrid_default | plataforma compatible (== base) | nulo | neutro (habilitador) |
| V4 cross_sentence | +recall pipeline (0.963) | F1 0.525, boundary_mae 18.6 | **no justificado** |

## Conclusion del doc 11
En el banco sintetico, **V3 subsume a V2**: la combinacion V2+V3 iguala a V3 en C1/C2
y solo mejora C3 por una via que no es el realineamiento. Recomendacion de ablacion:
**no combinar V2+V3 por defecto**; si se integra la pista de protocolo, hacerlo con
**V3 solo**, y dejar V2 fuera salvo que la corrida NVIDIA (doc 15) demuestre que la
evidencia a nivel frase de V3 pierde casos que el realineamiento fino de V2 recupera
sin false_realign. Hasta entonces, el veredicto del protocolo es **provisional**.

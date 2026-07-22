# 13 — Estadistica (intervalos de confianza bootstrap)

Metodo: bootstrap no parametrico (remuestreo de unidades por-caso), 10 000
remuestras, semilla fija `20250721`, CI 95% por percentiles. Determinista y
OFFLINE. Driver: `harness/confidence_intervals.py`. Salida:
`artifacts/pr95-unified-comparison/confidence-intervals.json`.

**Regla aplicada:** no se declara superioridad por diferencias pequenas sin
soporte; con muestras pequenas se marca la incertidumbre de forma explicita.

## PISTA PROTOCOLO — valid_response_rate en C1 (n=54)

| config | punto | CI 95% |
|---|---|---|
| base | 0.185 | [0.093, 0.296] |
| v2_realignment | 0.796 | [0.685, 0.889] |
| v3_fragments | 0.963 | [0.907, 1.000] |

Diferencias pareadas (mismos 54 casos):

| comparacion | dif. abs | dif. rel | CI 95% de la dif | excluye 0 |
|---|---|---|---|---|
| V3 − base | +0.778 | +420% | [0.667, 0.889] | **si** |
| V2 − base | +0.611 | +330% | [0.481, 0.741] | **si** |
| V3 − V2 | +0.167 | +21% | [0.074, 0.278] | **si** |

Lectura: base < V2 < V3 con CIs que **no se solapan** y diferencias pareadas que
**excluyen 0**. V3 > V2 es estadisticamente distinguible **en el banco**, pero la
magnitud es modesta (+17 pp) y el banco es sintetico -> **firmeza limitada**: sirve
para ordenar mecanismos, no para prometer calidad en produccion.

## V2 — false_realignment (banco, C1)

- Punto: 0.1818 (6 falsos / 33 realineamientos activados).
- CI 95% bootstrap: **[0.061, 0.333]** — **ancho**. Denominador pequeno (33).
- No se declara la magnitud exacta; lo firme es el **signo y la existencia** del
  fenomeno (el realineamiento difuso reubica a span erroneo con frecuencia
  material), no el valor puntual.
- En el flujo **V2+V3**, `realign_fired = 0` -> el ratio es 0/0. Se reporta como
  **0.0 estructural**: el riesgo desaparece porque el componente no se activa
  (doc 11), no porque realinee mejor.

## PISTA PIPELINE — evidence_correct base vs V1 (pareado, n=43 TP)

| config | punto | CI 95% |
|---|---|---|
| base | 0.907 | [0.814, 0.977] |
| v1_conservative | 0.837 | [0.721, 0.930] |

- Diferencia pareada base − V1: **+0.070**, CI 95% **[0.000, 0.163]** -> **INCLUYE 0**.
- Pares discordantes: 3 (base-ok/V1-no) vs 0 (base-no/V1-ok). McNemar exacto
  bilateral **p = 0.25** -> **no significativo**.
- Lectura honesta: **NO se puede declarar "base > V1" con confianza estadistica**
  (n insuficiente, solo 3 discordantes). Lo que SI es firme: **V1 no mejora nada**
  (0 mejoras sobre 43), y su direccion es consistentemente negativa. El argumento
  contra V1 no es "es peor con significancia" sino "**no aporta beneficio y arriesga
  regresion**".

## Confianza / calibracion (ECE, Brier)

**INSUFICIENTE.** El campo `confidence` sale `unsupported` / `NOT_EXECUTED` en ambas
pistas (proveedor no ejecutado; los scores no son probabilidades calibrables ni
comparables entre versiones). Sin casos con probabilidad calibrable, ECE y Brier
**no son calculables**. Se declara explicitamente en lugar de reportar un numero
sin soporte.

## Sintesis estadistica

- **Firme (banco):** base < V2 < V3 en recall valido; las tres diferencias excluyen 0.
- **Firme (pipeline):** V1 no mejora la evidencia; la supuesta ventaja de base es
  direccional pero **no significativa** — el caso contra V1 se apoya en "0 mejoras",
  no en significancia.
- **Provisional:** todo el orden V2/V3 procede del banco sintetico; la magnitud real
  la decide NVIDIA (doc 15).
- **No disponible:** calibracion (ECE/Brier) por falta de scores.

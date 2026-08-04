# Puerta 4 - B3: carril semantico NVIDIA en sombra

Split: `negation` -- 57 claims / 60 episodios (gold congelado, verificado por hash).

Generado por `scripts/gate4/measure_b3.py`. Ninguna cifra de este documento
se escribe a mano. Modo SOMBRA: el carril NVIDIA nunca escribe en Neo4j ni
decide; solo se compara contra el gold y contra el determinista.

## Carriles

| carril | cobertura | recall_simple | recall_overall | precision | falsos positivos |
| --- | --- | --- | --- | --- | --- |
| heuristico_local_bench | 0.0 | 0.0 | 0.0 | None | 0 |
| nvidia | 0.3571 | 0.4545 | 0.3393 | 0.5588 | 15 |
| nvidia_mas_heuristico_reconciliado | 0.3571 | 0.4545 | 0.3393 | 0.5588 | 15 |

## Puertas (umbral del programa, no redefinido por B3)

| carril | puerta | umbral | observado | veredicto |
| --- | --- | --- | --- | --- |
| heuristico_local_bench | cobertura_e2e_dev | 0.6 | 0.0 | NO_CONFORME |
| heuristico_local_bench | recall_simple | 0.7 | 0.0 | NO_CONFORME |
| nvidia | cobertura_e2e_dev | 0.6 | 0.3571 | NO_CONFORME |
| nvidia | recall_simple | 0.7 | 0.4545 | NO_CONFORME |
| nvidia_mas_heuristico_reconciliado | cobertura_e2e_dev | 0.6 | 0.3571 | NO_CONFORME |
| nvidia_mas_heuristico_reconciliado | recall_simple | 0.7 | 0.4545 | NO_CONFORME |

## Latencia del carril NVIDIA (tanda completa: cache + llamadas reales de hoy)

- llamadas medidas (tanda completa): 60
- de ellas, reales en esta corrida: 0
- media: 36075.7 ms
- p95: 53320.6 ms
- maxima: 58522 ms

## Tokens y extrapolacion

- tokens de entrada (total): 247851
- tokens de salida (total): 19811
- tokens totales: 267662
- tokens medios por episodio: 4461.0
- extrapolacion a 1000 episodios (tokens): 4461033.3
- precio USD/millon de tokens: None
- coste estimado de esta corrida: None
- coste estimado por 1000 episodios: None
- nota: sin precio documentado en el repo: se reporta solo tokens; pasa --price-per-million-tokens-usd para estimar coste

## Cache y llamadas reales vs servidas

- servidas desde cache: 60
- llamadas reales (miss de cache): 0
- llamadas reales OK: 0
- llamadas reales fallidas: 0

## Incidencias con la API NVIDIA

- reintentos de transporte usados: 0
- timeouts duros (60s): 0
- llamadas fallidas tras agotar reintentos: 0
- errores distintos observados: ninguno

## Datos para la decision de adopcion (operador)

- coste: precio USD/millon = None; sin precio fiable documentado en el repo ni precio publico por token verificable para este modelo en NVIDIA NIM en el momento de la corrida; el coste real depende del contrato del operador. Los tokens medidos y la extrapolacion a 1000 episodios estan en la seccion `tokens`.
- estabilidad: 0 reintentos de transporte, 0 timeouts duros de 60s, 0/60 episodios perdidos (0.0%).
- advertencia: una sola corrida no distingue un pico puntual del comportamiento habitual del proveedor; antes de adoptar, repetir la medicion en dias/horas distintas.

## Nota sobre las etiquetas de los carriles

El carril `heuristico_local_bench` es el extractor heuristico local de
`semantic_bench` (config A), NO el determinista E2E de B0-B2 (0.607).
Como aporta estructuralmente 0 en este arnes de claims, la vista
`nvidia_mas_heuristico_reconciliado` coincide con `nvidia`. La cifra
comparable al 0.607 exige la via `pipeline.runner.run_one(...,
external_port=...)` y queda para un bloque futuro (ver docs/v3/40).

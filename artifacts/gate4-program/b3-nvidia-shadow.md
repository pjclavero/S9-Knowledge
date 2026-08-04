# Puerta 4 - B3: carril semantico NVIDIA en sombra

Split: `negation` -- 57 claims / 60 episodios (gold congelado, verificado por hash).

Generado por `scripts/gate4/measure_b3.py`. Ninguna cifra de este documento
se escribe a mano. Modo SOMBRA: el carril NVIDIA nunca escribe en Neo4j ni
decide; solo se compara contra el gold y contra el determinista.

## Carriles

| carril | cobertura | recall_simple | recall_overall | precision | falsos positivos |
| --- | --- | --- | --- | --- | --- |
| determinista | 0.0 | 0.0 | 0.0 | None | 0 |
| nvidia | 0.3509 | 0.4545 | 0.3333 | 0.5758 | 14 |
| union_reconciliada | 0.3509 | 0.4545 | 0.3333 | 0.5758 | 14 |

## Puertas (umbral del programa, no redefinido por B3)

| carril | puerta | umbral | observado | veredicto |
| --- | --- | --- | --- | --- |
| determinista | cobertura_e2e_dev | 0.6 | 0.0 | NO_CONFORME |
| determinista | recall_simple | 0.7 | 0.0 | NO_CONFORME |
| nvidia | cobertura_e2e_dev | 0.6 | 0.3509 | NO_CONFORME |
| nvidia | recall_simple | 0.7 | 0.4545 | NO_CONFORME |
| union_reconciliada | cobertura_e2e_dev | 0.6 | 0.3509 | NO_CONFORME |
| union_reconciliada | recall_simple | 0.7 | 0.4545 | NO_CONFORME |

## Latencia del carril NVIDIA (llamadas REALES, no servidas desde cache)

- llamadas reales: 58
- media: 36011.0 ms
- p95: 53405.9 ms
- maxima: 58522 ms

## Tokens y extrapolacion

- tokens de entrada (total): 239602
- tokens de salida (total): 19140
- tokens totales: 258742
- tokens medios por episodio: 4312.4
- extrapolacion a 1000 episodios (tokens): 4312366.7
- precio USD/millon de tokens: None
- coste estimado de esta corrida: None
- coste estimado por 1000 episodios: None
- nota: sin precio documentado en el repo: se reporta solo tokens; pasa --price-per-million-tokens-usd para estimar coste

## Cache y llamadas reales vs servidas

- servidas desde cache: 0
- llamadas reales (miss de cache): 60
- llamadas reales OK: 58
- llamadas reales fallidas: 2

## Incidencias con la API NVIDIA

- reintentos de transporte usados: 50
- timeouts duros (60s): 31
- llamadas fallidas tras agotar reintentos: 2
- errores distintos observados: ['ProviderUnavailable']

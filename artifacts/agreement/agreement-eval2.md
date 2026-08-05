# ACUERDO-2: medicion en sombra sobre corpus NUEVO (agreement-eval2)

Split: `agreement-eval2` (workspace `bench-agreement-eval2`) -- 37 claims / 42 episodios (gold nuevo, verificado por hash). Denominador evaluable: 35.

Generado por `scripts/agreement/measure_agreement2.py`. Modo SOMBRA pura.

## Vista PRINCIPAL: acuerdo a nivel de CONTENIDO, por par de decisiones

n=21, precision=0.9524, recall sobre el gold=0.6 (21/35).

| par de decisiones (det/nvidia) | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| ABSTAIN/ABSTAIN | 4 | 3 | 1 | 0.75 |
| ABSTAIN/REVIEW | 2 | 2 | 0 | 1.0 |
| ACCEPT/REVIEW | 8 | 8 | 0 | 1.0 |
| REVIEW/REVIEW | 7 | 7 | 0 | 1.0 |

## Otros conjuntos

| conjunto | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| solo-det | 1 | 1 | 0 | 1.0 |
| solo-nvidia | 5 | 4 | 1 | 0.8 |
| discrepancia: polaridades opuestas ACTIVAS | 0 | 0 | 0 | None |
| discrepancia: abstain vs afirma | 7 | -- | -- | -- |
| discrepancia: predicado incompatible | 1 | -- | -- | -- |
| sin_cubrir | 0 | -- | -- | -- |

## Casos: polaridades opuestas ACTIVAS

| claim_id | det negated | nvidia negated | gold negated |
| --- | --- | --- | --- |

## Casos: abstain vs afirma

| claim_id | det decision | nvidia decision | det negated | nvidia negated | gold negated |
| --- | --- | --- | --- | --- | --- |
| claim:brumal-bitacora:e03:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:brumal-bitacora:e04:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:brumal-bitacora:e06:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:brumal-bitacora:e11:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:salitre-ruta:e02:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:vitral-taller:e04:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:vitral-taller:e06:c1 | REVIEW | ABSTAIN | True | False | True |

## Coste / latencia / cache de la pasada NVIDIA

- llamadas medidas: 38
- reales en esta corrida: 38
- latencia media: 37627.2 ms, p95: 56734.5 ms
- tokens totales: 193359
- servidas desde cache: 0
- llamadas fallidas: 0
- errores distintos: ninguno

## Lectura para la decision del operador

- precision del acuerdo de CONTENIDO: 0.9524 (n=21)
- recall sobre el gold: 0.6 (21/35)
- precision solo-det: 1.0 (n=1)
- precision solo-nvidia: 0.8 (n=5)
- polaridades opuestas activas: 0
- abstain vs afirma: 7
- predicado incompatible: 1
- sin cubrir: 0
- nota: corpus NUEVO (42 casos / 37 claims evaluables): frases y entidades nunca vistas en ningun otro split del repo. Ninguna cifra se escribe a mano. No se recomienda politica: eso es del operador.

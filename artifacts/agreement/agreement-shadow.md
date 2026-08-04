# Medicion en sombra: precision del subconjunto-acuerdo determinista ∧ NVIDIA

Split: `negation` (workspace `bench-negation`) -- 57 claims / 60 episodios (gold congelado, verificado por hash). Denominador evaluable: 56 (convencion B0-B3).

Generado por `scripts/agreement/measure_agreement.py`. Ninguna cifra de este
documento se escribe a mano. Modo SOMBRA pura: ningun carril escribe en Neo4j
ni decide politica; esto SOLO mide.

## Los 4 (+1 diagnostico) conjuntos

| conjunto | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| acuerdo | 0 | 0 | 0 | None |
| solo-det | 16 | 8 | 8 | 0.5 |
| solo-nvidia | 9 | 4 | 5 | 0.4444 |
| discrepancia | 3 | -- | -- | (ver nota) |
| degradado_no_acuerdo (fuera del acuerdo por factividad/evidencia) | 15 | -- | -- | -- |
| sin_cubrir (ningun carril propuso nada emparejable) | 13 | -- | -- | -- |

**Recall del acuerdo sobre el gold**: 0.0 (0/56 casos evaluables).

## Diseno

- criterio de acuerdo: mismo claim_id del gold (alineado via episode_alignment + mention_alignment + claim_alignment del runner congelado, reutilizados por ruta), predicado top-1 compatible (o ausente en algun carril), MISMA polaridad, Y AMBOS carriles con predicted_decision=='ACCEPT' -- el veredicto REAL del motor (engine/decision.py), que ya incorpora la puerta 6 (review_required + hint epistemico degradado nunca ACCEPT) y la verificacion de evidencia literal.
- factividad (puerta 6): un claim que el motor no aceptaria (REVIEW o REJECT reales) en CUALQUIERA de los dos carriles NUNCA entra en acuerdo, aunque ambos coincidan en polaridad: va a 'degradado_no_acuerdo', no a 'acuerdo'. Es la MISMA puerta que produccion, no una reimplementacion paralela.
- alineamiento reutilizado: episode_alignment/mention_alignment/claim_alignment/build_rows del runner E2E congelado (artifacts/v3-final-validation/gate4_negation_measure.py), cargado por ruta via knowledge_v3.eval._frozen_runner.load() -- nunca copiado ni modificado. Necesario porque score_extractor (benchmarks.harness) exige episode_id identico y la cadena real acuna ids propios a partir de los bytes de entrada; ver docstring del modulo.

## Casos de discrepancia (diagnostico)

| claim_id | det negated | nvidia negated | gold negated | razon |
| --- | --- | --- | --- | --- |
| claim:basalto-cronica:e01:c1 | False | True | True | polaridad_incompatible |
| claim:basalto-cronica:e05:c1 | False | True | True | polaridad_incompatible |
| claim:cirro-actas:e05:c1 | True | False | True | polaridad_incompatible |

## Casos excluidos por factividad/evidencia (mismo sujeto/objeto/polaridad, sin ACCEPT en ambos)

| claim_id | det decision | nvidia decision |
| --- | --- | --- |
| claim:basalto-cronica:e07:c1 | REVIEW | REVIEW |
| claim:basalto-cronica:e11:c1 | ABSTAIN | REVIEW |
| claim:basalto-cronica:e14:c1 | ABSTAIN | ABSTAIN |
| claim:basalto-cronica:e17:c1 | ACCEPT | REVIEW |
| claim:basalto-cronica:e18:c1 | ABSTAIN | REVIEW |
| claim:cirro-actas:e01:c1 | REVIEW | REVIEW |
| claim:cirro-actas:e02:c1 | REVIEW | REVIEW |
| claim:cirro-actas:e04:c1 | REVIEW | REVIEW |
| claim:cirro-actas:e08:c1 | ABSTAIN | REVIEW |
| claim:cirro-actas:e09:c1 | ABSTAIN | ABSTAIN |
| claim:cirro-actas:e12:c1 | ABSTAIN | ABSTAIN |
| claim:cirro-actas:e14:c1 | ABSTAIN | ABSTAIN |
| claim:zafiro-sesion:e01:c1 | ABSTAIN | ABSTAIN |
| claim:zafiro-sesion:e14:c1 | ABSTAIN | ABSTAIN |
| claim:zafiro-sesion:e15:c1 | ACCEPT | REVIEW |

## Coste / latencia / cache de la pasada NVIDIA

- llamadas medidas (tanda completa): 40
- reales en esta corrida: 40
- latencia media: 33701.9 ms, p95: 53684.7 ms
- tokens totales: 201222
- servidas desde cache: 0
- llamadas reales (miss de cache): 42
- llamadas fallidas: 2
- reintentos de transporte: 31
- timeouts duros: 26
- errores distintos: ['ProviderUnavailable']

## Lectura para la decision del operador (cifras desnudas, sin recomendacion)

- precision del acuerdo: None (n=0)
- recall del acuerdo sobre el gold: 0.0 (0/56)
- precision solo-det: 0.5 (n=16)
- precision solo-nvidia: 0.4444 (n=9)
- discrepancias: 3
- excluidos del acuerdo por factividad/evidencia pese a coincidir en polaridad: 15
- sin cubrir por ningun carril: 13
- nota: cifras desnudas, sin recomendacion de politica: esa decision es del operador. n=56 evaluables es el mismo techo pequeno que ya declaro el programa de la puerta 4 (dev==test): cualquier precision de un subconjunto de este tamano tiene un intervalo ancho, no se trata como una cifra poblacional.

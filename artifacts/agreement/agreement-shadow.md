# Medicion en sombra: precision del subconjunto-acuerdo determinista ∧ NVIDIA

Split: `negation` (workspace `bench-negation`) -- 57 claims / 60 episodios (gold congelado, verificado por hash). Denominador evaluable: 56 (convencion B0-B3).

Generado por `scripts/agreement/measure_agreement.py`. Ninguna cifra de este
documento se escribe a mano. Modo SOMBRA pura: ningun carril escribe en Neo4j
ni decide politica; esto SOLO mide.

## Vista PRINCIPAL: acuerdo a nivel de CONTENIDO, desglosado por par de decisiones

Mismo claim gold + predicado compatible + misma polaridad, SIN exigir ACCEPT de
ningun motor. n=15, precision global=0.8667, recall sobre el gold=0.2679 (15/56).

| par de decisiones (det/nvidia) | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| ABSTAIN/ABSTAIN | 6 | 4 | 2 | 0.6667 |
| ABSTAIN/REVIEW | 3 | 3 | 0 | 1.0 |
| ACCEPT/REVIEW | 2 | 2 | 0 | 1.0 |
| REVIEW/REVIEW | 4 | 4 | 0 | 1.0 |

nota: vista PRINCIPAL del bloque: mismo claim gold + predicado compatible + misma polaridad, SIN exigir ACCEPT de ningun motor. El par de decisiones (det/nvidia) de cada caso vive en `decision_pair`; el desglose por celda es la respuesta a la pregunta del operador, no el agregado. Los pares ABSTAIN/ABSTAIN coinciden en polaridad por CONVENCION (negated=False por defecto en ambos lados, no una comprobacion real) -- ver `ambos_abstienen` en cada caso.

## Vista SECUNDARIA (tautologica, conservada por trazabilidad): acuerdo_con_accept

n=0, precision=None, recall sobre el gold=0.0.

nota: vista SECUNDARIA (criterio original de este bloque, conservado por trazabilidad): subconjunto de `acuerdo_contenido` donde AMBOS motores dan ACCEPT real. DECLARADO TAUTOLOGICO por el dictamen del revisor: exigir ACCEPT en los dos carriles multiplica dos eventos ya raros del motor (la puerta 4 mide un recall de autoaprobacion bajo), asi que la interseccion tiende a vaciarse por construccion del filtro, no por la hipotesis medida. No usar esta vista para leer 'el acuerdo no sirve': para eso esta `acuerdo_contenido`.

## Otros conjuntos

| conjunto | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| solo-det | 14 | 6 | 8 | 0.4286 |
| solo-nvidia | 10 | 5 | 5 | 0.5 |
| discrepancia: polaridades opuestas ACTIVAS | 0 | 0 | 0 | None |
| discrepancia: abstain vs afirma | 5 | -- | -- | -- |
| discrepancia: predicado incompatible | 0 | -- | -- | -- |
| sin_cubrir (ningun carril propuso nada emparejable) | 12 | -- | -- | -- |

- nota solo-det: las filas con `is_abstain=True` cuentan con `negated=False` por convencion del programa (build_rows del runner congelado), no porque el carril haya afirmado una polaridad activa: su `correct` no debe leerse como precision de aserciones activas.
- nota solo-nvidia: misma convencion que `solo_det`: `is_abstain=True` implica `negated=False` por defecto, no una polaridad comprobada.

## Diseno

- criterio de acuerdo (vista principal): VISTA PRINCIPAL. mismo claim_id del gold (alineado via episode_alignment + mention_alignment + claim_alignment del runner congelado, reutilizados por ruta), predicado top-1 compatible (o ausente en algun carril), MISMA polaridad. NO exige ningun veredicto concreto del motor: el par de decisiones (ACCEPT/ACCEPT, REVIEW/REVIEW, ACCEPT/REVIEW, ABSTAIN/x...) se publica como atributo `decision_pair` de cada caso y se desglosa aparte -- esa tabla es la que responde la pregunta del operador.
- criterio de acuerdo_con_accept (vista secundaria, tautologica): VISTA SECUNDARIA (criterio original del bloque, conservado por trazabilidad): subconjunto de acuerdo_contenido donde AMBOS carriles reciben predicted_decision=='ACCEPT' real del motor. DECLARADO TAUTOLOGICO por el dictamen del revisor: exigir ACCEPT de ambos multiplica dos eventos ya raros del motor (la puerta 4 mide un recall de autoaprobacion bajo), asi que la interseccion tiende a vaciarse por construccion del filtro, no por la hipotesis medida.
- factividad (puerta 6): la puerta 6 (review_required + hint epistemico degradado nunca ACCEPT) sigue actuando dentro del motor real que produce cada `predicted_decision`; este bloque no la reimplementa. Lo que cambia respecto de la primera version es que 'acuerdo' ya NO exige ACCEPT de ambos carriles para existir: ese filtro se mueve a `acuerdo_con_accept`, la vista secundaria.
- alineamiento reutilizado: episode_alignment/mention_alignment/claim_alignment/build_rows del runner E2E congelado (artifacts/v3-final-validation/gate4_negation_measure.py), cargado por ruta via knowledge_v3.eval._frozen_runner.load() -- nunca copiado ni modificado. Necesario porque score_extractor (benchmarks.harness) exige episode_id identico y la cadena real acuna ids propios a partir de los bytes de entrada; ver docstring del modulo.

## Casos: polaridades opuestas ACTIVAS (discrepancia semantica dura)

| claim_id | det negated | nvidia negated | gold negated |
| --- | --- | --- | --- |

## Casos: abstain vs afirma (un carril abstiene, el otro predice algo activo)

| claim_id | det decision | nvidia decision | det negated | nvidia negated | gold negated |
| --- | --- | --- | --- | --- | --- |
| claim:basalto-cronica:e01:c1 | ABSTAIN | REVIEW | False | True | True |
| claim:basalto-cronica:e05:c1 | ABSTAIN | REVIEW | False | True | True |
| claim:cirro-actas:e05:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:zafiro-sesion:e05:c1 | REVIEW | ABSTAIN | True | False | True |
| claim:zafiro-sesion:e13:c1 | REVIEW | ABSTAIN | True | False | True |

## Coste / latencia / cache de la pasada NVIDIA

- llamadas medidas (tanda completa): 41
- reales en esta corrida: 1
- latencia media: 34288.8 ms, p95: 54230.0 ms
- tokens totales: 206483
- servidas desde cache: 40
- llamadas reales (miss de cache): 2
- llamadas fallidas: 1
- reintentos de transporte: 5
- timeouts duros: 4
- errores distintos: ['ProviderUnavailable']

## Lectura para la decision del operador (cifras desnudas, sin recomendacion)

- precision del acuerdo de CONTENIDO (vista principal): 0.8667 (n=15)
- recall del acuerdo de contenido sobre el gold: 0.2679 (15/56)
- precision del acuerdo_con_accept (vista secundaria, tautologica): None (n=0)
- precision solo-det: 0.4286 (n=14)
- precision solo-nvidia: 0.5 (n=10)
- polaridades opuestas activas (discrepancia dura): 0
- abstain vs afirma: 5
- predicado incompatible: 0
- sin cubrir por ningun carril: 12
- nota: cifras desnudas, sin recomendacion de politica: esa decision es del operador. n=56 evaluables es el mismo techo pequeno que ya declaro el programa de la puerta 4 (dev==test): cualquier precision de un subconjunto de este tamano tiene un intervalo ancho, no se trata como una cifra poblacional. La cifra 'estrella' de este bloque es `precision_acuerdo_contenido`, junto con su desglose por par de decisiones -- NO `precision_acuerdo_con_accept_tautologico`, conservada solo por trazabilidad con la primera version del bloque.

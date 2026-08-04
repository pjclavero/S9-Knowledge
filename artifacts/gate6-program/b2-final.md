# Puerta 6 — B2-FINAL: correcciones de backlog y cierre de medicion

Bloque B2-FINAL: cierra el backlog diagnosticado en B1. Correccion 1 (Bug homografo): guarda de determinante en _reported_speech_cue para formas de REPORT_VERBS que son tambien sustantivos ('cuenta', 'relato') -- impide que 'la cuenta que presento' se lea como reporte de tercero. Correccion 2 (Bug scope sin 'que'): se exige un 'que' completivo inmediato tras los verbos de SCOPE_VERBS para disparar SCOPE_AMBIGUOUS -- 'no reconocio el terreno' es ahora NEGATED_FACT, no UNKNOWN. Ambas correcciones generalizan a todos los verbos de su respectiva lista (no solo a los de B1). Se anaden 6 nuevos casos al corpus de generalizacion composicional (familias REPORT_FALSE_FRIEND y SCOPE_VERB_DIRECT_OBJ, dataset version 1.2.0). REWORK de B2 (dictamen del revisor): (a) el extractor determinista de produccion queda CONECTADO al verdict de la politica (rama EMIT_EPISTEMIC_PROPOSAL), que hasta ahora era codigo muerto para ese carril; (b) el invariante fail-closed se mide ademas contra la salida REAL de DeterministicExtractor (capa `deterministic_extractor`, publicada al lado de la capa de clasificador, nunca sumada con ella); (c) los conectores de classify_negation se amplian de 'que'/'si' a la clase gramatical cerrada de interrogativas indirectas del espanol, con 5 casos nuevos de corpus (familia INDIRECT_QUESTION_SCOPE, dataset version 1.3.0). Criterio NVIDIA (79,17 %): ver seccion de notas.

## 1. Historia B0 -> B1 -> B2

### 1.1 Corpus dev (100 frases congeladas)

| bloque | policy_accuracy |
| --- | ---: |
| B0 | 0.790 |
| B1 | 0.800 |
| B2 | 0.800 |

### 1.2 Corpus de generalizacion composicional

| bloque | casos | overall_accuracy |
| --- | ---: | ---: |
| B0 | 42 | 0.381 |
| B1 | 42 | 0.762 |
| B2 | 53 | 0.811 |

### 1.3 Invariante fail-closed

| bloque | violaciones |
| --- | ---: |
| B0 | 40 |
| B1 | 23 |
| B2 | 23 |

### 1.4 Invariante fail-closed POR CAPA (rework B2)

Las dos capas se publican separadas y nunca se suman. La capa 1 dice
si la politica LEE bien la frase; la capa 2 dice si el sistema la
ESCRIBIRIA como hecho del mundo, que es lo que la puerta protege.

| capa | corpus | casos | cubiertos (emiten claim) | violaciones |
| --- | --- | ---: | ---: | ---: |
| factivity_policy | dev | 100 | n/a | 15 |
| factivity_policy | generalization | 53 | n/a | 8 |
| deterministic_extractor | dev | 100 | 4 | 0 |
| deterministic_extractor | generalization | 53 | 4 | 2 |

- Casos cuyo gold PROHIBE materializar y que ademas llegan a producir algun claim (unicos en los que la capa 2 puede violar el invariante): dev 0/77, generalizacion 2/41.
- Violaciones de capa 2 escritas SIN revision humana: 2; con hint ASSERTED (con o sin revision): 2. Estado: NO CONFORME.
  - `gen6:factive_in_cond:06` (generalization)
  - `gen6:neg_rumor_hard:02` (generalization)

- Salvedad: las menciones se anclan con un lexico construido por caso a partir de nombres propios de superficie (`proper_name_candidates`): es andamiaje de medicion, no parte del extractor
- Salvedad: la cobertura (`coverage`) se publica al lado de las violaciones: un cero sobre pocos casos cubiertos no es la misma evidencia que un cero sobre muchos

## 2. Generalizacion composicional B2 por familia

| familia | casos | exactitud |
| --- | ---: | ---: |
| CONDITIONAL_IN_RUMOR | 6 | 1.000 |
| FACTIVE_IN_CONDITIONAL | 6 | 0.833 |
| INDIRECT_QUESTION_SCOPE | 5 | 1.000 |
| LEXICAL_NEGATION_EDGE | 2 | 0.000 |
| NEGATED_RUMOR_HARD | 6 | 0.000 |
| NEGATION_OF_FACTIVE | 6 | 0.833 |
| NESTED_REPORT | 6 | 1.000 |
| POSITIVE_CONTROL | 4 | 1.000 |
| REPORT_FALSE_FRIEND | 3 | 1.000 |
| REPORT_OF_NEGATION | 6 | 1.000 |
| SCOPE_VERB_DIRECT_OBJ | 3 | 1.000 |

## 3. Violaciones fail-closed restantes por familia

| familia | violaciones |
| --- | ---: |
| ALCANCE_COMPLEJO | 4 |
| CONDICIONAL | 2 |
| CONTRAFACTUAL | 4 |
| DESEO | 2 |
| FACTIVE_IN_CONDITIONAL | 1 |
| NEGATED_RUMOR_HARD | 6 |
| NEGATION_OF_FACTIVE | 1 |
| ORDEN | 3 |

## 4. Comparacion B2 vs B1 (cambios relativos)

- Dev: mejoras 0, regresiones 0
- Gen (filas comunes): mejoras 0, regresiones 0
- Violaciones: antes 23, despues 23, resueltas 0, nuevas 0

## 5. Criterio NVIDIA

**Postura propuesta: POSTURA_A** (decision final: operador humano con dictamen del revisor)

Se propone ABANDONAR FORMALMENTE el criterio NVIDIA (79,17 %) y sustituirlo por tres metricas deterministas que el arnes ya mide y reproduce: (1) policy_accuracy sobre el corpus dev congelado (100 frases, split dev-synthetic/opus-2026-07-30), (2) overall_accuracy sobre el corpus de generalizacion composicional (53 frases tras el rework de B2), y (3) el invariante fail-closed medido en LAS DOS CAPAS -- la de clasificador y la del extractor determinista real (matiz del revisor: un invariante medido solo sobre el clasificador no dice nada sobre lo que el sistema escribe, que es justo lo que la puerta protege). Razon: el criterio NVIDIA mezcla la politica de factividad con la precision del extractor completo y con el comportamiento de un modelo externo que puede cambiar sin aviso. Estas tres metricas son ortogonales, reproducibles y no dependen de ningun proveedor. Si en el futuro se integra un ciclo de validacion con el juez NVIDIA, debe tratarse como un cuarto eje de medicion anadido, no como sustituto de los tres deterministicos. NOTA: esta propuesta la ratifica el operador humano con el dictamen del revisor -- el implementador solo propone.

## 6. Notas

- El corpus de generalizacion composicional crece de 42 casos (B0/B1) a 53 tras B2 y su rework: +3 REPORT_FALSE_FRIEND y +3 SCOPE_VERB_DIRECT_OBJ (bugs 1 y 2 de B2), +5 INDIRECT_QUESTION_SCOPE (clase completa de interrogativas indirectas, rework). Las familias nuevas no existian en B0/B1, asi que la comparacion de overall_accuracy no es directamente proporcional: B1 acertaba 32 sobre 42 casos (0.762); ahora se aciertan 43 sobre 53 (0.811) sobre el corpus AMPLIADO.
- Capa 2 (`deterministic_extractor`): el extractor determinista solo emite cuando la frase de relacion esta en su lista de reglas, asi que la COBERTURA sobre estos dos corpus es baja y se publica al lado del recuento de violaciones -- un cero de violaciones sobre pocos casos cubiertos no es la misma evidencia que sobre muchos. Ver `extractor_layer.corpora.*.coverage`.
- NEGATED_RUMOR_HARD sigue en 0,0 % (6/6 fail): la construccion 'no es cierto el rumor de que' no es substring literal de ninguna FALSITY_PHRASE porque 'el rumor de' se interpone. Es un limite arquitectonico documentado desde B0. No se toca: corregirlo requeriria una busqueda con hueco ('no es cierto ... que') que aumentaria el riesgo de falsos positivos en otros contextos.
- LEXICAL_NEGATION_EDGE sigue en 0,0 % (2/2 fail): 'nunca salio del' entra en negated_cessation (CESSATION_PHRASES incluye 'salio del') y el gold modela la frase como NEGATED_FACT directo. Corregirlo sin arriesgar las cesaciones genuinas requiere distinguir 'salida fisica' de 'pertenencia', que el vocabulario cerrado actual no hace. Documentado como limite arquitectonico desde B1 (docs/v3/44).
- gen6:neg_of_factive:04 ('Nadie en la Camara confirmo que...') sigue en ASSERTED_FACT: 'nadie' no esta en NEGATION_CUES, por lo que la logica de scope_negation no detecta la negacion universal. Aniadir 'nadie' a NEGATION_CUES afectaria a muchos casos no relacionados. Queda diagnosticado como techo restante.

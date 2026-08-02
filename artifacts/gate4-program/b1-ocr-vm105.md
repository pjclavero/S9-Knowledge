# Puerta 4 — B0: arnes de medicion (desarrollo vs. generalizacion)

Arnes de medicion anti-sobreajuste: publica cobertura y precision de desarrollo y de generalizacion lado a lado, sin mezclarlas en un solo numero. Ninguna mejora futura del extractor se acepta si solo sube el numero de desarrollo.

## 1. Cobertura

| corpus | capa | casos evaluables | cubiertos | cobertura |
| --- | --- | ---: | ---: | ---: |
| negation | pipeline_e2e | 56 | 8 | 0.143 |
| generalization | negation_classifier | 46 | 46 | 1.000 |

## 2. Metricas globales, lado a lado

| metrica | desarrollo (E2E) | generalizacion (clasificador) |
| --- | ---: | ---: |
| `auto_approval_precision` | 1.000 | n/d |
| `auto_approval_recall` | 0.062 | n/d |
| `cessation_precision` | 1.000 | n/d |
| `cessation_recall` | 0.091 | n/d |
| `evidence_grounding` | 1.000 | 1.000 |
| `false_positive_relation_from_negation` | 0 | n/d |
| `hard_scope_litotes_accuracy` | n/d | 0.000 |
| `negated_cessation_safety` | 1.000 | n/d |
| `negation_scope_accuracy` | 0.875 | 1.000 |
| `negative_edge_precision` | 1.000 | 1.000 |
| `negative_edge_recall` | 0.083 | n/d |
| `non_factive_accuracy` | n/d | 1.000 |
| `overall_accuracy` | n/d | 0.913 |
| `recall_simple` | n/d | 1.000 |

## 3. Generalizacion por familia

| familia | casos | exactitud |
| --- | ---: | ---: |
| CESSATION | 8 | 1.000 |
| DOUBLE_NEGATION | 2 | 1.000 |
| HARD_SCOPE_LITOTES | 4 | 0.000 |
| NEGATED_CESSATION | 4 | 1.000 |
| NEVER | 4 | 1.000 |
| NOT_YET | 4 | 1.000 |
| POSITIVE_CONTROL | 4 | 1.000 |
| QUESTION_CONDITIONAL_RUMOR | 4 | 1.000 |
| SCOPE_EMBEDDED | 4 | 1.000 |
| SIMPLE | 8 | 1.000 |

## 4. Puertas de desarrollo (heredadas del runner E2E)

| puerta | observado | veredicto |
| --- | ---: | --- |
| ninguna operacion positiva sobre una relacion que el gold niega | 0 | **CONFORME** |
| cero aristas positivas falsas desde negacion | 0 | **CONFORME** |
| cero cesaciones falsas desde 'no dejo de' | 1.0 | **CONFORME** |
| evidencia anclada al 100% en lo emitido | 1.0 | **CONFORME** |
| precision CESSATION destructiva 100% | None | **NO_EVALUABLE** |
| precision de alcance destructivo 100% | None | **NO_EVALUABLE** |
| alcance global >= 0.95 | 0.875 | **NO_CONFORME** |
| recall de autoaprobacion SIMPLE >= 0.75 | 0.1 | **NO_CONFORME** |

## 5. Hallazgos

- El corpus de desarrollo se mide con la cadena COMPLETA (pipeline E2E, ablacion local_only, writer en DRY-RUN); el de generalizacion se mide a nivel del CLASIFICADOR de negacion (`extraction.cues.analyze_raw_text`), la misma funcion que invoca el extractor determinista. Es una diferencia de profundidad DECLARADA: construir fixtures de contrato completos para 42 casos nuevos es el trabajo de autoria propenso a sesgo que este arnes existe para no premiar.
- Por eso `coverage` no es comparable entre los dos corpus: en desarrollo mide si la cadena entera llego a proponer una decision (baja, por diseno: ablacion sin proveedores); en generalizacion mide si el clasificador de negacion respondio (siempre responde, por construccion). Lo comparable son las metricas de PRECISION Y ALCANCE dentro de cada capa.
- El numero honesto de este bloque es el de generalizacion: si baja mucho respecto al de desarrollo en una familia dada, esa familia esta memorizada, no entendida, exactamente como le paso al motor de relaciones v2 (predicado 0.81 en dev==test, 0.24 en real).
- IMPORTANTE (tras revision CONFORME CON OBSERVACIONES): la exactitud 1.0 de las 9 familias originales de generalizacion significa 'el clasificador de negacion generaliza a ESTAS 9 FAMILIAS CONCRETAS con entidades nuevas', NO 'el clasificador generaliza a la negacion espanola'. La bateria adversarial del agente de tests (`tests/test_gate4_harness_adversarial.py::test_documenta_fallos_del_clasificador_en_frases_nuevas_fuera_de_corpus`) prueba 8 frases nuevas fuera de ambos corpus y encuentra 4 fallos: subordinada exceptiva 'sin que', litotes correctiva 'no es que no...', cesacion perifrastica 'ha dejado atras' y litotes cuantitativa 'no pocos' -- los mismos cuatro fenomenos que ahora mide, con casos propios, la familia `HARD_SCOPE_LITOTES` de este corpus (ver mas abajo).
- La familia `HARD_SCOPE_LITOTES` (4 casos, dominio 'archivos', entidades nuevas que no repiten ninguna frase de la bateria adversarial) publica la exactitud de esas cuatro construcciones duras POR SEPARADO (`metrics_global.hard_scope_litotes_accuracy` y la fila `HARD_SCOPE_LITOTES` de la tabla por familia). Se espera BAJA -- es el liston que B2 (reglas) y B4 (carril semantico) tienen que subir, no un defecto de este arnes.
- LIMITACION CONOCIDA (TODO, ver tambien `tests/test_gate4_harness.py::test_ningun_nombre_propio_de_desarrollo_aparece_en_los_textos_de_generalizacion`): el detector de no-solapamiento inverso (nombres de desarrollo dentro de los textos de generalizacion) ignora nombres propios de menos de 6 caracteres para evitar falsos positivos por coincidir con una silaba de otra palabra. Un nombre corto de desarrollo reutilizado en generalizacion NO seria atrapado por este chequeo concreto (si lo atraparia el chequeo directo por entidad, que compara nombres completos sin umbral). Pendiente: sustituir el umbral de longitud por una lista explicita de palabras vacias.

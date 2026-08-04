# Puerta 4 - B4: analisis morfologico/estructural

Veredicto del bloque: **CONFORME**

Generado por `scripts/gate4/measure_b4.py`. Ninguna cifra de este
documento se escribe a mano. Baseline comparado: `artifacts/gate4-program/b2-resultado.json`.

## Puertas

| puerta | umbral | observado | veredicto |
| --- | --- | --- | --- |
| cobertura_e2e_dev | 0.6 | 0.607143 | CONFORME |
| recall_simple_generalizacion | 0.7 | 1.0 | CONFORME |
| familias_generalizacion_no_duras | 1.0 | 1.0 | CONFORME |
| hard_scope_litotes_estable_o_mejor_que_b2 | - | 0.5 | CONFORME |
| scope_embedded_generaliza_a_reporte_morfologico | - | - | CONFORME |
| invariantes_de_precision | - | - | CONFORME |

## Corpus de desarrollo (cadena E2E)

- cobertura: 0.607143 (34/56)
- auto_approval_precision: 1.0
- auto_approval_recall: 0.0625
- cessation_precision: 1.0
- cessation_recall: 0.454545
- evidence_grounding: 1.0
- false_positive_relation_from_negation: 0
- negated_cessation_safety: 1.0
- negation_scope_accuracy: 0.647059
- negative_edge_precision: 1.0
- negative_edge_recall: 0.222222

## Corpus de generalizacion (clasificador de negacion)

| familia | casos | exactitud |
| --- | --- | --- |
| CESSATION | 8 | 1.0 |
| DOUBLE_NEGATION | 2 | 1.0 |
| HARD_SCOPE_LITOTES | 4 | 0.5 |
| NEGATED_CESSATION | 4 | 1.0 |
| NEVER | 4 | 1.0 |
| NOT_YET | 4 | 1.0 |
| POSITIVE_CONTROL | 4 | 1.0 |
| QUESTION_CONDITIONAL_RUMOR | 4 | 1.0 |
| SCOPE_EMBEDDED | 6 | 1.0 |
| SIMPLE | 8 | 1.0 |

## Notas del arnes

- El corpus de desarrollo se mide con la cadena COMPLETA (pipeline E2E, ablacion local_only, writer en DRY-RUN); el de generalizacion se mide a nivel del CLASIFICADOR de negacion (`extraction.cues.analyze_raw_text`), la misma funcion que invoca el extractor determinista. Es una diferencia de profundidad DECLARADA: construir fixtures de contrato completos para 42 casos nuevos es el trabajo de autoria propenso a sesgo que este arnes existe para no premiar.
- Por eso `coverage` no es comparable entre los dos corpus: en desarrollo mide si la cadena entera llego a proponer una decision (baja, por diseno: ablacion sin proveedores); en generalizacion mide si el clasificador de negacion respondio (siempre responde, por construccion). Lo comparable son las metricas de PRECISION Y ALCANCE dentro de cada capa.
- El numero honesto de este bloque es el de generalizacion: si baja mucho respecto al de desarrollo en una familia dada, esa familia esta memorizada, no entendida, exactamente como le paso al motor de relaciones v2 (predicado 0.81 en dev==test, 0.24 en real).
- IMPORTANTE (tras revision CONFORME CON OBSERVACIONES): la exactitud 1.0 de las 9 familias originales de generalizacion significa 'el clasificador de negacion generaliza a ESTAS 9 FAMILIAS CONCRETAS con entidades nuevas', NO 'el clasificador generaliza a la negacion espanola'. La bateria adversarial del agente de tests (`tests/test_gate4_harness_adversarial.py::test_documenta_fallos_del_clasificador_en_frases_nuevas_fuera_de_corpus`) prueba 8 frases nuevas fuera de ambos corpus y encuentra 4 fallos: subordinada exceptiva 'sin que', litotes correctiva 'no es que no...', cesacion perifrastica 'ha dejado atras' y litotes cuantitativa 'no pocos' -- los mismos cuatro fenomenos que ahora mide, con casos propios, la familia `HARD_SCOPE_LITOTES` de este corpus (ver mas abajo).
- La familia `HARD_SCOPE_LITOTES` (4 casos, dominio 'archivos', entidades nuevas que no repiten ninguna frase de la bateria adversarial) publica la exactitud de esas cuatro construcciones duras POR SEPARADO (`metrics_global.hard_scope_litotes_accuracy` y la fila `HARD_SCOPE_LITOTES` de la tabla por familia). Se espera BAJA -- es el liston que B2 (reglas) y B4 (carril semantico) tienen que subir, no un defecto de este arnes.
- LIMITACION CONOCIDA (TODO, ver tambien `tests/test_gate4_harness.py::test_ningun_nombre_propio_de_desarrollo_aparece_en_los_textos_de_generalizacion`): el detector de no-solapamiento inverso (nombres de desarrollo dentro de los textos de generalizacion) ignora nombres propios de menos de 6 caracteres para evitar falsos positivos por coincidir con una silaba de otra palabra. Un nombre corto de desarrollo reutilizado en generalizacion NO seria atrapado por este chequeo concreto (si lo atraparia el chequeo directo por entidad, que compara nombres completos sin umbral). Pendiente: sustituir el umbral de longitud por una lista explicita de palabras vacias.

## Hallazgo honesto de B4

La cobertura E2E de desarrollo NO se movio respecto a B2 (34/56). Los dos casos que la taxonomia identificaba como candidatos morfologicos (`cirro-actas:e13`/`e14`, familia SCOPE_EMBEDDED) usan un sujeto de cuantificador negativo ('Nadie ha afirmado que...') en vez del patron 'no <verbo de reporte>' que el paradigma -AR ataca; resolverlos exige reconocer el ALCANCE DE UN CUANTIFICADOR, un fenomeno distinto del declarado para este bloque (conjugacion regular), y no se fuerzo una regla ad-hoc para dos casos concretos del corpus. Ver `artifacts/gate4-program/b4-taxonomia.md` para la clasificacion completa de los 22 casos NO_OUTPUT restantes.

Lo que si se demuestra es que `SCOPE_VERBS` generaliza: los dos casos nuevos del corpus de generalizacion (`gen:scope:05`/`06`, verbos 'declarar'/'asegurar' generados por el paradigma, ausentes del lexico literal anterior a B4) se clasifican correctamente con exactitud 1.0, sin tocar ningun literal de corpus.

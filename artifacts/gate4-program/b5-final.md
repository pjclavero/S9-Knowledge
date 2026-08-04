# Puerta 4 - B5 (FINAL): re-medicion integra y dictamen del programa

Veredicto de la PUERTA 4: **PARCIAL**

Generado por `scripts/gate4/measure_b5.py`. Ninguna cifra de este
documento se escribe a mano. Baseline comparado (reproducibilidad): `artifacts/gate4-program/b4-resultado.json`.

## 0. Reproducibilidad frente a B4

Reproduce EXACTO: cero discrepancias frente a `b4-resultado.json`.

## 1. Criterios de la puerta (fijados por el operador)

| criterio | umbral | observado | veredicto |
| --- | --- | --- | --- |
| 1_cobertura_e2e_dev | 0.6 | 0.607143 | CONFORME |
| 2_recall_simple_EN_DESARROLLO | 0.7 | 0.1 | NO_CONFORME |
| 2b_recall_simple_generalizacion_clasificador_referencia | - | 1.0 | - |
| 3_generalizacion_acompana | 1.0 | 1.0 | CONFORME |
| invariantes_de_precision | - | - | CONFORME |

## 2. Corpus de desarrollo (cadena E2E)

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

### Puertas heredadas del runner E2E congelado

| puerta | observado | veredicto |
| --- | ---: | --- |
| ninguna operacion positiva sobre una relacion que el gold niega | 0 | CONFORME |
| cero aristas positivas falsas desde negacion | 0 | CONFORME |
| cero cesaciones falsas desde 'no dejo de' | 1.0 | CONFORME |
| evidencia anclada al 100% en lo emitido | 1.0 | CONFORME |
| precision CESSATION destructiva 100% | None | NO_EVALUABLE |
| precision de alcance destructivo 100% | None | NO_EVALUABLE |
| alcance global >= 0.95 | 0.647059 | NO_CONFORME |
| recall de autoaprobacion SIMPLE >= 0.75 | 0.1 | NO_CONFORME |

## 3. Corpus de generalizacion (clasificador de negacion)

| familia | casos | exactitud |
| --- | ---: | ---: |
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

## 4. Notas del arnes

- El corpus de desarrollo se mide con la cadena COMPLETA (pipeline E2E, ablacion local_only, writer en DRY-RUN); el de generalizacion se mide a nivel del CLASIFICADOR de negacion (`extraction.cues.analyze_raw_text`), la misma funcion que invoca el extractor determinista. Es una diferencia de profundidad DECLARADA: construir fixtures de contrato completos para 42 casos nuevos es el trabajo de autoria propenso a sesgo que este arnes existe para no premiar.
- Por eso `coverage` no es comparable entre los dos corpus: en desarrollo mide si la cadena entera llego a proponer una decision (baja, por diseno: ablacion sin proveedores); en generalizacion mide si el clasificador de negacion respondio (siempre responde, por construccion). Lo comparable son las metricas de PRECISION Y ALCANCE dentro de cada capa.
- El numero honesto de este bloque es el de generalizacion: si baja mucho respecto al de desarrollo en una familia dada, esa familia esta memorizada, no entendida, exactamente como le paso al motor de relaciones v2 (predicado 0.81 en dev==test, 0.24 en real).
- IMPORTANTE (tras revision CONFORME CON OBSERVACIONES): la exactitud 1.0 de las 9 familias originales de generalizacion significa 'el clasificador de negacion generaliza a ESTAS 9 FAMILIAS CONCRETAS con entidades nuevas', NO 'el clasificador generaliza a la negacion espanola'. La bateria adversarial del agente de tests (`tests/test_gate4_harness_adversarial.py::test_documenta_fallos_del_clasificador_en_frases_nuevas_fuera_de_corpus`) prueba 8 frases nuevas fuera de ambos corpus y encuentra 4 fallos: subordinada exceptiva 'sin que', litotes correctiva 'no es que no...', cesacion perifrastica 'ha dejado atras' y litotes cuantitativa 'no pocos' -- los mismos cuatro fenomenos que ahora mide, con casos propios, la familia `HARD_SCOPE_LITOTES` de este corpus (ver mas abajo).
- La familia `HARD_SCOPE_LITOTES` (4 casos, dominio 'archivos', entidades nuevas que no repiten ninguna frase de la bateria adversarial) publica la exactitud de esas cuatro construcciones duras POR SEPARADO (`metrics_global.hard_scope_litotes_accuracy` y la fila `HARD_SCOPE_LITOTES` de la tabla por familia). Se espera BAJA -- es el liston que B2 (reglas) y B4 (carril semantico) tienen que subir, no un defecto de este arnes.
- LIMITACION CONOCIDA (TODO, ver tambien `tests/test_gate4_harness.py::test_ningun_nombre_propio_de_desarrollo_aparece_en_los_textos_de_generalizacion`): el detector de no-solapamiento inverso (nombres de desarrollo dentro de los textos de generalizacion) ignora nombres propios de menos de 6 caracteres para evitar falsos positivos por coincidir con una silaba de otra palabra. Un nombre corto de desarrollo reutilizado en generalizacion NO seria atrapado por este chequeo concreto (si lo atraparia el chequeo directo por entidad, que compara nombres completos sin umbral). Pendiente: sustituir el umbral de longitud por una lista explicita de palabras vacias.

## 5. Dictamen honesto de la puerta 4

1. Cobertura E2E de desarrollo >= 0.60: **CONFORME** (0.607143, 34/56).
2. Recall SIMPLE >= 0.70 EN DESARROLLO (decision de motor AUTO_APPROVE, no clasificador aislado): **NO_CONFORME** (0.1). La cifra que en B2/B4 se citaba como "recall_simple" (1.0) es la del CLASIFICADOR sobre el corpus de generalizacion, una capa mas facil; NO es la puerta de desarrollo que fijo el operador. Bajo esa medida correcta, el recall SIMPLE de desarrollo es bajo desde B0 y NO ha mejorado en ningun bloque del programa: la cobertura general subio (B2, reglas de cobertura) pero la decision de AUTO-APROBACION sobre los casos SIMPLE de desarrollo sigue sin llegar al umbral.
3. La generalizacion acompana (familias no duras a 1.0, HARD_SCOPE_LITOTES con causa estructural documentada): **CONFORME**.

Con el criterio 2 sin cumplir, el veredicto GLOBAL de la puerta 4 es **PARCIAL**: los invariantes de precision se mantienen intactos (nada se autoaprueba de mas, cero falsos positivos), la cobertura y la generalizacion cumplen su liston, pero el criterio de recall SIMPLE en desarrollo, medido correctamente contra la decision real del motor, no llega al 0.70 fijado por el operador.

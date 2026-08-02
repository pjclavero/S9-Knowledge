# Puerta 4 — Negaciones extremo a extremo en sombra

Corrida real de la cadena completa sobre el split `negation` (solo lectura), extraccion determinista, writer en DRY-RUN. Todos los numeros de este informe salen de un conteo sobre la salida de esa corrida; ninguno esta estimado.

## 1. Configuracion

| clave | valor |
| --- | --- |
| `split` | negation |
| `workspace` | bench-negation |
| `ablation` | local_only |
| `entry` | raw |
| `semantic_shadow_evaluation` | si |
| `graduated_negation_policy` | si |
| `graduated_temporal_policy` | si |
| `negation_policy_at_engine` | si |
| `accept_negated` | si |
| `emit_projection` | si |
| `writer_mode` | DRY_RUN |
| `providers` | local_only |
| `ollama_active` | no |
| `external_active` | no |

## 2. Corpus y cobertura

El gold trae **57 claims**, de los que **56** declaran polaridad y son evaluables, mas **4** negativos `NO_CLAIM`. La cadena emitio una decision para **8** de ellos (cobertura 0.143).

| fuente | episodios | claims | decisiones | parada |
| --- | ---: | ---: | ---: | --- |
| ambar-escaneo | 22 | 0 | 0 | el extractor no propuso ningun claim para esta fuente |
| basalto-cronica | 18 | 5 | 5 | — |
| cirro-actas | 16 | 1 | 1 | — |
| zafiro-sesion | 8 | 5 | 5 | — |

## 3. Metricas globales

| metrica | valor | vista |
| --- | ---: | --- |
| `negative_edge_precision` | 1.000 | covered |
| `negative_edge_recall` | 0.083 | full |
| `negated_cessation_safety` | 1.000 | full |
| `cessation_precision` | 1.000 | covered |
| `cessation_recall` | 0.091 | full |
| `negation_scope_accuracy` | 0.875 | covered |
| `evidence_grounding` | 1.000 | covered |
| `false_positive_relation_from_negation` | 0 | full |
| `auto_approval_precision` | 1.000 | covered |
| `auto_approval_recall` | 0.062 | full |

`covered` = solo los casos para los que el sistema emitio decision; `full` = los 56 casos evaluables del gold, contando como fallo los que la cadena no vio.

## 4. Por familia

| familia | casos | cubiertos | neg-P | neg-R | no-cese | ces-P | ces-R | alcance | evid. | FP+ | auto-P | auto-R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SIMPLE | 11 | 2 | 1.000 | 0.100 | n/d | n/d | n/d | 0.500 | 1.000 | 0 | 1.000 | 0.100 |
| NEVER | 6 | 0 | n/d | 0.000 | n/d | n/d | n/d | n/d | n/d | 0 | n/d | 0.000 |
| CESSATION | 10 | 1 | 1.000 | 0.100 | n/d | 1.000 | 0.100 | 1.000 | 1.000 | 0 | n/d | n/d |
| NEGATED_CESSATION | 8 | 0 | n/d | n/d | 1.000 | n/d | n/d | n/d | n/d | 0 | n/d | n/d |
| NOT_YET | 5 | 1 | 1.000 | 0.200 | n/d | n/d | n/d | 1.000 | 1.000 | 0 | n/d | n/d |
| SCOPE_EMBEDDED | 5 | 0 | n/d | 0.000 | n/d | n/d | n/d | n/d | n/d | 0 | n/d | n/d |
| QUESTION_CONDITIONAL_RUMOR | 3 | 0 | n/d | 0.000 | n/d | n/d | 0.000 | n/d | n/d | 0 | n/d | n/d |
| DOUBLE_NEGATION | 2 | 0 | n/d | 0.000 | n/d | n/d | n/d | n/d | n/d | 0 | n/d | n/d |
| POSITIVE_CONTROL | 6 | 4 | n/d | n/d | n/d | n/d | n/d | 1.000 | 1.000 | 0 | 1.000 | n/d |

`NO_CLAIM` (4 negativos, 0 con episodio alineado): 0 violaciones, exactitud n/d.

## 5. Puertas

| puerta | umbral | observado | veredicto |
| --- | ---: | ---: | --- |
| ninguna operacion positiva sobre una relacion que el gold niega | 0 | 0 | **CONFORME** |
| cero aristas positivas falsas desde negacion | 0 | 0 | **CONFORME** |
| cero cesaciones falsas desde 'no dejo de' | 1.000 | 1.000 | **CONFORME** |
| evidencia anclada al 100% en lo emitido | 1.000 | 1.000 | **CONFORME** |
| precision CESSATION destructiva 100% | 1.000 | n/d | **NO_EVALUABLE** |
| precision de alcance destructivo 100% | 1.000 | n/d | **NO_EVALUABLE** |
| alcance global >= 0.95 | 0.950 | 0.875 | **NO_CONFORME** |
| recall de autoaprobacion SIMPLE >= 0.75 | 0.750 | 0.100 | **NO_CONFORME** |

Una puerta marcada `NO_EVALUABLE` no es una puerta aprobada: significa que su denominador es 0 y que la corrida no produjo ni un solo caso con el que juzgarla.

## 6. Las dos variantes

| metrica | graduated_at_engine | extractor_forces_review |
| --- | ---: | ---: |
| `negative_edge_precision` | 1.000 | 1.000 |
| `negative_edge_recall` | 0.083 | 0.083 |
| `negated_cessation_safety` | 1.000 | 1.000 |
| `cessation_precision` | 1.000 | 1.000 |
| `cessation_recall` | 0.091 | 0.091 |
| `negation_scope_accuracy` | 0.875 | 0.875 |
| `evidence_grounding` | 1.000 | 1.000 |
| `false_positive_relation_from_negation` | 0 | 0 |
| `auto_approval_precision` | 1.000 | 1.000 |
| `auto_approval_recall` | 0.062 | 0.000 |

`graduated_at_engine` (`negation_policy_at_engine=True`) es la variante que puntua las puertas: es la unica en la que la politica graduada del motor llega a decidir. Con el valor por defecto de `PipelineConfig` (`negation_policy_at_engine=False`), el extractor determinista marca revision en TODA negacion y ninguna negacion puede autoaprobarse jamas, decida lo que decida el motor.

## 7. Sombra y writer

Evaluacion en sombra activa con **0 registros**. La sombra solo compara claims del paso `extract.semantic`, y esta corrida no lo ejecuta porque no se admite ningun proveedor: la cobertura de la sombra es 0 y no debe leerse como que la sombra este validada.

Writer en **DRY_RUN**: 2 planes, 2 aprobados, 5 operaciones (CREATE_ASSERTION, PROJECT_RELATION), resultado SIMULATED. Nada llega a Neo4j.

## 8. Hallazgos

- Corrida sin proveedores (ablacion local_only): extraccion DETERMINISTA. Ollama y el carril externo estan reservados por otro agente y no se usan. Esa es la causa dominante de la cobertura baja: el extractor determinista solo propone claim para 8 de los 56 casos evaluables.
- Writer en DRY-RUN (apply=False, sin driver): ninguna operacion llega a Neo4j.
- El corpus se ha leido; no se ha modificado ningun fichero suyo, ni se ha ampliado con casos propios: las puertas se miden sobre la bateria tal cual.
- Evaluacion en sombra activa, 0 registros. La sombra solo compara claims del paso `extract.semantic`, que esta corrida no ejecuta por no admitir proveedores: es cobertura 0 de la sombra, NO una sombra validada.
- La entrada por episodios no se puede usar en este corpus: 3 de sus 4 fuentes omiten las claves opcionales speaker/turn/table y `SourceEpisode.from_dict` las exige (falla con V3ContractError). Se entra por bytes, que ademas es la ruta completa que la puerta pide.
- La fuente `ambar-escaneo` (22 episodios, modalidad IMAGE) llega sin texto: sin `visual_provider` no hay OCR, el extractor no propone nada y la cadena se detiene en el motor. Sus casos entran como no cubiertos.
- Fallo de ALCANCE medido, caso a caso: NEG-SIMPLE-01 (SIMPLE) esperaba negado=True y salio negado=False con decision ABSTAIN.
- Ninguna operacion positiva del plan afirma una relacion que el gold declara negada (36 claves negadas comprobadas contra todas las operaciones del plan). Es la comprobacion de seguridad que no depende del alineamiento.
- Dos variantes medidas. `graduated_at_engine` (principal): el extractor no marca revision por negar y decide la politica graduada del motor. `extractor_forces_review`: el defecto de `PipelineConfig`, donde toda negacion va a revision desde el extractor y NINGUNA negacion puede autoaprobarse. Las puertas se puntuan sobre la principal; la otra se publica al lado.

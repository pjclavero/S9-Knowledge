# Puerta 6 — B0: arnes de medicion (dev vs. generalizacion composicional)

Arnes de medicion de la factividad composicional: publica la exactitud de la politica de factualidad sobre el corpus dev congelado y sobre un corpus NUEVO de composicion de operadores, lado a lado, sin mezclarlas en un solo numero. No se toca `extraction/factivity.py` ni `cues.py` en este bloque: B0 mide, no corrige.

## 1. Cifras globales

| corpus | casos | metrica | valor |
| --- | ---: | --- | ---: |
| dev (`dev-synthetic`) | 100 | `policy_accuracy` | 0.790 |
| generalizacion | 42 | `overall_accuracy` | 0.381 |
| generalizacion | 42 | `hard_family_accuracy` | 0.000 |
| generalizacion | 42 | `non_hard_accuracy` | 0.444 |

## 2. Desarrollo por familia

| familia | casos | exactitud |
| --- | ---: | ---: |
| ALCANCE_COMPLEJO | 4 | 0.000 |
| CONDICIONAL | 10 | 0.700 |
| CONTRAFACTUAL | 10 | 0.600 |
| DESEO | 8 | 0.750 |
| FALSEDAD_ATRIBUIDA | 8 | 0.750 |
| FICCION_EN_FICCION | 8 | 1.000 |
| HECHO_AFIRMADO | 10 | 1.000 |
| HIPOTESIS | 10 | 1.000 |
| NEGACION_FACTUAL | 10 | 0.700 |
| ORDEN | 8 | 0.625 |
| PREGUNTA | 10 | 1.000 |
| RUMOR | 4 | 1.000 |

## 3. Generalizacion composicional por familia

| familia | casos | exactitud | dura |
| --- | ---: | ---: | :---: |
| CONDITIONAL_IN_RUMOR | 6 | 1.000 |  |
| FACTIVE_IN_CONDITIONAL | 6 | 0.833 |  |
| NEGATED_RUMOR_HARD | 6 | 0.000 | sí |
| NEGATION_OF_FACTIVE | 6 | 0.167 |  |
| NESTED_REPORT | 6 | 0.000 |  |
| POSITIVE_CONTROL | 6 | 0.667 |  |
| REPORT_OF_NEGATION | 6 | 0.000 |  |

## 4. Invariante fail-closed

**Estado: NO CONFORME**

ningun caso cuyo gold exige abstenerse (dev: ABSTAIN/DIAGNOSTIC; generalizacion: NON_FACTIVE) debe leerse como ASSERTED_FACT o NEGATED_FACT

| corpus | caso | familia | clase leída |
| --- | --- | --- | --- |
| dev | fact:condicional:04 | CONDICIONAL | NEGATED_FACT |
| dev | fact:condicional:07 | CONDICIONAL | ASSERTED_FACT |
| dev | fact:condicional:10 | CONDICIONAL | ASSERTED_FACT |
| dev | fact:contrafactual:02 | CONTRAFACTUAL | NEGATED_FACT |
| dev | fact:contrafactual:05 | CONTRAFACTUAL | ASSERTED_FACT |
| dev | fact:contrafactual:06 | CONTRAFACTUAL | NEGATED_FACT |
| dev | fact:contrafactual:07 | CONTRAFACTUAL | ASSERTED_FACT |
| dev | fact:deseo:05 | DESEO | ASSERTED_FACT |
| dev | fact:deseo:07 | DESEO | ASSERTED_FACT |
| dev | fact:orden:01 | ORDEN | NEGATED_FACT |
| dev | fact:orden:03 | ORDEN | ASSERTED_FACT |
| dev | fact:orden:05 | ORDEN | ASSERTED_FACT |
| dev | fact:alcance-complejo:01 | ALCANCE_COMPLEJO | NEGATED_FACT |
| dev | fact:alcance-complejo:02 | ALCANCE_COMPLEJO | NEGATED_FACT |
| dev | fact:alcance-complejo:03 | ALCANCE_COMPLEJO | ASSERTED_FACT |
| dev | fact:alcance-complejo:04 | ALCANCE_COMPLEJO | NEGATED_FACT |
| generalization | gen6:nested_report:01 | NESTED_REPORT | ASSERTED_FACT |
| generalization | gen6:nested_report:02 | NESTED_REPORT | ASSERTED_FACT |
| generalization | gen6:nested_report:03 | NESTED_REPORT | ASSERTED_FACT |
| generalization | gen6:nested_report:04 | NESTED_REPORT | ASSERTED_FACT |
| generalization | gen6:nested_report:05 | NESTED_REPORT | ASSERTED_FACT |
| generalization | gen6:nested_report:06 | NESTED_REPORT | ASSERTED_FACT |
| generalization | gen6:neg_of_factive:02 | NEGATION_OF_FACTIVE | NEGATED_FACT |
| generalization | gen6:neg_of_factive:03 | NEGATION_OF_FACTIVE | NEGATED_FACT |
| generalization | gen6:neg_of_factive:04 | NEGATION_OF_FACTIVE | ASSERTED_FACT |
| generalization | gen6:neg_of_factive:05 | NEGATION_OF_FACTIVE | NEGATED_FACT |
| generalization | gen6:neg_of_factive:06 | NEGATION_OF_FACTIVE | NEGATED_FACT |
| generalization | gen6:factive_in_cond:06 | FACTIVE_IN_CONDITIONAL | ASSERTED_FACT |
| generalization | gen6:neg_rumor_hard:01 | NEGATED_RUMOR_HARD | NEGATED_FACT |
| generalization | gen6:neg_rumor_hard:02 | NEGATED_RUMOR_HARD | NEGATED_FACT |
| generalization | gen6:neg_rumor_hard:03 | NEGATED_RUMOR_HARD | NEGATED_FACT |
| generalization | gen6:neg_rumor_hard:04 | NEGATED_RUMOR_HARD | ASSERTED_FACT |
| generalization | gen6:neg_rumor_hard:05 | NEGATED_RUMOR_HARD | NEGATED_FACT |
| generalization | gen6:neg_rumor_hard:06 | NEGATED_RUMOR_HARD | ASSERTED_FACT |
| generalization | gen6:report_of_neg:01 | REPORT_OF_NEGATION | NEGATED_FACT |
| generalization | gen6:report_of_neg:02 | REPORT_OF_NEGATION | NEGATED_FACT |
| generalization | gen6:report_of_neg:03 | REPORT_OF_NEGATION | NEGATED_FACT |
| generalization | gen6:report_of_neg:04 | REPORT_OF_NEGATION | NEGATED_FACT |
| generalization | gen6:report_of_neg:05 | REPORT_OF_NEGATION | NEGATED_FACT |
| generalization | gen6:report_of_neg:06 | REPORT_OF_NEGATION | NEGATED_FACT |

## 5. Notas

- El numero de desarrollo de este arnes (policy_accuracy sobre las 100 frases) reproduce F6-7 de `gate6-findings.md` ('79/100 correctas'), NO el 79,17 % de F6-3 (ese es acuerdo de ACCION entre carriles det+combined+nvidia, que exige un extractor completo y un proveedor NVIDIA en vivo -- no reproducible de forma determinista y sin red por este arnes). Ver docstring del modulo.
- El corpus de generalizacion de este bloque mide un eje DISTINTO del de `factivity_generalization_probe.py` (0,231): aquel prueba vocabulario nuevo con UN operador por frase; este prueba COMPOSICION de operadores en su mayoria conocidos. Una exactitud baja aqui no es el mismo hallazgo que el 0,231 -- es un hallazgo relacionado, sobre el fallo de la precedencia plana al combinar marcos, no sobre el vocabulario ausente.
- La familia `NEGATED_RUMOR_HARD` se declara HARD por adelantado: se espera una exactitud baja porque 'no es cierto el rumor de que' no es substring literal de ninguna FALSITY_PHRASE (la interposicion de 'el rumor de' rompe el match). El gold no se ajusto para que el sistema acertase.
- Regla de aceptacion heredada de la fase 3 de la validacion V3: ninguna mejora futura de `cues.py`/`factivity.py` se acepta si solo sube el numero de desarrollo. La sonda de generalizacion (esta, y la de vocabulario) es el criterio de aceptacion, y debe ejecutarse ANTES de tocar la politica, no despues.

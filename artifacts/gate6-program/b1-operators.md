# Puerta 6 — B1: operadores (discurso reportado, 'mientras no', extension de SCOPE_VERBS)

Bloque B1: cierra, por prioridad del dictamen del revisor, el operador de discurso reportado por tercero (familias NESTED_REPORT + REPORT_OF_NEGATION, 12/40 violaciones de B0), 'mientras no' como condicional sin convertir usos temporales, y diagnostica (sin corregir, por riesgo de sobreajuste) el bug de 'nunca' con objeto locativo. Extiende ademas SCOPE_VERBS con verbos factivos/de reconocimiento (admitir/reconocer/verificar/aceptar), bonus de bajo riesgo sobre la misma familia arquitectonica ya cubierta por 'confirmar'. Compara fila a fila contra b0-baseline.json: ninguna cifra de esta comparacion esta escrita a mano.

## 1. Cifras globales, antes (B0) / despues (B1)

| corpus | metrica | B0 | B1 |
| --- | --- | ---: | ---: |
| dev | `policy_accuracy` | 0.790 | 0.800 |
| generalizacion | `overall_accuracy` | 0.381 | 0.762 |
| generalizacion | `hard_family_accuracy` | 0.000 | 0.000 |
| generalizacion | `non_hard_accuracy` | 0.444 | 0.889 |

## 2. Invariante fail-closed: violaciones

- Antes (B0): **40**
- Despues (B1): **23**
- Resueltas: **17**
- Nuevas (regresion): **0**

### Violaciones que siguen abiertas

| familia | casos |
| --- | ---: |
| ALCANCE_COMPLEJO | 4 |
| CONDICIONAL | 2 |
| CONTRAFACTUAL | 4 |
| DESEO | 2 |
| FACTIVE_IN_CONDITIONAL | 1 |
| NEGATED_RUMOR_HARD | 6 |
| NEGATION_OF_FACTIVE | 1 |
| ORDEN | 3 |

## 3. Cambios caso a caso (dev)

Mejoras: 1 · Regresiones: 0 · Cambio de clase sin cambio de veredicto: 0

- MEJORA `fact:condicional:04` (CONDICIONAL): NEGATED_FACT -> CONDITIONAL

## 4. Cambios caso a caso (generalizacion composicional)

Mejoras: 16 · Regresiones: 0 · Cambio de clase sin cambio de veredicto: 0

- MEJORA `gen6:nested_report:01` (NESTED_REPORT): ASSERTED_FACT -> RUMOR
- MEJORA `gen6:nested_report:02` (NESTED_REPORT): ASSERTED_FACT -> RUMOR
- MEJORA `gen6:nested_report:03` (NESTED_REPORT): ASSERTED_FACT -> RUMOR
- MEJORA `gen6:nested_report:04` (NESTED_REPORT): ASSERTED_FACT -> RUMOR
- MEJORA `gen6:nested_report:05` (NESTED_REPORT): ASSERTED_FACT -> RUMOR
- MEJORA `gen6:nested_report:06` (NESTED_REPORT): ASSERTED_FACT -> RUMOR
- MEJORA `gen6:neg_of_factive:02` (NEGATION_OF_FACTIVE): NEGATED_FACT -> UNKNOWN
- MEJORA `gen6:neg_of_factive:03` (NEGATION_OF_FACTIVE): NEGATED_FACT -> UNKNOWN
- MEJORA `gen6:neg_of_factive:05` (NEGATION_OF_FACTIVE): NEGATED_FACT -> UNKNOWN
- MEJORA `gen6:neg_of_factive:06` (NEGATION_OF_FACTIVE): NEGATED_FACT -> UNKNOWN
- MEJORA `gen6:report_of_neg:01` (REPORT_OF_NEGATION): NEGATED_FACT -> RUMOR
- MEJORA `gen6:report_of_neg:02` (REPORT_OF_NEGATION): NEGATED_FACT -> RUMOR
- MEJORA `gen6:report_of_neg:03` (REPORT_OF_NEGATION): NEGATED_FACT -> RUMOR
- MEJORA `gen6:report_of_neg:04` (REPORT_OF_NEGATION): NEGATED_FACT -> RUMOR
- MEJORA `gen6:report_of_neg:05` (REPORT_OF_NEGATION): NEGATED_FACT -> RUMOR
- MEJORA `gen6:report_of_neg:06` (REPORT_OF_NEGATION): NEGATED_FACT -> RUMOR

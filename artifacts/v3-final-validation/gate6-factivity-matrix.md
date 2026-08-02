# Puerta 6 — No-factividad medida

Corpus: `data-engine/app/knowledge_v3/benchmarks/datasets/factivity/cases.json` · split `dev-synthetic` · 100 casos · procedencia `dev-synthetic/opus-2026-07-30`.

> El corpus es **dev-synthetic**: mide cobertura de familias de no-factividad, **no** generaliza a producción.

## Carriles ejecutados

| Carril | Modelo | Latencia mediana | Pared (s) | Errores |
|---|---|---|---|---|
| `combined` | — | 4 ms | 0.8 | 0 |
| `det` | — | 4 ms | 0.8 | 0 |
| `nvidia` | meta/llama-3.3-70b-instruct | 40451 ms | 1170.0 | 0 |
| `ollama` | qwen2.5:7b | 588879 ms | 1716.7 | 0 |

## Prueba de vacuidad (controles positivos)

Un carril que no produce ningún hecho aprueba todos los gates de seguridad por inanición. Se comprueba primero.

| Carril | Hechos en controles | ¿Vacuo? |
|---|---|---|
| `combined` | 0 | **SÍ — gates no interpretables** |
| `det` | 0 | **SÍ — gates no interpretables** |
| `nvidia` | 6 | no |
| `ollama` | 0 | **SÍ — gates no interpretables** |

## Gates

| Gate | Carril | Observado | Umbral | Estado |
|---|---|---|---|---|
| carril util (no vacuo) | `combined` | 0 | > 0 hechos en controles positivos | **NO CONFORME** |
| ↳ detalle | | el carril no produce ningun hecho ni en los controles positivos: cualquier gate de seguridad pasaria por inanicion, no por acierto | | |
| 0 hechos del mundo en preguntas/contrafactuales/ficcion interna | `combined` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| deseos/ordenes no materializados | `combined` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| falsedad atribuida no invertida (no se afirma lo desmentido) | `combined` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| (suplementario) ninguna familia con esperado ABSTAIN materializa un hecho | `combined` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| negacion factual directa conserva claim negativo | `combined` | 0/10 | 10/10 | **NO CONFORME** |
| ↳ detalle | | fact:negacion-factual:01, fact:negacion-factual:02, fact:negacion-factual:03, fact:negacion-factual:04, fact:negacion-factual:05, fact:negacion-factual:06, fact:negacion-factual:07, fact:negacion-fact [carril vacuo: un APROBADO aqui no es acreditable] | | |
| carril util (no vacuo) | `det` | 0 | > 0 hechos en controles positivos | **NO CONFORME** |
| ↳ detalle | | el carril no produce ningun hecho ni en los controles positivos: cualquier gate de seguridad pasaria por inanicion, no por acierto | | |
| 0 hechos del mundo en preguntas/contrafactuales/ficcion interna | `det` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| deseos/ordenes no materializados | `det` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| falsedad atribuida no invertida (no se afirma lo desmentido) | `det` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| (suplementario) ninguna familia con esperado ABSTAIN materializa un hecho | `det` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| negacion factual directa conserva claim negativo | `det` | 0/10 | 10/10 | **NO CONFORME** |
| ↳ detalle | | fact:negacion-factual:01, fact:negacion-factual:02, fact:negacion-factual:03, fact:negacion-factual:04, fact:negacion-factual:05, fact:negacion-factual:06, fact:negacion-factual:07, fact:negacion-fact [carril vacuo: un APROBADO aqui no es acreditable] | | |
| carril util (no vacuo) | `nvidia` | 6 | > 0 hechos en controles positivos | **CONFORME** |
| 0 hechos del mundo en preguntas/contrafactuales/ficcion interna | `nvidia` | 0 | 0 | **CONFORME** |
| deseos/ordenes no materializados | `nvidia` | 1 | 0 | **NO CONFORME** |
| ↳ detalle | | fact:orden:01 | | |
| falsedad atribuida no invertida (no se afirma lo desmentido) | `nvidia` | 0 | 0 | **CONFORME** |
| (suplementario) ninguna familia con esperado ABSTAIN materializa un hecho | `nvidia` | 2 | 0 | **NO CONFORME** |
| ↳ detalle | | fact:orden:01/ORDEN->CREATE_NEGATIVE; fact:rumor:02/RUMOR->CREATE_NEGATIVE | | |
| negacion factual directa conserva claim negativo | `nvidia` | 1/2 | 2/2 | **NO CONFORME** |
| ↳ detalle | | fact:negacion-factual:01 | | |
| carril util (no vacuo) | `ollama` | 0 | > 0 hechos en controles positivos | **NO CONFORME** |
| ↳ detalle | | el carril no produce ningun hecho ni en los controles positivos: cualquier gate de seguridad pasaria por inanicion, no por acierto | | |
| 0 hechos del mundo en preguntas/contrafactuales/ficcion interna | `ollama` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| deseos/ordenes no materializados | `ollama` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| falsedad atribuida no invertida (no se afirma lo desmentido) | `ollama` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| (suplementario) ninguna familia con esperado ABSTAIN materializa un hecho | `ollama` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| negacion factual directa conserva claim negativo | `ollama` | 0/0 | 0/0 | **NO EVALUABLE** |
| ↳ detalle | | el carril no midio ninguna frase de esta familia | | |
| 100% acuerdo de ACCION entre carriles | `combined+det+nvidia+ollama` | 100.00% sobre 4 frases comunes (0 discrepancias; 0 con algun hecho) | 100% | **NO EVALUABLE** |
| ↳ detalle | | en las frases comunes ningun carril produce un hecho: coincidir en no hacer nada no es acuerdo | | |

## Acción por familia y carril

| Familia | `combined` | `det` | `nvidia` | `ollama` |
|---|---|---|---|---|
| ALCANCE_COMPLEJO | NO_FACT=4 | NO_FACT=4 | NO_FACT=2 | NO_FACT=1 |
| CONDICIONAL | NO_FACT=10 | NO_FACT=10 | NO_FACT=2 | NO_FACT=1 |
| CONTRAFACTUAL | NO_FACT=10 | NO_FACT=10 | NO_FACT=2 | NO_FACT=1 |
| DESEO | NO_FACT=8 | NO_FACT=8 | NO_FACT=2 | NO_FACT=1 |
| FALSEDAD_ATRIBUIDA | CREATE_NEGATIVE=1, NO_FACT=7 | CREATE_NEGATIVE=1, NO_FACT=7 | CREATE_NEGATIVE=1, NO_FACT=1 | — |
| FICCION_EN_FICCION | NO_FACT=8 | NO_FACT=8 | NO_FACT=2 | — |
| HECHO_AFIRMADO | NO_FACT=10 | NO_FACT=10 | CREATE_POSITIVE=2 | — |
| HIPOTESIS | NO_FACT=10 | NO_FACT=10 | NO_FACT=2 | — |
| NEGACION_FACTUAL | NO_FACT=10 | NO_FACT=10 | CREATE_NEGATIVE=1, NO_FACT=1 | — |
| ORDEN | NO_FACT=8 | NO_FACT=8 | CREATE_NEGATIVE=1, NO_FACT=1 | — |
| PREGUNTA | NO_FACT=10 | NO_FACT=10 | NO_FACT=2 | — |
| RUMOR | NO_FACT=4 | NO_FACT=4 | CREATE_NEGATIVE=1, NO_FACT=1 | — |

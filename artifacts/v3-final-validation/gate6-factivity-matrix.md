# Puerta 6 — No-factividad medida

Corpus: `data-engine/app/knowledge_v3/benchmarks/datasets/factivity/cases.json` · split `dev-synthetic` · 12 casos · procedencia `dev-synthetic/opus-2026-07-30`.

> El corpus es **dev-synthetic**: mide cobertura de familias de no-factividad, **no** generaliza a producción.

## Carriles ejecutados

| Carril | Modelo | Latencia mediana | Pared (s) | Errores |
|---|---|---|---|---|
| `combined` | — | 6 ms | 0.1 | 0 |
| `det` | — | 5 ms | 0.1 | 0 |
| `nvidia` | meta/llama-3.3-70b-instruct | 50107 ms | 1372.2 | 0 |
| `ollama` | qwen2.5:7b | 600199 ms | 1738.9 | 0 |

## Prueba de vacuidad (controles positivos)

Un carril que no produce ningún hecho aprueba todos los gates de seguridad por inanición. Se comprueba primero.

| Carril | Hechos en controles | ¿Vacuo? |
|---|---|---|
| `combined` | 0 | **SÍ — gates no interpretables** |
| `det` | 0 | **SÍ — gates no interpretables** |
| `nvidia` | 0 | **SÍ — gates no interpretables** |
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
| negacion factual directa conserva claim negativo | `combined` | 0/2 | 2/2 | **NO CONFORME** |
| ↳ detalle | | fact:negacion-factual:01, fact:negacion-factual:02 [carril vacuo: un APROBADO aqui no es acreditable] | | |
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
| negacion factual directa conserva claim negativo | `det` | 0/2 | 2/2 | **NO CONFORME** |
| ↳ detalle | | fact:negacion-factual:01, fact:negacion-factual:02 [carril vacuo: un APROBADO aqui no es acreditable] | | |
| carril util (no vacuo) | `nvidia` | 0 | > 0 hechos en controles positivos | **NO CONFORME** |
| ↳ detalle | | el carril no produce ningun hecho ni en los controles positivos: cualquier gate de seguridad pasaria por inanicion, no por acierto | | |
| 0 hechos del mundo en preguntas/contrafactuales/ficcion interna | `nvidia` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| deseos/ordenes no materializados | `nvidia` | 1 | 0 | **NO CONFORME** |
| ↳ detalle | | fact:orden:01 [carril vacuo: un APROBADO aqui no es acreditable] | | |
| falsedad atribuida no invertida (no se afirma lo desmentido) | `nvidia` | 0 | 0 | **CONFORME** |
| ↳ detalle | |  [carril vacuo: un APROBADO aqui no es acreditable] | | |
| (suplementario) ninguna familia con esperado ABSTAIN materializa un hecho | `nvidia` | 4 | 0 | **NO CONFORME** |
| ↳ detalle | | fact:hipotesis:01/HIPOTESIS->CREATE_POSITIVE; fact:hipotesis:02/HIPOTESIS->CREATE_POSITIVE; fact:orden:01/ORDEN->CREATE_NEGATIVE; fact:rumor:02/RUMOR->CREATE_NEGATIVE [carril vacuo: un APROBADO aqui no es acreditable] | | |
| negacion factual directa conserva claim negativo | `nvidia` | 0/2 | 2/2 | **NO CONFORME** |
| ↳ detalle | | fact:negacion-factual:01, fact:negacion-factual:02 [carril vacuo: un APROBADO aqui no es acreditable] | | |
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
| 100% acuerdo de ACCION entre carriles | `combined+det+nvidia+ollama` | 4 carriles medidos, todos vacuos | >= 2 carriles utiles | **NO CONFORME** |
| ↳ detalle | | sin dos carriles medidos, y al menos uno no vacuo, el acuerdo no es medible: dos carriles que no extraen nada coinciden siempre | | |

## Acción por familia y carril

| Familia | `combined` | `det` | `nvidia` | `ollama` |
|---|---|---|---|---|
| ALCANCE_COMPLEJO | — | — | CREATE_NEGATIVE=1, NO_FACT=1 | NO_FACT=1 |
| CONDICIONAL | — | — | NO_FACT=2 | NO_FACT=1 |
| CONTRAFACTUAL | — | — | NO_FACT=2 | NO_FACT=1 |
| DESEO | — | — | NO_FACT=2 | NO_FACT=1 |
| FALSEDAD_ATRIBUIDA | — | — | NO_FACT=2 | — |
| FICCION_EN_FICCION | — | — | NO_FACT=2 | — |
| HECHO_AFIRMADO | NO_FACT=10 | NO_FACT=10 | NO_FACT=2 | — |
| HIPOTESIS | — | — | CREATE_POSITIVE=2 | — |
| NEGACION_FACTUAL | NO_FACT=2 | NO_FACT=2 | NO_FACT=2 | — |
| ORDEN | — | — | CREATE_NEGATIVE=1, NO_FACT=1 | — |
| PREGUNTA | — | — | NO_FACT=2 | — |
| RUMOR | — | — | CREATE_NEGATIVE=1, NO_FACT=1 | — |

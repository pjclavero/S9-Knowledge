# 43 — Puerta 6, bloque B0: arnés de medición de factividad composicional

> **Nota de alcance (retroactiva, anadida en el rework del bloque B2).**
> Todas las cifras de este documento miden UNA capa: el CLASIFICADOR de
> factividad (`extraction.cues.analyze_raw_text` / `classify_factivity`).
> La revision de B2 demostro, con ejecucion independiente, que el extractor
> determinista de produccion (`extraction/deterministic.py`) NO consultaba
> ese resultado para la rama RUMOR / `EMIT_EPISTEMIC_PROPOSAL`: solo leia del
> `verdict` las dos acciones de aborto (`EMIT_DIAGNOSTIC` y `REVIEW_SCOPE`) y
> calculaba su hint epistemico con una lista local anterior al programa. Es
> decir: estas cifras describian lo que la politica LEE, no lo que el sistema
> ESCRIBE, y para el operador de discurso reportado ("El heraldo dijo que P")
> las dos cosas no coincidian. El rework de B2 conecta los dos carriles y
> publica desde entonces el invariante fail-closed medido tambien contra la
> salida real de `DeterministicExtractor` (capa `deterministic_extractor`,
> `knowledge_v3/eval/gate6_extractor_layer.py`), al lado de la capa de
> clasificador y sin mezclar las dos en un solo numero.


## Contexto

La validación final V3 (2026-07-31) cerró la puerta 6 (no-factividad) en
**NO CONFORME** (`artifacts/v3-final-validation/gate6-findings.md`): el
acuerdo de acción entre carriles (`det`+`combined`+`nvidia`) fue **79,17 %**
(F6-3), y la sonda de generalización de vocabulario nuevo
(`factivity_generalization_probe.py`) dio **0,231** de acierto en
no-factividad fuera de corpus (F6-5) — la política de `cues.py`/`factivity.py`
memoriza frases, no entiende la no-factividad.

Este documento describe el bloque **B0** del programa "Puerta 6 — factividad
composicional": un arnés de medición, sin tocar la política. B0 **mide**, no
**corrige**. El objetivo era responder una pregunta distinta a la que ya
contestó la sonda de vocabulario: ¿la política **compone** bien cuando dos
operadores de factividad ya conocidos aparecen en la misma frase (condicional
dentro de un rumor, reporte anidado, negación de un verbo factivo, factivo
dentro de un condicional, rumor negado, reporte de una negación)?

## Dónde estaba el corpus histórico y cómo se midió la puerta 6

- **Corpus dev-synthetic** (100 frases, 12 familias): vive en
  `data-engine/app/knowledge_v3/benchmarks/datasets/factivity/cases.json`,
  `dataset_version: 1.0.0`, `split: dev-synthetic`,
  `provenance: dev-synthetic/opus-2026-07-30`. **No tenía manifiesto de
  integridad** antes de B0 (se usó en la validación V3 con carga directa, sin
  hash congelado); B0 lo formaliza sin tocar su contenido —
  `manifest.json` hermano, sha256 de `cases.json`.
- **79,17 %** (F6-3, `gate6-findings.md`): acuerdo de ACCIÓN entre los
  carriles `det` + `combined` + `nvidia` del runner
  `artifacts/v3-final-validation/gate6_factivity_runner.py`, sobre las 24
  frases comunes con al menos un hecho producido por algún carril. Exige un
  extractor completo, un reconciliador y un proveedor NVIDIA en vivo. **No es
  reproducible de forma determinista y sin red.**
- **79/100** (F6-7, mismo informe): la política de factualidad SOLA
  (`extraction.cues.analyze_raw_text`), medida contra las 100 frases del
  corpus dev, comparando la clase de factividad predicha contra el campo
  `expected` (`WRITE_POSITIVE`/`WRITE_NEGATIVE`/`ABSTAIN`/`DIAGNOSTIC`) de cada
  caso. **Esta cifra SÍ es reproducible** de forma determinista y sin
  proveedores: es la que reproduce `gate6_harness.measure_dev()` de este
  bloque, byte a byte, en `policy_accuracy` (0,79).
- **0,231** (F6-5): sonda de generalización de VOCABULARIO
  (`artifacts/v3-final-validation/factivity_generalization_probe.py`), 30
  frases con marcadores no-factivos ausentes de `cues.py` y de `cases.json`
  (un operador por frase). Mide un eje distinto del de este bloque.

## Qué añade B0

1. **Gold congelado del corpus dev**: `benchmarks/datasets/factivity/manifest.json`
   (nuevo), sha256 de `cases.json`, comprobado antes de cargar
   (`eval/gate6_dev_corpus.py::verify_integrity`).
2. **Corpus de generalización COMPOSICIONAL nuevo** (42 casos, 7 familias, 6
   casos cada una): `eval/data/gate6_generalization/cases.json` +
   `manifest.json`. Dominio "diplomacia especiera" (inventado), entidades
   nuevas, **cero n-gramas (≥3 palabras) compartidos** con el corpus dev
   (comprobado por `test_sin_solapamiento_de_ngramas_con_el_corpus_dev`) ni
   con el código de `cues.py` salvo el reuso deliberado y declarado de las
   cue phrases que hacen falta para componer (`en caso de que`, `salvo que`,
   `es cierto que`, `se rumorea`, etc. — sin ellas no se puede probar
   *composición* de un operador conocido, solo vocabulario nuevo, que ya midió
   la sonda de fase 3).

   Familias:
   - `CONDITIONAL_IN_RUMOR` — un condicional dentro de un rumor.
   - `NESTED_REPORT` — reporte anidado con verbos declarativos comunes
     ("dijo que"/"afirma que"/"sostuvo que"), **ninguno enumerado en
     `EPISTEMIC_CUES` ni `FALSITY_PHRASES`**.
   - `NEGATION_OF_FACTIVE` — negación de un verbo factivo ("no confirmó que",
     "no admitió que", "no reconoció que"): negar la confirmación no afirma
     ni niega el hecho subyacente.
   - `FACTIVE_IN_CONDITIONAL` — un condicional envuelve una cláusula "es
     cierto que"/"sea verdad que".
   - `NEGATED_RUMOR_HARD` — familia **HARD declarada por adelantado**: "no es
     cierto el rumor de que X" no es substring literal de ninguna
     `FALSITY_PHRASE` (la interposición de "el rumor de" rompe el match
     exacto de "no es cierto que"). Se espera exactitud baja **a propósito**;
     el gold no se ajustó para que el sistema acertara.
   - `REPORT_OF_NEGATION` — un verbo de reporte envuelve una negación interna.
   - `POSITIVE_CONTROL` — sin composición, control de que el vocabulario y
     dominio nuevos no rompen el caso simple por sí solos.

3. **Runner unificado** `scripts/gate6/measure.py` (invoca
   `knowledge_v3.eval.gate6_harness.measure_gate6_program`): mide (a)
   `policy_accuracy` sobre el corpus dev, reproduciendo F6-7 (79/100); (b) el
   corpus de generalización composicional por familia; (c) el invariante
   fail-closed (ningún caso no-escribible del gold debe leerse como
   `ASSERTED_FACT`/`NEGATED_FACT`). Determinista byte a byte
   (`test_el_arnes_es_determinista_byte_a_byte`). Artefactos en
   `artifacts/gate6-program/b0-baseline.{json,md}`.

## Cifras del baseline (honestas, sin tocar la política)

| corpus | casos | métrica | valor |
| --- | ---: | --- | ---: |
| dev (`dev-synthetic`) | 100 | `policy_accuracy` | **0,790** |
| generalización composicional | 42 | `overall_accuracy` | **0,381** |
| generalización composicional | 42 | `hard_family_accuracy` (`NEGATED_RUMOR_HARD`) | **0,000** |
| generalización composicional | 42 | `non_hard_accuracy` | **0,444** |

Por familia (generalización):

| familia | casos | exactitud |
| --- | ---: | ---: |
| `CONDITIONAL_IN_RUMOR` | 6 | 1,000 |
| `FACTIVE_IN_CONDITIONAL` | 6 | 0,833 |
| `POSITIVE_CONTROL` | 6 | 0,667 |
| `NEGATION_OF_FACTIVE` | 6 | 0,167 |
| `NEGATED_RUMOR_HARD` | 6 | 0,000 |
| `NESTED_REPORT` | 6 | 0,000 |
| `REPORT_OF_NEGATION` | 6 | 0,000 |

**Invariante fail-closed: NO CONFORME.** 40 violaciones (16 en el corpus dev,
24 en el de generalización): casos cuyo gold exige abstenerse que la política
leyó como `ASSERTED_FACT`/`NEGATED_FACT`. En el corpus dev, las familias con
más violaciones son `CONTRAFACTUAL` (4), `ALCANCE_COMPLEJO` (4), `CONDICIONAL`
(3) y `ORDEN` (3) — consistentes con los hallazgos ya documentados en F6-7. En
generalización, `NESTED_REPORT`, `REPORT_OF_NEGATION` y `NEGATED_RUMOR_HARD`
fugan el 100 % de sus casos: **verbos de reporte y construcciones de negación
de rumor fuera del vocabulario literal de `cues.py` no disparan ninguna
señal, y el texto cae en la lectura por defecto (`ASSERTED_FACT`)**.

Lectura honesta: la exactitud de composición (0,381) es más alta que la de
vocabulario nuevo con un solo operador (0,231, F6-5) pero sigue siendo muy
baja, y el patrón de fallo es el mismo diagnosticado en la fase 3: la
arquitectura es una precedencia plana sobre un escaneo de superficie de
frases literales, sin seguimiento real de alcance ni de anidamiento
sintáctico. Familias enteras (`NESTED_REPORT`, `REPORT_OF_NEGATION`) fallan al
100 % porque usan verbos de reporte comunes en español ("dijo que", "afirmó
que", "sostuvo que", "declaró que") que **no están enumerados en ningún lado
de `cues.py`** — no es un problema de composición per se, es que el
vocabulario base de reporte verbal es más pobre que el de rumor/condicional.

## Decisiones discutibles

- Se usó `policy_accuracy` (política sola, sin extractor ni proveedor) como
  cifra de desarrollo, no el 79,17 % de acuerdo entre carriles: esa cifra
  necesita NVIDIA en vivo y no es reproducible de forma determinista por este
  arnés. Se documenta la diferencia explícitamente en vez de fingir que se
  reprodujo la misma cifra.
- La familia `NEGATED_RUMOR_HARD` se declaró dura *antes* de medir, en base al
  análisis del patrón literal de `FALSITY_PHRASES` (no basta con contener
  "rumor" y "no es cierto"; tiene que ser substring exacto). Al medir, en
  efecto salió a 0,0 — no se ajustó el gold para forzar ese resultado.
- `POSITIVE_CONTROL` (0,667, no 1,0) reveló que ni siquiera el caso simple sin
  composición acierta siempre con este vocabulario/dominio nuevo: es
  evidencia adicional de que parte del problema es léxico (verbos y
  construcciones de negación fuera de las listas), no solo estructural.
- No se corrigió nada de `extraction/factivity.py` ni `extraction/cues.py`:
  regla de oro del bloque. La sonda de generalización es el criterio de
  aceptación de cualquier corrección futura, y debe ejecutarse antes de
  tocar la política — igual que en el hallazgo de F6-5.

## Cómo reproducir

```
cd data-engine
PYTHONPATH=app python3 -m pytest app/tests/test_gate6_harness.py app/tests/test_gate6_harness_adversarial.py -v
cd ..
PYTHONPATH=data-engine/app python3 scripts/gate6/measure.py --out-dir artifacts/gate6-program --out-name b0-baseline
```

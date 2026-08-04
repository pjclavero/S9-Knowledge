# 41 — Puerta 4, bloque B4: análisis morfológico de verbos de reporte

## Objetivo del bloque

Atacar las familias `PREDICATE_ABSENT`/subordinadas del programa "Puerta 4 —
cobertura del extractor" por vía morfológica/estructural, explícitamente
**sin** heurísticas léxicas de sufijo suelto (el encargo prohíbe, como caso
concreto, tratar "-ría" como marca de condicional por terminación).

## Qué se construyó

`data-engine/app/knowledge_v3/extraction/morphology.py`: un conjugador
morfológico de verbos **regulares** de la primera conjugación española
(-AR), aplicado a `cues.SCOPE_VERBS` (los verbos de actitud/reporte tras los
que "no <verbo> que ..." niega la creencia, no la relación subordinada).

- `conjugate_regular_ar(lemma)` genera, desde la tabla de desinencias
  regular (presente, pretérito, imperfecto de 3ª persona + participio +
  formas compuestas con "haber"), el paradigma completo de un verbo -AR.
- `REPORTING_LEMMAS_AR` declara los LEMAS (no las formas): `afirmar`,
  `declarar`, `asegurar`, `confirmar`. Cada uno se comprobó manualmente
  regular antes de declararse.
- `negar` es -AR pero diptonga en presente (niega/niegan, no
  "\*nega"/"\*negan"); se excluyó de la tabla regular y se declaró aparte,
  a mano, con sus formas reales (`NEGAR_FORMS`) — exactamente el mismo
  criterio que ya usaba `cues.py` para "decir"/"saber" (irregulares
  declarados, no generados por analogía).
- `reporting_verb_forms()` junta ambos conjuntos y se añade a
  `cues.SCOPE_VERBS` (que conserva sus verbos irregulares previos: creer,
  decir, saber, pensar, ...).

## Por qué esto es "morfología", no lexicón disfrazado

El lexicón anterior a B4 escribía cada forma a mano, verbo a verbo
(`"afirma", "afirmaba", "afirmo"`, sin plural). Añadir un verbo de reporte
nuevo exigía teclear su paradigma entero. Ahora basta con declarar el LEMA;
las formas (incluidas las que nadie tecleó nunca, como el plural) salen de
la tabla de desinencias, que es morfología del español documentada, no una
observación del corpus. La prueba de que generaliza (y no memoriza) está en
el corpus de generalización: `gen:scope:05`/`gen:scope:06` usan
"declarar"/"asegurar" — verbos que no aparecían ni en el desarrollo ni en el
resto del corpus de generalización antes de B4 — y se clasifican
correctamente (ver `artifacts/gate4-program/b4-resultado.md`).

## Qué NO se pudo mover, y por qué

La cobertura E2E del corpus de desarrollo se mantiene en 34/56 (0.607,
igual que al cierre de B2). Los dos casos candidatos identificados en la
taxonomía de B2 (`cirro-actas:e13`/`e14`, "Nadie ... ha afirmado que ... no
dirija ...") resultaron depender de un sujeto de CUANTIFICADOR NEGATIVO
("Nadie"), no de la ausencia de "no <verbo de reporte>" adyacente — un
fenómeno gramaticalmente distinto del que este bloque ataca. Forzar una
regla ad-hoc para esos dos casos concretos habría sido memorización de
corpus disfrazada de regla de lengua, justo lo que el programa prohíbe. Se
documenta como hallazgo negativo, con el análisis caso a caso completo en
`artifacts/gate4-program/b4-taxonomia.md`, junto con las otras dos
categorías de casos NO_OUTPUT restantes (alineación imposible por fuente
OCR/ASR — arquitectura, no lingüística; guardia de coordinación — analizada
y descartada por dar precisión 0.5 con la única regla candidata probada).

## Reproducción

```bash
cd data-engine
PYTHONPATH=app pytest app/tests -k gate4 -q          # bateria completa del programa
PYTHONPATH=app pytest app/tests/test_gate4_b4_morphology.py -q   # unitarios + adversariales de B4

cd ..
PYTHONPATH=data-engine/app python3 scripts/gate4/measure_b4.py \
    --out-dir artifacts/gate4-program --out-name b4-resultado
```

`measure_b4.py` compara contra `artifacts/gate4-program/b2-resultado.json`
(el bloque anterior, no el baseline B0 del programa) y deriva todos los
veredictos del mismo arnés (`knowledge_v3.eval.harness.measure_gate4_program`)
que usan B0/B2/B3 — ninguna cifra del informe se escribe a mano.

## Corpus de generalización: dataset_version 1.2.0 → 1.3.0

Dos casos nuevos, familia `SCOPE_EMBEDDED` (cuota 4 → 6):
`gen:scope:05` (dominio `archivos`, verbo "declarar") y `gen:scope:06`
(dominio `gremios`, verbo "asegurar", plural). Ninguna entidad ni sintagma
coincide con el corpus de desarrollo ni con casos previos de generalización.
Manifest actualizado con el sha256 recalculado de `cases.json`
(`data-engine/app/knowledge_v3/eval/data/generalization/manifest.json`).

## Cifras antes / después

| métrica | B2 (cierre) | B4 |
|---|---|---|
| cobertura E2E dev | 0.607143 (34/56) | **0.607143 (34/56) — sin cambio** |
| `HARD_SCOPE_LITOTES` (generalización) | 0.5 | 0.5 — sin cambio (fuera de alcance de B4) |
| 9 familias no duras (generalización) | 1.0 | **1.0**, ahora con `SCOPE_EMBEDDED` en 6 casos (antes 4) |
| invariantes de precisión (auto_approval, negative_edge, negated_cessation, evidence_grounding) | 1.0 / fp=0 | **1.0 / fp=0 — sin cambio** |
| suite completa (`pytest app/tests`) | — | **4890+ passed** (ver informe de ejecución), 0 failed |

## Decisiones discutibles declaradas

1. **No se añadió ninguna dependencia externa** (spaCy u otro analizador
   morfológico de terceros). El conjugador propio, acotado a un paradigma
   regular y una familia semántica cerrada (verbos de reporte), es
   determinista, auditable línea a línea y no introduce ni peso ni
   variabilidad entre versiones de modelo. Para el alcance de B4 (una
   familia verbal, 3ª persona, indicativo) una dependencia pesada habría
   sido desproporcionada; si un bloque futuro necesita cobertura
   morfológica más amplia (otras conjugaciones, otras personas, verbos
   irregulares por analogía), esa sería la ocasión de reevaluar el balance.
2. **Se descartó explícitamente** resolver la guardia de coordinación
   (categoría C de la taxonomía) con una heurística de "elegir el sujeto
   coordinado más próximo": se midió contra los casos reales + variantes
   propias y dio precisión 0.5, por debajo del listón de 1.000. Descartar
   una regla que no llega a 1.000 es la aplicación literal de la regla de
   oro del programa, no un fallo de esfuerzo.
3. **No se forzó ninguna regla para `cirro-actas:e13`/`e14`.** Es la
   decisión más discutible del bloque: dos casos concretos del corpus de
   desarrollo se quedan sin cubrir pudiendo, en teoría, escribirse una regla
   que los reconociera ("sujeto ∈ {nadie, ninguno, ningún, nunca-nadie...} +
   SCOPE_VERB en la cláusula"). No se hizo porque el corpus de
   generalización no tiene ningún caso de ese fenómeno para probar que
   generaliza, y añadirlo solo para pasar estos dos casos del desarrollo
   sería precisamente la memorización que el programa mide y penaliza.

## Producción y held-out

Intactos. No se tocó ningún dato de producción, VM105, ni el corpus
held-out. El corpus de generalización de puerta 4 vive en el repo
(`data-engine/app/knowledge_v3/eval/data/generalization/`), separado del
corpus de desarrollo (`benchmarks/datasets/negation/`) y del held-out real
de otros programas.

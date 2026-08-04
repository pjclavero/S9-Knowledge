# 44 — Puerta 6, bloque B1: operador de discurso reportado por tercero

## Contexto

B0 (`docs/v3/43-gate6-b0-harness.md`) midio sin corregir: 40 violaciones
fail-closed (16 en el corpus dev, 24 en el de generalizacion composicional
nueva), `policy_accuracy` de dev en 0,790, exactitud de generalizacion
composicional en 0,381. El hallazgo central: familias enteras
(`NESTED_REPORT`, `REPORT_OF_NEGATION`) fugaban el 100 % de sus casos porque
los verbos de reporte comunes en espanol ("dijo que", "afirmo que", "sostuvo
que"...) no estaban enumerados en ningun lado de `cues.py` — no es un
problema de composicion per se, es que el vocabulario base de reporte verbal
era mas pobre que el de rumor/condicional.

Este bloque **corrige**, por primera vez en el programa de la puerta 6.
Orden de prioridad fijado por el dictamen del revisor (no se altero):

1. Operador de discurso reportado por tercero (12/40 violaciones).
2. `"mientras"` en `CONDITIONAL_PHRASES`.
3. Bug de `"nunca"` con objeto locativo.
4. Composicion en abstracto (solo si quedaba margen).

Ademas, higiene ordenada por el revisor: mover `gen6:positive_control:03/04`
del corpus de generalizacion a una familia propia `LEXICAL_NEGATION_EDGE`
(las etiquetas gold eran correctas; la familia estaba mal — miden negacion
lexica, no factividad).

## 1. Operador de discurso reportado por tercero

### Diseno y semantica elegida

**Decision**: reporte simple → clase no-factiva con hint epistemico, **como
RUMOR, degrada** (no abstencion dura). Se reutiliza integramente el
mecanismo YA EXISTENTE de `RUMORED` en vez de anadir una clase/accion nueva
a `FactivityClass`/`FactivityAction`:

- Nuevo codigo de razon `CODE_REPORTED_SPEECH` (`REPORTED_SPEECH_CONTEXT`)
  en `extraction/cues.py`, puramente informativo/trazable.
- Nueva funcion `_reported_speech_cue(tokens, lo, hi)`: busca el primer
  `<verbo de reporte> que` PEGADO (0 tokens entre verbo y "que", igual
  criterio de hueco cerrado que `scope_negation` usa para "no <verbo>") en
  toda la ventana.
- Si se encuentra y el `hint` todavia esta en `"ASSERTED"`, se degrada a
  `"RUMORED"` — el mismo valor que ya usan `"se rumorea"`/`"dicen que"`.
  `ContextVerdict.factivity` ya construye `rumor=self.hint == "RUMORED"`,
  asi que la clasificacion cae sola en `FactivityClass.RUMOR` con accion
  `EMIT_EPISTEMIC_PROPOSAL` (nunca `EMIT_WORLD_CLAIM`/
  `EMIT_NEGATED_WORLD_CLAIM`) sin tocar `extraction/factivity.py` en
  absoluto.

**Por que RUMOR y no abstencion dura (`EMIT_DIAGNOSTIC`, "no se emite
nada")**: el texto SI dice algo verificable — que un tercero lo dijo. Eso es
exactamente la misma naturaleza epistemica que un rumor (atribuido, no
confirmado por el propio texto), y el contrato `EpistemicStatusHint` ya
tiene ese valor (`RUMORED`) sin necesitar extender el enum del contrato
`claim-proposal/v3-internal-v1` — cambiar un contrato de datos es un riesgo
mayor que reutilizar uno ya validado. `EMIT_EPISTEMIC_PROPOSAL` sigue
cumpliendo la regla de oro (nunca se materializa como
`ASSERTED_FACT`/`NEGATED_FACT`; el gate6 harness comprueba exactamente eso).

**Composicion con negacion (REPORT_OF_NEGATION) sin codigo nuevo**: al
degradar el `hint` a `RUMORED`, `signals.rumor=True` entra en la tupla
ordenada de `classify_factivity` y se selecciona ANTES de llegar al
`if signals.negated` de reserva. "X informo que Y no trafica..." tiene
`negated=True` (la clausula interna esta negada) Y `rumor=True`
(por el verbo de reporte); gana `rumor`, así que nunca sale
`NEGATED_FACT`. Esto resuelve la familia `REPORT_OF_NEGATION` entera sin
ningun ajuste adicional — es una consecuencia gratuita del diseno, no una
regla nueva escrita a mano para ese caso.

### Vocabulario: `REPORT_VERBS`

`_REPORT_VERB_AR_LEMMAS` (regulares -AR, generados por
`morphology.conjugate_regular_ar`, nunca copiados de una frase de corpus):
`afirmar`, `declarar`, `asegurar`, `comentar`, `relatar`, `informar`,
`mencionar`, `indicar`. Mas `REPORT_VERB_HAND_FORMS` (irregulares o fuera de
la 1a conjugacion, declaradas a mano igual que `decir`/`saber` ya vivian en
`SCOPE_VERBS`): formas plurales de `decir` que faltaban, `sostener`,
`contar`, `repetir`, `confesar`, `escribir`, `insistir`.

**Exclusion deliberada de verbos factivos/de reconocimiento**
(`confirmar`, `admitir`, `reconocer`, `verificar`, `aceptar`): si alguien
CONFIRMA/ADMITE/RECONOCE/VERIFICA/ACEPTA algo, el verbo presupone que lo
dicho es cierto — son factivos-implicativos, categoria linguistica distinta
de un verbo de reporte puro (decir/afirmar no presuponen nada sobre la
verdad de lo dicho). Metidos en `REPORT_VERBS` degradarian a `RUMOR` frases
que el gold espera como hecho.

**Exclusion deliberada de "referir"**: el corpus dev
(`fact:hecho-afirmado:08`, "El escribano refirio que la Compania del
Arrecife opera dos rutas... y sus libros lo confirman", gold
`WRITE_POSITIVE`) es un reporte con corroboracion en la MISMA frase que el
gold SI espera escrito como hecho. Anadir "referir" a `REPORT_VERBS`
convertiria ese caso en una violacion nueva de precision (el falso positivo
de este dominio que el encargo prohibe). Se comprobo por grep contra el
corpus dev completo antes de fijar la lista final (ningun otro verbo
candidato aparecia en dev en un contexto que la lista pudiera romper).
Test de guarda explicito: `test_referir_queda_fuera_de_report_verbs_a_proposito`.

### Bono de bajo riesgo: extension de `SCOPE_VERBS`

`admitir` y `reconocer` (irregulares/-IR/-ER, declarados a mano) y
`verificar`/`aceptar` (regulares -AR, via `morphology.REPORTING_LEMMAS_AR`)
se anadieron a `SCOPE_VERBS`: son la MISMA clase de verbo factivo que
`confirmar` (ya cubierto), y su ausencia dejaba 4 de los 6 casos de
`NEGATION_OF_FACTIVE` sin disparar `CODE_NEGATION_SCOPE` ("no admitio que",
"no reconocio que", "no verifico que", "no acepto que" se leian como hecho
del mundo — violacion fail-closed). No es la prioridad 1 del dictamen, pero
es una extension de vocabulario de la MISMA arquitectura ya aprobada
(paradigma morfologico + irregulares declaradas), de riesgo y coste
minimos, verificada sin literales de corpus. `gen6:neg_of_factive:04`
("Nadie ... confirmo que...") queda sin resolver a proposito: usa "nadie"
como negador, que no esta en `NEGATION_CUES`, y es un bug DISTINTO (lexico
de negadores, no de vocabulario factivo) fuera de la prioridad de este
bloque; documentado como hueco conocido en el test adversarial nuevo.

## 2. `"mientras"` como condicional

**Regla**: `"mientras"` es ambiguo entre conjuncion TEMPORAL
("mientras cenaban, llego X" — indicativo) y CONDICIONAL ("mientras Toturi
no rompa la tregua..." — subjuntivo, equivalente a "a menos que"). No hay
analizador de modo verbal en esta arquitectura, pero SI hay una regla
gramatical cerrada (no ad-hoc, no derivada del corpus) que cubre exactamente
el caso ambiguo: en espanol, **"mientras no" + verbo siempre toma
subjuntivo** ("a menos que"/"hasta que no"), nunca es la lectura temporal-
indicativa. Se anadio `CONDITIONAL_PATTERNS` (mismo patron que
`EPISTEMIC_PATTERNS`, regex sobre la ventana normalizada) con
`\bmientras (?:\w+ ){0,4}no\b` — el hueco de hasta 4 tokens deja pasar un
sujeto interpuesto ("mientras Toturi no rompa"). Un `"mientras"` SIN "no"
cercano queda **fuera a proposito**: sigue leyendose como conjuncion de
clausula (`CLAUSE_CONJUNCTIONS`), nunca como condicional. Forzar esa lectura
habria convertido usos temporales en condicionales — exactamente el falso
positivo que el encargo prohibe.

Corrige `fact:condicional:04` del corpus dev (unico caso de "mientras" en
dev que era violacion; el otro, `fact:orden:07` "No jures... mientras yo
viva", ya se resolvia via `DEONTIC_PHRASES`/"no jures" y no se ve afectado).
Test de guarda explicito de que "mientras" temporal NO se convierte:
`test_mientras_temporal_sin_no_no_se_convierte_en_condicional`.

## 3. Bug de "nunca" con objeto locativo: limite arquitectonico documentado

`gen6:positive_control:04` ("El Arca de Especias nunca salio del Muelle de
la Canela.", gold `NEGATED_FACT`) sigue saliendo `UNKNOWN`
(`REVIEW_NEGATION_SCOPE`). Diagnostico:

- `"salio del"` esta en `CESSATION_PHRASES` (misma familia lexica que
  "abandono"/"dimitio de"/"se separo de": verbos de cese de una relacion de
  pertenencia o cargo).
- `negated_cessation()` trata CUALQUIER negacion pegada a una cesacion como
  DOBLE negacion ambigua: "no dejo de servir" AFIRMA la relacion (docstring
  original de la funcion, medido y corregido en B2 de la puerta 4). Esa
  regla es **correcta** para cesacion de pertenencia/cargo — negar el
  abandono afirma la continuidad de una relacion que el motor no puede
  materializar sin saber a que predicado positivo corresponde, y pedir
  revision ahi es la prudencia fail-closed deseada.
- En `"nunca salio del Muelle de la Canela"` el gold modela la frase como la
  negacion DIRECTA de un evento de partida (predicado ≈ "salir/partir"),
  no como la cesacion-con-flip de una relacion de pertenencia. Con el
  vocabulario/patron actual (deteccion lexica de `"salio del"`, sin
  distincion semantica del complemento) las dos lecturas son
  indistinguibles.

**Decision**: NO se toca `negated_cessation`/`cessation_matches`. Cualquier
intento de separar "cesacion de pertenencia" (donde el flip-ambiguo es
correcto) de "partida fisica" (donde deberia negarse directo) exigiria
inspeccionar el COMPLEMENTO ("del Muelle de la Canela" vs "del clan/de la
Orden") con un vocabulario cerrado de sustantivos-lugar vs.
sustantivos-organizacion — exactamente la clase de heuristica ajustada a un
caso concreto que el encargo prohibe, y con riesgo real de romper las
cesaciones de pertenencia genuinas que SI dependen de la ambiguedad (ver
`test_cessation_*` de la puerta 4, B2). Se documenta como limite
arquitectonico, no como bug puntual corregible sin riesgo. El resultado
(`UNKNOWN`/revision) es SEGURO — solo es impreciso, no viola fail-closed.

Test de regresion actualizado (ya existia desde B0, ahora con el
diagnostico completo):
`test_positive_control_04_sale_unknown_limite_arquitectonico_documentado`
en `test_gate6_harness_adversarial.py`.

## 4. Higiene del corpus: `LEXICAL_NEGATION_EDGE`

`gen6:positive_control:03` ("Bram Oyala queda fuera del Consulado de
Ambar.") y `gen6:positive_control:04` (la del punto 3) no miden factividad
ni composicion — miden negacion LEXICA simple (`"queda fuera"`/`"nunca"` +
verbo), y estaban mal clasificados en `POSITIVE_CONTROL` desde B0. Se movio
su campo `family` a una nueva familia `LEXICAL_NEGATION_EDGE` declarada en
`gate6_generalization_corpus._EXPECTED_FAMILIES` y en el test de esquema de
`test_gate6_harness.py`. El gold (`expected_class`) **no cambio**: la
correccion es solo de rotulo, autorizada explicitamente por el encargo.
`dataset_version` subio a `1.1.0` en `cases.json` y `manifest.json`, con el
sha256 recalculado tras el cambio (comprobado por
`verify_integrity()`/`test_integridad_del_corpus_de_generalizacion_no_rompe_en_reposo`).
`POSITIVE_CONTROL` queda con 4 casos puros (01, 02, 05, 06).

## Cifras: antes (B0) / despues (B1)

Todas las cifras de esta seccion las genera
`scripts/gate6/measure_b1.py` (compara `measure_gate6_program()` actual
contra `artifacts/gate6-program/b0-baseline.json` fila a fila); ninguna esta
escrita a mano. Artefactos completos:
`artifacts/gate6-program/b1-operators.{json,md}`.

| corpus | metrica | B0 | B1 |
| --- | --- | ---: | ---: |
| dev (100 casos) | `policy_accuracy` | 0,790 | **0,800** |
| generalizacion (42 casos) | `overall_accuracy` | 0,381 | **0,762** |
| generalizacion | `hard_family_accuracy` (`NEGATED_RUMOR_HARD`) | 0,000 | 0,000 |
| generalizacion | `non_hard_accuracy` | 0,444 | **0,889** |

**Invariante fail-closed: 40 → 23 violaciones (17 resueltas, 0 nuevas,
0 regresiones)** — verificado fila a fila, no solo por el conteo agregado
(`test_no_hay_regresiones_de_dev_ni_de_generalizacion`).

Por familia (generalizacion), violaciones que siguen abiertas tras B1:

| familia | casos con violacion |
| --- | ---: |
| `NEGATED_RUMOR_HARD` | 6 (declarada HARD desde B0, fuera de prioridad) |
| `NEGATION_OF_FACTIVE` | 1 (`:04`, "nadie" en vez de "no"; fuera de prioridad) |
| `FACTIVE_IN_CONDITIONAL` | 1 (`:06`, patron de condicional distinto — prioridad 4, sin margen en este bloque) |

Dev, violaciones que siguen abiertas: `ALCANCE_COMPLEJO` (4),
`CONTRAFACTUAL` (4), `ORDEN` (3), `DESEO` (2), `CONDICIONAL` (2, bajo de 3
en B0 tras la correccion de `fact:condicional:04`) — ninguna de estas
familias esta en la prioridad de este bloque.

### Caso dev que cambio (unico)

- `fact:condicional:04` ("Mientras Toturi no rompa la tregua, el Clan del
  León mantendrá sus guarniciones donde están."): `NEGATED_FACT` (violacion
  fail-closed en B0) → `CONDITIONAL` (correcto). Causa: la nueva regla
  `"mientras no"`.

### Evidencia externa (fuera de ambos corpus)

`test_gate6_harness_adversarial.py` tenia tres frases adversariales
compuestas en B0, con entidades y dominio que ningun corpus ni B1 vio antes
de escribir el operador: rumor+condicional anidado (ya acertaba en B0),
reporte anidado ("declaro que"/"insistio en que") y negacion de un verbo
factivo institucional ("reconocer"). **Las tres pasan a acertar tras B1**
(`test_las_frases_adversariales_de_b0_ahora_aciertan_evidencia_externa_de_b1`),
sin haber sido vistas al disenar el operador — evidencia de que la mejora
generaliza mas alla de los 42+100 casos de gold. Se anadieron tres frases
adversariales NUEVAS para los huecos que B1 dejo fuera de prioridad
("nadie" como negador, `"el rumor de"` interpuesto, "de resultar cierto
que"): las tres siguen fallando, documentado como evidencia de que quedan
huecos genuinos, no resueltos por accidente
(`test_documenta_fallos_de_la_politica_en_composiciones_nuevas_fuera_de_corpus`).

## Decisiones discutibles

- **RUMOR en vez de una clase/accion nueva**: se opto por reutilizar
  `EpistemicStatusHint.RUMORED`/`FactivityClass.RUMOR` en vez de anadir
  `REPORTED_SPEECH` al enum. Ventaja: cero cambios en `factivity.py` ni en
  el contrato `claim-proposal/v3-internal-v1`, reduce superficie de riesgo.
  Desventaja: en trazas/diagnosticos, un reporte de tercero y un rumor
  clasico ("se rumorea que") son indistinguibles por `factivity_class`
  (SI son distinguibles por `reason_codes`/`cues`, que conservan
  `CODE_REPORTED_SPEECH` y el verbo detectado). Si un bloque futuro necesita
  distinguirlos para el motor de escritura, el reason code ya esta ahi.
- **No se cerro el bug de "nunca" + locativo**: documentado como limite
  arquitectonico (seccion 3) en vez de forzar una heuristica sobre el
  complemento. Es la decision mas cara del bloque en terminos de "numero
  no resuelto", pero la alternativa (distinguir semanticamente lugar de
  organizacion en el complemento) es exactamente la clase de ajuste fragil
  que el programa ha penalizado antes (P0 de B2, puerta 4).
  `LEXICAL_NEGATION_EDGE` deja el caso visible y trazable en vez de
  enterrado en `POSITIVE_CONTROL`.
- **`NEGATION_OF_FACTIVE:04` ("nadie confirmo que") y
  `FACTIVE_IN_CONDITIONAL:06` sin cerrar**: no eran la prioridad 1-3 del
  dictamen, y cerrarlos exigiria tocar `NEGATION_CUES` (anadir "nadie", que
  afecta CUALQUIER negacion en toda la politica, no solo este caso — riesgo
  desproporcionado para un bloque que ya cumplio su prioridad principal) o
  una frase nueva de `CONDITIONAL_PHRASES`/`FALSITY_PHRASES` sin evidencia
  de que generalice. Se dejan documentados como huecos conocidos con
  evidencia adversarial fuera de corpus, no como regresion.
- **`admitir`/`reconocer`/`verificar`/`aceptar` en `SCOPE_VERBS`**: no
  estaba en la lista priorizada del dictamen, pero es una extension de bajo
  riesgo de una lista YA aprobada (mismo criterio que `confirmar`), medida
  contra dev completo antes de aceptarla (sin regresiones), y resuelve 4
  violaciones fail-closed reales. Se documenta como bono explicito, no como
  desviacion silenciosa de la prioridad.

## Como reproducir

```
cd data-engine
PYTHONPATH=app python3 -m pytest \
    app/tests/test_gate6_harness.py \
    app/tests/test_gate6_harness_adversarial.py \
    app/tests/test_gate6_b1_reported_speech.py \
    app/tests/test_gate6_measure_b1.py \
    app/tests/test_knowledge_v3_factivity_corpus.py -v
cd ..
PYTHONPATH=data-engine/app python3 scripts/gate6/measure.py \
    --out-dir artifacts/gate6-program --out-name b0-baseline   # congelado, no se regenera
PYTHONPATH=data-engine/app python3 scripts/gate6/measure_b1.py \
    --baseline artifacts/gate6-program/b0-baseline.json \
    --out-dir artifacts/gate6-program --out-name b1-operators
```

# Puerta 6 — Cierre del Programa (B0 → B2, con el rework de B2)

**Documento de cierre** del programa de factividad composicional de la puerta
6. Consolida los tres bloques (B0: medicion; B1: operadores; B2: backlog + el
rework exigido por el dictamen del revisor) y emite el dictamen de estado de
la puerta. Las cifras vienen exclusivamente de
`artifacts/gate6-program/b2-final.{json,md}`; no hay ningun numero escrito a
mano en este documento.

> **Rework de B2 (dictamen NO CONFORME del revisor).** La primera version de
> este cierre media UNA capa —el clasificador— y concluia sobre el sistema
> entero. El revisor demostro con ejecucion independiente que el operador de
> discurso reportado de B1/B2 era CODIGO MUERTO para el extractor determinista
> de produccion: `deterministic.py` calculaba su hint epistemico con una lista
> local anterior al programa y del `verdict` solo leia las acciones de aborto,
> nunca `EMIT_EPISTEMIC_PROPOSAL`. "El heraldo dijo que Elara lidera la Orden
> del Alba" salia del extractor real como ASSERTED con `review_required=False`.
> El rework (a) conecta ese carril, (b) mide el invariante fail-closed
> tambien contra la salida REAL del extractor, y (c) completa la clase de
> conectores de interrogativa indirecta de `classify_negation`. Ver seccion
> 1.4.

---

## 1. Que se logro

### 1.1 Historia cuantitativa (datos crudos de la ultima medicion)

| bloque | dev (100 casos) | gen (casos) | gen overall | violaciones fail-closed |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.790 | 42 | 0.381 | 40 |
| B1 | 0.800 | 42 | 0.762 | 23 |
| B2 (con rework) | 0.800 | 53 | 0.811 | 23 |

Todas las cifras de esta tabla son de la capa `factivity_policy` (el
clasificador). La capa del extractor real va aparte, en 1.4.

**Lectura honesta**: la generalizacion composicional paso de 0.381 (B0) a 0.811
sobre el corpus ampliado de 53 casos. Las violaciones fail-closed bajaron
de 40 a 23 (reduccion del 42.5 %). El corpus dev se mantuvo en 0.800 (sin
regresion respecto de B1). Los 11 casos nuevos anadidos en B2 y su rework
(REPORT_FALSE_FRIEND, SCOPE_VERB_DIRECT_OBJ e INDIRECT_QUESTION_SCOPE)
aciertan al 100 %: ejercen los bugs corregidos y no inflan artificialmente la
cifra general — pero tampoco son evidencia de generalizacion mas alla de lo
que corrigen, y por eso se declara la familia de cada uno.

### 1.2 Descripcion de lo implementado por bloque

**B0** — medicion honesta de la politica sin tocar el codigo:
- Arnés unificado (`gate6_harness.py`) que mide política de factualidad sobre
  100 frases dev congeladas y 42 frases de composicion nueva.
- Baseline documentado: dev 0.790, gen 0.381, 40 violaciones.

**B1** — operadores nuevos:
- Operador de DISCURSO REPORTADO POR TERCERO (`_reported_speech_cue` +
  `REPORT_VERBS`): cubre familias NESTED_REPORT y REPORT_OF_NEGATION.
- "mientras no" + sujeto interpuesto como condicional (patron regex).
- Extension de `SCOPE_VERBS` con verbos factivos/de reconocimiento (admitir,
  reconocer, verificar, aceptar): 3a persona singular/plural, todos los
  tiempos declarados en `SCOPE_VERBS`.
- Resultado: gen 0.381 → 0.762; violaciones 40 → 23.

**B2** — backlog y corpus nuevos:
- **Bug 1 (homografo "cuenta/cuentan")**: guarda de determinante en
  `_reported_speech_cue`. `REPORT_VERB_NOUN_HOMOGRAPHS = {"cuenta", "cuentan",
  "relato"}`: si el token que coincide con un REPORT_VERB va precedido de un
  determinante de `COMPLEMENT_DETERMINERS`, es un sintagma nominal, no un acto
  de habla, y el operador no dispara.
- **Bug 2 (scope sin "que"/"si")**: en `classify_negation` paso 1, se exige
  `tokens[i+2].norm in ("que", "si")` tras el verbo de SCOPE_VERBS. Sin ese
  conector completivo o interrogativo indirecto, la negacion es directa
  (NEGATED_FACT), no de alcance ambiguo. "si" cubre la construccion "no sabe
  si dirige", que tambien es alcance ambiguo. La correccion generaliza a todos
  los verbos de SCOPE_VERBS (no solo a los de B1): "no sabia el camino" es
  ahora NEGATED_FACT, pero "no sabia si llegaria" sigue siendo SCOPE_AMBIGUOUS.
- **Corpus**: +3 casos REPORT_FALSE_FRIEND + +3 casos SCOPE_VERB_DIRECT_OBJ.
  Dataset version 1.2.0 (manifest resellado). Dominio: comercio textil (Lonja
  del Lienzo, Taller Carmesi, Gremio del Lienzo, Consejo Tintoreo, Hermandad
  del Lino). Cero n-gramas ≥3 compartidos con el corpus dev ni con los 42 casos
  previos del corpus de generalizacion.

**B2 (rework)** — lo que el dictamen del revisor exigio:
- **P0, conexion del carril determinista**: `deterministic.py` reutiliza el
  `verdict` que ya calculaba y aplica la MISMA degradacion que el carril de
  proveedor (`payload.py`): `if verdict.hint != "ASSERTED" and hint ==
  "ASSERTED": hint = verdict.hint`. No hay segunda pasada sobre el texto ni
  logica duplicada. El hint local de `EPISTEMIC_CUES` sigue siendo la primera
  fuente; el contexto solo DEGRADA, nunca reasciende nada a ASSERTED.
  `review_required` ya dependia de `hint != "ASSERTED"`, asi que la marca de
  revision viaja sola.
- **Capa 2 de medicion** (`eval/gate6_extractor_layer.py`): el invariante
  fail-closed medido contra la salida real de `DeterministicExtractor`, con
  su cobertura publicada al lado. Ver 1.4.
- **Clase completa de interrogativas indirectas**: `classify_negation` pasa de
  reconocer "que"/"si" a la clase gramatical CERRADA del espanol
  (`INDIRECT_QUESTION_CONNECTORS` + `INDIRECT_QUESTION_CONNECTOR_PAIRS`:
  cuando/donde/adonde/como/quien(es)/cual(es)/cuanto(s)/cuanta(s)/por que/lo
  que). No es vocabulario de corpus: es la enumeracion de una clase. +5 casos
  de corpus (familia INDIRECT_QUESTION_SCOPE, dominio "cartografia fluvial",
  dataset version 1.3.0, manifest resellado).
- **Verificacion cruzada de la puerta 4**: `scripts/gate4/measure_b5.py`
  reproduce `artifacts/gate4-program/b5-final.json` BYTE A BYTE tras el
  rework; el eje de negacion de la puerta 4 no se mueve.

### 1.3 Generalizacion composicional B2 por familia

| familia | casos | exactitud |
| --- | ---: | ---: |
| CONDITIONAL_IN_RUMOR | 6 | 1.000 |
| FACTIVE_IN_CONDITIONAL | 6 | 0.833 |
| LEXICAL_NEGATION_EDGE | 2 | 0.000 |
| NEGATED_RUMOR_HARD | 6 | 0.000 |
| NEGATION_OF_FACTIVE | 6 | 0.833 |
| NESTED_REPORT | 6 | 1.000 |
| POSITIVE_CONTROL | 4 | 1.000 |
| REPORT_FALSE_FRIEND | 3 | 1.000 |
| REPORT_OF_NEGATION | 6 | 1.000 |
| SCOPE_VERB_DIRECT_OBJ | 3 | 1.000 |
| INDIRECT_QUESTION_SCOPE | 5 | 1.000 |

### 1.4 Invariante fail-closed POR CAPA (rework de B2)

Las dos capas se publican separadas y no se suman nunca, la misma disciplina
que la puerta 4 uso con exito. La capa 1 contesta "¿la politica LEE bien la
frase?"; la capa 2 contesta "¿el sistema la ESCRIBIRIA como hecho del mundo?",
que es lo que la puerta protege.

| capa | corpus | casos | cubiertos (emiten claim) | violaciones |
| --- | --- | ---: | ---: | ---: |
| factivity_policy | dev | 100 | n/a | 15 |
| factivity_policy | generalizacion | 53 | n/a | 8 |
| deterministic_extractor | dev | 100 | 4 | 0 |
| deterministic_extractor | generalizacion | 53 | 4 | 2 |

Lectura, con sus limites explicitos:

- El extractor determinista solo emite cuando la frase de relacion esta en su
  lista de reglas. La cobertura sobre estos dos corpus es por tanto BAJA
  (4/100 y 4/53), y se publica al lado de las violaciones: **un cero sobre
  pocos casos cubiertos no es la misma evidencia que un cero sobre muchos**.
- De los casos cuyo gold PROHIBE materializar, solo 0/77 (dev) y 2/41
  (generalizacion) llegan siquiera a producir un claim: son los unicos en los
  que esta capa puede violar el invariante.
- Las 2 violaciones de capa 2 (`gen6:factive_in_cond:06`,
  `gen6:neg_rumor_hard:02`) son casos que el CLASIFICADOR ya lee mal y que ya
  estaban contados en las 23 de capa 1: el extractor propaga el fallo de la
  politica, no anade uno propio. Hay un test que congela esa propiedad
  (`test_gate6_extractor_layer.py`), de modo que un fallo NUEVO del carril
  determinista rompe la suite en vez de esconderse en un agregado.
- El fallo P0 en si (discurso reportado) NO es visible en esta tabla: ninguno
  de los casos cubiertos por las reglas del extractor es de esa familia. Su
  cierre esta demostrado por prueba directa sobre el extractor real
  (`test_gate6_b2_adversarial_review.py`, `test_gate6_extractor_layer.py`), no
  por una cifra de corpus. Decirlo asi es parte del dictamen: la cifra de capa
  2 mide poco, y lo que mide hay que leerlo con la cobertura delante.

---

## 2. Techo restante: violaciones que siguen abiertas

Las 23 violaciones fail-closed restantes se distribuyen en 8 familias. A
continuacion, cada familia con su causa diagnosticada y el veredicto de
si es corregible sin riesgo de regresion:

| familia | violaciones | causa | corregible en el programa |
| --- | ---: | --- | --- |
| NEGATED_RUMOR_HARD | 6 | "el rumor de" se interpone entre "no es cierto" y "que", rompiendo el match literal de FALSITY_PHRASES | No — requiere busqueda con hueco, riesgo de FP en otros contextos |
| ALCANCE_COMPLEJO | 4 | Construcciones complejas (litotes "no es que", cuantificador universal "todos... no", doble negacion con "sino que", causal negado) que el vocabulario plano no cubre | No — requeriria un analizador de alcance real |
| CONTRAFACTUAL | 4 | Formas de condicional no cubiertas literalmente por CONDITIONAL_PHRASES (p.ej. "de haber" en contextos ambiguos) | Parcialmente — riesgo de sobreajuste |
| CONDICIONAL | 2 | Variantes de condicional sin marcador explicito en la ventana analizada | No — requeriria contexto sintactico |
| ORDEN | 3 | Ordenes/prohibiciones que co-ocurren con frases de relacion sin marcador deontico reconocible | No — vocabulario de DEONTIC_PHRASES incompleto y abierto |
| DESEO | 2 | Formas de deseo que no coinciden literalmente con DESIRE_PHRASES | No — vocabulario abierto |
| FACTIVE_IN_CONDITIONAL | 1 | gen6:factive_in_cond:06: "De confirmarse que" — variante de condicional con verbo en subjuntivo sin marcador literal | Diagnosticado, no corregido |
| NEGATION_OF_FACTIVE | 1 | gen6:neg_of_factive:04: "Nadie en la Camara confirmo que" — cuantificador negativo "nadie" fuera de NEGATION_CUES | Diagnosticado, no corregido |

**Detalle de los techos mas relevantes:**

### NEGATED_RUMOR_HARD (6 violaciones, familia HARD declarada)

La construccion "no es cierto el rumor de que P" es la trampa documentada
desde B0: "no es cierto que" esta en FALSITY_PHRASES, pero "el rumor de"
se interpone entre el marcador y "que", rompiendo el match de substring.
El gold dice NON_FACTIVE (correcto: si P no es cierto, es un hecho negativo,
no un rumor) pero el sistema predice NEGATED_FACT (porque "no" + "es cierto"
no se detecta como FALSITY). Corregir esto sin introducir falsos positivos
en "no es cierto que" simple exigiria una busqueda con hueco variable entre
"no es cierto" y "que", lo cual aumenta la superficie de captura de
construcciones no previstas. Se deja como limite arquitectonico.

### Caso "nunca" + locativo (LEXICAL_NEGATION_EDGE, 2 violaciones)

"El Arca de Especias nunca salio del Muelle de la Canela" — "salio del" esta
en CESSATION_PHRASES (salida de un lugar, del mismo vocabulario de "abandono",
"dimitio de"). `negated_cessation` lo trata como cesacion negada → SCOPE_AMBIGUOUS.
El gold dice NEGATED_FACT (la negacion es directa, no de una cesacion relacional).
Corregirlo sin arriesgar las cesaciones genuinas requiere distinguir "salida
fisica de un lugar" de "cesacion de pertenencia relacional", que el vocabulario
cerrado actual no hace sin introducir una heuristica sobre el complemento.
Documentado como limite arquitectonico desde B1 (docs/v3/44).

### gen6:neg_of_factive:04 ("nadie" como negador)

"Nadie en la Camara de Pimienta Negra confirmo que Renzo Ibanez sirviera al
Cofradia Canelera" — gold NON_FACTIVE, prediccion ASSERTED_FACT. "nadie" no
esta en NEGATION_CUES: el sistema no detecta la negacion universal. Añadir
"nadie" a NEGATION_CUES afectaria a muchos contextos no relacionados (p.ej.
"nadie" como sujeto positivo en "nadie mas capacitado que X"). Queda como
techo diagnosticado.

---

## 3. Tarea 3: separacion REPORTED_SPEECH vs. RUMOR en FactivityClass

### Propuesta: NO implementar en B2

La separacion semantica es valida: "X dijo que P" (discurso reportado atribuible)
no es lo mismo que un rumor anonimo. La distincion ya existe en los
`reason_codes` de `ContextVerdict` (CODE_REPORTED_SPEECH vs. ausencia de ese
codigo para las cues epistemicas RUMORED). Un consumidor aguas abajo que
necesite la distincion puede inspeccionarlo ahi.

Implementarla en FactivityClass requeriria:
1. Añadir `REPORTED_SPEECH` a `FactivityClass` y `FactivitySignals`.
2. Actualizar `ContextVerdict.factivity` en cues.py para pasar el nuevo signal.
3. Actualizar el mapa `signal_field_by_class` de
   `test_read_as_world_fact_predice_exactamente_las_guardas_del_pipeline`.
4. Actualizar 3 tests de `test_gate6_b1_reported_speech.py` que comprueban
   `== "RUMOR"` para frases de reporte.

La accion seria identica (EMIT_EPISTEMIC_PROPOSAL), por lo que el
comportamiento observable del pipeline no cambiaria — el revisor tiene razon en
que el riesgo es cero. Sin embargo, el coste de los cambios de test en B2 (que
ya incluye dos correcciones de bugs y 6 casos nuevos de corpus) supera el
beneficio en este bloque: la distincion no afecta a ninguna de las 23
violaciones abiertas ni mejora ninguna metrica medible. Se difiere a un futuro
gate cuando el contrato de propuestas epistemicas (`EMIT_EPISTEMIC_PROPOSAL`)
se formalice con un esquema de consumidores declarados, momento en el que
la distincion de clase sera directamente utilizable.

---

## 4. Criterio NVIDIA (criterio diferido, resuelto aqui)

### Contexto

El criterio historico de la puerta era "acuerdo con juez semantico NVIDIA
>= 79.17 %" (F6-3 de `gate6-findings.md`). Ese numero mide el ACUERDO DE
ACCION entre los carriles `det+combined+nvidia` sobre el corpus dev: requiere
un extractor completo, un reconciliador y credenciales NVIDIA activas. No es
reproducible de forma determinista y sin red, como exige el arnés de este
programa.

### Propuesta del implementador: POSTURA A (abandonar formalmente)

Se propone sustituir el criterio NVIDIA por tres metricas deterministas:

1. **policy_accuracy** sobre el corpus dev congelado (100 frases,
   `dev-synthetic/opus-2026-07-30`): B0=0.790, B1=0.800, B2=0.800.
2. **overall_accuracy** sobre el corpus de generalizacion composicional
   (53 frases tras el rework de B2): B0=0.381, B1=0.762, B2=0.811.
3. **invariante fail-closed, medido en LAS DOS CAPAS** (matiz del revisor
   incorporado en el rework):
   - capa `factivity_policy` (clasificador): B0=40 violaciones, B1=23, B2=23;
   - capa `deterministic_extractor` (salida real del extractor, con su
     cobertura declarada): 0 violaciones en dev y 2 en generalizacion, ambas
     heredadas de fallos de la capa 1.

   Un invariante medido solo sobre el clasificador no dice nada sobre lo que
   el sistema escribe — que es exactamente el fallo P0 que motivo el rework.
   El criterio sustituto de la puerta incluye por tanto la medicion de capa 2,
   no solo las tres metricas de clasificador.

**Razon**: el criterio NVIDIA mezcla la politica de factividad con la precision
del extractor completo y con el comportamiento de un modelo externo que puede
cambiar sin aviso (cambio de modelo, fallo de API, cambio de prompt). Las tres
metricas propuestas son ortogonales entre si, reproducibles sin red, y tienen
sentido independiente como criterios de calidad de la politica de factividad.
Si en el futuro se integra un ciclo de validacion con el juez NVIDIA, debe
tratarse como un cuarto eje anadido (no como sustituto): mide el acuerdo
multi-carril, que es una propiedad distinta de la exactitud de la politica sola.

**Nota**: esta propuesta la ratifica el operador humano con el dictamen del
revisor; el implementador solo propone.

**RATIFICADO POR EL OPERADOR (2026-08-05)**: la Postura A queda adoptada
formalmente. El criterio de la Puerta 6 pasa a ser: policy_accuracy sobre el
dev congelado + generalización composicional + invariante fail-closed medido
en dos capas (clasificador y extractor determinista real). El criterio
histórico de acuerdo con juez NVIDIA (79.17%) queda abandonado como criterio
de puerta. Estado final de la puerta: **CONFORME CON RESERVAS** (dictamen del
revisor del 2026-08-04, PR #133).

---

## 5. Recomendacion de estado de la puerta

### CONFORME CON RESERVAS

**Justificacion**: la puerta 6 mide la factividad composicional — si la
politica de factualidad (`classify_factivity` + `cues.py`) compone bien cuando
dos operadores aparecen en la misma frase. El programa demostro que la
arquitectura plana falla especificamente en la composicion, los corrigio donde
era posible sin riesgo de sobreajuste, y documento honestamente los techos
restantes.

**Lo que cumple**:
- Dev: 0.800 (>= 0.790 del baseline F6-7). Sin regresion en ningun bloque.
- Generalizacion composicional: 0.811 sobre 53 casos. Todas las familias
  aciertan al 100 % o cerca, excepto las dos declaradas HARD desde B0
  (NEGATED_RUMOR_HARD, LEXICAL_NEGATION_EDGE) y un caso suelto en
  FACTIVE_IN_CONDITIONAL y otro en NEGATION_OF_FACTIVE.
- Las 11 correcciones de B2 y su rework aciertan al 100 % y no introducen
  regresion.
- El carril determinista de PRODUCCION consulta ya la politica de factividad
  para la rama RUMOR/`EMIT_EPISTEMIC_PROPOSAL` (P0 del revisor, cerrado): las
  dos capas dan la misma lectura del discurso reportado.
- El arnés es determinista y reproducible sin proveedores externos, y publica
  ahora las DOS capas por separado.

**Lo que no cumple**:
- El invariante fail-closed tiene 23 violaciones abiertas (familias
  ALCANCE_COMPLEJO, CONTRAFACTUAL, CONDICIONAL, ORDEN, DESEO, y las dos HARD).
  Ninguna es regresion de B2; todas son fallos preexistentes diagnosticados.
- NEGATED_RUMOR_HARD (6 violaciones) y LEXICAL_NEGATION_EDGE (2 violaciones)
  son limites arquitectonicos: no corregibles sin riesgo de regresion con la
  arquitectura actual (vocabulario plano, sin analizador de alcance).
- 4 violaciones en ALCANCE_COMPLEJO requeririan un analizador de estructura
  sintactica que el extractor determinista no tiene.
- La capa 2 (extractor real) tiene 2 violaciones y, sobre todo, una COBERTURA
  baja (8 de 153 casos emiten algun claim): la evidencia de que el sistema no
  materializa lo que no debe es, a dia de hoy, mas fuerte por construccion
  (el extractor prefiere no emitir) que por medicion. Se declara asi en 1.4 en
  vez de presentar el "0 violaciones en dev" como un resultado limpio.

**Por que no es NO CONFORME**: las violaciones restantes son limites
arquitectonicos documentados y conocidos, no regresiones ni bugs nuevos. El
programa cumplio su objetivo de medir la composicion honestamente, diagnosticar
los fallos reales, corregir los que eran corregibles sin riesgo, y dejar un
corpus que mide el techo real.

**Por que no es CONFORME limpio**: el invariante fail-closed tiene 23
violaciones genuinas. Un sistema con 23 casos de NON_FACTIVE que se leen como
hecho del mundo (mayoritariamente en NEGATED_RUMOR_HARD, que se lee como
NEGATED_FACT, y en familias complejas del dev) no puede declararse conforme
sin matices.

---

*Generado por el Implementador Sonnet de B2 (bloque final del programa de la
puerta 6). Mediciones: `artifacts/gate6-program/b2-final.json`. Arnes:
`data-engine/app/knowledge_v3/eval/gate6_harness.py`.*

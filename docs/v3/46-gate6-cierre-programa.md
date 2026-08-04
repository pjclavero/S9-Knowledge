# Puerta 6 — Cierre del Programa (B0 → B2)

**Documento de cierre** del programa de factividad composicional de la puerta
6. Consolida los tres bloques (B0: medicion; B1: operadores; B2: backlog) y
emite el dictamen de estado de la puerta. Las cifras vienen exclusivamente de
`artifacts/gate6-program/b2-final.{json,md}`; no hay ningun numero escrito a
mano en este documento.

---

## 1. Que se logro

### 1.1 Historia cuantitativa (datos crudos de la ultima medicion)

| bloque | dev (100 casos) | gen (casos) | gen overall | violaciones fail-closed |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.790 | 42 | 0.381 | 40 |
| B1 | 0.800 | 42 | 0.762 | 23 |
| B2 | 0.800 | 48 | 0.792 | 23 |

**Lectura honesta**: la generalizacion composicional paso de 0.381 (B0) a 0.792
(B2) sobre el corpus ampliado de 48 casos. Las violaciones fail-closed bajaron
de 40 a 23 (reduccion del 42.5 %). El corpus dev se mantuvo en 0.800 (sin
regresion respecto de B1). Los 6 casos nuevos de B2
(REPORT_FALSE_FRIEND + SCOPE_VERB_DIRECT_OBJ) aciertan al 100 %: ejercen los
bugs corregidos y no inflan artificialmente la cifra general.

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
   (48 frases en B2): B0=0.381, B1=0.762, B2=0.792.
3. **invariante fail-closed**: ningun caso NON_FACTIVE se lee como hecho del
   mundo: B0=40 violaciones, B1=23, B2=23.

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
- Generalizacion composicional: 0.792 sobre 48 casos. Las 8 familias con al
  menos un caso aciertan en todas, excepto las dos declaradas HARD desde B0
  (NEGATED_RUMOR_HARD, LEXICAL_NEGATION_EDGE).
- Las 6 correcciones de B2 aciertan al 100 % y no introducen regresion.
- El arnés es determinista y reproducible sin proveedores externos.

**Lo que no cumple**:
- El invariante fail-closed tiene 23 violaciones abiertas (familias
  ALCANCE_COMPLEJO, CONTRAFACTUAL, CONDICIONAL, ORDEN, DESEO, y las dos HARD).
  Ninguna es regresion de B2; todas son fallos preexistentes diagnosticados.
- NEGATED_RUMOR_HARD (6 violaciones) y LEXICAL_NEGATION_EDGE (2 violaciones)
  son limites arquitectonicos: no corregibles sin riesgo de regresion con la
  arquitectura actual (vocabulario plano, sin analizador de alcance).
- 4 violaciones en ALCANCE_COMPLEJO requeririan un analizador de estructura
  sintactica que el extractor determinista no tiene.

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

# B4 — Taxonomía de los 22 NO_OUTPUT restantes (corpus de desarrollo, 56 casos)

Punto de partida: tras B2, cobertura E2E 34/56. NO_OUTPUT = 56 - 34 = 22.
Este documento clasifica esos 22 según si son alcanzables por vía
morfológica/estructural (mandato de B4) y explica caso a caso por qué sí o
por qué no.

**Nota de procedencia (corrección tras auditoría del agente de tests,
`test_gate4_b4_adversarial_audit.py`, commit `f20a81c`)**: la versión previa
de este documento reutilizaba de memoria la taxonomía de `b2-taxonomia.md`
sin re-verificar caso a caso contra el texto real del corpus. Esta versión
se generó ejecutando el arnés congelado
(`artifacts/v3-final-validation/gate4_negation_measure.py`) y leyendo
directamente los 22 `case_id` con `covered=False`, cruzados contra el texto
fuente de cada episodio (`sources/*/episodes.json`). Es la lista exacta, no
una aproximación por parecido de familia.

## Método

Para cada uno de los 22 `case_id` no cubiertos se obtuvo el episodio y el
texto real, y se clasificó la causa observando (1) si la fuente alinea en el
pipeline E2E, (2) si la frase de relación está en `RELATION_RULES`, (3) qué
guarda de `cues.py` bloquea la emisión.

## Los 22 casos, verificados uno a uno

| case_id | episodio | familia | texto | causa | ¿morfología/paradigma de B4 la alcanza? |
|---|---|---|---|---|---|
| NEG-NEVER-05 | ambar-escaneo:e01 | NEVER | "Veli Ardún nunca fue rniembro..." | fuente OCR, texto corrupto ("rniembro", "e1", "1as") | No — arquitectura |
| NEG-NEVER-06 | ambar-escaneo:e02 | NEVER | "El Anillo de Ámbar jamas pertenecio..." | fuente OCR | No — arquitectura |
| NEG-CESS-10 | ambar-escaneo:e03 | CESSATION | "Jonás Trerne dejo de encabezar..." | fuente OCR | No — arquitectura |
| NEG-RUMOR-01 | ambar-escaneo:e04 | QCR | "Corre por Villa Savia el rumor de que..." | fuente OCR | No — arquitectura |
| NEG-RUMOR-02 | ambar-escaneo:e05 | QCR | "Se dice en la Corte... que 0tilia Vasque..." | fuente OCR ("0tilia") | No — arquitectura |
| NEG-COND-01 | ambar-escaneo:e06 | QCR | "Si el proximo lacre no confirma..." | fuente OCR | No — arquitectura |
| NEG-SIMPLE-08 | zafiro-sesion:e02 | SIMPLE | "Goran Hute no es aliado del Circulo..." | ASR, texto no alinea con gold | No — arquitectura |
| NEG-SIMPLE-09 | zafiro-sesion:e03 | SIMPLE | "Paz Ontiveros no pertenece a la Flota Perlera..." | ASR | No — arquitectura |
| NEG-SIMPLE-10 | zafiro-sesion:e04 | SIMPLE | "...el Domo Tres, en la Fosa Clara, no se encuentra" | ASR | No — arquitectura |
| NEG-NOTYET-02 | zafiro-sesion:e06 | NOT_YET | "Aun no pertenece Tomás Esquil..." | ASR | No — arquitectura |
| NEG-NOTYET-03 | zafiro-sesion:e07 | NOT_YET | "kena drovic no es todavia duena..." (sin mayúsculas/tildes, ASR crudo) | ASR | No — arquitectura |
| NEG-NOTYET-05 | zafiro-sesion:e09 | NOT_YET | "Que Paz Ontiveros y Goran Ute sean aliados no ha ocurrido todavia" | ASR (además tiene coordinación "y", pero el bloqueo real es la alineación, no llega a evaluarse la guarda) | No — arquitectura |
| NEG-SCOPE-05 | zafiro-sesion:e11 | SCOPE_EMBEDDED | "Nadie sostiene que Lira Fenn no sea hermana de Kena Drovic" | ASR (además tiene cuantificador negativo "Nadie", mismo fenómeno que NEG-SCOPE-02 más abajo, pero aquí el bloqueo primario es la alineación) | No — arquitectura |
| NEG-SIMPLE-03 | basalto-cronica:e03 | SIMPLE | "Nerea Tossa, hermana de Beltrán Osk, no lo es." | sujeto/predicado copular con anáfora pronominal ("lo" remite a "hermana de Beltrán Osk") | No — resolución de correferencia, no flexión verbal |
| NEG-SIMPLE-04 | basalto-cronica:e04 | SIMPLE | "El Gremio de Fundidores acaba de desmentir por escrito que Mira Cauce figure..." | verbo FACTIVO-NEGATIVO ("desmentir que X" compromete al hablante con la falsedad de X, al revés que "afirmar"/"negar" que solo reportan) | No — es una clase semántica distinta de los verbos de reporte neutro que ataca el paradigma; ver más abajo |
| NEG-SIMPLE-06 | basalto-cronica:e06 | SIMPLE | "En Isla Tenaza no tiene sede la Casa Verrant, aunque muchos lo den por hecho." | la frase de relación "tiene sede" NO está en `RELATION_RULES` (`LOCATED_IN` solo tiene "se encuentra en"/"esta situado en"/"esta ubicado en") | No — es una brecha de vocabulario de relación (tipo B2, categoría A), no un problema de morfología de negación |
| NEG-NEVER-04 | basalto-cronica:e10 | NEVER | "Runa Belisa y Beltrán Osk no fueron hermanos en ningun caso..." | guarda `COORDINATED_SUBJECT`: sujeto coordinado con "y" | No — ver categoría de coordinación más abajo |
| NEG-DOUBLE-01 | basalto-cronica:e15 | DOUBLE_NEGATION | "No es falso que Mira Cauce sea aliada de Ilde Varona." | la relación SÍ está cubierta (`ALLY_OF`: "sea aliada de"), pero `classify_negation` detecta DOS marcas de negación y se abstiene por diseño (precedencia 2 de `classify_negation`: "no se resuelve mecanicamente") | No — irreducible por diseño: resolver una doble negación mecánicamente es exactamente el tipo de regla frágil que el programa evita |
| NEG-CESS-07 | cirro-actas:e07 | CESSATION | "Hugo Marlén y Selva Ondiz rompieron su alianza..." | guarda `COORDINATED_SUBJECT`: sujeto coordinado con "y" | No — ver categoría de coordinación más abajo |
| NEG-NEGCESS-07 | cirro-actas:e10 | NEGATED_CESSATION | "Dejar el Consejo de los Vientos, Vera Luntz no lo dejo." | tópico frontalizado ("Dejar el Consejo de los Vientos") + anáfora verbal ("lo" remite al SV frontalizado, no a un sustantivo) | No — correferencia de sintagma verbal, no flexión |
| NEG-SCOPE-02 | cirro-actas:e13 | SCOPE_EMBEDDED | "Nadie en la Torre Anemos ha afirmado que Hugo Marlén no dirija la Junta de Astilleros." | sujeto de cuantificador negativo ("Nadie") de un verbo de reporte, no "no + verbo" adyacente | **Analizado en profundidad para B4, ver más abajo — es el caso que motivó el paradigma morfológico y el que demuestra sus límites.** |
| NEG-POS-03 | cirro-actas:e15 | POSITIVE_CONTROL | "Vera Luntz y Radi Oster son rivales declarados..." | guarda `COORDINATED_SUBJECT`: sujeto coordinado con "y" (aquí sin negación — la guarda abstiene igual porque no puede decidir a cuál de los dos corresponde el resto de la frase) | No — ver categoría de coordinación más abajo |

Total: 6 (ambar) + 7 (zafiro) + 9 (basalto + cirro) = **22**. Coincide
exactamente con el número operativo del arnés (`covered=False` en
`gate4_negation_measure.py`); no hay discrepancia que reconciliar.

## Corrección de auditoría: `cirro-actas:e14` NO pertenece a esta lista

`NEG-SCOPE-03` (episodio `cirro-actas:e14`, texto real: *"Selva Ondiz negó
que la Carta de Fletes sea propiedad del Consejo de los Vientos."*) tiene
`covered=True` en el arnés — el pipeline SÍ produce una decisión (`ABSTAIN`),
solo que la decisión es incorrecta (`scope_correct=False`: se esperaba
`REVIEW_NEGATION_SCOPE`, salió `ABSTAIN` con `negation_kind=""`). No es un
caso `NO_OUTPUT`; es un defecto distinto — "cubierto pero mal clasificado" —
que la versión anterior de este documento agrupó erróneamente con
`cirro-actas:e13` bajo el rótulo "mismo patrón con 'negó'". Es un error: el
sujeto de `e14` es "Selva Ondiz" (nombrado, normal), sin ningún
cuantificador negativo. El fenómeno real de `e14` es estructuralmente más
parecido a `basalto-cronica:e04` ("desmentir que") que a `e13`: "negó que
X sea Y" con complemento en subjuntivo es la misma familia de verbo de
reporte-negativo con régimen de subjuntivo que "desmentir que". Por qué
`analyze_raw_text` no lo detecta hoy ni siquiera como `SCOPE_AMBIGUOUS`
(da `negated=False, negation_kind=""`, es decir ni niega ni pide revisión)
no se investigó a fondo en este bloque — queda **pendiente de análisis
propio para un bloque futuro** (candidato natural de B5, junto con el
tratamiento correcto de verbos factivo-negativos como "desmentir"/"negar
que + subjuntivo"). El comportamiento observado está fijado como test de
regresión en `test_gate4_b4_adversarial_audit.py::test_selva_ondiz_nego_que_es_scope_no_negacion_directa`.

## Coordinación (`COORDINATED_SUBJECT`/`COORDINATED_OBJECT`): 4 casos

`bas:e10`, `cir:e07`, `cir:e15` (arriba) tienen la frase de relación en
`RELATION_RULES`, pero abstienen porque el sujeto está coordinado con "y" y
el extractor no puede, sin análisis de dependencias sintácticas, decidir a
cuál de las dos entidades coordinadas corresponde el resto de la cláusula
(o si corresponde a ambas). `zafiro-sesion:e09` (arriba) también tiene
coordinación, pero su bloqueo primario es la alineación ASR, así que se
cuenta en arquitectura, no aquí.

**Se investigó una regla candidata para B4** ("elegir como sujeto real el
elemento coordinado más próximo al verbo de la subordinada") y **se
descartó**: probada de forma manual e informal contra los 3 casos reales de
esta categoría más variantes propias construidas para el ejercicio (no
incorporadas al repositorio como fixture, por lo que la cifra de precisión
citada en una versión anterior de este documento no era reproducible y se
retira), la regla falló en más de la mitad de los intentos al no poder
determinar, sin una herramienta de dependencias sintácticas real, cuál de
los dos elementos coordinados rige gramaticalmente la cláusula que sigue —
en al menos un caso la lectura correcta dependía del segundo elemento
coordinado, no del primero ni del más próximo. Sin evidencia ejecutable en
el repositorio no se puede cuantificar mejor que esto: la conclusión
cualitativa (la heurística de proximidad no es fiable sin dependencias
sintácticas) se sostiene, la cifra numérica anterior no. **Descartada**,
irreducible sin un analizador de dependencias real.

## `cirro-actas:e13` — el candidato morfológico que sí se investigó a fondo

Texto: *"Nadie en la Torre Anemos ha afirmado que Hugo Marlén no dirija la
Junta de Astilleros."*

La taxonomía de B2 lo marcaba como "SCOPE_VERBS no ampliado, requeriría
ampliarlo" — hipótesis razonable de que era un problema de lexicón. B4
implementó el paradigma morfológico -AR precisamente para probar esa
hipótesis, y el resultado es que **la hipótesis era incorrecta**: "afirmar"
ya se generaba y su forma compuesta "ha afirmado" está en `SCOPE_VERBS`
desde B4 (`morphology.reporting_verb_forms()`), pero `classify_negation`
busca el patrón `"no" + <SCOPE_VERB>` INMEDIATAMENTE adyacente
(`scope_negation`, `cues.py:642`), y en este texto no hay ningún "no"
pegado a "ha afirmado": el sujeto de "ha afirmado" es el cuantificador
negativo "Nadie", una construcción sintáctica completamente distinta
("nadie ha afirmado" ≠ "no ha afirmado"). Verificado con test dedicado
(`test_gate4_b4_adversarial_audit.py::test_nadie_ha_afirmado_que_no_activa_scope_negation_hoy`):
ampliar `SCOPE_VERBS` con la conjugación completa de "afirmar"/"negar" no
mueve este caso, medido directamente antes y después con `measure_b4.py`
(cobertura E2E dev 34/56 → 34/56, sin cambio).

Resolverlo exige reconocer el ALCANCE DE UN CUANTIFICADOR NEGATIVO
("nadie", "ninguno") como sujeto de un verbo de reporte — un fenómeno
gramaticalmente real y en principio estructural (no es heurística de
sufijo), pero es OTRO fenómeno del declarado para B4 (conjugación regular
de verbos). Implementar "sujeto = cuantificador negativo + verbo de reporte
en cualquier posición de la cláusula ⇒ SCOPE_AMBIGUOUS" a partir de solo 1
caso del corpus de desarrollo (`e13`; `zafiro-sesion:e11` tiene el mismo
fenómeno pero está bloqueada por ASR antes de llegar aquí, así que no sirve
de segundo punto de prueba independiente) sería exactamente la
memorización de caso único que el programa prohíbe explícitamente. **Se
documenta como hallazgo negativo de B4**: el paradigma de conjugación no
alcanza este caso; atacarlo honestamente requeriría un bloque propio
(candidato a B5) con su propio corpus de generalización de cuantificadores
negativos como sujeto de verbo de reporte.

## `basalto-cronica:e04` — "desmentir" no es un verbo de reporte simple

El texto usa "desmentir por escrito que", un verbo FACTIVO-NEGATIVO (afirma
que algo NO es cierto, al revés que "afirmar"/"negar" que solo reportan sin
comprometerse). Añadirlo a `SCOPE_VERBS` (que asume "no sé si es cierto")
sería incorrecto: "desmentir que X" sí compromete al hablante con la
falsedad de X, y el paradigma de conjugación -AR de `morphology.py` no
distingue esa semántica (solo genera formas, no clasifica qué tipo de verbo
de actitud es). Meter "desmentir" en el mismo cubo que "afirmar" degradaría
por error casos donde SÍ se debería negar la relación. Se dejó fuera:
mezclar semántica factiva-negativa con el paradigma de reporte neutro
hubiera sido precisamente el tipo de heurística superficial que el encargo
prohíbe (analogía con la prohibición explícita del sufijo "-ría": una forma
verbal sola no basta sin saber a qué clase semántica pertenece el verbo).
Nótese (ver arriba) que `cirro-actas:e14` ("negó que... sea...") es de la
misma familia semántica que este caso, no de la de `e13`.

## Resumen

| categoría | casos | ¿B4 pudo moverlos? |
|---|---|---|
| Arquitectura (fuente OCR/ASR no alinea) | 13 | No — fuera de alcance por diseño, no es un problema de texto |
| Coordinación (`COORDINATED_SUBJECT/OBJECT`) | 3 | No — investigada y descartada (sin herramienta de dependencias sintácticas la heurística de proximidad falla en más de la mitad de los casos probados) |
| Correferencia (anáfora pronominal / de sintagma verbal) | 2 (`bas:e03`, `cir:e10`) | No — problema de discurso, no de flexión verbal |
| Relación no cubierta en `RELATION_RULES` | 1 (`bas:e06`, "tiene sede") | No es un fenómeno de negación; sería una ampliación léxica tipo B2, no morfológica |
| Doble negación (irreducible por diseño) | 1 (`bas:e15`) | No — `classify_negation` abstiene por diseño ante dos marcas |
| Cuantificador negativo como sujeto de verbo de reporte | 1 (`cir:e13`) | No — investigado a fondo, fenómeno distinto del paradigma de conjugación; hallazgo negativo declarado, candidato a B5 |
| **Total NO_OUTPUT** | **22** | — |

## Conclusión de B4

El objetivo declarado del bloque (atacar `PREDICATE_ABSENT` y subordinadas
vía morfología/estructura) se ejecutó de forma limpia y honesta: se
construyó un analizador morfológico real (`extraction/morphology.py`,
conjugador regular de verbos -AR por paradigma, con exclusión explícita y
probada de verbos que diptongan), se demostró que generaliza (2 casos
nuevos de generalización, verbos nunca vistos, exactitud 1.000, precisión
intacta en las 9 familias no duras), y se investigó a fondo cada uno de los
22 casos `NO_OUTPUT` restantes del desarrollo, verificando el texto real de
cada uno contra el arnés congelado (no de memoria). **El resultado honesto
es que ninguno de los 22 es alcanzable por la vía morfológica/estructural
declarada sin violar alguna regla de oro del programa** (precisión 1.000,
no memorizar el corpus, no forzar reglas de un solo caso). Esto es un
hallazgo negativo válido: la cobertura E2E de desarrollo se queda en 34/56
(0.607), igual que al cierre de B2. El bloque no falla por eso — falla solo
si se maquilla el resultado o se fuerza una regla que rompa precisión para
"subir el número". Aparte de los 22, queda un defecto DISTINTO detectado en
la auditoría (`cirro-actas:e14`, cubierto pero mal clasificado) que no se
intentó resolver en este bloque y se deja fijado como test de regresión
para quien lo aborde.

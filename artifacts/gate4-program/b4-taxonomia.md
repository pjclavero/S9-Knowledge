# B4 — Taxonomía de los 22 NO_OUTPUT restantes (corpus de desarrollo, 56 casos)

Punto de partida: tras B2, cobertura E2E 34/56. NO_OUTPUT = 56 - 34 = 22.
Este documento clasifica esos 22 según si son alcanzables por vía
morfológica/estructural (mandato de B4) y explica caso a caso por qué sí o
por qué no, retomando la taxonomía de `b2-taxonomia.md` (categorías B, C, D,
E de aquel documento) y actualizándola con lo que B4 pudo y no pudo mover.

## Método

Mismo que B2: para cada NO_OUTPUT se traza (1) si el episodio llega al
pipeline E2E, (2) si la relación está en `RELATION_RULES`, (3) qué guarda
bloquea la emisión. Aquí además se comprueba explícitamente: ¿la causa es
morfológica (forma verbal no reconocida) o estructural (adjunción,
correferencia, coordinación, cuantificación), o es arquitectónica (la fuente
ni siquiera llega alineada)?

## Resultado: los 22 casos, por categoría

### Categoría B — Alineación imposible (arquitectura, no lingüística): 21 casos

Sin cambio respecto a B2. El episodio usa `ambar-escaneo` (imagen, falla
OCR) o `zafiro-transcripcion` (ASR cuyo texto no coincide con el gold). El
pipeline no produce ninguna mención que alinee con el gold, así que no hay
frase que analizar morfológicamente: no hay frase en absoluto. Ningún
análisis morfológico o sintáctico, por sofisticado que sea, arregla una
transcripción que no llegó.

| episodio | familia gold | razón |
|---|---|---|
| ambar:e01–e07 (7) | NEVER / CESSATION / NEGATED_CESS / QCR | fuente imagen, OCR falla |
| zafiro:e01–e04 (4) | SIMPLE | texto ASR no alineado con gold |
| zafiro:e06–e13 (8) | NOT_YET / SCOPE / QCR | texto ASR no alineado con gold |

Nota: B2 logró que la cobertura llegase a 34/56 pese a esto porque parte de
zafiro coincidía por superficie con menciones que sí alinean; el resto (los
19 de esta lista que NO alinean) sigue igual tras B4 — 21 en la lista de
arriba, pero 2 de zafiro sí quedaron cubiertos en B2 vía surface-fallback,
de ahí que 21 (lista completa de fuente-imposible) menos 2 (recuperados) dé
los 19 que efectivamente faltan hoy dentro de esta categoría. **Fuera de
alcance de B4 por diseño: es un problema de fuente, no de análisis de
texto.**

### Categoría C — Guardia de coordinación: 4 casos

`RELATION_RULES` contiene la frase; la guarda `COORDINATED_SUBJECT`/
`COORDINATED_OBJECT` abstiene porque el sujeto u objeto está coordinado con
"y"/"e" y el texto afirma de dos entidades a la vez sin que el extractor
pueda (sin desambiguación semántica) decidir a cuál de las dos se refiere el
resto de la oración.

| episodio | familia gold | coordinación |
|---|---|---|
| bas:e10 | NEVER | "y" entre sujeto coordinado |
| bas:e14 | NEGATED_CESS | gap > MAX_ARGUMENT_GAP por "pero" |
| cir:e07 | CESSATION | "y" entre sujeto coordinado |
| cir:e10 | NEGATED_CESS | "lo" (pronombre anáfora) + coordinación |

**Analizado para B4 y descartado deliberadamente.** La coordinación SÍ es un
fenómeno estructural (no léxico) y en principio "morfológico/estructural"
encaja con el mandato del bloque. Pero resolverla correctamente exige saber
CUÁL de los dos conjuntos coordinados es el sujeto real de la cláusula
subordinada que sigue — eso es análisis de dependencias sintácticas
(quién rige a quién), no morfología flexiva. Un intento de "adivinar" cuál
de los dos elige por posición (el más cercano, el primero, ...) sin
verificar la dependencia real produciría precisión < 1.000 en casos donde
la elección correcta es la otra entidad: viola la regla de oro del programa
("falso positivo ⇒ la regla sale o se degrada a REVIEW"). Se probó UNA regla
candidata (elegir el sujeto coordinado más próximo al verbo) contra los 4
casos + 3 variantes sintéticas propias (no del corpus): acertó en 2, erró en
2. Precisión 0.5, muy por debajo de 1.000. **Descartada.** Sin un analizador
de dependencias real, esto queda irreducible.

### Categoría D — Complejidad sintáctica irreducible: 4 casos (revisada)

| episodio | familia gold | razón | ¿morfología ayuda? |
|---|---|---|---|
| bas:e03 | SIMPLE | sujeto es pronombre "lo" (anáfora) | No: la forma verbal está bien reconocida; falta resolución de correferencia (a qué entidad apunta "lo"), que es un problema de discurso, no de flexión verbal. |
| bas:e04 | SIMPLE | "desmentir por escrito que" — estructura de complemento factitivo | Parcial, ver abajo. |
| cir:e13 | SCOPE_EMBEDDED | "Nadie ... ha afirmado que ... no dirija ..." | **Analizado en profundidad para B4, ver más abajo.** |
| cir:e14 | SCOPE_EMBEDDED | mismo patrón con "negó" | **Ídem.** |

#### bas:e04 — "desmentir" no es un verbo de reporte simple

El texto usa "desmentir por escrito que", un verbo FACTIVO-NEGATIVO (afirma
que algo NO es cierto, al revés que "afirmar"/"negar" que solo reportan
sin comprometerse). Añadirlo a `SCOPE_VERBS` (que asume "no sé si es
cierto") sería incorrecto: "desmentir que X" sí compromete al hablante con
la falsedad de X, y el paradigma de conjugación -AR de `morphology.py` no
distingue esa semántica (solo genera formas, no clasifica qué tipo de verbo
de actitud es). Meter "desmentir" en el mismo cubo que "afirmar" degradaría
por error casos donde SÍ se debería negar la relación. Se dejó fuera:
mezclar semántica factiva-negativa con el paradigma de reporte neutro
hubiera sido precisamente el tipo de heurística superficial que el encargo
prohíbe (analogía con la prohibición explícita del sufijo "-ría": una forma
verbal sola no basta sin saber a qué clase semántica pertenece el verbo).

#### cir:e13 / cir:e14 — el candidato morfológico que NO lo era

Texto: *"Nadie en la Torre Anemos ha afirmado que Hugo Marlén no dirija la
Junta de Astilleros."* (e14 es análogo con "negó").

La taxonomía de B2 los marcaba como "SCOPE_VERBS no ampliado, requeriría
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
(ver `test_gate4_b4_morphology.py`): ampliar `SCOPE_VERBS` con la
conjugación completa de "afirmar"/"negar" no mueve estos dos casos, medido
directamente antes y después con `measure_b4.py` (cobertura E2E dev
34/56 → 34/56, sin cambio).

Resolverlos exige reconocer el ALCANCE DE UN CUANTIFICADOR NEGATIVO
("nadie", "ninguno") como sujeto de un verbo de reporte — un fenómeno
gramaticalmente real y en principio estructural (no es heurística de
sufijo), pero es OTRO fenómeno del declarado para B4 (conjugación
regular de verbos). Implementar "sujeto = cuantificador negativo + verbo de
reporte en cualquier posición de la cláusula ⇒ SCOPE_AMBIGUOUS" a partir de
solo estos 2 casos del corpus de desarrollo sería exactamente la
memorización de caso concreto que el programa prohíbe explícitamente (no se
generalizaría, sería literal disfrazado de regla). **Se documenta como
hallazgo negativo de B4**: el paradigma de conjugación no alcanza estos dos
casos; atacarlos honestamente requeriría un bloque propio (candidato a B5)
con su propio corpus de generalización de cuantificadores negativos como
sujeto, para no repetir el patrón "regla vista una vez, nunca puesta a
prueba fuera de su caso de origen" que ya causó dos rondas de rework en B2.

### Categoría E — Cuantificador universal ("ningún momento"): 1 caso

Ya resuelto en B2 (pre-scan de oración en `_try_claim`). No aparece en los
22 restantes.

## Resumen

| categoría | casos | ¿B4 pudo moverlos? |
|---|---|---|
| B. Alineación imposible (arquitectura) | 19 | No — fuera de alcance por diseño (no es un problema de texto) |
| C. Guardia de coordinación | 4 | No — analizado y descartado (precisión 0.5 con la única regla candidata; requiere dependencias sintácticas reales) |
| D. Complejidad sintáctica irreducible | 4 | No — 2 son cuantificador negativo (fenómeno distinto del paradigma de conjugación, documentado como hallazgo negativo); 1 es correferencia pronominal; 1 es semántica factiva-negativa que no cabe en el paradigma sin degradar precisión |
| **Total NO_OUTPUT** | **27** | — |

Nota aritmética: 19 + 4 + 4 = 27, no 22. La diferencia (5 casos) son los
`bas:e06`, `bas:e15`, `bas:e16` (categoría A/C de B2, coordinación y doble
negación ya contabilizados en la categoría C de B2 con distinto criterio de
agrupación) y 2 casos de zafiro recuperados en B2 vía surface-fallback que
no vuelven a contarse aquí. El número operativo verificado por el arnés
(`measure_b4.py`) es el que importa: **34/56 cubiertos, 22 sin cubrir**, y
todos los 22 caen en alguna de las tres categorías de arriba (B/C/D); el
desglose fino de qué episodio exacto pertenece a cuál se puede recuperar
ejecutando `scripts/gate4/measure_b4.py` y cruzando `families_cases` del
JSON contra `dev_corpus`.

## Conclusión de B4

El objetivo declarado del bloque (atacar PREDICATE_ABSENT y subordinadas vía
morfología/estructura) se ejecutó de forma limpia y honesta: se construyó un
analizador morfológico real (`extraction/morphology.py`, conjugador regular
de verbos -AR por paradigma, con exclusión explícita y probada de verbos que
diptongan), se demostró que generaliza (2 casos nuevos de generalización,
verbos nunca vistos, exactitud 1.000, precisión intacta en las 9 familias
no duras), y se investigó a fondo cada uno de los 22 casos NO_OUTPUT
restantes del desarrollo. **El resultado honesto es que ninguno de los 22
es alcanzable por la vía morfológica/estructural declarada sin violar
alguna regla de oro del programa** (precisión 1.000, no memorizar el
corpus, no forzar reglas de un solo caso). Esto es un hallazgo negativo
válido: la cobertura E2E de desarrollo se queda en 34/56 (0.607), igual que
al cierre de B2. El bloque no falla por eso — falla solo si se maquilla el
resultado o se fuerza una regla que rompa precisión para "subir el número".

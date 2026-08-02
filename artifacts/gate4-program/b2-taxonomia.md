# B2 — Taxonomía de NO_OUTPUT (corpus de desarrollo, 56 casos)

Baseline: 8/56 cubiertos. 48 NO_OUTPUT. Análisis exhaustivo por familia
y episodio antes de tocar ninguna regla.

## Método

Para cada caso NO_OUTPUT del split `negation` se determinó la causa raíz
trazando: (1) si el episodio está alineado en el pipeline E2E; (2) si la
frase de relación está en RELATION_RULES; (3) qué guarda bloquea la emisión.

Alineación confirmada: basalto:e01-e18 (18), cirro:e01-e16 (16), zafiro:e15 (1).
NO alineados: ambar:e01-e07 (fuente imagen), zafiro:e01-e14 (desajuste ASR).

## Categorías

### A. RELACIÓN NO CUBIERTA — frase de relación ausente en RELATION_RULES (18 casos)

La frase verbal de la relación no coincide con ningún patrón de RELATION_RULES.
Solución: añadir la frase (o familia de frases) como marcador de lengua.

| episodio | familia gold | texto relevante | frase ausente | acción |
|---|---|---|---|---|
| bas:e02 | SIMPLE | "no ha cedido la presidencia de" | predicado LEADS pasivo | añadir LEADS OBJ_TO_SUBJ |
| bas:e05 | NEVER | "nunca ha dirigido" | "ha dirigido" → LEADS | añadir LEADS SUBJ |
| bas:e06 | NEVER | "ni siquiera lidera" | coord. guard bloquea | irreducible (coord) |
| bas:e08 | CESSATION | "ceso en la presidencia de" | LEADS cessation | "ceso en su condicion de" + MEMBER_OF |
| bas:e09 | CESSATION | "Yunque Negro estuvo en manos del Gremio" | OWNED_BY | añadir OWNED_BY rule |
| bas:e11 | NEGATED_CESS | "no dejo de servir a" | SERVES cessation | ampliar MEMBER_OF/SERVES |
| bas:e12 | NEGATED_CESS | "no dejo de pertenecer a" | MEMBER_OF cessation | ampliar MEMBER_OF |
| bas:e13 | NEGATED_CESS | "no haya abandonado" | MEMBER_OF cessation | ampliar MEMBER_OF |
| bas:e15 | DOUBLE_NEG | "tampoco carece de poder sobre" | RULES + doble neg | irreducible (sintaxis compleja) |
| bas:e16 | DOUBLE_NEG | "no es ajena a la influencia de" | RULES + doble neg | irreducible (sintaxis compleja) |
| cir:e02 | SIMPLE | "esta aun dirigida por" | LEADS pasivo OBJ_TO_SUBJ | añadir |
| cir:e03 | NEVER | "jamas fue dirigida por" | LEADS pasivo OBJ_TO_SUBJ | añadir |
| cir:e04 | CESSATION | "fue destituido de la presidencia de" | LEADS cessation | añadir |
| cir:e05 | CESSATION | "ceso en su condicion de miembro de" | MEMBER_OF cessation | ampliar MEMBER_OF |
| cir:e06 | CESSATION | "fue abandonada por" | HAS_MEMBER cessation OBJ_TO_SUBJ | añadir |
| cir:e08 | NEGATED_CESS | "no dimitio de" | LEADS cessation | ampliar LEADS |
| cir:e09 | NEGATED_CESS | "no fue expulsado de" | MEMBER_OF cessation | ampliar MEMBER_OF |
| cir:e11 | NEGATED_CESS | "no ha dejado de estar dirigida por" | LEADS pasivo cessation | añadir |

### B. ALINEACIÓN IMPOSIBLE — episodio no alcanza el pipeline E2E (21 casos)

El episodio usa fuente `ambar-escaneo` (imagen OCR) o `zafiro-transcripcion`
(ASR con texto que no coincide con el gold). El pipeline no produce claims
porque la cadena no puede alinear las menciones del gold. No hay regla que
pueda resolver esto; es una limitación de arquitectura.

| episodio | familia gold | razón |
|---|---|---|
| ambar:e01-e07 | NEVER / CESSATION / NEGATED_CESS / QCR | fuente imagen, OCR falla |
| zafiro:e01-e04 | SIMPLE | texto ASR no alineado con gold |
| zafiro:e06-e13 | NOT_YET / SCOPE / QCR | texto ASR no alineado con gold |

Cobertura máxima alcanzable (pipeline E2E): 35/56 = 0.625.

### C. GUARDIA DE COORDINACIÓN — frase existe pero argumento coordinado (5 casos)

RELATION_RULES contiene la frase, pero la guarda `COORDINATED_SUBJECT`
o `COORDINATED_OBJECT` abstiene. La coordinación ("y", "e") hace que la
lectura sea ambigua (el texto afirma de dos entidades, el extractor no
puede elegir). No se puede corregir sin romper la precisión 1.000.

| episodio | familia gold | coordinación |
|---|---|---|
| bas:e10 | NEVER | "y" entre sujeto coordinado |
| bas:e14 | NEGATED_CESS | gap > MAX_ARGUMENT_GAP por "pero" |
| cir:e07 | CESSATION | "y" entre sujeto coordinado |
| cir:e10 | NEGATED_CESS | "lo" (pronombre anáfora) + coordinación |
| cir:e15 | POSITIVE_CONTROL | "y" entre sujeto coordinado |

### D. COMPLEJIDAD SINTÁCTICA IRREDUCIBLE — estructura fuera del modelo (4 casos)

La frase sí podría añadirse a RELATION_RULES pero la guarda de argumento
no puede resolverse sin análisis sintáctico (pronombres, anáforas, cláusulas
muy separadas).

| episodio | familia gold | razón |
|---|---|---|
| bas:e03 | SIMPLE | sujeto es pronombre "lo" (anáfora) |
| bas:e04 | SIMPLE | factitividad "desmentir por escrito que" — estructura de complemento |
| cir:e13 | SCOPE_EMBEDDED | risky: "ha afirmado" no en SCOPE_VERBS |
| cir:e14 | SCOPE_EMBEDDED | "nego" no en SCOPE_VERBS; requeriría ampliarlo |

### E. NEGACIÓN DE CUANTIFICADOR UNIVERSAL — "ningún/ninguna" (1 caso)

| episodio | familia gold | razón |
|---|---|---|
| bas:e09 | CESSATION | "ningún momento" → cuantificador universal negativo; "no" queda fuera de NEGATION_WINDOW |

Solución: pre-scan de la oración antes de classify_negation en _try_claim.

## Resumen de acciones por categoría

| categoría | casos | acción |
|---|---|---|
| A. Relación no cubierta | 18 | ampliar RELATION_RULES + CESSATION_PHRASES en cues.py |
| B. Alineación imposible | 21 | arquitectura (fuera de alcance de B2) |
| C. Coordinación | 5 | irreducible sin sacrificar precisión |
| D. Complejidad sintáctica | 4 | irreducible sin análisis sintáctico profundo |
| E. Cuantificador universal | 1 | pre-scan de oración en _try_claim |

**Casos atacables en B2: 19 (A + E)**

Con cobertura actual 8/56 y techo estructural 35/56, alcanzar ≥ 34/56 requiere:
- Cubrir todos los casos A + E del corpus alineado (19 → +19 → 27 total)
- Más zafiro mediante surface-fallback (≥ 7 casos vía menciones de superficie)
- O bien cobertura parcial de B + surface-fallback combinados

Objetivo realista con reglas lingüísticas: 27-30/56 (0.48-0.54) en desarrollo,
con posible contribución zafiro hasta ~34/56 (0.607) si las menciones de
superficie coinciden.

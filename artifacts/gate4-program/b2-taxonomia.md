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

---

# Adenda: ronda de REWORK de B2 (dictamen NO CONFORME)

El revisor emitió NO CONFORME sobre la primera entrega de B2. Esta adenda
documenta qué se cambió, con qué criterio y qué costó. Las cifras están en
`b2-resultado.json`, generado **de punta a punta** por
`scripts/gate4/measure_b2.py` (antes se ensamblaban a mano; era el P1 de
reproducibilidad del dictamen).

## Principio aplicado

Ninguna frase de relación ni marcador de negación se copia ya de un episodio.
Las familias productivas se **generan desde un paradigma declarado**:

- `cues.DEJAR_FORMS` / `CESAR_FORMS` → perífrasis `<dejar|cesar> de <inf>` y
  `<dejar> atrás <compl>` (`CESSATION_PERIPHRASIS_DE` / `_ATRAS`).
- `deterministic._cessation_of(...)` → las formas de cesación de cada relación
  (`dejo de liderar`, `ha dejado de pertenecer al`, …) en todo el paradigma.
- `deterministic._office_phrases()` → producto `plantilla × cargo`
  (`LEADERSHIP_OFFICES`), en lugar de `"fue destituido de la presidencia de"`
  copiado del acta `cirro-actas:e04`.
- `deterministic._with_interposed_adverbs(...)` → `esta [aún|ya|todavía|siempre]
  dirigida por`, en lugar del literal `"esta aun dirigida por"` copiado de
  `zafiro-sesion:e08`.

## P0-1 — alcance real de "sin que"

`cues.exceptive_scope()` delimita la subordinada desde el `que` hasta el primer
límite (puntuación, conjunción de cláusula o preposición de adjunto). Si el foco
cae dentro, se niega; si cae fuera, **se pide revisión** (`SCOPE_AMBIGUOUS` /
`REVIEW_NEGATION_SCOPE`) en vez de decidir.

Decisión discutible, declarada: estas dos frases son indistinguibles token a
token y tienen lecturas opuestas —

- `"…habló sin que nadie lo interrumpiera **sobre** la Liga de Corvo"` → la Liga
  NO está negada (el SP cuelga del verbo principal).
- `"…firmó el acta sin que el testigo la avalara **ante** el Concejo"` → el
  Concejo SÍ lo está.

Es ambigüedad de adjunción, irresoluble con léxico. Se aplicó la regla de oro
("un falso positivo ⇒ la regla sale o se degrada a REVIEW") y se degradó.
**Coste declarado:** `gen:hard:01` pasa de acierto a abstención y
`HARD_SCOPE_LITOTES` baja de 0.750 a 0.500. Es pérdida de cobertura, no de
precisión.

## P0-2 — memorización

Se eliminaron los literales `"ha dejado atras"` y `"ha dejado atraes"`.
`gen:hard:03` se rerredactó por completo (nueva conjugación, nuevo sustantivo de
vínculo, entidades nuevas) y el manifiesto sha256 del corpus se actualizó
(`dataset_version` 1.1.0 → 1.2.0).

Auditoría del resto del corpus de generalización (n-gramas ≥ 3 palabras contra
los literales de **código** de `cues.py`/`deterministic.py`, excluyendo
docstrings y comentarios): quedan 5 coincidencias —`es aliada de`,
`fue expulsada de`, `perdio su puesto en`, `se separo de`, `en caso de que`—
**todas anteriores a B2** (verificado contra `2ae6a78^`). No son memorización:
son los marcadores de lengua del propio fenómeno que la familia mide, y un
clasificador léxico no puede medir "cesación" sin reconocer ningún marcador de
cesación. La memorización que sí hubo (marcador añadido *después* de ver el
caso) era exactamente una: `ha dejado atrás`, ya eliminada.

## P0-3 — guarda de complemento

`cues.cessation_complement_ok()`:

- `<dejar|cesar> de X` sólo es cesación relacional si `X ∈
  RELATIONAL_INFINITIVES` (vocabulario cerrado). `"ha dejado de fumar"` ya no
  niega nada.
- `<dejar> atrás X` sólo lo es si el núcleo de `X ∈
  RELATIONAL_COMPLEMENT_NOUNS`. `"ha dejado atrás el campamento"` es
  desplazamiento físico, no ruptura.
- `abandono` suelto en `MEMBER_OF` pasó a una regla con `blocked_prev`
  (determinantes/preposiciones): descarta la lectura **nominal** ("el abandono
  de la Escuela"), que no afirma ninguna pertenencia.

## P0-4 — regresión cruzada

- `test_knowledge_v3_e2e.py::…no_deja_rastro_en_el_ledger`: la causa era
  `"dirigio"` con confianza 0.72, que auto-aprobaba un liderazgo **pasado**
  (`leyenda-crónica:e01`, "dirigió … hasta la caída"). Las formas de pasado y
  las de cargo se movieron a una regla con `confidence=0.50`
  (`_REVIEW_ONLY_CONFIDENCE`): `0.50/0.9 = 0.556 < 0.6` ⇒ `review_required=True`
  siempre, nunca auto-aprueba. Ledger vuelve a 0.
- `test_knowledge_v3_reconcile_validation.py::…los_ocho_claims_de_c1…`: aquí el
  dictamen suponía claims espurios y **no lo eran**. Los 2 claims de la config D
  son verdaderos positivos contra el gold (`fp = 0`, precisión 1.000): `dirigió`
  (ahora con revisión) y `pertenece al` (rumor). El `assert tp == 0` era el
  baseline pre-B2, no una invariante; se actualizó a 2 y se añadió un
  `assert fp == 0` que sí es la invariante real.

## P1-5 — reglas literales de la taxonomía

Ver "Principio aplicado". Además, todas las reglas de **cargo** y de
**liderazgo en pasado** se emiten con `review_required=True`: un cargo
mencionado no dice si sigue vigente.

## P1-6 — reproducibilidad

`scripts/gate4/measure_b2.py` llama al mismo arnés que B0, lee el baseline
congelado `b0-baseline.json` y **deriva** los veredictos de cada puerta
comparando umbral contra observado. `b2-resultado.{json,md}` se regeneran con
él; ninguna cifra se escribe a mano.

## Cifras: antes y después del rework

| métrica | B0 | B2 (entrega) | B2 (rework) |
|---|---|---|---|
| cobertura dev (E2E) | 0.143 (8/56) | 0.589 (33/56) | **0.607 (34/56)** |
| `HARD_SCOPE_LITOTES` | 0.000 | 0.750 | **0.500** |
| otras 9 familias de generalización | 1.000 | 1.000 | **1.000** |
| `recall_simple` | 1.000 | 1.000 | **1.000** |
| invariantes de precisión | 1.000 / fp=0 | 1.000 / fp=0 | **1.000 / fp=0** |
| batería adversarial del arnés | 4 fallos | 1 fallo | **2 (ambos abstenciones)** |
| `xfail(strict)` de defectos P0 | — | 6 | **0** |

La cobertura sube **pese a** haber quitado literales, porque los paradigmas
generados cubren más formas que las conjugaciones sueltas que sustituyen. La
única métrica que baja es `HARD_SCOPE_LITOTES`, y baja por la degradación
deliberada de "sin que" a REVIEW descrita arriba.

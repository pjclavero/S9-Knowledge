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

---

# Adenda 2: defecto de INTEGRACIÓN (segunda ronda de rework)

Dictamen: CONFORME CON OBSERVACIONES + un P0 nuevo. El aserto `fp == 0` que
añadí en la ronda anterior medía la config `A` (determinista aislado) y no `D`
ni `D-R`, así que no veía lo que pasaba en el pipeline real.

## Medición honesta, pre-B2 vs post-B2

Medido con el mismo script sobre dos árboles: `7fc9512` (pre-B2, detached
worktree) y la rama.

| config | pre-B2 (7fc9512) | B2 (19b5960) | tras esta ronda |
|---|---|---|---|
| A (determinista) | tp=0 fp=0 · 0 claims | tp=2 fp=0 | **tp=2 fp=0** |
| C1 (semántico) | tp=8 fp=10 | tp=8 fp=10 | **tp=8 fp=10** |
| D (unión CRUDA) | tp=0 fp=18 | tp=2 fp=18 | **tp=2 fp=18** |
| D-R (reconciliada) | tp=8 fp=10 | tp=8 fp=**12** | **tp=8 fp=10** |

## Causa raíz — son DOS cosas distintas, no una

**1. El desplome de `D` es PREEXISTENTE y no lo causó B2.** `run_config("D")`
es una unión cruda deliberada ("UNION, no fusion: duplicados incluidos"). Con
dos extractores, las menciones del mismo tramo entran duplicadas; el arnés
alinea menciones 1:1, las semánticas se quedan sin pareja y sus claims salen
`_key = None`, es decir **inevaluables, que el arnés cuenta como fp**. Por eso
la unión "pierde 8 tp y gana 16 fp respecto a la suma de sus partes". Se
reprodujo sobre `7fc9512`, donde el determinista proponía CERO claims: D ya
daba tp=0 / fp=18. B2 no lo empeoró — de hecho lo subió de tp=0 a tp=2. `D` no
es una salida usable; para eso existe `D-R`.

**2. Los 2 fp netos de `D-R` sí eran nuevos, y la causa es el reconciliador.**
`ProposalReconciler` fusionaba menciones pero **no propuestas**: su `ClaimKey`
incluye `relation_phrase`, la evidencia y la firma de metadatos, así que dos
propuestas de la MISMA relación con distinta redacción no se tocaban:

- `leyenda-crónica:e01` — det `"dirigió"` LEADS vs sem `"dirigió la Casa del
  Ciervo desde el invierno…"` LEADS.
- `kestrel-informe:e03` — det `"pertenece al"` MEMBER_OF vs sem `"pertenece al
  Consorcio Halcyon desde el traslado"` LOCATED_IN.

Tras reconciliar las menciones, ambas parejas apuntan al MISMO par
sujeto/objeto. La clave de claims del arnés es `(episodio, sujeto, objeto)` —
sin predicado — y empareja 1:1, así que la segunda propuesta de cada pareja es
un falso positivo inevitable. Y no es sólo un artefacto de métrica: la cadena
entregaba **dos tarjetas de revisión para una sola relación**.

## Corrección

Segundo pase en el reconciliador: `CoreferentClaimKey` (episodio + menciones de
sujeto y objeto + `negated` + `abstained`; **sin predicado ni frase**) y fusión
vía el `_merge_claims` que ya existía, que une `predicate_candidates` ordenados
y conserva la procedencia. Tres guardas, cada una defendiendo un invariante ya
probado del pipeline:

1. **Sólo entre familias independientes distintas.** Dos claims del mismo
   extractor no se tocan: ahí no hay nada que arbitrar.
2. **Sólo si TODAS piden revisión.** Una propuesta auto-aprobable lleva
   autoridad propia; fundir un `ACCEPT` local con un `REVIEW` externo rebajaría
   la decisión local porque otro proveedor habló de lo mismo — exactamente al
   revés de como funciona la cadena (`TestE2E02HechoSemantico`, que sigue verde
   sin tocarlo).
3. **`produced_by_step` se toma de la propuesta MÁS externa** del grupo. Con la
   local (que ordena primero) se blanquearía una propuesta externa haciéndola
   pasar por local y el motor dejaría de emitir `EXTERNAL_PROPOSAL`.

El predicado NO entra en la clave a propósito: si dos extractores discrepan, la
salida correcta es UNA propuesta con los dos `predicate_candidates` ordenados —
que es lo que el motor sabe arbitrar (`PREDICATE_AMBIGUOUS`)— y no dos
propuestas que tendría que desempatar sin saber que hablan de lo mismo.

Flag `ReconcilerConfig.merge_coreferent_claims` (por defecto `True`), 4 tests
nuevos en `test_knowledge_v3_reconcile.py`, y los asertos de
`test_knowledge_v3_reconcile_validation.py` reescritos para comprobar **tp y fp
de las cuatro configuraciones**, con `D` asertada tal cual (tp=2/fp=18) para que
la degeneración de la unión cruda quede a la vista en vez de escondida.

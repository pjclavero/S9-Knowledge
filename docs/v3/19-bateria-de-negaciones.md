# 19 — Batería de negaciones (split `negation`)

Fecha: 2026-07-29 · Estado: **gold entregado, sin medir**

Esta es la batería que pide `docs/v3/18-politica-de-aprobacion-de-negaciones.md`
§3, y es la vara con la que se decidirá si puede retirarse el freno universal que
hoy manda toda negación a revisión humana.

- Dataset: `data-engine/app/knowledge_v3/benchmarks/datasets/negation/`
- Generador: `datasets/negation/_authoring/` (`cases.py` contenido, `build_negation.py` offsets/hashes/sobres)
- Test: `data-engine/app/tests/test_knowledge_v3_negation_battery.py`

**Este bloque no mide nada.** No ejecuta el extractor ni el motor contra la
batería, no toca el arnés, no toca los contratos y no conecta el split a ningún
flujo automático. Escribir el gold y medirlo son dos trabajos, y los hacen ojos
distintos: quien escribe conociendo el resultado deja de escribir un gold.

---

## 1. Declaración de independencia

La batería se ha escrito **sin leer la implementación**. En concreto, **NO** se
han abierto en ningún momento:

- `data-engine/app/knowledge_v3/extraction/cues.py`
- `data-engine/app/knowledge_v3/extraction/deterministic.py`
- `data-engine/app/knowledge_v3/extraction/payload.py`
- `data-engine/app/knowledge_v3/extraction/semantic.py`
- `data-engine/app/tests/test_knowledge_v3_semantic*.py`
- `data-engine/app/tests/test_knowledge_v3_extraction*.py`

Ninguna lista léxica del extractor ha entrado aquí: ni `CESSATION_PHRASES`, ni
`SCOPE_VERBS`, ni `NEGATION_CUES`. Los casos salen del español.

Sí se ha leído, y era necesario: `contracts/knowledge-v3/v1/` (esquemas y
validador congelados, contra los que valida todo el gold), `docs/v3/18`
(la especificación que se cumple), `docs/v3/08` (formato del dataset y del
arnés) y la **estructura** de `datasets/dev/` —nombres de fichero, sobres, claves
de los documentos—, nunca su contenido semántico.

Los mundos son nuevos y ajenos a todo lo existente: **basalto, cirro, zafiro,
ámbar**. No se reutiliza ninguno de `dev` (leyenda, mareas, kestrel) ni del
held-out (ferrovia, micelio, liga), ni una sola formulación de ellos. Un test lo
comprueba.

Ocho de los cincuenta casos son de la familia que se acaba de arreglar
(`NEGATED_CESSATION`). Escritos mirando la implementación medirían el propio
código y darían un verde vacío. Es la razón entera de que este bloque exista
aparte.

---

## 2. Composición

60 casos, uno por episodio, en cuatro fuentes y cuatro modalidades.

| Familia | Casos | Decisión esperada |
|---|--:|---|
| Negación simple | 10 | `AUTO_APPROVE` |
| NEVER | 6 | `AUTO_APPROVE` (con horizonte) |
| CESSATION | 10 | `REVIEW_NEGATION_CESSATION` |
| Negación de cesación | 8 | `REVIEW_NEGATION_SCOPE` |
| NOT_YET | 5 | `REVIEW_NEGATION_SCOPE` |
| Alcance en subordinadas | 5 | `REVIEW_NEGATION_SCOPE` |
| Preguntas / condicionales / rumores | 4 | 2 × `REVIEW_NEGATION_SCOPE`, 1 × `REVIEW_NEGATION_CESSATION`, 1 × `ABSTAIN` |
| Doble negación | 2 | `REVIEW_NEGATION_SCOPE` |
| **Subtotal de la tabla de docs/v3/18** | **50** | |
| Controles positivos *(añadido 1)* | 6 | `AUTO_APPROVE` |
| Sin claim en absoluto *(añadido 2)* | 4 | — (no hay decisión) |
| **Total** | **60** | |

Reparto de decisiones sobre los 60: `AUTO_APPROVE` 22 · `REVIEW_NEGATION_SCOPE`
22 · `REVIEW_NEGATION_CESSATION` 11 · `ABSTAIN` 1 · sin decisión 4.

### 2.1 Fuentes

| Fuente | Mundo | Tipo | Modalidad | Casos | Familias |
|---|---|---|---|--:|---|
| `basalto-cronica` | basalto | MARKDOWN | TEXT | 18 | simple, NEVER, negación de cesación, doble negación, control positivo |
| `cirro-actas` | cirro | MARKDOWN | TEXT | 16 | cesación, negación de cesación, alcance, control positivo |
| `zafiro-sesion` | zafiro | AUDIO | SPEAKER_TURN | 15 | simple, NOT_YET, alcance, cesación, control positivo |
| `ambar-escaneo` | ambar | IMAGE | OCR_TEXT | 11 | NEVER, cesación, pregunta/condicional/rumor, sin claim |

Totales del gold: 60 episodios, 188 fragmentos, 131 menciones, 131 resoluciones,
57 claims, 23 afirmaciones, 4 planes (57 decisiones, 23 operaciones), 4 casos
negativos. **600 documentos de contrato**, todos validados con el validador real
`contracts/knowledge-v3/v1/validator.py`.

Se usan los **diez** predicados de la ontología genérica: `MEMBER_OF`,
`HAS_MEMBER`, `LEADS`, `LED_BY`, `LOCATED_IN`, `ALLY_OF`, `RIVAL_OF`,
`SIBLING_OF`, `OWNS`, `OWNED_BY`.

### 2.2 Variedad exigida

- **Voz**: 8 casos en pasiva, el resto en activa.
- **Formas verbales**: presente, indefinido, perfecto compuesto, subjuntivo
  (presente, imperfecto, compuesto, pluscuamperfecto), infinitivo antepuesto,
  perífrasis (`acaba de`, `no ha dejado de`), condicional real, imperativo.
- **Posición de la marca**: antes del foco, después del foco y **entre** los dos
  argumentos.
- **Orden**: sujeto-objeto, objeto-sujeto, verbo-sujeto y relación tematizada al
  principio con la negación al final.
- **Longitud**: desde 37 caracteres (`Brixa Omal es hermana de Kena Drovic.`)
  hasta 288 caracteres, con tres oraciones de trámite antes de la
  relación.
- **Ruido de transcripción**: **7 casos** (≥ 5 exigidos). OCR en 3
  (`rn`↔`m`, `l`↔`1`, `O`↔`0`); ASR en 4 (sin puntuación, sin tildes, `ñ`→`n`,
  confusión fonética `Hute`/`Ute` y `Zonda`/`Sonda`).
- Ningún texto se repite y ninguna tripleta (sujeto, predicado, objeto) se
  repite. Ambas cosas las comprueba el test.

---

## 3. Qué declara cada caso

Cada claim lleva en `metadata.negation` la anotación completa del caso:

```json
{
  "case_id": "NEG-NEGCESS-04",
  "family": "NEGATED_CESSATION",
  "negation_kind": "NEGATED_CESSATION",
  "expected_decision": "REVIEW_NEGATION_SCOPE",
  "expected_negated": false,
  "expected_subject": "entity:basalto:beltran-osk",
  "expected_object": "entity:basalto:conclave-ceniza",
  "expected_predicate": "LEADS",
  "expected_direction": "SUBJECT_TO_OBJECT",
  "anchor_quote": "no dejo de liderar el Conclave de la Ceniza",
  "scope": "AMBIGUOUS",
  "cue_position": "BEFORE_FOCUS",
  "voice": "ACTIVE",
  "verb_form": "INDEFINIDO",
  "transcription_noise": "NONE",
  "reading": "CONTINUITY",
  "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
  "traps": ["..."],
  "rationale": "..."
}
```

Los casos sin claim viven en `negatives.json` con `must_not_produce: "claim"`,
`forbidden_predicates` y su motivo.

### 3.1 Tres convenciones declaradas (y por qué)

**1. El vocabulario de `negation_kind` es de esta batería, no del extractor.**
De `docs/v3/18` viene literalmente `CESSATION`; `SIMPLE`, `NEVER`, `NOT_YET`,
`NEGATED_CESSATION`, `SCOPE_EMBEDDED` y `DOUBLE_NEGATION` son nombres propios de
este gold, precisamente porque no se ha mirado cómo los llama el código. **Lo
vinculante es el par (`expected_negated`, `expected_decision`)**; los nombres son
informativos y quien mida debe mapear su vocabulario sobre esta tabla. Una
discrepancia de nomenclatura no es un fallo del motor.

**2. `negated` es la polaridad del HECHO, no la presencia de una marca.**
Para `CESSATION`, `negated = true` (así lo ejemplifica `docs/v3/18` §1). Para
`NEGATED_CESSATION`, `negated = false`: *"no dejó de liderar"* significa que la
cesación no ocurrió, y la lectura es continuidad. Esta es la decisión de gold más
consecuente de todo el documento: es exactamente el invariante que `docs/v3/18`
§4 pone por encima de todo — *"no dejó de X" nunca puede convertirse en "dejó de
X"*. Un sistema que emita `negated = true` + `CESSATION` en esos ocho casos falla
en los dos ejes a la vez, y así debe contarse.

**3. `REVIEW_NEGATION_CESSATION` y `REVIEW_NEGATION_SCOPE` no son códigos
canónicos del contrato congelado.** Cada decisión del plan lleva por tanto **dos**
razones: la canónica que el validador exige y la de la política.

| Decisión de política | `decision` del contrato | `reason_codes` |
|---|---|---|
| `AUTO_APPROVE` | `ACCEPT` | `LOCAL_APPROVED` |
| `REVIEW_NEGATION_CESSATION` | `REVIEW` | `REVIEW_TEMPORALITY`, `REVIEW_NEGATION_CESSATION` |
| `REVIEW_NEGATION_SCOPE` | `REVIEW` | `REVIEW_PREDICATE`, `REVIEW_NEGATION_SCOPE` |
| `ABSTAIN` | `ABSTAIN` | `AMBIGUOUS_SEMANTICS` |

`REVIEW_NEGATION_SCOPE` funciona además como cubo de todo lo que no es cesación
y no se puede autoaprobar —NOT_YET, alcance en subordinada, doble negación,
rumor— siguiendo el agrupamiento que hace el propio `docs/v3/18` §2 (*"NOT_YET y
alcance ambiguo: revisión o abstención"*).

### 3.2 Criterio de cada decisión

- **`AUTO_APPROVE`** exige las siete condiciones de `docs/v3/18` §2: cita
  anclada literalmente, sujeto y objeto en el texto, predicado de la ontología,
  alcance inequívoco, ni pregunta ni condicional ni rumor ni orden, sin
  contradicción sin resolver y validaciones conformes. Los 22 casos
  `AUTO_APPROVE` las cumplen las siete; los demás fallan al menos una, y el campo
  que dice cuál es `scope` (alcance) o el estatus epistémico del claim.
- **`REVIEW_NEGATION_CESSATION`**: hay una cesación real. Puede cerrar una
  afirmación existente y alterar la lectura temporal del grafo. Siempre revisión
  en esta fase, sin excepción, incluso cuando el alcance es inequívoco.
- **`REVIEW_NEGATION_SCOPE`**: el alcance de la negación no está resuelto, o
  está resuelto pero el enunciado no es asertivo. `forbidden_outcomes` dice qué
  no puede salir de ahí en ningún caso.
- **`ABSTAIN`**: la fuente nombra la relación y declara que no lo sabe.
  Abstenerse es una salida legítima y tiene clave propia para poder emparejarse.

### 3.3 Lo que se escribe y lo que no

Solo los 22 casos `AUTO_APPROVE` producen afirmación (23 en total: uno de ellos
tiene dos claims). Las 23 claves de hecho son distintas —los predicados
simétricos se canonizan antes de comparar— y un test lo comprueba. Los cuatro
planes salen con `approved = false`: este gold no es una aprobación, y además
contiene decisiones `REVIEW`, que por contrato bloquean la aprobación.

Todos los claims salen con `review_required = false`, incluidos los que la
política manda a revisión. Es deliberado y es la tesis del bloque: **el extractor
emite datos, no decisiones** (`docs/v3/18` §1). Si el gold trajera la revisión
puesta en el claim, estaría midiendo la política vieja.

---

## 4. Las trampas deliberadas

### 4.1 Las que más cuestan

| Caso | Trampa | Por qué está |
|---|---|---|
| `NEG-DOUBLE-01` / `NEG-DOUBLE-02` | *"No es falso que P"* (neto **positivo**) frente a *"Nadie puede negar que **no** P"* (tres marcas, neto **negativo**) | Van en pareja a propósito: quien resuelva la doble negación contando marcas módulo dos acierta la primera y falla la segunda. |
| `NEG-NEVER-04` | *"no fueron hermanos **en ningún caso**"* | Concordancia negativa del español: dos marcas **refuerzan**, no cancelan. Es el espejo exacto de la doble negación real. |
| `NEG-NEGCESS-04` | *"dimitió de tres cargos, **pero no dejó de** liderar el Cónclave"* | Una cesación **verdadera** y una **negada** en la misma frase y con el mismo sujeto. Cerrar la relación equivocada es el fallo caro. |
| `NEG-NEGCESS-08` | *"**no ha dejado de** estar dirigida por Ismael Corvo **en ningún momento**"* | Tres elementos negativos, en pasiva y en perfecto compuesto, con lectura neta de **continuidad**. |
| `NEG-NEGCESS-06` | *"**No consta que** haya abandonado la Junta"* | La única negación de cesación cuya lectura **no** es continuidad: es ausencia de registro. Confundirla con "sigue" es inventar evidencia. |
| `NEG-SIMPLE-07` | ASR sin puntuación: *"no brixa omal **no** forma parte del sindicato abisal"* | El primer *"no"* es un marcador de discurso. Contar marcas da dos y la paridad diría "afirmativo". |
| `NEG-SIMPLE-09` | *"Paz no pertenece a la Flota; quien **sí** figura es Tomás"* | Dos relaciones en un episodio, una negada y otra afirmada, **compartiendo objeto**. El alcance tiene que pararse en el punto y coma. |
| `NEG-POS-02` | *"Harun **no** llegó a tiempo, **pero** Sira pertenece a la Orden"* | Negación en una cláusula que no afecta a la relación anotada. Si el alcance se calcula por episodio, esta relación positiva sale negada. |
| `NEG-SIMPLE-04` | *"El Gremio **desmiente** que Mira figure entre sus miembros"* | Negación **léxica**: no aparece la palabra *no*. Un detector de marcas se la pierde entera. |
| `NEG-SIMPLE-03` | *"Nerea Tossa, hermana de Beltrán Osk, **no lo es**"* | La marca va **después** del foco y el predicado aparece en un inciso afirmativo, negado luego por un pronombre átono. |
| `NEG-NEGCESS-07` | *"**Dejar** el Consejo de los Vientos, Vera Luntz **no lo dejó**"* | El infinitivo de cesación abre la frase y la negación la cierra. Una ventana de alcance que mire hacia adelante no encuentra nada. |
| `NEG-COND-01` vs `NEG-NOCLAIM-02` | Condicional **real** (produce claim hipotético) frente a **contrafactual** (no produce nada) | La frontera entre condicional real e irreal decide si hay claim. Los dos casos están, uno al lado del otro. |
| `NEG-NOCLAIM-01` | *"¿Acaso Veli Ardún **no** pertenece a la Cofradía del Lacre?"* | Formalmente idéntico a `NEG-SIMPLE-01` salvo por los signos de interrogación. |
| `NEG-SCOPE-01` vs `NEG-SCOPE-03` | *"A **no cree** que P"* (no niega P) frente a *"A **negó** que P"* (sí niega P, atribuido) | Dos matrices negativas con efectos opuestos sobre la polaridad del hecho. |
| `NEG-CESS-03` / `NEG-CESS-06` / `NEG-CESS-09` | *"fue abandonada por"*, *"salió del patrimonio de"*, *"abandonó"* | Cesaciones **sin ninguna marca de negación**. La cesación no siempre trae un *no* delante. |
| `NEG-NEVER-05` | OCR: *"nunca fue **rniembro** de la Corte"* | El núcleo léxico del predicado llega roto por el OCR, y la cita que ancla es la **degradada**, no la corregida. |

### 4.2 Trampas estructurales

- **Pares mínimos.** `NEG-SIMPLE-02` y `NEG-POS-04` son la misma pasiva
  separada por una sola palabra. `NEG-NOTYET-03` y `NEG-POS-06` comparten objeto
  con distinto sujeto y distinta polaridad.
- **Predicados simétricos.** Once casos usan `SIBLING_OF`, `ALLY_OF` o
  `RIVAL_OF`; en siete de ellos la relación va negada o cesada. Negar o cerrar
  (A,B) tiene que valer también para (B,A).
- **`NEG-SIMPLE-08` tiene un riesgo ortogonal declarado.** Las dos entidades
  llegan degradadas por ASR. El eje que mide el caso es la negación, no la
  identidad: si se revisa por duda de entidad, **eso no cuenta como fallo de la
  política de negación**, y el caso lo dice en `orthogonal_risk`.
- **Horizonte del NEVER, con y sin texto.** `NEG-NEVER-01` y `NEG-NEVER-05`
  declaran el límite temporal en el propio enunciado; `NEG-NEVER-06` no lo
  declara y el límite sale de la procedencia. En las seis afirmaciones NEVER el
  horizonte va en `valid_to` con `state = UNKNOWN`, nunca como una negación
  abierta hacia el futuro.
- **`NEG-NOCLAIM-04` extiende el vocabulario de `kind`** de los casos negativos
  con `IMPERATIVE`. `docs/v3/18` nombra la orden como descalificador de la
  autoaprobación y no tenía caso propio en ningún split. Los otros tres usan los
  tipos ya documentados en `docs/v3/08` §3.6 (`QUESTION`, `COUNTERFACTUAL`,
  `FICTION_WITHIN_FICTION`).
- **Distractores de rol.** *"el escribano"*, *"los cómicos"*, *"el falso
  legado"*, *"cónclave de invierno"* en minúscula, *"del sindicato"* truncado:
  ninguno se anota como mención, siguiendo la política de `docs/v3/08` §2.1.1.

---

## 5. El test

`data-engine/app/tests/test_knowledge_v3_negation_battery.py` — 31 tests. Defiende:

1. La batería carga con el **loader real** (`load_gold("negation")`), con los diez
   ficheros por fuente y doble marca de split.
2. Los 600 documentos validan contra los **contratos congelados**, con el
   validador de verdad.
3. La **distribución por familia cuadra con la tabla** de `docs/v3/18` §3, con la
   cuota escrita a mano en el test: si el dataset cambia el reparto, el que falla
   es el dataset.
4. **No hay claves de hecho duplicadas**, canonizando los predicados simétricos.
5. Cada claim declara sujeto, objeto, predicado, dirección, cita y decisión
   esperada; la decisión del plan coincide con la declarada.
6. Los invariantes de política: ninguna negación de cesación se aprueba ni se lee
   como cesación; todas las cesaciones van a revisión de cesación; los NEVER
   declaran hasta cuándo sabe la fuente; los controles positivos no llevan
   negación; ningún claim pisa un episodio sin claim.
7. **Anclaje literal**: `texto[start:end] == literal_text` en los 188 fragmentos,
   y la cita declarada de cada caso es efectivamente su evidencia.
8. La variedad: los diez predicados, ≥ 5 casos con ruido de transcripción, marca
   antes y después del foco, pasiva, ≥ 8 formas verbales, mundos nuevos, sin
   textos ni tripletas repetidos.
9. Que el gold **se regenera byte a byte** desde `_authoring/`.
10. Que **nada fuera de la batería carga ni mide el split** `negation`.

```bash
export PYTHONPATH=data-engine/app
python -m pytest data-engine/app/tests/test_knowledge_v3_negation_battery.py -q
python -m knowledge_v3.benchmarks.cli validate --split negation
python -m knowledge_v3.benchmarks.datasets.negation._authoring.build_negation --check
```

---

## 6. Límites conocidos

1. **60 casos son pocos.** Sirven para detectar que algo está roto en una
   familia, no para estimar rendimiento. `ABSTAIN` tiene n = 1: solo puede valer
   0.0 o 1.0.
2. **El gold es de autoría propia y sintético.** Los cuatro mundos están
   inventados para esta batería. Rendir aquí no demuestra nada sobre material
   real: es la lección de 0.81 → 0.24 del motor de relaciones v2, y aplica igual.
3. **La anotación de `negated` en la negación de cesación es una decisión de
   gold, no un hecho del idioma.** Está argumentada en §3.1 y es discutible en
   `NEG-NEGCESS-06`, donde la lectura honesta es "no consta". Si el bloque que
   mida discrepa, que lo discuta contra este documento — no que cambie el gold
   después de ver el resultado.
4. **La batería no cubre el *recall* de autoaprobación por sí sola.** Aporta el
   denominador (22 casos que **deberían** aprobarse, 10 de ellos negaciones
   simples), pero medirlo es del bloque siguiente. `docs/v3/18` §4 avisa de por
   qué hace falta: un sistema que autoapruebe 0 de 10 cumple los otros cuatro
   criterios y no sirve para nada.
5. **No hay casos multimodales de verdad.** El escaneo tiene bbox y la sesión
   tiene anclaje temporal, pero no hay diagramas ni tablas: el fenómeno que se
   mide aquí es la negación, y meter inferencia visual habría mezclado dos ejes.

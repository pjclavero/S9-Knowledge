# Informe de validación — Bloque 4: Mejora de temporalidad

**Fecha:** 2026-07-19
**Rama:** `feat/relation-temporality-calibration-v1`
**Clasificador:** `relation-temporality-1.0.0` (`relations.temporality`)
**Corpus:** `relation-benchmark v1` (sintético; 16 fuentes + fixtures)
**Baseline evaluada:** `baseline1` (pipeline offline determinista)
**Gate:** `temporality` (umbral **0.60**)

## 1. Objetivo

El gate `temporality` estaba en **FAIL** con valor **0.28** (7/25 correctos). El
objetivo es que la temporalidad deje de puntuarse por **mera detección** (había o
no un `temporal_scope`) y pase a puntuarse por **clase temporal correcta** frente
al ground truth, subiendo el gate por encima de su umbral sin fabricar cobertura
y **sin** tocar el contrato de datos, las plantillas de prompt ni el corpus.

## 2. Diagnóstico raíz

El fallo tenía dos causas encadenadas, ambas en la **honestidad de la medida** y
en la **pobreza del léxico**:

1. **El matching solo medía detección.** `temporal_correct` en
   `benchmark/matching.py` comprobaba únicamente `temporal_scope is not None`. Un
   `temporal_scope` cualquiera —incluso de clase equivocada— contaba como acierto,
   y omitirlo contaba como fallo. La métrica no distinguía PAST de FUTURE de
   ONGOING: premiaba **etiquetar**, no **clasificar bien**.
2. **El léxico era pobre.** `signals.signal_temporality` reconocía un puñado de
   marcadores y años, pero **ignoraba el tiempo verbal** (pretérito `\w+ó`, futuro
   `\w+rá/rán`), el cese explícito («ya no», «dejó de», «hasta …»), el futuro
   perifrástico/potencial («será», «prometió», «podría», «quizá») y los
   **intervalos** («entre X y Y», «X–Y»). Muchas relaciones con temporalidad clara
   quedaban sin alcance, o con un alcance que no reflejaba su clase real.

El resultado combinado: una métrica laxa sobre una señal pobre, que ni así
alcanzaba el umbral porque la mayoría de scopes emitidos no correspondían a la
clase del GT.

## 3. Diseño

### 3.1 Módulo `temporality.py` (nuevo)

`TEMPORALITY_VERSION = "relation-temporality-1.0.0"`, **independiente** de
`SCHEMA_VERSION`: ampliar los léxicos NO cambia el contrato de datos, solo esta
capa de clasificación. El módulo es **DETERMINISTA y puro** (sin red, disco,
estado mutable ni azar), en la misma línea que `vocabulary.py` del Bloque 3.

### 3.2 Clases alineadas al ground truth

`TEMPORAL_CLASSES = (PAST, PRESENT, FUTURE, ONGOING, ENDED, ATEMPORAL)` es copia
exacta del enum `temporal_status` del ground truth. No se añaden ni renombran
clases: el tuple es **fuente única** para validar prefijos y para el matching.

### 3.3 Léxicos deterministas + morfología

Léxicos en minúsculas y **sin tildes** (se comparan contra el texto también
aplanado, de modo que `podría`/`podria` o `aún`/`aun` casan ambos), con
**frontera de palabra** para evitar falsos positivos por subcadena (p.ej. `era`
dentro de `cualquiera`). Además de léxico, dos reglas **morfológicas**:

- Pretérito 3ª persona: `\b\w+ó\b` → `selló`, `luchó`, `fundó`.
- Futuro simple: `\b\w+(?:rá|rán)\b` → `competirá`, `heredarán`.

Y evidencia temporal transversal: años de 3–4 cifras y **intervalos** explícitos
(`entre X y Y`, `X-Y` / `X–Y`).

### 3.4 Clasificación priorizada

`classify_temporality(text)` aplica una prioridad **documentada y estable**:

```text
ENDED > FUTURE > ONGOING > PAST > PRESENT > ATEMPORAL
```

Refleja que una marca de **cese** (ENDED) o de **futuro/potencial** (FUTURE)
domina sobre la morfología de pretérito (p.ej. `prometió` es FUTURE, no PAST); que
PRESENT es la clase por defecto solo cuando no hay marca fuerte; y que ATEMPORAL
se reserva para textos vacíos o sin verbo/marca. Devuelve un
`TemporalClassification` frozen con la decisión **trazada**: `temporal_class`,
`markers` (literales que dispararon la clase), `dates`, `interval`, `is_ended`,
`is_potential` y `temporality_version`.

### 3.5 `to_scope_string()` y `temporal_status_of()`

- `to_scope_string()` serializa a un **string estable** con la clase al frente:
  `CLASS | markers=a,b | dates=843 | interval=843-870`. El prefijo de clase
  garantiza el round-trip por parseo.
- `temporal_status_of(scope)` deriva la clase de cualquier `temporal_scope`:
  `None` → `None` (sin alcance, **no clasificable**); string canónico → clase del
  prefijo; string libre (LLM) → se reclasifica con `classify_temporality`. Un
  `ATEMPORAL`/sin señal devuelve `None`.

### 3.6 Matching class-aware

`benchmark/matching.py` pasa de detección binaria a **clasificación de clase**:
`temporal_correct` ahora exige `temporal_status_of(pred) == gt.temporal_status`.
Es **más estricto y más honesto**: no se puede «ganar» el gate etiquetando todo,
porque un `None` **nunca** casa con PAST/FUTURE/ONGOING/ENDED y una clase
equivocada tampoco puntúa.

### 3.7 Integración sin tocar el contrato

`signals.signal_temporality` delega en `classify_temporality` y enriquece su
`value` con clase/dates/interval/scope manteniendo `markers`/`years`;
`pipeline._temporal_scope` serializa vía `to_scope_string` (`str | None`, contrato
intacto). `temporal_scope` sigue siendo **string libre** en el contrato
(`Optional[Any]`): la estructura vive en `temporality.py` y se **serializa** a un
string estable. No se tocó `contracts.py`, `SCHEMA_VERSION`, corpus ni schema.

## 4. Resultados: ANTES / DESPUÉS

Benchmark `baseline1` sobre `relation-benchmark v1`, gate `temporality` (medido y
reconfirmado por el Organizador):

| Métrica | ANTES (detección binaria) | DESPUÉS (clasificación de clase) | Δ |
|---|---|---|---|
| Estado del gate | **FAIL** | **PASS** | — |
| Valor (umbral 0.60) | 0.28 | **0.76** | +0.48 |
| Correctos | 7/25 | **19/25** | **+12** |
| Existencia — Precision | 0.8269 | 0.8269 | 0 |
| Existencia — Recall | 0.7963 | 0.7963 | 0 |
| Existencia — F1 | 0.8113 | 0.8113 | 0 |

El gate pasa de **0.28 → 0.76** (12 aciertos nuevos) y las **métricas globales de
existencia no regresan** (P/R/F1 idénticas antes y después): la mejora es de
**clasificación temporal**, no altera qué pares se emparejan.

## 5. Análisis honesto: los 6 casos no cubiertos

De los 25 casos del subgrupo, **6 siguen siendo fallos** — y se dejan como
**fallos honestos**, sin forzarlos:

- **Presente histórico** («funda», «sucede») con GT **PAST**: el texto usa
  presente narrativo para un hecho pasado. El clasificador, correctamente, lee la
  morfología de presente; no hay marca léxica de pasado que lo desmienta.
- **Pretérito sin marca de cese** con GT **ENDED**: un pretérito simple («lideró»,
  «gobernó») sin «ya no» / «hasta …» / «dejó de» se clasifica PAST, no ENDED,
  porque **no hay evidencia explícita de cese**. Distinguir PAST de ENDED sin esa
  marca exigiría inferir el cese, es decir, **fabricarlo**.

Qué los mejoraría, sin gaming: más **morfología / tiempo verbal** (imperfecto vs.
indefinido, perífrasis de cese, aspecto), y un posible **vocabulario temporal v2**
con más cues de cese y de presente histórico. Ninguno de esos cambios se hace aquí
para no inflar el número: los 6 casos se reconocen como límite real de v1.

## 6. Garantías (qué NO se ha tocado)

- **Contrato de datos:** intacto. `SCHEMA_VERSION` no cambia; `temporal_scope`
  sigue siendo string libre (`Optional[Any]`). `TEMPORALITY_VERSION` es una capa
  aparte.
- **Plantillas de prompt y corpus/schema del benchmark:** no se modifican.
- **Áreas compartidas:** no se tocan. La estructura temporal vive en
  `temporality.py` y se serializa a string; nada externo depende de su forma.
- **Alcance del cambio de código (por otros agentes):** `temporality.py` (nuevo),
  `signals.py` (delegación), `pipeline.py` (serialización vía `to_scope_string`) y
  `benchmark/matching.py` (`temporal_correct` class-aware).

## 7. Estado de producción

Intacta. No se tocó VM105, Neo4j, `auth.db`, `jobs.db`, timers ni servicios.
`S9K_ALLOW_REAL_INGEST = off`. `release/rc6-candidate = 15ae1d4` (inmutable).

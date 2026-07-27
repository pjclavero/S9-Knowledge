# Cadena completa: extractor de entidades → motor de relaciones

**Fecha:** 2026-07-27 · **Rama:** `work/rel-v2e-b02-heldout` · **`code_sha`:** `2c58297`
**Motor:** `relation-pipeline-1.0.0` (contrato `internal-1.0.0`, consenso `relation-consensus-1.2.0`)
**Arnés de relaciones:** `data-engine/app/relations/benchmark/` — **importado, NO modificado**
**Extractor:** `review.extractor.extract_from_segments` (heurístico real) — **NO modificado**
**Driver nuevo:** `data-engine/app/tools/chain_benchmark.py`
**Proveedores:** `local=NOT_EXECUTED`, `external=NOT_EXECUTED`, **0 llamadas** · sin red, sin Neo4j, sin ingesta
**Corpus:** B1 (`relation_benchmark`, 16 fuentes / 54 rel.), H1 (`relation_heldout`, 30 / 45),
H2 (`relation_heldout_h2`, 36 / 52) — **sin tocar**, verificación sha256 activada en las tres cargas.

> Este documento existe para responder a una sola pregunta que nunca se había medido:
> **¿qué queda del motor de relaciones cuando deja de recibir entidades perfectas?**
> La respuesta es mala. Se publica tal cual salió. No se ha ajustado nada para mejorarla.

---

## 0. Resumen en cuatro frases

1. **El extractor reproduce lo publicado en `docs/34`** salvo una fuente: agregado heurístico
   F1 ent **0.692** frente a 0.689 (única divergencia: `asr_01`, +1 candidato). `llm` e `hybrid`
   quedan **NO EJECUTADOS** (exigen Ollama real; prohibido).
2. **Con entidades reales la cadena se hunde.** Sobre material real (H2, selector v2), el
   `predicate_correct` pasa de **0.2391 → 0.0526** (política laxa) y a **0.0000** (política
   estricta); el `strict_predicate.f1` pasa de **0.1897 → 0.0085 / 0.0000**.
   De **11 relaciones** correctas con predicado exacto (de 52) se pasa a **1** o a **0**.
3. **La mayor parte de la caída es del extractor, no del motor.** En H2 sólo el **44,2 %** de las
   relaciones del ground truth son siquiera *alcanzables* (política laxa: ambos extremos
   recuperados); con la estricta, el **11,5 %**. Pero el motor **también** empeora sobre entidades
   reales: su acierto de predicado sobre los pares que sí recupera cae de 0.2391 a 0.0526 (×0,22).
4. **El arnés no detecta el desastre.** Con `pair_F1 = 0.0611` en B1 (7 TP contra 168 FP) el
   veredicto que emite es `APTO CON REVISIÓN DE CASOS CONFLICTIVOS`: **no existe ningún gate sobre
   `global_existence`**. Es un hallazgo sobre el arnés, no una propuesta de cambiarlo (queda
   intacto).

---

## 1. Parte 1 — medición NUEVA del extractor

### 1.1 Qué se ejecutó

Arnés y corpus **tal cual están**:

```
python data-engine/app/cli/extractor_benchmark.py \
    --manifest tests/fixtures/benchmark/corpus-manifest.json --mode heuristic \
    --output-dir benchmark-results          # run 20260727-100349 (5 fuentes)
python data-engine/app/cli/benchmark_comparator.py \
    --run-dir benchmark-results/20260727-100349 --ground-truth-dir tests/fixtures/benchmark/
```

`corpus-manifest.json` tiene **5 fuentes** — son exactamente las de `docs/34`. Las **7 fuentes**
viven en `corpus-manifest-v2.json` (el corpus ampliado de `docs/36`); se midió también, aparte
(run `20260727-100534`).

`llm` e `hybrid`: **NO EJECUTADOS**. Ambos modos llaman a Ollama real
(`http://192.168.1.157:11434`, `qwen2.5:7b`). Activar un proveedor real está prohibido en este
encargo. **No hay cifras nuevas de `llm` ni de `hybrid` y no se inventan**: las de `docs/34`
(llm F1 0.718 · hybrid F1 0.728) y `docs/36` (hybrid F1 0.806) siguen siendo las últimas
disponibles y **no se han reverificado**.

### 1.2 Entidades, `heuristic`, 5 fuentes — nuevo vs `docs/34`

| Fuente | P ent (34) | P ent (nuevo) | R ent (34) | R ent (nuevo) | F1 ent (34) | F1 ent (nuevo) | Δ F1 |
|---|--:|--:|--:|--:|--:|--:|--:|
| `source_transcript_clean_01` | 0.650 | **0.6500** | 0.812 | **0.8125** | 0.722 | **0.7222** | 0.000 |
| `source_transcript_session_02` | 0.500 | **0.5000** | 0.615 | **0.6154** | 0.552 | **0.5517** | 0.000 |
| `source_transcript_asr_01` | 0.684 | **0.7000** | 0.867 | **0.8750** | 0.765 | **0.7778** | **+0.013** |
| `source_notes_01` | 0.500 | **0.5000** | 0.636 | **0.6364** | 0.560 | **0.5600** | 0.000 |
| `source_resolution_01` | 0.846 | **0.8462** | 0.846 | **0.8462** | 0.846 | **0.8462** | 0.000 |
| **Agregado (media)** | **0.636** | **0.6390** | **0.755** | **0.7574** | **0.689** | **0.6924** | **+0.003** |

Umbrales (P ≥ 0.85 · R ≥ 0.70 · F1 ≥ 0.75): **heuristic sigue suspendiendo** (P ✗, R ✓, F1 ✗) →
`FAIL`, exactamente igual que en `docs/34`.

### 1.3 Por qué ha cambiado `asr_01` (y sólo `asr_01`)

- El extractor (`review/extractor.py`), las stopwords, el clasificador, el comparador y el ground
  truth de `asr_01` **no se han tocado desde `df4c0e5`** (`git diff df4c0e5 HEAD` sobre esos
  ficheros: vacío). El GT de `asr_01` no se ha modificado nunca desde su creación.
- Los commits que `docs/34` declara haber evaluado (`a2bbb44` del extractor, `13fcab9` del
  comparador, rama `feat/priority-2-extractor-benchmark`) **no existen en la historia de este
  repositorio**: fueron aplastados (*squash*) en `df4c0e5`. Una reproducción bit a bit del run de
  `docs/34` es por tanto **imposible**; lo que se compara es "el código de hoy" contra "una cifra
  publicada cuyo código exacto ya no está".
- La diferencia observable es **un candidato de más**: 20 aprobados hoy contra 19 en `docs/34`
  (TP 14 vs 13; FP 6 en ambos). Los candidatos de hoy incluyen **a la vez** `'Clan Escorpion'`
  (tipo `Faction`, vía la regex de nombres propios) y `'Clan Escorpión'` (tipo `Clan`, vía la
  tabla `_CLANS`).
- **Hipótesis principal, mecánicamente coherente y no verificable aquí:** `state/glossary.db` es
  estado de ejecución *gitignored* y **no existe en este entorno**, así que el extractor corre
  **sin glosario**. Con un glosario que mapee `clan escorpion → Clan Escorpión`, la
  canonicalización de `_extract_entities` haría colisionar el `candidate_id` de ambos candidatos
  (el id se calcula *después* de canonicalizar) y `extract_from_segments` los deduplicaría: 19 en
  vez de 20. No se puede confirmar porque el `glossary.db` de aquel run no es reconstruible.

Cualquiera que sea la causa, **la conclusión de `docs/34` no cambia**: el heurístico suspende los
tres umbrales de entidad, y el desplazamiento es de +0.003 en F1 agregado.

### 1.4 Corpus ampliado de 7 fuentes (`corpus-manifest-v2.json`), `heuristic`

| Fuente | P ent | R ent | F1 ent |
|---|--:|--:|--:|
| `source_manual_01` | 0.8750 | 0.7778 | 0.8235 |
| `source_narrative_01` | 0.9231 | 1.0000 | 0.9600 |
| `source_notes_01` | 0.5000 | 0.6364 | 0.5600 |
| `source_resolution_01` | 0.8462 | 0.8462 | 0.8462 |
| `source_transcript_asr_01` | 0.7000 | 0.8750 | 0.7778 |
| `source_transcript_clean_01` | 0.6500 | 0.8125 | 0.7222 |
| `source_transcript_session_02` | 0.5000 | 0.6154 | 0.5517 |
| **Agregado (media, 7 fuentes)** | **0.7135** | **0.7948** | **0.7488** |

Sigue suspendiendo (P ✗, F1 ✗ por 0.0012). Las dos fuentes añadidas en `docs/36`
(`manual_01`, `narrative_01`) son **las dos más fáciles** del corpus y suben el agregado 0.056
puntos de F1 sin que el extractor haya cambiado ni una línea.

---

## 2. Parte 2 — la medición clave: la cadena completa

### 2.1 Método

`data-engine/app/tools/chain_benchmark.py`. Para cada fuente de cada corpus se ejecutan **tres
condiciones** con el **mismo** motor, el **mismo** corpus, el **mismo** ground truth y las
**mismas** funciones de puntuación (`benchmark.matching` + `benchmark.metrics`, invocadas a
través de `benchmark.report.build_report`, el mismo ensamblador que usa la CLI autoritativa):

| Condición | Entidades de entrada |
|---|---|
| `gt_perfect` | `runner.derive_entities` — **control**; se delega íntegramente en `runner.run_source` |
| `extractor_strict` | salida real del extractor, política de ids **estricta** |
| `extractor_lax` | salida real del extractor, política de ids **laxa** |

**Validación del driver:** las tres columnas de control reproducen **exactamente** las cifras
publicadas en `HELDOUT_BASELINE_H1.md` y `HELDOUT_REAL_H2.md` — B1 v2 `predicate_correct` 0.8140 y
`pair_F1` 0.8113; H1 v2 0.5385 / 0.8478; H2 v2 **0.2391** / 0.7931; TP/FP/FN 43/9/11, 39/8/6,
46/18/6. Si el control no reprodujera, nada de lo que sigue sería comparable.

#### 2.1.1 De candidatos del extractor a entidades del pipeline

El extractor devuelve `review.models.Candidate` con `name`, `entity_type`, `confidence` y
`evidence`. El pipeline necesita `{id, text, type, start, end}`. Cada hueco se rellena así:

1. **Segmentación.** Un segmento por fuente, `segment_id == source_id`, texto completo, igual que
   el arnés. **No** se ejecutan `review.segmenter` ni `review.classifier`: el segmento se
   construye ya clasificado con `should_extract=True`. **Sesgo: favorece al extractor** (no puede
   perder texto por una mala clasificación).
2. **Offsets** (el extractor no los emite): se recuperan localizando el `name` emitido con
   `re.finditer(re.escape(name))`, sensible a mayúsculas, **una mención por ocurrencia**.
   **Sesgo: favorece al extractor** (se le regala la localización exacta de todas sus menciones).
   Si el nombre canonicalizado no aparece literalmente en el texto, la mención **se descarta** y se
   anota (`name_not_found_in_text`); no se inventa posición.
3. **Des-solapamiento.** Un conjunto de menciones con spans solapados no es entrada válida para
   `relations.pairs` (dos "entidades" en la misma posición generan pares espurios de distancia 0),
   y el extractor sí los produce. Regla determinista: se conserva el span **más largo**; a igual
   longitud, el nombre alfabéticamente menor. Los descartes se anotan (`overlapping_span`).
4. **Tipos.** El extractor emite `Character | Location | Faction | Clan`. `Clan` **no** pertenece
   a `relations.contracts.ALLOWED_ENTITY_TYPES` y el pipeline lo rechazaría, así que se mapea
   **`Clan → Faction`** (los clanes del GT están anotados como `Faction`). **Sesgo: favorece al
   extractor** en `types_correct`; sin ese mapeo el segmento entero fallaría.
   El extractor **nunca** produce `Object`, `Event` ni `Concept`: esos tipos del GT son
   inalcanzables por construcción.
5. **Glosario.** `_load_glossary` lee `state/glossary.db`, que no existe aquí → el extractor corre
   **sin glosario**. **Sesgo: en contra del extractor** respecto a una producción con glosario.

#### 2.1.2 La política de emparejamiento de ids — la decisión más delicada

El ground truth referencia entidades por `id` (`ysolde`, `clan-roble`). El extractor **no produce
ids**, sólo cadenas. Sin política de emparejamiento, cero predicciones podrían emparejar nunca y
el resultado sería trivialmente 0 — un número sin información. Se miden **dos** políticas que
**acotan** la verdad:

| Política | Regla | Qué es |
|---|---|---|
| **ESTRICTA** | la mención del extractor recibe el id de una mención del GT **si y sólo si su span coincide exactamente** (`start` y `end` idénticos) | **límite inferior**: exige delimitar la mención con precisión de carácter |
| **LAXA** | recibe el id de la mención del GT con la que **más caracteres solapa** (basta solape > 0); desempate por span más largo e id menor | **límite superior**: cualquier trozo de la mención correcta vale |

En **ambas**, una mención sin correspondencia recibe un id sintético `xx::<slug>` que **jamás**
puede emparejar con el GT: contribuye a falsos positivos, nunca a verdaderos positivos.

**Efecto medido de la política** (véase §2.3): entre estricta y laxa, el `pair_F1` de B1 va de
**0.0611 a 0.5429**, y el de H2 de **0.0333 a 0.1610**. La elección de política mueve la cifra un
orden de magnitud. Por eso se publican las dos y **no se elige una como "la" cifra**.

> **ADVERTENCIA CAPITAL DE HONESTIDAD.** Las dos políticas usan **el ground truth** para asignar
> ids. Eso es un **oráculo de resolución de entidades** que el sistema real no tiene:
> `review/resolver.py` no interviene aquí. Por tanto **incluso la condición estricta sigue siendo
> una cota optimista**: mide la degradación que aporta la **detección** de entidades, con el
> **enlazado regalado**. La cadena completa de producción (detección + resolución + motor) será
> igual o peor que lo que se publica en este documento.

---

### 2.2 Calidad de la DETECCIÓN de entidades sobre los corpus de relaciones

Diagnóstico (no es el arnés de `docs/34`: allí las entidades son nombres, aquí son **menciones con
span**). Denominador de recall = menciones del GT, que son exactamente las que recibe el control.

| Corpus | Menciones GT | Menciones extractor | P (span exacto) | R (span exacto) | F1 exacto | P (solape) | R (solape) | **F1 solape** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| B1 | 93 | 143 | 0.2937 | 0.4516 | 0.3559 | 0.6084 | 0.9355 | **0.7373** |
| H1 | 83 | 123 | 0.4959 | 0.7349 | 0.5922 | 0.6260 | 0.9277 | **0.7476** |
| H2 (real) | 92 | 142 | 0.1972 | 0.3043 | 0.2393 | 0.3592 | 0.5543 | **0.4359** |

Sobre **material real** el extractor **no encuentra ni la mitad de las menciones** que el motor
necesita, ni siquiera admitiendo un solo carácter de solape.

**Cobertura por tipo de entidad del GT** (mención cubierta = algún solape):

| Tipo | B1 | H1 | H2 (real) |
|---|--:|--:|--:|
| `Character` | 35/37 (0.95) | 41/41 (1.00) | 18/25 (**0.72**) |
| `Faction` | 25/25 (1.00) | 23/23 (1.00) | 19/35 (**0.54**) |
| `Location` | 9/9 (1.00) | 5/6 (0.83) | 9/13 (0.69) |
| `Object` | 7/8 (0.88) | 4/7 (0.57) | 2/5 (0.40) |
| `Event` | 8/9 (0.89) | 4/6 (0.67) | 1/5 (**0.20**) |
| `Concept` | 3/5 (0.60) | — | 3/9 (**0.33**) |

**Por qué.** El extractor es una regex de **nombres propios capitalizados** de 2 a 4 tokens
(`_PROPER_NAME_RE`) más una tabla fija de clanes de L5A. El ground truth de relaciones anota
**sintagmas nominales**, no nombres propios. Ejemplo literal de H2 `src-01` (385 caracteres):

```
GT (4 menciones)                                extractor (3 menciones)
  stormlandeses  'los stormlandeses'   Faction    'Ninguna'        Character  (espuria)
  culto-antepas. 'un culto a sus antepasados' Concept  'Stormi'    Character  (correcta)
  stormi         'Stormi'              Character  'Gran Tormenta'  Character  (tipo erróneo)
  union-storml.  'unió a los stormlandeses en un solo pueblo' Event
```

Un `Concept` como *"un culto a sus antepasados"* o un `Event` como *"unió a los stormlandeses en
un solo pueblo"* son **inalcanzables** para una regex de mayúsculas. Dos cifras lo cuantifican:
la longitud media de mención del GT sube de 1.75 palabras en H1 a **2.40 en H2**, y la fracción de
menciones del GT que **no empiezan por mayúscula** —es decir, invisibles para `_PROPER_NAME_RE`—
pasa de **3,6 % en H1** y 18,3 % en B1 a **57,6 % en H2** (53 de 92).

---

### 2.3 LA TABLA DE ABLACIÓN

Carril del dictamen `baseline1`, proveedores off. Corpus completos, todas las fuentes.
`Δ` = condición real − control.

#### Selector de predicado **v2** (el motor de cabecera)

| Corpus | Métrica | **A) Entidades perfectas** | **B) Reales, ids estrictos** | Δ B | **C) Reales, ids laxos** | Δ C |
|---|---|--:|--:|--:|--:|--:|
| **B1** | `pair_F1` (`global_existence.f1`) | **0.8113** | 0.0611 | **−0.7502** | 0.5429 | **−0.2684** |
| | TP / FP / FN | 43 / 9 / 11 | 7 / 168 / 47 | | 38 / 48 / 16 | |
| | `predicate_correct` | **0.8140** | 0.5714 | −0.2426 | 0.3158 | **−0.4982** |
| | `strict_predicate.f1` | **0.6604** | 0.0349 | **−0.6255** | 0.1714 | **−0.4890** |
| | `direction_correct` | 0.9302 | 0.5714 | −0.3588 | 0.4211 | −0.5091 |
| | `types_correct` | 1.0000 | 0.5714 | −0.4286 | 0.2105 | −0.7895 |
| | `temporal_correct` | 0.8837 | 0.8571 | −0.0266 | 0.8684 | −0.0153 |
| | `evidence_correct` | 0.9302 | 1.0000 | +0.0698 | 0.8421 | −0.0881 |
| | `decision_correct` | 0.3488 | 0.1429 | −0.2059 | 0.2895 | −0.0593 |
| **H1** | `pair_F1` | **0.8478** | 0.2710 | **−0.5768** | 0.5231 | **−0.3247** |
| | TP / FP / FN | 39 / 8 / 6 | 21 / 89 / 24 | | 34 / 51 / 11 | |
| | `predicate_correct` | **0.5385** | 0.1905 | **−0.3480** | 0.1176 | **−0.4209** |
| | `strict_predicate.f1` | **0.4565** | 0.0516 | **−0.4049** | 0.0615 | **−0.3950** |
| | `direction_correct` | 0.8974 | 0.2857 | −0.6117 | 0.2353 | −0.6621 |
| | `types_correct` | 1.0000 | 0.3810 | −0.6190 | 0.2647 | −0.7353 |
| | `temporal_correct` | 0.5641 | 0.4762 | −0.0879 | 0.5588 | −0.0053 |
| | `evidence_correct` | 0.8462 | 0.8095 | −0.0367 | 0.8529 | +0.0067 |
| | `decision_correct` | 0.2564 | 0.2857 | +0.0293 | 0.2059 | −0.0505 |
| **H2 (real)** | `pair_F1` | **0.7931** | 0.0333 | **−0.7598** | 0.1610 | **−0.6321** |
| | TP / FP / FN | 46 / 18 / 6 | 4 / 184 / 48 | | 19 / 165 / 33 | |
| | `predicate_correct` | **0.2391** | **0.0000** | **−0.2391** | **0.0526** | **−0.1865** |
| | `strict_predicate.f1` | **0.1897** | **0.0000** | **−0.1897** | **0.0085** | **−0.1812** |
| | `direction_correct` | 0.6957 | 0.2500 | −0.4457 | 0.3684 | −0.3273 |
| | `types_correct` | 1.0000 | 0.2500 | −0.7500 | 0.1053 | −0.8947 |
| | `temporal_correct` | 0.1957 | 0.0000 | −0.1957 | 0.1053 | −0.0904 |
| | `evidence_correct` | 0.7174 | 0.5000 | −0.2174 | 0.6842 | −0.0332 |
| | `decision_correct` | 0.3261 | 0.0000 | −0.3261 | 0.2105 | −0.1156 |

#### Selector de predicado **v1** (base histórica)

| Corpus | Métrica | A) Perfectas | B) Estrictos | C) Laxos |
|---|---|--:|--:|--:|
| B1 | `predicate_correct` | 0.2093 | 0.1429 | 0.1579 |
| B1 | `strict_predicate.f1` | 0.1698 | 0.0087 | 0.0857 |
| H1 | `predicate_correct` | 0.1538 | 0.0952 | 0.0882 |
| H1 | `strict_predicate.f1` | 0.1304 | 0.0258 | 0.0462 |
| H2 | `predicate_correct` | 0.1957 | **0.0000** | **0.0000** |
| H2 | `strict_predicate.f1` | 0.1552 | **0.0000** | **0.0000** |

`pair_F1`, TP/FP/FN y `types_correct` son idénticos entre v1 y v2 (el selector sólo cambia el
predicado y lo que de él depende).

**La cifra final de la cadena completa sobre material real, selector v2:**

| | `predicate_correct` | `strict_predicate.f1` | relaciones con predicado exacto |
|---|--:|--:|--:|
| Entidades perfectas (lo publicado) | 0.2391 | 0.1897 | **11 de 52** |
| Entidades reales, ids **laxos** | **0.0526** | **0.0085** | **1 de 52** |
| Entidades reales, ids **estrictos** | **0.0000** | **0.0000** | **0 de 52** |

---

### 2.4 Reparto de culpa: cuánto es del extractor y cuánto del motor

El "recall exacto de extremo a extremo" (relaciones del GT recuperadas **con el predicado
correcto**, sobre el total del GT) se descompone **exactamente** en tres factores multiplicativos,
verificados numéricamente:

```
recall_exacto = alcanzabilidad × recall_de_pares_entre_alcanzables × predicate_correct
                └── EXTRACTOR ─┘ └──────── MOTOR ────────────────┘  └──── MOTOR ────┘
```

*Alcanzabilidad* = fracción de relaciones del GT cuyos **dos** extremos están entre los ids
asignados a las entidades de entrada. Si un extremo falta, el motor **no puede** emparejar la
relación por construcción: es un fallo imputable **íntegramente** al extractor (y a la política de
ids). Es una cota **superior**: estar presentes no garantiza que el generador de pares los junte.

| Corpus | Condición (v2) | Alcanzabilidad (**extractor**) | Recall de pares entre alcanzables (**motor**) | `predicate_correct` (**motor**) | = `recall_exacto` |
|---|---|--:|--:|--:|--:|
| B1 | perfectas | 1.0000 (54/54) | 0.7963 | 0.8140 | **0.6481** (35/54) |
| B1 | reales, laxos | **0.9259** (50/54) | 0.7600 | 0.3158 | **0.2222** (12/54) |
| B1 | reales, estrictos | **0.2778** (15/54) | 0.4667 | 0.5714 | **0.0741** (4/54) |
| H1 | perfectas | 1.0000 (45/45) | 0.8667 | 0.5385 | **0.4667** (21/45) |
| H1 | reales, laxos | **0.8667** (39/45) | 0.8718 | 0.1176 | **0.0889** (4/45) |
| H1 | reales, estrictos | **0.5556** (25/45) | 0.8400 | 0.1905 | **0.0889** (4/45) |
| **H2** | perfectas | 1.0000 (52/52) | 0.8846 | 0.2391 | **0.2115** (11/52) |
| **H2** | reales, laxos | **0.4423** (23/52) | 0.8261 | 0.0526 | **0.0192** (1/52) |
| **H2** | reales, estrictos | **0.1154** (6/52) | 0.6667 | 0.0000 | **0.0000** (0/52) |

**Lectura sobre material real (H2, v2, política laxa — el escenario más favorable de los reales):**

- **Extractor:** hunde la alcanzabilidad de 1.000 a **0.442**. Factor ×0.442. **Aporta el 55,8 %
  de la pérdida de recall antes de que el motor haga nada.**
- **Motor, etapa de pares:** casi no pierde nada adicional (0.885 → 0.826, factor ×0.93). El
  generador de pares **aguanta bien** con entidades sucias.
- **Motor, etapa de predicado:** cae de 0.2391 a 0.0526, factor **×0.22**. Ésta es una degradación
  **adicional y propia del motor**: sobre los pares que *sí* recupera, con menciones peor
  delimitadas y peor tipadas, acierta el predicado **cuatro veces y media menos**.
- **Producto:** 0.442 × 0.93 × 0.22 ≈ **0.091**. Del ya pobre 0.2115 queda el **9,1 %**.

**Reparto en una frase:** de la pérdida total, el extractor pone el factor mayor
(×0.44, el primero y el más contundente), pero el motor **no es un mero espectador**: multiplica
por otro ×0.22 al degradarse él mismo con entradas reales. **Ninguno de los dos se salva.**
Dos contrafácticos, calculados con la misma descomposición:

- Si se **arreglara sólo el motor** (predicado de vuelta a su 0.2391 con entidades reales):
  0.442 × 0.826 × 0.2391 ≈ **0.087** de recall exacto — 1 relación de cada 11.
- Si se **arreglara sólo el extractor** (alcanzabilidad de vuelta a 1.000):
  1.000 × 0.885 × 0.0526 ≈ **0.047** — 1 de cada 21.

Es decir: **arreglar cualquiera de los dos por separado deja la cadena por debajo del 0.2115 que ya
daba el control**, que a su vez ya era un suspenso. Hace falta atacar los dos.

**Efecto de la precisión (no aparece en el recall).** Con entidades reales, H2 pasa de 18 a **165
falsos positivos** (política laxa) o **184** (estricta) frente a 19 y 4 verdaderos positivos. La
precisión de existencia cae de **0.719 a 0.103 / 0.021**. El extractor emite 142 menciones donde
el GT tiene 92, y cada mención de más multiplica los pares candidatos. **El ruido de salida es el
problema tan grave como la cobertura.**

**`types_correct` merece mención aparte:** 1.0000 → 0.1053 en H2. En el control el tipo lo pone el
propio ground truth (es un 1.0 tautológico, no una medida de nada). Con el extractor real el tipo
es el que sale del heurístico, que sólo sabe producir `Character`/`Location`/`Faction`/`Clan` y
por defecto etiqueta `Character`. **`types_correct = 1.0000` en todas las cifras publicadas hasta
hoy no significaba que el sistema tipara bien: significaba que no se estaba midiendo el tipado.**

---

### 2.5 Lo que el arnés dice (y lo que no ve)

| Corpus | Condición (v2) | Veredicto del arnés | Gates en FAIL |
|---|---|---|---|
| B1 | perfectas | `APTO PARA CONTINUAR EN MODO SOMBRA` | — |
| B1 | reales, estrictos | `APTO CON REVISIÓN DE CASOS CONFLICTIVOS` | `negation`, `rumors` |
| B1 | reales, laxos | `APTO CON REVISIÓN HUMANA TOTAL` | — |
| H1 | perfectas | `APTO CON REVISIÓN DE CASOS CONFLICTIVOS` | `rumors` |
| H1 | reales (ambas) | `APTO CON REVISIÓN HUMANA TOTAL` | `rumors`, `predicate_structural` |
| H2 | perfectas | `APTO CON REVISIÓN HUMANA TOTAL` | `negation`, `temporality`, `predicate_structural` |
| H2 | reales, estrictos | `APTO CON REVISIÓN HUMANA TOTAL` | + `rumors` |
| H2 | reales, laxos | `APTO CON REVISIÓN HUMANA TOTAL` | `negation`, `temporality`, `predicate_structural` |

**El arnés emite `APTO CON REVISIÓN DE CASOS CONFLICTIVOS` para un run de B1 con `pair_F1 = 0.0611`
(7 verdaderos positivos contra 168 falsos).** La causa es estructural: **`evaluate_gates` no tiene
ningún gate sobre `global_existence`**, y las tasas estructurales (`predicate_correct`,
`negation_correct`, …) se calculan **sólo sobre los TP**, cuyo denominador se desploma a 7 — con
tan pocos casos, una tasa alta no significa nada. **Es una observación sobre el arnés, no una
propuesta:** `relations/benchmark/` queda intacto, umbrales incluidos.

**Falsos ACCEPT:** con entidades reales, **0** en los tres corpus y ambas políticas (el único
`REVIEW → ACCEPT` de H2 con entidades perfectas desaparece). No es una buena noticia: el motor
propone tan poco y con tan poca confianza que casi nada llega a `ACCEPT`.

---

## 3. Reproducción

```bash
# Parte 1 (extractor, sólo heuristic; llm/hybrid exigen Ollama y NO se ejecutan)
python data-engine/app/cli/extractor_benchmark.py \
    --manifest tests/fixtures/benchmark/corpus-manifest.json --mode heuristic \
    --output-dir benchmark-results
python data-engine/app/cli/benchmark_comparator.py \
    --run-dir benchmark-results/<run_id> --ground-truth-dir tests/fixtures/benchmark/

# Parte 2 (cadena completa) — desde data-engine/app
python tools/chain_benchmark.py --corpus B1 H1 H2 --selector v1 v2 --mode baseline1 \
    --out /tmp/chain.json
```

El driver es determinista y offline (no acepta modos con proveedor: sólo `runner.MODES`).

---

## 4. Limitaciones y lo NO medido

1. **`llm` e `hybrid` del extractor: NO EJECUTADOS.** Exigen Ollama real. La cadena completa está
   medida **sólo con el extractor heurístico**, que es el peor de los tres en `docs/34`/`docs/36`
   (F1 0.689 frente a 0.806 de `hybrid`). **Con `hybrid` la cadena sería mejor, y no se sabe
   cuánto.** Es la laguna más importante de este trabajo.
2. **Enlazado de entidades regalado.** Las dos políticas de ids usan el ground truth como oráculo
   de resolución. `review/resolver.py` no interviene. **Todas las cifras de las condiciones B y C
   siguen siendo cotas optimistas de la cadena de producción.**
3. **Segmentación y clasificación regaladas.** No se ejecutan `review.segmenter` ni
   `review.classifier`: se fija `should_extract=True` sobre el texto completo. En producción el
   clasificador puede descartar segmentos enteros.
4. **Offsets regalados.** El extractor no los emite; se recuperan por búsqueda literal del nombre.
   Un sistema real tendría que producirlos y podría equivocarse.
5. **Sin glosario** (`state/glossary.db` no existe aquí). Sesgo en contra del extractor.
6. **`Clan → Faction`** es un mapeo introducido por este driver; sin él el pipeline rechazaría el
   segmento. Favorece a `types_correct`.
7. **Sólo el carril `baseline1`.** No se han medido `baseline2`, `full_offline` ni
   `ensemble_offline` en las condiciones reales. `ensemble_offline` es donde H2 rompía la propiedad
   de "0 falsos ACCEPT": **no se sabe qué hace con entidades reales**.
8. **Determinismo no comprobado en las condiciones reales.** `build_report` se invoca con
   `check_determinism=False` (la segunda pasada de `determinism_report` re-ejecuta el arnés con
   `derive_entities`, no con el extractor, así que compararía peras con manzanas). El control sí
   está verificado como determinista en los documentos previos.
9. **Nada de esto se ha medido en producción** (VM105/Neo4j). Sin red, sin ingesta, sin despliegue.
10. **La regla de des-solapamiento (§2.1.1.3) es una decisión del driver.** Descarta menciones
    reales del extractor. Altera el resultado en una magnitud no cuantificada por separado.

---

## 5. Conclusión

**La cifra que fija el verdadero punto de partida de cualquier rediseño no es 0.2391: es
`predicate_correct ∈ [0.0000, 0.0526]` y `strict_predicate.f1 ∈ [0.0000, 0.0085]` sobre material
real** — y aun así con el enlazado de entidades regalado, con la segmentación regalada y con los
offsets regalados.

Sobre 52 relaciones anotadas en material real, la cadena completa extrae **una** con el predicado
correcto, y lo hace enterrada entre **165 falsos positivos**.

El sobreajuste que `HELDOUT_REAL_H2.md` documentó era real, pero **subestimaba el problema**: el
motor no sólo estaba midiéndose contra texto que conocía, sino además con las entidades resueltas
de antemano. Las dos ventajas juntas explican la distancia: `strict_predicate.f1` va de **0.6604**
(B1, entidades perfectas, selector v2) a **0.0085** (material real, entidades reales, política
laxa) — un factor de **78×**.

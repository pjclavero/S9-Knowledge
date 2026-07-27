# 08 — Dataset gold y arnés de medición (V3)

Bloque BENCHMARKS del programa V3. Cubre el dataset gold común (dosier §8) y el
arnés que calcula las métricas por subsistema y extremo a extremo (dosier §13).

Base: contratos **congelados** `v3-internal-v1` (`v3-contracts-frozen-1.0.0`).
Todo el gold valida contra ellos con el validador real
(`contracts/knowledge-v3/v1/validator.py`); no hay ninguna copia local.

- Código: `data-engine/app/knowledge_v3/benchmarks/`
- Dataset: `data-engine/app/knowledge_v3/benchmarks/datasets/dev/`
- Tests: `data-engine/app/tests/test_knowledge_v3_benchmarks_*.py`

Este bloque **no implementa ningún subsistema**, no escribe en Neo4j, no llama a
proveedores y no toca producción.

---

## 1. Qué es este dataset y qué no es

Es el dataset de **DESARROLLO**. Quien implementa puede verlo, y por eso mismo
no sirve para dar por buena ninguna cifra final.

La auditoría de V2 (`docs/v3/00-audit-current-system.md`) documenta el pecado
que hay que no repetir: medir sobre el mismo material sobre el que se ajustó.
En el motor de relaciones v2, `predicate` marcaba 0.81 con dev == test, 0.54
sobre sintético y 0.24 sobre real. La separación no puede ser una promesa: tiene
que ser estructural.

Aquí lo es de tres maneras:

1. **Marca explícita.** Todo fichero del dataset lleva `"split": "dev"` en su
   raíz y todo documento de contrato lleva `metadata.benchmark.split = "dev"`.
   Un test recorre los ficheros y falla si alguno no la lleva.
2. **El arnés no cablea el split.** `load_gold("dev")` y `load_gold("heldout")`
   recorren exactamente el mismo código; el split es un argumento, nunca una
   constante. Un test comprueba que pedir un split inexistente falla en vez de
   caer silenciosamente en `dev`.
3. **Medir un split contra otro es un error duro.** Si el bundle de predicciones
   declara un split distinto del gold cargado, `run()` lanza. No hay modo
   permisivo.

El held-out **no lo prepara este bloque** (dosier §9): lo prepara un equipo
independiente, con doble pase, y Fable lo custodia. Ver §7 de este documento.

---

## 2. Composición del dataset `dev`

Seis fuentes, tres mundos, seis modalidades. Los mundos son deliberadamente
lejanos entre sí para que acertar no se pueda confundir con memorizar un
vocabulario: corte medieval, archipiélago gremial y estaciones orbitales.

| Fuente | Mundo | Tipo | Modalidades | Ep. | Frag. | Menc. | Resol. | Claims | Afirm. | Dec. | Ops. | Negativos |
|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `leyenda-cronica` | leyenda | MARKDOWN | TEXT | 3 | 16 | 12 | 6 | 4 | 4 | 4 | 5 | 2 |
| `mareas-cuaderno` | mareas | MARKDOWN | TEXT | 3 | 13 | 10 | 6 | 3 | 3 | 3 | 3 | 1 |
| `kestrel-informe` | kestrel | MARKDOWN | TEXT | 3 | 14 | 9 | 5 | 5 | 4 | 5 | 3 | 1 |
| `kestrel-tripulacion` | kestrel | TABLE | TABLE | 1 | 9 | 6 | 5 | 3 | 2 | 3 | 3 | 0 |
| `mareas-sesion` | mareas | AUDIO | SPEAKER_TURN | 3 | 11 | 8 | 5 | 3 | 3 | 3 | 3 | 0 |
| `leyenda-escaneo` | leyenda | IMAGE | OCR_TEXT, DIAGRAM | 3 | 9 | 6 | 4 | 3 | 0 | 3 | 1 | 0 |
| **Total** | 3 mundos | 6 fuentes | 6 modalidades | **16** | **72** | **51** | **31** | **21** | **16** | **21** | **18** | **4** |

Más: **20 entidades** de catálogo (18 canónicas + 1 creada por la tabla + 1
provisional), **2 perfiles de juego** y **6 planes de mutación** (3 aprobados,
3 bloqueados). En total **220 documentos** de los nueve contratos V3.

`leyenda-escaneo` no aporta afirmaciones propias a propósito: lo que dice ya lo
dice la crónica, así que su plan lleva una operación **idempotente** (`NO_OP`)
sobre la afirmación existente. Es el segundo caso de hecho repetido entre
fuentes, junto con la fila de Vania en la tabla.

De los 21 claims, **20 son gold del extractor**; uno está marcado
`ENGINE_ONLY` (ver §3.7).

### 2.1 Las trampas, fuente a fuente

| Trampa | Dónde | Qué mide |
|---|---|---|
| Sucesión en un cargo con supersesión | `leyenda-cronica` e01 | temporalidad + ledger |
| Negación explícita + correferencia nominal ("El magistrado") | `leyenda-cronica` e02 | negación, coref |
| Rumor de pacto entre dos casas (predicado simétrico) | `leyenda-cronica` e03 | epistemicidad, simetría |
| Ficción dentro de ficción (los titiriteros) | `leyenda-cronica` e03 | **caso negativo** |
| Pregunta directa sobre una relación | `leyenda-cronica` e03 | **caso negativo** |
| Rivalidad simétrica entre gremios | `mareas-cuaderno` e01 | simetría |
| Pronombre locativo ("allí") + contención espacial | `mareas-cuaderno` e02 | coref, transitividad |
| Condicional contrafactual | `mareas-cuaderno` e03 | **caso negativo** |
| Nombramiento planeado (HYPOTHETICAL / state PLANNED) | `mareas-cuaderno` e03 | epistemicidad, temporalidad |
| Registro que NIEGA una pertenencia | `kestrel-informe` e02 | negación, conflicto |
| Serial de ficción emitido dentro del mundo | `kestrel-informe` e03 | **caso negativo** |
| Rumor sobre propiedad (predicado inverso `OWNED_BY`) | `kestrel-informe` e03 | epistemicidad, inversos |
| Propuesta que viola el dominio del predicado | `kestrel-informe` e03 | `REJECT_INVALID` |
| Tabla que CONTRADICE al informe | `kestrel-tripulacion` | CONFLICTED |
| Fila que repite un hecho ya conocido | `kestrel-tripulacion` | idempotencia (`NO_OP`) |
| Tripulante que el grafo no conoce | `kestrel-tripulacion` | `CREATE_NEW` |
| "Yo" de dos hablantes distintos | `mareas-sesion` e01/e03 | correferencia de hablante |
| Parentesco simétrico dicho en primera persona | `mareas-sesion` e02 | simetría + coref |
| Rumor de estibadores desmentido por el propio hablante | `mareas-sesion` e03 | epistemicidad |
| OCR degradado de un nombre conocido ("Daiki Oliaru", "Casa de1 Ciervo") | `leyenda-escaneo` e01 | resolución difusa |
| OCR degradado de un nombre NO conocido ("V4ndreth") | `leyenda-escaneo` e02 | `CREATE_PROVISIONAL` |
| Fragmento ilegible | `leyenda-escaneo` e02 | abstención |
| Plano del que solo cabe inferir | `leyenda-escaneo` e03 | `VISUAL_INFERRED` → revisión |
| El mismo cargo contado por segunda fuente con fecha más gruesa | `leyenda-escaneo` e01 | idempotencia (`NO_OP`) |
| "Umbra" ciudad frente a "Consejo de Umbra" facción | `leyenda-cronica` e02 | sede vs organización |

Fenómenos indexados en el manifiesto: `ABSTENTION`, `CONFLICT`, `COREFERENCE`,
`COUNTERFACTUAL`, `DUPLICATE_ACROSS_SOURCES`, `FICTION_WITHIN_FICTION`,
`HYPOTHETICAL`, `NEGATION`, `NEW_ENTITY`, `OCR_NOISE`, `ONTOLOGY_VIOLATION`,
`PROVISIONAL_ENTITY`, `QUESTION`, `RUMOR`, `SPEAKER_COREFERENCE`,
`SEAT_VS_ORGANIZATION`, `SUPERSESSION`, `SYMMETRIC`, `TABLE`, `TEMPORALITY`,
`TRANSITIVE`, `VISUAL_INFERRED`.

### 2.1.1 Qué se anota como mención y qué no

Se anota toda expresión que designa una entidad **identificable del catálogo**:
nombre propio, nominal definido correferente ("El magistrado" → Daiki) y
pronombre correferente ("allí" → Amarra Vieja, "Yo" → el hablante del turno).

**No** se anotan los sustantivos de rol sin referente resoluble: "el senescal",
"El escriba", "El maestre de puerto", "los titiriteros", "los estibadores", "el
guionista", "jefa de operaciones". Exigirlos mediría otra tarea —detección de
menciones genéricas— que el pipeline V3 no hace, y anotarlos sin entidad
obligaría al resolutor a inventarse identidades. La política tiene dos tests:
uno comprueba que esas superficies no están anotadas, y otro que todo pronombre
o nominal que **sí** se anota queda resuelto a una entidad.

Caso resuelto a raíz de la revisión: "emisarios llegados de Umbra" en
`leyenda-cronica` e02. Ahí *Umbra* es la **ciudad**, no el Consejo, así que se
anota como mención propia y se resuelve a `entity:leyenda:umbra`, una entidad
`Location` distinta de la facción `entity:leyenda:consejo-umbra`. Dejarla sin
anotar convertía en "acierto" que un extractor la ignorase y en "falso positivo"
que la detectara bien.

### 2.2 Rumor / hipótesis frente a caso negativo

Son dos cosas distintas y el dataset las separa a propósito:

- Un **rumor o una hipótesis SÍ producen claim**, con
  `epistemic_status_hint = RUMORED / HYPOTHETICAL`. Lo que no pueden producir es
  un hecho afirmado sin marca: la afirmación resultante nace `PROVISIONAL` y con
  su estatus epistémico puesto. Registrar un rumor como rumor es correcto;
  borrarlo es perder información.
- Un **caso negativo NO debe producir claim ninguno**: ficción dentro de la
  ficción, pregunta y condicional contrafactual. Las menciones sí existen (las
  entidades se nombran); la relación, no.

Un claim predicho que se ancle sobre el tramo de un caso negativo cuenta como
**candidato falso**. Un test comprueba que ningún claim del propio gold pisa
ninguna trampa: si el gold cayera en su propia trampa, la métrica no mediría
nada.

### 2.3 Estructura en disco

```
datasets/dev/
  manifest.json                      # composición, totales, índice de fenómenos, hashes
  catalog/entities.json              # catálogo gold de entidades (schema propio)
  catalog/game_profile_generic.json  # perfil correcto
  catalog/game_profile_narrow.json   # perfil incompleto (ablación "perfil incorrecto")
  sources/<source_id>/
    source_asset.json  episodes.json  fragments.json  mentions.json
    resolutions.json   claims.json    assertions.json plans.json
    negatives.json     reference_text.json
```

Cada fichero es un sobre `{benchmark_file, split, dataset_version,
format_version, source_id, world, documents[]}`. `documents` contiene documentos
de contrato tal cual, salvo en `negatives.json` y `reference_text.json`, que
llevan anotación propia del benchmark (§3.6).

Los ficheros están versionados pero se **generan** desde
`benchmarks/authoring/`: el contenido (textos y anotación) está escrito a mano;
los offsets, hashes y sobres se calculan. Un offset escrito a mano se equivoca;
uno calculado sobre el texto literal, no.

```bash
python -m knowledge_v3.benchmarks.authoring.build            # regenerar
python -m knowledge_v3.benchmarks.authoring.build --check    # ¿ha derivado?
```

Un test comprueba que regenerar produce **exactamente los mismos bytes**, igual
que hacen los ejemplos de contratos.

### 2.4 Anclaje de la tabla

Una tabla no tiene prosa, y aplanarla a texto pierde justo lo que la hace tabla.
Para poder anclar evidencia sobre ella hace falta **un** render acordado, y este
es el del dataset:

> **Render canónico TSV**: la cabecera primero, luego las filas; celdas
> separadas por `\t`, filas por `\n`, celdas nulas como cadena vacía.

Los offsets de fragmentos y menciones de un episodio `TABLE` son offsets sobre
ese render. El episodio conserva `table` estructurado y `text = null`.

---

## 3. El arnés

```
benchmarks/
  loader.py       # carga y valida un split; PredictionBundle
  matching.py     # emparejamiento predicción-vs-gold
  metrics.py      # aritmética (P/R/F1, CER/WER, alineamiento de clusters)
  ablations.py    # configuraciones etiquetadas
  harness.py      # puntuación por subsistema
  report.py       # JSON estable + tabla markdown
  cli.py          # línea de comandos
```

### 3.1 Dos reglas que atraviesan todo

1. **Denominador cero no es cero.** Si no hay población que medir, la métrica
   vale `null` y el informe dice por qué (`n/d` en markdown). Publicar `0.0`
   cuando no había nada que medir miente en la dirección más fácil de creer.
2. **Todo número sale de un conteo.** No hay constantes, ni valores por defecto
   "razonables", ni suavizado, ni estimaciones. Latencia, RAM, llamadas y coste
   los mide quien ejecuta y el arnés los copia tal cual; si no vienen, la
   sección sale `not_evaluated`.

Un subsistema que no entrega nada no puntúa: su sección sale con
`status: not_evaluated` y el motivo.

**3. Ninguna métrica de población emparejada se publica sola.** Toda métrica
calculada sobre lo que emparejó viaja en la tabla junto a su **cobertura** y a
su **variante estricta** (denominador = gold entero). Un motor que decide sobre
1 de 21 y acierta esa una publica `predicate F1 = 1.0` sobre lo emparejado — y
es cierto —, pero leído solo eso parece que resolvió el problema. Es la forma
exacta del 0.81 de V2. La tabla enseña `decision_coverage = 0.0476`,
`decisions_matched = 1`, `decisions_gold = 21` y `predicate_strict.f1`, y la
regla está escrita en `SUMMARY_ROWS`.

### 3.2 Emparejamiento (`matching.py`)

Aquí es donde se hacen las trampas sin querer. Un emparejamiento laxo sube
todas las métricas a la vez sin que nadie toque el modelo.

| Regla | Por qué |
|---|---|
| **Uno a uno** | Una predicción empareja con como mucho un gold y al revés. Sin esto, repetir cien veces el mismo acierto subiría el recall sin coste. |
| **Determinismo total** | Candidatos y desempates se ordenan siempre por la misma clave; el resultado no depende del orden de entrada. |
| **Span exacto por defecto** | `span_mode="exact"` exige mismo episodio y mismos offsets. `overlap` (IoU con umbral) es un modo **explícito**, nunca el defecto, y queda registrado en el informe. |
| **El umbral de solape tiene suelo** | `MIN_OVERLAP_THRESHOLD = 0.5`, no configurable, ni en librería ni en CLI. Por debajo de la mitad se emparejarían spans que comparten menos texto del que no comparten: eso ya no es tolerancia de anclaje, es regalar aciertos. |
| **Voraz, nunca óptimo** | El modo `overlap` y el alineamiento de clusters son voraces. Voraz nunca supera al óptimo: como mucho **subestima**. Una métrica de benchmark debe equivocarse hacia abajo. |
| **Lo no evaluable cuenta como fallo** | Un claim cuya mención no alineó no se descarta: se cuenta. Descartarlo inflaría la precisión. |
| **La clave del claim NO lleva predicado** | Decidir el predicado es trabajo del motor. Meterlo en la clave del extractor mezclaría dos medidas. Se puede activar (`claim_key_extra`) y queda registrado. |
| **Simétricos canonizan extremos** | En un predicado declarado simétrico en el perfil, (A,B) y (B,A) son el mismo hecho. En uno asimétrico invertirlos es un error, y así se cuenta. |
| **La negación siempre está en la clave del hecho** | "X pertenece a Y" y "X no pertenece a Y" no son el mismo hecho. |
| **Los ids del catálogo quedan fijados** | En el alineamiento de identidad, un cluster que selecciona una entidad real del catálogo se mapea a sí mismo. Si no, enlazar a la entidad equivocada se "autocorregiría" al renombrar clusters. |

Claves canónicas:

- **mención / fragmento**: `(episode_id, start, end)` en modo exacto; IoU ≥ umbral en modo overlap.
- **claim**: `(episode_id, {menciones sujeto gold}, {menciones objeto gold})`, más lo que pida `claim_key_extra`. Un claim abstenido (sin sujeto ni objeto) tiene clave `(episode_id, (), (), "ABSTAINED")`: abstenerse es una salida legítima y tiene que poder emparejarse.
- **episodio**: `(source_asset_id, sequence)`.
- **decisión del motor**: `claim_id`. Los claims son la ENTRADA del motor, así que alinear por su identificador es legítimo y no regala nada.
- **hecho**: `(sujeto, predicado, objeto, dirección, negado)`, con extremos canonizados si el predicado es simétrico y `direction = UNDIRECTED` forzada en ese caso. Con `fact_key_includes_validity` se añade `(valid_from, valid_to)`.

### 3.3 Métricas implementadas (§13)

**Normalizador**

| Métrica | Definición |
|---|---|
| `episode_detection` P/R/F1 | episodios emparejados por `(asset, sequence)` |
| `episode_char_recall` | caracteres de referencia para los que se emitió **algún** episodio / caracteres de referencia totales. **No mira el contenido**: dice si el normalizador llegó ahí, no si acertó |
| `char_coverage` | caracteres de referencia realmente recuperados (`len(ref) − ediciones`, con suelo en 0) / caracteres de referencia totales. Un episodio detectado con el texto vacío o entero equivocado aporta **0** |
| `cer` / `wer` | Levenshtein micro-agregado (ediciones totales / longitud de referencia total) sobre caracteres y sobre palabras |
| `truncation_rate` | episodios cuyo texto predicho mide < 95 % de la referencia |
| `repetition_rate` | episodios con un bloque de 24 caracteres repetido ≥ 3 veces (bucle de ASR/LLM) |
| `page_recall` | páginas gold recuperadas |
| `bbox_completeness` | episodios que exigen bbox y lo traen |
| `timecode_completeness` | episodios que exigen anclaje temporal y lo traen |

La referencia de cada episodio está en `reference_text.json`. Para las fuentes
OCR es la **transcripción corregida a mano**: devolver el OCR crudo tal cual no
es normalizar, y el arnés lo cobra (CER ≈ 0.0046 con el gold como predicción).

**Extractor**

| Métrica | Definición |
|---|---|
| `mentions` P/R/F1 | emparejamiento de spans |
| `type_accuracy_matched` | tipo top-1 correcto sobre las menciones emparejadas |
| `type_accuracy_strict` | ídem, pero con TODAS las menciones gold en el denominador: no detectar también es no tipar |
| `coreference` P/R/F1 | pares positivos (estilo pairwise/BLANC) del cierre transitivo de `coreference_candidates`, restringido a menciones alineadas; los pares descartados se reportan en `pairs_dropped_unaligned` |
| `claims` P/R/F1 | emparejamiento por clave de claim |
| `claims_unevaluable` | claims predichos sin clave (mención no alineada) |
| `false_candidates.traps_hit` / `traps_total` / `trap_hit_rate` | **cifra de cabecera, no diluible**: cuántas de las trampas del split se han pisado. El denominador lo fija el dataset |
| `false_candidates.false_candidate_rate` | claims que pisan una trampa / claims emitidos. **Diluible a propósito y con aviso**: emitir más claims correctos la baja sin haber mejorado nada en las trampas. Por eso no encabeza |
| `false_candidates.unanchored_claims_in_trap_episodes` | claims en un episodio con trampa cuya evidencia y menciones no vienen declaradas en el bundle. No pasan por limpios: son **no evaluables** y salen a la tabla |

La correferencia se mide sobre `coreference_candidates` (anotación del
extractor) y **no** sobre las resoluciones: a qué entidad del catálogo
corresponde el referente lo mide el resolutor. Mezclarlas haría que un fallo de
identidad contaminara la nota de correferencia y al revés.

**Resolutor**

| Métrica | Definición |
|---|---|
| `identity_accuracy` | menciones cuya entidad predicha mapea a la entidad gold, con alineamiento uno a uno e ids de catálogo fijados |
| `duplicate_rate` | clusters predichos de más por entidad gold cubierta (el grafo llenándose de copias del mismo personaje) |
| `over_merge_rate` | clusters predichos que mezclan entidades gold distintas |
| `resolution_coverage` | grupos gold cubiertos por alguna resolución predicha. **Va en la tabla** |
| `action_accuracy` / `action_accuracy_strict` | acción correcta (`LINK_EXISTING` / `CREATE_NEW` / `CREATE_PROVISIONAL` / `SPLIT` / `REVIEW`) sobre los grupos emparejados y sobre el gold entero |

**Motor**

| Métrica | Definición |
|---|---|
| `decision_coverage` | decisiones gold cubiertas por alguna predicción. **Va en la tabla** |
| `decision_accuracy` / `decision_accuracy_strict` | decisión idéntica a la gold, sobre lo emparejado y sobre el gold entero |
| `predicate`, `direction`, `epistemic` P/R/F1 | por eje; predicción no nula = positivo; un valor equivocado cuenta a la vez como FP y FN |
| `predicate_strict`, `direction_strict`, `epistemic_strict`, `negation_strict` | ídem con el gold entero en el denominador: las decisiones gold sin cubrir suman FN y las predichas sin gold suman FP |
| `negation` P/R/F1 | detección binaria de la negación |
| `temporal` | tupla `(valid_from, valid_to, event_time, state)` exacta sobre afirmaciones emparejadas, más exactitud por campo |
| `temporal.supersession_recall` | supersesiones reconocidas **por clave de hecho**, nunca por identificador: se busca la afirmación predicha con la misma clave que la gold superada y se comprueba que su sucesora tiene la clave de la sucesora gold. Exigir el `assertion_id` literal haría que un sistema real perfecto, que nombra sus propias afirmaciones, sacara 0.0. En `dev` es **binaria (n = 1)** |
| `false_approve_rate` | de todo lo aprobado, cuánto no debía aprobarse (gold no ACCEPT **o** tupla distinta) / total aprobado |
| `false_reject_rate` | gold ACCEPT marcado `REJECT_INVALID` / total gold ACCEPT |
| `abstention_rate` / `abstention_agreement` | cuánto se abstiene y cuánto acierta al hacerlo |
| `review_rate` / `review_agreement` | ídem para revisión |
| `evidence_validity` | decisiones cuya evidencia existe de verdad en el dataset |

El eje temporal se mide sobre **afirmaciones**, no sobre decisiones: las
decisiones no llevan vigencia. Sin afirmaciones predichas, la sección temporal
sale `not_evaluated` en vez de un cero.

**Extremo a extremo**

| Métrica | Definición |
|---|---|
| `facts` P/R/F1 | conjuntos de claves de hecho deduplicadas |
| `duplicate_fact_rate` | afirmaciones predichas que repiten una clave ya presente |
| `provenance_completeness` | afirmaciones con evidencia y episodios no vacíos y **todos** existentes en el dataset |
| `dangling_provenance` | afirmaciones con alguna referencia inventada |
| `false_approved_plan_rate` | planes aprobados con al menos una decisión ACCEPT sin respaldo gold |

Latencia, RAM, llamadas y coste externo van en `resources` y son
`reported_by_runner`: el arnés no los estima.

### 3.4 Prueba de cordura

`PredictionBundle.from_gold(gold)` presenta el gold como si fuera una predicción
perfecta. Un test exige **1.0 en todas las métricas de identidad** y cero en
todas las de error. Si medir el gold contra sí mismo no da 1.0, el arnés está
roto y ningún otro número suyo vale nada.

Dos excepciones documentadas y con test propio:

- `cer`/`wer` no son 0 porque el texto gold de las fuentes OCR **es** el OCR
  degradado. Un test aparte comprueba que un normalizador perfecto (el que
  devuelve la referencia corregida) sí da `cer = wer = truncation = 0`.
- `abstention_rate` es 1/21 porque el gold tiene una abstención de verdad.

### 3.5 Ablaciones (§8)

Trece configuraciones etiquetadas, validadas al construirse:
`nominal`, `gold_identity`, `gold_entities_to_engine`, `real_entities_to_engine`,
`gold_claims_to_engine`, `local_only`, `external_only`, `local_plus_external`,
`no_ollama`, `with_glossary`, `without_glossary`, `generic_profile`,
`wrong_profile`.

Una ablación cambia la ENTRADA del subsistema, no la forma de medirlo: el mismo
arnés puntúa todas y la etiqueta viaja siempre al informe. Una etiqueta
desconocida **falla**; una etiqueta libre en el informe es una etiqueta que nadie
podrá comparar después.

`wrong_profile` apunta a `bench-narrow`, un perfil real del dataset que se queda
con 4 de los 10 predicados: le faltan `LEADS`, `LED_BY`, `RIVAL_OF`,
`SIBLING_OF`, `OWNS` y `OWNED_BY`. Sirve para medir si el motor se
abstiene o se inventa el predicado más parecido.

Las ejecuciones reales de las ablaciones llegan en integración; aquí queda el
mecanismo, las etiquetas y el perfil incompleto.

### 3.6 Schemas propios del benchmark

No son contratos V3 porque los contratos describen lo que el pipeline
**produce**, y esto es material de referencia.

**Catálogo de entidades** (`catalog/entities.json`):
`{entity_id, world, name, type, aliases[], note, expected_action?, provisional?}`.

**Caso negativo** (`negatives.json`):
`{negative_id, split, episode_id, start, end, literal_text, kind,
must_not_produce, forbidden_predicates[], rationale}` con
`kind ∈ {FICTION_WITHIN_FICTION, QUESTION, COUNTERFACTUAL}`.

**Texto de referencia** (`reference_text.json`): `{episode_id, text}`.

**Anotación en `metadata`** de los documentos de contrato (el bloque abierto):
`metadata.benchmark = {split, dataset_version, world, source_id}`,
`metadata.phenomena[]`, `metadata.mention_kind`, `metadata.gold_key`,
`metadata.role`.

### 3.7 `ENGINE_ONLY`: dos poblaciones que no son la misma

`metadata.role` distingue:

- `EXTRACTOR_AND_ENGINE` (por defecto): claim que un buen extractor **debe**
  proponer, y que además entra al motor.
- `ENGINE_ONLY`: propuesta plausible pero incorrecta — en `dev`, una que viola
  el dominio del predicado. **No** cuenta en la cobertura del extractor
  (exigírsela sería pedirle que se equivoque), pero **sí** es entrada del motor:
  sin ella no hay forma de medir `false_reject_rate`.

---

## 4. Uso

```bash
cd /ruta/al/repo
export PYTHONPATH=data-engine/app

python -m knowledge_v3.benchmarks.cli splits
python -m knowledge_v3.benchmarks.cli describe --split dev
python -m knowledge_v3.benchmarks.cli validate --split dev
python -m knowledge_v3.benchmarks.cli ablations

# prueba de cordura del propio arnés
python -m knowledge_v3.benchmarks.cli score --split dev --predictions gold --format md

# medir una salida real
python -m knowledge_v3.benchmarks.cli score --split dev \
    --predictions salida_extractor.json --ablation local_only \
    --format json --out informe.json
```

Formato del fichero de predicciones (todos los campos opcionales; lo que no
venga, no se puntúa):

```json
{
  "split": "dev",
  "ablation": "local_only",
  "subsystem": "extractor",
  "run_id": "2026-07-27-01",
  "episodes": [], "fragments": [], "mentions": [], "resolutions": [],
  "claims": [], "decisions": [], "assertions": [], "plans": [],
  "metadata": {"latency_ms": 0, "peak_rss_mb": 0, "provider_calls": 0, "external_cost_usd": 0}
}
```

Como librería:

```python
from knowledge_v3.benchmarks.loader import load_gold, PredictionBundle
from knowledge_v3.benchmarks.harness import run
from knowledge_v3.benchmarks.report import to_json, to_markdown

gold = load_gold("dev", validate=True)
report = run(gold, PredictionBundle.from_path("salida.json"))
print(to_markdown(report))
```

El JSON es la fuente de verdad (comparable byte a byte entre corridas); el
markdown es para leerlo. No hay ningún número en la tabla que no esté en el JSON.

---

## 5. Tests

| Fichero | Tests | Qué defiende |
|---|--:|---|
| `test_knowledge_v3_benchmarks_dataset.py` | 60 | los 220 documentos validan contra los contratos congelados; marca de split; regeneración byte a byte; referencias cruzadas; offsets reales; cobertura de los 22 fenómenos; el gold no pisa sus propias trampas; política de sustantivos de rol; sin claves de hecho duplicadas |
| `test_knowledge_v3_benchmarks_matching.py` | 31 | uno a uno, determinismo, span exacto, suelo del umbral, claves canónicas, simetría |
| `test_knowledge_v3_benchmarks_metrics.py` | 21 | P/R/F1, CER/WER y alineamiento de clusters con resultados calculados a mano |
| `test_knowledge_v3_benchmarks_harness.py` | 64 | prueba de cordura, una degradación controlada por métrica, superficie del informe, ablaciones y CLI |
| **Total** | **176** | |

### 5.1 Tests de mutación

Un test verde solo cuenta si la mutación correspondiente lo pone rojo. Los tests
marcados `test_mutacion_*` construyen la versión laxa de la regla y **exigen que
apruebe lo que la estricta suspende**: si esa aserción dejara de cumplirse, el
test estricto correspondiente habría dejado de demostrar nada.

| Mutación | Test |
|---|---|
| Span desplazado contado como acierto | `test_mutacion_un_span_desplazado_no_es_un_acierto` |
| Predicción repetida subiendo el recall | `test_mutacion_repetir_la_misma_prediccion_no_sube_el_recall` |
| Muchos a uno en modo overlap | `test_mutacion_uno_a_uno_tambien_en_modo_laxo` |
| Declarar simétrico lo asimétrico (borra el eje de dirección) | `test_mutacion_declarar_simetrico_lo_asimetrico_borra_el_error_de_direccion` |
| No fijar los ids de catálogo (dos errores → dos aciertos) | `test_mutacion_sin_fijar_los_ids_un_enlace_equivocado_se_autocorrige` |

### 5.2 Casos adversarios de la revisión independiente

| Ataque | Test |
|---|---|
| Motor que decide 1 de 21 y publica F1=1.0 sin cobertura visible | `test_h1_un_motor_que_decide_una_de_veintiuna_no_publica_f1_perfecta` |
| Resolutor que resuelve un grupo y publica acción perfecta | `test_h1_el_resolver_tambien_publica_su_cobertura` |
| Tipo perfecto sobre 5 menciones de 51 | `test_h1_el_tipo_estricto_esta_en_la_tabla` |
| Episodio emitido con el texto vacío | `test_h2_un_episodio_detectado_con_el_texto_vacio_no_es_cobertura` |
| Episodio emitido con el texto entero equivocado | `test_h2_un_episodio_con_el_texto_entero_equivocado_no_es_cobertura` |
| Diluir la tasa de candidatos falsos emitiendo 100 claims correctos | `test_h3_la_tasa_de_trampas_no_se_diluye_emitiendo_mas_claims` |
| Evadir la trampa no declarando evidencia ni menciones | `test_h3_un_claim_sin_anclar_en_un_episodio_con_trampa_no_pasa_por_limpio` |
| Sistema real que nombra sus propias afirmaciones | `test_h4_la_supersesion_se_reconoce_con_identificadores_propios` |
| Superseder hacia el hecho equivocado | `test_h4_superseder_hacia_un_hecho_equivocado_no_cuenta` |
| Documento de otro split con el sobre reescrito | `test_h5_un_documento_colado_de_otro_split_no_entra` |
| Predicciones sin declarar split | `test_h5_unas_predicciones_sin_split_no_se_puntuan` |
| Bajar el umbral de solape desde la CLI | `test_h6_la_cli_rechaza_un_umbral_por_debajo_del_suelo` |

Además, cada métrica tiene su degradación controlada: perder una mención,
inventarla, desplazar su offset, tiparla mal, romper una correferencia, fundirlo
todo, anclar un claim sobre una ficción, partir una entidad, fundir dos, enlazar
la entidad provisional a quien se le parece, aprobar lo que hay que revisar,
rechazar lo que hay que aceptar, invertir la dirección, perder la negación,
tratar un rumor como afirmado, invertir la negación de un hecho, intercambiar
los extremos de una simétrica (no penaliza) y de una asimétrica (penaliza),
inventar evidencia, duplicar hechos, aprobar un plan sin respaldo, truncar
episodios y perderlos.

---

## 6. Límites conocidos

1. **`dev` es pequeño.** 51 menciones, 21 claims, 16 afirmaciones. Algunas
   métricas son directamente binarias: `supersession_recall` tiene **n = 1**, así
   que solo puede valer 0.0 o 1.0 y no admite lectura como porcentaje. Sirve para
   detectar que algo está roto, no para estimar rendimiento real. Un intervalo
   de confianza sobre 17 hechos no significa nada.
2. **El gold es de autoría propia.** Los mundos están inventados para este
   benchmark. Un sistema que rinda aquí no ha demostrado nada sobre material
   real; para eso están el held-out y la corrida sobre corpus real.
3. **El alineamiento de clusters es voraz.** Puede subestimar
   `identity_accuracy`. Es la dirección segura, pero está ahí.
4. **La correferencia se mide con pares positivos.** No es MUC ni B³ ni CEAF;
   la elección está documentada y es estable, pero no comparable con literatura
   que use otra métrica.
5. **`false_candidate_rate` es diluible por construcción.** Su denominador son
   los claims emitidos. Está publicada porque es la forma habitual de la
   métrica, pero la cifra que hay que leer es `trap_hit_rate`, cuyo denominador
   lo fija el dataset.
6. **El arnés no ejecuta nada.** No mide latencia, RAM ni coste: los copia. Y no
   valida por sí solo que la salida de un subsistema cumpla los contratos —
   `loader.validate_gold` es para el gold; para las predicciones esa validación
   corresponde al gate de cada bloque.

---

## 7. Cómo se añade el held-out sin tocar el arnés

El held-out lo prepara un **equipo independiente** con doble pase y lo custodia
Fable (dosier §9). Este bloque no lo ve ni lo escribe.

El procedimiento es una copia de directorio:

1. El equipo independiente construye `datasets/heldout/` con **la misma
   estructura** de §2.3: `manifest.json`, `catalog/`, `sources/<id>/*.json`.
2. Todo fichero lleva `"split": "heldout"` y todo documento
   `metadata.benchmark.split = "heldout"`. El loader comprueba **las dos
   marcas** al cargar: el sobre del fichero y la de cada documento. La segunda
   defensa vive en la carga precisamente porque instalar un split es copiar un
   directorio, y un fichero traído de otro split con el sobre reescrito a mano
   pasaría la primera comprobación y no la segunda.
   Además, un bundle de predicciones **sin `split`** no se puntúa: el campo no
   tiene valor por defecto y `from_dict` falla con mensaje explícito.
3. Todo el gold debe validar contra los contratos congelados. La misma llamada:
   `python -m knowledge_v3.benchmarks.cli validate --split heldout`.
4. Medir: `--split heldout`. Ni una línea del arnés cambia. Un bundle de
   predicciones que declare `dev` contra un gold `heldout` lanza.

No hace falta que el held-out use los mismos mundos, ni las mismas modalidades,
ni el mismo perfil: `manifest.json` describe su propia composición y el arnés la
lee. Lo único obligatorio es la estructura de ficheros y la marca de split.

Recomendación al equipo independiente, derivada de lo aprendido aquí: incluir
juegos distintos, fuentes distintas, modalidades distintas, frases que no
aparezcan en ningún prompt, casos negativos, temporalidad, cambios históricos,
correferencia, simétricas y errores de OCR/ASR — y **no** reutilizar ninguna
formulación de `dev`.

La tabla del informe final (dosier §14) separa las columnas por esa razón:

| Métrica | V1 | V2 | V3 dev | V3 held-out | V3 real |
|---|---:|---:|---:|---:|---:|

Una cifra de `dev` en la columna de held-out es exactamente el error que costó
0.81 → 0.24 en el motor de relaciones v2.

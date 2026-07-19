# relations — contrato interno `relation-candidate/internal-v1`

Paquete de **contrato de datos** para relaciones candidatas del pipeline interno
de relaciones del data-engine. Este paquete contiene **solo** el modelo, sus
enums, los validadores y la serializacion determinista.

## Alcance (lo que este paquete SI hace)

- Define `RelationCandidate` con **exactamente 20 campos**.
- Valida esos campos (`validate()`), con mensajes de error claros.
- Serializa de forma determinista (`to_json` / `from_json`, round-trip estable).

## Fuera de alcance (lo que este paquete NO hace)

- No extrae relaciones ni analiza texto.
- No invoca Ollama, NVIDIA, prompts ni ningun LLM.
- No ejecuta el ensemble/consenso (solo **referencia** sus estados canonicos).
- No autoaprueba ni escribe en Neo4j.

Estos subsistemas viven en otros modulos (`external_ai/`, `external_processing/`,
ingestas, etc.). Aqui unicamente se **referencian**.

## Los 20 campos

| # | campo | tipo | nota |
|---|-------|------|------|
| 1 | `subject_id` | str | obligatorio, no vacio |
| 2 | `subject_type` | str \| null | si se aporta, tipo de entidad valido |
| 3 | `predicate` | str | normalizado MAYUSCULAS_CON_GUION_BAJO |
| 4 | `object_id` | str | obligatorio, no vacio |
| 5 | `object_type` | str \| null | si se aporta, tipo de entidad valido |
| 6 | `direction` | enum | SUBJECT_TO_OBJECT \| OBJECT_TO_SUBJECT \| UNDIRECTED |
| 7 | `confidence` | float | en [0, 1] |
| 8 | `evidence_text` | str | obligatorio salvo `extraction_method=ONTOLOGY` |
| 9 | `evidence_start` | int | >= 0 |
| 10 | `evidence_end` | int | >= 0 y >= `evidence_start` |
| 11 | `source_id` | str | procedencia obligatoria |
| 12 | `source_page` | int \| null | si se aporta, >= 0 |
| 13 | `source_segment` | str | procedencia obligatoria |
| 14 | `extraction_method` | enum | HEURISTIC \| LLM_LOCAL \| NVIDIA \| ONTOLOGY |
| 15 | `model` | str \| null | `modelo@version` o null |
| 16 | `negated` | bool | **bool explicito** |
| 17 | `temporal_scope` | null \| obj | preservado tal cual |
| 18 | `epistemic_status` | enum | ASSERTED \| RUMORED \| HYPOTHETICAL \| INTENDED |
| 19 | `workspace` | str | obligatorio |
| 20 | `validation_flags` | list[str] | lista de flags |

## Diferencia justificada frente a la propuesta (§1)

La propuesta previa en `docs/coordination/contract-proposals.md §1` describia
**18 campos de dominio** (con `evidence_span` y sin `subject_type`/`object_type`).
Este contrato interno-v1 introduce dos cambios deliberados:

1. **Se anaden `subject_type` y `object_type`.** Permiten validacion ontologica
   de compatibilidad de tipos (que un predicado dado admita los tipos de sus
   extremos) sin tener que resolver la entidad contra Neo4j.
2. **Se desdobla `evidence_span` en `evidence_start` + `evidence_end`.** Offsets
   enteros explicitos: mas simples de validar (`start <= end`, ambos `>= 0`) y de
   serializar de forma determinista, sin sub-objeto anidado.

Resultado: **exactamente 20 campos**. No se anaden campos mas alla de estos 20.
Los metadatos de la propuesta (`schema_version`, `document_type`, `relation_id`)
no son campos de datos del modelo; `SCHEMA_VERSION` y `DOCUMENT_TYPE` se exponen
como constantes de modulo.

## Estados de consenso (reutilizados, no duplicados)

El ensemble usa cinco estados canonicos: **STRONG · PARTIAL · CONFLICT · INVALID
· HUMAN**. Su forma canonica en codigo (con sufijo) esta definida en
`external_ai/models.py` (`CONSENSUS_STATES = STRONG_CONSENSUS, PARTIAL_CONSENSUS,
MODEL_CONFLICT, INVALID_RESPONSES, HUMAN_REQUIRED`). Este paquete los **importa y
referencia** via `CANONICAL_CONSENSUS_STATES`; no crea un segundo sistema de
consenso. Si `external_ai` no estuviera disponible, se usa un espejo con los
mismos valores, documentado como tal en `contracts.py`.

## Reglas de validacion (`validate()`)

- `subject_id` y `object_id` no vacios.
- `subject_id != object_id` salvo predicado reflexivo permitido. Lista de
  reflexivos: `REFLEXIVE_PREDICATES`, **vacia por defecto**.
- `predicate` normalizado (MAYUSCULAS con guion_bajo) — ver `normalize_predicate`.
- `confidence` en `[0, 1]`.
- `evidence_start <= evidence_end`, ambos `>= 0`; `evidence_text` obligatorio si
  `extraction_method != ONTOLOGY`.
- `workspace` obligatorio.
- `extraction_method`, `direction`, `epistemic_status` deben ser valores validos.
- `negated` es `bool` explicito.
- Procedencia minima: `source_id` y `source_segment` presentes.
- Serializacion determinista: `to_json` ordena claves; `from_json` reconstruye;
  round-trip estable.

## Semantica epistemica

`negated=True` marca una **no-afirmacion** (invalida la afirmacion positiva).
`epistemic_status != ASSERTED` no es un hecho confirmado. `is_affirmative()`
devuelve `True` solo si `negated=False` y `epistemic_status=ASSERTED`.

## Compatibilidad futura

`from_json` / `from_dict` **rechazan** cualquier clave desconocida (fuera de los
20 campos) con `RelationContractError`. El contrato interno-v1 es **cerrado**: una
clave extra indica otra version u otro contrato y no debe silenciarse. La
promocion a una v2 requiere aprobacion del Supervisor.

## Vocabulario de predicados (Bloque 3)

Modulo: `relations/vocabulary.py`. `VOCAB_VERSION = "relation-vocab-1.0.0"`.

Esta capa es **normalizacion semantica** de predicados (sinonimos, canonicos,
simetria, compatibilidad de tipos), **separada** de la normalizacion meramente
tipografica de `normalize_predicate` (espacios/guiones -> `_`, MAYUSCULAS), que
se reutiliza como paso previo. `VOCAB_VERSION` es **independiente** de
`SCHEMA_VERSION`: ampliar el vocabulario NO cambia el contrato de datos.

Principios: DETERMINISTA y puro (sin red, disco ni estado mutable); alias **SIN
perdida** de significado; **fuente unica** de canonicos y tipos reutilizada de
`prompts.KNOWN_PREDICATES` y `prompts.TEMPLATES` (no se teclea la ontologia).

### Canonizar un predicado

`canonicalize_predicate(raw)` devuelve un `PredicateCanonicalization` frozen con
la decision **trazada**:

```python
from relations.vocabulary import canonicalize_predicate

r = canonicalize_predicate("lives in")
# r.normalized  -> "LIVES_IN"
# r.canonical   -> "LOCATED_IN"
# r.status      -> "alias"        (canonical | alias | out_of_vocab | unknown)
# r.rule        -> "alias-synonym"
# r.requires_human -> False
```

Orden de decision: canonico exacto -> alias sin perdida -> `out_of_vocab_v1`
(fallback humano) -> `unknown` (fallback humano).

### Comparar predicados (alias-aware)

`predicates_match(a, b)` es `True` si ambos resuelven al **mismo** canonico
(incluye alias). Dos predicados sin canonico (`None`) **nunca** emparejan, ni
siquiera consigo mismos: su significado no esta determinado. Es lo que usa el
scoring del benchmark (`benchmark/matching.py`) en lugar de la igualdad de
string.

Auxiliares: `is_symmetric(pred)` (simetricos `ALLIED_WITH`, `ENEMIES_WITH`,
`KIN_OF`, no orientados), `types_compatible(pred, subject_type, object_type)`
(ontologia derivada de las plantillas; ambos ordenes para simetricos) e
`inverse_of(pred)` (mecanismo listo, **vacio en v1** -> siempre `None`).

### Politica `out_of_vocab_v1` -> humano

Los predicados de dominio conocidos pero **sin canonico limpio en v1**
(subtipos de parentesco `PARENT_OF`/`SIBLING_OF`/`MARRIED_TO`/`CHILD_OF`/
`SPOUSE_OF` y 8 mas: `MENTOR_OF`, `GUARDS`, `FOUNDED`, `ALIAS_OF`, `TRUSTS`,
`LEADS`, `KNOWS`, `CREATED`) **no** se colapsan contra ningun canonico:
marcan `requires_human=True`. Es una decision **honesta** — no se fabrica
cobertura forzando mapeos con perdida.

### Como se extiende el vocabulario

- **Anadir un alias** (sinonimo lexico sin perdida de un canonico existente):
  seguro, solo esta capa; se agrega a `PREDICATE_ALIASES`.
- **Promover un `out_of_vocab_v1` a canonico**: NO es un cambio local. Un
  canonico nuevo necesita **plantilla de prompt** (fuente de canonicos y tipos)
  y, por tanto, **coordinacion** (area compartida) — es material de un **vocab
  v2**, no de v1.
- Anadir pares de inversas: rellenar `INVERSE_PREDICATES` (API ya lista).

## Temporalidad (Bloque 4)

Modulo: `relations/temporality.py`. `TEMPORALITY_VERSION =
"relation-temporality-1.0.0"`.

Esta capa **clasifica** el alcance temporal de una relacion en una de seis clases
**alineadas con el enum `temporal_status` del ground truth**, separada de la mera
deteccion de marcadores que hacia `signals.signal_temporality`. Es DETERMINISTA y
pura (sin red, disco ni estado mutable), como `vocabulary.py`. `TEMPORALITY_VERSION`
es **independiente** de `SCHEMA_VERSION`: ampliar los lexicos NO cambia el contrato
de datos, y `temporal_scope` sigue siendo string libre (`Optional[Any]`) — la
estructura vive aqui y se **serializa** a un string estable.

### Las 6 clases

```text
PAST · PRESENT · FUTURE · ONGOING · ENDED · ATEMPORAL
```

`TEMPORAL_CLASSES` es la **fuente unica** de estas clases (no se teclean sueltas).

### Clasificar un texto

`classify_temporality(text)` devuelve un `TemporalClassification` frozen con la
decision **trazada** (clase, `markers`, `dates`, `interval`, `is_ended`,
`is_potential`, `temporality_version`):

```python
from relations.temporality import classify_temporality

c = classify_temporality("goberno entre 843 y 870")
# c.temporal_class     -> "PAST"
# c.interval           -> ("843", "870")
# c.to_scope_string()  -> "PAST | markers=goberno | interval=843-870"
```

Prioridad de clase **documentada y estable**:

```text
ENDED > FUTURE > ONGOING > PAST > PRESENT > ATEMPORAL
```

Una marca de cese (ENDED) o de futuro/potencial (FUTURE) domina sobre la morfologia
de preterito (`prometio` es FUTURE, no PAST); PRESENT es la clase por defecto solo
cuando no hay marca fuerte. Se usa lexico determinista (con frontera de palabra,
aplanado sin tildes) mas morfologia verbal (preterito `\w+ó`, futuro `\w+rá/rán`) y
fechas/intervalos.

### Serializar y derivar la clase

- `TemporalClassification.to_scope_string()` → string estable con la CLASE al
  frente (`CLASS | markers=… | dates=… | interval=…`), parseable por round-trip.
- `temporal_status_of(scope)` → deriva la clase de cualquier `temporal_scope`:
  `None` → `None`; string canonico → clase del prefijo; string libre (LLM) → se
  reclasifica con `classify_temporality`.

### Politica de "no fabricar"

No se inventa temporalidad. Un texto sin marca de tiempo produce PRESENT/ATEMPORAL
segun corresponda, y el pipeline deja `temporal_scope = None` cuando no hay alcance
distintivo (`has_temporal_signal` False). `temporal_status_of(None)` devuelve
`None`: un alcance ausente **no es** una clase.

### Matching class-aware

El scoring del benchmark (`benchmark/matching.py`) pasa de **detectar** a
**clasificar**: `temporal_correct` exige `temporal_status_of(pred) ==
gt.temporal_status`. Un `None` **nunca** casa con PAST/FUTURE/ONGOING/ENDED, ni una
clase equivocada — no se puede "ganar" el gate etiquetando todo.

## Estado epistémico (Bloque 5)

Modulo: `relations/epistemic.py`. `EPISTEMIC_VERSION =
"relation-epistemic-1.0.0"`.

Esta capa **clasifica** el estado epistémico de una relación (¿es un hecho, un
rumor, una hipótesis o una intención?), separada de la mera detección binaria que
hacían `signals.signal_rumor`/`signals.signal_modality`. Es DETERMINISTA y pura (sin
red, disco ni estado mutable), como `temporality.py` (B4) y `vocabulary.py` (B3).
`EPISTEMIC_VERSION` es **independiente** de `SCHEMA_VERSION`: ampliar los léxicos NO
cambia el contrato de datos.

### Los 4 valores del enum (contrato) y los 9 matices (nuance)

`classify_epistemic` **reutiliza** el enum `EpistemicStatus` del contrato — **no
añade valores** ni cambia `SCHEMA_VERSION`. Los cuatro valores canónicos son:

```text
ASSERTED · RUMORED · HYPOTHETICAL · INTENDED
```

Internamente distingue **9 matices finos** (`nuance`) y los **mapea** a esos 4
valores. El `nuance` es **metadato de trazabilidad**: NO se persiste como campo del
contrato.

| nuance | status |
|---|---|
| `rumor` · `indirect` · `belief` | RUMORED |
| `contradiction` · `doubt` · `possibility` · `hypothesis` | HYPOTHETICAL |
| `intention` | INTENDED |
| `assertion` (sin marca) | ASSERTED |

### Clasificar un texto

`classify_epistemic(text)` devuelve un `EpistemicClassification` frozen con la
decisión **trazada** (`status`, `nuance`, `cues`, `epistemic_version`; propiedades
`is_asserted`, `has_epistemic_cue`):

```python
from relations.epistemic import classify_epistemic

c = classify_epistemic("se dice que fundo la orden")
# c.status           -> EpistemicStatus.RUMORED
# c.nuance           -> "rumor"
# c.cues             -> ("se dice que",)
# c.is_asserted      -> False
```

Precedencia **documentada y estable** (el primer grupo con match fija status +
nuance):

```text
RUMOR / INDIRECTO / CREENCIA            -> RUMORED       (mayor prioridad)
CONTRADICCION / DUDA / POSIBILIDAD / HIPOTESIS -> HYPOTHETICAL
INTENCION / PLAN                        -> INTENDED
(ninguna marca)                         -> ASSERTED       (menor prioridad)
```

El rumor pesa más que la hipótesis; la contradicción se degrada a HYPOTHETICAL
(nunca se afirma algo en disputa). El matching es por **frontera de palabra** sobre
texto aplanado (sin tildes, minúsculas).

### Regla bloqueante: un rumor NUNCA se convierte en hecho

**INVARIANTE DURO:** si hay CUALQUIER cue epistémico no-asertivo, el `status`
resultante NUNCA es `ASSERTED` — se degrada según la precedencia. `ASSERTED` se
reserva EXCLUSIVAMENTE para textos sin marca. El estado epistémico no se pierde.

`is_epistemically_safe(status, has_epistemic_cue)` es la guardia **explícita y
verificable** de ese invariante: devuelve `False` (inseguro) si hay un cue
no-asertivo y aun así el status es `ASSERTED`. `classify_epistemic` nunca debe
producir un estado inseguro; los consumidores pueden aseverarlo para blindar el
pipeline. La señal explicable `signals.signal_epistemic` y
`pipeline._epistemic_status` delegan en `classify_epistemic` y por tanto respetan el
invariante.

### La salvaguarda dura sigue siendo `is_affirmative`

Por encima de esta capa, la salvaguarda **dura** del contrato permanece intacta:
`is_affirmative() = (not negated) and epistemic_status == ASSERTED`. Una relación
solo cuenta como afirmación de hecho si no está negada **y** su estado es `ASSERTED`;
cualquier cue epistémico degrada el status, así que un rumor jamás satisface
`is_affirmative()`.

### Política de "no fabricar"

Conservador al degradar: una aserción llana del narrador **sin marcas** se clasifica
`ASSERTED` (no se degrada de más, para no falsear la métrica). Solo degrada cuando
hay atribución o cue epistémico real — ni se afirma de más, ni se degrada de más.

## Ensemble calibrado (Bloque 6)

Modulo: `relations/ensemble.py`. `ENSEMBLE_VERSION = "relation-ensemble-1.0.0"`,
`ENSEMBLE_SCHEMA = "relation-ensemble/v1"`.

Esta capa **NO es un segundo combinador de consenso**. `consensus_adapter.
compute_relation_consensus` sigue siendo el combinador canónico de las 4 vías
(heurísticas R2, sintaxis R3, LLM local R5, IA externa R6) y no se reescribe ni se
depreca. El ensemble se construye **encima** y hace dos cosas:

1. **DELEGA** en el consenso las **invalidaciones duras** (contrato inválido, mezcla
   de workspaces, proveedor presente inválido, evidencia ausente). Si el consenso
   devuelve `INVALID_RESPONSES`, el ensemble **respeta el veredicto tal cual** y no
   calibra nada.
2. **CALIBRA la zona gris** con pesos y umbrales versionados, e **incorpora por fin**
   las fuentes deterministas de los Bloques 3/4/5 (`vocabulary`, `temporality`,
   `epistemic`), que hasta ahora no consumía ninguna decisión del pipeline.

Es DETERMINISTA y pura (sin red, disco, escritura, LLM, `time`/`random` ni iteración
sobre sets), como `epistemic.py` (B5), `temporality.py` (B4) y `vocabulary.py` (B3).
Recibe evaluaciones **ya calculadas** o `None`: **nunca** invoca Ollama ni NVIDIA.

### Calibrar un candidato

```python
from relations.ensemble import combine, DEFAULT_PROFILE

d = combine(candidate, signals=signals, syntax=syntax,
            local=local_eval, external=external_eval, config=DEFAULT_PROFILE)
# d.state           -> "PARTIAL_CONSENSUS"        (de CONSENSUS_STATES)
# d.recommendation  -> "propose"                  (techo: nunca aprueba)
# d.score           -> 0.62                       (media ponderada, 6 decimales)
# d.contributions   -> 7 SourceContribution (SIEMPRE las 7)
# d.conflicts       -> tupla de conflictos tipificados
# d.config_hash     -> "…"                        (config reproducible)
# d.consensus_state -> estado del combinador delegado (trazabilidad)
```

`combine(...)` acepta además `local_availability` / `external_availability` para
declarar **por qué** falta un proveedor cuando su evaluación es `None`.

### Las 7 fuentes y su `availability`

Se emite **SIEMPRE una `SourceContribution` por cada una de las 7 fuentes**, aunque
la fuente esté ausente: ninguna contribución se pierde en la trazabilidad.

| Fuente | Origen | Peso | Qué aporta |
|---|---|---|---|
| `heuristics` | R2 · `signals.py` | 0.6 | Soporte estructural (`same_clause`, `same_sentence`, `svo_pattern`) |
| `syntax` | R3 · `syntax.py` | 0.8 | Tripleta S-V-O completa en alguna oración |
| `vocabulary` | **B3** | 1.0 | Canónico del predicado + compatibilidad ontológica de tipos |
| `temporality` | **B4** | 0.7 | Clase del texto vs `temporal_status_of(temporal_scope)` |
| `epistemic` | **B5** | 1.0 | Clase del texto vs `epistemic_status` (guardia `is_epistemically_safe`) |
| `local_llm` | R5 | 1.2 | Recomendación del LLM local (`_LOCAL_POLARITY`) |
| `external_ai` | R6 | 1.4 | Recomendación en sombra de la IA externa (`_EXTERNAL_POLARITY`) |

`availability` ∈ `PRESENT · NOT_EXECUTED · FAILED_CLOSED · SKIPPED · INVALID`. Los
tres estados de ausencia de proveedor se **reutilizan** de `relations.pipeline`.
`polarity` ∈ `positive · negative · abstain · none`, con el invariante duro: **una
fuente no presente solo admite `polarity = "none"`**. Cada contribución declara la
**versión del módulo de origen** (`VOCAB_VERSION`, `TEMPORALITY_VERSION`,
`EPISTEMIC_VERSION`, …).

### Conflictos tipificados

Objetos `{type, detail, sources}`, deduplicados y en orden canónico:

```text
provider_polarity · negation · epistemic · temporal · predicate_mismatch
```

Los `reason_codes` del consenso delegado se **traducen** a estos tipos en vez de
perderse (`provider_polarity_conflict`, `negation_contradiction`,
`epistemic_contradiction`). **Cualquier conflicto ⇒ `MODEL_CONFLICT` / `human`**: no
se promedia por encima de una contradicción.

### Reglas duras: no-autoaprobación y ausencia != rechazo

**NO AUTOAPRUEBA.** `EnsembleDecision` valida **tres barreras** en su
`__post_init__`, así que una decisión insegura es **inconstruible**:

1. `shadow` debe ser `True` (sin efectos).
2. `state` debe pertenecer a `external_ai.models.CONSENSUS_STATES` — la taxonomía de
   estados se **reutiliza**, no se duplica.
3. `recommendation` debe estar en `consensus_adapter.RELATION_RECOMMENDATIONS`
   (`propose` · `reject` · `human`) y no ser una recomendación prohibida
   (`approve`, `auto_approve`, `write`, `apply`…). **El techo es `propose`.**

Además: **`reject` es siempre delegado** — el ensemble nunca inventa un rechazo,
solo preserva la polaridad negativa que el consenso ya había recomendado; y el
**techo de calibración** impide subir a `STRONG_CONSENSUS` desde `HUMAN_REQUIRED`,
`MODEL_CONFLICT` o `INVALID_RESPONSES` (sí calibra `PARTIAL → STRONG` y
`HUMAN → PARTIAL`). `STRONG` exige además **al menos un proveedor PRESENTE**: las
fuentes deterministas corroboran, no sustituyen a un revisor.

**AUSENCIA != RECHAZO.** Un proveedor ausente aporta `polarity = "none"` y
`score = 0`, y **no entra** en el denominador de la media ponderada: no vota en
contra ni resta. Un score dentro de `conflict_margin` es **zona muerta** y escala a
`HUMAN_REQUIRED` en vez de resolverse por redondeo.

### Versionar y reproducir la configuración

`EnsembleConfig` (frozen) lleva pesos por fuente y umbrales (`strong_threshold`
0.75, `partial_threshold` 0.45, `conflict_margin` 0.15, `min_decisive_sources` 2),
con `weights_version` y `thresholds_version` **independientes** de
`ENSEMBLE_VERSION`: recalibrar NO cambia el código ni el contrato, solo esta capa.

```python
from relations.ensemble import PROFILES, config_from_dict

cfg = PROFILES["default-1.0.0"]          # mapa INMUTABLE de perfiles
cfg.config_hash                          # sha256 truncado a 16 hex, determinista
cfg2 = config_from_dict({"strong_threshold": 0.8,
                         "weights": {"external_ai": 1.6},
                         "weights_version": "…-1.1.0"})
```

`config_hash` se calcula sobre la vista canónica de `to_dict()` y **viaja en cada
decisión**, de modo que cualquier resultado archivado es reproducible bit a bit.
`config_from_dict` aplica **lista blanca** de claves y **rechaza** las claves de
escritura de `pipeline._FORBIDDEN_CONFIG_KEYS` (`write`/`apply`/`persist`/`commit`/
`auto_approve`…) con `EnsembleConfigError`: no existe ruta de configuración que
haga escribir al ensemble.

### Fuera de alcance en v1

El ensemble **no está cableado** como paso obligatorio de `pipeline.run_pipeline`:
su integración corresponde a un bloque posterior con su propio gate. Tampoco ejecuta
proveedores reales ni escribe en Neo4j.

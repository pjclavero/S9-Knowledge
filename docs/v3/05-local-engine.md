# 05 — Motor local de conocimiento V3

**Rama:** `feat/v3-local-engine` · **Base:** `36439a2` (contratos v3 CONGELADOS,
`v3-contracts-frozen-1.0.0`)
**Ámbito exclusivo:** `data-engine/app/knowledge_v3/engine/`,
`data-engine/app/tests/test_knowledge_v3_engine*.py`, este documento.
**Estado:** implementado; revisión independiente **NO CONFORME** sobre
`cbbcab8` → ronda de correcciones H1-H6 aplicada (§10). 138 tests propios en
verde, suite completa sin regresiones (4312 passed / 5 skipped).

El motor es el subsistema D del dosier (§11) y **la única autoridad del
sistema**: solo él valida, aprueba, invalida, cierra vigencias y autoriza una
escritura. Ollama y los proveedores externos entran aquí como datos.

---

## 1. Qué entra y qué sale

```text
ClaimProposal[] + EntityResolution[] + EvidenceFragment[] + SourceEpisode[]
  + GameProfile + GraphSnapshot (solo lectura)  [+ ExternalSignal[] opcional]
        │
        ▼
  LocalKnowledgeEngine.run(now=…)          ← el reloj se INYECTA
        │
        ├─► ClaimDecision[]     ACCEPT · REJECT_INVALID · ABSTAIN · REVIEW
        ├─► FactAssertion[]     (solo de las ACCEPT que escriben)
        ├─► GraphMutationPlan   plan de escritura, sellado, `approved` si procede
        └─► GraphMutationPlan   plan de revisión, sellado, `approved: false`
```

Ficheros:

| Pieza | Fichero |
|---|---|
| Fachada, validación del lote, aislamiento | `engine/engine.py` |
| Umbrales configurables | `engine/config.py` |
| Hallazgos y traducción a decisión canónica | `engine/findings.py` |
| Eje existencia / identidad | `engine/identity.py` |
| Eje evidencia | `engine/evidence.py` |
| Ejes predicado y dirección + clave canónica | `engine/ontology.py` |
| Eje temporal | `engine/temporal.py` |
| Eje contradicción | `engine/contradiction.py` |
| Agregación y decisión por claim | `engine/decision.py` |
| Construcción y sellado del plan | `engine/planner.py` |
| Snapshot del grafo (interfaz + memoria + Neo4j declarado) | `engine/snapshot.py` |
| Señales no locales | `engine/signals.py` |

---

## 2. Por qué esto NO es un clasificador léxico

La auditoría `00-audit-current-system.md` es el motivo de casi todas las
decisiones de diseño de este subsistema:

- el clasificador de predicado de V2 es **léxico**: ~70 % de su ganancia venía
  de expresiones calcadas del corpus;
- en material real **9 de 14 familias de predicado sacan cero**, el **41 %** de
  las salidas es el comodín `RELATED_TO` y la abstención efectiva es del 100 %
  (0 resultados `strong` de 64);
- sobre material real, **~170 falsos positivos por cada acierto**;
- ampliar la lista de expresiones es, textualmente, «una carrera sin final».

Consecuencia: **en todo `engine/` no hay una sola lista de palabras, ni un
`if "aliado" in texto`, ni una expresión regular sobre lenguaje natural.** El
motor no vuelve a leer el texto: leerlo otra vez sería duplicar exactamente el
modo de fallo que se está intentando abandonar.

Lo que el motor usa en su lugar es **estructura**:

1. los `predicate_candidates` / `direction_candidates` que el extractor ya
   entrega puntuados (el motor elige entre ellos, no los inventa);
2. la **ontología** del `GameProfile`: dominio, rango, simetría, inversa,
   funcionalidad;
3. los **tipos** de las entidades resueltas;
4. el **estado real del grafo** (snapshot);
5. la **coherencia entre documentos**: que la cita esté realmente en el
   episodio, que el calendario exista en el perfil, que la entidad exista en el
   grafo.

El único punto donde el motor mira caracteres es el cotejo literal de la
evidencia (`texto_episodio[start:end] == literal_text`), que es comparación de
cadenas exacta contra una fuente, no clasificación semántica.

---

## 3. Los ejes, uno a uno

Las doce etapas del dosier §11.2 se recorren **siempre y completas**: no hay
cortocircuito. Un claim que ya se sabe que irá a revisión sigue pasando por
temporalidad y contradicción, para que la decisión lleve *todas* sus razones y
no solo la primera que apareció. Cortar en el primer «no» produce explicaciones
que dependen del orden de evaluación.

### 3.1. Existencia e identidad (`identity.py`)

| Regla | Resultado |
|---|---|
| mención sin `EntityResolution` | `REVIEW` · `REVIEW_ENTITY` · `UNRESOLVED_MENTION` |
| acción ≠ `LINK_EXISTING` (`CREATE_NEW`, `CREATE_PROVISIONAL`, `SPLIT`, `REVIEW`) | `REVIEW` · `ENTITY_PROVISIONAL` / `ENTITY_RESOLUTION_DEFERRED` |
| entidad ausente del snapshot | `REVIEW` · `ENTITY_NOT_IN_SNAPSHOT` |
| confianza de resolución < umbral | `REVIEW` · `ENTITY_LOW_CONFIDENCE` |
| dos menciones del mismo rol → entidades distintas | `REVIEW` · `ENTITY_ROLE_AMBIGUOUS` |
| tipo de la resolución ≠ tipo del grafo | `REVIEW` · `ENTITY_TYPE_UNKNOWN` |
| sujeto = objeto | `REJECT_INVALID` · `DEMONSTRABLY_FALSE` · `SELF_RELATION` |
| `claim.abstained` | `ABSTAIN` · `INSUFFICIENT_EVIDENCE` |

Solo `LINK_EXISTING` consolida identidad. Ahí se corta de raíz el patrón «un
nodo nuevo por cada error de ASR/OCR»: una identidad no consolidada nunca se
escribe, va a revisión.

### 3.2. Evidencia (`evidence.py`)

El motor no cree a nadie. Comprueba que el fragmento existe, que pertenece al
mismo workspace y asset, que su episodio es el del claim, y —lo importante— que
**el texto citado está de verdad en el episodio en los offsets declarados**.

Sin ese cotejo, «hay evidencia» solo significa «hay un identificador bonito»:
basta con que un extractor alucine una cita para que el hecho pase. Con él, hay
que alucinar la cita *y además* acertar los offsets del episodio real.

| Regla | Resultado |
|---|---|
| fragmento inexistente | `ABSTAIN` · `INSUFFICIENT_EVIDENCE` |
| fragmento de otro asset | `REJECT_INVALID` · `DEMONSTRABLY_FALSE` |
| fragmento de otro episodio | `ABSTAIN` |
| cita que no coincide con el episodio | `REVIEW` · `REVIEW_EVIDENCE` · `EVIDENCE_TEXT_MISMATCH` |
| offsets fuera del episodio | `REVIEW` · `EVIDENCE_OFFSETS_OUT_OF_RANGE` |
| calidad del episodio < umbral | `ABSTAIN` · `LOW_QUALITY_EPISODE` |
| `claim.review_required` | `REVIEW` · `EXTRACTOR_REQUESTED_REVIEW` |
| confianza del claim < umbral | `REVIEW` |
| modalidad sin texto (imagen, mapa, tabla) | aviso `EVIDENCE_NOT_VERIFIABLE` (y, por invariante, nunca `ACCEPT`) |

### 3.3. Predicado (`ontology.py`)

Cascada, en este orden:

1. sin candidatos → `ABSTAIN` · `AMBIGUOUS_SEMANTICS`;
2. ninguno en la ontología del perfil → `REJECT_INVALID` ·
   `ONTOLOGY_INCOMPATIBLE` (incompatibilidad **demostrable** contra el perfil);
3. **si los dos tipos son conocidos** y ninguno encaja en dominio/rango en
   ninguna orientación → `REJECT_INVALID` · `TYPE_INCOMPATIBLE`. Si algún tipo
   es desconocido **no se rechaza**: «no lo sé» no es «es falso», y el eje de
   existencia ya mandó el claim a revisión;
4. si el favorito del extractor se cayó por (2) o (3) → aviso
   `PREDICATE_DEMOTED`: el motor está eligiendo algo distinto de lo propuesto y
   eso tiene que verse;
5. margen con el siguiente viable < `min_predicate_margin` → `REVIEW` ·
   `REVIEW_PREDICATE`. **Un empate no es una elección, es un sorteo**;
6. confianza < `min_predicate_confidence` → `REVIEW`.

### 3.4. Dirección (`ontology.py`)

- predicado **simétrico** → `UNDIRECTED` por ontología, diga lo que diga el
  extractor (dosier §11.4, `semantic_direction = NONE`). Es la única vez que el
  motor ignora la propuesta, y puede hacerlo porque no es una opinión sino una
  propiedad declarada del predicado;
- asimétrico sin dirección, o con `UNDIRECTED` → `REVIEW` ·
  `DIRECTION_UNDETERMINED` (elegir `SUBJECT_TO_OBJECT` por defecto sería
  inventarse el agente de la frase);
- dirección incompatible con los tipos cuando la contraria sí encaja →
  `REVIEW` · `DIRECTION_TYPE_MISMATCH`, **nunca un volteo automático**. Voltear
  en silencio convierte un error del extractor en un hecho del grafo y el
  humano ya no ve que hubo duda;
- empate entre las dos direcciones → `REVIEW` · `DIRECTION_AMBIGUOUS`;
- confianza < umbral → `REVIEW`.

### 3.5. Negación (`decision.py`)

`claim.negated` es **autoritativo y se copia tal cual** a la afirmación. El
motor nunca infiere negación del texto. Un hecho negado es un hecho: se acepta,
pero siempre con aviso (`NEGATED_CLAIM` → `LOCAL_APPROVED_WITH_WARNINGS`).
`accept_negated=False` lo manda a revisión en vez de escribirlo.

### 3.6. Epistemicidad (`decision.py`)

Por defecto **solo `ASSERTED` se aprueba localmente**
(`acceptable_epistemic_status`). Un rumor, una hipótesis, una intención o una
lectura visual son afirmaciones sobre el discurso, no sobre el mundo:

| `epistemic_status_hint` | Resultado |
|---|---|
| `ASSERTED` | puede aceptarse |
| `RUMORED`, `HYPOTHETICAL`, `INTENDED` | `REVIEW` · `EPISTEMIC_NOT_ASSERTED` |
| `VISUAL_INFERRED` | `REVIEW` · `EPISTEMIC_VISUAL_INFERRED` |
| `UNKNOWN` | `ABSTAIN` · `AMBIGUOUS_SEMANTICS` |

Si se amplía el conjunto aceptable, la afirmación nace con `status:
PROVISIONAL`, no `ASSERTED`. Cuando hay conflicto con el grafo, la decisión
lleva `epistemic_status: CONFLICTED` — el valor que el contrato tiene
exactamente para eso.

### 3.7. Temporalidad (`temporal.py`)

Se separan `event_time` (cuándo ocurrió), `valid_from`/`valid_to` (vigencia) y
`recorded_at` (cuándo lo supo el sistema, lo pone el ledger).

**El pasado verbal no implica `ENDED`.** No es un matiz: «Daiki juró lealtad a
la Casa del Ciervo» está en pasado y describe una pertenencia viva. Este eje no
mira el verbo; mira la estructura de las expresiones ya ancladas:

| Entrada | `state` |
|---|---|
| sin expresiones | `UNKNOWN` (o `PLANNED`/`HYPOTHETICAL` si el estatus epistémico lo dice) |
| `POINT` + `valid_from` | `ACTIVE`, `event_time = valid_from` |
| `INTERVAL` + `valid_from` + `valid_to` | `ENDED` |
| `INTERVAL` + `valid_from` | `ACTIVE` |
| `DURATION` anclada | `RECURRING` |
| `RELATIVE` sin anclaje | `UNKNOWN` + aviso `TEMPORAL_UNRESOLVED_RELATIVE` |

`ENDED` sale **únicamente** de un `valid_to` explícito — que es además lo que
el contrato congelado exige. Un `UNKNOWN` honesto se puede refinar después; un
`ENDED` inventado cierra una vigencia que nadie cerró.

A revisión (`REVIEW_TEMPORALITY`): calendario que el perfil no conoce
(**cruce inter-documento `temporal_expressions.calendar_id` ×
`GameProfile.calendars`, el que la revisión de contratos dejó anotado como
pendiente del motor**), dos calendarios en el mismo claim, intervalo invertido,
expresiones con anclajes incompatibles, o expresión que cita un fragmento
inexistente. Un calendario no validado **no se copia** a la afirmación: una
fecha en un calendario desconocido no es una fecha.

### 3.8. Contradicción (`contradiction.py`) — dos pasadas

Regla dura, **sin puerta de configuración**: una contradicción nunca se
auto-aprueba — **ni contra lo que el grafo ya dice, ni contra lo que este mismo
plan está a punto de escribir**. La segunda mitad de esa frase faltaba en la
primera versión y era un agujero real (§10, H1).

**Pasada 1 — contra el snapshot** (`check_contradictions`, por claim).
**Pasada 2 — el lote contra sí mismo** (`batch_conflicts` +
`decision.apply_batch_contradictions`, sobre el conjunto de decisiones, antes de
construir ningún plan). `decide_claim` ve un claim y todo el grafo; no ve a su
vecino de página, así que la segunda pasada no puede vivir dentro de él.

Ambas usan la **clave canónica** de la relación, no los campos crudos:

1. la orientación `OBJECT_TO_SUBJECT` se reescribe intercambiando extremos;
2. si el predicado es simétrico, la pareja se ordena — para `ALLY_OF`, (A,B) y
   (B,A) son la misma afirmación;
3. si el perfil declara `P inverse_of Q`, `(a,P,b)` y `(b,Q,a)` son la misma
   afirmación. Sin esto, `MEMBER_OF(Daiki, Casa)` y `HAS_MEMBER(Casa, Daiki)`
   conviven como dos hechos distintos y el detector no ve nada.

| Choque | Contra el snapshot | Dentro del lote |
|---|---|---|
| misma clave, `negated` opuesto | `CONTRADICTS_VIGENTE_ASSERTION` | `CONTRADICTS_CLAIM_IN_BATCH` |
| misma pareja y predicado, orientación contraria | `DIRECTION_CONFLICT_WITH_VIGENTE` | `DIRECTION_CONFLICT_IN_BATCH` |
| predicado `functional` con otro objeto | `FUNCTIONAL_PREDICATE_CONFLICT` | `FUNCTIONAL_CONFLICT_IN_BATCH` |
| reafirmar una `CONTRADICTED` sin resolver | `REAFFIRMS_CONTRADICTED_ASSERTION` | — |
| misma clave, mismo `negated` | `ALREADY_ASSERTED`, sin operación | `DUPLICATE_IN_BATCH`, sin operación |

Los cuatro primeros son `REVIEW` · `CONFLICT_WITH_EXISTING`. En un conflicto
interno se marcan **los dos** claims: no hay uno «correcto» al que dejar pasar,
y elegirlo sería justo la decisión que el motor no puede tomar solo.

Qué cuenta del snapshot (`blocks_new_claims()`): las afirmaciones **vigentes**
(`status ∈ {PROVISIONAL, ASSERTED, CONFIRMED, LIMITED}` **y** `state ∈ {ACTIVE,
RECURRING, UNKNOWN}`) **más** las marcadas `CONTRADICTED` y aún sin resolver
(§10, H2). `SUPERSEDED` y `RETRACTED` no cuentan: son historia. Los dos ejes
(`status` de ciclo de vida y `state` temporal) se consultan por separado, como
manda el contrato.

### 3.9. Autoridad (`signals.py`, `decision.py`)

Prompt maestro §2, sin interpretación posible. Cómo se materializa:

- una `ExternalSignal` **no puede** tener `provider: local` — lo que produce
  código local no es una señal, es una regla;
- `signals.contribute` solo devuelve hallazgos `INFO` (se consultó) o `REVIEW`
  (discrepa del motor). **No existe ningún camino por el que una señal produzca
  `ACCEPT`, suba una confianza o retire un hallazgo.** Que un modelo discrepe no
  prueba que tenga razón; prueba que hay algo que mirar;
- cada señal aporta su entrada **veraz** a `provider_trace` del plan (proveedor,
  nombre, versión, modelo);
- un claim propuesto por `external`/`ollama` se marca (`EXTERNAL_PROPOSAL`,
  `OLLAMA_PROPOSAL`) y, si se aprueba, se aprueba **con avisos**.

Un motor al que se le pasen mil señales entusiastas y ninguna evidencia
verificable sigue sin aprobar nada. Hay un test de mutación para eso.

---

## 4. De hallazgos a decisión

Un `Finding` lleva eje, gravedad, código canónico del contrato y código
descriptivo propio. La decisión es la agregación determinista de los hallazgos:

```text
REJECT  >  ABSTAIN  >  REVIEW  >  WARN  >  INFO
   │          │          │         │        └─ ACCEPT · LOCAL_APPROVED
   │          │          │         └────────── ACCEPT · LOCAL_APPROVED_WITH_WARNINGS
   │          │          └──────────────────── REVIEW
   │          └─────────────────────────────── ABSTAIN
   └────────────────────────────────────────── REJECT_INVALID
```

`ABSTAIN` por encima de `REVIEW` es una decisión consciente y discutible: si el
motor no logra anclar el claim en evidencia verificable, no hay nada que un
humano pueda adjudicar, y mandarlo a revisión solo inunda la cola — que es
exactamente cómo V2 se hizo inútil. Un claim bien anclado pero ambiguo sí va a
revisión.

`reason_codes` = canónico(s) de la gravedad ganadora + **todos** los códigos
descriptivos (también los de gravedad inferior: un aviso que no cambió la
decisión sigue siendo parte de la explicación), ordenados y sin duplicados para
que el `decision_hash` no dependa del orden de evaluación. Se usan
`ENGINE_DECISION_MAP` y `CANONICAL_REASON_CODES` del validador congelado, y hay
un test que produce de verdad **las diez decisiones del dosier §11.7**.

**Confianza del motor = mínimo** de las confianzas que la sostienen (claim,
predicado, dirección, ambas resoluciones). Nunca por encima de ninguna de sus
partes: multiplicarlas castigaría dos veces lo mismo, promediarlas dejaría que
una identidad dudosa quedara tapada por un predicado seguro. La cadena vale lo
que su eslabón más débil.

**Confianza = mínimo también sobre la evidencia**: entran la confianza del
fragmento citado y la calidad del episodio (§10, H3). Sin ellas, un claim de
0.99 anclado en una transcripción de 0.50 escribía `confidence: 0.99` y engañaba
a cualquier consumidor que filtre por confianza.

### Las invariantes sin umbral

No tienen flag en `EngineConfig` y viven en `decision._enforce_invariants`:

1. **no hay `ACCEPT` sin evidencia literal verificada**;
2. **no hay `ACCEPT` con una contradicción vigente ni con una contradicción
   dentro del propio lote**;
3. **no hay `ACCEPT` sin predicado, dirección, sujeto y objeto fijados**;
4. **no hay `ACCEPT` por debajo de `HARD_CONFIDENCE_FLOOR` (0.5)**, pase lo que
   pase en la configuración (§10, H4).

Y dos que `EngineConfig` rechaza en construcción, no en la decisión, para que el
error salga donde se comete: `acceptable_epistemic_status` **debe** contener
`ASSERTED` y **no puede** contener `UNKNOWN` ni `CONFLICTED`.

Detalle deliberado: poner `require_literal_evidence=False` **no abre la puerta,
la cierra del todo** — sin cotejo no hay nada verificado, y sin nada verificado
no hay aceptación. La configuración solo puede endurecer.

---

## 5. El plan de mutación

- operaciones **solo** desde decisiones `ACCEPT` (el validador congelado
  además lo exige, así que un fallo aquí es rojo dos veces);
- por cada aceptación que escribe: `CREATE_ASSERTION` (sin estado previo) y,
  opcionalmente, `PROJECT_RELATION` con `expected_version` / `expected_hash`
  **copiados del snapshot** — concurrencia optimista real;
- **no se reimplementa ningún hash**: `idempotency_key`, `decision_hash` y
  `plan_hash` los calcula `seal_plan` del validador congelado. Dos verdades
  sobre la misma firma acabarían rechazando planes correctos, o aceptando
  incorrectos;
- `assertion_id` y `plan_id` son **derivados** de la identidad lógica: la misma
  entrada produce el mismo identificador, y dos corridas del mismo corpus no
  crean dos hechos para lo mismo. El `payload` de la operación excluye
  `recorded_at` y la traza (volátiles): si entraran, la clave de idempotencia
  cambiaría en cada ejecución y destruiría la idempotencia que el contrato pide;
- `now` se **inyecta**; el motor no llama a `datetime.now()` en ningún sitio.
  Dos corridas sobre la misma entrada producen planes **byte a byte idénticos**
  (hay test);
- `expires_at = now + plan_ttl_seconds` (24 h por defecto);
- el validador interno `contradiction` comprueba además las **claves canónicas
  de las operaciones del propio plan** (`plan_is_self_consistent`): mira el
  artefacto final, no las decisiones que lo originaron, así que sigue delante
  del writer aunque algún día se añada otra ruta que construya operaciones;
- los pasos `engine.decide` / `engine.plan` están **reservados**: una señal que
  se llame así se renombra a `signal.<paso>` antes de entrar en el
  `provider_trace`, y `ExternalSignal` lo rechaza ya en construcción. El
  `provider_trace` no entra en el `decision_hash`, de modo que una procedencia
  falsa no rompería ninguna firma (§10, H5);
- cadena de validadores registrada en la aprobación: `structural`, `semantic`,
  `ontology`, `contradiction`, `authority`, `concurrency`. `approved` solo si
  hay ≥1 operación, ninguna decisión `REVIEW` y **todos** dan `PASS`;
- las decisiones `REVIEW` viajan en un **plan aparte**, sellado y válido, con
  `approved: false`. Sin separar, un solo claim dudoso bloquearía el lote
  entero, y la presión por «quitar el dudoso» es justo la presión que degrada un
  sistema de revisión.

Nada de esto autentica al firmante: el plan sigue siendo **verificable, no
confiable**, exactamente como lo dejó la fase de contratos. `is_authenticated()`
devuelve `False` a propósito.

---

## 6. Aislamiento y snapshot

- workspaces mezclados en el lote, perfil de otro workspace o snapshot de otro
  workspace → `EngineInputError`. **Bloqueo, no aviso**;
- todos los documentos de entrada se validan contra los contratos congelados
  antes de decidir nada: un documento inválido es un bloqueo, no una decisión;
- la homogeneidad de *asset* se exige sobre los **claims**, no sobre todo el
  lote: una evidencia que dice venir de otro asset no es un error de quien
  llama, es una evidencia prestada, y el eje de evidencia debe verla y rechazar
  *ese* claim en vez de tumbar la corrida;
- el motor **no habla con Neo4j, ni para leer**. Recibe un `GraphSnapshot`.
  `InMemoryGraphSnapshot` hace que todo el motor sea testeable sin base de
  datos ni red. `Neo4jReadOnlyGraphSnapshot` queda **declarado y lanzando
  `NotImplementedError`**, con el contrato que deberá cumplir el bloque de
  integración escrito en su docstring (sesión de solo lectura, `snapshot_id`
  derivado de una marca del grafo y no de `now()`, `version`/`state_hash` por
  nodo, filtro duro por workspace). Instanciarlo hoy es un error del llamante,
  no un modo degradado.

---

## 7. Tests

| Fichero | Tests | Qué cubre |
|---|---|---|
| `test_knowledge_v3_engine_gold.py` | 4 | corpus gold pequeño + comprobación de que el gold es gold |
| `test_knowledge_v3_engine.py` | 115 | los diez ejes, positivo y negativo; plan; aislamiento; autoridad; las diez decisiones del dosier **atadas cada una a su escenario**; regresión H1-H6 |
| `test_knowledge_v3_engine_mutations.py` | 19 | mutación: quitar reglas y comprobar que el resultado se vuelve incorrecto |
| **Total propio** | **138** | |
| Suite completa del repositorio | 4312 passed / 5 skipped | sin regresiones |

El corpus gold es **propio y pequeño** (seis entidades, dos episodios, un
perfil). El de contratos existe para ejercitar el *schema*, y sus offsets,
tipos y entidades no tienen por qué ser coherentes entre sí; el motor decide
sobre esa coherencia, así que necesita un corpus donde sea cierta por
construcción y donde romperla sea deliberado y visible.

### Mutantes cubiertos

| Mutación | Consecuencia demostrada |
|---|---|
| quitar la regla de contradicción (snapshot) | el motor **aprueba y escribe** lo contrario de lo vigente |
| quitar la pasada de lote | el lote que afirma y niega lo mismo saca dos `ACCEPT` (el validador del plan aún lo caza) |
| quitar la pasada de lote **y** la defensa del plan | plan **aprobado y firmado** que se contradice a sí mismo |
| dar la evidencia por buena sin cotejar | el motor **aprueba una cita falsificada** |
| quitar la capa de invariantes | el motor escribe evidencia no verificable |
| tomar el predicado de una señal externa | el motor **aprueba con base exclusivamente externa** |
| quitar dominio/rango | acepta una relación sin sentido de tipos |
| quitar la validación de calendario | escribe un calendario que el perfil no conoce |
| voltear la dirección en silencio | oculta un error del extractor como hecho |
| `ENDED` sin fecha de cierre | la afirmación ni se construye; plan sin aprobar |
| no sellar el plan | `EnginePlanError`: no hay plan |
| reimplementar la fórmula del hash | el validador congelado lo rechaza |
| operación colgando de un `REVIEW` / plan aprobado con `REVIEW` / firmante externo / clave inventada / `expected_version` ausente | rechazados por el contrato congelado |
| umbrales al mínimo y todos los estatus aceptados | la contradicción **sigue** en `REVIEW` |

---

## 8. Límites honestos

1. **El motor no mejora al extractor.** Si los `predicate_candidates` llegan
   mal puntuados, el motor solo puede abstenerse o mandar a revisión mejor o
   peor; no puede acertar por su cuenta. La calidad final de V3 está acotada
   por la del extractor, no por la de este subsistema.
2. **La evidencia no textual no se puede verificar.** Imágenes, mapas, tablas y
   diagramas no admiten cotejo por offsets, y la invariante 1 implica que
   **ningún claim apoyado solo en ellos puede aceptarse automáticamente**: irán
   siempre a revisión. Es una decisión consciente con un coste real en
   cobertura; levantarla exige una forma de verificación visual, no un flag.
3. **La supersession no está implementada aquí.** El motor detecta duplicados y
   conflictos —contra el grafo y dentro del lote— pero no cierra vigencias ni
   emite `SUPERSEDE_ASSERTION`: eso es del subsistema de ledger temporal (§12).
   Hoy un conflicto va a revisión y ahí se queda. Consecuencia directa: un
   corpus internamente contradictorio produce **cero escrituras y mucha cola de
   revisión**, y no hay ningún mecanismo automático que la vacíe.
4. **No hay medición de calidad todavía.** Estos 138 tests demuestran que las
   reglas hacen lo que dicen; **no** demuestran que el motor acierte sobre
   material real. Precisión, recall y tasa de falsos positivos son del bloque de
   benchmark, sobre held-out que este equipo no ha visto. Cualquier número de
   calidad citado antes de eso sería inventado — y el historial reciente del
   proyecto (`motor v2e`: predicado 0.81 en dev == test → 0.24 en real) dice
   exactamente por qué.
5. **`ProfileIndex` asume un solo perfil por corrida.** No hay mezcla de
   perfiles ni herencia entre ellos; en V3 inicial todos los workspaces usan
   `generic`, así que no aprieta todavía.
6. **La confianza mínima es conservadora por diseño.** Con umbrales por defecto,
   un corpus real producirá muchas más abstenciones y revisiones que
   aceptaciones. Eso es lo pretendido: el modo de fallo demostrado del sistema
   es aprobar de más.

---

## 9. Bloqueos encontrados en los contratos congelados

**Ninguno.** Los nueve contratos han bastado para todo lo que el motor
necesitaba. Dos observaciones para el registro, ninguna de las cuales exigió
tocar nada congelado:

- `decisions[].reason_codes` admite códigos no canónicos junto al canónico
  obligatorio, y el motor lo aprovecha para emitir sus códigos descriptivos por
  eje. Es exactamente el hueco que §6 de `01-contracts-v3.md` dejó como «no
  congelado», y funciona;
- `CANONICAL_REASON_CODES` no tiene un código propio para «estatus epistémico
  no asertado» ni para «negación no aceptada». Se emiten como `REVIEW_EVIDENCE`
  canónico + descriptivo `EPISTEMIC_NOT_ASSERTED` / `NEGATION_NOT_ACCEPTED`. Es
  correcto y trazable, pero si algún día se abre una minor del contrato, un
  `REVIEW_EPISTEMIC` canónico sería más limpio. **No se ha tocado nada.**


---

## 10. Ronda de correcciones tras la revisión independiente

Dictamen **NO CONFORME** sobre `cbbcab8`. La autoridad resistió los 41 ataques
del revisor (ninguna señal externa promovió jamás un `ACCEPT`; evidencia NFD,
NBSP y cruzada, toda cazada; 7/7 mutaciones suyas muertas), pero apareció un
agujero **bloqueante de alcance** y cinco hallazgos más. El diseño se mantuvo;
las correcciones son quirúrgicas.

| # | Hallazgo | Qué se hizo |
|---|---|---|
| **H1** | **BLOQUEANTE.** La contradicción solo se contrastaba contra el snapshot, nunca dentro del lote: `MEMBER_OF(daiki→casa)` y su negación en el mismo lote daban `[ACCEPT, ACCEPT]`, plan `approved: true` y `PASS` del validador congelado. También por la inversa (`MEMBER_OF` + `HAS_MEMBER` negada). La clave canónica era correcta; el fallo era de alcance. | (a) `contradiction.batch_conflicts` + `decision.apply_batch_contradictions`: pasada del lote contra sí mismo sobre la clave canónica, **antes** de construir el plan; los dos claims implicados a `REVIEW` con `CONFLICT_WITH_EXISTING`. Cubre negación opuesta, dirección invertida, predicado funcional y duplicado interno (que además producía dos `idempotency_key` iguales). (b) `planner.plan_is_self_consistent`: el validador interno `contradiction` comprueba las claves canónicas de las operaciones del propio plan. (c) tests con el par exacto del revisor y con la variante inversa, más dos mutantes. (d) docs §3.8 y docstrings de `contradiction.py` y `decision.py` corregidos: la promesa «una contradicción NUNCA se auto-aprueba» ya no se hace sin la salvedad. |
| **H2** | `LIVE_STATUSES` excluía `CONTRADICTED`, así que reafirmar un hecho que un humano había marcado como contradicho se aprobaba en silencio: bastaba reprocesar el asset para saltarse la cola. | `BLOCKING_STATUSES = LIVE_STATUSES ∪ {CONTRADICTED}` y `SnapshotAssertion.blocks_new_claims()`. Reafirmar cualquiera de las dos caras de un conflicto abierto → `REVIEW` · `REAFFIRMS_CONTRADICTED_ASSERTION`. `SUPERSEDED` y `RETRACTED` siguen fuera: son historia. Test con el escenario exacto y test de que la historia sigue siendo historia. |
| **H3** | El mínimo de confianza dejaba fuera la confianza del fragmento y la calidad del episodio: un claim de 0.99 con evidencia de 0.50 escribía `confidence: 0.99`. | `evidence.evidence_confidence()` entra en el mínimo, como el docstring ya prometía. Tests con el caso 0.99/0.50 y con la calidad de episodio. |
| **H4** | `EngineConfig` permitía `acceptable_epistemic_status={"RUMORED","UNKNOWN"}` con todos los umbrales a 0.0 → `ACCEPT` de un `RUMORED` a 0.05. | Dos cierres: `EngineConfig.__post_init__` rechaza conjuntos sin `ASSERTED` o con `UNKNOWN`/`CONFLICTED`; y `HARD_CONFIDENCE_FLOOR = 0.5` como invariante, por debajo de cualquier umbral configurable. Tests de las cuatro configuraciones rechazadas y del suelo duro. |
| **H5** | Una `ExternalSignal(step="engine.decide")` se colaba en el `provider_trace` del plan y la procedencia decía que Ollama produjo la decisión — sin romper ningún hash, porque el `provider_trace` no entra en el `decision_hash`. | `RESERVED_STEPS`: `ExternalSignal` lo rechaza en construcción y el planner renombra a `signal.<paso>` como defensa del lado del plan. Tests de ambos caminos (el segundo con una señal forjada vía `object.__setattr__`). |
| **H6** | `trace_entry()` no revalidaba el proveedor: un objeto `frozen` sigue siendo mutable con `object.__setattr__`. | Revalidación en `trace_entry()`, que es el punto por el que la señal entra en un documento firmado. Test. |
| — | El test de las diez decisiones acumulaba en un conjunto global: un escenario podía dejar de producir lo suyo tapado por otro. | Cada escenario atado a **su** `(decision, reason_code)` de `ENGINE_DECISION_MAP`, más una comprobación de que no falta ningún escenario. |

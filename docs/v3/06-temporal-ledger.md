# 06 — Ledger temporal V3

**Rama:** `feat/v3-temporal-ledger` · **Base:** `36439a2` (contratos congelados
`v3-contracts-frozen-1.0.0`)
**Ámbito:** `data-engine/app/knowledge_v3/ledger/`, tests
`data-engine/app/tests/test_knowledge_v3_ledger*.py`, este documento.
**No se ha tocado:** ningún contrato, ningún módulo V1/V2, `ci.yml`, `pytest.ini`,
producción ni Neo4j.

Este documento fija el **modelo bitemporal**, la **matriz de transiciones** y las
**garantías y límites** del ledger de `FactAssertion` exigido por la sección 7
del prompt maestro y por el §12 del dosier.

---

## 1. El principio, y todo lo que se deriva de él

> **Una afirmación nunca se muta. Todo cambio es una entrada nueva.**

De ahí sale el resto sin necesidad de más reglas:

| Propiedad | Por qué se cumple |
|---|---|
| Historia completa | nada se sobrescribe, luego nada se pierde |
| Rollback a cualquier `recorded_at` | el pasado sigue escrito; reconstruirlo es releer un prefijo |
| Cadena de custodia verificable | cada entrada sella la anterior por `prev_hash` |
| Auditoría del *por qué* | cada entrada lleva operación y `reason_code` canónico |
| Snapshot reproducible | el estado es función pura del prefijo del log |

El ledger es una **estructura lógica**. No importa ningún driver de base de
datos, no abre conexiones y no escribe en Neo4j: el respaldo del grafo es asunto
del writer y sólo a través de un `GraphMutationPlan` firmado. Un ledger que
supiera de Neo4j no podría probarse sin Neo4j, y entonces la garantía de
*append-only* dependería de un servidor en vez de del código.

Tampoco lee ningún reloj. Todos los instantes entran como dato desde fuera
(`test_the_ledger_never_reads_a_clock` lo comprueba sobre el código fuente). Un
ledger que se pusiera la hora solo dejaría de ser reproducible.

---

## 2. Dónde vive cada cosa

| Pieza | Fichero |
|---|---|
| Motor del ledger (5 operaciones, integridad, vistas) | `ledger/assertions.py` |
| Matriz de transiciones, motivos canónicos, derivación de versiones | `ledger/supersession.py` |
| Entrada inmutable + encadenado por hash | `ledger/entries.py` |
| Interfaz de almacén + memoria + JSONL append-only | `ledger/store.py` |
| Consultas bitemporales (`LedgerView`) | `ledger/temporal.py` |
| `GraphSnapshot` determinista | `ledger/snapshots.py` |
| Proyección a aristas directas | `ledger/projection.py` |
| Orden total de instantes ISO-8601 | `ledger/timeline.py` |
| Errores del subsistema | `ledger/errors.py` |
| Tests (116) | `data-engine/app/tests/test_knowledge_v3_ledger.py`, `..._mutation.py` |

---

## 3. Modelo bitemporal (en realidad, tres ejes)

El contrato congelado `fact-assertion/v3-internal-v1` trae los tres, separados a
propósito. El ledger los mantiene separados; mezclarlos es el error clásico.

| Eje | Campo | Pregunta que responde | Consulta |
|---|---|---|---|
| **Tiempo de transacción** | `recorded_at` | ¿qué **sabía el sistema** el día T? | `view(as_of=T)` / `rollback_to(T)` |
| **Tiempo de validez** | `valid_from` / `valid_to` | ¿qué **era cierto en el mundo** el día t? | `valid_at(t)` |
| **Tiempo del evento** | `event_time` | ¿**cuándo ocurrió** el hecho narrado? | `by_event_time(inicio, fin)` |

Los dos primeros son ortogonales y se **cruzan**:

```python
ledger.valid_at("1015-01-01T00:00:00Z", as_of="2026-01-01T00:00:00Z")
```

«Qué creía el sistema en enero de 2026 sobre lo que era cierto en el año 1015».
Ese cruce es lo que permite auditar una decisión pasada sin que el conocimiento
posterior la contamine: si el motor decidió mal en enero, la pregunta correcta no
es qué sabemos hoy, sino qué sabía él entonces.

`event_time` **no** es un sinónimo de `valid_from`. Un juramento ocurre en un
instante (`event_time`) y su efecto dura años (`valid_from`..`valid_to`); el test
`test_event_time_is_a_third_axis` fija esa diferencia con un caso concreto.

### Convenciones que hubo que decidir

| Decisión | Cuál es | Por qué |
|---|---|---|
| Intervalo de vigencia | **semiabierto** `[valid_from, valid_to)` | si una versión cierra en T y la siguiente empieza en T, un intervalo cerrado devolvería **dos verdades simultáneas** para el mismo instante |
| Ventana de `event_time` | **cerrada** `[inicio, fin]` | aquí se pregunta por eventos puntuales; excluir el extremo dejaría fuera justo el evento buscado |
| `valid_from = null` | **no** cuenta como vigente (salvo `include_unknown_start=True`) | `null` significa «inicio desconocido», no «desde siempre». Afirmar vigencia a partir de un dato que no existe es inventar |
| Orden de instantes | por **tupla parseada**, nunca por comparación de cadenas | el contrato admite fracción de segundo, y `"…:00Z" > "…:00.5Z"` en orden lexicográfico: un ledger que ordenase así invertiría la historia en silencio |
| Fechas del mundo | **no** se convierten a `datetime` | `calendar_id` puede expresar años como `1041`; sólo se necesita orden total, no aritmética de calendario |
| `recorded_at` | **monótono no decreciente**, comprobado al escribir y al verificar | un hecho conocido tarde con validez pasada se expresa con `valid_from`/`event_time`, **nunca** retrasando `recorded_at` |

---

## 4. Estructura del ledger

### 4.1. Entrada (`LedgerEntry`)

```yaml
seq:                     # 0,1,2… sin huecos
entry_id:                # ledger:<workspace>:<seq 8 dígitos>, determinista
operation:               # ASSERT | CONFIRM | SUPERSEDE | CONTRADICT | RETRACT
recorded_at:             # tiempo de transacción de ESTA entrada
workspace:               # aislamiento duro
assertion_id: / revision:# identidad del registro + nº de versión (1, 2, 3…)
assertion:               # documento fact-assertion COMPLETO tras la operación
related_assertion_ids:   # la otra parte (supersesión, contradicción)
reason_code:             # motivo canónico, cerrado por operación
prev_hash: / entry_hash: # cadena de custodia
```

El documento se guarda **entero**, no como delta. Un delta obliga a reconstruir
para leer, y una reconstrucción con un bug reescribe la historia sin que nadie
se entere.

### 4.2. Registro, versión y revisión

Hay dos niveles y conviene no confundirlos:

- **`assertion_id`** identifica un *registro de hecho*. Es lo que enlaza
  `supersedes` / `superseded_by` en el contrato congelado.
- **`revision`** es el número de entrada de ese registro dentro del ledger. Es
  lo que alimenta `expected_version` del `GraphMutationPlan`.

Confirmar una afirmación **no** crea un `assertion_id` nuevo: crea la revisión 2
del mismo. Superarla **sí** crea un `assertion_id` nuevo, porque el contrato
modela la supersesión como un enlace entre **dos** registros
(`assertion:0000 --superseded_by--> assertion:0001` en los propios ejemplos
congelados).

### 4.3. Almacenamiento

`LedgerStore` es abstracto: `append` + `read_all`, y **no existe** `update`,
`delete` ni `truncate` (`test_the_ledger_exposes_no_update_or_delete`). Dos
implementaciones:

- `InMemoryLedgerStore` — para el motor y los tests. Guarda y devuelve **copias
  profundas**: mutar lo que lees no puede alterar lo almacenado.
- `JsonlLedgerStore` — fichero JSONL append-only, una entrada por línea en JSON
  canónico. El fichero **sólo** se abre en modo `"a"`, y hay un test que lo
  comprueba leyendo el código fuente de la clase.

---

## 5. Las cinco operaciones

Todas son aditivas. No hay ninguna otra forma de cambiar nada.

| Operación | Qué hace | Entradas que añade |
|---|---|---|
| `assert_fact` | registra una afirmación nueva | 1 |
| `confirm` | evidencia adicional refuerza la **misma identidad** | 1 |
| `supersede` | una versión nueva cierra la vigencia de la anterior | **2** |
| `contradict` | marca **dos** afirmaciones en conflicto, sin destruir nada | **2** |
| `retract` | retira una afirmación, con motivo obligatorio | 1 |

### 5.1. `assert_fact`

Rechaza, con error explícito: nacer en un `status` que no sea `PROVISIONAL` o
`ASSERTED`; nacer ya superada; `recorded_at` que retrocede; workspace ajeno; y
**duplicar una identidad lógica ya viva**.

La identidad lógica es
`(workspace, collection_id, subject, predicate, object, direction, negated, valid_from)`.
Repetir un hecho ya vivo es **confirmarlo**, no registrarlo dos veces; el ledger
lo dice y remite a `confirm`. `valid_from` entra en la identidad porque «miembro
desde 1041» y «miembro desde 1050» son hechos distintos, no una repetición. Hay
una salida explícita (`allow_duplicate_identity=True`) para cuando de verdad son
dos registros.

### 5.2. `confirm`

Exige **evidencia realmente nueva**: confirmar con los mismos fragmentos que ya
sostenían la afirmación no añade información, sólo sube el estado. Y la confianza
**no puede bajar** en una confirmación; si baja, lo que hay es una contradicción
o una supersesión, no un refuerzo.

El ledger **no inventa confianzas**: no hay fórmula de refuerzo. El valor lo
aporta quien confirma; el ledger sólo impide que descienda.

### 5.3. `supersede`

Escribe **dos** entradas con el **mismo `recorded_at`**: la versión nueva y el
cierre de la anterior. Al compartir instante de transacción, la supersesión es
**atómica para cualquier consulta as-of**: no existe ningún T en el que se vea la
nueva sin la vieja cerrada (`test_supersede_is_atomic_in_transaction_time`).

Cierre de la anterior: `status = SUPERSEDED`, `superseded_by = <nuevo id>`,
`valid_to` cerrado y `state` de `ACTIVE` a `ENDED`.

- `valid_to` por defecto es el `valid_from` de la versión nueva: el hecho
  anterior deja de valer justo cuando empieza el siguiente. Si la nueva no tiene
  `valid_from`, hay que **darlo explícitamente**; deducirlo sería inventar la
  fecha en la que algo dejó de ser cierto.
- Una vigencia **ya cerrada no se mueve**. Desplazarla sería reescribir el pasado
  con otro nombre, así que es un error, no un ajuste silencioso.
- `state` sólo cambia de `ACTIVE` a `ENDED`, porque el contrato prohíbe `ACTIVE`
  con `valid_to`. `PLANNED`, `RECURRING` o `HYPOTHETICAL` se **conservan**: el
  ledger no tiene información para reclasificar el eje temporal de un hecho.
- Si el cierre no es posible, **no queda una versión nueva huérfana**: la
  comprobación se hace antes de escribir nada
  (`test_a_failed_supersession_leaves_nothing_behind`).

### 5.4. `contradict`

Marca las dos partes con `status = CONTRADICTED` y `epistemic_status =
CONFLICTED`, y **las dos siguen vivas y consultables**. El sistema no elige
ganador por su cuenta. Resolver el conflicto es una decisión posterior —
confirmar una, superarla, retractar la otra — y cada ruta deja su propia entrada.

> **Nota de vocabulario.** El prompt pide «marcar `CONFLICTED` ambas partes». En
> el contrato congelado esos son **dos campos**: el ciclo de vida es
> `status = CONTRADICTED` y el estatus epistémico es
> `epistemic_status = CONFLICTED`. El ledger fija **los dos**, que es lo que hace
> el ejemplo congelado `fact_assertion_conflicted.json`.

### 5.5. `retract`

El motivo es **obligatorio** y pertenece a un catálogo cerrado. Retractar **no
borra**: la afirmación y todas sus revisiones siguen en el ledger; lo que cambia
es que deja de contar como conocimiento vigente.

### 5.6. Motivos canónicos (cerrados por operación)

| Operación | `reason_code` admitidos |
|---|---|
| `ASSERT` | `INITIAL_ASSERTION`, `NEW_EVIDENCE`, `REINSTATED_AFTER_REVIEW` |
| `CONFIRM` | `CORROBORATING_EVIDENCE`, `SECOND_SOURCE`, `HUMAN_REVIEW_CONFIRMED` |
| `SUPERSEDE` | `SUPERSEDED_BY_NEWER`, `VALIDITY_CLOSED`, `CORRECTED_EXTRACTION` |
| `CONTRADICT` | `CONTRADICTORY_EVIDENCE`, `MUTUALLY_EXCLUSIVE_FACTS`, `CONFLICTING_SOURCES` |
| `RETRACT` | `EXTRACTION_ERROR`, `EVIDENCE_INVALID`, `SOURCE_WITHDRAWN`, `OPERATOR_RETRACTION`, `COPYRIGHT_TAKEDOWN` |

Mismo criterio que `CANONICAL_REASON_CODES` del validador de contratos: un motivo
de texto libre convierte la auditoría del ledger en prosa no agregable.

---

## 6. Matriz de transiciones de `status`

**Cerrada**: lo que no está explícitamente permitido, se rechaza. Una matriz por
lista negra deja colarse transiciones nuevas por omisión cada vez que alguien
añade un estado.

| Desde \ Hacia | PROVISIONAL | ASSERTED | CONFIRMED | LIMITED | SUPERSEDED | CONTRADICTED | RETRACTED |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| *(creación)* | ✅ | ✅ | — | — | — | — | — |
| PROVISIONAL | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ASSERTED | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| CONFIRMED | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| LIMITED | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| CONTRADICTED | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| **SUPERSEDED** | — | — | — | — | — | — | — |
| **RETRACTED** | — | — | — | — | — | — | — |

Lecturas que conviene hacer explícitas:

- **`SUPERSEDED` y `RETRACTED` son terminales.** Una versión ya sustituida no se
  retracta ni se confirma: quien quiera corregirla actúa sobre la **cabeza** de
  la cadena, que es la versión vigente. Permitir tocar el pasado convertiría la
  cadena en un grafo con dos verdades simultáneas.
- **No se retrocede a `PROVISIONAL` ni de `CONFIRMED` a `ASSERTED`.** Degradar un
  estado sin dejar rastro del motivo es exactamente lo que el ledger evita; si
  la confianza baja, es una contradicción o una supersesión.
- **`CONFIRMED → CONFIRMED` y `CONTRADICTED → CONTRADICTED` sí valen**: una
  segunda corroboración y un segundo conflicto son hechos nuevos, y cada uno deja
  su entrada.
- **`CONFIRMED` está prohibido sobre `state = PLANNED`** — no es una regla del
  ledger, es del contrato congelado (un hecho planificado aún no ha ocurrido). El
  ledger la comprueba antes para dar un error legible en vez de un fallo de
  schema.

### Estados «vivos»

`PROVISIONAL`, `ASSERTED`, `CONFIRMED`, `LIMITED` y **`CONTRADICTED`**.

`CONTRADICTED` está dentro a propósito: una contradicción **no destruye nada**, y
un hecho en conflicto es conocimiento que el motor debe ver y decidir, no algo
que deba encontrarse desaparecido. `GraphSnapshot` lo expone por separado en
`conflicted_assertion_ids` para que el motor pueda exigir revisión.

---

## 7. `GraphSnapshot`: el ancla de los planes

Es lo que el motor cita en `graph-mutation-plan/v3-internal-v1.snapshot_id` y lo
que da sentido a `expected_version`/`expected_hash`. Sin ancla, «la versión
esperada» es una afirmación sobre un grafo que ya nadie sabe cuál era, y dos
planes concurrentes no se pueden ordenar.

```text
snapshot:sha256:<64 hex de sha256(canonical_json(contenido))>
```

- **Determinista por contenido.** Mismo ledger → mismo `snapshot_id`, aunque uno
  esté en memoria y otro en fichero
  (`test_two_ledgers_with_the_same_content_share_the_snapshot_id`).
- **`as_of` es metadato, no identidad.** Dos snapshots del mismo estado tomados
  en momentos distintos tienen el **mismo** id. Es lo correcto para concurrencia
  optimista: si nada ha cambiado, el plan sigue siendo aplicable.
- **Versión por afirmación** = su `revision`. **Versión por entidad** = suma de
  las revisiones de las afirmaciones que la tocan, y el hash cubre
  `(assertion_id, revision, status)` de todas ellas.
- Las versiones de entidad cuentan afirmaciones **vivas y no vivas**. Si una
  supersesión no moviera la versión de la entidad, un plan calculado antes de esa
  supersesión pasaría el control optimista y escribiría sobre un estado que ya no
  existe: exactamente el fallo que la concurrencia optimista debe impedir.
- Lo que no existe se declara `(None, None)`, que es justo lo que el contrato
  exige en una operación de creación.

---

## 8. Rollback

```python
vista = ledger.rollback_to("2026-01-10T09:00:00Z")
ancla = ledger.snapshot("2026-01-10T09:00:00Z").snapshot_id
```

`rollback_to` **es** `view`: el mismo método, con dos nombres. Reconstruir el
pasado y consultar el pasado son la misma operación; si fuesen dos caminos de
código distintos, uno de los dos acabaría mintiendo.

Se reconstruye **sólo con el ledger**. `test_rollback_needs_nothing_but_the_ledger_file`
destruye el objeto, reabre el fichero JSONL desde cero y comprueba que el
`snapshot_id` de entonces se reproduce exactamente. No hace falta ninguna copia
de seguridad externa, ninguna tabla auxiliar y ningún estado del grafo.

Un rollback **no borra nada**: devuelve una vista del pasado. Si se quisiera
volver a ese estado de verdad, el camino es emitir las operaciones inversas —que
también quedan escritas—, no recortar el log.

---

## 9. Integridad de la cadena de custodia

`verify_chain()` recalcula desde el génesis y comprueba, en este orden:

1. numeración `seq` sin huecos ni desorden;
2. workspace de cada entrada;
3. enlace `prev_hash` con la entrada anterior;
4. `entry_hash` recalculado sobre el contenido;
5. monotonía del tiempo de transacción;
6. revisiones consecutivas por `assertion_id`;
7. coherencia entrada/documento (`assertion_id` y `recorded_at` no pueden
   discrepar);
8. opcionalmente (`validate_documents=True`), cada documento contra el contrato
   congelado.

Se ejecuta **al cargar** un ledger existente, salvo que se pida lo contrario.

Editar una entrada antigua rompe su `entry_hash`; recalcularlo rompe el
`prev_hash` de la siguiente. **No hay retoque local posible**: o se reescribe el
ledger entero, o la verificación cae. Las dos rutas están probadas
(`test_editing_an_old_entry_breaks_the_verification`,
`test_editing_an_old_entry_and_resealing_it_breaks_the_next_link`), junto con
borrado, reordenación, línea ilegible, campos desconocidos, revisión falseada,
workspace ajeno y retroceso del tiempo de transacción.

---

## 10. Garantías

1. Ninguna afirmación se muta: los documentos entran, salen y se guardan como
   copias; mutar lo devuelto no llega al ledger.
2. Toda la historia es recuperable: `history(assertion_id)` devuelve todas las
   revisiones, y ninguna operación reduce el número de entradas.
3. El estado a cualquier `recorded_at` pasado se reconstruye sólo con el ledger.
4. Toda edición, inserción, reordenación o borrado **interior** del log se
   detecta.
5. Toda transición de `status` fuera de la matriz se rechaza con error explícito.
6. Todo documento que sale del ledger cumple el contrato congelado: se valida
   antes de escribir, y un documento inválido **nunca llega al almacén**.
7. Snapshot determinista y reproducible entre backends de almacenamiento.
8. Aislamiento duro de workspace: un ledger es de un workspace, y no hay
   parámetro que permita mezclar bóvedas.
9. Ningún reloj, ningún proveedor, ninguna escritura en Neo4j.

---

## 11. Límites, dichos sin adornos

| Límite | Detalle |
|---|---|
| **Truncado del final** | Cortar limpiamente las últimas líneas deja una cadena **válida**: el prefijo de un log encadenado sigue siendo un log encadenado. Lo que lo delata es el `snapshot_id`, que ya no se puede reproducir. Está probado como límite (`test_truncating_the_tail_is_detected_by_the_snapshot_not_by_the_chain`), no disimulado. Cerrarlo del todo exige un ancla externa (sello firmado, testigo o `seq` esperado persistido fuera). |
| **Verificable, no autenticado** | El hash demuestra que el contenido no ha cambiado; **no** demuestra quién lo escribió. Quien tenga permiso de escritura sobre el fichero puede reescribir el ledger entero y sellarlo de nuevo. La firma criptográfica real está reservada en el contrato (`signature`/`key_id` de `local_approval`) y **no se usa todavía**; el ledger no la suple. |
| **Concurrencia de escritura** | Un solo escritor. `JsonlLedgerStore` no toma bloqueo de fichero: dos procesos escribiendo a la vez pueden entrelazar `seq` y romper la cadena. La verificación lo **detecta**, pero no lo previene. |
| **Coste lineal de lectura** | `read_all` recorre el log completo en cada operación; el estado no está materializado en un índice. Es correcto y verificable, pero no está pensado para millones de entradas sin añadir antes snapshots persistidos. |
| **`event_time` no se cruza con el eje de transacción** | `by_event_time` opera sobre una vista ya fijada; no hay una consulta tritemporal en un solo paso. No hace falta hoy y añadirla sin caso de uso sería adivinar. |
| **La proyección no es autoridad** | `projection.py` produce estructuras planas, nunca escribe. Materializarlas es trabajo del writer y sólo mediante un plan firmado. |
| **El motivo de retracción vive en la entrada, no en el documento** | El contrato congelado de `fact-assertion` **no tiene campo de motivo**. El `reason_code` va en la entrada del ledger, que es la estructura propia de este subsistema. Consecuencia: un `FactAssertion` proyectado a Neo4j **pierde el motivo**; quien lo necesite tiene que consultar el ledger. Se documenta como carencia del contrato, no se disimula duplicando el dato en `metadata` — dos copias divergen. |
| **Sin corpus** | Este subsistema no produce ninguna métrica de calidad de extracción. Aquí no hay nada que medir contra un held-out: son invariantes, y se demuestran con tests, no con porcentajes. |

---

## 12. Pruebas

```bash
python3 -m pytest data-engine/app/tests/test_knowledge_v3_ledger.py \
                 data-engine/app/tests/test_knowledge_v3_ledger_mutation.py -q
```

| Fichero | Tests | Cubre |
|---|---:|---|
| `test_knowledge_v3_ledger.py` | 79 | entradas y almacén, ASSERT, CONFIRM, SUPERSEDE, CONTRADICT, RETRACT, ciclo completo, matriz de transiciones, bitemporalidad, snapshot, rollback, proyección |
| `test_knowledge_v3_ledger_mutation.py` | 37 | manipulación de entradas antiguas, borrado/reordenación/inserción, entradas fabricadas a mano, ausencia de mutación in-place, matriz que no se afloja por la puerta de atrás |
| **Total** | **116** | |

Las fixtures son **propias** del ledger: no se importan las de
`contracts/knowledge-v3/v1/tests/`, para que un cambio en el subsistema de
contratos no ponga esto en rojo por un motivo ajeno. El documento base que
construyen se valida contra el contrato congelado en el primer test del fichero.

Suite completa del repositorio tras el trabajo: **4290 pasados, 5 saltados**, sin
regresiones.

---

## 13. Lo que este subsistema NO hace

- No escribe en Neo4j ni conoce ningún driver.
- No genera timestamps ni identificadores aleatorios.
- No llama a Ollama ni a ningún proveedor externo.
- No decide: no elige ganador en una contradicción, no calcula confianzas y no
  aprueba nada. Decidir es del motor local; escribir, del writer con plan firmado.
- No modifica contratos, V1, V2, `ci.yml` ni `pytest.ini`.

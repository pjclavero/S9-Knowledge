# 09 — Writer V3

**Rama:** `feat/v3-review-writer` · **Base:** `5f3cd67` (los siete subsistemas
mergeados)
**Ámbito:** `data-engine/app/knowledge_v3/writer/`, tests
`data-engine/app/tests/test_knowledge_v3_writer*.py`

El writer es **la única puerta física al grafo**. Todo lo demás del sistema
—multimodal, extractor, resolución, motor local, ledger temporal, proveedores—
existe para que este bloque solo acepte lo legítimo. Su única entrada admisible
es un `GraphMutationPlan` sellado por el motor local. No interpreta, no corrige,
no consulta modelos y no arregla planes casi correctos: los rechaza con un
código.

---

## 1. Arquitectura: tres capas y un orden que importa

```text
                plan (dict JSON)          petición del operador
                       │                            │
                       ▼                            │
        ┌──────────────────────────────┐            │
        │ ADMISIÓN  (admission.py)     │            │
        │ ¿es un plan legítimo, mío,   │            │
        │ vigente y sobre este estado? │            │
        │ SIEMPRE, también en dry-run  │            │
        └──────────────┬───────────────┘            │
                       │ SignedView                 │
                       ▼                            ▼
        ┌──────────────────────────────────────────────┐
        │ GATE DE OPERADOR  (gate.py)                  │
        │ nueve condiciones · solo bloquea el APPLY    │
        └──────────────┬───────────────────────────────┘
                       │
          ┌────────────┴─────────────┐
          ▼                          ▼
   DRY-RUN (por defecto)      APPLY (explícito)
   simulate_plan()            execute_plan()
   NO recibe el driver        una transacción, todo o nada
          │                          │
          └────────────┬─────────────┘
                       ▼
        AUDITORÍA JSONL append-only (todo intento)
```

El orden no es decorativo:

- La **admisión** se ejecuta siempre, también en dry-run. Simular un plan
  inadmisible sería prestarle credibilidad: el informe de simulación es
  exactamente lo que un operador lee antes de autorizar.
- El **gate** solo bloquea el APPLY. El dry-run no necesita permiso porque es
  seguro por construcción — literalmente no recibe el driver.
- La **ejecución** es transaccional. Si aborta, no queda nada escrito.

### 1.1. `SignedView`: la prohibición del contrato, hecha estructura

El contrato congelado dice que `created_at`, `plan_id`, `provider_trace` y
`metadata` quedan **fuera del `decision_hash`**: alterarlos no rompe ningún
hash, así que cualquier decisión basada en ellos sería manipulable sin dejar
rastro.

Prohibirlo con una nota en la documentación es confiar en que alguien la lea.
Aquí se prohíbe con la estructura: la admisión produce un `SignedView` que **no
contiene esos cuatro campos**, y el gate y el ejecutor solo reciben el view. No
es que no deban leerlos: es que no los tienen.

Y para que ese argumento se sostenga, los cuatro campos **sí se conservan**, en
el bloque `unsigned` de cada línea de auditoría. Si tampoco quedaran ahí, la
justificación sería «no los usamos» en vez de «los usamos solo para contar lo
que pasó», y se perdería la única traza de que un plan venía con una
`provider_trace` sospechosa. Describir sin decidir exige seguir describiendo.

### 1.2. Un writer, un workspace (R3 del ledger)

`GraphWriter` fija su `workspace` en el constructor y no admite cambiarlo por
petición: el aislamiento no es un parámetro. El plan tiene que ser de ese
workspace (admisión), el argumento de la CLI tiene que ser ese workspace y la
variable de entorno también (gate). Tres declaraciones que deben coincidir.

`JsonlLedgerStore` no toma bloqueo de fichero, así que la exclusión mutua real
—un proceso por workspace— sigue siendo responsabilidad del despliegue. Ver §6.

### 1.3. Requisitos que el ledger impuso (§11.1 de `06-temporal-ledger.md`)

| Requisito | Cómo se cumple |
|---|---|
| **R1** — el motivo viaja al grafo | Toda operación de cierre de vigencia (`UPDATE_ENTITY`, `SUPERSEDE_ASSERTION`) exige `payload.reason_code`; sin él el plan se aborta con `EXEC_REASON_CODE_MISSING`. Además, todo lo creado lleva los `reason_codes` de su decisión. |
| **R2** — el `snapshot_id` se conserva fuera del ledger | Queda en tres sitios: como propiedad `written_snapshot_id` de lo escrito, en el almacén persistente de claves aplicadas y en el registro de auditoría. Y el operador debe declararlo (`--snapshot`) para que el plan sea admisible. |
| **R3** — un solo escritor por workspace | `GraphWriter` es por workspace y lo comprueba en admisión y gate. La exclusión mutua entre procesos es del despliegue. |

---

## 2. El gate completo: nueve condiciones

Adaptación del gate V1 (`review/controlled_ingest/policy.py`) a un plan sellado.
La forma se conserva porque funciona: **si falta UNA sola condición, no se
escribe**. Lo que cambia es el reparto: allí el permiso lo daba el estado del
plan de revisión; aquí el plan ya viene sellado y la admisión lo ha juzgado, así
que el gate se ocupa solo de lo que aporta el **operador**.

| # | Condición | Cómo se declara | Código si falla |
|---|---|---|---|
| 1 | El entorno permite escritura real | `S9K_ALLOW_REAL_INGEST=1` (exactamente `1`) | `GATE_ENV_NOT_ALLOWED` |
| 2 | APPLY pedido explícitamente | `--apply` / `OperatorRequest(apply=True)` | `GATE_APPLY_NOT_REQUESTED` |
| 3 | Hay operador | `--operator` | `GATE_OPERATOR_MISSING` |
| 4 | El operador tiene forma admisible | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` | `GATE_OPERATOR_INVALID` |
| 5 | El operador confirma el hash del plan **tecleado de fuera** | `--expect-plan-hash <sha256>` | `GATE_PLAN_HASH_NOT_CONFIRMED` |
| 6 | El plan cabe en el límite de operaciones | `--max-operations` y/o el del writer; **manda el menor de los dos** | `GATE_OPERATION_LIMIT_EXCEEDED` |
| 7 | El workspace está declarado dos veces | `S9K_WRITER_WORKSPACE` | `GATE_WORKSPACE_NOT_DECLARED` |
| 8 | Las dos declaraciones coinciden | entorno == `--workspace` == writer | `GATE_WORKSPACE_DECLARATION_MISMATCH` |
| 9 | Hay registro de auditoría utilizable | `--audit-log` escribible | `GATE_AUDIT_UNAVAILABLE` |

**Modo por defecto: dry-run.** Sin `--apply` no se abre siquiera el driver. La
escritura real exige argumento explícito *y* variable de entorno: dos gestos
independientes, uno en la línea de órdenes y otro en el entorno del proceso.

**Sobre la condición 6.** El límite del writer es política del despliegue y el de
la petición es del operador; ninguno puede relajar al otro, así que se aplica el
**menor de los dos**. Por eso `OperatorRequest.max_operations` vale `None` por
defecto y no 200: sin ese `None` el writer no podría distinguir «el operador pide
200» de «el operador no ha dicho nada», y su propio límite sería decorativo.

### 2.1. Lo que el listón V1 tenía y aquí no

Tres condiciones de `evaluate_apply` no tienen equivalente V3. Se dicen en vez de
dejar creer que la adaptación es una equivalencia:

| Condición V1 | Por qué no está |
|---|---|
| `operator_id` atado a la autorización **del plan** (`auth.operator_id`) | El `GraphMutationPlan` congelado **no lleva identidad del aprobador humano**: `local_approval.approved_by` identifica el *motor*, no a la persona. Consecuencia real y no disimulada: **cualquier operador que pase el gate puede aplicar cualquier plan sellado**; el plan no dice para quién es. Atarlo exigiría un `1.1.0` de contratos o un canal de autorización fuera del plan. |
| `production_env` explícito | Se juzgó redundante: `S9K_ALLOW_REAL_INGEST=1` ya es la afirmación «esto es un entorno donde se escribe de verdad», y dos banderas que significan lo mismo acaban puestas las dos por costumbre. Es una decisión, no un descuido. |
| El segundo hash (`review_hash`) | En V1 el plan y la revisión eran documentos separados y hacían falta dos hashes. En V3 el `decision_hash` ya cubre decisiones, operaciones, aprobación y cadena de validadores: un segundo hash sobre lo mismo no añadiría nada. |

**Divergencia de literal, dicha claramente:** el V1 exige
`S9K_ALLOW_REAL_INGEST=true` y el V3 exige `=1`. Conviven en el repositorio y
**no son intercambiables**: un `true` no habilita el writer V3 y un `1` no
habilita la ingesta V1. Es incómodo a propósito — que un valor no active los dos
caminos por accidente —, pero quien opere las dos rutas tiene que saberlo.

---

## 3. Ejecución

### 3.1. Transaccional, todo o nada

Una sola transacción para el plan entero. Cualquier fallo —driver, precondición,
payload— la aborta completa. No existe «se aplicaron 3 de 5»: un plan a medias
deja el grafo en un estado que ningún snapshot describe.

### 3.2. Concurrencia optimista

Cada operación que toca algo existente lee `version` y `state_hash` del destino
y los compara con `expected_version` y `expected_hash`. Un solo desajuste aborta
**el plan entero**, no solo esa operación: si el grafo se movió bajo el plan, el
resto de operaciones tampoco se calcularon sobre este estado.

### 3.3. Idempotencia real

Una `idempotency_key` ya registrada como aplicada es un **no-op contabilizado**
que ni siquiera llega al driver. Las claves se registran **después del commit**:
marcarlas antes perdería para siempre una operación que la transacción acabó
revirtiendo.

El almacén es inyectable y persistente (`JsonlAppliedKeys`). Dicho sin adornos:
**la idempotencia vive en ese almacén**. Si alguien lo borra, el writer vuelve a
escribir. Hay un test que lo documenta en vez de disimularlo.

### 3.4. CREATE-only y cierre de vigencia

Heredado de `review/ingest_approved.py`, que ya demostró servir:

- **Nunca `MERGE`.** Un MERGE ciego crea o pisa según el estado del grafo, y esa
  ambigüedad es justo la que un plan sellado viene a eliminar.
- **Nunca `SET n = $props` ni `SET n += $props`.** Las creaciones llevan las
  propiedades en el propio patrón `CREATE (n:Label $props)`; no hay una sola
  asignación masiva en todo el módulo.
- **Cierre de vigencia, no borrado.** Lo que deja de valer se marca. No hay un
  solo `DELETE`, `DETACH` ni `REMOVE`, y las propiedades que un cierre puede
  tocar están en una lista blanca (`ALLOWED_UPDATE_PROPS`).
- **Etiquetas y tipos de relación validados** contra `^[A-Z][A-Za-z0-9_]{0,63}$`:
  son lo único que Cypher no admite parametrizado. Todo lo demás viaja como
  parámetro.
- `assert_safe()` vuelve a leer cada consulta ya construida y la bloquea si
  contiene una construcción destructiva. Es redundante a propósito: es la red
  que atrapa al próximo que añada un builder con prisa.

Operaciones soportadas: `CREATE_ENTITY`, `CREATE_ASSERTION`, `LINK_EXISTING`,
`PROJECT_RELATION`, `UPDATE_ENTITY`, `SUPERSEDE_ASSERTION`.

### 3.5. Procedencia que se estampa en todo lo escrito

`workspace`, `written_snapshot_id`, `written_by_plan_hash`,
`written_by_operator`, `written_at`, `idempotency_key`, `decision_id`,
`reason_codes`, `evidence_fragment_ids`, `source_asset_id`, `collection_id`,
`engine_version`, `ontology_version`, `game_profile`. Son propiedades
**reservadas**: un payload que intente fijarlas aborta el plan con
`EXEC_UNSUPPORTED_PAYLOAD`. La procedencia la escribe el writer, no el plan.

---

## 4. Rollback

Dos cosas distintas que la palabra suele mezclar, y aquí no se mezclan:

- **Aborto a mitad** — lo resuelve la transacción: si algo falla, no se escribe
  nada. No hay que deshacer porque no se hizo. Probado con un driver que revienta
  en la operación N: `commit` no se llama, `rollback` sí, y el almacén de claves
  queda vacío.
- **Deshacer un plan ya confirmado** — eso ya no es transaccional. El writer
  registra qué escribió (`AppliedOperation`) y genera un `RollbackDocument` con
  las instrucciones inversas en **orden inverso** (las aristas antes que los
  nodos que unen).

El writer **no ejecuta** el rollback. Deshacer es una decisión de operador, y
además las instrucciones inversas incluyen borrados — exactamente lo que este
subsistema tiene prohibido hacer sin plan. Lo que sale es un documento que un
operador lee, aprueba y aplica, o que el motor local convierte en un plan inverso
y vuelve a sellar.

### 4.1. Identidad durable: el rollback tiene que sobrevivir a un restore

Un documento de rollback se **guarda para aplicarse después**, y ese "después"
suele incluir haber restaurado la base. El `elementId` de Neo4j **contiene el
UUID de la base de datos**: al restaurar un volcado se regenera. Una instrucción
que dependiese de él dejaría de ser ejecutable justo en el momento en que hace
falta.

Por eso ninguna instrucción se localiza por `elementId`:

| Acción | Cómo se localiza el objetivo |
|---|---|
| `DELETE_NODE` | `(workspace, entity_id \| assertion_id)` + `idempotency_key`. |
| `DELETE_RELATIONSHIP` | `(workspace, sujeto, predicado, objeto)` + `idempotency_key` de la operación que la escribió. |
| `RESTORE_PROPERTIES` | `(workspace, target_id)` + el estado previo leído. |

El `elementId` que devolvió la escritura sigue viajando en el detalle, pero con
el nombre que le corresponde — `element_id_at_write` — y **como dato
informativo**: `rollback_query()` lo ignora. El `idempotency_key` es lo que
impide **borrar de más**: acota el borrado a la arista que escribió *ese* plan,
aunque existan otras entre los mismos extremos y con el mismo predicado.

`rollback_query(instruccion)` traduce una instrucción a Cypher ejecutable. Es
deliberadamente un tipo distinto de `cypher.Query` (que prohíbe `DELETE`, porque
el writer no borra): quien la ejecuta está ejercitando el camino de
recuperación, y eso tiene que verse en el código. Si a una instrucción le falta
identidad de dominio, la función levanta `RollbackNotReconstructible` en vez de
producir una consulta que borraría cualquier cosa, y el documento ya lo declara
en `unrecoverable`.

**Límite dicho sin adornos:** el rollback de un cierre de vigencia solo puede
restaurar `version` y `state_hash`, que es lo que el writer leyó antes de
escribir. Las propiedades previas que no leyó no las puede devolver, y el
documento lo declara en `unrecoverable` en vez de fingir que puede.

---

## 5. Flujo operativo real

### 5.1. Simular (siempre primero)

```bash
cd data-engine/app
python -m knowledge_v3.writer.cli /ruta/plan.json \
    --workspace leyenda \
    --snapshot snapshot:neo4j:2026-07-27T10:29:00Z \
    --audit-log /var/lib/s9k/writer_audit.jsonl \
    --applied-keys /var/lib/s9k/writer_applied_keys.jsonl
```

Sin `--apply` no se resuelve configuración de conexión ninguna: ni URI, ni
usuario, ni secreto. El dry-run sigue siendo el modo seguro. La salida es un JSON con `outcome`
(`SIMULATED` o `REJECTED`), los códigos de rechazo y el recuento de operaciones
que se aplicarían y de las que ya serían no-op.

### 5.2. Aplicar de verdad

```bash
S9K_ALLOW_REAL_INGEST=1 \
S9K_WRITER_WORKSPACE=leyenda \
python -m knowledge_v3.writer.cli /ruta/plan.json \
    --workspace leyenda \
    --snapshot snapshot:neo4j:2026-07-27T10:29:00Z \
    --operator pjc \
    --expect-plan-hash af2ee14ff3100e51b809706f531dbab051040d54f4f8e9aae82f48b483a7c428 \
    --max-operations 50 \
    --audit-log /var/lib/s9k/writer_audit.jsonl \
    --applied-keys /var/lib/s9k/writer_applied_keys.jsonl \
    --rollback-out /var/lib/s9k/rollback-$(date +%s).json \
    --apply \
    --neo4j-uri "$S9K_NEO4J_URI" \
    --neo4j-user neo4j \
    --neo4j-password-file /etc/s9k/neo4j.pass
```

**La contraseña no se pasa nunca por `argv`**: se declara el *camino* de un
fichero `0600` (o `-` para leerla de la entrada estándar). Si ese fichero es
legible por el grupo o por otros, la CLI se niega a leerlo. URI, usuario y
camino admiten también `S9K_NEO4J_URI`, `S9K_NEO4J_USER` y
`S9K_NEO4J_PASSWORD_FILE`. Si falta cualquiera de los tres con `--apply`, la
CLI falla **cerrado** con `CLI_DRIVER_CONFIG_MISSING` y código de salida `1`:
no se degrada a dry-run silencioso.

La fábrica vive en `knowledge_v3/driver_neo4j.py`, **fuera** del paquete del
writer, que conserva su higiene comprobada. Se invoca **después del gate**: un
intento bloqueado no llega a leer el secreto ni a abrir sesión.

`--rollback-out` guarda el documento de rollback del APPLY. Es lo que hay que
conservar para poder deshacer (§4.1).

El `plan_hash` se teclea a mano. Si el plan cambió desde que se revisó, no
coincide y no se escribe.

**Códigos de salida de la CLI.** `0` = fue bien y sin nada que contar; `1` =
rechazado o bloqueado (nada escrito); `2` = **se aplicó, pero con códigos** —
hoy el caso real es `AUDIT_APPEND_FAILED`: el grafo se escribió y la línea de
desenlace no llegó al registro. Un proceso desatendido (la unidad systemd de
§6) no puede leer eso como éxito limpio: trátese `2` como incidencia que exige
mirar el JSON y reconciliar la auditoría a mano.

### 5.3. Leer la auditoría

```bash
jq -r '[.timestamp, .outcome, .mode, .operator_id, (.rejections[0].code // "-")] | @tsv' \
    /var/lib/s9k/writer_audit.jsonl
```

Se registra **todo** intento: aceptado, rechazado, bloqueado o abortado. Un log
que solo guarda los éxitos no es auditoría.

Un APPLY deja **dos** líneas: `ATTEMPTED` antes de tocar el grafo y el desenlace
después. La primera existe porque la condición 9 del gate comprueba que el sink
*se declara* disponible, que es una promesa: si `append` falla igualmente, la
escritura habría ocurrido sin una sola línea. Por eso la línea `ATTEMPTED` va
antes, y **si no entra, no se escribe** (`GATE_AUDIT_UNAVAILABLE`). Si la que
falla es la del desenlace, lo aplicado está aplicado y el resultado lo dice con
`AUDIT_APPEND_FAILED`: el operador tiene que enterarse de que escribió sin dejar
esa constancia.

### 5.4. Uso programático

> **El `plan_hash` NUNCA se lee del plan que se está autorizando.** Se obtiene
> del canal por el que el operador revisó el plan —la consola de revisión, el
> mensaje que aprobó la ingesta, el informe del dry-run— y se teclea. Leerlo del
> documento que se va a aplicar convierte la condición 5 en una tautología:
> comprueba que el plan es igual a sí mismo, que siempre es cierto, incluso para
> un plan al que alguien añadió operaciones y volvió a sellar. Es la única
> condición del gate que ata lo que se aplica a lo que un humano revisó, y se
> anula sola en cuanto el hash sale del propio plan.

```python
from knowledge_v3.writer import GraphWriter, JsonlAppliedKeys, JsonlAuditSink, OperatorRequest

# Tecleado desde el informe de revisión. NO de plan_doc["plan_hash"].
HASH_REVISADO = "af2ee14ff3100e51b809706f531dbab051040d54f4f8e9aae82f48b483a7c428"

writer = GraphWriter(
    workspace="leyenda",
    driver_factory=abrir_driver,         # se invoca DESPUÉS del gate
    audit=JsonlAuditSink("/var/lib/s9k/writer_audit.jsonl"),
    applied_keys=JsonlAppliedKeys("/var/lib/s9k/writer_applied_keys.jsonl"),
    max_operations=50,
)
result = writer.write(plan_doc, OperatorRequest(
    apply=True, operator_id="pjc", workspace="leyenda",
    expected_plan_hash=HASH_REVISADO,
    current_snapshot_id="snapshot:neo4j:2026-07-27T10:29:00Z",
))
if result.codes:                          # APPLIED puede traer AUDIT_APPEND_FAILED
    print("atención:", result.codes)
```

`driver_factory` es una función sin argumentos que devuelve el driver. El writer
la invoca **solo si el gate deja pasar el APPLY**: construir la conexión antes
gastaría credenciales y una sesión en un intento que todavía puede bloquearse.
Quien ya tenga un driver abierto puede seguir pasándolo por `driver=`.

---

## 6. Qué queda para el despliegue

El **paquete** `knowledge_v3.writer` sigue sin poder conectarse por su cuenta:
no hay un solo `import` del paquete de Neo4j, ni URI, ni credencial, ni conexión
por defecto en ninguno de sus módulos, y hay un test que lo comprueba leyendo
los ficheros. Lo que sí existe ya es la **ruta de operador** (§5.2): la fábrica
vive en `knowledge_v3/driver_neo4j.py`, fuera del paquete, y sólo se invoca
cuando el operador pide `--apply` y el gate lo autoriza.

Lo que falta, y a quién le toca:

| Pendiente | Detalle |
|---|---|
| ~~**Conexión real**~~ | **Hecho.** `knowledge_v3/driver_neo4j.py` + `--neo4j-uri/--neo4j-user/--neo4j-password-file` (§5.2). Sigue invocándose después del gate. |
| **Unidad systemd** | Un servicio o timer que garantice **un único proceso escritor por workspace** (R3). El writer comprueba el workspace, pero no toma un bloqueo entre procesos: dos writers simultáneos sobre el mismo workspace entrelazarían el ledger. Un `.service` con `RemainAfterExit=no` más un fichero de bloqueo (`flock`) es lo mínimo. |
| **Rutas persistentes** | `--audit-log` y `--applied-keys` deben vivir en un volumen persistente y respaldado. Perder el fichero de claves aplicadas **rompe la idempotencia**: un replay volvería a escribir. |
| **Índices y restricciones** | Restricciones de unicidad sobre `(:V3Entity {entity_id, workspace})` y `(:V3Assertion {assertion_id, workspace})`. El writer ya comprueba la ausencia antes de crear, pero una restricción del motor es la garantía real frente a concurrencia. |
| **Propiedad `state_hash`** | El writer la lee para la concurrencia optimista y la escribe cuando el plan la trae. Quién la calcula y la mantiene al día en el grafo es una decisión de integración que este bloque no toma. |
| **Rotación del log** | El JSONL de auditoría crece sin límite. Rotar sin romper el carácter *append-only* (rotar por fichero, nunca truncar el vivo). |
| **Ejecución del rollback** | El documento ya es **reconstruible y ejecutable** sin `elementId`, y `rollback_query()` lo traduce a Cypher (§4.1); lo que sigue sin existir es un mando que lo aplique solo. Ejecutarlo es una decisión de operador, y convertirlo en un plan inverso sellado por el motor local sigue siendo trabajo de integración. |

---

## 7. Tabla de códigos de rechazo

Los códigos son **estables**: entran en el registro de auditoría. Renombrar uno
rompe el histórico. Son 32, en cuatro familias.

La columna «alcance» dice la verdad sobre cada comprobación: **directo** = se
llega a él con un documento realista; **defensivo** = el validador congelado o el
JSON Schema lo cazan antes, y la comprobación del writer existe por si un día
aflojan. Se dice en vez de fingir que las 32 son igual de alcanzables.

### 7.1. Admisión (`PLAN_*`)

| Código | Motivo | Alcance |
|---|---|---|
| `PLAN_CONTRACT_INVALID` | El documento no valida contra `graph-mutation-plan/v3-internal-v1`. Incluye `plan_hash`, `decision_hash` e `idempotency_key` recalculados por el validador congelado: aquí mueren todas las manipulaciones sin resellar. | directo |
| `PLAN_CONTRACT_VERSION_UNSUPPORTED` | `contract_version` con mayor distinta de la soportada. | defensivo |
| `PLAN_NOT_APPROVED` | `local_approval.approved != true`. | directo |
| `PLAN_NOT_SIGNED_LOCALLY` | El aprobador declarado no es el motor local. | defensivo (`const: "local"` en el schema) |
| `PLAN_VALIDATOR_CHAIN_NOT_PASS` | Cadena de validadores vacía o con resultados distintos de `PASS`. | directo si el plan no está aprobado; defensivo si lo está |
| `PLAN_SIGNATURE_MISMATCH` | `plan_hash` o `decision_hash` no corresponden al contenido. | defensivo |
| `PLAN_IDEMPOTENCY_KEY_UNDERIVED` | Alguna clave no deriva de su operación. | defensivo |
| `PLAN_EXPIRY_UNREADABLE` | `expires_at` no es un ISO-8601 UTC legible. | defensivo (patrón del schema) |
| `PLAN_EXPIRED` | El plan caducó según el reloj inyectado. Una firma correcta no lo resucita. | directo |
| `PLAN_WORKSPACE_MISMATCH` | El plan es de otro workspace (R3). | directo |
| `PLAN_SCOPE_CROSS_PARTIDA` | M3 (docs/v3/49 §2.4, Invariante 2): el ámbito declarado (`partida_id` raíz + bloque `scope`) es incoherente consigo mismo — `scope.layer` inválido, `PARTIDA` sin `partida_id`, `GAME` con `partida_id`, `scope.game_id` distinto del workspace, o raíz/`scope.partida_id` en desacuerdo. Error duro, nunca warning. | directo |
| `PLAN_SNAPSHOT_UNDECLARED` | El operador no declaró el snapshot vigente: sin testigo externo no se escribe (R2). | directo |
| `PLAN_SNAPSHOT_STALE` | El plan se calculó sobre un snapshot que ya no es el vigente. | directo |
| `PLAN_NO_OPERATIONS` | Plan sin operaciones: no hay nada que escribir. | directo |
| `PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER` | M4 (docs/v3/49 §2.5): una operación `CREATE_ASSERTION` declara `local_override_of` pero el plan entero es de capa juego (sin `partida_id` efectivo). Solo una PARTIDA puede declarar una divergencia local. Error duro, estructural. | directo |

### 7.2. Gate de operador (`GATE_*`)

| Código | Motivo |
|---|---|
| `GATE_ENV_NOT_ALLOWED` | `S9K_ALLOW_REAL_INGEST` no vale exactamente `1`. |
| `GATE_APPLY_NOT_REQUESTED` | No se pidió APPLY: el modo por defecto es dry-run. |
| `GATE_OPERATOR_MISSING` | Falta `operator_id`. |
| `GATE_OPERATOR_INVALID` | `operator_id` con forma no admisible. |
| `GATE_PLAN_HASH_NOT_CONFIRMED` | El operador no confirmó el `plan_hash`, o confirmó otro. |
| `GATE_OPERATION_LIMIT_EXCEEDED` | El plan supera el límite de operaciones autorizado. |
| `GATE_WORKSPACE_NOT_DECLARED` | Falta `S9K_WRITER_WORKSPACE`: el workspace no se declaró dos veces. |
| `GATE_WORKSPACE_DECLARATION_MISMATCH` | Las declaraciones del workspace no coinciden entre sí o con el writer. |
| `GATE_AUDIT_UNAVAILABLE` | No hay registro de auditoría utilizable. Sin rastro no se escribe. |

### 7.3. Auditoría (`AUDIT_*`)

| Código | Motivo | Alcance |
|---|---|---|
| `AUDIT_APPEND_FAILED` | El sink se declaró disponible y `append` falló igualmente. **No revierte nada**: avisa de que lo aplicado quedó aplicado sin esa línea de rastro. Si el que falla es el `ATTEMPTED`, no se escribe y el código es `GATE_AUDIT_UNAVAILABLE`. | directo |

### 7.4. Ejecución (`EXEC_*`)

| Código | Motivo | Alcance |
|---|---|---|
| `EXEC_VERSION_MISMATCH` | La versión leída del destino no es la esperada. Aborta el plan entero. | directo |
| `EXEC_HASH_MISMATCH` | El `state_hash` leído del destino no es el esperado. | directo |
| `EXEC_TARGET_MISSING` | La operación apunta a algo que no existe. | directo |
| `EXEC_TARGET_ALREADY_EXISTS` | Una creación apunta a algo que ya existe (CREATE-only estricto). | directo |
| `EXEC_SCOPE_MISMATCH` | M3 (docs/v3/49 §2.4): el objetivo existe, pero en OTRO ámbito de partida que el declarado por el plan (drift/carrera detectado en lectura, acotada por Cypher). Aborta el plan entero. | directo |
| `EXEC_UNSUPPORTED_OPERATION` | Tipo de operación no soportado. | defensivo (el `enum` del schema ya los limita a seis, y el writer soporta los seis) |
| `EXEC_UNSUPPORTED_PAYLOAD` | Payload inejecutable con seguridad: propiedad reservada, nombre inadmisible, etiqueta o predicado con forma sospechosa, valor no escalar. | directo |
| `EXEC_REASON_CODE_MISSING` | Cierre de vigencia sin `reason_code` válido (R1). | directo |
| `EXEC_DRIVER_FAILURE` | El driver falló, se pidió APPLY sin driver, o la fábrica de driver no devolvió ninguno. La transacción se revierte. | directo |
| `EXEC_IDEMPOTENCY_CONFLICT` | La clave ya fue aplicada en el workspace por un plan u operación incompatibles. | directo |
| `EXEC_DESTRUCTIVE_QUERY_BLOCKED` | Guardia interna: la consulta generada contenía una construcción destructiva. | **inalcanzable por los caminos públicos del writer** — ningún builder de `cypher.py` puede producir hoy una consulta destructiva, porque las etiquetas van validadas y los `SET` llevan lista blanca. Es la red para el próximo builder que alguien añada con prisa, y se prueba construyendo una `Query` destructiva a mano. |
| `EXEC_LOCAL_OVERRIDE_TARGET_MISSING` | M4 (docs/v3/49 §2.5): `local_override_of` apunta a un `assertion_id` que no existe en ningún ámbito de este workspace. | directo |
| `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER` | M4: el `assertion_id` apuntado por `local_override_of` existe, pero no es de capa juego — pertenece a una partida (la propia, otra, o una cadena de overrides). Cubre a la vez el cruce "partida→juego indebido" y el cruce "cross-partida". | directo |
| `EXEC_LOCAL_OVERRIDE_REASON_INVALID` | M4: `local_override_of` presente sin el `reason_code` canónico `LOCAL_DIVERGENCE` (R1 del ledger). | directo |
| `EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED` | M4 (rework): la misma partida ya tiene una divergencia local declarada sobre ese mismo hecho de capa juego. Unicidad estricta `(workspace, partida_id, local_override_of)`: el segundo intento es un conflicto, no una fusión ni una cadena — mismo criterio CREATE-only que `EXEC_TARGET_ALREADY_EXISTS`. | directo |

### 7.5. Ruta de operador (`CLI_*`)

| Código | Motivo | Alcance |
|---|---|---|
| `CLI_DRIVER_CONFIG_MISSING` | Se pidió `--apply` sin declarar cómo llegar al servidor (URI, usuario o camino del fichero con la contraseña). Falla cerrado, con código de salida `1`, sin escribir y sin degradarse a dry-run. | directo |

---

## 8. Pruebas

Dos suites de unidad, **172 tests**, con el driver de Neo4j **mockeado** en
todos los casos: ahí no se abre una conexión, no se lee una credencial y no se
escribe en ningún grafo real. Aparte, y saltada por defecto,
**`test_knowledge_v3_writer_neo4j_real.py` (23)** levanta su propio Neo4j
efímero en Docker (`S9K_WRITER_NEO4J_REAL=1`); entre ellas, la que aplica un
plan, resiembra el grafo en OTRA base efímera —donde los `elementId` son
necesariamente distintos, porque llevan el UUID de la base— y comprueba que el
documento de rollback guardado sigue borrando la relación correcta y sólo esa.

**`test_knowledge_v3_writer.py` (139)** — admisión (cada condición en positivo y
negativo, incluidas las defensivas mediante `monkeypatch`), las nueve
condiciones del gate, dry-run, ejecución, idempotencia, transaccionalidad,
rollback, auditoría e higiene. Incluye la tanda que salió de la revisión
independiente: el límite efectivo como mínimo de los dos declarados, el sink que
promete disponibilidad y falla, los documentos deformes que antes reventaban el
camino de auditoría, el salto de línea final que colaba por cuatro regex, y la
fábrica de driver que no se invoca si el gate bloquea.

**`test_knowledge_v3_writer_mutation.py` (33)** — lo que se pone rojo si alguien
quita una comprobación: la tabla de las nueve condiciones del gate con su
meta-test de cobertura, las manipulaciones del plan, la triple demostración
sobre los campos no firmados, y el plan forjado con una puerta trasera —parado
por la condición 5, y aplicado si el hash se lee del propio plan.

Lo que merece mención propia:

- **`ExplodingDriver`** — un driver que estalla en cuanto alguien lo toca. Es la
  única forma honesta de demostrar que el dry-run no escribe: no que «no
  parezca» escribir, sino que no puede.
- **Ataques del histórico** — sustituir la `provider_trace`, añadir una operación
  colada, extender `expires_at`, todos **sin resellar**: mueren en el `plan_hash`.
  Plan de otro workspace y snapshot desfasado: mueren en la admisión aunque el
  sello sea impecable.
- **Y el que sí funciona, probado como tal** — resellar. Alargar `expires_at`
  hasta después del reloj y volver a sellar produce un plan que la admisión
  acepta, y hay un test que lo demuestra en vez de insinuar lo contrario: los
  hashes son sha256 sin clave, así que quien puede reescribir puede resellar
  (§9). Lo que para un plan forjado con una operación añadida es la **condición
  5 del gate**: el hash tecleado es el del plan que se revisó, y ya no coincide.
  También está el test del antipatrón —leer el hash del propio plan— que
  **aplica la puerta trasera**, para que quede escrito por qué §5.4 insiste.
- **Campos no firmados, tres pruebas** — el `SignedView` no los contiene; los
  módulos que deciden no los nombran (escaneo del propio código fuente); y
  alterar los cuatro y volver a sellar produce **exactamente las mismas
  consultas con los mismos parámetros**, misma clave de idempotencia incluida.
  Una `metadata` hostil que declara `{"approved": "true", "workspace": "otra"}`
  no cambia nada.
- **Meta-test de la tabla del gate** — si alguien añade una décima condición sin
  su fila de mutación, el test cae. Y si borra una condición del gate, cae la
  fila correspondiente.
- **Meta-test de esta documentación** — los 32 códigos de §7 se comprueban contra
  `codes.py`. Un código sin documentar pone la suite en rojo.

### 8.1. Sin corpus

Este subsistema no produce ninguna métrica de calidad de extracción. Aquí no hay
nada que medir contra un *held-out*: son invariantes, y se demuestran con tests,
no con porcentajes.

---

## 9. Límites, dichos sin adornos

| Límite | Detalle |
|---|---|
| **Verificable, no autenticado** | Los hashes son sha256 **sin clave**. Detectan manipulación y desincronización, que es la clase de fallo que de verdad ocurre; **no** autentican al firmante. Quien pueda reescribir el documento puede volver a sellarlo. La garantía real hoy es la cadena de custodia: el plan no sale del proceso local. Los campos `local_approval.signature`/`key_id` están reservados y **sin usar**. El writer no lo suple ni finge lo contrario. |
| **La idempotencia vive en un fichero** | Borrar `--applied-keys` permite reescribir. El almacén es persistente y append-only, pero no está firmado ni replicado. Hay un test que lo documenta. |
| **La auditoría no resiste a quien tenga permiso de escritura** | Es append-only *por parte del writer*: no hay una sola función que reescriba, trunque o borre. Frente a un atacante con acceso al fichero, no pretende nada. |
| **Cualquier operador puede aplicar cualquier plan sellado** | El contrato congelado no lleva identidad del aprobador humano, así que el gate solo puede exigir que HAYA un operador identificado, no que sea **el** operador de este plan. El V1 sí ataba `operator_id` a la autorización del plan. Ver §2.1. |
| **Exclusión mutua entre procesos** | El writer comprueba el workspace, pero no toma un bloqueo. Dos writers simultáneos sobre el mismo workspace entrelazarían el ledger. R3 recae en el despliegue (§6). |
| **`state_hash` no lo calcula el writer** | Lo lee para la concurrencia optimista y lo escribe si el plan lo trae. Quién lo mantiene al día es una decisión de integración pendiente. |
| **El rollback no restaura lo que no leyó** | Un cierre de vigencia solo puede devolver `version` y `state_hash`. El documento lo declara en `unrecoverable`. |
| **Seis tipos de operación, ni uno más** | Un plan con un tipo desconocido se aborta con `EXEC_UNSUPPORTED_OPERATION`, no se ignora la operación. |
| **Ninguna prueba contra un Neo4j real** | Todo está mockeado, y a propósito. Lo que este bloque demuestra son invariantes de decisión, no de motor. Que las consultas generadas hagan en Neo4j lo que dicen hacer es una verificación de despliegue que aún no se ha hecho. |

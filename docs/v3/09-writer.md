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
es que no deban leerlos: es que no los tienen. El documento completo sí llega al
registro de auditoría, donde describir es todo lo que se hace.

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
| 5 | El operador confirma el hash del plan | `--expect-plan-hash <sha256>` | `GATE_PLAN_HASH_NOT_CONFIRMED` |
| 6 | El plan cabe en el límite de operaciones | `--max-operations` (200 por defecto) | `GATE_OPERATION_LIMIT_EXCEEDED` |
| 7 | El workspace está declarado dos veces | `S9K_WRITER_WORKSPACE` | `GATE_WORKSPACE_NOT_DECLARED` |
| 8 | Las dos declaraciones coinciden | entorno == `--workspace` == writer | `GATE_WORKSPACE_DECLARATION_MISMATCH` |
| 9 | Hay registro de auditoría utilizable | `--audit-log` escribible | `GATE_AUDIT_UNAVAILABLE` |

**Modo por defecto: dry-run.** Sin `--apply` no se abre siquiera el driver. La
escritura real exige argumento explícito *y* variable de entorno: dos gestos
independientes, uno en la línea de órdenes y otro en el entorno del proceso.

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

Sin `--apply` no se abre driver alguno. La salida es un JSON con `outcome`
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
    --apply
```

El `plan_hash` se teclea a mano. Si el plan cambió desde que se revisó, no
coincide y no se escribe.

### 5.3. Leer la auditoría

```bash
jq -r '[.timestamp, .outcome, .mode, .operator_id, (.rejections[0].code // "-")] | @tsv' \
    /var/lib/s9k/writer_audit.jsonl
```

Se registra **todo** intento: aceptado, rechazado, bloqueado o abortado. Un log
que solo guarda los éxitos no es auditoría.

### 5.4. Uso programático

```python
from knowledge_v3.writer import GraphWriter, JsonlAppliedKeys, JsonlAuditSink, OperatorRequest

writer = GraphWriter(
    workspace="leyenda",
    driver=driver,                       # inyectado; el writer no lo crea
    audit=JsonlAuditSink("/var/lib/s9k/writer_audit.jsonl"),
    applied_keys=JsonlAppliedKeys("/var/lib/s9k/writer_applied_keys.jsonl"),
    max_operations=50,
)
result = writer.write(plan_doc, OperatorRequest(
    apply=True, operator_id="pjc", workspace="leyenda",
    expected_plan_hash=plan_doc["plan_hash"]["value"],
    current_snapshot_id="snapshot:neo4j:2026-07-27T10:29:00Z",
))
```

---

## 6. Qué queda para el despliegue

Este bloque **no escribe en ningún Neo4j real y no puede hacerlo**: no hay un
solo `import` del paquete de Neo4j, ni URI, ni credencial, ni conexión por
defecto en todo el paquete. Hay un test que lo comprueba leyendo los ficheros.

Lo que falta, y a quién le toca:

| Pendiente | Detalle |
|---|---|
| **Conexión real** | Una fábrica de driver que lea URI y credenciales del entorno del despliegue (nunca del repositorio) y se pase a `cli.main(driver_factory=...)` o a `GraphWriter(driver=...)`. Hoy la fábrica por defecto lanza `NotImplementedError` con el motivo. |
| **Unidad systemd** | Un servicio o timer que garantice **un único proceso escritor por workspace** (R3). El writer comprueba el workspace, pero no toma un bloqueo entre procesos: dos writers simultáneos sobre el mismo workspace entrelazarían el ledger. Un `.service` con `RemainAfterExit=no` más un fichero de bloqueo (`flock`) es lo mínimo. |
| **Rutas persistentes** | `--audit-log` y `--applied-keys` deben vivir en un volumen persistente y respaldado. Perder el fichero de claves aplicadas **rompe la idempotencia**: un replay volvería a escribir. |
| **Índices y restricciones** | Restricciones de unicidad sobre `(:V3Entity {entity_id, workspace})` y `(:V3Assertion {assertion_id, workspace})`. El writer ya comprueba la ausencia antes de crear, pero una restricción del motor es la garantía real frente a concurrencia. |
| **Propiedad `state_hash`** | El writer la lee para la concurrencia optimista y la escribe cuando el plan la trae. Quién la calcula y la mantiene al día en el grafo es una decisión de integración que este bloque no toma. |
| **Rotación del log** | El JSONL de auditoría crece sin límite. Rotar sin romper el carácter *append-only* (rotar por fichero, nunca truncar el vivo). |
| **Ejecución del rollback** | Hoy se emite un documento. Convertirlo en un plan inverso sellado por el motor local es trabajo de integración, no del writer. |

---

## 7. Tabla de códigos de rechazo

Los códigos son **estables**: entran en el registro de auditoría. Renombrar uno
rompe el histórico.

La columna «alcance» dice la verdad sobre cada comprobación: **directo** = se
llega a él con un documento realista; **defensivo** = el validador congelado o el
JSON Schema lo cazan antes, y la comprobación del writer existe por si un día
aflojan. Se dice en vez de fingir que las 31 son igual de alcanzables.

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
| `PLAN_SNAPSHOT_UNDECLARED` | El operador no declaró el snapshot vigente: sin testigo externo no se escribe (R2). | directo |
| `PLAN_SNAPSHOT_STALE` | El plan se calculó sobre un snapshot que ya no es el vigente. | directo |
| `PLAN_NO_OPERATIONS` | Plan sin operaciones: no hay nada que escribir. | directo |

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

### 7.3. Ejecución (`EXEC_*`)

| Código | Motivo |
|---|---|
| `EXEC_VERSION_MISMATCH` | La versión leída del destino no es la esperada. Aborta el plan entero. |
| `EXEC_HASH_MISMATCH` | El `state_hash` leído del destino no es el esperado. |
| `EXEC_TARGET_MISSING` | La operación apunta a algo que no existe. |
| `EXEC_TARGET_ALREADY_EXISTS` | Una creación apunta a algo que ya existe (CREATE-only estricto). |
| `EXEC_UNSUPPORTED_OPERATION` | Tipo de operación no soportado. |
| `EXEC_UNSUPPORTED_PAYLOAD` | Payload inejecutable con seguridad: propiedad reservada, nombre inadmisible, etiqueta o predicado con forma sospechosa, valor no escalar. |
| `EXEC_REASON_CODE_MISSING` | Cierre de vigencia sin `reason_code` válido (R1). |
| `EXEC_DRIVER_FAILURE` | El driver falló, o se pidió APPLY sin driver inyectado. La transacción se revierte. |
| `EXEC_DESTRUCTIVE_QUERY_BLOCKED` | Guardia interna: la consulta generada contenía una construcción destructiva. |

---

## 8. Pruebas

Dos suites, **112 tests**, con el driver de Neo4j **mockeado** en todos los
casos. Aquí no se abre una conexión, no se lee una credencial y no se escribe en
ningún grafo real.

**`test_knowledge_v3_writer.py` (82)** — admisión (cada condición en positivo y
negativo, incluidas las defensivas mediante `monkeypatch`), las nueve
condiciones del gate, dry-run, ejecución, idempotencia, transaccionalidad,
rollback, auditoría e higiene.

**`test_knowledge_v3_writer_mutation.py` (30)** — lo que se pone rojo si alguien
quita una comprobación: la tabla de las nueve condiciones del gate con su
meta-test de cobertura, las manipulaciones del plan, y la triple demostración
sobre los campos no firmados.

Lo que merece mención propia:

- **`ExplodingDriver`** — un driver que estalla en cuanto alguien lo toca. Es la
  única forma honesta de demostrar que el dry-run no escribe: no que «no
  parezca» escribir, sino que no puede.
- **Ataques del histórico** — extender `expires_at` sin resellar (rompe el
  hash), extenderlo **y** resellar (firma impecable, sigue caducado), sustituir
  la `provider_trace`, añadir una operación colada, plan de otro workspace,
  snapshot desfasado. Todos rechazados con su código.
- **Campos no firmados, tres pruebas** — el `SignedView` no los contiene; los
  módulos que deciden no los nombran (escaneo del propio código fuente); y
  alterar los cuatro y volver a sellar produce **exactamente las mismas
  consultas con los mismos parámetros**, misma clave de idempotencia incluida.
  Una `metadata` hostil que declara `{"approved": "true", "workspace": "otra"}`
  no cambia nada.
- **Meta-test de la tabla del gate** — si alguien añade una décima condición sin
  su fila de mutación, el test cae. Y si borra una condición del gate, cae la
  fila correspondiente.
- **Meta-test de esta documentación** — los 31 códigos de §7 se comprueban contra
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
| **Exclusión mutua entre procesos** | El writer comprueba el workspace, pero no toma un bloqueo. Dos writers simultáneos sobre el mismo workspace entrelazarían el ledger. R3 recae en el despliegue (§6). |
| **`state_hash` no lo calcula el writer** | Lo lee para la concurrencia optimista y lo escribe si el plan lo trae. Quién lo mantiene al día es una decisión de integración pendiente. |
| **El rollback no restaura lo que no leyó** | Un cierre de vigencia solo puede devolver `version` y `state_hash`. El documento lo declara en `unrecoverable`. |
| **Seis tipos de operación, ni uno más** | Un plan con un tipo desconocido se aborta con `EXEC_UNSUPPORTED_OPERATION`, no se ignora la operación. |
| **Ninguna prueba contra un Neo4j real** | Todo está mockeado, y a propósito. Lo que este bloque demuestra son invariantes de decisión, no de motor. Que las consultas generadas hagan en Neo4j lo que dicen hacer es una verificación de despliegue que aún no se ha hecho. |

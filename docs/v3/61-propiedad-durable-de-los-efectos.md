# 61 — Propiedad durable de los efectos (`ownership_id`)

**Equipo 8B.** Rama `equipo8b/ownership-durable`, base
`integracion/carril7-integracion` = `34fca8f`.

## 1. El defecto

`apply_identity.compute_apply_id` deriva de `plan_hash`. `plan_hash` cubre el
documento entero salvo a sí mismo, incluidos `created_at` y `expires_at`, que
son **reloj**. Medido sobre el producto, dos procesos, mismo apply lógico, único
cambio el instante inyectado con `--ahora`:

| campo | ¿sobrevive? |
|---|---|
| `created_at` | **CAMBIA** |
| `expires_at` | **CAMBIA** |
| `plan_hash` | **CAMBIA** |
| `decision_hash` | **CAMBIA** |
| `apply_id` | **CAMBIA** (hereda el reloj vía `plan_hash`) |
| `plan_id` | IGUAL |
| `workspace`, `snapshot_id` | IGUAL |
| `idempotency_key` de cada operación | **IGUAL** |

Por eso `apply_id` es identidad de **intento**, no de propiedad: el mismo apply
lógico reejecutado —o replanificado tras un restore— produce otro `apply_id`, y
la clasificación del rollback que se apoyaba en él dejaba de reconocer lo que
ella misma había creado.

**Hallazgo que no se esperaba:** `decision_hash` **tampoco sirve**. Es el
candidato natural (es lo que el contrato sella y lo que el `SignedView` sí
lleva), pero `expires_at` está **dentro** de `DECISION_HASH_FIELDS`, y
`expires_at = now + plan_ttl_seconds`. Medido, no supuesto.

## 2. De dónde sale la autoridad

No basta un campo estable: hace falta un campo estable **que el writer pueda
usar como autoridad**. El contrato congelado y `writer/view.py` acotan ese
conjunto.

- `writer/view.py` — `UNSIGNED_FIELDS = {created_at, plan_id, provider_trace,
  metadata}`, y el `SignedView` sencillamente no los contiene: *«No es que no
  deban leerlos: es que no los tienen.»* `plan_id` **es estable** —lo confirma
  la medida— pero está excluido a propósito de lo que el writer puede tomar por
  autoridad. **No es candidato, y no se propone firmarlo.**
- `contracts/knowledge-v3/v1/validator.py` — `mutation_operations` **sí** está
  en `DECISION_HASH_FIELDS`: está sellado y llega al view.
- El mismo fichero declara qué es la identidad lógica de una operación:
  > *«Campos que definen la IDENTIDAD LOGICA de una operacion. `operation_id` NO
  > esta: la misma operacion calculada en dos planes distintos debe producir la
  > misma clave de idempotencia, o reaplicar duplica.»*
  `IDEMPOTENCY_KEY_FIELDS = (operation_type, decision_id, target_entity_id,
  assertion_id, payload)` — sin reloj.
- `writer/admission.py` paso 7 no se cree la clave por venir escrita: la
  **re-deriva** operación por operación y rechaza el plan con
  `PLAN_IDEMPOTENCY_KEY_UNDERIVED` si alguna no cuadra. El writer ya trata la
  `idempotency_key` como **autoridad verificada fail-closed**, al contrario que
  `plan_id`.

De ahí el material, y de nada más:

```
ownership_id = sha256(
    workspace + ámbito(partida_id) + snapshot_id + sorted({idempotency_key})
)[:32]
```

Ninguna pieza es reloj, ninguna lleva el UUID de la base, todas están selladas o
son re-derivables por el writer. El conjunto se **ordena**: las operaciones de
un apply son un conjunto, no una lista.

## 3. Las tres identidades

```
attempt_id (= apply_id)  -> qué INTENTO concreto escribió esto
ownership_id             -> a qué apply LÓGICO pertenecen los efectos
plan_id                  -> identidad documental existente,
                            NO autoridad firmada para el writer
```

`apply_id` **se conserva**: sigue siendo útil en auditoría para distinguir dos
intentos. Lo que cambia es que la **propiedad** deja de apoyarse en él.

## 4. Dónde se persiste

- Nodos de procedencia creados (`V3Source`, `V3Episode`, `V3Evidence`) —
  `provenance.py::_node_props`, solo en el `CREATE`. Un nodo **reutilizado**
  conserva el `ownership_id` de quien lo creó: es marca de creación, no de uso.
- `V3AppliedOperation` — `cypher.py::claim_applied_operation`, en `ON CREATE
  SET`.
- Documento de rollback — raíz (`RollbackDocument.ownership_id`) y detalle de la
  instrucción de barrido.

**Defecto colateral corregido:** `cli_rollback.load_document` reconstruía el
documento **sin leer el `apply_id` de la raíz**. Se serializaba y se perdía al
recargar, así que un rollback ejecutado desde fichero clasificaba como si el
apply no tuviera identidad y caía al radio por nombre. Ahora se releen las dos
marcas.

## 5. Qué NO es

- **No es un gate.** No impide ninguna escritura ni ningún borrado.
- **No relaja el rollback.** La condición de cero referencias vivas sigue
  **dentro** del `DELETE` atómico (evitar TOCTOU). La propiedad **estrecha** el
  conjunto candidato; nunca lo amplía.
- No toca `DECISION_HASH_FIELDS`, ni `IDEMPOTENCY_KEY_FIELDS`, ni el contrato
  congelado, ni `authz/`, ni políticas. Cero ficheros sellados regenerados.

## 6. Evidencia

`data-engine/app/tests/escenario_equipo8b.py` — **dos contenedores Neo4j
distintos**, ruta de operador (`ingest_cli` en subprocess). **33/33 OK, rc=0.**

- `elementId` de A y B **disjuntos** (`comunes=0`, `|A|=11`, `|B|=11`),
  comprobado **antes** de comparar: dentro de una misma base los ids se
  reutilizan y los sufijos locales coinciden entre bases.
- **(1)** mismo apply lógico, dos bases → `ownership_id` idéntico
  (`own:dc6140bc…`), nodo a nodo por identidad lógica y también en las
  `V3AppliedOperation` (3 claves compartidas).
- **(2)** intento distinto → `apply_id` cambia (`apply:dbf5dc33…` vs
  `apply:d6a6d650…`), `ownership_id` no.
- **(3)** apply lógico distinto → `own:c374f4bb…` ≠ `own:dc6140bc…`; y lo que
  creó X conserva su marca tras el apply Y.
- **(4)** clasificación PX/SHARED/RESIDUE se ejecuta sobre la base nueva y el
  rollback no borra de más: la procedencia de X sigue viva.
- **(5)** control negativo: la identidad rota (con el reloj dentro) se pone
  **roja**; y `apply_id` y `decision_hash` fallan la prueba 1 sobre el producto.

`tests/test_knowledge_v3_equipo8b_ownership_durable.py` — 31 pruebas offline.
Control negativo **sobre el producto**: mutando `compute_ownership_id` para que
dependa del reloj, la batería pasa a **4 failed / 25 passed** (medido sobre las 29 de entonces).

Suite offline completa: **5457 passed, 17 skipped, 2 xfailed, rc=0**.

## 7. Carencias declaradas

- `plan_id` es estable y **no se usa**: el diseño lo excluyó deliberadamente de
  la autoridad del writer. Firmarlo obligaría a regenerar 264+ ficheros
  sellados. Se deja como está.
- Las operaciones de cierre (`CLOSING_TYPES`) no dejan huella propia; su
  propiedad se sigue resolviendo por la marca, no por nodo.
- La clasificación **sigue consumiendo `apply_id`**: este bloque persiste la
  propiedad durable en los tres sitios y la deja disponible en el documento
  recargado, pero **no cambia el predicado** de `ownership_clause`. Migrarlo es
  una operación propia y explícita, con su propia medida.

## 8. Declarado al equipo 8A

**Lo que 8A avisó no me afecta; lo que sí me afecta es otra cosa.**

- **`state_hash`: sin acople.** `compute_ownership_id` no lo toca por ninguna
  vía — comprobado, no supuesto, y fijado en
  `test_la_propiedad_no_depende_del_state_hash`. Que el `state_hash` de un nodo
  creado con alias cambie no puede producir un falso rojo en este bloque.

- **`payload`: acople real, en la dirección contraria.** `payload` está en
  `IDEMPOTENCY_KEY_FIELDS`, y 8A persiste los alias **dentro del `payload`**.
  Luego los alias **entran en el `ownership_id`**.

  Que la propiedad lo note **no es un fallo**: un `payload` distinto es una
  operación lógica distinta, y discriminarla es justo lo que exige el criterio
  3. **El riesgo es el orden.** Si la lista de alias no va en **orden canónico**
  en el plan, dos corridas del mismo apply lógico producen `idempotency_key`
  distintas y, por tanto, `ownership_id` distintos — reintroduciendo en
  silencio el defecto que este bloque cierra, y sin romper ningún hash que
  alguien esté mirando.

  Es la misma preocupación que ya documenta `tests/planner_hashseed_probe.py`,
  que nombra `idempotency_key` explícitamente. Queda fijada en
  `test_el_payload_entra_en_la_propiedad_y_por_eso_debe_ir_canonizado`.

  **Petición concreta a 8A: ordenar canónicamente la lista de alias antes de
  meterla en el `payload`.**

- **Nodos compartidos.** El `ownership_id` se estampa en `V3Source`,
  `V3Episode`, `V3Evidence` y `V3AppliedOperation` — **no en `V3Entity`**, que
  es donde 8A escribe. No hay colisión de escritura entre los dos bloques.

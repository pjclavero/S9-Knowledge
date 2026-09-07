# 60 · Una sola ruta canónica de aplicación

**Equipo 6A, tanda 5.** Base `integracion/tanda5` = `5808a405`.

**Ámbito:** `data-engine/app/knowledge_v3/writer/apply.py` (nuevo),
`writer/cli.py`, `writer/writer.py`, `pipeline/pipeline.py`,
`pipeline/ingest_cli.py`, `engine/promotion.py` (nuevo), `engine/engine.py`,
`pipeline/config.py`.

---

## 1. El defecto: dos rutas que no escribían lo mismo

Un supervisor independiente aplicó **el mismo plan con el mismo esquema** por
los dos mandos:

```
                     aristas   V3Source   V3Evidence
ingest_cli --apply        18          1            7
writer.cli  --apply        0          0            0
```

`writer.cli` escribía la aserción con `evidence_fragment_ids:
["ef-d4b8…"]` apuntando a **un fragmento que no existía**, sin
`SUPPORTED_BY`, y reportaba `APPLIED` **sin una sola advertencia**.

### Por qué no se arregla «haciendo que los dos hagan lo mismo»

Porque no pueden, y ésa es la parte estructural: **la procedencia no está en el
plan**. El plan *cita* `evidence_fragment_ids`; los documentos `SourceAsset` /
`SourceEpisode` / `EvidenceFragment` que esos ids nombran viven en la corrida
de ingesta. Un mando al que sólo se le da `plan.json` **no tiene con qué**
persistir procedencia. Mantener dos implementaciones «equivalentes» era
imposible: una de las dos iba a mentir siempre.

## 2. Lo que hay ahora

```
        writer/apply.py :: apply_v3        <- LA definición de aplicar V3
                  ^                 ^
                  |                 |
            pipeline.write     writer.cli
           (ruta de operador)  (bajo nivel)
```

`apply_v3` hace, en este orden: compone el `apply_id` durable → entrega el plan
al `GraphWriter` (su gate, intacto) → persiste la procedencia **en su propia
transacción** si hay paquete → si no lo hay, **lo dice y enumera las
referencias colgantes** → amplía el documento de rollback con el barrido
acotado por `apply_id`.

Lo que distingue las dos rutas ya **no es código, son datos**: el
`ProvenanceBundle`. `writer.cli` queda declarado de bajo nivel y:

* sin `--procedencia`: emite `APPLY_PROVENANCE_NOT_PERSISTED`, lista los
  `fragment_id` que deja colgando y sale con **`rc = 2`** (no es éxito limpio);
* con `--procedencia` (el `procedencia.json` que `ingest_cli --out-dir` emite):
  alcanza **el mismo grafo** que la ruta de operador.

### Medición de la equivalencia

Mismo `plan.json` (`plan_hash 126d65ee…`), mismo `apply_id`
(`apply:fab0860a…`), grafo vaciado entre ambas ejecuciones:

```
                              V3Entity V3Assertion V3Source V3Episode V3Evidence aristas SUPPORTED_BY
ingest_cli --apply                   4           2        1         7          7      20            2
writer.cli --apply --procedencia     4           2        1         7          7      20            2
writer.cli --apply  (sin paquete)    4           2        0         0          0       0            0
```

Comparados **nodo a nodo por identidad durable** (nunca por posición, nunca por
`elementId`):

```
aristas indexadas: 20 vs 20
aristas solo en operador:  NINGUNA
aristas solo en writer.cli: NINGUNA
propiedades de producto que difieren: NINGUNA
V3AppliedOperation por idempotency_key: 6 vs 6 -> identicas
```

Las únicas diferencias son de reloj y se excluyen declarándolas:
`applied_at`, `written_at`, `claim_token`, `state_hash`.

## 3. La cadena del operador, entera

Sin abrir un fichero interno y sin escribir una línea de Python:

```
fuente -> ingest -> decisiones -> review -> promoción explícita
       -> plan sellado -> apply -> procedencia -> documento de rollback
```

`ingest_cli --out-dir DIR` emite ahora `acta.md`, `informe.json`,
**`plan.json`**, **`procedencia.json`**, **`rollback.json`**,
**`promociones.json`** y `decisiones.json`. Antes sólo los tres primeros: el
único mando que emitía póliza (`writer.cli --rollback-out`) exigía un fichero
de plan **que nadie producía**, y el supervisor tuvo que extraerlo del
`informe.json` a mano. `--rollback-out RUTA` también existe ya en `ingest_cli`.

## 4. `REVIEW` tiene salida

Antes: el motor mandaba una relación a `REVIEW` y **no había mando para
promoverla**. `--aprobar-alta` sólo aprueba altas de **entidad**. La decisión
`APPROVE` que una persona tomaba en el visor no tenía ningún camino de vuelta.

Ahora, `engine/promotion.py` + `ingest_cli --revisar --promover CLAIM_ID`.

Una promoción **no fija una decisión**: retira los hallazgos `REVIEW` firmados
y la decisión se **recalcula**. De ahí salen las garantías:

* un hallazgo `REJECT` o `ABSTAIN` sobrevive → una promoción **no puede** tapar
  una invalidez;
* los motivos retirados se sustituyen por `HUMAN_PROMOTED_<código>` en `WARN`,
  así que `reason_codes`, `decision_hash` y `plan_hash` **cambian**: un plan con
  promociones no se confunde con uno sin ellas;
* la firma declara los motivos que el humano **vio**; si el motor produce otros,
  caduca (`PROMOTION_STALE`) y no se aplica;
* un claim al que le falta `subject`/`object`/`predicate`/`direction` **no es
  promovible** (`PROMOTION_INCOMPLETE_CLAIM`) y se lista marcado. Sin esta
  guarda, promoverlo producía un `ACCEPT` que el contrato congelado rechazaba
  (`decisions[i].object_entity_id: None is not of type 'string'`) reventando la
  corrida **después** de que el operador hubiera firmado. Medido en la cadena
  real.

## 5. La identidad del apply y el reloj

Un equipo anterior afirmó que `apply_id` es «la misma cadena en cualquier base
y tras un restore». **Es cierto sólo a igualdad de plan.** `apply_id` deriva de
`plan_hash`, y `plan_hash` cubre `created_at`, que sale del reloj de pared.
Medido, dos ejecuciones idénticas:

```
SIN --ahora  apply_id: apply:fcca93cb… | apply:c30fa2bb… -> iguales? False
SIN --ahora  plan_id : plan:91f2e4f3…  | plan:91f2e4f3…  -> iguales? True
CON --ahora  apply_id: apply:18d06d3f… | apply:18d06d3f… -> iguales? True
```

### La carencia, declarada y no fabricada

El campo contractual que representa la identidad **lógica** del plan es
**`plan_id`**: es obligatorio en `graph-mutation-plan-v3.schema.json`, y el
planificador lo deriva de `(workspace, source_asset_id, snapshot_id, kind,
decisions, partida_id)` — **sin reloj**. Es exactamente la propiedad pedida.

**Pero el contrato congelado lo declara NO FIRMADO**
(`writer/view.py:UNSIGNED_FIELDS = {created_at, plan_id, provider_trace,
metadata}`): no entra en `decision_hash`, es manipulable sin romper ningún
hash, y el `SignedView` — lo único que el gate y el ejecutor ven — **no lo
contiene a propósito**.

> **Carencia declarada:** el contrato no tiene ningún campo *firmado* que
> represente la identidad lógica del plan independiente del reloj. `plan_id` lo
> es semánticamente pero no está cubierto por la firma, así que **no puede
> sostener una decisión de escritura** y no se usa para ninguna.

Lo que se hace en su lugar, sin tocar el contrato congelado:

1. `apply_id` **sigue derivando de `plan_hash`** — firmado, íntegro, seguro.
2. El informe **publica `plan_id` junto al `apply_id`** para que el operador
   pueda reconocer «el mismo plan» entre ejecuciones. Se publica; no se decide
   con él.
3. `informe.json → apply_identity.carencia` **dice en cada corrida sin
   `--ahora`** que el `apply_id` no será reproducible, en vez de dejarlo para
   que alguien lo descubra comparando.

## 6. `created_ids` ya no devuelve `elementId`

`cypher.create_relation` termina en `RETURN elementId(r) AS id`, y ese valor
llegaba crudo a `write.created_ids`, **mezclado** con los `entity_id` /
`assertion_id` y sin forma de distinguirlo. El `elementId` se regenera al
restaurar un dump: deja de identificar justo durante una recuperación.

Ahora `write.created` publica la **identidad durable** — `(workspace,
entity_id)` para nodos, la tripleta `(sujeto, predicado, objeto)` dentro de su
ámbito para aristas — y el `elementId` se conserva sólo bajo
`element_id_at_write`, el nombre que ya usa el documento de rollback.
`created_ids` se mantiene por compatibilidad pero **sólo con ids durables**.

## 7. `--decisiones` ya no miente

La ayuda decía «se escribe en la ingesta». Se escribe **sólo cuando la corrida
abrió el grafo** (`--desde-grafo` o `--apply`): el documento se reconcilia
contra lo que el grafo tiene, y sin grafo no hay con qué reconciliar. En una
ingesta offline la ruta se ignoraba **en silencio**; ahora la ayuda lo dice y
el mando avisa por `stderr` nombrando el fichero que no va a escribir.

## 8. Lo que NO se tocó

`authz/`, `policies/`, grants, visibilidad, protección de rama, producción,
VM105. Ningún gate nuevo. **Ninguna garantía del writer relajada**: gate triple
fail-closed, secreto nunca por `argv`, dry-run seguro por defecto, `--operator`
y auditoría obligatorios para borrar. La clasificación del resultado del
rollback (6B) no se toca: aquí se **emite** el documento, allí se juzga. La
cadena de `--partida` / `known_from_session` (6C) no se toca; el contexto sigue
pasando por donde pasaba — `apply_v3` lee el ámbito **del propio plan**
(`scope.partida_id` con precedencia sobre la raíz, mismo criterio que
`SignedView.of`) y se lo pasa a `persist_provenance` igual que antes.

# 57 — Integración de la tanda 3: las tres garantías, a la vez

**Rama:** `integracion/tanda3`
**Base:** `carril-b/reconciliacion-vertical` (`1f36cd2`), que ya traía fusionados
`carril-a`, `carril-c`, `equipo1/procedencia-navegable` y
`feat/writer-ruta-operador-rollback-durable` sobre `main@c29dfaa`.
**Integra además:** `equipo-r1/rollback-procedencia-honesto` (`0906589`) y
`equipo-r2/rollback-ambito-partida` (`c284de0`).

**NO se fusiona a `main`.** `BASE RC V3.1` (`f725bd8`) queda intacta. No se
tocan `authz/`, `policies/`, grants, visibilidad, protección de rama,
producción ni VM105.

---

## 1. Cómo quedó `rollback.py`

El conflicto estaba **anunciado por R2** y era textual, no de diseño. Se
resolvió entendiendo las dos mitades, no eligiendo un lado.

### Lo que aporta cada mitad, y por qué conviven

| mitad | qué añade | dónde |
|---|---|---|
| **R1** | `ACTION_PURGE_PROVENANCE`, `ACTION_FORGET_APPLIED`, `_provenance_edges_of`, la instrucción de purga y la de olvido tras cada operación | `build_rollback`, constantes de cabecera |
| **R2** | `scope_clause`, `DELETABLE_NODE_LABELS`, `delete_node_query`, y `rollback_query` reescrito con lista blanca de etiquetas y filtro de ámbito | reconstrucción de consultas |

Son regiones distintas del fichero. **Las dos sobreviven enteras.** El
inventario del módulo tras la fusión, leído por AST:

```
RollbackInstruction · RollbackDocument · build_rollback · _provenance_edges_of
RollbackQuery · RollbackNotReconstructible · _require
scope_clause · _scope_clause · delete_node_query · rollback_query
```

### El único choque textual real

Ambos añadían `partida_id` al `detail` del `DELETE_NODE`:

* R1: `op.partida_id if op.partida_id else view.partida_id`
* R2: `op.partida_id`

**Gana la forma de R2**, por dos razones medidas:

1. Es exactamente lo que el executor estampó en el nodo. En `executor.py` el
   ámbito de cada operación sale de `partida_id = view.partida_id` y de ahí va
   a `_estampar`. El `or view.partida_id` de R1 no aportaba valor distinto.
2. El fallback **borraba la distinción sobre la que se apoya el fail-closed de
   R2**: campo *ausente* ≠ campo a `None`. `None` es la capa juego; la
   ausencia se deniega. Un `or` convierte lo segundo en lo primero.

La misma unificación se aplicó al `detail` de `PURGE_PROVENANCE`, que la
fusión automática había dejado con la forma con fallback.

### Una sola definición del filtro de ámbito

R1 tenía `rollback_provenance._scope()` y R2 escribió `rollback.scope_clause()`.
Dicen lo mismo. **Dos definiciones que deben coincidir sin nada que lo
verifique acaban divergiendo, y la que diverge borra de más.**

`_scope` desaparece. Los cuatro puntos de uso de `rollback_provenance` llaman a
`rollback.scope_clause`. No se dejó un alias: un alias es una definición que
sigue teniendo dos nombres.

Lo que se **gana** al unificar, y no es cosmético: `_scope` aceptaba cualquier
cosa que no fuese `None` y la metía tal cual como si fuese una partida —una
cadena vacía incluida—. `scope_clause` valida y deniega el ámbito malformado.
Caso nuevo: `test_el_ambito_malformado_tambien_se_deniega`.

Coste: el parámetro pasa de `$partida` a `$partida_id`. Actualizado en la
prueba de R1 que lo comprobaba.

### Lo que deliberadamente NO se hizo

**Las cinco consultas de R1 no se absorbieron en el generador de R2.** R2 se
negó con razón: la condición de cero referencias vivas **viaja dentro del
propio `DELETE`**, y sacarla fuera abriría una ventana entre contar y borrar.
Ese diseño se respeta.

Y por lo mismo, **`V3Evidence` NO se añadió a `DELETABLE_NODE_LABELS`**. La vía
de borrado por clave durable de R2 no lleva guarda de referencias vivas, y la
evidencia la necesita. Tampoco hacía falta: `build_rollback` sólo emite
`DELETE_NODE` con etiqueta `V3Entity` o `V3Assertion`. Ambas decisiones quedan
**medidas**, no sólo escritas, en
`test_la_guarda_de_referencias_vivas_NO_se_absorbio_en_el_builder_de_R2`.

### `executor.py`

Conflicto puramente aditivo: `evidence_fragment_ids` (R1) y `node_label` (R2)
conviven en `AppliedOperation`. La fusión automática dejó además un
`partida_id=` **duplicado** en `CREATE_ASSERTION` —un `SyntaxError`— corregido
al resolver.

---

## 2. Las tres garantías, vivas a la vez

Cada equipo probó la suya por separado y nunca habían corrido juntas. Suite
nueva contra Neo4j real y efímero:
`data-engine/app/tests/test_knowledge_v3_tanda3_integracion_neo4j_real.py`.

| garantía | caso |
|---|---|
| **B** | fichero → reconciliación → altas aprobadas una a una → apply → procedencia navegable, **sin sembrar nada por Cypher** |
| **R1** | evidencia compartida por una aserción viva **NO se borra**, y se declara en `unrecoverable` |
| **R2** | gemelo de relación y gemelo **por nodo** en `partida:otra` sobreviven al rollback de capa juego |

### La combinación nueva

El carril B **emite `CREATE_ENTITY` de verdad**. Antes de esta integración no
existía un `CREATE_ENTITY` emitido por el producto que revertir: el rollback de
nodo sólo se había ejercitado sobre planes escritos a mano en las pruebas.
Ahora se ejercita **por la ruta real**, y el documento incluye entidades que
otras aserciones ya referencian —el caso de R1—.

Al probarlo apareció un hueco real: `run_ingest` **no publicaba el documento de
reversión** de lo que acababa de escribir. Crear sin publicar cómo deshacerlo
deja al operador con conocimiento escrito y sin documento, que es justo lo que
la ruta de operador del writer existe para evitar. `report["rollback"]` lo
publica. Sigue siendo **descriptivo**: nadie lo ejecuta por su cuenta.

### Cautelas de medida aplicadas

* Nunca dos `MATCH` sueltos en la misma consulta: producto cartesiano, y a
  menudo cero filas que parecen un verde. Cada censo va en su consulta.
* Antes de comparar dos conjuntos se comprueba que el de partida **no está
  vacío**. Un `[] == []` no demuestra nada.
* Las afirmaciones sobre la frontera del merge se comprueban **parseando** el
  módulo (AST) y el Cypher **generado**, no contando apariciones en el texto.

---

## 3. El checkpoint de contratos, avanzado con su control negativo

`test_19_contratos_congelados_mantienen_su_hash` estaba **rojo a propósito**:
`carril-a` corrigió `contracts/episode.py` (defecto real GATE4-03 —
`speaker`/`turn`/`table` sin `default`, que hacía que `from_dict` rechazase un
episodio válido según el schema publicado) y ese gate congela el árbol byte a
byte. Avanzar el checkpoint es tarea del integrador.

```
digest anterior (m4)       51cb491e727cf7d92d7e429a057f67d46aa1ad6ee3d09c57fd72e1d1d89e18e7
digest nuevo (gate4-03)    b36fbb3e2d1353c6ab230f21368966b587b6a573b903e6e9f323086a5e611216
tag nuevo                  v3-contracts-frozen-1.0.0-gate4-03
ficheros congelados        23 (mismas rutas en ambos checkpoints)
único cambio de contrato   data-engine/app/knowledge_v3/contracts/episode.py
```

El cambio es **aditivo**: `default=None` sin entrar en `OMIT_IF_NONE`, porque
el schema los declara nullable. `to_dict()` sigue emitiéndolos con `null`.
Relaja la **lectura**, no la escritura.

**No se silencia.** `test_19b_control_negativo_...` inyecta **en memoria** un
cambio contractual real —quitarle a `speaker` el `default=None` que GATE4-03
acaba de añadir— y exige que el digest cambie. Antes comprueba, como **control
positivo**, que el árbol limpio coincide con el checkpoint: sin eso, un rojo
suyo podría venir de cualquier otra cosa. El gate y su control comparten
**exactamente** la misma función de digest; si el control usase una copia,
probaría la copia.

**Calibrado en vivo**: mutando `episode.py` en el árbol de trabajo, los dos se
ponen rojos; restaurado, los dos verdes.

No es un gate nuevo ni un meta-gate: es el control negativo de uno que ya
existía, y actualizar el sujeto de un gate no es crear otro.

---

## 4. Saneo de la ruta absoluta filtrada

El repositorio es **público**. `docs/v3/ingesta-real/informe.json`, commiteado
por `carril-a`, llevaba una ruta absoluta local del worktree del agente:

```
- "original_location": "file:///home/ia02/S9-Knowledge/.claude/worktrees/agent-af9a655cf842e27f8/examples/ingesta-v3/nota-cofradia-de-ambar.md"
+ "original_location": "file:examples/ingesta-v3/nota-cofradia-de-ambar.md"
```

Una sola ocurrencia. El JSON sigue siendo válido y nada depende de ese valor.
Severidad baja.

**Declarado y no corregido** (no es de estas tres ramas): quedan rutas
`/home/ia02/...` en documentos antiguos —`docs/74`, `docs/archivados/51`,
`docs/coordination/sequential-program/block-7/8/9-*`—. No se tocan.

---

## 5. Colisión de numeración, producida por la propia integración

R1 y carril B traían los dos un `docs/v3/55`. Lo detectó
`tests/test_docs_numbering.py`, que existe justo para esto. El de R1 pasa a
`56-rollback-que-revierte-y-lo-dice.md`; el contenido no cambia.

---

## 6. Dos pruebas de R1 caducadas por el contrato más estricto de R2

Actualizadas **sin relajar nada**, y cada una con su caso contrario añadido:

* `test_el_ambito_falla_cerrado` esperaba `$partida`; ahora `$partida_id`.
  Mismo criterio, otro nombre. Se añade
  `test_el_ambito_malformado_tambien_se_deniega`.
* `test_el_encaminador_delega_lo_que_no_es_suyo` construía una instrucción sin
  `partida_id`. El ámbito es ahora obligatorio: la declara (`None` = capa
  juego). Se añade `test_el_encaminador_deniega_lo_que_no_declara_ambito` —
  delegar no relaja el fail-closed.

Ninguna es un defecto de R1: son el precio, correcto, de que R2 endurezca el
contrato del documento.

---

## 7. El contrato real de identidad de `Assertion` (encargo del operador)

R2 señaló al pasar que `(workspace, assertion_id) IS UNIQUE` no incluye el
ámbito. Reproducido, no interpretado, en
`artifacts/tanda3-integracion/reproduccion_identidad_assertion.py` (contra
Neo4j real y efímero, `rc=0`, todas las comprobaciones en verde).

### ¿Qué EXIGE el contrato?

**`assertion_id` es único por `workspace`, por contrato.** Derivado del
contrato publicado, no del comportamiento del código:

* `fact-assertion-v3.schema.json` (**congelado**) tiene
  `additionalProperties: false` y **no tiene `partida_id` ni `scope`**. Una
  aserción no puede ni declarar en qué partida vive, así que su identidad no
  puede incluir la partida. Es el único documento tardío sin ámbito:
  `ClaimProposal` (su entrada) y `GraphMutationPlan` (su escritor) sí lo
  tienen — el ámbito es del **plan**, no del hecho.
* `docs/v3/49-multipartida-diseno.md` lo dice con todas las letras: «un
  `entity_id`/`assertion_id` es único en TODO el workspace, cruzando capa
  juego y todas sus partidas — dos ámbitos jamás comparten el mismo id».
* El mecanismo del contrato para que un hecho difiera por partida **no es
  repetir el id**: es una aserción nueva, con id propio, apuntando a la de
  capa juego por `local_override_of` (§2.5). Confirma que los ids nunca se
  comparten.

### ¿Qué PERMITEN el writer y el esquema? (medido)

| escenario | gemelo por Cypher crudo | gemelo por el writer |
|---|---|---|
| **con** la restricción | `ConstraintValidationFailed` | — |
| **sin** la restricción (como la base real) | **CREADO** | `ABORTED` |

Y las dos barreras del writer, separadas a propósito, porque se confunden con
facilidad:

* misma `decision_id` → `EXEC_IDEMPOTENCY_CONFLICT`. Fail-closed, pero es la
  barrera de **idempotencia**, no la de unicidad del id.
* otra `decision_id` (clave ya distinta) → **`EXEC_TARGET_ALREADY_EXISTS`**,
  es decir `_assert_absent`: la barrera de **unicidad del id**, aislada.

La restricción se retiró sobre la base **efímera**, nunca sobre otra, y se
repuso verificándolo: 7 → 7 restricciones, el mismo juego.

### ¿Coinciden?

**Sí.** Contrato, writer y esquema norman lo mismo.

```
assertion_id UNICO POR WORKSPACE, POR CONTRATO
  -> la restriccion (workspace, assertion_id) es CORRECTA
  -> partida_id es atributo / contexto, NO identidad
  -> NO BLOQUEA el Vertical Slice 1
```

**Y no hay asimetría con el pariente conocido:** la identidad de producto es
`(workspace, entity_id)` y la de aserción `(workspace, assertion_id)` — la
misma forma. `writer/schema.py` ya documenta que la terna con `partida_id` se
consideró y se **descartó** por ser *más laxa* que el writer.

### El matiz que sí conviene decir

**Esquema y writer son dos barreras distintas, y hoy sólo una está puesta.**
La base productiva no tiene ni una restricción: allí el gemelo **entra** por
cualquier escritura que no pase por el writer (una restauración, una
importación, Cypher a mano). No cambia el veredicto —la regla de identidad es
la correcta— pero sí dice dónde está la cobertura real. No se toca nada de
producción aquí; queda declarado.

---

## 8. Un defecto real, encontrado sólo al juntar las ramas

La comprobación de honestidad de R1 (`INCONSISTENT` /
`EXEC_NOOP_WITHOUT_GRAPH_EVIDENCE`) pregunta al grafo «¿queda algo con esta
`idempotency_key`?» y, si no, declara el desenlace inconsistente.

**Presupone que toda operación deja algo llevando su clave.** Cierto para las
que **crean** (nodo o arista); **falso** para las que **cierran** una vigencia
(`UPDATE_ENTITY` / `SUPERSEDE_ASSERTION`): `close_entity_validity` y
`close_assertion_validity` sólo hacen `SET` sobre un nodo que ya existía, y ese
nodo conserva la clave de quien lo **creó**, nunca la de este cierre.

Consecuencia medida: **reaplicar un plan de sólo cierre se declaraba
`INCONSISTENT` con el conocimiento intacto.** Falso positivo.

No lo vio nadie porque hacía falta la combinación: R1 no tenía en su rama una
prueba de reaplicación de cierre; la que lo detecta —
`test_knowledge_v3_e2e_neo4j_real.py::TestCesacionContraGrafoReal::
test_la_cesacion_cierra_la_vigencia_y_conserva_la_historia`— es **preexistente**
y vive en otra suite.

**Corregido** excluyendo de la comprobación las claves de operaciones de cierre
— derivadas del catálogo `CLOSING_TYPES` del executor, no de una lista paralela
que haya que acordarse de actualizar. Se excluyen porque para ellas **la medida
no existe**, no porque se prefiera callar: sobre un cierre esta comprobación no
puede distinguir «revertido» de «nunca estampado».

**La garantía de R1 no se apagó**, y no se presume:

* `test_reaplicar_un_plan_de_solo_cierre_no_se_declara_INCONSISTENT` — el falso
  positivo, cerrado;
* `test_y_la_garantia_de_R1_sigue_mordiendo_donde_SI_se_puede_medir` — control
  positivo: sobre una **creación**, borrar el conocimiento y dejar la marca
  sigue dando `INCONSISTENT` con `EXEC_NOOP_WITHOUT_GRAPH_EVIDENCE`;
* la demostración completa de R1 (`artifacts/tanda3-r1/`, 5 escenarios) corre
  **verde entera** sobre el árbol integrado, escenario `INCONSISTENT` incluido.

---

## 9. Calibración: dos capas que se cubren la una a la otra

Al calibrar `test_nueva_la_evidencia_que_otra_asercion_viva_sostiene_no_se_borra`
apareció algo que merece constar, porque **una sola mutación no lo pone rojo**:

| mutación | resultado |
|---|---|
| retirar la guarda de dentro del `DELETE` | **verde** (el censo aún protege) |
| ignorar el censo de referencias vivas | **verde** (la guarda aún protege) |
| **retirar las dos** | **ROJO** |

Es defensa en profundidad real, no redundancia decorativa, y confirma por qué
la condición de cero referencias vivas **debe** viajar dentro de la operación
atómica de borrado: el censo informa, la guarda decide, y entre uno y otra el
grafo puede cambiar. Separar `COUNT` y `DELETE` introduciría TOCTOU.

Dicho con precisión, para no vender la prueba por más de lo que mide: el test
ejercita la rama del **censo**; la guarda del `DELETE` es la que cubre la
ventana temporal, y sólo se observa al retirar ambas.

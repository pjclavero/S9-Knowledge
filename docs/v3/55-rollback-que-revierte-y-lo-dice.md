# 55 — El rollback revierte lo que creó, y dice lo que no

**Rama:** `equipo-r1/rollback-procedencia-honesto`
**Bases de partida:** `feat/writer-ruta-operador-rollback-durable` (`22f0660`) +
`equipo1/procedencia-navegable` (`dbf0c94`)
**Ámbito:** `data-engine/app/knowledge_v3/writer/` — `rollback.py` (qué entra en
el documento), `rollback_provenance.py` (nuevo), `writer.py` (verdad del
desenlace), `cli.py`, `idempotency.py`, `executor.py`.

---

## 1. Los tres defectos, tal como los midió el supervisor

Cadena real: apply por la CLI del writer → procedencia persistida → ejecución
del documento de rollback.

```
antes:    V3Entity 4 · V3Assertion 1 · V3Source 1 · V3Episode 7 · V3Evidence 7
          SUPPORTED_BY 1 · HAS_SUBJECT 1 · HAS_OBJECT 1 · HAS_EPISODE 7 · HAS_FRAGMENT 7 · LEADS 2
rollback: DELETE_RELATIONSHIP {borradas:1} · DELETE_NODE {borrados:1}
después:  V3Entity 4 · V3Source 1 · V3Episode 7 · V3Evidence 7 · HAS_EPISODE 7 · HAS_FRAGMENT 7 · LEADS 2
```

1. **15 nodos y 14 aristas de procedencia quedaban huérfanos**, con el texto
   literal de la fuente dentro y nada apuntándolos. El `DETACH DELETE` se
   llevaba en silencio `SUPPORTED_BY`, `HAS_SUBJECT` y `HAS_OBJECT`. Y el
   documento afirmaba `"unrecoverable": []`: **evidencia falsa**, no una
   carencia declarada.
2. **Re-aplicar el mismo plan devolvía `APPLIED` con rc=0 y 0 escrituras.**
   Nadie limpiaba las claves aplicadas y —lo más grave— la marca autoritativa
   `V3AppliedOperation` sobrevivía en el grafo al borrado del conocimiento que
   reclamaba. Un runner desatendido leía éxito limpio sobre un grafo vacío.
3. **`--rollback-out` se sobrescribía con un documento vacío** al repetir el
   apply (el no-op idempotente devuelve `instructions: []`). Repetir una orden
   inocua destruía la única póliza de recuperación.

## 2. La trampa: las dos direcciones son un solo criterio

El supervisor montó dos aserciones **compartiendo fragmento** y deshizo sólo
una. Que la evidencia compartida sobreviviera pasaba **por accidente**: pasaba
porque el rollback no borraba procedencia en absoluto. En cuanto se corrige la
dirección A, ese caso deja de ser gratis.

Aquí las dos direcciones salen del **mismo** criterio, **cero referencias
vivas**, mirado desde los dos lados:

| Dirección | Regla | Resultado |
|---|---|---|
| A — huérfano | `V3Evidence` sin ninguna `(:V3Assertion)-[:SUPPORTED_BY]->` viva | se borra |
| B — compartido | otra aserción viva sigue apuntándola | **no** se borra, y se **declara** en `unrecoverable` |
| cascada | `V3Episode` sin `HAS_FRAGMENT`, `V3Source` sin `HAS_EPISODE` | se borran, sólo si son **antepasados** de los fragmentos purgados |

El **orden** es lo que hace que la cuenta mida algo:

1. `DELETE_NODE` de la aserción (su `DETACH DELETE` se lleva `SUPPORTED_BY`,
   `HAS_SUBJECT`, `HAS_OBJECT` — y ahora el documento lo **declara** en
   `detaches_provenance`);
2. censo de **antepasados por el camino**, `evidencia ← episodio ← fuente`, en
   una sola consulta encadenada — después ya no habría aristas que seguir, y
   dos `MATCH` sueltos darían producto cartesiano y 0 filas;
3. censo de **referencias vivas**;
4. cascada de borrado. La condición de cero referencias viaja **dentro** del
   propio `DELETE`: el censo informa, no decide.

## 3. Qué entra ahora en el documento de rollback

A las tres acciones de siempre se añaden dos:

* `PURGE_PROVENANCE` — lleva `fragment_ids` (los que el writer estampó en la
  aserción, leídos del plan, no del grafo), `workspace` y `partida_id`. Se
  ejecuta **después** del `DELETE_NODE`.
* `FORGET_APPLIED_OPERATION` — retira la marca `V3AppliedOperation`. Sin ella,
  el grafo sigue afirmando «ya aplicado» sobre conocimiento borrado.

`unrecoverable` deja de ser decorativo: `execute_rollback` escribe en él lo
conservado por compartido (`ROLLBACK_RETAINED_SHARED`) y los residuos medidos
(`ROLLBACK_RESIDUE`).

## 4. Verdad del desenlace, sin gates nuevos

`EXEC_NOOP_WITHOUT_GRAPH_EVIDENCE` se mide **después** de la transacción: si
una clave se declara no-op y en el grafo no queda ningún nodo ni arista con esa
`idempotency_key` (la marca está excluida a propósito: es la que sobrevivía),
el desenlace es `INCONSISTENT` y la CLI sale con `1`.

**No impide ninguna escritura.** No es un gate: no bloquea, no exige
declaración del operador y no se evalúa antes de escribir. Sólo impide que el
resultado afirme lo que el grafo no sostiene.

## 5. Mandos de operador

* `--forget-applied-keys <rollback.json>` — retira del almacén las claves de un
  documento ya ejecutado. Explícito y no automático: olvidar una clave habilita
  una reescritura. El JSONL sigue siendo append-only: se anota una **lápida**,
  no se reescribe la historia.
* `--rollback-out` — un documento **sin instrucciones nunca pisa** una póliza
  existente (`CLI_ROLLBACK_OUT_PRESERVED`, rc=2).

## 6. Frontera con el bloque de aislamiento por ámbito (equipo R2)

Este bloque **no toca** `rollback.rollback_query()`: la generación de Cypher de
las consultas de borrado del conocimiento sigue siendo suya.
`rollback_provenance.rollback_query_for()` sólo **encamina** las dos acciones
nuevas y delega el resto.

**Requisitos que este bloque le deja a R2:**

1. **Hacía falta una forma de consulta nueva** —borrar un `V3Evidence` /
   `V3Episode` / `V3Source` por su clave durable y bajo condición de cero
   referencias— que `rollback_query()` no tenía: sus dos formas localizan por
   `entity_id`/`assertion_id` + `idempotency_key`, y los nodos de procedencia no
   llevan `idempotency_key` ni ninguno de esos campos. Vive en
   `rollback_provenance.py` para no invadir la capa de R2. **Si R2 unifica la
   generación de Cypher, estas cinco consultas son las que hay que absorber.**
2. **El filtro de ámbito de la purga es deliberadamente estrecho**:
   `partida_id IS NULL` si el plan no declara partida, igualdad exacta si la
   declara. Nunca alcanza otra partida, pero **tampoco cubre reglas de
   visibilidad más finas**: si R2 introduce un criterio de ámbito canónico,
   `rollback_provenance._scope()` es el único punto que hay que sustituir.
3. `PURGE_PROVENANCE` **no se traduce a una consulta única**: es una secuencia
   con censo intermedio. Cualquier ejecutor que R2 escriba tiene que respetar el
   orden del §2 o la cuenta de referencias vivas deja de medir.

## 7. Lo que NO cubre este bloque (declarado)

* El criterio de borrado es de **alcanzabilidad**, no de autoría: un fragmento
  creado por un apply anterior y referenciado sólo por la aserción revertida
  también se purga. Es seguro —exige cero referencias vivas— pero no es
  «sólo lo que creó este apply» en sentido estricto, y se dice.
* La procedencia se persiste en su **propia transacción**, después de la del
  plan (`pipeline.write_provenance`). El rollback la revierte, pero el par
  apply+procedencia sigue sin ser atómico: un fallo entre ambas deja
  conocimiento sin procedencia, que es lo que `PROVENANCE_FAILED` anota.
* `RESTORE_PROPERTIES` sigue sin poder devolver propiedades que el writer no
  leyó antes de escribir. Límite heredado, no tocado aquí.

## 8. Evidencia

`artifacts/tanda3-r1/demostracion_rollback_procedencia.py` — cinco escenarios
contra un Neo4j real y efímero, con censo del grafo antes y después de cada uno
y las dos direcciones medidas. El contenedor se levanta con el **mismo**
mecanismo de la fixture `neo4j_efimero`, importado, no copiado.

Pruebas sin contenedor: `data-engine/app/tests/test_knowledge_v3_rollback_procedencia.py`.

# 58 · Propiedad por apply: qué puede borrar un rollback, y qué no

> **Un rollback sabe exactamente qué creó el apply que revierte, y no borra nada
> más. Y revertir tiene las mismas garantías operacionales que aplicar.**

Bloque 5B. Cierra cuatro defectos medidos por un supervisor independiente sobre
la ruta de operador.

---

## 1 · La propiedad, literal

```
apply X      ->  posee EXACTAMENTE el conjunto PX
rollback X   ->  puede eliminar PX
                 EXCEPTO los elementos compartidos todavia vivos
             ->  NO puede eliminar  P¬X
```

Hasta este bloque el producto no podía **expresar** esa frase: no había ninguna
propiedad del grafo que dijese qué apply había creado qué.

## 2 · La identidad durable de procedencia del apply

`knowledge_v3/writer/apply_identity.py` introduce **`apply_id`**, estampado en
cada nodo de procedencia (`V3Source`, `V3Episode`, `V3Evidence`).

```
apply_id = "apply:" + sha256( workspace | ámbito | snapshot_id | plan_hash )[:32]
```

* **Función del contenido, no de la base.** La misma cadena en cualquier Neo4j,
  antes y después de un restore.
* **`elementId` queda descartado y no se usa en ninguna consulta del camino de
  recuperación.** Lleva el UUID de la base y se regenera al restaurar un dump:
  deja de identificar justo durante una recuperación, que es cuando se usa.
* **El ámbito ausente ≠ `None`.** `None` es la capa juego; la ausencia se
  codifica aparte, para que dos applies de ámbitos distintos no compartan
  `apply_id`. Cuando el equipo 5A termine de estampar `partida_id` aguas
  arriba, dos partidas dejarán de coincidir sin tocar este módulo.

### Es una marca de CREACIÓN, no de uso

`provenance._ensure_node` **reutiliza** un nodo que ya existe y sólo estampa en
el `CREATE`. Por eso un nodo que un apply posterior reutiliza **conserva la
marca de quien lo creó**, y `apply_id` contesta *«quién lo creó»* — que es
exactamente la pregunta que el rollback necesita — en vez de *«quién lo tocó»*.

## 3 · El radio deja de ser la corrida

El `PURGE_PROVENANCE` del barrido llevaba `scope: "run"` y **la lista entera de
fragmentos de la corrida**. Medido: revertir un apply que sólo había creado
**una arista** borró **6 episodios y 6 evidencias que ese apply no creó**, y
dejó la `V3Source` con **1 de 7** episodios. Nada vivo se perdió —la guarda de
cero referencias vivas hizo su trabajo— pero **la fuente dejó de ser
navegable**: se borró P¬X.

Ahora la instrucción lleva `scope: "apply"` y `apply_id`, y **no enumera
fragmentos**: el conjunto candidato se **descubre en el grafo**
(`owned_by_apply_query`). Enumerarlos sería volver a fijar el radio en el
documento, y el documento es justo lo que se equivocaba.

## 4 · Lo que NO se ha relajado

La condición de borrado sigue siendo **cero referencias vivas, DENTRO de la
misma operación atómica que borra**. Contar fuera y borrar después es TOCTOU.
La propiedad se añade **en el mismo `WHERE`**, no en un paso previo:

```cypher
UNWIND $ids AS wanted
MATCH (n:V3Evidence {fragment_id: wanted, workspace: $ws})
WHERE  <ámbito>  AND  n.apply_id = $apply_id  AND  NOT EXISTS { ... }
DETACH DELETE n
```

La propiedad **estrecha** el conjunto candidato; nunca lo amplía.

## 5 · Las cuatro garantías del mando de reversión

`cli_rollback --execute` borraba **sin operador y sin auditoría**: con el
entorno y el workspace correctos pero omitiendo `--operator`, la reversión se
ejecutó de verdad —1 relación, 1 marca y 12 nodos de procedencia borrados— con
`"operator": null` en su propio informe. El mando ni siquiera aceptaba
`--audit-log`.

```
sin --operator                  ->  NO BORRA
sin audit log utilizable        ->  NO BORRA
operacion bloqueada             ->  no rc=0
residuos inesperados            ->  no ROLLED_BACK limpio
```

**No es un gate nuevo.** Son las condiciones que el gate del writer ya exige
para escribir —`GATE_OPERATOR_MISSING`, `GATE_OPERATOR_INVALID`,
`GATE_AUDIT_UNAVAILABLE`, y la misma expresión `gate._OPERATOR_ID`— aplicadas a
la operación que **borra**, que no puede pedir menos que la que escribe. Se
comprueban **antes** de resolver la conexión, leer el secreto y abrir sesión:
fail-closed de verdad es no llegar a tocar el grafo.

La auditoría usa el mismo `AuditRecord` append-only del apply, con
`mode: "ROLLBACK"`. El **intento** se registra antes de tocar nada; el
**desenlace**, después. Un bloqueo también deja rastro: un log que sólo guarda
los éxitos no es auditoría.

## 6 · El censo ve lo que el documento no menciona

Tras un rollback «limpio» (`ROLLED_BACK`, *«No queda nada de esa operación en el
grafo»*, `residues: []`) sobrevivía **una `V3AppliedOperation`**: `S0` real = 1
nodo, no 0. Y no era inofensiva —la marca sigue afirmando «esto ya está
aplicado», así que la relación no se puede reescribir y el grafo queda atascado.

`residues` sólo preguntaba por las `idempotency_key` que el **documento**
nombra. Ahora barre además las **marcas colgantes**: `V3AppliedOperation` sin ni
un nodo ni una arista viva con su clave. No se denuncia toda marca ajena —una
marca de otro apply cuyo conocimiento sigue vivo es legítima—, sólo la que el
grafo desmiente.

*Carencia declarada:* el ámbito de ese barrido es el `workspace`, no la partida,
porque hoy `V3AppliedOperation` no lleva `partida_id` (equipo 5A). Mide de más,
no de menos, que es el lado seguro para un censo que **observa y no borra**.

## 7 · Ningún desenlace se contradice

Se medía `"human": "…NO es una reversion limpia…"` junto a `"clean": true` en el
mismo documento. No era una redacción desafortunada: eran **dos definiciones de
«limpio»**.

Ahora hay una. `RollbackReport.clean` significa *ni residuos ni puntos no
revertidos*, y la prosa se deriva de unos **hechos estructurados**
(`rollback_facts`: `ran`, `deleted_anything`, `clean`, …), en la misma
disciplina que los `hechos` de `exit_codes.describe_outcome` del equipo 5C.
La palabra «limpia» sólo puede aparecer bajo `hechos["clean"] is True`.

## 8 · Desenlaces nuevos y códigos de salida

Nombres acordados con el equipo **5C**, que los dejó previstos en su tabla antes
de que existieran:

| desenlace | cuándo | `rc` |
|---|---|---|
| `NO_OPERATOR` | se pidió borrar sin `--operator`, o con forma no admisible | `1` |
| `NO_AUDIT` | sin registro de auditoría utilizable | `1` |
| `UNEXPECTED_RESIDUE` | corrió y quedaron residuos o puntos no revertidos | `1` |

**No se toca `exit_codes`**: `ROLLBACK_OUTCOMES_OK` es lista blanca y falla
cerrado, así que un desenlace nuevo sale `!= 0` por omisión. Se comprueba en las
pruebas en vez de darlo por supuesto. `INCOMPLETE` se conserva como alias
histórico del `code` del acta (`CLI_ROLLBACK_INCOMPLETE`), que no cambia.

## 9 · Cómo se midió

Contra **Neo4j real**, con censo completo antes y después y **huella del
contenido sin `elementId`**
(`tests/test_knowledge_v3_equipo5b_propiedad_rollback_neo4j_real.py`).

* **Dos applies distintos sobre la misma fuente.** El apply 1 crea la fuente, 3
  episodios y 3 fragmentos; el apply 2 vuelve sobre la **misma** fuente y añade
  1 episodio y 1 fragmento, reutilizando la fuente. Revertir el segundo borra
  `fr-4` y `ep-4` **y nada más**: la fuente sigue con sus 3 episodios.
* **Ningún conjunto vacío pasa por bueno.** Cada aserto sobre un conjunto va
  precedido de la comprobación de que no está vacío: `[] == []` demuestra
  cualquier cosa.
* **Controles negativos calibrados.** Dos mutaciones sobre el producto, cada una
  verificada en rojo y revertida:
  * la propiedad deja de acotar (`ownership_clause` devuelve `true`) → la prueba
    de propiedad falla con `['fr-1','fr-2','fr-3','fr-4'] == ['fr-4']`;
  * el censo deja de mirar las marcas colgantes → la prueba del censo falla.

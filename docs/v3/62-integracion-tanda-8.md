# 62 — Integración tanda 8: orden de los alias, propiedad durable y el escenario A/B

Integra `equipo8a/reutilizacion-entidades` (`b38db5e`) y
`equipo8b/ownership-durable` (`a349921`) sobre
`integracion/carril7-integracion` (`34fca8f8`).

Las tres operaciones de esta integración no son fusionar: son cerrar el acople
que 8B dejó señalado, hacer la migración que 8B declaró y **no** coló, y volver
a medir el escenario que da sentido a toda la tanda.

---

## 1. El orden de los alias — un defecto silencioso, cerrado y **calibrado**

8A persiste los alias de la entidad **dentro del `payload`**, y `payload` está
en `IDEMPOTENCY_KEY_FIELDS`. Luego los alias entran en la `idempotency_key`, y
por ella en el `ownership_id`, que 8B deriva del **conjunto** de claves del
apply.

Que la propiedad **note** el payload no es un fallo: un payload distinto es una
operación lógica distinta. El riesgo es el **ORDEN**, y es silencioso: si la
lista de alias no va canónicamente ordenada, dos corridas del mismo apply
lógico cuyo catálogo enumere los alias en otro orden producen `ownership_id`
distintos y **reintroducen el defecto que 8B acaba de cerrar sin romper ningún
hash visible**.

**Medido, no presumido.** `engine/planner.py::_payload_alta` ya ordenaba
(`sorted({...})`). Lo que faltaba era la prueba de que eso es lo que compra la
invariancia. En `tests/test_integracion_tanda8_orden_alias_y_propiedad.py` se
mide **extremo a extremo por el planificador real** (`build_plan` → `seal_plan`
→ `compute_idempotency_key` → `compute_ownership_id`):

| corrida | alias descubiertos, **en ese orden** | `ownership_id` |
|---|---|---|
| directa | `("Cofradia de Ambar", "la Cofradia de Ambar")` | **igual** |
| inversa | `("la Cofradia de Ambar", "Cofradia de Ambar")` | **igual** |

Y la garantía está **calibrada**: se retiró el `sorted` de `_payload_alta` y la
prueba se puso **ROJA** (`el planificador NO esta canonizando el orden de los
alias`); restaurado, verde. Una prueba de invariancia que no puede ponerse roja
no mide nada, así que además se fija que un **conjunto** de alias distinto sí
mueve la propiedad, y que la lista deduplica.

---

## 2. `ownership_clause` migrado a `ownership_id` — con su propia medida

8B lo dejó declarado y no colado, correctamente:

> «La clasificación **sigue consumiendo `apply_id`** […] pero **no cambié el
> predicado de `ownership_clause`**. Migrarlo es operación propia con su propia
> medida.»

`apply_id` es identidad de **intento**: deriva de `plan_hash`, que cubre el
reloj. El mismo apply lógico replanificado tras un restore trae otro `apply_id`
y la clasificación deja de reconocer lo que ella misma creó.

### La medida, contra **dos bases reales**

`tests/escenario_integracion_tanda8.py` — mismo apply lógico, dos bases
efímeras, dos instantes (que es lo que cambia al replanificar tras un restore).
Los `elementId` de las dos bases se comprueban **disjuntos antes** de comparar
nada. Resultado: **OK=19 FALLA=0**.

| pregunta sobre la base 2 (restaurada) | resultado |
|---|---|
| mismo apply lógico → mismo `ownership_id` | `own:1a705d3a…` en **las dos** |
| otro intento → `apply_id` distinto | `apply:74c06ec…` vs `apply:8f7eecb…` |
| PX con la marca **durable** de la base 1 | **exactamente su PX** (2 fragmentos) |
| PX con el **`apply_id`** de la base 1 (control) | **vacío** ← lo que hacía antes |
| PX con el `apply_id` propio de la base 2 (control) | su PX — la consulta no está rota |

Los dos controles son lo que hace que el primer verde signifique algo.

### Por qué el predicado es una **disyunción** y no sólo la durable

Filtrar **sólo** por `ownership_id` es **fail-open** sobre un grafo escrito
antes de que la marca durable existiera: esos nodos llevan `apply_id` y no
llevan `ownership_id`, así que un residuo real deja de verse y el mando diría
`clean` de algo que no lo está. **Medido**: con el filtro sólo por la durable,
`test_algo_creado_por_X_no_compartido_y_presente_sale_INCOMPLETE` (equipo 6B)
pasó de `UNEXPECTED_RESIDUE` a **`ROLLED_BACK`**.

Por eso `Propiedad` lleva las marcas que el documento declare y el predicado es
su disyunción, con `coalesce` (en Cypher `NULL = $x` es `NULL`, no `false`, y
propagado por un `OR` deja de leerse a simple vista):

```
misma base, mismo intento  -> casan las dos
base restaurada / replan   -> casa `ownership_id`   (`apply_id` no existe allí)
grafo anterior a 8B        -> casa `apply_id`       (no hay `ownership_id`)
```

No amplía la propiedad a nada ajeno: `apply_id` deriva del `plan_hash` de
**este** plan, así que sólo lo llevan los nodos que escribió este mismo intento
— que son, por definición, del mismo apply lógico. La propiedad sigue sólo
**estrechando** el conjunto candidato.

### Lo que se conserva

* La condición de **cero referencias vivas sigue dentro del `DELETE` atómico**
  (`_delete_if_unreferenced`). Separarla sería TOCTOU, y el operador lo ratificó.
* El vecino (`_ajeno`) se juzga con **la misma** `Propiedad` que el nodo: si se
  escribieran por separado, un mismo vecino podría contar a la vez como propio
  y como ajeno.
* Marca malformada → excepción. Sin propiedad declarada no se borra.
* Sin marca → radio antiguo `run`, **declarado**, no disfrazado.

---

## 3. El escenario A/B con la frase original — y el control

`tests/escenario_carril7.py`, Neo4j vacío, bootstrap del producto, sin Cypher
manual de escritura, con la frase original `"Sela Marrec lidera la Cofradia de
Ambar"` y **sin el rodeo**.

**Resultado: `OK=12 FALLA=5`** — la misma cifra de antes. **No alcanza `apply`.**

Antes de atribuir nada se ejecutó el **control sobre la base sin estas dos
ramas** (`34fca8f8` extraída con `git archive`, verificada sin
`ownership_identity.py` ni los tests de 8A), en **directorios separados** para
las dos corridas — la primera pareja compartía `/tmp`, y esa medida se descartó
por contaminada.

| | base pura (control) | 8A+8B integradas |
|---|---|---|
| resultado | `OK=12 FALLA=5` | `OK=12 FALLA=5` |

**Los cinco fallos son preexistentes.** Pero **la causa ha cambiado**, y el
agregado lo oculta. Siguiendo los valores de la partida A:

| valor | base pura | 8A+8B |
|---|---|---|
| `decisions_by_outcome` | `REVIEW: 1` | **`ACCEPT: 1`** |
| `link_existing` | 1 | **2** |
| `create_entity` | 1 | **0** |
| `assertions` | 0 | **1** |
| `plan_operations` | 0 | **2** |
| `no_promovible_por` | `["object_entity_id"]` | — |
| `reason_codes` | `ENTITY_PROVISIONAL` | — |
| `diagnostics` | `LEDGER_SKIPPED_PLAN_NOT_APPROVED` | **ninguno** |

Es decir: **8A cierra la causa documentada**. El comentario del propio
escenario decía que con la frase original «el objeto sale `CREATE_PROVISIONAL`,
el claim se va a `REVIEW` […] y la corrida no aplica nada». Eso ya no ocurre:
el objeto resuelve por los alias persistidos, el claim sale `ACCEPT` y el plan
queda **aprobado, con las seis validaciones en `PASS`** y una aserción
`Sela Marrec —LEADS→ Cofradia de Ambar`.

### El bloqueo nuevo, DECLARADO y no tocado

El apply de A muere **después** del plan, en el ejecutor:

```
write: {"applied_operations": 0, "codes": ["EXEC_SCOPE_MISMATCH"],
        "outcome": "ABORTED", "mode": "APPLY"}
```

**Causa, leída del código, no supuesta.** `writer/executor.py` lee la
precondición de concurrencia con `cypher._scoped_match`, que exige **ámbito
exacto**: `partida_id=None` exige capa juego, `partida_id="partida:A"` exige esa
partida. El plan de A declara `partida:A` y opera sobre `entity:sela-marrec` /
`entity:cofradia-ambar`, que son de **capa juego** (`partida_id IS NULL`), así
que la lectura acotada no las ve, la de cualquier ámbito sí, y aborta.

Y el propio módulo documenta la regla contraria para los extremos de una
relación — `cypher._visible_predicate`:

> «Se usa para los extremos de una relación: un plan de partida Y puede enlazar
> tanto entidades de capa juego como de su propia partida (M2 […]), nunca de
> otra partida.»

O sea: **un apply de partida no puede referenciar entidades compartidas del
lore**, aunque el diseño dice que debe poder. Es un defecto **ajeno** a estas
dos ramas — estaba enmascarado porque A nunca pasaba de `REVIEW` — y cae de
lleno en el terreno de multi-partida y de la semántica de visibilidad, que esta
integración **no toca**. Se declara; no se arregla aquí.

---

## Suites

| suite | cifra |
|---|---|
| offline completa (`data-engine/app/tests`) | **5498 passed, 147 skipped, 2 xfailed**, rc=0 |
| Neo4j real: 5a, 6c, 8a, integración5, carril B, e2e, estado durable, tanda3, tanda4, writer | **102 passed, 3 failed, 1 skipped** |
| Neo4j real: 5b, 6b, 4b (camino de reversión) | **16 passed, 2 failed, 6 skipped** |
| `escenario_integracion_tanda8.py` (Neo4j real) | **OK=19 FALLA=0** |
| `escenario_carril7.py` (Neo4j real) | `OK=12 FALLA=5` — **igual que el control** |

Cifras de ejecución completa de cada fichero, no de un subconjunto.

### Fallos ajenos declarados — los cinco son PREEXISTENTES

Todos se reprodujeron sobre la base pura `34fca8f8` (extraída con `git archive`
y verificada sin `ownership_identity.py` ni los tests de 8A), y los de 4B
además sobre la fusión 8A+8B **sin** esta migración:

| test | aquí | base pura |
|---|---|---|
| `equipo4b::test_sin_el_barrido_el_rollback_deja_procedencia_huerfana` | FALLA | FALLA |
| `equipo4b::test_casos_A_B_C_D_conservacion_y_limpieza` | FALLA | FALLA |
| `tanda4::test_ciclo_apply_repeat_rollback_apply_vuelve_a_S1` | FALLA | FALLA |
| `tanda4::test_el_state_hash_sigue_describiendo_el_nodo_despues_del_rollback` | FALLA | FALLA |
| `tanda4::test_un_rollback_con_residuos_no_puede_salir_con_cero` | FALLA | FALLA |

Los tres de `tanda4` salen por `GATE_AUDIT_UNAVAILABLE` / `NO_AUDIT` («no hay
registro de auditoría»), que es utillaje, no clasificación.

### Una regresión SÍ apareció, y se corrigió antes de cerrar

Con el predicado filtrando **sólo** por `ownership_id`,
`equipo6b::test_algo_creado_por_X_no_compartido_y_presente_sale_INCOMPLETE`
pasó de `UNEXPECTED_RESIDUE` a `ROLLED_BACK`: un residuo real dejaba de verse.
Es lo que motivó la disyunción del §2. Con ella, verde.

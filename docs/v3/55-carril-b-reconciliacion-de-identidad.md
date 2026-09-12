# 55 — Carril B: reconciliar identidad contra el grafo real

> Que un operador pueda meter un fichero real y que el sistema decida por sí
> mismo qué entidades ya existen en el grafo y cuáles hay que crear, sin que
> nadie siembre nada a mano.

## 1. El hueco, medido antes de tocarlo

Un supervisor independiente ejecutó la cadena completa y su primer `APPLY`
contra un Neo4j real dio `EXEC_TARGET_MISSING`. No era culpa de su fuente: el
plan del ejemplo del carril A tiene la misma forma. Reproducido sobre este
mismo HEAD con `artifacts/carril-b/calibracion_hueco.py`, contra un Neo4j real
y vacío:

```
== plan del ejemplo (carril A, dry-run)
   operaciones: ["CREATE_ASSERTION", "PROJECT_RELATION"]
   CREATE_ENTITY en el plan: 0
   objetivos que el plan PRESUPONE existentes: ["entity:casa-ciervo", "entity:cofradia-ambar"]

== APPLY contra Neo4j real y VACIO
   outcome: ABORTED
   codes:   ["EXEC_TARGET_MISSING"]
   -> EXEC_TARGET_MISSING | la operacion ...:project apunta a 'entity:cofradia-ambar', que no existe
   nodos de conocimiento escritos: 0
```

Ese guion es el **control positivo** del carril: si dejara de ponerse rojo, el
arreglo no estaría demostrando nada.

### 1.1 La causa, no el síntoma

El síntoma es "la entidad no existe". La causa son **dos huecos encadenados**:

1. **El catálogo era un fichero y el grafo era otra cosa.** `--catalogo` declara
   qué entidades existen; el writer escribe en un grafo real; nada contrastaba
   las dos afirmaciones.
2. **Ningún camino del producto emitía jamás un `CREATE_ENTITY`.** El tipo está
   en el contrato congelado desde el principio, el executor sabe ejecutarlo y
   los planes *gold* lo traen escrito **a mano** — pero `engine/planner.py` no
   lo producía nunca. Verificado leyendo el emisor, no contando apariciones:
   `_operations()` emitía `CREATE_ASSERTION`, `SUPERSEDE_ASSERTION` y
   `PROJECT_RELATION`, y nada más.

Por eso "sembrar a mano por Cypher" era la única salida: no había productor.

## 2. Lo que hace este carril

```
catálogo declarado ──┐
                     ├─► reconciliación ─► LINK_EXISTING
grafo real ──────────┘                  └─► CREATE_ENTITY_REQUIRED ─► revisión humana
                                                                          │
                                                                    plan sellado
                                                                          │
                                                              writer (gate triple)
                                                                          │
                                                                    procedencia
```

### 2.1 Dos fuentes, dos preguntas distintas

Es el reparto que faltaba:

| Fuente | Responde a | Módulo |
|---|---|---|
| `--catalogo` (fichero) | **cómo se llaman** las cosas: vocabulario de identidad | `load_catalog` |
| el grafo (`--desde-grafo`) | **qué existe** de verdad, con su `version` y `state_hash` | `writer/reads.list_entities` |

Antes solo existía la primera, tratada como si respondiera también a la
segunda. Ahí estaba el `EXEC_TARGET_MISSING`.

**Medido**: sin catálogo declarado y con el grafo vacío, la nota de ejemplo da
5 claims → 3 `REVIEW` + 2 `ABSTAIN`, 0 operaciones. El motor manda a revisión
humana cualquier hecho sobre una entidad provisional (`ENTITY_PROVISIONAL`), y
eso está bien: sin vocabulario no hay identidad de la que fiarse. El catálogo
declarado no es vestigial — es la declaración del operador sobre su mundo.

### 2.2 La regla que no se relaja

    LINK_EXISTING  ≠  CREATE_ENTITY

Un enlace cuya entidad **no aparece en el grafo** no se convierte en alta
automática. Se **degrada** a `CREATE_ENTITY_REQUIRED` con el motivo
`ENLACE_SIN_RESPALDO_EN_GRAFO` escrito al lado, y espera a una persona. Es el
hallazgo del supervisor convertido en decisión revisable: el fichero decía que
existía, el grafo dice que no, y quien resuelve la discrepancia es un humano,
no un valor por defecto.

La aprobación es **por id, uno a uno**. No hay `--aprobar-todas`: una bandera
así sería la conversión silenciosa que este carril existe para impedir, sólo
que escrita en la línea de comandos. Hay una prueba que comprueba que ninguna
opción del parser contiene "todas".

### 2.3 Aprobar autoriza una creación; no cambia cómo se resuelve la identidad

Primer intento, **medido y descartado**: meter las altas aprobadas en el
glosario y el catálogo del resolutor. Efecto observado: la cascada cambiaba de
rama y los `entity_id` derivados pasaban de `entity:prov:…` a `entity:new:…`
entre la primera pasada y la segunda. Es decir, **el operador aprobaba unos ids
y se escribían otros**, y la aprobación dejaba de cubrir lo que se escribía.

La regla que queda: la resolución es idéntica con aprobación y sin ella; lo
único que la aprobación mueve es el **snapshot**, donde el alta entra marcada
`pending_creation`.

## 3. Cambios en el producto

| Fichero | Qué |
|---|---|
| `writer/cypher.py` | `list_entities_query` (listado por workspace+partida, ámbito en el `WHERE`) y `locate_entity_query` |
| `writer/reads.py` | `list_entities` / `locate_entity`. Un fallo del driver **se propaga**: degradar a "no hay ninguna" convertiría una caída de Neo4j en una avalancha de altas |
| `resolution/catalog.py` | `Neo4jEntityCatalog` **implementado** (era un `NotImplementedError` declarado, a la espera de alguien con un grafo real). Cumple los cinco requisitos que el enganche pedía |
| `engine/snapshot.py` | `SnapshotEntity.pending_creation` y `canonical_name` |
| `engine/planner.py` | `_altas()` — **emite `CREATE_ENTITY`**, sólo para entidades `pending_creation`; `_dedupe_altas()`; y no proyecta relaciones sobre una entidad que se crea en el mismo plan |
| `pipeline/graph_catalog.py` | catálogo y snapshot **observados**, con `version`/`state_hash` del nodo |
| `pipeline/entity_decisions.py` | el documento de decisiones, la aprobación y el fallo cerrado |
| `pipeline/ingest_cli.py` | `--desde-grafo`, `--revisar`/`--aprobar-alta`/`--revisor`, `--apply` |

### 3.1 Por qué el planificador no proyecta una relación sobre un alta

`PROJECT_RELATION` copia `expected_version`/`expected_hash` del snapshot, y el
executor los contrasta contra el nodo. Una entidad que se crea en la misma
transacción **no los tiene todavía**. Proyectar produciría un plan que el
propio motor declara no anclado (validador `concurrency`) o que aborta al
aplicarse. El hecho **sí** se escribe como `CREATE_ASSERTION`, que es donde
vive el conocimiento; la arista proyectada la emitirá la siguiente ingesta,
cuando la entidad ya exista con su versión. Es exactamente lo que hacen los
planes gold que traen un `CREATE_ENTITY` (`dev/kestrel-tripulacion`): alta +
aserción, sin proyección.

## 4. Los mandos del operador

Tres pasos, ninguno saltable. Salida real pegada en
`artifacts/carril-b/evidencia-ejecucion.txt`.

```
# 1. ingesta: el catálogo se lee del grafo y se reconcilia
python3 -m knowledge_v3.pipeline.ingest_cli fuente.md \
    --perfil perfil.json --catalogo catalogo.json --desde-grafo \
    --out-dir DIR \
    --neo4j-uri "$S9K_NEO4J_URI" --neo4j-user neo4j \
    --neo4j-password-file /ruta/privada/neo4j.pass

# 2. revisión: una persona aprueba cada alta por su id
python3 -m knowledge_v3.pipeline.ingest_cli --revisar \
    --decisiones DIR/decisiones.json --revisor pjc \
    --aprobar-alta entity:cofradia-ambar --aprobar-alta entity:casa-ciervo

# 3. APPLY, con el gate del writer
S9K_ALLOW_REAL_INGEST=1 S9K_WRITER_WORKSPACE=ws-cofradia \
python3 -m knowledge_v3.pipeline.ingest_cli fuente.md \
    --perfil perfil.json --catalogo catalogo.json \
    --apply --operador pjc --decisiones DIR/decisiones.json --neo4j-...
```

### 4.1 Qué se observó

Grafo vacío, la nota real del carril A:

```
PASO 1  {"create_entity_required": 10, "graph_entities_observed": 0,
         "link_existing": 0, "pendientes": 10}
        ALTA PENDIENTE entity:cofradia-ambar (Faction)
            STRONG_MATCH,EXACT_NAME,...,ENLACE_SIN_RESPALDO_EN_GRAFO

PASO 2  (APPLY sin revisar)
        ERROR [altas]: 10 alta(s) de entidad sin aprobacion humana ... [rc=3]
        el grafo NO se ha movido: [{"entidades": 0}]

PASO 4  (APPLY tras aprobar)
        write: {"applied_operations": 3, "codes": [],
                "created_ids": ["entity:casa-ciervo", "entity:cofradia-ambar",
                                "assertion:b4b9a508..."],
                "mode": "APPLY", "outcome": "APPLIED"}

PASO 6  assertion:b4b9a508... -> 1 fila(s)
        {"episode_id": "ep-35a91c10...", "fragment_id": "ef-dcac9508...",
         "literal": "La Cofradia de Ambar es aliada de la Casa del Ciervo.",
         "predicate": "ALLY_OF", "source_asset_id": "sa-1f9c4e88...",
         "source_name": "nota-cofradia-de-ambar.md"}
```

El recorrido se lee con `provenance.trace`, que va **por el camino** en una
sola consulta encadenada: no hay dos `MATCH` sueltos, así que no puede
producirse el producto cartesiano que devolvería cero filas y parecería medir.
Y el conjunto es **no vacío**: un `[] == []` no habría demostrado nada.

## 5. Garantías del writer: intactas

Ninguna se relajó. Comprobado por efecto, no leyendo el código:

* **`GATE_ENV_NOT_ALLOWED`** — sin `S9K_ALLOW_REAL_INGEST=1` no se escribe
  aunque haya driver y altas aprobadas; el grafo se queda a 0 nodos.
* **`GATE_WORKSPACE_NOT_DECLARED`** — sigue exigiendo `S9K_WRITER_WORKSPACE`.
* **`GATE_PLAN_HASH_NOT_CONFIRMED`** — el hash lo confirma la propia cadena
  contra el plan que acaba de sellar.
* **Dry-run por defecto** — `--apply` hay que escribirlo. Y hay una prueba que
  falla si el dry-run intentara siquiera construir una fábrica de driver.
* **La contraseña nunca por `argv`** — sólo `--neo4j-password-file` (o `-`),
  fichero privado; un fichero legible por el grupo se rechaza.
* **Dos declaraciones nuevas, ambas fallando cerrado**: sin `--operador` y sin
  un documento de decisiones revisado, el `APPLY` corta **antes** de abrir
  conexión.

## 6. Carencias declaradas

1. ~~**`ENTIDAD_SIN_STATE_HASH`**~~ — **CERRADA**. Se declaró que «el carril lo
   rodea no proyectando», y eso **era falso en la segunda ingesta**: en la
   primera pasada la entidad es `pending_creation` y el planificador no
   proyecta, pero en la segunda ya está en el grafo, **sí** emite
   `PROJECT_RELATION`, y el plan moría contra el validador congelado con
   *"modifica algo existente sin expected_version/expected_hash"* — traza
   Python cruda y `rc=1` para el operador. La limitación declarada era **más
   pequeña que la real**: no era «no se proyecta», era «la segunda ingesta de
   cualquier fuente no vuelve a funcionar nunca».

   Cerrada tocando el writer: `CREATE_ENTITY` estampa ahora `version` y un
   `state_hash` que **describe el estado realmente persistido** y se recomputa
   desde el grafo (`writer/state.py`). `RESERVED_PROPS` **se conserva**: lo que
   prohíbe es que el *payload* dicte su propio hash, que es justo lo que
   volvería inútil el control optimista; el defecto no era la reserva, sino que
   nadie más lo escribía.
2. **`GRAFO_SIN_ALIAS`** — el grafo no almacena alias de entidad. El glosario
   recibe sólo el nombre canónico de cada nodo; las menciones por alias
   dependen del perfil.
3. **Contrato del documento de decisiones** — `entity-decisions/carril-b-v1`
   **no** es uno de los contratos congelados. No existe ninguno que exprese
   "decisiones de identidad pendientes de revisión humana", e inventarse uno con
   la etiqueta `v3-internal-v1` habría sido colar un contrato nuevo por la
   puerta de atrás. Se declara como lo que es: un artefacto de operación.
4. **Un plan sólo de altas no es expresable** en el contrato congelado: una
   `CREATE_ENTITY` tiene que colgar de una decisión `ACCEPT`, y `ACCEPT` exige
   predicado, dirección, sujeto y objeto. Verificado contra el validador:
   *"operacion op:sonda colgando de una decision REVIEW: solo ACCEPT puede
   generar escritura"*. Por eso las altas viajan **en el mismo plan** que el
   hecho que las menciona, igual que en los planes gold.
5. **Una entidad sin tipo no puede darse de alta**: `CREATE_ENTITY` usa
   `payload.entity_type` como etiqueta. Las altas sin tipo observado se filtran
   y quedan sin crear.

## 7. Para R1 y R2

Este carril **no toca el camino de rollback**. Pero crea nodos que R1 debería
conocer:

* **`CREATE_ENTITY` ahora se emite de verdad.** Hasta ahora ningún plan del
  producto lo traía, así que el rollback de una entidad creada era código sin
  ejercitar por la ruta real. Ahora sí se ejercita.
* El documento de rollback de un plan con altas incluirá la creación de
  entidades **que otras aserciones pueden estar referenciando ya**. Contar
  referencias vivas antes de borrar una entidad (R1) es exactamente el caso.
* Para R2: `list_entities_query` filtra por `workspace` **y** por ámbito de
  partida en el `WHERE`, con el mismo `_visible_predicate` que el resto. Hay
  pruebas contra Neo4j real con conjuntos **no vacíos por los dos lados** —
  dos listas vacías no demostrarían aislamiento ninguno.

## 8. Cómo reproducirlo

```
S9K_WRITER_NEO4J_REAL=1 python3 artifacts/carril-b/calibracion_hueco.py
S9K_WRITER_NEO4J_REAL=1 python3 artifacts/carril-b/demostracion_vertical.py
S9K_WRITER_NEO4J_REAL=1 python -m pytest \
    data-engine/app/tests/test_knowledge_v3_carril_b_neo4j_real.py -q
```

El contenedor lo levanta y lo destruye `neo4j_efimero_conexion`, el **mismo**
mecanismo de arranque que la fixture de `test_knowledge_v3_writer_neo4j_real`
(`neo4j_efimero` pasa a ser una envoltura de una línea sobre él). No hay un
segundo camino de arranque.

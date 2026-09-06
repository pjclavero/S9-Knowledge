# Idempotencia real y estado durable — evidencia medida

Repo `pjclavero/S9-Knowledge`. Base `integracion/tanda3` =
`9b129b60954238ea6909a090adbc7dbdbebb0553`. Todo lo de abajo se midió contra un
**Neo4j real y efímero** (imagen `neo4j:5.26-community`, base vaciada entre
escenarios), con el **mando del operador** (`knowledge_v3.pipeline.ingest_cli`),
no con un arnés propio.

## 1. El fallo, primero en ROJO

Grafo vacío → ingesta → aprobación de altas → `--apply` (todo `rc=0`), y a
continuación la MISMA fuente otra vez, en **proceso nuevo**:

```
$ python3 -m knowledge_v3.pipeline.ingest_cli examples/ingesta-v3/nota-cofradia-de-ambar.md \
    --perfil ... --catalogo ... --desde-grafo --out-dir DIR --neo4j-...
rc=1
  File ".../knowledge_v3/engine/planner.py", line 625, in build_plan
    raise EnginePlanError(
knowledge_v3.engine.errors.EnginePlanError: el plan construido no valida contra el
contrato congelado: op:claim:extract.deterministic:83ab075abd667658:project modifica
algo existente sin expected_version/expected_hash: no habria concurrencia optimista
```

Causa **medida en el grafo**, no supuesta:

```
MATCH (n:V3Entity) RETURN n.entity_id, n.version, n.state_hash
entity:casa-ciervo       version=0   state_hash=None
entity:cofradia-ambar    version=0   state_hash=None
total V3Entity = 2
```

Neo4j ni siquiera conocía la clave de propiedad `state_hash`
(`UnknownPropertyKeyWarning`): no era que estuviese a `NULL`, es que nunca se
escribió.

La carencia declarada `ENTIDAD_SIN_STATE_HASH` (`docs/v3/55` §6.1) predecía el
hecho pero afirmaba que «el carril lo rodea no proyectando». **Falso en la
segunda ingesta**: en la primera pasada la entidad es `pending_creation` y no se
proyecta; en la segunda ya existe, el planificador **sí** emite
`PROJECT_RELATION` y el plan muere. La limitación declarada era más pequeña que
la real.

## 2. El contrato real de `version` / `state_hash`

Cuatro sitios, ninguno inventado:

| dónde | qué exige |
|---|---|
| `graph-mutation-plan-v3.schema.json` | `expected_version`/`expected_hash`: *"Null solo cuando la operacion crea algo que aun no existe"* |
| `contracts/knowledge-v3/v1/validator.py` §557 | toda operación que **no** crea y no los trae se rechaza |
| `engine/snapshot.py` `SnapshotEntity` | son *"los que el plan copia a `expected_version`/`expected_hash`"* |
| `engine/snapshot.py` `Neo4jReadOnlyGraphSnapshot` cl. 3 | el grafo debe **devolver** `version` y `state_hash` por nodo |

De ahí el contrato, más ancho que «escribe un hash al crear»:

> una entidad que el producto crea sale del `CREATE` con **todo** el estado
> durable que el planificador y el writer le van a exigir después.

**`RESERVED_PROPS` se conserva.** Lo que prohíbe es que el *payload* dicte su
propio `version`/`state_hash` — precisamente lo que volvería inútil el control
optimista. El defecto no era la reserva: era que nadie más lo escribía.

## 3. El arreglo

* `writer/state.py` (nuevo): **una** definición de `state_hash` = `sha256` del
  JSON canónico de las propiedades persistidas del nodo, sin el propio
  `state_hash`. Se descartan los `None` porque Neo4j no almacena propiedades
  nulas: incluirlos daría un hash que el grafo no puede reproducir al releerse.
  El `sha256` se toma del validador congelado, no se reimplementa.
* `writer/cypher.py`: `create_entity` estampa el hash sobre el mapa **ya
  completo** (visibilidad y ámbito incluidos), que es el único punto donde se
  sabe todo lo que va a quedar escrito.
* `writer/executor.py`: el cierre de vigencia **recalcula** el hash sobre el
  estado resultante (un hash que ya no describe el nodo es peor que ninguno), y
  la comparación normaliza `{algorithm, value}` (plan) contra hexadecimal
  (grafo) — sin eso, documento y cadena nunca son iguales y el control se
  vuelve un rechazo constante en vez de una comprobación.

## 4. `S1` exacto en proceso nuevo

Escenario completo, cada `apply` en un **proceso nuevo**, comparando por
**huella del contenido sin `elementId`** (`censo_grafo.py`):

```
PASADA 1  apply -> {"applied_operations": 3, "noop_operations": 0, "outcome": "APPLIED"}
          censo -> {"n_nodos": 21, "n_relaciones": 17,
                    "huella": 4570ab2e77b55b75...}

PASADA 2  apply -> {"applied_operations": 1, "noop_operations": 1, "outcome": "APPLIED"}
          censo -> {"n_nodos": 22, "n_relaciones": 18,
                    "huella": 2802e337d6ea2dbf...}     <- ya proyecta la relación

PASADA 3  apply -> {"applied_operations": 0, "noop_operations": 2, "outcome": "APPLIED"}
          censo -> {"n_nodos": 22, "n_relaciones": 18,
                    "huella": 2802e337d6ea2dbf...}     <- IDÉNTICA
```

`S(pasada2) == S(pasada3)` **exacto** (19231 bytes de censo, byte a byte). Sin
excepción, sin operaciones espurias, `rc=0`, y `version` sigue en `0`: repetir
**no** incrementa la versión.

La pasada 2 escribe de más que la 1 **a propósito** y una sola vez: es la
`PROJECT_RELATION` que antes no podía existir. La convergencia ocurre en la 3.

## 5. `state_hash` describe el estado real

`verifica_state_hash.py` lee cada nodo y **rehace el hash desde el grafo**:

```
entity:casa-ciervo      guardado=c6b022351327d113... recomputado=c6b022351327d113... COINCIDE
entity:cofradia-ambar   guardado=00933e9dbb06255e... recomputado=00933e9dbb06255e... COINCIDE
total=2 coinciden=2   (rc=0)
```

Y no es un hash constante: los dos nodos tienen hashes distintos.

## 6. Control negativo — la comprobación sigue viva

`data-engine/app/tests/test_knowledge_v3_estado_durable_neo4j_real.py` incluye
dos controles negativos: un **cambio real de estado** por debajo del plan (un
escritor concurrente honesto: cambia el estado y recalcula su hash) y un plan
que **miente** sobre el estado. Los dos deben seguir abortando con
`EXEC_HASH_MISMATCH` y sin escribir la relación.

**Calibrado**, que es lo que los convierte en evidencia: sustituyendo la
comparación de hash por `if False:` (la relajación que este encargo existe para
no cometer), la suite se pone roja **exactamente** en esos dos, y en ninguno
más:

```
FAILED ...::test_CONTROL_NEGATIVO_un_cambio_real_de_estado_sigue_tumbando_el_control
FAILED ...::test_CONTROL_NEGATIVO_un_hash_que_no_describe_el_nodo_tambien_aborta
2 failed, 3 passed
```

Restaurada la comparación: `5 passed`.

## 7. Cómo reproducirlo

```
PYTHONPATH=data-engine/app python3 artifacts/estado-durable/censo_grafo.py \
    bolt://HOST:PUERTO /ruta/privada/neo4j.pass [salida.json]

PYTHONPATH=data-engine/app python3 artifacts/estado-durable/verifica_state_hash.py \
    bolt://HOST:PUERTO /ruta/privada/neo4j.pass

S9K_WRITER_NEO4J_REAL=1 python3 -m pytest \
    data-engine/app/tests/test_knowledge_v3_estado_durable_neo4j_real.py -q
```

La contraseña viaja **en un fichero**, nunca en la línea de comandos.

> Aviso de método: en una máquina con varios Neo4j efímeros a la vez, el
> contenedor del fixture no llega a aceptar conexiones dentro de su plazo y la
> suite da un rojo que **no es del producto** (se observó: 5 errores
> `Neo4j no acepto conexiones en bolt://...`). Por eso el fichero admite
> `S9K_4A_NEO4J_URI` / `S9K_4A_NEO4J_PASSWORD_FILE` para apuntar a una base real
> ya viva — cada prueba la deja vacía antes y después. Comprueba los recursos
> antes de atribuir un rojo.

# Inventario y clasificacion: tests que exigen Neo4j real

Repo `pjclavero/S9-Knowledge` · base `integracion/tanda11` =
`3d5dadc7ed4bd1552a0726d3cb9f6d95ce6b5a9f`.

## El hallazgo, en una linea

```
tests *_neo4j_real* existen
+ pytest local los salta (sin S9K_WRITER_NEO4J_REAL salen `skipped`, rc=0)
+ CI solo forzaba DOS nombres concretos (`writer` + `e2e`)
= los otros ONCE desaparecian de la cobertura obligatoria SIN poner CI rojo
```

Medido sobre la base, sin cambios:

```
$ python3 -m pytest data-engine/app/tests/test_knowledge_v3_tanda4_integracion_neo4j_real.py -q
11 skipped in 0.64s      PYTEST_RC=0        <-- el falso verde
```

El paso 1 de `test-data-engine` tiene guardia anti-cero (`N passed`) pero **no**
anti-salto; el paso 2 si la tiene, pero solo nombraba dos ficheros.

## Que propiedad estructural se elige, y por que

Se descartan las dos candidatas obvias **por medicion, no por preferencia**:

### 1. Un marker (`@pytest.mark.neo4j_real`) — NO EXISTE

`pytest.ini` registra **un unico marker**: `critico`. `tests/conftest.py:31-39`
registra otros cuatro (`e2e`, `integration`, `contract`, `prod_block`). Ninguno
significa «necesita Neo4j». Ademas `pytest.ini` **no lleva `--strict-markers`**,
asi que un marker mal escrito no daria error: seria un discriminador capaz de
fallar en silencio. No es que se prefiera otra cosa: es que no hay marker.

### 2. La convencion de nombres `*_neo4j_real*.py` — TIENE EXCEPCIONES EN LAS DOS DIRECCIONES

| direccion | fichero | por que rompe la convencion |
|---|---|---|
| falso **negativo** | `test_knowledge_v3_equipo11a_apply_completo.py` | lleva el mismo gate (`skipif` sobre `S9K_WRITER_NEO4J_REAL`, L126/L171) y **no** casa con el patron: una lista por nombre lo pierde |
| falso **positivo** | `test_knowledge_v3_equipo5b_propiedad_rollback_neo4j_real.py` | **si** casa con el nombre pero se gatea con OTRA familia de variables (`S9K_5B_NEO4J_URI` + `S9K_5B_NEO4J_PASSWORD_FILE`, L70-74): activar `S9K_WRITER_NEO4J_REAL` **no lo despierta** |

### 3. La elegida: el modulo LEE la variable de entorno que decide la omision

Es lo que pytest obedece de verdad, y coincide exactamente con lo que el paso de
CI exporta — asi «pertenece a la clase» y «CI lo ejecuta» son la MISMA condicion
y no pueden divergir con el tiempo.

Se lee **por AST** (`.github/scripts/descubre_neo4j_real.py`), no con `grep`.
La diferencia esta medida: `test_knowledge_v3_e2e_global.py:919` contiene
`assert "S9K_WRITER_NEO4J_REAL" in fuente` —comprueba que OTRO modulo conserve
su guardia— y **no se omite jamas**. Un detector que contara apariciones de
texto lo habria metido en la clase obligatoria. El primer detector que escribi
lo hizo: buscaba constantes de texto y devolvio 14 ficheros. Al exigir una
**lectura de entorno** (`os.environ.get` / `os.getenv` / `os.environ[...]`)
devuelve 13, los correctos.

## Tabla de clasificacion

| # | Fichero (`data-engine/app/tests/`) | Gate (linea) | Variable | Clase | Criterio |
|---|---|---|---|---|---|
| 1 | `test_equipo5a_partida_y_esquema_neo4j_real.py` | `pytestmark` L35-37 | `S9K_WRITER_NEO4J_REAL` | **REQUIRED_REAL_NEO4J** | esquema/constraints reales de partida; no hay doble offline |
| 2 | `test_equipo6c_sesion_de_partida_neo4j_real.py` | `pytestmark` L65-67 | idem | **REQUIRED_REAL_NEO4J** | sesion de partida contra la base |
| 3 | `test_equipo8a_reutilizacion_entidad_neo4j_real.py` | `pytestmark` L76-78 | idem | **REQUIRED_REAL_NEO4J** | reutilizacion de entidad, recorrido propio |
| 4 | `test_integracion5_dos_partidas_neo4j_real.py` | `pytestmark` L56-58 | idem | **REQUIRED_REAL_NEO4J** | aislamiento entre dos partidas |
| 5 | `test_knowledge_v3_carril_b_neo4j_real.py` | `pytestmark` L36-38 + `importorskip` L23-24 | idem | **REQUIRED_REAL_NEO4J** | reconciliacion de identidad/procedencia |
| 6 | `test_knowledge_v3_e2e_neo4j_real.py` | `pytestmark` L37-40 | idem | **REQUIRED_REAL_NEO4J** | ya obligatorio en CI antes de este PR |
| 7 | `test_knowledge_v3_equipo4b_mando_rollback_neo4j_real.py` | `pytestmark` L60-62 | idem (+ `S9K_4B_*` opcionales) | **REQUIRED_REAL_NEO4J** | mando de rollback por CLI |
| 8 | `test_knowledge_v3_equipo6b_clasificacion_rollback_neo4j_real.py` | `pytestmark` L83-85 | idem | **REQUIRED_REAL_NEO4J** | clasificacion del desenlace del rollback |
| 9 | `test_knowledge_v3_estado_durable_neo4j_real.py` | `pytestmark` L39-42 | idem (+ `S9K_4A_*` opcionales) | **REQUIRED_REAL_NEO4J** | `state_hash` durable |
| 10 | `test_knowledge_v3_tanda3_integracion_neo4j_real.py` | `pytestmark` L86-88 | idem | **REQUIRED_REAL_NEO4J** | procedencia navegable |
| 11 | `test_knowledge_v3_tanda4_integracion_neo4j_real.py` | `pytestmark` L53-56 | idem | **REQUIRED_REAL_NEO4J** | ciclo apply->repeat->rollback->re-apply |
| 12 | `test_knowledge_v3_writer_neo4j_real.py` | `pytestmark` L54-57 | idem | **REQUIRED_REAL_NEO4J** | el motor; ademas es la FUENTE de la fixture efimera |
| 13 | `test_knowledge_v3_equipo11a_apply_completo.py` | `skipif` por test L171 | idem | **REQUIRED_REAL_NEO4J** (parcial: 1 de 4 tests) | proyeccion de altas; los otros 3 ya corren siempre |
| — | `test_knowledge_v3_equipo5b_propiedad_rollback_neo4j_real.py` | `pytestmark` L70-74 | **`S9K_5B_NEO4J_URI`** | **OPTIONAL_EXTERNAL** | exige una base ALCANZABLE POR URI + fichero de password, no la efimera. Nadie define esas variables en CI: hoy es codigo muerto. **No se mete en la clase obligatoria fingiendo que la variable del writer lo despierta, porque no lo hace.** |

**No hay LEGACY ni DUPLICATE.** Se comprobo por contenido, no por nombre: cada
uno importa modulos vivos de `knowledge_v3.*` y afirma una propiedad distinta
(esquema, sesion, reutilizacion, dos partidas, identidad, puerta 7, mando de
rollback, clasificacion, estado durable, procedencia, ciclo completo, motor,
proyeccion). Los solapamientos son de **infraestructura** —casi todos importan
las fixtures de `writer_neo4j_real`— y no de recorrido.

El unico candidato debil a DUPLICATE era el 5b (propiedad por apply, que el 6b
tambien roza), pero se clasifica como OPTIONAL_EXTERNAL por su gate, que es una
razon mas fuerte y verificable.

## Otros tests con recurso externo (NO pertenecen a este contrato)

Ya cubiertos por CI con su propia guardia anti-salto: `viewer/tests/test_neo4j_integration_authz.py`,
`test_contrato_paneles_neo4j.py`, `test_contrato_writer_a_visor_neo4j.py`,
`test_integracion_tanda11_recorrido_completo.py` (los cuatro por `NEO4J_TEST_URI`,
job `test-neo4j-authz`).

**OPTIONAL_EXTERNAL** (necesitan algo distinto de Neo4j): NVIDIA
(`test_external_nvidia_live.py`, `test_knowledge_v3_providers_nvidia.py`,
`test_agreement_shadow.py`), Ollama (`test_local_llm_ollama_live.py`), Node
(`test_graph_ux_v2.py`), Chromium (`viewer/tests/browser/`), spaCy/Stanza
(`test_relation_v2_b5_parser.py`), git y python3.13 del sistema (`deploy/tests/`).
Node y Chromium ya tienen su fila en `HERRAMIENTAS`; el resto no forma parte de
la garantia de CI.

---

# Actualizacion sobre la base nueva `46549ec9` (PRs #210, #212, #213, #214, #215)

## La clase crecio sola de 13 a 15, SIN tocar el workflow

Es la propiedad del PR demostrada por un suceso que no controle. Las dos tandas
nuevas anadieron dos ficheros con el mismo gate:

```
+ data-engine/app/tests/test_integracion_tanda11_outcome_incompleto_neo4j_real.py
+ data-engine/app/tests/test_knowledge_v3_tanda11_retained_compartido_neo4j_real.py
```

El descubridor pasa de 13 a **15 ficheros** y la coleccion de 132 a **142
tests**, sin editar `ci.yml` ni ninguna lista. Con la unidad de control
anterior —dos nombres a mano— estos dos ficheros habrian nacido fuera de la
cobertura obligatoria, que es exactamente como nacieron los doce anteriores.

## `equipo5b`: OPTIONAL_EXTERNAL por una razon MAS FUERTE

La razon que tenia era «se gatea con otra familia de variables». La razon real
es peor y se acredita parseando: **`S9K_5B_NEO4J_URI` y
`S9K_5B_NEO4J_PASSWORD_FILE` no las define NADA en el repositorio.**

Solo aparecen como LECTURA (el propio test, y mis dos scripts al citarlas). No
hay job, script, `.env`, compose ni documento de despliegue que las asigne.

No es «una puerta que abre otra llave»: es **una puerta cuya llave no existe**.
Un condicional cuya condicion nadie define nunca es un apagado permanente con
aspecto de condicional. Confirmado de forma independiente en
`docs/v3/63-linea-base-de-silenciamientos.md:120`.

Por eso NO entra en la clase obligatoria: meterlo seria fingir que
`S9K_WRITER_NEO4J_REAL` lo despierta. Medido: `6 skipped, PYTEST_RC=0` incluso
con esa variable puesta.

## Mi clase (15) y los 15 modulos condicionales de PR B NO son el mismo conjunto

Coinciden en tamano por casualidad y **difieren en las dos direcciones**.
Comparado contra `.github/suite-inventario.json` (22 silenciados):

### En la linea base silenciada pero NO en mi clase (8)

| modulo | por que no es de la clase |
|---|---|
| `..._equipo5b_propiedad_rollback_neo4j_real.py` | `S9K_5B_*`, que nadie define (arriba) |
| `viewer/tests/test_neo4j_integration_authz.py` | `NEO4J_TEST_URI`; **ya cubierto** por `test-neo4j-authz` con su guardia anti-salto |
| `viewer/tests/test_contrato_paneles_neo4j.py` | idem |
| `viewer/tests/test_contrato_writer_a_visor_neo4j.py` | idem |
| `viewer/tests/test_integracion_tanda11_recorrido_completo.py` | idem |
| `tests/wave2b/test_external_nvidia_live.py` | NVIDIA, no Neo4j -> OPTIONAL_EXTERNAL; **ningun job lo invoca** |
| `tests/wave2b/test_local_llm_ollama_live.py` | Ollama -> OPTIONAL_EXTERNAL; **ningun job lo invoca** |
| `deploy/tests/test_resolve_release_commit.py` | `git` -> OPTIONAL_EXTERNAL; lo invoca `deployment-validation` |

### En mi clase pero NO silenciado a nivel de modulo (1)

`test_knowledge_v3_equipo11a_apply_completo.py`. Su gate es **por test**
(`@pytest.mark.skipif` en un solo test, L171), no un `pytestmark` de modulo: 3
de sus 4 pruebas corren siempre. Un inventario de **modulos silenciados** no
puede verlo, porque el modulo no esta silenciado. Mi detector si, porque mira
la **lectura de entorno** con independencia del alcance.

**Conclusion:** un inventario por modulo apagado y un inventario por recurso
exigido miden poblaciones distintas. El primero pierde los gates por test; el
segundo no opina sobre lo que se apaga por razones ajenas a Neo4j. **Hacen
falta los dos**, y ninguno sustituye al otro.

## Que cierra este PR del punto 1 de PR B

De los 15 condicionales de Neo4j real, **este PR abre la condicion de los 15**
(los 13 que PR B daba por no invocados, mas los 2 que ya estaban). Quedan fuera
a proposito:

- **`equipo5b`**: sigue a oscuras, y no por descuido de este PR sino porque su
  llave no existe. Declarado, no maquillado.
- **NVIDIA y Ollama**: `OPTIONAL_EXTERNAL`, no pertenecen al contrato de CI.
  Ningun job los invoca, y este PR no cambia eso.

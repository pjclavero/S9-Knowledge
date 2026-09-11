# Rojos destapados al conectar la cobertura, con su causa atribuida

Repo `pjclavero/S9-Knowledge` · rama `feat/o1-cobertura-neo4j-real-ci` ·
base `3d5dadc7ed4bd1552a0726d3cb9f6d95ce6b5a9f`.

Todas las cifras llevan el `PYTEST_RC` del pytest real. Medido con
`S9K_WRITER_NEO4J_REAL=1`, un fichero por invocacion, `TMPDIR` propio.

## Resultado del conjunto obligatorio (13 ficheros, 132 tests coleccionados)

| # | Fichero | PYTEST_RC | Resultado |
|---|---|---|---|
| 1 | `test_equipo5a_partida_y_esquema_neo4j_real.py` | 0 | 10 passed (91.26s) |
| 2 | `test_equipo6c_sesion_de_partida_neo4j_real.py` | 0 | 12 passed (128.14s) |
| 3 | `test_equipo8a_reutilizacion_entidad_neo4j_real.py` | 0 | 5 passed (231.22s) |
| 4 | `test_integracion5_dos_partidas_neo4j_real.py` | 0 | 3 passed (81.30s) |
| 5 | `test_knowledge_v3_carril_b_neo4j_real.py` | 0 | 12 passed (88.57s) |
| 6 | `test_knowledge_v3_e2e_neo4j_real.py` | 0 | 11 passed (95.46s) |
| 7 | `test_knowledge_v3_equipo4b_mando_rollback_neo4j_real.py` | **1** | **2 failed**, 8 passed (213.48s) |
| 8 | `test_knowledge_v3_equipo6b_clasificacion_rollback_neo4j_real.py` | 0 | 8 passed (101.67s) |
| 9 | `test_knowledge_v3_estado_durable_neo4j_real.py` | 0 | 5 passed (75.53s) |
| 10 | `test_knowledge_v3_tanda3_integracion_neo4j_real.py` | 0 | 10 passed (72.55s) |
| 11 | `test_knowledge_v3_tanda4_integracion_neo4j_real.py` | **1** | **2 failed**, 8 passed, **1 skipped** (57.79s) |
| 12 | `test_knowledge_v3_writer_neo4j_real.py` | 0 | 31 passed (170.88s) |
| 13 | `test_knowledge_v3_equipo11a_apply_completo.py` | 0 | 4 passed (54.83s) |

**11 de 13 en verde.** Los dos rojos caen ENTEROS en los ficheros del micro-PR
ajeno (`tanda4` y `equipo4b`), asi que se DECLARAN y no se tocan.

Fuera de la clase, por contraste: `..._equipo5b_propiedad_rollback_neo4j_real.py`
da `6 skipped`, `PYTEST_RC=0` **incluso con `S9K_WRITER_NEO4J_REAL=1`**. Es la
confirmacion ejecutada de que su gate es otro (`S9K_5B_NEO4J_URI`) y de que
meterlo en esta clase habria sido meter un fichero que no despierta.

## Control de atribucion: los rojos NO son mios ni son contencion

Los cuatro fallos se reprodujeron **sobre el sujeto sin mis cambios** (este PR
no toca ningun fichero de test ni de producto: solo `.github/` y `artifacts/`)
y **con la maquina en reposo**, en `TMPDIR` separado, despues de comprobar que
no quedaba ningun `pytest` ajeno ni mas contenedores que el mio:

```
equipo4b  2 failed, 8 passed              PYTEST_RC=1   (129.09s, en reposo)
tanda4    2 failed, 8 passed, 1 skipped   PYTEST_RC=1   ( 54.36s, en reposo)
```

Importa porque la primera pasada corrio mientras OTRO agente ejecutaba esos dos
mismos ficheros: sin repetir en reposo, estos rojos no serian atribuibles.

## Causa de cada rojo

### R1 y R2 — `tanda4`: el producto no puede emitir `INCOMPLETE`. Causa: **PRODUCTO**

```
tanda4:267  test_ciclo_apply_repeat_rollback_apply_vuelve_a_S1      assert False
tanda4:436  test_un_rollback_con_residuos_no_puede_salir_con_cero
            AssertionError: assert 'UNEXPECTED_RESIDUE' == 'INCOMPLETE'
```

`cli_rollback.py:131` define `OUTCOME_INCOMPLETE = "INCOMPLETE"` y **ninguna
linea del producto se lo asigna nunca a un desenlace**. El unico punto donde se
decide es `cli_rollback.py:724`:

```python
limpio = report.clean
outcome = OUTCOME_ROLLED_BACK if limpio else OUTCOME_UNEXPECTED_RESIDUE
```

Dos valores posibles; `INCOMPLETE` es vocabulario muerto. Tres ficheros de test
lo esperan (`tanda4`, `equipo5b`, `equipo4b_mando_rollback_seguridad`).

### R3 y R4 — `equipo4b`: la clasificacion del desenlace se estrecho. Causa: **PRODUCTO (o contrato)**

```
equipo4b:395  test_sin_el_barrido_el_rollback_deja_procedencia_huerfana
equipo4b:456  test_casos_A_B_C_D_conservacion_y_limpieza     assert False
```

El acta que devuelve el mando dice literalmente *«6 observaciones sobre
elementos que esta operacion NO creo: no afectan a este desenlace»*, mientras el
test exige `outcome == UNEXPECTED_RESIDUE` con procedencia huerfana delante.

Misma familia que R1/R2: el desenlace del rollback paso a derivarse de **una
sola propiedad** (`report.clean`, y el comentario de `cli_rollback.py:719-723`
lo declara como decision deliberada), y con ese estrechamiento dejaron de ser
ciertas tres afirmaciones que solo estos tests —contra Neo4j de verdad— podian
comprobar.

**Por que estaba escondido:** es exactamente el modo de fallo que el PR ataca.
Estos ficheros salian `skipped` en CI, asi que el estrechamiento del vocabulario
de desenlaces no enrojecio nada cuando se hizo.

**NO SE ARREGLA AQUI**, por dos razones independientes: (a) `tanda4` y
`equipo4b` pertenecen al micro-PR de otro agente —propiedad disjunta—; (b) si el
rojo revela un defecto real del producto, se declara y no se arregla: decidir si
lo correcto es devolver `INCOMPLETE` al producto o retirar la expectativa de los
tests es un encargo de contrato, no de cobertura.

### R5 — `tanda4:353`, 1 omitido. Causa: **ENTORNO**

```
SKIPPED tanda4:353 el proceso nuevo necesita una base alcanzable por URI:
        declara S9K_4A_NEO4J_URI y S9K_4A_NEO4J_PASSWORD_FILE
```

No es un defecto: es un recurso que CI no ofrece. La base efimera del writer se
levanta con `docker run --rm` y **no** se publica por URI, y este caso arranca
un proceso APARTE que necesita conectarse a la misma base.

Remedio concreto, **deliberadamente NO aplicado en este PR**: anadir un
`services: neo4j` al job `test-data-engine` y exportar `S9K_4A_NEO4J_URI` +
`S9K_4A_NEO4J_PASSWORD_FILE`. Se deja fuera porque esas variables tambien
redirigen a `estado_durable` y `equipo4b` a la base COMPARTIDA en vez de a la
suya efimera: cambiaria el sujeto de dos ficheros —uno hoy verde— y uno de ellos
es del micro-PR ajeno. Eso es un cambio de comportamiento disfrazado de
configuracion, y no cabe en un PR cuyo objeto es no relajar nada.

**Consecuencia honesta: mientras este skip siga ahi, el paso queda ROJO aunque
se arreglen R1-R4.** El PR es PARCIAL y se declara como tal.

## Coste de ejecucion en CI

Suma de las 13 invocaciones: **1462.68 s ≈ 24,4 min** (parte de ellas bajo
contencion con otro agente). En CI el coste real es MENOR que esa suma: el paso
hace **una sola** invocacion de pytest, asi que las fixtures `scope="session"`
comparten un unico contenedor en vez de rearrancarlo por fichero.

Contenedores Neo4j efimeros: **1 de sesion** (compartido por 5a, int5, e2e,
estado_durable, tanda4, writer) + **6-7 de modulo** (6c, 8a, carril_b, 4b —que
puede levantar 2—, tanda3, 6b, 11a). Secuenciales, nunca simultaneos.

**Viabilidad: SI.** Anade ~25 min a `test-data-engine`. No se parece a las ~24 h
de la suite completa contra Neo4j real: esto es el SUBCONJUNTO que exige base
real, no la suite entera. El paso anterior ya pagaba ~4,5 min por los dos
ficheros que nombraba, asi que el incremento neto es de ~20 min.

Aviso de saturacion, escrito en el propio arbol
(`test_knowledge_v3_estado_durable_neo4j_real.py:64-69`): con varios Neo4j
efimeros a la vez, un contenedor puede no aceptar conexiones dentro del plazo y
dar un rojo que NO es del producto. Los runners de `ubuntu-latest` ejecutan un
job por maquina, asi que no concurren con otros jobs; el riesgo real es la
maquina de desarrollo, donde hay que medir en reposo (como aqui).

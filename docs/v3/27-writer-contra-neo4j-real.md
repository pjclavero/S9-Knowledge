# Writer V3 contra Neo4j real

Fecha: 2026-07-29  
Rama: `test/v3-writer-neo4j-real`  
Base: `feat/knowledge-v3-redesign` en `76238a3`

## Qué se construyó

Se añadió una batería opt-in en
`data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py`.

La prueba no usa mocks ni acepta una URI externa. Cuando se activa con
`S9K_WRITER_NEO4J_REAL=1`, el fixture:

1. busca Docker CLI;
2. levanta un contenedor `neo4j:5.26-community` con nombre aleatorio
   `s9k-writer-real-<uuid>`;
3. publica Bolt en `127.0.0.1:<puerto libre>`;
4. conecta con el driver oficial `neo4j` ya presente en `data-engine/requirements.lock`;
5. limpia solo esa base efímera antes y después de cada test;
6. destruye el contenedor al terminar.

Por defecto las pruebas se saltan, igual que los humos reales de proveedores:

```bash
python -m pytest data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py -q
```

Para ejecutarlas contra base real:

```bash
S9K_WRITER_NEO4J_REAL=1 python -m pytest data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py -q
```

No se añadió ninguna dependencia nueva.

## Qué verifica la batería

La batería cubre los nueve puntos de la Parte C:

1. **Cypher válido:** una ejecución feliz toca `CREATE_ENTITY`,
   `CREATE_ASSERTION`, `LINK_EXISTING`, `UPDATE_ENTITY` y
   `SUPERSEDE_ASSERTION`.
2. **CREATE-only:** se siembra un nodo existente, se intenta crearlo otra vez y se
   comprueba por consulta que el nombre original no cambia.
3. **Concurrencia optimista real:** se calcula un plan sobre versión/hash antiguos,
   se muta el nodo por fuera antes del apply y se comprueba que aborta el plan
   entero.
4. **Transaccionalidad:** una segunda operación falla después de una escritura
   previa dentro de la misma transacción; la base queda con 0 nodos y 0 relaciones.
5. **Idempotencia:** aplicar dos veces el mismo plan deja el snapshot de la base
   idéntico y la segunda pasada es no-op.
6. **Cierre de vigencia y supersesión:** se conserva la aserción vieja, se marca
   `SUPERSEDED`, se fija `superseded_by` y se crea la sucesora.
7. **Dry-run:** con driver real disponible, el snapshot serializado de la base no
   cambia byte a byte.
8. **Gate:** falta de `S9K_ALLOW_REAL_INGEST`, hash no confirmado y workspace mal
   declarado bloquean sin escribir.
9. **Aislamiento de workspace:** un writer de `writer-real` no toca nodos sembrados
   en `writer-real-otro`.

La evidencia de cada punto la obtiene el test consultando Neo4j (`count(n)`,
`count(r)`, propiedades de nodos y snapshot JSON de nodos/relaciones), no a partir
del informe del writer.

## Evidencia real de base

No hay evidencia de base real producida en esta máquina.

Motivo: el entorno local no tiene Docker CLI en `PATH`; por tanto no pude levantar
la instancia efímera exigida por el encargo. No se leyó ni escribió ningún Neo4j
externo o de producción.

Comprobación:

```text
Get-Command docker -ErrorAction SilentlyContinue | Select-Object Source
```

Salida real:

```text
<sin salida; exit code 1>
```

Ejecución opt-in real:

```text
$env:S9K_WRITER_NEO4J_REAL='1'; python -m pytest data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py -q
sssssssssss                                                              [100%]
11 skipped in 0.40s
```

La salida anterior significa que la batería fue recogida, pero no ejercitó Neo4j
porque el fixture no pudo crear el contenedor. Esto es una limitación de entorno,
no una verificación del writer contra base real.

## Salida real de pytest

Nuevo archivo, modo por defecto:

```text
python -m pytest data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py -q
sssssssssss                                                              [100%]
11 skipped in 3.15s
```

Writer existente + nueva batería opt-in:

```text
python -m pytest data-engine/app/tests/test_knowledge_v3_writer.py data-engine/app/tests/test_knowledge_v3_writer_mutation.py data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py -q
........................................................................ [ 51%]
.........................................................sssssssssss     [100%]
129 passed, 11 skipped in 1.08s
```

Suite data-engine exigida:

```text
python -m pytest data-engine/app/tests/ -q
...
ModuleNotFoundError: No module named 'resource'
...
ERROR data-engine/app/tests/test_knowledge_v3_e2e.py
ERROR data-engine/app/tests/test_knowledge_v3_e2e_fixtures.py
ERROR data-engine/app/tests/test_knowledge_v3_e2e_semantic_wiring.py
ERROR data-engine/app/tests/test_knowledge_v3_negation.py
!!!!!!!!!!!!!!!!!!! Interrupted: 4 errors during collection !!!!!!!!!!!!!!!!!!!
41 warnings, 4 errors in 9.19s
```

Suite viewer exigida:

```text
python -m pytest viewer/tests/ -q
...
viewer\app\auth\db.py:4: in <module>
    import fcntl
E   ModuleNotFoundError: No module named 'fcntl'
...
viewer\tests\test_health_backups.py:321: in <module>
    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignora los permisos de lectura")
E   AttributeError: module 'os' has no attribute 'geteuid'. Did you mean: 'getpid'?
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!
1 skipped, 1 warning, 2 errors in 2.74s
```

Suite completa exigida:

```text
python -m pytest -q
ImportError while loading conftest 'C:\proyectos\S9-Knowledge\deploy\tests\conftest.py'.
deploy\tests\conftest.py:25: in <module>
    import retention as _retention_module  # noqa: E402
deploy\scripts\retention.py:18: in <module>
    import fcntl
E   ModuleNotFoundError: No module named 'fcntl'
```

## Defectos encontrados en otros subsistemas

No se parchearon, por la regla del encargo.

- `data-engine/app/knowledge_v3/pipeline/bundle.py:16`: importa `resource`, módulo
  POSIX ausente en Python 3.13 sobre Windows. Bloquea la recogida de varios tests
  de `data-engine/app/tests/`.
- `viewer/app/auth/db.py:4`: importa `fcntl`, módulo POSIX ausente en Windows.
  Bloquea `viewer/tests/test_api.py`.
- `viewer/tests/test_health_backups.py:321`: usa `os.geteuid()`, ausente en
  Windows.
- `deploy/scripts/retention.py:18`: importa `fcntl`, lo que bloquea la suite
  completa desde el `conftest` de `deploy/tests`.

## Rutas protegidas

Comprobado sin diff:

```text
git diff -- contracts\knowledge-v3\v1 data-engine\app\knowledge_v3\contracts .github\workflows\ci.yml pytest.ini benchmarks\datasets data-engine\app\knowledge_v3\benchmarks\datasets
<sin salida>
```

No se tocaron contratos, `ci.yml`, `pytest.ini` ni datasets.

## Limitaciones conocidas

- En esta máquina no se pudo cumplir la verificación real contra Neo4j porque no
  hay Docker. La entrega contiene la batería opt-in preparada para que un revisor
  con Docker la ejecute contra una instancia efímera.
- No se escribieron conteos ni estados antes/después de Neo4j como si se hubieran
  ejecutado. Están codificados en los asserts, pero no medidos localmente.
- No se modificó el writer ni ningún otro subsistema.

---

## Actualización — CARRIL C (2026-09-05): dejan de ser opt-in

Base: `main` en `f725bd8` (BASE RC V3.1, congelada). Rama `carril-c-neo4j-real`.

Las limitaciones de arriba ya no se sostienen: las 33 pruebas de
`test_knowledge_v3_writer_neo4j_real.py` (22) y
`test_knowledge_v3_e2e_neo4j_real.py` (11) se han ejecutado contra un Neo4j
real y efímero, y **ahora las ejecuta CI**.

### Cómo se levanta el Neo4j efímero

No hay camino nuevo: lo levanta la fixture `neo4j_driver` de siempre
(`docker run --rm --detach`, puerto libre, contraseña aleatoria, `docker rm -f`
al terminar). Lo único que cambia es que CI pone la variable:

```bash
S9K_WRITER_NEO4J_REAL=1 python -m pytest \
  data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py \
  data-engine/app/tests/test_knowledge_v3_e2e_neo4j_real.py -q
```

### Dónde corre en CI

Como un **paso más** del job existente `Data Engine Tests`, no como job nuevo:
no se añade ningún check requerido y no hace falta un bloque `services`
paralelo, porque la fixture se trae su propio contenedor. El paso distingue
cuatro estados y ninguno queda verde por silencio:

| situación | resultado |
| --- | --- |
| Neo4j no arrancó (la fixture hace `skip`) | ROJO por `grep skipped` |
| los tests no se ejecutaron | ROJO por ausencia de `N passed` |
| el writer falló | ROJO por `rc != 0` |
| el writer funcionó | VERDE |

La guarda de `skipped` no es decorativa: con el contenedor imposible de
arrancar, pytest sale con **rc=0 y "3 passed, 30 skipped"** —tres pruebas del
E2E no necesitan base—, así que la guarda anti-cero sola habría dejado el paso
en VERDE. Comprobado con `artifacts/carril-c/calibracion_rojo.sh`.

### Defecto que el opt-in tapaba

`test_m3_create_entity_de_partida_estampa_partida_id_real` llevaba **roja**
desde T2: en ámbito de partida el writer exige `known_from_session` por
operación y aborta con `EXEC_REVELACION_NO_DECLARADA`, pero la prueba se
escribió antes de T2 y, por ser opt-in, nadie volvió a ejecutarla. Corregida la
prueba (el comportamiento del writer es el correcto y no se ha tocado).

### Evidencia de producto

`artifacts/carril-c/demostracion_fuente_a_neo4j.py` recorre la cadena V3 entera
desde bytes, aplica el plan aprobado contra el Neo4j efímero y **consulta el
grafo después**. Salida completa en `artifacts/carril-c/evidencia-ejecucion.txt`.

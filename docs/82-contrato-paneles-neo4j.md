# 82 — Contrato paneles ↔ Neo4j: los cuatro huecos contra una base efímera

**Rama**: `test/contrato-paneles-neo4j` · **Base**: `main@993db1a` · **Estado**: contrato implementado, calibrado y **cableado en CI** (§8).

> **Aviso de alcance — no leas el título como si cubriera los cuatro paneles por
> igual.** Está **medido** que **B y C no consultan el grafo**: cero consultas
> Cypher durante sus peticiones. La superficie real del contrato con Neo4j es
> **F y G**. Los cuatro se *recorren* (lista y ficha, para la prueba de que
> ningún GET escribe), pero sólo dos tienen campos que contratar. Ver §2.

---

## 1. El hueco que esto cierra

Antes de esta rama había dos cuerpos de prueba, y entre ellos un hueco por el que
cabía el defecto entero:

| Qué se medía | Dónde | Qué NO cubría |
|---|---|---|
| El proveedor real contra Neo4j | `test_neo4j_integration_authz.py` (19 pruebas) | Sólo campos de **autorización**. Ni un campo de presentación. |
| Las cuatro pantallas | `test_panel_*.py` (257 pruebas) | Inyectan un `ProveedorFalso` que devuelve **diccionarios escritos a mano con las claves ya correctas**. |

Es decir: sabíamos que el proveedor funciona y sabíamos que las pantallas
funcionan **con sus fixtures**, pero **no que una consulta Neo4j real entregue
exactamente los campos que los paneles consumen**.

La hipótesis que circulaba era que esto era «plausible, porque `RETURN n` +
`_node_to_dict` devuelve todas las propiedades». **Es falsa.** `_node_to_dict`
(`viewer/app/providers/neo4j_provider.py`) no es `dict(n)`: es una **lista blanca
explícita de 25 propiedades**. Lo que no está en esa lista no llega al panel,
aunque esté en la base. El riesgo no era teórico.

---

## 2. Qué se ha construido

`viewer/tests/test_contrato_paneles_neo4j.py` — **43 pruebas** de integración que:

- escriben en un **Neo4j efímero real** (nunca producción: ver §7);
- leen con el **`Neo4jGraphProvider` real**, instalado como proveedor **BASE**
  (`app.deps.get_provider`), no como proveedor filtrado — así la cadena entera
  `get_filtered_provider → get_visibility_context → build_viewer_context →
  PolicyFilteredProvider → VisibilityPolicy` se atraviesa en **cada** petición;
- piden las pantallas **por HTTP sobre `app.main.app`**, con usuarios reales,
  cookie de sesión real y el rol que declara el contrato del chasis;
- afirman sobre el **HTML renderizado**, porque un campo que llega al contexto de
  plantilla y no se pinta no está entregado.

### Superficie real del contrato: F y G, no los cuatro

Medido, no supuesto (`test_los_paneles_B_y_C_no_consultan_neo4j_en_absoluto`):

| Panel | Ruta | Rol | Fuente de datos | ¿Contrato con Neo4j? |
|---|---|---|---|---|
| **C** Review | `/panel/review` | `reviewer` | paquete de propuestas V3 (ficheros) | **ninguno** — 0 consultas Cypher |
| **B** Operations | `/panel/operations` | `admin` | base de jobs + informe de salud | **ninguno** — 0 consultas Cypher |
| **F** Sources | `/panel/sources` | `reviewer` | `GraphProvider` | **sí** |
| **G** Entities | `/panel/entities` | `viewer` | `GraphProvider` | **sí** |

Los cuatro se ejercen igualmente (recorrido completo, lista y ficha), pero el
contrato campo a campo sólo puede existir donde hay campos. Que B y C no toquen
el grafo es ahora un **hecho con prueba**: si alguien los conectara, el test se
pone rojo y habría que ampliar el contrato.

---

## 3. El contrato, campo a campo, y su calibración

**Criterio de éxito del encargo**: *por cada campo que un panel consume, quítalo
en Neo4j y comprueba que algo se pone ROJO. Si no enrojece, el contrato es
decorativo.*

Se implementa como `test_quitar_un_campo_que_el_panel_consume_pone_algo_ROJO`,
parametrizado: se observa la pantalla **con** el campo, se **borra la propiedad
en Neo4j**, se vuelve a observar, y se exige (a) que la observación **cambie** y
(b) que el degradado sea el **declarado** — nunca un cero ni un valor plausible
inventado. Después se restaura y se comprueba que la pantalla vuelve a ser
idéntica, y que el **testigo** (un nodo que ninguna ablación toca) no se movió.

| Campo en Neo4j | Panel | Lo consume | Degradado exigido |
|---|---|---|---|
| `canonical_name` | G | enlace y título de la fila | etiqueta vacía |
| `entity_type` | G | columna Tipo | `data-entity-type=""` |
| `confidence` | G | columna Confianza | **«no disponible»**, nunca `0.00` |
| `review_status` | G | columna Estado | «no disponible» |
| `source_document` | G | columna Fuente | «no disponible» |
| `visibility` | G | política | **fila ausente** (fallo cerrado) |
| `workspace` | G | política | **fila ausente** |
| `description` | G (ficha) | cuerpo de la ficha | «no disponible» |
| `source_kind` | F | reparto de procedencia | «no disponible» |
| `source_document` | F | **clave de agrupación** | la fuente desaparece y la entidad se cuenta en el cubo «sin fuente declarada» |
| `review_status` | F | reparto de estados | «no declarado», `data-status-known="false"` |

---

## 4. La evidencia: ablación de la proyección Cypher

La calibración de arriba prueba que el contrato reacciona al **dato**. Falta
probar que reacciona al **defecto que se teme**: que la proyección Cypher pierda
un campo. Para eso se borró, una por una, cada línea de `_node_to_dict` y se
corrieron las tres suites.

> **Cifras medidas sobre ejecución completa de cada suite** (contrato = 43
> pruebas, paneles = 257, authz = 19). Ver tabla en §9.

El resultado es el argumento central de esta rama:

- **12 de 12 campos**: el contrato se pone **ROJO**.
- **12 de 12 campos**: las cuatro suites de panel siguen **VERDES**. Nunca ven
  nada, porque su `ProveedorFalso` fabrica las claves correctas.
- **6 de 12 campos** (`type`, `description`, `review_status`, `source_document`,
  `source_kind`, `confidence`): la suite de integración existente también sigue
  **VERDE**. Son exactamente los campos de presentación que nadie medía.

Para esos seis campos, **este fichero es hoy el único instrumento del repo capaz
de ver el defecto**.

---

## 5. Ningún GET escribe — dos controles independientes, ambos calibrados

1. **Foto del estado** (`test_recorrer_los_cuatro_paneles_no_cambia_el_estado_de_la_base`):
   nodos y aristas **con todas sus propiedades** antes y después de recorrer los
   cuatro paneles. No es un conteo: un conteo no ve un `SET` que cambie un valor
   sin crear nada.
2. **Espía de Cypher** (`test_ningun_get_emite_una_sola_clausula_de_escritura`):
   envuelve el driver real y registra **cada consulta emitida**; se rechaza
   cualquiera con `CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD CSV`. Ve una
   escritura idempotente que la foto no vería.

Cada uno lleva **su control negativo dentro de la propia suite**:
`test_el_detector_de_escritura_MUERDE` (emite un `CREATE` a propósito y exige que
lo cace) y `test_la_foto_de_la_base_MUERDE` (cambia una propiedad y exige que la
foto lo note). Y con un `SET` inyectado en el GET de la ficha del panel G, **los
dos controles se ponen rojos**.

---

## 6. El arnés no puede pasar en vacío

Tres suelos independientes, porque «el contenedor no levantó» y «todo correcto»
no pueden parecerse:

1. `test_la_base_efimera_tiene_el_material_contado_en_neo4j` — cuenta **en la
   base** (`MATCH … RETURN count(n)`), no la longitud de la constante de Python.
   Contar la lista sería un suelo que se autocumple: pasaría aunque el `CREATE`
   no hubiera escrito nada.
2. `test_los_paneles_pintan_filas_de_verdad` — el panel G debe pintar ≥5 filas y
   su conjunto visible debe ser **exactamente** el declarado a mano; el panel F
   debe agrupar ≥2 fuentes.
3. `test_el_control_de_autorizacion_COLAPSA` — cambiar el principal debe cambiar
   lo entregado. Si no colapsara, toda comprobación negativa pasaría sin
   demostrar nada.

**Calibrado**: sembrando el grafo **vacío**, la suite no pasa en verde — se
derrumba ruidosamente (ver §9).

Este suelo ya se ganó el sueldo: `main@993db1a` introdujo
`LORE_ANÓNIMO = DENEGADO` con una llave nueva (`can_view_lore`, defecto `False`)
que dejó a cuatro bancos de medida del repo midiendo cero en silencio. Al rebasar,
el suelo 2 habría gritado antes que ninguna otra cosa. (No hizo falta: los
lectores de esta suite son **autenticados con rol legítimo**, y reciben la llave
por `build_viewer_context`. Las 43 pruebas siguen verdes sobre `993db1a`.)

---

## 7. Nunca producción

`_exigir_efimera()` valida la URI contra una **lista blanca** de anfitriones
(`localhost`, `127.0.0.1`, `::1`, `neo4j`) y **aborta** con cualquier otro,
incluida una IP de la LAN escrita por error. Esta suite hace `DETACH DELETE`:
un fallo abierto aquí no sería un test rojo, sería el grafo de VM105.

La comprobación se repite en el fixture del driver, en el de la semilla y en el
del proveedor — no en un único punto que alguien pueda esquivar.

---

## 8. Cableado en CI, y por qué sin él esto no valía nada

### 8.1 El estado del que se parte, medido

Sobre la ejecución `31916319923` (**CI verde**, 15 identidades únicas de check):

```
viewer/tests/test_contrato_paneles_neo4j.py::test_la_base_efimera... SKIPPED
… (las 43, SKIPPED)
```

Las 43 pruebas **se saltaban en silencio** y CI salía **verde**. El job
`Integridad de gates (… skips críticos)` **no lo detecta**. Un fichero de
integración que se salta sin decirlo es el peor instrumento posible: ocupa el
sitio de una barrera y no es ninguna.

### 8.2 El cambio: una línea, en el job que ya existía

Autorizado expresamente por el operador y **limitado a eso**. No se ha tocado
nada más de `ci.yml`, ni se ha añadido ningún job. El job `test-neo4j-authz` ya
tenía el contenedor `neo4j:5.26.0`, las variables y los tres guardas
(`rc != 0`, `grep skipped`, `grep 'N passed'`):

```yaml
out="$(python -m pytest viewer/tests/test_neo4j_integration_authz.py \
                        viewer/tests/test_contrato_paneles_neo4j.py \
                        -v --no-header 2>&1)"
```

Los dos ficheros van en **una sola invocación** a propósito: los guardas miran la
salida **combinada**, así que cubren el fichero nuevo sin duplicar lógica.

### 8.3 Las cinco comprobaciones, medidas — no supuestas

| # | Qué se exigía | Cómo se midió | Resultado |
|---|---|---|---|
| 1 | Sólo esa línea, nada más en `ci.yml` | `git diff` | **1 invocación modificada**, 0 jobs añadidos |
| 2 | Los guardas anti-skip cubren **también** el fichero nuevo | se replicó el bloque `run:` del job **sin** `NEO4J_TEST_*` | **ROJO** — «la suite se ha OMITIDO». Con las variables: **62 passed** (19 + 43) |
| 3 | No se rompe el carril L | `check_ci_config.py` y `calibra_gate_integrity.py`, **antes y después** | antes: OK + **30/30**; después: OK + **30/30** |
| 4 | No se pierde ningún job | `yaml.safe_load` de los dos workflows | **antes 14 + 1 = 15; después 14 + 1 = 15**. `ci_jobs_running: 15` sigue siendo correcto: **no procede refrescarlo** |
| 5 | Con el grafo roto el job se pone **ROJO**, no verde-por-salto | semilla vaciada + bloque `run:` real | **ROJO** — «la suite ha FALLADO» |

La fila 5 es la que importa: distingue *«el contrato pasó»* de *«el contrato no
llegó a correr»*, que es la confusión que hace inútil a un test de integración.

---

## 9. Tabla de calibración — cifras medidas

Medido sobre `test/contrato-paneles-neo4j@68733dc` (rebasada en `main@993db1a`),
contra Neo4j community **5.26.0** efímero en `bolt://localhost:7699`, con purga de
`__pycache__` antes de **cada** ejecución (§10).

**Línea base, árbol limpio — ejecución completa de cada suite:**

| suite | resultado |
|---|---|
| contrato (este fichero) | **43 passed** |
| paneles (`test_panel_*.py`, los cuatro) | **257 passed** |
| authz (`test_neo4j_integration_authz.py`) | **19 passed** |

### 9.1 Ablación de la proyección Cypher — **totales, suites completas**

Se borra una línea de `_node_to_dict` y se ejecutan **las tres suites enteras**.

| campo borrado | contrato | paneles | authz | fallos en contrato |
|---|---|---|---|---|
| `label` | **ROJO** | verde | ROJO | 8 |
| `type` | **ROJO** | verde | verde | 3 |
| `description` | **ROJO** | verde | verde | 2 |
| `workspace` | **ROJO** | verde | ROJO | 22 |
| `visibility` | **ROJO** | verde | ROJO | 23 |
| `scope` | **ROJO** | verde | ROJO | 22 |
| `partida_id` | **ROJO** | verde | ROJO | 1 |
| `review_status` | **ROJO** | verde | verde | 5 |
| `source_document` | **ROJO** | verde | verde | 8 |
| `source_kind` | **ROJO** | verde | verde | 3 |
| `confidence` | **ROJO** | verde | verde | 3 |
| `known_from_session` | **ROJO** | verde | ROJO | 1 |

**12/12 ROJO en el contrato. 12/12 VERDE en los cuatro paneles. 6/12 VERDE
también en authz** — esos seis (`type`, `description`, `review_status`,
`source_document`, `source_kind`, `confidence`) sólo los ve este fichero.

### 9.2 Autorización, escritura y suelo — **muestras acotadas con `-k`**

> Estas filas **no son totales**: se ejecutó el subconjunto seleccionado por `-k`
> para acotar el tiempo. Se declaran como **muestra**, y lo que demuestran es la
> **existencia** del rojo, no su extensión.

| mutación inyectada | selección | resultado |
|---|---|---|
| G: no autorizado responde **403** en vez de 404 | `-k 'no_autorizado or fuente_solo_de_material'` | **ROJO** (1 de 2) |
| G: el cuerpo del 404 **nombra el objeto** | ídem | **ROJO** (1 de 2) |
| F: fuente no autorizada responde **403** | ídem | **ROJO** (1 de 2) |
| G: la ficha **esquiva la política** (fuga real) | ídem | **ROJO** (1 de 2) |
| un GET del panel G **escribe** (`SET`) en Neo4j | `-k 'escritura or estado_de_la_base or clausula'` | **ROJO** (2 de 3: foto **y** espía) |

### 9.3 El arnés no puede pasar en vacío — **total, suite completa**

| mutación | resultado |
|---|---|
| semilla **vacía** (el contenedor levanta pero el grafo queda sin datos) | **ROJO — 10 failed, 14 passed, 19 errors** |

Es la comprobación que más importa de toda la tabla: con el grafo vacío la suite
**no puede** salir verde.

---

## 10. El hallazgo del bytecode obsoleto

**Familia**: *un instrumento que mide otra cosa distinta de la que anuncia*.
Es el hallazgo más transferible de este carril y no lo habíamos visto en esta
forma.

### Cómo se detectó

Tras terminar una batería de mutaciones, una prueba de autorización empezó a
fallar con `assert 403 == 404`. El árbol estaba **limpio**
(`git status --porcelain` vacío, `git diff` vacío) y el fuente decía, sin lugar a
dudas:

```python
raise HTTPException(status_code=404, detail="Fuente no encontrada")
```

pero un espía sobre `HTTPException.__init__` mostró que en **tiempo de ejecución**
se levantaba `HTTPException(403, 'Fuente no encontrada')`. Fuente y runtime
discrepaban.

La discrepancia era el `.pyc`. El arnés de mutación restauraba con
`shutil.move(backup, ruta)`, que **preserva la mtime del backup**. CPython valida
el `.pyc` comparando mtime y tamaño del fuente: si la mtime restaurada casa con la
que quedó grabada en el `.pyc` compilado a partir del fichero **mutado**, el
bytecode mutado se considera válido y se sigue ejecutando, con el fuente limpio en
disco y `git` sin nada que decir.

### Por qué importa

Todas las mediciones tomadas después de esa restauración eran sospechosas: no
medían el árbol que decían medir. **Se descartó la batería entera y se repitió
desde cero con purga**, que es lo que sostiene las cifras de §4 y §9.

### La purga que hace falta

Antes de **cada** ejecución que sigue a una restauración de ficheros:

```bash
find <repo> -name __pycache__ -type d -exec rm -rf {} +
```

y, en el entorno del arnés, `PYTHONDONTWRITEBYTECODE=1`. Restaurar con
`shutil.copy` (que **no** preserva mtime) en vez de `shutil.move` reduce el riesgo
pero no lo elimina: dentro del mismo segundo, mtime y tamaño pueden coincidir.

### La regla que se deriva

`git status` limpio **no** es prueba de que el proceso medido ejecute el árbol
limpio. Cuando fuente y comportamiento discrepan, la primera hipótesis es el
**bytecode**, no el código. Y, ligado a la norma de la casa: si una cifra se
presenta como **total**, debe venir de la **ejecución completa**; si se mide un
subconjunto (`-k`, `-x`), se declara como **muestra o cota**, nunca como total.

> Ese error también se cometió aquí y se corrigió: una calibración de
> autorización se dio por «no muerde» usando un `-k` que seleccionaba **otras**
> pruebas. Con el filtro correcto, muerde. Un `-k` mal puesto es un bucle vacío
> con buena presentación.

---

## 11. Supervivientes, límites y deuda

### Supervivientes (mutaciones que el contrato NO detecta)

- **`entity_id` no viaja desde Neo4j.** La proyección no lo incluye, así que
  `serialize_node` publica `entity_id = ""` para todo nodo que venga del grafo.
  Ningún panel lo pinta hoy, así que **ninguna pantalla se rompe** y ninguna
  ablación puede enrojecer. Se congela como límite medido
  (`test_la_proyeccion_cypher_NO_entrega_entity_id_y_eso_esta_medido`).
- **`short_summary` tampoco viaja**, con el mismo patrón. Congelado igual.
- **⚠️ La identidad que viaja en las URLs de los paneles es el `elementId`**, que
  el propio comentario de `app/serializers.py` declara **NO DURABLE**: se regenera
  al restaurar un dump. El contrato comprueba que es **estable entre peticiones**
  y que lista y ficha resuelven el mismo objeto, pero **no puede comprobar
  durabilidad entre restauraciones**: haría falta volcar y restaurar la base
  dentro de la prueba.
  **Impacto real**: tras cualquier `restore`, **todo enlace guardado a una ficha
  deja de resolver**, y el panel responde 404 — indistinguible de «no existe»,
  porque esa indistinguibilidad es precisamente lo que exige la política. Es
  decir: el modo de fallo es **silencioso**. **Deuda declarada; va a decisión del
  operador**, no la cierra este carril.

### Límites

- **`null` no es un estado distinguible en esta frontera.** Neo4j **no puede
  almacenar una propiedad `null`**: `SET n.x = null` la borra. Medido, no supuesto
  (`test_null_en_neo4j_es_indistinguible_de_ausente_y_asi_se_declara`). Lo que sí
  se distingue de ambos es el **vacío** (`""`), que es una propiedad presente, y
  el panel lo degrada a «no disponible» en vez de pintar una fuente llamada `""`.
- **Panel B y C**: se ejercen y se afirma que no consultan el grafo, pero su
  contrato de datos (jobs, salud, paquete V3) **queda fuera** de este carril.
- **Una sola versión de Neo4j** (5.26.0, la del job de CI).
- **`partida_id`/`known_from_session`** se cubren por el camino HTTP con concesión
  real de partida, pero la matriz exhaustiva de la política sigue viviendo en
  `test_neo4j_integration_authz.py`: aquí no se duplica.

### Deuda de utillaje

El anfitrión de desarrollo no tiene acceso al socket de Docker, así que el Neo4j
efímero local se levantó desde el **tarball** de `neo4j-community-5.26.0` con un
JDK 21 propio, en `bolt://localhost:7699`. Funciona y es reproducible, pero no es
el mismo camino que CI; la equivalencia se apoya en que la imagen y el tarball son
la misma versión.

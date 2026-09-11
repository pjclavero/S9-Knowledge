# La línea base de silenciamientos: por qué se movió, y qué NO justifica moverla

`.github/suite-inventario.json` es el **testigo** del trinquete A2 de
`check_suite_inventory.py`: el conjunto de módulos apagados **sólo puede
encoger**. Cuando HEAD contradice la línea base, la regla es que **la línea base
gana** hasta que se demuestre, módulo por módulo, que el estado nuevo es
legítimo. Adaptar la base porque HEAD la contradice destruye el instrumento.

Este documento registra esa demostración para la actualización hecha en la
tanda 11.

## El síntoma

La fila **«restaurado (control positivo final)»** de
`calibra_suite_inventory.py` —que ejecuta el gate sobre el árbol **sin ninguna
mutación** y exige VERDE— salía **ROJA**. Con ella salían rojas todas las filas
de ABLACIÓN, que también esperan VERDE: la calibración entera estaba rota,
porque el gate no podía dar verde ni en reposo.

Medido sobre `integracion/tanda11` = `b13de59e`, gate en proceso propio con
`--base-fichero`:

```
FALLO: 15 problema(s) de inventario de suites   (RC=1)
```

Los 15 son el **mismo** error: `SILENCIADO NUEVO ... (CONDICIONAL)`.

## La demostración, módulo por módulo

La línea base se generó por última vez en `f725bd8` (2026-09-05), la BASE RC
V3.1 congelada. Contenía 7 silenciamientos, todos CONDICIONALES.

La pregunta decisiva no es «¿está silenciado?» sino **«¿dejó de ejecutarse algo
que antes se ejecutaba?»**. Para los 15 módulos la respuesta es **no**:

**Ninguno de los 15 existía en `f725bd8`.** Comprobado con `git ls-tree -r`
sobre el commit de la línea base, no leyendo el árbol de trabajo. Son ficheros
**nuevos**, introducidos entre el 2026-09-06 y el 2026-09-11 por commits de
funcionalidad documentados en `docs/v3/`. Ninguno fue un módulo vivo al que se
le apagara la luz.

La condición de silencio de los 15, leída por AST (`condicion_de_silencio`), es
en todos los casos una **puerta de entorno real**, del mismo tipo que las 7 ya
aceptadas en la base:

| condición | módulos | puerta |
|---|---|---|
| `not LIVE` (`S9K_WRITER_NEO4J_REAL == "1"`) | 12 | Neo4j real |
| `not (URI and PASS_FILE)` (`S9K_5B_NEO4J_*`) | 1 | Neo4j real, vars propias |
| `not URI or not PASSWORD` (`NEO4J_TEST_*`) | 2 (visor) | Neo4j efímero |

Ninguna es una constante verdadera ni una condición disfrazada: el gate las
clasifica CONDICIONAL, no INCONDICIONAL, y abrirlas colecciona pruebas de
verdad.

**Acreditado con el `PYTEST_RC` del pytest real**, no con un envoltorio:

- Con las condiciones **abiertas**: `123 tests collected`, `PYTEST_RC=0`.
- Con las condiciones **cerradas**: `123 skipped`, `PYTEST_RC=0` — el falso
  verde que el gate existe para cazar.

## Los tres módulos CRÍTICOS del visor: NO estaban silenciados

El registro del job nombraba, como `SILENCIADO NUEVO ... CRITICO ...
INCONDICIONAL`, a `test_chassis_mount_contract.py`, `test_identidad_durable.py`
y `test_parcialidad_declarada.py`. Un crítico apagado **sin condición** no se
ejecuta nunca, así que era la sospecha más grave del encargo y se comprobó
antes que nada.

**No lo estaban.** Evidencia por AST, con la propia función `silenciado()` del
gate aplicada al árbol en reposo:

```
viewer/tests/test_chassis_mount_contract.py  -> None
viewer/tests/test_identidad_durable.py       -> None
viewer/tests/test_parcialidad_declarada.py   -> None
```

Esas líneas las produce **la calibración misma**. `calibra_suite_inventory.py`
muta los tres ficheros a propósito —`m_silencia(...)` en los casos `RC-1a`,
`RC-1b` y `RC-1c`, y `m_skipif_condicional` / `m_skipif_disfrazado` sobre
`test_parcialidad_declarada.py`— y **exige ROJO**. Por eso ese módulo aparecía
con las dos clases a la vez, CONDICIONAL e INCONDICIONAL: son dos mutaciones
distintas, no dos silenciamientos. Los tres casos salieron ROJOS, que es
exactamente lo que se les pide.

Es decir: en esas líneas el instrumento estaba **funcionando**, no fallando. El
fallo real era uno solo y estaba en otra parte —los 15 condicionales de arriba—,
y arrastraba a rojo toda fila que esperase VERDE, incluido el control positivo
final.

## Qué dice el diff de la línea base

Auditado semánticamente (parseando el JSON, no contando líneas):

```
silenciados   7 -> 22   (+15, ninguno retirado, NINGUNO incondicional)
criticos     21 -> 21   (ninguno perdido, ninguno silenciado nuevo)
modulos     273 -> 300  (ninguno perdido, +27)
en_pie      277 -> 304
total      8120 -> 8505
```

El trinquete sigue apuntando en la dirección correcta: **no se retiró ningún
módulo, ningún crítico y ningún silenciamiento**. La base sólo incorpora
crecimiento ya demostrado legítimo.

## Lo que esta actualización NO tapa

Que un silenciamiento sea **legítimo como marca** no significa que la puerta
llegue a abrirse alguna vez. Son dos cosas distintas y aquí se separan:

1. **13 de los 15 módulos no los invoca ningún job.** `ci.yml` sólo ejecuta con
   `S9K_WRITER_NEO4J_REAL: "1"` los dos ficheros que ya estaban en la base
   (`..._writer_neo4j_real.py` y `..._e2e_neo4j_real.py`). Los otros 13 suman
   **102 pruebas que hoy no corren en ninguna parte**: un condicional cuya
   condición nadie activa es, en la práctica, un apagado permanente.
2. **`test_knowledge_v3_equipo5b_propiedad_rollback_neo4j_real.py` depende de
   `S9K_5B_NEO4J_URI` y `S9K_5B_NEO4J_PASSWORD_FILE`, que *nada* en el
   repositorio define.** Es exactamente el patrón «condición que nadie define
   nunca» contra el que avisa la propia docstring de `silenciado()`.

Ambos puntos son de la **invocación de cobertura Neo4j real de CI**, cuyo dueño
es otro cambio en curso. Se declaran aquí para que queden en el diff y no se
pierdan detrás de una base actualizada.

## La regla, para la próxima vez

- La línea base **no se regenera para que el gate calle**. Se regenera después
  de responder, por módulo: ¿está silenciado?, ¿por qué?, ¿desde cuándo?, ¿es
  intencionado?, ¿sigue siendo legítimo?
- La evidencia es **AST o ejecución con `PYTEST_RC`**, nunca lectura a ojo.
- La pregunta que decide es **«¿existía y corría en la base?»**. Si existía y
  corría, el silenciamiento se **quita**; no se mueve la base.
- Y después de mover la base hay que **volver a calibrar**: si las ablaciones
  dejan de ponerse rojas, la base «arreglada» es peor que el fallo original.

# M5b-C — Consolidación de la cadena de autorización

> **Séptima ronda (esta versión).** Seis dictámenes independientes, seis NO
> CONFORME. El sexto encontró el defecto de fondo: **el registro declarativo
> declaraba la semántica que queremos y nada probaba que el motor la cumpliera.**
> `known_from_session` declaraba `missing=DENY` y el motor —`if desde is not
> None:`— dejaba pasar la ausencia. Es la misma forma de fallo de las seis
> rondas, ahora dentro de la propia red anti-reincidencia. Este documento y la
> implementación se han vuelto a alinear: **que dijeran cosas distintas era
> parte del defecto**, no una errata.

Seis dictámenes independientes consecutivos, seis NO CONFORME, y **ninguno
encontró dos veces la misma línea de código**. Encontraron seis veces la misma
*forma* de fallo:

```
se implementa una barrera
  → se prueba el componente
    → queda verde
      → otro tramo de la cadena no transporta / no produce / no aplica
        → la barrera es decorativa, o falla abierta
```

Seguir parcheando caso por caso iba a seguir encontrando variantes. M5b-C no
añade funcionalidad: convierte cada dimensión de autorización en una **cadena
comprobable de extremo a extremo**.

## La tesis

Una dimensión de autorización **no es un campo: es una cadena**.

```
autoridad → productor → persistencia → transporte → contexto → consumidor
                                                      ↓
                                    ¿y si falta? ¿y si es inválido?
```

Un solo eslabón roto la convierte en decoración, y **ninguna prueba de
componente lo detecta**, porque cada componente por separado está bien. Ese es
el punto: no fallaba el código, fallaba el espacio entre piezas.

Los casos reales, para que no se lea como abstracción:

| # | Eslabón roto | Consecuencia |
|---|---|---|
| H1 | transporte | `_node_to_dict` descartaba `partida_id`: el aislamiento entre partidas no se evaluó nunca sobre datos reales, con 675 tests verdes |
| H2 | transporte | `_rel_to_dict` sin `visibility`: toda relación inválida |
| G3 | transporte | el motor leía `known_by_characters`; la proyección no lo llevaba — y la red anti-reincidencia no podía verlo |
| T1 | productor | el motor leía `party`/`is_public`/`session_index` y **nadie los escribía** |
| H-A | productor | `max_visible_session` tenía columna, lector y pruebas, y ningún escritor |
| H-B | ausencia | un valor corrupto se degradaba a `None` = "sin tope": el dato ilegible **abría** la barrera |
| ALTO-1 | ausencia | el arreglo de H-A fue *opt-in*: `NULL` seguía abriendo, y la migración deja `NULL` en todas las filas previas |
| H6-1 | ausencia | `if desde is not None:` — un nodo `scope=partida` **sin** `known_from_session` se saltaba la regla entera y era visible con cualquier tope, mientras el registro y este documento declaraban `missing=DENY`. El único guardián era un `raise` del writer, sin ninguna prueba |
| H6-5 | prueba | poner `active_character=None` en `dependencies.py` dejaba **806 tests verdes**: ninguna prueba demostraba que la concesión de personaje tuviera efecto de extremo a extremo (la de revocación leía la tabla en vez de pedir por HTTP) |
| H6-9 | ausencia | un autenticado **sin partida activa** quedaba *menos* restringido que un anónimo: `dependencies.py` devolvía `None` (= sin tope) y el anónimo recibe 0 |

## La matriz

Fuente autoritativa: `viewer/app/policies/registry.py`. Esta tabla es su
proyección legible; si divergen, manda el código, porque el código es el que
está probado.

### Dimensiones del dato

| Dimensión | Autoridad | Productor | Persistencia | Consumidor | Ausente | Inválido |
|---|---|---|---|---|---|---|
| `workspace` | servidor | writer V3 | Neo4j | policy + Cypher acotado | DENY | DENY |
| `scope` | contrato V3 | `scope_props` | Neo4j | policy | DENY | DENY |
| `partida_id` | contrato V3 | `scope_props` | Neo4j | policy | DENY (si `scope=partida`) | DENY |
| `visibility` | contrato V3 | `stamp` | Neo4j | policy | DENY | DENY |
| `known_by` | concesiones | `stamp` | Neo4j | `known_by_of` + policy | NEUTRO *(razonado)* | DENY |
| `known_by_characters` | concesiones | `ingest_rpg` | Neo4j | `known_by_of` | NEUTRO *(razonado)* | DENY |
| `known_from_session` | concesiones | `revelacion_props` | Neo4j | policy | **DENY** si `scope=partida` (lo aplica el motor); NOT_APPLICABLE si `scope=juego` | DENY |

### Dimensiones del contexto

No son campos de nodo, y **esa distinción es la que dejó pasar H-A**: la red
anterior sólo miraba campos de nodo, así que no cubría ninguna de estas.

| Dimensión | Autoridad | Productor | Persistencia | Ausente | Revocación |
|---|---|---|---|---|---|
| `max_visible_session` | servidor (concesión) | `grant_partida_access` + panel | `partida_access` v3 | **0** en la concesión; ilegible → DENY; sin partida activa → NOT_APPLICABLE | inmediata |
| `active_character` *(→ `character_id`)* | servidor (concesión) | `grant_partida_access` + panel | `partida_access` v3 | mínimo | inmediata |
| `allowed_partida_ids` *(→ `partida_id`)* | servidor | router de partida | `partida_access` | mínimo | inmediata |
| `can_view_future` | servidor (rol) | `context.py` | derivado del rol | `false` | inmediata |
| `can_view_secret` | servidor (rol) | `context.py` | derivado del rol | `false` | inmediata |
| `allowed_workspaces` | servidor | `context.py` | configuración | mínimo | inmediata |

Las dos flechas `→` señalan **renombrados declarados**: la dimensión se lee con
un nombre y se escribe con otro. Declararlo es obligatorio, porque un renombrado
tácito entre escritor y lector es exactamente T1.

### Dimensiones retiradas

Se declaran para que no vuelvan por la puerta de atrás: si alguien las
reintroduce en el motor, la comprobación bidireccional se pone roja.

- `party`, `is_public` — eran una ACL dinámica (T1).
- `session_index` — sustituido por `known_from_session` (T2).

## La regla de `None` (séptima ronda)

En autorización **`None` no puede significar tres cosas a la vez**. Lo hacía:
`max_visible_session = None` significaba, a la vez, *"no hay partida activa"*,
*"la concesión no declara tope"* y *"no se pudo leer la concesión"* — y el motor
las trataba a las tres igual, saltándose la regla. Cada dimensión tiene ahora
tres estados **distinguibles**:

| Estado | Significado | Efecto |
|---|---|---|
| `VALUE` | valor válido | se aplica |
| `NOT_APPLICABLE` | declarado explícitamente (`NO_APLICA`; p. ej. tope sin partida activa) | no concede: deniega el contenido que sí declara la dimensión |
| `MISSING_INVALID` | ausencia inesperada o valor inválido | **DENY** |

**Prohibido decidir con `if x is not None:`** cuando `None` pueda significar más
de un estado. En `app/policies/models.py` viven el centinela `NO_APLICA` y los
clasificadores `estado_de_entero_no_negativo` / `estado_de_identificador`.

Corolario, y es el que cierra H6-9: **quitarle contexto al lector nunca puede
darle más acceso.** Está probado como propiedad, no caso a caso
(`test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible`).

## La regla global de los defaults

**Un campo de seguridad ausente nunca es permiso máximo.** El único acceso
ampliado procede de una declaración positiva:

```
workspace ausente          → DENY
scope ausente              → DENY
visibility ausente         → DENY
known_by malformado        → DENY, nunca 500
max_visible_session NULL   → 0 en la concesión; ilegible → DENY del contenido
max_visible_session sin
  partida activa           → NOT_APPLICABLE (declarado), nunca "sin tope"
known_from_session ausente
  bajo scope=partida       → DENY   ← lo aplica el MOTOR, no sólo el writer
known_from_session ausente
  bajo scope=juego         → NOT_APPLICABLE (declarado)
can_view_future NULL       → false
can_view_secret NULL       → false
active_character NULL      → ningún bypass
```

El panel escribe **0 explícito** cuando el operador deja el tope en blanco: un
`NULL` en la tabla es indistinguible de una fila migrada, y esa ambigüedad es la
que hubo que cerrar. El formulario dice lo mismo que hace el backend
(`vacío = 0`); decía `vacío = sin tope`, que ya no existe como estado (H6-10).

## La red anti-reincidencia, rehecha

La anterior buscaba el nombre del campo por el repositorio con `grep`, y **falló
dos veces**: contaba 169 ficheros de prueba como "productor real" —o sea, un
campo presente sólo en fixtures pasaba por escrito de verdad, que es el defecto
de H1 dentro de la red contra H1—, se conformaba con una mención en un
comentario o en una lista de *prohibición*, y sólo miraba campos de nodo.

La nueva no adivina: el registro **declara** la cadena y las pruebas comprueban
que la realidad coincide, en las dos direcciones.

```
el motor consulta un campo   → debe estar en el registro
                             → el provider debe transportarlo
el registro declara un campo → el fichero que dice ser su productor debe escribirlo
                             → debe existir prueba de ausencia/invalidez
                             → si es de contexto, la autoridad debe ser el servidor
```

Comprueba la **ruta concreta** declarada como productor, no apariciones sueltas,
y descarta comentarios.

### De declaración a especificación ejecutable (séptima ronda)

Lo anterior seguía sin bastar, y el sexto dictamen lo demostró: la comprobación
de "tiene prueba" era que el **nombre** del campo apareciera en algún fichero de
tests. *Mencionar no es probar*, y por eso el registro pudo declarar
`missing=DENY` mientras el motor dejaba pasar la ausencia.

`tests/test_registro_es_especificacion_ejecutable.py` ejerce el motor de verdad,
dimensión a dimensión:

1. construye un caso **visible** de referencia (y comprueba que lo es: si no,
   toda prueba negativa pasaría sin demostrar nada);
2. le **quita** el campo y comprueba que el motor hace lo que el registro dice
   ante la ausencia;
3. lo **corrompe** y comprueba lo mismo ante el dato inválido;
4. exige que cada dimensión declare —y que existan— su `prueba_negativa` y su
   `prueba_http`, y que el fichero declarado como prueba HTTP **pida de verdad
   por HTTP** y no fabrique un `ViewerContext` a mano.

Si alguien vuelve a poner `if x is not None:` en una decisión de seguridad, el
registro seguirá diciendo `DENY` y este fichero se pondrá **rojo**.

## Revocación

`COALESCE(nuevo, viejo)` no puede usarse en autorización: hace que `NULL`
signifique a la vez *"no modificar"* y *"revocar"*, y con esa ambigüedad la
concesión de personaje **no se podía retirar** desde el panel. Reconceder declara
ahora el **estado completo** de la concesión. Revocar borra la fila, de modo que
"vigente" es *existe la fila*, sin estados intermedios que interpretar.

## Lo que se prueba por HTTP

Ninguna de las cinco rondas anteriores probó la cadena entera: todas fabricaban
el `ViewerContext` a mano, y por eso los defectos vivían justo en los tramos que
ese atajo se salta. `tests/test_autorizacion_e2e_http.py` no construye ningún
contexto: concede en la base, pide con cookie de sesión real y mira la respuesta.

Cubre: tope que oculta lo no revelado; **concesión migrada con `NULL` que no gana
acceso** (el caso del quinto dictamen, como regresión permanente); `known_by` que
no abre el spoiler; subir el tope que sí lo revela —la barrera no puede ser
"denegar siempre"—; acceso por ID que no esquiva la barrera; búsqueda; y
**revocación efectiva en la petición siguiente**, con la misma cookie, sin
reiniciar ni limpiar caché.

`tests/test_autorizacion_e2e_http_septima_ronda.py` añade **un testigo HTTP por
cada dimensión del registro**, y en particular los que faltaban: que la concesión
de personaje **abre** su secreto y que revocarla lo **cierra** en la petición
siguiente (H6-5); que un nodo de partida sin sesión de revelación no se lista ni
por ID (H6-1); que un `partida_id` en blanco no se degrada a lore compartido y
que una partida activa en blanco no es un comodín (H6-2); y que un autenticado
sin partida activa **no ve más** que con ella (H6-9).

Se prueban además, por primera vez, los caminos fail-closed de
`authz/dependencies.py` (`tests/test_dependencias_fail_closed.py`), el panel de
admin como productor real de las concesiones
(`tests/test_admin_panel_concesiones.py`), el acotado por workspace **dentro del
Cypher** (`tests/test_acotado_por_workspace_en_cypher.py`) y el guardado
reservado del writer sobre `known_by_characters` y `known_from_session`
(`data-engine/app/tests/test_props_reservadas_de_autorizacion.py`).

Verificado además **por mutación**: cada corrección tiene una mutación que
reintroduce el defecto y un test concreto que se pone rojo. Se comprueban las 14
mutaciones de una vez con `python3 mutaciones.py` desde la raíz del repo, que
revierte siempre lo que toca.

## Lo que sigue sin estar cerrado

Honestidad por delante, que es lo que faltó las seis rondas anteriores:

- **`ingest_rpg` escribe `known_from_session` como campo opcional** y no estampa
  `scope`. No produce, por tanto, contenido de ámbito `partida`: lo que escribe
  sin `scope` queda denegado por la regla 2b. La consecuencia es la ya aceptada
  en M5c —el grafo legacy queda mudo— no una fuga; pero la ingesta de rol sigue
  sin estar alineada con el contrato V3, y alinearla es trabajo aparte.
- **La integración real contra Neo4j se salta sin base efímera.** Los tests de
  `test_neo4j_integration_authz.py` sólo corren con `NEO4J_TEST_URI`; el acotado
  por workspace se comprueba aquí con un driver falso que captura el Cypher.
- **Sin dictamen independiente ni despliegue.** No se ha tocado producción.

## Estado

- Registro declarativo con 13 dimensiones, cada una con `prueba_negativa` y
  `prueba_http` **declaradas y verificadas**.
- ~90 comprobaciones derivadas del registro, ~26 pruebas HTTP de extremo a
  extremo, 13 mutaciones con test rojo demostrado.
- **Despliegue: sigue sin autorizar.** Requiere dictamen CONFORME independiente.

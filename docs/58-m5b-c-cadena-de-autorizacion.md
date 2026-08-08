# M5b-C — Consolidación de la cadena de autorización

Cinco dictámenes independientes consecutivos, cinco NO CONFORME, y **ninguno
encontró dos veces la misma línea de código**. Encontraron cinco veces la misma
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

Los cinco casos reales, para que no se lea como abstracción:

| # | Eslabón roto | Consecuencia |
|---|---|---|
| H1 | transporte | `_node_to_dict` descartaba `partida_id`: el aislamiento entre partidas no se evaluó nunca sobre datos reales, con 675 tests verdes |
| H2 | transporte | `_rel_to_dict` sin `visibility`: toda relación inválida |
| G3 | transporte | el motor leía `known_by_characters`; la proyección no lo llevaba — y la red anti-reincidencia no podía verlo |
| T1 | productor | el motor leía `party`/`is_public`/`session_index` y **nadie los escribía** |
| H-A | productor | `max_visible_session` tenía columna, lector y pruebas, y ningún escritor |
| H-B | ausencia | un valor corrupto se degradaba a `None` = "sin tope": el dato ilegible **abría** la barrera |
| ALTO-1 | ausencia | el arreglo de H-A fue *opt-in*: `NULL` seguía abriendo, y la migración deja `NULL` en todas las filas previas |

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
| `known_from_session` | concesiones | `revelacion_props` | Neo4j | policy | DENY (si `scope=partida`) | DENY |

### Dimensiones del contexto

No son campos de nodo, y **esa distinción es la que dejó pasar H-A**: la red
anterior sólo miraba campos de nodo, así que no cubría ninguna de estas.

| Dimensión | Autoridad | Productor | Persistencia | Ausente | Revocación |
|---|---|---|---|---|---|
| `max_visible_session` | servidor (concesión) | `grant_partida_access` + panel | `partida_access` v3 | **0** | inmediata |
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

## La regla global de los defaults

**Un campo de seguridad ausente nunca es permiso máximo.** El único acceso
ampliado procede de una declaración positiva:

```
workspace ausente          → DENY
scope ausente              → DENY
visibility ausente         → DENY
known_by malformado        → DENY, nunca 500
max_visible_session NULL   → 0
can_view_future NULL       → false
can_view_secret NULL       → false
active_character NULL      → ningún bypass
```

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

Verificado además **por mutación**: al restaurar `NULL = sin tope`, tres de estas
pruebas se ponen rojas. No son decorativas.

## Estado

- Registro declarativo con 13 dimensiones, 48 comprobaciones derivadas de él.
- 9 pruebas HTTP de extremo a extremo.
- **Despliegue: sigue sin autorizar.** Requiere dictamen CONFORME independiente.

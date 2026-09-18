# M1 — Descubrimiento jerárquico de bóvedas y clasificación ruta → ámbito

Implementa el contrato de [`89-bovedas-esquema-carpetas.md`](89-bovedas-esquema-carpetas.md),
§3, sin rediseñarlo. Este documento dice **dónde vive cada regla**, **qué se
garantiza** y —sobre todo— **qué NO se garantiza**, que es la parte que un
lector no puede deducir del código.

El documento 89 es el mismo texto que estaba en la rama `docs/bovedas-esquema-carpetas`,
rescatado sin modificar (se renumera porque el 53 está ocupado en `main`).

## 1. El defecto que se corrige, y el que NO se introduce al corregirlo

El catálogo de fuentes era **plano**: `sorted(raiz.iterdir())`, sin recursión.
Descartaba subdirectorios **sin aviso, sin warning y con `stderr` vacío**
(medido: cuatro niveles entraban, uno salía).

La corrección obvia —hacerlo recursivo— **es peor que el defecto**. La ruta sí
viajaba (`source_path`), pero nada aguas abajo derivaba ámbito de ella: el
`workspace` salía de un único perfil en la raíz y el payload encolado era
exactamente `['source_path','profile_path','catalog_path','workspace',
'source_title','requested_by']`, **sin `partida_id` y sin `visibility`**. Un
`rglob` a secas habría metido `reservado/`, `secretos/` y `compartido/` **todos
con el mismo ámbito único de la raíz y sin partida**.

Por eso **recursión y clasificación entran juntas**, y la unión no es una
convención que alguien pueda olvidarse de respetar:

> `FuenteDisponible.ambito` es un campo **obligatorio y sin defecto**.
> `FuenteDisponible(...)` sin `ambito` es un `TypeError` antes de que el objeto
> exista.

Quitar la clasificación no degrada el resultado: **impide construirlo**.

## 2. Dónde vive cada cosa

| Pieza | Fichero |
|---|---|
| La tabla §3, ejecutable | `viewer/app/vault_scope.py` |
| La frontera de montaje | `viewer/app/vault_mount.py` |
| El recorrido jerárquico | `viewer/app/sources_catalog.py::listar_fuentes_boveda` |
| El alta con partida y visibilidad | `viewer/app/routers/chassis_operations.py` |
| La partida hasta el motor | `data-engine/app/jobs/handlers/ingest_v3.py` |

Se enciende con `S9K_VAULT_ROOT`. Sin esa variable el catálogo **plano heredado
sigue exactamente igual** y sigue siendo **no recursivo a propósito**: un
directorio suelto no tiene esquema del que derivar ámbito, así que recorrerlo en
profundidad sería justamente la recursión sin clasificación que el invariante
prohíbe. `S9K_VAULT_REQUIRE_MOUNT=0` desactiva la exigencia de montaje activo;
el defecto es exigirlo.

## 3. La identidad del workspace se DECLARA, no se infiere

```
Bóveda Nextcloud / MONTAJE
   -> PERFIL DE LA BÓVEDA  (<juego>/perfil-operador.json)
        |- workspace = "leyenda"     <- explícito, ya existía
        `- reglas de ámbito/ruta     <- esta extensión
   -> común | partida concreta  ->  Source  ->  ingest_v3
```

`l5r/` es un **nombre externo de carpeta**. Que corresponda al workspace
`leyenda` es una **declaración del operador en el perfil**, nunca algo que el
código deduzca del nombre. Se reutiliza el mecanismo que ya existía —el alta ya
leía `workspace` de un perfil JSON—, uno por bóveda.

**No hay tabla global carpeta → workspace.** Una carpeta de juego cuyo perfil no
declare `workspace` **no aporta ninguna fuente**: sin declaración no se inventa
una, y la bóveda entera queda rechazada con motivo `PERFIL_DE_BOVEDA_INVALIDO`.

El `workspace` **no lleva `:`**: el contrato V3 congelado
(`contracts/knowledge-v3/v1/_common-v3.schema.json`, `$defs.workspace`) no lo
admite, así que `juego:<x>` queda descartado. Tampoco se llama
`workspace_aliases`: ese nombre ya designa el glosario de alias de **entidad**
(`review/workspace_aliases.py`).

## 4. Falla cerrado, y distingue dos rojos

```
ruta conocida + válida       -> Source
ruta desconocida             -> NO INGESTAR + diagnóstico explícito
ruta conocida INCOHERENTE    -> NO INGESTAR
```

Son **dos motivos distintos** porque son dos errores distintos del operador:
«esto no va en la bóveda» y «esto va aquí pero está mal nombrado». Colapsarlos
obligaría a adivinar cuál de los dos ocurrió.

| Motivo | Cuándo |
|---|---|
| `RUTA_DESCONOCIDA` | ninguna fila de §3 cubre la ruta |
| `RUTA_INCOHERENTE` | buzón de aportaciones que no corresponde a su partida; `sesion-NN` mal formada; ruta que sube de la raíz |
| `RUTA_RESERVADA` | `_plantilla/**` |
| `RUTA_NO_INGERIBLE` | `<juego>/archivo/**` |
| `PERFIL_DE_BOVEDA_INVALIDO` | la bóveda no declara su workspace |
| `FORMATO_NO_SOPORTADO` / `FUENTE_ILEGIBLE` | la fuente no se puede leer |
| `AUXILIAR_NO_ES_FUENTE` | perfil, catálogo o `README.md`: acompañan a las fuentes pero no lo son |

**Nunca «ya veremos luego qué ámbito era».** No existe ninguna rama que devuelva
un ámbito por defecto. La propiedad se mide con un **barrido de ~850.000 rutas**
(producto cartesiano de segmentos legítimos y hostiles hasta profundidad 4), que
exige de cada una: o `NoIngerible` con uno de los cuatro motivos **y su
diagnóstico**, o un `Ambito` con visibilidad del enum cerrado, regla dentro de la
tabla §3 y **sin workspace inventado**. Su techo está declarado en el propio test
(profundidades mayores, nombres arbitrarios, otros separadores, Unicode).

Y **lo que no entra se ve**: la pantalla del panel lista los rechazos con su
motivo. Descartar en silencio era el defecto original con otra cara.

### La tercera salida que sí existía

La primera entrega afirmaba, en el docstring del recorrido, que *«toda ruta
recorrida acaba en uno de los dos sitios… no hay tercera salida»*. **Era falso.**
`if nombre in _NO_SON_FUENTES: continue` se evaluaba **antes de clasificar y sin
registrar rechazo**, a cualquier profundidad: un `README.md` con contenido real
dentro de `compartido/lore/` salía **ni fuente ni rechazo, en silencio** — el
defecto de este corte en forma residual.

No podía producir un ámbito erróneo ni sobreexponer (excluye, es *fail-closed*),
pero la afirmación absoluta no se sostenía. Ahora esos ficheros se **declaran**
con `AUXILIAR_NO_ES_FUENTE`, que convierte un silencio en un hecho visible.

Lo encontró **un revisor independiente, no esta suite**, y la razón importa: el
testigo construía el universo esperado con `_NO_SON_FUENTES`, **la misma
constante del sujeto que causaba el descarte**. Un testigo que hereda del sujeto
la definición de lo que vigila no puede ponerse rojo por esa clase de fuga. El
testigo ya no filtra nada: el universo es *todo fichero del árbol*, y si el
catálogo quiere excluir algo, que lo declare.

## 5. Las convenciones cerradas (instrucción 11)

- **`lore/` y `manuales/` son organizativas.** Heredan del nivel contenedor y no
  pueden modificarlo. No tienen fila propia en §3 a propósito: caen dentro del
  `**` de su contenedor. Añadir una carpeta organizativa nueva **nunca cambia la
  visibilidad de nada**. Lo mismo vale para `videos/` y `transcripciones/` bajo
  una sesión, y para las que el operador añada.
- **`_plantilla/` es reservada y no ingerible**, y se comprueba **lo primero**.
  El orden importa: contiene una réplica del árbol entero, así que clasificada
  después cada fichero suyo caería en la regla de la carpeta que imita y
  entraría con el ámbito de la carpeta real que no es. Hoy no existe en el árbol
  medido; el parser sabe qué hacer si aparece.
- **`aportaciones/<partida>-<jugador>` se conserva, y es deliberado.** Nextcloud
  fija el `file_target` al crear el compartido y **no lo actualiza**: cambiar el
  nombre exigiría rehacer todos los compartidos. El prefijo **se valida** contra
  la partida del contexto, pero **no es la fuente de autoridad de esa partida**:
  la autoridad es la carpeta bajo `partidas/`, y el prefijo sólo puede
  **desmentirla** (y entonces no se ingiere).
- **Sesiones: sólo contrato de entrada**, `^sesion-[0-9]{2,}$`. Dice cómo puede
  llamarse la carpeta. **No es un identificador global** y no declara nada.

## 6. La frontera es el montaje rclone

`main` consume Nextcloud por montaje (`S9K_RCLONE_MOUNT`). **No se ha creado
ningún cliente HTTP/WebDAV paralelo.** `vault_mount.inspeccionar` distingue, en
la capa de fichero: `MOUNT_AVAILABLE_CONTENT`, `MOUNT_AVAILABLE_EMPTY`,
`MOUNT_MISSING`, `MOUNT_UNREADABLE`, `MOUNT_STALE`, `PATH_MISSING`, `ERROR`.

El caso por el que existe este requisito: **un mountpoint que existe pero sin
montaje activo parece un directorio local perfectamente vacío**. No hay error
que ignorar, no hay `rc != 0`, no hay nada en `stderr`. Así que se **verifica
que está realmente montado y sólo después se enumera**, y un montaje no
verificado **no trae listado** (`entradas is None`): estructuralmente no se
puede confundir «miré y no había nada» con «no pude mirar».

No es hipotético: la credencial que alimenta el montaje dio un **401 real** en
producción, con `stdout` vacío y `rc=1`, en la única medición que decidía este
alcance. Tratarlo como lista vacía habría concluido «bóveda plana» — la decisión
contraria a la correcta.

## 7. La partida viaja explícita, y `collection_id` no se toca

El payload del alta añade `partida_id`, `visibility` y `scope_rule`, y el
handler pasa `partida_id` a `run_ingest`, que **ya lo aceptaba**.

`collection = collection:{workspace}` **se mantiene como está**. No se introduce
`collection:{workspace}:{partida}` ni colecciones derivadas del directorio: la
identidad del asset sigue siendo **independiente de ruta y de renombrado**.
Partida y ámbito viajan como **dimensiones explícitas**; no se recicla
`collection_id` para codificarlos.

## 7 bis. `AMBITO_PLANO`: el único ámbito que no sale de una ruta

Se nombra aparte porque es **el sitio del árbol donde alguien podría apoyarse
mañana sin entender por qué es seguro**.

En modo bóveda todo ámbito lo produce `clasificar` a partir de la ruta. En el
catálogo **plano heredado** no hay árbol del que derivar nada, así que la fuente
se construye con `AMBITO_PLANO`. **No es «el ámbito por defecto»** ni una puerta
trasera del invariante, y por tres razones comprobables:

1. es **lo más restrictivo** (`visibility="secret"`, el mismo defecto
   *fail-closed* del estampador): no puede sobreexponer nada;
2. lleva `regla="catalogo-plano-sin-boveda"`, que **se pinta**: no se disfraza de
   ruta clasificada;
3. **no trae `workspace`**, y el alta lo vuelve a exigir
   (`SOURCE_PACKAGE_INVALID` si el perfil no lo declara): tampoco inventa ámbito.

**Lo que no debe hacerse con él**: usarlo para «rellenar» un ámbito en modo
bóveda. Si una ruta no se sabe clasificar, la respuesta es un rechazo con su
motivo, no este objeto.

## 7 ter. ORIGEN no es REVELACIÓN — la frontera entre capas

**Decisión de diseño ratificada por el operador**, y la línea que este carril no
cruza. Son dos preguntas distintas y se responden en sitios distintos:

```
sesion de ORIGEN      = donde/cuando NACIO el material
                      = sale del arbol de la boveda          <- PROCEDENCIA, es de M1
sesion de REVELACION  = desde que sesion puede CONOCERLO un personaje
                      = decision EXPLICITA de una persona    <- known_from_session, es de Review
```

La regla, textual:

```
ruta: sesiones/sesion-05/...      NO IMPLICA      known_from_session = 5
```

M1 **puede y debe** saber que un documento viene de `partida X / sesiones /
sesion-05 / transcripciones`: eso es **contexto y procedencia de la fuente**. Lo
que **no** hace es convertirlo en concesión de conocimiento. Derivarlo sería
volver a hacer que una carpeta conceda conocimiento, que es justo lo que M1
tiene prohibido.

### Cómo está implementado

`Ambito.sesion_origen` lleva la carpeta `sesion-NN` de la que salió el fichero, y
`None` cuando no viene de una sesión — **no se inventa** para material de
`secretos/`, `notas-narrador/` o capa juego. Se llama `sesion_origen` y no
`sesion` a propósito: **el nombre tiene que impedir que alguien lo lea como
revelación**.

### Cómo está defendido, en tres capas

1. **Por AST** (barata y temprana): el clasificador no puede **nombrar**
   `known_from_session` / `known_by` en su código. Su techo está declarado: no ve
   indirecciones (`getattr`, claves compuestas en ejecución, campos de nombre
   neutro).
2. **Por efecto, sobre el objeto**: se miran las **claves** del `Ambito`, que es
   `frozen` y tiene seis campos.
3. **Por efecto, sobre el payload**: se miran las claves de lo que se encola.

Las capas 2 y 3 **no se esquivan**: una evasión de la capa 1 sólo sirve si
consigue meter el dato **en el objeto o en el payload**, y ahí se mira por clave.

### Dónde entra la revelación, y por qué no aquí

En **REVIEW, antes de sellar**, que es donde ya está el punto de autoridad
humana. No se añade otro almacén ni otra etapa:

```
fuente -> ingest -> propuestas -> REVIEW -> decision + revelacion/visibilidad
                                         -> plan sellado -> APPLY
```

Cuando falte la declaración se falla cerrado, con frase accionable y código
estable, **sin pedir identificadores técnicos al operador**. Nunca se elige en
silencio la sesión del path, la última sesión ni la fecha de ingesta.

> **M1 decide DÓNDE PERTENECE el material. Review decide QUÉ SIGNIFICA y CUÁNDO
> puede revelarse. Auth decide QUIÉN puede verlo. Ninguna de las tres suplanta a
> las otras.**

## 8. Lo que este carril NO hace, a propósito

- **No deriva permisos ni `known_by` de carpetas.** `known_by` se sigue
  produciendo en un único sitio, dentro de `stamp()`, y ni `vault_scope` ni
  `vault_mount` lo nombran. La carpeta fija un valor **inicial** de
  `visibility`; a partir de ahí manda `KnowledgeVisibilityV1` y el motor.
- **No deriva `known_from_session`.** Ver §9: es el límite real de este carril.
- **No toca** `policies/engine`, grants, auth, identidad durable, writer, esquema
  Neo4j, migraciones, contratos congelados V3, rollback, motor de extracción,
  planes sellados, procedencia ni la identidad de `Source`.
- **No es suyo** `local_override_of` (carril MULTIPARTIDA-READ).

## 9. Límite descubierto: partida sin sesión de revelación

**El hallazgo más importante de este carril, y no se ha rodeado.**

`run_ingest` falla cerrado si `partida_id is not None and known_from_session is
None` (`PLAN_SESION_NO_DECLARADA`): para ámbito de partida exige declarar en qué
sesión se reveló el contenido. **Ninguna carpeta puede suministrar ese dato.**
Derivarlo de `sesion-NN` sería exactamente conceder conocimiento por inferencia
de directorio — lo que la instrucción 10 prohíbe.

Consecuencia, **verificada ejecutando** el recorrido completo (panel → cola →
worker → motor): **hoy, ingerir material de partida termina en `failed`**, con
el diagnóstico exacto `PARTIDA_SIN_SESION_DECLARADA`.

Esa es la conducta **correcta**, no un fallo de esta implementación: la
alternativa —que la partida no llegase al motor— haría que la ingesta terminase
«correctamente» **en capa juego**, silenciosamente en el ámbito equivocado, que
es justo el desenlace que este corte existe para impedir.

**Lo que falta, y es decisión del operador, no del código**: por dónde entra la
sesión de revelación en el alta de producto (un campo del formulario, una
declaración en el perfil de la partida, u otra cosa). Se deja **abierto y
declarado**, no resuelto por inferencia.

## 10. Deuda declarada, no arreglada

- **`visibility` llega al payload y se detiene ahí.** `run_ingest` no tiene
  parámetro de visibilidad inicial, y dárselo habría sido tocar el motor. Queda
  registrado y auditado en el trabajo; conectarlo es otro carril.
- **El `summary` de la capacidad `ingesta_de_fuente`** (`viewer/app/chassis.py`)
  queda **sin tocar**: está elevado al operador. Se ha medido que añadir
  `partida_id` al alta **no cambia `path`, `methods`, `role` ni `audited`** —
  sólo deja ese `summary` desactualizado. **No hizo falta tocar nada más de
  `WRITE_CAPABILITIES`.**
- **La divergencia de contratos** (V3 impone patrón de `workspace`,
  `review-ingest` v1 no) no se resuelve aquí: es deuda para un test contractual.
- **La profundidad del árbol medido (6) coincide con el `--max-depth 6` de la
  sonda.** Lo que haya por debajo es **no medido, no inexistente**. El parser no
  lo trata como vacío: cualquier nivel extra bajo una sesión hereda como carpeta
  de formato, y cualquier otro cuelga de una fila `**` o cae en
  `RUTA_DESCONOCIDA`. Ninguna rama asume que no hay nada más abajo.

- **El catálogo PLANO heredado sigue descartando en silencio.** No es una
  regresión —es el comportamiento que ya tenía en `main`, y ese camino no es
  recursivo, así que el descarte es de un solo nivel y a la vista— pero conviene
  que quede dicho: **`AUXILIAR_NO_ES_FUENTE` cubre el modo bóveda, no el plano.**

## 11. Condición del ensayo RC — esto no se ha ejercido contra un rclone real

**Hay que decirlo antes que nada: el modo bóveda nunca se ha ejercido contra un
montaje rclone real.** Todo lo medido usa `S9K_VAULT_REQUIRE_MOUNT=0` sobre un
directorio temporal. El recorrido que falta por ejercer, entero, es:

```
montaje rclone REAL -> catalogo jerarquico -> clasificacion M1 real -> Source -> ingest_v3
```

Lo que **sí** está establecido, y acota el alcance del ensayo: la clasificación
**no depende del sistema de ficheros**. `vault_scope` es una función pura sobre
la cadena de la ruta —usa `PurePosixPath`, no toca disco— y clasifica igual
rutas que no existen. Así que un directorio temporal ejercita la clasificación
**exactamente igual** que un FUSE. Lo que el ensayo tiene que ejercer es la otra
mitad: **la frontera de adquisición y los bytes que el montaje entrega**.

Tres comprobaciones concretas, todas encontradas **ejecutando**. Ninguna bloquea
—las tres excluyen, y ninguna puede producir un ámbito equivocado— pero el
ensayo tiene que mirarlas:

**1 · `S9K_VAULT_ROOT` tiene que ser el MOUNTPOINT, no un subdirectorio suyo.**
Reproducido: con el montaje en `<mount>` y las bóvedas en `<mount>/bovedas`,
`ismount` da False y se levanta `MOUNT_MISSING` **aunque la bóveda esté llena y
sea perfectamente legible**. La dirección del fallo es la correcta (no se degrada
a lista vacía), pero es un **riesgo de disponibilidad con un mensaje que
despista**: dice «no hay montaje activo» cuando lo que pasa es que se apuntó un
nivel por debajo.

**2 · Caja del nombre.** `Compartido/` cae en `RUTA_DESCONOCIDA`. Es fail-closed
y correcto, pero en un backend que pliegue mayúsculas el ensayo debe confirmar
que rclone entrega los nombres **exactamente** como los fija el esquema.

**3 · Forma Unicode.** La clasificación es pura, **pero los bytes del nombre se
los da el sistema de ficheros**. Con la partida en NFC y el buzón de
aportaciones en NFD sale `RUTA_INCOHERENTE` con un mensaje que enfrenta **dos
cadenas visualmente idénticas** — fail-closed, pero **indiagnosticable para el
operador**. Nextcloud y macOS normalizan distinto, así que el caso es plausible,
no teórico.


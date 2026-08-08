# 59 — Panel RPG: gestión de partidas, personajes y conocimiento (DISEÑO)

> **Estado: DISEÑO. No hay una sola línea de esto implementada.**
> Este documento no describe el panel actual: describe el panel que se quiere.
> Todo lo que aquí aparece como ruta, endpoint, pantalla o acción es una
> propuesta. Lo único implementado hoy es lo que se enumera en §2 («Punto de
> partida real»), y está deliberadamente separado del resto para que nadie
> confunda diseño con realidad. Si en algún momento este documento y el código
> divergen, manda el código.

- **Rama**: `docs/panel-rpg-management-design` (solo `docs/`).
- **Depende de**: M5b-C, PR #152/#153 — `docs/55`, `docs/56`, `docs/57`,
  `docs/58` y `viewer/app/policies/registry.py`.
- **No define semántica nueva de autorización.** Reutiliza, sin renombrar, el
  vocabulario del registro declarativo de 13 dimensiones. Cualquier nombre de
  campo que aparezca aquí es el del registro; si hace falta uno nuevo, no se
  inventa en este documento: se añade primero al registro, con su cadena
  completa declarada.

---

## 1. Por qué existe este panel

Dos hechos del proyecto, ya pagados, fijan los requisitos de producto:

1. **Una concesión de personaje no se podía revocar desde el panel.** El
   `UPDATE` usaba `COALESCE(nuevo, viejo)`, así que reconceder con el campo en
   blanco no borraba nada. Y como `active_character` salta la regla de nivel, lo
   que sobrevivía era un *bypass* del que el operador no tenía noticia
   (`docs/57`, quinto dictamen).
2. **`PartidaAccess` no leía dos columnas y el panel no las mostraba.** Un
   permiso que el operador no ve es un permiso que no sabe que ha dado.

De ahí las dos leyes de diseño de todo este panel:

> **L1 — Todo lo que se puede conceder se tiene que poder ver y revocar desde
> la misma pantalla en la que se concede.**
>
> **L2 — La interfaz muestra el *estado efectivo*, no el formulario. `0`,
> `vacío` y `sin configurar` son tres cosas distintas y se pintan distinto.**

Y una tercera, heredada directa de `docs/58`:

> **L3 — Ninguna pantalla es una barrera.** El panel no autoriza: refleja lo que
> el servidor ya decidió. Ocultar un botón no es un permiso; el endpoint que hay
> detrás vuelve a comprobarlo todo.

---

## 2. Punto de partida real (lo que SÍ existe hoy)

Base sobre la que se diseña, en la rama `fix/m5b-c-authorization-consolidation`:

| Pieza | Estado |
|---|---|
| `users`, `sessions`, `audit_events` | existe (`viewer/app/auth/db.py`) |
| `partida_access` (esquema v3: `+max_visible_session`, `+character_id`) | existe |
| `sessions.active_partida` | existe |
| Roles `admin` / `reviewer` / `viewer` | existe (`auth/models.py:ROLES`) |
| `/admin/users`, `/admin/users/{id}`, `/admin/audit` | existe |
| `/admin/partidas`, `/admin/partidas/grant`, `/admin/partidas/{access_id}/revoke` | existe |
| `/partida/select` | existe |
| `/entities`, `/sources`, `/quality`, `/jobs`, `/reviews`, `/review-console` | existe, pero **no organizado por partida** |
| Registro declarativo de 13 dimensiones | existe |

Lo que **no** existe y este documento diseña: la partida como objeto de primera
clase con ficha propia; personajes como entidad gestionable; la vista de
conocimiento concedido (`known_by`) y su revocación; «ver como personaje»; y la
agrupación por partida de sesiones, fuentes, jobs y revisiones.

---

## 3. Dependencias explícitas con M5b-C

Esta tabla es contractual: cada elemento del panel se apoya en una dimensión ya
declarada. **El panel no introduce ninguna dimensión nueva.**

| Elemento de panel | Dimensión (registry) | Autoridad | Ausente | Revocación |
|---|---|---|---|---|
| Selector de partida activa | `allowed_partida_ids` (`stored_as: partida_id`) | servidor, reverificada en cada petición | MÍNIMO | inmediata |
| Tope de sesión de la concesión | `max_visible_session` | servidor (concesión) | **0**, no «sin tope» | inmediata |
| Personaje activo de la concesión | `active_character` (`stored_as: character_id`) | servidor (concesión) | MÍNIMO: sin conocimiento individual | inmediata; reconceder declara el estado completo |
| Ver material no revelado | `can_view_future` | servidor (rol) | `false` | cambio de rol |
| Ver material secreto | `can_view_secret` | servidor (rol) | `false` | cambio de rol |
| Workspace del panel | `allowed_workspaces` | servidor | MÍNIMO | inmediata |
| Panel de conocimiento concedido | `known_by` / `known_by_characters` | concesiones | NEUTRO (razonado) | por concesión |
| Columna «revelado desde» | `known_from_session` | concesiones | DENY bajo `scope=partida` | — (es del dato) |
| Etiqueta de ámbito | `scope` + `partida_id` | contrato V3 | DENY | — |
| Etiqueta de nivel | `visibility` | contrato V3 | DENY | `deny` es terminal |

### 3.1 Reglas heredadas que el panel no puede contradecir

- **La party no es una ACL.** No habrá en ninguna pantalla un control del tipo
  «dar acceso a la party P». Lo que habrá es «conceder a los personajes de la
  party P», que **materializa concesiones individuales** en `known_by` y las
  lista una a una, revocables por separado (`docs/57`, T1). El panel puede
  *usar* la party como atajo de selección; nunca como frontera de lectura.
- **`known_from_session` no es `session_index`.** La columna de la interfaz se
  rotula «Revelable desde la sesión», nunca «sesión» a secas, y nunca
  «pertenece a la sesión». Los dos conceptos no se muestran en la misma columna.
- **`max_visible_session` sale del servidor.** No existe ningún control de
  interfaz —ni de administrador— que lo pase como parámetro de consulta. Se
  edita en la ficha de la concesión y se persiste; la lectura lo relee de la
  concesión.
- **`known_by` no salta el tope histórico.** «Ver como personaje» con tope 5 no
  muestra lo que ese personaje sabe desde la 12. Esto tiene consecuencia de UI:
  la pantalla debe explicar la diferencia, porque para el narrador parecerá un
  fallo (§8.3).
- **`party`, `is_public`, `session_index` están RETIRADAS.** No aparecen como
  filtro, columna, etiqueta ni campo de formulario en ninguna pantalla.

---

## 4. Modelo de navegación

La partida es el contenedor. Todo lo demás cuelga de ella, salvo la
administración de usuarios, que es transversal.

```
/admin
 ├── /admin/usuarios                  transversal
 │     └── /admin/usuarios/{user_id}  ficha de usuario
 ├── /admin/auditoria                 transversal (append-only)
 └── /admin/partidas
       └── /admin/partidas/{partida_id}        FICHA DE PARTIDA
             ├── /datos            nombre, estado, workspace, ámbito
             ├── /usuarios         accesos concedidos (partida_access)
             ├── /personajes       PJ/PNJ de la partida
             ├── /accesos          matriz usuario x personaje x tope
             ├── /sesiones         sesiones de juego (numeración de campaña)
             ├── /conocimiento     known_by concedido, por personaje
             ├── /fuentes          fuentes de ingesta de esta partida
             ├── /jobs             jobs con scope=partida
             ├── /revisiones       cola de revisión de esta partida
             └── /auditoria        auditoría filtrada por partida_id
```

Dos advertencias de diseño sobre esta estructura:

- **«Sesiones» es ambiguo y hay que desambiguarlo en la propia interfaz.** Hay
  *sesiones de juego* (episodios de campaña, numeradas, las que compara
  `max_visible_session`) y *sesiones de acceso* (cookies, `sessions`, las que se
  revocan). Se rotulan siempre «Sesiones de campaña» y «Accesos activos». Nunca
  «sesiones» a secas en ninguna pantalla.
- **El árbol de partida no implica autorización por ruta.** Estar bajo
  `/admin/partidas/{id}/` no concede nada: cada endpoint reverifica
  `allowed_partida_ids` contra `partida_access`. La URL no es una credencial.

---

## 5. Wireframes textuales

### 5.1 Índice de partidas — `/admin/partidas`

```
┌ Partidas ─────────────────────────────────────────────── [+ Nueva partida] ┐
│ Workspace: s9 (fijado por el servidor)                                     │
│                                                                            │
│  Partida            Estado    Sesiones  Usuarios  PJ   Pend.rev.  Últ.act. │
│  ──────────────────────────────────────────────────────────────────────── │
│  la-caida-de-arn    ACTIVA        12        4      6       3      hace 2 d │
│  crisol             PAUSADA        5        2      3       0      hace 40 d│
│  demo-interna       ARCHIVADA      1        1      1       0      hace 1 a │
│                                                                            │
│  ⚠ 2 concesiones sin tope declarado → tope efectivo 0  [Revisar]           │
└────────────────────────────────────────────────────────────────────────────┘
```

El aviso inferior no es decorativo: es la superficie visible del caso del quinto
dictamen. Toda fila de `partida_access` migrada con `NULL` se muestra
explícitamente como **«sin configurar → efectivo 0»**, y aparece agregada aquí
hasta que alguien la declare.

### 5.2 Ficha de partida — `/admin/partidas/{partida_id}`

```
┌ la-caida-de-arn ──────────────────────────── [ACTIVA ▾] [Archivar] [Borrar] ┐
│ workspace: s9   ·   scope: partida   ·   partida_id: la-caida-de-arn        │
│ Creada 2026-01-12 por pjc   ·   Última ingesta: hace 2 días                 │
├─ Datos ─ Usuarios ─ Personajes ─ Accesos ─ Sesiones ─ Conocimiento ─────────┤
│  ─ Fuentes ─ Jobs ─ Revisiones ─ Auditoría                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Sesiones de campaña   12    (última: S12, 2026-07-30)                      │
│  Usuarios con acceso    4    (2 con personaje, 2 sin)                       │
│  Personajes             6    (4 PJ, 2 PNJ)                                  │
│  Concesiones known_by  38    (sobre 5 personajes)                           │
│  Jobs                   9    (1 en curso, 0 fallidos)                       │
│  Revisiones pendientes  3                                                   │
│                                                                             │
│  ⚠ 1 concesión con personaje asignado y tope sin configurar (efectivo 0)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Pestaña Accesos — la pantalla crítica

Es la que falló. Sustituye al formulario de concesión actual y muestra el
**estado completo** de cada fila de `partida_access`, sin campos ocultos.

```
┌ Accesos · la-caida-de-arn ───────────────────────── [+ Conceder acceso] ────┐
│                                                                             │
│ Usuario     Rol       Personaje activo   Tope sesión     Conced.  Acciones  │
│ ─────────────────────────────────────────────────────────────────────────── │
│ ana         viewer    Kira (PJ01)        S8              12-01    [Editar]  │
│                                                                  [Revocar]  │
│ bruno       viewer    — sin personaje    S12             02-03    [Editar]  │
│                                                                  [Revocar]  │
│ carla       reviewer  Toren (PJ04)       ⚠ sin configurar 05-19   [Editar]  │
│                                          → efectivo S0                      │
│                                          can_view_future: SÍ (rol reviewer) │
│                                          → el tope no la limita             │
│ dario       viewer    Nils (PJ02)        S0 (declarado)  07-02    [Editar]  │
│                                                                  [Revocar]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

Cuatro decisiones de presentación, todas consecuencia directa de defectos ya
ocurridos:

1. **«S0 (declarado)» y «⚠ sin configurar → efectivo S0» son visualmente
   distintos.** El valor efectivo coincide, el estado no, y solo el segundo pide
   acción del operador. Esto es L2.
2. **El rol que anula el tope se dice en la propia fila.** Un `reviewer` con
   `can_view_future = true` no está limitado por su tope: mostrar el tope sin
   decirlo daría una falsa sensación de barrera, que es el patrón exacto que
   persiguieron los cinco dictámenes.
3. **«— sin personaje» es un estado explícito**, no una celda vacía. Sin
   personaje no hay conocimiento individual.
4. **Revocar está en la misma fila que conceder.** L1.

### 5.4 Editar una concesión — estado completo, nunca parcial

```
┌ Editar acceso: ana → la-caida-de-arn ──────────────────────────────────────┐
│                                                                            │
│  Personaje activo   ( ) ninguno                                            │
│                     (•) Kira (PJ01)                                        │
│                     ( ) Nils (PJ02)   ...                                  │
│                                                                            │
│  Tope de sesión     [ 8 ]   ← obligatorio. 0 = no ve nada aún revelado.    │
│                     Sesiones de campaña actuales: 12                       │
│                     Esta concesión NO permite ver más allá de S8.          │
│                                                                            │
│  ⓘ Este formulario declara el ESTADO COMPLETO de la concesión.             │
│    Dejar «ninguno» RETIRA el personaje. No hay «no modificar».             │
│                                                                            │
│                                     [Cancelar]  [Guardar estado completo]  │
└────────────────────────────────────────────────────────────────────────────┘
```

- El campo de tope **no es opcional y no admite blanco**. Blanco fue lo que
  produjo el opt-in del cuarto arreglo. Si el operador quiere «no ve nada», debe
  escribir `0`.
- El botón dice «Guardar estado completo» y no «Guardar»: el texto del botón
  también es parte del contrato, porque el modelo mental de «guardar» es
  *parcial* y aquí no lo es.
- **Prohibido `COALESCE` en el endpoint que hay detrás** (`docs/58`,
  «Revocación»). Está anotado aquí porque el diseño de la pantalla depende de
  ello: una interfaz de estado completo sobre un `UPDATE` parcial vuelve a
  producir el bypass invisible.

### 5.5 Ficha de usuario — `/admin/usuarios/{user_id}`

```
┌ ana ───────────────────────────────────── [ACTIVA ▾]  [Desactivar usuario] ┐
│ Identidad   ana · «Ana R.» · creada 2026-01-04 por pjc                      │
│ Rol         viewer  [Cambiar rol ▾]                                        │
│             capacidades derivadas del rol (servidor, no editables aquí):   │
│               can_view_secret: NO     can_view_future: NO                  │
│ Estado      activa · no bloqueada · debe cambiar contraseña: NO            │
│ Último acceso  2026-08-07 21:14 · fallos consecutivos: 0                   │
├─ Partidas y personajes ────────────────────────────────────────────────────┤
│  Partida            Personaje      Tope     Concedido   Acciones           │
│  la-caida-de-arn    Kira (PJ01)    S8       12-01       [Editar][Revocar]  │
│  crisol             — sin pers.    ⚠ s/conf 03-02       [Editar][Revocar]  │
├─ Accesos activos (sesiones de cookie) ─────────────────────────────────────┤
│  #4821  desde hace 2 h · partida activa: la-caida-de-arn  [Revocar]        │
│  #4790  desde hace 3 d · sin partida activa               [Revocar]        │
│                                        [Revocar todos los accesos]         │
├─ Auditoría (últimos 20) ───────────────────────────────────────────────────┤
│  2026-08-07 21:14  LOGIN_SUCCESS                                           │
│  2026-08-01 10:02  PARTIDA_ACCESS_GRANTED  la-caida-de-arn                 │
│                                              [Ver auditoría completa →]    │
└────────────────────────────────────────────────────────────────────────────┘
```

Las capacidades derivadas del rol se **muestran** y no se editan: su autoridad
es el rol, y ofrecer una casilla por usuario crearía una segunda fuente de
verdad para `can_view_future` — exactamente el tipo de vocabulario paralelo que
este diseño tiene prohibido.

### 5.6 Pestaña Conocimiento — `known_by` visible y revocable

Hoy no hay ninguna pantalla que responda «¿qué sabe este personaje y quién se lo
concedió?». Es el hueco que hizo que un bypass fuera invisible.

```
┌ Conocimiento · la-caida-de-arn ────────────────────────────────────────────┐
│ Personaje: [ Kira (PJ01) ▾ ]        38 concesiones · 3 desde la S10        │
│                                                                            │
│ Entidad / Aserto           Nivel      Revelable desde  Origen     Acciones │
│ ───────────────────────────────────────────────────────────────────────── │
│ El Pacto de Arn            secret     S3               party P1   [Revocar]│
│ Hermana de Toren           narrator   S7               manual     [Revocar]│
│ Localización del sello     secret     S12              sesión S12 [Revocar]│
│                                                                            │
│ [Conceder conocimiento…]   [Revocar selección (3)]                         │
└────────────────────────────────────────────────────────────────────────────┘
```

- **«Origen» es informativo, no autoritativo.** «party P1» significa *esta
  concesión individual se creó a partir de la party P1*, no *la party concede*.
  Es la materialización de T1 y así debe leerse en pantalla.
- Cada fila se revoca por separado. Una concesión creada en lote se revoca
  individualmente: si no, se repite el problema de la ACL.
- «Revelable desde» es `known_from_session`, del dato, no de la concesión. Se
  muestra porque explica por qué algo concedido puede no verse todavía.

### 5.7 «Ver como personaje»

```
┌ Ver como… ─────────────────────────────────────────────────────────────────┐
│ Partida    la-caida-de-arn                                                 │
│ Personaje  [ Kira (PJ01) ▾ ]                                               │
│ Hasta la sesión  [ 8 ]   (máx. permitido por tu propio acceso: 12)         │
│                                                                            │
│ ⓘ Es una simulación de LECTURA. No concede nada, no altera concesiones     │
│   y no puede mostrarte nada que tú no puedas ver ya.                       │
│                                     [Cancelar]  [Entrar en modo simulación]│
└────────────────────────────────────────────────────────────────────────────┘
```

Mientras está activo, banda persistente y no descartable en toda la interfaz:

```
▓▓ SIMULACIÓN · viendo como Kira (PJ01) hasta S8 · lo que ves NO es tu vista ▓▓
                                                              [Salir]
```

Reglas duras de la simulación, todas derivadas de `docs/57` y `docs/58`:

- **Es un techo, nunca un suelo.** La vista simulada es la
  *intersección* de lo que vería el personaje y lo que ve el operador. Un
  `viewer` que simula a otro personaje no gana visibilidad; si la simulación
  pudiera ampliar, sería una escalada de privilegio con forma de función de
  producto.
- El tope de la simulación se acota en servidor por el tope efectivo del
  operador (o por `can_view_future` si lo tiene). No se acepta un valor de
  cliente por encima de eso: sería `?max_visible_session=99` con otro nombre.
- **La simulación no escribe.** En modo simulación, toda acción de escritura
  —conceder, revocar, aprobar revisión, lanzar job— está deshabilitada en la
  interfaz y **rechazada en el servidor**. Deshabilitar el botón no es la
  barrera (L3).
- Entrar y salir se auditan.

---

## 6. Rutas y APIs necesarias

Nomenclatura: `GET` de pantalla devuelve HTML; los `/api/...` devuelven JSON y
comparten exactamente la misma autorización. Todo `POST` lleva CSRF, como el
panel actual.

### 6.1 Partidas

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| GET | `/admin/partidas` | admin | ya existe; se rehace |
| POST | `/admin/partidas` | admin | crear partida |
| GET | `/admin/partidas/{partida_id}` | admin | ficha; 404 si no autorizada |
| POST | `/admin/partidas/{partida_id}/estado` | admin | ACTIVA/PAUSADA/ARCHIVADA |
| POST | `/admin/partidas/{partida_id}/borrar` | admin | destructiva, §9 |
| GET | `/api/partidas` | admin | JSON del índice |

### 6.2 Accesos (concesiones)

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| GET | `/admin/partidas/{pid}/accesos` | admin | estado completo por fila |
| POST | `/admin/partidas/{pid}/accesos` | admin | conceder; **exige** `max_visible_session` |
| POST | `/admin/accesos/{access_id}` | admin | reconceder **estado completo**, sin `COALESCE` |
| POST | `/admin/accesos/{access_id}/revocar` | admin | borra la fila (sin estado intermedio) |

`partida_access` no gana columnas nuevas: el panel se limita a exponer las que
el esquema v3 ya tiene.

### 6.3 Personajes

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| GET | `/admin/partidas/{pid}/personajes` | admin | |
| POST | `/admin/partidas/{pid}/personajes` | admin | alta; `character_id` estable |
| POST | `/admin/personajes/{cid}` | admin | editar |
| POST | `/admin/personajes/{cid}/retirar` | admin | destructiva, §9 |

**Abierto (§11-D1)**: dónde vive el personaje. `character_id` está hoy en
`partida_access` como texto libre, sin catálogo. Un catálogo en `auth.db`
duplicaría lo que el grafo ya modela; leerlo del grafo mete Neo4j en la ruta de
administración. No se decide aquí.

### 6.4 Sesiones de campaña

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| GET | `/admin/partidas/{pid}/sesiones` | admin | numeración de campaña |
| POST | `/admin/partidas/{pid}/sesiones` | admin | registrar sesión N |

Solo lectura/registro: la sesión de campaña es la escala que `max_visible_session`
compara. Aquí **no** se toca `known_from_session`, que es del dato y lo escribe
el writer V3.

### 6.5 Conocimiento

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| GET | `/admin/partidas/{pid}/conocimiento?character_id=` | admin | lista `known_by` |
| POST | `/admin/partidas/{pid}/conocimiento/conceder` | admin | materializa individuales |
| POST | `/admin/partidas/{pid}/conocimiento/revocar` | admin | por concesión, en lote explícito |

**Abierto (§11-D2)**: `known_by` vive en Neo4j y lo estampa el writer. Conceder
desde el panel implica un escritor nuevo hacia el grafo, y `docs/56` (G4) ya
avisa de que hay escritores que producen `:Entity` sin pasar por `stamp`. **No
se diseña aquí el mecanismo de escritura**: solo la pantalla y el contrato de lo
que debe ocurrir. Ver §12.

### 6.6 Vistas agregadas por partida

| Método | Ruta | Rol |
|---|---|---|
| GET | `/admin/partidas/{pid}/fuentes` | admin |
| GET | `/admin/partidas/{pid}/jobs` | admin |
| GET | `/admin/partidas/{pid}/revisiones` | admin / reviewer |
| GET | `/admin/partidas/{pid}/auditoria` | admin |

Todas ellas **reusan** el filtrado existente; ninguna acepta `?workspace=` del
cliente. Es literalmente el defecto G2 (`docs/56`), donde `?workspace=` llegó a
enumerar directorios del servidor. El workspace lo decide el servidor y el
identificador de partida se valida por **lista blanca de forma**, nunca por
lista negra de `..`. Partida inexistente o no autorizada → **404, no 403**: un
403 confirmaría su existencia.

### 6.7 Simulación

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| POST | `/ver-como` | admin, reviewer | fija personaje+tope en la **sesión de servidor** |
| POST | `/ver-como/salir` | cualquiera en simulación | |

No es un parámetro de consulta. Es estado de sesión en servidor, acotado en
servidor, auditado al entrar y al salir.

---

## 7. Permisos necesarios

Sin roles nuevos. `admin` / `reviewer` / `viewer` bastan.

| Capacidad de panel | admin | reviewer | viewer |
|---|---|---|---|
| Ver índice y ficha de partida | sí | no | no |
| Crear / archivar / borrar partida | sí | no | no |
| Conceder / editar / revocar accesos | sí | no | no |
| Gestionar personajes | sí | no | no |
| Conceder / revocar conocimiento | sí | no | no |
| Ver conocimiento concedido | sí | solo lectura de su partida | no |
| «Ver como personaje» | sí | sí (acotado a su tope) | no |
| Ver auditoría | sí | no | no |
| Elegir su partida activa | sí | sí | sí |

Se rechazan explícitamente dos tentaciones:

- **No se crea un rol `narrator`.** `docs/57` ya registró que no existe y que la
  justificación «NULL = sin tope, para el narrador» no se sostenía. Si el
  producto lo necesita, es una decisión del operador (§11-D3) y entra por el
  registro, no por el panel.
- **No se añaden permisos por usuario** que dupliquen `can_view_future` /
  `can_view_secret`. Su autoridad es el rol.

---

## 8. Estados y su presentación

### 8.1 Estados de partida

| Estado | Lectura | Ingesta | Concesiones |
|---|---|---|---|
| ACTIVA | sí | sí | editables |
| PAUSADA | sí | no | editables |
| ARCHIVADA | solo admin | no | congeladas |

Archivar **no revoca**. Si el operador quiere retirar accesos, los revoca
explícitamente: un efecto colateral silencioso sobre autorización es lo que este
proyecto lleva cinco dictámenes evitando. La pantalla de archivar lo dice y
ofrece «revocar también los N accesos» como casilla **desmarcada**.

### 8.2 Estados de una concesión

| Presentación | Significado | Efectivo |
|---|---|---|
| `S8` | tope declarado | 8 |
| `S0 (declarado)` | declarado explícitamente | 0 |
| `⚠ sin configurar` | `NULL` en base (migración) | **0** |
| `— sin personaje` | `character_id` nulo | sin conocimiento individual |
| `no limitada por el tope` | rol con `can_view_future` | el tope no aplica |
| *fila ausente* | no hay concesión | sin acceso |

No existe estado «suspendida». `docs/58`: vigente **es** que la fila exista.

### 8.3 El estado que la interfaz debe explicar

El caso «concedido pero no visible» va a parecer un fallo y no lo es:

> *Kira tiene concedido «Localización del sello», revelable desde S12. Tu tope
> es S8, y `known_by` no salta el tope histórico. Para verlo: sube el tope a 12,
> o usa una cuenta con `can_view_future`.*

Ese texto, o equivalente, es requisito de la pantalla de conocimiento. Sin él,
alguien «arreglará» la regla de `docs/57` creyendo que es un bug.

---

## 9. Acciones destructivas y sus confirmaciones

Tres niveles. El nivel se elige por lo que se pierde, no por lo que cuesta
deshacerlo.

**N1 — confirmación simple** (modal, botón secundario):
revocar una sesión de acceso; salir de simulación; pausar partida.

**N2 — confirmación con consecuencias enumeradas**:

```
┌ Revocar acceso de ana a la-caida-de-arn ───────────────────────────────────┐
│ Efecto inmediato, en la siguiente petición, con la misma cookie:           │
│   · pierde el acceso a la partida                                          │
│   · pierde el personaje activo Kira (PJ01)                                 │
│   · si la tenía activa, su sesión pasa a «sin partida» (capa juego)        │
│ NO se borra ninguna concesión known_by ya materializada en el grafo.       │
│                                              [Cancelar]  [Revocar acceso]  │
└────────────────────────────────────────────────────────────────────────────┘
```

La última línea es esencial: revocar el acceso y revocar el conocimiento son
operaciones distintas, y creer que una implica la otra deja permisos vivos que
el operador cree retirados. También son N2: revocar conocimiento en lote,
retirar personaje, cambiar rol a la baja.

**N3 — confirmación por escritura del nombre + auditoría reforzada**:
borrar partida; borrar personaje con concesiones vivas; revocar todos los
accesos de una partida.

```
┌ Borrar la partida «la-caida-de-arn» ───────────────────────────────────────┐
│ Se eliminarán:  4 accesos · 6 personajes · 38 concesiones known_by         │
│ NO se elimina el contenido del grafo con partida_id=la-caida-de-arn        │
│ (159 nodos): quedaría sin partida autorizada, es decir, INVISIBLE.         │
│ Escribe el identificador para confirmar:  [                    ]           │
│                                        [Cancelar]  [Borrar definitivamente]│
└────────────────────────────────────────────────────────────────────────────┘
```

**Abierto (§11-D4)**: qué hacer con el contenido del grafo al borrar una
partida. Dejarlo huérfano es fail-closed y por tanto seguro, pero acumula datos
invisibles e irrecuperables desde la interfaz. Borrarlo es irreversible. La
propuesta por defecto es *no borrar nunca contenido de grafo desde el panel* y
exigir archivado previo; queda a decisión del operador.

Regla común a los tres niveles: **el modal enumera el efecto real, no la acción
nominal**. «¿Seguro?» no es una confirmación.

---

## 10. Auditoría

Reutiliza `audit_events` (append-only, no editable desde la interfaz) y los
tipos existentes. Tipos nuevos propuestos, en la misma convención:

```
PARTIDA_CREATED / PARTIDA_STATE_CHANGED / PARTIDA_DELETED
CHARACTER_CREATED / CHARACTER_UPDATED / CHARACTER_RETIRED
PARTIDA_ACCESS_UPDATED           (reconcesión de estado completo)
KNOWLEDGE_GRANTED / KNOWLEDGE_REVOKED
IMPERSONATION_STARTED / IMPERSONATION_ENDED
```

Ya existen y se conservan: `PARTIDA_ACCESS_GRANTED`, `PARTIDA_ACCESS_REVOKED`,
`PARTIDA_SELECTED`, `ROLE_CHANGED`, `SESSIONS_REVOKED`, `ACCESS_DENIED`.

Requisitos:

1. **Toda reconcesión registra el estado anterior y el nuevo, completos**
   (personaje y tope, ambos, incluso si uno no cambió). Con un diff parcial no
   se puede reconstruir un bypass a posteriori: es la versión de auditoría del
   mismo error que el `COALESCE`.
2. **Las acciones en simulación se auditan con el operador real**, no con el
   personaje simulado, y marcadas como simuladas.
3. La auditoría de partida se filtra por `partida_id` del servidor.
4. Nunca se registran valores de contenido del grafo en el evento: identificador
   y ámbito, no el secreto revelado.

---

## 11. Decisiones abiertas para el operador

| # | Decisión | Por qué no se decide aquí |
|---|---|---|
| **D1** | Dónde vive el catálogo de personajes: `auth.db` o grafo | duplicar el modelo o meter Neo4j en la ruta de administración; ambas tienen coste real |
| **D2** | Si el panel puede escribir `known_by` en el grafo | implica un escritor nuevo; G4 (`docs/56`) ya avisa de escritores que no pasan por `stamp` |
| **D3** | Si se crea el rol `narrator` | `docs/57` lo declaró inexistente; crearlo cambia la matriz de capacidades |
| **D4** | Qué ocurre con el contenido del grafo al borrar una partida | huérfano-invisible vs. irreversible |
| **D5** | Si `reviewer` puede «ver como personaje» en partidas que no tiene concedidas | útil para QA, es una ampliación de alcance de lectura |
| **D6** | Si conceder a una party materializa a los miembros *actuales* o a los *presentes en la sesión N* | es la pregunta que T1 dejó abierta al retirar la ACL |
| **D7** | Si al archivar una partida se revocan los accesos por defecto | la propuesta es «no», con casilla desmarcada |

---

## 12. Lo que este diseño NO cubre (y por qué)

Se enumera para que nadie lo lea como omisión:

- **El mecanismo de escritura de `known_by` desde el panel.** Depende de que se
  cierre G4 (`docs/56`): hoy `ingest_rpg` y `review/ingest_approved` producen
  `:Entity` sin pasar por `stamp`, y añadir un tercer escritor antes de eso
  metería `visibility` sin contrato por la puerta de al lado. Se diseñan la
  pantalla y el contrato; no el escritor.
- **El *ledger* temporal de concesiones** (`knowledge_grant` con
  `valid_from_session`). `docs/57` lo menciona como futuro y `known_by` es su
  proyección actual. Mientras no exista, no se puede ofrecer «conceder desde la
  sesión N» ni un historial de concesión: la pantalla de §5.6 muestra estado
  actual, no historia.
- **Identidad durable de nodos.** `docs/56` registra que `elementId` no
  sobrevive a un backup/restore. Cualquier concesión que apunte a un nodo debe
  usar `entity_id` / `assertion_id` + `workspace`; hasta que ese contrato esté
  cerrado, no se diseña la persistencia de la selección de la §5.6.
- **`VisibilityScope` y su inferencia permisiva** (G5): decisión explícita
  pendiente; el panel de jobs la hereda tal cual y no la contradice.
- **La numeración de sesiones de campaña como dato de dominio.** Hoy
  `max_visible_session` es un entero sin catálogo de sesiones detrás. §6.4 lo
  propone; su contrato no está cerrado.
- **Cualquier cambio en el motor de políticas.** Este panel no toca
  `policies/engine.py`. Si una pantalla pareciera exigirlo, la pantalla está mal
  diseñada.

---

## 13. Backlog por fases

Cada fase entrega algo utilizable y **ninguna se puede empezar antes de que
M5b-C tenga dictamen CONFORME independiente y despliegue autorizado**. Hoy no lo
tiene (`docs/55`, `docs/56`, `docs/57`, `docs/58`: «Despliegue: sigue sin
autorizar»).

**F0 — Hacer visible lo que ya se concede** *(sin esquema nuevo; el mayor valor
por unidad de riesgo)*
- Pestaña Accesos con estado completo (§5.3) y distinción `0` / `sin configurar`.
- Edición de concesión como estado completo (§5.4).
- Aviso agregado de concesiones sin tope declarado.
- Ficha de usuario con partidas, personajes y accesos activos (§5.5).
- Confirmaciones N2 con efectos enumerados.
- **Criterio de salida**: ninguna concesión con `NULL` sin marcar en pantalla, y
  toda concesión visible es revocable desde donde se ve.

**F1 — La partida como objeto**
- Índice y ficha (§5.1, §5.2), estados, auditoría por partida.
- Vistas agregadas de fuentes / jobs / revisiones, sin `?workspace=` de cliente.
- **Criterio de salida**: ningún endpoint nuevo acepta ámbito del cliente; 404
  para partida inexistente o no autorizada.

**F2 — Personajes** *(bloqueada por D1)*
- Catálogo, alta/edición/retirada, selector real en la concesión.

**F3 — «Ver como personaje»** *(bloqueada por F2)*
- Estado en sesión de servidor, techo por el tope del operador, banda
  persistente, escrituras rechazadas en servidor, auditoría de entrada y salida.

**F4 — Conocimiento** *(bloqueada por D2 y por G4)*
- Lectura de `known_by` por personaje y revocación individual.
- Concesión desde el panel **solo si** el escritor pasa por el contrato de
  `stamp`.

**F5 — Sesiones de campaña y concesión por party** *(bloqueada por D6 y por el
ledger temporal)*
- Catálogo de sesiones; materialización de concesiones individuales desde una
  party, listadas y revocables una a una.

---

## 14. Comprobaciones que este panel debe superar

Escritas ahora para que se implementen con la funcionalidad, en la línea de la
red anti-reincidencia de `docs/58`:

1. Una concesión con `character_id` no nulo **se puede revocar desde la
   interfaz** y el efecto se observa en la petición siguiente, con la misma
   cookie, sin reiniciar ni limpiar caché.
2. Reconceder con «personaje: ninguno» **retira** el personaje (no `COALESCE`).
3. Una fila con `max_visible_session = NULL` se renderiza como «sin configurar →
   efectivo 0», y nunca como celda vacía ni como «sin límite».
4. Ninguna plantilla del panel muestra `party`, `is_public` ni `session_index`.
5. Ningún endpoint del panel lee el workspace o el `partida_id` efectivos de un
   parámetro de consulta.
6. En simulación, toda ruta de escritura devuelve 403 aunque se invoque
   directamente, sin pasar por la interfaz.
7. La simulación nunca devuelve un nodo que el operador real no pudiera ver.
8. Toda acción destructiva escribe un evento de auditoría con estado anterior y
   posterior completos.

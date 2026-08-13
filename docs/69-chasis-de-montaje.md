# 69 — Chasis de montaje del visor

Contrato común sobre el que se montan cuatro funcionalidades futuras
(**C = Review**, **B = Operations**, **F = Sources**, **G = Entities**) sin
renegociar prefijos, guardas ni navegación. Este documento describe el chasis;
**no** describe ninguna de las cuatro funcionalidades, que aún no existen.

Piezas:

| Fichero | Papel |
| --- | --- |
| `viewer/app/chassis.py` | Contrato en datos: `FEATURE_SLOTS`, `NAV`, enumeración de rutas y resolución de la navegación |
| `viewer/app/routers/chassis_slot.py` | Fábrica del router de un hueco (guarda + contexto + plantilla) |
| `viewer/app/routers/chassis_{review,operations,sources,entities}.py` | Los cuatro huecos, montados y vacíos |
| `viewer/app/templates/chassis/_slot.html` | Estados explícitos: `error`, `empty`, `ready` |
| `viewer/app/main.py` | Montaje derivado del contrato + instalación de la navegación |
| `viewer/app/templates/base.html` | Menú recorrido desde el registro, sin enlaces a mano |
| `viewer/tests/test_chassis_mount_contract.py` | Las pruebas del contrato, contra la app real, más la copia a mano del contrato publicado |
| `viewer/.env.example` | Los cuatro interruptores `S9K_PANEL_<KEY>_ENABLED`, apagados por defecto |

## 1. Contrato de montaje

| | C — Review | B — Operations | F — Sources | G — Entities |
| --- | --- | --- | --- | --- |
| **Router** | `app.routers.chassis_review:router` | `app.routers.chassis_operations:router` | `app.routers.chassis_sources:router` | `app.routers.chassis_entities:router` |
| **Prefix** | `/panel/review` | `/panel/operations` | `/panel/sources` | `/panel/entities` |
| **Route name** | `chassis_review` | `chassis_operations` | `chassis_sources` | `chassis_entities` |
| **Role (quién puede)** | `reviewer` | `admin` | `reviewer` | `viewer` |
| **Template** | `chassis/review.html` | `chassis/operations.html` | `chassis/sources.html` | `chassis/entities.html` |
| **Nav item** | «Panel · Review» (orden 10) | «Panel · Operaciones» (11) | «Panel · Fuentes» (12) | «Panel · Entidades» (13) |
| **Estado vacío** | `data-state="empty"` — «Sin revisiones pendientes» | «Sin operaciones registradas» | «Sin fuentes» | «Sin entidades» |
| **Estado de error** | `data-state="error"` con el motivo, sin traza | ídem | ídem | ídem |
| **Test** | `test_chassis_mount_contract.py`, parametrizado por hueco (`[C]`) | `[B]` | `[F]` | `[G]` |

Sobre los prefijos: `/entities`, `/sources` y `/reviews` ya los ocupa el visor
de solo lectura, y un `/sources/panel` quedaría **capturado** por la ruta
dinámica `/sources/{source_id}` — la pantalla nueva no se serviría jamás y no
habría error en ninguna parte. Por eso los cuatro huecos viven bajo `/panel/…`,
libre de colisiones por construcción y comprobado en
`test_slot_prefixes_do_not_collide`.

Sobre los roles: el campo `role` toma valores de `app.auth.models.ROLES`
(`admin > reviewer > viewer`) y la decisión la ejecutan guardas **que ya
existían**: `app.auth.dependencies.require_admin` para los huecos `admin` y
`app.routers.readonly.html_role_guard` para los demás (ver §1 bis). **El chasis
no define ningún concepto de permiso nuevo**; el filtrado del menú delega en los
métodos del propio `User` (`can_access_admin`, `can_see_reviews`).

Este contrato está duplicado a mano en la propia suite
(`CONTRATO_PUBLICADO` en `test_chassis_mount_contract.py`) y se compara contra
`FEATURE_SLOTS`. La duplicación es deliberada: sin ella los tests leían
`slot.role` y `slot.prefix` del mismo dato que afirmaban —autorreferencia— y
cambiar el rol de B a `viewer`, el de G a `admin` o el prefijo de C a
`/panel/revision` pasaba **en verde** (medido: 40/2 skipped, 42 y 41 passed).
Cambiar el contrato debe costar tocar tres sitios: el dato, la tabla y este
documento.

### 1 bis. Guarda de cada hueco y por qué B es distinto

`chassis_slot.slot_guard(slot)` elige guarda **existente** según el rol
declarado:

| Rol del hueco | Guarda | Postura con `S9K_AUTH_ENABLED` ausente |
| --- | --- | --- |
| `admin` (B) | `app.auth.dependencies.require_admin` | 302 a `/login`, igual que `/admin/users` y `/admin/partidas` |
| `reviewer`, `viewer` (C, F, G) | `app.routers.readonly.html_role_guard` | no-op (comportamiento público), igual que `/sources` y `/reviews` |

Motivo, medido: con auth desactivada `html_role_guard` es no-op, así que el
hueco B —el panel de **administración**— devolvía **200 a un anónimo** mientras
sus pares del área de administración devolvían **302**. No era vocabulario de
autorización nuevo, pero sí una degradación respecto a sus pares. Cada hueco
queda ahora a la altura de las pantallas equivalentes que ya existen; la
comparación la hace `test_admin_slot_denies_anonymous_with_auth_disabled`
contra los pares reales, no contra una constante escrita en el test.

Recordatorio para quien monte encima: `Depends(guarda)` **no deniega por sí
solo**. Devuelve un `RedirectResponse` que el handler tiene que devolver. Si el
carril reescribe el handler y se come ese `return`, el anónimo entra.

### 1 ter. Interruptor por hueco: apagar un panel a medio construir

Cada hueco tiene su variable de entorno, `S9K_PANEL_<KEY>_ENABLED`
(`S9K_PANEL_C_ENABLED`, `…_B_…`, `…_F_…`, `…_G_…`).

- **Falla cerrado**: el panel se sirve si y sólo si el valor es exactamente
  `true` o `1` (`FLAG_ON_VALUES`, sin distinguir mayúsculas ni espacios).
  Ausente, vacío, `false`, `yes`, `0`, `quizas` → **404**. La ausencia de dato
  nunca es permiso máximo, y un valor que no se entiende es un dato ausente.
- **Por defecto los cuatro están apagados.** Es la postura correcta hoy: los
  huecos sirven una pantalla vacía.
- **El hueco sigue MONTADO aunque esté apagado.** Desmontarlo lo devolvería al
  fallo que este chasis existe para impedir (ruta muerta, censo que miente). Lo
  que se apaga es el servicio de la pantalla, no el montaje.
- **El interruptor se evalúa DESPUÉS de la guarda**: encender un panel no es
  autorizar a nadie, y un flag jamás puede ser una puerta lateral
  (`test_flag_does_not_bypass_authorization`).
- **Un panel apagado desaparece del menú**, porque enlazar un 404 es el enlace
  roto de siempre. Es la **única** omisión que `nav_for` admite —hueco declarado
  y explícitamente apagado—; cualquier otro enlace sin ruta sigue levantando
  `ChassisContractError`.
- El valor se lee del entorno en **cada petición**: apagar un panel no exige
  reiniciar el proceso.

Plantilla de despliegue: `viewer/.env.example`.

## 2. Cómo monta un carril su funcionalidad

1. Sustituye el cuerpo del handler de su módulo `chassis_<feature>.py` (o
   reemplaza el módulo entero, conservando `router`).
2. Mantiene prefijo, nombre de ruta, rol y plantilla. Cambiarlos exige cambiar
   también `FEATURE_SLOTS`, la tabla `CONTRATO_PUBLICADO` de la suite y este
   documento; los tests lo obligan.
2 bis. Enciende su panel con `S9K_PANEL_<KEY>_ENABLED=true` cuando esté listo
   para que alguien lo vea. Mientras tanto queda montado y apagado (404).
3. Pasa a la plantilla, como mínimo, las claves de `SLOT_CONTEXT_KEYS`:
   `auth_user`, `slot`, `items`, `error`. **`auth_user` no es negociable**:
   `base.html` pinta la barra superior con ese nombre exacto.
4. No toca `base.html` ni `main.py`: el montaje y el menú se derivan del
   contrato.

## 3. Las tres reglas y su mecanismo

| Regla | Mecanismo | Prueba |
| --- | --- | --- |
| Un router declarado y no montado es detectable | El montaje se **deriva** de `FEATURE_SLOTS`; un módulo que no importa o no exporta `router` aborta el arranque con `ChassisContractError` | `test_every_declared_slot_is_actually_mounted`, `test_mounted_slot_path_matches_declared_prefix` |
| Un enlace de menú a una ruta inexistente rompe | El menú resuelve **nombres** contra las rutas realmente montadas y levanta `ChassisContractError` si falta una; no se autocensura | `test_every_nav_item_resolves_to_a_mounted_route`, `test_nav_raises_loudly_when_a_route_is_missing`, `test_base_html_has_no_hardcoded_nav_links` |
| Toda ruta montada pasa por autorización; sin contexto se deniega | Barrido de **todas** las rutas montadas con auth activada y sin sesión: ninguna puede devolver 200. La excepción es una lista **blanca** (`/login`, `/logout`, `/static`, `/favicon.ico`) | `test_no_mounted_route_serves_200_to_anonymous`, `test_slot_denies_anonymous`, `test_slot_denies_insufficient_role` |
| Estados vacío y de error explícitos | `_slot.html` evalúa `error` → `empty` → `ready`; el caso sin datos es el camino por defecto, no el olvidado | `test_slot_renders_empty_state_instead_of_exploding`, `test_slot_template_has_an_error_state` |

### Nota técnica: por qué el chasis aplana el censo él mismo

Con FastAPI 0.139 las rutas incluidas no cuelgan de `app.routes`: se insertan
envoltorios `_IncludedRouter` cuyas rutas efectivas hay que pedir con
`effective_candidates()`. Medido: `len(app.routes)` = **27** frente a **68**
rutas reales. Sin aplanar, una ruta puede esconderse de cualquier barrido que
recorra sólo el primer nivel, y el barrido de autorización es uno de ellos —la
ablación lo demuestra: sin aplanar se cuela una ruta sin guarda—.

**Corrección de una afirmación anterior.** Este documento y el docstring de
`_walk` decían que `app.url_path_for` no encuentra las rutas de un router
incluido. **Es falso**, y se ha medido en FastAPI 0.139.0 / Starlette 1.3.1:

```
app.url_path_for("chassis_review") -> /panel/review/
app.url_path_for("entities_page")  -> /entities
```

El índice propio se conserva por dos razones que sí se sostienen: (1) es el
**mismo** censo aplanado que usa el barrido de autorización, así que una ruta no
puede aparecer en un censo y faltar en el otro —resolver la navegación con
Starlette y auditar con `_walk` serían dos censos capaces de discrepar—; y (2)
`url_path_for` devuelve la variante con barra final (`/panel/review/`) mientras
que el canónico para un enlace de menú es el otro.

### Nota técnica: los dos puntos ciegos que tenía el censo

Aplanar no bastaba. `iter_mounted_routes` lo usan **tres** consumidores a la vez
—el barrido de autorización de arriba, `route_index` y el gate de solo lectura
del hueco C—, así que un punto ciego del censo era un punto ciego de los tres.
Un revisor independiente midió dos, y los dos dejaban la suite en **48/48
VERDE**:

**R9 — el `path` de una sub-app montada es RELATIVO al punto de montaje.**
`_walk` sí descendía por los `Mount`, pero emitía el path tal cual. Medido:

```
app.mount("/panel/review/admin", subapp)   # subapp con POST /aprobar
POST /panel/review/admin/aprobar -> 200, y escribió en disco
en el censo esa ruta aparecía como: '/aprobar'
```

El censo la veía **con el nombre equivocado**, así que todo consumidor que
filtre por `path.startswith(prefijo)` la descartaba. Ahora `_walk` arrastra el
path de cada `Mount` y emite la **URL efectiva** (`MountedRoute`); el envoltorio
sólo se construye cuando hay prefijo que componer, de modo que una app sin
`Mount` produce exactamente el mismo censo que antes.

**R10 — ausencia de `methods` no es ausencia de escritura.**
`APIWebSocketRoute` **no tiene** atributo `methods` (verificado:
`hasattr(...) is False`), así que `getattr(r, "methods", set())` devolvía
`set()`, la intersección con los métodos de escritura salía vacía y un canal de
escritura perfectamente capaz quedaba invisible **en silencio**. Lo mismo vale
para un `Mount` opaco (`StaticFiles`), cuya app ASGI el censo no puede enumerar.

El chasis expone ahora `enumerable_methods` (devuelve `None` cuando no se puede
saber, distinto de "cero métodos") y `write_methods`, que **falla CERRADO**:
sin métodos enumerables devuelve `(METHODS_NOT_ENUMERABLE,)`, nunca la tupla
vacía. Es la misma doctrina que `slot_enabled` y el tope tri-estado — la
ausencia de dato no se interpreta como el valor benigno. El barrido de
autorización aplica el mismo criterio: una ruta que no puede sondear se declara
y revienta, y eximirla exige meterla a mano en `ANON_ALLOWED_PATHS`.

¿Es lícito un `Mount` de estáticos bajo el prefijo de un hueco? **No.** El censo
no puede *demostrar* que una app ASGI montada sea de solo lectura; que
`StaticFiles` hoy sirva sólo GET/HEAD es una propiedad de la clase que el censo
no ve y que un cambio de clase invalidaría sin ruido. Se falla cerrado.

Necesidad medida por **ablación** (reversión byte a byte verificada por sha256):
quitar la composición de prefijo deja colarse R9 y R11 (`Mount` anidado a dos
niveles); quitar el fallo cerrado por métodos deja colarse R10, R13 (`Mount` de
estáticos) y R14 (WebSocket ante el barrido de autorización). Ninguno de los dos
criterios es redundante. En cambio `include_router` con prefijo dentro de otro
router (R13→R12) **nunca fue** un punto ciego: FastAPI resuelve esos prefijos
dentro del `path` de cada `APIRoute`; se conserva como control negativo.

Sobre la app real, el censo corregido mide **exactamente las mismas cifras** que
antes (69 rutas aplanadas, 62 nombres en `route_index`, 3 rutas bajo
`/panel/review`): hoy el único `Mount` del visor es `/static`, en el primer nivel
y ya en la lista blanca. El arreglo no destapa hallazgos nuevos en producción;
cierra el hueco por el que B, F y G iban a copiar el patrón.

## 4. Regla de las pruebas

Todo lo que sea HTTP se prueba contra `app.main.app`, la aplicación **real**.
Nunca contra un `FastAPI()` construido dentro del test. Una app privada comparte
el código de los routers pero no el montaje, y el montaje es exactamente lo que
aquí se afirma. Ese atajo ya escondió un defecto real: un handler pasaba `admin`
a la plantilla mientras `base.html` leía `auth_user`, la barra superior salía
vacía y ningún test se enteró porque ninguno pintaba la plantilla real.
`test_slot_renders_topbar_identity` reproduce ese caso y lo caza.

## 5. Calibración

Cada mecanismo se validó introduciendo la violación, comprobando el rojo,
revirtiendo y comprobando el verde. Salidas reales sobre
`viewer/tests/test_chassis_mount_contract.py`:

| # | Violación introducida | Resultado | Prueba que se puso roja (primera) |
| --- | --- | --- | --- |
| 1 | `_mount_feature_slots`: `FEATURE_SLOTS[1:]` (hueco C sin montar) | 26 failed, 14 passed | `test_every_declared_slot_is_actually_mounted` — «Huecos declarados en FEATURE_SLOTS pero sin ruta montada: ['C']» |
| 2 | `NAV`: «Grafo» → `graph_view_renombrado` | 22 failed, 18 passed | `test_every_nav_item_resolves_to_a_mounted_route` — «Enlaces de navegación sin ruta montada: ['Grafo']» |
| 3 | `chassis_slot`: handler sin `Depends(html_role_guard(...))` | 12 failed, 28 passed | `test_no_mounted_route_serves_200_to_anonymous` — «Rutas que sirven 200 a un anónimo: ['GET /panel/review/', …]» |
| 4 | `slot_context`: `auth_user` → `admin` | 8 failed, 32 passed | `test_slot_renders_topbar_identity[C]` — «el nombre del usuario no aparece; la plantilla no recibió `auth_user`» |
| 5 | `_slot.html`: `{{ items[0].nombre }}` incondicional | 8 failed | `test_slot_allows_declared_role[C]` — 500; `jinja2.UndefinedError: list object has no element 0` |

### 5 bis. Segunda ronda: lo que la primera NO medía

Un revisor independiente encontró que la suite anterior pasaba **en verde** con
el rol y el prefijo del contrato cambiados, y que los interruptores por hueco
sencillamente no existían. Mutaciones y resultado **después** del arreglo (suite
completa: **67 passed, 1 skipped**):

| # | Mutación | Antes | Ahora | Prueba que se pone roja |
| --- | --- | --- | --- | --- |
| 6 | rol de B: `admin` → `viewer` | 40 passed, 2 skipped (**verde**) | **2 failed** | `test_feature_slots_match_the_published_contract`; `test_published_role_is_the_minimum_not_a_wider_one[B]` — «el contrato publica 'admin' como mínimo, pero 'reviewer' entra» |
| 7 | rol de G: `viewer` → `admin` | 42 passed (**verde**) | **3 failed** | `test_published_prefix_and_role_are_served_as_such[G]` — «el rol publicado 'viewer' recibe 403 en /panel/entities» |
| 8 | prefijo de C: `/panel/review` → `/panel/revision` | 41 passed, 1 skipped (**verde**) | **3 failed** | `test_published_prefix_and_role_are_served_as_such[C]` — «el contrato publica '/panel/review' para 'chassis_review'» |
| 9 | rol de F: `reviewer` → `viewer` | — | **2 failed** | `test_published_role_is_the_minimum_not_a_wider_one[F]` |
| 10 | prefijo de B: `/panel/operations` → `/panel/ops` | — | **3 failed** | `test_published_prefix_and_role_are_served_as_such[B]` |
| 11 | nombre de ruta de C: `chassis_review` → `chassis_revision` | — | **2 failed** | `test_feature_slots_match_the_published_contract` |
| 12 | `slot_enabled`: flag ausente → encendido | — | **5 failed** | `test_slot_is_off_when_flag_is_absent[C/B/F/G]`, `test_disabled_slot_is_not_linked_in_the_nav` |
| 13 | `slot_enabled`: cualquier valor no vacío enciende | — | **5 failed** | `test_slot_is_off_when_flag_is_garbage[quizas/false/TRUE-ish/0/yes]` |
| 14 | handler sin comprobar el interruptor | — | **10 failed** | las nueve anteriores + `[]` (valor vacío) |
| 15 | hueco `admin` con `html_role_guard` (la guarda débil) | — | **1 failed** | `test_admin_slot_denies_anonymous_with_auth_disabled` — «con auth desactivada responde 200 a un anónimo; sus pares responden [302, 302]» |

**El superviviente, ya sin serlo.** Mover la comprobación del interruptor por
delante de la guarda no ponía nada rojo, y esta nota decía que "no es un
defecto". La afirmación era correcta en lo importante —con el panel apagado
nadie lo recibe— pero **no estaba medida**, y le faltaba la cifra: bajo esa
mutación, con C encendido y B/F/G apagados, un anónimo obtiene

```
/panel/review 302 · /panel/operations 404 · /panel/sources 404 · /panel/entities 404
```

es decir, **enumera qué paneles están encendidos** sin identificarse. Con el
orden actual los cuatro responden `302`, variante con barra final incluida.

Ya no es prosa: `test_disabled_slots_are_not_enumerable_by_an_anonymous` afirma
que un anónimo recibe el **mismo** estado para un panel encendido y uno apagado
—indistinguibilidad, no un código escrito a mano— y la mutación del orden pone
esa prueba en **ROJO** (mutación 16). Un carril futuro que reordene esas dos
líneas se entera.

| # | Mutación | Resultado | Prueba que se pone roja |
| --- | --- | --- | --- |
| 16 | interruptor comprobado ANTES de la guarda | **1 failed** (antes de esta prueba: verde) | `test_disabled_slots_are_not_enumerable_by_an_anonymous` — «Un anónimo distingue paneles encendidos de apagados y puede enumerarlos: {C: 302, B: 404, F: 404, G: 404}» |
| 17 | el 404 vuelve a nombrar `S9K_PANEL_<KEY>_ENABLED` | **4 failed** | `test_slot_is_off_when_flag_is_absent[C/B/F/G]` |

Tras revertir cada una de las cinco primeras: **41 passed, 1 skipped** (el skip es
`test_slot_denies_insufficient_role[G]`: `viewer` es el rol más bajo, no existe
uno inferior con el que probar la denegación).

## 6. Lo que este chasis NO hace

- **No implementa C, B, F ni G.** Los cuatro huecos sirven una pantalla vacía.
- **No define autorización.** Reutiliza roles y guardas existentes. No introduce
  vocabulario paralelo: nada de `scope`, `visibility`, `known_by` ni contratos
  de visibilidad, que son de otros carriles.
- **No toca la política de visibilidad de contenido** (`app/policies`,
  `app/authz`, `neo4j_provider`). Un hueco que necesite filtrar material del
  grafo usará `get_filtered_provider`, como el resto del visor.
- **No cubre WebSockets ni rutas montadas fuera de FastAPI.** El barrido
  enumera rutas HTTP con métodos GET/POST.
- **No comprueba el rol correcto de las rutas preexistentes**, sólo que ninguna
  sirve 200 a un anónimo. Afinar rol por rol en todo el visor es trabajo del
  carril de auditoría de rutas (K).
- **No oculta los ocho `paths` `/panel/*` de `openapi.json`.** Un panel apagado
  sigue apareciendo en el esquema, porque el hueco sigue montado y el esquema se
  construye del montaje, no del entorno. Decisión consciente y no un descuido:
  (1) con auth activada, `/openapi.json` devuelve 404 salvo
  `S9K_AUTH_EXPOSE_DOCS=true`, y aun entonces sólo lo ve un `admin` (con auth
  desactivada el visor entero es público, que es otro asunto); (2) los cuatro
  prefijos ya son públicos en
  este mismo documento; y (3) esconderlos del esquema en función del entorno
  reintroduciría exactamente el problema del chasis —un censo que no coincide
  con el montaje—. Lo que sí está medido es que apagado ⇒ **404**, y que un
  anónimo no distingue encendido de apagado.
- **El cuerpo del 404 no nombra la variable de entorno del hueco.** No es un
  secreto (está aquí y en `.env.example`), pero una respuesta de error no es el
  sitio donde publicarlo; lo afirma `test_slot_is_off_when_flag_is_absent`.
- **No despliega nada.** Sin cambios en producción, VM105, Neo4j ni backups.

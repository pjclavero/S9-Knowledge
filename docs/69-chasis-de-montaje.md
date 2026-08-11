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
| `viewer/tests/test_chassis_mount_contract.py` | Las pruebas del contrato, contra la app real |

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
(`admin > reviewer > viewer`) y la decisión la ejecuta
`app.routers.readonly.html_role_guard`, que ya existía. **El chasis no define
ningún concepto de permiso nuevo**; el filtrado del menú delega en los métodos
del propio `User` (`can_access_admin`, `can_see_reviews`).

## 2. Cómo monta un carril su funcionalidad

1. Sustituye el cuerpo del handler de su módulo `chassis_<feature>.py` (o
   reemplaza el módulo entero, conservando `router`).
2. Mantiene prefijo, nombre de ruta, rol y plantilla. Cambiarlos exige cambiar
   también `FEATURE_SLOTS`, y el test lo obliga.
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

### Nota técnica: `app.url_path_for` no sirve aquí

Con FastAPI 0.139 las rutas incluidas no cuelgan de `app.routes`: se insertan
envoltorios `_IncludedRouter` cuyas rutas efectivas hay que pedir con
`effective_candidates()`. Consecuencia comprobada en este repo:
`app.url_path_for("entities_page")` levanta `NoMatchFound` aunque `/entities`
esté montado y sirviendo. Por eso el chasis enumera las rutas él mismo
(`iter_mounted_routes`) y resuelve contra su propio índice. Esa misma
enumeración es la que usa el barrido de autorización, así que una ruta que se
esconda de una se esconde de la otra: no hay dos censos que puedan discrepar.

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

Tras revertir cada una: **41 passed, 1 skipped** (el skip es
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
- **No despliega nada.** Sin cambios en producción, VM105, Neo4j ni backups.

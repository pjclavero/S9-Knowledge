# Mapa de rutas v2 — contrato mecánico de las rutas del visor

Repo: `S9-Knowledge` · rama `audit/route-contract-map-v2` · base auditada `cb874fe`
(carril L ya dentro de main). Reconstruido entero, no parcheado.

## 1. Qué arregla respecto al mapa anterior

El instrumento anterior **contaba menciones como cobertura**: que el nombre de una
ruta apareciera en un fichero se tomaba por prueba de que estaba montada, enlazada,
probada o autorizada. Ninguna de esas cuatro cosas se deduce de un `grep`.

Aquí cada propiedad tiene su propio mecanismo y su propia evidencia:

| propiedad | de dónde sale la evidencia | qué NO es |
|---|---|---|
| `defined` | AST de los decoradores `@router.<método>("...")` bajo `viewer/app/` | mención en un comentario |
| `mounted` | censo de rutas efectivas de la app **REAL** `app.main.app` | aparecer en `app.routes` |
| `linked` | BFS: navegación → ruta → plantilla que renderiza → sus enlaces y el JS que carga | que la cadena aparezca en algún HTML |
| `tested` | una petición atravesó el objeto `Route` de la app real durante `pytest` | que el nombre salga en un test |
| `authorized` | barrido HTTP real con auth activada: anónimo + un usuario por rol | que exista un `Depends` con nombre convincente |
| `consumed` | enlaces de plantillas/JS resueltos contra el enrutador + peticiones de tests | aparición del literal en cualquier fichero |

### El censo de rutas es el punto crítico

Con FastAPI 0.139 las rutas incluidas con `include_router` **no cuelgan de
`app.routes`**: quedan envueltas en objetos `_IncludedRouter` que resuelven sus
rutas efectivas en tiempo de petición. Medido en esta base:

- `app.routes` (enumeración ingenua): **11** rutas.
- censo efectivo (`iter_effective_routes`): **59** rutas.

Es decir, un auditor que use la API de Starlette declararía **48 rutas vivas como
muertas**. Es el mismo género de error que se venía a corregir, con el signo
cambiado. El censo efectivo recorre `effective_route_contexts()` y
`effective_low_priority_routes()`, y de cada contexto toma el path final, el
`dependant` ya combinado con las dependencias del `include_router`, y el objeto
`Route` ORIGINAL, que es el que FastAPI invoca realmente.

**Un único censo alimenta las tres medidas dinámicas** (montaje, sonda de
autorización y sonda de tests), de modo que no puede haber dos censos que
discrepen.

Nota medida, no supuesta: en esta base `app.url_path_for("entities_page")` **sí**
funciona (queda registrado en la calibración, caso M7). El problema real es la
enumeración, no `url_path_for`.

## 2. Cómo se ejecuta (reejecutable contra cualquier rama)

Todo se deriva de `--repo`, así que el mapa se puede recalcular contra otro árbol
—otra rama, otro worktree, un árbol mutado— sin tocar el repo:

```bash
# 1) evidencia de "probada": sonda sobre la app real durante la corrida
PYTHONPATH=scripts S9K_ROUTE_PROBE_OUT=/tmp/tested_routes.json \
  python3 -m pytest viewer/tests tests/integration tests/e2e \
  -p route_map.pytest_route_probe -q

# 2) mapa (incluye el barrido de autorización en un subproceso con auth ON)
python3 scripts/route_map/route_map.py --repo . \
  --tested /tmp/tested_routes.json \
  --out artifacts/route-map/route_map.json \
  --md  artifacts/route-map/route_map.md

# 3) calibración: inyecta defectos y exige que el mapa los vea
python3 scripts/route_map/calibrate.py --base . \
  --tested /tmp/tested_routes.json --out artifacts/route-map/calibracion.json
```

La sonda de autorización arranca la app en un **subproceso** con
`S9K_AUTH_ENABLED=true`, provider `mock` y una auth DB **efímera** en un
temporal; crea un usuario por rol y emite una sesión nueva por petición (el
barrido incluye rutas que revocan sesiones: una sesión reutilizada produciría
denegaciones falsas). No toca producción, ni Neo4j, ni la auth DB del repo.

## 3. Resultado sobre `cb874fe`

| medida | valor |
|---|---|
| rutas definidas (AST) | 59 |
| rutas montadas en la app real | 59 |
| alcanzables desde la navegación | 31 |
| ejercitadas de verdad por los tests | 47 |
| deniegan a un anónimo con auth ON | 57 (+2 públicas por diseño: `GET/POST /login`) |
| consumidas por alguien | 56 |

**Hallazgos duros: 0 rutas MUERTAS, 0 enlaces ROTOS, 0 rutas SIN AUTH.**
Ninguna ruta sirve 2xx a un anónimo salvo el formulario de login.

El detalle ruta por ruta —incluido el **rol mínimo medido** de cada una— está en
`artifacts/route-map/route_map.md` y `route_map.json`.

### 3.1 Rol por ruta (medido, no declarado)

El barrido repite cada ruta como `viewer`, `reviewer` y `admin`, y toma el rol
mínimo que obtiene respuesta servida. Resumen:

- **admin**: todo `/admin/**` y `/api/admin/health` (`viewer` y `reviewer` → 403).
- **reviewer**: `/sources*`, `/quality`, `/api/sources*`, `/api/quality`,
  `/reviews*`, `/review-console*`, `/v3/review*` (`viewer` → 403).
- **viewer**: `/`, `/graph`, `/status`, `/entities*`, `/entity/{id}`, `/jobs*`,
  `/account*` y las APIs de lectura general (`/api/status`, `/api/graph`,
  `/api/entities*`, `/api/search`, `/api/jobs*`, `/api/workspaces`,
  `/api/entity-types`) — 21 rutas.
- **nadie**: `/docs`, `/redoc`, `/openapi.json` (404 para todos mientras
  `S9K_AUTH_EXPOSE_DOCS=false`).

En los `POST` el veredicto de rol se declara **no concluyente**: la protección
CSRF responde antes que el control de rol, así que un 403 no distingue «rol
insuficiente» de «falta el token CSRF». Se prefiere decir que no se sabe a
inventarlo. Lo que sí queda medido en `POST` es que ningún rol —ni el anónimo—
obtiene 2xx.

### 3.2 Deudas señaladas (no son agujeros, pero conviene verlas)

- **12 rutas montadas y nunca ejercitadas** contra la app real: `GET /account`,
  `GET /admin/health`, `GET|POST /admin/users/new`, `GET|POST /admin/users/{user_id}`,
  `POST /admin/users/{user_id}/unlock`, `POST /admin/users/{user_id}/revoke-sessions`,
  `GET /review-console/`, `GET /v3/review/`, `GET /v3/review/glossary-candidates`,
  `POST /v3/review/undo`. La gestión de usuarios del panel admin es el hueco más
  visible: se prueba por otras vías, pero no atravesando sus rutas.
- **28 rutas no alcanzables desde la navegación**: casi todas son APIs JSON
  consumidas por fetch (legítimo), pero hay HTML sin ningún enlace que lleve a
  él: `GET /admin/health`, `GET /quality`, `GET /review-console`,
  `GET /review-console/source/{source_id}` y `GET /v3/review/glossary-candidates`.
  Existen, están protegidas y funcionan: simplemente no hay forma de llegar
  navegando. Material directo para el carril chasis.
- **`POST /logout` es la única ruta sin guardián estático detectable**; el
  barrido confirma que deniega igualmente (302 a `/login`), pero su protección no
  es declarativa.
- **Pares con y sin barra final** (`/review-console` y `/review-console/`,
  `/v3/review` y `/v3/review/`) son rutas distintas del censo con cobertura
  distinta: una está probada y la otra no.

### 3.3 Fragilidad estructural del patrón `Depends(html_guard)`

`html_guard` y `html_role_guard` **no deniegan por sí solos**: devuelven un
`RedirectResponse` que el handler tiene que devolver (`if isinstance(user,
RedirectResponse): return user`). Una ruta que declare la dependencia y olvide la
comprobación **sirve 200 a un anónimo aunque parezca protegida**. En `cb874fe`
todas las rutas que lo usan sí lo comprueban (0 hallazgos), pero el mapa incluye
un detector específico (`guardian_declarado_pero_no_aplicado`) calibrado con una
ruta que comete exactamente ese olvido — véase M4.

## 4. Calibración: el instrumento se ha visto rojo

«Una afirmación no constituye evidencia porque exista un test verde». Cada
defecto se inyecta en una **copia desechable** del árbol (nunca en el repo), se
recalcula el mapa, se comprueba que el hallazgo aparece, y se borra la copia; el
caso 0 sin mutar y la reejecución final sobre el árbol limpio deben dar
exactamente lo mismo.

| caso | defecto inyectado | salida real del mapa | ¿lo ve? |
|---|---|---|---|
| M0 | ninguno (control) | 0 hallazgos nuevos, `montadas` +0 | sí |
| M1 | `app.include_router(readonly_router.router)` comentado | `montadas` **−10** y 10 rutas MUERTAS nuevas (`GET /entities`, `/sources`, `/quality`, `/api/entities*`, `/api/sources*`…) + 11 enlaces ROTOS derivados | sí |
| M2 | `<a href="/ruta-que-no-existe">` en `base.html` | enlace ROTO nuevo: `/ruta-que-no-existe @ base.html` | sí |
| M3 | se quita `Depends(html_guard)` de `GET /entities` | SIN-AUTH nueva: `GET /entities` (200 anónimo) | sí |
| M4 | ruta nueva sin ningún test, con guardián declarado y no aplicado | NO PROBADA + SIN-AUTH + `guardian_declarado_pero_no_aplicado`: `GET /ruta-nueva-sin-test` | sí |
| M5 | `/ruta-solo-mencionada` citada en un comentario | **0 rutas nuevas**: la mención no crea ni cubre nada | sí |
| M6 | un test ejercita el router en una app `FastAPI()` **privada** | la sonda no registra `GET /entities`: no cuenta como cobertura | sí |
| M7 | censo: `app.routes` frente al censo efectivo | 11 vs **59**; 0 rutas que sirvieron y falten en el censo | sí |
| M8 | `GET /admin/audit` degradada de `require_admin` a autenticado | rol mínimo medido cambia **admin → viewer** | sí |

`reversion_identica: true` — tras las nueve mutaciones, el árbol limpio devuelve
el mismo mapa. Salida completa en `artifacts/route-map/calibracion.json`.

M1 y M3 son además la calibración pedida del enumerador: una ruta desmontada
desaparece del censo (y sale como muerta), y una ruta que sirve 200 aparece
montada. M6 cierra el error concreto que ya se cometió aquí: medir cobertura
contra una app privada de test.

## 5. Qué NO se cubrió (declarado, no disimulado)

- **`consumed` es el eslabón más débil.** Se resuelve por enlaces de plantillas y
  literales de URL en JS, con comentarios eliminados antes de mirar. No sigue
  URLs construidas dinámicamente más allá del caso `"/prefijo/" + variable`, ni
  consumidores externos al repo (nginx, otro servicio, un cliente humano). Una
  ruta marcada `consumed: false` puede tener consumidores reales fuera de vista.
- **Rol en `POST`: no medido**, por lo dicho en 3.1 (CSRF responde antes).
- **Nada de esto se probó contra producción ni contra Neo4j**: provider `mock`,
  auth DB efímera, sin red. El mapa describe el código, no el despliegue: no
  cubre reglas de nginx, redirecciones del proxy ni rutas servidas fuera de la
  app.
- **No se auditó la autorización de DATOS** (filtrado por visibilidad/partida:
  `get_filtered_provider`, `VisibilityScope`). El mapa distingue esas
  dependencias de las de control de acceso y las registra aparte, pero no evalúa
  si filtran bien: eso es de los carriles de authz/policies, que además están
  fuera de mi frontera.
- **Los `{param}` se sondean con un identificador inexistente**, así que en esas
  rutas se mide el control de acceso, no el comportamiento con datos reales.
- **La ejecución de tests no fija la lista de tests**: `tested` refleja la
  corrida concreta que se le pasa (`viewer/tests`, `tests/integration`,
  `tests/e2e`: 1054 pasados, 190 saltados). Con otro subconjunto, otra cobertura.
  190 tests saltados pueden ocultar cobertura real.
- **Sobre el chasis (PR #166) ya está ejecutado**: ver §5.bis. Lo que ahí NO se
  cubre: los huecos están vacíos (una pantalla sin funcionalidad), así que se
  verifica el montaje, no lo que cada carril meta dentro después; y el veredicto
  vale para `4b2ae5a`, no para lo que se le añada luego sin volver a medir.
- **Este mapa no se revisa a sí mismo**: la calibración demuestra que el
  instrumento se pone rojo ante nueve defectos concretos; no demuestra que no
  existan géneros de defecto que ninguno de los nueve representa.

## 5.bis Verificación del chasis (PR #166, `feat/chasis-montaje-v1` @ `4b2ae5a`)

Es el paso para el que existe este mapa: **C/B/F/G no se montan hasta que se
verifique que el chasis no deja routers muertos, enlaces rotos ni rutas sin
auth**. Veredicto: **APTO**.

### Ajuste necesario del instrumento: la navegación pasó a ser DATOS

Con el chasis, `base.html` ya no lleva enlaces escritos a mano: recorre
`chassis_nav`, que resuelve **nombres** de ruta contra lo montado. Un mapa que
sólo leyera `href="..."` literales habría visto una navegación vacía y declarado
huérfano el visor entero — un falso positivo masivo. El mapa resuelve ahora
también el contrato (`app.chassis.nav_for` con un usuario de permisos máximos), y
un `ChassisContractError` **no se traga**: se reporta como enlace ROTO. Añadido
el caso de calibración **M9** para ese camino.

### Resultado sobre `4b2ae5a`

| medida | `cb874fe` | `4b2ae5a` |
|---|---|---|
| definidas / montadas | 59 / 59 | 61 / 67 |
| enlazadas | 31 | 35 |
| probadas | 47 | **67 (todas)** |
| deniegan al anónimo | 57 | 65 (+2 públicas) |

**0 rutas muertas · 0 enlaces rotos · 0 rutas sin auth · 0 rutas no probadas.**
Ninguna ruta preexistente perdió cobertura, enlace, rol ni denegación.

Los cuatro huecos, medidos uno a uno:

| hueco | montada | enlazada | probada | anónimo | rol contrato | **rol medido** |
|---|:-:|:-:|:-:|---|---|---|
| `GET /panel/review` | sí | sí | sí (7) | 302 → `/login` | reviewer | **reviewer** |
| `GET /panel/operations` | sí | sí | sí (7) | 302 → `/login` | admin | **admin** |
| `GET /panel/sources` | sí | sí | sí (7) | 302 → `/login` | reviewer | **reviewer** |
| `GET /panel/entities` | sí | sí | sí (6) | 302 → `/login` | viewer | **viewer** |

Contrato y medida **coinciden en los cuatro**; `viewer` recibe 403 en review,
sources y operations, y `reviewer` recibe 403 en operations. Ninguno cae en la
trampa del `RedirectResponse`: los cuatro devuelven la salida de
`html_role_guard` (`guardian_declarado_pero_no_aplicado: 0`), y el barrido
anónimo lo confirma en vez de fiarse del código.

### Censo cruzado: dos enumeradores independientes

`iter_effective_routes` (K) y `iter_mounted_routes` (chasis) se contrastaron
contra la verdad de campo (rutas que sirvieron respuesta en la corrida):

- 67 rutas en el censo de K, 68 en el del chasis. **Ninguna ruta sólo en K.**
- Única diferencia: el chasis cuenta el `Mount /static` como una ruta más; K lo
  clasifica aparte como montaje. No es una mentira de nadie: es una diferencia de
  clasificación. Consecuencia práctica nula, con un matiz: `route_index` del
  chasis indexa el nombre `static`, así que un `NavItem` que apuntara a `"static"`
  resolvería a `/static` en vez de reventar. Hoy ninguno lo hace.
- **0 rutas que sirvieron y falten en cualquiera de los dos censos.**

### Deuda menor, no bloqueante

Cada hueco monta dos rutas (`/panel/review` y `/panel/review/`). La variante con
barra está montada, probada y autorizada, pero **no enlazada** (`route_index`
prefiere el path corto). Duplica el censo (8 rutas por 4 pantallas) sin aportar
nada. Es cosmético; conviene decidirlo antes de que cuatro carriles lo copien.

### Las 5 pantallas huérfanas: el chasis las IGNORA

`NAV` no incluye ninguna de las cinco que señalé en 3.2. Tras el chasis siguen sin
un solo enlace que lleve a ellas: `GET /admin/health`, `GET /quality`,
`GET /review-console`, `GET /review-console/source/{source_id}` y
`GET /v3/review/glossary-candidates`. No las duplica ni las rompe: simplemente no
las adopta. Como `NAV` es ahora la fuente única de navegación, incorporarlas es
añadir una línea por pantalla — y mientras no se haga, existen y están protegidas,
pero son inalcanzables navegando.

### Calibración sobre la propia rama del chasis

Los diez casos se reejecutaron **contra `4b2ae5a`**, no sólo contra la base:
**10/10 detectados, `reversion_identica: true`**. Incluye M9 (menú de datos que
apunta a una ruta no montada → ROTO, con el `ChassisContractError` textual) y M7
(censo: 11 vs 67, sin rutas servidas fuera del censo). Un instrumento que juzga
una rama debe haberse visto rojo **en esa rama**.

## 6. Aviso de captura, para el que venga detrás

Una ruta puede quedar **capturada** por otra sin que nada falle: `/sources/panel`
lo absorbería `/sources/{source_id}`, que respondería 404 «fuente no encontrada»
en vez de avisar de la colisión. El censo de este mapa lista las rutas efectivas
en el orden en que el enrutador las resuelve, y las sondas piden URLs concretas,
así que una ruta capturada se manifiesta como ruta cuyo handler nunca es el que
uno cree. Es la razón por la que el chasis eligió el prefijo `/panel/…`.

## 7. Ficheros

- `scripts/route_map/route_map.py` — censo, mapa, sondas e informe.
- `scripts/route_map/pytest_route_probe.py` — plugin de pytest: registra las
  peticiones que atraviesan la app real.
- `scripts/route_map/calibrate.py` — inyección de defectos y tabla de calibración.
- `artifacts/route-map/route_map.{json,md}` — mapa de `cb874fe`.
- `artifacts/route-map/calibracion.json` — salidas reales de la calibración.
- `artifacts/route-map/chasis-4b2ae5a/route_map.{json,md}` — mapa del chasis.
- `artifacts/route-map/chasis-4b2ae5a/calibracion.json` — calibración sobre la
  rama del chasis (10/10).

# 61 · Mapa de contratos ruta/UI del visor (Carril K)

Rama: `audit/viewer-route-contract-map` · base `origin/main` 28320bd.

Este carril no cambia comportamiento del visor: **audita, mide y pone una
puerta**. El objetivo es que el visor no se convierta en un conjunto de páginas
cuyos contratos divergen sin que nadie lo vea, justo antes de integrar los
carriles C (consola de revisión v2) y B (centro de estado admin).

## Qué es el mapa

- `viewer/tests/route_contract/inventory.py` — introspección de la aplicación
  FastAPI **real**: rutas registradas (incluidos routers montados), plantillas,
  herencias, enlaces de plantillas y del JS del visor, y cobertura declarada.
- `viewer/tests/route_contract/route_contract_map.json` — el mapa **declarado**
  (lo único escrito a mano): rol, entrega, fuente de datos, estados, errores,
  navegación entrante/saliente, consumidores JS y pruebas por ruta.
- `viewer/tests/test_route_contract_map.py` — **la puerta**. Compara mapa y
  realidad y falla ante ruta sin declarar, ruta sin cobertura, plantilla
  huérfana, enlace roto o ficha incompleta.
- `viewer/tests/route_contract/_generate.py` — borrador de fichas para rutas
  nuevas (no se ejecuta en la suite).

Un documento envejece; esta puerta no. El inventario en tabla de abajo es una
foto legible del JSON, y el JSON es lo que la suite verifica.

## Inventario (59 rutas + `/static` montado)

| Ruta | Rol | Entrega | Datos | Estados | Errores | #Tests | Nav. entrante | Notas |
|---|---|---|---|---|---|---|---|---|
| `GET /` | viewer+ (302 /login si anónimo) | index.html | provider.name + settings | ok | 302 login | 11 | sí |  |
| `GET /account` | autenticado | auth/account.html | request.state.user | ok | 302 login | 1 | sí |  |
| `GET /account/change-password` | autenticado | auth/change_password.html | request.state.user | ok | 302 login | 1 | sí |  |
| `POST /account/change-password` | autenticado | auth/change_password.html / 302 | auth DB | ok 302; errores de validación (400) | 400; 403 CSRF | 1 | sí |  |
| `GET /admin/audit` | admin | auth/admin/audit.html | auth DB (audit log) + filtros | ok; sin resultados | 302 login; 403 | 2 | sí | sólo enlazado desde /admin/users, no desde base.html |
| `GET /admin/health` | admin | auth/admin/health.html | app.health | ok; sin informes | 302 login; 403 | 1 | — | SIN ENLACE ENTRANTE: no aparece en base.html ni en admin/users.html |
| `GET /admin/partidas` | admin | auth/admin/partidas.html | auth DB (concesiones) | ok | 302 login; 403 | 3 | sí |  |
| `POST /admin/partidas/grant` | admin | 302 /admin/partidas | auth DB | ok; error de validación | 403 CSRF | 2 | sí |  |
| `POST /admin/partidas/{access_id}/revoke` | admin | 302 /admin/partidas | auth DB | ok | 403 CSRF; 404 | 1 | sí |  |
| `GET /admin/users` | admin | auth/admin/users.html | auth DB | ok | 302 login; 403 | 5 | sí |  |
| `GET /admin/users/new` | admin | auth/admin/user_detail.html (mode=new) | auth DB | formulario | 302 login; 403 | 1 | sí |  |
| `POST /admin/users/new` | admin | auth/admin/user_detail.html (error) / 302 | auth DB | ok 302; errores | 400; 403 CSRF | 1 | sí |  |
| `GET /admin/users/{user_id}` | admin | auth/admin/user_detail.html | auth DB | ok | 404; 403 | 2 | sí |  |
| `POST /admin/users/{user_id}` | admin | auth/admin/user_detail.html / 302 | auth DB | ok 302; errores | 404; 403 CSRF | 2 | sí |  |
| `POST /admin/users/{user_id}/revoke-sessions` | admin | 302 /admin/users/{id} | auth DB | ok | 403 CSRF; 404 | 0 | sí |  |
| `POST /admin/users/{user_id}/unlock` | admin | 302 /admin/users/{id} | auth DB | ok | 403 CSRF; 404 | 0 | sí |  |
| `GET /api/admin/health` | admin (API) | application/json | app.health (últimos informes) | ok; sin informes | 401; 403 | 1 | — |  |
| `GET /api/entities` | viewer+ (API) | application/json | provider.list_entities | ok | 401; 422 parámetros | 9 | — |  |
| `GET /api/entities/{entity_id}` | viewer+ (API) | application/json | provider.entity | ok | 401; 404; 503 | 6 | — |  |
| `GET /api/entity-types` | viewer+ (API) | application/json | provider.entity_types | ok | 401 | 2 | sí |  |
| `GET /api/entity/{entity_id}` | viewer+ (API) | application/json | provider.entity | ok | 401; 404 | 1 | — | LEGADO: duplica /api/entities/{entity_id} |
| `GET /api/graph` | viewer+ (API) | application/json | provider.graph | ok | 401 | 6 | sí | consumido por static/js del grafo |
| `GET /api/jobs` | viewer+ (API) | application/json | jobs_client acotado por scope | ok; db_no_disponible | 401; 503 | 4 | — |  |
| `GET /api/jobs/counts` | viewer+ (API) | application/json | jobs_client.scoped_counts | ok | 401 | 3 | — |  |
| `GET /api/jobs/{job_id}` | viewer+ (API) | application/json | jobs_client.scoped_job | ok | 401; 404 | 3 | — |  |
| `GET /api/quality` | reviewer+ (API) | application/json | provider.quality_metrics | ok | 401; 403; 503 | 3 | — |  |
| `GET /api/search` | viewer+ (API) | application/json | provider.search | ok | 401 | 3 | — |  |
| `GET /api/sources` | reviewer+ (API) | application/json | provider.list_sources | ok | 401; 403 | 2 | — |  |
| `GET /api/sources/{source_id}` | reviewer+ (API) | application/json | provider.source_detail | ok | 401; 403; 404; 503 | 1 | — |  |
| `GET /api/status` | viewer+ (API) | application/json | provider filtrado | ok | 401 | 6 | — |  |
| `GET /api/workspaces` | viewer+ (API) | application/json | provider.workspaces | ok | 401 | 2 | — |  |
| `GET /docs` | admin (404 si docs no expuestos) | swagger-ui (HTML de FastAPI) | /openapi.json | ok | 404; 401; 403 | 1 | — |  |
| `GET /entities` | viewer+ (302 /login) | entities.html | provider.list_entities + entity_types | ok; lista vacía; proveedor caído => lista vacía | 302 login | 12 | sí | enlaza al DETALLE LEGADO /entity/{id}, no a /entities/{id} |
| `GET /entities/{entity_id}` | viewer+ (302 /login) | entity_detail.html | provider.entity + relations_for_entity | ok | 404 error.html; 503 error.html | 7 | sí |  |
| `GET /entity/{entity_id}` | viewer+ (302 /login) | entity.html | provider.entity + relations_for_entity | ok | 404 JSON CRUDO (HTTPException) | 2 | sí | LEGADO: duplica /entities/{entity_id}; no pasa auth_user a la plantilla |
| `GET /graph` | viewer+ (302 /login) | graph.html | settings; datos vía /api/graph (JS) | ok | 302 login; error del fetch a /api/graph pintado en cliente | 8 | sí |  |
| `GET /jobs` | viewer+ (302 /login) | jobs.html | jobs_client (SQLite de jobs) acotado por scope | ok; db_no_disponible | 302 login; error de DB pintado en la plantilla, HTTP 200 | 7 | sí | no pasa auth_user a la plantilla |
| `GET /jobs/{job_id}` | viewer+ (302 /login) | job_detail.html | jobs_client.scoped_job | ok; job_not_found; db_no_disponible | job inexistente => HTTP 200 con error='job_not_found' | 4 | sí | no pasa auth_user a la plantilla |
| `GET /login` | público | auth/login.html | cookie CSRF de login | formulario; ya autenticado => 302 | - | 13 | sí |  |
| `POST /login` | público | auth/login.html (error) / 302 | auth DB (SQLite) | ok 302; credenciales_invalidas; bloqueado; csrf_invalido; campos_incompletos (400) | 400; 403 CSRF | 13 | sí |  |
| `POST /logout` | autenticado | 302 /login | auth DB (sesiones) | ok | 403 CSRF | 3 | sí |  |
| `GET /openapi.json` | admin (404 si S9K_AUTH_EXPOSE_DOCS=false) | application/json | app.openapi() | ok | 404; 401; 403 | 1 | — |  |
| `POST /partida/select` | autenticado | 302 a next | auth DB (concesiones) | ok; partida no concedida => se ignora | 403 CSRF; next externo saneado | 2 | sí |  |
| `GET /quality` | reviewer+ (302/403) | quality.html | provider.quality_metrics | ok; métricas vacías | 302 login; 403 | 4 | — | SIN ENLACE ENTRANTE: no aparece en base.html ni en index.html |
| `GET /redoc` | admin (404 si docs no expuestos) | redoc (HTML de FastAPI) | /openapi.json | ok | 404; 401; 403 | 1 | — |  |
| `GET /review-console` | reviewer+ (302/403) | reviews_console.html | almacén local de review v1 acotado por scope | ok; bandeja vacía | 302 login; 403 | 2 | sí | SIN ENLACE ENTRANTE desde base.html; ruta duplicada '' y '/' |
| `GET /review-console/` | reviewer+ (302/403) | reviews_console.html | almacén local de review v1 acotado por scope | ok; bandeja vacía | 302 login; 403 | 2 | — | SIN ENLACE ENTRANTE desde base.html; ruta duplicada '' y '/' |
| `GET /review-console/source/{source_id}` | reviewer+ (302/403) | reviews_console_source.html | review v1: candidatos + preview del plan | ok; stale_warning | 404 JSON CRUDO (fuera de ámbito o inexistente); 403 | 2 | sí |  |
| `POST /review-console/source/{source_id}/decide` | reviewer+ | 303 a /review-console/source/{id} | escribe review-decision v1 (almacén local, nunca Neo4j) | ok; conflicto optimista => stale=1 | 403 CSRF; 404 | 2 | sí |  |
| `GET /reviews` | reviewer+ (403 HTML) | reviews.html | output/reviews/<workspace> en disco | ok; sin fuentes | 302 login; 403 HTML auth/403.html | 8 | sí | no pasa auth_user a la plantilla |
| `GET /reviews/{source_id}` | reviewer+ (403 HTML) | reviews_detail.html | ficheros del pipeline en output/reviews | ok | 404 JSON CRUDO (HTTPException); 403 HTML | 3 | sí | no pasa auth_user a la plantilla |
| `GET /sources` | reviewer+ (302/403) | sources.html | provider.list_sources | ok; lista vacía | 302 login; 403 | 5 | sí |  |
| `GET /sources/{source_id}` | reviewer+ (302/403) | source_detail.html | provider.source_detail | ok | 404 error.html; 503 error.html | 1 | sí |  |
| `GET /status` | viewer+ (302 /login) | status.html | api_status(provider filtrado) | ok | 302 login | 8 | sí |  |
| `GET /v3/review` | reviewer+ (302/403) | v3_review.html | ReviewService (cola V3 en disco) acotada por scope | ok; sin workspace seleccionado; cola vacía | 302 login; 403; 404 workspace | 3 | sí | ruta duplicada '' y '/' |
| `GET /v3/review/` | reviewer+ (302/403) | v3_review.html | ReviewService (cola V3 en disco) acotada por scope | ok; sin workspace seleccionado; cola vacía | 302 login; 403; 404 workspace | 2 | — | ruta duplicada '' y '/' |
| `POST /v3/review/decide` | reviewer+ | 303 a /v3/review | ReviewService + almacén de decisiones | ok 303; stale (400) | 400; 403 CSRF | 2 | sí |  |
| `GET /v3/review/glossary-candidates` | reviewer+ (302/403) | v3_glossary_candidates.html | GlossaryCandidateStore | ok; sin workspace | 302 login; 403; 404 workspace | 0 | sí | SIN ENLACE ENTRANTE: no aparece en base.html ni en v3_review.html |
| `POST /v3/review/undo` | reviewer+ | 303 a /v3/review | ReviewService (deshacer última decisión) | ok 303 | 400; 403 CSRF | 0 | sí |  |

> `#Tests` = ficheros de prueba que nombran la ruta (verificado por la puerta,
> no declarado a ojo). `Nav. entrante` = alguna plantilla o el JS del visor
> enlaza a la ruta; las APIs no llevan enlace por diseño.

## Hallazgos, por gravedad y por propietario

### ALTA

**K-1 · El contrato de error de las páginas HTML no es uno, son tres.**
Medido con `TestClient` sobre la app real:

| Petición | Respuesta |
|---|---|
| `GET /entity/no-existe` | `404 application/json` — `{"detail":"Entidad no encontrada"}` |
| `GET /reviews/no-existe` | `404 application/json` |
| `GET /review-console/source/no-existe` | `404 application/json` |
| `GET /entities/no-existe` | `404 text/html` con `error.html` |
| `GET /sources/no-existe` | `404 text/html` con `error.html` |
| `GET /jobs/no-existe` | **`200 text/html`** con `error='job_not_found'` |

Un usuario de navegador recibe JSON crudo en unas rutas, una página de error en
otras y un 200 “correcto” con el error dentro en una tercera. La pista del
trabajo previo sigue viva y además tiene una tercera cara (el 200 de `/jobs`).
*Propietario: carril A (`main.py`) para `/entity`, `/reviews`, `/jobs`;*
*equipo del panel de revisión v1 (`routers/reviews_console.py`) para*
*`/review-console/source/{id}`.*

**K-2 · Lista y detalle de entidades apuntan a contratos distintos.**
`entities.html` (servida por `readonly.entities_page`) enlaza a `/entity/{id}`
—la ficha **legada** de `main.py`, con `entity.html`— y no a `/entities/{id}`,
que es la ficha nueva con `error.html`, `auth_user` y escapado. `static/js/graph.js`
hace lo mismo (`href="/entity/${id}"`). Resultado: la ficha buena sólo se
alcanza desde los enlaces de relación dentro de sí misma; navegando de verdad
nunca se llega. *Propietario: carril A.*

**K-3 · Cinco páginas pierden la barra superior de usuario.**
`main.py` no pasa `auth_user` al contexto de `entity.html`, `jobs.html`,
`job_detail.html`, `reviews.html` ni `reviews_detail.html`. Como `base.html`
condiciona todo el bloque de usuario a `auth_user is defined and auth_user`, en
esas cinco páginas desaparecen el nombre de usuario, el rol, el selector de
partida, “Salir” y los enlaces de reviewer/admin. Con auth activada es una
degradación real de navegación, no cosmética. *Propietario: carril A.*

### MEDIA

**K-4 · Pantallas montadas y sin enlace entrante** (sólo alcanzables tecleando
la URL): `/quality` (reviewer+), `/admin/health`, `/v3/review/glossary-candidates`
y `/review-console`. Ninguna aparece en `base.html`; `/admin/audit` sólo se
alcanza desde `/admin/users`. *Propietario: carril A (`base.html`), con aviso a
los equipos de V3 review y panel v1.*

**K-5 · Cuatro rutas sin ninguna prueba** (reconocidas en `known_gaps`):
`POST /admin/users/{user_id}/unlock`, `POST /admin/users/{user_id}/revoke-sessions`,
`GET /v3/review/glossary-candidates`, `POST /v3/review/undo`. Las dos primeras
son acciones de administración con efecto sobre sesiones y bloqueos.
*Propietario: carril A (admin/auth) y equipo V3 review.*

**K-6 · Duplicidad de contratos de API sobre la misma entidad.**
`app/api/entities.py` sirve `/api/entity/{id}` y `app/routers/readonly.py` sirve
`/api/entities/{id}`: mismo dato, distinta forma de error (la segunda distingue
404 de 503) y distinta ruta. Igual pasa con `/entity/{id}` vs `/entities/{id}` en
HTML. *Propietario: carril A.*

**K-7 · Rutas gemelas `''` y `/`.** `/review-console` y `/review-console/`, y
`/v3/review` y `/v3/review/`, están registradas dos veces con el mismo endpoint
(dos entradas en OpenAPI, ninguna redirección canónica). Inofensivo hoy, ruido
en el contrato. *Propietario: panel v1 y V3 review.*

### Hallazgos dirigidos a los carriles B y C (antes de integrar)

**K-8 (B) · `/admin/ops` y `/api/admin/ops` no están montadas.**
En `feat/admin-operations-dashboard`, `viewer/app/routers/ops.py` existe con las
dos rutas y su propio docstring reconoce que no se auto-registra: falta la línea
`app.include_router(ops_router.router)` en `main.py`. Tampoco hay enlace a
`/admin/ops` en `base.html` ni en `auth/admin/users.html`. Sin ambas cosas, la
pantalla no existe para nadie. *Propietario: carril B, coordinado con A.*

**K-9 (C) · `/v3/review/console` está montada pero es inalcanzable.**
En `feat/review-console-v2-readonly`, `routers/review_console_v2.py` (prefijo
`/console`) se incluye dentro del router de V3 (`v3_review.py:213`), así que las
rutas `GET /v3/review/console`, `/v3/review/console/` y
`/v3/review/console/item/{proposal_id}` sí quedan registradas — pero no hay ni un
enlace hacia ellas en `base.html` ni en `v3_review.html`. *Propietario: carril C,
coordinado con A para el enlace.*

**K-10 (organización) · Las ramas B y C están desfasadas respecto de `main`.**
Su diff contra `28320bd` **borra ~5.600 líneas** de pruebas del visor
(`tests/browser/*`, `test_autorizacion_e2e_http*`, `test_registro_*`, …) porque
parten de un `main` anterior. Rebase obligatorio antes de integrar; si se
mergean tal cual, se pierde la red de seguridad que hace útil este mapa.
*Propietario: quien orqueste la integración.*

## La puerta, en rojo y en verde

La puerta se llama `viewer/tests/test_route_contract_map.py` (9 pruebas) y se
ejecuta con la suite normal del visor.

**Verde de partida** — sobre `main` sin tocar nada:

```
$ python3 -m pytest viewer/tests/test_route_contract_map.py -q
9 passed
```

**Rojo demostrado** — se introdujeron a propósito tres defectos y se revirtieron:

1. una ruta nueva sin prueba ni ficha (`GET /demo-puerta-en-rojo` en
   `routers/readonly.py`):

   ```
   AssertionError: Rutas registradas en el visor que NADIE ha declarado en el
   mapa de contratos: ['GET /demo-puerta-en-rojo'].
   ```

2. un enlace roto en `index.html` (`href="/pantalla-que-no-existe"`):

   ```
   AssertionError: Enlaces de la interfaz que no resuelven contra ninguna ruta
   registrada: index.html: href='/pantalla-que-no-existe' -> /pantalla-que-no-existe
   ```

3. una plantilla huérfana (`templates/demo_huerfana.html`):

   ```
   AssertionError: Plantillas que nadie renderiza ni hereda: ['demo_huerfana.html']
   ```

Los tres defectos se revirtieron (`git checkout --` y borrado del fichero) y la
puerta volvió a verde; la suite completa del visor sigue en
`909 passed, 167 skipped`.

## Qué NO se pudo inventariar, y por qué

- **Los 503 reales del proveedor.** No hay Neo4j en este entorno: los estados
  `503`/“fuente de datos no disponible” se documentan leyendo el código, no
  medidos contra un backend caído.
- **Las rutas de los carriles B y C.** No se pueden introspeccionar desde la app
  real de `main` (una no está montada, la otra vive en otra rama). Se
  documentan por inspección de la rama; entrarán en el mapa cuando se integren,
  y la puerta lo exigirá.
- **Enlaces construidos por concatenación en JS.** Sólo se validan las rutas
  literales (incluidas las plantillas con `${…}`); `static/js/vendor/` queda
  fuera a propósito.
- **Contratos de `/static`.** Es un montaje de ficheros, no rutas con contrato.
- **La correspondencia prueba→ruta es por mención textual**, no por ejecución:
  sirve para verificar una declaración escrita a mano, no para medir cobertura
  real de ramas. Una prueba que nombre la ruta y no la ejerza engañaría a la
  puerta; ese es el límite honesto de este mecanismo.

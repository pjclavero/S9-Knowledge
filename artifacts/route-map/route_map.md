# Mapa de rutas v2 — 2185f2b01bb7

- definidas (AST): **59**
- montadas en `app.main.app`: **59**
- enlazadas desde navegación: **31**
- probadas de verdad (sonda pytest): **47**
- deniegan petición anónima con auth ON: **57** — de ellas 56 con guardián estático; 12 de métodos con cuerpo (sondeados con token CSRF válido: 12); 0 fuera del recuento
- consumidas: **56**

> Medido con esta configuración: `S9K_DEFAULT_WORKSPACE=leyenda`, `S9K_GRAPH_PROVIDER=mock`. El instrumento **no distingue «apagada por bandera» de «muerta»**: ejecútalo una vez por configuración antes de dictaminar.

| ruta | def | mnt | link | test | authz anónimo | rol mínimo medido | guardián estático | consum |
|---|:-:|:-:|:-:|:-:|---|---|---|:-:|
| `GET /` | si | si | si | si (8) | denegada | viewer | _require_user_or_redirect | si |
| `GET /account` | si | si | si | NO (0) | denegada | viewer | require_authenticated_user | si |
| `GET /account/change-password` | si | si | si | si (9) | denegada | viewer | require_authenticated_user | si |
| `POST /account/change-password` | si | si | si | si (9) | denegada | viewer | require_authenticated_user | si |
| `GET /admin/audit` | si | si | si | si (1) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /admin/health` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user | NO |
| `GET /admin/partidas` | si | si | si | si (11) | denegada | admin | require_admin, require_authenticated_user, list_partida_access | si |
| `POST /admin/partidas/grant` | si | si | si | si (9) | denegada | admin | require_admin, require_authenticated_user, grant_partida_access | si |
| `POST /admin/partidas/{access_id}/revoke` | si | si | si | si (1) | denegada | admin | require_admin, require_authenticated_user, revoke_partida_access | si |
| `GET /admin/users` | si | si | si | si (3) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /admin/users/new` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/new` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /admin/users/{user_id}` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/{user_id}` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/{user_id}/revoke-sessions` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/{user_id}/unlock` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /api/admin/health` | si | si | NO | si (3) | denegada | admin | require_api_role | si |
| `GET /api/entities` | si | si | NO | si (83) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/entities/{entity_id}` | si | si | si | si (16) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/entity-types` | si | si | NO | si (4) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/entity/{entity_id}` | si | si | NO | si (6) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/graph` | si | si | si | si (12) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/jobs` | si | si | NO | si (8) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/jobs/counts` | si | si | NO | si (4) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/jobs/{job_id}` | si | si | NO | si (4) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/quality` | si | si | NO | si (3) | denegada | reviewer | require_api_role | si |
| `GET /api/search` | si | si | NO | si (8) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/sources` | si | si | NO | si (2) | denegada | reviewer | require_api_role | si |
| `GET /api/sources/{source_id}` | si | si | NO | si (1) | denegada | reviewer | require_api_role | si |
| `GET /api/status` | si | si | NO | si (11) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/workspaces` | si | si | NO | si (6) | denegada | viewer | require_api_authenticated_user | si |
| `GET /docs` | si | si | NO | si (4) | denegada | ninguno-sirve | _docs_access | si |
| `GET /entities` | si | si | si | si (30) | denegada | viewer | html_guard | si |
| `GET /entities/{entity_id}` | si | si | si | si (3) | denegada | viewer | html_guard | si |
| `GET /entity/{entity_id}` | si | si | si | si (2) | denegada | viewer | _require_user_or_redirect | si |
| `GET /graph` | si | si | si | si (22) | denegada | viewer | _require_user_or_redirect | si |
| `GET /jobs` | si | si | si | si (5) | denegada | viewer | _require_user_or_redirect | si |
| `GET /jobs/{job_id}` | si | si | si | si (1) | denegada | viewer | _require_user_or_redirect | si |
| `GET /login` | si | si | NO | si (12) | publica-por-diseno | viewer | — | si |
| `POST /login` | si | si | NO | si (11) | publica-por-diseno | ninguno-sirve | — | si |
| `POST /logout` | si | si | si | si (2) | denegada | ninguno-sirve | — | si |
| `GET /openapi.json` | si | si | NO | si (1) | denegada | ninguno-sirve | _docs_access | si |
| `POST /partida/select` | si | si | si | si (31) | denegada | admin | require_authenticated_user | si |
| `GET /quality` | si | si | NO | si (2) | denegada | reviewer | _guard, html_role_guard | si |
| `GET /redoc` | si | si | NO | si (1) | denegada | ninguno-sirve | _docs_access | si |
| `GET /review-console` | si | si | NO | si (7) | denegada | reviewer | _guard | si |
| `GET /review-console/` | si | si | NO | NO (0) | denegada | reviewer | _guard | NO |
| `GET /review-console/source/{source_id}` | si | si | NO | si (8) | denegada | reviewer | _guard | si |
| `POST /review-console/source/{source_id}/decide` | si | si | NO | si (7) | denegada | reviewer | _guard | si |
| `GET /reviews` | si | si | si | si (7) | denegada | reviewer | _require_reviewer_or_redirect | si |
| `GET /reviews/{source_id}` | si | si | si | si (9) | denegada | reviewer | _require_reviewer_or_redirect | si |
| `GET /sources` | si | si | si | si (4) | denegada | reviewer | _guard, html_role_guard | si |
| `GET /sources/{source_id}` | si | si | si | si (1) | denegada | reviewer | _guard, html_role_guard | si |
| `GET /status` | si | si | si | si (2) | denegada | viewer | _require_user_or_redirect | si |
| `GET /v3/review` | si | si | si | si (24) | denegada | reviewer | _guard | si |
| `GET /v3/review/` | si | si | NO | NO (0) | denegada | reviewer | _guard | NO |
| `POST /v3/review/decide` | si | si | si | si (21) | denegada | reviewer | _guard | si |
| `GET /v3/review/glossary-candidates` | si | si | NO | NO (0) | denegada | reviewer | _guard | si |
| `POST /v3/review/undo` | si | si | si | NO (0) | denegada | reviewer | _guard | si |

## Hallazgos

### Rutas MUERTAS (definidas y no montadas): 0

### Enlaces ROTOS: 0

### Rutas SIN AUTH (2xx anónimo con auth ON): 0

### Rutas NO PROBADAS: 12
- `GET /account`
- `GET /admin/health`
- `GET /admin/users/new`
- `POST /admin/users/new`
- `GET /admin/users/{user_id}`
- `POST /admin/users/{user_id}`
- `POST /admin/users/{user_id}/revoke-sessions`
- `POST /admin/users/{user_id}/unlock`
- `GET /review-console/`
- `GET /v3/review/`
- `GET /v3/review/glossary-candidates`
- `POST /v3/review/undo`

### Rutas HUÉRFANAS (no alcanzables desde navegación): 28
- `GET /admin/health`
- `POST /admin/users/new`
- `POST /admin/users/{user_id}`
- `GET /api/admin/health`
- `GET /api/entities`
- `GET /api/entity-types`
- `GET /api/entity/{entity_id}`
- `GET /api/jobs`
- `GET /api/jobs/counts`
- `GET /api/jobs/{job_id}`
- `GET /api/quality`
- `GET /api/search`
- `GET /api/sources`
- `GET /api/sources/{source_id}`
- `GET /api/status`
- `GET /api/workspaces`
- `GET /docs`
- `GET /login`
- `POST /login`
- `GET /openapi.json`
- `GET /quality`
- `GET /redoc`
- `GET /review-console`
- `GET /review-console/`
- `GET /review-console/source/{source_id}`
- `POST /review-console/source/{source_id}/decide`
- `GET /v3/review/`
- `GET /v3/review/glossary-candidates`

### Rutas CAPTURADAS por otro patrón: 0

### Guardián declarado pero NO aplicado: 0

### Rutas servidas a rol viewer: 22
- `GET /` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /account` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /account/change-password` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `POST /account/change-password` — {'admin': 400, 'reviewer': 400, 'viewer': 400}
- `GET /api/entities` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/entities/{entity_id}` — {'admin': 404, 'reviewer': 404, 'viewer': 404}
- `GET /api/entity-types` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/entity/{entity_id}` — {'admin': 404, 'reviewer': 404, 'viewer': 404}
- `GET /api/graph` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/jobs` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/jobs/counts` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/jobs/{job_id}` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/search` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/status` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /api/workspaces` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /entities` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /entities/{entity_id}` — {'admin': 404, 'reviewer': 404, 'viewer': 404}
- `GET /entity/{entity_id}` — {'admin': 404, 'reviewer': 404, 'viewer': 404}
- `GET /graph` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /jobs` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /jobs/{job_id}` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /status` — {'admin': 200, 'reviewer': 200, 'viewer': 200}

### Sondas inconcluyentes: 0

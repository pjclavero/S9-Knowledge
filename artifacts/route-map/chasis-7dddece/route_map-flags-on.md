# Mapa de rutas v2 — 7dddece

- definidas (AST): **61**
- montadas en `app.main.app`: **67**
- enlazadas desde navegación: **35**
- probadas de verdad (sonda pytest): **0**
- deniegan petición anónima con auth ON: **65** — de ellas 64 con guardián estático; 12 de métodos con cuerpo (sondeados con token CSRF válido: 12); 0 fuera del recuento
- consumidas: **43**

> Medido con esta configuración: `S9K_DEFAULT_WORKSPACE=leyenda`, `S9K_GRAPH_PROVIDER=mock`, `S9K_PANEL_B_ENABLED=true`, `S9K_PANEL_C_ENABLED=true`, `S9K_PANEL_F_ENABLED=true`, `S9K_PANEL_G_ENABLED=true`. El instrumento **no distingue «apagada por bandera» de «muerta»**: ejecútalo una vez por configuración antes de dictaminar.

| ruta | def | mnt | link | test | authz anónimo | rol mínimo medido | guardián estático | consum |
|---|:-:|:-:|:-:|:-:|---|---|---|:-:|
| `GET /` | si | si | si | NO (0) | denegada | viewer | _require_user_or_redirect | si |
| `GET /account` | si | si | si | NO (0) | denegada | viewer | require_authenticated_user | si |
| `GET /account/change-password` | si | si | si | NO (0) | denegada | viewer | require_authenticated_user | si |
| `POST /account/change-password` | si | si | si | NO (0) | denegada | viewer | require_authenticated_user | si |
| `GET /admin/audit` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /admin/health` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user | NO |
| `GET /admin/partidas` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user, list_partida_access | si |
| `POST /admin/partidas/grant` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user, grant_partida_access | si |
| `POST /admin/partidas/{access_id}/revoke` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user, revoke_partida_access | si |
| `GET /admin/users` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /admin/users/new` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/new` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /admin/users/{user_id}` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/{user_id}` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/{user_id}/revoke-sessions` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `POST /admin/users/{user_id}/unlock` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user | si |
| `GET /api/admin/health` | si | si | NO | NO (0) | denegada | admin | require_api_role | NO |
| `GET /api/entities` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/entities/{entity_id}` | si | si | si | NO (0) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/entity-types` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/entity/{entity_id}` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/graph` | si | si | si | NO (0) | denegada | viewer | require_api_authenticated_user | si |
| `GET /api/jobs` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/jobs/counts` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/jobs/{job_id}` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/quality` | si | si | NO | NO (0) | denegada | reviewer | require_api_role | NO |
| `GET /api/search` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/sources` | si | si | NO | NO (0) | denegada | reviewer | require_api_role | NO |
| `GET /api/sources/{source_id}` | si | si | NO | NO (0) | denegada | reviewer | require_api_role | NO |
| `GET /api/status` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /api/workspaces` | si | si | NO | NO (0) | denegada | viewer | require_api_authenticated_user | NO |
| `GET /docs` | si | si | NO | NO (0) | denegada | ninguno-sirve | _docs_access | NO |
| `GET /entities` | si | si | si | NO (0) | denegada | viewer | html_guard | si |
| `GET /entities/{entity_id}` | si | si | si | NO (0) | denegada | viewer | html_guard | si |
| `GET /entity/{entity_id}` | si | si | si | NO (0) | denegada | viewer | _require_user_or_redirect | si |
| `GET /graph` | si | si | si | NO (0) | denegada | viewer | _require_user_or_redirect | si |
| `GET /jobs` | si | si | si | NO (0) | denegada | viewer | _require_user_or_redirect | si |
| `GET /jobs/{job_id}` | si | si | si | NO (0) | denegada | viewer | _require_user_or_redirect | si |
| `GET /login` | si | si | NO | NO (0) | publica-por-diseno | viewer | — | si |
| `POST /login` | si | si | NO | NO (0) | publica-por-diseno | ninguno-sirve | — | si |
| `POST /logout` | si | si | si | NO (0) | denegada | ninguno-sirve | — | si |
| `GET /openapi.json` | si | si | NO | NO (0) | denegada | ninguno-sirve | _docs_access | NO |
| `GET /panel/entities` | si | si | si | NO (0) | denegada | viewer | _guard, slot_guard | si |
| `GET /panel/entities/` | si | si | NO | NO (0) | denegada | viewer | _guard, slot_guard | NO |
| `GET /panel/operations` | si | si | si | NO (0) | denegada | admin | require_admin, require_authenticated_user, slot_guard | si |
| `GET /panel/operations/` | si | si | NO | NO (0) | denegada | admin | require_admin, require_authenticated_user, slot_guard | NO |
| `GET /panel/review` | si | si | si | NO (0) | denegada | reviewer | _guard, slot_guard | si |
| `GET /panel/review/` | si | si | NO | NO (0) | denegada | reviewer | _guard, slot_guard | NO |
| `GET /panel/sources` | si | si | si | NO (0) | denegada | reviewer | _guard, slot_guard | si |
| `GET /panel/sources/` | si | si | NO | NO (0) | denegada | reviewer | _guard, slot_guard | NO |
| `POST /partida/select` | si | si | si | NO (0) | denegada | admin | require_authenticated_user | si |
| `GET /quality` | si | si | NO | NO (0) | denegada | reviewer | _guard, html_role_guard | NO |
| `GET /redoc` | si | si | NO | NO (0) | denegada | ninguno-sirve | _docs_access | NO |
| `GET /review-console` | si | si | NO | NO (0) | denegada | reviewer | _guard | si |
| `GET /review-console/` | si | si | NO | NO (0) | denegada | reviewer | _guard | NO |
| `GET /review-console/source/{source_id}` | si | si | NO | NO (0) | denegada | reviewer | _guard | si |
| `POST /review-console/source/{source_id}/decide` | si | si | NO | NO (0) | denegada | reviewer | _guard | si |
| `GET /reviews` | si | si | si | NO (0) | denegada | reviewer | _require_reviewer_or_redirect | si |
| `GET /reviews/{source_id}` | si | si | si | NO (0) | denegada | reviewer | _require_reviewer_or_redirect | si |
| `GET /sources` | si | si | si | NO (0) | denegada | reviewer | _guard, html_role_guard | si |
| `GET /sources/{source_id}` | si | si | si | NO (0) | denegada | reviewer | _guard, html_role_guard | si |
| `GET /status` | si | si | si | NO (0) | denegada | viewer | _require_user_or_redirect | si |
| `GET /v3/review` | si | si | si | NO (0) | denegada | reviewer | _guard | si |
| `GET /v3/review/` | si | si | NO | NO (0) | denegada | reviewer | _guard | NO |
| `POST /v3/review/decide` | si | si | si | NO (0) | denegada | reviewer | _guard | si |
| `GET /v3/review/glossary-candidates` | si | si | NO | NO (0) | denegada | reviewer | _guard | si |
| `POST /v3/review/undo` | si | si | si | NO (0) | denegada | reviewer | _guard | si |

## Hallazgos

### Rutas MUERTAS (definidas y no montadas): 0

### Enlaces ROTOS: 0

### Rutas SIN AUTH (2xx anónimo con auth ON): 0

### Rutas NO PROBADAS: 67
- `GET /`
- `GET /account`
- `GET /account/change-password`
- `POST /account/change-password`
- `GET /admin/audit`
- `GET /admin/health`
- `GET /admin/partidas`
- `POST /admin/partidas/grant`
- `POST /admin/partidas/{access_id}/revoke`
- `GET /admin/users`
- `GET /admin/users/new`
- `POST /admin/users/new`
- `GET /admin/users/{user_id}`
- `POST /admin/users/{user_id}`
- `POST /admin/users/{user_id}/revoke-sessions`
- `POST /admin/users/{user_id}/unlock`
- `GET /api/admin/health`
- `GET /api/entities`
- `GET /api/entities/{entity_id}`
- `GET /api/entity-types`
- `GET /api/entity/{entity_id}`
- `GET /api/graph`
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
- `GET /entities`
- `GET /entities/{entity_id}`
- `GET /entity/{entity_id}`
- `GET /graph`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /login`
- `POST /login`
- `POST /logout`
- `GET /openapi.json`
- `GET /panel/entities`
- `GET /panel/entities/`
- `GET /panel/operations`
- `GET /panel/operations/`
- `GET /panel/review`
- `GET /panel/review/`
- `GET /panel/sources`
- `GET /panel/sources/`
- `POST /partida/select`
- `GET /quality`
- `GET /redoc`
- `GET /review-console`
- `GET /review-console/`
- `GET /review-console/source/{source_id}`
- `POST /review-console/source/{source_id}/decide`
- `GET /reviews`
- `GET /reviews/{source_id}`
- `GET /sources`
- `GET /sources/{source_id}`
- `GET /status`
- `GET /v3/review`
- `GET /v3/review/`
- `POST /v3/review/decide`
- `GET /v3/review/glossary-candidates`
- `POST /v3/review/undo`

### Rutas HUÉRFANAS (no alcanzables desde navegación): 32
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
- `GET /panel/entities/`
- `GET /panel/operations/`
- `GET /panel/review/`
- `GET /panel/sources/`
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

### Rutas servidas a rol viewer: 24
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
- `GET /panel/entities` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /panel/entities/` — {'admin': 200, 'reviewer': 200, 'viewer': 200}
- `GET /status` — {'admin': 200, 'reviewer': 200, 'viewer': 200}

### Sondas inconcluyentes: 0

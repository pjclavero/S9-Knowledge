# 48 · Visor de solo lectura — mejoras de usabilidad (Tarea C)

> Estado: **IMPLEMENTADO**. Rama `feat/viewer-readonly-usability` fusionada en `main`.
> **Estrictamente de solo lectura: no aprueba, edita, fusiona ni ingiere; 0 escrituras en Neo4j.**

---

## Rutas implementadas

### Entidades (viewer+)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/entities` | GET HTML | Listado paginado con filtros y búsqueda |
| `/entities/{entity_id}` | GET HTML | Ficha de entidad con relaciones entrantes/salientes |
| `/api/entities` | GET JSON | Listado paginado — envelope `{items, pagination, filters}` |
| `/api/entities/{entity_id}` | GET JSON | Ficha de entidad con relaciones |

### Fuentes (reviewer+)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/sources` | GET HTML | Listado de fuentes del workspace |
| `/sources/{source_id}` | GET HTML | Detalle de fuente: entidades por tipo y review_status |
| `/api/sources` | GET JSON | Listado de fuentes |
| `/api/sources/{source_id}` | GET JSON | Detalle de fuente |

### Panel de calidad (reviewer+)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/quality` | GET HTML | Panel de métricas de calidad |
| `/api/quality` | GET JSON | Métricas de calidad estructuradas |

**Todas las rutas son GET únicamente. No existe ningún endpoint POST/PUT/PATCH/DELETE en el router readonly.**

---

## Roles por ruta

```
viewer+   → /entities, /entities/{id}, /api/entities, /api/entities/{id}
reviewer+ → /sources, /sources/{id}, /api/sources, /api/sources/{id}
reviewer+ → /quality, /api/quality
```

Jerarquía: admin > reviewer > viewer.

Con `S9K_AUTH_ENABLED=false` (por defecto): acceso público sin autenticación (comportamiento de compatibilidad).

Con `S9K_AUTH_ENABLED=true`:
- Rutas HTML sin sesión → 302 a `/login?next=<ruta>`
- Rutas API sin sesión → 401 JSON
- Rol insuficiente HTML → 403
- Rol insuficiente API → 403 JSON

---

## Filtros y parámetros

### `/api/entities`

| Parámetro | Tipo | Por defecto | Descripción |
|-----------|------|-------------|-------------|
| `workspace` | string | `S9K_DEFAULT_WORKSPACE` | Filtro por workspace |
| `q` | string | `""` | Búsqueda en nombre, alias, descripción (insensible a mayúsculas) |
| `entity_type` | string | `null` | Filtro por tipo de entidad |
| `source_kind` | string | `null` | Filtro por tipo de fuente |
| `review_status` | string | `null` | Filtro por estado de revisión |
| `visibility` | string | `null` | Filtro por visibilidad |
| `quality_status` | string | `null` | Filtro por estado de calidad |
| `min_confidence` | float [0,1] | `null` | Confianza mínima |
| `sort` | string | `canonical_name` | Campo de ordenación (allowlist) |
| `order` | `asc`\|`desc` | `asc` | Dirección de ordenación |
| `limit` | int | 50 | Ítems por página (máx. 200) |
| `offset` | int ≥ 0 | 0 | Desplazamiento |

**Allowlist de `sort`:** `canonical_name`, `entity_type`, `confidence`, `review_status`, `created_at`. Si se pasa un valor no permitido, se normaliza silenciosamente a `canonical_name`.

---

## Paginación

La paginación se empuja al proveedor de datos (**no se hace en Python sobre listas completas**):

- En Neo4j: `SKIP $offset LIMIT $limit` en las queries Cypher.
- En el mock: slicing después de filtrar en memoria (comportamiento equivalente para tests).
- Se emite una query separada para el `count` total (mismos filtros, sin SKIP/LIMIT).

### Envelope de API

```json
{
  "items": [...],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 123,
    "has_next": true,
    "has_previous": false
  },
  "filters": {
    "workspace": "leyenda",
    "q": "",
    "entity_type": null,
    "source_kind": null,
    "review_status": null,
    "visibility": null,
    "quality_status": null,
    "min_confidence": null,
    "sort": "canonical_name",
    "order": "asc"
  }
}
```

---

## Configuración

Variables de entorno (en `.env` o directamente):

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `S9K_VIEWER_DEFAULT_PAGE_SIZE` | 50 | Tamaño de página por defecto |
| `S9K_VIEWER_MAX_PAGE_SIZE` | 200 | Límite superior de `limit` |
| `S9K_VIEWER_QUERY_TIMEOUT_SECONDS` | 10 | Timeout por consulta (segundos) |
| `S9K_VIEWER_MAX_SEARCH_LENGTH` | 200 | Longitud máxima del parámetro `q` |

---

## Gestión de errores

### Códigos de respuesta

| Código | Condición |
|--------|-----------|
| 400 | Parámetros inválidos (`offset < 0`, `q` demasiado largo, `order` no válido) |
| 401 | No autenticado (API: JSON; HTML: 302 → /login) |
| 403 | Rol insuficiente |
| 404 | Entidad o fuente no encontrada |
| 503 | Proveedor de datos no disponible (Neo4j caído) |
| 504 | Timeout de consulta |

### Formato de error en API (JSON)

```json
{"error": {"code": "ENTITY_NOT_FOUND", "message": "Entidad no encontrada"}}
```

Códigos de error definidos: `ENTITY_NOT_FOUND`, `SOURCE_NOT_FOUND`, `PROVIDER_UNAVAILABLE`, `QUERY_TIMEOUT`.

Las páginas HTML muestran mensajes de error claros (template `error.html`) sin stack traces ni queries Cypher.

---

## Seguridad

- **Jinja2 autoescape activo** (heredado de la configuración de la app). No se usa `|safe` con datos del grafo.
- **Datos del grafo en JS**: se usa `textContent`, no `innerHTML`. Los valores del grafo se inyectan vía `tojson` y se asignan con `textContent` para prevenir XSS.
- **Cypher paramétrico**: todos los parámetros van vía `$param`, nunca concatenados al texto de la query.
- **Búsqueda segura**: `toLower(coalesce(n.canonical_name,'')) CONTAINS toLower($q)`.
- **Allowlist de ordenación**: el campo `sort` se valida contra una lista blanca; valores no permitidos se normalizan silenciosamente.
- **Sin `id(n)`**: se usa `elementId(n)` en todas las queries Neo4j.
- **Sin tokens de escritura**: el router `readonly.py` no contiene CREATE, MERGE, SET, DELETE, DETACH, REMOVE, DROP, LOAD CSV (verificado por test de auditoría).
- **Sin stack traces**: las páginas HTML de error no exponen información interna.

---

## vis-network local (sin CDN)

- **Archivo**: `viewer/app/static/js/vendor/vis-network.min.js`
- **Versión**: v9.1.9
- **Origen**: vendorizado localmente; el visor funciona sin acceso a Internet.
- **Carga**: `graph.html` lo carga desde `/static/js/vendor/vis-network.min.js` con atributo `integrity` (SRI).
- **No hay ninguna referencia a CDN** (unpkg, jsdelivr, etc.) en las templates.

---

## Panel de calidad (`/quality`, `/api/quality`)

Métricas de **solo lectura** (queries MATCH-only en Neo4j):

- Total entidades y relaciones del workspace
- Distribución por `entity_type`, `review_status`, `visibility`, workspace
- Distribución de confianza: alta (≥ 0.8), media (≥ 0.5), baja (< 0.5), sin valor
- Gaps de datos: entidades sin `source_document`, sin `description`, sin `entity_type`

**No merges, no modificaciones del grafo, no análisis de duplicados activos.**

---

## Recomendaciones de índices Neo4j

Los índices siguientes mejorarían el rendimiento de las queries de listado y búsqueda. **Solo recomendados, no se crean automáticamente:**

```cypher
-- Filtrado principal
CREATE INDEX entity_workspace IF NOT EXISTS FOR (n:Entity) ON (n.workspace);
CREATE INDEX entity_workspace_type IF NOT EXISTS FOR (n:Entity) ON (n.workspace, n.entity_type);
CREATE INDEX entity_workspace_review IF NOT EXISTS FOR (n:Entity) ON (n.workspace, n.review_status);
CREATE INDEX entity_workspace_visibility IF NOT EXISTS FOR (n:Entity) ON (n.workspace, n.visibility);

-- Búsqueda de texto (si se usa fulltext search en lugar de CONTAINS)
CREATE FULLTEXT INDEX entity_names IF NOT EXISTS FOR (n:Entity) ON EACH [n.canonical_name, n.display_name, n.description];
```

---

## Limitaciones conocidas

1. **Búsqueda `q` con `CONTAINS`**: no es fulltext; es suficiente para volúmenes pequeños/medios. Para volúmenes grandes, migrar a índice fulltext de Neo4j.
2. **`quality_metrics` con múltiples queries separadas**: en Neo4j real, podría optimizarse con una sola query `MATCH...WITH...` pero la legibilidad y el aislamiento de errores son preferibles en esta fase.
3. **Mock provider**: `list_entities` filtra en memoria (correcto para tests; el mock no representa un Neo4j real).
4. **Timeout**: `S9K_VIEWER_QUERY_TIMEOUT_SECONDS` está configurado pero el mecanismo de imposición real depende del driver Neo4j (parámetro `timeout` en `session.run`). En el mock siempre responde instantáneamente.

---

## Garantía de solo lectura

- **0 escrituras en Neo4j**: todas las queries son `MATCH ... RETURN`. Ninguna query contiene CREATE, MERGE, SET, DELETE, DETACH, REMOVE, DROP, LOAD CSV.
- **Verificación automática**: `test_cypher_sin_tokens_escritura` en `test_readonly.py` falla si se añade un token de escritura a `readonly.py`.
- **Router readonly**: solo métodos GET/HEAD/OPTIONS. Verificado por `test_router_sin_post` y `test_router_sin_put_patch_delete`.
- **Provider base**: los métodos abstractos nuevos (`list_entities`, `list_sources`, `source_detail`, `quality_metrics`) no tienen firma de escritura.

---

## E2E

E2E ejecutado con **TestClient mock** (Neo4j no accesible sin credenciales actualizadas).

- Todas las rutas responden correctamente con el mock provider.
- **Escrituras Neo4j: 0** — garantizado por diseño (queries MATCH-only) y verificado por tests de auditoría.
- Suite viewer: **194 passed** (tests/test_readonly.py: **46 passed**).

---

## Archivos modificados/creados

**Modificados:**
- `viewer/app/config.py` — nuevas variables de configuración
- `viewer/app/providers/base.py` — métodos abstractos nuevos
- `viewer/app/providers/mock_provider.py` — implementación mock
- `viewer/app/providers/neo4j_provider.py` — implementación Neo4j (MATCH-only)
- `viewer/app/routers/readonly.py` — router completo (reescrito)
- `viewer/app/templates/sources.html` — actualizado con links y datos Neo4j
- `viewer/tests/test_readonly.py` — 46 tests (era 13)

**Creados:**
- `viewer/app/templates/entity_detail.html`
- `viewer/app/templates/source_detail.html`
- `viewer/app/templates/quality.html`
- `viewer/app/templates/error.html`

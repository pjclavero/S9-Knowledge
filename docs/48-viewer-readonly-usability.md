# 48 · Mejoras del visor de solo lectura (Tarea C)

> Estado: **AUDITORÍA INICIAL / EN CURSO**. Rama `feat/viewer-readonly-usability` desde `main@40cf75d`.
> Mejora la utilidad diaria del visor. **Estrictamente de solo lectura: no aprueba, edita, fusiona ni ingiere; 0 escrituras en Neo4j.**

---

## Auditoría inicial (estado actual)

- Rutas HTML: `/`, `/graph`, `/status`, `/entity/{id}`, `/jobs`, `/jobs/{id}`, `/reviews`, `/reviews/{source_id}` (`viewer/app/main.py`). Ya protegidas por rol tras la fase de auth.
- API: `/api/status`, `/api/workspaces`, `/api/entity-types`, `/api/search`, `/api/entity/{id}`, `/api/graph`, `/api/jobs*` (`viewer/app/api/`). `search` y `graph` **sin paginación**; `graph` limita por `limit`.
- Proveedor de datos: `viewer/app/providers/neo4j_provider.py` (solo lectura) + `mock_provider`.
- **vis-network se carga por CDN** (`unpkg.com`) en `templates/graph.html` → el visor NO funciona sin Internet. Estáticos: `static/js/graph.js`, `static/css/app.css`. No hay `static/js/vendor/`.
- Serialización: `viewer/app/serializers.py`. Templates comparten `templates/base.html` (compartido con auth).

## Declaración de ámbito

**Archivos que se crearán/modificarán (solo esta tarea):**
- `viewer/app/api/entities.py` y `graph.py` — paginación, filtros por workspace/tipo, búsqueda paginada (solo lectura).
- `viewer/app/main.py` — nuevas rutas GET `/entities`, `/entities/{id}`, `/sources`, `/sources/{source_id}`, `/quality` (sin POST de datos).
- `viewer/app/providers/neo4j_provider.py` — consultas de lectura optimizadas (evitar N+1, límites, timeout).
- `viewer/app/serializers.py`, `templates/` (entity, sources, quality, provenance) — presentación.
- `viewer/app/static/js/vendor/vis-network.min.js` (+ SRI) — **vendorizado**, sin CDN.
- `docs/48-viewer-readonly-usability.md`.
- Tests en `viewer/tests/` (roles, paginación, filtros, procedencia ausente, entidad inexistente, escaping, CDN no requerida, 0 escrituras).

**Módulos que NO se tocan:** writer/ingesta, `external_processing`, internals de auth (se reutilizan las dependencias de rol), no se añaden acciones POST sobre datos. Cambios en `base.html` mínimos y compatibles con auth.

**Documentos:** solo `docs/48`. **No** README/CHANGELOG/ROADMAP/`docs/INDEX` (Tarea E).

**Dependencias:** ninguna nueva; `vis-network` se sirve como estático vendorizado (el visor debe funcionar sin Internet). Sin React/Vue/otros frameworks.

## Contratos (permisos)

```
viewer   : consulta general
reviewer : consulta + información de revisión
admin    : todo lo anterior
```
Sin secretos, sin `elementId` como dato principal, sin rutas privadas. Paginación + límites configurables + índices recomendados documentados (no creados).

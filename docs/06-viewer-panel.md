# 06 · Visor y panel (FUTURO)

Estado: **no implementado**. Solo diseño. Fuente de detalle:
`docs/current/VISOR_DESIGN.md`, `docs/current/EXTERNAL_SOURCES_DESIGN.md`,
`docs/current/KNOWLEDGE_VISIBILITY_DESIGN.md`.

## Visor (solo lectura)

Lee de Neo4j y dibuja el grafo. Vistas previstas: grafo global, solo personajes,
bestiario, enemigos activos, lugares con encuentros, sesiones/cronología, evolución
temporal, novedades por sesión, red social, por documento, por lugar, por criatura.

Filtros transversales: `workspace`, `visibility`, `knowledge_layer`,
`review_status`, y **personaje activo** (modo `character_knowledge`).

## Panel de gestión

- **Fuentes / Importar**: alta de trabajos (URL o ruta + workspace + tipo + sesión
  + visibilidad + capa). Alimenta `state/jobs.db`.
- **/control/users**: usuarios-personajes (asignar, aprobar, revocar, activo por
  workspace, permisos).
- **/control/visibility**: marcar conocido por personaje/grupo/público, ocultar,
  marcar relación secreta/descubierta, compartir.

## Endpoints REST (previstos)

```
GET  /sources           GET  /sources/new        POST /api/sources
GET  /api/jobs          GET  /api/jobs/{id}       POST /api/jobs/{id}/process
POST /api/jobs/{id}/retry   POST /api/jobs/{id}/ignore   POST /api/jobs/{id}/cancel
GET  /api/jobs/{id}/transcript   GET /api/jobs/{id}/entities
```

## Modos de visualización

`admin_full`, `narrator`, `party`, `session_public`, `character_knowledge`
(ver `docs/current/KNOWLEDGE_VISIBILITY_DESIGN.md`).

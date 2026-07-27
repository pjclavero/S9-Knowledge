# 07 · Usuarios, personajes y permisos

Implementación base: `data-engine/app/access/access_store.py` (SQLite
`state/access.db`, no versionada). Diseño completo:
`docs/current/USERS_CHARACTERS_DESIGN.md` y
`docs/current/KNOWLEDGE_VISIBILITY_DESIGN.md`.

## Modelo

- Un **usuario** puede tener varios **personajes**, uno (o varios) por **workspace**.
- Tabla intermedia `user_character_link` (no `User.character_id`): estados
  `pending / approved / rejected / revoked / assigned`; `is_active_for_workspace`
  (un activo por usuario+workspace).
- El **admin** puede asignar directamente (`assigned`) o aprobar solicitudes del
  usuario (`pending → approved`); puede revocar y cambiar el activo.
- `user_workspace_permission`: permisos **por bóveda** (no globales): tipos de
  entidad visibles, `max_visible_session`, y flags de contenido sensible
  (secret/future/narrator/reference).
- `access_audit_log`: 7 eventos (request/approve/reject/assign/revoke/active_changed/
  permission_changed).

## Visibilidad en dos niveles

1. **Por sesión/campaña**: público / grupo hasta la sesión visible.
2. **Por conocimiento de personaje**: un usuario en modo `character_knowledge`
   solo ve una entidad si es pública/de-grupo dentro de la sesión visible, o si su
   personaje tiene una relación de conocimiento con ella, o participó en un
   evento/combate donde apareció, o se la compartieron (TELLS/SHARED_WITH).

Nunca ve `secret/narrator/future/reference/manual/admin_only` sin permiso explícito.

## Estado

- Modelo y almacén: **implementados** (selftest OK).
- Aplicación real de los filtros: **pendiente** (vive en el visor/API futuros). El
  grafo ya guarda las propiedades necesarias (`known_by_scope`, `knowledge_quality`,
  `known_from_session`, `visibility`, etc.).

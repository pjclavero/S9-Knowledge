# Diseño: Usuarios y Personajes Multi-Campaña

**Versión:** 1.0  
**Fecha:** 2026-07-09  
**Estado:** Diseño de referencia  
**Implementación:** `app/access/access_store.py` (SQLite `state/access.db`) — componente separado

---

## 1. Problema

Un usuario puede participar en varias campañas (workspaces/bóvedas) a la vez, interpretando un personaje distinto en cada una. El modelo de un único `character_id` en el objeto `User` no soporta este escenario.

**Ejemplo concreto:**

| Usuario  | Workspace (bóveda)  | Personaje activo   |
|----------|---------------------|--------------------|
| pedro    | leyenda             | Kakita Asuka       |
| pedro    | mundo_tinieblas     | Nila               |
| pedro    | trudvang            | Eirik              |
| maria    | leyenda             | Kimi               |
| carlos   | leyenda             | Bayushi Hisao      |
| carlos   | trudvang            | Björn              |

Pedro juega en tres campañas con tres personajes completamente distintos. Si el visor muestra "el personaje de pedro", necesita saber en qué workspace está trabajando pedro en este momento para mostrar el personaje correcto y filtrar el grafo adecuadamente.

**Solución:** Eliminar `User.character_id`. Usar una tabla intermedia `UserCharacterLink` que relaciona usuario, workspace y personaje, con estado de aprobación y metadatos de auditoría.

---

## 2. Modelo de Datos

### 2.1 Entidad: `User`

```
User
├── username          (PK, único)
├── display_name      (nombre mostrado en UI)
├── email             (opcional)
├── password_hash
├── is_admin          (boolean)
├── is_active         (boolean)
├── created_at        (datetime ISO)
└── last_login        (datetime ISO)
```

Sin `character_id`. La asignación de personajes se gestiona completamente en `UserCharacterLink`.

### 2.2 Entidad: `Workspace`

```
Workspace
├── workspace_id      (PK, slug único, ej: "leyenda", "mundo_tinieblas")
├── display_name      (nombre legible)
├── description       (texto libre)
├── neo4j_database    (nombre de la BD Neo4j asociada)
├── is_active         (boolean)
└── created_at        (datetime ISO)
```

### 2.3 Entidad: `Character`

```
Character
├── character_id      (PK, UUID)
├── workspace         (FK → Workspace.workspace_id)
├── character_name    (nombre del personaje)
├── player_notes      (notas opcionales)
├── is_active_in_story (boolean — el personaje sigue vivo/activo en la narración)
└── created_at        (datetime ISO)
```

Un personaje pertenece a un único workspace. No puede transferirse entre workspaces.

### 2.4 Tabla intermedia: `UserCharacterLink`

```
UserCharacterLink
├── id                     (PK, UUID)
├── username               (FK → User.username)
├── workspace              (FK → Workspace.workspace_id)
├── character_id           (FK → Character.character_id)
├── character_name         (desnormalizado para legibilidad en logs)
├── status                 (pending | approved | rejected | revoked | assigned)
├── assigned_by_admin      (boolean — true si admin asignó directamente)
├── requested_by_user      (boolean — true si fue solicitud del usuario)
├── requested_at           (datetime ISO, nullable)
├── approved_at            (datetime ISO, nullable)
├── approved_by            (username del admin que aprobó, nullable)
├── revoked_at             (datetime ISO, nullable)
├── revoked_by             (username del admin que revocó, nullable)
├── is_active_for_workspace (boolean — personaje activo actual del usuario en este workspace)
└── notes                  (texto libre para el admin)
```

### 2.5 Estados del enlace usuario-personaje

| Estado     | Descripción                                                                 |
|------------|-----------------------------------------------------------------------------|
| `pending`  | El usuario solicitó el personaje; pendiente de aprobación del admin         |
| `approved` | Aprobado por admin; el usuario puede usarlo                                 |
| `rejected` | Rechazado por admin; el usuario no puede usarlo                             |
| `revoked`  | Estaba aprobado/asignado pero el admin lo retiró                            |
| `assigned` | Asignado directamente por admin sin pasar por solicitud (`assigned_by_admin=true`) |

---

## 3. Reglas del Modelo

### Asignación y solicitudes

- **Un usuario puede tener varios personajes** en distintos workspaces (uno activo por workspace en cada momento).
- **En el mismo workspace**, un usuario puede tener múltiples personajes históricos (p. ej., un personaje anterior que murió), pero solo uno `is_active_for_workspace=true` a la vez.
- **Admin puede asignar directamente** (`assigned_by_admin=true`, `status=assigned`) sin requerir solicitud previa del usuario.
- **Usuario puede solicitar** un personaje (`requested_by_user=true`, `status=pending`). El admin aprueba (`status=approved`) o rechaza (`status=rejected`).
- **Admin puede revocar** cualquier enlace activo (`status=revoked`, `revoked_at`, `revoked_by`).
- **Admin puede cambiar el personaje activo** de un usuario en un workspace: pone `is_active_for_workspace=false` al anterior y `true` al nuevo.

### Invariantes de integridad

- Solo puede existir un registro con `is_active_for_workspace=true` por combinación `(username, workspace)`.
- Un personaje `is_active_for_workspace=true` debe tener `status` en `approved` o `assigned`.
- Un personaje solo puede estar asignado a un usuario activo a la vez por workspace (no compartir personaje entre usuarios en el mismo workspace sin revocación previa).

---

## 4. Permisos por Workspace: `UserWorkspacePermission`

Los permisos son **por usuario y workspace**, nunca globales (excepto `is_admin`). Un usuario puede tener permisos distintos en cada bóveda.

### Estructura de la tabla

```
UserWorkspacePermission
├── username                    (FK → User.username)
├── workspace                   (FK → Workspace.workspace_id)
├── enabled                     (boolean — acceso habilitado al workspace)
├── role_in_workspace           (player | narrator | observer | admin)
├── max_visible_session         (int | null — sesión máxima que puede ver; null = todas)
│
│   — Permisos de visualización de tipos de entidad —
├── can_view_characters         (boolean)
├── can_view_locations          (boolean)
├── can_view_creatures          (boolean)
├── can_view_enemies            (boolean)
├── can_view_allies             (boolean)
├── can_view_objects            (boolean)
├── can_view_events             (boolean)
├── can_view_timeline           (boolean)
├── can_view_documents          (boolean)
├── can_view_images             (boolean)
├── can_view_relationships      (boolean)
│
│   — Permisos de visibilidad de contenido sensible —
├── can_view_uncertain_relations (boolean — relaciones marcadas como dudosas/inferidas)
├── can_view_reference          (boolean — entidades de referencia/worldbuilding puro)
├── can_view_narrator           (boolean — contenido del narrador)
├── can_view_secret             (boolean — contenido marcado como secreto)
└── can_view_future             (boolean — contenido de sesiones futuras)
```

### Ejemplo: distintos permisos por bóveda

| Campo                      | pedro / leyenda | pedro / mundo_tinieblas | carlos / leyenda |
|----------------------------|-----------------|-------------------------|------------------|
| `enabled`                  | true            | true                    | true             |
| `role_in_workspace`        | player          | player                  | player           |
| `max_visible_session`      | null            | 3                       | null             |
| `can_view_creatures`       | true            | false                   | true             |
| `can_view_secret`          | false           | false                   | false            |
| `can_view_narrator`        | false           | false                   | false            |
| `can_view_future`          | false           | false                   | false            |
| `can_view_uncertain_relations` | true        | false                   | true             |

Pedro en `mundo_tinieblas` solo puede ver hasta la sesión 3 y no ve criaturas (su personaje Nila aún no las ha encontrado). En `leyenda` tiene acceso completo como jugador habitual.

---

## 5. Vista de Usuario: Selector de Juego y Personaje

### Flujo al entrar al visor

1. El usuario inicia sesión.
2. El sistema consulta `UserWorkspacePermission` para listar los workspaces con `enabled=true` para ese usuario.
3. El usuario elige workspace (bóveda/campaña).
4. El sistema busca en `UserCharacterLink` el registro con `username`, `workspace` y `is_active_for_workspace=true` y `status` en `approved` o `assigned`.
5. El visor carga el grafo de ese workspace, aplica `max_visible_session`, activa el modo `character_knowledge` para ese personaje y filtra según `UserWorkspacePermission`.

### Sin personaje activo en el workspace

Si el usuario no tiene personaje activo en el workspace seleccionado (no hay `UserCharacterLink` activo):

- Solo puede ver información con `known_publicly=true` o `known_by_party=true` (equivalente al modo `session_public` o `party`).
- El visor muestra un aviso: *"No tienes un personaje asignado en esta campaña. Solo puedes ver información pública."*
- El usuario puede enviar una solicitud de asignación de personaje si el admin lo permite.

---

## 6. Vista Admin: /control/users

Panel de administración completo de usuarios, personajes y permisos.

### Acciones disponibles

**Gestión de usuarios:**
- Crear usuario (username, contraseña inicial, nombre mostrado, email).
- Desactivar/reactivar usuario (`is_active=false/true`).
- Cambiar contraseña de usuario.

**Gestión de personajes por workspace:**
- Asignar personaje a usuario en un workspace (crea `UserCharacterLink` con `status=assigned`, `assigned_by_admin=true`).
- Aprobar solicitud pendiente (`status=pending` → `status=approved`).
- Rechazar solicitud (`status=pending` → `status=rejected`).
- Revocar enlace activo (`status=approved/assigned` → `status=revoked`).
- Cambiar personaje activo en un workspace (cambia `is_active_for_workspace`).

**Gestión de permisos:**
- Habilitar/deshabilitar acceso de usuario a workspace (`enabled`).
- Cambiar rol en workspace (`role_in_workspace`).
- Ajustar `max_visible_session`.
- Configurar permisos de visualización (checklist por tipo de entidad y contenido sensible).

### Ejemplo de pantalla de edición de usuario: pedro

```
Usuario: pedro  (pedro@ejemplo.com)  [Activo]

Workspaces:
  [x] leyenda             — Rol: jugador  — Sesiones: todas
  [x] mundo_tinieblas     — Rol: jugador  — Sesiones: hasta 3
  [ ] trudvang            — Rol: —        — (sin acceso)

Personajes por workspace:
  leyenda:
    [activo]  Kakita Asuka    (status: assigned)   [Cambiar] [Revocar]
              Kakita-anterior (status: revoked)     [Ver historial]

  mundo_tinieblas:
    [activo]  Nila            (status: approved)   [Cambiar] [Revocar]

  trudvang:
    (sin personaje)                                  [Asignar]

Permisos en leyenda:
  [x] personajes  [x] lugares  [x] criaturas  [x] enemigos  [x] aliados
  [x] objetos     [x] eventos  [x] línea temporal  [x] documentos
  [x] imágenes    [x] relaciones  [x] relaciones inciertas
  [ ] referencia  [ ] narrador  [ ] secreto  [ ] futuro

Permisos en mundo_tinieblas:
  [x] personajes  [x] lugares  [ ] criaturas  [ ] enemigos  [x] aliados
  [x] objetos     [x] eventos  [x] línea temporal  [ ] documentos
  [ ] imágenes    [x] relaciones  [ ] relaciones inciertas
  [ ] referencia  [ ] narrador  [ ] secreto  [ ] futuro
```

---

## 7. Casos de Uso

### Caso 1: Usuario con varios personajes en distintas campañas

Pedro entra al visor. Selecciona `leyenda` → el sistema activa Kakita Asuka, modo `character_knowledge`, ve lo que sabe Asuka. Luego cambia a `mundo_tinieblas` → el sistema activa Nila, diferente grafo, diferentes permisos, solo ve hasta sesión 3.

### Caso 2: Admin asigna personaje sin solicitud

El narrador quiere que María juegue a Kimi en `leyenda`. El admin crea el `UserCharacterLink` con `status=assigned`, `assigned_by_admin=true`. María entra al visor y ya tiene acceso inmediato al personaje sin necesidad de aprobar nada.

### Caso 3: Usuario solicita personaje

Un nuevo jugador, Raul, quiere unirse a `trudvang` como Eirik. Envía solicitud desde el visor (`status=pending`, `requested_by_user=true`). El admin ve la solicitud en `/control/users`, verifica que el personaje está disponible y aprueba (`status=approved`). Raul puede ahora usar Eirik.

### Caso 4: Usuario sin personaje activo

Ana tiene acceso a `leyenda` (`enabled=true`) pero ningún personaje asignado. Entra al visor, selecciona `leyenda` y ve solo la información pública y del grupo. El visor muestra el aviso correspondiente. Ana puede solicitar un personaje si el admin ha habilitado esa opción.

---

## 8. Reglas de Seguridad

### Lo que un usuario normal no puede hacer

- **No puede autoasignarse** un personaje: toda asignación la inicia el admin o pasa por aprobación (`requested_by_user=true` no otorga acceso hasta que admin aprueba).
- **No puede ver personajes de otros workspaces** para los que no tiene `enabled=true` en `UserWorkspacePermission`.
- **No puede cambiar** a un personaje que no tiene `status=approved` o `status=assigned`.
- **No puede modificar** sus propios permisos en ningún workspace.
- **No puede ver** contenido con `can_view_secret=false`, `can_view_narrator=false`, etc., aunque el nodo exista en el grafo.

### Lo que un admin puede hacer

- Asignar, aprobar, rechazar, revocar cualquier enlace usuario-personaje.
- Cambiar permisos de cualquier usuario en cualquier workspace.
- Ver todo el grafo en modo `admin_full`.
- Simular la vista de cualquier jugador (modo "Jugador simulado").
- Cambiar el personaje activo de cualquier usuario en cualquier workspace.

### Auditoría

**Todo cambio en asignaciones y permisos se registra en el audit log.** Eventos auditados:

| Evento                              | Descripción                                                      |
|-------------------------------------|------------------------------------------------------------------|
| `user_character_requested`          | Usuario solicitó un personaje                                    |
| `user_character_approved`           | Admin aprobó la solicitud                                        |
| `user_character_rejected`           | Admin rechazó la solicitud                                       |
| `user_character_assigned_by_admin`  | Admin asignó personaje directamente                              |
| `user_character_revoked`            | Admin revocó un enlace activo                                    |
| `user_active_character_changed`     | Se cambió el personaje activo de un usuario en un workspace      |
| `workspace_permission_changed`      | Se modificaron los permisos de un usuario en un workspace        |

Cada entrada del audit log incluye: `timestamp`, `actor` (admin que realizó la acción), `target_user`, `workspace`, `character_id` si aplica, `action`, `previous_value`, `new_value`.

---

## 9. Nota de Implementación

Este documento es el **diseño de referencia**. La implementación concreta de las tablas `UserCharacterLink` y `UserWorkspacePermission` se entrega en:

```
app/access/access_store.py
```

usando SQLite con base de datos en `state/access.db`. Este componente es independiente del pipeline de extracción y del grafo Neo4j; actúa como capa de control de acceso que el visor y la API consultan antes de ejecutar cualquier query sobre el grafo.

---

*Fin del documento. Tablas User y Workspace también en `access_store.py`.*

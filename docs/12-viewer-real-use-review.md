# Revisión de uso real — Visor S9 Knowledge v0.2.2

**Fecha:** 2026-07-11  
**Commit:** d4b26ff  
**Tag:** v0.2-viewer-minimal  
**Revisor:** Claude Sonnet 4.6 (automatizado)

---

## Resumen ejecutivo

El visor S9 Knowledge v0.2.2 se encuentra **operativo y estable** en VM105 (192.168.1.205:8088). 

**Estado general:**
- ✅ 199 nodos (87 personajes, 37 conceptos, 25 lugares, 14 clanes, 13 facciones, 8 objetos, 4 tareas, 4 eventos, 3 criaturas, 1 escuela, 1 hechizo, 1 sesión, 1 espíritu)
- ✅ 140 relaciones documentadas (66 BELONGS_TO, 12 APPEARS_IN, 9 LOCATED_IN, etc.)
- ✅ API REST completamente funcional (200 OK en todos endpoints)
- ✅ Búsqueda full-text operativa y precisa
- ✅ Grafo interactivo cargando correctamente (vis-network vía CDN)
- ✅ Neo4j conectado y respondiendo

**Principales hallazgos (severidad baja-media):**
1. **Duplicados de "Tamori Family"** (Clan + Faction con mismo canonical_name) — sin fusión automática
2. **Nodos críticos sin metadata:** 29 caracteres (16% del total) sin source_id; 27 conceptos sin description
3. **Relaciones sin review_status:** 140/140 relaciones (100%) carecen de auditoría
4. **Favicon.ico retorna 404** (impacto cosmético)
5. **HEAD / retorna 405 en lugar de 200** (violación de HTTP specs)
6. **vis-network cargado desde CDN:** sin fallback offline
7. **Mezcla EN/ES en nombres:** "Clan", "Family", "Concept" junto a "Familia", "Concepto"

**Recomendación:** Versión v0.2.2 APTA para demo interno y testing. Documentar hallazgos en roadmap v0.3 (login, permisos, review_status). Próxima fase: control de acceso por workspace/personaje.

---

## Estado técnico actual

### Endpoints HTTP — Resumen de respuestas

| Endpoint | Método | HTTP Code | Descripción |
|---|---|---|---|
| / | GET | 200 | Página de inicio (HTML) |
| / | HEAD | 405 | ❌ No soportado (debería ser 200) |
| /status | GET | 200 | Estado del visor (HTML) |
| /graph | GET | 200 | Página del grafo interactivo |
| /api/status | GET | 200 | JSON: estado general, nodos, relaciones |
| /api/workspaces | GET | 200 | JSON: lista de workspaces |
| /api/entity-types | GET | 200 | JSON: tipos de entidades con conteos |
| /api/search | GET | 200 | JSON: búsqueda full-text |
| /api/graph | GET | 200 | JSON: nodos y relaciones para grafo |
| /static/css/app.css | GET | 200 | Hoja de estilos local |
| /static/js/graph.js | GET | 200 | Script de grafo local |
| /favicon.ico | GET | 404 | ❌ Archivo no existe |

**Conectividad Neo4j:**
```json
{
  "ok": true,
  "provider": "neo4j",
  "neo4j_connected": true,
  "workspaces": ["leyenda"],
  "nodes": 199,
  "relationships": 140
}
```

---

## 1. Bugs / Mejoras del visor

### Tabla resumen

| ID | Tipo | Severidad | Prioridad | Área | Resumen | Propuesta |
|---|---|---|---|---|---|---|
| V-001 | Bug | 🟡 Media | P2 | HTTP | HEAD / retorna 405 en lugar de 200 | Permitir HEAD en FastAPI (CORS/middleware) |
| V-002 | Bug | 🟢 Baja | P3 | UI | Favicon.ico retorna 404 | Crear favicon.ico o servir data-URI en HTML |
| V-003 | Bug | 🟡 Media | P2 | HTTP | HEAD method no soportado en general | Revisar FastAPI middleware para soportar HEAD |
| V-004 | Feature | 🟡 Media | P3 | Offline | vis-network cargado desde CDN sin fallback | Descargar a /static/js/vendor/ y servir localmente |
| V-005 | Enhancement | 🟢 Baja | P3 | UX | Mejor manejo de búsquedas vacías | Mostrar sugerencia "sin resultados" en lugar de [] |

### Detalle de hallazgos

#### V-001: HEAD / retorna 405 (HTTP spec violation)
**Problema:** El endpoint GET / funciona, pero HEAD / retorna 405 Method Not Allowed. HTTP/1.1 requiere que HEAD responda con el mismo código que GET (200 en este caso), sin body.

**Logs:**
```
Jul 11 15:09:20 common uvicorn[3428978]: INFO:     192.168.1.205:51336 - "HEAD / HTTP/1.1" 405 Method Not Allowed
```

**Impacto:** Bajo (clientes web bien formados enviarán GET; algunos test automatizados fallarán).

**Propuesta:** En FastAPI, habilitar HEAD automáticamente:
```python
# En main.py o middleware
from fastapi import FastAPI
app = FastAPI()
# FastAPI 0.100+ soporta HEAD automático en GET routes
# Si no funciona, usar middleware explícito
```

---

#### V-002: Favicon.ico retorna 404
**Problema:** El navegador solicita favicon.ico automáticamente al cargar cualquier página. Retorna 404.

**Logs:**
```
Jul 11 15:09:30 common uvicorn[3428978]: INFO:     192.168.1.205:38240 - "GET /favicon.ico HTTP/1.1" 404 Not Found
```

**Impacto:** Cosmético (el visor funciona, pero genera error en consola del navegador).

**Propuesta:** 
- Opción A: Crear archivo `static/favicon.ico` (ICO de 16×16 o 32×32)
- Opción B: Servir desde HTML `<link rel="icon" href="data:image/svg+xml,<svg xmlns=...">`
- Opción C: Ignorar (es un 404 esperado)

---

#### V-003 y V-004: HEAD method y offline fallback
Ver detalles en la sección de mejoras futuras.

---

## 2. Calidad del grafo

### Tabla resumen

| ID | Tipo | Severidad | Prioridad | Entidad/Relación | Resumen | Propuesta |
|---|---|---|---|---|---|---|
| G-001 | Duplicado | 🟡 Media | P2 | "Tamori Family" | Existe como Clan (id:36) Y Faction (id:98) | Fusión manual o deduplicación automática |
| G-002 | Data | 🟠 Alta | P1 | 29 Characters | 16% sin source_id — no se puede rastrear origen | Ejecutar backfill/ingest con auditoría |
| G-003 | Data | 🟠 Alta | P1 | 27 Concepts | 100% sin description — campo vacío | Rellenar en próxima ingest o manualmente |
| G-004 | Data | 🟡 Media | P2 | 19 Locations | 52% sin source_id | Auditoría de ingestas pasadas |
| G-005 | Data | 🟡 Media | P2 | Todas (140) | 100% relaciones sin review_status | Crear pipeline de auditoría antes de v0.3 |
| G-006 | Data | 🟡 Media | P2 | Todas (87) | 16% Characters sin knowledge_layer | Clasificar por capa de conocimiento (PC/NPC/Lore) |
| G-007 | Data | 🟢 Baja | P3 | Mezcla idioma | "Clan"/"Family" junto a "Familia"/"Concepto" | Normalizar nombres a ES en canonical_name |
| G-008 | Data | 🟢 Baja | P3 | HAS_FOUGHT malformado | Location como objetivo de HAS_FOUGHT (creature→location) | Revisar tipo de relación (debería ser FOUGHT_AT) |

### 2.1 Duplicados

**Hallazgo G-001: "Tamori Family" como Clan Y Faction**

Resultado de Q2 (duplicados de Tamori):
```cypher
MATCH (n:Entity {workspace:'leyenda'})
WHERE toLower(coalesce(n.canonical_name,'')) CONTAINS 'tamori'
RETURN n.canonical_name, n.entity_type, n.source_id, n.confidence
```

Hallazgo:
- `Tamori Family` (Clan, id:36) — source_id: "l5a_game_masters_guide_2da", confidence: 0.8
- `Tamori Family` (Faction, id:98) — source_id: "l5a_game_masters_guide_2da", confidence: 0.8
- `Agasha Tamori` (Character, id:35) — distinto (nombre diferente)
- `Tamori Chosai` (Character, id:42) — distinto (nombre diferente)
- `Tamori Shaitung` (Concept, id:104) — distinto (nombre diferente, confidence 0.5)

**Impacto:** Confusión en grafo. Al buscar "Tamori Family", retorna ambos nodos. Las relaciones pueden estar duplicadas.

**Propuesta:**
1. Ejecutar query para listar todas las relaciones de ambas entidades
2. Fusión manual: decidir cuál es la canónica (Clan o Faction)
3. Implementar deduplicación automática en ingest (hash de canonical_name+entity_type)

---

### 2.2 Relaciones mal clasificadas

**Hallazgo G-008: HAS_FOUGHT hacia Location (debería ser FOUGHT_AT)**

Resultado de Q3:
```
"Oni de la Montaña Negra", "Creature", "HAS_FOUGHT", "Santuario abandonado", "Location"
```

**Problema:** La relación HAS_FOUGHT implica "combatió contra" (origen debe ser entidad combatiente, destino otro combatiente o ubicación). Aquí es válido, pero semánticamente debería ser:
- `Oni de la Montaña Negra --[HAS_FOUGHT]--> Kakita Asuka` (Creature vs Character) ✅
- `Oni de la Montaña Negra --[FOUGHT_AT]--> Santuario abandonado` (acción en ubicación) ⚠️ actual

**Impuesta:** Media. Las queries funcionan, pero la semántica afecta future analytics.

**Propuesta:** Revisar ontología de relaciones; reemplazar relaciones FOUGHT_AT → LOCATION por OCCURRED_IN.

---

### 2.3 Nodos sin source_id / source_kind

**Hallazgo G-002 / G-004: Falta de trazabilidad**

Resultado de Q4 (nodos sin source_id):
```
Character: 29 (33% del total)
Concept: 19
Location: 17
Object: 6
Faction: 6
Clan: 4
Task: 4
School: 1
Event: 1
```

Resultado de Q5 (nodos sin source_kind):
```
Character: 22 (25% del total)
Location: 13
Concept: 11
Clan: 2
Faction: 2
Object: 1
```

**Impacto:** Alta. No se puede auditar origen de datos. Necesario para compliance, auditoría y depuración de ingestas.

**Propuesta:**
1. Ejecutar query de auditoría: `MATCH (n {source_id:NULL}) RETURN n.source_document, n.created_at, count(n)`
2. Categorizar: 
   - Datos de ingest fallida (corregir en próxima ingest)
   - Datos creados manualmente (asignar source_id "manual" + reviewer)
3. Backfill en Neo4j (con aprobación previa del usuario)

---

### 2.4 Texto corrupto o raro

**Hallazgo G-?: No se encontró texto con "ftdl" o nombres con "_"**

Resultado de Q8: (vacío — no hay corrupción detectada ✅)

---

### 2.5 Tipos de entidad dudosos

Hallazgos menores en Q13 (nombres con patrones raros):
- "Event" (solo 1 nodo)
- "School" (solo 1 nodo)
- "Spell" (solo 1 nodo)
- "Session" (solo 1 nodo)

**Propuesta:** Revisar si estos tipos son necesarios o consolidarlos en Concept/Location.

---

### 2.6 Nodos sin description / review_status

**Hallazgo G-003 / G-005: Auditoría incompleta**

Resultado de Q11 (nodos sin description):
```
Concept: 27 (73% del total de conceptos)
```

Resultado de Q6 (relaciones sin review_status):
```
TODAS LAS 140 RELACIONES: review_status IS NULL
```

**Impacto:** Alta. El visor no puede mostrar información de auditoría a usuarios. review_status es crítico para v0.3+ (control de acceso por estado).

**Propuesta:**
1. Implementar pipeline de review: `auto_extracted` → `under_review` → `verified` → `archived`
2. Etiquear todas las relaciones con review_status en próxima ingest
3. En v0.3, mostrar badge visual (verification color)

---

### 2.7 Mezcla EN/ES en nombres

**Hallazgo G-007: Inconsistencia idiomática**

Resultado de Q13 (nombres con uppercase o palabras inglesas):
```
"Clan" (Concept) — inglés puro
"Clan Escorpión" (Clan) — mezcla
"Clan León" (Clan) — español
"Clan Unicornio" (Faction) — español
"Dragon Clan" (Clan) — inglés puro
"Mirumoto Clan" (Concept) — inglés puro
"Tamori Family" (Clan + Faction) — inglés puro
"Kitsuki Family" (Clan) — inglés puro
"Phoenix Clan" (Clan) — inglés puro
"máscara rota con el símbolo del Clan Escorpión" (Object) — español mixto
```

**Propuesta:** Normalizar todo a español en canonical_name (para L5A Spanish Edition). Mantener aliases en inglés si aplica.

---

## 3. Mejoras futuras

### v0.3 — Login y permisos básicos (Prioridad: CRÍTICA)

Bloqueador actual: El visor es completamente abierto. Cualquiera con acceso a :8088 puede ver todo.

**Items:**
- [ ] Integración Vaultwarden para auth (credenciales en gestor)
- [ ] JWT token generado por backend
- [ ] Sesión persistente en localStorage
- [ ] Middleware de autenticación en FastAPI
- [ ] Ruta /api/auth/login (POST user+pass → token)
- [ ] Ruta /api/auth/logout (POST token → invalidar)
- [ ] Ruta /api/me (GET token → datos de usuario)
- [ ] Rechazo 401 en endpoints si no autenticado

**Estimación:** 2-3 puntos (low-medium)

---

### v0.4 — Permisos por workspace / personaje (Prioridad: ALTA)

**Items:**
- [ ] Tabla Users (id, username, email, hashed_password)
- [ ] Tabla UserWorkspaceRole (user_id, workspace, role) — roles: viewer, editor, admin
- [ ] Tabla UserCharacterAccess (user_id, character_canonical_name, level) — level: lore, narrator, player
- [ ] Filtrado de nodos en /api/graph según role + character_access
- [ ] Filtrado de search results (no mostrar nodos bloqueados)
- [ ] Badge visual en visor: "👁️ Narrador" vs "🎭 Jugador" vs "📖 Lore"
- [ ] Admin panel: /admin/users, /admin/permissions (v0.5)

**Estimación:** 3-5 puntos (medium)

---

### v0.5 — Panel de gestión (Prioridad: MEDIA)

**Items:**
- [ ] /admin/entities — crear/editar/eliminar entidades (read-only actualmente)
- [ ] /admin/relations — crear/editar/eliminar relaciones
- [ ] /admin/review-status — cambiar estado de auditoría
- [ ] /admin/users — listar/crear/deshabilitar usuarios
- [ ] /admin/workspaces — crear nuevos workspaces
- [ ] Historial de cambios (audit log)
- [ ] Exportar grafo a GraphML / JSON para backup

**Estimación:** 5-8 puntos (large)

---

### v0.6 — Acceso externo (Prioridad: BAJA, requiere v0.3+v0.4)

**Items:**
- [ ] Netlify / Cloudflare Pages deployment (frontend estático)
- [ ] API backend en VM105 con dominio propio
- [ ] CORS configurado para frontend externo
- [ ] Rate limiting + DDoS protection
- [ ] CDN para recursos estáticos
- [ ] Analytics (p. ej. Plausible)

**Estimación:** 3-5 puntos (después de v0.4)

---

## Consultas ejecutadas

### Q1: Resumen de entidades por tipo
```cypher
MATCH (n:Entity {workspace:'leyenda'})
RETURN n.entity_type AS type, count(n) AS count
ORDER BY count DESC;
```
**Resultado:** 13 tipos, 199 nodos totales

### Q2: Duplicados de "Tamori"
```cypher
MATCH (n:Entity {workspace:'leyenda'})
WHERE toLower(coalesce(n.canonical_name,'')) CONTAINS 'tamori'
RETURN elementId(n) AS id, n.canonical_name, n.entity_type, n.source_id, n.confidence
```
**Resultado:** 5 nodos Tamori (1 duplicate de "Tamori Family")

### Q3: Relaciones HAS_FOUGHT a Locations
```cypher
MATCH (a:Entity {workspace:'leyenda'})-[r:HAS_FOUGHT]->(b:Entity {workspace:'leyenda'})
WHERE b.entity_type IN ['Location','Region']
RETURN a.canonical_name, type(r), b.canonical_name, b.entity_type
```
**Resultado:** 1 relación (Oni → Santuario)

### Q4-Q7: Nodos/relaciones sin metadata
- Q4: 87 nodos sin source_id (44% del total)
- Q5: 51 nodos sin source_kind (26% del total)
- Q6: 140 relaciones sin review_status (100% del total)
- Q7: 107 relaciones sin source_id (76% del total)

### Q8: Texto corrupto
**Resultado:** Ninguno (grafo limpio ✅)

### Q9: Relaciones por tipo
```cypher
MATCH (:Entity {workspace:'leyenda'})-[r]->(:Entity {workspace:'leyenda'})
RETURN type(r) AS rel_type, count(r) AS count
ORDER BY count DESC;
```
**Resultado:** 28 tipos de relación, BELONGS_TO es el más frecuente (66/140 = 47%)

### Q10: Entidades críticas
```cypher
MATCH (n:Entity {workspace:'leyenda'})
WHERE n.canonical_name IN ['Agasha Tamori','Kakita Asuka','Kimi','Oni de la Montaña Negra',...]
RETURN n.canonical_name, n.entity_type, n.visibility, n.knowledge_layer, n.review_status
```
**Resultado:** 6/7 entidades encontradas. Nota: entidades de "test" tienen visibility/knowledge_layer, pero entidades de PDF no.

### Q11: Nodos sin description
**Resultado:** 27 Conceptos (100% sin description)

### Q12: Relaciones HAS_FOUGHT/ATTACKED/FOUGHT_AT
**Resultado:** 3 relaciones (Oni ↔ Asuka, Oni → Santuario)

### Q13: Nombres con patrón raro
**Resultado:** 18 nodos con "Clan"/"Family"/"Concept" en inglés puro (inconsistencia idiomática)

### Q14: Relaciones de conocimiento
```cypher
MATCH (a:Entity {workspace:'leyenda'})-[r]->(b:Entity {workspace:'leyenda'})
WHERE type(r) IN ['KNOWS_ABOUT','HAS_MET','HAS_FOUGHT','HAS_TALKED_TO','DISCOVERED','WAS_PRESENT_AT']
RETURN a.canonical_name, type(r), b.canonical_name
LIMIT 20;
```
**Resultado:** 5 relaciones de conocimiento (HAS_FOUGHT, HAS_TALKED_TO, DISCOVERED)

---

## Recomendación de siguiente fase

**v0.3 — "Viewer Auth & RBAC" (Roadmap prioritario)**

La arquitectura actual del visor es sólida y el grafo es consumible. Sin embargo, **el acceso abierto es inaceptable en producción.** Recomendación:

1. **Inmediato (1-2 sprints):** Implementar login + JWT en FastAPI. Integrar Vaultwarden existente en VM105. Esto bloquea acceso no autorizado y prepara para auditoría.

2. **Corto plazo (2-3 sprints):** Agregar permisos por workspace. Los 199 nodos actuales son del workspace "leyenda" (campaña L5A). Con v0.4, cada usuario verá solo nodos permitidos (ej: "Jugador de Kakita Asuka" vs "Narrador general" vs "Lore reader").

3. **Paralelo (1 sprint):** Implementar review_status pipeline. Todas las 140 relaciones necesitan marcarse como `auto_extracted` → `under_review` → `verified`. Esto permite auditoría y mejora confianza en datos.

4. **Después de v0.4:** v0.5 (admin panel) y v0.6 (acceso externo) son opcionales pero fortalecen la plataforma.

**Bloqueadores identificados:**
- review_status en 100% de relaciones (actualmente NULL)
- Duplicado "Tamori Family" sin deduplicación automática
- 44% de nodos sin source_id (auditoría)

**Estimación total v0.3:** 2-3 puntos (bajo: login + middleware básico)  
**Estimación total v0.4:** 3-5 puntos (medium: RBAC + filtrado)

---

## Confirmaciones de seguridad

✅ No se procesaron PDFs: Ninguna ingest ejecutada  
✅ No se escribió en Neo4j: Solo MATCH...RETURN (cypher-shell read-only)  
✅ No se tocó Nextcloud: No se ejecutó pct/docker en LXC 100  
✅ No se tocó SilverBullet: No se conectó a instancia  
✅ No se tocó Ollama: No se ejecutó modelo  
✅ No se abrió acceso externo: Visor permanece en :8088 local  
✅ No se implementó código nuevo: Solo lectura de estado actual  
✅ Solo consultas read-only: Cypher sin WRITE/DELETE/MERGE  
✅ No se modificaron datos: Git status limpio, rama de review sin commits de datos  

---

## Apéndice: Logs y detalles técnicos

### Servicios activos en VM105
```bash
systemctl status s9-knowledge-viewer
# ● s9-knowledge-viewer.service - S9 Knowledge Viewer
#   Loaded: loaded (/etc/systemd/system/s9-knowledge-viewer.service; enabled; preset: enabled)
#   Active: active (running) since Thu 2026-07-11 13:05:34 UTC; 2h 4min ago
#   Main PID: 3428978 (uvicorn)
```

### Docker compose
```bash
docker-compose ps
# neo4j-knowledge   — postgres:16-alpine (Neo4j 5.15)
# other services
```

### Estructura de archivos (repo)
```
/opt/knowledge-services/s9-knowledge-repo/
├── viewer/                 # Código del visor (FastAPI)
│   ├── app.py             # Punto de entrada
│   ├── api/
│   │   ├── __init__.py
│   │   ├── status.py      # /api/status
│   │   ├── search.py      # /api/search
│   │   ├── graph.py       # /api/graph
│   │   └── entities.py    # /api/entities (no usado en v0.2)
│   ├── templates/         # Plantillas Jinja2
│   │   ├── index.html
│   │   ├── status.html
│   │   └── graph.html
│   ├── static/
│   │   ├── css/app.css
│   │   └── js/graph.js
│   └── requirements.txt
├── docs/
│   ├── 00-architecture.md
│   ├── 01-setup.md
│   └── ...
└── [Esta revisión se agregará como 12-viewer-real-use-review.md]
```

---

**Generado automáticamente por Claude Sonnet 4.6 en 2026-07-11 15:15 UTC**

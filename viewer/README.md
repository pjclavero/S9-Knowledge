# S9 Knowledge — Visor web

Visor web (FastAPI/uvicorn) para consultar el grafo de conocimiento (Neo4j) con
**login propio, roles y sesiones**. **Desplegado en producción** (VM105) mediante
releases inmutables, servido a través del symlink `current`. En desarrollo se
ejecuta en local con un provider mock; en producción usa Neo4j real.

## Arquitectura (producción)

- **Provider Neo4j** (`app/providers/neo4j_provider.py`): consultas Cypher de solo
  lectura contra el contenedor `neo4j-knowledge` (199 nodos / 140 relaciones).
  Probado y activo en VM105.
- **Auth DB externa a la release**: `/var/lib/s9-knowledge/auth/auth.db` (usuarios,
  roles, sesiones). No vive dentro de la release; la contraseña no la gestiona el
  despliegue.
- **Jobs DB externa a la release**: `/var/lib/s9-knowledge/jobs/jobs.db`.
- **Login propio**: formulario con **submit explícito** (evita autoenvío del
  navegador y autofill del gestor), **sesiones** server-side (cookies HttpOnly/
  Secure/SameSite), **CSRF** (token HMAC double-submit) y **roles**
  `admin`/`reviewer`/`viewer`. Basic Auth del proxy **retirada**.
- **systemd**: `s9-knowledge-viewer.service` (a través de `current`) +
  `s9-knowledge-healthcheck.service`/`.timer` (healthcheck horario de solo lectura).

## Proveedores de datos

Seleccionables por entorno (`S9K_GRAPH_PROVIDER`):

- `mock` (por defecto en local): lee `examples/sample_graph.json`. Sin Neo4j ni red.
- `neo4j` (producción): se conecta a Neo4j real. Activo y probado en VM105.

## Puesta en marcha en Windows (PowerShell)

```powershell
cd "E:\Projectos Esp32\S9-Knowledge\viewer"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8088 --reload
```

Abrir en el navegador:

```
http://127.0.0.1:8088
```

`.env` no se versiona (ver `.gitignore` del repo). `S9K_GRAPH_PROVIDER=mock` en
`.env.example` es el valor por defecto: no hace falta tocar nada para probar
con datos de ejemplo.

## Pruebas manuales (curl / PowerShell)

```powershell
curl http://127.0.0.1:8088/api/status
curl "http://127.0.0.1:8088/api/graph?workspace=leyenda&limit=100"
curl "http://127.0.0.1:8088/api/search?workspace=leyenda&q=Tamori"
```

## Tests

```powershell
cd "E:\Projectos Esp32\S9-Knowledge\viewer"
.\.venv\Scripts\activate
pytest
```

## Estructura

```
viewer/
├── app/
│   ├── main.py            · app FastAPI, rutas HTML (/, /graph, /entity/{id}, /status)
│   ├── config.py           · Settings (S9K_*), lee .env
│   ├── deps.py             · dependencias FastAPI (provider singleton)
│   ├── labels.py           · traducciones ES de tipos/relaciones/visibilidad
│   ├── serializers.py      · nodo/relación "crudo" → forma humana para API/UI
│   ├── providers/
│   │   ├── base.py         · interfaz GraphProvider (solo lectura)
│   │   ├── mock_provider.py· lee examples/sample_graph.json
│   │   └── neo4j_provider.py· consultas Cypher de solo lectura (activo en producción)
│   ├── api/                · endpoints JSON /api/*
│   ├── templates/          · Jinja2 (base/index/graph/entity/status)
│   └── static/             · CSS oscuro + graph.js (vis-network)
├── examples/sample_graph.json  · datos mock (11 nodos, 12 relaciones)
├── tests/                  · pytest
└── systemd/                · unidades (viewer + healthcheck.service/.timer), instaladas en VM105
```

## Frontend del grafo: vis-network

Se usa [vis-network](https://visjs.github.io/vis-network/) cargado por **CDN**
(`unpkg.com`) en `app/templates/graph.html`, para no complicar esta fase local
con vendoring. Antes de desplegar en un entorno sin salida a Internet (o si se
quiere evitar dependencia de CDN), descargar `vis-network.min.js` y servirlo
desde `app/static/js/vendor/`, cambiando el `<script src=...>` en `graph.html`.

## Endpoints

Páginas HTML: `GET /`, `GET /graph`, `GET /entity/{entity_id}`, `GET /status`.

JSON: `GET /api/status`, `GET /api/workspaces`, `GET /api/entity-types`,
`GET /api/graph`, `GET /api/entity/{entity_id}`, `GET /api/search`.

## Diferencias local vs producción

| | Local (desarrollo) | Producción (VM105) |
|---|---|---|
| Provider | `mock` (JSON de ejemplo) | `neo4j` (real, 199/140) |
| Auth | opcional (`S9K_AUTH_ENABLED`) | **login propio activo**, roles, sesiones, CSRF |
| Estado | efímero | auth/jobs DB externas en `/var/lib/s9-knowledge` |
| Arranque | `uvicorn --reload` | `s9-knowledge-viewer.service` vía `current` |
| Acceso | `127.0.0.1:8088` | HTTPS público (nginx VM104), sin Basic Auth |

## Qué queda incompleto

- **Acciones de revisión desde el visor** (aprobar/rechazar en UI): pendiente
  (hoy `/reviews` es de lectura).
- **Permisos RPG / visibilidad por personaje** aplicados en API/UI: el modelo
  existe en `data-engine/app/access/`, aún no se aplica en las consultas del visor.
- El visor **no escribe en Neo4j** (todas las consultas son `MATCH ... RETURN`).

## Despliegue en producción

El visor se despliega mediante el utillaje de `deploy/` (releases inmutables +
`current` + deploy-tools versionados). No se instala a mano en VM105; ver
[docs/47](../docs/47-reproducible-deployment.md), [docs/50](../docs/50-deploy-state-continuity.md)
y [docs/02-current-state.md](../docs/02-current-state.md).

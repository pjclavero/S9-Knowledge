# S9 Knowledge — Visor mínimo (v0.2, desarrollo local)

Visor web de **solo lectura** para consultar el grafo de conocimiento (Neo4j) de
forma humana, como sustituto mínimo de Neo4j Browser. Esta fase se desarrolla y
prueba **en local (Windows)**, con datos de ejemplo, sin tocar VM105 ni Neo4j real.

## Proveedores de datos

El visor puede leer de dos fuentes, seleccionables por `.env`:

- `S9K_GRAPH_PROVIDER=mock` (por defecto): lee `examples/sample_graph.json`.
  No requiere Neo4j ni red. Es lo que se usa para desarrollar y probar en local.
- `S9K_GRAPH_PROVIDER=neo4j`: se conecta a Neo4j real (`app/providers/neo4j_provider.py`).
  Queda implementado pero **no se ha probado** contra un Neo4j real todavía; se
  activará en una fase posterior, al desplegar en VM105.

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
│   │   └── neo4j_provider.py· consultas Cypher de solo lectura (sin probar aún)
│   ├── api/                · endpoints JSON /api/*
│   ├── templates/          · Jinja2 (base/index/graph/entity/status)
│   └── static/             · CSS oscuro + graph.js (vis-network)
├── examples/sample_graph.json  · datos mock (11 nodos, 12 relaciones)
├── tests/                  · pytest
└── systemd/s9-knowledge-viewer.service · unidad systemd, PREPARADA, no instalada
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

## Qué NO hace esta fase

- No escribe en Neo4j (todas las consultas del `Neo4jGraphProvider` son de
  lectura: `MATCH ... RETURN`, nunca `CREATE`/`SET`/`DELETE`/`MERGE`).
- No modifica `data-engine` (solo `labels.py` importa, en modo lectura,
  `RELATION_LABELS_ES` desde `data-engine/app/schemas/rpg_schema.py`, con
  fallback local si el import falla).
- No implementa login, permisos, Cloudflare, YouTube/web/audio, ni edición.
- No toca VM105 ni Nextcloud.

## Despliegue futuro en VM105 (referencia, no ejecutado en esta fase)

Cuando se decida desplegar (fase posterior):

```bash
cd /opt/knowledge-services/s9-knowledge-repo/viewer
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ajustar S9K_GRAPH_PROVIDER=neo4j y credenciales reales
uvicorn app.main:app --host 0.0.0.0 --port 8088

sudo cp systemd/s9-knowledge-viewer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now s9-knowledge-viewer
sudo systemctl status s9-knowledge-viewer --no-pager
```

`systemd/s9-knowledge-viewer.service` ya está en el repo con las rutas de
servidor correctas, pero **no se ha copiado ni activado en VM105** en esta fase.

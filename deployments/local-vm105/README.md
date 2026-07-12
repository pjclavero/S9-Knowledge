# Despliegue del visor S9 Knowledge en VM105

Guía y checklist para desplegar el visor mínimo (v0.2, tag `v0.2-viewer-minimal`)
en VM105. **Este documento es solo una guía: no se ha ejecutado ningún paso de
esta guía contra VM105 todavía.** El despliegue real queda pendiente de que se
pida explícitamente.

## Entorno de destino

- Host: VM105 `common`, LAN `192.168.1.205`.
- Repo en servidor: `/opt/knowledge-services/s9-knowledge-repo`.
- Proyecto original (NO TOCAR): `/opt/knowledge-services/property-graph`.
- Neo4j real: contenedor `neo4j-knowledge`, `bolt://127.0.0.1:7687` (también
  `192.168.1.205:7687` en LAN, pero el visor en VM105 debe usar `127.0.0.1`).
- Workspace principal: `leyenda`.

## Checklist de despliegue

### 1. Actualizar el repo en VM105

```bash
ssh <usuario>@192.168.1.205
cd /opt/knowledge-services/s9-knowledge-repo
git status                 # comprobar que no hay cambios locales sin commitear
git fetch origin
git checkout main
git pull origin main
git log --oneline -1       # debe mostrar el merge de v0.2 / tag v0.2-viewer-minimal
git describe --tags        # confirma que estás en (o después de) v0.2-viewer-minimal
```

Si hay cambios locales inesperados en el servidor, **no los descartes**: para
antes de continuar y revisa qué son (podrían ser trabajo en curso de otra
persona o de `property-graph`, que vive en otra ruta y no debería verse
afectado).

### 2. Crear el venv del viewer

```bash
cd /opt/knowledge-services/s9-knowledge-repo/viewer
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

`.venv/` no se versiona (está en `.gitignore`); se recrea en cada máquina.

### 3. Crear `viewer/.env` real

```bash
cp .env.example .env
```

Editar `.env` con los valores reales de VM105:

```env
S9K_VIEWER_HOST=0.0.0.0
S9K_VIEWER_PORT=8088
S9K_GRAPH_PROVIDER=neo4j
S9K_DEFAULT_WORKSPACE=leyenda
S9K_GRAPH_LIMIT=300
S9K_NEO4J_URI=bolt://127.0.0.1:7687
S9K_NEO4J_USER=neo4j
S9K_NEO4J_PASSWORD=
S9K_NEO4J_PASSWORD_FILE=/opt/knowledge-services/neo4j/secrets/neo4j_password
```

**`viewer/.env` nunca se commitea** (está en `.gitignore` vía `.env`/`.env.*`/`*.env`).
Solo existe en cada máquina donde corre el visor.

### 4. Password de Neo4j desde archivo

El visor resuelve la contraseña con esta prioridad (`app/config.py`,
propiedad `Settings.neo4j_password`):

1. Si `S9K_NEO4J_PASSWORD_FILE` apunta a un archivo existente, lee y usa su
   contenido (con `.strip()`).
2. Si no, usa `S9K_NEO4J_PASSWORD` tal cual.

En VM105 se espera que ya exista `/opt/knowledge-services/neo4j/secrets/neo4j_password`
(mismo archivo que usa `property-graph`/`ingest_rpg.py`). Verificar permisos
de lectura para el usuario que ejecuta el visor:

```bash
ls -l /opt/knowledge-services/neo4j/secrets/neo4j_password
```

No copiar ese archivo dentro del repo. No pegar la contraseña en el `.env` si
ya se resuelve por archivo (dejar `S9K_NEO4J_PASSWORD=` vacío).

### 5. Prueba manual con uvicorn (antes de systemd)

```bash
cd /opt/knowledge-services/s9-knowledge-repo/viewer
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8088
```

En otra terminal (o desde el propio VM105):

```bash
curl http://127.0.0.1:8088/api/status
curl "http://127.0.0.1:8088/api/graph?workspace=leyenda&limit=100"
curl "http://127.0.0.1:8088/api/search?workspace=leyenda&q=Tamori"
```

`/api/status` debe devolver `"provider": "neo4j"` y `"neo4j_connected": true`.
Si `neo4j_connected` es `false` o hay error de conexión, revisar `S9K_NEO4J_URI`
y el password file antes de seguir. Parar con `Ctrl+C` una vez validado.

### 6. Instalar el servicio systemd

El unit file ya está en el repo (`viewer/systemd/s9-knowledge-viewer.service`)
con las rutas de servidor correctas — no requiere ajustes para Debian/systemd
estándar (las variables `${S9K_VIEWER_HOST}`/`${S9K_VIEWER_PORT}` se resuelven
desde `EnvironmentFile=` de forma nativa por systemd, sin necesidad de un
wrapper de shell).

```bash
sudo cp /opt/knowledge-services/s9-knowledge-repo/viewer/systemd/s9-knowledge-viewer.service \
        /etc/systemd/system/s9-knowledge-viewer.service
sudo systemctl daemon-reload
sudo systemctl enable --now s9-knowledge-viewer
sudo systemctl status s9-knowledge-viewer --no-pager
```

### 7. Revisar logs

```bash
journalctl -u s9-knowledge-viewer -n 100 --no-pager
journalctl -u s9-knowledge-viewer -f          # seguimiento en vivo
```

Verificar en los logs que arrancó sin errores de import ni de conexión a
Neo4j, y probar de nuevo los `curl` del paso 5 contra `0.0.0.0:8088` /
`192.168.1.205:8088`.

### 8. Parar / reiniciar

```bash
sudo systemctl stop s9-knowledge-viewer
sudo systemctl restart s9-knowledge-viewer
sudo systemctl disable s9-knowledge-viewer     # si hay que desinstalarlo
```

### 9. Volver a mock si hay problemas (rollback rápido)

Si el provider `neo4j` falla en producción (Neo4j caído, credenciales rotas,
etc.) y se necesita que el visor siga respondiendo con algo mientras se
investiga:

```bash
cd /opt/knowledge-services/s9-knowledge-repo/viewer
sed -i 's/^S9K_GRAPH_PROVIDER=neo4j/S9K_GRAPH_PROVIDER=mock/' .env
sudo systemctl restart s9-knowledge-viewer
curl http://127.0.0.1:8088/api/status   # debe responder "provider": "mock"
```

Esto hace que el visor sirva los datos de ejemplo (`examples/sample_graph.json`)
en vez de fallar — útil para verificar que el problema es de conectividad a
Neo4j y no del propio visor. Revertir a `neo4j` cuando se resuelva la causa.

## Jobs panel / worker manual (v0.2.4)

Además del visor de grafo, `viewer/.env` puede incluir `S9K_JOBS_DB` para que
el panel de solo lectura `/jobs` muestre la cola de trabajos:

```env
S9K_JOBS_DB=/opt/knowledge-services/s9-knowledge-repo/state/jobs.db
```

Probarlo manualmente (sin tocar Neo4j ni datos reales):

```bash
cd /opt/knowledge-services/s9-knowledge-repo
export S9K_JOBS_DB=/opt/knowledge-services/s9-knowledge-repo/state/jobs.db
python data-engine/app/cli/jobs.py create --type echo --workspace leyenda \
    --payload '{"message":"prueba vm105"}'
python data-engine/app/jobs/worker.py --once --limit 1
python data-engine/app/cli/jobs.py list --workspace leyenda
```

Luego, con el visor arrancado (paso 5 de esta guía), abrir
`http://192.168.1.205:8088/jobs` y comprobar que aparece el job `echo` en
estado `complete`. Detalle completo en `docs/15-jobs-worker-panel.md`. Esta
fase no instala systemd para el worker; se ejecuta manualmente o vía
`scripts/run-jobs-worker.sh`.

## Qué NO hace esta guía

- No abre el visor a Internet ni configura Cloudflare/dominio externo — el
  servicio escucha en `0.0.0.0:8088` solo dentro de la LAN de VM105.
- No expone Neo4j ni Ollama.
- No modifica `property-graph`, Nextcloud, ni SilverBullet.
- No implementa login/permisos ni panel de gestión (fuera de alcance de v0.2).

## Verificación final esperada

- `http://192.168.1.205:8088/` abre y muestra "Proveedor actual: neo4j".
- `http://192.168.1.205:8088/api/status` → `"neo4j_connected": true`.
- Buscar "Tamori" en `/graph` encuentra "Agasha Tamori" real.
- Ficha de nodo y ficha de relación muestran datos reales del workspace `leyenda`.

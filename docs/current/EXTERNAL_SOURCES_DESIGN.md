# Diseño de Fuentes Externas — Pipeline de Grafo de Conocimiento RPG

**Versión:** 1.0 — 2026-07-11
**Proyecto:** `/opt/knowledge-services/property-graph`
**Servidor:** VM105 (192.168.1.205)

---

## 1. Objetivo y flujo general

El pipeline de fuentes externas permite incorporar contenido de diversas procedencias al grafo de conocimiento RPG almacenado en Neo4j. El flujo de alto nivel es el siguiente:

```
Usuario (panel web / CLI)
  │
  ▼
Crear trabajo en la cola (jobs.db)
  │ source_kind, workspace, source_url o source_path
  │
  ▼
Revisión automática del tipo de fuente
  ├─ ¿Faltan metadatos de sesión? → status: needs_metadata
  └─ Completo → status: pending / ready
  │
  ▼
Descarga o lectura del contenido
  ├─ YouTube: yt-dlp (solo audio, WAV/MP3)
  ├─ Web: HTTP GET + extracción de texto principal
  ├─ Audio Nextcloud: lectura del fichero .m4a/.mp3
  └─ Texto/PDF/Libro: lectura directa
  │
  ▼
Transcripción (si audio o vídeo)
  │ status: transcribing → Whisper → output_transcript_path
  │
  ▼
Extracción de entidades y relaciones
  │ status: extracting → LLM + rpg_schema → JSON
  │
  ▼
Ingesta en Neo4j
  │ Nodos Document / Transcript / Entity
  │ Relaciones según el schema del proyecto
  │ status: completed
  │
  ▼
Panel de gestión
  └─ Ver transcripción, entidades, grafo, estado
```

---

## 2. Tipos de fuente y `source_kind`

| `source_kind`  | Descripción                                                  |
|----------------|--------------------------------------------------------------|
| `book`         | Libro completo (PDF o texto), contenido de lore de campaña   |
| `pdf`          | Documento PDF genérico (manual, suplemento, ficha)           |
| `audio`        | Grabación de sesión de juego (Nextcloud, WAV/M4A/MP3)        |
| `transcript`   | Transcripción ya existente en texto plano o markdown         |
| `text`         | Nota de texto, fragmento de lore, entrada de diario          |
| `image`        | Imagen de mapa, ilustración, ficha escaneada                 |
| `youtube`      | Vídeo de YouTube (se descarga solo el audio)                 |
| `web`          | Página web: artículo, wiki, foro, blog                       |
| `manual_note`  | Nota introducida manualmente por el usuario desde el panel   |
| `test`         | Trabajos de prueba internos, no aparecen en producción       |

---

## 3. Modelo de trabajos

### 3.1 Base de datos

- **Ruta:** `/opt/knowledge-services/property-graph/state/jobs.db`
- **Motor:** SQLite con WAL journal
- **Módulo:** `app/jobs/job_store.py`

### 3.2 Tabla `jobs` — campos

| Campo                         | Tipo    | Descripción                                              |
|-------------------------------|---------|----------------------------------------------------------|
| `job_id`                      | TEXT PK | UUID4 generado al crear el trabajo                       |
| `workspace`                   | TEXT    | Espacio de trabajo (p.ej. `leyenda`, `global`)           |
| `source_kind`                 | TEXT    | Tipo de fuente (ver sección 2)                           |
| `source_url`                  | TEXT    | URL de origen (YouTube, web, etc.)                       |
| `source_path`                 | TEXT    | Ruta local o Nextcloud del fichero                       |
| `source_title`                | TEXT    | Título del contenido                                     |
| `source_author`               | TEXT    | Autor o canal de origen                                  |
| `source_date`                 | TEXT    | Fecha de publicación/grabación (ISO-8601)                |
| `status`                      | TEXT    | Estado actual (ver sección 3.3)                          |
| `created_at`                  | TEXT    | Timestamp ISO-8601 UTC de creación                       |
| `updated_at`                  | TEXT    | Timestamp ISO-8601 UTC de última actualización           |
| `started_at`                  | TEXT    | Timestamp de inicio del procesamiento                    |
| `finished_at`                 | TEXT    | Timestamp de finalización (completed/failed/etc.)        |
| `error_message`               | TEXT    | Mensaje de error si status=failed                        |
| `requires_metadata`           | INTEGER | 1 si el trabajo espera metadatos adicionales             |
| `session_number`              | INTEGER | Número de sesión RPG (para audio/youtube de campaña)     |
| `session_title`               | TEXT    | Título de la sesión                                      |
| `session_date`                | TEXT    | Fecha de la sesión (YYYY-MM-DD)                          |
| `campaign_arc`                | TEXT    | Arco narrativo al que pertenece                          |
| `visibility`                  | TEXT    | Visibilidad del contenido (public, private, gm-only)     |
| `knowledge_layer`             | TEXT    | Capa de conocimiento (world, campaign, session, meta)    |
| `output_transcript_path`      | TEXT    | Ruta al fichero de transcripción generado                |
| `output_markdown_path`        | TEXT    | Ruta al markdown de salida                               |
| `output_json_path`            | TEXT    | Ruta al JSON de entidades extraídas                      |
| `neo4j_nodes_created`         | INTEGER | Nodos creados en Neo4j (default 0)                       |
| `neo4j_relationships_created` | INTEGER | Relaciones creadas en Neo4j (default 0)                  |
| `manual_review_required_count`| INTEGER | Entidades que requieren revisión manual (default 0)      |

### 3.3 Estados válidos

```
pending          → Trabajo en espera, listo para procesar
needs_metadata   → Falta información de sesión (número, título, fecha)
ready            → Metadatos completos, listo para encolar
processing       → En proceso general (descarga, lectura)
transcribing     → Generando transcripción (Whisper)
extracting       → Extrayendo entidades con LLM
completed        → Proceso finalizado correctamente
failed           → Error durante el proceso (ver error_message)
ignored          → Descartado manualmente por el usuario
cancelled        → Cancelado antes de completar
```

Transiciones automáticas de `started_at` / `finished_at`:
- `started_at` se fija al entrar en `processing`, `transcribing` o `extracting`.
- `finished_at` se fija al llegar a `completed`, `failed`, `ignored` o `cancelled`.

### 3.4 API del módulo `app/jobs/job_store.py`

```python
# Constantes exportadas
DEFAULT_DB_PATH   # /opt/knowledge-services/property-graph/state/jobs.db
VALID_STATUSES    # set de estados válidos
VALID_SOURCE_KINDS  # set de source_kinds válidos

# Funciones de módulo
init_db(db_path=DEFAULT_DB_PATH) -> None
    """Crea la tabla jobs si no existe. Idempotente."""

create_job(workspace, source_kind, source_url=None, source_path=None,
           db_path=DEFAULT_DB_PATH, **optional) -> str  # job_id
    """
    Inserta un trabajo. Valida source_kind y workspace no vacío.
    Si source_kind in {audio, youtube} y no hay session_number/session_title
    → status='needs_metadata', requires_metadata=1.
    Campos opcionales: source_title, source_author, source_date,
    session_number, session_title, session_date, campaign_arc,
    visibility, knowledge_layer, output_*, neo4j_*.
    """

get_job(job_id, db_path=DEFAULT_DB_PATH) -> dict | None
    """Devuelve el trabajo como dict, o None si no existe."""

list_jobs(status=None, workspace=None, db_path=DEFAULT_DB_PATH) -> list[dict]
    """Lista trabajos con filtro opcional. Orden: created_at DESC."""

update_job(job_id, db_path=DEFAULT_DB_PATH, **fields) -> bool
    """
    Actualiza campos arbitrarios. updated_at se actualiza siempre.
    Valida status y source_kind si están en fields.
    """

set_status(job_id, status, error_message=None, db_path=DEFAULT_DB_PATH) -> bool
    """
    Helper para cambiar estado. Ajusta started_at/finished_at
    según las transiciones definidas.
    """

infer_session_metadata(filename) -> dict
    """
    Infiere session_number, session_title, session_date desde el nombre
    del fichero de audio. Usa expresiones regulares, sin dependencias externas.
    Devuelve {session_number: int|None, session_title: str|None, session_date: str|None}.
    """

# Clase de conveniencia
class JobStore:
    def __init__(self, db_path=DEFAULT_DB_PATH)
    # Todos los métodos anteriores como métodos de instancia
    # infer_session_metadata también disponible como método estático
```

**CLI:**
```bash
# Crear/verificar la BD
python app/jobs/job_store.py --init [--db /ruta/alternativa/jobs.db]

# Ejecutar selftest con BD temporal
python app/jobs/job_store.py --selftest
```

---

## 4. Fuente: YouTube

### 4.1 Flujo

1. Usuario introduce URL de YouTube en el panel.
2. Se crea un trabajo con `source_kind='youtube'`, `source_url=URL`.
3. Si `session_number` / `session_title` no están presentes → `needs_metadata`.
4. El usuario completa los metadatos de sesión → `status='ready'`.
5. El procesador llama a **yt-dlp** descargando **solo el audio** (formato WAV o MP3, no el vídeo).
6. El audio descargado se pasa al pipeline de transcripción (Whisper).
7. La transcripción se ingesta como nodo `Transcript` en Neo4j, vinculado al nodo `Document` con `source_kind='youtube'`.

### 4.2 Metadatos a preservar

| Campo                   | Descripción                                     |
|-------------------------|-------------------------------------------------|
| `source_url`            | URL completa del vídeo de YouTube               |
| `source_title`          | Título del vídeo                                |
| `source_author`         | Nombre del canal                                |
| `source_date`           | Fecha de publicación (upload_date de yt-dlp)    |
| `video_id`              | ID del vídeo (extraído de la URL)               |
| `downloaded_audio_path` | Ruta local del audio descargado                 |
| `output_transcript_path`| Ruta del fichero de transcripción               |

### 4.3 Carpeta de salida

```
/opt/knowledge-services/property-graph/output/<workspace>/youtube/
  <video_id>_audio.mp3
  <video_id>_transcript.md
  <video_id>_entities.json
```

### 4.4 Representación en Neo4j

```
(d:Document {source_kind: 'youtube', source_url: ..., source_title: ...,
             source_author: ..., source_date: ..., workspace: ...})
(t:Transcript {text: ..., source_kind: 'youtube', ...})
(t)-[:EXTRACTED_FROM]->(d)
(t)-[:HAS_SESSION]->(s:Session {number: ..., title: ...})
```

### 4.5 Módulo base existente

Ya existe `app/youtube/fetch_youtube.py` y el binario `property-graph-youtube`.
**No modificar.** El módulo `app/jobs/` debe integrarse con él llamándolo
como subproceso o importando sus funciones, manteniendo la trazabilidad
mediante el `job_id`.

---

## 5. Fuente: Web

### 5.1 Flujo

1. Usuario introduce URL de una página web.
2. Se crea trabajo con `source_kind='web'`, `source_url=URL`.
3. El procesador descarga el HTML (`requests.get`).
4. Se extrae el texto principal (trafilatura / readability-lxml / BeautifulSoup4).
5. Se limpia el texto (eliminar boilerplate, normalizar espacios).
6. Se guarda el texto limpio en la carpeta de salida.
7. Se extrae con LLM y se ingesta en Neo4j.

### 5.2 Herramientas candidatas (NO instaladas aún)

| Herramienta        | Propósito                              | Nota                                    |
|--------------------|----------------------------------------|-----------------------------------------|
| `trafilatura`      | Extracción de texto principal          | Primera opción recomendada              |
| `readability-lxml` | Alternativa, estilo Mozilla Readability| Segunda opción                          |
| `beautifulsoup4`   | Parsing HTML genérico                  | Fallback para páginas no estándar       |
| `requests`         | Descarga HTTP                          | Ya disponible en el venv del proyecto   |

**PENDIENTE:** instalar `trafilatura` y `requests` en el venv cuando se implemente este módulo.
No instalar globalmente; usar siempre `.venv/bin/pip install`.

### 5.3 Campos específicos de fuente web

| Campo        | Descripción                                        |
|--------------|----------------------------------------------------|
| `source_url` | URL completa de la página                          |
| `domain`     | Dominio de la URL (extraído con `urllib.parse`)    |
| `retrieved_at` | Timestamp ISO-8601 de la descarga                |
| `text_hash`  | SHA-256 del texto limpio (para deduplicación)      |

### 5.4 Carpeta de salida

```
/opt/knowledge-services/property-graph/output/web/
  <domain>_<hash8>_text.txt
  <domain>_<hash8>_entities.json
```

### 5.5 Representación en Neo4j

```
(d:Document {source_kind: 'web', source_url: ..., domain: ...,
             retrieved_at: ..., workspace: ...})
```

---

## 6. Fuente: Audio Nextcloud

### 6.1 Flujo

1. El usuario o el scanner (`property-graph-audio-scan`) detecta un fichero de audio nuevo en Nextcloud.
2. Se crea un trabajo con `source_kind='audio'`, `source_path=<ruta_nextcloud>`.
3. `infer_session_metadata(filename)` intenta extraer número, título y fecha de la sesión del nombre del fichero:
   - Si infiere el `session_number` → `status='pending'` (o `'ready'`).
   - Si no puede → `status='needs_metadata'`, `requires_metadata=1`.
4. Si `needs_metadata`: el panel muestra el trabajo al usuario para que complete los campos.
5. Con metadatos completos → transcripción con Whisper.
6. Extracción de entidades → Neo4j.

### 6.2 Nombres de fichero soportados

```
Sesion 12 - El Arbol Blanco.m4a
  → session_number=12, session_title='El Arbol Blanco', session_date=None

2026-07-10 - Sesion 12 - El Arbol Blanco.m4a
  → session_number=12, session_title='El Arbol Blanco', session_date='2026-07-10'

sesion_5_batalla_del_crepusculo.mp3
  → session_number=5, session_title='batalla del crepusculo', session_date=None

grabacion.mp3
  → session_number=None → needs_metadata
```

### 6.3 Módulos base existentes

- `app/audio/transcribe_audio.py` — transcripción con Whisper.
- `app/audio/audio_utils.py` — utilidades de audio.
- Binarios: `property-graph-audio`, `property-graph-audio-scan`.

**No modificar.** El módulo `app/jobs/` se integra llamándolos como subproceso
o importando sus funciones, registrando el progreso mediante `set_status`.

---

## 7. Representación en Neo4j

El schema del proyecto (en `app/schemas/rpg_schema.py`) ya define los tipos
de nodo y relación necesarios. Esta sección documenta cómo se usan para
las fuentes externas.

### 7.1 Tipos de nodo

| Nodo         | Propiedades clave                                                |
|--------------|------------------------------------------------------------------|
| `Document`   | `source_kind`, `source_url`, `source_path`, `source_title`,     |
|              | `source_author`, `source_date`, `workspace`, `knowledge_layer`  |
| `Transcript` | `text`, `source_kind`, `language`, `model_used`, `workspace`    |
| `Entity`     | `name`, `entity_type`, `description`, `workspace`               |
| `Session`    | `number`, `title`, `date`, `campaign_arc`, `workspace`          |
| `Image`      | `path`, `description`, `source_kind`, `workspace`               |

### 7.2 Relaciones

| Relación                    | Desde → Hacia               | Descripción                             |
|-----------------------------|-----------------------------|-----------------------------------------|
| `EXTRACTED_FROM`            | Transcript → Document       | La transcripción proviene del documento |
| `HAS_TRANSCRIPT`            | Document → Transcript       | El documento tiene transcripción        |
| `APPEARS_IN`                | Entity → Transcript         | Entidad mencionada en transcripción     |
| `SOURCE_OF`                 | Document → Entity           | Documento es fuente de la entidad       |
| `HAS_IMAGE`                 | Entity → Image              | Imagen asociada a la entidad            |
| `BELONGS_TO_SESSION`        | Document → Session          | Audio/youtube pertenece a una sesión    |

---

## 8. Panel de gestión futuro "S9 Knowledge"

### 8.1 Sección "Fuentes / Importar"

El panel web (parte de S9-RC o aplicación independiente) incluirá una sección
para gestionar la importación de fuentes externas. Campos del formulario:

| Campo              | Tipo              | Descripción                                      |
|--------------------|-------------------|--------------------------------------------------|
| URL o ruta         | text/file         | Origen del contenido                             |
| Workspace          | select            | Espacio de trabajo destino                       |
| Tipo detectado     | auto / select     | `source_kind` inferido o seleccionado manualmente|
| Sesión             | number            | Número de sesión RPG (si aplica)                 |
| Fecha              | date              | Fecha de la sesión o publicación                 |
| Visibilidad        | select            | public / private / gm-only                       |
| Capa de conocimiento | select          | world / campaign / session / meta                |
| Crear trabajo      | button            | Envía el formulario y crea el trabajo en la cola |

### 8.2 Estados mostrados en el panel

| Estado mostrado     | Status interno   | Acciones disponibles                         |
|---------------------|-----------------|----------------------------------------------|
| Pendiente           | pending / ready  | Procesar, Cancelar, Ignorar                  |
| Necesita metadatos  | needs_metadata   | Editar metadatos, Ignorar                    |
| Procesando          | processing / transcribing / extracting | (solo lectura, progreso) |
| Completado          | completed        | Ver transcripción, Ver entidades, Ver grafo  |
| Error               | failed           | Ver error, Reintentar, Ignorar               |
| Ignorado            | ignored          | Restaurar a pending                          |
| Cancelado           | cancelled        | Restaurar a pending                          |

---

## 9. Endpoints futuros del panel

Los siguientes endpoints serán implementados en la capa de API del panel:

```
GET  /sources                          → Página principal de fuentes
GET  /sources/new                      → Formulario para añadir nueva fuente

GET  /api/jobs                         → Lista de trabajos (filtros: status, workspace)
GET  /api/jobs/{job_id}                → Detalle de un trabajo
POST /api/sources                      → Crear nuevo trabajo desde formulario
POST /api/jobs/{job_id}/process        → Lanzar procesamiento de un trabajo
POST /api/jobs/{job_id}/retry          → Reintentar trabajo fallido
POST /api/jobs/{job_id}/ignore         → Marcar como ignorado
POST /api/jobs/{job_id}/cancel         → Cancelar trabajo en curso
GET  /api/jobs/{job_id}/transcript     → Obtener transcripción generada
GET  /api/jobs/{job_id}/entities       → Obtener entidades extraídas
```

---

## 10. Reglas de seguridad

1. **Sin procesamiento automático de URLs externas** sin confirmación explícita del usuario. El trabajo se crea en `pending`; el usuario debe lanzar el procesamiento.
2. **Sin descargas masivas:** máximo un trabajo en procesamiento activo simultáneo por defecto. Configurar límite en `config/settings.yaml`.
3. **No borrar originales:** los ficheros de audio en Nextcloud son de solo lectura para este pipeline. Solo se escriben ficheros en las carpetas de `output/`.
4. **Nextcloud en solo lectura:** el pipeline solo lee desde Nextcloud. La carpeta de salida controlada es `output/<workspace>/` en el servidor local.
5. **Validar rutas:** `source_path` debe resolver dentro de rutas permitidas. No se aceptan rutas con `..` ni fuera del workspace.
6. **Validar dominios web:** mantener lista de dominios bloqueados / requerir confirmación para dominios nuevos.
7. **Panel no expuesto a Internet:** el panel de gestión debe estar solo accesible en red local o Tailscale. Nunca en puerto público sin autenticación.
8. **Trazabilidad completa:** cada trabajo registra `source_url` / `source_path`, timestamps de todas las transiciones de estado, y el número de nodos/relaciones creados en Neo4j.
9. **Sin secretos en la BD:** `jobs.db` no almacena credenciales ni tokens. Las claves de API van en `config/runtime.env`.

---

## 11. Pruebas mínimas futuras

### 11.1 Audio local (IMPLEMENTADO — base disponible)

```bash
# Crear trabajo de audio con metadatos inferidos
python -c "
from app.jobs.job_store import create_job, infer_session_metadata, get_job
meta = infer_session_metadata('Sesion 12 - El Arbol Blanco.m4a')
job_id = create_job(
    workspace='leyenda',
    source_kind='audio',
    source_path='/mnt/nextcloud/audio/Sesion 12 - El Arbol Blanco.m4a',
    **meta
)
print('job_id:', job_id)
print('job:', get_job(job_id))
"

# Verificar que audio sin metadatos → needs_metadata
python -c "
from app.jobs.job_store import create_job, get_job
job_id = create_job('leyenda', 'audio', source_path='/mnt/audio/grabacion.mp3')
j = get_job(job_id)
assert j['status'] == 'needs_metadata', j['status']
print('OK: needs_metadata verificado')
"
```

**Estado:** `app/jobs/job_store.py` implementado y probado. La integración con
`property-graph-audio` / `transcribe_audio.py` está **PENDIENTE**.

### 11.2 YouTube (PENDIENTE)

```bash
# Futuro: cuando se integre la cola con fetch_youtube.py
python -c "
from app.jobs.job_store import create_job, get_job
job_id = create_job(
    workspace='leyenda',
    source_kind='youtube',
    source_url='https://www.youtube.com/watch?v=EJEMPLO',
    source_title='Ejemplo de partida',
    session_number=15,
    session_title='El Puente Roto',
)
print('job_id:', job_id)
"
# Luego: property-graph-youtube --job-id <job_id> --process
```

**Estado:** `app/youtube/fetch_youtube.py` y `property-graph-youtube` existen.
**PENDIENTE:** integrar con la cola de trabajos (`job_id` como parámetro).

### 11.3 Web (PENDIENTE)

```bash
# Futuro: cuando se implemente app/web/fetch_web.py
python -c "
from app.jobs.job_store import create_job, get_job
job_id = create_job(
    workspace='global',
    source_kind='web',
    source_url='https://ejemplo.com/articulo-rpg',
    source_title='Artículo de ejemplo',
)
print('job_id:', job_id)
"
# Luego: property-graph-web --job-id <job_id> --process
```

**Estado:** módulo `app/web/` **NO EXISTE AÚN**. Falta implementar:
- `app/web/__init__.py`
- `app/web/fetch_web.py` (descarga + extracción de texto)
- Instalación de `trafilatura` en el venv
- Binario `property-graph-web`

### 11.4 Verificación de trazabilidad

```bash
# Comprobar que source_url/source_path se guardaron correctamente
python -c "
from app.jobs.job_store import list_jobs
jobs = list_jobs(workspace='leyenda')
for j in jobs:
    print(j['job_id'][:8], j['source_kind'], j['status'], j['source_url'] or j['source_path'])
"
```

---

## Apéndice: estructura de directorios esperada

```
/opt/knowledge-services/property-graph/
├── app/
│   ├── jobs/
│   │   ├── __init__.py           ← (nuevo, vacío)
│   │   └── job_store.py          ← (nuevo, este diseño)
│   ├── audio/                    ← existente, no modificar
│   ├── youtube/                  ← existente, no modificar
│   └── web/                      ← PENDIENTE crear
├── state/
│   └── jobs.db                   ← creado por --init
├── output/
│   ├── <workspace>/
│   │   ├── audio/
│   │   └── youtube/
│   └── web/
└── docs/
    ├── RPG_GRAPH_MODEL_UPDATE.md  ← existente
    └── EXTERNAL_SOURCES_DESIGN.md ← (nuevo, este documento)
```

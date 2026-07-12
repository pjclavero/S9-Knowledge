# 14 · Worker de ingesta multimedia (v0.2.4)

## Objetivo

Automatizar el primer tramo del procesado de fuentes multimedia (vídeo/audio):

```
carpeta staging con vídeos/audio
  → detección automática (scanner)
  → registro de job
  → extracción de audio si es vídeo (ffmpeg)
  → transcripción (motor configurable)
  → generación de Markdown revisable
  → estado del job actualizado
  → preparado para ingesta posterior
```

## Qué automatiza

- Detección de archivos de vídeo/audio soltados en `staging/media/`.
- Cálculo de `sha256`, deduplicación por contenido y sondeo de metadatos con
  `ffprobe` (duración, formato, códecs).
- Extracción/normalización de audio a WAV mono 16 kHz con `ffmpeg`.
- Transcripción mediante un motor **configurable** (`stub` por defecto;
  `faster-whisper` opcional).
- Escritura de un **Markdown revisable** por fuente, con metadatos, transcripción
  con marcas de tiempo y una sección de observaciones de calidad.
- Seguimiento de estado por job (JSON) y, opcionalmente, reflejo en la cola
  SQLite `jobs.db`.

## Qué NO hace todavía (importante)

- **No escribe en Neo4j.** No ejecuta ninguna ingesta al grafo.
- No procesa PDFs (eso es del pipeline `ingest_rpg.py`).
- No genera resumen automático (solo deja un placeholder).
- No es un daemon: el worker se ejecuta manualmente (o por cron/systemd-timer
  en el futuro).
- No descarga modelos de Whisper por sí solo en tests ni en `stub`.

Cada Markdown generado lleva explícitamente `Preparado para ingesta: no`. La
fase actual produce **fuente revisable por un humano**, no datos de grafo.

## Carpetas (configurables por entorno)

| Variable | Contenido | Default (relativo al repo) |
|---|---|---|
| `S9K_MEDIA_STAGING_DIR` | Entrada: vídeos/audio a procesar | `staging/media` |
| `S9K_MEDIA_OUTPUT_DIR` | Registro JSON de jobs multimedia | `output/media` |
| `S9K_MEDIA_AUDIO_DIR` | WAV extraídos | `output/audio` |
| `S9K_MEDIA_TRANSCRIPT_DIR` | Markdown + JSON de transcripción | `output/transcriptions` |
| `S9K_MEDIA_LOG_DIR` | Logs del worker | `logs/media` |

Todas estas rutas están bajo `output/`, `staging/`, `logs/` → **ignoradas por
git**. Los binarios (`*.mp4`, `*.wav`, ...) también están en `.gitignore`. No se
versiona ningún vídeo, audio, transcripción ni salida pesada.

## Variables de entorno

```env
S9K_MEDIA_STAGING_DIR=/opt/knowledge-services/s9-knowledge-repo/staging/media
S9K_MEDIA_OUTPUT_DIR=/opt/knowledge-services/s9-knowledge-repo/output/media
S9K_MEDIA_AUDIO_DIR=/opt/knowledge-services/s9-knowledge-repo/output/audio
S9K_MEDIA_TRANSCRIPT_DIR=/opt/knowledge-services/s9-knowledge-repo/output/transcriptions
S9K_MEDIA_LOG_DIR=/opt/knowledge-services/s9-knowledge-repo/logs/media
S9K_MEDIA_DEFAULT_WORKSPACE=leyenda
S9K_MEDIA_TRANSCRIBER=stub          # stub | faster-whisper
S9K_MEDIA_LANGUAGE=es
S9K_MEDIA_MAX_DURATION_SECONDS=7200
S9K_MEDIA_DRY_RUN=false
S9K_MEDIA_JOBSTORE_BRIDGE=false     # true = reflejar jobs en jobs.db (SQLite)

# Solo si S9K_MEDIA_TRANSCRIBER=faster-whisper
S9K_FASTER_WHISPER_MODEL=small
S9K_FASTER_WHISPER_DEVICE=cpu
S9K_FASTER_WHISPER_COMPUTE_TYPE=int8
```

## Comandos CLI

La CLI vive en `data-engine/app/cli/media_jobs.py`. El paquete `data-engine`
lleva guion y **no** es importable como `data_engine`; la convención del repo es
que `data-engine/app/` es la raíz de imports (`from media...`, `from jobs...`).
Por eso la CLI se invoca por ruta de archivo (hace bootstrap de `sys.path`):

```bash
python data-engine/app/cli/media_jobs.py scan   --workspace leyenda
python data-engine/app/cli/media_jobs.py list   --workspace leyenda
python data-engine/app/cli/media_jobs.py worker --workspace leyenda --limit 1
python data-engine/app/cli/media_jobs.py show   --workspace leyenda --source-id <SOURCE_ID>
```

Equivalente con `data-engine/app` en `PYTHONPATH`:

```bash
PYTHONPATH=data-engine/app python -m cli.media_jobs scan --workspace leyenda
```

Flags útiles: `--dry-run` (scan/worker, no persiste ni procesa), `--limit N`,
`--source-id`, `--once`.

## Ejemplo de flujo

```bash
# 1. Dejar archivos en staging
cp "Sesion 6 - El Bosque.mp3" staging/media/

# 2. Escanear (crea jobs pending)
python data-engine/app/cli/media_jobs.py scan --workspace leyenda
#   → Nuevos jobs: 1 | ya existentes: 0 | ignorados: 0

# 3. Procesar 1 job
python data-engine/app/cli/media_jobs.py worker --workspace leyenda --limit 1
#   → Procesados: 1 | fallidos: 0 | omitidos: 0

# 4. Revisar el Markdown generado
cat output/transcriptions/leyenda/media_<hash>.md
```

## Formato del Markdown generado

```markdown
# Transcripción — <nombre archivo>

## Metadatos
- Source ID / Source kind / Workspace / Archivo original / SHA256 / Tamaño /
  Duración / Fecha de procesado / Motor / Modelo / Idioma / Estado
- Preparado para ingesta: no

## Resumen rápido
Pendiente de resumen automático.

## Transcripción con marcas de tiempo
[00:00:00] texto...

## Observaciones de calidad
- Ruido / Cortes / Varias voces / Música / Confianza aproximada
- Revisión humana requerida: sí
```

## Cómo probar con stub (sin Whisper)

El transcriptor `stub` no requiere Whisper ni GPU. Es el modo por defecto:

```bash
export S9K_MEDIA_TRANSCRIBER=stub
python data-engine/app/cli/media_jobs.py scan   --workspace leyenda
python data-engine/app/cli/media_jobs.py worker --workspace leyenda --limit 1
```

> Nota: la extracción de audio usa `ffmpeg` real. En un entorno sin `ffmpeg`
> (p.ej. un PC de desarrollo Windows sin instalarlo) el worker marca el job como
> `failed` con un mensaje controlado ("ffmpeg no está instalado"), sin romperse.
> Los tests cubren el camino feliz mockeando `ffmpeg`/`ffprobe`.

## Cómo probar con faster-whisper (si está disponible)

```bash
pip install faster-whisper            # solo en el entorno donde se quiera usar
export S9K_MEDIA_TRANSCRIBER=faster-whisper
export S9K_FASTER_WHISPER_MODEL=small
export S9K_FASTER_WHISPER_DEVICE=cpu
export S9K_FASTER_WHISPER_COMPUTE_TYPE=int8
python data-engine/app/cli/media_jobs.py worker --workspace leyenda --limit 1
```

El modelo se descarga/carga de forma perezosa la primera vez que se transcribe,
nunca en el import ni en tests. Si `faster-whisper` no está instalado, el worker
falla con un mensaje claro sugiriendo volver a `stub`.

**Motor recomendado para VM105** (según prueba real del servidor): `faster-whisper`
en **CPU con `compute_type=int8`** (no requiere GPU). Si no hay motor local
disponible, `stub` deja el pipeline funcional y esta guía explica cómo instalar
`faster-whisper` después.

Motores futuros, solo documentados (aún no implementados): `whisper.cpp`,
`external`. La fábrica de transcriptores devuelve un error claro si se piden.

## Cómo desplegar en VM105

1. Actualizar el repo en `/opt/knowledge-services/s9-knowledge-repo` (`git pull`).
2. Usar el venv existente (viewer o data-engine) o crear uno para data-engine.
3. Exportar las variables `S9K_MEDIA_*` (o dejarlas en un `.env`/EnvironmentFile).
4. Crear las carpetas de staging/output/logs (el worker las crea al vuelo, pero
   `staging/media` conviene crearla para soltar archivos).
5. Ejecutar `scripts/run-media-worker.sh` manualmente para validar.
6. Instalar `ffmpeg` en VM105 si no está (`apt install ffmpeg`).
7. Opcional: `pip install faster-whisper` y `S9K_MEDIA_TRANSCRIBER=faster-whisper`.

## Cómo convertirlo luego en systemd/timer

Cuando el flujo esté validado, se puede automatizar con un `systemd.timer` que
dispare un `oneshot` ejecutando `scripts/run-media-worker.sh` cada N minutos:

```ini
# /etc/systemd/system/s9-media-worker.service  (oneshot, NO daemon)
[Unit]
Description=S9 Knowledge media worker (oneshot)
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/opt/knowledge-services/s9-knowledge-repo
EnvironmentFile=/opt/knowledge-services/s9-knowledge-repo/media.env
ExecStart=/opt/knowledge-services/s9-knowledge-repo/scripts/run-media-worker.sh
```

```ini
# /etc/systemd/system/s9-media-worker.timer
[Unit]
Description=Ejecuta el media worker periódicamente

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

> Esta fase **no** instala systemd; solo deja el script y esta plantilla como
> referencia. No se toca el systemd de producción existente.

## Cómo pasaría después a ingesta al grafo (fase futura)

El Markdown/JSON de transcripción quedan en `output/transcriptions/<workspace>/`.
Una fase posterior (fuera de alcance aquí) podría:

1. Presentar los Markdown en el panel de gestión para revisión/edición humana.
2. Marcar la fuente como "aprobada para ingesta".
3. Alimentar `ingest_rpg.py` (u otro ingestor) con el texto revisado, aplicando
   los metadatos de sesión (`session_number`, `visibility`, `knowledge_layer`).
4. Solo entonces se escribiría en Neo4j.

## Riesgos y límites

- Depende de `ffmpeg`/`ffprobe` en el sistema; sin ellos, el sondeo degrada y la
  extracción de audio falla de forma controlada (job → `failed`).
- El `stub` produce texto ficticio: útil para validar el pipeline, inútil como
  contenido real.
- `faster-whisper` en CPU es más lento que en GPU; para sesiones largas conviene
  ajustar `S9K_MEDIA_MAX_DURATION_SECONDS` o el modelo.
- La deduplicación es por `sha256` del contenido: un mismo audio recodificado
  (bytes distintos) se trataría como fuente nueva.
- No hay control de concurrencia entre varios workers a la vez sobre el mismo
  workspace (se asume ejecución manual/secuencial en esta fase).
```

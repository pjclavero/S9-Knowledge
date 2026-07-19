# Plan de runtime multimedia v1 (OLA 2B — Lote 2, P6)

> **Alcance de este documento.** Es *exclusivamente un plan*. No descarga
> modelos, no ejecuta OCR real, no procesa corpus privado, no realiza llamadas
> externas y no modifica ningún módulo de producto. Diseña cómo *debería*
> ejecutarse el runtime multimedia (OCR / visión / texto embebido) alineado con
> el contrato ya integrado `data-engine/app/media/multimedia_contract.py`
> (`multimedia-artifact/internal-v1`) y con el pipeline ASR existente
> (`data-engine/app/media/transcriber.py`), sin tocar ninguno de los dos.

Base de alineación (solo lectura, no se modifican):

- Contrato: `data-engine/app/media/multimedia_contract.py`
  (`CONTRACT_ID = "multimedia-artifact/internal-v1"`).
- ASR: `data-engine/app/media/transcriber.py`
  (`Transcriber` / `StubTranscriber` / `FasterWhisperTranscriber`).

**En OLA 2B no se descargan modelos ni se ejecuta OCR/visión real.** Todo lo
descrito aquí se implementará en olas posteriores bajo autorización explícita;
mientras tanto, el runtime por defecto es *stub* y `NOT_EXECUTED`.

---

## 1. Principios rectores

1. **Extender, no duplicar.** El contrato `MultimediaArtifact` ya unifica los
   cuatro orígenes (`EMBEDDED_TEXT`, `ASR_TEXT`, `OCR_TEXT`,
   `IMAGE_DESCRIPTION` y subtipos visuales). El runtime *produce* artefactos que
   validan contra ese contrato; no define un segundo modelo de datos.
2. **ASR no se reimplementa.** El audio ya lo cubre `media.transcriber` y se
   proyecta con `MultimediaArtifact.from_transcript_result()`. Este plan cubre el
   *resto* (texto embebido, OCR e interpretación visual) con la misma disciplina:
   selección por configuración, carga perezosa y stub por defecto.
3. **Dry-run y auditable.** Cada artefacto lleva su procedencia (`source_id`,
   `file_hash`), método de extracción (`extraction_method`), `model` y
   `confidence`. Nada se ingiere en el grafo desde este runtime: solo produce
   artefactos revisables.
4. **Local primero, red opt-in.** El procesamiento por defecto es local. Cualquier
   proveedor externo es explícito, apagado por defecto y `NOT_EXECUTED` sin
   autorización.
5. **Sin modelos en tiempo de import.** Igual que `transcriber.py`, ningún motor
   descarga ni carga modelos al importar el módulo; la carga es perezosa y solo
   ocurre en la primera llamada real (que en OLA 2B no se produce).

---

## 2. Espejo del patrón ASR existente

El runtime OCR/visión replica el patrón ya probado en `transcriber.py` para
minimizar sorpresas y reutilizar disciplina:

| Concepto ASR (`transcriber.py`)        | Equivalente multimedia (este plan)                   |
|----------------------------------------|------------------------------------------------------|
| `Transcriber` (interfaz)               | `TextExtractor` / `OcrEngine` / `VisionEngine` (interfaces) |
| `StubTranscriber` (sin dependencias)   | `StubOcrEngine` / `StubVisionEngine` (default)       |
| `FasterWhisperTranscriber` (perezoso)  | motor OCR real perezoso (p. ej. Tesseract/PaddleOCR) |
| `get_transcriber(config)`              | `get_ocr_engine(config)` / `get_vision_engine(config)` |
| `S9K_MEDIA_TRANSCRIBER`                | `S9K_MEDIA_OCR` / `S9K_MEDIA_VISION` (por definir)   |
| `whisper.cpp`/`external` → error claro | motores externos → error claro hasta autorización    |

Reglas heredadas del ASR:

- El **stub** devuelve un artefacto ficticio marcado como tal (nunca se confunde
  con contenido real), suficiente para validar el pipeline sin modelos.
- El motor real hace **import perezoso** y, si la librería falta, lanza un error
  legible que sugiere instalar o usar el stub — nunca rompe el import del módulo.
- La selección es **por configuración** (variable de entorno + `MediaConfig`),
  con `stub` como valor por defecto.

---

## 3. OCR_TEXT vs IMAGE_DESCRIPTION (separación no negociable)

El contrato lo declara explícitamente (líneas 13-18 y 49-59 de
`multimedia_contract.py`) y este runtime lo respeta al pie de la letra:

- **`OCR_TEXT`** = *texto reconocido carácter a carácter* sobre una región de
  imagen. Exige el campo `text` no vacío (`_TEXT_REQUIRED`). Es transcripción
  óptica, no comprensión.
- **`IMAGE_DESCRIPTION`** = *interpretación semántica* de lo que muestra la imagen
  (mapa, diagrama, retrato, escena). Exige el campo `description`
  (`_DESCRIPTION_REQUIRED`). Es comprensión visual, no lectura de caracteres.

**OCR ≠ comprensión visual.** Una misma región puede generar *ambos* artefactos,
pero cada uno es un `MultimediaArtifact` independiente con su propio `media_type`;
nunca se mezclan `text` y `description` en un solo artefacto para "resumir" una
imagen. Los subtipos visuales (`MAP`, `DIAGRAM`, `CHARACTER_SHEET`, `TABLE`,
`CAPTION`, `UNKNOWN_VISUAL`) son especializaciones de la rama de comprensión
visual / datos estructurados, no de OCR.

Consecuencia de runtime: el planificador de una página decide, por región, qué
motores invocar (extractor de texto embebido, OCR, visión) y emite un artefacto
por cada salida real. El fallback ante un visual no clasificable es
`UNKNOWN_VISUAL` (política documentada del contrato, `strict=False`).

---

## 4. Tipología de entradas y ruta de procesamiento

### 4.1 PDF con texto nativo (no escaneado)

- Ruta preferente: **extracción de texto embebido** (`EMBEDDED_TEXT`,
  `extraction_method="pdf_text"`), sin OCR. Es más rápida, exacta y barata.
- Se conserva `page` (1-based) y, cuando el extractor lo permita, la
  `bounding_box` normalizada del bloque.

### 4.2 PDF escaneado (imagen por página)

- No hay texto nativo → se trata cada página como **imagen** y se enruta a OCR y,
  si procede, a visión.
- Detección: si la extracción de texto embebido de una página devuelve vacío o
  por debajo de un umbral de densidad, la página se marca como *escaneada* y pasa
  al carril de imagen. (Heurística documentada; no se ejecuta en OLA 2B.)

### 4.3 Imágenes sueltas

- Entran directamente al carril de imagen (OCR + visión según el segmentador de
  regiones). `page = None` cuando la imagen no pertenece a un documento paginado.

### 4.4 OCR por página vs OCR por región

- **Por página:** una sola pasada OCR sobre la página completa. Barato, útil para
  páginas de texto corrido. `bounding_box = None` o caja de página completa.
- **Por región:** un segmentador delimita regiones (columnas, cajas de texto,
  celdas, leyendas) y se lanza OCR *por región*. Produce un
  `MultimediaArtifact` por región con su `region_id`, su `bounding_box`
  normalizada y, si aplica, `parent_region` para la jerarquía.
- El coste de "por región" es mayor pero mejora la precisión en maquetaciones
  complejas (mapas con etiquetas, fichas, tablas). La política por defecto será
  *por página*, con escalado *por región* cuando la confianza de página sea baja
  o la maqueta sea densa (decisión del planificador, documentada).

---

## 5. Orientación, idioma y calidad

### 5.1 Orientación

- El contrato solo admite `orientation ∈ {0, 90, 180, 270}`
  (`VALID_ORIENTATIONS`). El runtime debe **detectar** la rotación de la región y
  normalizarla a uno de esos cuatro valores antes de emitir el artefacto.
- Rotaciones intermedias (deskew fino, p. ej. 3°) se corrigen en preproceso de
  imagen y NO se reflejan en `orientation` (que es discreto); si acaso, se anota
  en `provenance`/`warnings`. No se inventa un valor fuera del enum.

### 5.2 Idioma

- `language` es ISO 639-1 (`"es"`, `"en"`, …) o `""`. El OCR debe recibir el
  idioma esperado como pista (mejora el reconocimiento). Por defecto `"es"`,
  igual que el ASR.
- Idioma desconocido → `language=""` y aviso en `warnings`, nunca un código
  inventado.
- El glosario del proyecto (usado ya por ASR vía `initial_prompt`/`hotwords`)
  puede alimentar diccionarios/sesgos de OCR en olas futuras; aquí solo se deja
  anotada la interfaz, sin implementarla.

### 5.3 Confianza y revisión humana

- `confidence ∈ [0, 1]` o `None`. Por debajo de `LOW_CONFIDENCE_THRESHOLD = 0.50`
  el contrato marca `requires_human_review()` y añade un warning no bloqueante.
- El runtime **no descarta** artefactos de baja confianza: los emite marcados
  para revisión. La decisión de ingesta es humana y externa a este runtime.

---

## 6. Contenidos visuales especializados

Todos se modelan como artefactos del contrato; el runtime elige el `media_type`:

- **Tablas (`TABLE`):** exigen `structured_data` (`_STRUCTURED_REQUIRED`). El
  reconocimiento de estructura (filas/columnas/celdas) va en `structured_data`;
  el texto de cada celda puede además emitirse como `OCR_TEXT` por región con
  `parent_region` apuntando a la tabla.
- **Mapas (`MAP`):** comprensión visual (rama descripción). Las etiquetas/topónimos
  legibles se extraen aparte como `OCR_TEXT` por región. El mapa como tal describe
  su contenido en `description`.
- **Diagramas/esquemas (`DIAGRAM`):** `description` semántica; los rótulos internos,
  como `OCR_TEXT` por región.
- **Ilustraciones / escenas / retratos:** `IMAGE_DESCRIPTION` (o `UNKNOWN_VISUAL`
  si no se clasifica). Sin texto salvo que contengan caracteres legibles.
- **Pies de figura / leyendas (`CAPTION`):** normalmente `EMBEDDED_TEXT` u
  `OCR_TEXT` según el origen; se enlazan con la figura mediante `parent_region`.
- **Fichas de personaje (`CHARACTER_SHEET`):** estructura en `structured_data`,
  más OCR por región para los campos.
- **Texto incrustado en imágenes** (carteles, sellos, texto dentro de una
  ilustración): es **`OCR_TEXT`**, no descripción. Se distingue del `EMBEDDED_TEXT`
  (texto nativo del documento, sin OCR) por el `extraction_method`.

Solapes entre regiones de una misma página se anotan (no bloquean) vía
`annotate_overlaps()`; la jerarquía `parent_region` evita marcar como
"sospechoso" el solape padre-hijo legítimo (celda dentro de tabla, rótulo dentro
de diagrama).

---

## 7. Caché, hashes y deduplicación

- **Hash de procedencia:** `file_hash` identifica el contenido de la fuente. Es la
  clave primaria de trazabilidad de todo artefacto (`provenance.file_hash` debe
  coincidir con el campo `file_hash`, validado por el contrato).
- **Caché por hash:** el runtime cachea resultados por
  `(file_hash, page, region, motor, versión_de_motor, idioma, orientación)`. Si la
  misma región del mismo contenido se reprocesa con el mismo motor y parámetros,
  se sirve desde caché — evita repetir OCR/visión caros. La caché es local y no
  contiene el corpus privado más allá de los artefactos derivados.
- **Invalidación:** cambiar el motor, su versión o los parámetros de extracción
  invalida la entrada de caché (la versión forma parte de la clave).
- **Deduplicación de contenido:** el contrato provee `content_dedup_key()` y
  `deduplicate()`, que colapsan artefactos con la misma
  `(source_id, page, media_type, text, description)`. El runtime aplica
  `deduplicate()` antes de entregar el lote, de modo que regiones idénticas (p. ej.
  cabeceras repetidas) no generen ruido duplicado.
- **Determinismo:** para una entrada, motor y parámetros dados, la salida debe ser
  estable; los hashes y las claves de caché lo asumen. El stub es determinista por
  construcción.

---

## 8. Privacidad y local vs externo

- **Corpus privado:** el material fuente es privado. El procesamiento por defecto
  es **local**; ningún byte del corpus sale de la máquina sin autorización
  explícita.
- **Local (por defecto):** OCR y visión sobre CPU local. Es la única ruta activa
  contemplada; en OLA 2B ni siquiera esta se ejecuta (stub).
- **Externo (opt-in, apagado):** motores de visión/OCR remotos (p. ej. proveedores
  tipo NVIDIA NIM ya explorados en el ecosistema para relaciones) quedan detrás de
  una configuración explícita, con la política de "sombra"/`NOT_EXECUTED` hasta
  autorización. Enviar imágenes a un tercero es una decisión de privacidad que
  requiere aprobación humana y queda fuera de este plan ejecutar.
- **Minimización:** cuando (en el futuro) se use un motor externo, se enviará la
  mínima región necesaria, nunca el documento completo por defecto, y se registrará
  en `provenance` qué motor procesó qué.
- **Sin autoingesta:** este runtime no escribe en Neo4j ni aprueba nada; produce
  artefactos para revisión.

---

## 9. Recursos: CPU / RAM / GPU

- **CPU (baseline):** igual que `faster-whisper` corre en CPU `int8` por defecto,
  el OCR/visión local se dimensiona para CPU. Es la ruta de referencia y la única
  garantizada en el homelab.
- **RAM:** los motores OCR y sobre todo los de visión cargan modelos que consumen
  memoria. La carga es perezosa (un motor por proceso worker) y se libera al
  terminar el lote. Debe fijarse un techo de RAM por worker (documentado antes de
  activar cualquier motor real).
- **GPU (opcional, futura):** si hubiera GPU disponible, los motores reales podrían
  usarla vía configuración (`device`), igual que `FasterWhisperTranscriber` acepta
  `device`/`compute_type`. No se asume GPU; el plan no depende de ella.
- **Presión de página escaneada:** el OCR por región multiplica el trabajo por el
  número de regiones; el planificador limita la concurrencia para no saturar RAM.

---

## 10. Colas, límites y reintentos

- **Colas:** el trabajo multimedia se encola por *unidad* (documento → páginas →
  regiones). Se reutiliza la infraestructura de jobs ya existente en `media/`
  (`worker.py`, `job_store_bridge.py`, `store.py`) en lugar de crear otra; este
  plan solo describe la política, no la reimplementa.
- **Límites (backpressure):**
  - máximo de páginas/regiones concurrentes por worker (techo de RAM);
  - tamaño y resolución máximos de imagen aceptados (rechazo con warning si se
    exceden);
  - tiempo máximo por región (timeout → artefacto marcado, no cuelgue del lote).
- **Reintentos:** los fallos *transitorios* (I/O, timeout de un motor local) se
  reintentan con backoff acotado. Los fallos *deterministas* (imagen corrupta,
  motor no instalado) NO se reintentan: se emite un error claro (patrón
  `TranscriberError` del ASR) o un artefacto de baja confianza / `UNKNOWN_VISUAL`
  según proceda, y se continúa con el resto del lote (fail-soft por región,
  nunca caída global silenciosa).
- **Idempotencia:** gracias a la caché por hash y a `deduplicate()`, reencolar un
  documento ya procesado no duplica trabajo ni artefactos.

---

## 11. Qué NO se hace en OLA 2B (barreras explícitas)

- **No** se descargan modelos (ni OCR, ni visión, ni Whisper).
- **No** se ejecuta OCR real ni comprensión visual real: el motor por defecto es
  *stub* y el estado de la ejecución real es `NOT_EXECUTED`.
- **No** se modifica `data-engine/app/media/transcriber.py` ni el contrato
  `multimedia_contract.py` (ambos leídos solo para alinear).
- **No** se procesa corpus privado.
- **No** se realizan llamadas externas ni se envían imágenes a terceros.
- **No** se toca producto, viewer ni `.github`.
- **No** se escribe en el grafo ni se aprueba ingesta.

Este documento es el plan; su implementación queda gateada a autorización en olas
posteriores.

---

## 12. Trazabilidad con el contrato (resumen)

| Aspecto del runtime            | Campo/función del contrato usado                          |
|--------------------------------|-----------------------------------------------------------|
| Origen del contenido           | `source_id`, `file_hash`, `provenance`                    |
| Página / región                | `page`, `region_id`, `bounding_box`, `parent_region`      |
| Tipo de salida                 | `media_type` (`MediaType`)                                |
| Cómo se extrajo                | `extraction_method`, `model`                              |
| Calidad                        | `confidence`, `LOW_CONFIDENCE_THRESHOLD`, `warnings`      |
| Orientación / idioma           | `orientation` (`VALID_ORIENTATIONS`), `language`          |
| OCR vs visión                  | `OCR_TEXT` (`text`) vs `IMAGE_DESCRIPTION` (`description`) |
| Estructura                     | `structured_data` (`TABLE`, `CHARACTER_SHEET`)            |
| Deduplicación                  | `content_dedup_key()`, `deduplicate()`                    |
| Solapes                        | `annotate_overlaps()`                                     |
| ASR (no reimplementado)        | `MultimediaArtifact.from_transcript_result()`             |

---

*P6 — OLA 2B Lote 2. Documento de planificación; sin ejecución de modelos.*

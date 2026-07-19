# Contrato interno multimedia — `multimedia-artifact/internal-v1`

Contrato interno común para unificar los resultados de extracción de
**ASR** (audio), **OCR** (texto reconocido), **texto embebido** y
**comprensión visual** (descripción semántica de imágenes) antes de cualquier
ingesta en el grafo.

Implementado en `data-engine/app/media/multimedia_contract.py`. Solo stdlib
(`dataclasses` + `enum`). **No descarga modelos, no ejecuta OCR real, no importa
dependencias de visión.** Solo describe y valida datos revisables.

## OCR != comprensión visual (regla central)

Son **tipos distintos** y NO deben mezclarse en un mismo artefacto:

- `OCR_TEXT`: **texto reconocido** carácter a carácter sobre una región de
  imagen. El contenido va en `text`.
- `IMAGE_DESCRIPTION`: **interpretación semántica** de lo que muestra la imagen
  (fotografías, escenas). El contenido va en `description`.

Una misma región puede producir **ambos** artefactos, pero cada uno es un
`MultimediaArtifact` independiente con su propio `media_type`.

## Tipos (`MediaType`)

| Tipo | Significado | Campo principal |
|------|-------------|-----------------|
| `EMBEDDED_TEXT` | Texto nativo del documento (sin OCR) | `text` |
| `ASR_TEXT` | Transcripción de audio (compat. `media.transcriber`) | `text` (+ `structured_data.segments`) |
| `OCR_TEXT` | Texto reconocido ópticamente | `text` |
| `IMAGE_DESCRIPTION` | Comprensión visual (descripción) | `description` |
| `TABLE` | Tabla estructurada | `structured_data` |
| `MAP` | Mapa (subtipo visual) | `description` / `structured_data` |
| `DIAGRAM` | Diagrama / esquema | `description` / `structured_data` |
| `CHARACTER_SHEET` | Ficha de personaje | `structured_data` |
| `CAPTION` | Pie de figura / leyenda | `text` |
| `UNKNOWN_VISUAL` | Visual no clasificado (fallback) | — |

## Campos del artefacto

`source_id`, `file_hash`, `page`, `region_id`, `bounding_box`, `media_type`,
`extraction_method`, `model`, `confidence`, `language`, `orientation`, `text`,
`description`, `structured_data`, `parent_region`, `provenance`, `warnings`
(+ `contract`, fijado a `multimedia-artifact/internal-v1`).

## Bounding box normalizada

`BoundingBox(x, y, width, height)` con coordenadas **normalizadas en `[0, 1]`**
relativas a la página/imagen.

- **Origen `(0, 0)` en la esquina SUPERIOR IZQUIERDA.**
- `x` crece hacia la derecha; `y` crece hacia abajo.
- El rectángulo cubre `[x, x+width]` (horizontal) y `[y, y+height]` (vertical).

Reglas validadas: `width > 0`, `height > 0`, `x >= 0`, `y >= 0`,
`x + width <= 1`, `y + height <= 1`. Una caja que se sale de esos límites =
región fuera de página = **error**.

Para audio o documento entero, `bounding_box` puede ser `None`.

## Reglas del pipeline (documentadas / validadas)

- **Texto embebido vs OCR**: si existe `EMBEDDED_TEXT` para una región, NO se
  hace OCR de la misma región (el texto nativo es preferente).
- **Deduplicación**: regiones con contenido idéntico (misma fuente, página,
  tipo y texto/descripción) se colapsan con `deduplicate()` /
  `content_dedup_key()`.
- **Rotación / orientación**: `orientation` en `{0, 90, 180, 270}`. Cualquier
  otro valor es error. Cubre columnas rotadas y páginas escaneadas giradas.
- **Columnas y tablas**: las tablas usan `structured_data` (obligatorio para
  `TABLE`); las columnas se modelan como regiones separadas o jerarquía.
- **Imágenes dentro de PDF / fotografías / páginas escaneadas**: se modelan
  como `OCR_TEXT` (si hay texto) y/o `IMAGE_DESCRIPTION` (si hay contenido
  visual), nunca mezclados.
- **Regiones solapadas**: `annotate_overlaps()` añade un `warning` no
  bloqueante a las cajas de la misma página que se solapan (salvo jerarquía
  padre-hijo explícita vía `parent_region`).
- **Confianza baja**: `confidence < 0.50` (`LOW_CONFIDENCE_THRESHOLD`) marca el
  artefacto para **revisión humana** (`requires_human_review()` + warning).
- **Jerarquía**: `parent_region` referencia el `region_id` del contenedor
  (p. ej. una tabla dentro de una ficha de personaje).

## Validación (`MultimediaArtifact.validate()`)

Devuelve la lista de **errores** (bloqueantes); acumula **warnings** no
bloqueantes en `self.warnings`. Comprueba:

- `media_type` conocido (o degradación a `UNKNOWN_VISUAL` con `strict=False`).
- `bounding_box` válida y dentro de la página.
- `confidence` en `[0, 1]`.
- `orientation` en `{0, 90, 180, 270}`.
- `OCR_TEXT` / `EMBEDDED_TEXT` exigen `text` no vacío.
- `IMAGE_DESCRIPTION` exige `description`.
- `TABLE` exige `structured_data`.
- Procedencia mínima: `source_id` y `file_hash` presentes (y coherentes con
  `provenance` si aparece).
- `page` entero `>= 1` o `None`.

Política de tipo desconocido: con `strict=True` (por defecto) es **error**; con
`strict=False` se degrada a `UNKNOWN_VISUAL` con warning.

## Compatibilidad con ASR existente

`MultimediaArtifact.from_transcript_result(result, source_id=..., file_hash=...)`
proyecta un `media.models.TranscriptResult` (producido por
`media.transcriber`, stub o faster-whisper) a un artefacto `ASR_TEXT`. **No
reimplementa la transcripción**: consume el resultado ya generado.

## Fixtures sintéticas

`data-engine/app/tests/data/multimedia/*.json`: metadata **sintética
sanitizada** (sin imágenes ni binarios privados, sin texto reconocido real).
Cubren casos válidos por tipo, casos inválidos (bbox fuera de rango, confianza
fuera de rango, orientación inválida, tipo desconocido, OCR sin texto,
procedencia ausente), pares de solape y deduplicación, y un caso de baja
confianza. Tests en `tests/test_multimedia_contract.py`.

**OCR real ejecutado: NO.** Ningún modelo descargado ni ejecutado.

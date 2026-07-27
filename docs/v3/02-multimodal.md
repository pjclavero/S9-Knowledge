# 02 — Subsistema A: ingesta y normalización multimodal

**Rama:** `feat/v3-multimodal` · **Base:** `36439a2` (`v3-contracts-frozen-1.0.0`)
**Ámbito:** `data-engine/app/knowledge_v3/multimodal/` (nuevo) y sus tests.
**Contratos:** CONGELADOS. Este subsistema no ha tocado ni un byte de
`contracts/knowledge-v3/v1/` ni de `data-engine/app/knowledge_v3/contracts/`.
**Producción:** intacta. Nada de esto escribe en Neo4j, ejecuta proveedores
externos ni consulta el reloj.

Implementa la sección 7 del prompt maestro y el subsistema A del dosier:

```text
fuente → SourceAsset → SourceEpisode(s) → EvidenceFragment(s)
```

---

## 1. Arquitectura

```text
                       ┌──────────────────────────────┐
   SourceInput  ─────► │ AdapterRegistry.resolve()    │  kind > MIME > extensión
   (bytes + payload)   └──────────────┬───────────────┘
                                      │
                       ┌──────────────▼───────────────┐
                       │ SourceAdapter.content_bytes()│  sha256 REAL del contenido
                       │ SourceAdapter.extract()      │  → EpisodeDraft/FragmentDraft
                       └──────────────┬───────────────┘
                                      │
                       ┌──────────────▼───────────────┐
                       │ base.assemble()              │  ids · sequence · prev/next
                       │  · guarda de anclaje         │  hashes · envelope · traza
                       │  · guarda de unicidad        │
                       │  · validate() contra schema  │
                       └──────────────┬───────────────┘
                                      │
                        NormalizationResult(asset, episodes, fragments, report)
```

**Por qué el adaptador no construye documentos.** Un adaptador sólo sabe de su
formato: produce *borradores* con texto, offsets, bbox y timecodes. Todo lo que
es contrato — identificadores, `sequence`, encadenado `previous/next`, hashes,
envelope, `provider_trace` — lo escribe una sola función (`base.assemble`). Un
adaptador no puede equivocarse en algo que no escribe, y añadir un adaptador
nuevo no puede introducir una variante del envelope.

### Ficheros

| Fichero | Qué es |
|---|---|
| `base.py` | `SourceInput`, `IngestOptions`, borradores, `SourceAdapter`, `assemble()`, `NormalizationResult` |
| `registry.py` | `AdapterRegistry`, `default_registry()`, inventario real/stub |
| `normalizer.py` | `normalize()` / `normalize_bytes()`: la API pública |
| `ids.py` | derivación determinista de identificadores por sha256 |
| `quality.py` | medida de calidad y banderas (`reason_code`) |
| `textutil.py` | decodificación y segmentación con offsets absolutos |
| `errors.py` | `NormalizationError` con `reason_code` enumerable |
| `adapters/` | un módulo por familia de fuente |

---

## 2. Determinismo

`normalize()` es una función pura de `(bytes, payload, opciones)`:

* **ningún identificador se inventa.** Todos derivan por sha256 del JSON
  canónico de los campos que definen la identidad lógica:
  `asset_id = sa-<sha256(workspace + collection_id + content_hash)[:32]>`,
  `episode_id = ep-<sha256(asset_id + sequence + content_hash)[:32]>`,
  `fragment_id = ef-<sha256(episode_id + start + end + media_type + literal)[:32]>`;
* **el `workspace` entra en la identidad del asset.** Dos bóvedas que ingieren
  el mismo fichero comparten `content_hash` pero **no** `asset_id`: el
  aislamiento es duro;
* **no se llama al reloj.** `ingested_at` y `created_at` son datos de
  `IngestOptions`. Cambiarlos no cambia ningún identificador derivado;
* `content_hash` del asset es el **sha256 real de los bytes del contenido**, y
  `source_hash` de los tres documentos es exactamente ese hash.

Un UUID aleatorio habría hecho que reingerir el mismo PDF creara una segunda
cadena de procedencia irreconciliable con la primera. El hash lo impide por
construcción, y hay un test que compara `to_json()` de dos ejecuciones byte a
byte.

---

## 3. El invariante de anclaje

Para todo fragmento cuyo episodio tenga texto:

```python
episode.text[fragment.start:fragment.end] == fragment.literal_text
```

Se comprueba en `assemble()` **siempre**, no sólo en los tests. Un fragmento
cuyo offset no recorta su propio literal es evidencia falsa, y una evidencia
falsa es peor que ninguna: apunta a un sitio que *parece* verificado. Los
offsets son relativos al texto del **episodio**, que es la unidad direccionable
del contrato; relativos al fichero obligarían a reabrir la fuente para
verificar una cita.

`literal_text` es exacto por definición (no se reescribe, no se corrige, no se
traduce). `normalized_text` es NFKC + espacios colapsados, y va aparte.

Además, `assemble()` verifica que no haya `episode_id` ni `fragment_id`
repetidos: con identificadores duplicados la procedencia deja de ser una
función.

---

## 4. Adaptadores

### 4.1. Qué es real y qué es stub

| Adaptador | `source_kind` | Implementación | Produce |
|---|---|---|---|
| `text.PlainTextAdapter` | `TEXT`, `NOTE` | **real** | `TEXT` por párrafo + `EMBEDDED_TEXT` por frase |
| `markdown.MarkdownAdapter` | `MARKDOWN` | **real** | secciones `TEXT` + tablas `TABLE` |
| `table.CsvTableAdapter` | `TABLE` | **real** | un `TABLE` estructurado + evidencia por fila |
| `pdf.PdfAdapter` | `PDF` | **real** (pypdf) | `TEXT` por página; página sin texto → pendiente |
| `transcript.AudioTranscriptAdapter` | `AUDIO` | **real (envoltorio)** | `SPEAKER_TURN` / `ASR_TEXT` + evidencia `ASR_TEXT` |
| `transcript.VideoTranscriptAdapter` | `VIDEO` | **real (envoltorio)** | ídem |
| `transcript.YouTubeTranscriptAdapter` | `YOUTUBE` | **real (envoltorio)** | ídem; sin timecodes, lo declara |
| `visual.ImageAdapter` | `IMAGE`, `CHARACTER_SHEET` | **declarado + stub** | OCR e interpretación, por separado |
| `visual.HandwritingAdapter` | `HANDWRITING` | **declarado + stub** | HTR |
| `visual.DrawingAdapter` | `MAP`, `DIAGRAM` | **declarado + stub** | interpretación visual |

`AdapterRegistry.inventory()` devuelve esta misma tabla en tiempo de ejecución,
con `implementation: "real" | "stub"`. El informe de cada normalización lleva
`adapter_implementation`. Un adaptador stub que se anunciara como real sería una
mentira en el inventario, y aquí el inventario se calcula, no se declara: para
los visuales, `is_stub` es `True` mientras el proveedor inyectado sea
`NoVisualProvider`.

### 4.2. PDF (dosier 7.5)

**No se aplica OCR a todas las páginas si el texto nativo es correcto.** Una
página con ≥ `MIN_NATIVE_CHARS` (16, configurable por instancia de adaptador)
caracteres no blancos produce episodios `TEXT` con `page` y evidencia
`EMBEDDED_TEXT`. Una página sin texto extraíble produce:

```yaml
modality: IMAGE            # NO OCR_TEXT: sin lectura no hay texto reconocido
text: null
bbox: {x: 0, y: 0, width: 1, height: 1, page: N}
quality: {score: 0.0, flags: [NO_NATIVE_TEXT, UNPROCESSED_PENDING_PROVIDER]}
metadata:
  pending_reason: NO_NATIVE_TEXT
  next_adapters: [OCR_TEXT, HTR_TEXT, IMAGE_DESCRIPTION]
fragments: []              # cero evidencia: no se ha leído nada
```

La página queda **direccionable, ordenada y trazada**, y ese es el punto de
enganche del subsistema de proveedores. Lo que no hace es fingir que se procesó.

Dependencia: `pypdf`, ya presente y pineada en `data-engine/requirements.lock`
(`pypdf==6.14.2`) y declarada en `requirements.in`. **No se ha añadido ninguna
dependencia nueva.**

### 4.3. Tabla

El episodio `TABLE` lleva **las dos cosas**: `table` (cabecera + filas
estructuradas, que el contrato exige) y `text` (una renderización canónica
`" | "` entre celdas, `"\n"` entre filas). No es duplicar por comodidad: sin
`text` no hay nada contra lo que anclar offsets, y una evidencia de tabla sin
anclaje no se puede verificar. Con las dos, no se pierde ni la estructura ni la
trazabilidad, y la renderización es determinista.

Cubre CSV (delimitador y cabecera explícitos, **sin sniffer**: un sniffer que se
equivoca convierte una tabla en una columna) y tablas Markdown, que salen del
flujo de texto como episodio propio.

### 4.4. Audio, vídeo y YouTube — se **envuelve**, no se transcribe

Este subsistema **no transcribe nada**. Consume por *forma* (duck typing, sin
`import`, para no acoplar) la salida real de los módulos existentes, que son de
sólo lectura para V3:

| Entrada aceptada | Origen real |
|---|---|
| `TranscriptResult` (`text`, `segments`, `engine`, `model`, `duration_seconds`) | `media/transcriber.py` |
| `MultimediaArtifact` `ASR_TEXT` (`structured_data.segments`) | `media/multimedia_contract.from_transcript_result()` |
| `TranscriptDocument` (`segments` con `speaker` y `confidence`) | `audio/audio_schema.py` |
| `dict` con `text` plano | `youtube/fetch_youtube.py` |

**Diarización.** Si algún segmento trae hablante, los consecutivos del mismo
hablante se agrupan en un episodio `SPEAKER_TURN` con `speaker` (cuyo
`speaker_id` deriva de la etiqueta, no de un contador: si el proveedor reordena
los turnos, el hablante sigue siendo el mismo) y `turn`. Si no la hay, se agrupa
en ventanas deterministas de `ASR_TEXT` con bandera `NO_DIARIZATION`. Nunca se
emite un `SPEAKER_TURN` con hablante inventado.

**Calidad del audio (dosier 7.7).** Se miden y se marcan: cobertura
(`LOW_ASR_COVERAGE`), huecos temporales (`TIMELINE_GAP`), final ausente
(`TRUNCATED_TAIL`), bucles de repetición (`REPEATED_CONTENT`), ausencia de
diarización (`NO_DIARIZATION`) y confianza baja del proveedor
(`LOW_PROVIDER_CONFIDENCE`).

**Atribución.** El texto lo produjo el motor ASR, no el normalizador: los
episodios de audio llevan `produced_by_step = "asr"` y un paso de traza
`transcriber:<engine>` con su modelo. El paso `anchor` (offsets, bbox,
timecodes) es **siempre** `local`, incluso cuando el texto viene de fuera: el
contrato dice que los anclajes los pone o los verifica el sistema local.

**Vídeo** (dosier 7.8) usa la misma vía: su audio va al flujo ASR. Keyframes,
escenas y OCR de pantalla son trabajo de los adaptadores visuales sobre el mismo
asset, y hoy están pendientes de proveedor. Este adaptador no los simula.

### 4.5. OCR, HTR, imagen y dibujo — declarados, no fingidos

**Qué es real aquí:** el puerto `VisualProvider`, las estructuras
`VisualRegion` / `VisualRequest` / `VisualResult`, el enrutado por región, la
proyección completa a `SourceEpisode` + `EvidenceFragment` con bbox, y la
separación de tipos. Todo ello probado con un doble del puerto.

**Qué no está:** el reconocimiento. Ejecutar OCR, HTR o un modelo de visión
corresponde al subsistema de proveedores. Sin proveedor inyectado
(`NoVisualProvider`, el valor por defecto), estos adaptadores producen episodios
`modality: IMAGE`, `text: null`, `score: 0.0`,
`flags: [UNPROCESSED_PENDING_PROVIDER]`, **cero fragmentos**, y `metadata` que
declara qué modo se pidió y qué habría producido.

No existe ningún camino por el que este módulo devuelva texto que no le haya
dado un proveedor. Un stub que devolviera texto plausible sería peor que no
tener nada: alimentaría el grafo con contenido inventado y trazado como si
hubiera sido leído.

**OCR literal ≠ HTR ≠ interpretación visual** (dosier 7.6):

| Qué es | `modality` | `media_type` |
|---|---|---|
| Texto impreso reconocido | `OCR_TEXT` | `OCR_TEXT` |
| Manuscrito reconocido | `HTR_TEXT` | `HTR_TEXT` |
| Interpretación visual | `IMAGE` (texto `null`, descripción en `metadata`) | `IMAGE_DESCRIPTION` |
| Mapa interpretado | `MAP` | `MAP` |
| Diagrama interpretado | `DIAGRAM` | `DIAGRAM` |

Un proveedor que devuelva a la vez `text` y `description` es **rechazado**: está
mezclando lectura con interpretación. Una descripción visual nunca ocupa el
campo `text` de un episodio textual.

**Enganche para el subsistema de proveedores:**

```python
from knowledge_v3.multimodal import normalize_bytes, default_registry

registry = default_registry(visual_provider=mi_proveedor_real)  # implementa recognize()
result = normalize_bytes(datos, ..., source_kind="HANDWRITING", registry=registry)
```

El proveedor declara su `provider`/`name`/`version`/`model` reales y la traza los
copia tal cual; de ahí sale la atribución de procedencia (`provider: external`
cuando lo es).

---

## 5. Política de ingesta

`IngestOptions.processing_policy()` construye el bloque del asset y **rechaza**
`allow_external_providers=True` con `privacy_class` `PERSONAL_DATA` o
`RESTRICTED` (código `INCONSISTENT_POLICY`). El contrato lo prohíbe; degradarlo
en silencio ocultaría la intención de quien lo pidió.

---

## 6. Errores: códigos, no prosa

`NormalizationError` lleva `reason_code` enumerable:
`EMPTY_SOURCE`, `CORRUPT_SOURCE`, `UNDECODABLE_TEXT`, `UNSUPPORTED_SOURCE_KIND`,
`MISSING_PAYLOAD`, `INCONSISTENT_POLICY`, `ANCHOR_MISMATCH`,
`NO_CONTENT_EXTRACTED`, `DUPLICATE_ADAPTER`.

La decodificación de texto es **UTF-8 estricta**, sin `errors="replace"`:
sustituir bytes ilegibles por `�` produce un texto que parece válido y no lo es,
y ese texto acabaría siendo evidencia literal de algo que nadie escribió.

---

## 7. Pruebas

**138 tests, todos en verde.**

* `data-engine/app/tests` + `contracts/knowledge-v3/v1/tests`: **3557 pasados,
  2 saltados, 0 fallos**.
* Suite completa del repositorio (`pytest` sin argumentos, los 9 `testpaths`):
  **4312 pasados, 5 saltados, 0 fallos**.
* Línea base sin los cuatro ficheros nuevos: **4174 pasados, 5 saltados**.
  4174 + 138 = 4312: **cero regresiones**, ni un test previo alterado.

No se ha tocado `ci.yml` ni `pytest.ini`: los tests de
`data-engine/app/tests/` ya se recogen.

| Fichero | Tests | Qué cubre |
|---|---|---|
| `test_knowledge_v3_multimodal_core.py` | 43 | registro (10), determinismo (7), envelope y contratos (11), política (7), informe (3), API (5) |
| `test_knowledge_v3_multimodal_adapters.py` | 57 | texto (5), Markdown (5), tabla (6), PDF (5), transcripción (19), visuales (17) |
| `test_knowledge_v3_multimodal_negative.py` | 38 | fuentes inválidas (12), mutación de anclaje (6), de identidad (3), de modalidad (9), de traza (3), aislamiento (3), entradas grandes (2) |
| `test_knowledge_v3_multimodal_fixtures.py` | — | fixtures compartidas (sin tests) |

### Fixtures

Generadas en código, no versionadas como binarios, para que se vea exactamente
qué contienen. El PDF se construye con sintaxis PDF cruda (catálogo, páginas,
stream `BT … Tj … ET`): es un PDF real que `pypdf` abre de verdad, y permite
generar tanto una página con texto nativo como una **sin** texto extraíble, que
es el caso que enruta a reconocimiento.

**Para audio no se usa audio**: se usa una transcripción fixture, porque este
subsistema envuelve transcripciones, no las produce. Se prueban las tres formas
reales de entrada (`TranscriptResult`, `MultimediaArtifact`, `dict`).

### Casos negativos

Fichero vacío, fichero sólo con espacios, binario disfrazado de texto, texto no
UTF-8, PDF corrupto, PDF truncado a la mitad, texto plano con extensión `.pdf`,
PDF sin texto en ninguna página, CSV vacío, CSV sólo con cabecera, Markdown
vacío, extensión desconocida, imagen sin bytes, transcripción sin payload,
artefacto multimedia que no es ASR, región visual sin bbox.

### Pruebas de mutación

Sección 10 del prompt: *un test verde sólo cuenta si la mutación correspondiente
lo pone rojo*. 21 tests rompen a propósito una regla y exigen que algo lo
detecte:

| Mutación | Quién la detecta |
|---|---|
| El segmentador de frases desplaza los offsets un carácter | guarda de anclaje (`ANCHOR_MISMATCH`) |
| La renderización de tabla deja de coincidir con los offsets de fila | guarda de anclaje |
| Offsets desplazados / literal reescrito / `start > end` / literal vacío | guarda de anclaje |
| `derive_id` deja de depender del contenido | guarda de unicidad (`episode_id duplicado`) |
| `fragment_id_for` devuelve una constante | guarda de unicidad |
| El hash del asset deja de depender de los bytes | el test de determinismo del núcleo pasa a fallar (se demuestra: dos ficheros distintos colisionan) |
| Un episodio textual sale sin texto | `NO_CONTENT_EXTRACTED` |
| `TABLE` sin `table` / `SPEAKER_TURN` sin `speaker` | validador de contratos |
| Evidencia `ASR_TEXT` sin timecodes / `OCR_TEXT` sin bbox | validador de contratos |
| El adaptador de audio pierde la diarización o los timecodes | validador de contratos |
| `produced_by_step` colgando de la traza | validador de contratos |
| `metadata` con clave sensible | validador de contratos |
| Episodio que supera el límite de longitud del contrato | validador de contratos |

### Cobertura

No hay `coverage.py` ni `pytest-cov` instalados en este entorno, así que **no se
declara ningún porcentaje**: sería un número inventado. Lo que sí se puede
afirmar y está verificado por los tests: los **diez** adaptadores registrados se
ejercitan (los cinco `source_kind` visuales, en sus dos rutas — con proveedor y
sin él); las **tres** formas de transcripción real se envuelven; y las guardas
de anclaje, unicidad, política y modalidad tienen cada una al menos un test que
las pone rojas al mutarlas.

---

## 8. Métricas del normalizador (sección 13 del prompt)

| Métrica pedida | Estado |
|---|---|
| cobertura | `report.episode_count` / `fragment_count`; cobertura ASR medida (`LOW_ASR_COVERAGE`) |
| truncado | medido (`TRUNCATED_TAIL`) |
| repetición | medido (`REPEATED_CONTENT`, detector de bucle literal) |
| bbox | presente y **exigido** por contrato en `OCR_TEXT`/`IMAGE_DESCRIPTION`/`MAP`/`DIAGRAM` |
| timecode | presente y **exigido** por contrato en evidencia `ASR_TEXT` |
| páginas | `report.pdf_pages`, `pdf_pages_with_native_text`, `pdf_pages_pending_recognition` |
| CER / WER | **no calculables aquí.** Exigen una transcripción de referencia (*gold*) y una ejecución real de ASR/OCR. El dataset gold es de la sección 8 del programa y el reconocimiento real es del subsistema de proveedores. No se declara ningún valor. |

---

## 9. Bloqueos y observaciones

### Bloqueos de contrato

**Ninguno.** Los tres contratos (`source-asset`, `source-episode`,
`evidence-fragment`) han bastado para todo lo implementado. No ha hecho falta
ningún campo que no exista.

### Observaciones (no bloqueantes, sobre código congelado — no tocado)

1. **`MEDIA_TYPES` de `knowledge_v3/contracts/evidence.py` no incluye
   `HTR_TEXT`.** El JSON Schema (`_common-v3.schema.json#/$defs/media_type`) sí
   lo incluye, y es el schema el que valida, así que la evidencia `HTR_TEXT` se
   acepta sin problema. Pero esa tupla Python es una lista de diez elementos
   documentada como «idéntica a `media/multimedia_contract.MediaType`», mientras
   el schema tiene once. Quien la use como catálogo se llevará una sorpresa.
   *No se ha modificado: es código congelado.*

2. **La evidencia sin timecodes de YouTube es una pérdida real.**
   `youtube/fetch_youtube.py` descarta los tiempos del VTT
   (`parse_vtt_to_text`), y el contrato — con razón — rechaza evidencia
   `ASR_TEXT` sin anclaje temporal. Resultado: para una transcripción de YouTube
   sin tiempos, este subsistema **no inventa timecodes**; emite evidencia
   `CAPTION` si el origen declarado es un fichero de subtítulos, y **ninguna
   evidencia** si viene de whisper sin tiempos, marcando el episodio con
   `NO_TIMECODES`. La solución de fondo es que `youtube/` conserve los tiempos
   del VTT; no está en el ámbito de esta rama (`youtube/` es de sólo lectura).

3. **`source_kind: WEB` no tiene adaptador.** El dosier 7.1 lo lista entre las
   entradas, pero la sección 7 del prompt maestro no lo pide entre los
   adaptadores a añadir, y convertir HTML a texto con offsets fiables es un
   trabajo propio. Queda declarado como hueco, no cubierto en silencio.

4. **`media/worker.py` sigue sin producir `MultimediaArtifact`** (hallazgo D2 de
   la auditoría). Este subsistema ya sabe envolverlo, así que el día que el
   worker lo emita no hay que tocar nada aquí; hoy la vía en uso es
   `TranscriptResult`.

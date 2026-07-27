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
| `registry.py` | `AdapterRegistry` (sin colisiones de `source_kind`, MIME ni extensión), `default_registry()`, inventario real/stub |
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

### 3.1. Los offsets se refieren al texto con saltos de línea normalizados

`decode_text()` convierte CRLF y CR sueltos a LF **antes** de segmentar, y los
offsets se refieren a ese texto normalizado. Es una decisión, y tiene dos
razones:

1. Sin ella, un `.txt` de Windows no casa con el separador de párrafos
   (`\n\s*\n`) y el fichero **entero** acaba en un único episodio; pasado de
   200 000 caracteres el contrato lo rechaza y la fuente se pierde por completo.
   La granularidad de episodios no puede depender del sistema operativo donde se
   escribió el fichero.
2. El anclaje sigue siendo verificable contra el texto del episodio, que es la
   unidad direccionable del contrato. Quien quiera volver a los bytes originales
   tiene el `content_hash` del asset.

La normalización es idempotente y se aplica también a lo que devuelve pypdf.

### 3.2. Convención de offsets cuando el anclaje es una bbox

El contrato exige `start` y `end`; no admite omitirlos. En un fragmento de
**interpretación visual** el episodio no tiene texto (`text: null`), así que no
hay nada contra lo que medir: ambos valen **0** — un tramo vacío — y
`metadata.anchor = "bbox"` dice cuál es el anclaje real. Poner
`end = len(descripción)` habría fabricado offsets con aspecto de offsets de
texto que no recortan nada de ningún sitio. Los fragmentos `OCR_TEXT` y
`HTR_TEXT` sí llevan offsets de texto reales, porque ahí el episodio sí tiene
texto.

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

Una tabla dentro de un **bloque cercado** (` ``` ` o `~~~`) **no** es una tabla:
es documentación de un formato. El parser rastrea las vallas y trata su
contenido como texto, igual que las almohadillas que haya dentro (que tampoco
abren sección). Extraer como datos del grafo el ejemplo de tabla de un manual
sería convertir la explicación de un formato en hechos sobre el mundo.

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

#### El registro JSON de `youtube/` hay que remapearlo

`youtube/fetch_youtube.py` guarda un registro cuya clave `transcript` es una
**cadena**, no un objeto. Ese payload **no se puede envolver tal cual**: el
adaptador lo rechaza con `EMPTY_SOURCE` (no hay ni segmentos ni `full_text`), y
hay un test que fija ese comportamiento como el esperado. El llamante debe
remapearlo explícitamente:

```python
crudo = json.loads(registro_de_youtube)          # {"transcript": "texto...", ...}
payload = {"transcript": {
    "full_text":     crudo["transcript"],        # la cadena pasa a full_text
    "source_method": crudo["source_method"],     # "subtitles" | "whisper"
    "engine":        "whisper",
    "language":      crudo.get("language", "es"),
}}
```

El remapeo es del llamante a propósito: adivinar aquí que una cadena suelta «es
seguramente el texto» sería exactamente el tipo de suposición que hace que un
formato cambie de significado sin que nadie se entere.

#### Frontera de confianza: `source_method` lo declara el llamante

`CAPTION` se emite cuando el `source_method` **declarado** es `subtitles` o
`captions`. No se deriva ni se verifica: el normalizador no puede saber de dónde
salió realmente un texto que le entregan ya hecho. Consecuencia concreta y
asumida: **declarar `"subtitles"` sobre una salida de whisper produciría
evidencia `CAPTION` sin timecodes**. Quien construye el payload responde de que
ese campo diga la verdad. Hay un test que fija ambos comportamientos —el honesto
y el mentiroso— para que la frontera esté escrita y no sea una sorpresa.

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

**Supuesto de confianza, anotado y no resuelto aquí:** el adaptador *copia* lo
que el proveedor dice de sí mismo, sin verificarlo contra ninguna fuente
independiente. Un proveedor que mintiera sobre su `name`/`version` produciría
una traza plausible y falsa. Es frontera con el bloque de proveedores y se
resuelve en integración, no en esta rama.

#### La política de proveedores externos se aplica, no se declara

El contrato dice que si `processing_policy.allow_external_providers` es `false`,
ningún `provider_trace` de la cadena derivada puede llevar `provider: external`.
La vía visual lo **comprueba**, con dos guardas:

1. **antes** de invocar al proveedor, si éste declara su clase por adelantado
   (atributo `provider_kind`) — así el material no llega a salir;
2. **después**, sobre el `provider` que trae el resultado — porque un proveedor
   puede no declarar nada por adelantado.

Cualquiera de las dos falla con `EXTERNAL_PROVIDER_NOT_ALLOWED`. Sin esto,
inyectar un proveedor remoto producía un asset que se contradecía a sí mismo:
política `false` y traza `external` en el mismo documento, ambos válidos por
separado. Hay un test de mutación que desactiva la guarda y enseña justamente
ese documento contradictorio.

#### Confianza del proveedor: una sola política en las tres vías

Un valor de confianza fuera de `[0,1]` — una escala 0-100, un porcentaje, un
`-1` de «no sé», un `"alta"` — **se rechaza** con
`PROVIDER_CONFIDENCE_OUT_OF_RANGE`, en las tres vías (segmento ASR, hablante,
resultado visual). No se acota en silencio: acotar convertiría un `42.0` en
`1.0`, es decir, en la certeza absoluta de un motor que no dijo eso. Es mentir
con la forma de un dato válido.

Por debajo de `LOW_CONFIDENCE_THRESHOLD` (0.50, el mismo umbral que
`media/multimedia_contract`) el episodio se marca con el `reason_code`
`LOW_PROVIDER_CONFIDENCE`, también en las tres vías: toda penalización del score
lleva su código, sin excepciones.

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
`NO_CONTENT_EXTRACTED`, `DUPLICATE_ADAPTER`,
`PROVIDER_CONFIDENCE_OUT_OF_RANGE`, `EXTERNAL_PROVIDER_NOT_ALLOWED`.

La decodificación de texto es **UTF-8 estricta**, sin `errors="replace"`:
sustituir bytes ilegibles por `�` produce un texto que parece válido y no lo es,
y ese texto acabaría siendo evidencia literal de algo que nadie escribió.

---

## 7. Pruebas

**176 tests, todos en verde** (138 del bloque inicial + 38 de la ronda de
correcciones tras la revisión independiente).

* Suite completa del repositorio (`pytest` sin argumentos, los 9 `testpaths`):
  **4350 pasados, 5 saltados, 0 fallos**.
* Línea base sin los cuatro ficheros nuevos: **4174 pasados, 5 saltados**.
  4174 + 176 = 4350: **cero regresiones**, ni un test previo alterado.

No se ha tocado `ci.yml` ni `pytest.ini`: los tests de
`data-engine/app/tests/` ya se recogen.

| Fichero | Tests | Qué cubre |
|---|---|---|
| `test_knowledge_v3_multimodal_core.py` | 47 | registro (14), determinismo (7), envelope y contratos (11), política (7), informe (3), API (5) |
| `test_knowledge_v3_multimodal_adapters.py` | 86 | texto (8), Markdown (9), tabla (6), PDF (5), transcripción (29), visuales (29) |
| `test_knowledge_v3_multimodal_negative.py` | 43 | fuentes inválidas (12), mutación de anclaje (6), de identidad (3), de modalidad (9), de traza (3), de la ronda de correcciones (5), aislamiento (3), entradas grandes (2) |
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
lo pone rojo*. 26 tests rompen a propósito una regla y exigen que algo lo
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
| Se quita la normalización de CRLF | un `.txt` de Windows grande pasa a ser un episodio único de >200 k y el contrato lo rechaza |
| Se desactiva la guarda de proveedor externo | el asset resultante se contradice: política `false` + traza `external` |
| `check_provider_confidence` se sustituye por un acotado | un `42.0` se convierte en `1.0`: certeza inventada |
| Se desactiva la detección de vallas de código | el ejemplo de tabla de un manual entra como episodio `TABLE` |
| El registro admite colisiones de MIME/extensión | el adaptador elegido pasa a depender del orden de registro |

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

5. **La traza del proveedor se copia sin verificar** (H3 de la revisión). El
   adaptador visual copia el `name`/`version`/`model` que el proveedor declara
   de sí mismo. Un proveedor que mintiera produciría una traza plausible y
   falsa. Es frontera con el bloque de proveedores y se resuelve en integración;
   queda anotado como supuesto de confianza, no arreglado en esta rama.

---

## 10. Ronda de correcciones tras la revisión independiente

Dictamen: **CONFORME CON OBSERVACIONES NO BLOQUEANTES**. Aplicado:

| Hallazgo | Qué se hizo |
|---|---|
| **H1** CRLF | `normalize_newlines()` en `decode_text()` y en `episodes_from_text()`; los offsets se refieren al texto normalizado (§3.1). Tests CRLF/CR + mutación |
| **H2** política externa | Dos guardas en la vía visual (antes y después de invocar), `EXTERNAL_PROVIDER_NOT_ALLOWED`. Tests + mutación que enseña el asset contradictorio |
| **H4** confianza | `check_provider_confidence()` única para ASR, hablante y visual: fuera de `[0,1]` → rechazo, nunca acotado. Tests en las tres vías + mutación |
| **H5** score sin código | `LOW_PROVIDER_CONFIDENCE` también en la vía visual (literal e interpretación), con `LOW_CONFIDENCE_THRESHOLD` compartido |
| **H6** colisiones del registro | `DUPLICATE_ADAPTER` también para MIME y extensión; se comprueba todo antes de escribir nada (un fallo no deja el registro a medias) |
| **H9** vallas de código | El parser Markdown rastrea ` ``` `/`~~~`; dentro no hay tablas ni encabezados |
| **H10** offsets con bbox | Interpretación visual → `start = end = 0` y `metadata.anchor = "bbox"`; convención documentada (§3.2) + tests |
| **H7** registro de `youtube/` | Remapeo exacto documentado + test que fija `EMPTY_SOURCE` como comportamiento esperado del payload crudo |
| **H8** `source_method` | Documentada la frontera de confianza + test que fija el caso honesto y el mentiroso |
| **H3** traza sin verificar | **No tocado** por indicación del coordinador: frontera con proveedores. Anotado en §9.5 |

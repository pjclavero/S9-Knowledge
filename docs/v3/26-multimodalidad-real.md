# Multimodalidad real

Fecha de ejecución: 2026-07-29
Rama: `feat/v3-multimodal-real`
Base: `origin/feat/knowledge-v3-redesign` en `2d76f4b`

## Proveedor elegido

Se implementó `TesseractVisualProvider`, un proveedor local para el puerto
`VisualProvider` existente. Usa directamente la salida TSV de Tesseract, sin
`pytesseract`, servicios de nube ni dependencias Python nuevas. Pillow ya estaba
fijado en `data-engine/requirements.lock` y se utiliza únicamente para validar y
recortar la región solicitada.

Tesseract se eligió porque:

- procesa el contenido en la máquina;
- devuelve texto, confianza y coordenadas;
- su salida TSV es estable y parseable con la biblioteca estándar;
- no mezcla OCR literal con descripción visual;
- no añade autoridad: solo produce evidencia para el pipeline existente.

El proveedor solo responde a `MODE_OCR`. `DESCRIPTION`, HTR, mapas y diagramas
siguen en su estado previo y honesto.

## Instalación y descubrimiento

Se requiere Tesseract 5 con el paquete de idioma utilizado. El ejecutable se
busca, en orden, en:

1. argumento explícito del constructor;
2. `S9K_TESSERACT_CMD`;
3. `PATH`;
4. `.tools/Tesseract-OCR/tesseract.exe`;
5. las rutas habituales de `Program Files` en Windows.

Para esta ejecución se usó el instalador de UB Mannheim:

```text
tesseract-ocr-w64-setup-5.4.0.20240606.exe
SHA-256 C885FFF6998E0608BA4BB8AB51436E1C6775C2BAFC2559A19B423E18678B60C9
```

Se verificó el hash publicado antes de extraerlo a una ruta temporal local. La
salida real fue:

```text
tesseract v5.4.0.20240606
leptonica-1.84.1
Found AVX2
Found AVX
Found FMA
Found SSE4.1
```

La copia temporal no se versionó y se eliminó tras las pruebas.

## Texto posicionado

Cada fila de palabra del TSV se normaliza contra las dimensiones de la imagen.
Las palabras se agrupan por línea y cada línea produce:

- el tramo exacto dentro del texto OCR (`start`, `end`, `text`);
- un bbox normalizado que contiene las palabras de la línea;
- confianza media de sus palabras;
- un `EvidenceFragment` `OCR_TEXT` con
  `metadata.anchor = "text+bbox"`.

Se usan líneas, no palabras aisladas, porque el primer E2E real descubrió que
fragmentar `Liora Vale` en dos evidencias impedía al extractor reconocer la
entidad compuesta: el resultado inicial fue 0 menciones. Al conservar la línea
como unidad posicionada se mantienen simultáneamente el anclaje visual y el
contexto que necesita extracción.

Cada bbox debe estar dentro de `[0,1]`, tener área positiva y no rebasar la
imagen. Cada offset debe recortar exactamente su literal. La confianza general
y la de cada línea se rechazan si quedan fuera de `[0,1]`; no se recortan.

Una imagen vacía produce `OCR_NO_TEXT_DETECTED`. Bytes que no forman una imagen
producen `OCR_UNREADABLE_IMAGE`. Ambos casos quedan pendientes, sin texto ni
evidencia inventados y sin romper el lote.

## Recorrido completo y medición

La fuente del E2E es el escaneo degradado y versionado
`benchmarks/datasets/multimodal/sources/bruma-scan.png`. El mismo fichero se
usó para CER/WER y para:

```text
imagen -> normalización -> extracción -> reconciliación -> resolución
       -> motor -> GraphMutationPlan -> writer dry-run
```

El driver entregado al writer lanza una excepción si se toca. El test llegó a
`writer_mode = DRY_RUN` sin activarlo.

Salida real de la medición del pipeline:

```json
{
  "ocr_characters": 331,
  "episodes": 2,
  "fragments": 6,
  "mentions": 3,
  "claims": 1,
  "resolutions": 3,
  "decisions": 1,
  "plan": "write",
  "writer_mode": "DRY_RUN"
}
```

Los dos episodios son uno `OCR_TEXT` y uno pendiente de descripción visual:
Tesseract no pretende describir imágenes.

La referencia tiene 333 caracteres tras retirar el salto final. Las métricas se
calcularon con `knowledge_v3.benchmarks.metrics.error_rate` y `ratio`:

```json
{
  "reference_characters": 333,
  "ocr_characters": 331,
  "cer_edits": 5,
  "cer": 0.015015,
  "wer_edits": 0,
  "wer": 0.0,
  "episodes": 2,
  "fragments": 6
}
```

La diferencia de caracteres procede de espaciado/saltos y puntuación; las
palabras recuperadas coinciden con la referencia en esta fixture.

## Gold multimodal

Se creó el split nuevo y desconectado
`benchmarks/datasets/multimodal/`, autorizado expresamente para B.3. No se
leyó ni modificó ningún split existente.

El mundo y el texto son nuevos. Las cuatro modalidades comparten exactamente:

```text
Liora Vale --ALLY_OF--> Narek Sol
```

Composición:

- texto plano: `bruma.txt`;
- PDF nativo: `bruma-native.pdf`;
- escaneo degradado: `bruma-scan.png`;
- transcripción ASR simulada con errores realistas:
  `bruma-audio-transcript.json`.

El test normaliza y valida las cuatro contra los contratos, y exige que cada
salida conserve `Liora Vale`, `Narek Sol` y `es aliada de`. Cambiar una
modalidad sin cambiar las demás rompe la prueba.

Los binarios son reproducibles con `_authoring/build_assets.py`:

```text
bruma-native.pdf
DCDA2429530CC5189CEA3ADF685EFF3435EA176ED1939228218E12885D703E19

bruma-scan.png
3CC9FDD2EAE155E357ACD272B9FB04BAE5059993ED55A1BD57F4E3FB9B6F20DD
```

El manifest declara `"automatic": false`; no se conectó a loader, CI ni flujos
automáticos.

## Ficheros

- `.gitattributes` (solo marca PDF/PNG del nuevo gold como binarios)
- `data-engine/app/knowledge_v3/multimodal/adapters/visual.py`
- `data-engine/app/knowledge_v3/multimodal/providers/__init__.py`
- `data-engine/app/knowledge_v3/multimodal/providers/tesseract.py`
- `data-engine/app/tests/test_knowledge_v3_multimodal_real.py`
- `benchmarks/datasets/multimodal/README.md`
- `benchmarks/datasets/multimodal/manifest.json`
- `benchmarks/datasets/multimodal/semantic_gold.json`
- `benchmarks/datasets/multimodal/sources/bruma.txt`
- `benchmarks/datasets/multimodal/sources/bruma-native.pdf`
- `benchmarks/datasets/multimodal/sources/bruma-scan.png`
- `benchmarks/datasets/multimodal/sources/bruma-audio-transcript.json`
- `benchmarks/datasets/multimodal/_authoring/build_assets.py`
- `docs/v3/26-multimodalidad-real.md`

No se modificaron contratos, requisitos, engine, extraction, resolution,
reconcile, writer, CI, `pytest.ini` ni datasets preexistentes.

## Pruebas ejecutadas

Suite exigida de B con OCR real:

```text
python -m pytest data-engine/app/tests/test_knowledge_v3_multimodal_real.py -q
```

Salida real final:

```text
..........                                                               [100%]
10 passed in 2.11s
```

Batería multimodal completa:

```text
python -m pytest \
  data-engine/app/tests/test_knowledge_v3_multimodal_core.py \
  data-engine/app/tests/test_knowledge_v3_multimodal_adapters.py \
  data-engine/app/tests/test_knowledge_v3_multimodal_negative.py \
  data-engine/app/tests/test_knowledge_v3_multimodal_real.py -q
```

Salida real final:

```text
........................................................................ [ 38%]
........................................................................ [ 77%]
..........................................                               [100%]
186 passed, 1 warning in 4.57s
```

La advertencia es `PytestRemovedIn10Warning` sobre una fixture de clase
preexistente en `test_knowledge_v3_multimodal_core.py`.

Suite completa del data-engine:

```text
python -m pytest data-engine/app/tests/ -q
```

Resultado real:

```text
ERROR test_knowledge_v3_e2e.py
ERROR test_knowledge_v3_e2e_fixtures.py
ERROR test_knowledge_v3_e2e_semantic_wiring.py
Interrupted: 3 errors during collection
41 warnings, 3 errors in 2.32s
```

Los tres errores ocurren antes de ejecutar tests:

```text
data-engine/app/knowledge_v3/pipeline/bundle.py:16
ModuleNotFoundError: No module named 'resource'
```

Suite global:

```text
python -m pytest -q
```

Resultado real:

```text
ImportError while loading conftest 'deploy/tests/conftest.py'
deploy/scripts/retention.py:18: ModuleNotFoundError: No module named 'fcntl'
```

Son incompatibilidades POSIX preexistentes en esta máquina Windows y no se
parchearon, conforme a la prohibición de cambios laterales.

## Cobertura y limitaciones

Quedan cubiertos con ejecución real:

- OCR de imagen con texto, offsets, bbox y contratos válidos;
- imagen vacía e ilegible sin texto inventado;
- mezcla de lectura y descripción rechazada;
- confianza fuera de rango rechazada;
- bbox fuera de imagen rechazado;
- comportamiento stub sin proveedor;
- E2E hasta plan y writer dry-run;
- las cuatro modalidades con el mismo gold semántico.

Limitaciones:

- solo se midió una página escaneada y un diseño tipográfico;
- la fixture usa el modelo `eng`, ya incluido en el paquete ejecutado; para
  español con tildes debe instalarse `spa.traineddata`;
- no se implementaron HTR, descripción visual, mapas ni diagramas;
- Tesseract es un ejecutable del sistema y no se distribuye dentro del repo;
- el test E2E usa en Windows un shim de importación para `resource` únicamente
  porque `pipeline.__init__` importa el medidor RSS POSIX; el shim no se llama
  ni altera el pipeline ejercitado.

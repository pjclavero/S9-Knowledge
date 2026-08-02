# 39 — Carril OCR conectado a la extracción V3 (puerta 4, bloque B1)

## 1. Problema y contexto

En la medición de la puerta 4 (negaciones extremo a extremo,
`artifacts/v3-final-validation/gate4_negation_measure.py`), la fuente
`ambar-escaneo` del split `negation` cuenta como **no cubierta**: entra por
bytes (`entry="raw"`, la única puerta medible del runner E2E congelado) y sale
sin texto, así que el extractor no propone nada y la cadena se detiene en el
motor.

**Lo que se investigó primero, antes de escribir una línea de código**, porque
el diagnóstico determina el diseño:

- El `SourceAsset` de `ambar-escaneo` declara `source_kind=IMAGE`.
- Sus 11 episodios (no 22 en la versión actual del split) declaran
  `modality=OCR_TEXT` y **ya traen el texto gold**, con ruido de OCR simulado
  a mano (`rniembro`, `e1`, `1as`, `0tilia`...).
- El gold **no guarda bytes de imagen reales**: `benchmarks.loader` solo
  publica el `SourceAsset` (un descriptor con `byte_size`/`content_hash`), tal
  y como ya documenta `pipeline/sources.py` para todo el dataset `dev`.
- `pipeline.sources.reconstruct_bytes`, al entrar por bytes, fabricaba para
  `IMAGE` un placeholder sin píxeles (`b"IMAGEN-RECONSTRUIDA-DEL-GOLD"`) y sin
  el texto del episodio: de ahí la cobertura cero, documentada ya en las notas
  del runner congelado ("sin `visual_provider` no hay OCR").

**Decisión**: no hay ningún byte de imagen real que reconstruir. La única
salida honesta es **renderizar el texto gold conocido en una imagen de
verdad** y dejar que el OCR intente recuperarlo — igual que sugiere el propio
encargo del bloque. Esto es distinto de inventar evidencia: la imagen nace del
texto que el gold ya declara, y la medición registra si el OCR devuelve ESE
mismo texto o no. Ningún atajo copia el texto de un lado a otro sin pasar por
reconocimiento real.

## 2. Lo que ya existía y no hubo que tocar

El subsistema `multimodal` (B0 de otro bloque, no de este) ya traía el
cableado real y probado:

- `multimodal/adapters/visual.py` — `ImageAdapter`, con el puerto
  `VisualProvider`, el enrutado por región, la separación OCR/HTR/descripción
  y la proyección a `SourceEpisode`/`EvidenceFragment` con `bbox`. Sin
  proveedor, produce episodios `IMAGE` **pendientes**
  (`UNPROCESSED_PENDING_PROVIDER`), nunca texto inventado.
- `multimodal/providers/tesseract.py` — `TesseractVisualProvider`, OCR local
  real sobre el TSV posicional de Tesseract, con confianza por palabra y
  agregación por línea.
- `multimodal/registry.py::default_registry(visual_provider=...)` — ya acepta
  un proveedor visual e lo inyecta en los tres adaptadores visuales.
- `pipeline/config.py::PipelineConfig.visual_provider` y
  `pipeline/pipeline.py` — ya declaran el campo y ya lo pasan a
  `default_registry`. **Este cableado extremo a extremo (config →
  normalizador → adaptador) ya estaba hecho**; B1 no repite nada de esto.
- `extraction/deterministic.py::low_quality(episode)` — ya fuerza
  `review_required=True` cuando `episode.quality.score < 0.5`, y
  `multimodal/adapters/visual.py::_episode_from_result` ya baja ese score al
  mínimo entre la calidad de texto y la confianza del proveedor. **La regla de
  oro de este bloque (ver §4) ya estaba implementada** en la intersección de
  esas dos piezas; B1 solo la ha verificado con pruebas nuevas, no ha tenido
  que tocar ni una línea de `extraction/`.

## 3. Lo que añade B1

Solo dos piezas nuevas, ambas apagadas por defecto:

1. **`knowledge_v3/pipeline/ocr_render.py`** (nuevo). `render_source_image`
   dibuja, con PIL, una banda horizontal por episodio a partir de su texto
   gold conocido, y devuelve el PNG más las regiones (`bbox`, `mode`, `page`)
   que el adaptador visual necesita para recortar cada banda por separado.
   `renderable()` exige que **todos** los episodios de la fuente tengan texto
   y modalidad `OCR_TEXT`/`HTR_TEXT` — todo o nada: una fuente con episodios
   mixtos no es el caso que este bloque ataca.

2. **`knowledge_v3/pipeline/sources.py::reconstruct_bytes`** — nuevo parámetro
   `render_ocr_images: bool = False` (propagado por `from_raw` y
   `cases_from_gold`). `False` (el valor por defecto) reproduce EXACTAMENTE
   el comportamiento anterior a B1 — comprobado byte a byte: el baseline B0
   (`artifacts/gate4-program/b0-baseline.json`) sale idéntico con o sin este
   cambio. `True` y una fuente `IMAGE` renderizable usa `ocr_render` en vez
   del placeholder.

3. **`knowledge_v3/eval/ocr_lane.py`** (nuevo). Corre la cadena SOLO sobre
   `ambar-escaneo`, con `render_ocr_images=True` y un `visual_provider`
   opcional, y publica cobertura, recuperación literal, claims y anclaje de
   evidencia. **No toca el runner E2E congelado ni el baseline B0**: es un
   informe aparte, pensado para colgar de `corpora.ocr_lane` cuando se pide
   explícitamente.

4. **`scripts/gate4/measure.py --with-ocr`** — la única bandera nueva de
   interfaz. Sin ella, la salida es byte a byte idéntica a la de antes de B1
   (verificado). Con ella, intenta un `TesseractVisualProvider` real y, si el
   binario no está instalado (no lo está hoy en esta máquina), se degrada
   solo — el carril corre igual que sin proveedor (cero claims, diagnóstico
   de proveedor ausente) y el informe declara `unavailable_reason`. Nunca
   revienta la medición completa por falta de un binario opcional.

## 4. La regla de oro del bloque

> El texto OCR es la ÚNICA fuente de evidencia de los claims que salen de una
> imagen. Si el OCR devuelve confianza baja, el claim resultante se marca
> `REVIEW`, nunca se autoaprueba.

Cómo se cumple, en la cadena real (nada de esto es nuevo de B1, solo se ha
verificado con pruebas):

1. `multimodal/adapters/visual.py::_literal_fragments` construye cada
   fragmento de evidencia a partir de los `spans` que el proveedor devuelve
   con sus offsets — y rechaza (`NormalizationError`) cualquier span cuyo
   literal no coincida byte a byte con el texto del episodio. Un claim nunca
   puede citar texto que el episodio OCR no contiene literalmente.
2. `_episode_from_result` fija `episode_quality["score"] = min(score_de_texto,
   confianza_del_proveedor)`. Confianza baja → score bajo, siempre, sin
   excepción.
3. `extraction/deterministic.py::low_quality(episode)` lee ese score: por
   debajo de `0.5`, `review_required=True` en cualquier claim que salga de
   ese episodio — no hay combinación de reglas que lo esquive.
4. `eval/ocr_lane.py` repite la comprobación de forma independiente sobre la
   salida real (`golden_rule_respected` por fila), para que el informe no
   dependa solo de la garantía interna.

## 5. Fail-closed

Sin binario OCR (`visual_provider=None`, el valor por defecto de
`PipelineConfig`): la fuente `IMAGE` queda con episodios **pendientes**
(`UNPROCESSED_PENDING_PROVIDER`, `NO_VISUAL_PROVIDER`), cero claims, cero
evidencia — nunca texto inventado. Con una imagen ilegible (bytes corruptos):
`OCR_UNREADABLE_IMAGE`, mismo resultado. Con una imagen sin texto detectable:
`OCR_NO_TEXT_DETECTED`. Los tres casos están probados en
`tests/test_knowledge_v3_multimodal_real.py` (adaptador) y
`tests/test_gate4_b1_ocr_lane.py` (carril completo).

## 6. Cómo ejecutar la medición con OCR

Sin Tesseract instalado (hoy, en esta máquina), el flujo normal no cambia:

```
PYTHONPATH=data-engine/app python3 scripts/gate4/measure.py \
    --out-dir artifacts/gate4-program --out-name b0-baseline
```

Con `--with-ocr`, se añade el informe del carril (degradado si no hay
binario):

```
PYTHONPATH=data-engine/app python3 scripts/gate4/measure.py --with-ocr \
    --out-dir artifacts/gate4-program --out-name b0-baseline-with-ocr
```

Cuando el operador instale Tesseract (`S9K_TESSERACT_CMD` o el binario en el
`PATH`), la misma orden activa el proveedor real y las pruebas reales pasan
de `skipped` a ejecutarse:

```
PYTHONPATH=data-engine/app python3 -m pytest \
    data-engine/app/tests/test_gate4_b1_ocr_real.py -q
```

## 7. Pruebas

- `tests/test_gate4_b1_ocr_lane.py` — proveedor falso, sin binario: imagen
  sintética real y decodificable, regiones coherentes, fail-closed sin
  proveedor, ciclo completo con proveedor de pruebas, regla de oro con
  confianza baja, degradación limpia de `measure_ocr_lane_with_tesseract`.
- `tests/test_gate4_b1_ocr_real.py` — gateadas con `pytest.skip` si no hay
  Tesseract: ciclo completo sobre `ambar-escaneo` con OCR real, y
  reconocimiento de frases de negación NUEVAS (entidades inventadas para la
  prueba, no las del split) para comprobar que el carril no depende de haber
  visto ya esas frases.

## 7bis. Los dos modos por región, y por qué `DESCRIPTION` queda pendiente

`multimodal/adapters/visual.py::ImageAdapter.modes = (MODE_OCR,
MODE_DESCRIPTION)`: por cada región, el adaptador pide **los dos modos**,
siempre, tenga o no proveedor. Un proveedor puramente OCR (Tesseract, o el
`_FakeVisualProvider` de `test_gate4_b1_ocr_lane.py`) sabe responder al modo
OCR y **declina** `DESCRIPTION` (`recognize()` devuelve `None`: interpretar
una imagen no es su trabajo, y mezclar lectura con interpretación es
justamente lo que este adaptador rechaza). Ese `None`, por región, genera un
episodio `IMAGE` **pendiente** con `NO_VISUAL_PROVIDER`.

Con 11 episodios en `ambar-escaneo`, esto significa que una corrida con OCR
conectado produce 11 episodios `OCR_TEXT` **y** 11 episodios `IMAGE`
pendientes — no porque el carril haya fallado en la mitad de las regiones,
sino porque `DESCRIPTION` (interpretación visual) queda pendiente
**estructuralmente** con cualquier proveedor que no cubra esa capacidad. Por
eso `eval/ocr_lane.py` publica `episodes.pending_by_mode` (un diccionario por
modo solicitado, p. ej. `{"DESCRIPTION": 11}`) en vez de un total sin
desglosar: un número suelto como "11 pendientes" sugeriría regiones sin leer,
y no es eso.

**B1 = conexión del carril OCR; B2 (o el bloque que corresponda) = cobertura
de la extracción sobre ese texto.** Que solo 2 o 3 de 11 episodios lleguen a
producir un claim determinista no es un fracaso de este bloque: el extractor
determinista es deliberadamente conservador (ver el docstring de
`extraction/deterministic.py`, "diseñado para precisión, no cobertura") y esa
disciplina no cambia porque el texto venga de OCR en vez de markdown. B1 solo
responde "¿llega texto real al extractor?"; cuánto de ese texto se convierte
en claim es una pregunta distinta, ya existente antes de este bloque y fuera
de su alcance.

## 8. Límites declarados

- **P2 (limitación de diseño, señalada por el agente de tests)**:
  `evidence_anchored`/la regla de oro de este bloque garantizan que el
  literal de un claim existe, byte a byte, en el texto que el proveedor OCR
  **devolvió** — no que ese texto sea fiel a los píxeles de la imagen. Un
  proveedor que alucinara texto plausible con confianza alta pasaría el
  anclaje exactamente igual que uno que leyera bien: la cadena de
  `_literal_fragments` verifica coincidencia texto-episodio, no
  texto-imagen. La defensa contra eso es la elección y la calibración de
  confianza del proveedor (Tesseract es determinista y no genera texto que no
  esté en la imagen; un VLM generativo sí podría hacerlo, ver
  `docs/v3/28-requisitos-de-instalacion.md` §8: "los VLM transcriben, pero NO
  sustituyen al OCR" es la misma razón), y esa elección queda **fuera del
  alcance de B1**, que conecta el carril con el proveedor determinista
  (Tesseract) precisamente para no depender de esa garantía.
- Este carril **no mide** las puertas oficiales de B0
  (`negation_scope_accuracy`, `evidence_grounding`, etc. del runner
  congelado): esas siguen midiéndose exactamente igual, sin OCR, porque el
  runner congelado no admite parámetros nuevos y no se ha tocado.
  `eval/ocr_lane.py` publica sus propios números, aparte, precisamente para no
  mezclarlos.
- `render_ocr_images` solo sabe renderizar fuentes cuyos episodios YA
  declaran modalidad `OCR_TEXT`/`HTR_TEXT` con texto. No se ha tocado
  `MAP`/`DIAGRAM` (interpretación visual, no lectura): esas siguen siendo
  stub declarado, como antes de B1.
- La recuperación literal exacta de Tesseract sobre las imágenes sintéticas
  no está medida en esta entrega (el binario no está instalado en la máquina
  de desarrollo): la prueba real está escrita y gateada, lista para
  ejecutarse el día que el operador instale Tesseract.

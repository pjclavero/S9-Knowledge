# V3 · Diseño y arquitectura

SHA base: `92583f4`.

## Principio

Trasladar la carga del "produce offsets exactos" (que el LLM hace mal) al sistema,
que es determinista. El modelo solo elige entre un conjunto CERRADO de fragmentos
con IDs. Los offsets los reconstruye el sistema, garantizando literalidad.

## Módulo puro: `relations/fragment_protocol.py`

Sin red, sin estado, sin escritura. Componentes:

### Fragmentación estable — `fragment_document(document, *, max_fragments=200)`
- Recorre el documento con `signals._sentence_bounds` (reutilizado; no se duplica la
  lógica de fronteras de frase: `.`, `!`, `?`, `\n`).
- Descarta tramos formados solo por blancos; recorta bordes de cada frase.
- Asigna IDs posicionales `f-001`, `f-002`, …
- **Invariante estructural:** `document[frag.start:frag.end] == frag.text` y los
  fragmentos **no se solapan** (particionan el documento sin solapes).

### Identidad estable
- `normalize_for_identity(text)`: NFC + colapso de espaciado + strip. Absorbe
  diferencias triviales (NFC/NFD, dobles espacios) sin tocar mayúsculas ni léxico.
- `content_hash(text)`: `sha256(normalizado)[:16]`. Dos textos que normalizan igual
  comparten hash. La identidad de un fragmento combina **orden** (`fragment_id`) +
  **hash de contenido normalizado** (`content_hash`), como pide el diseño.

### Render para el prompt — `render_fragments_for_prompt(fragments, sanitizer=…)`
- Emite líneas `f-NNN: <texto>`. El `sanitizer` (opcional) neutraliza delimitadores
  en el texto MOSTRADO; **no** afecta a offsets ni a la reconstrucción (que operan
  sobre el documento real).

### Reconstrucción — `reconstruct_evidence(document, index, fragment_ids)`
- `fragment_ids`: lista no vacía de strings; todo ID debe existir → si no, rechazo
  (`fragment_inexistente`).
- El **orden es irrelevante**: se toma `min(start)` y `max(end)` de los fragmentos
  seleccionados; la evidencia es `document[start:end]`, subcadena literal por
  construcción (incluye texto intermedio si los fragmentos no son contiguos →
  coherencia + literalidad).
- **INVARIANTE:** si `ok`, `document[start:end] == text` y
  `0 <= start <= end <= len(document)`. Guardas defensivas incluidas.

## Enhebrado en `external_ai_shadow.py`

- `RelationExternalConfig`: nuevos campos `fragment_protocol_enabled: bool = False`
  y `max_fragments: int = 200`.
- `_build_fragment_messages(...)`: prompt alternativo (fragmentos con IDs; pide
  `fragment_ids`, no offsets).
- `_validate_fragment_verdict(...)`: reconstruye offsets desde `fragment_ids` contra
  el documento real, exige literalidad y **devuelve un verdicto saneado con la misma
  forma que el clásico** (`evidence_text` + offsets reconstruidos), de modo que
  `_classify` no cambia. `fragment_ids` y `fragment_protocol_version` se anotan como
  trazabilidad experimental en el verdicto (no en el nodo persistido).
- El bucle de `evaluate_relation_external` ramifica por el flag tanto en la
  construcción del prompt como en la validación. Con flag OFF, ejecuta exactamente el
  camino clásico.

## Reutilización (no se duplica nada)
- Fronteras de frase: `signals._sentence_bounds`.
- Cliente/transporte, parser JSON, guarda de secretos, estados de consenso,
  `require_shadow`, contrato de relación y prompts: todo el existente de la base.

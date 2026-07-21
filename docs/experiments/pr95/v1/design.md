# Diseño — Anclaje conservador (PR#95 V1)

SHA base: `92583f4`.

## Hipótesis

El span mecánico `min(subject,object).start .. max(subject,object).end` puede
(a) incluir texto irrelevante que precede al predicado (aposiciones del sujeto) y
(b) **perder** señales que el ground truth sí recoge cuando caen fuera de la
ventana sujeto–objeto (negación antepuesta, atribución, marcas temporales tras el
objeto). Un anclaje **basado en cláusula** que reincorpore esas señales debería
acercarse más al GT que el span, sin llegar a la sobre-extensión de la frase
completa (que un experimento previo mostró que empeora: GT ~43 chars vs frase ~80).

## Arquitectura y punto de inserción

El anclaje vive donde ya se construye la evidencia: `relations/pipeline.py`.

- **Flag:** `PipelineConfig.evidence_anchor_mode: str = "span"` (dataclass frozen,
  añadido a `to_dict()` y por tanto al `execution_id` canónico). Se propaga por
  **parámetro**, sin globales: `_process_pair` → `_build_candidate(..., anchor_mode=config.evidence_anchor_mode)`.
- **`_build_candidate(pair, sigmap, seg_text, workspace, anchor_mode="span")`:**
  calcula `lo/hi` como antes (span); si `anchor_mode == "conservative"` intenta la
  envolvente conservadora y, si devuelve `None`, **conserva el span** (fallback).
  La evidencia sigue siendo `seg_text[lo:hi]` (coherencia literal intacta).

## Algoritmo `_conservative_anchor`

Entrada: `segment` y offsets de las dos menciones. Puro y determinista.

1. `m_lo, m_hi` = span de menciones (`min(starts)`, `max(ends)`).
2. **Frase**: `_sentence_bounds` de cada mención → unión `[sent_lo, sent_hi)`.
   Reutiliza la primitiva existente; NO reimplementa detección de frase.
3. **Cláusula segura**: `_clause_index` da el índice de cláusula de sujeto y objeto;
   `_clause_bounds_for_range` deriva los límites de carácter de las cláusulas
   `min..max` con la **misma semántica** que `_clause_index` (una posición
   pertenece a la cláusula = nº de separadores `,;:` estrictamente a su izquierda
   dentro de la frase). La envolvente base se acota para contener ambas menciones.
4. **Reincorporación de marcadores** (solo dentro de la frase):
   - `pre_cues` = negación (`signals._NEGATION_CUES`) + atribución
     (`_ATTRIBUTION_CUES`) + epistémico (`_EPISTEMIC_CUES = _RUMOR_CUES + _MODALITY_CUES`):
     si aparecen **antes** de `env_lo`, bajan `env_lo`.
   - temporal (`signals._TEMPORAL_CUES`): si terminan **después** de `env_hi`, lo suben.
   Los léxicos se **reutilizan** de `relations.signals` (no se duplica lógica).
5. **Recorte** de espacios y separadores `,;:` externos para offsets limpios.
6. **Fallback seguro → `None`** si: envolvente vacía, no contiene ambas menciones,
   o se saldría de la frase. El llamante cae entonces al span.

## Garantías (invariantes)

- **Coherencia**: `segment[lo:hi] == evidence_text` (corte literal).
- **Subconjunto de frase**: `sent_lo <= lo < hi <= sent_hi` (metamórfico).
- **Contiene ambas menciones**: `lo <= min(starts)` y `hi >= max(ends)`.
- **Default intacto**: con `anchor_mode="span"` la salida es byte-idéntica a la base
  (el flag solo añade una clave a la config; el cálculo de evidencia es el original).

## Restricciones respetadas (PROHIBIDO en V1)

Sin fuzzy matching, sin fragment IDs, sin parser nuevo, sin cambiar la generación
de pares, sin tocar review policy, sin bajar thresholds, sin escritura a Neo4j, sin
red. Solo se reutilizan primitivas puras ya existentes.

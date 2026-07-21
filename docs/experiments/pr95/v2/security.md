# V2 · Seguridad

**Base SHA:** `92583f4`

El realineamiento es un punto sensible: si estuviera mal diseñado, sería un vector para
**aceptar evidencia inventada**. El diseño lo impide por construcción.

## 1. Garantía estructural: solo rodajas literales del documento real

`realign_evidence` **nunca** devuelve texto del modelo. Cuando acepta, devuelve
`doc[start:end]` — una rodaja del documento real — y `_validate_verdict` re-verifica con un
`assert` que `seg[start:end] == evidence_text`. Consecuencia: **es imposible** que la
evidencia final contenga texto que no esté ya en el documento. Cualquier payload hostil
inyectado en `evidence_text` (instrucciones, `AUTO_APPROVED`, `rm -rf`, `DROP TABLE`) o no
casa (rechazo) o se sustituye por texto real del documento.

Tests: `test_security_prompt_injection_in_evidence_cannot_escape`,
`test_security_realignment_only_returns_literal_doc_slices`.

## 2. Prompt injection

Texto hostil en la evidencia que **no** existe en el documento no se alinea (score bajo →
`below_threshold`) y se rechaza. No cambia el comportamiento del evaluador, no escapa la
validación, no altera el `shadow_recommendation` (que sigue exigiendo revisión humana; el
estado `AUTO_APPROVED` sigue prohibido por invariante en `RelationExternalEvaluation`).

## 3. False alignment (umbral respetado)

Un texto que comparte solo tokens sueltos con el documento puntúa por debajo de
`REALIGN_SCORE_THRESHOLD = 0.82` y se rechaza. La mutación del umbral (ver test-plan)
demuestra que el test **detecta** una relajación del umbral.
Test: `test_security_false_alignment_respects_threshold`.

## 4. Ambigüedad (fail-closed)

Dos alineamientos equivalentes por encima del umbral que mapean a rodajas reales distintas
⇒ **rechazo**, nunca elección arbitraria. Evita "elegir" una ocurrencia conveniente.
Tests: `test_unit_ambiguity_two_equivalent_alignments_rejected`,
`test_integration_on_ambiguous_still_rejected`.

## 5. Unicode Bidi / zero-width

Los controles Bidi (LRE/RLE/PDF/LRO/RLO, isolates) y zero-width (ZWSP/ZWJ/ZWNJ/BOM/word
joiner) están en `_REMOVABLE` y se eliminan en la normalización de **ambos** lados. No
pueden usarse para falsear visualmente un alineamiento ni para introducir un span espurio;
la rodaja real devuelta no los contiene en los bordes.
Test: `test_security_unicode_bidi_stripped_no_spoof`.

## 6. Payload grande / DoS

- Evidencia con longitud `> REALIGN_MAX_EVIDENCE (2000)` ⇒ no se realinea (`too_long`).
- Ventana fuzzy acotada por `REALIGN_MAX_WINDOW (4000)`; sin hint usable se limita a
  `[0, 4000]`. El trabajo de `difflib` está siempre acotado.
Test: `test_security_large_payload_bounded_rejected`.

## 7. Sin secretos, sin red, sin escritura

Módulo puro: no lee entorno, no abre sockets, no escribe. No registra secretos (no maneja
credenciales). El evaluador mantiene todas las garantías previas: `require_shadow`,
`assert_no_secrets`, cero escritura en Neo4j, cero ingesta, `AUTO_APPROVED` prohibido.

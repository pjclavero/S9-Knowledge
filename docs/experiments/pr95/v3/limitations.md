# V3 · Limitaciones y rollback

SHA base: `92583f4`.

## Limitaciones conocidas

- **Token budget.** Documentos muy largos se acotan a `max_fragments` (default 200)
  de forma determinista: se conservan los PRIMEROS fragmentos en orden natural del
  documento. Si la evidencia relevante cae más allá del corte, su fragmento no se
  presenta al modelo y su ID no existirá → la respuesta que lo cite se rechaza como
  `fragment_inexistente` (comportamiento seguro, no silencioso). Ajustable vía
  `RelationExternalConfig.max_fragments`. El render por fragmento también acota a 500
  chars solo en la PRESENTACIÓN (la reconstrucción usa el texto real completo).
- **Granularidad de frase.** Los fragmentos son frases (fronteras `.!?\n`). Evidencias
  sub-frase no se pueden seleccionar por debajo de la frase; la evidencia reconstruida
  cubre frase(s) completa(s). Es un compromiso deliberado a favor de la estabilidad y
  la literalidad.
- **Selección no contigua.** Si el modelo elige fragmentos no adyacentes (p.ej. `f-002`
  + `f-005`), la reconstrucción devuelve el span `min(start)..max(end)`, que incluye el
  texto intermedio. Es literal y coherente, pero más amplio que la unión estricta. Es
  intencional para preservar la literalidad como subcadena.
- **Contrato NO migrado.** Por diseño, `fragment_ids` NO se persiste en
  `RelationCandidate`. Si en el futuro se quisiera trazabilidad persistente de
  fragmentos, requeriría una decisión de esquema aparte (fuera del alcance de V3).
- **Capa experimental.** Flag default OFF. No validado contra un modelo real (sin red
  en esta fase). El banco A/B es sintético y determinista; las cifras absolutas
  dependen del banco, aunque el modo de fallo eliminado (offsets) es estructural.

## Fuera de alcance (respetado)

No fuzzy (V2), no cambio de anclaje heurístico (V1), no parser nuevo (V4), no pares,
no review policy, no bajar thresholds, no red, no escritura Neo4j.

## Rollback

- Rollback total sin migración: poner `fragment_protocol_enabled=False` (default)
  restaura el protocolo clásico. Ningún dato persistido depende de V3.
- Revert de código: eliminar `relations/fragment_protocol.py`, revertir el enhebrado en
  `external_ai_shadow.py` (2 campos de config + 2 helpers + 2 ramas) y borrar la suite
  V3. No hay estado que limpiar.

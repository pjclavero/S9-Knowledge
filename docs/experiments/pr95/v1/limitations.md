# Limitaciones y rollback — PR#95 V1

## Limitaciones

1. **La hipótesis no se sostiene en B1.** El anclaje por cláusula empeora la
   evidencia porque el GT del corpus es una frase-predicado más ajustada que la
   cláusula. Ver `results.md`.
2. **Cláusula ≈ frase sin puntuación.** En frases de una sola cláusula (sin `,;:`)
   la envolvente coincide con la frase e incluye texto que el GT recorta
   (aposiciones, colas locativas de un par vecino). No se hace recorte al predicado
   (eso requeriría un parser, PROHIBIDO en V1).
3. **Reincorporación de marcadores por sustring literal.** La extensión temporal
   llega hasta el final del *cue* (p.ej. `durante`), no de la frase temporal completa
   (`durante el asedio`); es contigua y coherente pero puede quedar corta respecto al
   GT. La detección de cues es léxica (case-insensitive), sin desambiguación
   sintáctica: un cue puede reincorporarse aunque no modifique semánticamente la
   relación objetivo.
4. **Ámbito de medición.** A/B sobre `baseline1` y corpus B1 únicamente; no se
   evaluaron modos con proveedores ni otros corpus.
5. **Sin efecto en F1.** El anclaje no cambia el emparejamiento de pares; su impacto
   es exclusivamente sobre la calidad del span de evidencia.

## Rollback

- **Inmediato (sin código):** no fijar `evidence_anchor_mode`; el default `"span"`
  mantiene el comportamiento base byte-idéntico. El modo `conservative` nunca se
  activa por sí solo.
- **Retirada del código:** revertir el commit de la rama
  `exp/pr95-v1-conservative-anchor`. Los cambios están acotados a
  `relations/pipeline.py` (funciones aditivas + un campo de config + wiring),
  `tools/relation_anchor_ab.py` y el fichero de tests; no hay migraciones ni estado
  persistente que deshacer. El artefacto A/B (`artifacts/pr95-variants/v1/`) es un
  resultado de medición, borrable sin efectos.

## Próximos pasos sugeridos (fuera de V1)

- Recorte al predicado / frontera verbal (necesitaría análisis sintáctico → otro
  carril).
- Reincorporación de la *frase temporal completa* en vez de solo el cue.
- Evaluar en corpus con GT de granularidad de cláusula, donde la hipótesis podría
  invertirse.

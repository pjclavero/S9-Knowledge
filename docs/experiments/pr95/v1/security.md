# Seguridad — PR#95 V1

## Superficie de cambio

Solo tres artefactos de código:

- `relations/pipeline.py`: funciones **puras** de anclaje + un campo de config +
  wiring por parámetro. Sin I/O, sin red, sin escritura.
- `tools/relation_anchor_ab.py`: herramienta de medición OFFLINE. Lee el corpus B1
  local (verificado por sha256) y escribe **un único** JSON de resultados en
  `artifacts/pr95-variants/v1/`. No abre red ni proveedores.
- `tests/test_pr95_v1_conservative_anchor.py`: tests deterministas en memoria.

## Propiedades

- **Offline / sin red**: no se usan proveedores (`local_llm_enabled` /
  `external_ai_enabled` permanecen `False`; modo `baseline1`). Ninguna llamada HTTP.
- **Sin escritura a Neo4j**: el pipeline sigue en dry-run estructural; no se toca
  persistencia. El único fichero escrito es el artefacto A/B (resultados de métricas).
- **Sin secretos**: no se leen ni emiten credenciales. Nada que respetar en
  `.gitignore` más allá de lo habitual.
- **Determinismo**: mismas entradas → misma salida (offsets y hashes incluidos).
- **Default seguro**: `evidence_anchor_mode` por defecto `"span"`; el nuevo código
  no se ejecuta salvo activación explícita por config. El `execution_id` incorpora
  el flag en su hash canónico (trazabilidad), sin alterar la salida del modo span.
- **Fallback cerrado**: ante cualquier envolvente incoherente, se conserva el span
  ya validado; nunca se emite evidencia que rompa la coherencia del contrato.

## No se tocó

Generación de pares, review policy, thresholds, vocabulario, consenso, proveedores,
contrato del evaluador externo (P0 intacto: `test_relation_external_document_contract`
sigue en verde).

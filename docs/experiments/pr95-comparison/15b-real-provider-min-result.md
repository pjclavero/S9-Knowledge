# 15b · Corrida real NVIDIA — submuestra MÍNIMA (efecto aislado de P0)

**Autorizada** (submuestra mínima para gastar lo justo). OFFLINE→red real, gateada.
Modelo `meta/llama-3.3-70b-instruct` · commit BASE `92583f4` (post-P0) · doble llave ·
key sourceada sin imprimir · **sin escritura, sin Neo4j, sin ingesta**.

## Alcance
- Submuestra: `--sources src-09,src-13` (2 fuentes, las más pequeñas), `--no-determinism`.
- **8 llamadas reales** en total (2 corridas × 4 candidatos). 0 fallos de transporte.

## Resultado (n=4 candidatos con verdicto)

| | Antes de P0 (histórico) | Después de P0 (esta corrida) |
|---|---|---|
| NVIDIA responde | sí | **4/4, 0 errores transporte** |
| Verdicto aceptado | 0/27 | **0/4** |
| Motivo del rechazo | `evidencia_inexistente` (evidence_text no está en el "documento" = el **ID**) | **`offsets_invalidos: segmento[start:end] no coincide con evidence_text`** |
| Consenso | INVALID_RESPONSES | INVALID_RESPONSES (→ REVIEW, sombra) |

Los 4 payloads crudos (`real-provider/base_p0_payloads.jsonl`) coinciden: `state=INVALID_RESPONSES`,
`reason_codes=['invalid_response']`, `validation_errors=['offsets_invalidos: …']`.

## Interpretación (con cautela: n=4, una submuestra)

1. **P0 tumbó el primer modo de fallo.** Desaparece `evidencia_inexistente`: el modelo ya
   ve el texto real y su cita SÍ se reconoce en el documento. Es el muro que causaba el
   27/27 histórico.
2. **Queda un segundo modo de fallo, ahora visible:** NVIDIA devuelve la cita correcta
   pero con **offsets mal contados** (`offsets_invalidos`). Es el problema "los LLM manejan
   mal los offsets".
3. **Consecuencia para el veredicto:** **P0 es NECESARIO pero NO SUFICIENTE** para obtener
   verdictos NVIDIA aceptados. La aceptación en BASE sigue siendo 0/4; el bloqueo restante
   es **exactamente lo que atacan V2 (recomputar offsets desde la cita literal) y V3
   (protocolo por fragmentos, sin offsets libres)**. Esto valida empíricamente la utilidad
   de V2/V3 sobre la capa de protocolo.

## Pendiente (no ejecutado — más cuota)
Correr V2 y V3 REALES sobre la misma submuestra para medir cuántos de esos
`offsets_invalidos` se convierten en aceptaciones (V3 debería sortearlos por construcción;
V2 si la cita es literal). Requiere drivers con el flag de cada versión + autorización.

## Seguridad
Red: 8 llamadas contabilizadas, 0 fallos. Escritura/Neo4j: none (dry-run). Key nunca
impresa (stderr redactado). Endpoint `https://integrate.api.nvidia.com`.

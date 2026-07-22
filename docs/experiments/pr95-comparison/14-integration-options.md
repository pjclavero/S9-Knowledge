# 14 — Opciones de integracion

Cada opcion lista: (a) alcance de codigo, (b) prerequisitos antes de integrar,
(c) rollback. Ninguna se activa aqui; esto es el mapa para la decision (doc 16).

## P0 — corregir el contrato DOCUMENTO/ID del evaluador externo (independiente)

**Estado:** ya implementado y congelado en `92583f4` (base). El auditor de P0
concluyo que el arreglo es **MINIMO y correcto**.

- **Alcance de codigo (dcded31 -> 92583f4):**
  - `relations/external_ai_shadow.py`: +33 / −11 lineas.
  - `relations/pipeline.py`: +14 / −0.
  - Test nuevo: `tests/.../test_relation_external_document_contract.py`: **+250**.
  - El resto del diff (`artifacts/pr95-variants/*`, `docs/experiments/pr95/base/*`)
    es **andamiaje de auditoria a descartar** en la rama de integracion limpia.
- **Neto integrable:** ~36-47 lineas de codigo de produccion + 250 de test. Rama
  limpia = P0 sin el andamiaje.
- **Prerequisitos:** ninguno adicional; CI verde + puerta §18 (pasa). Es la unica
  pieza **integrable ya** con firmeza.
- **Rollback:** revertir un unico commit acotado; sin migracion de datos, sin
  cambio de esquema, sin estado de proveedor. Riesgo de rollback: minimo.

## V3 (protocolo de fragmentos) — integrable tras validacion real

- **Alcance:** modulo `relations/fragment_protocol.py` + rama `fragment_response`
  en `external_ai_shadow` (flag `fragment_protocol_enabled`). Aislado tras flag.
- **Prerequisitos antes de integrar:**
  1. **Corrida NVIDIA real** (doc 15): confirmar que el recall del banco (0.963) se
     sostiene con el modelo real y que la evidencia a nivel **frase** no degrada la
     utilidad aguas abajo (grafo/consulta).
  2. Medir el **coste de prompt/granularidad**: los fragmentos aumentan el tamano de
     prompt y bajan la finura de la cita; cuantificar tokens/latencia reales.
  3. Re-verificar puerta §18 contra modelo real (inyeccion/literalidad).
- **Rollback:** desactivar `fragment_protocol_enabled` (vuelve a base). Sin estado
  persistente mientras el proveedor este en shadow. Riesgo: bajo.

## V2 (realineamiento determinista) — no recomendado junto a V3

- **Alcance:** flag `realignment_enabled` en `external_ai_shadow`.
- **Prerequisitos antes de integrar:**
  1. **Mitigacion obligatoria del false_realign 0.182**: hoy realinea a span erroneo
     (IoU=0) el 18% de las veces que se activa. Requiere una guarda (rechazar
     realineamientos con baja confianza de anclaje / IoU esperado bajo) **antes** de
     cualquier integracion.
  2. Demostrar beneficio marginal **unico** sobre V3 en la corrida real — hoy en el
     banco es 0 (doc 11, `realign_fired=0`).
- **Rollback:** desactivar `realignment_enabled`. Riesgo: bajo tecnicamente, pero el
  riesgo de **calidad** (evidencia literal-pero-equivocada) persiste mientras este
  activo sin la guarda.

## V1 (anclaje conservador) — no integrar

- 0 mejoras, 3 regresiones en evidence_correct (doc 13), sin significancia pero sin
  beneficio. Coste > 0, beneficio = 0. **Descartar.**

## V4 — plataforma, no mejora

- `hybrid_default` es compatible byte a byte con base: integrable como **habilitador**
  si se quiere la plataforma de etapas, sin cambio de metricas. `cross_sentence`
  **no** (F1 0.525). Rollback: `hybrid_stages` vacio == base.

## Resumen de integrabilidad

| opcion | integrable ya | prerequisito clave | rollback |
|---|---|---|---|
| **P0** | **si** | ninguno (CI+§18 verdes) | revert de 1 commit |
| V3 | no (gateada) | NVIDIA real + coste prompt + §18 real | apagar flag |
| V2 (+V3) | no | guarda anti false_realign + beneficio unico | apagar flag |
| V1 | no (descartar) | — | — |
| V4 hybrid | opcional | ninguno (== base) | stages vacio |

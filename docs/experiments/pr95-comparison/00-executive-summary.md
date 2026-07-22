# 00 — Resumen ejecutivo (comparativa unificada PR#95)

Evaluacion independiente, OFFLINE (sin red, sin escritura Neo4j, sin ingesta), dos
pistas con la MISMA vara. Detalle en docs 03-16; datos en
`artifacts/pr95-unified-comparison/`.

## Veredicto en una linea
**Integrar A (solo P0) ya** — firme. **V1/V4 no mejoran** la calidad. El protocolo
(V2/V3) es prometedor pero su eleccion es **PROVISIONAL** hasta la corrida NVIDIA
real: si V3 valida, secuenciar **C (P0+V3)**; **V2 no se recomienda**.

## Dos pistas, no un ranking unico
- **PIPELINE (C1 real, n=52 cand / 43 TP):** base es la referencia. **V1** empeora la
  evidencia (0.907->0.837, 0 mejoras) — no significativo pero sin beneficio.
  **V4** `hybrid_default` == base byte a byte; `cross_sentence` sube recall a 0.963
  pero hunde F1 a 0.525. **Ninguna variante de pipeline mejora la base.**
- **PROTOCOLO (banco sintetico):** base valid 0.185 -> **V2 0.796** (con false_realign
  **0.182**) -> **V3 0.963** (inmune a inyeccion, literal 1.0). base < V2 < V3 con CIs
  no solapados. **V3 domina a V2** en el banco.

## Combinacion V2+V3 (numeros reales del banco)
Con el orden del spec (fragmento -> literal -> realineo solo si hace falta -> rechazo):
- C1: valid **0.963**, literal **1.0**, injection **0**, y **false_realign 0.182 -> 0.0**.
- Clave honesta: baja a 0 **porque el realineamiento nunca se activa**
  (`realign_fired = 0`), no porque realinee mejor. **V3 subsume a V2**; V2 no aporta
  beneficio unico. En C3 la combinacion sube 4/6 -> **5/6** por un fallback literal,
  no por realinear.

## Estadistica (bootstrap 95%, doc 13)
- Protocolo C1: base 0.185 [0.093,0.296] · V2 0.796 [0.685,0.889] · V3 0.963 [0.907,1.0].
  Diferencias pareadas V3−base +0.778, V3−V2 +0.167, V2−base +0.611: **todas excluyen 0**.
- Evidencia base−V1: +0.070 CI **[0.000, 0.163]** — **incluye 0**, McNemar p=0.25 -> **no
  significativo**. El caso contra V1 es "0 beneficio", no "peor con significancia".
- Calibracion (ECE/Brier): **INSUFICIENTE** (confidence unsupported, proveedor no corrido).

## Seguridad (§18, doc 12)
Puerta **PASA** para base/V1/V2/V3/V4/V2+V3 en el banco: network/write/secret/injection/
unsafe = 0, literal 1.0, determinismo 1.0, fail-closed. El false_realign de V2 es fallo
de **calidad** (evidencia literal pero equivocada), no de seguridad; **mitigado por V3**.
Re-verificar §18 contra NVIDIA antes de integrar el protocolo.

## Firme vs provisional
- **Firme:** P0 integrable ya · §18 pasada (offline) · V1 negativo/sin beneficio ·
  V4 compatible sin mejora · mecanismo base<V2<V3.
- **Provisional:** V2 vs V3 en produccion (banco sintetico ≠ juez real); recall real de
  V3; coste de prompt. Se decide con la corrida NVIDIA (doc 15, gateada, no ejecutada).

## Recomendacion
1. Integrar **P0 (A)** ahora. 2. Ejecutar la puerta **NVIDIA** (doc 15) para aislar el
efecto de P0 y comparar V2/V3 reales. 3. Si V3 valida -> **P0+V3 (C)**. **No** V2.

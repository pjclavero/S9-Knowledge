# 16 — Veredicto final (matriz de decision §19)

Fuente cuantitativa: `artifacts/pr95-unified-comparison/decision-matrix.json`
(`harness/decision_matrix.py`). Seguridad = **puerta** (§18), no peso.

## Puerta §18 (obligatoria)
**Todas** las opciones pasan la puerta en el banco OFFLINE (doc 12):
network/write/secret/injection/unsafe = 0; literal = 1.0; determinismo = 1.0;
fail-closed. Ninguna opcion queda descalificada por seguridad **en el banco**;
la §18 debe re-verificarse contra NVIDIA real antes de integrar el protocolo.

## Ponderacion (Evidencia 25 / Estructura 20 / Falsos aceptados 20 / Recall 10 /
Rendimiento 10 / Mantenibilidad 10 / Complejidad 5)

| opcion | total | firmeza |
|---|---|---|
| **A — solo P0** | **0.846** | **FIRME (integrable ya)** |
| F — ninguna | 0.846 | equivale a A pero renuncia a P0: peor por dejar valor firme en la mesa |
| C — P0+V3 | 0.841 | PROVISIONAL (pende NVIDIA) |
| D — P0+V2/V3 | 0.809 | PROVISIONAL; V2 no aporta unico (realign_fired=0) |
| E — V4 componentes | 0.797 | habilitador; cross_sentence descartado |
| B — P0+V2 | 0.784 | PROVISIONAL + riesgo false_realign sin guarda |

Pareto: A y C forman la frontera sensata (A maximiza simplicidad y seguridad de
falsos-aceptados **ahora**; C anade recall a coste **provisional**). B y D quedan
dominadas en la practica por C (mismo/menor recall real con mas riesgo o complejidad).

## Conclusion elegida: **A (solo P0)** — con SECUENCIA recomendada

**A** es la unica conclusion **FIRME** hoy: P0 esta corregido de forma minima
(~36-47 lineas + 250 test), CI verde, puerta §18 pasada, rollback de un commit.
Se integra ya.

**Secuencia recomendada:**
1. **Ahora (firme):** integrar **A (P0)**. Descartar V1 (0 mejoras) y `cross_sentence`
   de V4 (F1 0.525). `v4_hybrid_default` opcional como habilitador (== base).
2. **Puerta NVIDIA (gateada, doc 15):** ejecutar la corrida real para (a) medir
   cuantos rechazos desaparecen **solo por P0** y (b) resolver **V2 vs V3 reales**.
3. **Condicional:** si V3 sostiene su recall real sin degradar utilidad ni §18,
   integrar **C (P0+V3)**. **No** integrar V2 (B/D): en el banco su realineamiento
   nunca se activa junto a V3 y aporta 0.182 de false_realign cuando dispara; solo
   reconsiderar V2 si NVIDIA demuestra un beneficio unico + con guarda anti
   false_realign.

## FIRME vs PROVISIONAL (honestidad del dictamen)

**Firme (verificado OFFLINE, reproducible):**
- P0 integrable ya; puerta §18 pasada por todas las opciones en el banco.
- V1 no aporta (0 mejoras / 3 regresiones; diferencia base-V1 **no** significativa,
  McNemar p=0.25 — el caso contra V1 es "0 beneficio", no "peor con significancia").
- V4 `hybrid_default` == base byte a byte; `cross_sentence` sube recall pero hunde F1.
- Mecanismo del protocolo: base < V2 < V3 en recall valido (CIs no solapados);
  V2+V3 lleva false_realign a 0 **por no activar** el realineamiento, no por mejorarlo.

**Provisional (depende de la corrida NVIDIA real):**
- V2 vs V3 como eleccion de produccion. El banco es sintetico y NO es el juez real.
- El recall real de V3 (0.963 en banco) y el coste de prompt/granularidad.
- La §18 frente a un modelo real (inyeccion/literalidad).

> El veredicto del **protocolo** (V2/V3) es **PROVISIONAL**: se juzga de verdad con
> NVIDIA (no corrido). El veredicto de **P0** es **FIRME**: A se puede integrar hoy.
> No se declara ganadora entre V2 y V3 por diferencias del banco sintetico.
